/**
 * The saved leagues as React state (ADR-106).
 *
 * The store is an external store, read through `useSyncExternalStore` for the same reason the
 * URL is: a render can never see a league the store has already replaced. Tests hand in their
 * own store through `LeagueStoreContext`; the page uses the shared one.
 */

import { createContext, useContext, useSyncExternalStore } from "react";

import { sharedLeagueStore, type LeagueSnapshot, type LeagueStore } from "../data/leagueStore";

export const LeagueStoreContext = createContext<LeagueStore | null>(null);

export function useLeagueStore(): LeagueStore {
  return useContext(LeagueStoreContext) ?? sharedLeagueStore();
}

export function useLeagueSnapshot(): LeagueSnapshot {
  const store = useLeagueStore();
  return useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
}
