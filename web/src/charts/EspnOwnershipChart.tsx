/**
 * ESPN roster and start percentages over the retained window, drawn small (ADR-112).
 *
 * **Two aligned small multiples, never one axis.** Rostered % and started % are drawn in two
 * panels that share one dated x axis and each carry their own labelled percent scale, so a
 * start share that moves with ESPN's weekly lineup rhythm can never be read off the roster
 * line's scale. Sleeper's add counts are not here: they are transactions, not a share of
 * leagues, and putting them on a percent axis would invent an exchange rate.
 *
 * **Observations, not a curve.** A point is one retained daily read that carried the player.
 * The x axis is time, because reads are not evenly spaced. Two reads more than 36 hours apart
 * are not joined: the line breaks and a dashed hairline on the floor marks the gap, because a
 * day with no read is unknown, not a straight line between its neighbours. A start share ESPN
 * did not publish in one read breaks that panel's line in the same way and is never drawn as 0.
 *
 * **Week boundaries are drawn.** Each point carries the scoring period ESPN reported as current
 * when it was read; where that changes between two points a vertical rule labelled with the new
 * period is drawn across both panels, so lineup-setting at a week rollover is not mistaken for
 * a trend.
 *
 * **Exact readings without hover.** Every point is focusable and announces its date and value;
 * the caption repeats the focused reading in text; and a table under the chart lists every read
 * exactly. Direction is never colour alone.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";

import type { EspnOwnershipPoint } from "../data/contracts";
import { exactPercent } from "../data/espn";

/** The drawing width before the container is measured (and in a test without layout). */
const FALLBACK_WIDTH = 240;
const HEIGHT = 54;
const PAD_LEFT = 5;
const PAD_RIGHT = 5;
const PAD_Y = 8;

/**
 * The plot's real pixel width, so marks are drawn at true size instead of a stretched viewBox
 * turning dots into ellipses. One observer per chart, disconnected when the chart unmounts.
 */
function useMeasuredWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(FALLBACK_WIDTH);
  useEffect(() => {
    const element = ref.current;
    if (element === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const measured = Math.round(entries[0]?.contentRect.width ?? 0);
      if (measured > 0) setWidth(measured);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);
  return [ref, width];
}
/** Reads further apart than this are not joined by a line. */
export const GAP_HOURS = 36;

type Field = "percent_rostered" | "percent_started";

const PANELS: readonly { readonly field: Field; readonly label: string; readonly short: string }[] = [
  { field: "percent_rostered", label: "Rostered %", short: "rostered" },
  { field: "percent_started", label: "Started %", short: "started" },
];

function formatDay(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
}

/** The top of a panel's percent axis: a round number at or above the largest value, at least 5. */
export function axisTop(values: readonly number[]): number {
  const peak = Math.max(0, ...values);
  if (peak >= 50) return 100;
  for (const step of [5, 10, 20, 25, 50]) if (peak <= step) return step;
  return 100;
}

/** Index pairs `[i, i+1]` that are not joined: too far apart, or a value missing on either side. */
export function segments(
  points: readonly EspnOwnershipPoint[],
  field: Field,
): readonly (readonly EspnOwnershipPoint[])[] {
  const runs: EspnOwnershipPoint[][] = [];
  let current: EspnOwnershipPoint[] = [];
  let previous: EspnOwnershipPoint | null = null;
  for (const point of points) {
    const value = point[field];
    const far =
      previous !== null &&
      (Date.parse(point.observed_at_utc) - Date.parse(previous.observed_at_utc)) / 3_600_000 > GAP_HOURS;
    if (value === null || far) {
      if (current.length > 0) runs.push(current);
      current = [];
    }
    if (value !== null) current.push(point);
    previous = point;
  }
  if (current.length > 0) runs.push(current);
  return runs;
}

/** Where ESPN's reported period changes between consecutive points, as the new period. */
export function periodBoundaries(
  points: readonly EspnOwnershipPoint[],
): readonly { readonly before: string; readonly after: string; readonly period: number }[] {
  const out: { before: string; after: string; period: number }[] = [];
  for (let index = 1; index < points.length; index += 1) {
    const prev = points[index - 1];
    const next = points[index];
    if (prev === undefined || next === undefined) continue;
    if (prev.espn_current_period !== null && next.espn_current_period !== null && prev.espn_current_period !== next.espn_current_period) {
      out.push({ before: prev.observed_at_utc, after: next.observed_at_utc, period: next.espn_current_period });
    }
  }
  return out;
}

export function EspnOwnershipChart({
  points,
}: {
  readonly points: readonly EspnOwnershipPoint[];
}): React.JSX.Element {
  const titleId = useId();
  const [focused, setFocused] = useState<{ readonly field: Field; readonly index: number } | null>(null);
  const [plotRef, WIDTH] = useMeasuredWidth();

  const stamps = useMemo(() => points.map((point) => Date.parse(point.observed_at_utc)), [points]);
  const start = Math.min(...stamps);
  const end = Math.max(...stamps);
  const elapsed = end - start;
  const x = (iso: string): number =>
    elapsed === 0 ? (PAD_LEFT + WIDTH - PAD_RIGHT) / 2 : PAD_LEFT + ((Date.parse(iso) - start) / elapsed) * (WIDTH - PAD_LEFT - PAD_RIGHT);
  const boundaries = periodBoundaries(points);
  const gapCount = segments(points, "percent_rostered").length - 1;

  const focusedPoint = focused === null ? null : (points[focused.index] ?? null);
  const latest = points[points.length - 1];

  return (
    <figure className="espn-chart" data-testid="espn-ownership-chart" data-points={points.length}>
      {PANELS.map(({ field, label, short }) => {
        const values = points.map((point) => point[field]).filter((value): value is number => value !== null);
        const top = axisTop(values);
        const y = (value: number): number => PAD_Y + (1 - value / top) * (HEIGHT - 2 * PAD_Y);
        const runs = segments(points, field);
        return (
          <div className="espn-panel" key={field} data-field={field}>
            <span className="espn-panel-label">{label}</span>
            {values.length === 0 ? (
              <p className="espn-panel-empty" data-testid={`espn-${short}-empty`}>
                ESPN published no {short} share for him in any retained read.
              </p>
            ) : (
              <div className="espn-plot">
              <span className="espn-ticks" aria-hidden="true">
                <span>{`${String(top)}%`}</span>
                <span>0%</span>
              </span>
              <div className="espn-plot-area" ref={field === "percent_rostered" ? plotRef : undefined}>
              {field === "percent_rostered" &&
                boundaries.map((boundary) => (
                  <span
                    key={`label-${boundary.after}`}
                    className="espn-period-label"
                    aria-hidden="true"
                    style={{ left: `${String(((x(boundary.before) + x(boundary.after)) / 2 / WIDTH) * 100)}%` }}
                  >
                    {`P${String(boundary.period)}`}
                  </span>
                ))}
              <svg
                viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
                width={WIDTH}
                height={HEIGHT}
                role="group"
                aria-labelledby={`${titleId}-${field}`}
              >
                <title id={`${titleId}-${field}`}>
                  {`${label} on ESPN, ${String(values.length)} retained read${values.length === 1 ? "" : "s"}, axis 0% to ${String(top)}%.`}
                </title>
                {/* The explicit percent scale: floor and top, labelled beside the plot. */}
                <line className="espn-axis" x1={PAD_LEFT} x2={WIDTH - PAD_RIGHT} y1={y(0)} y2={y(0)} />
                <line className="espn-grid" x1={PAD_LEFT} x2={WIDTH - PAD_RIGHT} y1={y(top)} y2={y(top)} />
                {boundaries.map((boundary) => {
                  const at = (x(boundary.before) + x(boundary.after)) / 2;
                  return (
                    <line
                      key={boundary.after}
                      className="espn-period"
                      data-period={boundary.period}
                      x1={at}
                      x2={at}
                      y1={PAD_Y - 4}
                      y2={HEIGHT - PAD_Y + 2}
                    />
                  );
                })}
                {runs.slice(1).map((run, index) => {
                  const before = runs[index]?.at(-1);
                  const after = run[0];
                  if (before === undefined || after === undefined) return null;
                  return (
                    <line
                      key={`gap-${after.observed_at_utc}`}
                      className="espn-gap"
                      x1={x(before.observed_at_utc)}
                      x2={x(after.observed_at_utc)}
                      y1={y(0)}
                      y2={y(0)}
                    />
                  );
                })}
                {runs.map((run) =>
                  run.length > 1 ? (
                    <path
                      key={`run-${run[0]?.observed_at_utc ?? ""}`}
                      className="espn-line"
                      data-field={field}
                      fill="none"
                      d={run
                        .map((point, index) => {
                          const value = point[field] ?? 0;
                          return `${index === 0 ? "M" : "L"}${x(point.observed_at_utc).toFixed(1)} ${y(value).toFixed(1)}`;
                        })
                        .join(" ")}
                    />
                  ) : null,
                )}
                {points.map((point, index) => {
                  const value = point[field];
                  if (value === null) return null;
                  const active = focused?.field === field && focused.index === index;
                  return (
                    <circle
                      key={point.observed_at_utc}
                      className="espn-point"
                      data-field={field}
                      data-latest={index === points.length - 1 ? "true" : undefined}
                      cx={x(point.observed_at_utc)}
                      cy={y(value)}
                      r={active ? 3.4 : 2}
                      tabIndex={0}
                      role="button"
                      aria-label={
                        `${formatDay(point.observed_at_utc)}: ${short} ${exactPercent(value)} of ESPN leagues` +
                        (point.espn_current_period === null ? "" : `, ESPN period ${String(point.espn_current_period)}`)
                      }
                      onMouseEnter={() => {
                        setFocused({ field, index });
                      }}
                      onMouseLeave={() => {
                        setFocused(null);
                      }}
                      onFocus={() => {
                        setFocused({ field, index });
                      }}
                      onBlur={() => {
                        setFocused(null);
                      }}
                      onClick={() => {
                        setFocused({ field, index });
                      }}
                    />
                  );
                })}
              </svg>
              </div>
              </div>
            )}
          </div>
        );
      })}

      <div className="espn-axis-dates" aria-hidden="true">
        <span>{formatDay(points[0]?.observed_at_utc ?? "")}</span>
        {elapsed > 0 && <span>{formatDay(latest?.observed_at_utc ?? "")}</span>}
      </div>

      <figcaption className="espn-caption">
        <span className="espn-reading" aria-live="polite">
          {focusedPoint === null || focused === null
            ? `${String(points.length)} daily read${points.length === 1 ? "" : "s"}` +
              (gapCount > 0 ? ` · ${String(gapCount)} gap${gapCount === 1 ? "" : "s"} (no read)` : "") +
              (boundaries.length > 0 ? " · week rule marks ESPN's period change" : "")
            : `${formatDay(focusedPoint.observed_at_utc)} · ${focused.field === "percent_rostered" ? "rostered" : "started"} ` +
              exactPercent(focusedPoint[focused.field] ?? 0) +
              (focusedPoint.espn_current_period === null ? "" : ` · ESPN period ${String(focusedPoint.espn_current_period)}`)}
        </span>
      </figcaption>

      <details className="espn-readings">
        <summary>{`Exact readings (${String(points.length)})`}</summary>
        <table className="sheet espn-readings-table">
          <caption className="visually-hidden">
            Every retained ESPN read for this player, oldest first: our read time, rostered and
            started shares of ESPN leagues, and the scoring period ESPN reported as current.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="plain">Read</th>
              <th scope="col" className="plain">Rostered</th>
              <th scope="col" className="plain">Started</th>
              <th scope="col" className="plain">ESPN period</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.observed_at_utc}>
                <th scope="row">{formatDay(point.observed_at_utc)}</th>
                <td className="num">{point.percent_rostered === null ? "not listed" : exactPercent(point.percent_rostered)}</td>
                <td className="num">{point.percent_started === null ? "not listed" : exactPercent(point.percent_started)}</td>
                <td className="num">{point.espn_current_period === null ? "—" : String(point.espn_current_period)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
