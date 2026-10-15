/**
 * Win My Matchup's inputs (ADR-110 §2, §5): what each starter slot contributes, whether the two
 * lineups can be simulated at all, the lineup changes worth evaluating, and the compact numeric
 * input the engine receives.
 *
 * **Every slot is in one stated condition.** A starter is *modelled* (his published distribution,
 * "if active" when questionable or uncertain, "pregame" when his game has kicked off), *final* (a
 * confirmed final score, in the scenario that uses finals), a *bye* (a known zero), a *confirmed
 * zero* (out, doubtful or unavailable, and the reader said to count him as 0), a *confirmed empty*
 * slot, or *blocking*. Anything blocking — an empty slot nobody confirmed, a player with no
 * distribution, another week's record, an unresolved id, an unconfirmed absence, a player on both
 * teams — disables Simulate and is named. Nothing unknown becomes an unnoticed zero, and a missing
 * projection never falls back to rest-of-season points or last week's statistics.
 *
 * **The opponent is simulated as entered**, never optimised. **Proposals** reuse Auto
 * Start/Sit's exact assignment (`lineup_assignment_v1`, all three objectives) and a bounded set of
 * single bench swaps; they move only players `readWeek` calls candidates, so locks, pinned
 * players, IR and roster capacity hold.
 *
 * Pure: everything is read through the injected `WeekContext`.
 */

import { startEligible } from "./availability";
import type { RosWeeklyMetadata, WeeklyProjectionRecord } from "./contracts";
import {
  STARTER_GROUPS,
  isStarterGroup,
  rosterIds,
  slotAccepts,
  type LineupMode,
  type Roster,
  type SavedLeague,
  type SlotCounts,
  type StarterGroup,
} from "./leagueContract";
import { MODE_LABELS, optimizeLineup, readWeek, readWeeks, type LineupMove, type PlayerWeek, type WeekContext } from "./lineup";
import {
  MATCHUP_DRAWS,
  MATCHUP_ENGINE_VERSION,
  MATCHUP_MAX_VARIANTS,
  MATCHUP_SEED,
  type SimInput,
  type SimPlayer,
  type SimSlot,
} from "./matchup";
import { slotKey, type SlotRef } from "./roster";
import { knots, quantileValues, type DistributionRule } from "./startsit";
import { opponentIds, slotKeyOf, type MatchupEntry, type Side } from "./wmmContract";

export const MATCHUP_SETUP_VERSION = "matchup_setup_v1";
/** Normal-mode proposals per run: the three Auto Start/Sit objectives and single swaps. */
export const MAX_NORMAL_PROPOSALS = 23;

export type Scenario = "pregame" | "finals";

export type SlotKind = "modelled" | "final" | "bye" | "zero" | "empty" | "blocking";

/** What the reader can do about a blocking slot. */
export type SlotFix = "fill" | "count_zero" | "final" | "replace" | "resolve_overlap";

export interface SlotReading {
  readonly side: Side;
  readonly slot: SlotRef;
  readonly id: string | null;
  readonly week: PlayerWeek | null;
  readonly kind: SlotKind;
  /** Points a fixed slot contributes (final, bye, zero, empty); 0 otherwise. */
  readonly fixed: number;
  /** Modelled and questionable or uncertain: simulated as playing. */
  readonly conditional: boolean;
  /** Modelled with his game kicked off: simulated from his pregame distribution. */
  readonly locked: boolean;
  /** Why the slot blocks, or what the fixed value is, in a sentence. */
  readonly note: string | null;
  readonly fix: SlotFix | null;
}

export interface MatchupSetup {
  readonly scenario: Scenario;
  readonly mine: readonly SlotReading[];
  readonly theirs: readonly SlotReading[];
  /** Opponent starters the league's slot counts no longer have room for. */
  readonly overflow: readonly { readonly group: StarterGroup; readonly id: string }[];
  /** Players entered for the opponent who are also on my roster. */
  readonly overlaps: readonly string[];
  readonly blocking: readonly SlotReading[];
  readonly complete: boolean;
  /** Starters, either side, whose games have kicked off: the finals scenario applies to them. */
  readonly lockedStarters: readonly SlotReading[];
}

export interface SetupInput {
  readonly league: SavedLeague;
  readonly entry: MatchupEntry | null;
  readonly context: WeekContext;
  readonly scenario: Scenario;
}

/** My starters in lineup order: every starter slot the league has, filled or not. */
export function starterSlots(slots: SlotCounts): SlotRef[] {
  const out: SlotRef[] = [];
  for (const group of STARTER_GROUPS) for (let index = 0; index < slots[group]; index += 1) out.push({ group, index });
  return out;
}

/** The opponent's starters laid out on the league's slots, and whoever no longer fits. */
export function opponentLineup(
  entry: MatchupEntry | null,
  slots: SlotCounts,
): { readonly starters: Readonly<Record<StarterGroup, readonly (string | null)[]>>; readonly overflow: { group: StarterGroup; id: string }[] } {
  const overflow: { group: StarterGroup; id: string }[] = [];
  const starters = Object.fromEntries(
    STARTER_GROUPS.map((group) => {
      const entered = entry?.opponent.starters[group] ?? [];
      const laid = Array.from({ length: slots[group] }, (_, index) => entered[index] ?? null);
      entered.slice(slots[group]).forEach((id) => {
        if (id !== null) overflow.push({ group, id });
      });
      return [group, laid];
    }),
  ) as unknown as Record<StarterGroup, (string | null)[]>;
  return { starters, overflow };
}

function reading(base: Omit<SlotReading, "fixed" | "conditional" | "locked" | "note" | "fix"> & Partial<SlotReading>): SlotReading {
  return { fixed: 0, conditional: false, locked: false, note: null, fix: null, ...base };
}

function isBye(record: WeeklyProjectionRecord | null): boolean {
  return record !== null && (record.game_state === "bye" || record.game === null);
}

/** One starter slot's condition. */
export function readSlot(
  side: Side,
  slot: SlotRef,
  id: string | null,
  input: SetupInput,
  overlaps: ReadonlySet<string>,
): SlotReading {
  const { entry, context, scenario } = input;
  if (id === null) {
    const confirmed = entry?.confirmedEmpty[side].includes(slotKeyOf(slot.group as StarterGroup, slot.index)) === true;
    return confirmed
      ? reading({ side, slot, id, week: null, kind: "empty", note: "Left empty: counts 0." })
      : reading({ side, slot, id, week: null, kind: "blocking", note: "This starting slot is empty.", fix: "fill" });
  }
  if (overlaps.has(id)) {
    return reading({ side, slot, id, week: null, kind: "blocking", note: "He is entered for both teams. A player can be on only one.", fix: "resolve_overlap" });
  }
  const week = readWeek(id, context);
  if (week.position === null) {
    return reading({ side, slot, id, week, kind: "blocking", note: week.reason ?? "This build has no record of him.", fix: "replace" });
  }
  if (!slotAccepts(slot.group, week.position)) {
    return reading({ side, slot, id, week, kind: "blocking", note: "His position cannot fill this slot.", fix: "replace" });
  }
  const final = entry?.finals[id];
  const zeroed = entry?.countZero.includes(id) === true;
  switch (week.kind) {
    case "candidate":
      return reading({
        side,
        slot,
        id,
        week,
        kind: "modelled",
        conditional: week.conditional,
        note: week.conditional ? "If active: simulated as playing." : null,
      });
    case "locked": {
      if (scenario === "finals" && final !== undefined) {
        return reading({ side, slot, id, week, kind: "final", fixed: final, note: `Final score you confirmed: ${final.toFixed(2)}.` });
      }
      const absent = week.availability !== null && !startEligible(week.availability);
      if (absent) {
        if (zeroed) return reading({ side, slot, id, week, kind: "zero", note: "Not playing: you chose to count him as 0." });
        return reading({
          side,
          slot,
          id,
          week,
          kind: "blocking",
          note: `${week.availability?.headline ?? "Not available"}, and his game has kicked off. Count him as 0${scenario === "finals" ? " or enter his final score" : ""}.`,
          fix: "count_zero",
        });
      }
      if (week.record?.quantiles != null) {
        return reading({
          side,
          slot,
          id,
          week,
          kind: "modelled",
          locked: true,
          conditional: week.conditional,
          note: "Game kicked off: simulated from his pregame projection; the current score is not used.",
        });
      }
      return reading({
        side,
        slot,
        id,
        week,
        kind: "blocking",
        note:
          scenario === "finals"
            ? "His game has started and no distribution was published for it. Enter his final score once it is final."
            : "His game has started and no distribution was published for it. Use “With final scores” and enter his final score once it is final.",
        fix: "final",
      });
    }
    case "sidelined":
      if (isBye(week.record)) {
        return reading({ side, slot, id, week, kind: "bye", note: `Bye in week ${String(week.record?.target_week ?? "")}: counts 0.` });
      }
      if (zeroed) return reading({ side, slot, id, week, kind: "zero", note: `${(week.reason ?? "Not playing.").replace(/\.$/, "")}: you chose to count him as 0.` });
      return reading({
        side,
        slot,
        id,
        week,
        kind: "blocking",
        note: `${(week.reason ?? "Not playing this week.").replace(/\.$/, "")}. Count him as 0, or start someone else.`,
        fix: "count_zero",
      });
    case "pinned":
      return reading({ side, slot, id, week, kind: "blocking", note: week.reason ?? "His week is unknown.", fix: "replace" });
  }
}

/** Both lineups, slot by slot, and whether they can be simulated. */
export function readSetup(input: SetupInput): MatchupSetup {
  const { league, entry } = input;
  const opponent = opponentLineup(entry, league.slots);
  const mineIds = new Set(rosterIds(league.roster));
  const overlaps = new Set(entry === null ? [] : opponentIds(entry).filter((id) => mineIds.has(id)));
  const slots = starterSlots(league.slots);
  const mine = slots.map((slot) => readSlot("mine", slot, league.roster[slot.group][slot.index] ?? null, input, overlaps));
  const theirs = slots.map((slot) =>
    readSlot("theirs", slot, opponent.starters[slot.group as StarterGroup][slot.index] ?? null, input, overlaps),
  );
  const blocking = [...mine, ...theirs].filter((line) => line.kind === "blocking");
  const lockedStarters = [...mine, ...theirs].filter((line) => line.week?.kind === "locked");
  return {
    scenario: input.scenario,
    mine,
    theirs,
    overflow: opponent.overflow,
    overlaps: [...overlaps].sort(),
    blocking,
    complete: blocking.length === 0 && overlaps.size === 0 && opponent.overflow.length === 0,
    lockedStarters,
  };
}

// ------------------------------------------------------------------------------ proposals

export type ProposalKind = "auto" | "swap" | "yolo";

export interface Proposal {
  readonly id: string;
  readonly kind: ProposalKind;
  readonly label: string;
  /** The roster after the change (a YOLO pickup is added; any drop is chosen on apply). */
  readonly roster: Roster;
  readonly moves: readonly LineupMove[];
  /** My starters under this proposal. */
  readonly mine: readonly SlotReading[];
}

/** The starters as a multiset: two lineups that start the same players are one lineup. */
export function startersSignature(readings: readonly SlotReading[]): string {
  return readings
    .map((line) => `${line.slot.group}=${line.id ?? (line.kind === "empty" ? "empty" : "?")}`)
    .sort()
    .join(",");
}

function quantileOf(week: PlayerWeek | null | undefined, key: "q50" | "q90"): number | null {
  const quantiles = week?.record?.quantiles ?? null;
  return quantiles === null ? null : quantiles[key];
}

/** The slots a reading's occupant may leave: empty, a candidate, a bye or an absence. */
export function movableOccupant(line: SlotReading): boolean {
  if (line.locked) return false;
  if (line.kind === "modelled") return line.week?.kind === "candidate";
  return line.kind === "empty" || line.kind === "bye" || line.kind === "zero" || (line.kind === "blocking" && (line.fix === "fill" || line.fix === "count_zero"));
}

/** His contribution at a quantile when he is the incumbent: 0 for a known-zero or empty slot. */
export function incumbentQuantile(line: SlotReading, key: "q50" | "q90"): number | null {
  if (line.kind === "modelled") return quantileOf(line.week, key);
  if (line.kind === "empty" || line.kind === "bye" || line.kind === "zero") return 0;
  if (line.kind === "blocking" && (line.fix === "fill" || line.fix === "count_zero")) return 0;
  return null;
}

function withSlot(roster: Roster, slot: SlotRef, value: string | null): Roster {
  const next = [...roster[slot.group]];
  next[slot.index] = value;
  return { ...roster, [slot.group]: next };
}

/**
 * The lineup changes normal mode evaluates: the three Auto Start/Sit proposals, then single bench
 * swaps — for each bench candidate, the starting slot where his median gains most and the one
 * where his ceiling gains most — deduplicated by the starters they field. Bounded and
 * deterministic.
 */
export function normalProposals(input: SetupInput, baseline: readonly SlotReading[]): Proposal[] {
  const steps = normalProposalSteps(input, baseline);
  for (;;) {
    const step = steps.next();
    if (step.done === true) return step.value;
  }
}

/**
 * `normalProposals` in pieces — one lineup optimisation, or one candidate's readings, per
 * `next()` — so the page can build them between frames instead of in one long task.
 */
export function* normalProposalSteps(input: SetupInput, baseline: readonly SlotReading[]): Generator<undefined, Proposal[], undefined> {
  const { league, context } = input;
  const weeks = readWeeks(league.roster, context);
  const seen = new Set([startersSignature(baseline)]);
  const out: Proposal[] = [];
  const add = (proposal: Omit<Proposal, "mine">): void => {
    const mine = proposalReadings(proposal.roster, input);
    if (mine.some((line) => line.kind === "blocking")) return;
    const signature = startersSignature(mine);
    if (seen.has(signature)) return;
    seen.add(signature);
    out.push({ ...proposal, mine });
  };
  const modes: LineupMode[] = ["q50", "q10", "q90"];
  for (const mode of modes) {
    const proposal = optimizeLineup(league.roster, league.slots, context, mode, weeks);
    if (proposal.moves.length > 0) {
      add({ id: `auto-${mode}`, kind: "auto", label: `Auto Start/Sit · ${MODE_LABELS[mode]}`, roster: proposal.roster, moves: proposal.moves });
    }
    yield;
  }
  const swaps: { gain: number; proposal: Omit<Proposal, "mine"> }[] = [];
  league.roster.BN.forEach((benchId, benchIndex) => {
    if (benchId === null) return;
    const week = weeks.get(benchId);
    if (week?.kind !== "candidate" || week.position === null) return;
    const position = week.position;
    const options = baseline.filter((line) => slotAccepts(line.slot.group, position) && movableOccupant(line));
    for (const key of ["q50", "q90"] as const) {
      const mine = quantileOf(week, key);
      if (mine === null) continue;
      let best: { line: SlotReading; gain: number } | null = null;
      for (const line of options) {
        const theirs = incumbentQuantile(line, key);
        if (theirs === null) continue;
        const gain = mine - theirs;
        if (gain > 0 && (best === null || gain > best.gain)) best = { line, gain };
      }
      if (best === null) continue;
      const bench: SlotRef = { group: "BN", index: benchIndex };
      const occupant = best.line.id;
      const roster = withSlot(withSlot(league.roster, best.line.slot, benchId), bench, occupant);
      const moves: LineupMove[] = [{ id: benchId, from: bench, to: best.line.slot }];
      if (occupant !== null) moves.push({ id: occupant, from: best.line.slot, to: bench });
      swaps.push({
        gain: best.gain,
        proposal: { id: `swap-${benchId}-${slotKey(best.line.slot)}`, kind: "swap", label: key === "q50" ? "Bench swap (median)" : "Bench swap (ceiling)", roster, moves },
      });
    }
  });
  swaps.sort((a, b) => b.gain - a.gain || (a.proposal.id < b.proposal.id ? -1 : a.proposal.id > b.proposal.id ? 1 : 0));
  for (const swap of swaps) {
    add(swap.proposal);
    yield;
  }
  return out.slice(0, MAX_NORMAL_PROPOSALS);
}

/** My starters under a proposed roster, read exactly as the baseline's are. */
export function proposalReadings(roster: Roster, input: SetupInput): SlotReading[] {
  const proposed: SetupInput = { ...input, league: { ...input.league, roster } };
  const mineIds = new Set(rosterIds(roster));
  const overlaps = new Set(input.entry === null ? [] : opponentIds(input.entry).filter((id) => mineIds.has(id)));
  return starterSlots(input.league.slots).map((slot) => readSlot("mine", slot, roster[slot.group][slot.index] ?? null, proposed, overlaps));
}

// --------------------------------------------------------------------- the engine's input

export interface Identity {
  readonly buildId: string;
  readonly modelVersion: string;
  readonly scoring: string;
  readonly week: number;
  readonly leagueId: string;
}

export interface BuiltInput {
  readonly input: SimInput;
  /** The run's identity: every input a result depends on, as one string. */
  readonly fingerprint: string;
  /** The variant id of each proposal, in order (the baseline is `base`). */
  readonly variantIds: readonly string[];
}

/** The latent correlations by key, as the build published them (`rho`, never `spearman`). */
export function latentCorrelations(weekly: RosWeeklyMetadata | null | undefined): Record<string, number> {
  return Object.fromEntries(Object.entries(weekly?.correlation.pairs ?? {}).map(([key, entry]) => [key, entry.rho]));
}

/**
 * The compact engine input for a complete setup and its proposals: one entry per unique
 * modelled player (his knots, game, team and position) and each lineup as slot indexes or fixed
 * points. `detailFor` names the proposals that keep per-group distributions.
 */
export function buildSimInput(
  setup: MatchupSetup,
  proposals: readonly Proposal[],
  rule: DistributionRule,
  correlation: Readonly<Record<string, number>>,
  identity: Identity,
  options: { readonly draws?: number; readonly detailFor?: readonly string[] } = {},
): BuiltInput {
  if (!setup.complete) throw new Error("the lineups are not complete");
  const players: SimPlayer[] = [];
  const index = new Map<string, number>();
  const toSlot = (line: SlotReading): SimSlot => {
    const group = line.slot.group;
    if (!isStarterGroup(group)) throw new Error("not a starter slot");
    if (line.kind === "modelled" && line.id !== null && line.week?.record != null) {
      let at = index.get(line.id);
      if (at === undefined) {
        const record = line.week.record;
        const quantiles = quantileValues(record);
        if (quantiles === null) throw new Error(`no distribution for ${line.id}`);
        const { taus, values } = knots(quantiles, rule);
        at = players.length;
        players.push({ key: line.id, taus, values, game: record.game?.game_id ?? null, team: record.team, position: record.position });
        index.set(line.id, at);
      }
      return { group, player: at, fixed: 0 };
    }
    if (line.kind === "blocking") throw new Error("a blocking slot cannot be simulated");
    return { group, player: -1, fixed: line.fixed };
  };
  const opponent = setup.theirs.map(toSlot);
  const detail = new Set(options.detailFor ?? []);
  const usable = proposals.filter((proposal) => proposal.mine.every((line) => line.kind !== "blocking")).slice(0, MATCHUP_MAX_VARIANTS - 1);
  const variants = [
    { id: "base", slots: setup.mine.map(toSlot), detail: true },
    ...usable.map((proposal) => ({ id: proposal.id, slots: proposal.mine.map(toSlot), detail: detail.has(proposal.id) })),
  ];
  const input: SimInput = {
    version: MATCHUP_ENGINE_VERSION,
    seed: MATCHUP_SEED,
    draws: options.draws ?? MATCHUP_DRAWS,
    players,
    correlation,
    opponent,
    variants,
  };
  const describe = (lines: readonly SlotReading[]): string =>
    lines.map((line) => `${slotKey(line.slot)}=${line.kind}:${line.id ?? "-"}:${String(line.fixed)}`).join(";");
  const fingerprint = JSON.stringify({
    engine: MATCHUP_ENGINE_VERSION,
    setup: MATCHUP_SETUP_VERSION,
    seed: input.seed,
    draws: input.draws,
    ...identity,
    scenario: setup.scenario,
    rule,
    correlation: Object.entries(correlation).sort(),
    mine: describe(setup.mine),
    theirs: describe(setup.theirs),
    variants: usable.map((proposal) => `${proposal.id}:${detail.has(proposal.id) ? "d" : ""}:${describe(proposal.mine)}`),
  });
  return { input, fingerprint, variantIds: usable.map((proposal) => proposal.id) };
}
