/**
 * The availability policy (ADR-101), one situation per test, against the evidence shapes the
 * production feeds actually publish. The two named cases are the records the 2026-10-02
 * production build carried; the policy is never told who they are.
 */

import { describe, expect, it } from "vitest";

import {
  featureable,
  readAvailability,
  rosActionable,
  startEligible,
  startExclusion,
  tradeOutgoing,
  tradeTargetBlock,
  type AvailabilityEvidence,
  type StatusEvidence,
} from "../src/data/availability";

const BUILT = "2026-10-02T15:43:05Z";
const OBSERVED = "2026-10-02T15:38:41Z";

function status(patch: Partial<StatusEvidence> = {}): StatusEvidence {
  return {
    player_id: "gsis:00-0000001",
    season: 2026,
    roster_status: "ACT",
    sleeper_status: "Active",
    injury_status: null,
    injury_body_part: null,
    observed_at_utc: OBSERVED,
    quality_flags: [],
    availability_override: null,
    ...patch,
  };
}

function read(patch: Partial<AvailabilityEvidence> = {}) {
  return readAvailability({ status: status(), referenceTime: BUILT, season: 2026, ...patch });
}

const SEASON_OVERRIDE = {
  horizon: "season" as const,
  summary: "Placed on injured reserve; reported out for the rest of the season.",
  source_urls: ["https://www.nfl.com/news/example"],
  reviewed_at: "2026-10-02",
  expires_at: "2027-01-12",
};

/** The shape of the 2026-10-02 record for a player on IR after a reported season-ending injury. */
const SEASON_ENDING = status({
  roster_status: "RES",
  sleeper_status: "Inactive",
  injury_status: "IR",
  injury_body_part: "Knee - ACL",
  availability_override: SEASON_OVERRIDE,
});

/** The shape of the 2026-10-02 record for a player ruled out, week to week, not on IR. */
const OUT_WEEK_TO_WEEK = status({ injury_status: "Out", injury_body_part: "Quadriceps" });

describe("the availability policy", () => {
  it("ends the season only on a reviewed report corroborated by a reserve list", () => {
    const reading = read({ status: SEASON_ENDING });
    expect(reading.week).toBe("unavailable");
    expect(reading.horizon).toBe("season_over");
    expect(reading.short).toBe("OUT · season");
    expect(reading.override).toEqual(SEASON_OVERRIDE);
    expect(rosActionable(reading)).toBe(false);
    expect(startEligible(reading)).toBe(false);
    expect(tradeTargetBlock(reading, true)).toBe("season_over");
    expect(tradeOutgoing(reading)).toBe("blocked");
    expect(featureable(reading)).toBe(false);
  });

  it("never infers a season-ending injury from IR or a reserve code alone", () => {
    const reading = read({ status: { ...SEASON_ENDING, availability_override: null } });
    expect(reading.horizon).toBe("unavailable_now");
    expect(reading.kind).toBe("reserve");
    expect(reading.short).toBe("IR");
    expect(reading.headline).toMatch(/return date unknown/);
    expect(reading.detail).toMatch(/does not say when he returns, or that his season is over/);
    // Muted and labelled, but still part of the rest-of-season ranking.
    expect(rosActionable(reading)).toBe(true);
    expect(startEligible(reading)).toBe(false);
    expect(tradeTargetBlock(reading, false)).toBe("unavailable_now");
    // The labelled opt-in admits a player expected back.
    expect(tradeTargetBlock(reading, true)).toBeNull();
    expect(tradeOutgoing(reading)).toBe("warn");
  });

  it("does not honour an override once both feeds clear him, and says the sources disagree", () => {
    const reading = read({ status: status({ availability_override: SEASON_OVERRIDE }) });
    expect(reading.horizon).toBe("uncertain");
    expect(reading.kind).toBe("conflict");
    expect(reading.conflict).toBe(true);
    expect(rosActionable(reading)).toBe(true);
    expect(startEligible(reading)).toBe(true);
  });

  it("ignores an expired override", () => {
    const reading = read({
      status: { ...SEASON_ENDING, availability_override: { ...SEASON_OVERRIDE, expires_at: "2026-10-01" } },
    });
    expect(reading.horizon).toBe("unavailable_now");
  });

  it("keeps OUT to this week: out of the verdict, rest of season retained with a warning", () => {
    const reading = read({ status: OUT_WEEK_TO_WEEK });
    expect(reading.week).toBe("out");
    expect(reading.horizon).toBe("caution");
    expect(startEligible(reading)).toBe(false);
    expect(startExclusion(reading)).toMatch(/left out of the verdict/);
    expect(rosActionable(reading)).toBe(true);
    expect(tradeTargetBlock(reading, false)).toBeNull();
    expect(tradeOutgoing(reading)).toBe("warn");
    expect(featureable(reading)).toBe(false);
  });

  it("excludes Doubtful from the default verdict and warns on the rest of season", () => {
    const reading = read({ report: { week: 5, designation: "Doubtful", practice_status: null, primary_injury: "Ankle" } });
    expect(reading.week).toBe("doubtful");
    expect(startEligible(reading)).toBe(false);
    expect(startExclusion(reading)).toMatch(/assume he plays/);
    expect(reading.horizon).toBe("caution");
    expect(tradeTargetBlock(reading, false)).toBeNull();
  });

  it("keeps Questionable comparable, labelled, and never removed", () => {
    const reading = read({ status: status({ injury_status: "Questionable", injury_body_part: "Hamstring" }) });
    expect(reading.week).toBe("questionable");
    expect(reading.short).toBe("Q");
    expect(startEligible(reading)).toBe(true);
    expect(rosActionable(reading)).toBe(true);
    expect(featureable(reading)).toBe(true);
    expect(tradeOutgoing(reading)).toBe("ok");
  });

  it("lets the more severe of two disagreeing designations govern, and shows both", () => {
    const reading = read({
      status: status({ injury_status: "Out" }),
      report: { week: 4, designation: "Questionable", practice_status: null, primary_injury: null },
    });
    expect(reading.week).toBe("out");
    expect(reading.conflict).toBe(true);
    expect(reading.detail).toMatch(/Questionable on the official week 4 report/);
    expect(reading.detail).toMatch(/Out on Sleeper/);
  });

  it("reads an official designation when Sleeper has none, and normalises verified aliases", () => {
    expect(read({ report: { week: 4, designation: "Out", practice_status: null, primary_injury: null } }).week).toBe("out");
    expect(read({ status: status({ injury_status: "Injured Reserve", roster_status: "RES" }) }).short).toBe("IR");
    expect(read({ status: status({ roster_status: "PUP", sleeper_status: "Physically Unable to Perform" }) }).short).toBe("PUP");
    expect(read({ status: status({ injury_status: "Sus", roster_status: "SUS" }) }).kind).toBe("reserve");
  });

  it("treats a cleared player as available, and only on current, complete evidence", () => {
    const cleared = read();
    expect(cleared.week).toBe("available");
    expect(cleared.short).toBeNull();
    expect(cleared.headline).not.toMatch(/healthy/i);
    expect(featureable(cleared)).toBe(true);
    expect(tradeOutgoing(cleared)).toBe("ok");
  });

  it("recovers when a reserve status clears", () => {
    expect(read({ status: SEASON_ENDING }).horizon).toBe("season_over");
    // The next build: activated, Sleeper active, override still on file — not honoured.
    const back = read({ status: { ...status({ availability_override: SEASON_OVERRIDE }) } });
    expect(back.horizon).not.toBe("season_over");
    expect(startEligible(back)).toBe(true);
  });

  it("says unknown — never healthy — for missing, stale, refused or other-season evidence", () => {
    const missing = readAvailability({ status: null, rosterCode: "ACT", referenceTime: BUILT, season: 2026 });
    expect(missing.week).toBe("uncertain");
    expect(missing.headline).toBe("Status unknown");

    const stale = read({ status: status({ observed_at_utc: "2026-09-28T11:00:00Z" }) });
    expect(stale.kind).toBe("stale");
    expect(stale.week).toBe("uncertain");

    for (const flag of ["sleeper_unavailable", "sleeper_record_missing", "sleeper_identity_conflict"]) {
      const refused = read({ status: status({ quality_flags: [flag] }) });
      expect(refused.week).toBe("uncertain");
    }

    const lastYear = read({ status: status({ season: 2025, injury_status: "Out" }) });
    expect(lastYear.kind).toBe("unknown");

    // Uncertain stays comparable and inspectable, and is never featured or removed.
    for (const reading of [missing, stale]) {
      expect(startEligible(reading)).toBe(true);
      expect(rosActionable(reading)).toBe(true);
      expect(tradeTargetBlock(reading, false)).toBeNull();
      expect(tradeOutgoing(reading)).toBe("warn");
    }
  });

  it("calls a disagreement between reserve list and active feed a conflict, not a clearance", () => {
    const reading = read({ status: status({ roster_status: "RES" }) });
    expect(reading.kind).toBe("conflict");
    expect(reading.week).toBe("uncertain");
    expect(featureable(reading)).toBe(false);
  });

  it("falls back to the board's roster code without a status record", () => {
    const reading = readAvailability({ status: null, rosterCode: "RES", referenceTime: BUILT, season: 2026 });
    expect(reading.horizon).toBe("unavailable_now");
  });

  it("separates released, retired and inactive", () => {
    expect(read({ status: status({ roster_status: "CUT", sleeper_status: null }) }).headline).toMatch(/Released/);
    const retired = read({ status: status({ roster_status: "RET" }) });
    expect(retired.horizon).toBe("season_over");
    const inactive = read({ status: status({ roster_status: "INA" }) });
    expect(inactive.week).toBe("uncertain");
    expect(inactive.horizon).toBe("caution");
    expect(startEligible(inactive)).toBe(true);
    expect(featureable(inactive)).toBe(false);
    expect(tradeTargetBlock(inactive, false)).toBeNull();
  });
});
