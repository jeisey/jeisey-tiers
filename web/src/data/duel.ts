/**
 * The Start/Sit duel: two to four players, one lineup slot, and the reader's matchup (ADR-096).
 *
 * **The question other sites answer** is "who is projected for more points". Two medians and
 * a winner. **The question a manager is actually asking** is "who gives me the best chance to
 * win this week" — and those are different questions whenever the two players' ranges differ
 * and the manager is not in an even matchup. A trailing manager needs the ceiling; a leading
 * one needs the floor. This module answers the second question, from published numbers only:
 *
 * - each player's **next-game distribution** (seven quantiles, `weekly-startsit-v1`);
 * - the **matchup margin** the reader supplies, and its **measured uncertainty** (out-of-fold
 *   residual variance over a standard lineup, published in the build metadata);
 * - the measured **same-game correlation** when two players share a game.
 *
 * It then says who to start, how sure that is (the head-to-head probability the evaluation
 * calibrated), and — the reading nothing else offers — **the margin at which the answer
 * flips**, so a reader knows whether their own matchup is on the other side of it.
 *
 * Nothing here computes a player value. Every per-player number is a published quantile, and
 * every combination is a probability over them.
 */

import type {
  RosWeeklyMetadata,
  ScoringPreset,
  WeeklyProjectionRecord,
} from "./contracts";
import { startEligible, startExclusion, type Availability } from "./availability";
import { matchesPosition, matchesSearch } from "./model";
import type { InSeasonBundle } from "./ros";
import type { AppState } from "./state";
import { MAX_DUEL, SCORING_TO_PRESET, leaguePresetId } from "./state";
import {
  bestOfSet,
  confidenceWord,
  designationRate,
  distributionRule,
  flipMargin,
  gridFromQuantiles,
  marginSigma,
  pairCorrelation,
  probAtLeast,
  probGreater,
  probGreaterCorrelated,
  quantileValues,
  startableThreshold,
  winProbability,
  type DistributionRule,
} from "./startsit";

export interface Contender {
  readonly record: WeeklyProjectionRecord;
  readonly quantiles: readonly number[] | null;
  readonly grid: Float64Array | null;
  /** The league-and-scoring startable threshold for his position, and his chance to reach it. */
  readonly startable: { readonly threshold: number; readonly probability: number } | null;
  /** P(win) at the reader's margin, when a margin uncertainty is published. */
  readonly winProbability: number | null;
  /** P(he is the set's top scorer), for three or four eligible players. */
  readonly topOfSet: number | null;
  /** His game had kicked off when the build ran, or has by the reader's clock. */
  readonly locked: boolean;
  readonly bye: boolean;
  /** His game has no posted line yet, so the build published no distribution for it. */
  readonly pending: boolean;
  /** Designated out for this game (official report or Sleeper). */
  readonly out: boolean;
  /** The availability policy's reading (ADR-101). */
  readonly availability: Availability;
  /** Why the policy leaves him out of the verdict (out, doubtful, reserve, season over), or null. */
  readonly exclusion: string | null;
  /**
   * Eligible for the verdict: a distribution (not on bye, not awaiting a line) and available
   * to start under the policy. Questionable and uncertain stay eligible, labelled "if active".
   */
  readonly eligible: boolean;
}

export interface DuelVerdict {
  readonly pick: Contender;
  readonly runnerUp: Contender;
  /** P(pick outscores runner-up): the calibrated head-to-head the evaluation scored. */
  readonly edge: number;
  readonly word: ReturnType<typeof confidenceWord>;
  /** Whether the win-probability pick differs from the higher median. */
  readonly postureChangedPick: boolean;
  readonly medianLeader: Contender;
  readonly flip: {
    readonly margin: number;
    /** Who is the better start past the flip, in the direction away from zero. */
    readonly beyond: Contender;
    readonly side: "behind" | "ahead";
  } | null;
  readonly correlation: { readonly rho: number; readonly key: string | null; readonly measured: boolean };
}

export interface DuelReading {
  readonly targetWeek: number | null;
  readonly scoring: ScoringPreset;
  readonly leaguePreset: string;
  readonly margin: number;
  readonly sigma: number | null;
  readonly rule: DistributionRule;
  readonly contenders: readonly Contender[];
  /** Ids in the URL that this build has no projection for. */
  readonly missing: readonly string[];
  readonly eligible: readonly Contender[];
  /** P(row outscores column) among eligible contenders; the diagonal is null. */
  readonly matrix: readonly (readonly (number | null)[])[] | null;
  readonly verdict: DuelVerdict | null;
}

function isLocked(record: WeeklyProjectionRecord, now: Date | undefined): boolean {
  if (record.game_state === "kicked_off") return true;
  const kickoff = record.game?.kickoff_utc;
  if (now === undefined || kickoff === null || kickoff === undefined) return false;
  return Date.parse(kickoff) <= now.getTime();
}

function contenderFor(
  record: WeeklyProjectionRecord,
  availability: Availability,
  context: {
    readonly rule: DistributionRule;
    readonly weekly: RosWeeklyMetadata | null | undefined;
    readonly leaguePreset: string;
    readonly scoring: ScoringPreset;
    readonly margin: number;
    readonly sigma: number | null;
    readonly now: Date | undefined;
  },
): Contender {
  const quantiles = quantileValues(record);
  const grid = quantiles === null ? null : gridFromQuantiles(quantiles, context.rule);
  const threshold = startableThreshold(
    context.weekly,
    context.leaguePreset,
    context.scoring,
    record.position,
  );
  const bye = record.game_state === "bye";
  const pending = record.game_state === "lines_pending";
  const out = availability.week === "out";
  const exclusion = startExclusion(availability);
  return {
    record,
    quantiles,
    grid,
    startable:
      grid === null || threshold === null
        ? null
        : { threshold, probability: probAtLeast(grid, threshold) },
    winProbability:
      grid === null || context.sigma === null
        ? null
        : winProbability(grid, context.margin, context.sigma),
    topOfSet: null,
    locked: isLocked(record, context.now),
    bye,
    pending,
    out,
    availability,
    exclusion,
    eligible: grid !== null && !bye && startEligible(availability),
  };
}

/** P(a outscores b): independent unless they share a game and the build measured a ρ. */
function headToHead(
  a: Contender,
  b: Contender,
  weekly: RosWeeklyMetadata | null | undefined,
  rule: DistributionRule,
): number {
  const rho = pairCorrelation(a.record, b.record, weekly).rho;
  if (rho === 0 && a.grid !== null && b.grid !== null) return probGreater(a.grid, b.grid);
  return probGreaterCorrelated(a.quantiles ?? [], b.quantiles ?? [], rho, rule);
}

function median(contender: Contender): number {
  return contender.record.quantiles?.q50 ?? -Infinity;
}

/** Everything the duel section draws, for the players in the URL. */
export function readDuel(
  bundle: InSeasonBundle,
  state: Pick<AppState, "duel" | "margin" | "scoring" | "teams">,
  now?: Date,
): DuelReading {
  const weekly = bundle.metadata.weekly;
  const scoring = SCORING_TO_PRESET[state.scoring];
  const leaguePreset = leaguePresetId(state.teams);
  const rule = distributionRule(weekly);
  const records: WeeklyProjectionRecord[] = [];
  const missing: string[] = [];
  for (const id of state.duel.slice(0, MAX_DUEL)) {
    const record = bundle.weeklyRecordFor(scoring, id);
    if (record === null) missing.push(id);
    else records.push(record);
  }
  const positions = [...new Set(records.map((record) => record.position))];
  const sigma = marginSigma(weekly, scoring, positions);
  const context = { rule, weekly, leaguePreset, scoring, margin: state.margin, sigma, now };
  let contenders = records.map((record) =>
    contenderFor(record, bundle.availabilityFor(record.player_id), context),
  );
  const eligible = contenders.filter((contender) => contender.eligible);

  // Each pair is computed once and its mirror is the complement, so the matrix a reader sees
  // is always coherent. The copula's discretisation is not exactly antisymmetric (a same-game
  // pair can read 0.5212 one way and 0.4788 + 7e-5 the other); the independent case is exact.
  let matrix: (number | null)[][] | null = null;
  if (eligible.length >= 2) {
    const cells: (number | null)[][] = eligible.map(() => eligible.map(() => null));
    eligible.forEach((row, i) => {
      eligible.forEach((column, j) => {
        if (j <= i) return;
        const p = headToHead(row, column, weekly, rule);
        const upper = cells[i];
        const lower = cells[j];
        if (upper !== undefined) upper[j] = p;
        if (lower !== undefined) lower[i] = 1 - p;
      });
    });
    matrix = cells;
  }

  if (eligible.length >= 3) {
    const correlation = eligible.map((row) =>
      eligible.map((column) =>
        row === column ? 1 : pairCorrelation(row.record, column.record, weekly).rho,
      ),
    );
    const anyCorrelated = correlation.some((row, i) => row.some((value, j) => i !== j && value !== 0));
    const tops = bestOfSet(
      eligible.map((contender) => contender.quantiles ?? []),
      anyCorrelated ? correlation : null,
      rule,
    );
    const byId = new Map(eligible.map((contender, index) => [contender.record.player_id, tops[index] ?? 0]));
    contenders = contenders.map((contender) =>
      byId.has(contender.record.player_id)
        ? { ...contender, topOfSet: byId.get(contender.record.player_id) ?? null }
        : contender,
    );
  }
  const eligibleAfter = contenders.filter((contender) => contender.eligible);

  return {
    targetWeek: weekly?.target_week ?? records[0]?.target_week ?? null,
    scoring,
    leaguePreset,
    margin: state.margin,
    sigma,
    rule,
    contenders,
    missing,
    eligible: eligibleAfter,
    matrix,
    verdict: verdictFor(eligibleAfter, { sigma, weekly, margin: state.margin }),
  };
}

function verdictFor(
  eligible: readonly Contender[],
  context: {
    readonly sigma: number | null;
    readonly weekly: RosWeeklyMetadata | null | undefined;
    readonly margin: number;
  },
): DuelVerdict | null {
  const medianOrder = [...eligible].sort(
    (a, b) => median(b) - median(a) || a.record.player_id.localeCompare(b.record.player_id),
  );
  const [medianLeader] = medianOrder;
  if (medianLeader === undefined || eligible.length < 2) return null;
  // The pick is the best chance to win the week when a margin uncertainty is published, and
  // the higher median when it is not — which is what the win probability reduces to at an
  // even matchup for two symmetric distributions anyway.
  const order =
    context.sigma === null
      ? medianOrder
      : [...eligible].sort(
          (a, b) =>
            (b.winProbability ?? 0) - (a.winProbability ?? 0) ||
            median(b) - median(a) ||
            a.record.player_id.localeCompare(b.record.player_id),
        );
  const [pick, runnerUp] = order;
  if (pick === undefined || runnerUp === undefined) return null;
  const correlation = pairCorrelation(pick.record, runnerUp.record, context.weekly);
  const edge = headToHead(pick, runnerUp, context.weekly, distributionRule(context.weekly));

  let flip: DuelVerdict["flip"] = null;
  if (context.sigma !== null && pick.grid !== null && runnerUp.grid !== null) {
    const crossing = flipMargin(pick.grid, runnerUp.grid, context.sigma);
    if (crossing !== null) {
      // Which of the two is better on the far side of the crossing from the reader's margin.
      const probe = crossing < context.margin ? crossing - 5 : crossing + 5;
      const pickThere = winProbability(pick.grid, probe, context.sigma);
      const runnerThere = winProbability(runnerUp.grid, probe, context.sigma);
      flip = {
        margin: crossing,
        beyond: runnerThere > pickThere ? runnerUp : pick,
        side: crossing < context.margin ? "behind" : "ahead",
      };
    }
  }
  return {
    pick,
    runnerUp,
    edge,
    word: confidenceWord(edge),
    postureChangedPick: pick.record.player_id !== medianLeader.record.player_id,
    medianLeader,
    flip,
    correlation,
  };
}

// ------------------------------------------------------------------------ the week board

export type WeekBoardOrder = "median" | "ceiling" | "floor" | "startable";

export interface WeekBoardRow {
  readonly record: WeeklyProjectionRecord;
  readonly availability: Availability;
  readonly startable: number | null;
  readonly threshold: number | null;
  readonly locked: boolean;
  /**
   * 1-based rank by median among this position's records that can play (ADR-101): a player
   * who is out or on a reserve list has no rank this week rather than a slot he cannot fill.
   */
  readonly positionRank: number | null;
}

/**
 * The week's projections for the reader's filters, in the chosen order.
 *
 * With every position on screen the default order is the startable probability, because it is
 * the one reading that means the same thing at every position — a quarterback's median and a
 * tight end's are not on one scale, but "how likely is a startable week" is.
 */
export function selectWeekBoard(
  bundle: InSeasonBundle,
  state: Pick<AppState, "scoring" | "teams" | "position" | "search">,
  order: WeekBoardOrder,
  now?: Date,
): readonly WeekBoardRow[] {
  const weekly = bundle.metadata.weekly;
  const scoring = SCORING_TO_PRESET[state.scoring];
  const leaguePreset = leaguePresetId(state.teams);
  const rule = distributionRule(weekly);
  const records = bundle.weeklyFor(scoring);

  const ranks = new Map<string, number>();
  const byPosition = new Map<string, WeeklyProjectionRecord[]>();
  const playing = (record: WeeklyProjectionRecord): boolean => {
    const week = bundle.availabilityFor(record.player_id).week;
    return week !== "out" && week !== "unavailable";
  };
  for (const record of records) {
    if (record.quantiles === null || !playing(record)) continue;
    const bucket = byPosition.get(record.position) ?? [];
    bucket.push(record);
    byPosition.set(record.position, bucket);
  }
  for (const bucket of byPosition.values()) {
    bucket
      .sort((a, b) => (b.quantiles?.q50 ?? 0) - (a.quantiles?.q50 ?? 0) || a.player_id.localeCompare(b.player_id))
      .forEach((record, index) => ranks.set(record.player_id, index + 1));
  }

  const rows = records
    .filter((record) => matchesPosition(record.position, state.position))
    .filter((record) => matchesSearch(record, state.search))
    .map((record): WeekBoardRow => {
      const quantiles = quantileValues(record);
      const threshold = startableThreshold(weekly, leaguePreset, scoring, record.position);
      const startable =
        quantiles === null || threshold === null
          ? null
          : probAtLeast(gridFromQuantiles(quantiles, rule), threshold);
      return {
        record,
        availability: bundle.availabilityFor(record.player_id),
        startable,
        threshold,
        locked: isLocked(record, now),
        positionRank: ranks.get(record.player_id) ?? null,
      };
    });

  const key = (row: WeekBoardRow): number => {
    const quantiles = row.record.quantiles;
    if (quantiles === null) return -Infinity;
    switch (order) {
      case "ceiling":
        return quantiles.q90;
      case "floor":
        return quantiles.q10;
      case "startable":
        return row.startable ?? -Infinity;
      default:
        return quantiles.q50;
    }
  };
  // A player who cannot play this week sorts below every one who can, whatever his numbers:
  // the board is a list of choices, and he is not one. He stays on it, muted and labelled.
  const sidelined = (row: WeekBoardRow): number =>
    row.availability.week === "out" || row.availability.week === "unavailable" ? 1 : 0;
  return rows.sort(
    (a, b) =>
      sidelined(a) - sidelined(b) ||
      key(b) - key(a) ||
      (b.record.quantiles?.q50 ?? -Infinity) - (a.record.quantiles?.q50 ?? -Infinity) ||
      a.record.player_id.localeCompare(b.record.player_id),
  );
}

/** One column of the week board as the reader sorted it: which, and which way. */
export interface WeekBoardSort<Column extends string = string> {
  readonly column: Column;
  readonly desc: boolean;
}

/**
 * The board re-sorted by one column a reader clicked.
 *
 * A missing value — a bye's median, an unprojected player's RoS rank, a season rank for a
 * player who has not appeared — sorts last in either direction, because "no reading" is not
 * the smallest or the largest reading. Rows that tie keep the order they arrived in, which
 * is the board's "Order by" order, so a coarse column still reads best-first inside each value.
 * Sorted before the board is paged: the first page of a sort is the top of the whole board.
 */
export function sortWeekBoard<Row>(
  rows: readonly Row[],
  key: (row: Row) => number | string | null | undefined,
  desc: boolean,
): Row[] {
  const keyed = rows.map((row, index) => {
    const value = key(row);
    const missing = value === null || value === undefined || (typeof value === "number" && !Number.isFinite(value));
    return { row, index, value: missing ? null : value };
  });
  keyed.sort((a, b) => {
    if (a.value === null || b.value === null) {
      if (a.value === null && b.value === null) return a.index - b.index;
      return a.value === null ? 1 : -1;
    }
    const order =
      typeof a.value === "number" && typeof b.value === "number"
        ? a.value - b.value
        : String(a.value).localeCompare(String(b.value));
    if (order !== 0) return desc ? -order : order;
    return a.index - b.index;
  });
  return keyed.map((entry) => entry.row);
}

/** His chance of a startable week in this league and scoring, or null (no distribution, no threshold). */
export function startableFor(
  record: WeeklyProjectionRecord | null,
  weekly: RosWeeklyMetadata | null | undefined,
  leaguePreset: string,
  scoring: ScoringPreset,
): { readonly threshold: number; readonly probability: number } | null {
  if (record === null) return null;
  const quantiles = quantileValues(record);
  const threshold = startableThreshold(weekly, leaguePreset, scoring, record.position);
  if (quantiles === null || threshold === null) return null;
  return {
    threshold,
    probability: probAtLeast(gridFromQuantiles(quantiles, distributionRule(weekly)), threshold),
  };
}

/** The designation, with how often it has meant a missed game. */
export function injuryReading(
  record: WeeklyProjectionRecord,
  weekly: RosWeeklyMetadata | null | undefined,
): { readonly short: string; readonly sentence: string } | null {
  const report = record.injury;
  if (report?.designation == null) return null;
  const short = report.designation === "Questionable" ? "Q" : report.designation === "Doubtful" ? "D" : "OUT";
  const rate = designationRate(weekly, report.designation);
  const injury = report.primary_injury === null ? "" : ` (${report.primary_injury})`;
  const practice = report.practice_status === null ? "" : ` ${report.practice_status}.`;
  const base =
    rate === null
      ? ""
      : ` Players listed ${report.designation.toLowerCase()} have played ${String(Math.round(rate.rate * 100))}% of the time (${rate.reports.toLocaleString("en-US")} reports).`;
  return {
    short,
    sentence: `${report.designation}${injury} on the week ${String(report.week)} report.${practice}${base} The projection assumes he plays.`,
  };
}

/**
 * The flip point in the reader's words, for any sign of margin on either side.
 *
 * Moving *down* past the crossing (a worse matchup) the better start is the one whose ceiling
 * is worth more; moving *up* past it, the one whose floor is. The sentence names the margin the
 * way a platform prints it — "lose by", "win by" — rather than as a signed number.
 */
export function flipSentence(flip: NonNullable<DuelVerdict["flip"]>): string {
  const points = Math.round(Math.abs(flip.margin) * 10) / 10;
  const amount = Number.isInteger(points) ? String(points) : points.toFixed(1);
  const name = flip.beyond.record.display_name;
  if (flip.side === "behind") {
    const condition =
      flip.margin < 0
        ? `you are projected to lose by more than ${amount}`
        : `you are projected to win by less than ${amount}`;
    return `If ${condition} without this slot, start ${name} — you need his ceiling.`;
  }
  const condition =
    flip.margin > 0
      ? `you are projected to win by more than ${amount}`
      : `you are projected to lose by less than ${amount}`;
  return `If ${condition} without this slot, start ${name} — his floor protects the lead.`;
}

/** Add or remove one player; order is the reader's, and the fifth add is refused. */
export function toggleDuel(duel: readonly string[], playerId: string): readonly string[] {
  if (duel.includes(playerId)) return duel.filter((id) => id !== playerId);
  if (duel.length >= MAX_DUEL) return duel;
  return [...duel, playerId];
}
