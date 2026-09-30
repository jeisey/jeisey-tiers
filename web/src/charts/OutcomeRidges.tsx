/**
 * The duel's picture: every contender's week as a shape, on one points axis (ADR-096).
 *
 * **Why a shape and not a bar.** Two players with the same median are different starts when
 * one of them is a touchdown-or-nothing receiver and the other is a volume back — and a bar
 * ending at the median hides exactly that. Each ridge is the published distribution itself:
 * the 200-point grid `quantile_distribution_v1` builds from the seven quantiles, binned and
 * lightly smoothed. The P25–P75 box, the P10–P90 whisker and the median tick are drawn over
 * it from the published quantiles, so the readable marks are exact and the shape is context.
 *
 * **One scale for every ridge.** The heights share one maximum, so a wide distribution looks
 * flat and a narrow one tall — which is the truth about their certainty, and the reason a
 * chart that normalised each ridge to its own peak would mislead.
 *
 * **The dashed line is the reader's league.** The points the last starter at his position
 * scored in an average week, for this league size and scoring (measured, published in the
 * build metadata). Where a ridge sits against it is what "is he startable" means.
 *
 * Direction and identity are never colour alone: every ridge carries its slot letter and its
 * player's name, and the whole figure has a text equivalent in the cards and the matrix.
 */

import { useMemo, useRef } from "react";

import { useElementWidth } from "../components/useElementWidth";
import type { Contender } from "../data/duel";
import { formatValue } from "../data/format";

const BINS = 64;
const SLOT_LETTERS = ["A", "B", "C", "D"] as const;

export function slotLetter(index: number): string {
  return SLOT_LETTERS[index] ?? "?";
}

function smooth(values: number[]): number[] {
  const kernel = [0.06, 0.24, 0.4, 0.24, 0.06];
  return values.map((_, index) => {
    let total = 0;
    let weight = 0;
    kernel.forEach((k, offset) => {
      const at = index + offset - 2;
      if (at >= 0 && at < values.length) {
        total += k * (values[at] ?? 0);
        weight += k;
      }
    });
    return weight === 0 ? 0 : total / weight;
  });
}

function niceStep(span: number): number {
  if (span <= 12) return 2;
  if (span <= 30) return 5;
  if (span <= 60) return 10;
  return 20;
}

export function OutcomeRidges({
  contenders,
}: {
  readonly contenders: readonly Contender[];
}): React.JSX.Element | null {
  const wrapper = useRef<HTMLDivElement>(null);
  const width = useElementWidth(wrapper, 880);
  const drawable = contenders.flatMap((contender, slot) =>
    contender.grid === null ? [] : [{ contender, slot, grid: contender.grid }],
  );

  const geometry = useMemo(() => {
    if (drawable.length === 0) return null;
    let low = Infinity;
    let high = -Infinity;
    for (const { contender, grid } of drawable) {
      low = Math.min(low, grid[0] ?? 0, contender.startable?.threshold ?? Infinity);
      high = Math.max(high, grid[grid.length - 1] ?? 0, contender.startable?.threshold ?? -Infinity);
    }
    low = Math.floor(Math.min(low, 0));
    high = Math.ceil(high + 1);
    const step = niceStep(high - low);
    const ticks: number[] = [];
    for (let tick = Math.ceil(low / step) * step; tick <= high; tick += step) ticks.push(tick);
    const densities = drawable.map(({ grid }) => {
      const counts = new Array<number>(BINS).fill(0);
      for (const value of grid) {
        const bin = Math.min(BINS - 1, Math.max(0, Math.floor(((value - low) / (high - low)) * BINS)));
        counts[bin] = (counts[bin] ?? 0) + 1;
      }
      return smooth(counts.map((count) => count / grid.length));
    });
    const peak = Math.max(...densities.flat(), 1e-9);
    return { low, high, ticks, densities, peak };
  }, [drawable]);

  if (geometry === null) return null;

  const narrow = width < 560;
  const gutter = narrow ? 8 : 168;
  const right = 20;
  const labelBand = narrow ? 18 : 0;
  const rowHeight = (narrow ? 56 : 62) + labelBand;
  const axisHeight = 28;
  const height = drawable.length * rowHeight + axisHeight + 6;
  const plot = Math.max(40, width - gutter - right);
  const x = (value: number): number =>
    gutter + ((value - geometry.low) / (geometry.high - geometry.low)) * plot;

  return (
    <div ref={wrapper} className="ridges" data-narrow={narrow ? "true" : undefined}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${String(width)} ${String(height)}`}
        aria-hidden="true"
        focusable="false"
      >
        {geometry.ticks.map((tick) => (
          <g key={tick} className="ridges-tick">
            <line x1={x(tick)} x2={x(tick)} y1={0} y2={height - axisHeight} />
            <text x={x(tick)} y={height - 10} textAnchor="middle">
              {String(tick)}
            </text>
          </g>
        ))}
        {drawable.map(({ contender, slot }, row) => {
          const top = row * rowHeight + labelBand;
          const base = top + rowHeight - labelBand - 8;
          const ridgeHeight = rowHeight - labelBand - 16;
          const density = geometry.densities[row] ?? [];
          const binWidth = (geometry.high - geometry.low) / BINS;
          const points = density.map((value, bin) => {
            const px = x(geometry.low + (bin + 0.5) * binWidth);
            const py = base - (value / geometry.peak) * ridgeHeight;
            return `${px.toFixed(1)},${py.toFixed(1)}`;
          });
          const first = x(geometry.low + 0.5 * binWidth).toFixed(1);
          const last = x(geometry.low + (BINS - 0.5) * binWidth).toFixed(1);
          const path = `M${first},${String(base)} L${points.join(" L")} L${last},${String(base)} Z`;
          const q = contender.record.quantiles;
          if (q === null) return null;
          const mid = base - 6;
          const letter = slotLetter(slot);
          return (
            <g key={contender.record.player_id} className="ridge" data-slot={letter}>
              <line className="ridge-baseline" x1={gutter} x2={gutter + plot} y1={base} y2={base} />
              <path className="ridge-area" d={path} />
              <line className="ridge-whisker" x1={x(q.q10)} x2={x(q.q90)} y1={mid} y2={mid} />
              <rect
                className="ridge-box"
                x={x(q.q25)}
                y={mid - 4}
                width={Math.max(2, x(q.q75) - x(q.q25))}
                height={8}
              />
              <line className="ridge-median" x1={x(q.q50)} x2={x(q.q50)} y1={mid - 9} y2={mid + 9} />
              <text className="ridge-median-label" x={x(q.q50)} y={mid - 12} textAnchor="middle">
                {formatValue(q.q50)}
              </text>
              {contender.startable !== null && (
                <line
                  className="ridge-threshold"
                  x1={x(contender.startable.threshold)}
                  x2={x(contender.startable.threshold)}
                  y1={top + 2}
                  y2={base}
                />
              )}
              <text
                className="ridge-label"
                x={narrow ? gutter : 8}
                y={narrow ? top - 4 : mid + 4}
                textAnchor="start"
              >
                <tspan className="ridge-letter">{letter}</tspan>
                {` ${contender.record.display_name}`}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="ridges-legend">
        <span className="ridges-key ridges-key-box" aria-hidden="true" /> P25–P75
        <span className="ridges-key ridges-key-whisker" aria-hidden="true" /> P10–P90
        <span className="ridges-key ridges-key-median" aria-hidden="true" /> median
        <span className="ridges-key ridges-key-threshold" aria-hidden="true" /> a startable week in
        your league
        <span className="ridges-axis-note">fantasy points, this week, given he plays</span>
      </p>
    </div>
  );
}
