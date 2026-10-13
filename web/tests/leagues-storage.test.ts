/**
 * The saved-leagues contract and store (ADR-106): validation at the boundary, migration,
 * unavailable and full storage, malformed and future payloads, the three-league cap, league
 * isolation, and cross-tab edits that must not overwrite newer ones.
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_PREFS,
  DEFAULT_SLOTS,
  EMPTY_DOCUMENT,
  LEAGUE_FORMAT,
  MAX_LEAGUES,
  cleanLeagueName,
  emptyRoster,
  isPlayerId,
  newLeagueId,
  parseLeagueDocument,
  serializeLeagueDocument,
  validateLeague,
  type LeagueDocument,
  type SavedLeague,
} from "../src/data/leagueContract";
import { LeagueStore, leagueStorageKey, type StorageLike } from "../src/data/leagueStore";
import {
  addLeague,
  canAddLeague,
  deleteLeague,
  renameLeague,
  updateLeague,
} from "../src/data/leagueOps";
import { required } from "./required";

const KEY = leagueStorageKey("/jeisey-tiers/");

/** A Storage double that shares one map between "tabs" and can be made to fail. */
class MemoryStorage implements StorageLike {
  readonly map: Map<string, string>;
  failWrites: "quota" | "error" | null = null;
  failReads = false;
  constructor(map = new Map<string, string>()) {
    this.map = map;
  }
  getItem(key: string): string | null {
    if (this.failReads) throw new Error("SecurityError");
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    if (this.failWrites === "quota") throw new DOMException("full", "QuotaExceededError");
    if (this.failWrites === "error") throw new Error("write refused");
    this.map.set(key, value);
  }
}

function league(id: string, name = "Office", overrides: Partial<SavedLeague> = {}): SavedLeague {
  return {
    id,
    name,
    season: 2026,
    scoring: "half",
    teams: 12,
    slots: DEFAULT_SLOTS,
    roster: emptyRoster(DEFAULT_SLOTS),
    prefs: DEFAULT_PREFS,
    rev: 1,
    updatedAt: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

function doc(leagues: SavedLeague[], extra: Partial<LeagueDocument> = {}): LeagueDocument {
  return { ...EMPTY_DOCUMENT, revision: 3, activeId: leagues[0]?.id ?? null, leagues, ...extra };
}

let tick = 0;
const clock = (): string => `2026-10-13T12:00:${String(tick++ % 60).padStart(2, "0")}Z`;

function storeOn(storage: StorageLike | null): LeagueStore {
  return new LeagueStore({ storage, key: KEY, clock });
}

describe("the contract", () => {
  it("round-trips a document exactly", () => {
    const original = doc([league("lg-aaaa1111"), league("lg-bbbb2222", "Family")]);
    const parsed = parseLeagueDocument(serializeLeagueDocument(original));
    expect(parsed.kind).toBe("ok");
    if (parsed.kind !== "ok") return;
    expect(parsed.doc).toEqual(original);
    expect(parsed.setAside).toEqual([]);
  });

  it("accepts canonical ids and refuses malformed ones and team units", () => {
    expect(isPlayerId("gsis:00-0036389")).toBe(true);
    expect(isPlayerId("sleeper:12345")).toBe(true);
    expect(isPlayerId("Josh Allen")).toBe(false);
    expect(isPlayerId("gsis:")).toBe(false);
    expect(isPlayerId("dst:BUF")).toBe(false);
    expect(isPlayerId(42)).toBe(false);
  });

  it("refuses a duplicate player, a wrong-length group, an unknown preset and a bad count", () => {
    const base = league("lg-aaaa1111");
    const dup = { ...base, roster: { ...base.roster, QB: ["gsis:00-0000008"], BN: ["gsis:00-0000008", null, null, null, null] } };
    expect(validateLeague(dup)).toEqual({ problem: "duplicate_player" });
    const short = { ...base, roster: { ...base.roster, RB: [null] } };
    expect(validateLeague(short)).toEqual({ problem: "bad_roster" });
    expect(validateLeague({ ...base, teams: 16 })).toEqual({ problem: "unknown_teams" });
    expect(validateLeague({ ...base, scoring: "custom" })).toEqual({ problem: "unknown_scoring" });
    expect(validateLeague({ ...base, slots: { ...base.slots, FLEX: 9 } })).toEqual({ problem: "bad_counts" });
    expect(validateLeague({ ...base, roster: { ...base.roster, QB: ["Josh Allen"] } })).toEqual({
      problem: "bad_player_id",
    });
  });

  it("keeps an unresolved id: the contract checks shape, never whether a build knows him", () => {
    const base = league("lg-aaaa1111");
    const old = { ...base, roster: { ...base.roster, QB: ["gsis:00-9999999"] } };
    const result = validateLeague(old);
    expect("league" in result && result.league.roster.QB).toEqual(["gsis:00-9999999"]);
  });

  it("defaults missing preferences rather than refusing the league", () => {
    const result = validateLeague({ ...league("lg-aaaa1111"), prefs: { mode: "q77" } });
    expect("league" in result && result.league.prefs).toEqual(DEFAULT_PREFS);
  });

  it("sets aside an unreadable league and keeps the others, saying which and why", () => {
    const good = league("lg-aaaa1111");
    const raw = JSON.stringify({ ...doc([good]), leagues: [good, { id: "nope" }] });
    const parsed = parseLeagueDocument(raw);
    expect(parsed.kind).toBe("ok");
    if (parsed.kind !== "ok") return;
    expect(parsed.doc.leagues.map((entry) => entry.id)).toEqual(["lg-aaaa1111"]);
    expect(parsed.setAside).toEqual([{ index: 1, problem: "bad_id" }]);
  });

  it("caps at three leagues and sets the rest aside", () => {
    const four = ["lg-aaaa1111", "lg-bbbb2222", "lg-cccc3333", "lg-dddd4444"].map((id) => league(id));
    const parsed = parseLeagueDocument(JSON.stringify(doc(four)));
    expect(parsed.kind === "ok" && parsed.doc.leagues.length).toBe(MAX_LEAGUES);
    expect(parsed.kind === "ok" && parsed.setAside).toEqual([{ index: 3, problem: "over_cap" }]);
  });

  it("reads malformed JSON, a foreign format and a missing version as malformed", () => {
    expect(parseLeagueDocument("{not json").kind).toBe("malformed");
    expect(parseLeagueDocument(JSON.stringify({ format: "other", version: 1 })).kind).toBe("malformed");
    expect(parseLeagueDocument(JSON.stringify({ format: LEAGUE_FORMAT })).kind).toBe("malformed");
    expect(parseLeagueDocument(null).kind).toBe("empty");
  });

  it("reads a newer version as future, never as malformed", () => {
    expect(parseLeagueDocument(JSON.stringify({ format: LEAGUE_FORMAT, version: 2, leagues: [] }))).toEqual({
      kind: "future",
      version: 2,
    });
  });

  it("upgrades an older version one step at a time", () => {
    // A synthetic v0 → v1 migration: v0 called the leagues `items`.
    const migrations = {
      0: (payload: Record<string, unknown>) => ({ ...payload, version: 1, leagues: payload.items }),
    };
    const raw = JSON.stringify({ format: LEAGUE_FORMAT, version: 0, items: [league("lg-aaaa1111")] });
    // Version 0 is below the contract's floor of 1: refused as unreadable by the real parser…
    expect(parseLeagueDocument(raw).kind).toBe("malformed");
    // …and upgraded when the stepper is given a table that covers it, at a raised floor.
    const shifted = JSON.stringify({ format: LEAGUE_FORMAT, version: 1, items: [league("lg-aaaa1111")] });
    const parsed = parseLeagueDocument(shifted, { 1: migrations[0] }, 2);
    expect(parsed.kind).toBe("ok");
    expect(parsed.kind === "ok" && parsed.migratedFrom).toBe(1);
    expect(parsed.kind === "ok" && parsed.doc.leagues.map((entry) => entry.id)).toEqual(["lg-aaaa1111"]);
    // A gap in the table is unreadable, not a crash.
    expect(parseLeagueDocument(shifted, {}, 2).kind).toBe("malformed");
    expect(
      parseLeagueDocument(shifted, { 1: () => { throw new Error("boom"); } }, 2).kind,
    ).toBe("malformed");
  });

  it("cleans names and makes unique ids", () => {
    expect(cleanLeagueName("  Office\u0007  league  ", "League 1")).toBe("Office league");
    expect(cleanLeagueName("   ", "League 2")).toBe("League 2");
    expect(cleanLeagueName("x".repeat(80), "L")).toHaveLength(40);
    const sequence = [0, 0, 0, 0, 0, 0, 0, 0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5];
    let index = 0;
    const id = newLeagueId(doc([league("lg-00000000")]), () => sequence[index++] ?? 0.9);
    expect(id).toBe("lg-iiiiiiii");
  });
});

describe("the store", () => {
  it("starts empty and writes nothing until the reader changes something", () => {
    const storage = new MemoryStorage();
    const store = storeOn(storage);
    expect(store.snapshot().doc.leagues).toEqual([]);
    expect(store.snapshot().save.kind).toBe("saved");
    expect(storage.map.size).toBe(0);
  });

  it("creates, renames, switches and deletes leagues, each isolated from the others", () => {
    const storage = new MemoryStorage();
    const store = storeOn(storage);
    const a = addLeague(store, { name: "Office", scoring: "half", teams: 12, season: 2026 });
    const b = addLeague(store, { name: "Family", scoring: "ppr", teams: 10, season: 2026 });
    expect(a.ok && b.ok).toBe(true);
    const snapshot = store.snapshot();
    expect(snapshot.doc.leagues.map((entry) => entry.name)).toEqual(["Office", "Family"]);
    expect(snapshot.activeId).toBe(snapshot.doc.leagues[1]?.id);
    const office = snapshot.doc.leagues[0];
    const family = snapshot.doc.leagues[1];
    if (office === undefined || family === undefined) throw new Error("missing");
    // An edit to one league leaves the other's object and revision untouched.
    updateLeague(store, office, (current) => ({
      ...current,
      roster: { ...current.roster, QB: ["gsis:00-0000008"] },
    }));
    const after = store.snapshot().doc.leagues;
    expect(after[1]).toBe(store.snapshot().doc.leagues[1]);
    expect(after[1]?.rev).toBe(family.rev);
    expect(after[0]?.roster.QB).toEqual(["gsis:00-0000008"]);
    // The same player may be on a roster in another league.
    updateLeague(store, family, (current) => ({
      ...current,
      roster: { ...current.roster, QB: ["gsis:00-0000008"] },
    }));
    expect(store.snapshot().doc.leagues.map((entry) => entry.roster.QB[0])).toEqual([
      "gsis:00-0000008",
      "gsis:00-0000008",
    ]);
    renameLeague(store, required(store.snapshot().doc.leagues[0], "league 0"), "  Work  ");
    expect(store.snapshot().doc.leagues[0]?.name).toBe("Work");
    store.activate(office.id);
    expect(store.snapshot().activeId).toBe(office.id);
    deleteLeague(store, required(store.snapshot().doc.leagues[0], "league 0"));
    expect(store.snapshot().doc.leagues.map((entry) => entry.name)).toEqual(["Family"]);
    expect(store.snapshot().activeId).toBe(family.id);
    // Persisted: a fresh store over the same storage reads the same leagues.
    expect(storeOn(storage).snapshot().doc.leagues.map((entry) => entry.name)).toEqual(["Family"]);
  });

  it("refuses a fourth league", () => {
    const store = storeOn(new MemoryStorage());
    for (const name of ["A", "B", "C"]) addLeague(store, { name, scoring: "ppr", teams: 12, season: 2026 });
    expect(canAddLeague(store.snapshot().doc)).toBe(false);
    const fourth = addLeague(store, { name: "D", scoring: "ppr", teams: 12, season: 2026 });
    expect(fourth.ok).toBe(false);
    expect(store.snapshot().doc.leagues).toHaveLength(3);
  });

  it("keeps working in memory when storage is unavailable, and says it is not saved", () => {
    const store = storeOn(null);
    expect(store.snapshot().save).toEqual({ kind: "unsaved", reason: "unavailable" });
    const result = addLeague(store, { name: "Office", scoring: "ppr", teams: 12, season: 2026 });
    expect(result.ok).toBe(true);
    expect(store.snapshot().doc.leagues).toHaveLength(1);
    expect(store.snapshot().save.kind).toBe("unsaved");

    const throwing = new MemoryStorage();
    throwing.failReads = true;
    expect(storeOn(throwing).snapshot().save).toEqual({ kind: "unsaved", reason: "unavailable" });
  });

  it("keeps an edit in memory when storage is full, and saves it on the next write that fits", () => {
    const storage = new MemoryStorage();
    const store = storeOn(storage);
    addLeague(store, { name: "Office", scoring: "ppr", teams: 12, season: 2026 });
    storage.failWrites = "quota";
    const office = required(store.snapshot().doc.leagues[0], "league 0");
    updateLeague(store, office, (current) => ({ ...current, roster: { ...current.roster, QB: ["gsis:00-0000008"] } }));
    expect(store.snapshot().save).toEqual({ kind: "unsaved", reason: "quota" });
    expect(store.snapshot().doc.leagues[0]?.roster.QB).toEqual(["gsis:00-0000008"]);
    expect(storeOn(storage).snapshot().doc.leagues[0]?.roster.QB).toEqual([null]);
    storage.failWrites = null;
    renameLeague(store, required(store.snapshot().doc.leagues[0], "league 0"), "Office 2");
    expect(store.snapshot().save.kind).toBe("saved");
    expect(storeOn(storage).snapshot().doc.leagues[0]?.roster.QB).toEqual(["gsis:00-0000008"]);
  });

  it("backs up a malformed payload before anything is written over it", () => {
    const storage = new MemoryStorage(new Map([[KEY, "{broken"]]));
    const store = storeOn(storage);
    expect(store.snapshot().notices).toEqual([
      { kind: "malformed", reason: "the saved data is not valid JSON", backedUp: true },
    ]);
    const backup = JSON.parse(storage.map.get(`${KEY}:backup`) ?? "{}") as { raw: string };
    expect(backup.raw).toBe("{broken");
    addLeague(store, { name: "Fresh", scoring: "ppr", teams: 12, season: 2026 });
    expect(storeOn(storage).snapshot().doc.leagues.map((entry) => entry.name)).toEqual(["Fresh"]);
  });

  it("refuses to overwrite unreadable data it could not back up, until the reader chooses to", () => {
    const storage = new MemoryStorage(new Map([[KEY, "{broken"]]));
    storage.failWrites = "quota";
    const store = storeOn(storage);
    expect(store.snapshot().save.kind).toBe("protected");
    storage.failWrites = null;
    const refused = addLeague(store, { name: "Fresh", scoring: "ppr", teams: 12, season: 2026 });
    expect(refused.ok).toBe(false);
    expect(storage.map.get(KEY)).toBe("{broken");
    store.discardUnreadable();
    expect(addLeague(store, { name: "Fresh", scoring: "ppr", teams: 12, season: 2026 }).ok).toBe(true);
  });

  it("never writes over a newer build's leagues", () => {
    const raw = JSON.stringify({ format: LEAGUE_FORMAT, version: 9, leagues: [{ anything: true }] });
    const storage = new MemoryStorage(new Map([[KEY, raw]]));
    const store = storeOn(storage);
    expect(store.snapshot().save).toEqual({ kind: "readonly", version: 9 });
    const result = addLeague(store, { name: "X", scoring: "ppr", teams: 12, season: 2026 });
    expect(result.ok).toBe(false);
    expect(storage.map.get(KEY)).toBe(raw);
  });

  it("backs up and reports a set-aside league", () => {
    const good = league("lg-aaaa1111");
    const raw = JSON.stringify({ ...doc([good]), leagues: [good, { id: "lg-bbbb2222", name: 5 }] });
    const storage = new MemoryStorage(new Map([[KEY, raw]]));
    const store = storeOn(storage);
    expect(store.snapshot().doc.leagues).toHaveLength(1);
    expect(store.snapshot().notices[0]).toMatchObject({ kind: "set_aside", backedUp: true });
    expect(storage.map.has(`${KEY}:backup`)).toBe(true);
  });

  it("refuses a stale tab's edit to a league another tab changed, and shows the newer one", () => {
    const shared = new Map<string, string>();
    const tabA = storeOn(new MemoryStorage(shared));
    addLeague(tabA, { name: "Office", scoring: "ppr", teams: 12, season: 2026 });
    const tabB = storeOn(new MemoryStorage(shared));
    const seenByA = required(tabA.snapshot().doc.leagues[0], "league 0");
    const seenByB = required(tabB.snapshot().doc.leagues[0], "league 0");
    // B edits first; A has not received the storage event yet.
    updateLeague(tabB, seenByB, (current) => ({ ...current, roster: { ...current.roster, QB: ["gsis:00-0000008"] } }));
    const result = updateLeague(tabA, seenByA, (current) => ({
      ...current,
      roster: { ...current.roster, QB: ["gsis:00-0000018"] },
    }));
    expect(result.ok).toBe(false);
    expect(tabA.snapshot().doc.leagues[0]?.roster.QB).toEqual(["gsis:00-0000008"]);
    expect(tabA.snapshot().notices.some((notice) => notice.kind === "conflict")).toBe(true);
    expect(storeOn(new MemoryStorage(shared)).snapshot().doc.leagues[0]?.roster.QB).toEqual(["gsis:00-0000008"]);
  });

  it("applies a stale tab's edit to a different league on top of the newer document", () => {
    const shared = new Map<string, string>();
    const tabA = storeOn(new MemoryStorage(shared));
    addLeague(tabA, { name: "Office", scoring: "ppr", teams: 12, season: 2026 });
    addLeague(tabA, { name: "Family", scoring: "ppr", teams: 12, season: 2026 });
    const tabB = storeOn(new MemoryStorage(shared));
    const [officeB] = tabB.snapshot().doc.leagues as SavedLeague[];
    const familyA = required(tabA.snapshot().doc.leagues[1], "league 1");
    updateLeague(tabB, required(officeB, "office in B"), (current) => ({ ...current, name: "Office (B)" }));
    expect(updateLeague(tabA, familyA, (current) => ({ ...current, name: "Family (A)" })).ok).toBe(true);
    const merged = storeOn(new MemoryStorage(shared)).snapshot().doc.leagues.map((entry) => entry.name);
    expect(merged).toEqual(["Office (B)", "Family (A)"]);
  });

  it("adopts another tab's write from a storage event, but not over unsaved edits", () => {
    const shared = new Map<string, string>();
    const tabA = storeOn(new MemoryStorage(shared));
    addLeague(tabA, { name: "Office", scoring: "ppr", teams: 12, season: 2026 });
    const storageB = new MemoryStorage(shared);
    const tabB = storeOn(storageB);
    renameLeague(tabA, required(tabA.snapshot().doc.leagues[0], "league 0"), "Renamed");
    tabB.external(shared.get(KEY) ?? null);
    expect(tabB.snapshot().doc.leagues[0]?.name).toBe("Renamed");

    storageB.failWrites = "quota";
    renameLeague(tabB, required(tabB.snapshot().doc.leagues[0], "league 0"), "Unsaved in B");
    renameLeague(tabA, required(tabA.snapshot().doc.leagues[0], "league 0"), "Newer in A");
    tabB.external(shared.get(KEY) ?? null);
    expect(tabB.snapshot().doc.leagues[0]?.name).toBe("Unsaved in B");
    expect(tabB.snapshot().notices.some((notice) => notice.kind === "diverged")).toBe(true);
    storageB.failWrites = null;
    tabB.reloadFromStorage();
    expect(tabB.snapshot().doc.leagues[0]?.name).toBe("Newer in A");
  });

  it("keeps each tab's open league its own", () => {
    const shared = new Map<string, string>();
    const tabA = storeOn(new MemoryStorage(shared));
    addLeague(tabA, { name: "Office", scoring: "ppr", teams: 12, season: 2026 });
    addLeague(tabA, { name: "Family", scoring: "ppr", teams: 12, season: 2026 });
    const tabB = storeOn(new MemoryStorage(shared));
    const [office, family] = tabA.snapshot().doc.leagues as SavedLeague[];
    tabB.activate(office?.id ?? "");
    tabA.activate(family?.id ?? "");
    tabB.external(shared.get(KEY) ?? null);
    expect(tabB.snapshot().activeId).toBe(office?.id);
    expect(tabA.snapshot().activeId).toBe(family?.id);
  });

  it("reads a cleared site as no leagues", () => {
    const shared = new Map<string, string>();
    const store = storeOn(new MemoryStorage(shared));
    addLeague(store, { name: "Office", scoring: "ppr", teams: 12, season: 2026 });
    shared.clear();
    store.external(null);
    expect(store.snapshot().doc.leagues).toEqual([]);
  });
});
