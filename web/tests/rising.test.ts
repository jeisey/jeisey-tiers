/**
 * Rising Stars (ADR-106, `rising_stars_v1`): the Opportunity Board's AND rule read through its
 * own predicates, missing and stale evidence, roster and availability exclusions, single-
 * position ordering by the published change, and the narrow FLEX comparator — with the
 * Opportunity Board's own semantics unchanged.
 */

import { describe, expect, it } from "vitest";

import {
  compareRole,
  flexRoleMagnitudeOrder,
  hasEvidence,
  opportunityCandidate,
  passesFilter,
  roleOrderingFor,
  type OpportunityCandidate,
} from "../src/data/candidates";
import { InSeasonBundle } from "../src/data/ros";
import { RISING_LIMIT, selectRisingStars } from "../src/data/rising";
import {
  behaviorSeriesRecords,
  inSeasonPlayerStatusRecords,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  teamMatchupRecords,
  unprojectedRecords,
  usageRecords,
  weeklyProjectionRecords,
} from "./fixtures/artifacts";

function bundle(options: { signals?: boolean; series?: boolean; opportunity?: boolean } = {}): InSeasonBundle {
  return new InSeasonBundle({
    metadata: rosBuildMetadata({}, true),
    rosTiers: rosTierRecords(),
    opportunity: options.opportunity === false ? null : [...opportunityRecords(true), ...unprojectedRecords(true)],
    opportunityDegradation: null,
    behaviorSeries: options.series === false ? null : behaviorSeriesRecords(),
    usage: options.signals === false ? null : usageRecords(),
    matchups: teamMatchupRecords(),
    weekly: weeklyProjectionRecords(),
    status: inSeasonPlayerStatusRecords(),
  });
}

function candidatesOf(source: InSeasonBundle): OpportunityCandidate[] {
  return source
    .opportunityFor("redraft-12", "PPR")
    .map((record) => opportunityCandidate(source, { record, rank: 0 }));
}

describe("membership", () => {
  it("is exactly the Opportunity Board's role AND momentum conjunction, minus the roster", () => {
    const source = bundle();
    const selection = selectRisingStars(source, "redraft-12", "PPR", new Set());
    expect(selection.kind).toBe("ready");
    if (selection.kind !== "ready") return;
    const listed = new Set(
      Object.values(selection.groups).flatMap((stars) => stars.map((star) => star.record.player_id)),
    );
    const both = candidatesOf(source).filter(
      (candidate) => passesFilter(candidate, "role") && passesFilter(candidate, "momentum"),
    );
    // Every listed player passes both predicates; nobody passing only one is listed.
    for (const candidate of candidatesOf(source)) {
      const id = candidate.row.record.player_id;
      if (listed.has(id)) {
        expect(passesFilter(candidate, "role") && passesFilter(candidate, "momentum")).toBe(true);
      }
    }
    expect(both.length).toBeGreaterThan(0);
    expect(selection.qualifying).toBeGreaterThanOrEqual(both.length);
  });

  it("never admits a one-observation, ended-window or absent momentum reading", () => {
    const source = bundle();
    const selection = selectRisingStars(source, "redraft-12", "PPR", new Set());
    if (selection.kind !== "ready") throw new Error("expected ready");
    for (const star of Object.values(selection.groups).flat()) {
      expect(star.candidate.momentum.kind).toBe("measured");
      expect(star.candidate.role.kind).toBe("measured");
      expect(hasEvidence(star.candidate, "momentum")).toBe(true);
    }
  });

  it("excludes every player on the league's roster, bench and IR included", () => {
    const source = bundle();
    const open = selectRisingStars(source, "redraft-12", "PPR", new Set());
    if (open.kind !== "ready") throw new Error("expected ready");
    const ids = Object.values(open.groups).flat().map((star) => star.record.player_id);
    expect(ids.length).toBeGreaterThan(0);
    const owned = selectRisingStars(source, "redraft-12", "PPR", new Set(ids));
    if (owned.kind !== "ready") throw new Error("expected ready");
    expect(Object.values(owned.groups).flat()).toEqual([]);
    expect(owned.owned).toBeGreaterThanOrEqual(new Set(ids).size);
  });

  it("says a signal is missing rather than that nobody is rising", () => {
    expect(selectRisingStars(bundle({ signals: false }), "redraft-12", "PPR", new Set())).toEqual({
      kind: "unavailable",
      missing: ["role"],
    });
    expect(selectRisingStars(bundle({ series: false }), "redraft-12", "PPR", new Set())).toEqual({
      kind: "unavailable",
      missing: ["momentum"],
    });
    expect(selectRisingStars(bundle({ opportunity: false }), "redraft-12", "PPR", new Set())).toMatchObject({
      kind: "unavailable",
    });
  });

  it("reads the same lists from a bundle it has already read for another roster", () => {
    const shared = bundle();
    const open = selectRisingStars(shared, "redraft-12", "PPR", new Set());
    if (open.kind !== "ready") throw new Error("expected ready");
    // Own the first name in every group: the next ones must move up, exactly as on a bundle
    // read for the first time.
    const roster = new Set(Object.values(open.groups).flatMap((stars) => stars.slice(0, 1).map((star) => star.record.player_id)));
    const again = selectRisingStars(shared, "redraft-12", "PPR", roster);
    const fresh = selectRisingStars(bundle(), "redraft-12", "PPR", roster);
    const ids = (selection: typeof again): unknown =>
      selection.kind === "ready"
        ? { ...selection, groups: Object.fromEntries(Object.entries(selection.groups).map(([group, stars]) => [group, stars.map((star) => star.record.player_id)])) }
        : selection;
    expect(ids(again)).toEqual(ids(fresh));
    expect(ids(selectRisingStars(shared, "redraft-12", "PPR", new Set()))).toEqual(ids(open));
  });

  it("keeps each group short", () => {
    const selection = selectRisingStars(bundle(), "redraft-12", "PPR", new Set());
    if (selection.kind !== "ready") throw new Error("expected ready");
    for (const stars of Object.values(selection.groups)) expect(stars.length).toBeLessThanOrEqual(RISING_LIMIT);
  });
});

describe("ordering", () => {
  it("orders a single position by the published change, largest first", () => {
    const selection = selectRisingStars(bundle(), "redraft-12", "PPR", new Set());
    if (selection.kind !== "ready") throw new Error("expected ready");
    for (const group of ["QB", "RB", "WR", "TE"] as const) {
      const changes = selection.groups[group].map((star) =>
        star.candidate.role.kind === "measured" ? (star.candidate.role.reading.change?.change ?? 0) : 0,
      );
      expect([...changes].sort((a, b) => b - a)).toEqual(changes);
      expect(selection.groups[group].every((star) => star.record.position === group)).toBe(true);
    }
  });

  it("lists backs, receivers and tight ends in FLEX, never a quarterback, by snap-share change", () => {
    const selection = selectRisingStars(bundle(), "redraft-12", "PPR", new Set());
    if (selection.kind !== "ready") throw new Error("expected ready");
    for (const star of selection.groups.FLEX) {
      expect(["RB", "WR", "TE"]).toContain(star.record.position);
      expect(star.candidate.role.kind === "measured" && star.candidate.role.reading.spec.metric).toBe("snap_share");
    }
  });

  it("refuses to compare a quarterback's attempts with snap-share points in FLEX", () => {
    const source = bundle();
    const all = candidatesOf(source).filter((candidate) => candidate.role.kind === "measured");
    const qb = all.find((candidate) => candidate.row.record.position === "QB");
    const rb = all.find((candidate) => candidate.row.record.position === "RB");
    if (qb === undefined || rb === undefined) throw new Error("fixture lacks a measured QB or RB");
    expect(flexRoleMagnitudeOrder(qb, rb)).toBe(0);
    expect(flexRoleMagnitudeOrder(rb, qb)).toBe(0);
  });

  it("leaves the Opportunity Board's mixed-position guard exactly as it was", () => {
    const source = bundle();
    const mixed = candidatesOf(source);
    const ordering = roleOrderingFor(mixed);
    expect(ordering.magnitudes).toBe(false);
    // With a mixed set the role sort stays categorical: within "rising", rest-of-season rank.
    const rising = mixed.filter((candidate) => candidate.role.kind === "measured" && candidate.role.direction === "up");
    const sorted = [...rising].sort((a, b) => compareRole(a, b, ordering));
    const ranks = sorted.map((candidate) => candidate.row.record.ros_fair_rank);
    expect([...ranks].sort((a, b) => a - b)).toEqual(ranks);
  });
});
