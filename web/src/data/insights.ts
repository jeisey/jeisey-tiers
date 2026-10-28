/**
 * The Insights feed (ADR-116): reading the stories, choosing what the feed shows, and the words
 * around them.
 *
 * **The page writes no finding.** Every headline, dek, fact, counterpoint and caveat is the
 * artifact's own text, generated at build time from fixed rules over published evidence. What
 * this module adds is presentation only — which stories a filter shows and in what order, the
 * labels around them, the link and summary a reader copies — and one decision the page must make
 * at the reader's clock rather than the build's: a `this_week` story stops being a start idea at
 * kickoff, or when the availability policy (ADR-101) would refuse him.
 *
 * Imported only by the lazy Insights chunk: the entry bundle never pays for the parser.
 */

import { featureable, startExclusion, type Availability } from "./availability";
import type {
  InsightBasis,
  InsightChart,
  InsightEvidenceRow,
  InsightFamily,
  InsightFamilyStatus,
  InsightHorizon,
  InsightStoryRow,
  InsightVariant,
  InsightsMetadata,
  ScoringPreset,
  WeeklyProjectionRecord,
} from "./contracts";
import { EM_DASH, formatAge, formatEastern } from "./format";
import { STALE_WARNING_HOURS } from "./freshness";
import { matchesPosition, matchesSearch } from "./model";
import type { InsightCeiling, InsightFilter, PositionFilter, ScoringValue } from "./state";

/**
 * A story as the feed reads it: a served feed row (no record version, no evidence), validated.
 * Its evidence, qualification and sibling findings are a separate slice, read on demand.
 */
export type InsightStory = InsightStoryRow;

/** One story's evidence, qualification and sibling findings (`insight_evidence/<scoring>`). */
export type InsightEvidence = InsightEvidenceRow;

type Raw = Record<string, unknown>;

// ------------------------------------------------------------------------------- parsing

const FAMILIES: readonly InsightFamily[] = [
  "weekly_upside",
  "opportunity_opening",
  "volume_vs_results",
  "streak_watch",
  "role_battle",
  "pace_perspective",
];

const VARIANTS: readonly InsightVariant[] = [
  "lagging",
  "shrinking",
  "ceiling",
  "observed",
  "prospective",
  "backfield",
  "receiving",
  "breakout",
  "production_without_role",
  "quiet_role_growth",
  "per_game_hidden",
  "overlooked",
];

const HORIZONS: readonly InsightHorizon[] = ["this_week", "stash", "role_watch", "season_view"];
const BASES: readonly InsightBasis[] = ["observed", "model", "market"];
const PRESETS: readonly ScoringPreset[] = ["STD", "HALF", "PPR"];
const POSITIONS = ["QB", "RB", "WR", "TE"] as const;
const SOURCES = [
  "nflverse_player_stats",
  "nflverse_snap_counts",
  "nflverse_pbp",
  "nflverse_schedule",
  "nflverse_injuries",
  "weekly_startsit_v1",
  "espn_fantasy_ownership",
] as const;

const STORY_ID = /^[a-z]+-[a-z0-9-]+$/;
const EDITION = /^([0-9]{4})w([0-9]{2})$/;

function isObject(value: unknown): value is Raw {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isString(value: unknown): value is string {
  return typeof value === "string";
}
function isText(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}
function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
function isInt(value: unknown, minimum = Number.NEGATIVE_INFINITY): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}
function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value);
}
function orNull(check: (value: unknown) => boolean): (value: unknown) => boolean {
  return (value) => value === null || check(value);
}
function isScalar(value: unknown): boolean {
  return value === null || ["number", "string", "boolean"].includes(typeof value);
}
function isTime(value: unknown): boolean {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}
function isGsis(value: unknown): boolean {
  return typeof value === "string" && value.startsWith("gsis:");
}
function every(value: unknown, check: (item: unknown) => boolean, min = 0, max = Infinity): boolean {
  return Array.isArray(value) && value.length >= min && value.length <= max && value.every(check);
}

const nullableNumber = orNull(isNumber);
const nullableInt = (minimum: number) => orNull((value) => isInt(value, minimum));

function isFact(value: unknown): boolean {
  return isObject(value) && isText(value.label) && isText(value.value) && isOneOf(value.basis, BASES);
}

function isWindow(value: unknown): boolean {
  return (
    isObject(value) &&
    isText(value.label) &&
    isInt(value.first_week, 1) &&
    isInt(value.last_week, 1) &&
    isInt(value.weeks, 1) &&
    nullableInt(1)(value.baseline_first_week) &&
    nullableInt(1)(value.baseline_last_week)
  );
}

function isPredicate(value: unknown): boolean {
  return (
    isObject(value) &&
    isText(value.rule) &&
    isText(value.label) &&
    isScalar(value.value) &&
    isScalar(value.threshold) &&
    value.passed === true
  );
}

function isStripWeek(value: unknown): boolean {
  return (
    isObject(value) &&
    isInt(value.week, 1) &&
    isOneOf(value.status, ["P", "B", "D"] as const) &&
    typeof value.in_window === "boolean" &&
    nullableNumber(value.points) &&
    nullableNumber(value.td_points) &&
    nullableNumber(value.opportunity) &&
    nullableNumber(value.share) &&
    nullableInt(1)(value.rank)
  );
}

function isWithWithoutRow(value: unknown): boolean {
  return (
    isObject(value) &&
    isGsis(value.player_id) &&
    isText(value.name) &&
    isOneOf(value.position, POSITIONS) &&
    nullableNumber(value.share_with) &&
    isInt(value.games_with, 0) &&
    nullableNumber(value.share_without) &&
    isInt(value.games_without, 0) &&
    nullableNumber(value.latest_share)
  );
}

function isRoomRow(value: unknown): boolean {
  return (
    isObject(value) &&
    isGsis(value.player_id) &&
    isText(value.name) &&
    isOneOf(value.position, POSITIONS) &&
    isInt(value.window_games, 0) &&
    isInt(value.baseline_games, 0) &&
    nullableNumber(value.snap_share) &&
    nullableNumber(value.snap_share_baseline) &&
    isInt(value.count, 0) &&
    nullableNumber(value.share) &&
    nullableNumber(value.share_baseline) &&
    nullableInt(0)(value.red_zone) &&
    nullableInt(0)(value.inside_five)
  );
}

function isChart(value: unknown): boolean {
  if (!isObject(value)) return false;
  switch (value.type) {
    case "week_strip":
      return (
        every(value.weeks, isStripWeek, 1, 18) &&
        isText(value.opportunity_label) &&
        orNull(isString)(value.share_label) &&
        nullableInt(1)(value.band)
      );
    case "interval":
      return (
        isNumber(value.q10) &&
        isNumber(value.q50) &&
        isNumber(value.q90) &&
        nullableNumber(value.typical_q10) &&
        nullableNumber(value.typical_q50) &&
        nullableNumber(value.typical_q90)
      );
    case "with_without": {
      const absent = value.absent;
      return (
        isOneOf(value.metric, ["target_share", "carry_share", "pass_share"] as const) &&
        isObject(absent) &&
        isGsis(absent.player_id) &&
        isText(absent.name) &&
        isOneOf(absent.position, POSITIONS) &&
        isNumber(absent.share) &&
        isInt(absent.games, 1) &&
        isNumber(absent.per_game) &&
        isText(absent.reason) &&
        every(value.rows, isWithWithoutRow, 1, 4)
      );
    }
    case "room":
      return (
        isOneOf(value.room, ["backfield", "receiving"] as const) &&
        isOneOf(value.metric, ["carries", "targets"] as const) &&
        isInt(value.team_count, 1) &&
        isInt(value.team_games, 1) &&
        nullableInt(0)(value.team_red_zone) &&
        nullableInt(0)(value.team_inside_five) &&
        every(value.rows, isRoomRow, 2, 5)
      );
    case "stat_line":
      return (
        isInt(value.games, 1) &&
        isInt(value.team_games, 1) &&
        isNumber(value.points) &&
        isNumber(value.points_per_game) &&
        isNumber(value.pace_17) &&
        isInt(value.ppg_rank, 1) &&
        nullableInt(1)(value.total_rank) &&
        isInt(value.cohort_size, 1) &&
        isInt(value.cohort_min_games, 1)
      );
    default:
      return false;
  }
}

function isCeilingRanks(value: unknown): boolean {
  return (
    isObject(value) &&
    Object.keys(value).length === 3 &&
    ["50", "25", "10"].every((key) => key in value && nullableInt(1)(value[key]))
  );
}

function isInjury(value: unknown): boolean {
  return (
    isObject(value) &&
    isInt(value.week, 1) &&
    (value.designation === null || isOneOf(value.designation, ["Out", "Doubtful", "Questionable"] as const)) &&
    orNull(isString)(value.practice_status) &&
    orNull(isString)(value.primary_injury)
  );
}

function isSourceTimes(value: unknown): boolean {
  if (!isObject(value)) return false;
  for (const [key, entry] of Object.entries(value)) {
    if (key === "espn_observed_at_utc" || key === "lines_retrieved_at_utc") {
      if (!(entry === null || isTime(entry))) return false;
    } else if (key === "injury_report_final") {
      if (!(entry === null || typeof entry === "boolean")) return false;
    } else {
      return false;
    }
  }
  return true;
}

/**
 * One story, or null when the row is not a story this page can render faithfully.
 *
 * The check is the contract's (`schemas/insight_story.schema.json`) wherever a wrong value would
 * reach the reader: every enum, every id and edition pattern, every nullable number, the facts'
 * bases and the chart's shape. A served feed row carries no `schema_version`, `evidence`,
 * `qualification` or `also_qualifies` (they are the evidence slice's); a whole-artifact record
 * carries all of them, and each is then checked too. A rejected row is skipped and counted,
 * never half-drawn.
 */
export function parseInsightStory(raw: unknown): InsightStory | null {
  if (!isObject(raw)) return null;
  const row = raw;
  if (row.schema_version !== undefined && !(isString(row.schema_version) && row.schema_version.split(".")[0] === "1")) {
    return null;
  }
  const valid =
    isText(row.build_id) &&
    isInt(row.season, 2000) &&
    isInt(row.through_week, 1) &&
    nullableInt(1)(row.target_week) &&
    isString(row.edition) &&
    EDITION.test(row.edition) &&
    isOneOf(row.scoring_preset, PRESETS) &&
    typeof row.scoring_dependent === "boolean" &&
    isString(row.story_id) &&
    row.story_id.length <= 64 &&
    STORY_ID.test(row.story_id) &&
    isOneOf(row.family, FAMILIES) &&
    isOneOf(row.variant, VARIANTS) &&
    isOneOf(row.horizon, HORIZONS) &&
    isOneOf(row.nature, ["fact", "thesis"] as const) &&
    (row.lead_rank === null || (isInt(row.lead_rank, 1) && row.lead_rank <= 12)) &&
    isInt(row.family_rank, 1) &&
    isGsis(row.player_id) &&
    isText(row.display_name) &&
    isOneOf(row.position, POSITIONS) &&
    orNull(isString)(row.team) &&
    isText(row.headline) &&
    isText(row.dek) &&
    every(row.facts, isFact, 2, 4) &&
    orNull(isText)(row.counterpoint) &&
    isText(row.caveat) &&
    orNull(isWindow)(row.window) &&
    orNull(isTime)(row.kickoff_utc) &&
    (row.espn_rostered === null || (isNumber(row.espn_rostered) && row.espn_rostered >= 0 && row.espn_rostered <= 100)) &&
    orNull(isCeilingRanks)(row.ceiling_ranks) &&
    orNull(isInjury)(row.injury) &&
    orNull(isString)(row.opponent) &&
    (row.home_away === null || isOneOf(row.home_away, ["home", "away"] as const)) &&
    isChart(row.chart) &&
    every(row.sources, (source) => isOneOf(source, SOURCES), 1) &&
    isSourceTimes(row.source_times) &&
    (row.evidence === undefined || isObject(row.evidence)) &&
    (row.qualification === undefined || every(row.qualification, isPredicate, 1)) &&
    (row.also_qualifies === undefined || every(row.also_qualifies, (id) => isString(id) && STORY_ID.test(id)));
  return valid ? (row as unknown as InsightStory) : null;
}

/** One story's evidence row, or null when it is not one this page can print faithfully. */
export function parseInsightEvidence(raw: unknown): InsightEvidence | null {
  if (!isObject(raw)) return null;
  const valid =
    isOneOf(raw.scoring_preset, PRESETS) &&
    isString(raw.story_id) &&
    STORY_ID.test(raw.story_id) &&
    isGsis(raw.player_id) &&
    isObject(raw.evidence) &&
    every(raw.qualification, isPredicate, 1) &&
    every(raw.also_qualifies, (id) => isString(id) && STORY_ID.test(id));
  return valid ? (raw as unknown as InsightEvidence) : null;
}

/** An evidence slice by story id; a malformed row is left out (its story says so). */
export function evidenceByStory(rows: readonly unknown[]): ReadonlyMap<string, InsightEvidence> {
  const out = new Map<string, InsightEvidence>();
  for (const row of rows) {
    const evidence = parseInsightEvidence(row);
    if (evidence !== null && !out.has(evidence.story_id)) out.set(evidence.story_id, evidence);
  }
  return out;
}

/** Every row of a slice: the stories that parse, in slice order, and how many did not. */
export function parseInsightStories(rows: readonly unknown[]): {
  readonly stories: readonly InsightStory[];
  readonly rejected: number;
} {
  const stories: InsightStory[] = [];
  const seen = new Set<string>();
  let rejected = 0;
  for (const row of rows) {
    const story = parseInsightStory(row);
    // A story id is unique within a preset; a second row with the same id is not a story.
    const key = story === null ? "" : `${story.scoring_preset}|${story.story_id}`;
    if (story === null || seen.has(key)) {
      rejected += 1;
      continue;
    }
    seen.add(key);
    stories.push(story);
  }
  return { stories, rejected };
}

function isFamilyStatus(value: unknown): boolean {
  return (
    isObject(value) &&
    isOneOf(value.status, ["published", "empty", "unavailable"] as const) &&
    orNull(isString)(value.reason) &&
    isObject(value.qualified) &&
    isObject(value.published) &&
    isObject(value.suppressed)
  );
}

/**
 * The build's account of Insights, or null when it is absent or not one this page can read
 * (which is the same unavailable state). `raw` is the manifest's summary
 * (`ros_build_metadata.insights`: status, edition and times); `full` is the stories slice's
 * `meta`, which adds the family states, counts, rule, definitions, limitations and unsupported
 * claims — a published build serves that slice for every preset, empty when no story
 * qualified. The parts the page prints are checked; missing parts take neutral defaults, never
 * invented values.
 */
export function parseInsightsMetadata(raw: unknown, full: unknown = null): InsightsMetadata | null {
  if (!isObject(raw)) return null;
  if (isObject(full)) raw = { ...raw, ...full };
  if (!isObject(raw)) return null;
  const valid =
    isOneOf(raw.status, ["published", "withheld"] as const) &&
    orNull(isString)(raw.withheld_reason) &&
    isString(raw.edition) &&
    EDITION.test(raw.edition) &&
    (raw.season === undefined || isInt(raw.season, 2000)) &&
    isInt(raw.through_week, 1) &&
    nullableInt(1)(raw.target_week) &&
    isTime(raw.generated_at_utc) &&
    (raw.families === undefined || (isObject(raw.families) && Object.values(raw.families).every(isFamilyStatus))) &&
    (raw.definitions === undefined || isObject(raw.definitions)) &&
    (raw.limitations === undefined || every(raw.limitations, isString)) &&
    (raw.unsupported === undefined ||
      every(raw.unsupported, (item) => isObject(item) && isString(item.claim) && isString(item.reason)));
  if (!valid) return null;
  const meta = raw as unknown as Partial<InsightsMetadata>;
  const selection = isObject(raw.selection) && every(raw.selection.family_order, isString) ? meta.selection : undefined;
  return {
    ...(raw as unknown as InsightsMetadata),
    rule_version: isString(raw.rule_version) ? raw.rule_version : "insights_v1",
    selection_rule_version: isString(raw.selection_rule_version) ? raw.selection_rule_version : "insights_select_v1",
    families: isObject(raw.families) ? (meta.families ?? {}) : {},
    rule: isObject(raw.rule) ? raw.rule : {},
    selection: selection ?? { lead_max: 12, family_order: FAMILIES, family_caps: {}, team_cap: 2, one_story_per_player: true },
    sources: isObject(raw.sources) ? (meta.sources ?? {}) : {},
    counts: isObject(raw.counts) ? (meta.counts ?? {}) : {},
    definitions: meta.definitions ?? {},
    limitations: meta.limitations ?? [],
    unsupported: meta.unsupported ?? [],
    window: isObject(raw.window) ? (meta.window ?? null) : null,
  };
}

// ------------------------------------------------------------------------- availability

/** Whether the build's Insights can be shown at all, and why not when they cannot. */
export type InsightsState =
  | { readonly kind: "absent"; readonly reason: string }
  | { readonly kind: "incompatible"; readonly reason: string }
  | { readonly kind: "withheld"; readonly reason: string; readonly meta: InsightsMetadata }
  | { readonly kind: "published"; readonly meta: InsightsMetadata };

export const INSIGHTS_NOT_PUBLISHED =
  "This build published no Insights. Stories are written from a completed week's published evidence; every other in-season tab is unaffected.";

export function insightsState(source: {
  readonly published: boolean;
  readonly compatible: boolean;
  /** The manifest's summary. */
  readonly meta: unknown;
  /** The loaded stories slice's full account, when there is one. */
  readonly fullMeta?: unknown;
}): InsightsState {
  const meta = parseInsightsMetadata(source.meta, source.fullMeta ?? null);
  if (meta !== null && meta.status === "withheld") {
    return {
      kind: "withheld",
      meta,
      reason:
        meta.withheld_reason === null || meta.withheld_reason.trim() === ""
          ? "This build withheld its Insights."
          : `This build withheld its Insights: ${meta.withheld_reason.replace(/\.$/, "")}.`,
    };
  }
  if (meta === null || !source.published) return { kind: "absent", reason: INSIGHTS_NOT_PUBLISHED };
  if (!source.compatible) {
    return {
      kind: "incompatible",
      reason: "This build's Insights use a contract version this page cannot read, so none is shown.",
    };
  }
  return { kind: "published", meta };
}

// ----------------------------------------------------------------------------- labels

export const FAMILY_LABELS: Readonly<Record<InsightFamily, string>> = {
  volume_vs_results: "Volume vs results",
  weekly_upside: "This week's upside",
  opportunity_opening: "Opportunity opening",
  role_battle: "Role battle",
  streak_watch: "Streak watch",
  pace_perspective: "Pace perspective",
};

export const VARIANT_LABELS: Readonly<Record<InsightVariant, string>> = {
  lagging: "Workload ahead of results",
  shrinking: "Shrinking workload",
  ceiling: "Ceiling",
  observed: "Seen without him",
  prospective: "Before a first game without him",
  backfield: "Backfield",
  receiving: "Receiving room",
  breakout: "Breakout",
  production_without_role: "Points ahead of role",
  quiet_role_growth: "Quiet role growth",
  per_game_hidden: "Per-game standing hidden",
  overlooked: "Overlooked",
};

export const BASIS_LABELS: Readonly<Record<InsightBasis, string>> = {
  observed: "Observed",
  model: "Model",
  market: "ESPN",
};

/** What each basis tag means, for its accessible description and the legend. */
export const BASIS_DESCRIPTIONS: Readonly<Record<InsightBasis, string>> = {
  observed: "an observed nflverse statistic",
  model: "a published model output",
  market: "ESPN's public roster share",
};

export const FILTER_LABELS: Readonly<Record<InsightFilter, string>> = {
  all: "All",
  week: "This week",
  disappoint: "Volume vs results",
  opening: "Openings",
  roles: "Role battles",
  streaks: "Streaks",
  pace: "Pace",
};

const FILTER_FAMILY: Readonly<Partial<Record<InsightFilter, InsightFamily>>> = {
  disappoint: "volume_vs_results",
  opening: "opportunity_opening",
  roles: "role_battle",
  streaks: "streak_watch",
  pace: "pace_perspective",
};

const PRESET_VALUE: Readonly<Record<ScoringPreset, ScoringValue>> = { STD: "std", HALF: "half", PPR: "ppr" };
const PRESET_LABEL: Readonly<Record<ScoringPreset, string>> = { STD: "Standard", HALF: "Half PPR", PPR: "PPR" };

/** `2026w07` → 7, or null for anything else. */
export function editionWeek(edition: string): number | null {
  const match = EDITION.exec(edition);
  return match === null ? null : Number(match[2]);
}

/** `2026w07` → `Week 7`. The edition is the completed week its stories run through. */
export function editionLabel(edition: string): string {
  const week = editionWeek(edition);
  return week === null ? edition : `Week ${String(week)}`;
}

export function horizonLabel(story: Pick<InsightStory, "horizon" | "target_week" | "through_week">): string {
  const target = story.target_week === null ? null : `Week ${String(story.target_week)}`;
  switch (story.horizon) {
    case "this_week":
      return target ?? "This week";
    case "stash":
      return target === null ? "Stash · bye week" : `Stash · bye in ${target}`;
    case "role_watch":
      return "Role watch";
    case "season_view":
      return `Through Week ${String(story.through_week)}`;
  }
}

/** `This week's upside · Week 8`: the family and the horizon, the card's first line. */
export function kicker(story: InsightStory): string {
  return `${FAMILY_LABELS[story.family]} · ${horizonLabel(story)}`;
}

/** The scoring a story's numbers are in, or that none of them depend on scoring. */
export function scoringLabel(story: Pick<InsightStory, "scoring_dependent" | "scoring_preset">): string {
  return story.scoring_dependent ? `${PRESET_LABEL[story.scoring_preset]} scoring` : "Same in every scoring";
}

/** `Last 3 weeks · W6–W8, baseline W1–W5`, or the week the story is about. */
export function windowText(story: InsightStory): string {
  const window = story.window;
  if (window === null) {
    return story.target_week === null
      ? `Through Week ${String(story.through_week)}`
      : `Week ${String(story.target_week)} model distribution`;
  }
  const span =
    window.first_week === window.last_week
      ? `W${String(window.first_week)}`
      : `W${String(window.first_week)}–W${String(window.last_week)}`;
  const label = window.label.includes(`W${String(window.first_week)}`) ? window.label : `${window.label} · ${span}`;
  if (window.baseline_first_week === null || window.baseline_last_week === null) return label;
  const baseline =
    window.baseline_first_week === window.baseline_last_week
      ? `W${String(window.baseline_first_week)}`
      : `W${String(window.baseline_first_week)}–W${String(window.baseline_last_week)}`;
  return `${label}, baseline ${baseline}`;
}

const SOURCE_LABELS: Readonly<Record<string, string>> = {
  nflverse_player_stats: "nflverse (CC-BY 4.0)",
  nflverse_snap_counts: "nflverse (CC-BY 4.0)",
  nflverse_pbp: "nflverse (CC-BY 4.0)",
  nflverse_schedule: "nflverse (CC-BY 4.0)",
  nflverse_injuries: "nflverse (CC-BY 4.0)",
  weekly_startsit_v1: "weekly-startsit-v1 model",
  espn_fantasy_ownership: "ESPN roster % (espn.com)",
};

/** The attribution a story's sources need, each once, in a fixed order. */
export function sourceLabels(story: Pick<InsightStory, "sources">): readonly string[] {
  const out: string[] = [];
  for (const source of SOURCES) {
    if (!story.sources.includes(source)) continue;
    const label = SOURCE_LABELS[source] ?? source;
    if (!out.includes(label)) out.push(label);
  }
  return out;
}

const KICKOFF_FORMAT = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** `Sun, Nov 8, 1:00 PM ET`, or null when the story names no kickoff. */
export function kickoffText(iso: string | null): string | null {
  if (iso === null) return null;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return null;
  return `${KICKOFF_FORMAT.format(new Date(parsed))} ET`;
}

/** `vs DAL` / `at DAL`, for a this-week story that names its opponent; else null. */
export function opponentText(story: Pick<InsightStory, "opponent" | "home_away">): string | null {
  if (story.opponent === null || story.opponent === "") return null;
  return `${story.home_away === "away" ? "at" : "vs"} ${story.opponent}`;
}

/** `WR · LAR · at BAL · Sun, Nov 8, 1:00 PM ET`: the card's line under the name. */
export function playerContext(story: InsightStory): readonly string[] {
  const parts: string[] = [story.position, story.team ?? "FA"];
  if (story.horizon === "this_week") {
    const opponent = opponentText(story);
    if (opponent !== null) parts.push(opponent);
    const kickoff = kickoffText(story.kickoff_utc);
    if (kickoff !== null) parts.push(opponent === null ? `kickoff ${kickoff}` : kickoff);
  }
  return parts;
}

/** The edition line: `Week 7 edition · through W7 · built Oct 27 · 6:00 AM ET`. */
export function editionLine(meta: Pick<InsightsMetadata, "edition" | "through_week" | "generated_at_utc">): string {
  return `${editionLabel(meta.edition)} edition · through W${String(meta.through_week)} · built ${formatEastern(meta.generated_at_utc)}`;
}

/** How old the edition is at the reader's clock, and whether that is stale (`data/freshness`). */
export function editionAge(generatedAt: string, now: number): { readonly text: string; readonly stale: boolean } | null {
  const built = Date.parse(generatedAt);
  if (Number.isNaN(built)) return null;
  const hours = Math.max(0, (now - built) / 3_600_000);
  return { text: formatAge(hours), stale: hours > STALE_WARNING_HOURS };
}

// ----------------------------------------------------------------------- the feed

/** A weekly-upside story's rank within his position under an ESPN ceiling, or null. */
export function ceilingRank(story: Pick<InsightStory, "ceiling_ranks">, ceiling: InsightCeiling): number | null {
  return story.ceiling_ranks?.[String(ceiling) as "50" | "25" | "10"] ?? null;
}

export function matchesFilter(story: InsightStory, filter: InsightFilter): boolean {
  if (filter === "all") return true;
  if (filter === "week") return story.family === "weekly_upside" || story.horizon === "this_week";
  return story.family === FILTER_FAMILY[filter];
}

/** Whether the ESPN ceiling keeps a story: it reads the upside family only. */
export function passesCeiling(story: InsightStory, ceiling: InsightCeiling): boolean {
  return story.family !== "weekly_upside" || ceilingRank(story, ceiling) !== null;
}

export interface FeedOptions {
  readonly ins: InsightFilter;
  readonly ceil: InsightCeiling;
  readonly search: string;
  readonly position: PositionFilter;
  /** A story shown on its own above the feed (a linked story), left out of the lists. */
  readonly exclude?: string | undefined;
  /** The build's family order (`selection.family_order`), for "More findings". */
  readonly familyOrder?: readonly string[] | undefined;
}

export interface Feed {
  /** Lead stories, in `lead_rank` order. */
  readonly lead: readonly InsightStory[];
  /** Every other qualified story, by family, then the family's own order. */
  readonly more: readonly InsightStory[];
  /** Stories each filter would show under the other settings, for the filter's labels. */
  readonly counts: Readonly<Record<InsightFilter, number>>;
  /** Upside stories the ESPN ceiling hides under the current filter. */
  readonly hiddenByCeiling: number;
}

/** Upside interleaves positions in this order inside the family (`insights_select_v1`). */
const UPSIDE_POSITIONS = ["WR", "RB", "TE", "QB"];

function familyIndex(family: string, order: readonly string[]): number {
  const index = order.indexOf(family);
  return index === -1 ? order.length + FAMILIES.indexOf(family as InsightFamily) : index;
}

/**
 * What the feed shows, and in what order. Deterministic for a given set of stories and options:
 * the lead is the build's lead order; the rest are by family (the build's family order), then —
 * for the upside family — by rank under the ESPN ceiling with positions interleaved (WR, RB, TE,
 * QB), else by variant and the family's own rank.
 */
export function selectFeed(stories: readonly InsightStory[], options: FeedOptions): Feed {
  const order = options.familyOrder ?? FAMILIES;
  const base = stories.filter(
    (story) =>
      story.story_id !== options.exclude &&
      matchesPosition(story.position, options.position) &&
      matchesSearch(story, options.search),
  );
  const counts = {} as Record<InsightFilter, number>;
  for (const filter of ["all", "week", "disappoint", "opening", "roles", "streaks", "pace"] as const) {
    counts[filter] = base.filter((story) => matchesFilter(story, filter) && passesCeiling(story, options.ceil)).length;
  }
  const filtered = base.filter((story) => matchesFilter(story, options.ins));
  const shown = filtered.filter((story) => passesCeiling(story, options.ceil));
  const lead = shown
    .filter((story) => story.lead_rank !== null)
    .sort((a, b) => (a.lead_rank ?? 0) - (b.lead_rank ?? 0) || a.story_id.localeCompare(b.story_id));
  const more = shown
    .filter((story) => story.lead_rank === null)
    .sort((a, b) => {
      const byFamily = familyIndex(a.family, order) - familyIndex(b.family, order);
      if (byFamily !== 0) return byFamily;
      if (a.family === "weekly_upside" && b.family === "weekly_upside") {
        // Positions interleaved: every position's first under this ceiling, then every second.
        const byRank = (ceilingRank(a, options.ceil) ?? 999) - (ceilingRank(b, options.ceil) ?? 999);
        if (byRank !== 0) return byRank;
        const byPosition = UPSIDE_POSITIONS.indexOf(a.position) - UPSIDE_POSITIONS.indexOf(b.position);
        if (byPosition !== 0) return byPosition;
      } else {
        const byVariant = VARIANTS.indexOf(a.variant) - VARIANTS.indexOf(b.variant);
        if (byVariant !== 0) return byVariant;
        const byRank = a.family_rank - b.family_rank;
        if (byRank !== 0) return byRank;
      }
      return a.story_id.localeCompare(b.story_id);
    });
  return { lead, more, counts, hiddenByCeiling: filtered.length - shown.length };
}

// ------------------------------------------------------------------------- withdrawal

export const KICKOFF_PASSED = "Kickoff passed — no longer a start idea.";

/** A story's standing at the reader's clock. Only a `this_week` story is ever withdrawn. */
export interface StoryStanding {
  readonly withdrawn: boolean;
  /** Why it was withdrawn, in the policy's words or the kickoff's; null when it was not. */
  readonly reason: string | null;
  /** The availability policy's reading, when the page holds one. */
  readonly availability: Availability | null;
}

/** The official report a story carries for its focal player, in the weekly record's shape. */
export function storyReport(story: Pick<InsightStory, "injury">): WeeklyProjectionRecord["injury"] {
  return story.injury;
}

/**
 * Whether a `this_week` story still stands as a start idea. Kickoff decides first — a page left
 * open across it withdraws the story in place — then the shared availability policy: a player
 * the policy would not feature (out, doubtful, on a reserve list, inactive, unsigned) is shown
 * withdrawn with the policy's reason, never silently dropped. Questionable and uncertain stay.
 */
export function storyStanding(story: InsightStory, now: number, availability: Availability | null): StoryStanding {
  if (story.horizon !== "this_week") return { withdrawn: false, reason: null, availability };
  const kickoff = story.kickoff_utc === null ? Number.NaN : Date.parse(story.kickoff_utc);
  if (Number.isFinite(kickoff) && now >= kickoff) return { withdrawn: true, reason: KICKOFF_PASSED, availability };
  if (availability !== null && !featureable(availability)) {
    return {
      withdrawn: true,
      reason: startExclusion(availability) ?? `${availability.headline} — no longer a start idea.`,
      availability,
    };
  }
  return { withdrawn: false, reason: null, availability };
}

// ------------------------------------------------------------------- links and summaries

/**
 * The story's shareable address: the site's own base path, the Insights tab, the preset, the
 * story and its edition. Never a league, a roster, a saved preference or another tab's state.
 */
export function storyLink(
  origin: string,
  base: string,
  story: Pick<InsightStory, "story_id" | "edition" | "scoring_preset">,
): string {
  const root = base.endsWith("/") ? base : `${base}/`;
  const params = new URLSearchParams();
  params.set("view", "insights");
  params.set("scoring", PRESET_VALUE[story.scoring_preset]);
  params.set("story", story.story_id);
  params.set("ed", story.edition);
  return `${origin}${root}?${params.toString()}`;
}

/** The plain-text summary a reader copies: the story's own words, its caveat and its link. */
export function storySummary(story: InsightStory, link: string, standing?: StoryStanding): string {
  const lines: string[] = [story.headline, `${story.display_name} · ${playerContext(story).join(" · ")}`];
  if (standing?.withdrawn === true && standing.reason !== null) lines.push(`Withdrawn: ${standing.reason}`);
  lines.push("", `Reading: ${story.dek}`, "");
  for (const fact of story.facts) lines.push(`• ${fact.label}: ${fact.value} (${BASIS_LABELS[fact.basis]})`);
  lines.push("");
  if (story.counterpoint !== null) lines.push(`What could undermine it: ${story.counterpoint}`);
  lines.push(`Caveat: ${story.caveat}`);
  lines.push(
    `${windowText(story)} · ${scoringLabel(story)} · ${editionLabel(story.edition)} edition (${story.edition})`,
  );
  lines.push(`Sources: ${sourceLabels(story).join(", ")}`);
  lines.push(`Jeisey Tiers — ${link}`);
  return lines.join("\n");
}

/** A download's filename: `jeisey-tiers-upside-00-0000017-2026w08-landscape.png`. */
export function exportFilename(story: Pick<InsightStory, "story_id" | "edition">, layout: "land" | "port"): string {
  return `jeisey-tiers-${story.story_id}-${story.edition}-${layout === "land" ? "landscape" : "portrait"}.png`;
}

// ---------------------------------------------------------------------- exact values

const EVIDENCE_LABELS: Readonly<Record<string, string>> = {
  ceiling_ranks: "Rank under ESPN ceiling",
  espn_rostered: "ESPN rostered %",
  injury: "Official report",
  opponent: "Opponent",
  home_away: "Home or away",
  matchup_delta_q90: "Matchup effect on the ceiling (pts)",
  terms_q90: "Ceiling terms (pts)",
};

/** `matchup_delta_q90` → `Matchup delta P90`, unless the page has a better name for it. */
export function humanizeKey(key: string): string {
  const known = EVIDENCE_LABELS[key];
  if (known !== undefined) return known;
  const words = key
    .replace(/_/g, " ")
    .replace(/\bq(\d{2})\b/g, "P$1")
    .replace(/\bppg\b/gi, "PPG")
    .replace(/\bespn\b/gi, "ESPN")
    .trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A published value exactly as published: no rounding, `—` for null, never `0` for missing. */
export function formatExact(value: unknown): string {
  if (value === null || value === undefined) return EM_DASH;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : EM_DASH;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value === "" ? EM_DASH : value;
  if (Array.isArray(value)) {
    return value.length === 0 ? "none" : value.map((item) => (isObject(item) ? JSON.stringify(item) : formatExact(item))).join(", ");
  }
  return JSON.stringify(value);
}

/** The evidence as label/value rows, one level of nesting flattened (`Rank under ESPN ceiling · 25`). */
export function evidenceRows(evidence: Readonly<Record<string, unknown>>): readonly (readonly [string, string])[] {
  const rows: (readonly [string, string])[] = [];
  for (const [key, value] of Object.entries(evidence)) {
    if (isObject(value)) {
      const entries = Object.entries(value);
      if (entries.length === 0) rows.push([humanizeKey(key), "none"]);
      for (const [inner, innerValue] of entries) {
        rows.push([`${humanizeKey(key)} · ${humanizeKey(inner)}`, formatExact(innerValue)]);
      }
    } else {
      rows.push([humanizeKey(key), formatExact(value)]);
    }
  }
  return rows;
}

// ------------------------------------------------------------------------ families

/** Family statuses the reader should hear about: unavailable, with the build's own reason. */
export function unavailableFamilies(meta: InsightsMetadata): readonly { readonly family: string; readonly label: string; readonly reason: string }[] {
  const out: { family: string; label: string; reason: string }[] = [];
  const order = meta.selection.family_order.length > 0 ? meta.selection.family_order : FAMILIES;
  const keys = [...new Set([...order, ...Object.keys(meta.families)])];
  for (const family of keys) {
    const status: InsightFamilyStatus | undefined = meta.families[family];
    if (status?.status !== "unavailable") continue;
    out.push({
      family,
      label: FAMILY_LABELS[family as InsightFamily] ?? humanizeKey(family),
      reason: status.reason ?? "not built for this edition",
    });
  }
  return out;
}

/** Every family's state, in the build's order, for the empty edition and the method notes. */
export function familyStates(meta: InsightsMetadata): readonly { readonly family: string; readonly label: string; readonly status: InsightFamilyStatus }[] {
  const order = meta.selection.family_order.length > 0 ? meta.selection.family_order : FAMILIES;
  const keys = [...new Set([...order, ...Object.keys(meta.families)])];
  const out: { family: string; label: string; status: InsightFamilyStatus }[] = [];
  for (const family of keys) {
    const status = meta.families[family];
    if (status === undefined) continue;
    out.push({ family, label: FAMILY_LABELS[family as InsightFamily] ?? humanizeKey(family), status });
  }
  return out;
}

/** The chart's kind, for test ids and the figure's class. */
export function chartKind(chart: InsightChart): InsightChart["type"] {
  return chart.type;
}

/** A share in `0.237` form as `24%`; null as `—`. Display rounding only. */
export function percentText(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

/** Points with one decimal; null as `—`. */
export function pointsText(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return value.toFixed(1);
}
