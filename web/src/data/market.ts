/**
 * What the market metadata means, derived rather than asserted.
 *
 * Every number in this file comes out of `build_metadata.json` or the arbitrage records. None
 * of it is written down in TypeScript, and that decision has now been tested by events: the
 * launch board was priced by 125 keeper-free drafts against a frozen bar of 300 and every row
 * read `low`; a week later the same frozen rule was clearing the same bar and most rows read
 * `medium`. A panel that had hardcoded either state would have been wrong within days
 * (ADR-045, ADR-052).
 *
 * So this module has no notion of a normal condition. `summarizeMarket` reports whatever the
 * rows say — one label or several — and `marketHeadline` turns that into a sentence for any
 * of them. The same components render `low`, `medium`, `high` and a mixed board, and a trend
 * that is null renders exactly as correctly as one that is not.
 *
 * The distinction the module exists to keep straight: **`confidence` is market-data quality,
 * not a probability** (ADR-041). A `low` row is not a player the model is unsure about. It is
 * a price with little draft evidence behind it.
 */

import type { ArbitrageRecord, BuildMetadata, Confidence, ScoringPreset } from "./contracts";

export interface CohortAssignmentView {
  readonly scoringPreset: ScoringPreset;
  readonly leagueSize: number;
  readonly cohortId: string;
  readonly exact: boolean;
  readonly sufficient: boolean;
  readonly sourceFormatDetail: string;
  readonly failedClauses: readonly string[];
}

export function cohortAssignment(
  metadata: BuildMetadata,
  scoring: ScoringPreset,
  teams: number,
): CohortAssignmentView | null {
  const match = metadata.market?.assignments?.find(
    (entry) => entry.scoring_preset === scoring && entry.league_size === teams,
  );
  if (match === undefined) return null;
  return {
    scoringPreset: match.scoring_preset,
    leagueSize: match.league_size,
    cohortId: match.cohort_id,
    exact: match.exact,
    sufficient: match.sufficient,
    sourceFormatDetail: match.source_format_detail,
    failedClauses: match.failed_clauses ?? [],
  };
}

/**
 * A frozen sufficiency clause, e.g. `total_drafts 214 < 300`, turned into a sentence.
 *
 * The clause strings are the build's own words. Parsing them keeps the observed value and
 * the bound out of this file; an unrecognized clause is passed through verbatim rather than
 * dropped, so a future rule version degrades to "readable" rather than "invisible".
 */
export function explainClause(clause: string): string {
  const parsed = /^(\w+)\s+(\S+)\s*<\s*(\S+)$/.exec(clause.trim());
  if (parsed === null) return clause;
  const [, field, observed, bound] = parsed;
  const templates: Readonly<Record<string, (a: string, b: string) => string>> = {
    total_drafts: (a, b) =>
      `the cohort holds ${a} drafts against the ${b} the rule requires`,
    priced_players: (a, b) => `only ${a} of the ${b} required players carry a price`,
    top100_board_coverage: (a, b) =>
      `${a} of the top 100 board players are priced, against ${b} required`,
    top150_board_coverage: (a, b) =>
      `${a} of the top 150 board players are priced, against ${b} required`,
    median_top150_sample_size: (a, b) =>
      `the median top-150 player was priced by ${a} drafts, against ${b} required`,
    identity_coverage: (a, b) => `identity coverage is ${a}, against ${b} required`,
  };
  const template = templates[field ?? ""];
  return template === undefined ? clause : template(observed ?? "?", bound ?? "?");
}

export interface MarketConditionSummary {
  /** Distinct confidence labels on the rows currently in scope. */
  readonly confidenceCounts: Readonly<Record<Confidence, number>>;
  /** The single label, when every row in scope carries the same one. Null on a mixed board. */
  readonly uniform: Confidence | null;
  /** The label the largest number of rows carry. Never null when there is a row. */
  readonly dominant: Confidence | null;
  readonly assignment: CohortAssignmentView | null;
  /** Median `market_sample_size` over the rows in scope. The direct per-player evidence. */
  readonly medianSampleSize: number | null;
  readonly rows: number;
  readonly trendAvailable: boolean;
  readonly trendSnapshots: number | null;
  readonly snapshotAtUtc: string | null;
  readonly sourceId: string;
}

const EMPTY_COUNTS: Readonly<Record<Confidence, number>> = {
  high: 0,
  medium: 0,
  low: 0,
  unknown: 0,
};

export function summarizeMarket(
  metadata: BuildMetadata,
  records: readonly ArbitrageRecord[],
  scoring: ScoringPreset,
  teams: number,
): MarketConditionSummary {
  const counts: Record<Confidence, number> = { ...EMPTY_COUNTS };
  const samples: number[] = [];
  for (const record of records) {
    counts[record.confidence] += 1;
    if (record.market_sample_size !== null) samples.push(record.market_sample_size);
  }
  const present = (Object.keys(counts) as Confidence[]).filter((key) => counts[key] > 0);
  let dominant: Confidence | null = null;
  for (const key of present) {
    if (dominant === null || counts[key] > counts[dominant]) dominant = key;
  }
  samples.sort((a, b) => a - b);
  const middle = Math.floor(samples.length / 2);
  const medianSampleSize =
    samples.length === 0
      ? null
      : samples.length % 2 === 1
        ? (samples[middle] ?? null)
        : ((samples[middle - 1] ?? 0) + (samples[middle] ?? 0)) / 2;

  return {
    confidenceCounts: counts,
    uniform: present.length === 1 ? (present[0] ?? null) : null,
    dominant,
    assignment: cohortAssignment(metadata, scoring, teams),
    medianSampleSize,
    rows: records.length,
    trendAvailable: metadata.market?.trend_available ?? false,
    trendSnapshots: metadata.market?.trend_history_snapshots ?? null,
    snapshotAtUtc: metadata.market?.snapshot_at_utc ?? null,
    sourceId: metadata.market?.source_id ?? "myfantasyleague_adp",
  };
}

/** The human name of a market source. Never "Consensus ADP": this product built no consensus. */
export function marketSourceLabel(sourceId: string): string {
  return sourceId === "myfantasyleague_adp" ? "MyFantasyLeague ADP" : sourceId;
}

export const CONFIDENCE_LABELS: Readonly<Record<Confidence, string>> = {
  high: "High market data",
  medium: "Medium market data",
  low: "Low market data",
  unknown: "No market sample",
};

export const CONFIDENCE_SHORT: Readonly<Record<Confidence, string>> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  unknown: "Unknown",
};

/**
 * What the label is a statement about. Read on every surface that shows a confidence value,
 * because "low" beside a player's name reads as "the model is unsure about him" unless it is
 * told otherwise, and that is the opposite of what the field means.
 */
export const CONFIDENCE_MEANING =
  "Market-data quality: how much draft evidence stands behind this price. " +
  "It is not a probability that the player is a bargain, and it says nothing about the " +
  "intrinsic projection beside it.";

/** Trend semantics, in words, so a sign is never the only channel (ADR-042). */
export function describeTrend(trend: number | null): {
  readonly text: string;
  readonly direction: "earlier" | "later" | "flat" | "unknown";
} {
  if (trend === null) {
    return { text: "Trend collecting", direction: "unknown" };
  }
  if (trend === 0) return { text: "No measured movement", direction: "flat" };
  return trend > 0
    ? { text: "Moving earlier (more expensive)", direction: "earlier" }
    : { text: "Moving later (less expensive)", direction: "later" };
}

export const TREND_UNAVAILABLE_EXPLANATION =
  "A trend needs at least three observation days spanning three days in our own retained " +
  "snapshot store. Until then there is no estimate — which is not the same as no movement.";

/**
 * The bargain sentence, spelled out.
 *
 * `rank_gap = market_adp − fair_rank`. Positive means the market drafts him later than his
 * fair rank, so he can be had cheaply (ADR-040). Direction is stated in words as well as sign
 * so nothing depends on colour or on the reader knowing that smaller pick numbers are earlier.
 */
export function describeGap(rankGap: number): {
  readonly kind: "bargain" | "premium" | "even";
  readonly sentence: string;
  readonly compact: string;
} {
  const magnitude = Math.abs(rankGap).toFixed(1);
  if (Math.abs(rankGap) < 0.05) {
    return { kind: "even", sentence: "The market drafts him at his fair rank.", compact: "Even" };
  }
  if (rankGap > 0) {
    return {
      kind: "bargain",
      sentence: `The market drafts him ${magnitude} picks later than his fair rank.`,
      compact: `+${magnitude} picks later`,
    };
  }
  return {
    kind: "premium",
    sentence: `The market drafts him ${magnitude} picks earlier than his fair rank.`,
    compact: `\u2212${magnitude} picks earlier`,
  };
}

/**
 * Confidence labels, ordered weakest to strongest.
 *
 * Used to decide whether a board's market condition needs a warning tone or an informational
 * one. `unknown` sits below `low`: a row with no sample at all is weaker evidence than a row
 * with a small one.
 */
export const CONFIDENCE_ORDER: readonly Confidence[] = ["unknown", "low", "medium", "high"];

/** True when this label is weak enough that a board carrying it should say so up front. */
export function isWeakConfidence(confidence: Confidence): boolean {
  return confidence === "low" || confidence === "unknown";
}

export interface MarketHeadline {
  readonly tone: "info" | "warning";
  readonly sentence: string;
}

/**
 * The one-line market condition, for whatever the board actually is.
 *
 * Three shapes, all derived: every row carrying one label, a mixed board, and no rows at all.
 * There is no branch here that assumes a particular label, which is the whole point — the
 * product moved `low` -> `medium` on its own between two daily refreshes and this sentence
 * had to move with it without a code change.
 */
export function marketHeadline(summary: MarketConditionSummary): MarketHeadline | null {
  if (summary.rows === 0) return null;
  const { uniform, confidenceCounts, dominant } = summary;
  if (uniform !== null) {
    return {
      tone: isWeakConfidence(uniform) ? "warning" : "info",
      sentence: `Every priced row on this board carries ${CONFIDENCE_SHORT[
        uniform
      ].toLowerCase()} market-data confidence.`,
    };
  }
  const parts = CONFIDENCE_ORDER.filter((key) => confidenceCounts[key] > 0)
    .reverse()
    .map((key) => `${String(confidenceCounts[key])} ${CONFIDENCE_SHORT[key].toLowerCase()}`);
  return {
    tone: dominant !== null && isWeakConfidence(dominant) ? "warning" : "info",
    sentence: `Market-data confidence across these ${String(summary.rows)} priced rows: ${parts.join(", ")}.`,
  };
}
