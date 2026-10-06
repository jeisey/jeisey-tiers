/**
 * Role, week by week: small multiples on one shared week axis (ADR-091).
 *
 * **The question it is drawn to answer.** "Did his role change before his box score did?"
 * One rail per role metric — the ones his position leads with — and, beneath them on the same
 * week axis, his fantasy points. A back whose snap and carry rails climb while the points
 * rail has not moved yet is the picture a waiver claim is made on, and it is legible at a
 * glance in a way three percentages in a row are not.
 *
 * **It draws published values; the reading beside each rail is published too.** A bar is a
 * week's value from `player_usage.json`. The number beside it is the artifact's own latest
 * value, and the change is the artifact's own `role_change_v1` difference — nothing here
 * subtracts, averages or rescales a published number. The window a change was measured over
 * is printed with it, always, for the reason ADR-089 prints a span with every slope.
 *
 * **A share keeps its absolute scale.** A bar for 25% of targets is a quarter-height bar
 * whoever else is on the team, the same rule ADR-086 set for the cohort strip; a count (pass
 * or rush attempts, fantasy points) is scaled to the player's own peak and the caption says so.
 *
 * **An absence is not a zero.** A bye, a week he did not play, and a played week the metric
 * has no value for (no snap-count row bridged to him) are three different facts, drawn as
 * three different marks with a letter each — never as a floor-height bar, which would read as
 * "he was on the field and got nothing". Never colour alone: the direction is a glyph and a
 * signed number, and every rail has a sentence for a screen reader.
 */

import { useId } from "react";

import type { UsageWeekStatus } from "../data/contracts";
import { formatValue } from "../data/format";
import {
  DIRECTION_GLYPH,
  type BreadthReading,
  type ChangeDirection,
  changeWindow,
  formatChange,
  formatMetric,
  roleSentence,
  type RoleBar,
  type RoleReading,
} from "../data/signals";

const ABSENCE_MARK: Readonly<Record<Exclude<UsageWeekStatus, "played">, string>> = {
  bye: "B",
  did_not_play: "×",
};

export function Bars({
  bars,
  axisMax,
  notches,
}: {
  readonly bars: readonly RoleBar[];
  readonly axisMax: number;
  /** ADR-104: week → a reference value drawn as a notch across that week's bar. */
  readonly notches?: ReadonlyMap<number, number | null> | undefined;
}): React.JSX.Element {
  return (
    <div className="usage-bars" aria-hidden="true">
      {bars.map((bar) => {
        if (bar.status !== "played") {
          return (
            <span key={bar.week} className="usage-bar" data-status={bar.status}>
              {ABSENCE_MARK[bar.status]}
            </span>
          );
        }
        if (bar.value === null) {
          return (
            <span key={bar.week} className="usage-bar" data-status="no_value">
              ·
            </span>
          );
        }
        const height = Math.max(4, Math.min(100, Math.round((bar.value / axisMax) * 100)));
        const notch = notches?.get(bar.week) ?? null;
        return (
          <span
            key={bar.week}
            className="usage-bar"
            data-status="played"
            data-latest={bar.latest ? "true" : undefined}
          >
            <span className="usage-bar-fill" style={{ height: `${String(height)}%` }} />
            {notch !== null && (
              <span
                className="usage-bar-notch"
                style={{
                  bottom: `${String(Math.max(0, Math.min(100, Math.round((notch / axisMax) * 100))))}%`,
                }}
              />
            )}
          </span>
        );
      })}
    </div>
  );
}

/**
 * One rail: the label and its question, the bars, and the reading — the same grid and the
 * same classes for every row, so a row added to the block reads as one more of the same kind.
 */
function Rail({
  metric,
  label,
  question,
  direction,
  bars,
  axisMax,
  notches,
  value,
  change,
  window,
  note,
  sentence,
}: {
  readonly metric: string;
  readonly label: string;
  readonly question: string;
  readonly direction: ChangeDirection | null;
  readonly bars: readonly RoleBar[];
  readonly axisMax: number;
  readonly notches?: ReadonlyMap<number, number | null> | undefined;
  readonly value: string;
  readonly change: string | null;
  readonly window: string;
  readonly note?: string | undefined;
  readonly sentence: string;
}): React.JSX.Element {
  const sentenceId = useId();
  return (
    <div
      className="usage-rail"
      data-metric={metric}
      data-direction={direction ?? "none"}
      aria-describedby={sentenceId}
    >
      <span className="usage-rail-label">
        {label}
        <span className="usage-rail-question">{question}</span>
      </span>
      <Bars bars={bars} axisMax={axisMax} notches={notches} />
      <p className="usage-rail-reading">
        <span className="usage-rail-value">{value}</span>
        {change !== null && direction !== null ? (
          <span className="usage-rail-change" data-direction={direction}>
            <span aria-hidden="true">{DIRECTION_GLYPH[direction]}</span> {change}
          </span>
        ) : null}
        <span className="usage-rail-window">{window}</span>
        {note !== undefined && <span className="usage-rail-note">{note}</span>}
      </p>
      <span className="visually-hidden" id={sentenceId}>
        {sentence}
      </span>
    </div>
  );
}

function RoleRail({ reading }: { readonly reading: RoleReading }): React.JSX.Element {
  const { spec, change, direction } = reading;
  return (
    <Rail
      metric={spec.metric}
      label={spec.label}
      question={spec.question}
      direction={direction}
      bars={reading.bars}
      axisMax={reading.axisMax}
      value={change === null ? "—" : formatMetric(spec, change.latest)}
      change={change?.change !== null && change?.change !== undefined ? formatChange(spec, change.change) : null}
      window={
        change === null
          ? "no value in his latest game"
          : change.earlier === null
            ? changeWindow(change)
            : `from ${formatMetric(spec, change.earlier)} · ${changeWindow(change)}`
      }
      sentence={roleSentence(reading)}
    />
  );
}

/**
 * ADR-104's drive rail: a rail like the others — one bar per game, his drive share on the
 * shares' absolute axis, the latest against the earlier games — plus a notch on each bar where
 * the same count placed at random would reach, and one line with the four-game comparison.
 */
function BreadthRail({ reading }: { readonly reading: BreadthReading }): React.JSX.Element {
  return (
    <Rail
      metric="drive_breadth"
      label={reading.label}
      question={reading.question}
      direction={reading.direction}
      bars={reading.bars}
      axisMax={1}
      notches={reading.expected}
      value={reading.valueText}
      change={reading.changeText}
      window={reading.window}
      note={reading.vsRandom ?? undefined}
      sentence={reading.sentence}
    />
  );
}

export function UsageRails({
  readings,
  production,
  productionLabel,
  weeks,
  breadth = null,
}: {
  readonly readings: readonly RoleReading[];
  /** ADR-104: the drive rail, drawn after the role rails; null draws nothing. */
  readonly breadth?: BreadthReading | null;
  /** Fantasy points per week in the reader's preset, on the same week axis. */
  readonly production: { readonly bars: readonly RoleBar[]; readonly axisMax: number } | null;
  readonly productionLabel: string;
  readonly weeks: readonly number[];
}): React.JSX.Element {
  const latestPoints = production?.bars.find((bar) => bar.latest) ?? null;
  return (
    <div className="usage-rails" role="group" aria-label="Role and production, week by week">
      {readings.map((reading) => (
        <RoleRail key={reading.spec.metric} reading={reading} />
      ))}
      {breadth !== null && <BreadthRail reading={breadth} />}
      {production !== null && (
        <div className="usage-rail" data-metric="fantasy_points" data-direction="none">
          <span className="usage-rail-label">
            {productionLabel}
            <span className="usage-rail-question">Has the scoring followed?</span>
          </span>
          <Bars bars={production.bars} axisMax={production.axisMax} />
          <p className="usage-rail-reading">
            <span className="usage-rail-value">
              {formatValue(latestPoints?.value)}
            </span>
            <span className="usage-rail-window">
              {latestPoints === null ? "no appearances" : `week ${String(latestPoints.week)}`}
            </span>
          </p>
        </div>
      )}
      <div className="usage-axis" aria-hidden="true">
        <span />
        <div className="usage-axis-weeks">
          {weeks.map((week) => (
            <span key={week}>{week}</span>
          ))}
        </div>
        <span />
      </div>
    </div>
  );
}
