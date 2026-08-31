/**
 * The two chart helpers Phase 8 introduced.
 *
 * Both encode a judgement about what a reader can see, and both are the sort of thing that
 * silently becomes wrong when the data moves — so they are unit-tested against the shapes
 * that actually occur rather than against the shape of today's board.
 */

import { describe, expect, it } from "vitest";

import { DEFAULT_OPEN_DEPTH, defaultOpenTiers, shortName } from "../src/charts/TierBoard";
import { railBound } from "../src/charts/DraftRail";
import type { TierGroup } from "../src/data/model";

function group(ordinal: number, size: number): TierGroup {
  return {
    ordinal,
    label: `Tier ${String(ordinal + 1)}`,
    rows: Array.from({ length: size }, () => ({}) as TierGroup["rows"][number]),
  };
}

describe("defaultOpenTiers", () => {
  it("opens whole tiers until the draft-relevant depth is covered", () => {
    // The real 2026 PPR board: 8 / 14 / 25 / 33 / 29 / 42 / 45 / 69 / 35.
    const groups = [8, 14, 25, 33, 29, 42, 45, 69, 35].map((size, index) => group(index, size));
    const open = defaultOpenTiers(groups);
    // 8 + 14 = 22 is under the depth, so the third tier opens too and the rest collapse.
    expect(open).toEqual([0, 1, 2]);
    const shown = open.reduce((total, ordinal) => total + (groups[ordinal]?.rows.length ?? 0), 0);
    expect(shown).toBeGreaterThanOrEqual(DEFAULT_OPEN_DEPTH);
  });

  it("never opens a partial tier", () => {
    // A cut position on screen presented as a threshold is the one thing ADR-035 forbids, so
    // the open set is always a whole number of tiers even when that overshoots the depth.
    const groups = [200, 100].map((size, index) => group(index, size));
    expect(defaultOpenTiers(groups)).toEqual([0]);
  });

  it("always opens the first tier, however large it is", () => {
    expect(defaultOpenTiers([group(0, 300)])).toEqual([0]);
  });

  it("opens every tier on a board smaller than the depth", () => {
    const groups = [4, 5, 6].map((size, index) => group(index, size));
    expect(defaultOpenTiers(groups)).toEqual([0, 1, 2]);
  });

  it("handles an empty board without throwing", () => {
    expect(defaultOpenTiers([])).toEqual([]);
  });
});

describe("railBound", () => {
  it("sizes the scale to the population rather than to its worst outlier", () => {
    // One structural quarterback premium against a field of ordinary gaps. Scaling to the
    // outlier would render every other row as a hairline.
    const gaps = [...Array.from({ length: 20 }, (_, i) => i + 1), -206];
    const bound = railBound(gaps);
    expect(bound).toBeLessThan(60);
    expect(bound).toBeGreaterThanOrEqual(10);
  });

  it("never collapses below ten picks, so rounding is not a full-width bar", () => {
    expect(railBound([0.2, -0.1, 0.4])).toBe(10);
  });

  it("never exceeds the ceiling, so a board of premiums is still readable", () => {
    expect(railBound(Array.from({ length: 30 }, () => -400))).toBe(120);
  });

  it("has a defined bound for an empty rail", () => {
    expect(railBound([])).toBe(10);
  });
});

describe("shortName", () => {
  it("drops a generational suffix rather than mistaking it for a surname", () => {
    expect(shortName("Kyle Pitts Sr.")).toBe("Pitts");
    expect(shortName("James Cook III")).toBe("Cook");
  });

  it("keeps a single-word name whole", () => {
    expect(shortName("Ochocinco")).toBe("Ochocinco");
  });
});
