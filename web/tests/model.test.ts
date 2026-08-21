/**
 * The browser's data model.
 *
 * The join, the filters and the status semantics. The most important assertion in this file is
 * the negative one: a null `injury_status` never becomes the word "Healthy", because absence of
 * a reported designation is not a report of health (ADR-043).
 */

import { describe, expect, it } from "vitest";

import type { PlayerStatusRecord } from "../src/data/contracts";
import {
  ArtifactIndex,
  groupByTier,
  hasMeaningfulStatus,
  matchesPosition,
  matchesSearch,
  normalizeSearch,
  selectArbitrageRows,
  selectTierRows,
  statusBadge,
  unpricedMatches,
} from "../src/data/model";
import { DEFAULT_STATE } from "../src/data/state";
import {
  arbitrageRecords,
  buildMetadata,
  playerStatusRecords,
  projectionRecords,
  tierRecords,
} from "./fixtures/artifacts";

function index(overrides: Partial<ConstructorParameters<typeof ArtifactIndex>[0]> = {}): ArtifactIndex {
  return new ArtifactIndex({
    metadata: buildMetadata(),
    tiers: tierRecords(),
    arbitrage: arbitrageRecords(),
    playerStatus: playerStatusRecords(),
    projections: projectionRecords(),
    ...overrides,
  });
}

describe("ArtifactIndex", () => {
  it("indexes tiers by preset block in fair-rank order", () => {
    const rows = index().tiersFor("redraft-12", "PPR");
    expect(rows).toHaveLength(18);
    expect(rows.map((row) => row.fair_rank)).toEqual([...Array(18).keys()].map((n) => n + 1));
  });

  it("indexes arbitrage by preset block in arbitrage-score order", () => {
    const rows = index().arbitrageFor("redraft-12", "PPR");
    const scores = rows.map((row) => row.arbitrage_score);
    expect([...scores].sort((a, b) => b - a)).toEqual(scores);
  });

  it("reports which artifacts are present", () => {
    const full = index();
    expect(full.hasArbitrage).toBe(true);
    expect(full.hasPlayerStatus).toBe(true);
    const degraded = index({ arbitrage: null, playerStatus: null });
    expect(degraded.hasArbitrage).toBe(false);
    expect(degraded.hasPlayerStatus).toBe(false);
    // The intrinsic board is unchanged by either absence.
    expect(degraded.tiersFor("redraft-12", "PPR")).toHaveLength(18);
  });

  it("only advertises preset blocks the build actually published", () => {
    const blocks = index().availableBlocks();
    expect(blocks).toHaveLength(9);
    expect(blocks.every((block) => block.leaguePreset.startsWith("redraft-"))).toBe(true);
  });

  it("looks a player up by preset and id without scanning", () => {
    const tier = index().tierFor("redraft-12", "PPR", "gsis:00-0000001");
    expect(tier?.display_name).toBe("Bijan Robinson");
    expect(index().tierFor("redraft-12", "PPR", "gsis:nobody")).toBeNull();
  });
});

describe("filters", () => {
  it("filters by position", () => {
    expect(matchesPosition("RB", "all")).toBe(true);
    expect(matchesPosition("RB", "rb")).toBe(true);
    expect(matchesPosition("RB", "wr")).toBe(false);
  });

  it("matches a search ignoring case, punctuation and accents", () => {
    const row = { display_name: "Amon-Ra St. Brown", team: "DET", position: "WR" } as const;
    expect(matchesSearch(row, "amonra")).toBe(true);
    expect(matchesSearch(row, "st brown")).toBe(true);
    expect(matchesSearch(row, "DET")).toBe(true);
    expect(matchesSearch(row, "wr")).toBe(true);
    expect(matchesSearch(row, "burrow")).toBe(false);
    expect(matchesSearch(row, "")).toBe(true);
  });

  it("strips diacritics so an accented name is findable from a plain keyboard", () => {
    expect(normalizeSearch("Amon-Rá St. Brown")).toBe("amonrastbrown");
  });

  it("applies position and search together when selecting tier rows", () => {
    const rows = selectTierRows(index(), { ...DEFAULT_STATE, position: "te" });
    expect(rows.map((row) => row.record.display_name).sort()).toEqual([
      "Kyle Pitts Sr.",
      "Trey McBride",
      "Zach Ertz",
    ]);
  });

  it("joins status onto tier rows and leaves it null where none was published", () => {
    const rows = selectTierRows(index(), DEFAULT_STATE);
    const injured = rows.find((row) => row.record.display_name === "Amon-Ra Bright");
    expect(injured?.status?.injury_status).toBe("Questionable");
    const unknown = rows.find((row) => row.record.display_name === "Deebo Gray");
    expect(unknown?.status).toBeNull();
    // The absence of a status record changes nothing about his numbers.
    expect(unknown?.record.p50_vorp).toBeGreaterThan(0);
  });

  it("numbers arbitrage rows by their published order, not by the filtered subset", () => {
    const all = selectArbitrageRows(index(), DEFAULT_STATE);
    const receivers = selectArbitrageRows(index(), { ...DEFAULT_STATE, position: "wr" });
    for (const row of receivers) {
      const original = all.find((entry) => entry.record.player_id === row.record.player_id);
      expect(row.arbitrageRank).toBe(original?.arbitrageRank);
    }
  });
});

describe("players with no market price", () => {
  it("keeps them on the tier board", () => {
    const rows = selectTierRows(index(), { ...DEFAULT_STATE, search: "ertz" });
    expect(rows).toHaveLength(1);
    expect(rows[0]?.arbitrage).toBeNull();
  });

  it("names them instead of returning an empty arbitrage result", () => {
    const state = { ...DEFAULT_STATE, search: "ertz" };
    expect(selectArbitrageRows(index(), state)).toHaveLength(0);
    expect(unpricedMatches(index(), state).map((record) => record.display_name)).toEqual([
      "Zach Ertz",
    ]);
  });

  it("reports nothing unpriced when the search is empty", () => {
    expect(unpricedMatches(index(), DEFAULT_STATE)).toHaveLength(0);
  });
});

describe("groupByTier", () => {
  it("produces contiguous groups in fair-rank order", () => {
    const groups = groupByTier(selectTierRows(index(), DEFAULT_STATE));
    expect(groups.map((group) => group.label)).toEqual(["S", "A", "B"]);
    expect(groups.map((group) => group.rows.length)).toEqual([3, 5, 10]);
    const ranks = groups.flatMap((group) => group.rows.map((row) => row.record.fair_rank));
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });

  it("returns nothing for an empty board rather than an empty group", () => {
    expect(groupByTier([])).toEqual([]);
  });
});

function status(overrides: Partial<PlayerStatusRecord>): PlayerStatusRecord {
  const base = playerStatusRecords()[0];
  if (base === undefined) throw new Error("fixture has no status records");
  return { ...base, ...overrides };
}

describe("status semantics", () => {
  it("treats a null injury designation as no information, not as health", () => {
    const record = status({
      injury_status: null,
      injury_body_part: null,
      injury_notes: null,
      roster_status: "ACT",
      sleeper_status: "Active",
    });
    expect(hasMeaningfulStatus(record)).toBe(false);
    expect(statusBadge(record)).toBeNull();
  });

  it("never produces the word Healthy from any input", () => {
    for (const record of playerStatusRecords()) {
      const badge = statusBadge(record);
      expect(JSON.stringify(badge ?? {}).toLowerCase()).not.toContain("healthy");
    }
  });

  it("abbreviates a designation and keeps the full text available", () => {
    const badge = statusBadge(status({ injury_status: "Questionable", injury_body_part: "Hamstring" }));
    expect(badge?.short).toBe("Q · Hamstring");
    expect(badge?.full).toBe("Questionable · Hamstring");
    expect(badge?.severity).toBe("caution");
  });

  it("marks a season-ending designation more severely than a game-time one", () => {
    expect(statusBadge(status({ injury_status: "Out" }))?.severity).toBe("warn");
    expect(statusBadge(status({ injury_status: "IR" }))?.severity).toBe("warn");
    expect(statusBadge(status({ injury_status: "Doubtful" }))?.severity).toBe("caution");
  });

  it("surfaces a reserve designation even with no injury field", () => {
    const badge = statusBadge(
      status({ injury_status: null, injury_body_part: null, roster_status: "RES", sleeper_status: "Active" }),
    );
    expect(badge).not.toBeNull();
    expect(badge?.full).toBe("RES");
  });

  it("shows nothing at all when there is no status record", () => {
    expect(statusBadge(null)).toBeNull();
    expect(hasMeaningfulStatus(null)).toBe(false);
  });
});
