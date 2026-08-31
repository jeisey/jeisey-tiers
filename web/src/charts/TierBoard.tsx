/**
 * The Tier Board.
 *
 * **What changed in Phase 8, and why.** Phase 6 drew one SVG chart row per player: a dot at
 * the median with a P25-P75 whisker behind it, packed into a lane per tier. It was correct
 * and it was 1,800px tall for the default top hundred, because a top back's interquartile
 * interval is wider than the whole gap between the first and twentieth median, so nothing
 * could share a row. The owner's Phase-8 review asked for a board that can be scanned during
 * a live draft without faking narrower intervals.
 *
 * The encoding here keeps every number and changes the geometry:
 *
 * - one **HUD row** per player — rank, position, name, a compact interval glyph, the median
 *   readout — instead of one chart row;
 * - the glyph is the same P25-P75 interval on the same shared board scale. It is narrower
 *   because it no longer has to share the plot with a name label, not because the interval
 *   was shortened;
 * - **tiers collapse.** The draft-relevant top of the board is open and the tail is one
 *   header row per tier, so the shape of the whole board fits on a screen and the reader
 *   opens the tier they are drafting from. `board=tiers` in the URL carries the open set,
 *   so the view is shareable like every other control.
 *
 * **A tier is a group, not a line.** Phase 4 measured tier *membership* as reproducible
 * (bootstrap ARI 0.865) and tier *boundaries* as not (boundary agreement 0.239 against a
 * 0.500 bar); across 1,200 replicates only about four cut sites on a 300-deep board survived
 * in a majority (ADR-035). So no rule, arrow or "value cliff" is drawn anywhere here. The
 * collapsed header draws the tier's own P25-P75 span as a band on the shared scale, which
 * makes the softness *visible*: adjacent tier bands overlap, because the values do.
 *
 * **The axis is `p50_vorp` and says so.** Fair rank is median simulated VORP (ADR-034).
 */

import { useCallback, useMemo, useRef } from "react";

import { StatusBadge } from "../components/primitives";
import { useElementWidth } from "../components/useElementWidth";
import { useRovingMarks } from "./useRovingMarks";
import { formatRank, formatValue } from "../data/format";
import type { TierGroup, TierRow } from "../data/model";

export const TIER_SOFT_EDGE_NOTE =
  "Tier groups are useful; exact tier edges are statistically soft. Membership reproduces " +
  "across resamples; the precise cut positions do not.";

/** How many players the open tiers hold before the rest collapse, on a first visit. */
export const DEFAULT_OPEN_DEPTH = 36;

interface Span {
  readonly low: number;
  readonly high: number;
  readonly mid: number;
}

/** The tier's own interquartile envelope, on the shared scale. Never a cut position. */
function tierSpan(group: TierGroup): Span {
  let low = Number.POSITIVE_INFINITY;
  let high = Number.NEGATIVE_INFINITY;
  for (const row of group.rows) {
    low = Math.min(low, row.record.p25_vorp);
    high = Math.max(high, row.record.p75_vorp);
  }
  const first = group.rows[0]?.record.p50_vorp ?? 0;
  return {
    low: Number.isFinite(low) ? low : first,
    high: Number.isFinite(high) ? high : first,
    mid: first,
  };
}

/**
 * Which tiers open on a first visit.
 *
 * Whole tiers only: opening half of one would put a cut position on screen as if it were a
 * threshold, which is exactly the quantity ADR-035 says is not identified. The first tier is
 * always open, so the board is never a wall of closed headers.
 */
export function defaultOpenTiers(
  groups: readonly TierGroup[],
  depth = DEFAULT_OPEN_DEPTH,
): readonly number[] {
  const open: number[] = [];
  let shown = 0;
  for (const group of groups) {
    if (open.length > 0 && shown >= depth) break;
    open.push(group.ordinal);
    shown += group.rows.length;
  }
  return open;
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

/** A percentage position on the shared scale, clamped so a rounding error cannot escape it. */
function pct(value: number, min: number, range: number): number {
  if (range <= 0) return 0;
  return Math.max(0, Math.min(100, ((value - min) / range) * 100));
}

function positionMix(group: TierGroup): readonly { position: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const row of group.rows) {
    counts.set(row.record.position, (counts.get(row.record.position) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([position, count]) => ({ position, count }))
    .sort((a, b) => b.count - a.count || a.position.localeCompare(b.position));
}

function markLabel(row: TierRow, tierLabel: string): string {
  const record = row.record;
  return (
    `${record.display_name}, ${record.position}${String(record.position_rank)}` +
    `${record.team === null ? "" : `, ${record.team}`}, tier ${tierLabel}, ` +
    `fair rank ${formatRank(record.fair_rank)}, median simulated VORP ` +
    `${formatValue(record.p50_vorp)}, P25 to P75 ${formatValue(record.p25_vorp)} ` +
    `to ${formatValue(record.p75_vorp)}, P10 to P90 ${formatValue(record.p10_vorp)} ` +
    `to ${formatValue(record.p90_vorp)}`
  );
}

export function TierBoard({
  groups,
  onSelect,
  selectedPlayerId,
  scoringLabel,
  openTiers,
  onToggleTier,
}: {
  readonly groups: readonly TierGroup[];
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly scoringLabel: string;
  /** The tier ordinals currently expanded. */
  readonly openTiers: ReadonlySet<number>;
  readonly onToggleTier: (ordinal: number) => void;
}): React.JSX.Element {
  const container = useRef<HTMLDivElement>(null);
  const width = useElementWidth(container, 1040);
  const compact = width < 720;

  const scale = useMemo(() => {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    for (const group of groups) {
      for (const row of group.rows) {
        min = Math.min(min, row.record.p25_vorp);
        max = Math.max(max, row.record.p75_vorp);
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1, range: 1 };
    // A whole-number step, so the ticks below read as values rather than as artefacts.
    const step = niceStep((max - min) / (compact ? 3 : 6));
    const low = Math.floor(min / step) * step;
    const high = Math.ceil(max / step) * step;
    return { min: low, max: high, range: high - low || 1, step };
  }, [compact, groups]);

  const ticks = useMemo(() => {
    const step = scale.step ?? scale.range;
    const out: number[] = [];
    for (let value = scale.min; value <= scale.max + step / 2; value += step) {
      out.push(Math.round(value * 10) / 10);
    }
    return out;
  }, [scale]);

  // One flat list over the rows that are actually rendered, in fair-rank order, so arrow keys
  // walk the open board rather than stepping into a tier the reader has closed.
  const visible = useMemo(
    () =>
      groups
        .filter((group) => openTiers.has(group.ordinal))
        .flatMap((group) => group.rows)
        .sort((a, b) => a.record.fair_rank - b.record.fair_rank)
        .map((row) => row.record.player_id),
    [groups, openTiers],
  );
  const indexOf = useMemo(() => new Map(visible.map((id, index) => [id, index])), [visible]);

  const activate = useCallback(
    (index: number) => {
      const playerId = visible[index];
      if (playerId !== undefined) onSelect(playerId);
    },
    [onSelect, visible],
  );
  const roving = useRovingMarks(visible.length, activate);

  if (groups.length === 0) {
    return (
      <div className="tier-board" ref={container}>
        <p className="muted">No players match the current filters.</p>
      </div>
    );
  }

  return (
    <div className="tier-board" ref={container}>
      <p className="visually-hidden">
        {`${String(groups.length)} tier groups of ${scoringLabel} players. Each row shows the ` +
          "player's median simulated VORP and the P25 to P75 interval around it on a shared " +
          "scale. Tier bands overlap because exact tier edges are not statistically stable. " +
          "The table below carries the same values."}
      </p>

      <div className="board-scale" aria-hidden="true">
        <span className="board-scale-track">
          {ticks.map((tick) => (
            <span
              key={tick}
              className="board-tick"
              style={{ left: `${String(pct(tick, scale.min, scale.range))}%` }}
            >
              {tick}
            </span>
          ))}
        </span>
      </div>

      <div className="board-lanes">
        {groups.map((group) => {
          const open = openTiers.has(group.ordinal);
          const span = tierSpan(group);
          const first = group.rows[0]?.record.fair_rank;
          const last = group.rows[group.rows.length - 1]?.record.fair_rank;
          const headId = `tier-head-${String(group.ordinal)}`;
          const rowsId = `tier-rows-${String(group.ordinal)}`;
          return (
            <section
              className="tier-lane"
              key={group.ordinal}
              data-open={open}
              data-parity={group.ordinal % 2 === 0 ? "even" : "odd"}
              aria-labelledby={headId}
            >
              <h3 className="tier-lane-heading">
                <button
                  type="button"
                  id={headId}
                  className="tier-head"
                  aria-expanded={open}
                  aria-controls={rowsId}
                  onClick={() => {
                    onToggleTier(group.ordinal);
                  }}
                >
                  <span className="tier-head-mark" aria-hidden="true" />
                  <span className="tier-head-name">{group.label}</span>
                  <span className="tier-head-detail">
                    <span className="tier-head-meta">
                      {`${String(group.rows.length)} player${group.rows.length === 1 ? "" : "s"}`}
                      {first !== undefined && last !== undefined && (
                        <>
                          <span className="dot-sep" aria-hidden="true" />
                          {`ranks ${formatRank(first)}–${formatRank(last)}`}
                        </>
                      )}
                    </span>
                    {!compact && (
                      <span className="tier-head-mix" aria-hidden="true">
                        {positionMix(group).map((entry) => (
                          <span key={entry.position} className="mix-chip" data-pos={entry.position}>
                            {entry.position}
                            <b>{entry.count}</b>
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                  {/* A band, never an edge. Its ends are the tier's own P25 and P75 extremes on
                      the shared scale, so neighbouring bands overlap wherever the values do —
                      which is most of the board, and is the honest picture (ADR-035, ADR-046). */}
                  <span className="tier-head-band">
                    <span
                      className="tier-band-fill"
                      style={{
                        left: `${String(pct(span.low, scale.min, scale.range))}%`,
                        width: `${String(
                          Math.max(
                            pct(span.high, scale.min, scale.range) -
                              pct(span.low, scale.min, scale.range),
                            0.8,
                          ),
                        )}%`,
                      }}
                    />
                  </span>
                  <span className="tier-head-span">
                    {`${formatValue(span.high)} → ${formatValue(span.low)}`}
                    <span className="visually-hidden">
                      {` VORP; P25 to P75 across the tier. ${open ? "Collapse" : "Expand"} this tier.`}
                    </span>
                  </span>
                </button>
              </h3>

              {/* A closed tier renders no rows at all rather than hidden ones: on a 300-deep
                  board that is a real saving, and it keeps the DOM honest about what the
                  roving-focus list contains. The container stays so `aria-controls` still
                  resolves. */}
              <ol className="tier-rows" id={rowsId} hidden={!open}>
                {open &&
                group.rows.map((row) => {
                  const record = row.record;
                  const index = indexOf.get(record.player_id) ?? 0;
                  const left = pct(record.p25_vorp, scale.min, scale.range);
                  const right = pct(record.p75_vorp, scale.min, scale.range);
                  return (
                    <li key={record.player_id}>
                      <div
                        className="board-row"
                        role="button"
                        data-selected={record.player_id === selectedPlayerId}
                        data-player={record.player_id}
                        aria-label={markLabel(row, group.label)}
                        {...roving.markProps(index)}
                        onClick={() => {
                          onSelect(record.player_id);
                        }}
                      >
                        <span className="row-rank">{formatRank(record.fair_rank)}</span>
                        <span className="row-pos pos-tag" data-pos={record.position}>
                          {record.position}
                          <b>{record.position_rank}</b>
                        </span>
                        <span className="row-name">
                          <span className="row-name-text">
                            {compact ? shortName(record.display_name) : record.display_name}
                          </span>
                          <StatusBadge status={row.status} />
                        </span>
                        {/* The interval, unchanged: P25 to P75 on the shared scale, with the
                            median as a tick. P10-P90 is in player detail and in the label. */}
                        <span className="row-interval" aria-hidden="true">
                          <span
                            className="interval-bar"
                            data-pos={record.position}
                            style={{
                              left: `${String(left)}%`,
                              width: `${String(Math.max(right - left, 0.6))}%`,
                            }}
                          />
                          <span
                            className="interval-median"
                            style={{
                              left: `${String(pct(record.p50_vorp, scale.min, scale.range))}%`,
                            }}
                          />
                        </span>
                        <span className="row-value">{formatValue(record.p50_vorp)}</span>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </section>
          );
        })}
      </div>

      <div className="board-axis" aria-hidden="true">
        <span className="board-axis-title">Median simulated VORP</span>
      </div>
    </div>
  );
}

/** 1, 2, 5, 10, 20, 50 … so an axis reads as values rather than as arbitrary thirds. */
function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}
