/**
 * The Opportunity Board chart.
 *
 * **Two tracks, never one.** The draft-season question had a price to draw against, so the
 * Draft Rail could put a fair rank and an ADP on one axis and call the distance between them
 * a gap. In November there is no price: there is a rest-of-season value in points, and a count
 * of roster transactions over a declared window. Those have no common unit, and `AGENTS.md`
 * is explicit that this board is three orderings over unlike quantities with no blend — so the
 * picture is two tracks with their own scales, their own headers and a rule between them, and
 * a reader is never offered a single position that claims to combine them.
 *
 * That constraint is the design, not a limitation worked around. The useful in-season question
 * is exactly a comparison of two separate readings — *is the wire moving on someone the model
 * still rates?* — and it is answered by putting the two beside each other and letting the eye
 * find the rows where they disagree. Averaging them into one score would destroy the only
 * thing the picture is for.
 *
 * **The moves track is diverging and centred on zero.** Adds run right, drops run left, from a
 * shared centre line on a symmetric scale. Neither side is "good": a count is a count, and the
 * direction is carried by the side of the line, by the printed numbers and by the accessible
 * label as well as by colour (`AGENTS.md` section 11).
 *
 * **Behaviour decides visibility, never value.** A player surfaced from beyond the published
 * tier depth carries the rest-of-season value the model gave him and no tier at all, and says
 * so. When the feed is down the moves track is drawn empty and labelled, and every value
 * beside it is untouched.
 *
 * The vocabulary — the lane grid, the tick header, the glowing mark, the axis footer — is
 * artboard 2a's, the same one the Tier Board uses. Like the Draft Rail before it, this board
 * has no artboard of its own (`docs/DESIGN_SOURCE_MAP.md` section 6), so it borrows the
 * system rather than inventing a second one.
 */

import { useCallback, useMemo, useRef } from "react";

import { useElementWidth } from "../components/useElementWidth";
import { useRovingMarks } from "./useRovingMarks";
import { formatRank, formatValue } from "../data/format";
// The population bound is a rule over published counts rather than a geometry, and the player
// card draws the same strip from it, so it lives in `data/ros` and has one definition.
import { movesBound } from "../data/ros";
import type { Position } from "../data/contracts";

/** One row of the board. Every field is read from the artifact; nothing here is derived. */
export interface OpportunityMark {
  readonly playerId: string;
  readonly rosRank: number;
  readonly position: Position;
  readonly positionRank: number;
  readonly displayName: string;
  readonly rosExpectedVorp: number;
  readonly addCount: number | null;
  readonly dropCount: number | null;
  readonly netAddCount: number | null;
  readonly snapShare: number | null;
  readonly surfaced: boolean;
  readonly badges?: React.ReactNode;
  readonly label: string;
}

interface Scale {
  readonly min: number;
  readonly max: number;
  readonly range: number;
  readonly step: number;
}

/** A percentage position on a scale, clamped so a rounding error cannot escape the track. */
function pct(value: number, scale: Scale): number {
  if (scale.range <= 0) return 0;
  return Math.max(0, Math.min(100, ((value - scale.min) / scale.range) * 100));
}

/** 1, 2, 5, 10, 20, 50 … so an axis reads as values rather than as arbitrary thirds. */
function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function valueScale(marks: readonly OpportunityMark[], divisions: number): Scale {
  let min = 0;
  let max = 0;
  for (const mark of marks) {
    min = Math.min(min, mark.rosExpectedVorp);
    max = Math.max(max, mark.rosExpectedVorp);
  }
  // Zero is always on the scale: a bar grows from it, and a negative rest-of-season value is a
  // real reading rather than an artefact to hide by cropping the axis at the smallest number.
  const step = niceStep((max - min) / divisions);
  const low = Math.floor(min / step) * step;
  const high = Math.ceil(max / step) * step;
  return { min: low, max: high, range: high - low || 1, step };
}

/**
 * The moves scale: symmetric about zero, sized by `movesBound`.
 *
 * Symmetric on purpose. An asymmetric diverging axis makes twelve adds and twelve drops
 * different lengths, which is a picture of a difference that is not in the data.
 */
function movesScale(marks: readonly OpportunityMark[], divisions: number): Scale {
  const counts: number[] = [];
  for (const mark of marks) {
    if (mark.addCount !== null) counts.push(mark.addCount);
    if (mark.dropCount !== null) counts.push(mark.dropCount);
  }
  const widest = movesBound(counts);
  // At least 1, because these are counts of transactions: a tick strip reading
  // "1 · 0.5 · 0 · 0.5 · 1" on a quiet board would label half a roster move.
  const step = Math.max(1, niceStep(widest / divisions));
  const bound = Math.max(step, Math.ceil(widest / step) * step);
  return { min: -bound, max: bound, range: bound * 2, step };
}

function ticksOf(scale: Scale): readonly number[] {
  const out: number[] = [];
  for (let value = scale.min; value <= scale.max + scale.step / 2; value += scale.step) {
    out.push(Math.round(value * 100) / 100);
  }
  return out;
}

/** A count, or the em dash that means the feed said nothing — never a zero standing in. */
function countText(value: number | null): string {
  return value === null ? "—" : String(value);
}

export function OpportunityBoard({
  marks,
  windowLabel,
  behaviorAvailable,
  orderLabel,
  onSelect,
  selectedPlayerId,
}: {
  readonly marks: readonly OpportunityMark[];
  /** The requested behaviour window, e.g. `24h`, straight from the artifact. */
  readonly windowLabel: string;
  readonly behaviorAvailable: boolean;
  /** Which of the three orderings the rows are in, for the accessible summary. */
  readonly orderLabel: string;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
}): React.JSX.Element {
  const container = useRef<HTMLDivElement>(null);
  const width = useElementWidth(container, 1040);
  const compact = width < 768;

  const value = useMemo(() => valueScale(marks, compact ? 2 : 5), [compact, marks]);
  const moves = useMemo(() => movesScale(marks, compact ? 1 : 2), [compact, marks]);
  const valueTicks = useMemo(() => ticksOf(value), [value]);
  const movesTicks = useMemo(() => ticksOf(moves), [moves]);
  const valueZero = pct(0, value);
  const movesZero = pct(0, moves);

  const ids = useMemo(() => marks.map((mark) => mark.playerId), [marks]);
  const activate = useCallback(
    (index: number) => {
      const playerId = ids[index];
      if (playerId !== undefined) onSelect(playerId);
    },
    [ids, onSelect],
  );
  const roving = useRovingMarks(ids.length, activate);

  if (marks.length === 0) {
    return (
      <div className="opp-board" ref={container}>
        <p className="muted">No players match the current filters.</p>
      </div>
    );
  }

  return (
    <div className="opp-board" ref={container}>
      <p className="visually-hidden">
        {`${String(marks.length)} players, ordered by ${orderLabel}. Each row carries two ` +
          "separate readings on two separate scales: rest-of-season expected VORP in points, " +
          "and roster adds and drops as counts of transactions over the " +
          `${windowLabel} window. They are never combined into one number, because a count of ` +
          "transactions and a projected value have no common unit. The table below carries " +
          "the same values."}
      </p>

      {/*
        The scale header, two rows deep on purpose.

        The names span each track *and* its readout column; the ticks sit on the track column
        alone, which is the column the bars below occupy. That separation is load-bearing — a
        tick strip laid over track-plus-readout is wider than the bars it labels, so every
        reading comes out shifted, which is the alignment defect `TierBoard` records against
        its own axis. The divider between the two tracks is a border rather than a gap, because
        "these are two measurements" is the claim the whole board rests on.
      */}
      <div className="opp-scale" aria-hidden="true">
        <span className="opp-scale-head">Player</span>
        <span className="opp-track-name" data-track="value">
          ROS value
        </span>
        <span className="opp-track-name" data-track="moves">
          {behaviorAvailable ? `Roster moves · ${windowLabel}` : "Roster moves · none"}
        </span>
        <span className="opp-scale-unit" data-col="snap">
          Snap
        </span>
        <span className="opp-scale-unit" data-col="net">
          Net
        </span>
        <span className="opp-scale-ticks" data-track="value">
          {!compact &&
            valueTicks.map((tick) => (
              <span
                key={tick}
                className="opp-tick"
                style={{ left: `${String(pct(tick, value))}%` }}
              >
                {tick}
              </span>
            ))}
        </span>
        <span className="opp-scale-ticks" data-track="moves">
          {!compact &&
            behaviorAvailable &&
            movesTicks.map((tick) => (
              <span
                key={tick}
                className="opp-tick"
                style={{ left: `${String(pct(tick, moves))}%` }}
              >
                {Math.abs(tick)}
              </span>
            ))}
        </span>
      </div>

      <ol className="opp-rows">
        {marks.map((mark, index) => {
          const vorpAt = pct(mark.rosExpectedVorp, value);
          const adds = mark.addCount ?? 0;
          const drops = mark.dropCount ?? 0;
          const addsAt = pct(adds, moves);
          const dropsAt = pct(-drops, moves);
          return (
            <li key={mark.playerId}>
              <div
                className="opp-row"
                role="button"
                data-selected={mark.playerId === selectedPlayerId}
                data-player={mark.playerId}
                data-surfaced={mark.surfaced ? "true" : undefined}
                aria-label={mark.label}
                {...roving.markProps(index)}
                onClick={() => {
                  onSelect(mark.playerId);
                }}
              >
                <span className="row-rank">{formatRank(mark.rosRank)}</span>
                <span className="row-pos pos-tag" data-pos={mark.position}>
                  {mark.position}
                  <b>{mark.positionRank}</b>
                </span>
                <span className="row-name">
                  <span className="row-name-text">{mark.displayName}</span>
                  {mark.badges}
                </span>

                {/* Track one: the model's remaining value, as a bar from zero. */}
                <span className="opp-track" data-track="value" aria-hidden="true">
                  <span className="opp-zero" style={{ left: `${String(valueZero)}%` }} />
                  <span
                    className="opp-value-bar"
                    data-pos={mark.position}
                    data-sign={mark.rosExpectedVorp < 0 ? "negative" : "positive"}
                    style={{
                      left: `${String(Math.min(valueZero, vorpAt))}%`,
                      width: `${String(Math.max(Math.abs(vorpAt - valueZero), 0.5))}%`,
                    }}
                  />
                  <span className="opp-value-mark" style={{ left: `${String(vorpAt)}%` }} />
                </span>
                <span className="opp-readout" data-track="value">
                  {formatValue(mark.rosExpectedVorp)}
                </span>

                {/* Track two: transactions, diverging from their own zero on their own scale.
                    A count past the axis bound keeps its bar at the edge and says so with a
                    chevron — the number itself is printed beside the track either way, so a
                    clipped bar never becomes a wrong reading (the Draft Rail's own rule). */}
                <span className="opp-track" data-track="moves" aria-hidden="true">
                  <span className="opp-zero" style={{ left: `${String(movesZero)}%` }} />
                  {behaviorAvailable ? (
                    <>
                      <span
                        className="opp-move-bar"
                        data-kind="drop"
                        style={{
                          left: `${String(dropsAt)}%`,
                          width: `${String(Math.max(movesZero - dropsAt, drops > 0 ? 0.5 : 0))}%`,
                        }}
                      />
                      <span
                        className="opp-move-bar"
                        data-kind="add"
                        style={{
                          left: `${String(movesZero)}%`,
                          width: `${String(Math.max(addsAt - movesZero, adds > 0 ? 0.5 : 0))}%`,
                        }}
                      />
                      {adds > moves.max && (
                        <span className="opp-overflow" data-kind="add">
                          ›
                        </span>
                      )}
                      {drops > moves.max && (
                        <span className="opp-overflow" data-kind="drop">
                          ‹
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="opp-track-empty" />
                  )}
                </span>
                <span className="opp-readout" data-track="moves">
                  <span className="opp-count" data-kind="drop" data-zero={drops === 0}>
                    {countText(mark.dropCount)}
                  </span>
                  <span className="opp-count-sep">/</span>
                  <span className="opp-count" data-kind="add" data-zero={adds === 0}>
                    {countText(mark.addCount)}
                  </span>
                </span>

                {/* Usage, on its own bounded 0-100 scale: a share, never a count. */}
                <span className="opp-snap">
                  {mark.snapShare === null ? (
                    <span className="opp-snap-none" aria-hidden="true">
                      —
                    </span>
                  ) : (
                    <>
                      <span className="opp-snap-track" aria-hidden="true">
                        <span
                          className="opp-snap-fill"
                          style={{
                            width: `${String(Math.max(0, Math.min(100, mark.snapShare * 100)))}%`,
                          }}
                        />
                      </span>
                      <span className="opp-snap-value">
                        {`${String(Math.round(mark.snapShare * 100))}%`}
                      </span>
                    </>
                  )}
                </span>

                <span
                  className="opp-net"
                  data-change={
                    mark.netAddCount === null
                      ? "none"
                      : mark.netAddCount > 0
                        ? "up"
                        : mark.netAddCount < 0
                          ? "down"
                          : "flat"
                  }
                >
                  {mark.netAddCount === null
                    ? "—"
                    : mark.netAddCount > 0
                      ? `+${String(mark.netAddCount)}`
                      : String(mark.netAddCount)}
                </span>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="opp-axis" aria-hidden="true">
        <span className="board-axis-title">Rest-of-season expected VORP</span>
        <span className="board-axis-range">
          {`${formatValue(value.min)} to ${formatValue(value.max)}`}
        </span>
        <span className="legend-sep" />
        <span className="board-axis-title">
          {behaviorAvailable
            ? `Drops ← 0 → adds · ${windowLabel} · axis ±${String(moves.max)}, a chevron marks a count past it`
            : "Roster moves unavailable in this build"}
        </span>
        <span className="board-axis-title">
          Two scales, never combined · rows in {orderLabel} order
        </span>
      </div>
    </div>
  );
}
