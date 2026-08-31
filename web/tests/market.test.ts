/**
 * Market semantics.
 *
 * Three things this file exists to hold in place, all of them repository decisions rather than
 * presentation preferences:
 *
 * - a null trend is insufficient history, never zero movement (ADR-042);
 * - `confidence` is data quality, never a probability (ADR-041);
 * - a positive rank gap is the bargain direction and is stated in words (ADR-040).
 */

import { describe, expect, it } from "vitest";

import type { ArbitrageRecord, Confidence } from "../src/data/contracts";
import {
  CONFIDENCE_MEANING,
  cohortAssignment,
  describeGap,
  describeTrend,
  explainClause,
  marketHeadline,
  marketSourceLabel,
  summarizeMarket,
} from "../src/data/market";
import { arbitrageRecords, buildMetadata } from "./fixtures/artifacts";

describe("cohort assignment", () => {
  it("reads the assignment for the selected preset", () => {
    const assignment = cohortAssignment(buildMetadata(), "PPR", 12);
    expect(assignment?.cohortId).toBe("no-mock-no-keeper");
    expect(assignment?.exact).toBe(false);
    expect(assignment?.sufficient).toBe(false);
    expect(assignment?.failedClauses).toEqual(["total_drafts 125 < 300"]);
  });

  it("returns null for a preset the build did not price", () => {
    expect(cohortAssignment(buildMetadata(), "PPR", 8)).toBeNull();
  });

  it("survives a build that published no market block at all", () => {
    expect(cohortAssignment(buildMetadata({ market: null }), "PPR", 12)).toBeNull();
  });

  it("treats an assignment with no failed_clauses as an empty list, not undefined", () => {
    // The Phase-1 fixture pipeline writes a leaner assignment block than the production
    // arbitrage build does, and an older retained build predates the field entirely.
    const metadata = buildMetadata();
    const market = metadata.market;
    const lean = {
      ...metadata,
      market: {
        ...market,
        assignments: (market?.assignments ?? []).map((assignment) => {
          const lean: Record<string, unknown> = { ...assignment };
          delete lean.failed_clauses;
          return lean as (typeof assignment);
        }),
      },
    };
    expect(cohortAssignment(lean, "PPR", 12)?.failedClauses).toEqual([]);
  });
});

describe("explainClause", () => {
  it("turns the frozen rule's own words into a sentence without restating the numbers", () => {
    expect(explainClause("total_drafts 125 < 300")).toBe(
      "the cohort holds 125 drafts against the 300 the rule requires",
    );
    expect(explainClause("median_top150_sample_size 20.0 < 25.0")).toContain("20.0");
  });

  it("passes an unrecognized clause through rather than dropping it", () => {
    expect(explainClause("some_future_clause failed")).toBe("some_future_clause failed");
  });
});

describe("summarizeMarket", () => {
  const records = arbitrageRecords().filter(
    (record) => record.league_preset_id === "redraft-12" && record.scoring_preset === "PPR",
  );

  it("detects that every row shares one confidence label", () => {
    const summary = summarizeMarket(buildMetadata(), records, "PPR", 12);
    expect(summary.uniform).toBe("low");
    expect(summary.confidenceCounts.low).toBe(records.length);
    expect(summary.confidenceCounts.high).toBe(0);
  });

  it("computes the per-player median sample size from the rows in scope", () => {
    const summary = summarizeMarket(buildMetadata(), records, "PPR", 12);
    const samples = records
      .map((record) => record.market_sample_size ?? 0)
      .sort((a, b) => a - b);
    const middle = Math.floor(samples.length / 2);
    const expected =
      samples.length % 2 === 1
        ? samples[middle]
        : ((samples[middle - 1] ?? 0) + (samples[middle] ?? 0)) / 2;
    expect(summary.medianSampleSize).toBe(expected);
  });

  it("reports no uniform label when the rows disagree", () => {
    const mixed = [
      { ...records[0], confidence: "low" } as (typeof records)[number],
      { ...records[1], confidence: "medium" } as (typeof records)[number],
    ];
    expect(summarizeMarket(buildMetadata(), mixed, "PPR", 12).uniform).toBeNull();
  });

  it("carries the trend verdict from metadata rather than inferring it from null rows", () => {
    const summary = summarizeMarket(buildMetadata(), records, "PPR", 12);
    expect(summary.trendAvailable).toBe(false);
    expect(summary.trendSnapshots).toBe(2);
  });

  it("names the dominant label on a mixed board", () => {
    const matured = arbitrageRecords("matured").filter(
      (record) => record.league_preset_id === "redraft-12" && record.scoring_preset === "PPR",
    );
    const summary = summarizeMarket(buildMetadata({}, "matured"), matured, "PPR", 12);
    expect(summary.uniform).toBeNull();
    expect(summary.dominant).toBe("medium");
    expect(summary.confidenceCounts.medium).toBeGreaterThan(summary.confidenceCounts.low);
    expect(summary.confidenceCounts.low).toBeGreaterThan(0);
    expect(summary.trendAvailable).toBe(true);
  });
});

/**
 * The headline is the sentence that used to be a hardcoded launch condition.
 *
 * There is no "normal" branch here on purpose: `low`, `medium`, `high` and a mixed board are
 * all first-class, and the tone follows the evidence rather than a label the code was written
 * around (ADR-052).
 */
describe("marketHeadline", () => {
  const records = arbitrageRecords().filter(
    (record) => record.league_preset_id === "redraft-12" && record.scoring_preset === "PPR",
  );
  const template = records[0];
  if (template === undefined) throw new Error("the fixture published no priced rows");
  const withConfidence = (labels: readonly Confidence[]): ArbitrageRecord[] =>
    labels.map((confidence, index) => ({
      ...template,
      player_id: `synthetic-${String(index)}`,
      confidence,
    }));

  it("warns on a uniformly weak board and says which label", () => {
    const headline = marketHeadline(
      summarizeMarket(buildMetadata(), withConfidence(["low", "low", "low"]), "PPR", 12),
    );
    expect(headline?.tone).toBe("warning");
    expect(headline?.sentence).toMatch(/Every priced row on this board carries low/);
  });

  it("does not warn once the board is uniformly medium or high", () => {
    for (const label of ["medium", "high"] as const) {
      const headline = marketHeadline(
        summarizeMarket(buildMetadata(), withConfidence([label, label]), "PPR", 12),
      );
      expect(headline?.tone).toBe("info");
      expect(headline?.sentence).toContain(label);
    }
  });

  it("counts the labels on a mixed board rather than picking one", () => {
    const headline = marketHeadline(
      summarizeMarket(
        buildMetadata(),
        withConfidence(["medium", "medium", "medium", "low"]),
        "PPR",
        12,
      ),
    );
    expect(headline?.sentence).toContain("3 medium");
    expect(headline?.sentence).toContain("1 low");
    // Dominated by medium, so the panel is informational rather than a warning.
    expect(headline?.tone).toBe("info");
  });

  it("warns when the weak label dominates a mixed board", () => {
    const headline = marketHeadline(
      summarizeMarket(buildMetadata(), withConfidence(["low", "low", "medium"]), "PPR", 12),
    );
    expect(headline?.tone).toBe("warning");
  });

  it("returns nothing for a board with no priced rows", () => {
    expect(marketHeadline(summarizeMarket(buildMetadata(), [], "PPR", 12))).toBeNull();
  });
});

describe("confidence semantics", () => {
  it("describes data quality, not a probability", () => {
    expect(CONFIDENCE_MEANING).toContain("Market-data quality");
    expect(CONFIDENCE_MEANING).toContain("not a probability");
    // The phrase that would make it wrong must not appear.
    expect(CONFIDENCE_MEANING.toLowerCase()).not.toContain("likely");
  });
});

describe("describeTrend", () => {
  it("calls a null trend collecting, never flat and never zero", () => {
    const described = describeTrend(null);
    expect(described.direction).toBe("unknown");
    expect(described.text).toBe("Trend collecting");
    expect(described.text).not.toMatch(/flat|no movement|^0/i);
  });

  it("names the direction in words as well as sign", () => {
    expect(describeTrend(0.8)).toEqual({ text: "Moving earlier (more expensive)", direction: "earlier" });
    expect(describeTrend(-0.8)).toEqual({ text: "Moving later (less expensive)", direction: "later" });
  });

  it("distinguishes a measured zero from a missing measurement", () => {
    expect(describeTrend(0).direction).toBe("flat");
    expect(describeTrend(null).direction).toBe("unknown");
  });
});

describe("describeGap", () => {
  it("calls a positive gap a bargain and says which way the market drafts him", () => {
    const gap = describeGap(14.5);
    expect(gap.kind).toBe("bargain");
    expect(gap.sentence).toBe("The market drafts him 14.5 picks later than his fair rank.");
    expect(gap.compact).toBe("+14.5 picks later");
  });

  it("calls a negative gap a premium", () => {
    const gap = describeGap(-30.14);
    expect(gap.kind).toBe("premium");
    expect(gap.sentence).toBe("The market drafts him 30.1 picks earlier than his fair rank.");
    expect(gap.compact).toContain("picks earlier");
  });

  it("communicates direction without relying on colour", () => {
    // Every branch carries a word; nothing depends on the caller reading a hue.
    for (const value of [12, -12, 0]) {
      expect(describeGap(value).sentence.length).toBeGreaterThan(10);
    }
  });
});

describe("marketSourceLabel", () => {
  it("names MyFantasyLeague explicitly and never says consensus", () => {
    expect(marketSourceLabel("myfantasyleague_adp")).toBe("MyFantasyLeague ADP");
    expect(marketSourceLabel("myfantasyleague_adp").toLowerCase()).not.toContain("consensus");
  });

  it("falls back to the raw id for a source it has no name for", () => {
    expect(marketSourceLabel("something_new")).toBe("something_new");
  });
});
