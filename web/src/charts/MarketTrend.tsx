/**
 * The market-history mini chart: a player's retained ADP by day, drawn small.
 *
 * Release 1 published the trend as a bare number — `-3.11`, "moving later (less expensive)" —
 * which is accurate and hard to feel. `docs/RELEASE2_ROADMAP.md` 10.7 asks for the same
 * quantity as a shape, and the shape is the point: a steady drift and a two-day collapse can
 * produce the same slope, and only one of them is news.
 *
 * **What this chart is, and what it is not.** It draws *observations*. The scalar
 * `market_trend` beside it is an *estimate* over those observations, gated by
 * `phase5_trend_v1` — three observation days spanning three days. The first version of this
 * component conflated the two and refused to draw anything below three points, on the
 * reasoning that two points imply a trend the store cannot support. That reasoning is right
 * about the *slope* and wrong about the *history*: a retained ADP on a Thursday is a fact
 * whether or not a Saturday follows it, and refusing to show it is how a market with seven
 * real snapshots came to read "0 snapshots so far" (ADR-081). So the chart draws what it
 * has — a point, two points, a line — and the slope stays "collecting" until the frozen rule
 * qualifies it, independently.
 *
 * **The orientation is the whole design problem.** A lower ADP means a player is going
 * *earlier* — more expensive, more in demand. Plotted naively, "the market likes him more"
 * would be a line that falls, which is the opposite of what a reader's eye reports. So the
 * y axis is **inverted**: up is earlier, up is hotter, and the caption is worded to say so
 * rather than leaving the reader to work it out.
 *
 * **The x axis is time, not position.** Captures are not evenly spaced — the store has three
 * on one afternoon and none the next morning — and an index axis would draw an even cadence
 * that never happened. It also makes the cross-market view mean what it says: two series on
 * one dated axis show how far apart the markets were *on a given day*.
 *
 * Three rules keep it honest:
 *
 * - **No vendor call, ever.** The points come from the artifact, which came from a retained
 *   snapshot. A chart that fetched history in the browser would put a vendor on the critical
 *   path of a static page (roadmap 10.7).
 * - **One source's line is never another's.** Each series names its market, in the legend and
 *   in the accessible summary. Nothing is averaged: there is no cross-market series, because
 *   no capture produced one.
 * - **Never colour alone.** Series are separated by stroke pattern and named in the legend;
 *   direction is in the caption in words and in the accessible summary.
 */

import { useId, useMemo, useState } from "react";

export interface TrendPoint {
  /** ISO-8601 instant the snapshot was retrieved. */
  readonly observed_at: string;
  readonly market_adp: number;
}

/** One market's retained history, ready to draw. */
export interface TrendSeries {
  readonly sourceId: string;
  /** The market's name, as the selector spells it. */
  readonly label: string;
  readonly points: readonly TrendPoint[];
  /** The frozen slope over these points, or null while `phase5_trend_v1` has not qualified. */
  readonly trend: number | null;
}

const WIDTH = 240;
const HEIGHT = 60;
const PAD_X = 5;
const PAD_Y = 7;

/**
 * Stroke patterns, in series order. Series are told apart without relying on colour.
 *
 * The first is solid — `undefined` rather than an empty string, because `strokeDasharray=""`
 * is a value React would render as an attribute.
 */
const DASHES: readonly (string | undefined)[] = [undefined, "4 2.5", "1.5 2", "6 2 1.5 2"];

function formatDay(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** The UTC calendar day an instant falls on, as `YYYY-MM-DD`. */
function utcDay(iso: string): string {
  return iso.slice(0, 10);
}

/**
 * One point per UTC calendar day: **the latest retained observation of that day**.
 *
 * The store can hold several captures in one afternoon — three on 2026-09-03, in the build
 * that found this bug — and plotting all of them puts a vertical cluster where a reader
 * expects a day. The rule is stated rather than tuned: latest-of-day, because that is the
 * reading that was current when the day ended, and it makes the newest point of the whole
 * series the price the board publishes.
 *
 * This is a **presentation** reduction and nothing else. `phase5_trend_v1` still fits its OLS
 * over every retained observation, unreduced, and the two are allowed to differ precisely
 * because they answer different questions (ADR-081).
 */
export function pointsByDay(points: readonly TrendPoint[]): readonly TrendPoint[] {
  const latest = new Map<string, TrendPoint>();
  for (const point of [...points].sort((a, b) => a.observed_at.localeCompare(b.observed_at))) {
    latest.set(utcDay(point.observed_at), point);
  }
  return [...latest.values()];
}

function movementSentence(label: string, points: readonly TrendPoint[]): string {
  const count = points.length;
  if (count === 0) return `No retained ${label} history yet.`;
  const first = points[0]?.market_adp ?? 0;
  const last = points[count - 1]?.market_adp ?? 0;
  if (count === 1) {
    return `${label}: one retained observation, ADP ${last.toFixed(1)} on ${formatDay(points[0]?.observed_at ?? "")}.`;
  }
  if (last === first) {
    return `${label} ADP is unchanged at ${last.toFixed(1)} across ${String(count)} days.`;
  }
  return `${label} ADP moved from ${first.toFixed(1)} to ${last.toFixed(1)} across ${String(count)} days — ${last < first ? "earlier, so more expensive" : "later, so less expensive"}.`;
}

interface DrawnSeries {
  readonly series: TrendSeries;
  readonly points: readonly TrendPoint[];
  readonly index: number;
}

/**
 * A compact retained-ADP history with an inverted y axis and a dated x axis.
 *
 * One series is the single-market view; several are the cross-market view, overlaid on one
 * axis so the reader can see the gap between markets by date rather than being handed a
 * number for it.
 */
export function MarketTrend({
  series,
  label,
}: {
  readonly series: readonly TrendSeries[];
  /**
   * What the reader asked for, for the empty state — a market's name in the single-market
   * view, the bare word "market" under cross. It cannot be derived from `series`, because the
   * case that needs naming is exactly the one where `series` is empty.
   */
  readonly label: string;
}): React.JSX.Element {
  const titleId = useId();
  const [hovered, setHovered] = useState<{ series: number; point: number } | null>(null);

  const drawn = useMemo<readonly DrawnSeries[]>(
    () =>
      series.map((entry, index) => ({
        series: entry,
        points: pointsByDay(entry.points),
        index,
      })),
    [series],
  );

  const populated = drawn.filter((entry) => entry.points.length > 0);

  if (populated.length === 0) {
    // A truthful state, and a *specific* one: it names the market the reader selected, so
    // "nothing here" cannot be mistaken for "nothing anywhere". One observation is enough to
    // leave this branch — the chart draws a point, and the slope stays collecting.
    return (
      <p className="trend-empty" data-testid="market-trend-empty">
        {`No retained ${label} history has been captured for him yet, so there is nothing to chart.`}
      </p>
    );
  }

  const values = populated.flatMap((entry) => entry.points.map((point) => point.market_adp));
  const stamps = populated.flatMap((entry) =>
    entry.points.map((point) => Date.parse(point.observed_at)),
  );
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low;
  // A price that has not moved has no range to scale against, and dividing by zero would put
  // it at the top of the box — where "the most expensive it has been" lives. It goes in the
  // middle instead, which is what "unchanged" should look like.
  const flat = span === 0;
  const start = Math.min(...stamps);
  const end = Math.max(...stamps);
  // A history confined to one instant has no time axis to speak of; the marks go in the
  // middle rather than all on the left edge.
  const elapsed = end - start;

  const x = (iso: string): number =>
    elapsed === 0
      ? WIDTH / 2
      : PAD_X + ((Date.parse(iso) - start) / elapsed) * (WIDTH - 2 * PAD_X);
  // Inverted: the SMALLEST ADP (earliest pick, most expensive) sits at the TOP.
  const y = (value: number): number =>
    flat ? HEIGHT / 2 : PAD_Y + ((value - low) / span) * (HEIGHT - 2 * PAD_Y);

  const summary = populated
    .map((entry) => movementSentence(entry.series.label, entry.points))
    .join(" ");

  const active =
    hovered === null
      ? null
      : {
          entry: populated.find((item) => item.index === hovered.series) ?? null,
          point:
            populated.find((item) => item.index === hovered.series)?.points[hovered.point] ?? null,
        };

  return (
    <figure className="trend-chart" data-testid="market-trend" data-series-count={populated.length}>
      {/*
        `group`, not `img`. The marks below are focusable buttons — a keyboard user reads each
        day's price from them — and `role="img"` declares its subtree presentational, which
        axe reports as `nested-interactive` and which would hide those readings from a screen
        reader. The plot keeps its accessible name; the caption repeats the whole sentence in
        text for everyone.

        This was here from the first version of the chart and no gate saw it, because no
        fixture published a history for it to draw (ADR-081).
      */}
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        width="100%"
        height={HEIGHT}
        role="group"
        aria-labelledby={titleId}
        preserveAspectRatio="none"
      >
        <title id={titleId}>{summary}</title>
        {populated.map((entry) => {
          const first = entry.points[0]?.market_adp ?? 0;
          const last = entry.points[entry.points.length - 1]?.market_adp ?? 0;
          const kind = last < first ? "earlier" : last > first ? "later" : "flat";
          const path = entry.points
            .map(
              (point, index) =>
                `${index === 0 ? "M" : "L"}${x(point.observed_at).toFixed(1)} ${y(point.market_adp).toFixed(1)}`,
            )
            .join(" ");
          return (
            <g key={entry.series.sourceId} data-source={entry.series.sourceId}>
              {/* One observation is a reading, not a line. Drawing a zero-length path would
                  render nothing at all and the reader would be told, wrongly, that there is
                  no history. */}
              {entry.points.length > 1 && (
                <path
                  className="trend-line"
                  d={path}
                  fill="none"
                  data-kind={kind}
                  data-series={entry.index}
                  strokeDasharray={DASHES[entry.index % DASHES.length]}
                />
              )}
              {entry.points.map((point, index) => (
                <circle
                  key={point.observed_at}
                  className="trend-point"
                  cx={x(point.observed_at)}
                  cy={y(point.market_adp)}
                  r={hovered?.series === entry.index && hovered.point === index ? 3.2 : 1.8}
                  data-series={entry.index}
                  data-kind={kind}
                  data-latest={index === entry.points.length - 1 ? "true" : undefined}
                  onMouseEnter={() => {
                    setHovered({ series: entry.index, point: index });
                  }}
                  onMouseLeave={() => {
                    setHovered(null);
                  }}
                  onFocus={() => {
                    setHovered({ series: entry.index, point: index });
                  }}
                  onBlur={() => {
                    setHovered(null);
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={`${entry.series.label}, ${formatDay(point.observed_at)}: ADP ${point.market_adp.toFixed(1)}`}
                />
              ))}
            </g>
          );
        })}
      </svg>

      {/* The dates the axis actually spans. "By day" is the thing being shown, so it is
          written down rather than left to the spacing of the marks. */}
      <div className="trend-axis" aria-hidden="true">
        <span>{formatDay(new Date(start).toISOString())}</span>
        {elapsed > 0 && <span>{formatDay(new Date(end).toISOString())}</span>}
      </div>

      <figcaption className="trend-caption">
        {/* The reading, in words, for everyone — not a tooltip-only fact. Touch devices get
            no hover, and a caption is reachable where a title attribute is not. */}
        <span className="trend-reading">
          {active?.point == null
            ? populated
                .map(
                  (entry) =>
                    `${entry.series.label} ${(entry.points[entry.points.length - 1]?.market_adp ?? 0).toFixed(1)}`,
                )
                .join(" · ")
            : `${active.entry?.series.label ?? ""} · ${formatDay(active.point.observed_at)} · ${active.point.market_adp.toFixed(1)}`}
        </span>
        <span className="visually-hidden">{summary}</span>
      </figcaption>

      {/* One row per market: its stroke, its name, its direction in words, and its slope or
          the reason there is not one yet. In the single-market view this is one line; in the
          cross-market view it is what stops the two series being told apart by colour. */}
      <ul className="trend-legend">
        {populated.map((entry) => {
          const first = entry.points[0]?.market_adp ?? 0;
          const last = entry.points[entry.points.length - 1]?.market_adp ?? 0;
          const kind = last < first ? "earlier" : last > first ? "later" : "flat";
          return (
            <li key={entry.series.sourceId} data-source={entry.series.sourceId}>
              <svg className="trend-swatch" viewBox="0 0 18 6" width="18" height="6" aria-hidden="true">
                <path
                  className="trend-line"
                  d="M0 3 L18 3"
                  fill="none"
                  data-kind={kind}
                  data-series={entry.index}
                  strokeDasharray={DASHES[entry.index % DASHES.length]}
                />
              </svg>
              <span className="trend-legend-name">{entry.series.label}</span>
              <span className="trend-direction" data-kind={kind}>
                {kind === "flat"
                  ? "unchanged"
                  : kind === "earlier"
                    ? "▲ moving earlier"
                    : "▼ moving later"}
              </span>
              <span className="trend-slope muted">
                {entry.series.trend === null
                  ? "trend collecting"
                  : `${entry.series.trend > 0 ? "+" : ""}${entry.series.trend.toFixed(2)}/day`}
              </span>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}
