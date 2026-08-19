/**
 * TypeScript mirrors of the public artifact contracts in `schemas/`.
 *
 * The JSON Schemas remain the source of truth (AGENTS.md section 18). These interfaces
 * exist so the app is type-checked against them, and the exported field lists below let a
 * test assert that the two descriptions still agree — a field renamed in Python must fail
 * the frontend build rather than surface as `undefined` in a table cell.
 */

/** Bumped together across `schemas/`, the serializers, the fixtures and this file. */
export const ARTIFACT_SCHEMA_VERSION = "1.0";

export type ScoringPreset = "STD" | "HALF" | "PPR";
export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DST";
export type ArbitrageMode = "baseline" | "ml";
export type Confidence = "high" | "medium" | "low" | "unknown";
export type SourceStatus = "pass" | "warning" | "failed" | "disabled";
export type ArtifactName = "tiers" | "arbitrage" | "projections" | "market_snapshot";

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
  readonly arbitrage_mode: ArbitrageMode;
  readonly arbitrage_score: number;
  /** Null in baseline mode. ADR-010 forbids claiming a model that was not trained. */
  readonly expected_surplus_vorp: number | null;
  readonly p_positive_surplus: number | null;
  readonly market_trend: number | null;
  readonly market_sample_size: number | null;
  /** Always null for MyFantasyLeague: the export publishes no standard deviation. */
  readonly market_adp_sd: number | null;
  readonly confidence: Confidence;
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
  readonly expected_games: number | null;
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

export interface BuildMetadata {
  readonly schema_version: string;
  readonly build_id: string;
  readonly generated_at_utc: string;
  readonly git_sha: string;
  readonly season: number;
  readonly intrinsic_model_version: string;
  readonly arbitrage_mode: ArbitrageMode;
  readonly arbitrage_model_version: string | null;
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
  "arbitrage_mode",
  "arbitrage_score",
  "expected_surplus_vorp",
  "p_positive_surplus",
  "market_trend",
  "market_sample_size",
  "market_adp_sd",
  "confidence",
  "quality_flags",
] as const satisfies readonly (keyof ArbitrageRecord)[];

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

export const ARTIFACT_FIELDS: Readonly<Record<ArtifactName, readonly string[]>> = {
  tiers: TIER_FIELDS,
  arbitrage: ARBITRAGE_FIELDS,
  projections: PROJECTION_FIELDS,
  market_snapshot: MARKET_SNAPSHOT_FIELDS,
};

export const ARTIFACT_FILENAMES: Readonly<Record<ArtifactName, string>> = {
  tiers: "tiers.json",
  arbitrage: "arbitrage.json",
  projections: "projections.json",
  market_snapshot: "market_snapshot.json",
};

export const BUILD_METADATA_FILENAME = "build_metadata.json";
