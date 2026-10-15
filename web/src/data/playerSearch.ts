/**
 * The player search's results, over a pool the open board already loaded (ADR-111).
 *
 * One rule decides both what the board shows for a search and what the search dialog lists for
 * it: `matchesSearch`, the board's own case-, accent- and punctuation-insensitive match on
 * name, team and position. So the dialog's count is the board's count, a query applied as typed
 * shows exactly the players the dialog listed, and a picked player is always on the board his
 * name is applied to.
 *
 * Order is stable for a pool: names with a word that starts with the query first, then the
 * rest, each in the pool's own order (the board's), ties never re-sorted by anything typed.
 */

import type { Availability } from "./availability";
import type { PlayerStatusRecord, Position } from "./contracts";
import { matchesSearch, normalizeSearch } from "./model";

/** One player a search can return: identity, and the context that tells two apart. */
export interface SearchEntry {
  /** Canonical player id. A selection is resolved by this, never by the name. */
  readonly id: string;
  readonly name: string;
  readonly position: Position;
  /** The club the board prints (`FA` for a verified free agent), or null. */
  readonly team: string | null;
  /** The in-season availability reading (ADR-101), where the board has one. */
  readonly availability?: Availability | undefined;
  /** The draft board's status annotation, where there is no availability reading. */
  readonly status?: PlayerStatusRecord | null | undefined;
  /** A short trailing line; the team when absent. */
  readonly meta?: string | undefined;
  /** Why he cannot be chosen here, when he cannot (shown, never hidden). */
  readonly unavailableReason?: string | undefined;
}

export interface SearchResult {
  readonly entries: readonly SearchEntry[];
  /** Every match in the pool, of which `entries` is the first `limit`. */
  readonly total: number;
}

/** The words of a name, normalized the way the board matches them. */
function words(name: string): string[] {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .split(/[^a-z0-9]+/)
    .filter((word) => word !== "");
}

export function searchPlayers(
  pool: readonly SearchEntry[],
  query: string,
  limit = 8,
): SearchResult {
  const needle = normalizeSearch(query);
  if (needle === "") return { entries: [], total: 0 };
  const starts: SearchEntry[] = [];
  const rest: SearchEntry[] = [];
  const seen = new Set<string>();
  for (const entry of pool) {
    if (seen.has(entry.id)) continue;
    seen.add(entry.id);
    if (!matchesSearch({ display_name: entry.name, team: entry.team, position: entry.position }, query)) continue;
    const name = normalizeSearch(entry.name);
    if (name.startsWith(needle) || words(entry.name).some((word) => word.startsWith(needle))) starts.push(entry);
    else rest.push(entry);
  }
  return { entries: [...starts, ...rest].slice(0, limit), total: starts.length + rest.length };
}

/** The search term a picked player applies: his name, as the board matches it. */
export function searchTermFor(entry: { readonly name: string }): string {
  return entry.name.trim().slice(0, 64);
}
