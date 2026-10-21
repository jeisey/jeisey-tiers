/**
 * "Hide bye-week players" on the ROS and Start/Sit boards (ADR-115).
 *
 * A bye is read off the build's schedule for its target week and nothing else: a missing line,
 * an injury, a kicked-off game, a null opponent or an absent projection is never one, and an
 * unknown schedule keeps a player visible.
 */

import { describe, expect, it } from "vitest";

import { settingsSummary } from "../src/app/Controls";
import { applyByeFilter, rosByeSchedule, weekByeState } from "../src/data/bye";
import type { TeamMatchupRecord, WeeklyProjectionRecord } from "../src/data/contracts";
import { selectWeekBoard, selectWeekBoardWithByes } from "../src/data/duel";
import { InSeasonBundle, selectRosBoard, selectRosRows } from "../src/data/ros";
import { DEFAULT_STATE, parseState, serializeState, type AppState } from "../src/data/state";
import { requiredKeys } from "../src/data/store";
import {
  inSeasonPlayerStatusRecords,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  teamMatchupRecords,
  weeklyProjectionRecords,
} from "./fixtures/artifacts";

function bundle(options: { matchups?: TeamMatchupRecord[] | null; metadata?: ReturnType<typeof rosBuildMetadata> } = {}): InSeasonBundle {
  return new InSeasonBundle({
    metadata: options.metadata ?? rosBuildMetadata(),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(),
    opportunityDegradation: null,
    weekly: weeklyProjectionRecords(),
    matchups: options.matchups === undefined ? teamMatchupRecords() : options.matchups,
    status: inSeasonPlayerStatusRecords(),
  });
}

const ON: AppState = { ...DEFAULT_STATE, hideBye: true };
const meta = rosBuildMetadata();
const TARGET = meta.through_week + 1;

function matchup(team: string, week: number, byes: number[], throughWeek = meta.through_week): TeamMatchupRecord {
  const base = teamMatchupRecords()[0];
  if (base === undefined) throw new Error("fixture has no matchup");
  return { ...base, team, week, upcoming_bye_weeks: byes, through_week: throughWeek };
}

function scheduleOf(records: TeamMatchupRecord[], metadata = meta) {
  const byTeam = new Map(records.map((record) => [record.team, record]));
  return rosByeSchedule({
    metadata,
    hasMatchups: true,
    matchupFor: (team) => (team == null ? null : (byTeam.get(team) ?? null)),
  });
}

describe("the ROS rule reads the schedule for the build's target week", () => {
  const schedule = scheduleOf([
    matchup("ATL", TARGET + 1, [TARGET]),
    matchup("DET", TARGET, []),
    // Played Thursday of the target week: the next game is a week later and there is no bye.
    matchup("CIN", TARGET + 1, []),
    // A record cut at another cutoff is not this week's schedule.
    matchup("SF", TARGET + 1, [TARGET], meta.through_week - 1),
    // A later bye is not this week's.
    matchup("BUF", TARGET, [TARGET + 3]),
  ]);

  it("knows a bye, a scheduled game and an already-played game apart", () => {
    expect(schedule.kind).toBe("ready");
    if (schedule.kind !== "ready") return;
    expect(schedule.targetWeek).toBe(TARGET);
    expect(schedule.stateOf("ATL")).toBe("bye");
    expect(schedule.stateOf("DET")).toBe("playing");
    expect(schedule.stateOf("CIN")).toBe("playing");
    expect(schedule.stateOf("BUF")).toBe("playing");
  });

  it("keeps unknown teams, mismatched records and free agents visible", () => {
    if (schedule.kind !== "ready") throw new Error("not ready");
    expect(schedule.stateOf("SF")).toBe("unknown");
    expect(schedule.stateOf("NYJ")).toBe("unknown");
    expect(schedule.stateOf(null)).toBe("unknown");
  });

  it("rolls over with the build: last week's bye is not next week's", () => {
    const next = { ...meta, through_week: TARGET, weekly: meta.weekly == null ? null : { ...meta.weekly, target_week: TARGET + 1 } };
    const rolled = scheduleOf([matchup("ATL", TARGET + 1, [TARGET], TARGET)], next);
    expect(rolled.kind === "ready" && rolled.stateOf("ATL")).toBe("playing");
  });

  it("is unavailable, not guessed, without a schedule or with a mismatched week", () => {
    expect(rosByeSchedule({ metadata: meta, hasMatchups: false, matchupFor: () => null })).toEqual({
      kind: "unavailable",
      reason: "this build published no schedule",
    });
    const stale = { ...meta, weekly: meta.weekly == null ? null : { ...meta.weekly, target_week: TARGET + 1 } };
    expect(scheduleOf([], stale).kind).toBe("unavailable");
  });
});

describe("Start/Sit reads its own weekly game state", () => {
  const weekly = meta.weekly ?? { target_week: TARGET };
  const record = (patch: Partial<WeeklyProjectionRecord>): WeeklyProjectionRecord => {
    const base = weeklyProjectionRecords()[0];
    if (base === undefined) throw new Error("fixture has no weekly record");
    return { ...base, ...patch };
  };

  it("hides only a bye — never a pending line, a kicked-off game or an injury", () => {
    expect(weekByeState(record({ game_state: "bye" }), weekly)).toBe("bye");
    expect(weekByeState(record({ game_state: "lines_pending" }), weekly)).toBe("playing");
    expect(weekByeState(record({ game_state: "kicked_off" }), weekly)).toBe("playing");
    expect(
      weekByeState(
        record({ game_state: "upcoming", injury: { week: TARGET, designation: "Out", practice_status: null, primary_injury: "Knee" } }),
        weekly,
      ),
    ).toBe("playing");
  });

  it("does not trust a record for another week", () => {
    expect(weekByeState(record({ game_state: "bye", target_week: TARGET + 1 }), weekly)).toBe("unknown");
    expect(weekByeState(record({ game_state: "bye" }), null)).toBe("unknown");
  });
});

describe("the two boards", () => {
  it("agree with each other about who is on a bye in the fixture's week", () => {
    const board = bundle();
    const ros = rosByeSchedule(board);
    if (ros.kind !== "ready") throw new Error("fixture schedule unavailable");
    const fromWeekly = new Set(
      weeklyProjectionRecords()
        .filter((record) => record.game_state === "bye")
        .map((record) => record.team),
    );
    expect(fromWeekly.size).toBeGreaterThan(0);
    for (const team of fromWeekly) expect(ros.stateOf(team)).toBe("bye");
  });

  it("filters ROS before the split, intersects position and search, and renumbers nothing", () => {
    const board = bundle();
    const all = selectRosRows(board, DEFAULT_STATE);
    const { rows, byeHidden } = selectRosBoard(board, ON);
    expect(byeHidden).toBeGreaterThan(0);
    expect(rows.length + byeHidden).toBe(all.length);
    // The published ranks are carried through unchanged.
    const ranks = new Map(all.map((row) => [row.record.player_id, row.record.ros_fair_rank]));
    for (const row of rows) expect(row.record.ros_fair_rank).toBe(ranks.get(row.record.player_id));
    const rb = selectRosBoard(board, { ...ON, position: "rb" });
    expect(rb.rows.every((row) => row.record.position === "RB")).toBe(true);
  });

  it("does not let a search override the filter, and says what it hid", () => {
    const board = bundle();
    const kept = new Set(selectRosBoard(board, ON).rows.map((row) => row.record.player_id));
    const hidden = selectRosRows(board, DEFAULT_STATE).find((row) => !kept.has(row.record.player_id));
    const name = hidden?.record.display_name ?? "";
    expect(name).not.toBe("");
    const searched = selectRosBoard(board, { ...ON, search: name });
    expect(searched.rows.find((row) => row.record.player_id === hidden?.record.player_id)).toBeUndefined();
    expect(searched.byeHidden).toBeGreaterThan(0);
  });

  it("leaves ROS whole when the schedule is missing", () => {
    const board = bundle({ matchups: null });
    const result = selectRosBoard(board, ON);
    expect(result.byeHidden).toBe(0);
    expect(result.bye?.kind).toBe("unavailable");
    expect(result.rows.length).toBe(selectRosRows(board, DEFAULT_STATE).length);
  });

  it("filters Start/Sit before paging and keeps the week ranks", () => {
    const board = bundle();
    const off = selectWeekBoard(board, DEFAULT_STATE, "median");
    const on = selectWeekBoardWithByes(board, ON, "median");
    expect(on.byeHidden).toBeGreaterThan(0);
    expect(on.rows.length + on.byeHidden).toBe(off.length);
    expect(on.rows.every((row) => row.record.game_state !== "bye")).toBe(true);
    expect(on.rows.some((row) => row.record.game_state === "lines_pending")).toBe(
      off.some((row) => row.record.game_state === "lines_pending"),
    );
    const rank = new Map(off.map((row) => [row.record.player_id, row.positionRank]));
    for (const row of on.rows) expect(row.positionRank).toBe(rank.get(row.record.player_id));
  });

  it("is a no-op when off", () => {
    expect(applyByeFilter([1, 2, 3], false, () => "bye")).toEqual({ shown: [1, 2, 3], hidden: 0 });
  });
});

describe("the URL and the folded summary", () => {
  it("round-trips nobye=1, defaults off and normalizes a bad value", () => {
    expect(serializeState(DEFAULT_STATE)).toBe("");
    const parsed = parseState("?view=ros&nobye=1");
    expect(parsed.state.hideBye).toBe(true);
    expect(parsed.normalized).toBe(true);
    expect(serializeState(parsed.state)).toBe("?view=ros&nobye=1");
    const bad = parseState("?nobye=yes");
    expect(bad.state.hideBye).toBe(false);
    expect(bad.normalized).toBe(false);
  });

  it("names the filter in the phone's folded row only where it applies", () => {
    expect(settingsSummary(ON, true, null, true)).toContain("Byes hidden");
    expect(settingsSummary(ON, true, null, false)).not.toContain("Byes hidden");
    expect(settingsSummary(DEFAULT_STATE, true, null, true)).not.toContain("Byes hidden");
  });
});

describe("payload", () => {
  const manifest = {
    files: { "ros_tiers/redraft-12.PPR": "a", "season_actuals/PPR": "b", "team_matchups/all": "c" },
    card_buckets: 64,
  } as unknown as Parameters<typeof requiredKeys>[0];
  const context = { view: "ros", leaguePreset: "redraft-12", scoring: "PPR", cardPlayerId: null } as const;

  it("loads the schedule slice for ROS only while the filter is on", () => {
    expect(requiredKeys(manifest, context)).not.toContain("team_matchups/all");
    expect(requiredKeys(manifest, { ...context, hideBye: true })).toContain("team_matchups/all");
  });
});
