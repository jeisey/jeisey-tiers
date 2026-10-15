/**
 * The player search's rules (ADR-111): one match rule shared with the boards, a stable order,
 * a choice that applies the player's name and clears only a filter that would hide him, and an
 * add that never removes.
 */

import { describe, expect, it } from "vitest";

import { chooseSearchPlayer } from "../src/data/boardSearch";
import { addToDuel } from "../src/data/duel";
import { matchesSearch } from "../src/data/model";
import { searchPlayers, type SearchEntry } from "../src/data/playerSearch";
import { DEFAULT_STATE, MAX_DUEL } from "../src/data/state";

const POOL: readonly SearchEntry[] = [
  { id: "gsis:1", name: "Amon-Ra St. Brown", position: "WR", team: "DET" },
  { id: "gsis:2", name: "Ja'Marr Chase", position: "WR", team: "CIN" },
  { id: "gsis:3", name: "Joe Burrow", position: "QB", team: "CIN" },
  { id: "gsis:4", name: "Kyle Pitts Sr.", position: "TE", team: "ATL" },
  { id: "gsis:5", name: "José Montaño", position: "RB", team: "MIA" },
  { id: "gsis:6", name: "Tee Higgins", position: "WR", team: "CIN" },
  // A repeated id (a priced row and its tier row) is listed once.
  { id: "gsis:3", name: "Joe Burrow", position: "QB", team: "CIN" },
];

const names = (query: string, limit?: number): string[] =>
  searchPlayers(POOL, query, limit).entries.map((entry) => entry.name);

describe("searchPlayers", () => {
  it("ignores case, accents and punctuation, as the board does", () => {
    expect(names("stbrown")).toEqual(["Amon-Ra St. Brown"]);
    expect(names("ST. BROWN")).toEqual(["Amon-Ra St. Brown"]);
    expect(names("jamarr")).toEqual(["Ja'Marr Chase"]);
    expect(names("montano")).toEqual(["José Montaño"]);
    expect(names("pitts sr")).toEqual(["Kyle Pitts Sr."]);
  });

  it("lists exactly what the board would show for the same query", () => {
    for (const query of ["cin", "wr", "te", "joe", "a", "zz"]) {
      const board = POOL.filter((entry, index) => POOL.findIndex((other) => other.id === entry.id) === index).filter(
        (entry) => matchesSearch({ display_name: entry.name, team: entry.team, position: entry.position }, query),
      );
      const result = searchPlayers(POOL, query, 99);
      expect(result.total).toBe(board.length);
      expect(new Set(result.entries.map((entry) => entry.id))).toEqual(new Set(board.map((entry) => entry.id)));
    }
  });

  it("puts a name that starts with the query first, otherwise keeps the board's order", () => {
    // "chase" starts a word of Ja'Marr Chase; the CIN matches by team follow in board order.
    expect(names("cin")).toEqual(["Ja'Marr Chase", "Joe Burrow", "Tee Higgins"]);
    expect(names("hig")).toEqual(["Tee Higgins"]);
    expect(names("t", 2)).toEqual(["Tee Higgins", "Amon-Ra St. Brown"]);
  });

  it("counts every match beyond the shown few, and nothing for an empty query", () => {
    expect(searchPlayers(POOL, "a", 2)).toMatchObject({ total: 4 });
    expect(searchPlayers(POOL, "a", 2).entries).toHaveLength(2);
    expect(searchPlayers(POOL, "  ", 8)).toEqual({ entries: [], total: 0 });
  });
});

describe("chooseSearchPlayer", () => {
  const chase = { id: "gsis:2", name: "Ja'Marr Chase", position: "WR" as const };

  it("applies his name and leaves every other setting alone", () => {
    const state = { ...DEFAULT_STATE, scoring: "half" as const, teams: 10 as const, position: "wr" as const };
    expect(chooseSearchPlayer(chase, state, "ros", null)).toEqual({
      patch: { search: "Ja'Marr Chase" },
      note: null,
    });
  });

  it("clears a position filter that would hide him, and says which", () => {
    const state = { ...DEFAULT_STATE, position: "rb" as const, board: "full" as const };
    expect(chooseSearchPlayer(chase, state, "tiers", null)).toEqual({
      patch: { search: "Ja'Marr Chase", position: "all" },
      note: "Cleared the RB position filter to show Ja'Marr Chase (WR).",
    });
  });
});

describe("addToDuel", () => {
  it("adds at the end, never twice, never past four, and never removes", () => {
    expect(addToDuel(["a"], "b")).toEqual(["a", "b"]);
    const two = ["a", "b"];
    expect(addToDuel(two, "a")).toBe(two);
    const full = ["a", "b", "c", "d"];
    expect(full).toHaveLength(MAX_DUEL);
    expect(addToDuel(full, "e")).toBe(full);
  });
});
