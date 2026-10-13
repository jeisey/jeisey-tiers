/**
 * The saved-leagues contract (ADR-106): what "My Leagues" keeps in this browser, and how a
 * stored payload is read back.
 *
 * **What is stored, and what is not.** Up to three leagues, each with its name, season,
 * scoring and team presets, starter/bench/IR counts, the reader's own roster as canonical
 * player ids per slot, and two small preferences. Nothing else: no projection, no value, no
 * name, no portrait, no artifact record. Every number the workspace shows is read from the
 * current build's artifacts on every visit, joined by canonical id — never by name — so a
 * saved roster can never carry a stale number forward.
 *
 * **The boundary is validated.** A payload is untrusted input: another tab, an older or newer
 * build of this site, a browser extension or a hand edit can all have written it. Nothing here
 * throws on a bad payload; it answers with what it could read and what it set aside, so the
 * store can keep a backup and the page can say so (`parseLeagueDocument`).
 *
 * Pure: no storage access, no clock, no React. `leagueStore.ts` owns the side effects.
 */

import type { Position } from "./contracts";
import { SCORING_VALUES, TEAM_COUNTS, type ScoringValue, type TeamCount } from "./state";

export const LEAGUE_FORMAT = "jeisey-tiers.my-leagues";
/** The contract version this build writes. Bump with a migration in `MIGRATIONS`. */
export const LEAGUE_VERSION = 1;
export const MAX_LEAGUES = 3;
export const LEAGUE_NAME_MAX = 40;

/** Starter groups in lineup order, then the two holding groups. */
export const STARTER_GROUPS = ["QB", "RB", "WR", "TE", "FLEX"] as const;
export type StarterGroup = (typeof STARTER_GROUPS)[number];
export const SLOT_GROUPS = [...STARTER_GROUPS, "BN", "IR"] as const;
export type SlotGroup = (typeof SLOT_GROUPS)[number];

/** Ordinary FLEX: a running back, receiver or tight end. No superflex (ADR-106). */
export const FLEX_ELIGIBLE: readonly Position[] = ["RB", "WR", "TE"];

/**
 * The bounds a league's counts may take, and the defaults a new league starts with.
 *
 * The defaults are the owner's: 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 5 bench, 2 IR. Note that the
 * published presets the boards were built for start **two** FLEX (`config/league-defaults.yaml`),
 * so a default league already differs from them, and every preset-based benchmark says so.
 * The bounds cover ordinary redraft leagues (a two-quarterback league, three receivers, no
 * tight end slot, a deep bench) without admitting a shape no published number speaks to.
 */
export const SLOT_BOUNDS: Readonly<
  Record<SlotGroup, { readonly min: number; readonly max: number; readonly default: number }>
> = {
  QB: { min: 1, max: 2, default: 1 },
  RB: { min: 1, max: 4, default: 2 },
  WR: { min: 1, max: 4, default: 2 },
  TE: { min: 0, max: 2, default: 1 },
  FLEX: { min: 0, max: 3, default: 1 },
  BN: { min: 0, max: 10, default: 5 },
  IR: { min: 0, max: 4, default: 2 },
};

/**
 * The starters every published preset was built for (`config/league-defaults.yaml`: the same at
 * 10, 12 and 14 teams; pinned by `web/tests/leagues-ui.test.tsx`). Rest-of-season VORP, ranks,
 * tiers and the weekly startable thresholds all assume this lineup; a saved league that starts
 * a different one is told so beside every benchmark (ADR-106).
 */
export const PUBLISHED_STARTERS: Readonly<Record<StarterGroup, number>> = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 2 };
export const PUBLISHED_BENCH = 5;

/** Whether a league's starters differ from the lineup the published numbers assume. */
export function startersDiffer(slots: SlotCounts): boolean {
  return STARTER_GROUPS.some((group) => slots[group] !== PUBLISHED_STARTERS[group]);
}

export const SLOT_LABELS: Readonly<Record<SlotGroup, string>> = {
  QB: "QB",
  RB: "RB",
  WR: "WR",
  TE: "TE",
  FLEX: "FLEX",
  BN: "Bench",
  IR: "IR",
};

/** Which positions a slot group accepts. Bench and IR accept anyone. */
export function slotAccepts(group: SlotGroup, position: Position | null): boolean {
  if (group === "BN" || group === "IR") return true;
  if (position === null) return false;
  if (group === "FLEX") return FLEX_ELIGIBLE.includes(position);
  return group === position;
}

export function isStarterGroup(group: SlotGroup): group is StarterGroup {
  return (STARTER_GROUPS as readonly string[]).includes(group);
}

/** Which quantile Auto Start/Sit maximises: the median by default, or the floor or ceiling. */
export const LINEUP_MODES = ["q50", "q10", "q90"] as const;
export type LineupMode = (typeof LINEUP_MODES)[number];

export interface LeaguePrefs {
  /** Show Rising Stars beside the lineup. Remembered per league. */
  readonly risingStars: boolean;
  /** The Auto Start/Sit objective last chosen. A view preference: it never moves a player. */
  readonly mode: LineupMode;
}

export const DEFAULT_PREFS: LeaguePrefs = { risingStars: false, mode: "q50" };

export type SlotCounts = Readonly<Record<SlotGroup, number>>;
/** Canonical player id or null (an empty slot), per slot, in slot order. */
export type Roster = Readonly<Record<SlotGroup, readonly (string | null)[]>>;

export interface SavedLeague {
  readonly id: string;
  readonly name: string;
  readonly season: number;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  readonly slots: SlotCounts;
  readonly roster: Roster;
  readonly prefs: LeaguePrefs;
  /**
   * Bumped by every change to this league. An edit names the revision it was made against,
   * and the store refuses it when another tab has moved the league on since (ADR-106).
   */
  readonly rev: number;
  readonly updatedAt: string;
}

export interface LeagueDocument {
  readonly format: typeof LEAGUE_FORMAT;
  readonly version: typeof LEAGUE_VERSION;
  /** Bumped by every write, whichever league it touched. */
  readonly revision: number;
  readonly activeId: string | null;
  readonly leagues: readonly SavedLeague[];
}

export const EMPTY_DOCUMENT: LeagueDocument = {
  format: LEAGUE_FORMAT,
  version: LEAGUE_VERSION,
  revision: 0,
  activeId: null,
  leagues: [],
};

export const DEFAULT_SLOTS: SlotCounts = Object.fromEntries(
  SLOT_GROUPS.map((group) => [group, SLOT_BOUNDS[group].default]),
) as unknown as SlotCounts;

/** A canonical, namespaced player id (`gsis:00-0036389`). Team units are never players. */
const PLAYER_ID = /^[a-z]{2,12}:[A-Za-z0-9._-]{1,40}$/;
const LEAGUE_ID = /^lg-[a-z0-9]{4,16}$/;

export function isPlayerId(value: unknown): value is string {
  return typeof value === "string" && PLAYER_ID.test(value) && !value.startsWith("dst:");
}

export function emptyRoster(slots: SlotCounts): Roster {
  return Object.fromEntries(
    SLOT_GROUPS.map((group) => [group, Array.from({ length: slots[group] }, () => null)]),
  ) as unknown as Roster;
}

/** Every assigned id in a roster, in slot order. */
export function rosterIds(roster: Roster): string[] {
  const ids: string[] = [];
  for (const group of SLOT_GROUPS) {
    for (const id of roster[group]) if (id !== null) ids.push(id);
  }
  return ids;
}

/** One printable name: trimmed, single-spaced, no control characters, bounded. */
export function cleanLeagueName(raw: string, fallback: string): string {
  // eslint-disable-next-line no-control-regex
  const cleaned = raw.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  return cleaned === "" ? fallback : cleaned.slice(0, LEAGUE_NAME_MAX);
}

// ------------------------------------------------------------------------------ validation

/** Why a stored league could not be read. Each is printed to the reader as a sentence. */
export type LeagueProblem =
  | "not_an_object"
  | "bad_id"
  | "duplicate_id"
  | "bad_name"
  | "bad_season"
  | "unknown_scoring"
  | "unknown_teams"
  | "bad_counts"
  | "bad_roster"
  | "bad_player_id"
  | "duplicate_player"
  | "over_cap";

export const LEAGUE_PROBLEM_TEXT: Readonly<Record<LeagueProblem, string>> = {
  not_an_object: "the entry is not a league",
  bad_id: "its id is malformed",
  duplicate_id: "another saved league has the same id",
  bad_name: "its name is not text",
  bad_season: "its season is not a year",
  unknown_scoring: "its scoring preset is not one this site publishes",
  unknown_teams: "its league size is not one this site publishes",
  bad_counts: "its slot counts are outside the supported bounds",
  bad_roster: "its roster does not match its slot counts",
  bad_player_id: "it names a malformed player id",
  duplicate_player: "it lists one player twice",
  over_cap: "more than three leagues were saved",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown, group: SlotGroup): value is number {
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= SLOT_BOUNDS[group].min &&
    value <= SLOT_BOUNDS[group].max
  );
}

function readPrefs(value: unknown): LeaguePrefs {
  if (!isRecord(value)) return DEFAULT_PREFS;
  const mode = LINEUP_MODES.find((candidate) => candidate === value.mode) ?? DEFAULT_PREFS.mode;
  return { risingStars: value.risingStars === true, mode };
}

/** One stored league, or the first reason it cannot be read. Strict on everything but prefs. */
export function validateLeague(value: unknown): { league: SavedLeague } | { problem: LeagueProblem } {
  if (!isRecord(value)) return { problem: "not_an_object" };
  if (typeof value.id !== "string" || !LEAGUE_ID.test(value.id)) return { problem: "bad_id" };
  if (typeof value.name !== "string") return { problem: "bad_name" };
  if (
    typeof value.season !== "number" ||
    !Number.isInteger(value.season) ||
    value.season < 2000 ||
    value.season > 2100
  ) {
    return { problem: "bad_season" };
  }
  const scoring = SCORING_VALUES.find((candidate) => candidate === value.scoring);
  if (scoring === undefined) return { problem: "unknown_scoring" };
  const teams = TEAM_COUNTS.find((candidate) => candidate === value.teams);
  if (teams === undefined) return { problem: "unknown_teams" };
  if (!isRecord(value.slots)) return { problem: "bad_counts" };
  const counts: Partial<Record<SlotGroup, number>> = {};
  for (const group of SLOT_GROUPS) {
    const count = value.slots[group];
    if (!isCount(count, group)) return { problem: "bad_counts" };
    counts[group] = count;
  }
  const slots = counts as SlotCounts;
  if (!isRecord(value.roster)) return { problem: "bad_roster" };
  const roster: Partial<Record<SlotGroup, (string | null)[]>> = {};
  const seen = new Set<string>();
  for (const group of SLOT_GROUPS) {
    const entries = value.roster[group];
    if (!Array.isArray(entries) || entries.length !== slots[group]) return { problem: "bad_roster" };
    const out: (string | null)[] = [];
    for (const entry of entries as unknown[]) {
      if (entry === null) {
        out.push(null);
        continue;
      }
      if (!isPlayerId(entry)) return { problem: "bad_player_id" };
      if (seen.has(entry)) return { problem: "duplicate_player" };
      seen.add(entry);
      out.push(entry);
    }
    roster[group] = out;
  }
  const rev =
    typeof value.rev === "number" && Number.isInteger(value.rev) && value.rev >= 0 ? value.rev : 0;
  return {
    league: {
      id: value.id,
      name: cleanLeagueName(value.name, "League"),
      season: value.season,
      scoring,
      teams,
      slots,
      roster: roster as Roster,
      prefs: readPrefs(value.prefs),
      rev,
      updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
    },
  };
}

// ------------------------------------------------------------------------------ migrations

/**
 * Upgrades, one version at a time: `MIGRATIONS[n]` turns a version-`n` payload into a
 * version-`n + 1` one. Version 1 is the first published contract, so the table is empty; the
 * stepper is exercised by tests with a synthetic table, so the first real migration lands on a
 * tested path rather than on a new one.
 */
export type Migration = (payload: Record<string, unknown>) => Record<string, unknown>;
export const MIGRATIONS: Readonly<Record<number, Migration>> = {};

export type ParseResult =
  /** Nothing stored: a first visit, or cleared site data. */
  | { readonly kind: "empty" }
  | {
      readonly kind: "ok";
      readonly doc: LeagueDocument;
      /** Leagues that could not be read and were set aside (kept in the backup). */
      readonly setAside: readonly { readonly index: number; readonly problem: LeagueProblem }[];
      /** The version the payload was written in, when it was migrated. */
      readonly migratedFrom: number | null;
    }
  /** Written by a newer build of this site: read-only until the page is reloaded. */
  | { readonly kind: "future"; readonly version: number }
  /** Not JSON, not this format, or not an upgradeable version. Kept in the backup. */
  | { readonly kind: "malformed"; readonly reason: string };

export function parseLeagueDocument(
  raw: string | null,
  migrations: Readonly<Record<number, Migration>> = MIGRATIONS,
  current: number = LEAGUE_VERSION,
): ParseResult {
  if (raw === null || raw === "") return { kind: "empty" };
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return { kind: "malformed", reason: "the saved data is not valid JSON" };
  }
  if (!isRecord(payload) || payload.format !== LEAGUE_FORMAT) {
    return { kind: "malformed", reason: "the saved data is not a My Leagues document" };
  }
  const version = payload.version;
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1) {
    return { kind: "malformed", reason: "the saved data has no readable version" };
  }
  if (version > current) return { kind: "future", version };
  let upgraded: Record<string, unknown> = payload;
  for (let step = version; step < current; step += 1) {
    const migration = migrations[step];
    if (migration === undefined) {
      return { kind: "malformed", reason: `no upgrade from version ${String(step)} is known` };
    }
    try {
      upgraded = migration(upgraded);
    } catch {
      return { kind: "malformed", reason: `the upgrade from version ${String(step)} failed` };
    }
  }
  const entries = Array.isArray(upgraded.leagues) ? (upgraded.leagues as unknown[]) : null;
  if (entries === null) return { kind: "malformed", reason: "the saved data lists no leagues" };

  const leagues: SavedLeague[] = [];
  const setAside: { index: number; problem: LeagueProblem }[] = [];
  const ids = new Set<string>();
  entries.forEach((entry, index) => {
    const result = validateLeague(entry);
    if ("problem" in result) {
      setAside.push({ index, problem: result.problem });
      return;
    }
    if (ids.has(result.league.id)) {
      setAside.push({ index, problem: "duplicate_id" });
      return;
    }
    if (leagues.length >= MAX_LEAGUES) {
      // More than the cap can only come from a hand edit or a future build; keep the first
      // three on screen and the rest in the backup, never silently dropped.
      setAside.push({ index, problem: "over_cap" });
      return;
    }
    ids.add(result.league.id);
    leagues.push(result.league);
  });
  const revision =
    typeof upgraded.revision === "number" && Number.isInteger(upgraded.revision) && upgraded.revision >= 0
      ? upgraded.revision
      : 0;
  const activeId =
    typeof upgraded.activeId === "string" && ids.has(upgraded.activeId)
      ? upgraded.activeId
      : (leagues[0]?.id ?? null);
  return {
    kind: "ok",
    doc: { format: LEAGUE_FORMAT, version: LEAGUE_VERSION, revision, activeId, leagues },
    setAside,
    migratedFrom: version === current ? null : version,
  };
}

export function serializeLeagueDocument(doc: LeagueDocument): string {
  return JSON.stringify(doc);
}

export function activeLeague(doc: LeagueDocument): SavedLeague | null {
  return doc.leagues.find((league) => league.id === doc.activeId) ?? doc.leagues[0] ?? null;
}

/** A new league id, unique within the document. */
export function newLeagueId(doc: LeagueDocument, random: () => number = Math.random): string {
  for (;;) {
    let id = "lg-";
    for (let i = 0; i < 8; i += 1) id += Math.floor(random() * 36).toString(36);
    if (!doc.leagues.some((league) => league.id === id)) return id;
  }
}
