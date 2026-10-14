/**
 * The Skill Tree's view model (ADR-107): published readings and definitions → branches, nodes
 * and the words each node prints.
 *
 * Loaded only with the Skill Tree's lazy chunk. It **computes nothing about football**: every
 * value, sample, rank, percentile, label, definition and limitation is the artifact's own, and
 * this module only formats them and arranges them in the order the definitions give. The one
 * judgement it makes is presentational — how many of five meter segments a published
 * percentile lights — and that rule is ADR-107's, stated beside the meter in the legend.
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
  /** Lit meter segments, 0-5 (higher/lower metrics); 0 when not ranked. */
  readonly segments: number;
  /** A neutral (context) metric's position on its track, 0-100, instead of a fill. */
  readonly marker: number | null;
  /** True when the node must draw its neutral "no reading" frame. */
  readonly empty: boolean;
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

function sampleText(
  reading: PlayerSkillMetricRecord | null,
  definition: SkillTreeDefinitionRecord,
): string {
  if (reading === null) return "";
  if (definition.role === "archive") {
    if (reading.source_season === null) return "";
    const tested = reading.reason?.startsWith("tested_as:") === true ? ` as a ${reading.reason.slice(10)}` : "";
    return `tested ${String(reading.source_season)}${tested}`;
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

function standingText(
  reading: PlayerSkillMetricRecord | null,
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
      if (definition.direction === "neutral") return `above ${String(Math.round(percentile))}% · ${place}`;
      return `${ordinal(Math.round(percentile))} pct · ${place}`;
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
    case "unavailable":
      return reading.reason !== null && meta?.reasons?.[reading.reason] !== undefined
        ? "Unavailable this build"
        : "Unavailable";
    case "no_appearances":
      return "No games yet";
  }
}

function segmentsFor(reading: PlayerSkillMetricRecord | null, definition: SkillTreeDefinitionRecord): number {
  if (reading?.state !== "ranked" || reading.percentile === null) return 0;
  if (definition.direction === "neutral" || definition.role === "presence") return 0;
  return Math.min(5, Math.floor(reading.percentile / 20) + 1);
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
    segments: segmentsFor(reading, definition),
    marker:
      reading?.state === "ranked" && definition.direction === "neutral" && definition.role !== "presence"
        ? numberOrNull(reading.percentile)
        : null,
    empty,
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

/** The accessible name of a node: label, value, state and standing, never colour alone. */
export function nodeName(node: SkillReading): string {
  const value = node.empty ? "" : ` ${node.valueText}${node.unitText === "" ? "" : ` ${node.unitText}`}`;
  return `${node.definition.label}:${value}. ${node.standingText}.`;
}
