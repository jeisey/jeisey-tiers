/**
 * Every Insights chart in words (ADR-116): one sentence for a screen reader in place of the
 * drawing, and a table of the exact values the drawing places, for everyone (it is the
 * "Exact values" a card's Evidence opens). Read straight from the chart payload; nothing here
 * rounds a value the table prints except where a share is written as a percentage.
 */

import type { InsightChart } from "../../data/contracts";
import { percentText, pointsText, type InsightStory } from "../../data/insights";

const EM_DASH = "—";

export interface ChartTable {
  readonly caption: string;
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
}

const STATUS: Readonly<Record<"P" | "B" | "D", string>> = { P: "played", B: "bye", D: "did not play" };

function exact(value: number | null): string {
  return value === null ? EM_DASH : String(value);
}

function share(value: number | null): string {
  return value === null ? EM_DASH : `${percentText(value, 1)} (${String(value)})`;
}

function unitOf(chart: Extract<InsightChart, { type: "with_without" }>): string {
  return chart.metric === "target_share" ? "targets" : chart.metric === "carry_share" ? "carries" : "pass attempts";
}

/** The figure's short visible caption. */
export function chartCaption(story: InsightStory): string {
  const chart = story.chart;
  switch (chart.type) {
    case "week_strip":
      return story.family === "streak_watch"
        ? `Fantasy points by week with his weekly ${story.position} rank${chart.share_label === null ? "" : `, and ${chart.share_label.toLowerCase()}`}`
        : `${chart.opportunity_label} and fantasy points by week, on one week axis`;
    case "interval":
      return "This week's points distribution against his typical week";
    case "with_without":
      return `Share of team ${unitOf(chart)} with and without ${chart.absent.name}`;
    case "room":
      return `The ${chart.room === "backfield" ? "backfield" : "receiving room"}: share of team ${chart.metric}`;
    case "stat_line":
      return "Per game, pace and the two season ranks";
  }
}

/** One sentence that says what the drawing shows. */
export function chartSentence(story: InsightStory): string {
  const chart = story.chart;
  switch (chart.type) {
    case "week_strip": {
      const first = chart.weeks[0]?.week ?? 0;
      const last = chart.weeks[chart.weeks.length - 1]?.week ?? 0;
      const window = chart.weeks.filter((week) => week.in_window).map((week) => week.week);
      const windowText = window.length === 0 ? "" : ` The window is weeks ${String(window[0])} to ${String(window[window.length - 1])}.`;
      const played = chart.weeks.filter((week) => week.status === "P");
      const points = played.map((week) => `week ${String(week.week)} ${pointsText(week.points)}`).join(", ");
      const missing = chart.weeks.filter((week) => week.status !== "P").map((week) => `week ${String(week.week)} ${STATUS[week.status]}`);
      return (
        `Weeks ${String(first)} to ${String(last)}.${windowText} Fantasy points: ${points}.` +
        (missing.length > 0 ? ` ${missing.join(", ")}.` : "") +
        " Every value is in the Exact values table under Evidence."
      );
    }
    case "interval": {
      const typical =
        chart.typical_q10 === null || chart.typical_q50 === null || chart.typical_q90 === null
          ? " No typical week is published."
          : ` His typical week: floor ${pointsText(chart.typical_q10)}, median ${pointsText(chart.typical_q50)}, ceiling ${pointsText(chart.typical_q90)}.`;
      return `This week: floor (P10) ${pointsText(chart.q10)}, median (P50) ${pointsText(chart.q50)}, ceiling (1 week in 10) ${pointsText(chart.q90)} points.${typical}`;
    }
    case "with_without": {
      const rows = chart.rows.map((row) => {
        const without =
          row.share_without === null
            ? "no game without him yet"
            : `${percentText(row.share_without)} without him over ${String(row.games_without)} game${row.games_without === 1 ? "" : "s"}`;
        return `${row.name} ${percentText(row.share_with)} with him over ${String(row.games_with)} game${row.games_with === 1 ? "" : "s"}, ${without}`;
      });
      return `${chart.absent.name}: ${percentText(chart.absent.share)} of team ${unitOf(chart)} over ${String(chart.absent.games)} games. ${rows.join("; ")}.`;
    }
    case "room": {
      const rows = chart.rows.map(
        (row) =>
          `${row.name} ${percentText(row.share)} (${String(row.count)} of ${String(chart.team_count)})${row.share_baseline === null ? "" : `, before ${percentText(row.share_baseline)}`}`,
      );
      return `Team ${chart.metric}: ${String(chart.team_count)} in ${String(chart.team_games)} games. ${rows.join("; ")}.`;
    }
    case "stat_line":
      return (
        `${pointsText(chart.points_per_game)} points per game in ${String(chart.games)} of ${String(chart.team_games)} team games; ` +
        `17-game pace ${pointsText(chart.pace_17)} (arithmetic, not a projection). PPG rank ${String(chart.ppg_rank)}, ` +
        `total rank ${chart.total_rank === null ? EM_DASH : String(chart.total_rank)}, among ${String(chart.cohort_size)} ${story.position}s with ${String(chart.cohort_min_games)}+ games.`
      );
  }
}

/** The chart's exact values. */
export function chartTable(story: InsightStory): ChartTable {
  const chart = story.chart;
  switch (chart.type) {
    case "week_strip":
      return {
        caption: "Week by week",
        columns: ["Week", "Status", "In window", chart.opportunity_label, "Points", "TD points", chart.share_label ?? "Share", "Rank"],
        rows: chart.weeks.map((week) => [
          String(week.week),
          STATUS[week.status],
          week.in_window ? "yes" : "no",
          exact(week.opportunity),
          exact(week.points),
          exact(week.td_points),
          share(week.share),
          exact(week.rank),
        ]),
      };
    case "interval":
      return {
        caption: "Points distribution",
        columns: ["", "Floor (P10)", "Median (P50)", "Ceiling (P90, 1 week in 10)"],
        rows: [
          ["This week", String(chart.q10), String(chart.q50), String(chart.q90)],
          ["Typical week", exact(chart.typical_q10), exact(chart.typical_q50), exact(chart.typical_q90)],
        ],
      };
    case "with_without":
      return {
        caption: `With and without ${chart.absent.name} (${chart.absent.reason})`,
        columns: ["Player", "With him", "Games with", "Without him", "Games without", "Latest"],
        rows: [
          [`${chart.absent.name} (absent)`, share(chart.absent.share), String(chart.absent.games), EM_DASH, EM_DASH, `${String(chart.absent.per_game)} per game`],
          ...chart.rows.map((row) => [
            `${row.name} (${row.position})`,
            share(row.share_with),
            String(row.games_with),
            share(row.share_without),
            String(row.games_without),
            share(row.latest_share),
          ]),
        ],
      };
    case "room":
      return {
        caption: `Team ${chart.metric} ${String(chart.team_count)} in ${String(chart.team_games)} games; red zone ${exact(chart.team_red_zone)}; inside the 5 ${exact(chart.team_inside_five)}`,
        columns: ["Player", "Games (window)", "Count", "Share", "Before", "Games before", "Snaps", "Snaps before", "Red zone", "Inside 5"],
        rows: chart.rows.map((row) => [
          `${row.name} (${row.position})`,
          String(row.window_games),
          `${String(row.count)} of ${String(chart.team_count)}`,
          share(row.share),
          share(row.share_baseline),
          String(row.baseline_games),
          share(row.snap_share),
          share(row.snap_share_baseline),
          exact(row.red_zone),
          exact(row.inside_five),
        ]),
      };
    case "stat_line":
      return {
        caption: "Season to date",
        columns: ["Measure", "Value"],
        rows: [
          ["Games", `${String(chart.games)} of ${String(chart.team_games)} team games`],
          ["Points", String(chart.points)],
          ["Points per game", String(chart.points_per_game)],
          ["17-game pace (PPG × 17, arithmetic)", String(chart.pace_17)],
          ["PPG rank", String(chart.ppg_rank)],
          ["Total points rank", exact(chart.total_rank)],
          ["Cohort", `${String(chart.cohort_size)} ${story.position}s with ${String(chart.cohort_min_games)}+ games`],
        ],
      };
  }
}
