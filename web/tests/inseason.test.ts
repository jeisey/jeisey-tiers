/**
 * The in-season presentation helpers (ADR-085), and the two label helpers ADR-084 left open.
 *
 * Small pure functions, and each encodes a judgement that goes silently wrong when the data
 * moves — which is exactly the category `charts.test.ts` exists for. They are tested against
 * the shapes that actually occur rather than against the shape of today's board.
 */

import { describe, expect, it } from "vitest";

import {
  InSeasonBundle,
  buildRosCohortContext,
  longAbsenceLabel,
  movesBound,
  projectedRemainingRate,
  rankChangeLabel,
  rosStatusBadge,
  rosTierPlacement,
  scoredRate,
  type RosCohortContext,
} from "../src/data/ros";
import type { RosTierRecord } from "../src/data/contracts";
import { required } from "./required";
import { opportunityRecords, rosBuildMetadata, rosTierRecords } from "./fixtures/artifacts";

describe("rosStatusBadge", () => {
  it("says nothing for the ordinary roster codes", () => {
    // `ACT` on five hundred rows is five hundred repetitions of "nothing to report". ADR-043's
    // rule is that the absence of a designation is never a report, and this is where the
    // in-season board obeys it.
    for (const code of ["ACT", "act", "A01", "DEV"]) {
      expect(rosStatusBadge(code), code).toBeNull();
    }
  });

  it("says nothing for an absent or blank status", () => {
    expect(rosStatusBadge(null)).toBeNull();
    expect(rosStatusBadge(undefined)).toBeNull();
    expect(rosStatusBadge("   ")).toBeNull();
  });

  it("renders a noteworthy code verbatim, and names it where it can", () => {
    const badge = rosStatusBadge("RES");
    expect(badge?.short).toBe("RES");
    expect(badge?.full).toBe("Reserve");
    expect(badge?.severity).toBe("warn");
  });

  it("renders a code it cannot name as itself rather than as a guess", () => {
    // ADR-082's lesson, in the other direction: a check that enumerated the day's roster codes
    // failed a correct board. A *renderer* that enumerates them would print a wrong expansion
    // instead, which is worse — it would put a designation in front of a reader that the
    // artifact never made.
    const badge = rosStatusBadge("TRC");
    expect(badge?.short).toBe("TRC");
    expect(badge?.full).toBe("TRC");
    expect(badge?.severity).toBe("caution");
  });

  it("marks inactive as the code ADR-082 met in production", () => {
    // `INA` is nflverse's code for a player declared inactive. It is noteworthy, it is severe,
    // and the badge that carried it was correct when a check refused it.
    expect(rosStatusBadge("INA")).toEqual({
      short: "INA",
      full: "Inactive",
      severity: "warn",
    });
  });

  it("normalises case, because a feed's casing is not a semantic", () => {
    expect(rosStatusBadge("res")?.short).toBe("RES");
  });
});

describe("movesBound", () => {
  it("sizes the moves axis to the population rather than to one waiver-wire spike", () => {
    // The shape production actually produces: a board of quiet rows and one player every
    // league is adding at once. Scaling to him draws every other row as a hairline, which
    // hides the comparison the track exists for.
    const counts = [...Array.from({ length: 20 }, (_, i) => i + 1), 2400];
    expect(movesBound(counts)).toBeLessThan(100);
    expect(movesBound(counts)).toBeGreaterThan(0);
  });

  it("ignores zeros, which are most of a quiet board", () => {
    // A board where nothing moved except one player must still draw that one player, not
    // scale the axis to a percentile of zeros.
    expect(movesBound([0, 0, 0, 0, 0, 0, 0, 0, 0, 12])).toBe(12);
  });

  it("never collapses below one, so a bar is never divided by zero", () => {
    expect(movesBound([])).toBe(1);
    expect(movesBound([0, 0, 0])).toBe(1);
  });

  it("is the largest count when every count is the same", () => {
    expect(movesBound([8, 8, 8, 8])).toBe(8);
  });

  it("returns a whole number, because these are counts of transactions", () => {
    // The axis step is derived from this and floors at 1, so a quiet board's ticks read
    // "1 · 0 · 1" rather than labelling half a roster move.
    for (const counts of [[3], [1, 1, 1], [0, 7], []]) {
      expect(Number.isInteger(movesBound(counts)), JSON.stringify(counts)).toBe(true);
    }
  });
});

/*
 * The two label helpers `verify-real-build.mjs` deliberately does not compare.
 *
 * ADR-084 left them out of the verifier on purpose — they render sentences the component
 * chooses, and restating that table in a check would make the check a transcription of the
 * code it checks. It also recorded that nothing else covered them, which is this. The fix
 * belongs here rather than there.
 */
describe("rankChangeLabel", () => {
  it("signs a move so the direction survives without colour", () => {
    // Positive means the model likes him more now than it did in August. The sign is the
    // reading; `AGENTS.md` section 11 forbids leaving that to the green and the red alone.
    expect(rankChangeLabel(9)).toBe("+9");
    expect(rankChangeLabel(-12)).toBe("-12");
  });

  it("prints an unmoved rank as zero, not as a blank", () => {
    // "He has not moved" and "we do not know" are different facts and must look different.
    expect(rankChangeLabel(0)).toBe("0");
  });

  it("prints an em dash where there is no preseason rank to compare against", () => {
    expect(rankChangeLabel(null)).toBe("—");
    expect(rankChangeLabel(undefined)).toBe("—");
  });
});

describe("longAbsenceLabel", () => {
  it("says only what is known: a number of weeks without an appearance", () => {
    expect(longAbsenceLabel({ weeks_since_last_game: 4 })).toBe("Has not appeared for 4 weeks");
  });

  it("agrees with itself at one week", () => {
    expect(longAbsenceLabel({ weeks_since_last_game: 1 })).toBe("Has not appeared for 1 week");
  });

  it("rounds a fractional week rather than printing one", () => {
    expect(longAbsenceLabel({ weeks_since_last_game: 3.4 })).toBe("Has not appeared for 3 weeks");
  });

  it("never produces a word that reads as a designation", () => {
    // ADR-076: the model has no injury or practice-report information, so nothing it emits may
    // read as a status. This is the one sentence the flag is allowed to say.
    for (const weeks of [1, 2, 5, 11]) {
      expect(longAbsenceLabel({ weeks_since_last_game: weeks })).not.toMatch(
        /out|questionable|doubtful|injur|ir\b|reserve/i,
      );
    }
  });
});

describe("projectedRemainingRate", () => {
  it("is the model's remaining points divided by its remaining games", () => {
    // Two published totals, divided. Both halves are `ros_label_v1`'s own decomposition, which
    // is what makes the comparison with `points_per_game_to_date` a comparison at all rather
    // than a blend of unlike units (ADR-086).
    expect(
      projectedRemainingRate({ ros_expected_points: 118.6, ros_expected_games: 12.5 }),
    ).toBeCloseTo(9.488, 3);
  });

  it("says nothing where the model expects no remaining appearances", () => {
    // A real state at the end of a season and after a season-ending absence. An absence, never
    // a zero and never an Infinity in a style attribute.
    expect(projectedRemainingRate({ ros_expected_points: 0, ros_expected_games: 0 })).toBeNull();
    expect(projectedRemainingRate({ ros_expected_points: 40, ros_expected_games: -1 })).toBeNull();
  });

  it("says nothing where a total is not a finite number", () => {
    expect(
      projectedRemainingRate({ ros_expected_points: Number.NaN, ros_expected_games: 8 }),
    ).toBeNull();
  });
});

describe("scoredRate", () => {
  const base = {
    points_per_game_to_date: 11.9,
    games_played_to_date: 1,
    points_to_date: 11.9,
  } as unknown as RosTierRecord;

  it("prefers the published field over recomputing it", () => {
    expect(scoredRate(base)).toBe(11.9);
  });

  it("falls back to the two totals when the build published no rate", () => {
    const record = { ...base, points_per_game_to_date: undefined } as unknown as RosTierRecord;
    expect(scoredRate(record)).toBeCloseTo(11.9, 6);
  });

  it("says nothing for a player who has not appeared, rather than a zero rate", () => {
    // Dividing by no games is not a rate of zero: he has no rate. The pace rail draws one as
    // an absence and says why, which is a different sentence from "he scored nothing".
    const record = {
      ...base,
      points_per_game_to_date: null,
      games_played_to_date: 0,
      points_to_date: 0,
    } as unknown as RosTierRecord;
    expect(scoredRate(record)).toBeNull();
  });
});

describe("rosTierPlacement", () => {
  function row(rank: number, tier: number | null, id = `p${String(rank)}`): RosTierRecord {
    return {
      player_id: id,
      ros_fair_rank: rank,
      ros_tier: tier,
      ros_tier_label: tier === null ? null : `Tier ${String(tier + 1)}`,
    } as unknown as RosTierRecord;
  }

  /** The nth row of a just-built list; `required` keeps the index honest without a `!`. */
  function at(rows: readonly RosTierRecord[], index: number): RosTierRecord {
    return required(rows[index], `row ${String(index)}`);
  }

  it("places a player inside his own band, in published rank order", () => {
    const rows = [row(1, 0), row(2, 0), row(3, 0), row(4, 1)];
    expect(rosTierPlacement(rows, at(rows, 1))).toEqual({ label: "Tier 1", place: 2, size: 3 });
  });

  it("says nothing for a player with no tier — a surfaced row has no band to sit in", () => {
    const rows = [row(1, 0), row(2, 0), row(3, 0), row(99, null, "surfaced")];
    expect(rosTierPlacement(rows, at(rows, 3))).toBeNull();
  });

  it("says nothing for a band of one, where a place is the whole band", () => {
    const rows = [row(1, 0), row(2, 1), row(3, 1)];
    expect(rosTierPlacement(rows, at(rows, 0))).toBeNull();
  });

  it("ignores rows from another tier when counting the band", () => {
    const rows = [row(1, 0), row(2, 1), row(3, 0), row(4, 1), row(5, 0)];
    expect(rosTierPlacement(rows, at(rows, 4))).toEqual({ label: "Tier 1", place: 3, size: 3 });
  });
});

describe("buildRosCohortContext", () => {
  const bundle = new InSeasonBundle({
    metadata: rosBuildMetadata(),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(),
    opportunityDegradation: null,
  });
  const block = { leaguePreset: "redraft-12", scoring: "PPR" } as const;
  const rows = bundle.rosFor(block.leaguePreset, block.scoring);
  const subject = required(
    rows.find((row) => row.position === "WR"),
    "a wide receiver on the fixture board",
  );

  function contextFor(record: RosTierRecord): RosCohortContext {
    return buildRosCohortContext(
      bundle,
      block.leaguePreset,
      block.scoring,
      record,
      bundle.opportunityRecordFor(block.leaguePreset, block.scoring, record.player_id),
    );
  }

  it("names the population and counts it", () => {
    const context = contextFor(subject);
    expect(context.noun).toBe("WRs");
    expect(context.boardCount).toBe(
      rows.filter((row) => row.position === "WR").length,
    );
  });

  it("compares a player only against his own position", () => {
    const context = contextFor(subject);
    // Every cohort reading's denominator is the position's row count, never the board's.
    expect(context.vorp?.count).toBe(context.boardCount);
    expect(context.uncertainty?.count).toBe(context.boardCount);
    expect(context.boardDepth).toBe(rows.length);
    expect(context.boardDepth).toBeGreaterThan(context.boardCount);
  });

  it("puts the board's best remaining value first in its own position", () => {
    const best = rows
      .filter((row) => row.position === "WR")
      .reduce((a, b) => (a.ros_vorp_p50 >= b.ros_vorp_p50 ? a : b));
    expect(contextFor(best).vorp?.rank).toBe(1);
  });

  it("leaves rows that have not appeared out of the scoring-rate cohort", () => {
    const context = contextFor(subject);
    const played = rows.filter((row) => row.position === "WR" && row.games_played_to_date > 0);
    expect(context.scoredRate?.count).toBe(played.length);
  });

  it("bounds the moves axis from the whole block, the way the board does", () => {
    const counts = bundle
      .opportunityFor(block.leaguePreset, block.scoring)
      .flatMap((row) => [row.add_count, row.drop_count])
      .filter((value): value is number => typeof value === "number");
    expect(contextFor(subject).movesAxis).toBe(movesBound(counts));
  });

  it("says nothing about a share the feed did not publish for this player", () => {
    const silent = required(
      rows.find(
        (row) =>
          bundle.opportunityRecordFor(block.leaguePreset, block.scoring, row.player_id)
            ?.snap_share_last3 == null,
      ),
      "a fixture row whose usage shares the feed never published",
    );
    expect(contextFor(silent).snapShare).toBeNull();
  });

  it("places a share on an absolute axis, not on the cohort's own range", () => {
    // 91% of snaps means the same thing whoever else is on the board, so the axis is 0 to 1.
    const context = contextFor(subject);
    expect(context.snapShare?.axisLow).toBe(0);
    expect(context.snapShare?.axisHigh).toBe(1);
  });
});
