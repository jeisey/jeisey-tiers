/**
 * The availability policy where it bites (ADR-101): the actionable ROS list, Pick of the Week
 * and the Trade engine, on the in-season fixture's status shapes. What is tested is the
 * observable decision — who can be recommended — and that no published number moves.
 */

import { describe, expect, it } from "vitest";

import { buildPotwBoard } from "../src/data/potw";
import { InSeasonBundle, selectRosRows, splitActionable } from "../src/data/ros";
import { DEFAULT_STATE } from "../src/data/state";
import { explorationStamp, searchTrade } from "../src/data/trade";
import {
  FIXTURE_OUT_WEEK_ID,
  FIXTURE_SEASON_OVER_ID,
  inSeasonPlayerStatusRecords,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  weeklyProjectionRecords,
} from "./fixtures/artifacts";

function bundle(withStatus = true): InSeasonBundle {
  return new InSeasonBundle({
    metadata: rosBuildMetadata(),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(),
    opportunityDegradation: null,
    weekly: weeklyProjectionRecords(),
    status: withStatus ? inSeasonPlayerStatusRecords() : null,
  });
}

const BLOCK = ["redraft-12", "PPR"] as const;

describe("the actionable rest-of-season board", () => {
  it("holds back a season that is over, keeps reserve and OUT players listed, and renumbers nothing", () => {
    const rows = selectRosRows(bundle(), DEFAULT_STATE);
    const { shown, held } = splitActionable(rows, false, "");
    expect(held.map((row) => row.record.player_id)).toEqual([FIXTURE_SEASON_OVER_ID]);
    expect(shown.some((row) => row.availability?.horizon === "unavailable_now")).toBe(true);
    expect(shown.some((row) => row.record.player_id === FIXTURE_OUT_WEEK_ID)).toBe(true);
    // Ranks are the model's: the gap is left, not closed.
    const ranks = shown.map((row) => row.record.ros_fair_rank);
    const all = rows.map((row) => row.record.ros_fair_rank);
    expect(all.filter((rank) => !ranks.includes(rank))).toEqual(held.map((row) => row.record.ros_fair_rank));
  });

  it("shows him on request, and to a search that names him", () => {
    const rows = selectRosRows(bundle(), DEFAULT_STATE);
    expect(splitActionable(rows, true, "").held).toHaveLength(0);
    const searched = selectRosRows(bundle(), { ...DEFAULT_STATE, search: "Hampton" });
    expect(splitActionable(searched, false, "Hampton").shown).toHaveLength(1);
  });

  it("leaves every published ROS record byte-identical", () => {
    const before = JSON.stringify(rosTierRecords());
    selectRosRows(bundle(), DEFAULT_STATE);
    expect(JSON.stringify(bundle().rosFor(...BLOCK))).toBe(
      JSON.stringify(rosTierRecords().filter((r) => r.league_preset_id === BLOCK[0] && r.scoring_preset === BLOCK[1]).sort((a, b) => a.ros_fair_rank - b.ros_fair_rank)),
    );
    expect(JSON.stringify(rosTierRecords())).toBe(before);
  });
});

describe("Pick of the Week", () => {
  it("never features a player who cannot play this week or whose season is over", () => {
    const board = buildPotwBoard(bundle(), ...BLOCK);
    const picked = board.sets.flatMap((set) => set.picks.map((pick) => pick.opportunity.player_id));
    const b = bundle();
    for (const id of picked) {
      const reading = b.availabilityFor(id);
      expect(["out", "doubtful", "unavailable"]).not.toContain(reading.week);
      expect(["season_over", "unavailable_now"]).not.toContain(reading.horizon);
    }
  });
});

describe("the Trade engine", () => {
  const records = () => bundle().rosFor(...BLOCK);
  const reader = (id: string) => bundle().availabilityFor(id);
  const base = { goal: "value" as const, get: 2 as const, range: 50, comp: [] };

  it("never suggests a season that is over, even with the returning opt-in", () => {
    for (const includeReturning of [false, true]) {
      const search = searchTrade({ ...base, records: records(), give: ["gsis:00-0000001"], availability: reader, includeReturning });
      if (search.status !== "ok") throw new Error(search.status);
      const members = search.pool.flatMap((entry) => entry.pkg.members.map((member) => member.id));
      expect(members).not.toContain(FIXTURE_SEASON_OVER_ID);
      expect(search.excluded.find((row) => row.record.player_id === FIXTURE_SEASON_OVER_ID)?.reason).toBe("season_over");
    }
  });

  it("admits reserve-list players only with the opt-in", () => {
    const off = searchTrade({ ...base, records: records(), give: ["gsis:00-0000001"], availability: reader, includeReturning: false });
    const on = searchTrade({ ...base, records: records(), give: ["gsis:00-0000001"], availability: reader, includeReturning: true });
    if (off.status !== "ok" || on.status !== "ok") throw new Error("search");
    expect(off.excluded.some((row) => row.reason === "unavailable_now")).toBe(true);
    expect(on.excluded.some((row) => row.reason === "unavailable_now" || row.reason === "long_absence")).toBe(false);
    expect(on.eligible).toBeGreaterThan(off.eligible);
  });

  it("refuses a season-ending outgoing budget, and warns on an OUT one", () => {
    const over = searchTrade({ ...base, records: records(), give: [FIXTURE_SEASON_OVER_ID], availability: reader });
    expect(over.status).toBe("unavailable_outgoing");
    const out = searchTrade({ ...base, records: records(), give: [FIXTURE_OUT_WEEK_ID], availability: reader });
    if (out.status !== "ok") throw new Error(out.status);
    expect(out.outgoingWarnings.map((entry) => entry.record.player_id)).toEqual([FIXTURE_OUT_WEEK_ID]);
  });

  it("puts the opt-in in the exploration's identity without changing any earlier stamp", () => {
    const parts = { buildId: "b", leaguePreset: "redraft-12", scoring: "PPR", give: ["x"], goal: "value" as const, get: 1, range: 20, comp: [] };
    expect(explorationStamp(parts)).toBe(explorationStamp({ ...parts, includeReturning: false }));
    expect(explorationStamp({ ...parts, includeReturning: true })).not.toBe(explorationStamp(parts));
  });
});
