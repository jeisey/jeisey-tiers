/**
 * Auto Start/Sit: the best legal lineup for one saved roster this week (ADR-106,
 * `lineup_assignment_v1`).
 *
 * **What it maximises.** The sum, over every starter slot, of the published weekly quantile the
 * reader chose — q50 (median, the default), q10 (floor) or q90 (ceiling) — from
 * `weekly-startsit-v1`. That sum is a sum of individual quantiles: it is **not** the team's
 * joint median, floor or ceiling (the quantile of a sum is not the sum of quantiles) and it is
 * not a win probability. Every surface that prints it says so. Nothing here rescales a
 * published value for injury risk.
 *
 * **Who may be started.** Each roster player's week is read once (`readWeek`) from the weekly
 * record, the shared availability policy (ADR-101) and the clock:
 *
 * | kind | when | the optimiser |
 * |---|---|---|
 * | `candidate` | an upcoming game, a published distribution for the target week, kickoff known and in the future, and the policy allows a start (available, questionable, uncertain — the last two "if active") | may start him in any slot his position fits, or bench him |
 * | `sidelined` | a bye, or out, doubtful, on a reserve list, released, unsigned, out for the season | never starts him; may bench him |
 * | `locked` | his game kicked off at build time or by the reader's clock | leaves him exactly where he is |
 * | `pinned` | no weekly record, a record for another week, no line posted (no distribution), an unknown kickoff, or an id this build cannot resolve | leaves him exactly where he is: unknown schedule data never becomes a confident move |
 *
 * IR occupants are not read at all: they stay in IR until the reader moves them.
 *
 * **How.** One exact assignment of every movable player (candidates and sidelined players) to
 * every slot not held by a fixed player — starter slots and bench slots together, so bench
 * capacity is a constraint of the problem rather than a check afterwards. The objective is
 * lexicographic and encoded as exact integers for the Hungarian algorithm:
 *
 * 1. every movable player is placed somewhere (always possible: his current slot is allowed);
 * 2. as many starter slots as possible hold a candidate;
 * 3. the sum of their chosen quantiles, in published hundredths, is as large as possible;
 * 4. a sidelined starter with no possible replacement stays where he is, rather than leaving
 *    the slot empty (so nothing is benched for nothing);
 * 5. as many players as possible keep their current slot — the reader's lineup wins ties;
 * 6. among remaining ties, players with earlier canonical ids start (deterministic).
 *
 * Within a group of identical slots (RB1/RB2, the bench) a newcomer takes the lowest free
 * index, ordered by his quantile then id, so one roster always produces one proposal.
 *
 * Nothing is applied here: a proposal is shown with its changes and the reader applies it.
 */

import { startEligible, startExclusion, type Availability } from "./availability";
import type { Position, WeeklyProjectionRecord } from "./contracts";
import {
  SLOT_GROUPS,
  STARTER_GROUPS,
  isStarterGroup,
  slotAccepts,
  type LineupMode,
  type Roster,
  type SlotCounts,
  type SlotGroup,
} from "./leagueContract";
import { formatEastern } from "./format";
import { sameSlot, type SlotRef } from "./roster";

export const LINEUP_RULE_VERSION = "lineup_assignment_v1";

export const MODE_LABELS: Readonly<Record<LineupMode, string>> = {
  q50: "Median",
  q10: "Floor",
  q90: "Ceiling",
};

export type WeekKind = "candidate" | "sidelined" | "locked" | "pinned";

export interface PlayerWeek {
  readonly id: string;
  readonly kind: WeekKind;
  /** Why he is not a plain candidate, in a sentence; null for an unremarkable candidate. */
  readonly reason: string | null;
  /** A candidate who starts only "if active": questionable, or status unknown. */
  readonly conditional: boolean;
  readonly record: WeeklyProjectionRecord | null;
  readonly availability: Availability | null;
  readonly position: Position | null;
}

/** What the optimiser reads, injected so tests and the Improve engine can hand in their own. */
export interface WeekContext {
  readonly weeklyFor: (playerId: string) => WeeklyProjectionRecord | null;
  readonly availabilityFor: (playerId: string) => Availability | null;
  readonly positionOf: (playerId: string) => Position | null;
  /** The week the build published projections for; null when no weekly layer exists. */
  readonly targetWeek: number | null;
  /** The reader's clock, in milliseconds. */
  readonly now: number;
}

/** One player's week, decided once. Pure in its inputs. */
export function readWeek(playerId: string, context: WeekContext): PlayerWeek {
  const position = context.positionOf(playerId);
  const base = { id: playerId, position, conditional: false };
  if (position === null) {
    return {
      ...base,
      kind: "pinned",
      reason: "This build has no record of him, so his week is unknown. Left where you put him.",
      record: null,
      availability: null,
    };
  }
  const record = context.weeklyFor(playerId);
  const availability = context.availabilityFor(playerId);
  if (record === null) {
    return {
      ...base,
      kind: "pinned",
      reason: "No weekly projection is published for him, so his game and kickoff are unknown. Left where you put him.",
      record: null,
      availability,
    };
  }
  if (context.targetWeek !== null && record.target_week !== context.targetWeek) {
    return {
      ...base,
      kind: "pinned",
      reason: `His projection is for week ${String(record.target_week)}, not week ${String(context.targetWeek)}. Left where you put him.`,
      record,
      availability,
    };
  }
  if (record.game_state === "bye" || record.game === null) {
    return { ...base, kind: "sidelined", reason: `Bye in week ${String(record.target_week)}.`, record, availability };
  }
  const kickoff = record.game.kickoff_utc;
  const kicked = record.game_state === "kicked_off" || (kickoff !== null && Date.parse(kickoff) <= context.now);
  if (kicked) {
    return {
      ...base,
      kind: "locked",
      reason:
        kickoff === null
          ? "His game had kicked off when this build ran. Locked."
          : `His game kicked off ${formatEastern(kickoff)}. Locked.`,
      record,
      availability,
    };
  }
  if (availability !== null && !startEligible(availability)) {
    return { ...base, kind: "sidelined", reason: sidelinedReason(availability), record, availability };
  }
  if (record.game_state === "lines_pending" || record.quantiles === null) {
    return {
      ...base,
      kind: "pinned",
      reason: "No line is posted for his game yet, so no projection is published. Left where you put him.",
      record,
      availability,
    };
  }
  if (kickoff === null) {
    return {
      ...base,
      kind: "pinned",
      reason: "His kickoff time is not published, so it is not known whether his game has started. Left where you put him.",
      record,
      availability,
    };
  }
  const conditional =
    availability === null || availability.week === "questionable" || availability.week === "uncertain";
  return {
    ...base,
    kind: "candidate",
    conditional,
    reason: conditional
      ? availability === null || availability.week === "uncertain"
        ? "If active: his status is uncertain."
        : "If active: questionable this week."
      : null,
    record,
    availability,
  };
}

/** The policy's reason he is not started automatically (ADR-101's exclusions, reworded). */
function sidelinedReason(availability: Availability): string {
  switch (availability.week) {
    case "out":
      return "Out this week.";
    case "doubtful":
      return "Doubtful this week, so not started automatically.";
    default:
      return startExclusion(availability) === null ? availability.headline : `${availability.headline}.`;
  }
}

/** His chosen quantile in published hundredths, or null without a distribution. */
export function scoreOf(week: PlayerWeek | null, mode: LineupMode): number | null {
  const quantiles = week?.record?.quantiles ?? null;
  if (quantiles === null) return null;
  return Math.round(quantiles[mode] * 100);
}

/** Whether a starter slot's occupant contributes his quantile to a lineup's sum. */
function counts(week: PlayerWeek | null, group: SlotGroup): boolean {
  if (week?.position == null) return false;
  if (week.kind !== "candidate" && week.kind !== "locked") return false;
  return slotAccepts(group, week.position) && week.record?.quantiles != null;
}

// --------------------------------------------------------------------------- the solver

/**
 * Kuhn–Munkres (Hungarian) for an `n × m` cost matrix with `n ≤ m`, minimising. `Infinity`
 * marks a forbidden pair. Returns the column of each row. Exact on integer costs below 2^53.
 */
export function hungarian(cost: readonly (readonly number[])[], columns: number): number[] {
  const n = cost.length;
  const m = columns;
  if (n > m) throw new Error("more rows than columns");
  const u = new Float64Array(n + 1);
  const v = new Float64Array(m + 1);
  const p = new Int32Array(m + 1);
  const way = new Int32Array(m + 1);
  for (let i = 1; i <= n; i += 1) {
    p[0] = i;
    let j0 = 0;
    const minv = new Float64Array(m + 1).fill(Infinity);
    const used = new Uint8Array(m + 1);
    do {
      used[j0] = 1;
      const i0 = p[j0] ?? 0;
      const row = cost[i0 - 1] ?? [];
      let delta = Infinity;
      let j1 = 0;
      for (let j = 1; j <= m; j += 1) {
        if (used[j] === 1) continue;
        const current = (row[j - 1] ?? Infinity) - (u[i0] ?? 0) - (v[j] ?? 0);
        if (current < (minv[j] ?? Infinity)) {
          minv[j] = current;
          way[j] = j0;
        }
        if ((minv[j] ?? Infinity) < delta) {
          delta = minv[j] ?? Infinity;
          j1 = j;
        }
      }
      if (delta === Infinity) throw new Error("no feasible assignment");
      for (let j = 0; j <= m; j += 1) {
        if (used[j] === 1) {
          const row0 = p[j] ?? 0;
          u[row0] = (u[row0] ?? 0) + delta;
          v[j] = (v[j] ?? 0) - delta;
        } else {
          minv[j] = (minv[j] ?? Infinity) - delta;
        }
      }
      j0 = j1;
    } while (p[j0] !== 0);
    do {
      const j1 = way[j0] ?? 0;
      p[j0] = p[j1] ?? 0;
      j0 = j1;
    } while (j0 !== 0);
  }
  const assignment = new Array<number>(n).fill(-1);
  for (let j = 1; j <= m; j += 1) {
    const row = p[j] ?? 0;
    if (row !== 0) assignment[row - 1] = j - 1;
  }
  return assignment;
}

/** The objective's components for one complete placement; compared lexicographically. */
export interface Objective {
  readonly filled: number;
  readonly score: number;
  readonly sidelinedKept: number;
  readonly kept: number;
  readonly idPreference: number;
}

export function compareObjective(a: Objective, b: Objective): number {
  return (
    a.filled - b.filled ||
    a.score - b.score ||
    a.sidelinedKept - b.sidelinedKept ||
    a.kept - b.kept ||
    a.idPreference - b.idPreference
  );
}

/** The problem in the solver's terms, shared with the exhaustive oracle in the tests. */
export interface AssignmentProblem {
  readonly players: readonly { readonly week: PlayerWeek; readonly current: SlotRef }[];
  readonly slots: readonly SlotRef[];
  /** Candidates' id preference: higher for an earlier id. */
  readonly preference: ReadonlyMap<string, number>;
  readonly mode: LineupMode;
}

/** The objective contribution of one player in one slot, or null when forbidden. */
export function pairValue(
  player: AssignmentProblem["players"][number],
  slot: SlotRef,
  problem: AssignmentProblem,
): Objective | null {
  const own = sameSlot(player.current, slot);
  const keep = own ? 1 : 0;
  if (!isStarterGroup(slot.group)) {
    return { filled: 0, score: 0, sidelinedKept: 0, kept: keep, idPreference: 0 };
  }
  const { week } = player;
  if (week.kind === "candidate" && week.position !== null && slotAccepts(slot.group, week.position)) {
    return {
      filled: 1,
      score: scoreOf(week, problem.mode) ?? 0,
      sidelinedKept: 0,
      kept: keep,
      idPreference: problem.preference.get(week.id) ?? 0,
    };
  }
  // A player who cannot score here may only stay where he already is.
  if (own) return { filled: 0, score: 0, sidelinedKept: 1, kept: 1, idPreference: 0 };
  return null;
}

/** Solve exactly. Returns the slot index (into `problem.slots`) of each player. */
export function solveAssignment(problem: AssignmentProblem): number[] {
  const players = problem.players;
  const slots = problem.slots;
  const p = players.length;
  const t = slots.length;
  if (p === 0) return [];
  // Integer weights whose sum orders placements exactly as `compareObjective` does: each
  // multiplier exceeds the largest total the components below it can reach.
  let maxScore = 1;
  for (const player of players) {
    const score = scoreOf(player.week, problem.mode);
    if (score !== null) maxScore = Math.max(maxScore, Math.abs(score));
  }
  const starters = slots.filter((slot) => isStarterGroup(slot.group)).length;
  const keepUnit = p * p + 1;
  const sidelinedUnit = keepUnit * (p + 1);
  const scoreUnit = sidelinedUnit * (starters + 1);
  const fillUnit = scoreUnit * (2 * starters * maxScore + 1);
  const placeUnit = fillUnit * (starters + 2);
  if (placeUnit * (p + 1) > Number.MAX_SAFE_INTEGER / 4) throw new Error("lineup too large to solve exactly");
  const cost = players.map((player) =>
    slots.map((slot) => {
      const value = pairValue(player, slot, problem);
      if (value === null) return Infinity;
      return -(
        placeUnit +
        value.filled * fillUnit +
        value.score * scoreUnit +
        value.sidelinedKept * sidelinedUnit +
        value.kept * keepUnit +
        value.idPreference
      );
    }),
  );
  return hungarian(cost, t);
}

export function objectiveOf(problem: AssignmentProblem, assignment: readonly number[]): Objective {
  let filled = 0;
  let score = 0;
  let sidelinedKept = 0;
  let kept = 0;
  let idPreference = 0;
  assignment.forEach((slotIndex, playerIndex) => {
    const player = problem.players[playerIndex];
    const slot = problem.slots[slotIndex];
    if (player === undefined || slot === undefined) return;
    const value = pairValue(player, slot, problem);
    if (value === null) {
      filled = Number.NEGATIVE_INFINITY;
      return;
    }
    filled += value.filled;
    score += value.score;
    sidelinedKept += value.sidelinedKept;
    kept += value.kept;
    idPreference += value.idPreference;
  });
  return { filled, score, sidelinedKept, kept, idPreference };
}

// ------------------------------------------------------------------------- the proposal

export interface StarterLine {
  readonly slot: SlotRef;
  readonly id: string | null;
  readonly week: PlayerWeek | null;
  /** His chosen quantile in points when it counts toward the sum; null otherwise. */
  readonly score: number | null;
}

export interface LineupMove {
  readonly id: string;
  readonly from: SlotRef;
  readonly to: SlotRef;
}

export interface LineupGap {
  readonly slot: SlotRef;
  /**
   * `gap`: the slot cannot be filled with a player who can play (empty, or only a sidelined
   * player). `unscored`: a player left in place whose week is unknown or whose game started
   * without a published distribution — not a hole, but not in the sum either.
   */
  readonly kind: "gap" | "unscored";
  readonly reason: string;
}

export interface LineupProposal {
  readonly mode: LineupMode;
  readonly roster: Roster;
  readonly starters: readonly StarterLine[];
  readonly moves: readonly LineupMove[];
  readonly gaps: readonly LineupGap[];
  /** Σ counted quantiles of the proposed lineup, in points. */
  readonly total: number;
  /** The same sum for the lineup as it stands. */
  readonly currentTotal: number;
  /** Starter slots the proposal fills with a player who counts. */
  readonly filled: number;
  readonly starterSlots: number;
  /** Players left in place because their week is unknown or their game has started. */
  readonly fixed: readonly PlayerWeek[];
  readonly weeks: ReadonlyMap<string, PlayerWeek>;
  readonly objective: Objective;
}

function slotOf(roster: Roster, playerId: string): SlotRef | null {
  for (const group of SLOT_GROUPS) {
    const index = roster[group].indexOf(playerId);
    if (index >= 0) return { group, index };
  }
  return null;
}

/** Σ counted quantiles of a roster's starters, in hundredths. */
export function lineupHundredths(
  roster: Roster,
  weeks: ReadonlyMap<string, PlayerWeek>,
  mode: LineupMode,
): number {
  let total = 0;
  for (const group of STARTER_GROUPS) {
    for (const id of roster[group]) {
      if (id === null) continue;
      const week = weeks.get(id) ?? null;
      if (counts(week, group)) total += scoreOf(week, mode) ?? 0;
    }
  }
  return total;
}

/** Read every non-IR player's week once. */
export function readWeeks(roster: Roster, context: WeekContext): Map<string, PlayerWeek> {
  const weeks = new Map<string, PlayerWeek>();
  for (const group of SLOT_GROUPS) {
    if (group === "IR") continue;
    for (const id of roster[group]) if (id !== null) weeks.set(id, readWeek(id, context));
  }
  return weeks;
}

/** The best legal lineup for this roster and mode. Pure; never applied here. */
export function optimizeLineup(
  roster: Roster,
  slotCounts: SlotCounts,
  context: WeekContext,
  mode: LineupMode,
  weeks: ReadonlyMap<string, PlayerWeek> = readWeeks(roster, context),
): LineupProposal {
  const fixed: PlayerWeek[] = [];
  const movable: { week: PlayerWeek; current: SlotRef }[] = [];
  const freeSlots: SlotRef[] = [];
  for (const group of SLOT_GROUPS) {
    if (group === "IR") continue;
    for (let index = 0; index < slotCounts[group]; index += 1) {
      const id = roster[group][index] ?? null;
      const slot = { group, index };
      const week = id === null ? null : (weeks.get(id) ?? null);
      if (week !== null && (week.kind === "locked" || week.kind === "pinned")) {
        fixed.push(week);
        continue;
      }
      freeSlots.push(slot);
      if (week !== null) movable.push({ week, current: slot });
    }
  }
  const candidates = movable
    .filter((player) => player.week.kind === "candidate")
    .map((player) => player.week.id)
    .sort();
  const preference = new Map(candidates.map((id, index) => [id, candidates.length - 1 - index]));
  const problem: AssignmentProblem = { players: movable, slots: freeSlots, preference, mode };
  const assignment = solveAssignment(problem);

  // Lay the result out: fixed players where they were, kept players at their own index, and
  // newcomers to a group in its lowest free indices, best quantile first.
  const next: Partial<Record<SlotGroup, (string | null)[]>> = {};
  for (const group of SLOT_GROUPS) {
    next[group] = group === "IR" ? [...roster.IR] : Array.from({ length: slotCounts[group] }, () => null);
  }
  for (const week of fixed) {
    const slot = slotOf(roster, week.id);
    if (slot !== null) (next[slot.group] ?? [])[slot.index] = week.id;
  }
  const newcomers = new Map<SlotGroup, { week: PlayerWeek; current: SlotRef }[]>();
  assignment.forEach((slotIndex, playerIndex) => {
    const player = movable[playerIndex];
    const slot = freeSlots[slotIndex];
    if (player === undefined || slot === undefined) return;
    if (sameSlot(player.current, slot)) {
      (next[slot.group] ?? [])[slot.index] = player.week.id;
      return;
    }
    const bucket = newcomers.get(slot.group) ?? [];
    bucket.push(player);
    newcomers.set(slot.group, bucket);
  });
  const order = (a: { week: PlayerWeek; current: SlotRef }, b: { week: PlayerWeek; current: SlotRef }): number =>
    (scoreOf(b.week, mode) ?? Number.NEGATIVE_INFINITY) - (scoreOf(a.week, mode) ?? Number.NEGATIVE_INFINITY) ||
    SLOT_GROUPS.indexOf(a.current.group) - SLOT_GROUPS.indexOf(b.current.group) ||
    a.current.index - b.current.index ||
    (a.week.id < b.week.id ? -1 : 1);
  for (const [group, players] of newcomers) {
    const target = next[group] ?? [];
    const free = freeSlots.filter((slot) => slot.group === group && target[slot.index] === null);
    players.sort(order).forEach((player, index) => {
      const slot = free[index];
      if (slot !== undefined) target[slot.index] = player.week.id;
    });
  }
  const proposed = next as Roster;

  const moves: LineupMove[] = [];
  for (const player of movable) {
    const to = slotOf(proposed, player.week.id);
    if (to !== null && !sameSlot(to, player.current)) moves.push({ id: player.week.id, from: player.current, to });
  }
  moves.sort(
    (a, b) =>
      SLOT_GROUPS.indexOf(a.to.group) - SLOT_GROUPS.indexOf(b.to.group) || a.to.index - b.to.index,
  );

  const starters: StarterLine[] = [];
  const gaps: LineupGap[] = [];
  let filled = 0;
  for (const group of STARTER_GROUPS) {
    for (let index = 0; index < slotCounts[group]; index += 1) {
      const id = proposed[group][index] ?? null;
      const week = id === null ? null : (weeks.get(id) ?? null);
      const slot = { group, index };
      const counted = counts(week, group);
      if (counted) filled += 1;
      starters.push({ slot, id, week, score: counted ? (scoreOf(week, mode) ?? 0) / 100 : null });
      if (counted) continue;
      if (week === null) {
        gaps.push({ slot, kind: "gap", reason: emptyReason(group, weeks) });
      } else if (week.kind === "sidelined") {
        gaps.push({
          slot,
          kind: "gap",
          reason: `${week.reason ?? "Not playing."} No eligible replacement on your roster.`,
        });
      } else if (week.kind === "pinned") {
        gaps.push({ slot, kind: "unscored", reason: week.reason ?? "His week is unknown." });
      } else if (week.kind === "locked") {
        gaps.push({ slot, kind: "unscored", reason: "His game has started and no distribution was published for it." });
      } else {
        gaps.push({ slot, kind: "gap", reason: "His position cannot fill this slot." });
      }
    }
  }
  const starterSlots = STARTER_GROUPS.reduce((sum, group) => sum + slotCounts[group], 0);
  return {
    mode,
    roster: proposed,
    starters,
    moves,
    gaps,
    total: lineupHundredths(proposed, weeks, mode) / 100,
    currentTotal: lineupHundredths(roster, weeks, mode) / 100,
    filled,
    starterSlots,
    fixed,
    weeks,
    objective: objectiveOf(problem, assignment),
  };
}

function emptyReason(group: SlotGroup, weeks: ReadonlyMap<string, PlayerWeek>): string {
  const fitting = [...weeks.values()].filter(
    (week) => week.position !== null && slotAccepts(group, week.position),
  );
  if (fitting.length === 0) return "Nobody on your roster can fill this slot.";
  const unavailable = fitting.filter((week) => week.kind !== "candidate");
  if (unavailable.length === fitting.length) {
    return `No eligible player: ${unavailable
      .map((week) => `${week.record?.display_name ?? week.id} (${(week.reason ?? "").replace(/\.$/, "")})`)
      .join("; ")}.`;
  }
  return "Every eligible player on your roster is already starting in another slot.";
}

/** The players a slot could be compared between in Start/Sit: its occupant and fitting bench. */
export function comparablesFor(
  slot: SlotRef,
  roster: Roster,
  weeks: ReadonlyMap<string, PlayerWeek>,
  limit = 4,
): string[] {
  const occupantId = roster[slot.group][slot.index] ?? null;
  const ids: string[] = [];
  if (occupantId !== null && weeks.get(occupantId)?.record != null) ids.push(occupantId);
  const bench = roster.BN.filter((id): id is string => id !== null)
    .map((id) => weeks.get(id))
    .filter(
      (week): week is PlayerWeek =>
        week?.record?.quantiles != null && week.position !== null && slotAccepts(slot.group, week.position),
    )
    .sort((a, b) => (b.record?.quantiles?.q50 ?? 0) - (a.record?.quantiles?.q50 ?? 0) || (a.id < b.id ? -1 : 1));
  for (const week of bench) {
    if (ids.length >= limit) break;
    ids.push(week.id);
  }
  return ids;
}
