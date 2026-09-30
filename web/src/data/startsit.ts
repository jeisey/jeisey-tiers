/**
 * The start/sit arithmetic: seven published quantiles in, the answers a lineup decision needs
 * out (ADR-096).
 *
 * **One definition, two implementations.** `ffdraft.weekly.distribution` is the Python half,
 * and the development and holdout evaluations were scored with it. This file is the page's
 * half, and `web/tests/startsit.test.ts` holds it to a golden vector the Python side wrote, so
 * the probability printed here is the probability that was evaluated — not a re-derivation
 * that happens to look similar.
 *
 * `quantile_distribution_v1`:
 *
 * 1. **Knots** — the seven levels plus a knot at 0 and at 1, each a linear extension of the
 *    adjacent segment (lower once its width, upper twice, because weekly points are
 *    right-skewed). The factors travel on the build metadata, never as constants here.
 * 2. **Grid** — the piecewise-linear inverse CDF read at `M` midpoints `(i + 0.5) / M`.
 * 3. **P(A > B)** — for every grid point of A, the grid points of B strictly below plus half
 *    of those equal, over `M²`. Exact for the discretised pair; ties counted half.
 * 4. **Win probability** — `mean_i Φ((μ + x_i) / σ)`, where `μ` is the matchup margin from
 *    every other slot and `σ` the measured uncertainty of that margin.
 *
 * Two refinements are the page's own and are labelled wherever they apply: a same-game
 * correlation (a Gaussian copula over the same grid, with the measured `ρ`) and the
 * multi-way "best of the set" probability (a fixed Halton point set, so it is deterministic).
 *
 * **Nothing here invents a player value.** Every input is a published quantile, a published
 * measurement, or the reader's own margin.
 */

import type {
  RosWeeklyMetadata,
  WeeklyProjectionRecord,
  WeeklyQuantileKey,
} from "./contracts";
import { WEEKLY_QUANTILE_KEYS } from "./contracts";

/** Bump when how a quantile set becomes a decision changes. */
export const STARTSIT_PRESENTATION_VERSION = "startsit_presentation_v1";

export interface DistributionRule {
  readonly levels: readonly number[];
  readonly tailLowerFactor: number;
  readonly tailUpperFactor: number;
  readonly gridPoints: number;
}

/** The rule as the build published it; the defaults are the frozen v1 values. */
export function distributionRule(weekly: RosWeeklyMetadata | null | undefined): DistributionRule {
  return {
    levels: weekly?.quantile_levels ?? [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95],
    tailLowerFactor: weekly?.distribution_rule.tail_lower_factor ?? 1,
    tailUpperFactor: weekly?.distribution_rule.tail_upper_factor ?? 2,
    gridPoints: weekly?.distribution_rule.grid_points ?? 200,
  };
}

export function quantileValues(record: WeeklyProjectionRecord): number[] | null {
  const quantiles = record.quantiles;
  if (quantiles === null) return null;
  return WEEKLY_QUANTILE_KEYS.map((key: WeeklyQuantileKey) => quantiles[key]);
}

/** `(probabilities, values)` including both tail knots; values sorted. */
export function knots(
  quantiles: readonly number[],
  rule: DistributionRule,
): { readonly taus: number[]; readonly values: number[] } {
  if (quantiles.length !== rule.levels.length) {
    throw new Error(`expected ${String(rule.levels.length)} quantiles`);
  }
  const values = [...quantiles].sort((a, b) => a - b);
  const first = values[0] ?? 0;
  const second = values[1] ?? first;
  const last = values[values.length - 1] ?? 0;
  const penultimate = values[values.length - 2] ?? last;
  const lower = first - rule.tailLowerFactor * (second - first);
  const upper = last + rule.tailUpperFactor * (last - penultimate);
  return { taus: [0, ...rule.levels, 1], values: [lower, ...values, upper] };
}

/** `numpy.interp` semantics: clamp outside, linear inside, `xs` ascending. */
export function interp(x: number, xs: readonly number[], ys: readonly number[]): number {
  const n = xs.length;
  const x0 = xs[0] ?? 0;
  const xn = xs[n - 1] ?? 0;
  if (x <= x0) return ys[0] ?? 0;
  if (x >= xn) return ys[n - 1] ?? 0;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((xs[mid] ?? 0) <= x) lo = mid;
    else hi = mid;
  }
  const xa = xs[lo] ?? 0;
  const xb = xs[hi] ?? 0;
  const ya = ys[lo] ?? 0;
  const yb = ys[hi] ?? 0;
  if (xb === xa) return ya;
  return ya + ((x - xa) * (yb - ya)) / (xb - xa);
}

/** The distribution as `gridPoints` equally likely values, ascending. */
export function gridFromQuantiles(quantiles: readonly number[], rule: DistributionRule): Float64Array {
  const { taus, values } = knots(quantiles, rule);
  const grid = new Float64Array(rule.gridPoints);
  for (let i = 0; i < rule.gridPoints; i += 1) {
    grid[i] = interp((i + 0.5) / rule.gridPoints, taus, values);
  }
  return grid;
}

function lowerBound(sorted: Float64Array, value: number): number {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((sorted[mid] ?? 0) < value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function upperBound(sorted: Float64Array, value: number): number {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((sorted[mid] ?? 0) <= value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** P(A outscores B), independent, ties counted half. Identical to the Python evaluation. */
export function probGreater(gridA: Float64Array, gridB: Float64Array): number {
  let total = 0;
  for (const value of gridA) {
    const below = lowerBound(gridB, value);
    const atOrBelow = upperBound(gridB, value);
    total += below + 0.5 * (atOrBelow - below);
  }
  return total / (gridA.length * gridB.length);
}

// ------------------------------------------------------------------- the normal distribution

/** erf, Abramowitz & Stegun 7.1.26 refined (max error ~1.2e-7). */
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const z = Math.abs(x);
  const t = 1 / (1 + 0.5 * z);
  const y =
    1 -
    t *
      Math.exp(
        -z * z -
          1.26551223 +
          t *
            (1.00002368 +
              t *
                (0.37409196 +
                  t *
                    (0.09678418 +
                      t *
                        (-0.18628806 +
                          t *
                            (0.27886807 +
                              t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))),
      );
  return sign * y;
}

export function normalCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

/** Acklam's inverse normal CDF (relative error < 1.2e-9). */
export function normalQuantile(p: number): number {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const low = 0.02425;
  const at = (xs: number[], i: number): number => xs[i] ?? 0;
  if (p < low) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (
      (((((at(c, 0) * q + at(c, 1)) * q + at(c, 2)) * q + at(c, 3)) * q + at(c, 4)) * q + at(c, 5)) /
      ((((at(d, 0) * q + at(d, 1)) * q + at(d, 2)) * q + at(d, 3)) * q + 1)
    );
  }
  if (p > 1 - low) {
    const q = Math.sqrt(-2 * Math.log(1 - p));
    return -(
      (((((at(c, 0) * q + at(c, 1)) * q + at(c, 2)) * q + at(c, 3)) * q + at(c, 4)) * q + at(c, 5)) /
      ((((at(d, 0) * q + at(d, 1)) * q + at(d, 2)) * q + at(d, 3)) * q + 1)
    );
  }
  const q = p - 0.5;
  const r = q * q;
  return (
    ((((((at(a, 0) * r + at(a, 1)) * r + at(a, 2)) * r + at(a, 3)) * r + at(a, 4)) * r + at(a, 5)) * q) /
    (((((at(b, 0) * r + at(b, 1)) * r + at(b, 2)) * r + at(b, 3)) * r + at(b, 4)) * r + 1)
  );
}

/**
 * P(A outscores B) when their outcomes are correlated (Gaussian copula, correlation `rho`).
 *
 * Only for two players in the same game, with the measured `rho`. At `rho = 0` this defers to
 * the independent function so the two can never disagree about an unrelated pair.
 */
export function probGreaterCorrelated(
  quantilesA: readonly number[],
  quantilesB: readonly number[],
  rho: number,
  rule: DistributionRule,
): number {
  const gridA = gridFromQuantiles(quantilesA, rule);
  if (rho === 0) return probGreater(gridA, gridFromQuantiles(quantilesB, rule));
  const { taus, values } = knots(quantilesB, rule);
  const m = rule.gridPoints;
  const z = new Float64Array(m);
  for (let i = 0; i < m; i += 1) z[i] = normalQuantile((i + 0.5) / m);
  const scale = Math.sqrt(1 - rho * rho);
  let total = 0;
  for (let i = 0; i < m; i += 1) {
    const xa = gridA[i] ?? 0;
    const zi = z[i] ?? 0;
    for (let j = 0; j < m; j += 1) {
      const xb = interp(normalCdf(rho * zi + scale * (z[j] ?? 0)), taus, values);
      total += xa > xb ? 1 : xa === xb ? 0.5 : 0;
    }
  }
  return total / (m * m);
}

/** P(the matchup is won) when this player fills the slot. */
export function winProbability(grid: Float64Array, margin: number, sigma: number): number {
  let total = 0;
  for (const value of grid) total += normalCdf((margin + value) / sigma);
  return total / grid.length;
}

/** P(a week at or above `threshold`), read off the same grid. */
export function probAtLeast(grid: Float64Array, threshold: number): number {
  const below = lowerBound(grid, threshold);
  return (grid.length - below) / grid.length;
}

/**
 * The margin at which starting A and starting B win equally often, or null when one of them
 * is the better start at every margin in `[-range, range]`.
 *
 * This is the reading no ranking can give: *how far behind* a manager has to be before the
 * player with the higher ceiling becomes the right start. Bisection on a function that is
 * smooth in the margin; deterministic.
 */
export function flipMargin(
  gridA: Float64Array,
  gridB: Float64Array,
  sigma: number,
  range = 45,
): number | null {
  const gap = (margin: number): number =>
    winProbability(gridA, margin, sigma) - winProbability(gridB, margin, sigma);
  const steps = 90;
  let previousMargin = -range;
  let previous = gap(previousMargin);
  for (let step = 1; step <= steps; step += 1) {
    const margin = -range + (2 * range * step) / steps;
    const current = gap(margin);
    if (previous === 0) return previousMargin;
    if (Math.sign(current) !== Math.sign(previous)) {
      let lo = previousMargin;
      let hi = margin;
      let atLo = previous;
      for (let iteration = 0; iteration < 40; iteration += 1) {
        const mid = (lo + hi) / 2;
        const atMid = gap(mid);
        if (Math.sign(atMid) === Math.sign(atLo)) {
          lo = mid;
          atLo = atMid;
        } else {
          hi = mid;
        }
      }
      return (lo + hi) / 2;
    }
    previousMargin = margin;
    previous = current;
  }
  return null;
}

// ------------------------------------------------------------------- the multi-way question

const HALTON_BASES = [2, 3, 5, 7] as const;

function halton(index: number, base: number): number {
  let result = 0;
  let fraction = 1 / base;
  let i = index;
  while (i > 0) {
    result += fraction * (i % base);
    i = Math.floor(i / base);
    fraction /= base;
  }
  return result;
}

/** Lower-triangular Cholesky factor, or null when the matrix is not positive definite. */
function cholesky(matrix: readonly (readonly number[])[]): number[][] | null {
  const n = matrix.length;
  const lower = Array.from({ length: n }, () => new Array<number>(n).fill(0));
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j <= i; j += 1) {
      let sum = matrix[i]?.[j] ?? 0;
      for (let k = 0; k < j; k += 1) sum -= (lower[i]?.[k] ?? 0) * (lower[j]?.[k] ?? 0);
      const row = lower[i];
      if (row === undefined) return null;
      if (i === j) {
        if (sum <= 0) return null;
        row[j] = Math.sqrt(sum);
      } else {
        row[j] = sum / (lower[j]?.[j] ?? 1);
      }
    }
  }
  return lower;
}

/**
 * P(each player is the set's top scorer), for two to four players. Ties split evenly.
 *
 * A fixed Halton point set of `points` draws (bases 2, 3, 5, 7, skipping the origin), so the
 * answer is the same on every reload. Correlations are the measured same-game ones; players
 * in different games are independent. A correlation matrix that is not positive definite
 * falls back to independence rather than to an arbitrary repair.
 */
export function bestOfSet(
  quantileSets: readonly (readonly number[])[],
  correlation: readonly (readonly number[])[] | null,
  rule: DistributionRule,
  points = 4096,
): number[] {
  const count = quantileSets.length;
  if (count === 0) return [];
  if (count > HALTON_BASES.length) throw new Error("at most four players");
  const knotSets = quantileSets.map((quantiles) => knots(quantiles, rule));
  const factor = correlation === null ? null : cholesky(correlation);
  const wins = new Array<number>(count).fill(0);
  const z = new Array<number>(count).fill(0);
  const x = new Array<number>(count).fill(0);
  for (let draw = 1; draw <= points; draw += 1) {
    for (let k = 0; k < count; k += 1) {
      z[k] = normalQuantile(halton(draw, HALTON_BASES[k] ?? 2));
    }
    for (let k = 0; k < count; k += 1) {
      let value = z[k] ?? 0;
      if (factor !== null) {
        value = 0;
        for (let j = 0; j <= k; j += 1) value += (factor[k]?.[j] ?? 0) * (z[j] ?? 0);
      }
      const set = knotSets[k];
      x[k] = set === undefined ? 0 : interp(normalCdf(value), set.taus, set.values);
    }
    let best = -Infinity;
    for (const value of x) best = Math.max(best, value);
    const leaders = x.filter((value) => value === best).length;
    x.forEach((value, k) => {
      if (value === best) wins[k] = (wins[k] ?? 0) + 1 / leaders;
    });
  }
  return wins.map((value) => value / points);
}

// ------------------------------------------------------------------- reading the metadata

/**
 * The measured correlation for two players, or zero when they do not share a game.
 *
 * Teammates are keyed by their positions in alphabetical order (`teammates:QB-WR`), opponents
 * by `opponents:any`. A pair the build did not measure — too few rows — is treated as
 * independent and the page says so.
 */
export function pairCorrelation(
  a: WeeklyProjectionRecord,
  b: WeeklyProjectionRecord,
  weekly: RosWeeklyMetadata | null | undefined,
): { readonly rho: number; readonly key: string | null; readonly measured: boolean } {
  const game = a.game?.game_id ?? null;
  if (game === null || game !== (b.game?.game_id ?? null)) {
    return { rho: 0, key: null, measured: false };
  }
  const pairs = weekly?.correlation.pairs ?? {};
  const key =
    a.team === b.team
      ? `teammates:${[a.position, b.position].sort().join("-")}`
      : "opponents:any";
  const entry = pairs[key];
  return entry === undefined
    ? { rho: 0, key, measured: false }
    : { rho: entry.rho, key, measured: true };
}

/** The margin uncertainty for a slot the chosen players could fill. */
export function marginSigma(
  weekly: RosWeeklyMetadata | null | undefined,
  scoring: string,
  positions: readonly string[],
): number | null {
  const bySlot = weekly?.margin[scoring]?.margin_sd_by_slot;
  if (bySlot === undefined || positions.length === 0) return null;
  const values = positions
    .map((position) => bySlot[position])
    .filter((value): value is number => typeof value === "number" && value > 0);
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

/** The points a startable week at this position takes, in this league and scoring. */
export function startableThreshold(
  weekly: RosWeeklyMetadata | null | undefined,
  leaguePreset: string,
  scoring: string,
  position: string,
): number | null {
  const value = weekly?.startable[leaguePreset]?.[scoring]?.[position];
  return typeof value === "number" ? value : null;
}

/** How often players carrying this designation actually appeared, or null. */
export function designationRate(
  weekly: RosWeeklyMetadata | null | undefined,
  designation: string | null | undefined,
): { readonly rate: number; readonly reports: number } | null {
  if (designation === null || designation === undefined) return null;
  const entry = weekly?.injury_base_rates[designation];
  if (entry === undefined || !("appearance_rate" in entry) || entry.appearance_rate === null) {
    return null;
  }
  return { rate: entry.appearance_rate, reports: entry.reports };
}

/** A probability as the page words it. Never "certain": the grid cannot express certainty. */
export function confidenceWord(probability: number): "Coin flip" | "Lean" | "Clear" | "Strong" {
  const edge = Math.abs(probability - 0.5);
  if (edge < 0.05) return "Coin flip";
  if (edge < 0.12) return "Lean";
  if (edge < 0.22) return "Clear";
  return "Strong";
}
