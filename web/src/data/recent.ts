/**
 * Recent form and breakout categories, read one way everywhere (ADR-113).
 *
 * The build publishes `recent_form_v1`: for the last 1, 2, 3, 4 and 6 completed calendar weeks
 * ending at the cutoff, each player's points, games and positional rank among **every** player
 * who appeared in those weeks — and `breakout_v1`, a descriptive category with its evidence.
 * This module is the only place the site turns those records into words, so the table, the
 * explanation dialog, the status line and the filtered CSV cannot disagree.
 *
 * **Nothing is ranked or classified here.** A window rank, a weekly rank and a category are
 * read from the record; this file never sorts loaded rows into a rank (which would rank the
 * page rather than the league) and never re-decides a badge.
 *
 * **States, never merged.** `ranked` (he appeared in the window), `no_games` (the build knows
 * he did not), `unavailable` (no artifact, a withheld or incompatible one, or no record for
 * him). A category of `insufficient` is "not enough evidence", never "no".
 */

import type { SeasonStanding } from "./actuals";
import type {
  BreakoutCategory,
  BreakoutVerdict,
  Position,
  RecentFormMetadata,
  RecentFormRow,
  RecentWindowKey,
} from "./contracts";
import { RECENT_WINDOW_KEYS } from "./contracts";
import { EM_DASH } from "./format";

/** The lens a reader picks. `season` shows season actuals only, with no comparison. */
export const RECENT_LENSES = ["season", ...RECENT_WINDOW_KEYS] as const;
export type RecentLens = (typeof RECENT_LENSES)[number];
export const DEFAULT_RECENT_LENS: RecentLens = "3";

/** The breakout filter. `all` applies none; `any` keeps the three badges. */
export const BREAKOUT_FILTERS = ["all", "any", "takeover", "sneaking", "eyebrow"] as const;
export type BreakoutFilter = (typeof BREAKOUT_FILTERS)[number];

export type BreakoutBadge = "takeover" | "sneaking" | "eyebrow";
export const BREAKOUT_BADGES: readonly BreakoutBadge[] = ["takeover", "sneaking", "eyebrow"];

export const BREAKOUT_LABELS: Readonly<Record<BreakoutBadge, string>> = {
  takeover: "Takeover",
  sneaking: "Sneaking",
  eyebrow: "Eyebrow",
};

/** A short glyph that carries the category without colour: three, two or one game. */
export const BREAKOUT_GLYPHS: Readonly<Record<BreakoutBadge, string>> = {
  takeover: "▲▲▲",
  sneaking: "▲▲",
  eyebrow: "▲",
};

export const BREAKOUT_FILTER_LABELS: Readonly<Record<BreakoutFilter, string>> = {
  all: "All",
  any: "Any signal",
  takeover: "Takeover",
  sneaking: "Sneaking",
  eyebrow: "Eyebrow",
};

export const LENS_LABELS: Readonly<Record<RecentLens, string>> = {
  season: "Season",
  "1": "Last 1",
  "2": "Last 2",
  "3": "Last 3",
  "4": "Last 4",
  "6": "Last 6",
};

/** Whether this build's recent form can be read at all, and why not when it cannot. */
export type RecentAvailability =
  | { readonly kind: "published"; readonly meta: RecentFormMetadata }
  | { readonly kind: "unavailable"; readonly reason: string };

export const RECENT_NOT_PUBLISHED =
  "This build published no recent-form windows, so only season columns are shown.";

export function recentAvailability(
  metadata: RecentFormMetadata | null | undefined,
  artifactPublished: boolean,
  compatible: boolean,
): RecentAvailability {
  if (metadata === null || metadata === undefined || !artifactPublished) {
    return { kind: "unavailable", reason: RECENT_NOT_PUBLISHED };
  }
  if (!compatible) {
    return {
      kind: "unavailable",
      reason: "This build's recent-form windows use a contract version this page cannot read.",
    };
  }
  if (metadata.status !== "published") {
    return {
      kind: "unavailable",
      reason:
        "Recent-form windows are withheld for this build" +
        (metadata.withheld_reason === null ? "." : `: ${metadata.withheld_reason}.`),
    };
  }
  return { kind: "published", meta: metadata };
}

/** The real weeks behind a window, from the metadata — never assumed from its name. */
export interface WindowSpan {
  readonly key: RecentWindowKey;
  readonly requested: number;
  readonly firstWeek: number | null;
  readonly lastWeek: number | null;
  readonly weeks: number;
}

export function windowSpan(meta: RecentFormMetadata, key: RecentWindowKey): WindowSpan {
  const entry = meta.windows[key];
  return {
    key,
    requested: entry?.requested ?? Number(key),
    firstWeek: entry?.first_week ?? null,
    lastWeek: entry?.last_week ?? null,
    weeks: entry?.weeks ?? 0,
  };
}

/** `W3–W5`, `W5`, and the shortfall when the season is younger than the window: `W1–W2 (2 of 3 wks)`. */
export function formatSpan(span: WindowSpan, short = false): string {
  if (span.firstWeek === null || span.lastWeek === null) return EM_DASH;
  const range =
    span.firstWeek === span.lastWeek
      ? `W${String(span.lastWeek)}`
      : short
        ? `W${String(span.firstWeek)}–${String(span.lastWeek)}`
        : `W${String(span.firstWeek)}–W${String(span.lastWeek)}`;
  return span.weeks < span.requested
    ? `${range} (${String(span.weeks)} of ${String(span.requested)} wks)`
    : range;
}

export type RecentStanding =
  | {
      readonly kind: "ranked";
      readonly position: Position;
      readonly rank: number;
      readonly points: number;
      readonly games: number;
      readonly perGame: number;
      readonly span: WindowSpan;
      readonly verdict: BreakoutVerdict;
      readonly row: RecentFormRow;
    }
  | {
      readonly kind: "no_games";
      readonly position: Position;
      readonly span: WindowSpan;
      readonly verdict: BreakoutVerdict;
      readonly row: RecentFormRow;
    }
  | { readonly kind: "unavailable"; readonly reason: string };

/** One player's standing in one window, from his record (or its absence). */
export function recentStanding(
  row: RecentFormRow | null | undefined,
  key: RecentWindowKey,
  availability: RecentAvailability,
): RecentStanding {
  if (availability.kind !== "published") return { kind: "unavailable", reason: availability.reason };
  if (row === null || row === undefined) {
    return { kind: "unavailable", reason: "No recent-form record is published for this player." };
  }
  const entry = row.windows[key];
  const span = windowSpan(availability.meta, key);
  if (entry.games <= 0 || entry.rank === null || entry.points_per_game === null) {
    return { kind: "no_games", position: row.position, span, verdict: entry.breakout, row };
  }
  return {
    kind: "ranked",
    position: row.position,
    rank: entry.rank,
    points: entry.points,
    games: entry.games,
    perGame: entry.points_per_game,
    span,
    verdict: entry.breakout,
    row,
  };
}

/** The badge he carries in this window, or null. Only the three badge categories count. */
export function badgeOf(standing: RecentStanding | undefined): BreakoutBadge | null {
  if (standing === undefined || standing.kind === "unavailable") return null;
  const category = standing.verdict.category;
  return category === "takeover" || category === "sneaking" || category === "eyebrow"
    ? category
    : null;
}

/** A category state for counting: badge, `none`, `insufficient`, or `unavailable`. */
export function categoryOf(standing: RecentStanding | undefined): BreakoutCategory | "unavailable" {
  if (standing === undefined || standing.kind === "unavailable") return "unavailable";
  return standing.verdict.category;
}

/** Does this standing pass the breakout filter? `all` passes everyone. */
export function passesBreakout(standing: RecentStanding | undefined, filter: BreakoutFilter): boolean {
  if (filter === "all") return true;
  const badge = badgeOf(standing);
  if (badge === null) return false;
  return filter === "any" || filter === badge;
}

/**
 * Season rank minus recent rank, in places: positive when the recent rank is the better place.
 * Null when either is missing — no appearance in the window is not a gap of zero.
 */
export function recentVsSeasonPlaces(
  season: SeasonStanding | undefined,
  recent: RecentStanding | undefined,
): number | null {
  if (season?.kind !== "ranked" || recent?.kind !== "ranked") return null;
  return season.rank - recent.rank;
}

/** `+12`, `−4` with a real minus sign, `0`, or an em dash. */
export function formatPlaces(places: number | null): string {
  if (places === null) return EM_DASH;
  if (places === 0) return "0";
  return places > 0 ? `+${String(places)}` : `−${String(Math.abs(places))}`;
}

export function describeRecentVsSeason(places: number | null, span: string): string {
  if (places === null) return `No gap: no season rank or no game in ${span}`;
  if (places === 0) return `Rank in ${span} equals season rank`;
  const count = Math.abs(places);
  return `Rank in ${span} is ${String(count)} place${count === 1 ? "" : "s"} ${places > 0 ? "better" : "worse"} than season rank`;
}

/** One decimal, a real minus sign, never "-0.0". */
export function formatPoints(value: number): string {
  const text = Math.abs(value).toFixed(1);
  return value < 0 && Number(text) !== 0 ? `−${text}` : text;
}

export function formatRecentRank(standing: RecentStanding | undefined): string {
  return standing?.kind === "ranked" ? `${standing.position}${String(standing.rank)}` : EM_DASH;
}

/** The compact detail under a recent rank: `12.7/g · 3g`, or why there is no rank. */
export function recentDetail(standing: RecentStanding | undefined): string {
  // Short on purpose: the cell's title and screen-reader sentence carry the reason.
  if (standing === undefined || standing.kind === "unavailable") return "";
  if (standing.kind === "no_games") return "0g";
  return `${formatPoints(standing.perGame)}/g · ${String(standing.games)}g`;
}

/** The accessible sentence for a recent-rank cell. */
export function recentSentence(standing: RecentStanding | undefined): string {
  if (standing === undefined) return "No recent form";
  if (standing.kind === "unavailable") return standing.reason;
  const span = formatSpan(standing.span);
  if (standing.kind === "no_games") return `No appearance in ${span}`;
  return (
    `${standing.position}${String(standing.rank)} in ${span}: ${formatPoints(standing.points)} ` +
    `points in ${String(standing.games)} game${standing.games === 1 ? "" : "s"}, ` +
    `${formatPoints(standing.perGame)} per game`
  );
}

/** Sort keys: undefined sorts last in both directions. */
export function recentPointsSortKey(standing: RecentStanding | undefined): number | undefined {
  if (standing?.kind === "ranked") return standing.points;
  return standing?.kind === "no_games" ? 0 : undefined;
}

/** The badge chip's accessible name: the category and its one-line meaning. */
export function badgeAccessibleName(badge: BreakoutBadge, span: WindowSpan): string {
  const meaning =
    badge === "eyebrow" ? "one-game watch" : badge === "sneaking" ? "two-game emergence" : "three-game run with role";
  return `${BREAKOUT_LABELS[badge]} in ${formatSpan(span)}: ${meaning}. Show evidence`;
}

// ------------------------------------------------------------------------------------ CSV

/** The filtered export's recent columns (ADR-113), after every existing column. */
export const RECENT_CSV_COLUMNS = [
  "recent_window",
  "recent_first_week",
  "recent_last_week",
  "recent_weeks",
  "recent_position_rank",
  "recent_points",
  "recent_games_played",
  "recent_points_per_game",
  "recent_vs_season_places",
  "breakout_category",
  "breakout_reason",
  "breakout_rule_version",
  "breakout_games_weeks",
  "breakout_role_passed",
] as const;

export function recentCsvCells(
  lens: RecentLens,
  standing: RecentStanding | undefined,
  season: SeasonStanding | undefined,
  meta: RecentFormMetadata | null,
): readonly (string | number | null)[] {
  if (lens === "season") {
    return ["season", null, null, null, null, null, null, null, null, null, null, null, null, null];
  }
  if (standing === undefined || standing.kind === "unavailable") {
    return [lens, null, null, null, null, null, null, null, null, "unavailable", null, null, null, null];
  }
  const { span, verdict } = standing;
  const passed = (verdict.role ?? [])
    .filter((reading) => reading.passed !== null)
    .map((reading) => `${reading.metric}:${reading.passed ?? ""}`)
    .join("|");
  return [
    lens,
    span.firstWeek,
    span.lastWeek,
    span.weeks,
    standing.kind === "ranked" ? standing.rank : null,
    standing.kind === "ranked" ? standing.points : 0,
    standing.kind === "ranked" ? standing.games : 0,
    standing.kind === "ranked" ? standing.perGame : null,
    recentVsSeasonPlaces(season, standing),
    verdict.category,
    verdict.reason,
    meta?.breakout_rule.version ?? null,
    verdict.games.join("|"),
    passed === "" ? null : passed,
  ];
}

/** Counts for the status line: badges and the missing-evidence states, kept apart. */
export interface BreakoutCensus {
  readonly takeover: number;
  readonly sneaking: number;
  readonly eyebrow: number;
  readonly none: number;
  readonly insufficient: number;
  readonly unavailable: number;
}

export function breakoutCensus(standings: readonly (RecentStanding | undefined)[]): BreakoutCensus {
  const census = { takeover: 0, sneaking: 0, eyebrow: 0, none: 0, insufficient: 0, unavailable: 0 };
  for (const standing of standings) census[categoryOf(standing)] += 1;
  return census;
}
