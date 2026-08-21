/**
 * The app's single source of state, kept in the address bar.
 *
 * The URL is an external store, so it is read through `useSyncExternalStore` rather than
 * mirrored into component state. That removes the class of bug where the address bar and the
 * rendered board disagree for a frame, and it means back/forward, a pasted link and a control
 * click all flow through exactly one path.
 *
 * `pushState` on a user action, so back/forward walk the boards a user actually looked at;
 * `replaceState` when the app is only normalizing an invalid or redundant URL, so a typo does
 * not become a history entry the back button has to climb over (`docs/UX_SPEC.md` section 10).
 */

import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";

import { type AppState, parseState, serializeState } from "../data/state";

/** Fired after the app itself changes the URL; `popstate` only covers navigation. */
const LOCATION_EVENT = "ffdraft:locationchange";

const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("popstate", listener);
  window.addEventListener(LOCATION_EVENT, listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("popstate", listener);
    window.removeEventListener(LOCATION_EVENT, listener);
  };
}

function getSnapshot(): string {
  return window.location.search;
}

/** Server/prerender snapshot. There is no address bar, so there is no query. */
function getServerSnapshot(): string {
  return "";
}

function writeLocation(query: string, mode: "push" | "replace"): void {
  const href = `${window.location.pathname}${query}`;
  if (mode === "push") {
    window.history.pushState(null, "", href);
  } else {
    window.history.replaceState(null, "", href);
  }
  window.dispatchEvent(new Event(LOCATION_EVENT));
  notify();
}

export interface AppStateController {
  readonly state: AppState;
  readonly setState: (next: Partial<AppState>) => void;
  /** The canonical query string, for building shareable links. */
  readonly query: string;
}

export function useAppState(): AppStateController {
  const search = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const parsed = useMemo(() => parseState(search), [search]);
  const state = parsed.state;
  const canonical = useMemo(() => serializeState(state), [state]);

  // Normalization writes to the external store rather than to component state: an unsupported
  // value must produce a valid board and a clean address bar, not an error (UX spec 10).
  useEffect(() => {
    if (!parsed.normalized || window.location.search !== canonical) {
      writeLocation(canonical, "replace");
    }
  }, [canonical, parsed.normalized]);

  const setState = useCallback((next: Partial<AppState>) => {
    const merged = { ...parseState(window.location.search).state, ...next };
    const query = serializeState(merged);
    if (query !== window.location.search) writeLocation(query, "push");
  }, []);

  return { state, setState, query: canonical };
}
