/**
 * The Draft Rail: fair rank against MyFantasyLeague ADP, one paired rail per player.
 *
 * D3 supplies the pick scale; React draws. Every coordinate is an artifact value — the fair
 * anchor is `fair_rank` from the arbitrage record and the market anchor is `market_adp`.
 * Nothing here recomputes a gap or a score.
 *
 * Two things the chart has to make obvious without colour:
 *
 * - **direction.** Pick numbers run the wrong way round for intuition (earlier is smaller), so
 *   the axis says which end is which and every row carries a sentence: "market drafts him 14.5
 *   picks later".
 * - **what it is not.** V1 has no learned surplus model, so no rail claims expected points or
 *   dollars gained (ADR-010). The length of a connector is picks, and only picks.
 *
 * Tier boundaries are deliberately absent: A0 consumes fair rank and never a tier edge
 * (ADR-040), so drawing one here would imply an input the score does not have.
 */

import { scaleLinear } from "d3-scale";
import { useCallback, useMemo, useRef } from "react";

import { useElementWidth } from "../components/useElementWidth";
import { useRovingMarks } from "./useRovingMarks";
import { formatAdp, formatRank } from "../data/format";
import { describeGap } from "../data/market";
import type { ArbitrageRow } from "../data/model";
import { statusBadge } from "../data/model";

const MARGIN = { top: 26, right: 16, bottom: 30, left: 14 };
const ROW_HEIGHT = 22;
const NAME_WIDTH_WIDE = 168;
const NAME_WIDTH_COMPACT = 116;
const GAP_WIDTH = 136;

export function DraftRail({
  rows,
  onSelect,
  selectedPlayerId,
}: {
  readonly rows: readonly ArbitrageRow[];
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
}): React.JSX.Element {
  const container = useRef<HTMLDivElement>(null);
  const width = useElementWidth(container, 1040);
  const compact = width < 720;
  const nameWidth = compact ? NAME_WIDTH_COMPACT : NAME_WIDTH_WIDE;
  const gapWidth = compact ? 112 : GAP_WIDTH;
  const railWidth = Math.max(width - MARGIN.left - MARGIN.right - nameWidth - gapWidth, 140);

  const scale = useMemo(() => {
    const picks = rows.flatMap((row) => [row.record.fair_rank, row.record.market_adp]);
    const max = picks.length === 0 ? 300 : Math.max(...picks);
    // Pick 1 sits at the left. Numbers increase rightward, and the axis title names both ends
    // so nobody has to work out which direction is "cheap".
    return scaleLinear().domain([1, Math.ceil(max / 25) * 25]).range([0, railWidth]);
  }, [railWidth, rows]);

  const activate = useCallback(
    (index: number) => {
      const row = rows[index];
      if (row !== undefined) onSelect(row.record.player_id);
    },
    [onSelect, rows],
  );
  const roving = useRovingMarks(rows.length, activate);

  if (rows.length === 0) {
    return (
      <div className="chart-frame" ref={container}>
        <p className="muted">No priced players match the current filters.</p>
      </div>
    );
  }

  const height = MARGIN.top + rows.length * ROW_HEIGHT + MARGIN.bottom;
  const railLeft = MARGIN.left + nameWidth;
  const ticks = scale.ticks(compact ? 4 : 7);

  return (
    <div className="chart-frame" ref={container}>
      <svg
        role="img"
        viewBox={`0 0 ${String(Math.max(width, 320))} ${String(height)}`}
        aria-labelledby="draft-rail-title draft-rail-desc"
      >
        <title id="draft-rail-title">Draft rail</title>
        <desc id="draft-rail-desc">
          {`${String(rows.length)} players. Each row pairs the model's fair rank, drawn as a filled ` +
            "diamond, with the MyFantasyLeague average draft position, drawn as an open circle. " +
            "A market anchor to the right of the fair anchor means the market drafts him later " +
            "than his fair rank, which is the bargain direction. The arbitrage table below " +
            "carries the same numbers."}
        </desc>

        <g transform={`translate(${String(railLeft)},0)`}>
          {ticks.map((tick) => (
            <line
              key={tick}
              className="grid-line"
              x1={scale(tick)}
              x2={scale(tick)}
              y1={MARGIN.top - 8}
              y2={height - MARGIN.bottom}
            />
          ))}
          {ticks.map((tick) => (
            <text
              key={tick}
              className="axis-label"
              x={scale(tick)}
              y={MARGIN.top - 12}
              textAnchor="middle"
            >
              {tick}
            </text>
          ))}
        </g>

        {rows.map((row, index) => {
          const record = row.record;
          const y = MARGIN.top + index * ROW_HEIGHT + ROW_HEIGHT / 2;
          const gap = describeGap(record.rank_gap);
          const fairX = railLeft + scale(record.fair_rank);
          const marketX = railLeft + scale(record.market_adp);
          const badge = statusBadge(row.status);
          const selected = record.player_id === selectedPlayerId;
          return (
            <g
              key={record.player_id}
              className="player-mark"
              role="button"
              {...roving.markProps(index)}
              aria-label={
                `${record.display_name}, ${record.position}, fair rank ` +
                `${formatRank(record.fair_rank)}, MyFantasyLeague ADP ${formatAdp(record.market_adp)}. ` +
                gap.sentence +
                (badge === null ? "" : ` Current status ${badge.full}, annotation only.`)
              }
              onClick={() => {
                onSelect(record.player_id);
              }}
            >
              {selected && (
                <rect
                  x={MARGIN.left - 4}
                  y={y - ROW_HEIGHT / 2}
                  width={Math.max(width - MARGIN.left - MARGIN.right + 8, 0)}
                  height={ROW_HEIGHT}
                  fill="currentColor"
                  opacity={0.06}
                  rx={3}
                />
              )}
              <text className="rail-name" x={MARGIN.left} y={y + 4} aria-hidden="true">
                {truncate(record.display_name, compact ? 15 : 22)}
              </text>
              <line
                className="rail-connector"
                data-kind={gap.kind}
                x1={fairX}
                x2={marketX}
                y1={y}
                y2={y}
                strokeWidth={2}
                strokeLinecap="round"
              />
              {/* Fair anchor: a filled diamond. Market anchor: an open circle. Two shapes, so
                  the pair reads without relying on hue. */}
              <path
                className="rail-fair"
                d={`M ${String(fairX)} ${String(y - 4.6)} L ${String(fairX + 4.6)} ${String(y)} L ${String(fairX)} ${String(y + 4.6)} L ${String(fairX - 4.6)} ${String(y)} Z`}
              />
              <circle className="rail-market" cx={marketX} cy={y} r={4.2} />
              <text
                className="rail-gap"
                data-kind={gap.kind}
                x={Math.max(width - MARGIN.right, 0)}
                y={y + 4}
                textAnchor="end"
                aria-hidden="true"
              >
                {`${gap.kind === "bargain" ? "→ " : gap.kind === "premium" ? "← " : ""}${gap.compact}`}
              </text>
            </g>
          );
        })}

        <text className="axis-title" x={railLeft} y={height - 8}>
          Earlier picks
        </text>
        <text
          className="axis-title"
          x={Math.max(width - MARGIN.right, 0)}
          y={height - 8}
          textAnchor="end"
        >
          Later picks
        </text>
      </svg>
    </div>
  );
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}
