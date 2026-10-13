/**
 * Improve (ADR-106, `improve_v1`): the slot-relative weakness rule, the bench first, targets
 * that exclude the whole roster and unavailable players, and packages judged after removing
 * the outgoing players, adding the incoming ones and re-optimising — including the trade that
 * looks like an upgrade and only moves the hole, and the one the roster has no room for.
 */

import { describe, expect, it } from "vitest";

import { readAvailability, type Availability } from "../src/data/availability";
import type { Position, RosTierRecord, WeeklyProjectionRecord } from "../src/data/contracts";
import { DEFAULT_PREFS, emptyRoster, type Roster, type SavedLeague, type SlotCounts, type SlotGroup } from "../src/data/leagueContract";
import { improveRoster, rosterLine, type ImproveInput } from "../src/data/improve";
import type { WeekContext } from "../src/data/lineup";
import { distributionRule } from "../src/data/startsit";
import { required } from "./required";

const WEEK = 9;
const NOW = Date.parse("2026-11-08T12:00:00Z");
const THRESHOLD: Readonly<Record<Position, number>> = { QB: 16, RB: 9, WR: 9, TE: 6, K: 0, DST: 0 };

interface Player {
  readonly position: Position;
  /** Weekly median; null means a bye. */
  readonly q50: number | null;
  /** Rest-of-season expected VORP; also orders fair rank. */
  readonly vorp: number;
  readonly posRank: number;
  readonly status?: "retired" | "reserve" | "out";
}

function weekly(id: string, player: Player): WeeklyProjectionRecord {
  const q50 = player.q50;
  const bye = q50 === null;
  const spread = (value: number, factor: number): number => Math.round(value * factor * 100) / 100;
  return {
    schema_version: "1.1",
    build_id: "t",
    season: 2026,
    through_week: WEEK - 1,
    target_week: WEEK,
    player_id: id,
    display_name: id,
    position: player.position,
    team: "BUF",
    scoring_preset: "PPR",
    model_version: "weekly-startsit-v1",
    game_state: bye ? "bye" : "upcoming",
    game: bye
      ? null
      : {
          game_id: "g",
          opponent: "MIA",
          home_away: "home",
          neutral_site: false,
          kickoff_utc: "2026-11-08T18:00:00Z",
          roof: null,
          total_line: 45,
          team_margin: 0,
          team_points: 22.5,
        },
    quantiles: bye
      ? null
      : {
          q05: spread(q50, 0.3),
          q10: spread(q50, 0.45),
          q25: spread(q50, 0.72),
          q50,
          q75: spread(q50, 1.3),
          q90: spread(q50, 1.65),
          q95: spread(q50, 1.9),
        },
    drivers: null,
    explanation: null,
    opponent: null,
    injury: null,
  };
}

function ros(id: string, player: Player, fairRank: number): RosTierRecord {
  const v = player.vorp;
  return {
    schema_version: "1.2",
    build_id: "t",
    season: 2026,
    through_week: WEEK - 1,
    league_preset_id: "redraft-12",
    scoring_preset: "PPR",
    player_id: id,
    display_name: id,
    team: "BUF",
    position: player.position,
    ros_fair_rank: fairRank,
    ros_position_rank: player.posRank,
    ros_tier: 0,
    ros_tier_label: "A",
    ros_expected_vorp: v,
    ros_vorp_p10: v - 20,
    ros_vorp_p25: v - 8,
    ros_vorp_p50: v,
    ros_vorp_p75: v + 8,
    ros_vorp_p90: v + 20,
    ros_expected_points: 100 + v,
    ros_points_p10: 60 + v,
    ros_points_p50: 100 + v,
    ros_points_p90: 140 + v,
    ros_expected_games: 9,
    ros_uncertainty: 40,
    remaining_horizon_weeks: 9,
    games_played_to_date: 8,
    points_to_date: 80,
    weeks_since_last_game: 0,
    consecutive_weeks_missed: 0,
    has_played_this_season: true,
    long_absence: false,
    in_preseason_universe: true,
    current_status: "ACT",
    quality_flags: [],
  };
}

function availability(player: Player | undefined): Availability {
  const status = {
    player_id: "x",
    roster_status: player?.status === "retired" ? "RET" : player?.status === "reserve" ? "RES" : "ACT",
    sleeper_status: player?.status === "reserve" ? "Inactive" : "Active",
    injury_status: player?.status === "out" ? "Out" : player?.status === "reserve" ? "IR" : null,
    observed_at_utc: "2026-11-08T10:00:00Z",
    quality_flags: [],
  };
  return readAvailability({ status, referenceTime: "2026-11-08T11:00:00Z", season: 2026 });
}

function input(players: Readonly<Record<string, Player>>, league: SavedLeague): ImproveInput {
  const ids = Object.keys(players).sort((a, b) => (players[b]?.vorp ?? 0) - (players[a]?.vorp ?? 0));
  const records = ids.map((id, index) => ros(id, required(players[id], id), index + 1));
  const week: WeekContext = {
    weeklyFor: (id) => (players[id] === undefined ? null : weekly(id, players[id])),
    availabilityFor: (id) => availability(players[id]),
    positionOf: (id) => players[id]?.position ?? null,
    targetWeek: WEEK,
    now: NOW,
  };
  return {
    league,
    records,
    week,
    threshold: (position) => THRESHOLD[position],
    rule: distributionRule(null),
    availabilityFor: (id) => availability(players[id]),
  };
}

const COUNTS: SlotCounts = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 3, IR: 1 };

function league(groups: Partial<Record<SlotGroup, (string | null)[]>>, counts: SlotCounts = COUNTS): SavedLeague {
  const base = emptyRoster(counts);
  const roster = Object.fromEntries(
    Object.entries(base).map(([group, slots]) => [
      group,
      slots.map((_, index) => groups[group as SlotGroup]?.[index] ?? null),
    ]),
  ) as unknown as Roster;
  return {
    id: "lg-test0001",
    name: "Test",
    season: 2026,
    scoring: "ppr",
    teams: 12,
    slots: counts,
    roster,
    prefs: DEFAULT_PREFS,
    rev: 1,
    updatedAt: "",
  };
}

/** A sound roster, every slot comfortably startable and inside its line. */
const CORE: Record<string, Player> = {
  qb: { position: "QB", q50: 22, vorp: 60, posRank: 4 },
  rb1: { position: "RB", q50: 16, vorp: 80, posRank: 3 },
  rb2: { position: "RB", q50: 14, vorp: 55, posRank: 10 },
  wr1: { position: "WR", q50: 17, vorp: 85, posRank: 2 },
  wr2: { position: "WR", q50: 14, vorp: 50, posRank: 12 },
  te: { position: "TE", q50: 11, vorp: 30, posRank: 3 },
  flex: { position: "WR", q50: 13, vorp: 40, posRank: 20 },
};
const CORE_LINEUP = { QB: ["qb"], RB: ["rb1", "rb2"], WR: ["wr1", "wr2"], TE: ["te"], FLEX: ["flex"] };

describe("the weakness rule", () => {
  it("measures each slot against its own position's line, not raw points", () => {
    const players = { ...CORE, te: { position: "TE" as const, q50: 7.5, vorp: 25, posRank: 5 } };
    const result = improveRoster(input(players, league(CORE_LINEUP)));
    // A 7.5-point tight end clears his 6-point line comfortably; nothing here is a need, even
    // though he scores less than anyone else in the lineup.
    expect(result.needs).toEqual([]);
    const te = result.standings.find((entry) => entry.slot.group === "TE");
    expect(te?.chance).toBeGreaterThan(0.5);
    expect(result.customStarters).toBe(true);
  });

  it("flags a weak slot as temporary when his rest of season is fine, and a roster need when it is not", () => {
    const players = {
      ...CORE,
      rb2: { position: "RB" as const, q50: null, vorp: 50, posRank: 11 },
      te: { position: "TE" as const, q50: 4, vorp: 2, posRank: 19 },
    };
    const result = improveRoster(input(players, league(CORE_LINEUP)));
    const bySlot = Object.fromEntries(result.needs.map((need) => [need.slot.group, need]));
    expect(bySlot.RB?.kind).toBe("temporary");
    expect(bySlot.RB?.current.chance).toBe(0);
    expect(bySlot.TE?.kind).toBe("roster");
    expect(bySlot.TE?.current.rank).toBe(19);
    expect(bySlot.TE?.current.line).toBe(12);
    // Holes first: the bye (0%) before the weak tight end.
    expect(result.needs[0]?.slot.group).toBe("RB");
  });

  it("uses the league's own size and starters for the rest-of-season line", () => {
    const base = league(CORE_LINEUP);
    expect(rosterLine("RB", base)).toBe(24);
    expect(rosterLine("FLEX", base)).toBe(12 * (2 + 2 + 1 + 1));
    expect(rosterLine("QB", { ...base, teams: 10 })).toBe(10);
  });
});

describe("what is suggested", () => {
  it("offers the bench first, and nothing external when the bench fixes the slot", () => {
    const players = {
      ...CORE,
      rb2: { position: "RB" as const, q50: null, vorp: 50, posRank: 11 },
      benchRb: { position: "RB" as const, q50: 13, vorp: 20, posRank: 20 },
    };
    const result = improveRoster(input(players, league({ ...CORE_LINEUP, BN: ["benchRb"] })));
    const need = result.needs.find((entry) => entry.slot.group === "RB" && entry.slot.index === 1);
    expect(need?.benchUpgrade).toBe(true);
    expect(need?.best.id).toBe("benchRb");
    expect(need?.remaining).toBe(false);
    expect(need?.targets).toEqual([]);
  });

  it("names targets that fit the slot, excluding the whole roster and players who cannot be acquired", () => {
    const players = {
      ...CORE,
      te: { position: "TE" as const, q50: 4, vorp: 2, posRank: 19 },
      irTe: { position: "TE" as const, q50: 12, vorp: 45, posRank: 1 },
      benchTe: { position: "TE" as const, q50: 3, vorp: 1, posRank: 25 },
      freeTe: { position: "TE" as const, q50: 9, vorp: 20, posRank: 6 },
      retiredTe: { position: "TE" as const, q50: 10, vorp: 35, posRank: 2, status: "retired" as const },
      reserveTe: { position: "TE" as const, q50: 10, vorp: 33, posRank: 4, status: "reserve" as const },
      freeRb: { position: "RB" as const, q50: 15, vorp: 70, posRank: 5 },
    };
    const result = improveRoster(
      input(players, league({ ...CORE_LINEUP, BN: ["benchTe"], IR: ["irTe"] })),
    );
    const need = result.needs.find((entry) => entry.slot.group === "TE");
    expect(need?.kind).toBe("roster");
    expect(need?.targets.map((target) => target.record.player_id)).toEqual(["freeTe"]);
  });

  it("evaluates a package after the trade: the weak starter and a bench player for a target", () => {
    const players = {
      ...CORE,
      te: { position: "TE" as const, q50: 4, vorp: 6, posRank: 19 },
      benchWr: { position: "WR" as const, q50: 8, vorp: 12, posRank: 40 },
      freeTe: { position: "TE" as const, q50: 9, vorp: 20, posRank: 6 },
    };
    const result = improveRoster(input(players, league({ ...CORE_LINEUP, BN: ["benchWr"] })));
    const need = result.needs.find((entry) => entry.slot.group === "TE");
    const idea = need?.packages.find((entry) => entry.get.map((player) => player.id).join() === "freeTe");
    expect(idea).toBeDefined();
    expect(idea?.give.map((player) => player.id).sort()).toEqual(["benchWr", "te"]);
    expect(idea?.after).toBeGreaterThan(idea?.before ?? Infinity);
    expect(idea?.rosterNeedsAfter).toBeLessThan(idea?.rosterNeedsBefore ?? 0);
    expect(idea?.affected.map((entry) => `${entry.slot.group}:${String(entry.from)}>${String(entry.to)}`)).toEqual([
      "TE:te>freeTe",
    ]);
    expect(idea?.notes).toContain("Frees 1 roster spot.");
    // Value-matched inside the ±20% band.
    expect(idea?.incoming.value).toBeGreaterThanOrEqual((idea?.outgoing.value ?? 0) * 0.8);
    expect(idea?.incoming.value).toBeLessThanOrEqual((idea?.outgoing.value ?? 0) * 1.2);
  });

  it("refuses the trade that only moves the hole: a valuable starter for the target", () => {
    const players = {
      ...CORE,
      wr2: { position: "WR" as const, q50: 14, vorp: 20, posRank: 12 },
      te: { position: "TE" as const, q50: 4, vorp: 2, posRank: 19 },
      freeTe: { position: "TE" as const, q50: 9, vorp: 20, posRank: 6 },
    };
    const result = improveRoster(input(players, league(CORE_LINEUP)));
    const need = result.needs.find((entry) => entry.slot.group === "TE");
    // wr2 alone prices exactly at freeTe's value, but giving him leaves WR2 empty: refused.
    expect(need?.packages.some((idea) => idea.give.some((player) => player.id === "wr2") && idea.give.length === 1)).toBe(
      false,
    );
    expect(result.rejected.hole + result.rejected.new_need).toBeGreaterThan(0);
  });

  it("refuses a package that leaves the need in place, even when the lineup sum rises", () => {
    // RB 2 is on bye; the only RB target is worth exactly the second receiver. Giving that
    // receiver lets the FLEX receiver slide to WR 2 and the new back take FLEX: +1 point, but
    // RB 2 is still a bye. A need moved around is not a need fixed: refused.
    const players = {
      ...CORE,
      rb2: { position: "RB" as const, q50: null, vorp: 50, posRank: 11 },
      wr2: { position: "WR" as const, q50: 14, vorp: 45, posRank: 12 },
      freeRb: { position: "RB" as const, q50: 15, vorp: 45, posRank: 9 },
    };
    const result = improveRoster(input(players, league(CORE_LINEUP)));
    const need = result.needs.find((entry) => entry.slot.group === "RB");
    expect(need?.targets.map((target) => target.record.player_id)).toContain("freeRb");
    expect(need?.packages.some((idea) => idea.give.length === 1 && idea.give[0]?.id === "wr2")).toBe(false);
    expect(result.rejected.no_gain).toBeGreaterThan(0);
  });

  it("refuses a package that empties another group to fill the need", () => {
    // No spare receiver this time: giving the second receiver for the back fills RB 2 and
    // leaves WR 2 empty. The hole moved: refused for leaving a slot empty.
    const counts: SlotCounts = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 0, BN: 3, IR: 1 };
    const players = {
      ...CORE,
      rb2: { position: "RB" as const, q50: null, vorp: 50, posRank: 11 },
      wr2: { position: "WR" as const, q50: 14, vorp: 45, posRank: 12 },
      freeRb: { position: "RB" as const, q50: 15, vorp: 45, posRank: 9 },
    };
    const noFlex = { QB: CORE_LINEUP.QB, RB: CORE_LINEUP.RB, WR: CORE_LINEUP.WR, TE: CORE_LINEUP.TE };
    const result = improveRoster(input(players, league(noFlex, counts)));
    const need = result.needs.find((entry) => entry.slot.group === "RB");
    expect(need?.packages.some((idea) => idea.give.length === 1 && idea.give[0]?.id === "wr2")).toBe(false);
    expect(result.rejected.hole).toBeGreaterThan(0);
  });

  it("refuses a package the roster has no room for, and counts it", () => {
    const counts: SlotCounts = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 0, IR: 1 };
    const players = {
      ...CORE,
      te: { position: "TE" as const, q50: 4, vorp: 6, posRank: 19 },
      irWr: { position: "WR" as const, q50: null, vorp: 20, posRank: 38 },
      freeTe: { position: "TE" as const, q50: 9, vorp: 20, posRank: 6 },
      freeRb: { position: "RB" as const, q50: 9, vorp: 6, posRank: 30 },
    };
    const result = improveRoster(input(players, league({ ...CORE_LINEUP, IR: ["irWr"] }, counts)));
    const need = result.needs.find((entry) => entry.slot.group === "TE");
    // Giving the IR receiver for the tight end needs an active roster spot there is not.
    expect(
      need?.packages.some((idea) => idea.give.length === 1 && idea.give[0]?.id === "irWr"),
    ).toBe(false);
    expect(result.rejected.capacity).toBeGreaterThan(0);
  });

  it("says nothing defensible exists rather than weakening a rule", () => {
    const players = { ...CORE, te: { position: "TE" as const, q50: 4, vorp: 2, posRank: 19 } };
    const result = improveRoster(input(players, league(CORE_LINEUP)));
    const need = result.needs.find((entry) => entry.slot.group === "TE");
    expect(need?.targets).toEqual([]);
    expect(need?.packages).toEqual([]);
  });

  it("lists a package once, under the weakest need it fixes", () => {
    const players = {
      ...CORE,
      rb2: { position: "RB" as const, q50: null, vorp: 50, posRank: 11 },
      flex: { position: "WR" as const, q50: null, vorp: 40, posRank: 20 },
      benchWr: { position: "WR" as const, q50: 8, vorp: 30, posRank: 40 },
      freeRb: { position: "RB" as const, q50: 15, vorp: 80, posRank: 4 },
    };
    const result = improveRoster(input(players, league({ ...CORE_LINEUP, BN: ["benchWr"] })));
    const keys = result.needs.flatMap((need) => need.packages.map((idea) => idea.key));
    expect(keys.length).toBeGreaterThan(0);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("is deterministic", () => {
    const players = {
      ...CORE,
      te: { position: "TE" as const, q50: 4, vorp: 6, posRank: 19 },
      benchWr: { position: "WR" as const, q50: 8, vorp: 12, posRank: 40 },
      freeTe: { position: "TE" as const, q50: 9, vorp: 20, posRank: 6 },
      freeTe2: { position: "TE" as const, q50: 8.5, vorp: 18, posRank: 7 },
    };
    const first = improveRoster(input(players, league({ ...CORE_LINEUP, BN: ["benchWr"] })));
    const second = improveRoster(input(players, league({ ...CORE_LINEUP, BN: ["benchWr"] })));
    expect(second.needs.map((need) => need.packages.map((idea) => idea.key))).toEqual(
      first.needs.map((need) => need.packages.map((idea) => idea.key)),
    );
  });
});
