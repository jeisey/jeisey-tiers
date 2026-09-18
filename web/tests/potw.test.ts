/**
 * The Pick-of-the-Week engine.
 *
 * Two of these tests exist because of a rule rather than because of a behaviour, and they are
 * the ones to keep if the rest are ever rewritten:
 *
 * - **the gate is not a weighting.** `AGENTS.md` section 10 forbids blending an add count with
 *   a value, and a reviewer cannot check that by reading a sort comparator. The pair of tests
 *   under "membership and ordering are separate questions" checks it behaviourally: hold the
 *   adds fixed and the winner tracks the VORP; raise one candidate's adds far above every
 *   other and the winner does not move. A blend of any weight fails the second.
 * - **the availability claim is a count, never a share.** Nothing the engine emits may read as
 *   a percentage of leagues, because no source this project may publish from reports one
 *   (ADR-088). The reasons are asserted for what they say.
 */

import { describe, expect, it } from "vitest";

import type { OpportunityRecord, Position } from "../src/data/contracts";
import {
  POTW_MAX_SETS,
  addFloorFor,
  buildPotwBoard,
  clampSet,
  isPotwCandidate,
  visiblePicks,
} from "../src/data/potw";
import { InSeasonBundle } from "../src/data/ros";
import {
  FIXTURE_BEHAVIOR_LOOKBACK_HOURS,
  rosBuildMetadata,
  rosTierRecords,
} from "./fixtures/artifacts";

const LEAGUE = "redraft-12";
const SCORING = "PPR" as const;

/** A minimal opportunity row. Every field a gate reads is a named argument. */
function row(
  overrides: Partial<OpportunityRecord> & { player_id: string; position: Position },
): OpportunityRecord {
  const adds = overrides.add_count ?? 1000;
  const drops = overrides.drop_count ?? 10;
  return {
    schema_version: "1.0",
    build_id: "test-build",
    season: 2026,
    through_week: 3,
    league_preset_id: LEAGUE,
    scoring_preset: SCORING,
    display_name: `Player ${overrides.player_id}`,
    team: "SF",
    ros_fair_rank: 100,
    ros_position_rank: 10,
    ros_expected_vorp: 10,
    ros_expected_points: 90,
    ros_expected_games: 9,
    ros_uncertainty: 20,
    ros_tier: 3,
    behavior_source_id: "sleeper",
    behavior_available: true,
    behavior_snapshot_at_utc: "2026-09-18T11:00:00Z",
    behavior_lookback_hours: FIXTURE_BEHAVIOR_LOOKBACK_HOURS,
    behavior_request_limit: 100,
    add_count: adds,
    drop_count: drops,
    net_add_count: adds - drops,
    add_rank: 1,
    drop_rank: 1,
    long_absence: false,
    weeks_since_last_game: 0,
    games_played_to_date: 3,
    snap_share_last3: 0.6,
    target_share_last3: 0.2,
    current_status: null,
    outside_tier_board: false,
    surface_reasons: ["intrinsic_top_tier_depth"],
    quality_flags: [],
    ...overrides,
  };
}

/** A bundle carrying exactly these opportunity rows, over the fixture's ROS board. */
function bundleOf(rows: readonly OpportunityRecord[]): InSeasonBundle {
  return new InSeasonBundle({
    metadata: rosBuildMetadata(),
    rosTiers: rosTierRecords(),
    opportunity: [...rows],
    opportunityDegradation: null,
  });
}

function board(rows: readonly OpportunityRecord[]) {
  return buildPotwBoard(bundleOf(rows), LEAGUE, SCORING);
}

/** Four rows at one position with the given (adds, vorp) pairs. */
function candidates(
  position: Position,
  pairs: readonly (readonly [number, number])[],
): OpportunityRecord[] {
  return pairs.map(([adds, vorp], index) =>
    row({
      player_id: `${position}-${String(index)}`,
      position,
      add_count: adds,
      drop_count: 1,
      net_add_count: adds - 1,
      ros_expected_vorp: vorp,
      ros_fair_rank: 100 + index,
    }),
  );
}

describe("the add floor", () => {
  it("is the median of the position's own non-zero add counts", () => {
    const rows = candidates("WR", [
      [100, 1],
      [200, 1],
      [300, 1],
      [400, 1],
      [500, 1],
    ]);
    const floor = addFloorFor(rows, "WR");
    expect(floor.value).toBe(300);
    expect(floor.count).toBe(5);
    expect(floor.fromPopulation).toBe(true);
  });

  it("is taken per position, because two positions are two markets", () => {
    const rows = [
      ...candidates("WR", [
        [1000, 1],
        [2000, 1],
        [3000, 1],
      ]),
      ...candidates("TE", [
        [10, 1],
        [20, 1],
        [30, 1],
      ]),
    ];
    expect(addFloorFor(rows, "WR").value).toBe(2000);
    expect(addFloorFor(rows, "TE").value).toBe(20);
  });

  it("ignores rows the feed never counted rather than reading them as zero", () => {
    const rows = [
      ...candidates("RB", [
        [100, 1],
        [200, 1],
        [300, 1],
      ]),
      row({ player_id: "RB-none", position: "RB", add_count: null, net_add_count: null }),
      row({ player_id: "RB-zero", position: "RB", add_count: 0, net_add_count: 0 }),
    ];
    // Five rows, three counts. A zero is a count the feed did publish and still sets no bar,
    // because a bar of zero is not a bar.
    expect(addFloorFor(rows, "RB")).toMatchObject({ value: 200, count: 3, fromPopulation: true });
  });

  it("falls back to 'the feed saw him' when the population is too small, and says so", () => {
    const floor = addFloorFor(candidates("QB", [[900, 1]]), "QB");
    expect(floor).toMatchObject({ value: 1, count: 1, fromPopulation: false });
  });

  it("rounds a fractional median up, because half a transaction is not a bar", () => {
    const floor = addFloorFor(
      candidates("WR", [
        [100, 1],
        [101, 1],
        [102, 1],
        [103, 1],
      ]),
      "WR",
    );
    expect(floor.value).toBe(102);
  });
});

describe("the gates", () => {
  const floor = { value: 500, count: 9, fromPopulation: true };

  it("admits a row that clears every one", () => {
    expect(isPotwCandidate(row({ player_id: "a", position: "WR" }), floor)).toBe(true);
  });

  it("refuses a row the feed never counted — no evidence is not evidence of nothing", () => {
    const record = row({ player_id: "a", position: "WR", add_count: null, net_add_count: null });
    expect(isPotwCandidate(record, floor)).toBe(false);
  });

  it("refuses a row under the bar", () => {
    const record = row({
      player_id: "a",
      position: "WR",
      add_count: 499,
      drop_count: 1,
      net_add_count: 498,
    });
    expect(isPotwCandidate(record, floor)).toBe(false);
  });

  it("refuses a row the wire is net shedding, however many adds it has", () => {
    const record = row({
      player_id: "a",
      position: "WR",
      add_count: 5000,
      drop_count: 6000,
      net_add_count: -1000,
    });
    expect(isPotwCandidate(record, floor)).toBe(false);
  });

  it("refuses a long absence, where the model's own ordering is near-random", () => {
    const record = row({
      player_id: "a",
      position: "WR",
      long_absence: true,
      weeks_since_last_game: 4,
    });
    expect(isPotwCandidate(record, floor)).toBe(false);
  });

  it("refuses a severe roster code and admits an ordinary one", () => {
    for (const code of ["RES", "INA", "PUP", "NFI", "SUS", "CUT", "RET"]) {
      const record = row({ player_id: code, position: "WR", current_status: code });
      expect(isPotwCandidate(record, floor), `${code} should not be a pick`).toBe(false);
    }
    for (const code of ["ACT", "A01", "DEV"]) {
      const record = row({ player_id: code, position: "WR", current_status: code });
      expect(isPotwCandidate(record, floor), `${code} should be eligible`).toBe(true);
    }
  });

  it("refuses a player worth no more than the wire he would come off", () => {
    // The in-season replacement rule is `rostered_depth` — the best unrostered player — so a
    // remaining VORP at or below zero is the model saying he is not an upgrade on waivers.
    for (const vorp of [0, -0.4, -12]) {
      const record = row({ player_id: "a", position: "WR", ros_expected_vorp: vorp });
      expect(isPotwCandidate(record, floor), `VORP ${String(vorp)} should not be a pick`).toBe(
        false,
      );
    }
    expect(
      isPotwCandidate(row({ player_id: "a", position: "WR", ros_expected_vorp: 0.1 }), floor),
    ).toBe(true);
  });

  it("refuses every row when the behaviour feed is down", () => {
    const record = row({
      player_id: "a",
      position: "WR",
      behavior_available: false,
      add_count: null,
      net_add_count: null,
    });
    expect(isPotwCandidate(record, floor)).toBe(false);
  });

  it("does not require a tier — a surfaced player is who this feature exists to find", () => {
    const record = row({
      player_id: "a",
      position: "WR",
      ros_tier: null,
      outside_tier_board: true,
      surface_reasons: ["sleeper_trending_add"],
    });
    expect(isPotwCandidate(record, floor)).toBe(true);
  });
});

describe("membership and ordering are separate questions", () => {
  /*
    The pair that stands in for `AGENTS.md` section 10. A blended score — any weighting of a
    count against a value — passes the first of these and fails the second.
  */
  it("orders the eligible by rest-of-season value when the adds are equal", () => {
    const rows = candidates("WR", [
      [1000, 5],
      [1000, 30],
      [1000, 12],
    ]);
    const first = board(rows).sets[0]?.picks[0];
    expect(first?.opportunity.ros_expected_vorp).toBe(30);
  });

  it("does not let a huge add count buy a place in the ordering", () => {
    const quiet = candidates("WR", [
      [1000, 5],
      [1000, 30],
      [1000, 12],
    ]);
    // The lowest-valued candidate is now added two hundred times as often as anybody else. If
    // adds carried any weight at all in the ordering he would move; he must not.
    const loud = quiet.map((record) =>
      record.ros_expected_vorp === 5
        ? { ...record, add_count: 200_000, net_add_count: 199_999 }
        : record,
    );
    const picks = board(loud).sets[0]?.picks ?? [];
    expect(picks[0]?.opportunity.ros_expected_vorp).toBe(30);
    // And he is still a candidate — the adds decided that he is in the pool, and nothing else.
    expect(board(loud).poolSizes.get("WR")).toBe(3);
  });

  it("breaks a tie on rest-of-season rank, then on player id, so a build is reproducible", () => {
    const rows = [
      row({ player_id: "b", position: "TE", ros_expected_vorp: 9, ros_fair_rank: 40 }),
      row({ player_id: "a", position: "TE", ros_expected_vorp: 9, ros_fair_rank: 40 }),
      row({ player_id: "c", position: "TE", ros_expected_vorp: 9, ros_fair_rank: 12 }),
    ];
    const picks = board(rows).sets[0]?.picks ?? [];
    expect(picks.map((pick) => pick.opportunity.player_id)).toEqual(["c"]);
    expect(board(rows).sets[1]?.picks[0]?.opportunity.player_id).toBe("a");
  });
});

describe("sets", () => {
  it("takes the nth-ranked candidate at each position", () => {
    const rows = [
      ...candidates("WR", [
        [1000, 30],
        [1000, 20],
        [1000, 10],
      ]),
      ...candidates("RB", [
        [1000, 44],
        [1000, 22],
        [1000, 11],
      ]),
    ];
    const result = board(rows);
    expect(result.sets).toHaveLength(3);
    expect(result.sets[0]?.picks.map((pick) => pick.opportunity.ros_expected_vorp)).toEqual([
      44, 30,
    ]);
    expect(result.sets[1]?.picks.map((pick) => pick.opportunity.ros_expected_vorp)).toEqual([
      22, 20,
    ]);
  });

  it("orders picks inside a set QB, RB, WR, TE whatever order the rows arrived in", () => {
    const rows = [
      row({ player_id: "te", position: "TE" }),
      row({ player_id: "qb", position: "QB" }),
      row({ player_id: "wr", position: "WR" }),
      row({ player_id: "rb", position: "RB" }),
    ];
    expect(board(rows).sets[0]?.picks.map((pick) => pick.position)).toEqual([
      "QB",
      "RB",
      "WR",
      "TE",
    ]);
  });

  it("never publishes more than five", () => {
    const rows = candidates(
      "WR",
      Array.from({ length: 9 }, (_, index) => [1000, 100 - index] as const),
    );
    expect(board(rows).sets.length).toBe(POTW_MAX_SETS);
  });

  it("names a position that has no pick at this depth, and which case it is in", () => {
    const rows = [
      ...candidates("WR", [
        [1000, 30],
        [1000, 20],
      ]),
      ...candidates("RB", [[1000, 44]]),
    ];
    const result = board(rows);
    // RB has one candidate, WR two. Set 2 therefore has a WR and no RB, and the reason is
    // that the pool ran out rather than that nobody qualified.
    expect(result.sets[1]?.absent.get("RB")).toBe("set_deeper_than_pool");
    // QB and TE had no rows at all.
    expect(result.sets[0]?.absent.get("QB")).toBe("none_eligible");
    expect(result.sets[0]?.absent.get("TE")).toBe("none_eligible");
  });

  it("publishes no set when the feed is down, and says which case that is", () => {
    const rows = candidates("WR", [
      [1000, 30],
      [1000, 20],
      [1000, 10],
    ]).map((record) => ({
      ...record,
      behavior_available: false,
      add_count: null,
      drop_count: null,
      net_add_count: null,
    }));
    const result = board(rows);
    expect(result.behaviorAvailable).toBe(false);
    expect(result.sets).toHaveLength(0);
  });
});

describe("the pick a card renders", () => {
  it("carries the opportunity row and the rest-of-season row unmodified", () => {
    const ros = rosTierRecords().find(
      (record) => record.league_preset_id === LEAGUE && record.scoring_preset === SCORING,
    );
    expect(ros).toBeDefined();
    const rows = [
      row({
        player_id: ros?.player_id ?? "",
        position: ros?.position ?? "WR",
        ros_expected_vorp: 40,
      }),
    ];
    const pick = board(rows).sets[0]?.picks[0];
    expect(pick?.opportunity.ros_expected_vorp).toBe(40);
    // The paired rest-of-season record is the published one, not a copy the engine assembled.
    expect(pick?.ros).toEqual(ros);
  });

  it("divides remaining points by remaining games and calls it nothing else", () => {
    const rows = [
      row({
        player_id: "a",
        position: "WR",
        ros_expected_points: 90,
        ros_expected_games: 9,
      }),
    ];
    expect(board(rows).sets[0]?.picks[0]?.projectedRate).toBeCloseTo(10, 6);
  });

  it("withholds the rate rather than dividing by zero remaining games", () => {
    const rows = [
      row({ player_id: "a", position: "WR", ros_expected_points: 90, ros_expected_games: 0 }),
    ];
    expect(board(rows).sets[0]?.picks[0]?.projectedRate).toBeNull();
  });

  it("states the add volume as a count with its window, and never as a share of leagues", () => {
    const rows = candidates("WR", [
      [900, 30],
      [1000, 20],
      [1100, 10],
    ]);
    const reasons = board(rows).sets[0]?.picks[0]?.reasons.join(" ") ?? "";
    expect(reasons).toContain("adds in 24h");
    expect(reasons).toContain("median");
    // The three claims this product cannot source. None may appear in a generated sentence.
    expect(reasons).not.toMatch(/%\s*rostered|rostered in|percent of leagues|owned/i);
    expect(reasons).not.toMatch(/matchup|vs\s+[A-Z]{2,3}\b/);
    expect(reasons).not.toMatch(/last 3 games|trend/i);
  });

  it("says the preseason board never ranked a breakout rather than printing a zero move", () => {
    const breakout = rosTierRecords().find(
      (record) =>
        record.league_preset_id === LEAGUE &&
        record.scoring_preset === SCORING &&
        record.preseason_fair_rank === null,
    );
    expect(breakout, "the fixture must carry a player with no preseason rank").toBeDefined();
    const rows = [
      row({ player_id: breakout?.player_id ?? "", position: breakout?.position ?? "WR" }),
    ];
    const reasons = board(rows).sets[0]?.picks[0]?.reasons ?? [];
    expect(reasons.join(" ")).toContain("preseason board never ranked him");
  });
});

describe("the set a link opens", () => {
  const three = board([
    ...candidates("WR", [
      [1000, 30],
      [1000, 20],
      [1000, 10],
    ]),
  ]);

  it("clamps a set deeper than the build produced instead of showing an empty panel", () => {
    expect(clampSet(5, three)).toBe(3);
    expect(clampSet(2, three)).toBe(2);
    expect(clampSet(0, three)).toBe(1);
    expect(clampSet(-4, three)).toBe(1);
  });

  it("clamps to 1 against a build with no sets at all", () => {
    expect(clampSet(3, board([]))).toBe(1);
  });
});

describe("the position filter", () => {
  const result = board([
    row({ player_id: "qb", position: "QB" }),
    row({ player_id: "rb", position: "RB" }),
    row({ player_id: "wr", position: "WR" }),
    row({ player_id: "te", position: "TE" }),
  ]);

  it("shows every pick under `all`", () => {
    expect(visiblePicks(result.sets[0] ?? { index: 1, picks: [], absent: new Map() }, "all")).toHaveLength(4);
  });

  it("shows one under a named position", () => {
    const set = result.sets[0] ?? { index: 1, picks: [], absent: new Map() };
    expect(visiblePicks(set, "rb").map((pick) => pick.position)).toEqual(["RB"]);
  });
});
