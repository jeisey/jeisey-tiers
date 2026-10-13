/**
 * The edits a reader makes to their saved leagues, as store commits (ADR-106).
 *
 * Each names the league revision it was made against, so a stale tab's edit is refused rather
 * than written over a newer one (`leagueStore.ts`, rule 4). Creating a league is checked
 * against the cap on the freshest document, so two tabs cannot together save a fourth.
 */

import {
  DEFAULT_PREFS,
  DEFAULT_SLOTS,
  MAX_LEAGUES,
  cleanLeagueName,
  emptyRoster,
  newLeagueId,
  type LeagueDocument,
  type LeaguePrefs,
  type SavedLeague,
  type SlotCounts,
} from "./leagueContract";
import type { CommitResult, LeagueStore } from "./leagueStore";
import type { ScoringValue, TeamCount } from "./state";

export type OpResult = CommitResult | { readonly ok: false; readonly reason: "cap"; readonly message: string };

const CAP_MESSAGE = `Up to ${String(MAX_LEAGUES)} leagues can be saved. Delete one to add another.`;

export function canAddLeague(doc: LeagueDocument): boolean {
  return doc.leagues.length < MAX_LEAGUES;
}

export interface NewLeague {
  readonly name: string;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  readonly season: number;
  readonly slots?: SlotCounts;
}

export function addLeague(store: LeagueStore, input: NewLeague): OpResult & { readonly id?: string } {
  const before = store.snapshot().doc;
  if (!canAddLeague(before)) return { ok: false, reason: "cap", message: CAP_MESSAGE };
  const id = newLeagueId(before);
  const slots = input.slots ?? DEFAULT_SLOTS;
  let added = false;
  const result = store.commit({
    activate: id,
    apply: (doc) => {
      if (!canAddLeague(doc) || doc.leagues.some((league) => league.id === id)) return doc;
      added = true;
      const league: SavedLeague = {
        id,
        name: cleanLeagueName(input.name, `League ${String(doc.leagues.length + 1)}`),
        season: input.season,
        scoring: input.scoring,
        teams: input.teams,
        slots,
        roster: emptyRoster(slots),
        prefs: DEFAULT_PREFS,
        rev: 0,
        updatedAt: "",
      };
      return { ...doc, activeId: id, leagues: [...doc.leagues, league] };
    },
  });
  if (!result.ok) return result;
  if (!added) return { ok: false, reason: "cap", message: CAP_MESSAGE };
  return { ok: true, id };
}

/** Replace one league with `change(league)`, against the revision the reader saw. */
export function updateLeague(
  store: LeagueStore,
  seen: SavedLeague,
  change: (league: SavedLeague) => SavedLeague,
): OpResult {
  return store.commit({
    expect: { leagueId: seen.id, rev: seen.rev },
    apply: (doc) => ({
      ...doc,
      leagues: doc.leagues.map((league) => (league.id === seen.id ? change(league) : league)),
    }),
  });
}

export function renameLeague(store: LeagueStore, seen: SavedLeague, name: string): OpResult {
  return updateLeague(store, seen, (league) => ({ ...league, name: cleanLeagueName(name, league.name) }));
}

export function setPrefs(store: LeagueStore, seen: SavedLeague, prefs: Partial<LeaguePrefs>): OpResult {
  return updateLeague(store, seen, (league) => ({ ...league, prefs: { ...league.prefs, ...prefs } }));
}

export function deleteLeague(store: LeagueStore, seen: SavedLeague): OpResult {
  return store.commit({
    expect: { leagueId: seen.id, rev: seen.rev },
    apply: (doc) => {
      const leagues = doc.leagues.filter((league) => league.id !== seen.id);
      return { ...doc, leagues, activeId: doc.activeId === seen.id ? (leagues[0]?.id ?? null) : doc.activeId };
    },
  });
}
