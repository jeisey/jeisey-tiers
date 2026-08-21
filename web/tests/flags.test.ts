/**
 * Quality-flag explanations.
 *
 * Two properties: every flag the build actually publishes has a sentence, and a flag this
 * release has never seen still renders rather than vanishing. A badge that silently disappears
 * when a build adds a check is worse than one that shows a raw identifier.
 */

import { describe, expect, it } from "vitest";

import {
  FLAG_EXPLANATIONS,
  NON_DISCRIMINATING_FLAGS,
  explainFlag,
  explainFlags,
  rowLevelMarketFlags,
} from "../src/data/flags";
import { arbitrageRecords, tierRecords } from "./fixtures/artifacts";

describe("explainFlag", () => {
  it("explains every flag the fixture build publishes", () => {
    const published = new Set([
      ...arbitrageRecords().flatMap((record) => record.quality_flags),
      ...tierRecords().flatMap((record) => record.quality_flags),
    ]);
    for (const flag of published) {
      expect(Object.keys(FLAG_EXPLANATIONS)).toContain(flag);
    }
  });

  it("explains the production flags the Phase-5 build emitted", () => {
    for (const flag of [
      "cohort_approximate",
      "cohort_insufficient",
      "insufficient_trend_history",
      "low_market_sample",
      "secondary_identity_bridge_only",
      "wide_market_range",
      "market_snapshot_stale",
      "rookie",
      "no_prior_season_stats",
      "no_depth_context",
      "no_current_roster_entry",
      "current_status_reserve",
      "sleeper_record_missing",
      "sleeper_identity_conflict",
    ]) {
      expect(explainFlag(flag).detail.length).toBeGreaterThan(20);
    }
  });

  it("says what cohort_insufficient is about, and what it is not about", () => {
    const detail = explainFlag("cohort_insufficient").detail;
    expect(detail).toContain("market sample");
    expect(detail).toContain("not the player");
  });

  it("falls back readably for a flag it has never seen", () => {
    const unknown = explainFlag("some_future_check");
    expect(unknown.label).toBe("some_future_check");
    expect(unknown.detail).toContain("does not have a description");
  });

  it("keeps the flag identifier alongside each explanation", () => {
    expect(explainFlags(["rookie", "mystery"]).map((entry) => entry.flag)).toEqual([
      "rookie",
      "mystery",
    ]);
  });
});

describe("row-level flag filtering", () => {
  it("suppresses wide_market_range from per-row display", () => {
    // It fires on roughly 90% of the production board, which makes it true and
    // non-discriminating: as a per-row badge it is noise (ADR-041).
    expect(NON_DISCRIMINATING_FLAGS).toContain("wide_market_range");
    expect(
      rowLevelMarketFlags(["wide_market_range", "low_market_sample"], new Set()),
    ).toEqual(["low_market_sample"]);
  });

  it("suppresses a flag every row shares, because it belongs to the build", () => {
    const shared = new Set(["cohort_insufficient", "cohort_approximate"]);
    expect(
      rowLevelMarketFlags(
        ["cohort_insufficient", "cohort_approximate", "secondary_identity_bridge_only"],
        shared,
      ),
    ).toEqual(["secondary_identity_bridge_only"]);
  });

  it("keeps a flag that genuinely distinguishes this row", () => {
    expect(rowLevelMarketFlags(["low_market_sample"], new Set())).toEqual(["low_market_sample"]);
  });
});
