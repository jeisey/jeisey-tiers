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
import type {
  OpportunityRecord,
  Position,
  ProductMode,
  RosBuildMetadata,
  RosTierRecord,
  ScoringPreset,
  SeasonState,
} from "./contracts";
import { matchesPosition, matchesSearch } from "./model";
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

/** Positive means the model likes him more now than it did in August. */
export function rankChangeLabel(change: number | null | undefined): string {
  if (change === null || change === undefined) return "—";
  if (change === 0) return "0";
  return change > 0 ? `+${String(change)}` : String(change);
}

export function positionsOnBoard(bundle: InSeasonBundle, state: AppState): readonly Position[] {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const seen = new Set<Position>();
  for (const record of bundle.rosFor(leaguePreset, scoring)) seen.add(record.position);
  return [...seen];
}

export type { PositionFilter };
