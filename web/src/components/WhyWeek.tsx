/**
 * "Why this week" (ADR-099): this week against a typical week, at the floor, the median and
 * the ceiling, in words a manager reads in a glance.
 *
 * Two kinds of line, never mixed: model reasons carry points (each is the published Shapley
 * term for an input the served model reads), context carries facts and no points. Direction
 * is always spelled — a sign, an arrow and "above"/"below" — and colour only repeats it.
 */

import type { WeeklyExplainedLevel } from "../data/contracts";
import {
  arrow,
  deltaSentence,
  signedPoints,
  type ContextChip,
  type LevelReading,
  type ModelChip,
  type WhyThisWeek,
} from "../data/whyweek";

const LEVEL_NAMES: Readonly<Record<WeeklyExplainedLevel, string>> = {
  q10: "Floor",
  q50: "Median",
  q90: "Ceiling",
};

/** Short names for a one-cell summary. */
export const SHORT_REASON: Readonly<Record<string, string>> = {
  lines: "Vegas",
  home: "Venue",
  rest: "Rest",
  roof: "Roof",
  opponent: "Opp.",
};

function direction(value: number): "up" | "down" | "flat" {
  const rounded = Math.round(value * 10) / 10;
  return rounded === 0 ? "flat" : rounded > 0 ? "up" : "down";
}

function Headline({ reading }: { readonly reading: LevelReading }): React.JSX.Element {
  const name = LEVEL_NAMES[reading.level];
  return (
    <div className="why-week-head" data-direction={direction(reading.delta)}>
      <span className="why-week-level">{name}</span>
      <span className="why-week-number">{reading.thisWeek.toFixed(1)}</span>
      <span className="why-week-delta">
        <span aria-hidden="true">{arrow(reading.delta)} </span>
        {deltaSentence(reading)}
      </span>
    </div>
  );
}

/** The factor rows: every model reason material at any of the three levels. */
function reasonRows(why: WhyThisWeek): readonly {
  readonly group: ModelChip["group"];
  readonly label: string;
  readonly values: Readonly<Record<WeeklyExplainedLevel, number>>;
}[] {
  const groups = new Map<ModelChip["group"], string>();
  for (const reading of [why.median, why.ceiling, why.floor]) {
    for (const chip of reading.chips) if (!groups.has(chip.group)) groups.set(chip.group, chip.label);
  }
  const value = (reading: LevelReading, group: ModelChip["group"]): number =>
    reading.chips.find((chip) => chip.group === group)?.value ?? 0;
  return [...groups.entries()]
    .map(([group, label]) => ({
      group,
      label,
      values: { q10: value(why.floor, group), q50: value(why.median, group), q90: value(why.ceiling, group) },
    }))
    .sort(
      (a, b) =>
        Math.abs(b.values.q50) + Math.abs(b.values.q90) - (Math.abs(a.values.q50) + Math.abs(a.values.q90)) ||
        a.group.localeCompare(b.group),
    );
}

function Signed({ value }: { readonly value: number }): React.JSX.Element {
  return (
    <span className="why-week-value" data-direction={direction(value)}>
      <span aria-hidden="true">{arrow(value)} </span>
      {signedPoints(value)}
    </span>
  );
}

export function ContextChips({ chips }: { readonly chips: readonly ContextChip[] }): React.JSX.Element | null {
  if (chips.length === 0) return null;
  const licences = [...new Set(chips.flatMap((chip) => (chip.attribution === undefined ? [] : [chip.attribution])))];
  return (
    <>
      <ul className="why-week-context" aria-label="Game-day context (no points: the model does not read it)">
        {chips.map((chip) => (
          <li key={chip.id} data-tone={chip.tone} title={chip.detail}>
            <span className="why-week-context-text">{chip.label}</span>
            <span className="visually-hidden">{` — ${chip.detail}`}</span>
          </li>
        ))}
      </ul>
      {licences.map((licence) => (
        <p key={licence} className="why-week-attribution">
          {licence}
        </p>
      ))}
    </>
  );
}

/** The full reading: headlines, the reasons table, the context, and what it is not. */
export function WhyWeek({
  why,
  name,
  statement,
}: {
  readonly why: WhyThisWeek;
  readonly name: string;
  readonly statement?: string | null | undefined;
}): React.JSX.Element {
  const rows = reasonRows(why);
  return (
    <div className="why-week">
      <div className="why-week-heads">
        <Headline reading={why.median} />
        <Headline reading={why.ceiling} />
        <Headline reading={why.floor} />
      </div>
      {rows.length === 0 ? (
        <p className="why-week-empty">
          {`The game moves ${name}'s numbers by less than a tenth of a point at every level: this week reads like a typical week.`}
        </p>
      ) : (
        <table className="why-week-table">
          <caption className="visually-hidden">{`Why ${name}'s week differs from a typical week, in points`}</caption>
          <thead>
            <tr>
              <th scope="col">This week</th>
              <th scope="col">Median</th>
              <th scope="col">Ceiling</th>
              <th scope="col" className="why-week-floor-col">Floor</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.group} data-group={row.group}>
                <th scope="row">{row.label}</th>
                <td><Signed value={row.values.q50} /></td>
                <td><Signed value={row.values.q90} /></td>
                <td className="why-week-floor-col"><Signed value={row.values.q10} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ContextChips chips={why.context} />
      <p className="why-week-note">
        {statement ??
          "Each number is how far the model's projection moved with that input against a typical week, the others held — a model attribution, not a measured cause."}
      </p>
    </div>
  );
}

/** Two lines for a deck card: the median and ceiling against typical, and the top reason. */
export function WhyWeekCompact({ why }: { readonly why: WhyThisWeek }): React.JSX.Element {
  const top = why.median.chips[0] ?? why.ceiling.chips[0] ?? null;
  const ceilingValue = top === null ? 0 : (why.ceiling.chips.find((chip) => chip.group === top.group)?.value ?? 0);
  const medianValue = top === null ? 0 : (why.median.chips.find((chip) => chip.group === top.group)?.value ?? 0);
  return (
    <div className="why-week-compact">
      <p className="why-week-compact-head">
        <span className="why-week-compact-label">vs typical</span>
        <span data-direction={direction(why.median.delta)}>
          {`Median ${arrow(why.median.delta)} ${signedPoints(why.median.delta)}`}
        </span>
        <span data-direction={direction(why.ceiling.delta)}>
          {`Ceiling ${arrow(why.ceiling.delta)} ${signedPoints(why.ceiling.delta)}`}
        </span>
      </p>
      {top !== null && (
        <p className="why-week-compact-reason">
          {`${top.label} (${signedPoints(medianValue)} median, ${signedPoints(ceilingValue)} ceiling)`}
        </p>
      )}
      {why.context.length > 0 && (
        <p className="why-week-compact-context" title={why.context.map((chip) => chip.detail).join("\n")}>
          {why.context[0]?.label}
          {why.context.length > 1 && ` · +${String(why.context.length - 1)} more`}
        </p>
      )}
      {why.context[0]?.attribution !== undefined && (
        <p className="why-week-attribution">{why.context[0].attribution}</p>
      )}
    </div>
  );
}
