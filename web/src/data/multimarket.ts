/**
 * The multi-source market layer, read from the artifact rather than declared here.
 *
 * Release 1 had one price, so "the market" needed no qualification. Release 2 has several,
 * and the whole job of this module is to keep them from blurring together on the way to the
 * screen. Three rules, each of which the backend also enforces — restated here because a
 * frontend that quietly averaged them would produce a number no artifact contains:
 *
 * 1. **An ADP and an ECR are different measurements.** A price is what people spent; a
 *    consensus rank is what people think. `selectableMarkets` returns only ADP sources, and
 *    the expert consensus is rendered from its own field with its own label.
 * 2. **A source keeps its identity.** Every displayed number names the source it came from,
 *    and `MARKET_SOURCES` supplies the label rather than the record inventing one.
 * 3. **The cross-market median is a summary, not a price.** It is shown, and it is shown as
 *    a summary — the interesting number beside it is the disagreement range, which is the
 *    thing a single-source board could not have told you.
 *
 * Everything degrades. A Release 1 artifact has no `markets` array, an FFC outage leaves one
 * source missing, and FantasyPros is retained-but-unpublished until its API tier changes.
 * Each of those renders as "this source has nothing to say today" rather than as a blank
 * where a number should be.
 */

import type {
  AggregationWindow,
  ArbitrageRecord,
  CrossMarketSummary,
  ExpertConsensus,
  MarketComparison,
  MarketTrendSeriesRecord,
} from "./contracts";

/** The market selection a reader can make. `cross` is a view, not a source. */
export type MarketSelection = string;

export const CROSS_MARKET = "cross";

export interface MarketSourceMeta {
  readonly id: string;
  /** What the selector shows. Short enough for a segmented control on a phone. */
  readonly label: string;
  /** One line under the selector: what this market actually measures. */
  readonly description: string;
}

/**
 * The sources this product can show, in selector order.
 *
 * FFC leads because it is the scoring-exact market that responds to the current week, which
 * is what a reader drafting today is comparing against. MyFantasyLeague follows because its
 * season-cumulative aggregate is the broader, slower reading — a genuinely different
 * question, not a worse answer.
 */
export const MARKET_SOURCES: Readonly<Record<string, MarketSourceMeta>> = {
  fantasyfootballcalculator_adp: {
    id: "fantasyfootballcalculator_adp",
    label: "FFC Recent",
    description: "Scoring-exact ADP over a recent rolling window of drafts",
  },
  myfantasyleague_adp: {
    id: "myfantasyleague_adp",
    label: "MFL Cumulative",
    description: "ADP aggregated across the season's drafts to date",
  },
  fantasypros_adp: {
    id: "fantasypros_adp",
    label: "FantasyPros ADP",
    description: "FantasyPros' own draft-price aggregate",
  },
  fantasypros_ecr: {
    id: "fantasypros_ecr",
    label: "FantasyPros ECR",
    description: "Expert consensus ranking — an opinion, not an observed price",
  },
};

export function marketLabel(sourceId: string | null | undefined): string {
  if (sourceId === null || sourceId === undefined) return "Market";
  if (sourceId === CROSS_MARKET) return "Cross-market";
  return MARKET_SOURCES[sourceId]?.label ?? sourceId;
}

const WINDOW_LABELS: Readonly<Record<AggregationWindow, string>> = {
  rolling: "recent window",
  season_cumulative: "season to date",
  not_applicable: "no draft window",
  unknown: "window not published",
};

/**
 * How a source aggregates, in words.
 *
 * Shown beside the selected market because "ADP" over seven days and "ADP" over five months
 * are different numbers, and a reader comparing them needs to be told which is which
 * (Release 2 guardrail 2.3).
 */
export function windowLabel(
  window: AggregationWindow | undefined,
  days: number | null | undefined,
): string {
  if (window === undefined) return "";
  const base = WINDOW_LABELS[window];
  return window === "rolling" && days !== null && days !== undefined
    ? `${String(days)}-day ${base}`
    : base;
}

/** Every ADP comparison on a record, keyed by source. ECR is structurally absent. */
export function marketsOf(record: ArbitrageRecord): Readonly<Record<string, MarketComparison>> {
  const out: Record<string, MarketComparison> = {};
  for (const entry of record.markets ?? []) {
    if (entry.market_signal_type !== "adp") continue;
    out[entry.source_id] = entry;
  }
  return out;
}

export function consensusOf(record: ArbitrageRecord): ExpertConsensus | null {
  const consensus = record.expert_consensus;
  return consensus?.market_signal_type === "ecr" ? consensus : null;
}

export function crossMarketOf(record: ArbitrageRecord): CrossMarketSummary | null {
  return record.cross_market ?? null;
}

/**
 * The ADP markets a board can actually offer, derived from what the rows carry.
 *
 * Derived rather than declared, for the same reason the confidence panel is: a selector
 * offering a source the build did not publish is a promise the page cannot keep, and a
 * hardcoded list goes stale the day a source is enabled or withdrawn.
 */
export function selectableMarkets(rows: readonly ArbitrageRecord[]): readonly string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    for (const entry of row.markets ?? []) {
      if (entry.market_signal_type === "adp") seen.add(entry.source_id);
    }
    // A Release 1 row has no `markets` array at all; its single source is still selectable.
    if ((row.markets ?? []).length === 0) seen.add(row.market_source_id);
  }
  const known = Object.keys(MARKET_SOURCES).filter((id) => seen.has(id));
  const extra = [...seen].filter((id) => !(id in MARKET_SOURCES)).sort();
  return [...known, ...extra];
}

/** Whether a cross-market view is worth offering: it needs at least two prices to compare. */
export function crossMarketAvailable(rows: readonly ArbitrageRecord[]): boolean {
  return rows.some((row) => (row.cross_market?.sources_available.length ?? 0) > 1);
}

/**
 * The comparison a given selection should display for one row.
 *
 * `cross` resolves to the median-priced source rather than to the median *number*: a reader
 * clicking through to a player should land on a real source with a real cohort and a real
 * snapshot time, not on a synthetic row that no capture produced.
 */
export function comparisonFor(
  record: ArbitrageRecord,
  selection: MarketSelection,
): MarketComparison | null {
  const markets = marketsOf(record);
  if (selection !== CROSS_MARKET) return markets[selection] ?? null;

  const entries = Object.values(markets).sort(
    (left, right) => left.market_adp - right.market_adp || left.source_id.localeCompare(right.source_id),
  );
  if (entries.length === 0) return null;
  return entries[Math.floor((entries.length - 1) / 2)] ?? null;
}

/** The gap the selected market shows, falling back to the record's Release 1 field. */
export function gapFor(record: ArbitrageRecord, selection: MarketSelection): number | null {
  const comparison = comparisonFor(record, selection);
  if (comparison !== null) return comparison.rank_gap;
  return selection === record.market_source_id || selection === CROSS_MARKET
    ? record.rank_gap
    : null;
}

export function adpFor(record: ArbitrageRecord, selection: MarketSelection): number | null {
  const comparison = comparisonFor(record, selection);
  if (comparison !== null) return comparison.market_adp;
  return selection === record.market_source_id || selection === CROSS_MARKET
    ? record.market_adp
    : null;
}

/**
 * The trend the selected market shows for one row, or null.
 *
 * Under `cross` this is the trend of **the same source** `adpFor` and `gapFor` resolve to, so
 * a row's price, gap and movement are one market's account of the player rather than three
 * markets' accounts spliced together. Before this existed the Trend column read the flat V1
 * field unconditionally — MyFantasyLeague's — beside an FFC price and an FFC gap (ADR-081).
 *
 * Null is a real answer and is never filled in from another source: it means this market has
 * not yet supplied three observation days spanning three days.
 */
export function trendFor(record: ArbitrageRecord, selection: MarketSelection): number | null {
  const comparison = comparisonFor(record, selection);
  if (comparison !== null) return comparison.market_trend;
  return (record.markets ?? []).length === 0 &&
    (selection === record.market_source_id || selection === CROSS_MARKET)
    ? record.market_trend
    : null;
}

/** Which source a row's displayed numbers came from under a given selection. */
export function sourceFor(record: ArbitrageRecord, selection: MarketSelection): string | null {
  const comparison = comparisonFor(record, selection);
  if (comparison !== null) return comparison.source_id;
  return (record.markets ?? []).length === 0 &&
    (selection === record.market_source_id || selection === CROSS_MARKET)
    ? record.market_source_id
    : null;
}

/**
 * The disagreement between markets, for sorting and filtering the cross-market view.
 *
 * Null when fewer than two sources priced the player: zero would be wrong — it would claim
 * the markets agree, when in fact only one of them spoke.
 */
export function disagreementFor(record: ArbitrageRecord): number | null {
  const cross = record.cross_market;
  if (cross == null || cross.sources_available.length < 2) return null;
  return cross.market_disagreement_range;
}

/**
 * A short, screen-reader-friendly account of the cross-market spread.
 *
 * The direction words are the ones a drafter uses. `cheapest_market_source` is the market
 * where a player costs the *latest* pick, which reads backwards if you think about the
 * number rather than the draft.
 */
export function crossMarketSummaryText(cross: CrossMarketSummary | null): string {
  if (cross == null || cross.sources_available.length === 0) return "No market priced him.";
  if (cross.sources_available.length === 1) {
    return `Only ${marketLabel(cross.sources_available[0])} priced him.`;
  }
  const spread = cross.market_disagreement_range;
  const cheapest = marketLabel(cross.cheapest_market_source);
  const dearest = marketLabel(cross.most_expensive_market_source);
  return spread === null
    ? `${String(cross.sources_available.length)} markets priced him.`
    : `${spread.toFixed(1)} picks between ${dearest} (earliest) and ${cheapest} (latest).`;
}

/** Whether a row was surfaced by market relevance from beyond the tier board (ADR-063). */
export function isSurfaceException(record: ArbitrageRecord): boolean {
  return record.outside_tier_board === true;
}

/**
 * The one market the player card is reading, resolved once.
 *
 * **This exists because `??` was doing the resolving.** The card read
 * `selected?.rank_gap ?? arbitrage.rank_gap`, `selected?.market_adp ?? arbitrage.market_adp`
 * and, in four other places, the flat `arbitrage.market_trend` outright. The flat fields are
 * MyFantasyLeague's, so with FFC selected a legitimately null FFC trend silently became
 * MFL's number, and a reader saw one market's slope under another market's label. The null
 * was the *message* — "FFC has observations but not yet three days of span" — and the
 * fallback deleted it (ADR-081).
 *
 * The fallback that remains is the only one that was ever meant: a **Release 1** record has
 * no `markets` array at all, and its flat fields are that single source's own numbers. That
 * is a different bundle, not a different field on this one, so it is resolved here once and
 * the card never sees the choice.
 */
export interface MarketView {
  readonly selection: MarketSelection;
  readonly cross: boolean;
  /**
   * The source these numbers came from, which under `cross` is a real market rather than the
   * selection. Null when nothing priced this player.
   */
  readonly sourceId: string | null;
  readonly comparison: MarketComparison | null;
  /**
   * The scalar slope, or null. Under `cross` it is **always** null: no market published a
   * cross-market trend, and showing one source's slope beside the word "Cross-market" would
   * name a market the number did not come from.
   */
  readonly trend: number | null;
  /** Whether a scalar trend is a coherent thing to ask for at all in this view. */
  readonly trendIsScalar: boolean;
}

function comparisonFromFlatFields(record: ArbitrageRecord): MarketComparison {
  return {
    source_id: record.market_source_id,
    market_signal_type: "adp",
    market_adp: record.market_adp,
    market_rank: record.market_rank,
    rank_gap: record.rank_gap,
    regional_value_gap: record.regional_value_gap,
    market_sample_size: record.market_sample_size,
    market_adp_sd: record.market_adp_sd,
    market_adp_low: record.market_adp_low,
    market_adp_high: record.market_adp_high,
    league_size: null,
    aggregation_window_type: "unknown",
    aggregation_window_days: null,
    market_cohort_id: record.market_cohort_id,
    market_cohort_detail: record.market_cohort_detail,
    market_snapshot_at_utc: record.market_snapshot_at_utc,
    market_trend: record.market_trend,
    quality_flags: record.quality_flags,
  };
}

export function marketView(
  record: ArbitrageRecord | null,
  selection: MarketSelection,
): MarketView | null {
  if (record === null) return null;
  const cross = selection === CROSS_MARKET;
  const hasArray = (record.markets ?? []).length > 0;
  // Release 1 bundles carry no `markets` array; their flat fields *are* the one market's
  // comparison, so they are lifted into the same shape rather than read through a fallback
  // at every call site.
  const comparison = hasArray
    ? comparisonFor(record, selection)
    : selection === record.market_source_id || cross
      ? comparisonFromFlatFields(record)
      : null;
  return {
    selection,
    cross,
    sourceId: comparison?.source_id ?? null,
    comparison,
    trend: cross ? null : (comparison?.market_trend ?? null),
    trendIsScalar: !cross,
  };
}

/**
 * The histories the chart should draw for one selection.
 *
 * Single source: that source's series, and nothing if it has none — never another market's.
 * Cross: every source that has one, so the reader can see by date how far apart the markets
 * were. There is deliberately no synthetic `cross` series to look up; the store contains no
 * such market and averaging two real ones into a line would draw a price nobody paid.
 */
export function historiesFor(
  histories: readonly MarketTrendSeriesRecord[],
  selection: MarketSelection,
): readonly MarketTrendSeriesRecord[] {
  const ordered = [...histories]
    // `cross` is a selection, not a market. A record naming it would be a synthesized
    // history no capture produced, and the cross view — the one place it could slip through
    // unnoticed — is exactly where it must not be drawn.
    .filter((record) => record.market_source_id !== CROSS_MARKET)
    .sort((left, right) => marketOrder(left.market_source_id) - marketOrder(right.market_source_id));
  return selection === CROSS_MARKET
    ? ordered
    : ordered.filter((record) => record.market_source_id === selection);
}

/** Selector order, so a chart's series and the market control agree about which comes first. */
function marketOrder(sourceId: string): number {
  const index = Object.keys(MARKET_SOURCES).indexOf(sourceId);
  return index === -1 ? Object.keys(MARKET_SOURCES).length : index;
}
