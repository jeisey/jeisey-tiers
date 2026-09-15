/**
 * The in-season data model: rest-of-season rows, opportunity rows, and the mode question.
 *
 * A sibling of `model.ts` rather than an extension of it, for the reason ADR-071 gives: a
 * rest-of-season fair rank and a preseason fair rank are different quantities from different
 * models over different horizons, and putting them in one index would be one type coercion
 * away from being averaged, compared or sorted together. They share a player id and nothing
 * else, and this file is where that separation lives.
 *
 * The same three rules hold as in `model.ts`: nothing is recomputed, status is annotation,
 * and records are read-only. One more is specific to this bundle:
 *
 * **The disclosure block is not optional.** Every surface that shows `long_absence` reads its
 * sentences from `ros_build_metadata.json` rather than hardcoding them, so the artifact and
 * the interface cannot drift apart, and a build that omitted them cannot render at all.
 */

import type { Degradation } from "./bundle";
import { cohortStat, finiteValues, type CohortStat } from "./cohort";
import type {
  OpportunityRecord,
  Position,
  ProductMode,
  RosBuildMetadata,
  RosTierRecord,
  ScoringPreset,
  SeasonState,
} from "./contracts";
import { isNoteworthyRosterStatus, matchesPosition, matchesSearch } from "./model";
import type { AppState, PositionFilter } from "./state";
import { SCORING_TO_PRESET, leaguePresetId } from "./state";

function blockKey(leaguePreset: string, scoring: ScoringPreset): string {
  return `${leaguePreset}|${scoring}`;
}

export interface InSeasonInput {
  readonly metadata: RosBuildMetadata;
  readonly rosTiers: readonly RosTierRecord[];
  readonly opportunity: readonly OpportunityRecord[] | null;
  readonly opportunityDegradation: Degradation | null;
}

/** A rest-of-season row. `status` is the row's own annotation string, never a model input. */
export interface RosRow {
  readonly record: RosTierRecord;
}

export interface OpportunityRow {
  readonly record: OpportunityRecord;
  /** 1-based position in the published ordering for this block, for a stable readout. */
  readonly rank: number;
}

/** Contiguous rest-of-season-rank runs sharing a tier ordinal. A band, never a line. */
export interface RosTierGroup {
  readonly ordinal: number;
  readonly label: string;
  readonly rows: readonly RosRow[];
}

export class InSeasonBundle {
  readonly metadata: RosBuildMetadata;
  readonly opportunityDegradation: Degradation | null;
  readonly hasOpportunity: boolean;
  private readonly rosByBlock: ReadonlyMap<string, readonly RosTierRecord[]>;
  private readonly rosByBlockPlayer: ReadonlyMap<string, RosTierRecord>;
  private readonly opportunityByBlock: ReadonlyMap<string, readonly OpportunityRecord[]>;
  private readonly opportunityByBlockPlayer: ReadonlyMap<string, OpportunityRecord>;

  constructor(input: InSeasonInput) {
    this.metadata = input.metadata;
    this.opportunityDegradation = input.opportunityDegradation;
    this.hasOpportunity = input.opportunity !== null;

    const rosByBlock = new Map<string, RosTierRecord[]>();
    const rosByBlockPlayer = new Map<string, RosTierRecord>();
    for (const record of input.rosTiers) {
      const key = blockKey(record.league_preset_id, record.scoring_preset);
      const bucket = rosByBlock.get(key);
      if (bucket === undefined) rosByBlock.set(key, [record]);
      else bucket.push(record);
      rosByBlockPlayer.set(`${key}|${record.player_id}`, record);
    }
    for (const rows of rosByBlock.values()) {
      rows.sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
    }
    this.rosByBlock = rosByBlock;
    this.rosByBlockPlayer = rosByBlockPlayer;

    const opportunityByBlock = new Map<string, OpportunityRecord[]>();
    const opportunityByBlockPlayer = new Map<string, OpportunityRecord>();
    for (const record of input.opportunity ?? []) {
      const key = blockKey(record.league_preset_id, record.scoring_preset);
      const bucket = opportunityByBlock.get(key);
      if (bucket === undefined) opportunityByBlock.set(key, [record]);
      else bucket.push(record);
      opportunityByBlockPlayer.set(`${key}|${record.player_id}`, record);
    }
    for (const rows of opportunityByBlock.values()) {
      rows.sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
    }
    this.opportunityByBlock = opportunityByBlock;
    this.opportunityByBlockPlayer = opportunityByBlockPlayer;
  }

  get season(): number {
    return this.metadata.season;
  }

  get throughWeek(): number {
    return this.metadata.through_week;
  }

  get seasonState(): SeasonState {
    return this.metadata.season_state.season_state;
  }

  get derivedMode(): ProductMode {
    return this.metadata.season_state.product_mode;
  }

  rosFor(leaguePreset: string, scoring: ScoringPreset): readonly RosTierRecord[] {
    return this.rosByBlock.get(blockKey(leaguePreset, scoring)) ?? [];
  }

  rosRecordFor(
    leaguePreset: string,
    scoring: ScoringPreset,
    playerId: string,
  ): RosTierRecord | null {
    return this.rosByBlockPlayer.get(`${blockKey(leaguePreset, scoring)}|${playerId}`) ?? null;
  }

  opportunityFor(leaguePreset: string, scoring: ScoringPreset): readonly OpportunityRecord[] {
    return this.opportunityByBlock.get(blockKey(leaguePreset, scoring)) ?? [];
  }

  opportunityRecordFor(
    leaguePreset: string,
    scoring: ScoringPreset,
    playerId: string,
  ): OpportunityRecord | null {
    return (
      this.opportunityByBlockPlayer.get(`${blockKey(leaguePreset, scoring)}|${playerId}`) ?? null
    );
  }

  availableBlocks(): readonly { leaguePreset: string; scoring: ScoringPreset }[] {
    return [...this.rosByBlock.keys()].map((key) => {
      const [leaguePreset = "", scoring = "PPR"] = key.split("|");
      return { leaguePreset, scoring: scoring as ScoringPreset };
    });
  }
}

export function selectRosRows(bundle: InSeasonBundle, state: AppState): readonly RosRow[] {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const rows: RosRow[] = [];
  for (const record of bundle.rosFor(leaguePreset, scoring)) {
    if (!matchesPosition(record.position, state.position)) continue;
    if (!matchesSearch(record, state.search)) continue;
    rows.push({ record });
  }
  return rows;
}

/**
 * The Opportunity Board's rows, ordered by the sort the reader chose.
 *
 * `net` and `adds` sort by behaviour and `value` by intrinsic rank — and the two are
 * genuinely different orderings of the same rows rather than one blended score. There is no
 * combined ranking on this board on purpose: an add count and a fair rank have no common
 * unit, and a single number mixing them would imply one this product does not have.
 */
export function selectOpportunityRows(
  bundle: InSeasonBundle,
  state: AppState,
): readonly OpportunityRow[] {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const matched = bundle
    .opportunityFor(leaguePreset, scoring)
    .filter(
      (record) =>
        matchesPosition(record.position, state.position) && matchesSearch(record, state.search),
    );
  const sorted = [...matched];
  if (state.opportunity === "adds") {
    sorted.sort((a, b) => (b.add_count ?? -1) - (a.add_count ?? -1) || a.ros_fair_rank - b.ros_fair_rank);
  } else if (state.opportunity === "net") {
    sorted.sort(
      (a, b) =>
        (b.net_add_count ?? Number.NEGATIVE_INFINITY) -
          (a.net_add_count ?? Number.NEGATIVE_INFINITY) || a.ros_fair_rank - b.ros_fair_rank,
    );
  } else {
    sorted.sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
  }
  return sorted.map((record, index) => ({ record, rank: index + 1 }));
}

/** Contiguous runs sharing a tier ordinal. A surfaced row has no tier and forms no band. */
export function groupRosByTier(rows: readonly RosRow[]): readonly RosTierGroup[] {
  const groups: { ordinal: number; label: string; rows: RosRow[] }[] = [];
  for (const row of rows) {
    const ordinal = row.record.ros_tier;
    if (ordinal === null) continue;
    const last = groups.at(-1);
    if (last?.ordinal !== ordinal) {
      groups.push({
        ordinal,
        label: row.record.ros_tier_label ?? `Tier ${String(ordinal + 1)}`,
        rows: [row],
      });
    } else {
      last.rows.push(row);
    }
  }
  return groups;
}

/**
 * The one sentence a row's long-absence flag is allowed to say, and it says only what is known.
 *
 * "Has not appeared for N weeks" — an observation about appearances. Never "out", never
 * "questionable", never anything that reads as a designation, because the model has no
 * injury or practice-report information to base one on (ADR-070, ADR-076).
 */
export function longAbsenceLabel(record: {
  readonly weeks_since_last_game: number;
}): string {
  const weeks = Math.round(record.weeks_since_last_game);
  return weeks === 1 ? "Has not appeared for 1 week" : `Has not appeared for ${String(weeks)} weeks`;
}

export function isLongAbsence(record: { readonly long_absence: boolean }): boolean {
  return record.long_absence;
}

/**
 * The roster codes an expansion can be given for, and nothing else.
 *
 * Deliberately short. These are the nflverse transaction codes whose meaning is unambiguous;
 * any other code renders as itself rather than as a guess, which is the same rule ADR-082
 * settled for the check that reads these badges — assert the contract, never enumerate the
 * day's data. A wrong expansion here would put a designation the artifact never made in front
 * of a reader, which is precisely what ADR-076 forbids.
 */
const ROSTER_STATUS_NAMES: Readonly<Record<string, string>> = {
  RES: "Reserve",
  INA: "Inactive",
  PUP: "Physically unable to perform",
  NFI: "Non-football injury",
  SUS: "Suspended",
  EXE: "Exempt",
  CUT: "Released",
  RET: "Retired",
};

/** The codes that mean he cannot take the field, as opposed to a note about his roster spot. */
const ROSTER_STATUS_SEVERE = new Set(["RES", "INA", "PUP", "NFI", "SUS", "CUT", "RET"]);

/**
 * The in-season board's status badge.
 *
 * The same treatment the draft board gives `player_status.json`: a mark beside the player's
 * name, rendered only when the artifact carries something worth saying. `ACT` is the ordinary
 * case and says nothing about a player, so a column of it on every row was five hundred
 * repetitions of "nothing to report" — the Phase-12 board printed exactly that.
 *
 * The visible text is the artifact's own code, verbatim. Nothing here converts a roster code
 * into a health claim, and the badge is never the only channel: the accessible text is a
 * sentence and the code itself is legible without colour.
 */
export function rosStatusBadge(status: string | null | undefined): {
  readonly short: string;
  readonly full: string;
  readonly severity: "caution" | "warn";
} | null {
  if (status === null || status === undefined) return null;
  const code = status.trim().toUpperCase();
  if (code === "" || !isNoteworthyRosterStatus(code)) return null;
  return {
    short: code,
    full: ROSTER_STATUS_NAMES[code] ?? code,
    severity: ROSTER_STATUS_SEVERE.has(code) ? "warn" : "caution",
  };
}

/** Positive means the model likes him more now than it did in August. */
export function rankChangeLabel(change: number | null | undefined): string {
  if (change === null || change === undefined) return "—";
  if (change === 0) return "0";
  return change > 0 ? `+${String(change)}` : String(change);
}

/**
 * The bound for a diverging strip of roster transactions, from the population.
 *
 * The same problem `railBound` solved on the Draft Rail, and for the same reason. A single
 * surfaced waiver-wire pickup can carry two thousand adds against a board whose ordinary rows
 * are in single digits; scaling to him renders every other row as a hairline, which hides
 * exactly the comparison the track exists for. The 85th percentile of the non-zero counts
 * sizes the axis to the rows a reader is actually comparing, and anything past it is drawn as
 * a clipped bar with its real number printed beside it — never silently truncated.
 *
 * It lives in the data layer rather than in the chart that first needed it because two
 * surfaces now draw the same strip — the Opportunity Board and the player card — and the
 * moment a rule like this is written twice is the moment the two pictures start disagreeing
 * about the same player. One definition, two callers, each stating the bound it used.
 */
export function movesBound(counts: readonly number[]): number {
  const nonZero = counts.filter((count) => count > 0).sort((a, b) => a - b);
  if (nonZero.length === 0) return 1;
  const index = Math.min(nonZero.length - 1, Math.floor(nonZero.length * 0.85));
  return Math.max(1, nonZero[index] ?? 1);
}

/**
 * The model's remaining points divided by its remaining games.
 *
 * **Why this is a legitimate reading and not a blend.** `ros_label_v1` decomposes the target
 * into exactly three parts — remaining games, remaining points *per appearance*, and their
 * product — so points per appearance is a quantity the model is built on rather than one
 * invented here, and `points_per_game_to_date` on the same record is the identical quantity
 * measured over the weeks before the cutoff. Two numbers in one unit, one either side of the
 * cutoff, is a comparison the artifact supports; it is the opposite of the add-count-against-
 * VORP blend `AGENTS.md` forbids, which has no shared unit at all.
 *
 * **What it is not.** The ratio of two published expectations is not the expectation of the
 * ratio, so this is the model's remaining points divided by its remaining games and is
 * described that way wherever it is shown — never as "expected points per game", which would
 * claim a per-appearance estimate the artifact does not publish.
 *
 * Null when the model expects no remaining appearances, which is a real state at the end of a
 * season and after a season-ending absence, and is an absence rather than a zero.
 */
export function projectedRemainingRate(record: {
  readonly ros_expected_points: number;
  readonly ros_expected_games: number;
}): number | null {
  const games = record.ros_expected_games;
  if (!Number.isFinite(games) || games <= 0) return null;
  if (!Number.isFinite(record.ros_expected_points)) return null;
  return record.ros_expected_points / games;
}

/** The observed rate, from the published field or from the two totals behind it. */
export function scoredRate(record: RosTierRecord): number | null {
  if (typeof record.points_per_game_to_date === "number") {
    return Number.isFinite(record.points_per_game_to_date) ? record.points_per_game_to_date : null;
  }
  if (record.games_played_to_date > 0) return record.points_to_date / record.games_played_to_date;
  return null;
}

/** A player's place inside his own rest-of-season tier. A band has an order; it has no edge. */
export interface TierPlacement {
  readonly label: string;
  readonly place: number;
  readonly size: number;
}

export function rosTierPlacement(
  rows: readonly RosTierRecord[],
  record: RosTierRecord,
): TierPlacement | null {
  if (record.ros_tier === null || record.ros_tier_label === null) return null;
  const members = rows
    .filter((row) => row.ros_tier === record.ros_tier)
    .sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
  const place = members.findIndex((row) => row.player_id === record.player_id) + 1;
  if (place === 0 || members.length < 2) return null;
  return { label: record.ros_tier_label, place, size: members.length };
}

/**
 * Everything the player card needs in order to say what a number means.
 *
 * Assembled here rather than in the card for the reason the whole `data/` layer exists: the
 * card is a renderer, and a component that reached into the bundle to compute a rank would be
 * a component that could quietly compute it over the reader's current filter instead of over
 * the published board. The cohort is always **the published rows for this block and this
 * position**, never the filtered view, so the same player reads the same way whatever the
 * position control happens to say.
 *
 * Every member is nullable and every null is an ordinary state: a cohort under
 * `COHORT_MINIMUM`, a field the build did not publish for this player, a behaviour feed that
 * was down. None of them is an error and none of them renders as a zero.
 */
export interface RosCohortContext {
  readonly position: Position;
  /** The population's own name, as it is printed: `WRs`. */
  readonly noun: string;
  /** Published rest-of-season rows of this position in this block. */
  readonly boardCount: number;
  /**
   * Published rest-of-season rows in this block, all positions — the depth a rank is a rank
   * out of. A rank move is drawn against it rather than against the two ranks themselves, so
   * three places at the top of a 500-deep board is drawn as the small move it is.
   */
  readonly boardDepth: number;
  readonly vorp: CohortStat | null;
  readonly uncertainty: CohortStat | null;
  readonly remainingPoints: CohortStat | null;
  /** Points per appearance to date, over the rows of this position that have appeared. */
  readonly scoredRate: CohortStat | null;
  readonly snapShare: CohortStat | null;
  readonly targetShare: CohortStat | null;
  /** The whole block's add and drop counts, bounded as the Opportunity Board bounds them. */
  readonly movesAxis: number | null;
  readonly tier: TierPlacement | null;
}

/**
 * The population's printed name. `K` and `DST` are in the contract and on no board this
 * project builds, so they are named rather than defaulted — a cohort heading is text a reader
 * reads, and "the 96 Ks on this board" should be wrong loudly rather than quietly.
 */
const POSITION_NOUN: Readonly<Record<Position, string>> = {
  QB: "QBs",
  RB: "RBs",
  WR: "WRs",
  TE: "TEs",
  K: "kickers",
  DST: "defences",
};

export function buildRosCohortContext(
  bundle: InSeasonBundle,
  leaguePreset: string,
  scoring: ScoringPreset,
  record: RosTierRecord,
  opportunity: OpportunityRecord | null,
): RosCohortContext {
  const board = bundle.rosFor(leaguePreset, scoring);
  const cohort = board.filter((row) => row.position === record.position);
  const opportunityRows = bundle.opportunityFor(leaguePreset, scoring);
  const opportunityCohort = opportunityRows.filter((row) => row.position === record.position);

  const moveCounts = finiteValues([
    ...opportunityRows.map((row) => row.add_count),
    ...opportunityRows.map((row) => row.drop_count),
  ]);

  return {
    position: record.position,
    noun: POSITION_NOUN[record.position],
    boardCount: cohort.length,
    boardDepth: board.length,
    vorp: cohortStat(
      cohort.map((row) => row.ros_vorp_p50),
      record.ros_vorp_p50,
      "desc",
    ),
    uncertainty: cohortStat(
      cohort.map((row) => row.ros_uncertainty),
      record.ros_uncertainty,
      "desc",
    ),
    remainingPoints: cohortStat(
      cohort.map((row) => row.ros_expected_points),
      record.ros_expected_points,
      "desc",
    ),
    // Only the players who have appeared. A rate over nobody is not a low rate, and letting a
    // zero-appearance row into the denominator would flatter every player who has played.
    scoredRate: cohortStat(
      finiteValues(cohort.filter((row) => row.games_played_to_date > 0).map(scoredRate)),
      scoredRate(record),
      "desc",
    ),
    // A share has an absolute scale, so the axis is 0 to 1 rather than the cohort's own range:
    // 91% of snaps means the same thing whoever else is on the board.
    snapShare: cohortStat(
      finiteValues(opportunityCohort.map((row) => row.snap_share_last3)),
      opportunity?.snap_share_last3,
      "desc",
      { low: 0, high: 1 },
    ),
    targetShare: cohortStat(
      finiteValues(opportunityCohort.map((row) => row.target_share_last3)),
      opportunity?.target_share_last3,
      "desc",
      { low: 0, high: 1 },
    ),
    movesAxis: moveCounts.length === 0 ? null : movesBound(moveCounts),
    tier: rosTierPlacement(board, record),
  };
}

export function positionsOnBoard(bundle: InSeasonBundle, state: AppState): readonly Position[] {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const seen = new Set<Position>();
  for (const record of bundle.rosFor(leaguePreset, scoring)) seen.add(record.position);
  return [...seen];
}

export type { PositionFilter };
