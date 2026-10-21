/**
 * ADR-114: Sleeper's add and drop feeds are two separate top-100 lists, read one side at a time.
 *
 * The case these pin is the one the owner reported: on the retained 2026-10-17 capture Tyler
 * Allgeier had 549,030 adds and was outside the drop feed, whose smallest count was 17,444, and
 * the board printed his net as +549,030. The numbers below are those two real numbers on a
 * synthetic row; nothing here claims to reproduce today's API.
 */

import { describe, expect, it } from "vitest";

import {
  describeNet,
  describeSide,
  formatNet,
  formatSide,
  netAdds,
  netIsPositive,
  netLowerBound,
  netSortValue,
  sideOf,
} from "../src/data/behavior";
import type { OpportunityRecord } from "../src/data/contracts";
import { isPotwCandidate } from "../src/data/potw";
import { opportunityRecords, unprojectedRecords } from "./fixtures/artifacts";

type Behaviour = Pick<
  OpportunityRecord,
  | "behavior_available"
  | "add_count"
  | "drop_count"
  | "net_add_count"
  | "add_state"
  | "drop_state"
  | "add_count_max"
  | "drop_count_max"
  | "add_rank"
  | "drop_rank"
>;

const ALLGEIER: Behaviour = {
  behavior_available: true,
  add_state: "observed",
  drop_state: "not_in_feed",
  add_count: 549_030,
  drop_count: null,
  add_count_max: null,
  drop_count_max: 17_444,
  net_add_count: null,
  add_rank: 1,
  drop_rank: null,
};

describe("one side at a time", () => {
  it("never reads an absent side as zero", () => {
    expect(sideOf(ALLGEIER, "drop")).toEqual({ state: "not_in_feed", count: null, max: 17_444 });
    expect(sideOf(ALLGEIER, "add")).toEqual({ state: "observed", count: 549_030, max: null });
  });

  it("prints the 2026-10-17 net as the bound it is, not +549,030", () => {
    const net = netAdds(ALLGEIER);
    expect(net).toEqual({ kind: "bounded", min: 531_586, max: 549_030, known: "add" });
    expect(formatNet(net)).toBe("≥ +531,586");
    expect(describeNet(ALLGEIER)).toBe("net at least +531,586 (drops not in Sleeper's top 100)");
    expect(netSortValue(net)).toBe(531_586);
    expect(netLowerBound(ALLGEIER)).toBe(531_586);
    expect(netIsPositive(ALLGEIER)).toBe(true);
  });

  it("bounds a drop-only player from above and proves nothing positive", () => {
    const dropOnly: Behaviour = {
      ...ALLGEIER,
      add_state: "not_in_feed",
      drop_state: "observed",
      add_count: null,
      drop_count: 80_000,
      add_count_max: 9_546,
      drop_count_max: null,
      add_rank: null,
      drop_rank: 3,
    };
    const net = netAdds(dropOnly);
    expect(net).toEqual({ kind: "bounded", min: -80_000, max: -70_454, known: "drop" });
    expect(formatNet(net)).toBe("≤ −70,454");
    expect(netIsPositive(dropOnly)).toBe(false);
    expect(netLowerBound(dropOnly)).toBeNull();
  });

  it("keeps an exact net only when both sides were observed, including a real zero", () => {
    const both: Behaviour = { ...ALLGEIER, drop_state: "observed", drop_count: 0, drop_count_max: null, net_add_count: 549_030 };
    expect(netAdds(both)).toEqual({ kind: "exact", value: 549_030 });
    expect(formatSide(sideOf(both, "drop"))).toBe("0");
  });

  it("names unreachable, stale and unavailable sides, and gives them no number", () => {
    for (const state of ["no_sleeper_id", "ambiguous_sleeper_id", "stale", "unavailable"] as const) {
      const row: Behaviour = { ...ALLGEIER, add_state: state, add_count: null, drop_state: state, drop_count_max: null };
      expect(netAdds(row)).toEqual({ kind: "unknown" });
      expect(formatNet(netAdds(row))).toBe("—");
      expect(formatSide(sideOf(row, "add"))).toBe("—");
      expect(describeSide(sideOf(row, "add"), "add")).not.toMatch(/\d/);
    }
  });

  it("reads a 1.2 row's zero with no feed rank as an absence, never as a measured zero", () => {
    const legacy: Behaviour = {
      behavior_available: true,
      add_count: 549_030,
      drop_count: 0,
      net_add_count: 549_030,
      add_rank: 1,
      drop_rank: null,
    };
    expect(sideOf(legacy, "drop")).toEqual({ state: "not_in_feed", count: null, max: null });
    expect(netAdds(legacy)).toEqual({ kind: "unknown" });
    // A 1.2 row whose zero came with a feed rank was in the feed: that zero is a reading.
    expect(sideOf({ ...legacy, drop_rank: 90 }, "drop").state).toBe("observed");
  });
});

describe("Pick of the Week's direction gate", () => {
  const floor = { value: 100, count: 5, fromPopulation: true };
  const pick = (behaviour: Behaviour): OpportunityRecord => {
    const base = opportunityRecords().find((record) => record.ros_expected_vorp > 0 && !record.long_absence);
    if (base === undefined) throw new Error("fixture has no playable row");
    return { ...base, current_status: null, ...behaviour };
  };

  it("passes a one-sided row only when its bound is positive", () => {
    expect(isPotwCandidate(pick(ALLGEIER), floor)).toBe(true);
    const marginal: Behaviour = { ...ALLGEIER, add_count: 17_000 };
    expect(netIsPositive(marginal)).toBe(false);
    expect(isPotwCandidate(pick(marginal), floor)).toBe(false);
  });
});

describe("the browser fixture expresses every state", () => {
  it("carries both-observed, one-sided and in-neither rows", () => {
    const states = new Set(
      [...opportunityRecords(), ...unprojectedRecords()].map((row) => `${String(row.add_state)}/${String(row.drop_state)}`),
    );
    expect(states).toContain("observed/observed");
    expect(states).toContain("observed/not_in_feed");
    expect(states).toContain("not_in_feed/not_in_feed");
  });

  it("publishes no count for any side it did not observe", () => {
    for (const row of [...opportunityRecords(), ...unprojectedRecords()]) {
      expect(row.add_count === null).toBe(row.add_state !== "observed");
      expect(row.drop_count === null).toBe(row.drop_state !== "observed");
      expect(row.net_add_count !== null).toBe(row.add_state === "observed" && row.drop_state === "observed");
    }
  });
});
