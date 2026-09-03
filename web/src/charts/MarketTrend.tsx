/**
 * The market-trend mini chart: a player's retained ADP history, drawn small.
 *
 * Release 1 published the trend as a bare number — `-3.11`, "moving later (less expensive)" —
 * which is accurate and hard to feel. `docs/RELEASE2_ROADMAP.md` 10.7 asks for the same
 * quantity as a shape, and the shape is the point: a steady drift and a two-day collapse can
 * produce the same slope, and only one of them is news.
 *
 * **The orientation is the whole design problem.** A lower ADP means a player is going
 * *earlier* — more expensive, more in demand. Plotted naively, "the market likes him more"
 * would be a line that falls, which is the opposite of what a reader's eye reports. So the
 * y axis is **inverted**: up is earlier, up is hotter, and the axis is labelled to say so
 * rather than leaving the reader to work it out.
 *
 * Three rules keep it honest:
 *
 * - **No vendor call, ever.** The points come from the artifact, which came from a retained
 *   snapshot. A chart that fetched history in the browser would put a vendor on the critical
 *   path of a static page (roadmap 10.7).
 * - **Sparse history is a truthful state, not an empty chart.** Nought, one or two points
 *   say "not enough history yet" in words, because a two-point line implies a trend the
 *   store cannot support.
 * - **Never colour alone.** The direction is in the accessible summary and in the numeric
 *   readout beside the chart, so the meaning survives a greyscale print and a screen reader.
 *
 * The scalar `market_trend` stays: it sorts, it exports, and it is what the accessible
 * summary reads. This draws the same history that produced it.
 */

import { useId, useMemo, useState } from "react";

export interface TrendPoint {
  /** ISO-8601 instant the snapshot was retrieved. */
  readonly observed_at: string;
  readonly market_adp: number;
}

/** Below this many points there is no shape to draw, only two dots and an implication. */
export const MIN_TREND_POINTS = 3;

const WIDTH = 220;
const HEIGHT = 56;
const PAD_X = 4;
const PAD_Y = 6;

function formatDay(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/**
 * A compact ADP history with an inverted y axis.
 *
 * `label` names the source, because switching the market selector changes which series this
 * is and an unlabelled line would silently become a different source's history.
 */
export function MarketTrend({
  points,
  label,
  trend,
}: {
  readonly points: readonly TrendPoint[];
  readonly label: string;
  /** The scalar slope this history produced, for the summary. Null when uncomputed. */
  readonly trend: number | null;
}): React.JSX.Element {
  const titleId = useId();
  const [hovered, setHovered] = useState<number | null>(null);

  const ordered = useMemo(
    () => [...points].sort((a, b) => a.observed_at.localeCompare(b.observed_at)),
    [points],
  );

  if (ordered.length < MIN_TREND_POINTS) {
    return (
      <p className="trend-empty" data-testid="market-trend-empty">
        {`Not enough retained ${label} history to draw a trend yet — ${String(ordered.length)} snapshot${ordered.length === 1 ? "" : "s"} so far.`}
      </p>
    );
  }

  const values = ordered.map((point) => point.market_adp);
  const low = Math.min(...values);
  const high = Math.max(...values);
  // A perfectly flat series would divide by zero. One pick of padding keeps the line in the
  // middle of the box, which is what "it has not moved" should look like.
  const span = high - low || 1;

  const x = (index: number): number =>
    PAD_X + (index * (WIDTH - 2 * PAD_X)) / Math.max(1, ordered.length - 1);
  // Inverted: the SMALLEST ADP (earliest pick, most expensive) sits at the TOP.
  const y = (value: number): number => PAD_Y + ((value - low) / span) * (HEIGHT - 2 * PAD_Y);

  const path = ordered
    .map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)} ${y(point.market_adp).toFixed(1)}`)
    .join(" ");

  const first = values[0] ?? 0;
  const last = values[values.length - 1] ?? 0;
  const movedEarlier = last < first;
  const summary =
    last === first
      ? `${label} ADP is unchanged over the last ${String(ordered.length)} snapshots.`
      : `${label} ADP moved from ${first.toFixed(1)} to ${last.toFixed(1)} over the last ${String(ordered.length)} snapshots — ${movedEarlier ? "earlier, so more expensive" : "later, so less expensive"}.`;

  const active = hovered === null ? null : ordered[hovered];

  return (
    <figure className="trend-chart" data-testid="market-trend">
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        width="100%"
        height={HEIGHT}
        role="img"
        aria-labelledby={titleId}
        preserveAspectRatio="none"
      >
        <title id={titleId}>{summary}</title>
        <path className="trend-line" d={path} fill="none" data-kind={movedEarlier ? "earlier" : "later"} />
        {ordered.map((point, index) => (
          <circle
            key={point.observed_at}
            className="trend-point"
            cx={x(index)}
            cy={y(point.market_adp)}
            r={index === hovered ? 3.2 : 1.8}
            data-latest={index === ordered.length - 1 ? "true" : undefined}
            onMouseEnter={() => {
              setHovered(index);
            }}
            onMouseLeave={() => {
              setHovered(null);
            }}
            onFocus={() => {
              setHovered(index);
            }}
            onBlur={() => {
              setHovered(null);
            }}
            tabIndex={0}
            role="button"
            aria-label={`${formatDay(point.observed_at)}: ADP ${point.market_adp.toFixed(1)}`}
          />
        ))}
      </svg>
      <figcaption className="trend-caption">
        {/* The reading, in words, for everyone — not a tooltip-only fact. Touch devices get
            no hover, and a caption is reachable where a title attribute is not. */}
        <span className="trend-reading">
          {active === undefined || active === null
            ? `Latest ${last.toFixed(1)}`
            : `${formatDay(active.observed_at)} · ${active.market_adp.toFixed(1)}`}
        </span>
        <span className="trend-direction" data-kind={movedEarlier ? "earlier" : "later"}>
          {last === first
            ? "unchanged"
            : movedEarlier
              ? "▲ moving earlier"
              : "▼ moving later"}
        </span>
        {trend !== null && (
          <span className="trend-slope muted">{`${trend > 0 ? "+" : ""}${trend.toFixed(2)}/day`}</span>
        )}
        <span className="visually-hidden">{summary}</span>
      </figcaption>
    </figure>
  );
}
