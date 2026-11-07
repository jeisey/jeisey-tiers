/**
 * The Skill Tree's view model (ADR-107): published readings and definitions → branches, nodes
 * and the words each node prints.
 *
 * Loaded only with the Skill Tree's lazy chunk. It **computes nothing about football**: every
 * value, sample, rank, percentile, label, definition and limitation is the artifact's own, and
 * this module only formats them and arranges them in the order the definitions give. The two
 * judgements it makes are presentational — how many of the meter's ten ticks a published
 * percentile lights (`meterTicks`) and which of five bands tints them (`percentileBand`) —
 * and both rules are stated beside the meter in the legend.
 */

import type {
  PlayerSkillMetricRecord,
  Position,
  SkillState,
  SkillTreeDefinitionRecord,
  SkillTreeMetadata,
} from "./contracts";
import { ordinal } from "./cohort";
import type { SkillTreeLoad } from "./store";

/** The meter's ticks: one per ten percentile points. */
export const METER_TICKS = 10;

/**
 * Ticks a ranked higher/lower reading lights — **the one tick rule**, shared by the node meter,
 * the detail, the legend and the accessible name.
 *
 * `0` lights none; any positive percentile lights `ceil(p / 10)`, capped at ten: 0.1–10 → 1,
 * 10.1–20 → 2, …, 90.1–100 → 10. Rounded up, so a reading the cohort places above its very
 * bottom never draws as an empty meter, and only the bottom of the cohort (percentile 0) does.
 * Published percentiles carry one decimal; the value is read at that precision first so a
 * float such as 20.000000001 cannot light a third tick. The percentile is already
 * direction-adjusted (a lower-is-better metric's best reading is 100): never invert it here.
 */
export function meterTicks(percentile: number): number {
  if (!Number.isFinite(percentile) || percentile <= 0) return 0;
  return Math.min(METER_TICKS, Math.ceil(Math.round(percentile * 10) / 100));
}

/** A percentile band, 1 (lowest) to 5 (highest). */
export type PercentileBand = 1 | 2 | 3 | 4 | 5;

/**
 * The band that tints a ranked higher/lower reading's ticks, frame and glyph: below 20 → 1,
 * 20 to under 40 → 2, 40 to under 60 → 3, 60 to under 80 → 4, 80 to 100 → 5. Lower bounds are
 * inclusive. Like the ticks it reads the published, direction-adjusted percentile.
 */
export function percentileBand(percentile: number): PercentileBand {
  const p = Number.isFinite(percentile) ? Math.round(percentile * 10) / 10 : 0;
  if (p >= 80) return 5;
  if (p >= 60) return 4;
  if (p >= 40) return 3;
  if (p >= 20) return 2;
  return 1;
}

/** Each band's range in words, for the legend and the accessible names. */
export const BAND_WORDS: Readonly<Record<PercentileBand, string>> = {
  1: "below 20",
  2: "20 to under 40",
  3: "40 to under 60",
  4: "60 to under 80",
  5: "80 to 100",
};

/** Each band's range as the legend's key prints it. */
export const BAND_KEY: Readonly<Record<PercentileBand, string>> = {
  1: "<20",
  2: "20–39.9",
  3: "40–59.9",
  4: "60–79.9",
  5: "80–100",
};

/** A published percentile in words: "80th", "1.5", "0" — exact, never rounded to a whole. */
export function percentileWords(percentile: number): string {
  if (percentile === 0) return "0";
  return Number.isInteger(percentile) ? ordinal(percentile) : percentile.toFixed(1);
}

const STATES: ReadonlySet<string> = new Set([
  "ranked",
  "below_minimum",
  "small_cohort",
  "no_opportunity",
  "not_covered",
  "unavailable",
  "no_appearances",
]);

/** One metric, as a node or a node's detail, ready to draw. */
export interface SkillReading {
  readonly id: string;
  readonly definition: SkillTreeDefinitionRecord;
  readonly state: SkillState | "missing";
  readonly value: number | null;
  readonly numerator: number | null;
  readonly denominator: number | null;
  readonly rank: number | null;
  readonly percentile: number | null;
  readonly cohortSize: number | null;
  readonly sourceSeason: number | null;
  readonly reason: string | null;
  /** The value as the node prints it ("65.1%", "+0.14", "—"). */
  readonly valueText: string;
  /** A short unit after the value ("yds", "EPA", "pp", "s"), or "". */
  readonly unitText: string;
  /** The sample behind the value ("27 of 34 targets"), or "". */
  readonly sampleText: string;
  /** Where it stands, in words ("84th pct · 6th of 36", "Unranked · 12 of 50 dropbacks"). */
  readonly standingText: string;
  /**
   * What the meter draws: `ticks` lit ticks of ten (a ranked higher/lower reading, the
   * archive's included), `marker` (a context metric's position on a neutral track), or
   * `none` — no rank to draw, so a dashed empty track and the state in words.
   */
  readonly meter: "ticks" | "marker" | "none";
  /** Lit ticks, 0-10, by `meterTicks`; 0 unless `meter` is `ticks`. */
  readonly ticks: number;
  /**
   * The tint band of a ranked higher/lower reading of this season, by `percentileBand`. Null
   * for everything the band palette must not judge: context metrics, the archive (historical
   * testers, not a current grade), presence, and every unranked or missing reading.
   */
  readonly band: PercentileBand | null;
  /** The meter in words, for the accessible name ("3 of 10 ticks, band 20 to under 40"). */
  readonly meterText: string;
  /** A neutral (context) metric's position on its track, 0-100, instead of a fill. */
  readonly marker: number | null;
  /** True when the node must draw its neutral "no reading" frame. */
  readonly empty: boolean;
  /**
   * Whose reading this is and from which build and window — what a comparison checks every
   * cohort row against (ADR-117). Null when the build has no record for this metric.
   */
  readonly provenance: {
    readonly playerId: string;
    readonly buildId: string;
    readonly season: number;
    readonly throughWeek: number;
    readonly position: string;
    readonly games: number;
  } | null;
  readonly details: readonly SkillReading[];
}

export interface SkillBranch {
  readonly id: string;
  readonly label: string;
  readonly nodes: readonly SkillReading[];
}

export interface SkillTreeView {
  readonly position: Position;
  readonly games: number;
  readonly window: string;
  readonly branches: readonly SkillBranch[];
  readonly archive: SkillReading | null;
  readonly presence: SkillReading | null;
  /** He has a presence record and no games. */
  readonly noAppearances: boolean;
  /** No record at all: the build published a tree but not for him. */
  readonly noRecord: boolean;
  /** Sources withheld for this build, by name, with their sentences. */
  readonly withheld: readonly { readonly source: string; readonly sentence: string }[];
}

const NOUN: Readonly<Record<string, string>> = {
  QB: "QBs",
  RB: "RBs",
  WR: "WRs",
  TE: "TEs",
};

const SHORT_REASON: Readonly<Record<string, string>> = {
  not_in_ngs_summary: "Not in Next Gen Stats",
  ngs_volume_mismatch: "NGS total does not match",
  no_combine_forty: "No combine 40 on file",
  no_snap_rows: "No snap data",
  next_gen_stats_not_at_cutoff: "NGS not at this week yet",
  next_gen_stats_not_published: "Not published",
};

const SOURCE_NAMES: Readonly<Record<string, string>> = {
  player_stats: "Box score",
  snap_counts: "Snap counts",
  play_by_play: "Play-by-play",
  next_gen_stats: "Next Gen Stats",
  combine: "Combine",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Shape-check one reading; anything malformed is skipped rather than drawn wrong. */
export function parseReading(row: Record<string, unknown>): PlayerSkillMetricRecord | null {
  if (typeof row.metric_id !== "string" || typeof row.player_id !== "string") return null;
  if (typeof row.state !== "string" || !STATES.has(row.state)) return null;
  return row as unknown as PlayerSkillMetricRecord;
}

export function parseDefinition(row: Record<string, unknown>): SkillTreeDefinitionRecord | null {
  if (typeof row.metric_id !== "string" || typeof row.label !== "string") return null;
  if (!["presence", "node", "detail", "archive"].includes(String(row.role))) return null;
  return row as unknown as SkillTreeDefinitionRecord;
}

function signed(definition: SkillTreeDefinitionRecord): boolean {
  return (
    definition.unit === "epa" ||
    definition.unit === "pp" ||
    definition.metric_id.includes("over_expected")
  );
}

/** A published value as the node prints it. Display rounding only; the value is the artifact's. */
export function formatSkillValue(value: number | null, definition: SkillTreeDefinitionRecord): string {
  if (value === null) return "—";
  const sign = signed(definition) && value > 0 ? "+" : "";
  switch (definition.unit) {
    case "count":
      return Math.round(value).toLocaleString("en-US");
    case "fraction":
      return `${(value * 100).toFixed(1)}%`;
    case "pp":
      return `${sign}${value.toFixed(1)}`;
    case "epa":
      return `${sign}${value.toFixed(2)}`;
    case "seconds":
      return value.toFixed(2);
    case "yards":
      return `${sign}${value.toFixed(definition.metric_id.includes("over_expected") ? 2 : 1)}`;
  }
}

export function unitText(definition: SkillTreeDefinitionRecord): string {
  switch (definition.unit) {
    case "pp":
      return "pp";
    case "epa":
      return "EPA";
    case "seconds":
      return "s";
    case "yards":
      return "yds";
    default:
      return "";
  }
}

function count(value: number): string {
  return Number.isInteger(value) ? value.toLocaleString("en-US") : value.toFixed(1);
}

/** What a sample or standing line reads of a reading: a tree record or a cohort row. */
export type ReadingFields = Pick<
  PlayerSkillMetricRecord,
  "state" | "numerator" | "denominator" | "games" | "rank" | "percentile" | "cohort_size"
> &
  Partial<Pick<PlayerSkillMetricRecord, "source_season" | "reason">>;

/** The sample behind a value ("27 of 34 targets", "in 8 games"), or "". */
export function sampleText(
  reading: ReadingFields | null,
  definition: SkillTreeDefinitionRecord,
): string {
  if (reading === null) return "";
  if (definition.role === "archive") {
    const season = reading.source_season ?? null;
    if (season === null) return "";
    const reason = reading.reason ?? null;
    const tested = reason?.startsWith("tested_as:") === true ? ` as a ${reason.slice(10)}` : "";
    return `tested ${String(season)}${tested}`;
  }
  if (definition.role === "presence") return "";
  if (definition.kind === "volume") {
    return reading.games > 0 ? `in ${String(reading.games)} game${reading.games === 1 ? "" : "s"}` : "";
  }
  const { numerator, denominator } = reading;
  if (denominator === null) return "";
  const unit = definition.denominator_label ?? "";
  if (numerator === null) return `on ${count(denominator)} ${unit}`.trim();
  if (definition.numerator_label === "EPA") {
    const sign = numerator > 0 ? "+" : "";
    return `${sign}${numerator.toFixed(1)} EPA on ${count(denominator)} ${unit}`;
  }
  if (definition.unit === "fraction") return `${count(numerator)} of ${count(denominator)} ${unit}`;
  return `${count(numerator)} ${definition.numerator_label ?? ""} on ${count(denominator)} ${unit}`;
}

/**
 * Where a reading stands, in words. A ranked reading prints its **exact** published percentile
 * ("55.6 pct", "80th pct", "0 pct") and its place ("5th of 10"): the meter is a coarse aid,
 * these words are the reading.
 */
export function standingText(
  reading: ReadingFields | null,
  definition: SkillTreeDefinitionRecord,
  meta: SkillTreeMetadata | null,
): string {
  const noun = NOUN[definition.position] ?? "players";
  if (reading === null) return "No reading in this build";
  const { percentile, rank, cohort_size: cohort } = reading;
  switch (reading.state) {
    case "ranked": {
      if (percentile === null || rank === null || cohort === null) return "";
      const place = `${ordinal(rank)} of ${String(cohort)}`;
      if (definition.role === "presence") return `${place} ${noun} by games`;
      if (definition.direction === "neutral") {
        const above = Number.isInteger(percentile) ? String(percentile) : percentile.toFixed(1);
        return `above ${above}% · ${place}`;
      }
      return `${percentileWords(percentile)} pct · ${place}`;
    }
    case "below_minimum": {
      const sample = definition.minimum_unit === "games" ? reading.games : reading.denominator;
      return definition.minimum === null || sample === null
        ? "Unranked · small sample"
        : `Unranked · ${count(sample)} of ${count(definition.minimum)} ${definition.minimum_unit ?? ""}`.trim();
    }
    case "small_cohort":
      return `Unranked · ${String(cohort ?? 0)} qualified ${noun}`;
    case "no_opportunity":
      return definition.denominator_label === null
        ? "No opportunity yet"
        : `No ${definition.denominator_label} yet`;
    case "not_covered":
      return SHORT_REASON[reading.reason ?? ""] ?? "Not covered";
    case "unavailable": {
      const reason = reading.reason ?? null;
      return reason !== null && meta?.reasons?.[reason] !== undefined ? "Unavailable this build" : "Unavailable";
    }
    case "no_appearances":
      return "No games yet";
  }
}

/**
 * The meter of one reading. Ticks for a ranked higher/lower reading (the archive's too); a
 * marker for a ranked context metric; nothing for presence (its standing is a place by games)
 * or for anything unranked. Only a current-season ranked higher/lower reading is banded.
 */
function meterFor(
  reading: PlayerSkillMetricRecord | null,
  definition: SkillTreeDefinitionRecord,
): Pick<SkillReading, "meter" | "ticks" | "band" | "marker" | "meterText"> {
  const percentile = numberOrNull(reading?.percentile);
  if (reading?.state !== "ranked" || percentile === null || definition.role === "presence") {
    return { meter: "none", ticks: 0, band: null, marker: null, meterText: "" };
  }
  if (definition.direction === "neutral") {
    return {
      meter: "marker",
      ticks: 0,
      band: null,
      marker: percentile,
      meterText: "a position marker, not a grade",
    };
  }
  const ticks = meterTicks(percentile);
  const lit = `${String(ticks)} of ${String(METER_TICKS)} ticks`;
  if (definition.role === "archive") {
    return { meter: "ticks", ticks, band: null, marker: null, meterText: `${lit} among historical testers` };
  }
  const band = percentileBand(percentile);
  return { meter: "ticks", ticks, band, marker: null, meterText: `${lit}, band ${BAND_WORDS[band]}` };
}

function toReading(
  definition: SkillTreeDefinitionRecord,
  reading: PlayerSkillMetricRecord | null,
  meta: SkillTreeMetadata | null,
  details: readonly SkillReading[],
): SkillReading {
  const state: SkillState | "missing" = reading?.state ?? "missing";
  const empty =
    state === "no_opportunity" || state === "not_covered" || state === "unavailable" || state === "missing";
  return {
    id: definition.metric_id,
    definition,
    state,
    value: numberOrNull(reading?.value),
    numerator: numberOrNull(reading?.numerator),
    denominator: numberOrNull(reading?.denominator),
    rank: numberOrNull(reading?.rank),
    percentile: numberOrNull(reading?.percentile),
    cohortSize: numberOrNull(reading?.cohort_size),
    sourceSeason: numberOrNull(reading?.source_season),
    reason: reading?.reason ?? null,
    valueText: formatSkillValue(numberOrNull(reading?.value), definition),
    unitText: unitText(definition),
    sampleText: sampleText(reading, definition),
    standingText: standingText(reading, definition, meta),
    ...meterFor(reading, definition),
    empty,
    provenance:
      reading === null
        ? null
        : {
            playerId: reading.player_id,
            buildId: reading.build_id,
            season: reading.season,
            throughWeek: reading.through_week,
            position: reading.position,
            games: reading.games,
          },
    details,
  };
}

export function parseMeta(value: unknown): SkillTreeMetadata | null {
  return isRecord(value) && typeof value.method_version === "string"
    ? (value as unknown as SkillTreeMetadata)
    : null;
}

/** Published readings and definitions → the tree. Order is the definitions'. */
export function buildSkillTreeView(load: SkillTreeLoad, metaValue: unknown, position: Position): SkillTreeView {
  const meta = parseMeta(metaValue);
  const definitions = load.definitions
    .map(parseDefinition)
    .filter((row): row is SkillTreeDefinitionRecord => row !== null && row.position === position);
  const readings = new Map<string, PlayerSkillMetricRecord>();
  for (const row of load.rows) {
    const reading = parseReading(row);
    if (reading !== null) readings.set(reading.metric_id, reading);
  }
  const reading = (id: string): PlayerSkillMetricRecord | null => readings.get(id) ?? null;

  const branches = new Map<string, { label: string; order: number; nodes: SkillTreeDefinitionRecord[] }>();
  for (const definition of definitions) {
    if (definition.role !== "node" || definition.branch_id === null) continue;
    const branch = branches.get(definition.branch_id) ?? {
      label: definition.branch_label ?? definition.branch_id,
      order: definition.branch_order ?? 99,
      nodes: [],
    };
    branch.nodes.push(definition);
    branches.set(definition.branch_id, branch);
  }
  const detailsOf = (parent: string): readonly SkillReading[] =>
    definitions
      .filter((definition) => definition.role === "detail" && definition.parent_metric_id === parent)
      .sort((a, b) => a.order - b.order)
      .map((definition) => toReading(definition, reading(definition.metric_id), meta, []));

  const presenceDefinition = definitions.find((definition) => definition.role === "presence") ?? null;
  const archiveDefinition = definitions.find((definition) => definition.role === "archive") ?? null;
  const presenceReading = presenceDefinition === null ? null : reading(presenceDefinition.metric_id);
  const games = presenceReading?.games ?? 0;
  const withheld = Object.entries(meta?.sources ?? {})
    .filter(([, state]) => state.status !== "published")
    .map(([source, state]) => ({
      source: SOURCE_NAMES[source] ?? source,
      sentence: (state.reason !== null ? meta?.reasons?.[state.reason] : undefined) ?? "Unavailable for this build.",
    }));

  return {
    position,
    games,
    window: definitions[0]?.window ?? meta?.window ?? "",
    branches: [...branches.entries()]
      .sort(([, a], [, b]) => a.order - b.order)
      .map(([id, branch]) => ({
        id,
        label: branch.label,
        nodes: branch.nodes
          .sort((a, b) => a.order - b.order)
          .map((definition) =>
            toReading(definition, reading(definition.metric_id), meta, detailsOf(definition.metric_id)),
          ),
      })),
    archive:
      archiveDefinition === null || games === 0
        ? null
        : toReading(archiveDefinition, reading(archiveDefinition.metric_id), meta, []),
    presence:
      presenceDefinition === null ? null : toReading(presenceDefinition, presenceReading, meta, []),
    noAppearances: presenceReading?.state === "no_appearances",
    noRecord: readings.size === 0,
    withheld,
  };
}

/** Every node in reading order (branch by branch), for keyboard movement. */
export function nodeOrder(view: SkillTreeView): readonly string[] {
  return view.branches.flatMap((branch) => branch.nodes.map((node) => node.id));
}

/**
 * The accessible name of a node: label, value, state, standing and the meter in words, never
 * colour alone. A ranked reading at percentile 0 says "0 pct · 66th of 66. 0 of 10 ticks"; a
 * missing one says why it has no value and has no meter words at all.
 */
export function nodeName(node: SkillReading): string {
  const value = node.empty ? "" : `: ${node.valueText}${node.unitText === "" ? "" : ` ${node.unitText}`}`;
  const meter = node.meterText === "" ? "" : ` Meter: ${node.meterText}.`;
  return `${node.definition.label}${value}. ${node.standingText}.${meter}`;
}
