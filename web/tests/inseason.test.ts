/**
 * The in-season presentation helpers (ADR-085), and the two label helpers ADR-084 left open.
 *
 * Small pure functions, and each encodes a judgement that goes silently wrong when the data
 * moves — which is exactly the category `charts.test.ts` exists for. They are tested against
 * the shapes that actually occur rather than against the shape of today's board.
 */

import { describe, expect, it } from "vitest";

import { movesBound } from "../src/charts/OpportunityBoard";
import { longAbsenceLabel, rankChangeLabel, rosStatusBadge } from "../src/data/ros";

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
