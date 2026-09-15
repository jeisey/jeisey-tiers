/**
 * Where one published value sits among its peers on the same published board.
 *
 * **This is a description of an artifact, not an estimate.** Nothing here models anything,
 * predicts anything or blends two quantities: every function takes numbers the build already
 * published and answers *how many of them are above this one*. That distinction is the whole
 * reason the module can exist at all — `AGENTS.md` section 11 requires every value shown in
 * the UI to originate from a versioned public artifact contract, and a rank among the rows of
 * one artifact is arithmetic over those rows rather than a new quantity beside them.
 *
 * It exists because a bare number with no scale is not a reading. `ROS uncertainty 82.1` tells
 * a reader nothing: 82.1 of what, against what, is that a lot? The same 82.1 stated as *the
 * ninth-widest interval of the ninety-six wide receivers on this board* is the same published
 * number and an actual answer.
 *
 * Four rules, each of which is a thing that would otherwise go quietly wrong:
 *
 * 1. **The denominator is always carried.** A `CohortStat` holds its own `count`, and every
 *    surface that draws one prints it. `docs/UX_SPEC.md` section 7.1A already requires this of
 *    a bar; a rank without its population is worse, because it looks exact.
 * 2. **A rank, never a percentile.** "Ninth of ninety-six" is a fact about a finite list.
 *    "Ninety-first percentile" implies a distribution that a board of published rows is not,
 *    and would need a sample-size caveat this product would then have to keep repeating.
 * 3. **Ties share the better rank.** Competition ranking, so two identical values cannot be
 *    ordered by an accident of the sort.
 * 4. **A cohort too small to say anything says nothing.** Below `COHORT_MINIMUM` there is no
 *    stat at all, rather than a confident "1st of 2".
 *
 * The axis is the cohort's own minimum and maximum unless a caller names one. That is
 * deliberate and it is the opposite of `movesBound`'s rule next door: an add count has a
 * pathological tail (one waiver pickup carries a million transactions) and has to be bounded
 * by a percentile, whereas a VORP, an interval width or a points-per-game over one position
 * does not, and cropping those would move a mark away from the value it stands for. Where a
 * quantity has a natural absolute scale — a share is 0 to 1 — the caller passes it.
 */

/** Bump when the meaning of a cohort reading changes. Stated wherever one is drawn. */
export const COHORT_RULE_VERSION = "cohort_context_v1";

/**
 * The smallest cohort that gets a reading at all.
 *
 * Three is the floor because "2nd of 2" is a coin toss wearing a number. It is low rather than
 * statistically comfortable on purpose: this is a *rank in a named list*, not an estimate, so
 * the honest bar is "is there a list", and the printed denominator lets the reader judge the
 * rest. A fixture board carries three quarterbacks and a production board carries ninety-six
 * wide receivers; both are true statements about their own board.
 */
export const COHORT_MINIMUM = 3;

/**
 * The cohort's own quartiles, drawn as a band with a tick.
 *
 * Null below `COHORT_BAND_MINIMUM`, where a quartile is two values pretending to be a
 * distribution. The mark and the rank still render; only the band behind them is withheld.
 */
export const COHORT_BAND_MINIMUM = 8;

export interface CohortBand {
  readonly p25: number;
  readonly p50: number;
  readonly p75: number;
}

export interface CohortStat {
  /** This player's published value, unchanged. */
  readonly value: number;
  /** How many rows in the cohort carried a value for this field. The printed denominator. */
  readonly count: number;
  /** 1-based competition rank, in the order the caller asked for. Ties share the better rank. */
  readonly rank: number;
  readonly axisLow: number;
  readonly axisHigh: number;
  /** The cohort's middle half, or null when the cohort is too small to have one. */
  readonly band: CohortBand | null;
}

/** Ascending order means rank 1 is the smallest value; descending means it is the largest. */
export type CohortOrder = "asc" | "desc";

/**
 * The linear-interpolated quantile of an already-sorted ascending array.
 *
 * The ordinary definition (NumPy's default, R's type 7). Written here rather than imported
 * because the frontend's production dependency set is React, ReactDOM and TanStack Table and
 * a quantile is six lines (ADR-048).
 */
export function quantileAt(sorted: readonly number[], q: number): number {
  if (sorted.length === 0) return Number.NaN;
  if (sorted.length === 1) return sorted[0] ?? Number.NaN;
  const position = (sorted.length - 1) * Math.min(1, Math.max(0, q));
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const low = sorted[lower] ?? Number.NaN;
  const high = sorted[upper] ?? Number.NaN;
  return lower === upper ? low : low + (high - low) * (position - lower);
}

/** Finite values only. A null in an artifact is the absence of a reading, never a zero. */
export function finiteValues(values: readonly (number | null | undefined)[]): readonly number[] {
  const out: number[] = [];
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) out.push(value);
  }
  return out;
}

/**
 * Where `value` sits among `values`.
 *
 * Returns null when the cohort is too small to be a cohort, or when the value itself is not a
 * finite number — both of which are ordinary states rather than errors, and both of which the
 * caller renders as an absence rather than as a zero.
 *
 * `axis` overrides the drawn extent for a quantity with an absolute scale, such as a share on
 * `{ low: 0, high: 1 }`. The mark is clamped into the axis so a rounding error cannot escape
 * the track; with the default axis it can never need to be, because the extent is the cohort's
 * own range and the value is one of its members.
 */
export function cohortStat(
  values: readonly number[],
  value: number | null | undefined,
  order: CohortOrder,
  axis?: { readonly low: number; readonly high: number },
): CohortStat | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const finite = finiteValues(values);
  if (finite.length < COHORT_MINIMUM) return null;

  const sorted = [...finite].sort((a, b) => a - b);
  const ahead =
    order === "desc"
      ? sorted.filter((candidate) => candidate > value).length
      : sorted.filter((candidate) => candidate < value).length;

  const low = axis?.low ?? (sorted[0] ?? value);
  const high = axis?.high ?? (sorted.at(-1) ?? value);
  return {
    value,
    count: sorted.length,
    rank: ahead + 1,
    axisLow: low,
    axisHigh: high,
    band:
      sorted.length < COHORT_BAND_MINIMUM
        ? null
        : {
            p25: quantileAt(sorted, 0.25),
            p50: quantileAt(sorted, 0.5),
            p75: quantileAt(sorted, 0.75),
          },
  };
}

/**
 * A percentage position on a cohort's axis, clamped into it.
 *
 * A degenerate axis — every row carrying the same value — puts the mark in the middle rather
 * than dividing by zero. That happens on a fixture board and it will happen on a real one the
 * first week every player's remaining-games estimate is identical.
 */
export function cohortPercent(stat: CohortStat, value: number): number {
  const range = stat.axisHigh - stat.axisLow;
  if (!(range > 0)) return 50;
  return Math.max(0, Math.min(100, ((value - stat.axisLow) / range) * 100));
}

/** `1st`, `2nd`, `3rd`, `11th` … the ordinal a rank is read as. */
export function ordinal(rank: number): string {
  const whole = Math.round(rank);
  const tens = whole % 100;
  if (tens >= 11 && tens <= 13) return `${String(whole)}th`;
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[whole % 10] ?? "th";
  return `${String(whole)}${suffix}`;
}

/**
 * The sentence a reading is stated as: `2nd widest of 96 WRs`.
 *
 * `qualifier` is the word that makes the direction readable without a legend — `widest` for an
 * interval, nothing at all for a value whose order is obvious from its name. The noun is the
 * population, and it is never optional: a rank without one looks like a rank on the board.
 */
export function cohortReading(stat: CohortStat, noun: string, qualifier?: string): string {
  const word = qualifier === undefined || qualifier === "" ? "" : `${qualifier} `;
  return `${ordinal(stat.rank)} ${word}of ${String(stat.count)} ${noun}`;
}
