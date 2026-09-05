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

/**
 * Per-record contract versions. Phase 5 moved `arbitrage_record` to 1.1 (ADR-040); Phase 10
 * moves it to 1.2 (ADR-065), which is **additive** — every 1.1 field keeps its exact meaning
 * and its MyFantasyLeague provenance.
 */
export const RECORD_SCHEMA_VERSIONS = {
  tiers: "1.0",
  arbitrage: "1.2",
  market_trend_series: "1.0",
  projections: "1.0",
  market_snapshot: "1.0",
  player_status: "1.0",
  ros_tiers: "1.0",
  inseason_opportunity: "1.0",
} as const;

export type ScoringPreset = "STD" | "HALF" | "PPR";
export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DST";
export type ArbitrageMode = "baseline" | "ml";
export type Confidence = "high" | "medium" | "low" | "unknown";
export type SourceStatus = "pass" | "warning" | "failed" | "disabled";
export type ArtifactName =
  | "tiers"
  | "arbitrage"
  | "market_trend_series"
  | "projections"
  | "market_snapshot"
  | "player_status"
  | "ros_tiers"
  | "inseason_opportunity";

/** The four states `season_state_v1` derives from the NFL schedule and a timestamp. */
export type SeasonState =
  | "preseason_draft"
  | "regular_season"
  | "fantasy_postseason"
  | "season_complete";

/** The two product modes Release 2 ships. */
export type ProductMode = "draft" | "in_season";

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

/** What a market quote measures. An ADP is a price; an ECR is an opinion (ADR-062). */
export type MarketSignalType = "adp" | "ecr";

/** How a source aggregates the drafts behind a price (ADR-062). */
export type AggregationWindow =
  | "rolling"
  | "season_cumulative"
  | "not_applicable"
  | "unknown";

/** Why a player is publicly visible. Market membership decides visibility only (ADR-063). */
export type SurfaceReason =
  | "intrinsic_top_tier_depth"
  | "market_top300_ffc_adp"
  | "market_top300_fantasypros_adp"
  | "market_top300_fantasypros_ecr"
  | "market_top300_mfl_adp"
  | "current_roster_relevant"
  | "sleeper_trending_add"
  | "sleeper_trending_drop"
  | "current_depth_promotion";

/**
 * One ADP source's independent comparison against intrinsic fair rank.
 *
 * The populated fields differ by source and that is the information, not an inconsistency:
 * FFC fills `market_adp_sd` and leaves `league_size` null because its API ignores `teams`;
 * MyFantasyLeague fills `market_adp_low`/`high`, which are extreme order statistics rather
 * than a dispersion estimate, and leaves `market_adp_sd` null because it publishes none.
 */
export interface MarketComparison {
  readonly source_id: string;
  readonly market_signal_type: "adp";
  readonly market_adp: number;
  readonly market_rank: number | null;
  readonly rank_gap: number;
  readonly regional_value_gap: number;
  readonly market_sample_size: number | null;
  readonly market_adp_sd: number | null;
  readonly market_adp_low: number | null;
  readonly market_adp_high: number | null;
  /** Null when the source does not observe league size, or the cohort is approximate. */
  readonly league_size: number | null;
  readonly aggregation_window_type: AggregationWindow;
  readonly aggregation_window_days: number | null;
  readonly market_cohort_id: string;
  readonly market_cohort_detail: string;
  readonly market_snapshot_at_utc: string;
  readonly market_trend: number | null;
  readonly quality_flags: readonly string[];
}

/**
 * An expert consensus ranking. **Not a price.**
 *
 * Its gap is `ecr_gap`, never `rank_gap`, and it never appears in `markets` or in any
 * cross-market ADP field. A reader comparing the model to the experts is asking a different
 * question from one comparing the model to the market (roadmap 10.4).
 */
export interface ExpertConsensus {
  readonly source_id: string;
  readonly market_signal_type: "ecr";
  readonly ecr: number;
  readonly ecr_gap: number;
  readonly consensus_rank_mean?: number | null;
  readonly consensus_rank_min?: number | null;
  readonly consensus_rank_max?: number | null;
  readonly consensus_rank_sd?: number | null;
  readonly expert_count: number | null;
  readonly market_cohort_id: string;
  readonly market_snapshot_at_utc: string;
  readonly quality_flags: readonly string[];
}

/**
 * Where the ADP sources agree and disagree.
 *
 * `market_adp_median` is a convenience summary and **not** a canonical price: the sources
 * describe different populations over different windows, so the interesting number here is
 * `market_disagreement_range` — the thing a single-source board could not tell you.
 */
export interface CrossMarketSummary {
  readonly sources_available: readonly string[];
  readonly market_adp_min: number | null;
  readonly market_adp_max: number | null;
  readonly market_adp_median: number | null;
  readonly market_disagreement_range: number | null;
  /** The market where he costs the *latest* pick, i.e. the largest ADP. */
  readonly cheapest_market_source: string | null;
  readonly most_expensive_market_source: string | null;
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
  /**
   * Phase 10, additive. One entry per ADP source that priced this player.
   *
   * Optional in the type because a Release 1 artifact has no such field and the frontend
   * must render an older bundle rather than crash on it — the same reason the loader is
   * tolerant of a missing optional artifact.
   */
  readonly markets?: readonly MarketComparison[];
  readonly expert_consensus?: ExpertConsensus | null;
  readonly cross_market?: CrossMarketSummary | null;
  readonly surface_reasons?: readonly SurfaceReason[];
  /** True when market relevance surfaced him from beyond the tier depth: no tier, real rank. */
  readonly outside_tier_board?: boolean;
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

/**
 * Where the season is, carried on the draft build because that build always runs.
 *
 * The in-season bundle answers "is there a rest-of-season board"; this answers "should there
 * be one". They differ for the days between the season's first kickoff and its first
 * published week, and again once the horizon is spent — and in both windows the site shows
 * the draft board, so without this it would call itself Draft mode in November (ADR-079).
 *
 * Optional because a build older than ADR-079 has none, and a missing block means only that
 * the page cannot say more than which boards it holds.
 */
export interface BuildSeasonState {
  readonly rule_version: string;
  readonly state: SeasonState | null;
  readonly product_mode: ProductMode | null;
  readonly completed_week: number | null;
  readonly latest_snapshot_week: number | null;
  /** Whether a rest-of-season board should exist right now. Not "has the season started". */
  readonly ros_board_expected: boolean;
  readonly note: string;
}

export interface BuildMetadata {
  readonly season_state?: BuildSeasonState | null;
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
  "markets",
  "expert_consensus",
  "cross_market",
  "surface_reasons",
  "outside_tier_board",
] as const satisfies readonly (keyof ArbitrageRecord)[];

/**
 * One player's retained ADP history for one source (ADR-066).
 *
 * The points come from the append-only snapshot store by way of the build. **The browser
 * never calls a vendor for chart history** — that is the property this artifact exists to
 * make possible on a static site, and it is why the series is published rather than fetched.
 */
export interface MarketTrendSeriesRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly market_source_id: string;
  readonly scoring_preset: ScoringPreset;
  readonly league_preset_id: string;
  readonly player_id: string;
  readonly cohort_id: string;
  readonly window_days: number;
  /** The same slope the arbitrage row carries, over these same points. */
  readonly market_trend: number | null;
  readonly points: readonly { readonly observed_at: string; readonly market_adp: number }[];
}

export const MARKET_TREND_SERIES_FIELDS = [
  "schema_version",
  "build_id",
  "market_source_id",
  "scoring_preset",
  "league_preset_id",
  "player_id",
  "cohort_id",
  "window_days",
  "market_trend",
  "points",
] as const satisfies readonly (keyof MarketTrendSeriesRecord)[];

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


/**
 * One player's rest-of-season value at an explicit point-in-time cutoff.
 *
 * Every value-bearing field is named `ros_*` and **none of them is the preseason quantity of
 * the same shape**. A rest-of-season fair rank comes from a different model, over a
 * different horizon, against a different replacement baseline (the best player nobody
 * *rosters*, not the best nobody starts). The naming is the guard: a reader who sees
 * `fair_rank` is entitled to assume it is the draft one, so this record never uses the name.
 */
export interface RosTierRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  /** Weeks 1..through_week of this season are the only in-season evidence behind the row. */
  readonly through_week: number;
  readonly league_preset_id: string;
  readonly scoring_preset: ScoringPreset;
  readonly player_id: string;
  readonly display_name: string;
  readonly team: string | null;
  readonly position: Position;
  readonly ros_fair_rank: number;
  readonly ros_position_rank: number;
  /** Null for a surfaced player from beyond the tier depth: no tier, rather than a made-up one. */
  readonly ros_tier: number | null;
  readonly ros_tier_label: string | null;
  readonly ros_expected_vorp: number;
  readonly ros_vorp_p10: number;
  readonly ros_vorp_p25: number;
  readonly ros_vorp_p50: number;
  readonly ros_vorp_p75: number;
  readonly ros_vorp_p90: number;
  readonly ros_expected_points: number;
  readonly ros_points_p10: number;
  readonly ros_points_p50: number;
  readonly ros_points_p90: number;
  readonly ros_expected_games: number;
  readonly ros_uncertainty: number;
  readonly remaining_horizon_weeks?: number;
  readonly team_remaining_scheduled_games?: number | null;
  readonly preseason_fair_rank?: number | null;
  readonly fair_rank_change?: number | null;
  readonly games_played_to_date: number;
  readonly points_to_date: number;
  readonly points_per_game_to_date?: number | null;
  readonly weeks_since_last_game: number;
  readonly consecutive_weeks_missed: number;
  readonly has_played_this_season: boolean;
  /**
   * ADR-076. True when the player HAS played this season and has missed three or more
   * consecutive weeks ending at the cutoff. An observable fact about appearances: the model
   * uses no injury or practice-report information, so this is never a status, a designation
   * or medical knowledge, and it is never encoded by colour alone.
   */
  readonly long_absence: boolean;
  readonly in_preseason_universe: boolean;
  /** Annotation only. Never a model input, and always displayed apart from one. */
  readonly current_status: string | null;
  readonly outside_tier_board?: boolean;
  readonly surface_reasons?: readonly SurfaceReason[];
  readonly quality_flags: readonly string[];
}

/**
 * One row of the in-season Opportunity Board.
 *
 * The intrinsic columns are copied from `ros_tiers` verbatim; behaviour columns sit beside
 * them and never touch them. `add_count` is a number of transactions inside a declared
 * window — not an ADP, not a rank, and never differenced against `ros_fair_rank`.
 */
export interface OpportunityRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  readonly through_week: number;
  readonly league_preset_id: string;
  readonly scoring_preset: ScoringPreset;
  readonly player_id: string;
  readonly display_name: string;
  readonly team: string | null;
  readonly position: Position;
  readonly ros_fair_rank: number;
  readonly ros_position_rank: number;
  readonly ros_expected_vorp: number;
  readonly ros_expected_points: number | null;
  readonly ros_expected_games: number | null;
  readonly ros_uncertainty: number;
  readonly ros_tier: number | null;
  readonly behavior_source_id?: string | null;
  /** False when the optional feed was missing or stale. Intrinsic columns are unaffected. */
  readonly behavior_available: boolean;
  readonly behavior_snapshot_at_utc?: string | null;
  /** The window REQUESTED. Sleeper confirms no window of its own. */
  readonly behavior_lookback_hours?: number | null;
  readonly behavior_request_limit?: number | null;
  readonly add_count?: number | null;
  readonly drop_count?: number | null;
  readonly net_add_count?: number | null;
  readonly add_rank?: number | null;
  readonly drop_rank?: number | null;
  readonly long_absence: boolean;
  readonly weeks_since_last_game: number;
  readonly games_played_to_date?: number | null;
  readonly snap_share_last3?: number | null;
  readonly target_share_last3?: number | null;
  readonly current_status: string | null;
  readonly outside_tier_board: boolean;
  readonly surface_reasons: readonly SurfaceReason[];
  readonly quality_flags: readonly string[];
}

/** ADR-076's disclosure contract, carried on the artifact rather than written in the UI. */
export interface RosDisclosures {
  /** A constant `false`: a property of the model, not an observation about a build. */
  readonly uses_injury_information: false;
  readonly long_absence_definition: string;
  readonly long_absence_statement: string;
  readonly long_absence_ordering_weakness: string;
  readonly status_is_annotation_only: true;
  readonly long_absence_players: number;
  readonly tier_boundary_statement?: string;
}

export interface RosSeasonState {
  readonly rule_version: string;
  readonly season_state: SeasonState;
  readonly product_mode: ProductMode;
  readonly completed_week: number;
  readonly latest_snapshot_week?: number | null;
  readonly next_transition_utc?: string | null;
}

export interface RosBehaviorMetadata {
  readonly source_id: string | null;
  readonly available: boolean;
  readonly snapshot_at_utc: string | null;
  readonly lookback_hours: number | null;
  readonly request_limit: number | null;
  readonly add_rows?: number | null;
  readonly drop_rows?: number | null;
  readonly matched_players?: number | null;
  readonly age_hours?: number | null;
  readonly degraded_reason?: string | null;
  readonly signal_semantics?: string;
}

export interface RosBuildMetadata {
  readonly schema_version: string;
  readonly build_id: string;
  readonly generated_at_utc: string;
  readonly git_sha: string;
  readonly season: number;
  readonly through_week: number;
  readonly season_state: RosSeasonState;
  readonly ros_model_version: string;
  readonly ros_model_configuration_hash?: string | null;
  readonly production_fit_rule_version?: string | null;
  readonly model_fitted_at_utc?: string | null;
  readonly model_training_seasons?: readonly number[];
  readonly model_refit_reason?: string | null;
  readonly cutoff_rule_version: string;
  readonly feature_set_version?: string | null;
  readonly feature_set_hash?: string | null;
  readonly methodology_version: string;
  readonly simulation: {
    readonly draws: number;
    readonly draws_status?: string;
    readonly seed: number;
    readonly ranking_statistic?: string;
    readonly replacement_rule: "fresh_allocation" | "rostered_depth";
    readonly replacement_rule_description?: string;
    readonly tier_algorithm?: string;
    readonly tier_penalty?: number;
    readonly tier_depth?: number;
    readonly convergence_gate: "pass" | "fail";
    readonly tier_stability_gate: "pass" | "fail";
  };
  readonly source_freshness: {
    readonly rule_version: string;
    readonly available_through_week: number;
    readonly schedule_completed_week: number;
    readonly blocking_week?: number | null;
    readonly buildable?: boolean;
  };
  readonly behavior?: RosBehaviorMetadata | null;
  readonly surface?: Record<string, unknown> | null;
  readonly disclosures: RosDisclosures;
  readonly limitations: readonly string[];
  readonly supported_presets: readonly string[];
  readonly sources: readonly BuildSourceStatus[];
  readonly quality_gate: {
    readonly status: "pass" | "fail";
    readonly critical_failures: number;
    readonly warnings: number;
  };
  readonly warnings: readonly string[];
}

export const ROS_TIER_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "through_week",
  "league_preset_id",
  "scoring_preset",
  "player_id",
  "display_name",
  "team",
  "position",
  "ros_fair_rank",
  "ros_position_rank",
  "ros_tier",
  "ros_tier_label",
  "ros_expected_vorp",
  "ros_vorp_p10",
  "ros_vorp_p25",
  "ros_vorp_p50",
  "ros_vorp_p75",
  "ros_vorp_p90",
  "ros_expected_points",
  "ros_points_p10",
  "ros_points_p50",
  "ros_points_p90",
  "ros_expected_games",
  "ros_uncertainty",
  "remaining_horizon_weeks",
  "team_remaining_scheduled_games",
  "preseason_fair_rank",
  "fair_rank_change",
  "games_played_to_date",
  "points_to_date",
  "points_per_game_to_date",
  "weeks_since_last_game",
  "consecutive_weeks_missed",
  "has_played_this_season",
  "long_absence",
  "in_preseason_universe",
  "current_status",
  "outside_tier_board",
  "surface_reasons",
  "quality_flags",
] as const satisfies readonly (keyof RosTierRecord)[];

export const OPPORTUNITY_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "through_week",
  "league_preset_id",
  "scoring_preset",
  "player_id",
  "display_name",
  "team",
  "position",
  "ros_fair_rank",
  "ros_position_rank",
  "ros_expected_vorp",
  "ros_expected_points",
  "ros_expected_games",
  "ros_uncertainty",
  "ros_tier",
  "behavior_source_id",
  "behavior_available",
  "behavior_snapshot_at_utc",
  "behavior_lookback_hours",
  "behavior_request_limit",
  "add_count",
  "drop_count",
  "net_add_count",
  "add_rank",
  "drop_rank",
  "long_absence",
  "weeks_since_last_game",
  "games_played_to_date",
  "snap_share_last3",
  "target_share_last3",
  "current_status",
  "outside_tier_board",
  "surface_reasons",
  "quality_flags",
] as const satisfies readonly (keyof OpportunityRecord)[];

export const ROS_TIER_FIELDS_COMPLETE: NoMissingKeys<
  RosTierRecord,
  typeof ROS_TIER_FIELDS
> = true;
export const OPPORTUNITY_FIELDS_COMPLETE: NoMissingKeys<
  OpportunityRecord,
  typeof OPPORTUNITY_FIELDS
> = true;

export const ARTIFACT_FIELDS: Readonly<Record<ArtifactName, readonly string[]>> = {
  tiers: TIER_FIELDS,
  arbitrage: ARBITRAGE_FIELDS,
  market_trend_series: MARKET_TREND_SERIES_FIELDS,
  projections: PROJECTION_FIELDS,
  market_snapshot: MARKET_SNAPSHOT_FIELDS,
  player_status: PLAYER_STATUS_FIELDS,
  ros_tiers: ROS_TIER_FIELDS,
  inseason_opportunity: OPPORTUNITY_FIELDS,
};

export const ARTIFACT_FILENAMES: Readonly<Record<ArtifactName, string>> = {
  tiers: "tiers.json",
  arbitrage: "arbitrage.json",
  market_trend_series: "market_trend_series.json",
  projections: "projections.json",
  market_snapshot: "market_snapshot.json",
  player_status: "player_status.json",
  ros_tiers: "ros_tiers.json",
  inseason_opportunity: "inseason_opportunity.json",
};

export const BUILD_METADATA_FILENAME = "build_metadata.json";

/**
 * The in-season bundle's own metadata file.
 *
 * Separate from `build_metadata.json` because the two bundles are produced by different
 * models at different cutoffs on different cadences, carry different build ids, and are
 * validated independently. A site can hold a fresh draft board and a stale in-season one,
 * or either alone, and each says so for itself.
 */
export const ROS_BUILD_METADATA_FILENAME = "ros_build_metadata.json";
