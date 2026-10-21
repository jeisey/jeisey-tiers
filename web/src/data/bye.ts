/**
 * "Hide bye-week players" on the ROS and Start/Sit boards (ADR-115).
 *
 * A bye is a scheduled fact about a team in one week, so the rule reads the build's schedule
 * and nothing else. In particular it never infers a bye from a missing projection, a missing
 * betting line, an injury, a null opponent or a next-game date: each of those has another
 * cause, and a player hidden for one of them would be a player the filter invented a reason
 * for. Anything the schedule cannot answer is `unknown`, and an unknown row stays visible.
 *
 * **Which week.** The build's own target week — `through_week + 1`, the week Start/Sit
 * projects — never the reader's clock. A link opened on Friday reads the same bye week as one
 * opened on Tuesday from the same build, and the control says which week it means.
 *
 * **Start/Sit** reads `game_state === "bye"` on the week's projection: the weekly build
 * already decided it from the schedule for exactly that week.
 *
 * **ROS** has no per-row game state, so it reads the team's `team_matchups` record — loaded
 * only while the filter is on, never for an ordinary ROS visit. `upcoming_bye_weeks` is
 * computed from the *whole* schedule, played games included, so a team whose Thursday game is
 * already over is not on a bye; `week` is the team's next unplayed game. A record cut at a
 * different cutoff than the board, or a team with no record, is `unknown`.
 */

import type {
  RosBuildMetadata,
  TeamMatchupRecord,
  WeeklyProjectionRecord,
} from "./contracts";

export type ByeState = "bye" | "playing" | "unknown";

export type ByeSchedule =
  | {
      readonly kind: "ready";
      /** The week "bye" means: the build's target week. */
      readonly targetWeek: number;
      readonly stateOf: (team: string | null | undefined) => ByeState;
    }
  /** The filter cannot be applied: the control is disabled and says why. */
  | { readonly kind: "unavailable"; readonly reason: string };

interface ScheduleSource {
  readonly metadata: Pick<RosBuildMetadata, "season" | "through_week" | "weekly">;
  readonly hasMatchups: boolean;
  matchupFor(team: string | null | undefined): TeamMatchupRecord | null;
}

/** The ROS board's schedule reading, from the build's next-game records. */
export function rosByeSchedule(source: ScheduleSource): ByeSchedule {
  const { season, through_week: throughWeek } = source.metadata;
  const targetWeek = throughWeek + 1;
  const weeklyTarget = source.metadata.weekly?.target_week ?? null;
  if (weeklyTarget !== null && weeklyTarget !== targetWeek) {
    return {
      kind: "unavailable",
      reason: `this build's schedule is for week ${String(weeklyTarget)}, not week ${String(targetWeek)}`,
    };
  }
  if (!source.hasMatchups) return { kind: "unavailable", reason: "this build published no schedule" };
  return {
    kind: "ready",
    targetWeek,
    stateOf: (team) => {
      const record = source.matchupFor(team);
      if (record === null) return "unknown";
      // A record from another cutoff describes another week's schedule.
      if (record.season !== season || record.through_week !== throughWeek) return "unknown";
      if (record.week === targetWeek) return "playing";
      if (record.upcoming_bye_weeks.includes(targetWeek)) return "bye";
      // His next game is later and the target week is not a bye: he played it already.
      if (record.week > targetWeek) return "playing";
      return "unknown";
    },
  };
}

/** Start/Sit's reading for one projection: the weekly build's own game state. */
export function weekByeState(
  record: WeeklyProjectionRecord,
  weekly: { readonly target_week: number } | null | undefined,
): ByeState {
  if (record.target_week !== weekly?.target_week) return "unknown";
  return record.game_state === "bye" ? "bye" : "playing";
}

/** Split rows into those shown and those the filter hid. Off, or unavailable: nothing hidden. */
export function applyByeFilter<Row>(
  rows: readonly Row[],
  on: boolean,
  stateOf: ((row: Row) => ByeState) | null,
): { readonly shown: readonly Row[]; readonly hidden: number } {
  if (!on || stateOf === null) return { shown: rows, hidden: 0 };
  const shown = rows.filter((row) => stateOf(row) !== "bye");
  return { shown, hidden: rows.length - shown.length };
}
