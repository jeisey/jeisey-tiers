/**
 * Win My Matchup's saved inputs (ADR-110 §7): a separate, versioned document that cannot touch
 * the saved leagues, validated at the boundary, bounded, and written under ADR-106's store rules
 * — only edits write, failures keep edits in memory, unreadable data is backed up, a newer
 * version is read-only and a stale tab's edit is refused.
 */

import { describe, expect, it } from "vitest";

import { leagueStorageKey, type StorageLike } from "../src/data/leagueStore";
import {
  EMPTY_WMM,
  WMM_FORMAT,
  addOpponentOther,
  assignOpponent,
  clearOpponentSlot,
  confirmEmpty,
  countAsZero,
  removeOpponentPlayer,
  renameOpponent,
  setFinal,
  setMark,
  trimOpponent,
  WMM_MAX_ENTRIES,
  WMM_WEEKS_PER_LEAGUE,
  boundDocument,
  cleanFinal,
  emptyStarters,
  entryKey,
  findEntry,
  newEntry,
  opponentIds,
  parseWmmDocument,
  prefsFor,
  previousEntry,
  serializeWmmDocument,
  validateEntry,
  type MatchupEntry,
  type WmmDocument,
} from "../src/data/wmmContract";
import { WmmStore, editEntry, reuseEntry, setWmmPrefs, wmmStorageKey } from "../src/data/wmmStore";

const KEY = wmmStorageKey("/jeisey-tiers/");

class MemoryStorage implements StorageLike {
  readonly map: Map<string, string>;
  failWrites: "quota" | "error" | null = null;
  failReads = false;
  writes = 0;
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
    this.writes += 1;
    this.map.set(key, value);
  }
}

let tick = 0;
const clock = (): string => `2026-10-15T12:00:${String(tick++ % 60).padStart(2, "0")}Z`;
const storeOn = (storage: StorageLike | null): WmmStore => new WmmStore({ storage, key: KEY, clock });

/** What a stored payload holds, read without trusting it. */
function stored(raw: string | undefined): { entries?: unknown[]; raw?: string } {
  return JSON.parse(raw ?? "{}") as { entries?: unknown[]; raw?: string };
}

const g = (n: number): string => `gsis:00-00000${String(n).padStart(2, "0")}`;
const AT = { leagueId: "lg-office01", season: 2026, week: 6 };

function entry(overrides: Partial<MatchupEntry> = {}): MatchupEntry {
  return {
    ...newEntry(AT.leagueId, AT.season, AT.week),
    opponent: { name: "Mike", starters: { ...emptyStarters(), QB: [g(8)], RB: [g(11), g(13)] }, others: [g(4)] },
    rev: 1,
    updatedAt: "2026-10-15T00:00:00Z",
    ...overrides,
  };
}

function docOf(entries: MatchupEntry[], extra: Partial<WmmDocument> = {}): WmmDocument {
  return { ...EMPTY_WMM, revision: 2, entries, ...extra };
}

describe("the contract", () => {
  it("round-trips a valid document", () => {
    const doc = docOf([entry()], { prefs: { "lg-office01": { yolo: true } } });
    const parsed = parseWmmDocument(serializeWmmDocument(doc));
    expect(parsed).toEqual({ kind: "ok", doc, setAside: [], migratedFrom: null });
  });

  it("reads nothing as empty, and refuses garbage and other formats", () => {
    expect(parseWmmDocument(null)).toEqual({ kind: "empty" });
    expect(parseWmmDocument("{")).toMatchObject({ kind: "malformed" });
    expect(parseWmmDocument(JSON.stringify({ format: "jeisey-tiers.my-leagues", version: 1 }))).toMatchObject({ kind: "malformed" });
    expect(parseWmmDocument(JSON.stringify({ format: WMM_FORMAT, version: 0, entries: [] }))).toMatchObject({ kind: "malformed" });
  });

  it("leaves a newer version alone, and migrates an older one step by step", () => {
    expect(parseWmmDocument(JSON.stringify({ format: WMM_FORMAT, version: 2, entries: [] }))).toEqual({ kind: "future", version: 2 });
    const v1 = JSON.stringify({ format: WMM_FORMAT, version: 1, revision: 1, matchups: [entry()] });
    const migrated = parseWmmDocument(v1, { 1: (payload) => ({ ...payload, version: 2, entries: payload.matchups }) }, 2);
    expect(migrated).toMatchObject({ kind: "ok", migratedFrom: 1 });
    expect(parseWmmDocument(v1, {}, 2)).toMatchObject({ kind: "malformed" });
  });

  it("sets aside an unreadable entry and a second entry for the same week", () => {
    const raw = JSON.stringify({
      format: WMM_FORMAT,
      version: 1,
      entries: [entry(), { ...entry(), opponent: { name: "x", starters: { QB: ["Josh Allen"] } } }, entry({ rev: 4 })],
    });
    const parsed = parseWmmDocument(raw);
    expect(parsed.kind).toBe("ok");
    if (parsed.kind !== "ok") return;
    expect(parsed.doc.entries).toHaveLength(1);
    expect(parsed.setAside).toEqual([
      { index: 1, problem: "bad_player_id" },
      { index: 2, problem: "duplicate_key" },
    ]);
  });

  it("validates ids, duplicates, sizes, finals and marks", () => {
    expect(validateEntry({ ...entry(), leagueId: "office" })).toEqual({ problem: "bad_league" });
    expect(validateEntry({ ...entry(), week: 0 })).toEqual({ problem: "bad_week" });
    expect(
      validateEntry({ ...entry(), opponent: { name: "", starters: { ...emptyStarters(), QB: [g(8)] }, others: [g(8)] } }),
    ).toEqual({ problem: "duplicate_player" });
    expect(
      validateEntry({ ...entry(), opponent: { name: "", starters: { ...emptyStarters(), QB: [g(1), g(2), g(3)] }, others: [] } }),
    ).toEqual({ problem: "bad_starters" });
    expect(
      validateEntry({ ...entry(), opponent: { name: "", starters: emptyStarters(), others: Array.from({ length: 15 }, (_, i) => g(i + 1)) } }),
    ).toEqual({ problem: "too_many" });
    expect(validateEntry({ ...entry(), finals: { [g(8)]: 140 } })).toEqual({ problem: "bad_final" });
    const read = validateEntry({
      ...entry(),
      finals: { [g(8)]: 21.456 },
      marks: { [g(3)]: "available", [g(5)]: "maybe" },
      confirmedEmpty: { mine: ["TE:0", "K:0", "TE:0"], theirs: "FLEX:0" },
      countZero: [g(17), g(17)],
    });
    expect("entry" in read).toBe(true);
    if (!("entry" in read)) return;
    expect(read.entry.finals).toEqual({ [g(8)]: 21.46 });
    expect(read.entry.marks).toEqual({ [g(3)]: "available" });
    expect(read.entry.confirmedEmpty).toEqual({ mine: ["TE:0"], theirs: [] });
    expect(read.entry.countZero).toEqual([g(17)]);
    expect(cleanFinal(-3.333)).toBe(-3.33);
    expect(cleanFinal(Number.NaN)).toBeNull();
  });

  it("stores ids and a name, never a projection or a result", () => {
    const serialized = serializeWmmDocument(docOf([entry({ finals: { [g(8)]: 24.1 } })]));
    expect(serialized).not.toMatch(/q50|"win"|probab|display_name|Josh/);
    expect(opponentIds(entry())).toEqual([g(8), g(11), g(13), g(4)]);
  });
});

describe("bounds", () => {
  it("keeps each league's four latest weeks and twelve entries in all, oldest out", () => {
    const many: MatchupEntry[] = [];
    for (let week = 1; week <= 6; week += 1) many.push({ ...entry(), week });
    for (let league = 0; league < 4; league += 1) {
      for (let week = 1; week <= 3; week += 1) many.push({ ...entry(), leagueId: `lg-other0${String(league)}`, week });
    }
    const bounded = boundDocument(docOf(many));
    const office = bounded.entries.filter((item) => item.leagueId === AT.leagueId).map((item) => item.week);
    expect(office.sort()).toEqual([3, 4, 5, 6]);
    expect(office).toHaveLength(WMM_WEEKS_PER_LEAGUE);
    expect(bounded.entries).toHaveLength(WMM_MAX_ENTRIES);
    expect(boundDocument(docOf([entry()]))).toEqual(docOf([entry()]));
  });

  it("finds this week's entry and the previous one for a rollover", () => {
    const doc = docOf([{ ...entry(), week: 4 }, { ...entry(), week: 5 }, { ...entry(), leagueId: "lg-family01", week: 6 }]);
    expect(findEntry(doc, AT.leagueId, 2026, 6)).toBeNull();
    expect(previousEntry(doc, AT.leagueId, 2026, 6)?.week).toBe(5);
    expect(previousEntry(doc, AT.leagueId, 2026, 4)).toBeNull();
    expect(prefsFor(doc, AT.leagueId)).toEqual({ yolo: false });
  });
});

describe("the store", () => {
  it("never writes unless the reader edits", () => {
    const storage = new MemoryStorage();
    const store = storeOn(storage);
    expect(store.snapshot().doc).toEqual(EMPTY_WMM);
    expect(storage.writes).toBe(0);
    expect(editEntry(store, AT, null, (current) => current)).toEqual({ ok: true });
    expect(storage.writes).toBe(0);
    expect(store.snapshot().doc.entries).toHaveLength(0);
  });

  it("creates this week's entry on the first edit and revises it after", () => {
    const storage = new MemoryStorage();
    const store = storeOn(storage);
    editEntry(store, AT, null, (current) => ({ ...current, opponent: { ...current.opponent, name: "Mike" } }));
    const saved = findEntry(store.snapshot().doc, AT.leagueId, AT.season, AT.week);
    expect(saved?.rev).toBe(1);
    expect(saved?.opponent.name).toBe("Mike");
    editEntry(store, AT, saved, (current) => ({ ...current, finals: { [g(8)]: 20 } }));
    expect(findEntry(store.snapshot().doc, AT.leagueId, AT.season, AT.week)?.rev).toBe(2);
    expect(stored(storage.map.get(KEY)).entries).toHaveLength(1);
  });

  it("never touches the saved leagues' key", () => {
    const leaguesKey = leagueStorageKey("/jeisey-tiers/");
    const leagues = JSON.stringify({ format: "jeisey-tiers.my-leagues", version: 1, revision: 9, activeId: null, leagues: [] });
    const storage = new MemoryStorage(new Map([[leaguesKey, leagues]]));
    const store = storeOn(storage);
    editEntry(store, AT, null, (current) => ({ ...current, countZero: [g(1)] }));
    setWmmPrefs(store, AT.leagueId, { yolo: true });
    expect(storage.map.get(leaguesKey)).toBe(leagues);
    expect([...storage.map.keys()].sort()).toEqual([KEY, leaguesKey].sort());
  });

  it("refuses a stale tab's edit and keeps both tabs on the newer version", () => {
    const shared = new Map<string, string>();
    const a = storeOn(new MemoryStorage(shared));
    const b = storeOn(new MemoryStorage(shared));
    editEntry(a, AT, null, (current) => ({ ...current, opponent: { ...current.opponent, name: "From A" } }));
    // B never saw A's entry: its "create" is refused rather than overwriting it.
    const refused = editEntry(b, AT, null, (current) => ({ ...current, opponent: { ...current.opponent, name: "From B" } }));
    expect(refused).toMatchObject({ ok: false, reason: "conflict" });
    expect(findEntry(b.snapshot().doc, AT.leagueId, AT.season, AT.week)?.opponent.name).toBe("From A");
    expect(b.snapshot().notices.some((notice) => notice.kind === "conflict")).toBe(true);
    // Another week's entry does not conflict.
    expect(editEntry(b, { ...AT, week: 7 }, null, (current) => ({ ...current, countZero: [g(2)] }))).toEqual({ ok: true });
    expect(stored(shared.get(KEY)).entries).toHaveLength(2);
  });

  it("follows another tab's write, unless it holds unsaved edits", () => {
    const shared = new Map<string, string>();
    const a = storeOn(new MemoryStorage(shared));
    const failing = new MemoryStorage(shared);
    const b = storeOn(failing);
    editEntry(a, AT, null, (current) => ({ ...current, opponent: { ...current.opponent, name: "A" } }));
    b.external(shared.get(KEY) ?? null);
    expect(findEntry(b.snapshot().doc, AT.leagueId, AT.season, AT.week)?.opponent.name).toBe("A");
    failing.failWrites = "error";
    editEntry(b, { ...AT, week: 8 }, null, (current) => ({ ...current, countZero: [g(3)] }));
    expect(b.snapshot().save).toEqual({ kind: "unsaved", reason: "error" });
    editEntry(a, { ...AT, week: 9 }, null, (current) => ({ ...current, countZero: [g(4)] }));
    b.external(shared.get(KEY) ?? null);
    expect(b.snapshot().notices.some((notice) => notice.kind === "diverged")).toBe(true);
    failing.failWrites = null;
    b.reloadFromStorage();
    expect(b.snapshot().doc.entries.map((item) => item.week).sort()).toEqual([6, 9]);
  });

  it("keeps edits in memory when storage is blocked or full", () => {
    const blocked = storeOn(null);
    expect(blocked.snapshot().save).toEqual({ kind: "unsaved", reason: "unavailable" });
    editEntry(blocked, AT, null, (current) => ({ ...current, countZero: [g(1)] }));
    expect(blocked.snapshot().doc.entries).toHaveLength(1);
    const full = new MemoryStorage();
    full.failWrites = "quota";
    const store = storeOn(full);
    editEntry(store, AT, null, (current) => ({ ...current, countZero: [g(1)] }));
    expect(store.snapshot().save).toEqual({ kind: "unsaved", reason: "quota" });
    expect(store.snapshot().doc.entries).toHaveLength(1);
    const unreadable = new MemoryStorage();
    unreadable.failReads = true;
    expect(storeOn(unreadable).snapshot().save).toEqual({ kind: "unsaved", reason: "unavailable" });
  });

  it("backs up unreadable data before writing, and protects it when no backup is possible", () => {
    const storage = new MemoryStorage(new Map([[KEY, "not json"]]));
    const store = storeOn(storage);
    expect(store.snapshot().notices[0]).toMatchObject({ kind: "malformed", backedUp: true });
    expect(stored(storage.map.get(`${KEY}:backup`)).raw).toBe("not json");
    editEntry(store, AT, null, (current) => ({ ...current, countZero: [g(1)] }));
    expect(store.snapshot().save.kind).toBe("saved");

    const locked = new MemoryStorage(new Map([[KEY, "not json"]]));
    locked.failWrites = "error";
    const careful = storeOn(locked);
    expect(careful.snapshot().save).toEqual({ kind: "protected" });
    expect(editEntry(careful, AT, null, (current) => ({ ...current, countZero: [g(1)] }))).toMatchObject({ ok: false, reason: "protected" });
    expect(locked.map.get(KEY)).toBe("not json");
    careful.discardUnreadable();
    expect(careful.snapshot().save.kind).toBe("saved");
  });

  it("is read-only over a newer version's data", () => {
    const newer = JSON.stringify({ format: WMM_FORMAT, version: 3, entries: [] });
    const storage = new MemoryStorage(new Map([[KEY, newer]]));
    const store = storeOn(storage);
    expect(store.snapshot().save).toEqual({ kind: "readonly", version: 3 });
    expect(setWmmPrefs(store, AT.leagueId, { yolo: true })).toMatchObject({ ok: false, reason: "readonly" });
    expect(storage.map.get(KEY)).toBe(newer);
  });

  it("reuses an earlier week's opponent without its finals, confirmations or marks", () => {
    const store = storeOn(new MemoryStorage());
    const last = entry({ week: 5, finals: { [g(8)]: 30 }, marks: { [g(3)]: "available" }, countZero: [g(16)], confirmedEmpty: { mine: ["TE:0"], theirs: [] } });
    const result = reuseEntry(store, AT, last);
    expect(result).toEqual({ ok: true });
    const fresh = findEntry(store.snapshot().doc, AT.leagueId, 2026, 6);
    expect(fresh?.opponent).toEqual(last.opponent);
    expect(fresh?.finals).toEqual({});
    expect(fresh?.marks).toEqual({});
    expect(fresh?.countZero).toEqual([]);
    expect(fresh?.confirmedEmpty).toEqual({ mine: [], theirs: [] });
  });

  it("remembers YOLO per league, off by default", () => {
    const store = storeOn(new MemoryStorage());
    expect(prefsFor(store.snapshot().doc, AT.leagueId).yolo).toBe(false);
    setWmmPrefs(store, AT.leagueId, { yolo: true });
    expect(prefsFor(store.snapshot().doc, AT.leagueId).yolo).toBe(true);
    expect(prefsFor(store.snapshot().doc, "lg-family01").yolo).toBe(false);
    expect(entryKey("lg-a1b2", 2026, 6)).toBe("lg-a1b2|2026|6");
  });
});

describe("the edits", () => {
  const counts = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1 } as const;
  const fits = (group: string, id: string): boolean => group !== "QB" || id === g(8);

  it("assigns opponent starters on the league's layout, swapping or clearing a moved player", () => {
    const start = entry({ confirmedEmpty: { mine: [], theirs: ["WR:0"] } });
    const placed = assignOpponent(start, counts, { group: "WR", index: 0 }, g(20), fits);
    expect(placed.opponent.starters.WR).toEqual([g(20), null]);
    expect(placed.confirmedEmpty.theirs).toEqual([]);
    expect(placed.opponent.starters.TE).toEqual([null]);
    // Moving RB1 to RB2 swaps the two backs.
    const swapped = assignOpponent(placed, counts, { group: "RB", index: 1 }, g(11), fits);
    expect(swapped.opponent.starters.RB).toEqual([g(13), g(11)]);
    // Moving a back to FLEX leaves his old slot empty when the occupant cannot fill it.
    const flexed = assignOpponent(swapped, counts, { group: "FLEX", index: 0 }, g(13), () => false);
    expect(flexed.opponent.starters.RB).toEqual([null, g(11)]);
    expect(flexed.opponent.starters.FLEX).toEqual([g(13)]);
    // A player among their others moves out of that list.
    const promoted = assignOpponent(flexed, counts, { group: "TE", index: 0 }, g(4), fits);
    expect(promoted.opponent.others).toEqual([]);
    expect(assignOpponent(promoted, counts, { group: "TE", index: 0 }, g(4), fits)).toBe(promoted);
  });

  it("clears, trims, removes and adds without duplicates or growth past the bound", () => {
    const start = entry();
    expect(clearOpponentSlot(start, counts, { group: "RB", index: 0 }).opponent.starters.RB).toEqual([null, g(13)]);
    const wide = entry({ opponent: { name: "", starters: { ...emptyStarters(), RB: [g(11), g(13), g(14)] }, others: [] } });
    expect(trimOpponent(wide, counts).opponent.starters.RB).toEqual([g(11), g(13)]);
    expect(removeOpponentPlayer(start, g(4)).opponent.others).toEqual([]);
    expect(removeOpponentPlayer(start, g(11)).opponent.starters.RB).toEqual([null, g(13)]);
    expect(addOpponentOther(start, g(11))).toBe(start);
    let full = entry({ opponent: { name: "", starters: emptyStarters(), others: [] } });
    for (let i = 1; i <= 20; i += 1) full = addOpponentOther(full, g(i));
    expect(full.opponent.others).toHaveLength(14);
  });

  it("confirms empties, zeros, finals and marks, and changes nothing when nothing changes", () => {
    const start = entry();
    const empty = confirmEmpty(start, "mine", "TE:0", true);
    expect(empty.confirmedEmpty.mine).toEqual(["TE:0"]);
    expect(confirmEmpty(empty, "mine", "TE:0", true)).toBe(empty);
    expect(confirmEmpty(empty, "mine", "TE:0", false).confirmedEmpty.mine).toEqual([]);
    expect(countAsZero(start, g(1), true).countZero).toEqual([g(1)]);
    expect(countAsZero(start, g(1), false)).toBe(start);
    const final = setFinal(start, g(8), 24.567);
    expect(final.finals).toEqual({ [g(8)]: 24.57 });
    expect(setFinal(final, g(8), 500)).toBe(final);
    expect(setFinal(final, g(8), null).finals).toEqual({});
    const marked = setMark(start, g(3), "available");
    expect(marked.marks).toEqual({ [g(3)]: "available" });
    expect(setMark(marked, g(3), "unavailable").marks).toEqual({ [g(3)]: "unavailable" });
    expect(setMark(marked, g(3), null).marks).toEqual({});
    expect(renameOpponent(start, "  Mike\n ")).toBe(start);
    expect(renameOpponent(start, "Jordan").opponent.name).toBe("Jordan");
  });
});
