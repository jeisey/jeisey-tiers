/**
 * A Skill Tree metric's whole positional cohort, checked and laid out for comparison (ADR-117).
 *
 * Loaded only with the comparison's own lazy chunk, which a reader reaches by opening one
 * ranked node's detail and asking for it. Like the tree's view model it **computes nothing
 * about football**: every value, sample, rank and percentile is the served row's own. What it
 * adds is refusal and geometry:
 *
 * * **refusal** — a cohort is drawn only when every row is of the focal reading's build,
 *   season, cutoff, position and metric, the ranked rows are exactly the published cohort
 *   (`cohort_size` of each), and the focal player's own row agrees with his tree reading. Any
 *   disagreement draws nothing and says why: a comparison across builds or windows is wrong;
 * * **geometry** — a raw-value axis that survives negative values and an all-equal cohort, and
 *   a deterministic stacking that puts equal values in one column (never jitter by chance).
 */

import type { SkillTreeDefinitionRecord } from "./contracts";
import { ordinal } from "./cohort";
import { percentileWords, sampleText, standingText, type SkillReading } from "./skilltree";
import type { SkillCohortLoad } from "./store";

/** At most this many players pinned beside the focal one. */
export const MAX_PINS = 3;

/** The states a served cohort row may carry: each has a value to place on the axis. */
export type MemberState = "ranked" | "below_minimum" | "small_cohort";

const MEMBER_STATES: ReadonlySet<string> = new Set(["ranked", "below_minimum", "small_cohort"]);

/** One player of the cohort, as served. */
export interface CohortMember {
  readonly playerId: string;
  readonly name: string;
  readonly state: MemberState;
  readonly value: number;
  readonly numerator: number | null;
  readonly denominator: number | null;
  readonly rank: number | null;
  readonly percentile: number | null;
  readonly cohortSize: number | null;
  readonly games: number;
  readonly focal: boolean;
}

/** A verified cohort: the ranking cohort, the players outside it, and the focal player. */
export interface Cohort {
  /** The ranking cohort, by rank (ties by name). */
  readonly ranked: readonly CohortMember[];
  /** Players with a value outside the ranked cohort, better values first. */
  readonly unranked: readonly CohortMember[];
  readonly focal: CohortMember;
  readonly byId: ReadonlyMap<string, CohortMember>;
}

export type CohortCheck =
  | { readonly status: "ready"; readonly cohort: Cohort }
  | { readonly status: "refused"; readonly message: string };

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A published value at its published precision: "4.32", "+0.107", "65.12%", "1,214". */
export function formatExact(value: number, definition: SkillTreeDefinitionRecord): string {
  const signed =
    definition.unit === "epa" || definition.unit === "pp" || definition.metric_id.includes("over_expected");
  const sign = signed && value > 0 ? "+" : "";
  switch (definition.unit) {
    case "count":
      return Math.round(value).toLocaleString("en-US");
    case "fraction":
      return `${(value * 100).toFixed(Math.max(0, definition.decimals - 2))}%`;
    default:
      return `${sign}${value.toFixed(definition.decimals)}`;
  }
}

function singular(word: string): string {
  if (word.endsWith("ies")) return `${word.slice(0, -3)}y`;
  return word.endsWith("s") ? word.slice(0, -1) : word;
}

/** "Rushing TDs" → "rushing TDs": a count's own noun, acronyms kept. */
function countNoun(label: string): string {
  return label
    .split(" ")
    .map((word) => (word.slice(1) === word.slice(1).toLowerCase() ? word.toLowerCase() : word))
    .join(" ");
}

/**
 * The unit a value or a difference is read in: "yds/carry", "EPA/dropback", "pp", "s",
 * "carries". A pooled per-opportunity rate names its opportunity; a percentage's difference is
 * in percentage points.
 */
export function compareUnit(definition: SkillTreeDefinitionRecord): string {
  const per = (unit: string): string => {
    if (definition.numerator_label === null || definition.denominator_label === null) return unit;
    const noun = definition.denominator_label.replace(/\s*\(.*\)\s*$/, "").trim().split(" ").at(-1) ?? "";
    return noun === "" ? unit : `${unit}/${singular(noun)}`;
  };
  switch (definition.unit) {
    case "count":
      return countNoun(definition.label);
    case "fraction":
    case "pp":
      return "pp";
    case "seconds":
      return "s";
    case "epa":
      return per("EPA");
    case "yards":
      return per("yds");
  }
}

/** A value with its unit, for the comparison's words ("4.32 yds/carry", "65.12%", "412 carries"). */
export function valueWithUnit(value: number, definition: SkillTreeDefinitionRecord): string {
  const text = formatExact(value, definition);
  if (definition.unit === "fraction") return text;
  return `${text} ${compareUnit(definition)}`;
}

/** The comparison's side of a difference, in the metric's own direction. */
export type Side = "ahead" | "behind" | "level" | "undirected";

/**
 * A pinned player's value against the focal player's, at the published precision (integer
 * arithmetic on scaled values, so no float residue): "+0.42 yds/carry vs Joe Pierce", and on
 * which side of him in the metric's direction. A lower-is-better metric's smaller value is
 * ahead; a context metric has no side.
 */
export function difference(
  member: CohortMember,
  focal: CohortMember,
  definition: SkillTreeDefinitionRecord,
  focalName: string,
): { readonly text: string; readonly side: Side; readonly words: string } {
  const scale = 10 ** definition.decimals;
  const steps = Math.round(member.value * scale) - Math.round(focal.value * scale);
  const unit = compareUnit(definition);
  let magnitude: string;
  if (definition.unit === "fraction") {
    magnitude = ((Math.abs(steps) / scale) * 100).toFixed(Math.max(0, definition.decimals - 2));
  } else if (definition.unit === "count") {
    magnitude = Math.round(Math.abs(steps) / scale).toLocaleString("en-US");
  } else {
    magnitude = (Math.abs(steps) / scale).toFixed(definition.decimals);
  }
  const better = definition.direction === "lower" ? "lower is better" : "higher is better";
  if (steps === 0) {
    return {
      text: `Same as ${focalName}`,
      side: definition.direction === "neutral" ? "undirected" : "level",
      words: `0 ${unit} difference`,
    };
  }
  const sign = steps > 0 ? "+" : "-";
  const text = `${sign}${magnitude} ${unit} vs ${focalName}`;
  if (definition.direction === "neutral") return { text, side: "undirected", words: "no better direction" };
  const ahead = definition.direction === "lower" ? steps < 0 : steps > 0;
  return {
    text,
    side: ahead ? "ahead" : "behind",
    words: `${ahead ? "ahead of" : "behind"} ${focalName}; ${better}`,
  };
}

function describeRow(row: Record<string, unknown>): string {
  return `build ${String(row.build_id)}, ${String(row.season)} through week ${String(row.through_week)}, ${String(row.position)} ${String(row.metric_id)}`;
}

/**
 * Check a served cohort against the focal reading it is meant to explain, and decode it. Any
 * disagreement refuses the whole cohort with a sentence that says what disagreed.
 */
export function checkCohort(
  load: SkillCohortLoad,
  focal: SkillReading,
  nameOf: (playerId: string) => string | null,
): CohortCheck {
  const provenance = focal.provenance;
  const definition = focal.definition;
  if (provenance === null || focal.state !== "ranked" || focal.value === null) {
    return { status: "refused", message: "His reading is not ranked, so there is no cohort to compare against." };
  }
  const expected = {
    build_id: provenance.buildId,
    season: provenance.season,
    through_week: provenance.throughWeek,
    position: provenance.position,
    metric_id: definition.metric_id,
  } as const;
  if (load.position !== provenance.position || load.metricId !== definition.metric_id) {
    return {
      status: "refused",
      message: `The cohort served is ${load.position} ${load.metricId}, not his ${provenance.position} ${definition.metric_id}. Nothing is drawn.`,
    };
  }
  const members: CohortMember[] = [];
  const seen = new Set<string>();
  for (const row of load.rows) {
    const wrong = (Object.keys(expected) as (keyof typeof expected)[]).filter((field) => row[field] !== expected[field]);
    if (wrong.length > 0) {
      return {
        status: "refused",
        message:
          `A cohort row is from another ${wrong.map((field) => field.replace("_id", "").replace("_", " ")).join(", ")} ` +
          `(${describeRow(row)}) than his reading (build ${provenance.buildId}, ${String(provenance.season)} ` +
          `through week ${String(provenance.throughWeek)}). Nothing is drawn: a comparison across builds, windows, ` +
          `positions or metrics would be wrong.`,
      };
    }
    const playerId = typeof row.player_id === "string" ? row.player_id : null;
    const value = finite(row.value);
    const state = typeof row.state === "string" && MEMBER_STATES.has(row.state) ? (row.state as MemberState) : null;
    if (playerId === null || value === null || state === null) {
      return { status: "refused", message: "The cohort file has a row this page cannot read. Nothing is drawn." };
    }
    if (seen.has(playerId)) {
      return { status: "refused", message: "The cohort file lists a player twice. Nothing is drawn." };
    }
    seen.add(playerId);
    members.push({
      playerId,
      name: nameOf(playerId) ?? `Unnamed player (${playerId})`,
      state,
      value,
      numerator: finite(row.numerator),
      denominator: finite(row.denominator),
      rank: state === "ranked" ? finite(row.rank) : null,
      percentile: state === "ranked" ? finite(row.percentile) : null,
      cohortSize: state === "ranked" ? finite(row.cohort_size) : null,
      games: finite(row.games) ?? 0,
      focal: playerId === provenance.playerId,
    });
  }
  const ranked = members.filter((member) => member.state === "ranked");
  const brokenRank = ranked.find(
    (member) =>
      member.cohortSize !== ranked.length ||
      member.rank === null ||
      member.rank < 1 ||
      member.rank > ranked.length ||
      member.percentile === null ||
      member.percentile < 0 ||
      member.percentile > 100,
  );
  if (brokenRank !== undefined || focal.cohortSize !== ranked.length) {
    return {
      status: "refused",
      message:
        `The cohort file ranks ${String(ranked.length)} players, but his reading was ranked among ` +
        `${String(focal.cohortSize ?? "an unknown number of")}. Nothing is drawn.`,
    };
  }
  const mine = members.find((member) => member.focal);
  if (mine === undefined) {
    return { status: "refused", message: "He is not in the cohort file for this metric. Nothing is drawn." };
  }
  if (
    mine.state !== "ranked" ||
    mine.value !== focal.value ||
    mine.rank !== focal.rank ||
    mine.percentile !== focal.percentile
  ) {
    const reading = (value: number | null, rank: number | null, percentile: number | null): string =>
      `${value === null ? "no value" : formatExact(value, definition)}, ${rank === null ? "unranked" : ordinal(rank)}, ` +
      `${percentile === null ? "no" : percentileWords(percentile)} pct`;
    return {
      status: "refused",
      message:
        `His row in the cohort (${reading(mine.value, mine.rank, mine.percentile)}) disagrees with his reading in the ` +
        `tree (${reading(focal.value, focal.rank, focal.percentile)}). Nothing is drawn.`,
    };
  }
  const sign = definition.direction === "lower" ? 1 : -1;
  const byName = (a: CohortMember, b: CohortMember): number => a.name.localeCompare(b.name);
  return {
    status: "ready",
    cohort: {
      ranked: [...ranked].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0) || byName(a, b)),
      unranked: members
        .filter((member) => member.state !== "ranked")
        .sort((a, b) => sign * (a.value - b.value) || byName(a, b)),
      focal: mine,
      byId: new Map(members.map((member) => [member.playerId, member])),
    },
  };
}

/** A member's sample in words ("92 carries", "30 of 34 targets"). */
export function memberSample(member: CohortMember, definition: SkillTreeDefinitionRecord): string {
  return sampleText(
    {
      state: member.state,
      numerator: member.numerator,
      denominator: member.denominator,
      games: member.games,
      rank: member.rank,
      percentile: member.percentile,
      cohort_size: member.cohortSize,
    },
    definition,
  );
}

/** A member's standing in words: "55.6 pct · 5th of 10", or "Unranked · 7 of 25 carries". */
export function memberStanding(member: CohortMember, definition: SkillTreeDefinitionRecord): string {
  return standingText(
    {
      state: member.state,
      numerator: member.numerator,
      denominator: member.denominator,
      games: member.games,
      rank: member.rank,
      percentile: member.percentile,
      cohort_size: member.cohortSize,
    },
    definition,
    null,
  );
}

/** Case- and accent-insensitive name search, best matches (name starts) first. */
export function searchMembers(
  cohort: Cohort,
  query: string,
  exclude: ReadonlySet<string>,
  limit = 6,
): readonly CohortMember[] {
  const fold = (text: string): string =>
    text
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .trim();
  const wanted = fold(query);
  if (wanted === "") return [];
  const all = [...cohort.ranked, ...cohort.unranked].filter(
    (member) => !member.focal && !exclude.has(member.playerId) && fold(member.name).includes(wanted),
  );
  const starts = (member: CohortMember): number =>
    fold(member.name)
      .split(/\s+/)
      .some((word) => word.startsWith(wanted))
      ? 0
      : 1;
  return all.sort((a, b) => starts(a) - starts(b)).slice(0, limit);
}

// ------------------------------------------------------------------------------ geometry

/** The axis domain over these values: never zero-width, never NaN, negative values kept. */
export function valueDomain(values: readonly number[], definition: SkillTreeDefinitionRecord): [number, number] {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) return [0, 1];
  let min = Math.min(...finiteValues);
  let max = Math.max(...finiteValues);
  if (max - min <= 0) {
    // An all-equal cohort: a window around the one value, a step of its published precision
    // at least, so the axis has width and the dots sit in its middle.
    const step = definition.unit === "count" ? 1 : 10 ** -Math.max(0, definition.decimals - 1);
    const pad = Math.max(Math.abs(min) * 0.1, step);
    min -= pad;
    max += pad;
  }
  if (definition.unit === "count" || definition.unit === "fraction") {
    // Counts and shares never go below zero; start the axis at zero when it is near.
    if (min > 0 && min < (max - min) * 0.25) min = 0;
  }
  return [min, max];
}

/** About `count` round tick values inside [min, max]. */
export function niceTicks(min: number, max: number, count = 4): readonly number[] {
  const span = max - min;
  if (!(span > 0) || !Number.isFinite(span)) return [min];
  const raw = span / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
  const first = Math.ceil(min / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let value = first; value <= max + step * 1e-9; value += step) {
    // Snap away float residue (0.30000000000000004) without changing the tick.
    ticks.push(Number(value.toPrecision(12)));
  }
  return ticks;
}

/**
 * Deterministic dot stacking: members in value order (ties by player id) each take the lowest
 * level whose previous dot is at least `diameter` pixels to the left. Equal values therefore
 * share one column, stacked upward; no randomness anywhere.
 */
export function stackLevels(
  members: readonly CohortMember[],
  x: (value: number) => number,
  diameter: number,
): ReadonlyMap<string, number> {
  const ordered = [...members].sort((a, b) => a.value - b.value || a.playerId.localeCompare(b.playerId));
  const lastX: number[] = [];
  const levels = new Map<string, number>();
  for (const member of ordered) {
    const position = x(member.value);
    let level = lastX.findIndex((previous) => position - previous >= diameter);
    if (level === -1) level = lastX.length;
    lastX[level] = position;
    levels.set(member.playerId, level);
  }
  return levels;
}
