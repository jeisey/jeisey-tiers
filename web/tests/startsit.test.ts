/**
 * The start/sit arithmetic (ADR-096), held to the Python half through a shared golden vector.
 *
 * `tests/fixtures/weekly/distribution_golden.json` was written by `ffdraft.weekly.distribution`,
 * the code the development and holdout evaluations were scored with. `tests/unit/
 * test_weekly_distribution.py` holds Python to the same bytes. A change on either side that
 * moves a probability fails one of the two.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  bestOfSet,
  confidenceWord,
  distributionRule,
  flipMargin,
  gridFromQuantiles,
  knots,
  normalCdf,
  normalQuantile,
  probAtLeast,
  probGreater,
  probGreaterCorrelated,
  winProbability,
} from "../src/data/startsit";

interface Golden {
  readonly rule: {
    readonly levels: number[];
    readonly tail_lower_factor: number;
    readonly tail_upper_factor: number;
    readonly grid_points: number;
  };
  readonly cases: Record<string, number[]>;
  readonly grid_samples: Record<string, number[]>;
  readonly prob_greater: { readonly a: string; readonly b: string; readonly p: number }[];
  readonly win_probability: {
    readonly case: string;
    readonly margin: number;
    readonly sigma: number;
    readonly p: number;
  }[];
}

const GOLDEN: Golden = JSON.parse(
  readFileSync(resolve(__dirname, "../../tests/fixtures/weekly/distribution_golden.json"), "utf-8"),
) as Golden;

const RULE = distributionRule(null);

function quantilesOf(name: string): number[] {
  const values = GOLDEN.cases[name];
  if (values === undefined) throw new Error(`no golden case ${name}`);
  return values;
}

describe("quantile_distribution_v1 against the Python golden vector", () => {
  it("uses the rule the Python side wrote", () => {
    expect(RULE.levels).toEqual(GOLDEN.rule.levels);
    expect(RULE.tailLowerFactor).toBe(GOLDEN.rule.tail_lower_factor);
    expect(RULE.tailUpperFactor).toBe(GOLDEN.rule.tail_upper_factor);
    expect(RULE.gridPoints).toBe(GOLDEN.rule.grid_points);
  });

  it("builds the same grid, point for point", () => {
    for (const [name, sample] of Object.entries(GOLDEN.grid_samples)) {
      const grid = gridFromQuantiles(quantilesOf(name), RULE);
      [0, 9, 99, 100, 189, 199].forEach((index, position) => {
        expect(grid[index]).toBeCloseTo(sample[position] ?? Number.NaN, 9);
      });
    }
  });

  it("computes the same head-to-head probability, exactly", () => {
    for (const row of GOLDEN.prob_greater) {
      const p = probGreater(
        gridFromQuantiles(quantilesOf(row.a), RULE),
        gridFromQuantiles(quantilesOf(row.b), RULE),
      );
      expect(Math.abs(p - row.p)).toBeLessThan(1e-12);
    }
  });

  it("computes the same win probability, to the normal CDF's precision", () => {
    for (const row of GOLDEN.win_probability) {
      const p = winProbability(gridFromQuantiles(quantilesOf(row.case), RULE), row.margin, row.sigma);
      expect(Math.abs(p - row.p)).toBeLessThan(1e-6);
    }
  });
});

describe("the distribution", () => {
  const steady = quantilesOf("steady_rb");
  const boom = quantilesOf("boom_wr");

  it("extends the lower tail once and the upper tail twice", () => {
    const { taus, values } = knots(steady, RULE);
    expect(taus[0]).toBe(0);
    expect(taus[taus.length - 1]).toBe(1);
    expect(values[0]).toBeCloseTo(7.07 - (8.43 - 7.07), 9);
    expect(values[values.length - 1]).toBeCloseTo(20.67 + 2 * (20.67 - 19.04), 9);
  });

  it("is complementary, and even against itself", () => {
    const a = gridFromQuantiles(steady, RULE);
    const b = gridFromQuantiles(boom, RULE);
    expect(probGreater(a, b) + probGreater(b, a)).toBeCloseTo(1, 12);
    expect(probGreater(a, a)).toBeCloseTo(0.5, 12);
  });

  it("reads a startable probability off the same grid", () => {
    const grid = gridFromQuantiles(steady, RULE);
    expect(probAtLeast(grid, -100)).toBe(1);
    expect(probAtLeast(grid, 1000)).toBe(0);
    expect(probAtLeast(grid, 13.6)).toBeCloseTo(0.5, 1);
  });

  it("inverts its own normal CDF", () => {
    for (const p of [0.001, 0.02, 0.2, 0.5, 0.8, 0.98, 0.999]) {
      expect(normalCdf(normalQuantile(p))).toBeCloseTo(p, 6);
    }
  });
});

describe("the reading only this tab gives", () => {
  const steady = gridFromQuantiles(quantilesOf("steady_rb"), RULE);
  const boom = gridFromQuantiles(quantilesOf("boom_wr"), RULE);
  const sigma = 31.4;

  it("starts the steady player when ahead and the boom player when behind", () => {
    expect(probGreater(steady, boom)).toBeGreaterThan(0.5);
    expect(winProbability(boom, -25, sigma)).toBeGreaterThan(winProbability(steady, -25, sigma));
    expect(winProbability(steady, 25, sigma)).toBeGreaterThan(winProbability(boom, 25, sigma));
  });

  it("finds the margin where the answer flips, and it is where the two win equally often", () => {
    const flip = flipMargin(steady, boom, sigma);
    expect(flip).not.toBeNull();
    const at = flip ?? 0;
    expect(at).toBeLessThan(25);
    expect(at).toBeGreaterThan(-25);
    expect(Math.abs(winProbability(steady, at, sigma) - winProbability(boom, at, sigma))).toBeLessThan(1e-9);
  });

  it("finds no flip when one player dominates at every margin", () => {
    const better = gridFromQuantiles(quantilesOf("steady_rb").map((q) => q + 12), RULE);
    expect(flipMargin(better, steady, sigma)).toBeNull();
  });
});

describe("same-game correlation and the multi-way question", () => {
  const a = quantilesOf("steady_rb");
  const b = quantilesOf("boom_wr");

  it("defers to the independent answer at zero correlation", () => {
    expect(probGreaterCorrelated(a, b, 0, RULE)).toBe(
      probGreater(gridFromQuantiles(a, RULE), gridFromQuantiles(b, RULE)),
    );
  });

  it("moves the head-to-head toward the medians' order as correlation rises", () => {
    // Positively correlated outcomes remove the independent noise, so the higher median wins
    // more often: the copula must move P(steady > boom) up, not down.
    const independent = probGreaterCorrelated(a, b, 0, RULE);
    const correlated = probGreaterCorrelated(a, b, 0.5, RULE);
    expect(correlated).toBeGreaterThan(independent);
    expect(correlated).toBeLessThan(1);
  });

  it("gives probabilities that sum to one and agree with the head-to-head for two", () => {
    const two = bestOfSet([a, b], null, RULE);
    expect(two.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 12);
    const exact = probGreater(gridFromQuantiles(a, RULE), gridFromQuantiles(b, RULE));
    expect(Math.abs((two[0] ?? 0) - exact)).toBeLessThan(0.01);

    const four = bestOfSet([a, b, quantilesOf("qb"), quantilesOf("flat_low")], null, RULE);
    expect(four.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 12);
    expect(four[3]).toBeLessThan(0.02);
  });

  it("is deterministic, and falls back to independence on a matrix that is not positive definite", () => {
    const sets = [a, b, quantilesOf("qb")];
    expect(bestOfSet(sets, null, RULE)).toEqual(bestOfSet(sets, null, RULE));
    const broken = [
      [1, 0.99, -0.99],
      [0.99, 1, 0.99],
      [-0.99, 0.99, 1],
    ];
    expect(bestOfSet(sets, broken, RULE)).toEqual(bestOfSet(sets, null, RULE));
  });

  it("refuses a fifth player", () => {
    expect(() => bestOfSet([a, a, a, a, a], null, RULE)).toThrow("at most four");
  });
});

describe("the words", () => {
  it("never says certain, and calls a near-even pair a coin flip", () => {
    expect(confidenceWord(0.52)).toBe("Coin flip");
    expect(confidenceWord(0.48)).toBe("Coin flip");
    expect(confidenceWord(0.6)).toBe("Lean");
    expect(confidenceWord(0.7)).toBe("Clear");
    expect(confidenceWord(0.95)).toBe("Strong");
    expect(confidenceWord(0.05)).toBe("Strong");
  });
});
