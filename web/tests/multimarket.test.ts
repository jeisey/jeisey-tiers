/**
 * The multi-source market layer in the browser (Phase 10, ADR-065).
 *
 * The rules these pin are the same ones the backend enforces, and they are re-pinned here
 * because the frontend is the last place they could quietly be undone: a component that
 * averaged an expert rank into a price would produce a number no artifact contains, and no
 * backend test would notice.
 *
 * The other half is degradation. A Release 1 bundle has no `markets` array, a source can be
 * missing for a player, and FantasyPros is retained-but-unpublished — each of which must
 * render as "nothing to say" rather than as a blank where a number belongs.
 */

import { describe, expect, it } from "vitest";

import type {
  ArbitrageRecord,
  MarketComparison,
  MarketTrendSeriesRecord,
} from "../src/data/contracts";
import {
  CROSS_MARKET,
  adpFor,
  comparisonFor,
  consensusOf,
  crossMarketAvailable,
  crossMarketSummaryText,
  disagreementFor,
  gapFor,
  historiesFor,
  isSurfaceException,
  marketLabel,
  marketView,
  marketsOf,
  selectableMarkets,
  sourceFor,
  trendFor,
  windowLabel,
} from "../src/data/multimarket";

const FFC = "fantasyfootballcalculator_adp";
const MFL = "myfantasyleague_adp";

function comparison(overrides: Partial<MarketComparison> & { source_id: string }): MarketComparison {
  return {
    market_signal_type: "adp",
    market_adp: 50,
    market_rank: null,
    rank_gap: 8,
    regional_value_gap: 0.17,
    market_sample_size: 400,
    market_adp_sd: null,
    market_adp_low: null,
    market_adp_high: null,
    league_size: null,
    aggregation_window_type: "rolling",
    aggregation_window_days: 7,
    market_cohort_id: "ffc-half-ppr",
    market_cohort_detail: "format=half-ppr",
    market_snapshot_at_utc: "2026-09-02T12:00:00Z",
    market_trend: null,
    quality_flags: [],
    ...overrides,
  };
}

function record(overrides: Partial<ArbitrageRecord> = {}): ArbitrageRecord {
  return {
    schema_version: "1.2",
    build_id: "b",
    league_preset_id: "redraft-12",
    scoring_preset: "HALF",
    player_id: "gsis:1",
    display_name: "Test Player",
    team: "BUF",
    position: "RB",
    fair_rank: 42,
    market_adp: 53,
    market_rank: 50,
    rank_gap: 11,
    regional_value_gap: 0.23,
    arbitrage_mode: "baseline",
    arbitrage_score: 70,
    expected_surplus_vorp: null,
    p_positive_surplus: null,
    market_trend: null,
    market_sample_size: 500,
    market_adp_sd: null,
    market_adp_low: 40,
    market_adp_high: 70,
    market_source_id: MFL,
    market_cohort_id: "no-keeper",
    market_cohort_detail: "IS_KEEPER=N",
    market_snapshot_at_utc: "2026-09-02T12:00:00Z",
    confidence: "medium",
    quality_flags: [],
    ...overrides,
  };
}

const MULTI = record({
  markets: [
    comparison({ source_id: FFC, market_adp: 61, rank_gap: 19, market_adp_sd: 8.2 }),
    comparison({
      source_id: MFL,
      market_adp: 53,
      rank_gap: 11,
      market_adp_low: 40,
      market_adp_high: 70,
      aggregation_window_type: "season_cumulative",
      aggregation_window_days: null,
    }),
  ],
  expert_consensus: {
    source_id: "fantasypros_ecr",
    market_signal_type: "ecr",
    ecr: 49,
    ecr_gap: 7,
    expert_count: 104,
    market_cohort_id: "fantasypros-half-ecr",
    market_snapshot_at_utc: "2026-09-02T12:00:00Z",
    quality_flags: [],
  },
  cross_market: {
    sources_available: [FFC, MFL],
    market_adp_min: 53,
    market_adp_max: 61,
    market_adp_median: 57,
    market_disagreement_range: 8,
    cheapest_market_source: FFC,
    most_expensive_market_source: MFL,
  },
  surface_reasons: ["intrinsic_top_tier_depth"],
  outside_tier_board: false,
});

describe("ECR is never a price", () => {
  it("keeps the expert consensus out of the ADP market list", () => {
    expect(Object.keys(marketsOf(MULTI))).toEqual([FFC, MFL]);
    expect(selectableMarkets([MULTI])).not.toContain("fantasypros_ecr");
  });

  it("reads the consensus only from a record that declares the ecr signal", () => {
    expect(consensusOf(MULTI)?.ecr).toBe(49);
    // A block claiming to be a price where the consensus belongs must be refused rather
    // than rendered under a ranking label.
    const mislabelled = record({
      expert_consensus: {
        source_id: "fantasypros_ecr",
        market_signal_type: "adp" as unknown as "ecr",
        ecr: 49,
        ecr_gap: 7,
        expert_count: 104,
        market_cohort_id: "fantasypros-half-ecr",
        market_snapshot_at_utc: "2026-09-02T12:00:00Z",
        quality_flags: [],
      },
    });
    expect(consensusOf(mislabelled)).toBeNull();
  });

  it("never resolves a market selection to the consensus source", () => {
    expect(comparisonFor(MULTI, "fantasypros_ecr")).toBeNull();
    expect(adpFor(MULTI, "fantasypros_ecr")).toBeNull();
  });
});

describe("each source keeps its identity", () => {
  it("returns the selected source's own price and gap", () => {
    expect(adpFor(MULTI, FFC)).toBe(61);
    expect(gapFor(MULTI, FFC)).toBe(19);
    expect(adpFor(MULTI, MFL)).toBe(53);
    expect(gapFor(MULTI, MFL)).toBe(11);
  });

  it("keeps a source's own dispersion field and does not borrow the other's", () => {
    const markets = marketsOf(MULTI);
    expect(markets[FFC]?.market_adp_sd).toBe(8.2);
    expect(markets[FFC]?.market_adp_low).toBeNull();
    expect(markets[MFL]?.market_adp_sd).toBeNull();
    expect(markets[MFL]?.market_adp_low).toBe(40);
  });

  it("describes each source's window in its own terms", () => {
    expect(windowLabel("rolling", 7)).toBe("7-day recent window");
    expect(windowLabel("season_cumulative", null)).toBe("season to date");
    expect(windowLabel("not_applicable", null)).toBe("no draft window");
    expect(windowLabel(undefined, null)).toBe("");
  });

  it("labels a source rather than printing its id", () => {
    expect(marketLabel(FFC)).toBe("FFC Recent");
    expect(marketLabel(CROSS_MARKET)).toBe("Cross-market");
    expect(marketLabel("some_new_vendor")).toBe("some_new_vendor");
  });
});

describe("the cross-market view", () => {
  it("resolves to a real source rather than a synthetic median row", () => {
    const chosen = comparisonFor(MULTI, CROSS_MARKET);
    expect(chosen).not.toBeNull();
    expect([FFC, MFL]).toContain(chosen?.source_id);
    // Whatever it picks must carry a real cohort and a real snapshot, because the card
    // shows both and neither can be invented.
    expect(chosen?.market_cohort_id).toBeTruthy();
    expect(chosen?.market_snapshot_at_utc).toBeTruthy();
  });

  it("offers the cross view only when two markets actually priced someone", () => {
    expect(crossMarketAvailable([MULTI])).toBe(true);
    const single = record({
      markets: [comparison({ source_id: FFC })],
      cross_market: {
        sources_available: [FFC],
        market_adp_min: 50,
        market_adp_max: 50,
        market_adp_median: 50,
        market_disagreement_range: 0,
        cheapest_market_source: FFC,
        most_expensive_market_source: FFC,
      },
    });
    expect(crossMarketAvailable([single])).toBe(false);
  });

  it("reports no disagreement rather than zero when only one market spoke", () => {
    const single = record({
      cross_market: {
        sources_available: [FFC],
        market_adp_min: 50,
        market_adp_max: 50,
        market_adp_median: 50,
        market_disagreement_range: 0,
        cheapest_market_source: FFC,
        most_expensive_market_source: FFC,
      },
    });
    expect(disagreementFor(single)).toBeNull();
    expect(disagreementFor(MULTI)).toBe(8);
  });

  it("says which market drafts him earliest in a drafter's words", () => {
    const text = crossMarketSummaryText(MULTI.cross_market ?? null);
    expect(text).toContain("8.0 picks");
    expect(text).toContain("MFL Cumulative (earliest)");
    expect(text).toContain("FFC Recent (latest)");
  });

  it("has something truthful to say when nothing priced him", () => {
    expect(crossMarketSummaryText(null)).toBe("No market priced him.");
  });
});

describe("degrading to a Release 1 bundle", () => {
  const legacy = record();

  it("still offers the single source the row names", () => {
    expect(selectableMarkets([legacy])).toEqual([MFL]);
  });

  it("falls back to the Release 1 fields for that source", () => {
    expect(adpFor(legacy, MFL)).toBe(53);
    expect(gapFor(legacy, MFL)).toBe(11);
  });

  it("reports nothing for a source the row does not carry", () => {
    expect(adpFor(legacy, FFC)).toBeNull();
    expect(gapFor(legacy, FFC)).toBeNull();
    expect(consensusOf(legacy)).toBeNull();
    expect(disagreementFor(legacy)).toBeNull();
  });

  it("treats a row with no surface fields as an ordinary board member", () => {
    expect(isSurfaceException(legacy)).toBe(false);
  });
});

describe("the surface exception", () => {
  it("marks a player the market surfaced from beyond the tier depth", () => {
    const surfaced = record({
      fair_rank: 640,
      surface_reasons: ["market_top300_ffc_adp"],
      outside_tier_board: true,
    });
    expect(isSurfaceException(surfaced)).toBe(true);
    // His fair rank is the model's, unchanged. Market relevance decided visibility only.
    expect(surfaced.fair_rank).toBe(640);
  });
});


// --------------------------------------------------------------------------------------
// One resolution for the whole card (ADR-081)
// --------------------------------------------------------------------------------------
//
// `marketView` exists because `??` was doing the resolving, and `??` cannot tell "this
// bundle has no markets array" from "this market's answer is null". The first is a Release 1
// artifact and deserves the flat fields; the second is a measurement and deserves to survive.

describe("the selected market view", () => {
  const dual = record({
    market_trend: 0.4,
    markets: [
      comparison({ source_id: FFC, market_adp: 40, rank_gap: -2, market_trend: null }),
      comparison({ source_id: MFL, market_adp: 53, rank_gap: 11, market_trend: 0.4 }),
    ],
  });

  it("takes every number from the selected source", () => {
    const view = marketView(dual, FFC);
    expect(view?.sourceId).toBe(FFC);
    expect(view?.comparison?.market_adp).toBe(40);
    expect(view?.comparison?.rank_gap).toBe(-2);
  });

  it("keeps a selected source's null trend null, whatever the other source says", () => {
    // The flat field and the other market both carry 0.4. Neither may reach this view.
    expect(dual.market_trend).toBe(0.4);
    expect(marketView(dual, FFC)?.trend).toBeNull();
    expect(marketView(dual, MFL)?.trend).toBe(0.4);
  });

  it("has no scalar trend at all under the cross-market view", () => {
    const view = marketView(dual, CROSS_MARKET);
    expect(view?.cross).toBe(true);
    expect(view?.trendIsScalar).toBe(false);
    // ...and it does not quietly become the resolved source's slope either.
    expect(view?.trend).toBeNull();
  });

  it("reports nothing when the selected market did not price him", () => {
    const single = record({
      markets: [comparison({ source_id: MFL, market_adp: 53, market_trend: 0.4 })],
    });
    const view = marketView(single, FFC);
    expect(view?.comparison).toBeNull();
    expect(view?.sourceId).toBeNull();
    expect(view?.trend).toBeNull();
  });

  it("lifts a Release 1 row's flat fields into the same shape, once", () => {
    const legacy = record();
    const view = marketView(legacy, MFL);
    expect(view?.sourceId).toBe(MFL);
    expect(view?.comparison?.market_adp).toBe(53);
    expect(view?.comparison?.rank_gap).toBe(11);
    // A source that bundle never carried is still absent, not filled in.
    expect(marketView(legacy, FFC)?.comparison).toBeNull();
  });

  it("gives the table the same source's trend as its price and gap", () => {
    expect(trendFor(dual, FFC)).toBeNull();
    expect(trendFor(dual, MFL)).toBe(0.4);
    // Under cross, the trend comes from whichever source the ADP and gap came from.
    expect(sourceFor(dual, CROSS_MARKET)).toBe(adpFor(dual, CROSS_MARKET) === 40 ? FFC : MFL);
    expect(trendFor(dual, CROSS_MARKET)).toBe(
      sourceFor(dual, CROSS_MARKET) === FFC ? null : 0.4,
    );
  });
});

describe("which histories a selection draws", () => {
  function history(sourceId: string): MarketTrendSeriesRecord {
    return {
      schema_version: "1.0",
      build_id: "b",
      market_source_id: sourceId,
      scoring_preset: "HALF",
      league_preset_id: "redraft-12",
      player_id: "gsis:1",
      cohort_id: "c",
      window_days: 7,
      market_trend: null,
      points: [{ observed_at: "2026-09-05T12:00:00Z", market_adp: 40 }],
    };
  }

  const all = [history(MFL), history(FFC)];

  it("draws only the selected source's history", () => {
    expect(historiesFor(all, FFC).map((entry) => entry.market_source_id)).toEqual([FFC]);
    expect(historiesFor(all, MFL).map((entry) => entry.market_source_id)).toEqual([MFL]);
  });

  it("draws every source under cross, in selector order", () => {
    expect(historiesFor(all, CROSS_MARKET).map((entry) => entry.market_source_id)).toEqual([
      FFC,
      MFL,
    ]);
  });

  it("draws nothing rather than another market's line when the selected one has none", () => {
    expect(historiesFor([history(MFL)], FFC)).toEqual([]);
  });

  it("never draws a `cross` record, because no capture produces one", () => {
    const planted = [...all, history(CROSS_MARKET)];
    expect(historiesFor(planted, CROSS_MARKET).map((entry) => entry.market_source_id)).toEqual([
      FFC,
      MFL,
    ]);
    expect(historiesFor(planted, CROSS_MARKET)).toHaveLength(2);
  });
});
