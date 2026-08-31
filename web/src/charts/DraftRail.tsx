/**
 * The Draft Rail: fair rank against MyFantasyLeague ADP, one HUD row per player.
 *
 * **What changed in Phase 8, and why.** Phase 6 drew an absolute pick-space rail — a shared
 * 1-to-300 axis with a filled diamond at `fair_rank`, an open circle at `market_adp` and a
 * connector between them. Judged against the real 2026 board it does not read: the axis has
 * to reach the quarterback premiums (Joe Burrow's gap is about −206 picks), so a genuine
 * eight-and-a-half-pick bargain at the top of the board is three percent of the width and
 * invisible. The sentence beside each row was doing all the work and the geometry none of it.
 *
 * So the geometry now encodes the quantity the view is about: the **signed gap**, on a
 * symmetric scale centred on zero. Bargains extend right, premiums left, and the scale is
 * sized to the population actually shown so ordinary gaps have room. A row whose gap runs off
 * the scale keeps its exact number and gains an overflow chevron — clipped, never rescaled to
 * imply a magnitude it does not have.
 *
 * What did **not** change: every coordinate is still an artifact value. `fair_rank` and
 * `market_adp` are printed as their own readouts beside the bar, `rank_gap` is the bar, and
 * `arbitrage_score` is the published percentile. Nothing here recomputes a gap or a score.
 *
 * Two things the rail still has to make obvious without colour:
 *
 * - **direction** — a glyph, a word and a side, not a hue. Pick numbers run the wrong way
 *   round for intuition, so "later" and "earlier" are spelled out on every row.
 * - **what it is not** — V1 has no learned surplus model, so no row claims expected points,
 *   dollars or a probability (ADR-010). The bar is picks, and only picks.
 *
 * Tier boundaries are deliberately absent: A0 consumes fair rank and never a tier edge
 * (ADR-040), so drawing one here would imply an input the score does not have.
 */

import { useCallback, useMemo, useRef } from "react";

import { StatusBadge } from "../components/primitives";
import { useElementWidth } from "../components/useElementWidth";
import { shortName } from "./TierBoard";
import { useRovingMarks } from "./useRovingMarks";
import { formatAdp, formatRank, formatScore, formatSigned } from "../data/format";
import { describeGap } from "../data/market";
import { statusBadge } from "../data/model";
import type { ArbitrageRow } from "../data/model";

/**
 * The scale bound, in picks.
 *
 * The 85th percentile of the shown population's absolute gaps, floored at 10 so a board of
 * near-even rows does not turn rounding into a full-width bar, and ceilinged at 120 so one
 * structural quarterback premium cannot flatten every other row to a hairline. Rows beyond it
 * are marked as beyond it.
 */
export function railBound(gaps: readonly number[]): number {
  if (gaps.length === 0) return 10;
  const sorted = [...gaps].map(Math.abs).sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.85));
  const percentile = sorted[index] ?? 10;
  return Math.max(10, Math.min(120, Math.ceil(percentile / 5) * 5));
}

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

  const bound = useMemo(() => railBound(rows.map((row) => row.record.rank_gap)), [rows]);

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
      <div className="draft-rail" ref={container}>
        <p className="muted">No priced players match the current filters.</p>
      </div>
    );
  }

  return (
    <div className="draft-rail" ref={container}>
      <p className="visually-hidden">
        {`${String(rows.length)} players. Each row pairs the model's fair rank with the ` +
          "MyFantasyLeague average draft position and shows the signed difference in picks. " +
          "A positive difference means the market drafts him later than his fair rank, which " +
          "is the bargain direction. The arbitrage table below carries the same numbers."}
      </p>

      <div className="rail-scale" aria-hidden="true">
        <span className="rail-scale-track">
          <span className="rail-scale-end">{`← ${String(bound)} picks earlier`}</span>
          <span className="rail-scale-mid">fair rank</span>
          <span className="rail-scale-end">{`${String(bound)} picks later →`}</span>
        </span>
      </div>

      <ol className="rail-rows">
        {rows.map((row, index) => {
          const record = row.record;
          const gap = describeGap(record.rank_gap);
          const badge = statusBadge(row.status);
          const magnitude = Math.min(Math.abs(record.rank_gap), bound) / bound;
          const overflow = Math.abs(record.rank_gap) > bound;
          return (
            <li key={record.player_id}>
              <div
                className="rail-row"
                role="button"
                data-selected={record.player_id === selectedPlayerId}
                data-player={record.player_id}
                data-kind={gap.kind}
                aria-label={
                  `${record.display_name}, ${record.position}, fair rank ` +
                  `${formatRank(record.fair_rank)}, MyFantasyLeague ADP ` +
                  `${formatAdp(record.market_adp)}. ${gap.sentence} ` +
                  `Arbitrage score ${formatScore(record.arbitrage_score)}.` +
                  (badge === null ? "" : ` Current status ${badge.full}, annotation only.`)
                }
                {...roving.markProps(index)}
                onClick={() => {
                  onSelect(record.player_id);
                }}
              >
                <span className="rail-pos pos-tag" data-pos={record.position}>
                  {record.position}
                </span>
                <span className="rail-name">
                  <span className="rail-name-text">
                    {compact ? shortName(record.display_name) : record.display_name}
                  </span>
                  <StatusBadge status={row.status} />
                </span>

                <span className="rail-anchors" aria-hidden="true">
                  <span className="rail-anchor">
                    <span className="rail-anchor-label">Fair</span>
                    {formatRank(record.fair_rank)}
                  </span>
                  <span className="rail-anchor">
                    <span className="rail-anchor-label">ADP</span>
                    {formatAdp(record.market_adp)}
                  </span>
                </span>

                {/* Zero is the centre and it is where fair rank sits. The bar grows toward the
                    side the market is on: right when it drafts him later (a bargain), left
                    when it drafts him earlier (a premium). */}
                <span className="rail-delta" aria-hidden="true">
                  <span className="rail-axis" />
                  <span
                    className="rail-fill"
                    data-kind={gap.kind}
                    style={
                      gap.kind === "bargain"
                        ? { left: "50%", width: `${String(magnitude * 50)}%` }
                        : gap.kind === "premium"
                          ? { right: "50%", width: `${String(magnitude * 50)}%` }
                          : { left: "50%", width: "0%" }
                    }
                  />
                  {overflow && (
                    <span className="rail-overflow" data-kind={gap.kind}>
                      {gap.kind === "bargain" ? "▸" : "◂"}
                    </span>
                  )}
                </span>

                <span className="rail-gap" data-kind={gap.kind} aria-hidden="true">
                  <span className="rail-gap-value">{formatSigned(record.rank_gap)}</span>
                  <span className="rail-gap-word">
                    {gap.kind === "bargain" ? "later" : gap.kind === "premium" ? "earlier" : "even"}
                  </span>
                </span>
                <span className="rail-score" aria-hidden="true">
                  {formatScore(record.arbitrage_score)}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
