/**
 * Win My Matchup's picture (ADR-110 §3): how often my modelled lineup wins, by how much, and
 * where the two lineups differ — every number read off one simulation's summary.
 *
 * * **The headline** is P(win), tie and loss as whole percents, the numerical noise beside it,
 *   and the count of simulated games. The noise is the simulation's; the model's own
 *   uncertainty is the caveat under it.
 * * **The margin chart** bins my total minus theirs on the run's shared bins: bars right of the
 *   zero line are wins, left are losses, and a previewed lineup is drawn over them as a line on
 *   the same bins. At most 48 bars; no per-game marks, no animation.
 * * **The group table** compares disjoint slot groups (a FLEX back counts in FLEX only) as
 *   simulated totals with their 10th–90th percentile ranges and P(mine is higher) — group
 *   against group, never player against an arbitrarily paired player.
 */

import { useEffect, useMemo, useRef } from "react";

import { useElementWidth } from "../../components/useElementWidth";
import {
  noisePoints,
  percentLabel,
  tieLabel,
  type GroupComparison,
  type SimResult,
  type Spread,
  type VariantResult,
} from "../../data/matchup";
import { points } from "./shared";

/** The margin chart's last measured width, so a new result's chart is drawn at it first. */
let lastPlotWidth = 640;

const GROUP_LABEL: Readonly<Record<string, string>> = { QB: "QB", RB: "RB", WR: "WR", TE: "TE", FLEX: "FLEX" };

function signed(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "—";
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return (0).toFixed(digits);
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(digits)}`;
}

/** "+2.4 pts", "−1.0 pts" for a probability difference in percentage points. */
export function deltaPoints(delta: number): string {
  return `${signed(delta * 100)} pts`;
}

export function rangeText(spread: Spread): string {
  return `${points(spread.p10)}–${points(spread.p90)}`;
}

export function Headline({
  base,
  draws,
  scenario,
}: {
  readonly base: VariantResult;
  readonly draws: number;
  readonly scenario: string;
}): React.JSX.Element {
  return (
    <div className="wmm-headline" role="status">
      <p className="wmm-headline-main">
        <span className="wmm-headline-figure">{percentLabel(base.win)}</span>
        <span className="wmm-headline-words">{`your modelled lineup wins, of ${draws.toLocaleString("en-US")} simulated games`}</span>
      </p>
      <p className="wmm-headline-sub">
        <span>{`Opponent wins ${percentLabel(base.loss)}`}</span>
        <span>{`Tie ${tieLabel(base.tie)}`}</span>
        <span>{`Simulation noise ±${noisePoints(base.se).toFixed(1)} pts (95%)`}</span>
        <span className="wmm-scenario-tag">{scenario}</span>
      </p>
    </div>
  );
}

/** Margin bins → path geometry, shared by the bars and an overlaid proposal. */
function useBins(result: SimResult, compare: VariantResult | null) {
  return useMemo(() => {
    const base = result.variants[0]?.histogram ?? [];
    const other = compare?.histogram ?? null;
    const peak = Math.max(1, ...base, ...(other ?? []));
    return { base, other, peak };
  }, [result, compare]);
}

function niceTicks(start: number, end: number): number[] {
  const span = end - start;
  const step = span <= 30 ? 5 : span <= 80 ? 10 : span <= 160 ? 20 : 50;
  const ticks: number[] = [];
  for (let tick = Math.ceil(start / step) * step; tick <= end; tick += step) ticks.push(tick);
  return ticks;
}

export function MarginChart({
  result,
  compare,
  compareLabel,
}: {
  readonly result: SimResult;
  /** A previewed lineup, drawn as a line over the baseline's bars. */
  readonly compare: VariantResult | null;
  readonly compareLabel: string | null;
}): React.JSX.Element {
  const wrapper = useRef<HTMLDivElement>(null);
  // Each new result mounts a new chart: starting from the last measured width draws it once at
  // the right size instead of once at a guess and again a frame later.
  const width = useElementWidth(wrapper, lastPlotWidth);
  useEffect(() => {
    lastPlotWidth = width;
  }, [width]);
  const { base, other, peak } = useBins(result, compare);
  const { start, width: binWidth, count } = result.bins;
  const end = start + binWidth * count;
  const height = 150;
  const top = 8;
  const axis = 22;
  const plotHeight = height - top - axis;
  const left = 8;
  const right = 8;
  const plotWidth = Math.max(40, width - left - right);
  const x = (value: number): number => left + ((value - start) / (end - start)) * plotWidth;
  const y = (countValue: number): number => top + plotHeight - (countValue / peak) * plotHeight;
  const ticks = niceTicks(start, end);
  const floor = top + plotHeight;
  const bars = (win: boolean): string =>
    base
      .map((value, index) => {
        const low = start + index * binWidth;
        const barHeight = Math.max(0, floor - y(value));
        if (low >= 0 !== win || barHeight === 0) return "";
        const barWidth = Math.max(0.5, x(low + binWidth) - x(low) - 1);
        return `M${(x(low) + 0.5).toFixed(1)},${floor.toFixed(1)}v${(-barHeight).toFixed(1)}h${barWidth.toFixed(1)}v${barHeight.toFixed(1)}z`;
      })
      .join("");
  const baseVariant = result.variants[0];
  const total = result.draws;
  const line =
    other === null
      ? null
      : other
          .map((value, index) => {
            const x0 = x(start + index * binWidth);
            const x1 = x(start + (index + 1) * binWidth);
            return `${index === 0 ? "M" : "L"}${x0.toFixed(1)},${y(value).toFixed(1)}L${x1.toFixed(1)},${y(value).toFixed(1)}`;
          })
          .join("");
  return (
    <figure className="wmm-chart" aria-labelledby="wmm-chart-caption">
      <div ref={wrapper} className="wmm-chart-plot">
        <svg width={width} height={height} viewBox={`0 0 ${String(width)} ${String(height)}`} aria-hidden="true" focusable="false">
          {ticks.map((tick) => (
            <g key={tick} className="wmm-tick">
              <line x1={x(tick)} x2={x(tick)} y1={top} y2={top + plotHeight} />
              <text x={x(tick)} y={height - 6} textAnchor="middle">
                {tick > 0 ? `+${String(tick)}` : String(tick)}
              </text>
            </g>
          ))}
          {/* One path per side, a rectangle per bin: two shapes to lay out, not one per bin. */}
          <path className="wmm-bar" data-side="loss" d={bars(false)} />
          <path className="wmm-bar" data-side="win" d={bars(true)} />
          <line className="wmm-zero" x1={x(0)} x2={x(0)} y1={top - 4} y2={top + plotHeight} />
          {line !== null && <path className="wmm-overlay" d={line} />}
        </svg>
      </div>
      <figcaption id="wmm-chart-caption" className="wmm-chart-caption">
        <span className="wmm-legend" data-side="loss">Opponent ahead</span>
        <span className="wmm-legend" data-side="zero">0 = tie</span>
        <span className="wmm-legend" data-side="win">You ahead</span>
        {compareLabel !== null && <span className="wmm-legend" data-side="overlay">{`Line: ${compareLabel}`}</span>}
        <span className="visually-hidden">
          {baseVariant === undefined
            ? ""
            : `Your total minus theirs across ${total.toLocaleString("en-US")} simulated games: median ${signed(baseVariant.margin.p50)} points, 80% between ${signed(baseVariant.margin.p10)} and ${signed(baseVariant.margin.p90)}.`}
          {compare === null ? "" : ` With ${compareLabel ?? "the proposal"}: median ${signed(compare.margin.p50)}, 80% between ${signed(compare.margin.p10)} and ${signed(compare.margin.p90)}.`}
        </span>
      </figcaption>
      <details className="wmm-table-toggle">
        <summary>Margins as a table</summary>
        <MarginTable result={result} compare={compare} compareLabel={compareLabel} />
      </details>
    </figure>
  );
}

/** The chart's bins merged to at most eight rows: the text equivalent. */
function MarginTable({
  result,
  compare,
  compareLabel,
}: {
  readonly result: SimResult;
  readonly compare: VariantResult | null;
  readonly compareLabel: string | null;
}): React.JSX.Element {
  const { start, width, count } = result.bins;
  const base = result.variants[0]?.histogram ?? [];
  const group = Math.max(1, Math.ceil(count / 8));
  const rows: { low: number; high: number; base: number; other: number | null }[] = [];
  for (let index = 0; index < count; index += group) {
    const slice = (list: readonly number[]): number => list.slice(index, index + group).reduce((sum, value) => sum + value, 0);
    rows.push({
      low: start + index * width,
      high: start + Math.min(count, index + group) * width,
      base: slice(base),
      other: compare === null ? null : slice(compare.histogram),
    });
  }
  const share = (value: number): string => `${((value / result.draws) * 100).toFixed(1)}%`;
  return (
    <table className="wmm-table">
      <caption className="visually-hidden">Share of simulated games by margin (your total minus theirs)</caption>
      <thead>
        <tr>
          <th scope="col">Margin</th>
          <th scope="col">Your lineup</th>
          {compare !== null && <th scope="col">{compareLabel ?? "Proposal"}</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={row.low}>
            <th scope="row">
              {index === 0 ? `below ${signed(row.high, 0)}` : index === rows.length - 1 ? `${signed(row.low, 0)} or more` : `${signed(row.low, 0)} to ${signed(row.high, 0)}`}
            </th>
            <td>{share(row.base)}</td>
            {row.other !== null && <td>{share(row.other)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Totals({
  result,
  compare,
  compareLabel,
}: {
  readonly result: SimResult;
  readonly compare: VariantResult | null;
  readonly compareLabel: string | null;
}): React.JSX.Element | null {
  const base = result.variants[0];
  if (base === undefined) return null;
  return (
    <dl className="wmm-totals">
      <div>
        <dt>Your modelled total</dt>
        <dd>
          <strong>{points(base.mine.p50)}</strong>
          <span>{` median · 80% of games ${rangeText(base.mine)}`}</span>
        </dd>
      </div>
      {compare !== null && (
        <div data-variant="proposal">
          <dt>{`With ${compareLabel ?? "the proposal"}`}</dt>
          <dd>
            <strong>{points(compare.mine.p50)}</strong>
            <span>{` median · 80% of games ${rangeText(compare.mine)} · 90th percentile ${signed(compare.mine.p90 - base.mine.p90)}`}</span>
          </dd>
        </div>
      )}
      <div>
        <dt>Their modelled total</dt>
        <dd>
          <strong>{points(result.theirs.p50)}</strong>
          <span>{` median · 80% of games ${rangeText(result.theirs)}`}</span>
        </dd>
      </div>
    </dl>
  );
}

/** A p10–p90 bar with a median tick on a row's shared scale (decorative; the text carries it). */
function RangeBar({ spread, low, high, side }: { readonly spread: Spread; readonly low: number; readonly high: number; readonly side: "mine" | "theirs" }): React.JSX.Element {
  const span = Math.max(high - low, 1);
  const left = ((spread.p10 - low) / span) * 100;
  const width = Math.max(1, ((spread.p90 - spread.p10) / span) * 100);
  const median = ((spread.p50 - low) / span) * 100;
  return (
    <span className="wmm-range" data-side={side} aria-hidden="true">
      <span className="wmm-range-band" style={{ left: `${left.toFixed(1)}%`, width: `${width.toFixed(1)}%` }} />
      <span className="wmm-range-median" style={{ left: `${median.toFixed(1)}%` }} />
    </span>
  );
}

/** Both sides of a group are known points (finals, byes, zeros, empty slots): no simulation. */
function fixed(group: GroupComparison): boolean {
  return group.mine.p10 === group.mine.p90 && group.theirs.p10 === group.theirs.p90;
}

export function GroupTable({
  groups,
  baseline,
  label,
}: {
  readonly groups: readonly GroupComparison[];
  /** The baseline's groups, when `groups` are a previewed lineup's. */
  readonly baseline: readonly GroupComparison[] | null;
  readonly label: string;
}): React.JSX.Element {
  const before = new Map(baseline?.map((group) => [group.group, group]) ?? []);
  return (
    <div className="wmm-groups">
      {/* A focusable region: on a phone the table can scroll sideways (axe scrollable-region-focusable). */}
      <div className="wmm-groups-scroll" tabIndex={0} role="region" aria-label={label}>
      <table className="wmm-table wmm-group-table">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col">You · median (10th–90th)</th>
            <th scope="col">Them · median (10th–90th)</th>
            <th scope="col" className="wmm-range-col">
              <span className="visually-hidden">Ranges</span>
            </th>
            <th scope="col">Your group scores more</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const low = Math.min(group.mine.p10, group.theirs.p10);
            const high = Math.max(group.mine.p90, group.theirs.p90);
            const was = before.get(group.group);
            const changed = was !== undefined && Math.abs(was.ahead - group.ahead) >= 0.005;
            return (
              <tr key={group.group} data-changed={changed || undefined}>
                <th scope="row">
                  {GROUP_LABEL[group.group] ?? group.group}
                  {group.slots > 1 && <span className="wmm-muted">{` ×${String(group.slots)}`}</span>}
                </th>
                <td>
                  <strong>{points(group.mine.p50)}</strong> <span className="wmm-muted">{`(${rangeText(group.mine)})`}</span>
                </td>
                <td>
                  <strong>{points(group.theirs.p50)}</strong> <span className="wmm-muted">{`(${rangeText(group.theirs)})`}</span>
                </td>
                <td className="wmm-range-col">
                  <span className="wmm-range-pair">
                    <RangeBar spread={group.mine} low={low} high={high} side="mine" />
                    <RangeBar spread={group.theirs} low={low} high={high} side="theirs" />
                  </span>
                </td>
                <td>
                  {fixed(group) ? (
                    <span className="wmm-muted">{group.mine.p50 > group.theirs.p50 ? "Always (both fixed)" : group.mine.p50 < group.theirs.p50 ? "Never (both fixed)" : "Tied (both fixed)"}</span>
                  ) : (
                    <>
                      <strong>{percentLabel(group.ahead)}</strong>
                      {group.tie >= 0.001 && <span className="wmm-muted">{` · tie ${tieLabel(group.tie)}`}</span>}
                      {changed && was !== undefined && <span className="wmm-muted">{` (was ${percentLabel(was.ahead)})`}</span>}
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      <p className="lg-help">
        Each row compares one slot group&rsquo;s simulated total against the same group on the other side — a FLEX
        player counts in FLEX only. These are group comparisons, not head-to-head contests between paired players,
        and the matchup chance above is not their product.
      </p>
    </div>
  );
}
