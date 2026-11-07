/**
 * One Skill Tree metric's whole positional cohort beside the card's player (ADR-117).
 *
 * A lazy chunk of its own, loaded from inside the tree's: a ranked node's detail offers it and
 * only pressing that button loads this code and the metric's one cohort slice (the store
 * fetches the position's small index first). Nothing here is computed about football: every
 * value, sample, rank and percentile is the served row's own, checked against the tree's
 * reading before anything is drawn (`checkCohort`).
 *
 * * **The distribution** is a dot plot on the metric's raw-value axis — one dot per ranked
 *   player, equal values stacked in one column, deterministically. The card's player is a
 *   diamond with his name above it; pinned players are numbered rings (or numbered squares in
 *   a separate *Unranked* lane: they are outside the ranking cohort). Shape and words carry
 *   every meaning; colour only repeats it.
 * * **Pins**: a name search over the same cohort pins up to three players, each with value,
 *   sample, rank, percentile and a labelled difference from the card's player. Pinning never
 *   changes the cohort; it may widen the axis to show an unranked pin.
 * * **The table** is the numeric alternative: every row of the cohort, the card's player and
 *   the pins marked in words.
 *
 * React owns every element; there is no chart library. Touch and keyboard reach everything a
 * pointer does: tapping a dot reads it out and offers its pin, and the table lists them all.
 */

import { memo, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import "../styles/skillcompare.css";

import { useElementWidth } from "../components/useElementWidth";
import type { Position, SkillTreeDefinitionRecord } from "../data/contracts";
import {
  MAX_PINS,
  checkCohort,
  compareUnit,
  difference,
  formatExact,
  memberSample,
  memberStanding,
  niceTicks,
  searchMembers,
  stackLevels,
  valueDomain,
  valueWithUnit,
  type Cohort,
  type CohortMember,
} from "../data/skillCompare";
import type { SkillReading } from "../data/skilltree";
import type { SkillTreeSource } from "../data/store";

const NOUNS: Readonly<Partial<Record<Position, string>>> = { QB: "QBs", RB: "RBs", WR: "WRs", TE: "TEs" };

type CompareState =
  | { readonly status: "loading" }
  | { readonly status: "absent" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "refused"; readonly message: string }
  | { readonly status: "ready"; readonly cohort: Cohort };

/**
 * Checked cohorts by source and `player|position|metric|build`: reopening a comparison draws
 * in its first frame and asks the store for nothing. Weakly keyed by the source, so a new
 * deploy's store starts empty. Errors are not kept, so a retry can succeed.
 */
const CHECKED = new WeakMap<SkillTreeSource, Map<string, CompareState>>();

function cached(source: SkillTreeSource, key: string): CompareState | undefined {
  return CHECKED.get(source)?.get(key);
}

function remember(source: SkillTreeSource, key: string, state: CompareState): void {
  const map = CHECKED.get(source) ?? new Map<string, CompareState>();
  map.set(key, state);
  CHECKED.set(source, map);
}

export default function SkillCompare({
  source,
  focal,
  position,
  name,
}: {
  readonly source: SkillTreeSource;
  readonly focal: SkillReading;
  readonly position: Position;
  readonly name: string;
}): React.JSX.Element {
  const metricId = focal.id;
  const key = `${focal.provenance?.playerId ?? ""}|${position}|${metricId}|${focal.provenance?.buildId ?? ""}`;
  const [state, setState] = useState<{ readonly key: string; readonly value: CompareState }>(() => ({
    key,
    value: cached(source, key) ?? { status: "loading" },
  }));
  const noun = NOUNS[position] ?? "players";
  const label = focal.definition.label;

  useEffect(() => {
    if (cached(source, key) !== undefined) return;
    // A load that resolves after the reader moved to another player or metric is dropped: this
    // component is keyed by both and unmounts, and the key is checked again on arrival.
    let live = true;
    source.loadCohort(position, metricId).then(
      (load) => {
        const checked = load === null ? null : checkCohort(load, focal, source.nameOf);
        const value: CompareState =
          checked === null
            ? { status: "absent" }
            : checked.status === "ready"
              ? { status: "ready", cohort: checked.cohort }
              : { status: "refused", message: checked.message };
        remember(source, key, value);
        if (live) setState({ key, value });
      },
      (error: unknown) => {
        if (live) setState({ key, value: { status: "error", message: error instanceof Error ? error.message : String(error) } });
      },
    );
    return () => {
      live = false;
    };
  }, [source, position, metricId, key, focal]);

  const current: CompareState = state.key === key ? state.value : (cached(source, key) ?? { status: "loading" });
  switch (current.status) {
    case "loading":
      return (
        <p className="stc-status" role="status">
          Loading every {position} with a {label.toLowerCase()} reading…
        </p>
      );
    case "absent":
      return (
        <p className="stc-status" data-kind="unavailable">
          Comparison is not available for this build: it serves no cohort for {label.toLowerCase()}.
        </p>
      );
    case "error":
      return (
        <p className="stc-status" data-kind="error" role="alert">
          The comparison could not be loaded ({current.message}). The tree is unaffected.
        </p>
      );
    case "refused":
      return (
        <p className="stc-status" data-kind="refused" role="alert">
          <strong>No comparison drawn.</strong> {current.message}
        </p>
      );
    case "ready":
      return <ComparePanel cohort={current.cohort} focal={focal} name={name} noun={noun} />;
  }
}

// --------------------------------------------------------------------------------- panel

function initialWidth(): number {
  return typeof window === "undefined" ? 640 : Math.max(240, Math.min(680, window.innerWidth - 72));
}

function ComparePanel({
  cohort,
  focal,
  name,
  noun,
}: {
  readonly cohort: Cohort;
  readonly focal: SkillReading;
  readonly name: string;
  readonly noun: string;
}): React.JSX.Element {
  const definition = focal.definition;
  const rootRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const width = useElementWidth(rootRef, initialWidth());
  const baseId = useId();
  const [pins, setPins] = useState<readonly string[]>([]);
  const [query, setQuery] = useState("");
  const [tableOpen, setTableOpen] = useState(false);
  const [probe, setProbe] = useState<string | null>(null);
  const unit = compareUnit(definition);
  const full = pins.length >= MAX_PINS;

  const pin = useCallback((playerId: string): void => {
    setPins((current) =>
      current.length >= MAX_PINS || current.includes(playerId) ? current : [...current, playerId],
    );
  }, []);
  const pinFromSearch = (playerId: string): void => {
    pin(playerId);
    setQuery("");
    searchRef.current?.focus();
  };
  const unpin = (playerId: string): void => {
    setPins((current) => current.filter((id) => id !== playerId));
    searchRef.current?.focus();
  };
  const clear = (): void => {
    setPins([]);
    searchRef.current?.focus();
  };

  const pinned = useMemo(
    () =>
      pins
        .map((id) => cohort.byId.get(id))
        .filter((member): member is CohortMember => member !== undefined),
    [pins, cohort],
  );
  const matches = useMemo(() => searchMembers(cohort, query, new Set(pins)), [cohort, query, pins]);
  const probed = probe === null ? null : (cohort.byId.get(probe) ?? null);
  const focalMember = cohort.focal;
  const better =
    definition.direction === "neutral"
      ? "no better direction"
      : definition.direction === "lower"
        ? "lower is better"
        : "higher is better";
  const minimum =
    definition.minimum === null
      ? ""
      : ` · minimum ${String(definition.minimum)} ${definition.minimum_unit ?? ""}`.trimEnd();

  return (
    <section
      className="stc"
      ref={rootRef}
      aria-label={`${definition.label} compared across ${String(cohort.ranked.length)} ranked ${noun}`}
    >
      <p className="stc-scope">
        <strong>{cohort.ranked.length}</strong> ranked {noun} · {definition.window}
        {minimum}
      </p>
      <p className="stc-rule">{definition.cohort_rule}</p>
      <p className="stc-focal">
        <span className="stc-focal-mark" aria-hidden="true">
          ◆
        </span>{" "}
        <strong>{name}</strong>: {valueWithUnit(focalMember.value, definition)}
        {memberSample(focalMember, definition) !== "" && <> · {memberSample(focalMember, definition)}</>} ·{" "}
        {memberStanding(focalMember, definition)}
      </p>
      <Plot
        cohort={cohort}
        definition={definition}
        pinned={pinned}
        probe={probe}
        onProbe={setProbe}
        width={width}
        name={name}
        noun={noun}
      />
      <p className="stc-axis-note">
        Axis: {definition.label.toLowerCase()}
        {definition.unit === "count" ? "" : ` (${definition.unit === "fraction" ? "%" : unit})`} ·{" "}
        <span data-direction={definition.direction}>
          {definition.direction === "lower" ? "← " : ""}
          {better}
          {definition.direction === "higher" ? " →" : ""}
        </span>
      </p>
      {probed !== null && (
        <p className="stc-probe">
          <span>
            <strong>{probed.focal ? `◆ ${name}` : probed.name}</strong> · {valueWithUnit(probed.value, definition)} ·{" "}
            {memberStanding(probed, definition)}
          </span>
          {!probed.focal && !pins.includes(probed.playerId) && (
            <button
              type="button"
              className="stc-button"
              disabled={full}
              aria-label={`Pin ${probed.name}`}
              onClick={() => {
                pin(probed.playerId);
              }}
            >
              Pin
            </button>
          )}
        </p>
      )}
      {cohort.unranked.length > 0 && (
        <p className="stc-unranked-note">
          {cohort.unranked.length} more {noun} have a value but are unranked (below the minimum, or too few
          qualified to rank). They are not part of the distribution; a pinned one is drawn apart from it.
        </p>
      )}

      <div className="stc-pick">
        <label className="stc-label" htmlFor={`${baseId}-search`}>
          Pin up to {MAX_PINS} {noun} to compare
        </label>
        <input
          id={`${baseId}-search`}
          ref={searchRef}
          className="stc-search"
          type="search"
          value={query}
          placeholder="Search by name"
          autoComplete="off"
          aria-describedby={`${baseId}-pin-note`}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
        <p className="stc-pin-note" id={`${baseId}-pin-note`} aria-live="polite">
          {full
            ? `${String(MAX_PINS)} players pinned: remove one to pin another.`
            : `${String(pins.length)} of ${String(MAX_PINS)} pinned. Pinning never changes the ranking.`}
        </p>
        {query.trim() !== "" && (
          <ul className="stc-matches" aria-label={`${noun} matching “${query.trim()}”`}>
            {matches.length === 0 && <li className="stc-match-none">No {singularNoun(noun)} in this cohort by that name.</li>}
            {matches.map((member) => (
              <li key={member.playerId} className="stc-match">
                <button
                  type="button"
                  className="stc-button"
                  disabled={full}
                  aria-label={`Pin ${member.name}`}
                  onClick={() => {
                    pinFromSearch(member.playerId);
                  }}
                >
                  Pin
                </button>
                <span className="stc-match-name">{member.name}</span>
                <span className="stc-match-reading">
                  {valueWithUnit(member.value, definition)} · {member.state === "ranked" ? memberStanding(member, definition) : "Unranked"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {pinned.length > 0 && (
        <>
          <ol className="stc-pins" aria-label="Pinned players">
            {pinned.map((member, index) => {
              const diff = difference(member, focalMember, definition, name);
              return (
                <li key={member.playerId} className="stc-pin" data-state={member.state}>
                  <span className="stc-pin-num" aria-hidden="true">
                    {index + 1}
                  </span>
                  <span className="stc-pin-name">
                    <span className="visually-hidden">{`Pin ${String(index + 1)}: `}</span>
                    {member.name}
                    {member.state !== "ranked" && <span className="stc-tag">Unranked</span>}
                  </span>
                  <span className="stc-pin-value">{valueWithUnit(member.value, definition)}</span>
                  <span className="stc-pin-standing">
                    {[memberSample(member, definition), memberStanding(member, definition)]
                      .filter((text) => text !== "")
                      .join(" · ")}
                  </span>
                  <span className="stc-pin-diff" data-side={diff.side}>
                    {diff.text} <span className="stc-pin-side">({diff.words})</span>
                  </span>
                  <button
                    type="button"
                    className="stc-button stc-remove"
                    aria-label={`Remove ${member.name}`}
                    onClick={() => {
                      unpin(member.playerId);
                    }}
                  >
                    Remove
                  </button>
                </li>
              );
            })}
          </ol>
          <button type="button" className="stc-button stc-clear" onClick={clear}>
            Clear pins
          </button>
        </>
      )}

      <button
        type="button"
        className="stc-button stc-table-toggle"
        aria-expanded={tableOpen}
        aria-controls={tableOpen ? `${baseId}-table` : undefined}
        onClick={() => {
          setTableOpen((open) => !open);
        }}
      >
        {tableOpen ? "Hide the table" : `Show all ${String(cohort.ranked.length + cohort.unranked.length)} as a table`}
      </button>
      {tableOpen && (
        <CohortTable
          id={`${baseId}-table`}
          cohort={cohort}
          definition={definition}
          pins={pins}
          name={name}
          noun={noun}
        />
      )}
    </section>
  );
}

/** "WRs" → "WR": the singular for "No WR by that name". */
function singularNoun(noun: string): string {
  return noun.endsWith("s") ? noun.slice(0, -1) : noun;
}

// ---------------------------------------------------------------------------------- plot

const DOT = 3.5;
const STEP = 2 * DOT + 1;
const MAX_STACK = 104;
const PAD_X = 16;
const TOP = 22;

interface Mark {
  readonly member: CohortMember;
  readonly x: number;
  readonly y: number;
}

const Plot = memo(function Plot({
  cohort,
  definition,
  pinned,
  probe,
  onProbe,
  width,
  name,
  noun,
}: {
  readonly cohort: Cohort;
  readonly definition: SkillTreeDefinitionRecord;
  readonly pinned: readonly CohortMember[];
  readonly probe: string | null;
  readonly onProbe: (playerId: string | null) => void;
  readonly width: number;
  readonly name: string;
  readonly noun: string;
}): React.JSX.Element {
  const layout = useMemo(() => {
    const w = Math.max(220, Math.round(width));
    const unrankedPins = pinned.filter((member) => member.state !== "ranked");
    const [min, max] = valueDomain(
      [...cohort.ranked.map((member) => member.value), ...unrankedPins.map((member) => member.value)],
      definition,
    );
    const span = max - min;
    const x = (value: number): number => PAD_X + ((value - min) / span) * (w - 2 * PAD_X);
    const levels = stackLevels(cohort.ranked, x, STEP);
    const tallest = Math.max(1, ...levels.values()) + 1;
    const step = Math.min(STEP, MAX_STACK / tallest);
    const baseline = TOP + DOT + 4 + (tallest - 1) * step + DOT + 2;
    const marks: Mark[] = cohort.ranked.map((member) => ({
      member,
      x: x(member.value),
      y: baseline - DOT - 2 - (levels.get(member.playerId) ?? 0) * step,
    }));
    const axisY = baseline + 4;
    const ticks = niceTicks(min, max, w < 360 ? 3 : 5);
    const laneY = axisY + 34;
    const lane: Mark[] = unrankedPins.map((member) => ({ member, x: x(member.value), y: laneY }));
    const height = (lane.length > 0 ? laneY + 14 : axisY + 22) + 2;
    return { w, x, marks, axisY, ticks, lane, laneY, height, min, max, zero: min < 0 && max > 0 ? x(0) : null };
  }, [cohort, definition, pinned, width]);

  const focalMark = layout.marks.find((mark) => mark.member.focal) ?? null;
  const pinIndex = new Map(pinned.map((member, index) => [member.playerId, index + 1]));
  const all = [...layout.marks, ...layout.lane];
  const tickStep = (layout.ticks[1] ?? 0) - (layout.ticks[0] ?? 0);
  const tickText = (value: number): string => {
    if (definition.unit === "count") return Math.round(value).toLocaleString("en-US");
    if (definition.unit === "fraction") return `${(value * 100).toFixed(stepDecimals(tickStep * 100))}%`;
    const decimals = Math.min(definition.decimals, stepDecimals(tickStep));
    const signed = definition.unit === "epa" || definition.unit === "pp" || definition.metric_id.includes("over_expected");
    return `${signed && value > 0 ? "+" : ""}${value.toFixed(decimals)}`;
  };

  const nearest = (event: React.PointerEvent<SVGSVGElement>): string | null => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - box.left;
    const py = event.clientY - box.top;
    let best: string | null = null;
    let distance = 18;
    for (const mark of all) {
      const d = Math.hypot(mark.x - px, (mark.y - py) * 0.6);
      if (d < distance) {
        distance = d;
        best = mark.member.playerId;
      }
    }
    return best;
  };

  const focalLabelAnchor =
    focalMark === null ? "middle" : focalMark.x < layout.w * 0.3 ? "start" : focalMark.x > layout.w * 0.7 ? "end" : "middle";
  const describe =
    `Dot plot of ${String(cohort.ranked.length)} ranked ${noun} by ${definition.label.toLowerCase()}, ` +
    `${formatExact(layout.min, definition)} to ${formatExact(layout.max, definition)}. ` +
    `${name}, the diamond, at ${formatExact(cohort.focal.value, definition)}.` +
    (pinned.length > 0
      ? ` Pinned: ${pinned.map((member, index) => `${String(index + 1)} ${member.name} ${formatExact(member.value, definition)}${member.state === "ranked" ? "" : " (unranked)"}`).join("; ")}.`
      : "") +
    " The table lists every value.";

  return (
    <svg
      className="stc-plot"
      width={layout.w}
      height={layout.height}
      viewBox={`0 0 ${String(layout.w)} ${String(layout.height)}`}
      role="img"
      aria-label={describe}
      onPointerDown={(event) => {
        onProbe(nearest(event));
      }}
      onPointerMove={(event) => {
        if (event.pointerType === "mouse") onProbe(nearest(event));
      }}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") onProbe(null);
      }}
    >
      {layout.zero !== null && (
        <line className="stc-zero" x1={layout.zero} x2={layout.zero} y1={TOP} y2={layout.axisY} />
      )}
      {focalMark !== null && (
        <line className="stc-focal-guide" x1={focalMark.x} x2={focalMark.x} y1={TOP - 4} y2={layout.axisY} />
      )}
      <g className="stc-dots">
        {layout.marks.map((mark) =>
          mark.member.focal ? null : (
            <circle key={mark.member.playerId} className="stc-dot" cx={mark.x} cy={mark.y} r={DOT} />
          ),
        )}
      </g>
      {/* The axis: the metric's raw values, its unit in the note under the plot. */}
      <line className="stc-axis" x1={PAD_X} x2={layout.w - PAD_X} y1={layout.axisY} y2={layout.axisY} />
      {layout.ticks.map((value) => (
        <g key={value} transform={`translate(${String(layout.x(value))} ${String(layout.axisY)})`}>
          <line className="stc-axis" y1={0} y2={4} />
          <text className="stc-tick" y={16} textAnchor="middle">
            {tickText(value)}
          </text>
        </g>
      ))}
      {layout.lane.length > 0 && (
        <g>
          <line className="stc-lane" x1={PAD_X} x2={layout.w - PAD_X} y1={layout.laneY} y2={layout.laneY} />
          <text className="stc-lane-label" x={PAD_X} y={layout.laneY - 7}>
            Unranked (pinned, outside the ranking)
          </text>
        </g>
      )}
      {[...layout.marks, ...layout.lane]
        .filter((mark) => pinIndex.has(mark.member.playerId))
        .map((mark) => {
          const ranked = mark.member.state === "ranked";
          return (
            <g key={`pin-${mark.member.playerId}`} className="stc-pin-mark" data-state={mark.member.state}>
              {ranked ? (
                <circle cx={mark.x} cy={mark.y} r={DOT + 3} />
              ) : (
                <rect x={mark.x - 4.5} y={mark.y - 4.5} width={9} height={9} />
              )}
              <text className="stc-pin-label" x={mark.x} y={mark.y - (ranked ? 9 : 8)} textAnchor="middle">
                {pinIndex.get(mark.member.playerId)}
              </text>
            </g>
          );
        })}
      {focalMark !== null && (
        <g className="stc-focal">
          <path
            className="stc-focal-diamond"
            d={`M ${String(focalMark.x)} ${String(focalMark.y - 6.5)} l 6.5 6.5 l -6.5 6.5 l -6.5 -6.5 z`}
          />
          <text className="stc-focal-label" x={focalMark.x} y={TOP - 8} textAnchor={focalLabelAnchor}>
            {`◆ ${name} ${formatExact(cohort.focal.value, definition)}`}
          </text>
        </g>
      )}
      {probe !== null &&
        all
          .filter((mark) => mark.member.playerId === probe)
          .map((mark) => <circle key="probe" className="stc-probe-ring" cx={mark.x} cy={mark.y} r={DOT + 5.5} />)}
    </svg>
  );
});

/** Decimals that tell ticks this far apart from each other: 0.5 → 1, 0.02 → 2, 5 → 0. */
function stepDecimals(step: number): number {
  if (!(step > 0) || !Number.isFinite(step)) return 2;
  return Math.max(0, Math.min(3, Math.ceil(-Math.log10(step) - 1e-9)));
}

// --------------------------------------------------------------------------------- table

function CohortTable({
  id,
  cohort,
  definition,
  pins,
  name,
  noun,
}: {
  readonly id: string;
  readonly cohort: Cohort;
  readonly definition: SkillTreeDefinitionRecord;
  readonly pins: readonly string[];
  readonly name: string;
  readonly noun: string;
}): React.JSX.Element {
  const unit = definition.unit === "fraction" ? "%" : compareUnit(definition);
  // Four columns, so a 320px phone shows every one: the sample rides under the name.
  const row = (member: CohortMember): React.JSX.Element => {
    const pinNumber = pins.indexOf(member.playerId) + 1;
    const sample = memberSample(member, definition);
    return (
      <tr
        key={member.playerId}
        className="stc-row"
        data-focal={member.focal ? "true" : undefined}
        data-pinned={pinNumber > 0 ? "true" : undefined}
        aria-current={member.focal ? "true" : undefined}
      >
        <td className="stc-num">{member.rank ?? "Unranked"}</td>
        <th scope="row">
          {member.focal && <span aria-hidden="true">◆ </span>}
          {member.name}
          {member.focal && <span className="stc-row-tag"> (this card: {name})</span>}
          {pinNumber > 0 && <span className="stc-row-tag"> (pin {pinNumber})</span>}
          {sample !== "" && <span className="stc-row-sample">{sample}</span>}
        </th>
        <td className="stc-num">{formatExact(member.value, definition)}</td>
        <td className="stc-num">{member.percentile === null ? "—" : member.percentile.toFixed(1)}</td>
      </tr>
    );
  };
  return (
    <div className="stc-table-wrap" id={id} role="region" tabIndex={0} aria-label={`Every ${noun.slice(0, -1)} in the cohort, as a table`}>
      <table className="stc-table">
        <caption className="visually-hidden">
          {definition.label}: {cohort.ranked.length} ranked {noun} by rank, then {cohort.unranked.length} unranked.
        </caption>
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Player · sample</th>
            <th scope="col">{definition.unit === "count" ? "Value" : `Value (${unit})`}</th>
            <th scope="col">Pct</th>
          </tr>
        </thead>
        <tbody>{cohort.ranked.map(row)}</tbody>
        {cohort.unranked.length > 0 && <tbody className="stc-table-unranked">{cohort.unranked.map(row)}</tbody>}
      </table>
    </div>
  );
}
