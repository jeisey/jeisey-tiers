/**
 * The Tier Board.
 *
 * D3 owns the scale and the geometry; React owns the elements and the state. No D3 selection
 * touches a React-managed node (`docs/ARCHITECTURE.md` section 10).
 *
 * **A tier is a group, not a line.** Phase 4 measured tier *membership* as reproducible
 * (bootstrap ARI 0.865) and tier *boundaries* as not (boundary agreement 0.239 against a
 * 0.500 bar); across 1,200 replicates only about four cut sites on a 300-deep board survived
 * in a majority, and the median promoted boundary sits on a 0.55-point cliff against an
 * 80-130-point interval (ADR-035). So the lanes here are separated by whitespace and a change
 * of surface, never by a rule, an arrow or a "value cliff" label. Drawing a hard edge would
 * be the UI asserting a quantity the measurement says is not identified.
 *
 * **The axis is `p50_vorp` and says so.** Fair rank is median simulated VORP (ADR-034), so
 * the horizontal coordinate is the statistic the ranking is actually made of, labelled
 * "Median simulated VORP" rather than a generic "value".
 */

import { scaleLinear } from "d3-scale";
import { useCallback, useMemo, useRef } from "react";

import { useElementWidth } from "../components/useElementWidth";
import { useRovingMarks } from "./useRovingMarks";
import { formatRank, formatValue } from "../data/format";
import type { TierGroup, TierRow } from "../data/model";
import { statusBadge } from "../data/model";

export const TIER_SOFT_EDGE_NOTE =
  "Tier groups are useful; exact tier edges are statistically soft. Membership reproduces " +
  "across resamples; the precise cut positions do not.";

const MARGIN = { top: 24, right: 20, bottom: 34, left: 58 };
const LANE_GAP = 10;
const ROW_HEIGHT = 17;
const DOT_RADIUS = 3.6;

interface PlacedMark {
  readonly row: TierRow;
  readonly x: number;
  readonly y: number;
  readonly x25: number;
  readonly x75: number;
  readonly labelAnchor: "start" | "end";
}

interface PlacedLane {
  readonly group: TierGroup;
  readonly top: number;
  readonly height: number;
  readonly marks: readonly PlacedMark[];
}

/**
 * Greedy row packing inside a lane.
 *
 * Each mark claims the horizontal extent of its interval *and* its label, and drops into the
 * first row where that extent is free. On the real board almost nothing shares a row, and
 * that is the finding rather than a layout failure: a top back's P25-P75 interval is wider
 * than the entire gap between the first and twentieth median. Two players packed side by side
 * would only be possible by drawing intervals too short to be true.
 *
 * Vertical position carries no meaning beyond avoiding collisions, and the legend says so.
 */
function packLane(
  rows: readonly TierRow[],
  x: (value: number) => number,
  labelWidth: (row: TierRow) => number,
  plotWidth: number,
): { readonly marks: PlacedMark[]; readonly rowCount: number } {
  const occupied: number[] = [];
  const marks: PlacedMark[] = [];
  // Highest value first, so the players a drafter looks for land in the top row of the lane.
  const ordered = [...rows].sort((a, b) => b.record.p50_vorp - a.record.p50_vorp);

  for (const row of ordered) {
    const cx = x(row.record.p50_vorp);
    const x25 = x(row.record.p25_vorp);
    const x75 = x(row.record.p75_vorp);
    // A label sits to the left of its dot unless that would run off the plot.
    const width = labelWidth(row);
    const anchor: "start" | "end" = cx - width - DOT_RADIUS - 4 < 0 ? "start" : "end";
    const left = Math.min(anchor === "end" ? cx - width - DOT_RADIUS - 4 : cx - DOT_RADIUS, x25);
    const right = Math.max(anchor === "end" ? cx + DOT_RADIUS : cx + width + DOT_RADIUS + 4, x75);

    let rowIndex = occupied.findIndex((edge) => left > edge + 8);
    if (rowIndex === -1) {
      rowIndex = occupied.length;
      occupied.push(0);
    }
    occupied[rowIndex] = Math.min(right, plotWidth);
    marks.push({
      row,
      x: cx,
      y: rowIndex * ROW_HEIGHT + ROW_HEIGHT / 2,
      x25,
      x75,
      labelAnchor: anchor,
    });
  }
  return { marks, rowCount: Math.max(occupied.length, 1) };
}

/** Generational suffixes are not surnames: "James Cook III" shortens to "Cook", never "III". */
const NAME_SUFFIXES = new Set(["jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"]);

/** Last name only when space is tight; the full name is always in the accessible label. */
export function shortName(name: string): string {
  const parts = name.split(" ").filter((part) => part !== "");
  while (parts.length > 1 && NAME_SUFFIXES.has((parts[parts.length - 1] ?? "").toLowerCase())) {
    parts.pop();
  }
  return parts.length > 1 ? (parts[parts.length - 1] ?? name) : (parts[0] ?? name);
}

function markLabel(row: TierRow, compact: boolean): string {
  return compact ? shortName(row.record.display_name) : row.record.display_name;
}

export function TierBoard({
  groups,
  onSelect,
  selectedPlayerId,
  scoringLabel,
}: {
  readonly groups: readonly TierGroup[];
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly scoringLabel: string;
}): React.JSX.Element {
  const container = useRef<HTMLDivElement>(null);
  const width = useElementWidth(container, 1040);
  const compact = width < 760;
  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 220);

  const layout = useMemo(() => {
    // The axis spans exactly the interval the chart draws — P25 to P75. Scaling to P10-P90
    // instead would spend a third of the width on tails the chart does not render, and would
    // push every median into the middle half of the plot.
    const values = groups.flatMap((group) =>
      group.rows.flatMap((row) => [row.record.p25_vorp, row.record.p75_vorp]),
    );
    const min = values.length === 0 ? 0 : Math.min(...values);
    const max = values.length === 0 ? 1 : Math.max(...values);
    const x = scaleLinear().domain([min, max]).nice().range([0, plotWidth]);

    // Measured advance width of the 10px `.mark-label` face. A character estimate rather than
    // a DOM measurement, because laying out 150 marks must not cost 150 synchronous text
    // metrics on every resize — but it is measured rather than guessed, since underestimating
    // it packs labels into space they do not have.
    const charWidth = compact ? 5.8 : 6.1;
    const labelWidth = (row: TierRow): number =>
      markLabel(row, compact).length * charWidth + (compact ? 0 : 26);

    const lanes: PlacedLane[] = [];
    let top = MARGIN.top;
    for (const group of groups) {
      const packed = packLane(group.rows, (value) => x(value), labelWidth, plotWidth);
      const height = packed.rowCount * ROW_HEIGHT + 6;
      lanes.push({ group, top, height, marks: packed.marks });
      top += height + LANE_GAP;
    }
    return { x, lanes, height: top - LANE_GAP + MARGIN.bottom };
  }, [compact, groups, plotWidth]);

  // One flat fair-rank-ordered list across all lanes, so arrow keys walk the board in the
  // order it is ranked rather than in whatever order each lane happened to pack.
  const order = useMemo(
    () =>
      groups
        .flatMap((group) => group.rows)
        .sort((a, b) => a.record.fair_rank - b.record.fair_rank)
        .map((row) => row.record.player_id),
    [groups],
  );
  const activate = useCallback(
    (index: number) => {
      const playerId = order[index];
      if (playerId !== undefined) onSelect(playerId);
    },
    [onSelect, order],
  );
  const roving = useRovingMarks(order.length, activate);

  if (groups.length === 0) {
    return (
      <div className="chart-frame" ref={container}>
        <p className="muted">No players match the current filters.</p>
      </div>
    );
  }

  const ticks = layout.x.ticks(compact ? 4 : 8);
  const plotBottom = layout.height - MARGIN.bottom;

  return (
    <div className="chart-frame" ref={container}>
      <svg
        role="img"
        viewBox={`0 0 ${String(Math.max(width, 320))} ${String(layout.height)}`}
        aria-labelledby="tier-board-title tier-board-desc"
      >
        <title id="tier-board-title">Tier board</title>
        <desc id="tier-board-desc">
          {`${String(groups.length)} tier groups of ${scoringLabel} players positioned by median ` +
            "simulated VORP, with the P25 to P75 interval drawn behind each mark. Tier groups are " +
            "drawn as soft bands because exact tier edges are not statistically stable. The table " +
            "below carries the same values."}
        </desc>

        <g transform={`translate(${String(MARGIN.left)},0)`}>
          {ticks.map((tick) => (
            <line
              key={tick}
              className="grid-line"
              x1={layout.x(tick)}
              x2={layout.x(tick)}
              y1={MARGIN.top + 2}
              y2={plotBottom}
            />
          ))}
          {/* The board is taller than a viewport, so the scale is repeated at the head as well
              as the foot; otherwise the top of the board has no reference. */}
          {ticks.map((tick) => (
            <text
              key={`head-${String(tick)}`}
              className="axis-label"
              x={layout.x(tick)}
              y={MARGIN.top - 3}
              textAnchor="middle"
            >
              {tick}
            </text>
          ))}

          {layout.lanes.map((lane) => (
            <g key={lane.group.ordinal}>
              {/* A band, not a boundary: the lane is filled and separated by whitespace, and
                  no stroke is drawn where one tier ends and the next begins (ADR-035). */}
              <rect
                className="lane-band"
                x={-MARGIN.left + 4}
                y={lane.top - 3}
                width={plotWidth + MARGIN.left - 8}
                height={lane.height}
                rx={3}
                opacity={lane.group.ordinal % 2 === 0 ? 0.85 : 0.45}
              />
              <text className="lane-label" x={-MARGIN.left + 12} y={lane.top + 13}>
                {lane.group.label}
              </text>
              <text className="lane-count" x={-MARGIN.left + 12} y={lane.top + 25}>
                {lane.group.rows.length}
              </text>

              {lane.marks.map((mark) => {
                const record = mark.row.record;
                const badge = statusBadge(mark.row.status);
                const label = markLabel(mark.row, compact);
                const selected = record.player_id === selectedPlayerId;
                const markIndex = order.indexOf(record.player_id);
                return (
                  <g
                    key={record.player_id}
                    className="player-mark"
                    role="button"
                    {...roving.markProps(markIndex)}
                    aria-label={
                      `${record.display_name}, ${record.position}${String(record.position_rank)}` +
                      `${record.team === null ? "" : `, ${record.team}`}, tier ${lane.group.label}, ` +
                      `fair rank ${formatRank(record.fair_rank)}, median simulated VORP ` +
                      `${formatValue(record.p50_vorp)}, P25 to P75 ${formatValue(record.p25_vorp)} ` +
                      `to ${formatValue(record.p75_vorp)}, P10 to P90 ${formatValue(record.p10_vorp)} ` +
                      `to ${formatValue(record.p90_vorp)}` +
                      (badge === null ? "" : `. Current status ${badge.full}, annotation only`)
                    }
                    onClick={() => {
                      onSelect(record.player_id);
                    }}
                  >
                    <line
                      className="whisker"
                      x1={mark.x25}
                      x2={mark.x75}
                      y1={lane.top + mark.y}
                      y2={lane.top + mark.y}
                    />
                    <circle
                      className="mark-dot"
                      data-pos={record.position}
                      cx={mark.x}
                      cy={lane.top + mark.y}
                      r={selected ? DOT_RADIUS + 1.5 : DOT_RADIUS}
                      stroke={selected ? "currentColor" : "none"}
                      strokeWidth={selected ? 2 : 0}
                    />
                    <text
                      className="mark-label"
                      x={mark.labelAnchor === "end" ? mark.x - DOT_RADIUS - 4 : mark.x + DOT_RADIUS + 4}
                      y={lane.top + mark.y + 3.5}
                      textAnchor={mark.labelAnchor}
                      aria-hidden="true"
                    >
                      {compact ? label : `${label} ${record.position}${String(record.position_rank)}`}
                    </text>
                  </g>
                );
              })}
            </g>
          ))}

          <line className="grid-line" x1={0} x2={plotWidth} y1={plotBottom} y2={plotBottom} />
          {ticks.map((tick) => (
            <text
              key={tick}
              className="axis-label"
              x={layout.x(tick)}
              y={plotBottom + 13}
              textAnchor="middle"
            >
              {tick}
            </text>
          ))}
          <text className="axis-title" x={plotWidth / 2} y={plotBottom + 28} textAnchor="middle">
            Median simulated VORP
          </text>
        </g>
      </svg>
    </div>
  );
}
