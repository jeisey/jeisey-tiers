/**
 * Win My Matchup's saved inputs (ADR-110 §7): what this browser keeps about a reader's weekly
 * opponents, separate from the saved leagues.
 *
 * **A document of its own.** `jeisey-tiers.win-my-matchup` lives under its own key, so it can
 * never erase or rewrite the leagues document (`leagueContract.ts`), and a build that predates
 * it is unaffected. It stores inputs only — an opponent's name, his starters and other players
 * by canonical id, the slots and players a reader confirmed as zero, confirmed final scores and
 * waiver availability marks — keyed by league, season and week. No result, projection, value
 * or player name is stored: every number is read from the current build on every visit, and a
 * simulation is never saved, so no earlier week's result can be shown as current.
 *
 * **Bounded.** At most four weeks per league and twelve entries in all, oldest week first out;
 * at most fourteen other players, thirty finals and twenty-four marks per entry.
 *
 * **Validated at the boundary**, like the leagues document: a payload is untrusted input, and
 * reading it answers with what it could read and what it set aside. Pure: no storage, clock or
 * React; `wmmStore.ts` owns the side effects.
 */

import {
  SLOT_BOUNDS,
  STARTER_GROUPS,
  cleanLeagueName,
  isPlayerId,
  type StarterGroup,
} from "./leagueContract";

export const WMM_FORMAT = "jeisey-tiers.win-my-matchup";
/** The contract version this build writes. Bump with a migration in `WMM_MIGRATIONS`. */
export const WMM_VERSION = 1;
export const WMM_MAX_ENTRIES = 12;
export const WMM_WEEKS_PER_LEAGUE = 4;
export const WMM_MAX_OTHERS = 14;
export const WMM_MAX_FINALS = 30;
export const WMM_MAX_MARKS = 24;
export const WMM_MAX_PREFS = 6;
/** A final score's bound, in fantasy points either way. */
export const WMM_FINAL_BOUND = 100;
export const OPPONENT_NAME_MAX = 40;

export type Side = "mine" | "theirs";
export type Mark = "available" | "unavailable";

/** The opponent's starters, by group, in slot order: canonical ids or null. */
export type Starters = Readonly<Record<StarterGroup, readonly (string | null)[]>>;

export interface MatchupEntry {
  readonly leagueId: string;
  readonly season: number;
  readonly week: number;
  readonly opponent: {
    readonly name: string;
    readonly starters: Starters;
    /** Bench and IR, together: only ever used to exclude known-owned players. */
    readonly others: readonly string[];
  };
  /** Starter slots (`QB:0`, `FLEX:1`) the reader chose to leave empty, scoring 0. */
  readonly confirmedEmpty: Readonly<Record<Side, readonly string[]>>;
  /** Players out, doubtful or unavailable whom the reader chose to count as 0 if started. */
  readonly countZero: readonly string[];
  /** Final fantasy points the reader confirmed for starters whose games have kicked off. */
  readonly finals: Readonly<Record<string, number>>;
  /** Waiver availability the reader confirmed in their own league. */
  readonly marks: Readonly<Record<string, Mark>>;
  /** Bumped by every change; a stale tab's edit names an older one and is refused. */
  readonly rev: number;
  readonly updatedAt: string;
}

export interface WmmPrefs {
  /** YOLO waiver mode, per league. Off unless the reader turns it on. */
  readonly yolo: boolean;
}

export interface WmmDocument {
  readonly format: typeof WMM_FORMAT;
  readonly version: typeof WMM_VERSION;
  readonly revision: number;
  readonly entries: readonly MatchupEntry[];
  /** League id → preferences. */
  readonly prefs: Readonly<Record<string, WmmPrefs>>;
}

export const EMPTY_WMM: WmmDocument = { format: WMM_FORMAT, version: WMM_VERSION, revision: 0, entries: [], prefs: {} };

export const DEFAULT_WMM_PREFS: WmmPrefs = { yolo: false };

const LEAGUE_ID = /^lg-[a-z0-9]{4,16}$/;
const SLOT_KEY = /^(QB|RB|WR|TE|FLEX):([0-9])$/;

export function entryKey(leagueId: string, season: number, week: number): string {
  return `${leagueId}|${String(season)}|${String(week)}`;
}

export function slotKeyOf(group: StarterGroup, index: number): string {
  return `${group}:${String(index)}`;
}

export function emptyStarters(): Starters {
  return Object.fromEntries(STARTER_GROUPS.map((group) => [group, []])) as unknown as Starters;
}

export function newEntry(leagueId: string, season: number, week: number): MatchupEntry {
  return {
    leagueId,
    season,
    week,
    opponent: { name: "", starters: emptyStarters(), others: [] },
    confirmedEmpty: { mine: [], theirs: [] },
    countZero: [],
    finals: {},
    marks: {},
    rev: 0,
    updatedAt: "",
  };
}

export function cleanOpponentName(raw: string): string {
  return cleanLeagueName(raw, "").slice(0, OPPONENT_NAME_MAX);
}

/** Every id an entry names for the opponent: starters, then others. */
export function opponentIds(entry: MatchupEntry): string[] {
  const ids: string[] = [];
  for (const group of STARTER_GROUPS) for (const id of entry.opponent.starters[group]) if (id !== null) ids.push(id);
  return [...ids, ...entry.opponent.others];
}

/** A final as stored: hundredths of a point, within the bound, or null. */
export function cleanFinal(value: number): number | null {
  if (!Number.isFinite(value) || Math.abs(value) > WMM_FINAL_BOUND) return null;
  return Math.round(value * 100) / 100;
}

// ------------------------------------------------------------------------------ validation

export type EntryProblem =
  | "not_an_object"
  | "bad_league"
  | "bad_week"
  | "bad_starters"
  | "bad_player_id"
  | "duplicate_player"
  | "too_many"
  | "bad_final";

export const ENTRY_PROBLEM_TEXT: Readonly<Record<EntryProblem, string>> = {
  not_an_object: "the entry is not a matchup",
  bad_league: "its league id is malformed",
  bad_week: "its season or week is not readable",
  bad_starters: "its starters are not laid out by slot",
  bad_player_id: "it names a malformed player id",
  duplicate_player: "it lists one player twice",
  too_many: "it holds more players, finals or marks than the contract allows",
  bad_final: "a final score is outside the allowed range",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInt(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= min && value <= max;
}

function readIds(value: unknown, limit: number): string[] | EntryProblem {
  if (!Array.isArray(value)) return "bad_starters";
  if (value.length > limit) return "too_many";
  const out: string[] = [];
  for (const item of value as unknown[]) {
    if (!isPlayerId(item)) return "bad_player_id";
    out.push(item);
  }
  return out;
}

function readSlotKeys(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set((value as unknown[]).filter((item): item is string => typeof item === "string" && SLOT_KEY.test(item)))].slice(0, 15);
}

/** One stored entry, or the first reason it cannot be read. */
export function validateEntry(value: unknown): { entry: MatchupEntry } | { problem: EntryProblem } {
  if (!isRecord(value)) return { problem: "not_an_object" };
  if (typeof value.leagueId !== "string" || !LEAGUE_ID.test(value.leagueId)) return { problem: "bad_league" };
  if (!isInt(value.season, 2000, 2100) || !isInt(value.week, 1, 25)) return { problem: "bad_week" };
  const opponent = value.opponent;
  if (!isRecord(opponent) || !isRecord(opponent.starters)) return { problem: "bad_starters" };
  const seen = new Set<string>();
  const starters: Partial<Record<StarterGroup, (string | null)[]>> = {};
  for (const group of STARTER_GROUPS) {
    const slots = opponent.starters[group];
    if (!Array.isArray(slots) || slots.length > SLOT_BOUNDS[group].max) return { problem: "bad_starters" };
    const out: (string | null)[] = [];
    for (const item of slots as unknown[]) {
      if (item === null) {
        out.push(null);
        continue;
      }
      if (!isPlayerId(item)) return { problem: "bad_player_id" };
      if (seen.has(item)) return { problem: "duplicate_player" };
      seen.add(item);
      out.push(item);
    }
    starters[group] = out;
  }
  const others = readIds(opponent.others ?? [], WMM_MAX_OTHERS);
  if (typeof others === "string") return { problem: others };
  for (const id of others) {
    if (seen.has(id)) return { problem: "duplicate_player" };
    seen.add(id);
  }
  const confirmed = isRecord(value.confirmedEmpty) ? value.confirmedEmpty : {};
  const countZero = readIds(value.countZero ?? [], 30);
  if (typeof countZero === "string") return { problem: countZero };
  const finals: Record<string, number> = {};
  if (value.finals !== undefined) {
    if (!isRecord(value.finals)) return { problem: "bad_final" };
    const pairs = Object.entries(value.finals);
    if (pairs.length > WMM_MAX_FINALS) return { problem: "too_many" };
    for (const [id, points] of pairs) {
      if (!isPlayerId(id)) return { problem: "bad_player_id" };
      const clean = typeof points === "number" ? cleanFinal(points) : null;
      if (clean === null) return { problem: "bad_final" };
      finals[id] = clean;
    }
  }
  const marks: Record<string, Mark> = {};
  if (isRecord(value.marks)) {
    const pairs = Object.entries(value.marks);
    if (pairs.length > WMM_MAX_MARKS) return { problem: "too_many" };
    for (const [id, mark] of pairs) {
      if (!isPlayerId(id)) return { problem: "bad_player_id" };
      if (mark === "available" || mark === "unavailable") marks[id] = mark;
    }
  }
  return {
    entry: {
      leagueId: value.leagueId,
      season: value.season,
      week: value.week,
      opponent: {
        name: typeof opponent.name === "string" ? cleanOpponentName(opponent.name) : "",
        starters: starters as Starters,
        others,
      },
      confirmedEmpty: { mine: readSlotKeys(confirmed.mine), theirs: readSlotKeys(confirmed.theirs) },
      countZero: [...new Set(countZero)],
      finals,
      marks,
      rev: isInt(value.rev, 0, Number.MAX_SAFE_INTEGER) ? value.rev : 0,
      updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
    },
  };
}

function readPrefs(value: unknown): Record<string, WmmPrefs> {
  if (!isRecord(value)) return {};
  const out: Record<string, WmmPrefs> = {};
  for (const [leagueId, prefs] of Object.entries(value).slice(0, WMM_MAX_PREFS)) {
    if (!LEAGUE_ID.test(leagueId) || !isRecord(prefs)) continue;
    out[leagueId] = { yolo: prefs.yolo === true };
  }
  return out;
}

// ---------------------------------------------------------------------------- bounding it

function newer(a: MatchupEntry, b: MatchupEntry): number {
  return b.season - a.season || b.week - a.week || (b.updatedAt < a.updatedAt ? -1 : b.updatedAt > a.updatedAt ? 1 : 0);
}

/**
 * The document within its bounds: each league's four latest weeks, then the twelve latest
 * entries, then six leagues' preferences. Order is newest first, so a dropped entry is always
 * the oldest. Pure; returns the same object when nothing had to go.
 */
export function boundDocument(doc: WmmDocument): WmmDocument {
  const sorted = [...doc.entries].sort(newer);
  const perLeague = new Map<string, number>();
  const kept: MatchupEntry[] = [];
  for (const entry of sorted) {
    const count = perLeague.get(entry.leagueId) ?? 0;
    if (count >= WMM_WEEKS_PER_LEAGUE || kept.length >= WMM_MAX_ENTRIES) continue;
    perLeague.set(entry.leagueId, count + 1);
    kept.push(entry);
  }
  const prefKeys = Object.keys(doc.prefs);
  if (kept.length === doc.entries.length && prefKeys.length <= WMM_MAX_PREFS) return doc;
  const keptSet = new Set(kept);
  return {
    ...doc,
    entries: doc.entries.filter((entry) => keptSet.has(entry)),
    prefs: Object.fromEntries(Object.entries(doc.prefs).slice(-WMM_MAX_PREFS)),
  };
}

// ------------------------------------------------------------------------------ migrations

export type WmmMigration = (payload: Record<string, unknown>) => Record<string, unknown>;
/** Version 1 is the first contract; the stepper is tested with a synthetic table. */
export const WMM_MIGRATIONS: Readonly<Record<number, WmmMigration>> = {};

export type WmmParseResult =
  | { readonly kind: "empty" }
  | {
      readonly kind: "ok";
      readonly doc: WmmDocument;
      readonly setAside: readonly { readonly index: number; readonly problem: EntryProblem | "duplicate_key" }[];
      readonly migratedFrom: number | null;
    }
  | { readonly kind: "future"; readonly version: number }
  | { readonly kind: "malformed"; readonly reason: string };

export function parseWmmDocument(
  raw: string | null,
  migrations: Readonly<Record<number, WmmMigration>> = WMM_MIGRATIONS,
  current: number = WMM_VERSION,
): WmmParseResult {
  if (raw === null || raw === "") return { kind: "empty" };
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return { kind: "malformed", reason: "the saved data is not valid JSON" };
  }
  if (!isRecord(payload) || payload.format !== WMM_FORMAT) {
    return { kind: "malformed", reason: "the saved data is not a Win My Matchup document" };
  }
  const version = payload.version;
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1) {
    return { kind: "malformed", reason: "the saved data has no readable version" };
  }
  if (version > current) return { kind: "future", version };
  let upgraded: Record<string, unknown> = payload;
  for (let step = version; step < current; step += 1) {
    const migration = migrations[step];
    if (migration === undefined) return { kind: "malformed", reason: `no upgrade from version ${String(step)} is known` };
    try {
      upgraded = migration(upgraded);
    } catch {
      return { kind: "malformed", reason: `the upgrade from version ${String(step)} failed` };
    }
  }
  if (!Array.isArray(upgraded.entries)) return { kind: "malformed", reason: "the saved data lists no matchups" };
  const entries: MatchupEntry[] = [];
  const setAside: { index: number; problem: EntryProblem | "duplicate_key" }[] = [];
  const keys = new Set<string>();
  (upgraded.entries as unknown[]).forEach((item, index) => {
    const result = validateEntry(item);
    if ("problem" in result) {
      setAside.push({ index, problem: result.problem });
      return;
    }
    const key = entryKey(result.entry.leagueId, result.entry.season, result.entry.week);
    if (keys.has(key)) {
      setAside.push({ index, problem: "duplicate_key" });
      return;
    }
    keys.add(key);
    entries.push(result.entry);
  });
  const revision = isInt(upgraded.revision, 0, Number.MAX_SAFE_INTEGER) ? upgraded.revision : 0;
  const doc = boundDocument({ format: WMM_FORMAT, version: WMM_VERSION, revision, entries, prefs: readPrefs(upgraded.prefs) });
  return { kind: "ok", doc, setAside, migratedFrom: version === current ? null : version };
}

export function serializeWmmDocument(doc: WmmDocument): string {
  return JSON.stringify(doc);
}

export function findEntry(doc: WmmDocument, leagueId: string, season: number, week: number): MatchupEntry | null {
  return doc.entries.find((entry) => entry.leagueId === leagueId && entry.season === season && entry.week === week) ?? null;
}

/** The most recent entry for this league before `week` of `season` — a rollover candidate. */
export function previousEntry(doc: WmmDocument, leagueId: string, season: number, week: number): MatchupEntry | null {
  return (
    [...doc.entries]
      .filter((entry) => entry.leagueId === leagueId && (entry.season < season || (entry.season === season && entry.week < week)))
      .sort(newer)[0] ?? null
  );
}

export function prefsFor(doc: WmmDocument, leagueId: string): WmmPrefs {
  return doc.prefs[leagueId] ?? DEFAULT_WMM_PREFS;
}

// ------------------------------------------------------------------------------ the edits

/**
 * The edits a reader makes to one week's entry, as pure transforms. Each returns the same
 * object when nothing changes, so the store writes nothing. The opponent's starters are always
 * stored laid out on the league's current slot counts.
 */

type Layout = Readonly<Record<StarterGroup, number>>;

function laid(entry: MatchupEntry, counts: Layout): Record<StarterGroup, (string | null)[]> {
  return Object.fromEntries(
    STARTER_GROUPS.map((group) => [group, Array.from({ length: counts[group] }, (_, index) => entry.opponent.starters[group][index] ?? null)]),
  ) as Record<StarterGroup, (string | null)[]>;
}

function sameStarters(a: Starters, b: Starters): boolean {
  return STARTER_GROUPS.every(
    (group) => a[group].length === b[group].length && a[group].every((id, index) => id === b[group][index]),
  );
}

function withoutKey(list: readonly string[], key: string): readonly string[] {
  return list.includes(key) ? list.filter((item) => item !== key) : list;
}

/**
 * Put a player into one of the opponent's starter slots. A player already in another of their
 * starter slots swaps with the occupant when the occupant fits his old slot (`fits`), and leaves
 * it empty otherwise; a player listed among their others moves out of that list. The slot stops
 * being a confirmed empty one.
 */
export function assignOpponent(
  entry: MatchupEntry,
  counts: Layout,
  slot: { readonly group: StarterGroup; readonly index: number },
  id: string,
  fits: (group: StarterGroup, playerId: string) => boolean,
): MatchupEntry {
  const starters = laid(entry, counts);
  const target = starters[slot.group];
  if (slot.index < 0 || slot.index >= target.length) return entry;
  const occupant = target[slot.index] ?? null;
  if (occupant === id) return entry;
  for (const group of STARTER_GROUPS) {
    const index = starters[group].indexOf(id);
    if (index < 0) continue;
    starters[group][index] = occupant !== null && fits(group, occupant) ? occupant : null;
  }
  target[slot.index] = id;
  return {
    ...entry,
    opponent: { ...entry.opponent, starters, others: entry.opponent.others.filter((other) => other !== id) },
    confirmedEmpty: { ...entry.confirmedEmpty, theirs: withoutKey(entry.confirmedEmpty.theirs, slotKeyOf(slot.group, slot.index)) },
  };
}

/** Empty one opponent starter slot. */
export function clearOpponentSlot(entry: MatchupEntry, counts: Layout, slot: { readonly group: StarterGroup; readonly index: number }): MatchupEntry {
  const starters = laid(entry, counts);
  if ((starters[slot.group][slot.index] ?? null) === null && sameStarters(starters, entry.opponent.starters)) return entry;
  starters[slot.group][slot.index] = null;
  return { ...entry, opponent: { ...entry.opponent, starters } };
}

/** Drop opponent starters the league's counts no longer have room for. */
export function trimOpponent(entry: MatchupEntry, counts: Layout): MatchupEntry {
  const starters = laid(entry, counts);
  return sameStarters(starters, entry.opponent.starters) ? entry : { ...entry, opponent: { ...entry.opponent, starters } };
}

/** Remove a player from the opponent's entry entirely (starters or others). */
export function removeOpponentPlayer(entry: MatchupEntry, id: string): MatchupEntry {
  const inStarters = STARTER_GROUPS.some((group) => entry.opponent.starters[group].includes(id));
  if (!inStarters && !entry.opponent.others.includes(id)) return entry;
  const starters = Object.fromEntries(
    STARTER_GROUPS.map((group) => [group, entry.opponent.starters[group].map((item) => (item === id ? null : item))]),
  ) as unknown as Starters;
  return { ...entry, opponent: { ...entry.opponent, starters, others: entry.opponent.others.filter((other) => other !== id) } };
}

/** Add one of the opponent's bench or IR players. Refused past the bound or when listed already. */
export function addOpponentOther(entry: MatchupEntry, id: string): MatchupEntry {
  if (opponentIds(entry).includes(id) || entry.opponent.others.length >= WMM_MAX_OTHERS) return entry;
  return { ...entry, opponent: { ...entry.opponent, others: [...entry.opponent.others, id] } };
}

export function renameOpponent(entry: MatchupEntry, raw: string): MatchupEntry {
  const name = cleanOpponentName(raw);
  return name === entry.opponent.name ? entry : { ...entry, opponent: { ...entry.opponent, name } };
}

/** Confirm (or withdraw) an empty starter slot as scoring 0. */
export function confirmEmpty(entry: MatchupEntry, side: Side, key: string, on: boolean): MatchupEntry {
  const list = entry.confirmedEmpty[side];
  if (on === list.includes(key)) return entry;
  return { ...entry, confirmedEmpty: { ...entry.confirmedEmpty, [side]: on ? [...list, key] : list.filter((item) => item !== key) } };
}

/** Count (or stop counting) a player who is not playing as 0 when he is started. */
export function countAsZero(entry: MatchupEntry, id: string, on: boolean): MatchupEntry {
  if (on === entry.countZero.includes(id)) return entry;
  return { ...entry, countZero: on ? [...entry.countZero, id] : entry.countZero.filter((item) => item !== id) };
}

/** Record (or clear, with null) a confirmed final score. Refused outside the bound. */
export function setFinal(entry: MatchupEntry, id: string, points: number | null): MatchupEntry {
  if (points === null) {
    if (!(id in entry.finals)) return entry;
    return { ...entry, finals: Object.fromEntries(Object.entries(entry.finals).filter(([key]) => key !== id)) };
  }
  const clean = cleanFinal(points);
  if (clean === null || entry.finals[id] === clean) return entry;
  if (!(id in entry.finals) && Object.keys(entry.finals).length >= WMM_MAX_FINALS) return entry;
  return { ...entry, finals: { ...entry.finals, [id]: clean } };
}

/** Mark a potential pickup available or unavailable in the reader's league (null clears). */
export function setMark(entry: MatchupEntry, id: string, mark: Mark | null): MatchupEntry {
  const current = entry.marks[id] ?? null;
  if (current === mark) return entry;
  const rest = Object.fromEntries(Object.entries(entry.marks).filter(([key]) => key !== id));
  if (mark === null) return { ...entry, marks: rest };
  if (current === null && Object.keys(rest).length >= WMM_MAX_MARKS) return entry;
  return { ...entry, marks: { ...rest, [id]: mark } };
}
