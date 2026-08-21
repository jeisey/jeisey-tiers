/**
 * TypeScript mirrors of the public artifact contracts in `schemas/`.
 *
 * The JSON Schemas remain the source of truth (AGENTS.md section 18). These interfaces
 * exist so the app is type-checked against them, and the exported field lists below let a
 * test assert that the two descriptions still agree — a field renamed in Python must fail
 * the frontend build rather than surface as `undefined` in a table cell.
 */

/**
 * The *envelope* (bundle) version, bumped together across `schemas/`, the serializers, the
 * fixtures and this file. Individual record contracts version independently — see
 * `RECORD_SCHEMA_VERSIONS`, which mirrors `ffdraft.artifacts.RECORD_SCHEMA_VERSIONS`.
 */
export const ARTIFACT_SCHEMA_VERSION = "1.0";

/** Per-record contract versions. Phase 5 moved `arbitrage_record` to 1.1 (ADR-040). */
export const RECORD_SCHEMA_VERSIONS = {
  tiers: "1.0",
  arbitrage: "1.1",
  projections: "1.0",
  market_snapshot: "1.0",
  player_status: "1.0",
} as const;

export type ScoringPreset = "STD" | "HALF" | "PPR";
export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DST";
export type ArbitrageMode = "baseline" | "ml";
export type Confidence = "high" | "medium" | "low" | "unknown";
export type SourceStatus = "pass" | "warning" | "failed" | "disabled";
export type ArtifactName =
  | "tiers"
  | "arbitrage"
  | "projections"
  | "market_snapshot"
  | "player_status";

export interface ArtifactEnvelope<TRecord> {
  readonly schema_version: string;
  readonly artifact: ArtifactName;
  readonly record_schema?: string;
  readonly build_id: string;
  readonly generated_at_utc: string;
  readonly record_count: number;
  readonly arbitrage_mode?: ArbitrageMode;
  readonly records: readonly TRecord[];
}

export interface TierRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly league_preset_id: string;
  readonly scoring_preset: ScoringPreset;
  readonly player_id: string;
  readonly display_name: string;
  readonly team: string | null;
  readonly position: Position;
  readonly fair_rank: number;
  readonly position_rank: number;
  readonly tier_ordinal: number;
  readonly tier_label: string;
  readonly expected_vorp: number;
  readonly p10_vorp: number;
  readonly p25_vorp: number;
  readonly p50_vorp: number;
  readonly p75_vorp: number;
  readonly p90_vorp: number;
  readonly expected_points: number;
  readonly uncertainty: number;
  readonly quality_flags: readonly string[];
}

export interface ArbitrageRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly league_preset_id: string;
  readonly scoring_preset: ScoringPreset;
  readonly player_id: string;
  readonly display_name: string;
  readonly team: string | null;
  readonly position: Position;
  readonly fair_rank: number;
  readonly market_adp: number;
  readonly market_rank: number | null;
  /** `market_adp - fair_rank`. Positive means the market is late on the player. */
  readonly rank_gap: number;
  /** `ln(market_adp / fair_rank)`: the same comparison, normalized for draft region. */
  readonly regional_value_gap: number;
  readonly arbitrage_mode: ArbitrageMode;
  /** Midpoint percentile of `regional_value_gap` within this preset block. An ordering. */
  readonly arbitrage_score: number;
  /** Null in baseline mode. ADR-010 forbids claiming a model that was not trained. */
  readonly expected_surplus_vorp: number | null;
  readonly p_positive_surplus: number | null;
  /** Picks per day, positive = moving earlier. Null until the store has enough history. */
  readonly market_trend: number | null;
  readonly market_sample_size: number | null;
  /** Always null for MyFantasyLeague: the export publishes no standard deviation. */
  readonly market_adp_sd: number | null;
  /** Extreme order statistics: they widen with sample size, so do not compare across rows. */
  readonly market_adp_low: number | null;
  readonly market_adp_high: number | null;
  readonly market_source_id: string;
  readonly market_cohort_id: string;
  /** The filters actually sent, plus whether the cohort is exact for this preset. */
  readonly market_cohort_detail: string;
  readonly market_snapshot_at_utc: string;
  /** Market-data quality, never a probability that the player is a bargain (ADR-041). */
  readonly confidence: Confidence;
  readonly quality_flags: readonly string[];
}

/**
 * Current roster and injury status, keyed once per player (ADR-043).
 *
 * Joined to Tier and Arbitrage rows in the browser by `player_id`. **Annotation only**: no
 * field here participated in producing a projection, a fair rank, a tier or an arbitrage
 * score, and the UI must not present it as if it had.
 */
export interface PlayerStatusRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  readonly player_id: string;
  readonly display_name: string;
  readonly current_team: string | null;
  readonly position: Position;
  /** nflverse roster status, as published (ACT/RES/CUT/...). */
  readonly roster_status: string | null;
  readonly roster_depth_chart_position: string | null;
  readonly sleeper_status: string | null;
  readonly injury_status: string | null;
  readonly injury_body_part: string | null;
  readonly injury_notes: string | null;
  readonly injury_start_date: string | null;
  readonly practice_participation: string | null;
  readonly practice_description: string | null;
  readonly depth_chart_position: string | null;
  readonly depth_chart_order: number | null;
  readonly observed_at_utc: string;
  readonly source_ids: readonly string[];
  readonly quality_flags: readonly string[];
}

export interface PlayerProjectionRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly model_version: string;
  readonly season: number;
  readonly as_of_utc: string;
  readonly player_id: string;
  readonly display_name: string;
  readonly team: string | null;
  readonly position: Position;
  readonly scoring_preset: ScoringPreset;
  readonly expected_points: number;
  readonly p10_points: number;
  readonly p25_points: number;
  readonly p50_points: number;
  readonly p75_points: number;
  readonly p90_points: number;
  readonly uncertainty_points: number;
  /**
   * Optional in `schemas/player_projection.schema.json` — it is not in that schema's
   * `required` list, and the production current build omits it while the fixture pipeline
   * emits it. Declared optional here so a consumer has to handle its absence rather than
   * reading `undefined` out of a field the type promised was present.
   */
  readonly expected_games?: number | null;
  readonly quality_flags: readonly string[];
}

export interface MarketSnapshotRecord {
  readonly schema_version: string;
  readonly source_id: string;
  readonly snapshot_at_utc: string;
  /** Null whenever the source publishes no data-as-of time, which MyFantasyLeague does not. */
  readonly source_as_of_utc: string | null;
  readonly season: number;
  readonly league_size: number;
  readonly scoring_preset: ScoringPreset;
  readonly player_id: string;
  readonly market_adp: number;
  readonly market_rank: number | null;
  readonly sample_size: number | null;
  readonly adp_sd: number | null;
  readonly adp_low: number | null;
  readonly adp_high: number | null;
  /** The filters actually sent, plus whether the cohort is approximate (ADR-012). */
  readonly source_format_detail: string | null;
  readonly quality_flags: readonly string[];
}

export interface BuildSourceStatus {
  readonly source_id: string;
  readonly status: SourceStatus;
  readonly retrieved_at_utc: string;
  readonly source_as_of_utc?: string | null;
  readonly record_count: number;
  readonly warnings?: readonly string[];
}

/** Market provenance for the arbitrage board (ADR-038/039/041/042). */
export interface BuildMarketMetadata {
  readonly source_id?: string;
  readonly snapshot_key?: string;
  readonly snapshot_at_utc?: string;
  /** Always null for MyFantasyLeague: its response timestamp is generation time. */
  readonly source_as_of_utc?: string | null;
  readonly cohort_rule_version?: string;
  readonly confidence_rubric_version?: string;
  readonly trend_rule_version?: string;
  readonly trend_available?: boolean;
  /** How many retained snapshots the trend window saw. Two is not three (ADR-042). */
  readonly trend_history_snapshots?: number;
  readonly cohort_report?: string;
  readonly assignments?: readonly {
    readonly scoring_preset: ScoringPreset;
    readonly league_size: number;
    readonly cohort_id: string;
    readonly exact: boolean;
    readonly sufficient: boolean;
    readonly source_format_detail: string;
    /**
     * The sufficiency clauses this cohort failed, verbatim (`total_drafts 125 < 300`).
     *
     * Published by the build so the Arbitrage view can say *why* every row reads `low`
     * without embedding a measurement in frontend source, which would go stale as the
     * draft season fills the cohort out (ADR-041, ADR-045).
     */
    readonly failed_clauses?: readonly string[];
  }[];
  /** Per-preset priced-versus-board counts, so "42 unpriced" is read, not asserted. */
  readonly coverage?: {
    readonly blocks?: readonly {
      readonly league_preset_id: string;
      readonly scoring_preset: ScoringPreset;
      readonly board_players: number;
      readonly priced_players: number;
      readonly board_coverage: number;
      readonly top150_priced: number;
      readonly top150_players: number;
      readonly top150_coverage: number;
    }[];
    readonly total_priced_rows?: number;
    readonly min_top150_coverage?: number;
    readonly min_board_coverage?: number;
  };
  readonly confidence_counts?: Readonly<Partial<Record<Confidence, number>>>;
  readonly unpriced_top_players?: number;
}

/** Player-status artifact provenance (ADR-043). Annotation only. */
export interface BuildPlayerStatusMetadata {
  readonly players?: number;
  readonly sleeper_available?: boolean;
  readonly sleeper_matched?: number;
  readonly sleeper_identity_conflicts?: number;
  readonly observed_at_utc?: string | null;
  readonly source_ids?: readonly string[];
}

export interface BuildMetadata {
  readonly schema_version: string;
  readonly build_id: string;
  readonly generated_at_utc: string;
  readonly git_sha: string;
  readonly season: number;
  readonly intrinsic_model_version: string;
  readonly arbitrage_mode: ArbitrageMode;
  readonly arbitrage_model_version: string | null;
  readonly arbitrage_method_version?: string | null;
  readonly market?: BuildMarketMetadata | null;
  readonly player_status?: BuildPlayerStatusMetadata | null;
  readonly supported_presets: readonly string[];
  readonly sources: readonly BuildSourceStatus[];
  readonly quality_gate: {
    readonly status: "pass" | "fail";
    readonly critical_failures: number;
    readonly warnings: number;
  };
  readonly warnings: readonly string[];
  readonly methodology_version: string;
}

/**
 * Declared field order per record, matching each JSON Schema's property order.
 *
 * `satisfies` proves every entry is a real key; the exhaustiveness checks below prove no
 * key is missing. Together they make a field added on the Python side a TypeScript error
 * here, which is the only way two independently written descriptions stay in step.
 */
export const TIER_FIELDS = [
  "schema_version",
  "build_id",
  "league_preset_id",
  "scoring_preset",
  "player_id",
  "display_name",
  "team",
  "position",
  "fair_rank",
  "position_rank",
  "tier_ordinal",
  "tier_label",
  "expected_vorp",
  "p10_vorp",
  "p25_vorp",
  "p50_vorp",
  "p75_vorp",
  "p90_vorp",
  "expected_points",
  "uncertainty",
  "quality_flags",
] as const satisfies readonly (keyof TierRecord)[];

export const ARBITRAGE_FIELDS = [
  "schema_version",
  "build_id",
  "league_preset_id",
  "scoring_preset",
  "player_id",
  "display_name",
  "team",
  "position",
  "fair_rank",
  "market_adp",
  "market_rank",
  "rank_gap",
  "regional_value_gap",
  "arbitrage_mode",
  "arbitrage_score",
  "expected_surplus_vorp",
  "p_positive_surplus",
  "market_trend",
  "market_sample_size",
  "market_adp_sd",
  "market_adp_low",
  "market_adp_high",
  "market_source_id",
  "market_cohort_id",
  "market_cohort_detail",
  "market_snapshot_at_utc",
  "confidence",
  "quality_flags",
] as const satisfies readonly (keyof ArbitrageRecord)[];

export const PLAYER_STATUS_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "player_id",
  "display_name",
  "current_team",
  "position",
  "roster_status",
  "roster_depth_chart_position",
  "sleeper_status",
  "injury_status",
  "injury_body_part",
  "injury_notes",
  "injury_start_date",
  "practice_participation",
  "practice_description",
  "depth_chart_position",
  "depth_chart_order",
  "observed_at_utc",
  "source_ids",
  "quality_flags",
] as const satisfies readonly (keyof PlayerStatusRecord)[];

export const PROJECTION_FIELDS = [
  "schema_version",
  "build_id",
  "model_version",
  "season",
  "as_of_utc",
  "player_id",
  "display_name",
  "team",
  "position",
  "scoring_preset",
  "expected_points",
  "p10_points",
  "p25_points",
  "p50_points",
  "p75_points",
  "p90_points",
  "uncertainty_points",
  "expected_games",
  "quality_flags",
] as const satisfies readonly (keyof PlayerProjectionRecord)[];

export const MARKET_SNAPSHOT_FIELDS = [
  "schema_version",
  "source_id",
  "snapshot_at_utc",
  "source_as_of_utc",
  "season",
  "league_size",
  "scoring_preset",
  "player_id",
  "market_adp",
  "market_rank",
  "sample_size",
  "adp_sd",
  "adp_low",
  "adp_high",
  "source_format_detail",
  "quality_flags",
] as const satisfies readonly (keyof MarketSnapshotRecord)[];

type MissingKeys<TRecord, TFields extends readonly (keyof TRecord)[]> = Exclude<
  keyof TRecord,
  TFields[number]
>;
type NoMissingKeys<TRecord, TFields extends readonly (keyof TRecord)[]> = [
  MissingKeys<TRecord, TFields>,
] extends [never]
  ? true
  : { error: "field list is missing keys"; missing: MissingKeys<TRecord, TFields> };

// These fail to compile if an interface gains a field the list above does not name.
export const TIER_FIELDS_COMPLETE: NoMissingKeys<TierRecord, typeof TIER_FIELDS> = true;
export const ARBITRAGE_FIELDS_COMPLETE: NoMissingKeys<
  ArbitrageRecord,
  typeof ARBITRAGE_FIELDS
> = true;
export const PROJECTION_FIELDS_COMPLETE: NoMissingKeys<
  PlayerProjectionRecord,
  typeof PROJECTION_FIELDS
> = true;
export const MARKET_SNAPSHOT_FIELDS_COMPLETE: NoMissingKeys<
  MarketSnapshotRecord,
  typeof MARKET_SNAPSHOT_FIELDS
> = true;
export const PLAYER_STATUS_FIELDS_COMPLETE: NoMissingKeys<
  PlayerStatusRecord,
  typeof PLAYER_STATUS_FIELDS
> = true;

export const ARTIFACT_FIELDS: Readonly<Record<ArtifactName, readonly string[]>> = {
  tiers: TIER_FIELDS,
  arbitrage: ARBITRAGE_FIELDS,
  projections: PROJECTION_FIELDS,
  market_snapshot: MARKET_SNAPSHOT_FIELDS,
  player_status: PLAYER_STATUS_FIELDS,
};

export const ARTIFACT_FILENAMES: Readonly<Record<ArtifactName, string>> = {
  tiers: "tiers.json",
  arbitrage: "arbitrage.json",
  projections: "projections.json",
  market_snapshot: "market_snapshot.json",
  player_status: "player_status.json",
};

export const BUILD_METADATA_FILENAME = "build_metadata.json";
