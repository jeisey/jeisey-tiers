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
  // 1.1 (ADR-101): additive `availability_override`. 1.2 (ADR-102): additive employment.
  player_status: "1.2",
  ros_tiers: "1.0",
  // 1.1 (ADR-097): additive `ros_vorp_p50`, the statistic the rank orders by.
  // 1.2 (ADR-102): additive `employment_status` and `model_coverage`; an unprojected row's
  // ranks and values are null, and the bundle keeps such rows apart (`UnprojectedRecord`).
  inseason_opportunity: "1.2",
  player_headshots: "1.0",
  behavior_trend_series: "1.0",
  // 1.1 (ADR-103): additive optional `drive_breadth`.
  // 1.2 (ADR-104): `drive_breadth` v2 — `weeks` and `change`, QB metric `designed_runs`.
  player_usage: "1.2",
  team_matchups: "1.0",
  // 1.1 (ADR-099): additive `explanation`.
  weekly_projections: "1.1",
  weekly_context: "1.0",
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
  | "inseason_opportunity"
  | "player_headshots"
  | "behavior_trend_series"
  | "player_usage"
  | "team_matchups"
  | "weekly_projections"
  | "weekly_context";

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
  /**
   * Contract 1.1 (ADR-101): a reviewed entry recording reliable reporting that his season is
   * over, which neither feed can say. Absent on a 1.0 build, null when none is in force.
   * Evidence for the availability policy (`data/availability.ts`), never a model input.
   */
  readonly availability_override?: AvailabilityOverrideRecord | null;
  /**
   * Contract 1.2 (ADR-102), `employment_evidence_v1`: who employs him now. `unsigned` is a
   * verified free agent (shown as "FA"); `unknown` is never shown as FA. Absent on older
   * builds, null when the build computed no reading.
   */
  readonly employment_status?: EmploymentStatus | null;
  readonly employment_source?: "nflverse_roster" | "sleeper" | null;
  readonly employment_observed_at_utc?: string | null;
}

export type EmploymentStatus = "signed" | "unsigned" | "retired" | "unknown";

export interface AvailabilityOverrideRecord {
  readonly horizon: "season";
  readonly summary: string;
  readonly source_urls: readonly string[];
  readonly reviewed_at: string;
  readonly expires_at: string;
}

/**
 * Where one player's public portrait lives (ADR-087).
 *
 * Decoration, in the same sense that `PlayerStatusRecord` is annotation and for a stronger
 * reason: it carries no measurement of the player at all. Nothing here may be sorted on,
 * exported, or presented as a fact about how good he is.
 *
 * `image_url` is published rather than assembled here on purpose. The site makes no other
 * cross-origin request, so the one host a card may reach is a property the build validates
 * and this file reads — not a string a frontend could quietly change.
 */
export interface PlayerHeadshotRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly player_id: string;
  readonly provider: "espn";
  readonly provider_player_id: string;
  readonly image_url: string;
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
  readonly cutoff_rule_version?: string;
  /**
   * Set once the draft anchor binds: every market was read at or before this instant, the
   * board's own information cutoff, so the snapshot stops moving for the season (ADR-094).
   */
  readonly read_at_or_before_utc?: string | null;
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

/**
 * One player's retained add/drop history, from the append-only behaviour store (ADR-089).
 *
 * **Behaviour, never a price.** Every number here is a count of roster transactions inside a
 * declared lookback window. Nothing derived from it may become a draft position, a rank gap
 * or an input to any published value — the same rule the Opportunity Board is built on,
 * applied to the history instead of the day.
 *
 * Two fields carry the honesty of a short window and a consumer must use both.
 * `span_days` is what the reading was measured over: `behavior_trend_v1` states a direction
 * from as few as two observations, because an add count moves in hours, so a slope printed
 * without its span would read as a week. `snapshots_in_window` minus `observations` is how
 * many retained snapshots did not carry this player at all — days he was outside the feed's
 * top N, which is an unknown count and never a zero.
 *
 * Keyed by player alone, not by preset: the same transactions are observed however points
 * are scored.
 */
export interface BehaviorTrendSeriesRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  readonly through_week: number;
  readonly behavior_source_id: string;
  readonly player_id: string;
  /** The window every point was REQUESTED over; null when the captures disagree. */
  readonly lookback_hours?: number | null;
  /** The feed depth requested. It is what gives a day with no point a stated ceiling. */
  readonly request_limit?: number | null;
  readonly window_days: number;
  readonly snapshots_in_window: number;
  readonly observations: number;
  readonly observation_days: number;
  readonly span_days: number;
  /** Transactions per day. Positive means rising. Null below two observations. */
  readonly add_trend: number | null;
  readonly net_trend: number | null;
  readonly quality_flags?: readonly string[];
  readonly points: readonly {
    readonly observed_at: string;
    readonly add_count: number;
    readonly drop_count: number;
    readonly net_add_count: number;
  }[];
}

export const BEHAVIOR_TREND_SERIES_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "through_week",
  "behavior_source_id",
  "player_id",
  "lookback_hours",
  "request_limit",
  "window_days",
  "snapshots_in_window",
  "observations",
  "observation_days",
  "span_days",
  "add_trend",
  "net_trend",
  "quality_flags",
  "points",
] as const satisfies readonly (keyof BehaviorTrendSeriesRecord)[];

/** A value per scoring preset. Null where the rule withholds a reading for that preset. */
export interface ByPreset {
  readonly STD: number | null;
  readonly HALF: number | null;
  readonly PPR: number | null;
}

/** `played`: a stats row or an offensive snap. Every metric is null unless `played`. */
export type UsageWeekStatus = "played" | "bye" | "did_not_play";

export interface UsageWeek {
  readonly week: number;
  readonly status: UsageWeekStatus;
  readonly team: string | null;
  readonly opponent: string | null;
  readonly snap_share: number | null;
  readonly target_share: number | null;
  readonly carry_share: number | null;
  readonly air_yards_share: number | null;
  readonly targets: number | null;
  readonly carries: number | null;
  readonly pass_attempts: number | null;
  readonly fantasy_points: ByPreset | null;
}

/**
 * `role_change_v1`: the latest appearance against the average of every earlier one.
 *
 * `change` is exactly `latest - earlier` as published, so a surface prints it rather than
 * subtracting — the two numbers and their difference can never disagree on a card.
 */
export interface RoleChange {
  readonly latest_week: number;
  readonly latest: number;
  readonly earlier: number | null;
  readonly earlier_games: number;
  readonly change: number | null;
}

export type RoleMetric =
  | "snap_share"
  | "target_share"
  | "carry_share"
  | "air_yards_share"
  | "pass_attempts"
  | "carries";

/**
 * One player's observed role and production this season, week by week (ADR-091).
 *
 * **Observed facts, never a model output and never a model input.** Every number is
 * arithmetic over nflverse's weekly rows and snap counts through the cutoff. Nothing here is
 * from ffopportunity: whether an expected-points figure may be published is an open
 * CC-BY-SA question (ADR-086), so this contract deliberately carries none.
 */
export interface PlayerUsageRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  readonly through_week: number;
  readonly player_id: string;
  readonly display_name: string;
  readonly position: Position;
  /** The team `team_matchups.json` is read for. */
  readonly team: string | null;
  readonly usage_rule_version: string;
  readonly appearances: number;
  readonly weeks: readonly UsageWeek[];
  readonly role_changes: Readonly<Record<RoleMetric, RoleChange | null>>;
  readonly fantasy_points_to_date: ByPreset;
  /** Points from touchdowns over points to date. Null below 10 points. */
  readonly touchdown_points_share: ByPreset;
  readonly dropbacks: number;
  /** Null below 20 dropbacks. */
  readonly pass_epa_per_dropback: number | null;
  /**
   * Contract 1.2 (ADR-103, ADR-104): did his involvement recur across his team's drives or
   * cluster into a few, against a uniform allocation of the same count. Descriptive; no model
   * reads it. Absent on a 1.0 build, null when play-by-play was unavailable.
   */
  readonly drive_breadth?: DriveBreadth | null;
}

export type DriveBreadthMetric = "designed_runs" | "backfield" | "targets" | "open_field_targets";

/** One played game of the drive rail (ADR-104). */
export interface DriveBreadthWeek {
  readonly week: number;
  readonly eligible_drives: number;
  readonly reached_drives: number;
  /** reached / eligible drives; null with no eligible drive. */
  readonly drive_share: number | null;
  /** The share the same count would reach placed at random among the game's slots. */
  readonly expected_share: number | null;
}

export interface DriveBreadth {
  readonly method_version: string;
  readonly metric: DriveBreadthMetric;
  /** The window rule: his latest this-many completed appearances. */
  readonly window_rule: number;
  readonly appearances: number;
  readonly first_week: number | null;
  readonly last_week: number | null;
  readonly eligible_drives: number;
  readonly reached_drives: number;
  /** Drives a uniform allocation of his opportunities among the slots would reach. */
  readonly expected_drives: number;
  readonly opportunities: number;
  /** 100 × (reached − expected) / eligible drives; null with no eligible drive. */
  readonly breadth_gap_pp: number | null;
  /** Clears the provisional display minimums. A display rule, not reliability. */
  readonly displayable: boolean;
  readonly withheld_reason:
    | "too_few_appearances"
    | "too_few_eligible_drives"
    | "too_few_opportunities"
    | null;
  /**
   * Whether the card compares him with the random allocation — the notch and the four-game
   * line. False at QB: the designed-run variant failed the publication rule (ADR-104).
   */
  readonly compares_with_random: boolean;
  /** Every played game with play-by-play, in week order (ADR-104). */
  readonly weeks: readonly DriveBreadthWeek[];
  /** `role_change_v1` on the drive share, pooled; null when the latest game has none. */
  readonly change: RoleChange | null;
}

/** Each position's displayed quartiles on this build: what "typical" is (ADR-103). */
export interface DriveBreadthReference {
  readonly players: number;
  readonly p25: number;
  readonly p50: number;
  readonly p75: number;
}

/**
 * The fields of an Opportunity Board row a player card's cohort strips read from every row of
 * the block: the served `inseason_opportunity_cohort` family (ADR-098).
 */
export type OpportunityCohortRecord = Pick<
  OpportunityRecord,
  | "league_preset_id"
  | "scoring_preset"
  | "player_id"
  | "position"
  | "add_count"
  | "drop_count"
  | "snap_share_last3"
  | "target_share_last3"
>;

/**
 * The fields of a usage record a player card's cohort strip reads from every player: the
 * served `player_usage_cohort` family (ADR-098), so a card opened from the ROS board need not
 * download every player's weekly series to place one player among them.
 */
export type UsageCohortRecord = Pick<
  PlayerUsageRecord,
  "player_id" | "position" | "touchdown_points_share" | "pass_epa_per_dropback"
>;

export const PLAYER_USAGE_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "through_week",
  "player_id",
  "display_name",
  "position",
  "team",
  "usage_rule_version",
  "appearances",
  "weeks",
  "role_changes",
  "fantasy_points_to_date",
  "touchdown_points_share",
  "dropbacks",
  "pass_epa_per_dropback",
  "drive_breadth",
] as const satisfies readonly (keyof PlayerUsageRecord)[];

/**
 * One team's next unplayed game (ADR-091). **Published context only.**
 *
 * The sportsbook fields are a market quantity AGENTS.md section 8 forbids as a model input.
 * They are printed beside a player and move no projection, VORP, rank, tier or pick. The
 * spread has already been re-expressed from this team's side — positive means favoured — so
 * nothing downstream handles nflverse's home-oriented convention.
 */
export interface TeamMatchupRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  readonly through_week: number;
  readonly team: string;
  readonly matchup_rule_version: string;
  readonly game_id: string;
  readonly week: number;
  readonly kickoff_utc: string;
  readonly opponent: string;
  readonly home_away: "home" | "away";
  readonly neutral_site: boolean;
  readonly team_rest_days: number | null;
  readonly opponent_rest_days: number | null;
  readonly roof: string | null;
  readonly total_line: number | null;
  readonly team_expected_margin: number | null;
  readonly implied_team_points: number | null;
  readonly implied_opponent_points: number | null;
  readonly upcoming_bye_weeks: readonly number[];
  readonly lines_source_id: string | null;
  readonly lines_retrieved_at_utc: string | null;
}

export const TEAM_MATCHUP_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "through_week",
  "team",
  "matchup_rule_version",
  "game_id",
  "week",
  "kickoff_utc",
  "opponent",
  "home_away",
  "neutral_site",
  "team_rest_days",
  "opponent_rest_days",
  "roof",
  "total_line",
  "team_expected_margin",
  "implied_team_points",
  "implied_opponent_points",
  "upcoming_bye_weeks",
  "lines_source_id",
  "lines_retrieved_at_utc",
] as const satisfies readonly (keyof TeamMatchupRecord)[];

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
  "availability_override",
  "employment_status",
  "employment_source",
  "employment_observed_at_utc",
] as const satisfies readonly (keyof PlayerStatusRecord)[];

export const PLAYER_HEADSHOT_FIELDS = [
  "schema_version",
  "build_id",
  "player_id",
  "provider",
  "provider_player_id",
  "image_url",
] as const satisfies readonly (keyof PlayerHeadshotRecord)[];

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
export const PLAYER_HEADSHOT_FIELDS_COMPLETE: NoMissingKeys<
  PlayerHeadshotRecord,
  typeof PLAYER_HEADSHOT_FIELDS
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
  /**
   * Median simulated remaining VORP — the statistic `ros_fair_rank` orders by and the number
   * the rest-of-season board draws (ADR-097). Optional only so a 1.0 artifact still loads;
   * every 1.1 build publishes it.
   */
  readonly ros_vorp_p50?: number | null;
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
  /** Contract 1.2 (ADR-102): the employment reading, also on `player_status`. */
  readonly employment_status?: EmploymentStatus | null;
  /** Contract 1.2: always `projected` here — unprojected rows are `UnprojectedRecord`s. */
  readonly model_coverage?: "projected" | "unprojected";
}

/**
 * An Opportunity row for a verified off-roster player with no validated model output
 * (contract 1.2, ADR-102): unsigned, or signed only on Sleeper evidence, and added widely
 * enough to clear the surface rule. Identity, club, employment and behaviour; every ROS
 * number null, never zero. The bundle keeps these apart from `OpportunityRecord`, so no
 * ranking, chart or filter that orders by value can meet one.
 */
export type UnprojectedRecord = Omit<
  OpportunityRecord,
  | "ros_fair_rank"
  | "ros_position_rank"
  | "ros_expected_vorp"
  | "ros_vorp_p50"
  | "ros_expected_points"
  | "ros_expected_games"
  | "ros_uncertainty"
  | "ros_tier"
  | "model_coverage"
> & {
  readonly ros_fair_rank: null;
  readonly ros_position_rank: null;
  readonly ros_expected_vorp: null;
  readonly ros_vorp_p50?: null;
  readonly ros_expected_points: null;
  readonly ros_expected_games: null;
  readonly ros_uncertainty: null;
  readonly ros_tier: null;
  readonly model_coverage: "unprojected";
};

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

/** The signal layer's own account of itself (ADR-091), carried on `ros_build_metadata`. */
export interface RosSignalMetadata {
  readonly usage_rule: {
    readonly version: string;
    readonly change_rule_version: string;
    readonly min_earlier_games: number;
    readonly min_touchdown_share_points: number;
    readonly min_epa_dropbacks: number;
  };
  readonly usage_records: number;
  readonly matchup_rule_version: string;
  readonly matchup_records: number;
  readonly lines_source_id: string | null;
  readonly lines_retrieved_at_utc: string | null;
  readonly lines_posted_teams: number;
  /** Printed wherever a line is shown. */
  readonly sportsbook_context_statement: string;
  /** Why no expected-points reading is published. */
  readonly expected_points_statement: string;
  /** ADR-103: the drive-breadth layer's status, minimums and positional references. */
  readonly drive_breadth?: {
    readonly method_version: string;
    readonly status: "published" | "unavailable";
    readonly statement: string;
    readonly window_appearances?: number;
    readonly display_minimums?: {
      readonly appearances: number;
      readonly eligible_drives: number;
      readonly opportunities: number;
    };
    readonly position_reference?: Partial<Record<Position, DriveBreadthReference | null>> | null;
  } | null;
}

/** The seven published levels, as record keys. */
export const WEEKLY_QUANTILE_KEYS = ["q05", "q10", "q25", "q50", "q75", "q90", "q95"] as const;
export type WeeklyQuantileKey = (typeof WEEKLY_QUANTILE_KEYS)[number];

/** The feature families a driver account groups by, in the order the page draws them. */
export const WEEKLY_DRIVER_FAMILIES = [
  "form",
  "role",
  "availability",
  "offense",
  "game",
  "opponent",
  "prior",
] as const;
export type WeeklyDriverFamily = (typeof WEEKLY_DRIVER_FAMILIES)[number];

/**
 * `lines_pending`: the game exists but its sportsbook total or spread is not posted. The model
 * never trained without them, so the build publishes the game and no distribution (ADR-096).
 */
export type WeeklyGameState = "upcoming" | "kicked_off" | "bye" | "lines_pending";

/** The game-specific input groups a typical-week account splits a difference into (ADR-099). */
export const WEEKLY_EXPLANATION_GROUPS = ["lines", "home", "rest", "roof", "opponent"] as const;
export type WeeklyExplanationGroup = (typeof WEEKLY_EXPLANATION_GROUPS)[number];

/** The levels explained: floor, median, ceiling. */
export const WEEKLY_EXPLAINED_LEVELS = ["q10", "q50", "q90"] as const;
export type WeeklyExplainedLevel = (typeof WEEKLY_EXPLAINED_LEVELS)[number];

/**
 * One quantile against his typical week (`typical_week_shapley_v1`):
 * `typical + Σ terms + calibration + rearrangement` is the published quantile, exactly.
 */
export interface WeeklyAccount {
  readonly typical: number;
  readonly terms: Readonly<Record<WeeklyExplanationGroup, number>>;
  /** Always 0: the conformal shift is in both readings. */
  readonly calibration: number;
  readonly rearrangement: number;
}

/** One player's next game as a distribution (`weekly-startsit-v1`, ADR-096). */
export interface WeeklyProjectionRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  readonly through_week: number;
  readonly target_week: number;
  readonly player_id: string;
  readonly display_name: string;
  readonly position: Position;
  readonly team: string;
  readonly scoring_preset: ScoringPreset;
  readonly model_version: string;
  readonly game_state: WeeklyGameState;
  readonly game: {
    readonly game_id: string;
    readonly opponent: string;
    readonly home_away: "home" | "away";
    readonly neutral_site: boolean;
    readonly kickoff_utc: string | null;
    readonly roof: string | null;
    readonly total_line: number | null;
    readonly team_margin: number | null;
    readonly team_points: number | null;
  } | null;
  readonly quantiles: Readonly<Record<WeeklyQuantileKey, number>> | null;
  /** Ten parts that sum to `quantiles.q50`. */
  readonly drivers:
    | (Readonly<Record<WeeklyDriverFamily, number>> & {
        readonly baseline: number;
        readonly calibration: number;
        readonly rearrangement: number;
      })
    | null;
  /** Why this week differs from his typical week, at P10, P50 and P90 (contract 1.1, ADR-099). */
  readonly explanation: Readonly<Record<WeeklyExplainedLevel, WeeklyAccount>> | null;
  readonly opponent: {
    readonly defense: string;
    readonly allowed_ppg: number | null;
    readonly league_ppg: number | null;
    readonly index: number | null;
    readonly rank: number | null;
    readonly defenses: number | null;
    readonly games: number | null;
  } | null;
  readonly injury: {
    readonly week: number;
    readonly designation: "Out" | "Doubtful" | "Questionable" | null;
    readonly practice_status: string | null;
    readonly primary_injury: string | null;
  } | null;
}

export const WEEKLY_PROJECTION_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "through_week",
  "target_week",
  "player_id",
  "display_name",
  "position",
  "team",
  "scoring_preset",
  "model_version",
  "game_state",
  "game",
  "quantiles",
  "drivers",
  "explanation",
  "opponent",
  "injury",
] as const satisfies readonly (keyof WeeklyProjectionRecord)[];

export type WeatherStatus =
  | "ok"
  | "roof_unknown"
  | "indoors"
  | "unavailable"
  | "stale"
  | "out_of_range"
  | "implausible"
  | "no_venue";

/** A listed player on a team's report: a lagged starter or a notable skill player. */
export interface ListedPlayer {
  readonly player_id: string;
  readonly name: string | null;
  readonly position: string | null;
  readonly role: string;
  readonly group: "OL" | "QB" | "CB" | "S" | "DL" | "SKILL";
  readonly starter_rank: number | null;
  readonly snap_share: number | null;
  readonly target_share: number | null;
  readonly carry_share: number | null;
  readonly designation: "Out" | "Doubtful" | "Questionable";
  readonly practice_status: string | null;
  readonly primary_injury: string | null;
}

/** One team's target-week game as published facts (`weekly_gameday_context_v1`, ADR-099). */
export interface WeeklyGameContextRecord {
  readonly schema_version: string;
  readonly build_id: string;
  readonly season: number;
  readonly through_week: number;
  readonly target_week: number;
  readonly team: string;
  readonly game_id: string;
  readonly opponent: string;
  readonly home_away: "home" | "away";
  readonly neutral_site: boolean;
  readonly kickoff_utc: string | null;
  readonly context_rule_version: string;
  readonly venue: {
    readonly venue_id: string;
    readonly name: string;
    readonly country: string;
    readonly roof_type: "open" | "retractable" | "dome" | "unverified";
    readonly latitude: number;
    readonly longitude: number;
  } | null;
  readonly roof: {
    readonly recorded: string | null;
    readonly model_indoors: number | null;
    readonly assumed_from_last_home_game: boolean;
  };
  readonly weather: {
    readonly status: WeatherStatus;
    readonly provider: "nws" | "open_meteo" | null;
    readonly wind_mph: number | null;
    readonly gust_mph: number | null;
    readonly temp_f: number | null;
    readonly precip_probability: number | null;
    readonly precip_in: number | null;
    readonly short_forecast: string | null;
    readonly valid_from_utc: string | null;
    readonly valid_to_utc: string | null;
    readonly provider_updated_utc: string | null;
    readonly retrieved_at_utc: string | null;
  };
  readonly lineup: {
    readonly report_available: boolean;
    readonly report_final: boolean;
    readonly listed: readonly ListedPlayer[];
  };
  readonly typical: {
    readonly games: number;
    readonly total_line: number | null;
    readonly team_margin: number | null;
    readonly team_points: number | null;
    readonly home_share: number;
    readonly indoors_share: number | null;
  };
  readonly this_week: {
    readonly total_line: number | null;
    readonly team_margin: number | null;
    readonly team_points: number | null;
    readonly is_home: number | null;
    readonly rest_advantage: number | null;
    readonly indoors: number | null;
  };
}

export interface WeeklyCalibrationRow {
  readonly low: number;
  readonly high: number;
  readonly pairs: number;
  readonly predicted: number;
  readonly observed: number;
}

/** What the build says about the weekly layer, and every measured number the tab prints. */
export interface RosWeeklyMetadata {
  readonly model_version: string;
  readonly candidate_version: string;
  readonly configuration_hash: string;
  readonly training_seasons: readonly number[];
  readonly fitted_at_utc: string | null;
  readonly through_week: number;
  readonly target_week: number;
  readonly records: number;
  readonly upcoming: number;
  readonly kicked_off: number;
  readonly bye: number;
  readonly lines_pending: number;
  readonly quantile_levels: readonly number[];
  readonly distribution_rule: {
    readonly version: string;
    readonly tail_lower_factor: number;
    readonly tail_upper_factor: number;
    readonly grid_points: number;
  };
  readonly families: Readonly<Record<string, string>>;
  readonly margin: Readonly<
    Record<
      string,
      {
        readonly position_variance: Readonly<Record<string, number>>;
        readonly lineup_variance: number;
        readonly margin_sd_by_slot: Readonly<Record<string, number>>;
        readonly starter_rows: number;
      }
    >
  >;
  readonly correlation: {
    readonly method?: string;
    readonly pairs?: Readonly<
      Record<string, { readonly pairs: number; readonly spearman: number; readonly rho: number }>
    >;
  };
  /** league preset -> scoring preset -> position -> points of the last starter. */
  readonly startable: Readonly<
    Record<string, Readonly<Record<string, Readonly<Record<string, number | null>>>>>
  >;
  readonly injury_base_rates: Readonly<
    Record<
      string,
      | { readonly reports: number; readonly appeared: number; readonly appearance_rate: number | null }
      | { readonly version: string; readonly seasons: readonly number[]; readonly definition: string }
    >
  >;
  readonly evaluation: {
    readonly development_verdict?: boolean;
    readonly holdout_verdict?: boolean;
    readonly holdout_season?: number;
    readonly holdout_pairs?: number;
    readonly holdout_pair_accuracy?: number;
    readonly holdout_pair_brier?: number;
    readonly holdout_coverage_80?: number;
    readonly holdout_coverage_50?: number;
    readonly best_baseline_pair_accuracy?: number;
    readonly calibration?: readonly WeeklyCalibrationRow[];
  };
  readonly injuries_retrieved_at_utc: string | null;
  readonly statement: string;
  /** How every record's `explanation` was made (ADR-099); absent on an older build. */
  readonly explanation?: {
    readonly rule: string;
    readonly levels: readonly string[];
    readonly groups: Readonly<Record<string, string>>;
    readonly reference_shrink_games: number;
    readonly reference: string;
    readonly statement: string;
  } | null;
  /** What weekly_context.json was built from (ADR-099). */
  readonly context?: Readonly<Record<string, unknown>> | null;
  /** The private weekly-startsit-v2 shadow record's summary; its rows are never published. */
  readonly shadow?: {
    readonly model_version: "weekly-startsit-v2";
    readonly status: "absent" | "shadow" | "failed";
    readonly rows: number;
    readonly pregame?: number;
    readonly with_v2?: number;
    readonly configuration_hash?: string | null;
  } | null;
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
  readonly signals?: RosSignalMetadata | null;
  /** The weekly start/sit layer (ADR-096). Absent or null removes the Start/Sit tab's content. */
  readonly weekly?: RosWeeklyMetadata | null;
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
  "ros_vorp_p50",
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
  "employment_status",
  "model_coverage",
] as const satisfies readonly (keyof OpportunityRecord)[];

export const ROS_TIER_FIELDS_COMPLETE: NoMissingKeys<
  RosTierRecord,
  typeof ROS_TIER_FIELDS
> = true;
export const OPPORTUNITY_FIELDS_COMPLETE: NoMissingKeys<
  OpportunityRecord,
  typeof OPPORTUNITY_FIELDS
> = true;
export const PLAYER_USAGE_FIELDS_COMPLETE: NoMissingKeys<
  PlayerUsageRecord,
  typeof PLAYER_USAGE_FIELDS
> = true;
export const TEAM_MATCHUP_FIELDS_COMPLETE: NoMissingKeys<
  TeamMatchupRecord,
  typeof TEAM_MATCHUP_FIELDS
> = true;
export const WEEKLY_PROJECTION_FIELDS_COMPLETE: NoMissingKeys<
  WeeklyProjectionRecord,
  typeof WEEKLY_PROJECTION_FIELDS
> = true;

export const WEEKLY_CONTEXT_FIELDS = [
  "schema_version",
  "build_id",
  "season",
  "through_week",
  "target_week",
  "team",
  "game_id",
  "opponent",
  "home_away",
  "neutral_site",
  "kickoff_utc",
  "context_rule_version",
  "venue",
  "roof",
  "weather",
  "lineup",
  "typical",
  "this_week",
] as const satisfies readonly (keyof WeeklyGameContextRecord)[];
export const WEEKLY_CONTEXT_FIELDS_COMPLETE: NoMissingKeys<
  WeeklyGameContextRecord,
  typeof WEEKLY_CONTEXT_FIELDS
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
  player_headshots: PLAYER_HEADSHOT_FIELDS,
  behavior_trend_series: BEHAVIOR_TREND_SERIES_FIELDS,
  player_usage: PLAYER_USAGE_FIELDS,
  team_matchups: TEAM_MATCHUP_FIELDS,
  weekly_projections: WEEKLY_PROJECTION_FIELDS,
  weekly_context: WEEKLY_CONTEXT_FIELDS,
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
  player_headshots: "player_headshots.json",
  behavior_trend_series: "behavior_trend_series.json",
  player_usage: "player_usage.json",
  team_matchups: "team_matchups.json",
  weekly_projections: "weekly_projections.json",
  weekly_context: "weekly_context.json",
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
