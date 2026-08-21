/**
 * Deterministic artifact fixtures for the frontend tests.
 *
 * Separate from `web/public/data/`, which is the real generated build and changes every time
 * it is regenerated. These are fixed, tiny, and constructed to carry the cases the UI has to
 * get right rather than a sample of a real board:
 *
 * | player          | case                                                        |
 * |-----------------|-------------------------------------------------------------|
 * | Bijan Robinson  | top of board, priced, bargain, no injury designation          |
 * | Amon-Ra Bright  | priced bargain, `Questionable` with a body part and a note    |
 * | Joe Burrow      | priced premium, quarterback compression                       |
 * | Zach Ertz       | on the tier board, **no market price** at all                 |
 * | Deebo Gray      | priced, **no player-status record at all**                    |
 * | Kyle Pitts Sr.  | generational suffix, so the short-name path is exercised      |
 * | James Cook III  | the other suffix form, which must not shorten to "III"         |
 *
 * Every arbitrage row carries `low` confidence and a null trend, which mirrors the launch
 * condition the UI has to explain rather than hide.
 */

import type {
  ArbitrageRecord,
  ArtifactEnvelope,
  BuildMetadata,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  Position,
  ScoringPreset,
  TierRecord,
} from "../../src/data/contracts";

export const FIXTURE_BUILD_ID = "fixture-20260821T120000Z";
export const FIXTURE_GENERATED_AT = "2026-08-21T14:38:00Z";
export const FIXTURE_SNAPSHOT_AT = "2026-08-20T14:38:44Z";

interface Seed {
  readonly id: string;
  readonly name: string;
  readonly position: Position;
  readonly team: string;
  /** Median simulated VORP at PPR/12; other presets scale deterministically from it. */
  readonly p50: number;
  /** Null means the player carries no market price at all. */
  readonly adp: number | null;
  readonly sample: number | null;
}

const SEEDS: readonly Seed[] = [
  { id: "gsis:00-0000001", name: "Bijan Robinson", position: "RB", team: "ATL", p50: 135.4, adp: 2.6, sample: 125 },
  { id: "gsis:00-0000002", name: "Amon-Ra Bright", position: "WR", team: "DET", p50: 133.6, adp: 10.5, sample: 126 },
  { id: "gsis:00-0000003", name: "Ja'Marr Swift", position: "WR", team: "CIN", p50: 130.9, adp: 4.1, sample: 124 },
  { id: "gsis:00-0000011", name: "Jahmyr Cook", position: "RB", team: "DET", p50: 124.2, adp: 6.8, sample: 123 },
  { id: "gsis:00-0000012", name: "Puka Nightingale", position: "WR", team: "LAR", p50: 118.7, adp: 21.4, sample: 120 },
  { id: "gsis:00-0000013", name: "James Cook III", position: "RB", team: "BUF", p50: 101.2, adp: 33.7, sample: 117 },
  { id: "gsis:00-0000004", name: "Kyle Pitts Sr.", position: "TE", team: "ATL", p50: 74.2, adp: 96.4, sample: 88 },
  { id: "gsis:00-0000005", name: "Trey McBride", position: "TE", team: "ARI", p50: 71.0, adp: 40.2, sample: 118 },
  { id: "gsis:00-0000014", name: "Derrick Hampton", position: "RB", team: "BAL", p50: 66.5, adp: 58.9, sample: 111 },
  { id: "gsis:00-0000015", name: "Zay Meadows", position: "WR", team: "BAL", p50: 61.8, adp: 47.3, sample: 114 },
  { id: "gsis:00-0000006", name: "Deebo Gray", position: "WR", team: "SF", p50: 55.3, adp: 61.5, sample: 22 },
  { id: "gsis:00-0000016", name: "Omarion Vance", position: "RB", team: "LAC", p50: 48.9, adp: 72.6, sample: 104 },
  { id: "gsis:00-0000007", name: "Zach Ertz", position: "TE", team: "WAS", p50: 40.8, adp: null, sample: null },
  { id: "gsis:00-0000017", name: "Rashee Kirk", position: "WR", team: "KC", p50: 37.4, adp: 84.1, sample: 97 },
  { id: "gsis:00-0000008", name: "Josh Allen", position: "QB", team: "BUF", p50: 33.1, adp: 4.0, sample: 121 },
  { id: "gsis:00-0000018", name: "Jalen Marsh", position: "QB", team: "PHI", p50: 12.6, adp: 31.8, sample: 119 },
  { id: "gsis:00-0000009", name: "Joe Burrow", position: "QB", team: "CIN", p50: -18.4, adp: 3.2, sample: 125 },
  { id: "gsis:00-0000010", name: "Jaylin Lane", position: "WR", team: "WAS", p50: -32.7, adp: 188.2, sample: 41 },
];

const SCORING: readonly ScoringPreset[] = ["STD", "HALF", "PPR"];
const LEAGUES: readonly { id: string; teams: number }[] = [
  { id: "redraft-10", teams: 10 },
  { id: "redraft-12", teams: 12 },
  { id: "redraft-14", teams: 14 },
];

/** Scoring shifts value a little; league size shifts it a little more. Pure and repeatable. */
function scale(p50: number, scoring: ScoringPreset, teams: number): number {
  const scoringFactor = scoring === "PPR" ? 1 : scoring === "HALF" ? 0.94 : 0.88;
  const leagueFactor = teams === 12 ? 1 : teams === 10 ? 0.92 : 1.07;
  return Number((p50 * scoringFactor * leagueFactor).toFixed(4));
}

function round(value: number): number {
  return Number(value.toFixed(4));
}

/**
 * Tier assignment: three contiguous groups over the fixture board.
 *
 * Contiguous in fair-rank order, which is the artifact contract the UI relies on when it
 * groups rows into lanes (`docs/DATA_CONTRACTS.md` section 8).
 */
function tierOf(fairRank: number): { ordinal: number; label: string } {
  if (fairRank <= 3) return { ordinal: 0, label: "S" };
  if (fairRank <= 8) return { ordinal: 1, label: "A" };
  return { ordinal: 2, label: "B" };
}

export function tierRecords(): TierRecord[] {
  const records: TierRecord[] = [];
  for (const league of LEAGUES) {
    for (const scoring of SCORING) {
      const ranked = [...SEEDS]
        .map((seed) => ({ seed, p50: scale(seed.p50, scoring, league.teams) }))
        .sort((a, b) => b.p50 - a.p50);
      const positionCounts = new Map<Position, number>();
      ranked.forEach(({ seed, p50 }, index) => {
        const fairRank = index + 1;
        const tier = tierOf(fairRank);
        const positionRank = (positionCounts.get(seed.position) ?? 0) + 1;
        positionCounts.set(seed.position, positionRank);
        records.push({
          schema_version: "1.0",
          build_id: FIXTURE_BUILD_ID,
          league_preset_id: league.id,
          scoring_preset: scoring,
          player_id: seed.id,
          display_name: seed.name,
          team: seed.team,
          position: seed.position,
          fair_rank: fairRank,
          position_rank: positionRank,
          tier_ordinal: tier.ordinal,
          tier_label: tier.label,
          expected_vorp: round(p50 * 0.93),
          p10_vorp: round(p50 - 78.2),
          p25_vorp: round(p50 - 41.6),
          p50_vorp: p50,
          p75_vorp: round(p50 + 52.4),
          p90_vorp: round(p50 + 96.1),
          expected_points: round(120 + p50 * 0.8),
          uncertainty: round(94.6 + index),
          quality_flags: seed.name === "Jaylin Lane" ? ["rookie", "no_prior_season_stats"] : [],
        });
      });
    }
  }
  return records;
}

export function arbitrageRecords(): ArbitrageRecord[] {
  const tiers = tierRecords();
  const records: ArbitrageRecord[] = [];
  for (const league of LEAGUES) {
    for (const scoring of SCORING) {
      const block = tiers.filter(
        (tier) => tier.league_preset_id === league.id && tier.scoring_preset === scoring,
      );
      const priced = block
        .map((tier) => ({ tier, seed: SEEDS.find((seed) => seed.id === tier.player_id) }))
        .filter(
          (entry): entry is { tier: TierRecord; seed: Seed } =>
            entry.seed !== undefined && entry.seed.adp !== null,
        );
      // `arbitrage_score` is a within-preset midpoint percentile of the regional gap, so it is
      // derived here the same way the build derives it rather than invented per row.
      const gaps = priced.map(({ tier, seed }) => ({
        tier,
        seed,
        regional: Math.log((seed.adp ?? 1) / tier.fair_rank),
      }));
      const sorted = [...gaps].sort((a, b) => a.regional - b.regional);
      for (const entry of gaps) {
        const rank = sorted.findIndex((candidate) => candidate.tier.player_id === entry.tier.player_id);
        const score = Number((((rank + 0.5) / sorted.length) * 100).toFixed(2));
        const adp = entry.seed.adp ?? 0;
        const flags = ["cohort_approximate", "cohort_insufficient", "insufficient_trend_history"];
        if ((entry.seed.sample ?? 0) < 30) flags.push("low_market_sample");
        if (adp > 50) flags.push("wide_market_range");
        records.push({
          schema_version: "1.1",
          build_id: FIXTURE_BUILD_ID,
          league_preset_id: league.id,
          scoring_preset: scoring,
          player_id: entry.tier.player_id,
          display_name: entry.tier.display_name,
          team: entry.tier.team,
          position: entry.tier.position,
          fair_rank: entry.tier.fair_rank,
          market_adp: adp,
          market_rank: Math.max(1, Math.round(adp / 2)),
          rank_gap: round(adp - entry.tier.fair_rank),
          regional_value_gap: round(entry.regional),
          arbitrage_mode: "baseline",
          arbitrage_score: score,
          expected_surplus_vorp: null,
          p_positive_surplus: null,
          market_trend: null,
          market_sample_size: entry.seed.sample,
          market_adp_sd: null,
          market_adp_low: round(Math.max(1, adp - 18)),
          market_adp_high: round(adp + 44),
          market_source_id: "myfantasyleague_adp",
          market_cohort_id: "no-mock-no-keeper",
          market_cohort_detail: "IS_KEEPER=N&IS_MOCK=0 (approximate cohort)",
          market_snapshot_at_utc: FIXTURE_SNAPSHOT_AT,
          confidence: "low",
          quality_flags: flags.sort(),
        });
      }
    }
  }
  return records;
}

export function playerStatusRecords(): PlayerStatusRecord[] {
  const base = {
    schema_version: "1.0",
    build_id: FIXTURE_BUILD_ID,
    season: 2026,
    injury_start_date: null,
    practice_participation: null,
    practice_description: null,
    observed_at_utc: "2026-08-20T14:39:19Z",
    source_ids: ["nflreadpy", "sleeper"] as readonly string[],
    quality_flags: [] as readonly string[],
  };
  return SEEDS
    // Deebo Gray deliberately has no status record: the UI must show his numbers and simply
    // omit the annotation, never invent one.
    .filter((seed) => seed.name !== "Deebo Gray")
    .map((seed) => {
      const injured = seed.name === "Amon-Ra Bright";
      const out = seed.name === "Jaylin Lane";
      return {
        ...base,
        player_id: seed.id,
        display_name: seed.name,
        current_team: seed.team,
        position: seed.position,
        roster_status: out ? "RES" : "ACT",
        roster_depth_chart_position: seed.position,
        sleeper_status: out ? "Injured Reserve" : "Active",
        injury_status: injured ? "Questionable" : out ? "IR" : null,
        injury_body_part: injured ? "Hamstring" : null,
        injury_notes: injured ? "Limited in Wednesday's session; expected to test it Friday." : null,
        depth_chart_position: seed.position,
        depth_chart_order: 1,
        quality_flags: out ? ["current_status_reserve"] : [],
      } satisfies PlayerStatusRecord;
    });
}

export function projectionRecords(): PlayerProjectionRecord[] {
  const records: PlayerProjectionRecord[] = [];
  for (const scoring of SCORING) {
    for (const seed of SEEDS) {
      const points = 120 + scale(seed.p50, scoring, 12) * 0.8;
      records.push({
        schema_version: "1.0",
        build_id: FIXTURE_BUILD_ID,
        model_version: "intrinsic-cb-hurdle-v1",
        season: 2026,
        as_of_utc: FIXTURE_GENERATED_AT,
        player_id: seed.id,
        display_name: seed.name,
        team: seed.team,
        position: seed.position,
        scoring_preset: scoring,
        expected_points: round(points),
        p10_points: round(points - 90),
        p25_points: round(points - 44),
        p50_points: round(points - 6),
        p75_points: round(points + 48),
        p90_points: round(points + 102),
        uncertainty_points: round(96.4),
        quality_flags: [],
      });
    }
  }
  return records;
}

export function buildMetadata(overrides: Partial<BuildMetadata> = {}): BuildMetadata {
  return {
    schema_version: "1.0",
    build_id: FIXTURE_BUILD_ID,
    generated_at_utc: FIXTURE_GENERATED_AT,
    git_sha: "0000000",
    season: 2026,
    intrinsic_model_version: "intrinsic-cb-hurdle-v1",
    arbitrage_mode: "baseline",
    arbitrage_model_version: null,
    arbitrage_method_version: "a0_rank_gap_v1",
    market: {
      source_id: "myfantasyleague_adp",
      snapshot_key: "2026-08-20T14-38-44Z",
      snapshot_at_utc: FIXTURE_SNAPSHOT_AT,
      source_as_of_utc: null,
      cohort_rule_version: "phase5_cohort_v2",
      confidence_rubric_version: "phase5_confidence_v1",
      trend_rule_version: "phase5_trend_v1",
      trend_available: false,
      trend_history_snapshots: 2,
      assignments: LEAGUES.flatMap((league) =>
        SCORING.map((scoring) => ({
          scoring_preset: scoring,
          league_size: league.teams,
          cohort_id: "no-mock-no-keeper",
          exact: false,
          sufficient: false,
          source_format_detail: "IS_KEEPER=N&IS_MOCK=0 (approximate cohort)",
          failed_clauses: ["total_drafts 125 < 300"],
        })),
      ),
      confidence_counts: { low: 153 },
      unpriced_top_players: 9,
    },
    player_status: {
      players: 17,
      sleeper_available: true,
      sleeper_matched: 17,
      sleeper_identity_conflicts: 0,
      observed_at_utc: "2026-08-20T14:39:19Z",
      source_ids: ["nflreadpy", "sleeper"],
    },
    supported_presets: ["redraft-10", "redraft-12", "redraft-14"],
    sources: [
      {
        source_id: "myfantasyleague_adp",
        status: "warning",
        retrieved_at_utc: FIXTURE_SNAPSHOT_AT,
        source_as_of_utc: null,
        record_count: 4364,
        warnings: ["cohort_approximate", "cohort_insufficient"],
      },
      {
        source_id: "nflreadpy",
        status: "pass",
        retrieved_at_utc: FIXTURE_GENERATED_AT,
        source_as_of_utc: null,
        record_count: 732882,
        warnings: [],
      },
      {
        source_id: "sleeper",
        status: "pass",
        retrieved_at_utc: "2026-08-20T14:39:19Z",
        source_as_of_utc: null,
        record_count: 12240,
        warnings: [],
      },
    ],
    quality_gate: { status: "pass", critical_failures: 0, warnings: 2 },
    warnings: [
      "tiers are published having not passed the frozen tier stability gate; read a tier as a group of comparable players, not as a hard line - membership is reproducible but boundary positions are not (ADR-035)",
      "top-150 board players with no market price are excluded, not filled in",
    ],
    methodology_version: "phase4_intrinsic_v1",
    ...overrides,
  };
}

function envelope<TRecord>(
  artifact: ArtifactEnvelope<TRecord>["artifact"],
  recordSchema: string,
  records: readonly TRecord[],
  schemaVersion = "1.0",
): ArtifactEnvelope<TRecord> {
  return {
    schema_version: schemaVersion,
    artifact,
    record_schema: recordSchema,
    build_id: FIXTURE_BUILD_ID,
    generated_at_utc: FIXTURE_GENERATED_AT,
    record_count: records.length,
    records,
  };
}

export function tierEnvelope(schemaVersion?: string): ArtifactEnvelope<TierRecord> {
  return envelope("tiers", "tier_record", tierRecords(), schemaVersion);
}

export function arbitrageEnvelope(): ArtifactEnvelope<ArbitrageRecord> {
  return { ...envelope("arbitrage", "arbitrage_record", arbitrageRecords()), arbitrage_mode: "baseline" };
}

export function playerStatusEnvelope(): ArtifactEnvelope<PlayerStatusRecord> {
  return envelope("player_status", "player_status", playerStatusRecords());
}

export function projectionEnvelope(): ArtifactEnvelope<PlayerProjectionRecord> {
  return envelope("projections", "player_projection", projectionRecords());
}

/** Everything a page load needs, keyed by the filename the loader will ask for. */
export function fixtureFiles(): Record<string, unknown> {
  return {
    "build_metadata.json": buildMetadata(),
    "tiers.json": tierEnvelope(),
    "arbitrage.json": arbitrageEnvelope(),
    "player_status.json": playerStatusEnvelope(),
    "projections.json": projectionEnvelope(),
  };
}
