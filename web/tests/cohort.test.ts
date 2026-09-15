/**
 * `data/cohort` — where one published value sits among its peers.
 *
 * Unit-tested rather than left to a component test because every one of these functions is a
 * claim a reader will act on. "Ninth widest of ninety-six" looks exact whether or not it is,
 * which makes a quiet off-by-one here worse than a visible one anywhere else in the card.
 *
 * The cases below are the ones that actually occur on a board: ties, a degenerate cohort where
 * every row carries the same number, a cohort too small to be one, and a field the build did
 * not publish for this player.
 */

import { describe, expect, it } from "vitest";

import { required } from "./required";
import {
  COHORT_BAND_MINIMUM,
  COHORT_MINIMUM,
  cohortPercent,
  cohortReading,
  cohortStat,
  finiteValues,
  ordinal,
  quantileAt,
} from "../src/data/cohort";

describe("quantileAt", () => {
  it("interpolates linearly, the way NumPy and R type 7 do", () => {
    const sorted = [1, 2, 3, 4];
    expect(quantileAt(sorted, 0)).toBe(1);
    expect(quantileAt(sorted, 1)).toBe(4);
    expect(quantileAt(sorted, 0.5)).toBe(2.5);
    expect(quantileAt(sorted, 0.25)).toBeCloseTo(1.75, 10);
    expect(quantileAt(sorted, 0.75)).toBeCloseTo(3.25, 10);
  });

  it("answers for a single value and refuses an empty array", () => {
    expect(quantileAt([7], 0.5)).toBe(7);
    expect(Number.isNaN(quantileAt([], 0.5))).toBe(true);
  });

  it("clamps a quantile outside [0, 1] rather than running off the array", () => {
    expect(quantileAt([1, 2, 3], -1)).toBe(1);
    expect(quantileAt([1, 2, 3], 4)).toBe(3);
  });
});

describe("finiteValues", () => {
  it("drops nulls, undefined and non-finite numbers — a null is an absence, not a zero", () => {
    expect(finiteValues([1, null, 2, undefined, Number.NaN, Infinity, 3])).toEqual([1, 2, 3]);
  });

  it("keeps a real zero, because a published zero is a reading", () => {
    expect(finiteValues([0, null])).toEqual([0]);
  });
});

describe("cohortStat", () => {
  const values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

  it("ranks descending by default direction, with 1 for the largest", () => {
    expect(cohortStat(values, 100, "desc")?.rank).toBe(1);
    expect(cohortStat(values, 10, "desc")?.rank).toBe(10);
    expect(cohortStat(values, 70, "desc")?.rank).toBe(4);
  });

  it("ranks ascending when asked, with 1 for the smallest", () => {
    expect(cohortStat(values, 10, "asc")?.rank).toBe(1);
    expect(cohortStat(values, 100, "asc")?.rank).toBe(10);
  });

  it("gives tied values the same, better rank", () => {
    // Competition ranking: three players on 50 are all third, and nobody is fourth.
    const tied = [10, 20, 50, 50, 50, 60];
    expect(cohortStat(tied, 50, "desc")?.rank).toBe(2);
    expect(cohortStat(tied, 60, "desc")?.rank).toBe(1);
    expect(cohortStat(tied, 20, "desc")?.rank).toBe(5);
  });

  it("carries its own denominator, counting only the rows that published a value", () => {
    const stat = cohortStat([1, 2, 3, 4], 3, "desc");
    expect(stat?.count).toBe(4);
  });

  it("says nothing at all below the minimum cohort, rather than '1st of 2'", () => {
    expect(cohortStat([5, 9], 9, "desc")).toBeNull();
    expect(cohortStat([], 9, "desc")).toBeNull();
    expect(cohortStat(Array.from({ length: COHORT_MINIMUM }, (_, i) => i), 1, "desc")).not.toBeNull();
  });

  it("says nothing for a value the build did not publish", () => {
    expect(cohortStat(values, null, "desc")).toBeNull();
    expect(cohortStat(values, undefined, "desc")).toBeNull();
    expect(cohortStat(values, Number.NaN, "desc")).toBeNull();
  });

  it("takes its axis from the cohort's own range, so the mark is never off it", () => {
    const stat = required(cohortStat(values, 30, "desc"), "a stat over ten values");
    expect(stat.axisLow).toBe(10);
    expect(stat.axisHigh).toBe(100);
    expect(cohortPercent(stat, 10)).toBe(0);
    expect(cohortPercent(stat, 100)).toBe(100);
  });

  it("takes an absolute axis when the quantity has one, such as a share", () => {
    const shares = [0.1, 0.4, 0.72, 0.9];
    const stat = required(cohortStat(shares, 0.72, "desc", { low: 0, high: 1 }), "a share stat");
    expect(stat.axisLow).toBe(0);
    expect(stat.axisHigh).toBe(1);
    expect(cohortPercent(stat, 0.72)).toBeCloseTo(72, 10);
  });

  it("withholds the quartile band until the cohort is big enough to have quartiles", () => {
    const small = Array.from({ length: COHORT_BAND_MINIMUM - 1 }, (_, index) => index);
    const big = Array.from({ length: COHORT_BAND_MINIMUM }, (_, index) => index);
    expect(cohortStat(small, 1, "desc")?.band).toBeNull();
    expect(cohortStat(big, 1, "desc")?.band).not.toBeNull();
  });

  it("puts the band's own quartiles where the cohort's are", () => {
    const stat = cohortStat(values, 50, "desc");
    expect(stat?.band?.p50).toBeCloseTo(55, 10);
    expect(stat?.band?.p25).toBeCloseTo(32.5, 10);
    expect(stat?.band?.p75).toBeCloseTo(77.5, 10);
  });
});

describe("cohortPercent", () => {
  it("puts the mark in the middle of a degenerate axis rather than dividing by zero", () => {
    // Every row carrying the same number is a real state on a fixture board and on the first
    // week of a real one, and it must not produce NaN in a style attribute.
    const flat = required(cohortStat([4, 4, 4, 4], 4, "desc"), "a stat over a flat cohort");
    expect(cohortPercent(flat, 4)).toBe(50);
  });

  it("clamps a value outside the axis into it", () => {
    const stat = required(
      cohortStat([0, 0.5, 1], 0.5, "desc", { low: 0, high: 1 }),
      "a stat on an absolute axis",
    );
    expect(cohortPercent(stat, -3)).toBe(0);
    expect(cohortPercent(stat, 9)).toBe(100);
  });
});

describe("ordinal", () => {
  it("reads a rank the way a person says it", () => {
    expect(ordinal(1)).toBe("1st");
    expect(ordinal(2)).toBe("2nd");
    expect(ordinal(3)).toBe("3rd");
    expect(ordinal(4)).toBe("4th");
    expect(ordinal(21)).toBe("21st");
    expect(ordinal(102)).toBe("102nd");
  });

  it("gets the teens right, which is the whole reason this is a function", () => {
    expect(ordinal(11)).toBe("11th");
    expect(ordinal(12)).toBe("12th");
    expect(ordinal(13)).toBe("13th");
    expect(ordinal(111)).toBe("111th");
    expect(ordinal(112)).toBe("112th");
  });
});

describe("cohortReading", () => {
  const stat = required(cohortStat([1, 2, 3, 4, 5], 4, "desc"), "a stat over five values");

  it("always names the population, because a rank without one looks like a board rank", () => {
    expect(cohortReading(stat, "WRs")).toBe("2nd of 5 WRs");
  });

  it("takes a qualifier where the direction is not obvious from the name", () => {
    expect(cohortReading(stat, "WRs", "widest")).toBe("2nd widest of 5 WRs");
  });

  it("treats an empty qualifier as none, rather than printing a double space", () => {
    expect(cohortReading(stat, "RBs", "")).toBe("2nd of 5 RBs");
  });
});
