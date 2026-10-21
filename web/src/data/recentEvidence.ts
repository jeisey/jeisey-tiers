/**
 * The words behind a breakout badge (ADR-113): every number the category rests on, in
 * sentences, from the artifact. Loaded with the evidence dialog only, so a visit that never
 * opens one never downloads this text.
 */

import type { SeasonStanding } from "./actuals";
import type {
  BreakoutCategory,
  BreakoutReason,
  BreakoutRoleReading,
  Position,
  RecentFormMetadata,
  RecentFormRow,
} from "./contracts";
import {
  formatPlaces,
  formatPoints,
  formatSpan,
  recentVsSeasonPlaces,
  type RecentStanding,
  type WindowSpan,
} from "./recent";

const METRIC_LABELS: Readonly<Record<string, string>> = {
  snap_share: "snap share",
  target_share: "target share",
  carry_share: "carry share",
  pass_attempts: "pass attempts per game",
};

function formatMeasure(metric: string, value: number): string {
  return metric === "pass_attempts" ? value.toFixed(1) : `${(value * 100).toFixed(1)}%`;
}

/** One role reading in words, with the threshold it was held to. */
export function roleReadingText(
  reading: BreakoutRoleReading,
  meta: RecentFormMetadata,
  position: Position,
): string {
  const label = METRIC_LABELS[reading.metric] ?? reading.metric;
  const spec = (meta.breakout_rule.measures[position] ?? []).find(
    (measure) => measure.metric === reading.metric,
  );
  const over = `over ${String(reading.games)} game${reading.games === 1 ? "" : "s"}`;
  if (reading.level === null) return `${label}: not available for every evidence game`;
  const level = formatMeasure(reading.metric, reading.level);
  const baseline =
    reading.baseline === null
      ? "no pre-window baseline"
      : `${formatMeasure(reading.metric, reading.baseline)} before the window (${String(reading.baseline_games)} games)`;
  const threshold =
    spec === undefined
      ? ""
      : reading.passed === "substantial"
        ? ` — passes: at least ${formatMeasure(reading.metric, spec.substantial)}`
        : reading.passed === "increase" && spec.emerging !== null && spec.increase !== null
          ? ` — passes: at least ${formatMeasure(reading.metric, spec.emerging)} and up ${formatMeasure(reading.metric, spec.increase)} or more`
          : ` — below ${formatMeasure(reading.metric, spec.substantial)}${
              spec.emerging !== null && spec.increase !== null
                ? ` (or ${formatMeasure(reading.metric, spec.emerging)} with a rise of ${formatMeasure(reading.metric, spec.increase)})`
                : ""
            }`;
  return `${label} ${level} ${over}; ${baseline}${threshold}`;
}

const REASON_TEXT: Readonly<Record<BreakoutReason, string>> = {
  no_games: "No appearance in this window, so there is no recent rank to compare.",
  outside_band: "The recent rank is outside the position's band.",
  no_baseline:
    "Too few games before the window for the season rank to be a baseline, so no category is stated.",
  not_improved: "The recent rank is not better than the season rank.",
  gain_too_small: "The rise is smaller than the rule's minimum (places and percentage).",
  stale: "He missed a team game after his latest appearance, so the run is not current.",
  latest_not_strong: "His latest appearance was not a top-band weekly finish.",
  role_unavailable:
    "His production qualifies, but the role facts needed to confirm it are missing for an evidence game, so no category is stated.",
  role_not_confirmed:
    "Two or more strong weeks, but no role measure confirms a substantial or clearly increased role: a one-game watch.",
  one_strong: "His latest appearance was strong; earlier games do not establish a pattern: a one-game watch.",
  takeover_role: "Three consecutive strong appearances with a confirmed role.",
  sneaking_role: "His two most recent appearances are strong with a confirmed role.",
};

export function reasonText(reason: BreakoutReason): string {
  return REASON_TEXT[reason];
}

/** The plain statement of what a category means, from the build's own definitions. */
export function categoryDefinition(meta: RecentFormMetadata, category: BreakoutCategory): string {
  return meta.definitions[category] ?? "";
}

export interface BreakoutExplanation {
  readonly headline: string;
  readonly lines: readonly string[];
  readonly footnote: string;
}

function weekLabel(meta: RecentFormMetadata, row: RecentFormRow, week: number): string {
  const index = meta.span_weeks.indexOf(week);
  const rank = index >= 0 ? row.span_ranks[index] : null;
  const points = index >= 0 ? row.span_points[index] : null;
  return rank === null || rank === undefined || points === null || points === undefined
    ? `W${String(week)}`
    : `W${String(week)} ${row.position}${String(rank)} (${formatPoints(points)})`;
}

/** The span weeks, one token each: `W3 TE5 (14.2)`, `W4 bye`, `W5 did not play`. */
export function spanText(meta: RecentFormMetadata, row: RecentFormRow, span: WindowSpan): string {
  const tokens: string[] = [];
  meta.span_weeks.forEach((week, index) => {
    if (span.firstWeek === null || week < span.firstWeek) return;
    const code = row.span_status[index];
    if (code === "P") tokens.push(weekLabel(meta, row, week));
    else tokens.push(`W${String(week)} ${code === "B" ? "bye" : "did not play"}`);
  });
  return tokens.join(" · ");
}

/**
 * Every number a badge rests on, in sentences, from the artifact: the rank movement, the games
 * used with their weekly ranks, each role measure against its threshold and baseline, and the
 * sample. Also written for `none` and `insufficient`, so "why not?" has the same answer.
 */
export function breakoutExplanation(
  standing: Exclude<RecentStanding, { kind: "unavailable" }>,
  season: SeasonStanding | undefined,
  meta: RecentFormMetadata,
): BreakoutExplanation {
  const { verdict, row, span } = standing;
  const range = formatSpan(span);
  const seasonText = season?.kind === "ranked" ? `${row.position}${String(season.rank)} season` : "no season rank";
  const recentText =
    standing.kind === "ranked" ? `${row.position}${String(standing.rank)} in ${range}` : `no game in ${range}`;
  const places = recentVsSeasonPlaces(season, standing);
  const headline = `${seasonText} → ${recentText}${places === null ? "" : ` (${formatPlaces(places)} place${Math.abs(places) === 1 ? "" : "s"})`}`;
  const lines: string[] = [reasonText(verdict.reason)];
  const band = meta.breakout_rule.bands[row.position];
  if (verdict.games.length > 0) {
    const used = verdict.games.map((week) => weekLabel(meta, row, week)).join(", ");
    lines.push(
      `Games used: ${used}${band === undefined ? "" : `; a strong week is a top-${String(band)} ${row.position} finish`}.`,
    );
  }
  for (const reading of verdict.role ?? []) {
    lines.push(`Role: ${roleReadingText(reading, meta, row.position)}.`);
  }
  const entry = row.windows[span.key];
  lines.push(
    `Sample: ${String(entry.games)} game${entry.games === 1 ? "" : "s"} in ${range} ` +
      `(${String(span.weeks)} week${span.weeks === 1 ? "" : "s"}); ` +
      `${formatPoints(entry.points)} points; ${String(entry.prior_games)} game${entry.prior_games === 1 ? "" : "s"} before the window.`,
  );
  lines.push(`Weeks: ${spanText(meta, row, span)}.`);
  const rule = meta.breakout_rule;
  return {
    headline,
    lines,
    footnote:
      `${rule.version}: a descriptive heuristic from fixed thresholds, not a prediction or a ` +
      `probability, and read by no model. A badge needs a recent rank inside the band ` +
      `(QB/TE top ${String(rule.bands.QB ?? 12)}, RB/WR top ${String(rule.bands.RB ?? 24)}), at least ` +
      `${String(rule.min_gain_places)} places and ${String(rule.min_gain_percent)}% better than the ` +
      `season rank, and ${String(rule.min_prior_games)}+ games before the window.`,
  };
}

