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
 * **Two market conditions, because one of them was a trap.** Until Phase 8 this file only
 * described the launch board: every arbitrage row `low`, every trend null, the cohort below
 * the frozen sufficiency bar. That was the real condition in August 2026 and it made the
 * whole verification layer blind — production moved to a mostly-`medium` board with a
 * measured trend and a cohort that *clears* the bar within a week, and not one test in the
 * repository rendered that state. The same class of defect as the Phase-7 trend verifier,
 * which had frozen the null launch condition into an assertion (ADR-052, and the
 * `verify-real-build.mjs` note).
 *
 * So `MARKET_CONDITIONS` describes both, and the market-sensitive tests run against each:
 *
 * | condition  | confidence          | trend            | cohort                        |
 * |------------|---------------------|------------------|-------------------------------|
 * | `launch`   | every row `low`     | null everywhere  | below the frozen bar          |
 * | `matured`  | mixed medium/low    | mostly non-null  | clears every clause           |
 *
 * The matured board deliberately keeps one row with a null trend and one `low` row, because
 * a mature market does not make either impossible and a component that only handles the
 * uniform case would still be wrong.
 */

import type {
  ArbitrageRecord,
  ArtifactEnvelope,
  BuildMetadata,
  OpportunityRecord,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  Position,
  RosBuildMetadata,
  RosTierRecord,
  ScoringPreset,
  TierRecord,
  MarketComparison,
  MarketTrendSeriesRecord,
} from "../../src/data/contracts";

/**
 * The market condition a fixture board describes.
 *
 * `launch` is August 2026: a thin keeper-free cohort, no trend history, one confidence label.
 * `matured` is the same board a fortnight later. Neither is "the normal one" — that is the
 * point, and every market-sensitive component is checked against both.
 */
export type MarketCondition = "launch" | "matured";

export const MARKET_CONDITIONS: readonly MarketCondition[] = ["launch", "matured"];

export const FIXTURE_BUILD_ID = "fixture-20260821T120000Z";
export const FIXTURE_GENERATED_AT = "2026-08-21T14:38:00Z";
export const FIXTURE_SNAPSHOT_AT = "2026-08-20T14:38:44Z";
/** The same board a fortnight later: a fuller cohort, a trend window, mixed confidence. */
export const FIXTURE_MATURED_SNAPSHOT_AT = "2026-09-03T11:25:57Z";

/**
 * FFC's own capture times, which are **not** MyFantasyLeague's.
 *
 * Two markets captured by two jobs are observed minutes apart at best, and a card that
 * printed one source's snapshot time under the other's name would be wrong in a way nothing
 * could see while both fixtures carried the same instant.
 */
export const FFC_SNAPSHOT_AT: Readonly<Record<MarketCondition, string>> = {
  launch: "2026-08-20T14:41:07Z",
  matured: "2026-09-03T11:27:12Z",
};

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

function round(value: number, digits = 4): number {
  return Number(value.toFixed(digits));
}

/**
 * The one matured-board row that still has no trend estimate.
 *
 * Deebo Gray: 22 drafts at launch, and the thinnest sample on the board afterwards. A window
 * with enough observation days does not guarantee an estimate for every player, so the
 * matured fixture keeps a row that proves the em-dash path is still reachable.
 */
const NULL_TREND_PLAYER_ID = "gsis:00-0000006";

/** Two more weeks of drafts. Not a rescale of the price — only of the evidence behind it. */
function maturedSample(sample: number | null): number | null {
  return sample === null ? null : Math.round(sample * 3.9);
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

export function arbitrageRecords(condition: MarketCondition = "launch"): ArbitrageRecord[] {
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
        const thinSample = (entry.seed.sample ?? 0) < 30;
        const flags = condition === "launch"
          ? ["cohort_approximate", "cohort_insufficient", "insufficient_trend_history"]
          : ["cohort_approximate"];
        if (thinSample) flags.push("low_market_sample");
        if (adp > 50) flags.push("wide_market_range");
        // A matured board is mixed, not uniformly `medium`: a player only 22 drafts selected
        // still has a thin price, and a component that assumed one label per board would be
        // wrong on the very first row that disagreed.
        const confidence = condition === "launch" ? "low" : thinSample ? "low" : "medium";
        // ...and one player deliberately keeps a null trend on the matured board, because a
        // present trend window does not guarantee an estimate for every row (ADR-042).
        const trend =
          condition === "launch" || entry.tier.player_id === NULL_TREND_PLAYER_ID
            ? null
            : round(Math.sin(entry.tier.fair_rank * 1.7) * 0.42, 2);
        records.push({
          schema_version: "1.2",
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
          market_trend: trend,
          market_sample_size:
            condition === "launch" ? entry.seed.sample : maturedSample(entry.seed.sample),
          market_adp_sd: null,
          market_adp_low: round(Math.max(1, adp - 18)),
          market_adp_high: round(adp + 44),
          market_source_id: "myfantasyleague_adp",
          market_cohort_id: condition === "launch" ? "no-mock-no-keeper" : "no-keeper",
          market_cohort_detail:
            condition === "launch"
              ? "IS_KEEPER=N&IS_MOCK=0 (approximate cohort)"
              : "IS_KEEPER=N (approximate cohort)",
          market_snapshot_at_utc:
            condition === "launch" ? FIXTURE_SNAPSHOT_AT : FIXTURE_MATURED_SNAPSHOT_AT,
          confidence,
          quality_flags: flags.sort(),
          ...secondMarket(
            entry.tier.player_id,
            adp,
            entry.tier.fair_rank,
            condition,
            rank,
            trend,
            condition === "launch" ? entry.seed.sample : maturedSample(entry.seed.sample),
          ),
        });
      }
    }
  }
  return records;
}

/**
 * The second market, and the reason this fixture has one.
 *
 * Until it did, no fixture in the repository carried more than one market — so the page
 * always rendered MyFantasyLeague whichever source was selected, every consumer that read
 * the flat V1 `market_adp` looked correct, and three consecutive production refreshes were
 * needed to find that the draft rail, the player card and `verify-real-build.mjs` were all
 * reading a different market from the table (ADR-067).
 *
 * The two markets must **disagree** for that to be catchable: if FFC repeated MFL's number,
 * a consumer reading the wrong one would still render the right value. FFC's seven-day
 * window prices a riser earlier than MFL's season aggregate, so the offset leans that way.
 *
 * Three named players are left single-market on purpose. A source covering part of the board
 * is the normal case, and those rows are what prove the cross-market summary says "one
 * market" rather than inventing a spread of zero — and, since the selector defaults to FFC,
 * what proves the card says "this market does not price him" instead of quietly showing
 * MyFantasyLeague's number under an FFC heading (ADR-081).
 *
 * Named rather than derived from a gap rank, so which player is single-market is a fact this
 * file states and a test can rely on, rather than a consequence of the arithmetic above.
 */
/** MyFantasyLeague's own comparison, which is also the whole of a single-market row. */
function onlyMflMarket(
  adp: number,
  fairRank: number,
  condition: MarketCondition,
  trend: number | null,
  sample: number | null,
): MarketComparison {
  return {
    source_id: "myfantasyleague_adp",
    market_signal_type: "adp",
    market_adp: adp,
    market_rank: Math.max(1, Math.round(adp / 2)),
    rank_gap: round(adp - fairRank),
    regional_value_gap: round(Math.log(adp / fairRank), 6),
    // Source-specific: an FFC rolling week and an MFL season aggregate are backed by
    // different numbers of drafts, and a card showing one under the other's name is the
    // same class of mistake as showing one's trend under the other's label.
    market_sample_size: sample,
    // MFL publishes order statistics and no standard deviation; FFC is the other way round.
    // Keeping that asymmetry is what stops the Dispersion column being written for one shape.
    market_adp_sd: null,
    market_adp_low: round(Math.max(1, adp - 18)),
    market_adp_high: round(adp + 44),
    league_size: null,
    aggregation_window_type: "season_cumulative",
    aggregation_window_days: null,
    market_cohort_id: condition === "launch" ? "no-mock-no-keeper" : "no-keeper",
    market_cohort_detail: "IS_KEEPER=N (approximate cohort)",
    market_snapshot_at_utc:
      condition === "launch" ? FIXTURE_SNAPSHOT_AT : FIXTURE_MATURED_SNAPSHOT_AT,
    // The flat V1 field is MyFantasyLeague's, so this entry carries the same number. They
    // are two views of one measurement and a fixture in which they differed would be
    // describing an artifact the build cannot produce.
    market_trend: trend,
    quality_flags: [],
  };
}

const FFC_UNPRICED: ReadonlySet<string> = new Set([
  "gsis:00-0000009", // Joe Burrow, a premium row
  "gsis:00-0000008", // Josh Allen, the other premium row
  "gsis:00-0000015", // Zay Meadows, a bargain row in the middle of the board
]);

function secondMarket(
  playerId: string,
  adp: number,
  fairRank: number,
  condition: MarketCondition,
  rank: number,
  trend: number | null,
  sample: number | null,
): Pick<ArbitrageRecord, "markets" | "cross_market"> | Record<string, never> {
  if (FFC_UNPRICED.has(playerId)) {
    // Still a `markets` array: MyFantasyLeague priced him and says so. An absent array would
    // mean "Release 1 bundle", which is a different shape entirely.
    const only = onlyMflMarket(adp, fairRank, condition, trend, sample);
    return {
      markets: [only],
      cross_market: {
        sources_available: [only.source_id],
        market_adp_min: adp,
        market_adp_max: adp,
        market_adp_median: adp,
        // Null, never zero: one market speaking is not two markets agreeing.
        market_disagreement_range: null,
        cheapest_market_source: only.source_id,
        most_expensive_market_source: only.source_id,
      },
    };
  }
  const ffcAdp = round(Math.max(1, adp - (adp * 0.08 + (rank % 2 ? 1.5 : -2.5))));
  const mfl = onlyMflMarket(adp, fairRank, condition, trend, sample);
  const ffc: MarketComparison = {
    ...mfl,
    source_id: "fantasyfootballcalculator_adp",
    market_adp: ffcAdp,
    market_rank: Math.max(1, Math.round(ffcAdp / 2)),
    // Each source is compared against the same fair rank, so the gaps genuinely differ.
    rank_gap: round(ffcAdp - fairRank),
    regional_value_gap: round(Math.log(ffcAdp / fairRank), 6),
    market_sample_size: condition === "launch" ? 1794 : 3142,
    market_adp_sd: round(2 + (rank % 5)),
    market_adp_low: null,
    market_adp_high: null,
    aggregation_window_type: "rolling",
    aggregation_window_days: 7,
    market_cohort_id: "ffc-half-ppr",
    market_cohort_detail: "format=half-ppr",
    market_snapshot_at_utc: FFC_SNAPSHOT_AT[condition],
    /*
     * **Null on purpose, and never inherited.** FFC is captured on its own cadence and its
     * retained window is younger than MyFantasyLeague's: it has real observations over four
     * calendar days but only 2.6 days of elapsed span, so `phase5_trend_v1` declines to
     * estimate a slope while the chart has five points to draw.
     *
     * This is the production state on the day the bug was found, and no fixture in this
     * repository could express it: FFC simply repeated MFL's null, so nothing distinguished
     * "this market has not moved" from "this market's slope is not computable yet" and
     * nothing could catch a card that filled the null in from MyFantasyLeague (ADR-081).
     */
    market_trend: null,
  };
  const cheapest = ffcAdp <= adp ? ffc.source_id : mfl.source_id;
  return {
    markets: [ffc, mfl],
    cross_market: {
      sources_available: [ffc.source_id, mfl.source_id],
      market_adp_min: Math.min(ffcAdp, adp),
      market_adp_max: Math.max(ffcAdp, adp),
      market_adp_median: round((ffcAdp + adp) / 2),
      market_disagreement_range: round(Math.abs(adp - ffcAdp)),
      cheapest_market_source: cheapest,
      most_expensive_market_source: cheapest === ffc.source_id ? mfl.source_id : ffc.source_id,
    },
  };
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
      /*
       * Declared inactive, with no injury designation and no Sleeper annotation at all.
       *
       * Until 2026-09-12 no fixture in this repository carried a *non-injury* roster code:
       * the reserve case above also reports `IR`, so every badge on every fixture board had
       * an `injury_status` behind it. `verify:board` had encoded that coincidence as a list
       * of the roster codes it expected to see, and the first in-season refresh - where
       * nflverse publishes `INA` for a player who was inactive for a game - failed on a
       * board that was right. The state now exists in the fixture, so the local gates meet
       * it before a production refresh does.
       */
      const inactive = seed.name === "Omarion Vance";
      return {
        ...base,
        player_id: seed.id,
        display_name: seed.name,
        current_team: seed.team,
        position: seed.position,
        roster_status: out ? "RES" : inactive ? "INA" : "ACT",
        roster_depth_chart_position: seed.position,
        sleeper_status: out ? "Injured Reserve" : "Active",
        injury_status: injured ? "Questionable" : out ? "IR" : null,
        injury_body_part: injured ? "Hamstring" : null,
        injury_notes: injured ? "Limited in Wednesday's session; expected to test it Friday." : null,
        depth_chart_position: seed.position,
        depth_chart_order: 1,
        // `INA` carries no `current_status_*` flag because the build publishes none for it
        // (`FLAGGED_STATUSES` names `RES`, `CUT` and `E14`); the badge is the whole signal.
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

export function buildMetadata(
  overrides: Partial<BuildMetadata> = {},
  condition: MarketCondition = "launch",
): BuildMetadata {
  const launch = condition === "launch";
  return {
    schema_version: "1.0",
    build_id: FIXTURE_BUILD_ID,
    generated_at_utc: FIXTURE_GENERATED_AT,
    git_sha: "0000000",
    season: 2026,
    // The default fixture is a preseason build, which is what makes it the *draft* fixture:
    // the season has not started, so no rest-of-season board is expected and none is
    // published. The in-season and lifecycle scenarios override this block.
    season_state: {
      rule_version: "season_state_v1",
      state: "preseason_draft",
      product_mode: "draft",
      completed_week: 0,
      latest_snapshot_week: null,
      ros_board_expected: false,
      note: "the season has not kicked off; the draft board is the current product",
    },
    intrinsic_model_version: "intrinsic-cb-hurdle-v1",
    arbitrage_mode: "baseline",
    arbitrage_model_version: null,
    arbitrage_method_version: "a0_rank_gap_v1",
    market: {
      source_id: "myfantasyleague_adp",
      snapshot_key: launch ? "2026-08-20T14-38-44Z" : "2026-09-03T11-25-57Z",
      snapshot_at_utc: launch ? FIXTURE_SNAPSHOT_AT : FIXTURE_MATURED_SNAPSHOT_AT,
      source_as_of_utc: null,
      cohort_rule_version: "phase5_cohort_v2",
      confidence_rubric_version: "phase5_confidence_v1",
      trend_rule_version: "phase5_trend_v1",
      trend_available: !launch,
      trend_history_snapshots: launch ? 2 : 7,
      assignments: LEAGUES.flatMap((league) =>
        SCORING.map((scoring) => ({
          scoring_preset: scoring,
          league_size: league.teams,
          cohort_id: launch ? "no-mock-no-keeper" : "no-keeper",
          // One matured block is exact, so the "approximate" qualifier has to be *derived*
          // rather than assumed: a UI that hardcoded the word would fail this row.
          exact: !launch && league.teams === 10 && scoring === "STD",
          sufficient: !launch,
          source_format_detail: launch
            ? "IS_KEEPER=N&IS_MOCK=0 (approximate cohort)"
            : "IS_KEEPER=N (approximate cohort)",
          failed_clauses: launch ? ["total_drafts 125 < 300"] : [],
        })),
      ),
      confidence_counts: launch ? { low: 153 } : { medium: 135, low: 18 },
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
        retrieved_at_utc: launch ? FIXTURE_SNAPSHOT_AT : FIXTURE_MATURED_SNAPSHOT_AT,
        source_as_of_utc: null,
        record_count: 4364,
        warnings: launch ? ["cohort_approximate", "cohort_insufficient"] : ["cohort_approximate"],
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

export function arbitrageEnvelope(
  condition: MarketCondition = "launch",
): ArtifactEnvelope<ArbitrageRecord> {
  return {
    ...envelope("arbitrage", "arbitrage_record", arbitrageRecords(condition)),
    arbitrage_mode: "baseline",
  };
}

/**
 * The retained capture cadences the two markets actually have, per condition.
 *
 * They differ in every respect that matters, because a fixture whose two histories matched
 * could not tell a chart reading the right source from one reading the wrong source — the
 * exact reason a second market shipped with no chart at all and every gate stayed green
 * (ADR-081).
 *
 * `hours` are offsets back from that source's own snapshot instant, newest last. FFC's
 * matured plan puts **two captures on one calendar day** (55h and 38h back) and spans 62
 * hours in total: four observation days, which `phase5_trend_v1` accepts, over 2.6 days of
 * span, which it does not. That is a chart with five points and a slope of `null`, which is
 * the state the card has to render honestly rather than fill in from elsewhere.
 */
const HISTORY_PLANS: Readonly<
  Record<string, Readonly<Record<MarketCondition, { readonly hours: readonly number[]; readonly drift: number }>>>
> = {
  myfantasyleague_adp: {
    launch: { hours: [26, 0], drift: 0.3 },
    matured: { hours: [144, 120, 96, 72, 48, 24, 0], drift: 0.3 },
  },
  fantasyfootballcalculator_adp: {
    launch: { hours: [0], drift: 0.55 },
    matured: { hours: [62, 55, 38, 19, 0], drift: 0.55 },
  },
};

/**
 * One market's retained history for every player it priced.
 *
 * Derived from the published arbitrage rows, so the chart's newest point is the ADP the card
 * shows and the record's `market_trend` is that market's own slope — the two agreements the
 * artifact validator checks on the Python side and the browser has no way to notice.
 */
export function marketTrendSeriesRecords(
  condition: MarketCondition = "launch",
): MarketTrendSeriesRecord[] {
  const records: MarketTrendSeriesRecord[] = [];
  for (const row of arbitrageRecords(condition)) {
    const quotes: readonly MarketComparison[] =
      (row.markets ?? []).length > 0
        ? (row.markets ?? []).filter((entry) => entry.market_signal_type === "adp")
        : [];
    for (const quote of quotes) {
      const plan = HISTORY_PLANS[quote.source_id]?.[condition];
      if (plan === undefined) continue;
      const anchor = Date.parse(quote.market_snapshot_at_utc);
      // Signed from the player id, so the fixture holds both directions.
      let codes = 0;
      for (let i = 0; i < row.player_id.length; i += 1) codes += row.player_id.charCodeAt(i);
      const step = codes % 2 === 0 ? plan.drift : -plan.drift;
      records.push({
        schema_version: "1.0",
        build_id: FIXTURE_BUILD_ID,
        market_source_id: quote.source_id,
        scoring_preset: row.scoring_preset,
        league_preset_id: row.league_preset_id,
        player_id: row.player_id,
        cohort_id: quote.market_cohort_id,
        window_days: 7,
        market_trend: quote.market_trend,
        points: [...plan.hours]
          .sort((a, b) => b - a)
          .map((offset) => ({
            observed_at: new Date(anchor - offset * 3_600_000).toISOString().replace(/\.\d{3}Z$/, "Z"),
            market_adp: round(Math.max(0.1, quote.market_adp + step * (offset / 24))),
          })),
      });
    }
  }
  return records;
}

export function marketTrendSeriesEnvelope(
  condition: MarketCondition = "launch",
): ArtifactEnvelope<MarketTrendSeriesRecord> {
  return envelope("market_trend_series", "market_trend_series", marketTrendSeriesRecords(condition));
}

/**
 * The in-season fixture bundle.
 *
 * Derived from the draft fixture's own tier rows so the two boards describe the same
 * players, which is what makes the firewall assertion meaningful: an opportunity row copies
 * its intrinsic columns from the rest-of-season row, and a test can compare them.
 *
 * Three shapes are deliberately present, each of which only misbehaves in production: a
 * long-absence row carrying the ADR-076 fields, a player surfaced from beyond the tier depth
 * with a declared reason and no tier, and behaviour counts with their requested window.
 */
export const FIXTURE_THROUGH_WEEK = 8;
export const FIXTURE_BEHAVIOR_LOOKBACK_HOURS = 24;

export function rosTierRecords(): RosTierRecord[] {
  return tierRecords().map((record, index) => {
    const absent = index % 3 === 2;
    const scale = 0.5;
    return {
      schema_version: "1.0",
      build_id: FIXTURE_BUILD_ID,
      season: 2026,
      through_week: FIXTURE_THROUGH_WEEK,
      league_preset_id: record.league_preset_id,
      scoring_preset: record.scoring_preset,
      player_id: record.player_id,
      display_name: record.display_name,
      team: record.team,
      position: record.position,
      ros_fair_rank: record.fair_rank,
      ros_position_rank: record.position_rank,
      ros_tier: record.tier_ordinal,
      ros_tier_label: record.tier_label,
      ros_expected_vorp: round(record.expected_vorp * scale),
      ros_vorp_p10: round(record.p10_vorp * scale),
      ros_vorp_p25: round(record.p25_vorp * scale),
      ros_vorp_p50: round(record.p50_vorp * scale),
      ros_vorp_p75: round(record.p75_vorp * scale),
      ros_vorp_p90: round(record.p90_vorp * scale),
      ros_expected_points: round(record.expected_points * scale),
      ros_points_p10: round(record.expected_points * scale * 0.7),
      ros_points_p50: round(record.expected_points * scale),
      ros_points_p90: round(record.expected_points * scale * 1.3),
      ros_expected_games: absent ? 5.4 : 8.1,
      ros_uncertainty: round(record.uncertainty * scale),
      remaining_horizon_weeks: 9,
      team_remaining_scheduled_games: 8,
      // Derived, not asserted independently: `fair_rank_change` is `preseason - ros`, so a
      // fixture that states both must state them consistently or the player card shows two
      // equal ranks beside a non-zero move.
      preseason_fair_rank: Math.max(1, record.fair_rank + (absent ? -12 : 3)),
      fair_rank_change: Math.max(1, record.fair_rank + (absent ? -12 : 3)) - record.fair_rank,
      games_played_to_date: absent ? 5 : 8,
      points_to_date: round(record.expected_points * (1 - scale)),
      points_per_game_to_date: round((record.expected_points * (1 - scale)) / 8),
      weeks_since_last_game: absent ? 3 : 0,
      consecutive_weeks_missed: absent ? 3 : 0,
      has_played_this_season: true,
      long_absence: absent,
      in_preseason_universe: true,
      current_status: absent ? "RES" : null,
      outside_tier_board: false,
      surface_reasons: ["intrinsic_top_tier_depth"],
      quality_flags: absent ? ["long_absence"] : [],
    };
  });
}

export function opportunityRecords(behaviorAvailable = true): OpportunityRecord[] {
  const base: OpportunityRecord[] = rosTierRecords().map((record, index) => {
    const adds = Math.max(0, 900 - index * 37);
    const drops = Math.max(0, 120 - index * 5);
    return {
      schema_version: "1.0",
      build_id: FIXTURE_BUILD_ID,
      season: record.season,
      through_week: record.through_week,
      league_preset_id: record.league_preset_id,
      scoring_preset: record.scoring_preset,
      player_id: record.player_id,
      display_name: record.display_name,
      team: record.team,
      position: record.position,
      // Copied, never recomputed — the property the firewall test asserts.
      ros_fair_rank: record.ros_fair_rank,
      ros_position_rank: record.ros_position_rank,
      ros_expected_vorp: record.ros_expected_vorp,
      ros_expected_points: record.ros_expected_points,
      ros_expected_games: record.ros_expected_games,
      ros_uncertainty: record.ros_uncertainty,
      ros_tier: record.ros_tier,
      behavior_source_id: behaviorAvailable ? "sleeper" : null,
      behavior_available: behaviorAvailable,
      behavior_snapshot_at_utc: behaviorAvailable ? FIXTURE_GENERATED_AT : null,
      behavior_lookback_hours: behaviorAvailable ? FIXTURE_BEHAVIOR_LOOKBACK_HOURS : null,
      behavior_request_limit: behaviorAvailable ? 100 : null,
      add_count: behaviorAvailable ? adds : null,
      drop_count: behaviorAvailable ? drops : null,
      net_add_count: behaviorAvailable ? adds - drops : null,
      add_rank: behaviorAvailable ? index + 1 : null,
      drop_rank: behaviorAvailable ? index + 1 : null,
      long_absence: record.long_absence,
      weeks_since_last_game: record.weeks_since_last_game,
      games_played_to_date: record.games_played_to_date,
      snap_share_last3: 0.72,
      target_share_last3: 0.19,
      current_status: record.current_status,
      outside_tier_board: false,
      surface_reasons: ["intrinsic_top_tier_depth"],
      quality_flags: record.quality_flags,
    };
  });

  // One surfaced player **per block**, exactly as the production build produces one per
  // block: a single row anchored on the first record would land in whichever league and
  // scoring preset happened to sort first, and the default board would show none.
  const blocks = new Map<string, OpportunityRecord>();
  for (const record of base) {
    const key = `${record.league_preset_id}|${record.scoring_preset}`;
    if (!blocks.has(key)) blocks.set(key, record);
  }
  for (const anchor of blocks.values()) {
    base.push({
      ...anchor,
      player_id: `${anchor.player_id}-surfaced`,
      display_name: `${anchor.display_name} (surfaced)`,
      ros_fair_rank: 900,
      ros_position_rank: 90,
      ros_expected_vorp: 0,
      ros_expected_points: null,
      ros_expected_games: null,
      ros_uncertainty: 0,
      // No tier. The segmentation never saw him, and inventing one is what ADR-063 forbids.
      ros_tier: null,
      add_count: behaviorAvailable ? 1450 : null,
      drop_count: behaviorAvailable ? 20 : null,
      net_add_count: behaviorAvailable ? 1430 : null,
      add_rank: behaviorAvailable ? 1 : null,
      drop_rank: behaviorAvailable ? 90 : null,
      long_absence: false,
      weeks_since_last_game: 0,
      outside_tier_board: true,
      surface_reasons: ["sleeper_trending_add"],
      quality_flags: [],
    });
  }
  return base;
}

export function rosBuildMetadata(
  overrides: Partial<RosBuildMetadata> = {},
  behaviorAvailable = true,
): RosBuildMetadata {
  return {
    schema_version: "1.0",
    build_id: FIXTURE_BUILD_ID,
    generated_at_utc: FIXTURE_GENERATED_AT,
    git_sha: "0000000",
    season: 2026,
    through_week: FIXTURE_THROUGH_WEEK,
    season_state: {
      rule_version: "season_state_v1",
      season_state: "regular_season",
      product_mode: "in_season",
      completed_week: FIXTURE_THROUGH_WEEK,
      latest_snapshot_week: FIXTURE_THROUGH_WEEK,
      next_transition_utc: null,
    },
    ros_model_version: "intrinsic-ros-v1",
    ros_model_configuration_hash: "d79133847436f04f",
    production_fit_rule_version: "ros_production_fit_v1",
    model_fitted_at_utc: FIXTURE_GENERATED_AT,
    model_training_seasons: [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
    model_refit_reason: "initial_production_fit",
    cutoff_rule_version: "ros_cutoff_v1",
    feature_set_version: "ros_core_v1",
    feature_set_hash: "f5ad9df207795351",
    methodology_version: "phase12_ros_v1",
    simulation: {
      draws: 10000,
      draws_status: "declared fallback",
      seed: 20260903,
      ranking_statistic: "median_vorp",
      replacement_rule: "rostered_depth",
      replacement_rule_description: "the best player nobody rosters",
      tier_algorithm: "pelt_rbf",
      tier_penalty: 3,
      tier_depth: 500,
      convergence_gate: "fail",
      tier_stability_gate: "fail",
    },
    source_freshness: {
      rule_version: "ros_source_freshness_v1",
      available_through_week: FIXTURE_THROUGH_WEEK,
      schedule_completed_week: FIXTURE_THROUGH_WEEK,
      blocking_week: null,
      buildable: true,
    },
    behavior: {
      source_id: behaviorAvailable ? "sleeper" : null,
      available: behaviorAvailable,
      snapshot_at_utc: behaviorAvailable ? FIXTURE_GENERATED_AT : null,
      lookback_hours: behaviorAvailable ? FIXTURE_BEHAVIOR_LOOKBACK_HOURS : null,
      request_limit: behaviorAvailable ? 100 : null,
      matched_players: behaviorAvailable ? 18 : 0,
      degraded_reason: behaviorAvailable ? null : "no retained behaviour capture",
    },
    disclosures: {
      uses_injury_information: false,
      long_absence_definition:
        "has played at least once this season and has not appeared for 3 or more consecutive weeks ending at the cutoff",
      long_absence_statement:
        "This estimate uses no injury or practice-report information of any kind. The model infers absence from appearances alone.",
      long_absence_ordering_weakness:
        "Ranking quality inside this group is weak: Spearman 0.311 against 0.797 on the full universe.",
      status_is_annotation_only: true,
      long_absence_players: rosTierRecords().filter((record) => record.long_absence).length,
      tier_boundary_statement: "Rest-of-season tiers are bands, not lines.",
    },
    limitations: [
      "Overconfident on high-draft-capital rookies.",
      "Close to unable to order players returning from a long absence.",
    ],
    supported_presets: ["redraft-10", "redraft-12", "redraft-14"],
    sources: [],
    quality_gate: { status: "pass", critical_failures: 0, warnings: 0 },
    warnings: [],
    ...overrides,
  };
}

export function rosTierEnvelope(schemaVersion?: string): ArtifactEnvelope<RosTierRecord> {
  return envelope("ros_tiers", "ros_tier_record", rosTierRecords(), schemaVersion);
}

export function opportunityEnvelope(
  behaviorAvailable = true,
): ArtifactEnvelope<OpportunityRecord> {
  return envelope(
    "inseason_opportunity",
    "inseason_opportunity_record",
    opportunityRecords(behaviorAvailable),
  );
}

export function playerStatusEnvelope(): ArtifactEnvelope<PlayerStatusRecord> {
  return envelope("player_status", "player_status", playerStatusRecords());
}

export function projectionEnvelope(): ArtifactEnvelope<PlayerProjectionRecord> {
  return envelope("projections", "player_projection", projectionRecords());
}

/** Everything a page load needs, keyed by the filename the loader will ask for. */
export function fixtureFiles(condition: MarketCondition = "launch"): Record<string, unknown> {
  return {
    "build_metadata.json": buildMetadata({}, condition),
    "tiers.json": tierEnvelope(),
    "arbitrage.json": arbitrageEnvelope(condition),
    // Two markets' retained histories, which is the shape production has and no fixture
    // here carried until it turned out to matter (ADR-081).
    "market_trend_series.json": marketTrendSeriesEnvelope(condition),
    "player_status.json": playerStatusEnvelope(),
    "projections.json": projectionEnvelope(),
  };
}

/** Everything a page load needs **in season**, on top of the draft bundle. */
export function inSeasonFixtureFiles(behaviorAvailable = true): Record<string, unknown> {
  return {
    // The draft build's own record of the season, replaced because in season it says
    // something different — and the page reads it whether or not a ROS bundle is beside it.
    "build_metadata.json": buildMetadata({
      season_state: {
        rule_version: "season_state_v1",
        state: "regular_season",
        product_mode: "in_season",
        completed_week: FIXTURE_THROUGH_WEEK,
        latest_snapshot_week: FIXTURE_THROUGH_WEEK,
        ros_board_expected: true,
        note: `the rest-of-season board is current through week ${String(FIXTURE_THROUGH_WEEK)}`,
      },
    }),
    "ros_build_metadata.json": rosBuildMetadata({}, behaviorAvailable),
    "ros_tiers.json": rosTierEnvelope(),
    "inseason_opportunity.json": opportunityEnvelope(behaviorAvailable),
  };
}

/**
 * The two lifecycle windows in which the season has started and **no** rest-of-season board
 * exists: opening week, before the first completed week is published, and after the last
 * scored week. Both publish the draft bundle alone, and both must say so rather than letting
 * the page imply the season has not begun (ADR-079).
 */
export function lifecycleFixtureFiles(
  phase: "awaiting_first_week" | "season_complete",
): Record<string, unknown> {
  const awaiting = phase === "awaiting_first_week";
  return {
    ...fixtureFiles(),
    "build_metadata.json": buildMetadata({
      season_state: {
        rule_version: "season_state_v1",
        state: awaiting ? "regular_season" : "season_complete",
        product_mode: "in_season",
        completed_week: awaiting ? 0 : 17,
        latest_snapshot_week: null,
        ros_board_expected: false,
        note: awaiting
          ? "the season is under way; the first rest-of-season board is published once week 1 is complete and its upstream data has been released"
          : "every scored week has been played; no rest-of-season horizon remains, so no new rest-of-season board is produced",
      },
    }),
  };
}
