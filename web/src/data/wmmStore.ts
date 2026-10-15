/**
 * Win My Matchup's saved inputs at runtime (ADR-110 §7): one store per page over its own
 * localStorage key, with the saved-leagues store's rules (ADR-106) applied to matchup entries.
 *
 * 1. **Only user changes are written.** Opening the view, loading data and simulating never
 *    write; a page that only reads matchups never touches the key.
 * 2. **A failed write keeps the edit** in memory and says it is not saved.
 * 3. **Nothing unreadable is silently replaced.** An unreadable or partly set-aside payload is
 *    copied to `<key>:backup` first; if that fails the store is protected until the reader
 *    chooses. A newer build's payload is read-only.
 * 4. **A stale tab cannot overwrite a newer edit.** Each entry carries a revision; an edit
 *    names the one it was made against (or that the entry did not exist), the store re-reads
 *    storage first, and a mismatch is refused and reported. Different entries do not conflict.
 * 5. **Bounded.** Every write keeps the document within `boundDocument`'s limits.
 */

import { browserStorage, isQuota, type SaveState, type StorageLike } from "./leagueStore";
import {
  ENTRY_PROBLEM_TEXT,
  EMPTY_WMM,
  boundDocument,
  entryKey,
  findEntry,
  newEntry,
  parseWmmDocument,
  serializeWmmDocument,
  type MatchupEntry,
  type WmmDocument,
  type WmmPrefs,
} from "./wmmContract";

export type WmmNotice =
  | { readonly kind: "set_aside"; readonly problems: readonly string[]; readonly backedUp: boolean }
  | { readonly kind: "malformed"; readonly reason: string; readonly backedUp: boolean }
  | { readonly kind: "migrated"; readonly from: number }
  | { readonly kind: "conflict"; readonly message: string }
  | { readonly kind: "diverged" };

export interface WmmSnapshot {
  readonly doc: WmmDocument;
  readonly save: SaveState;
  readonly notices: readonly WmmNotice[];
}

export type WmmCommit =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: "readonly" | "protected" | "conflict"; readonly message: string };

export interface WmmEdit {
  /** The entry the edit was made against: its revision, or null when it did not exist yet. */
  readonly expect?: { readonly key: string; readonly rev: number | null };
  readonly apply: (doc: WmmDocument) => WmmDocument;
}

export function wmmStorageKey(base: string): string {
  return `jeisey-tiers:win-my-matchup@${base}`;
}

export class WmmStore {
  private readonly storage: StorageLike | null;
  private readonly key: string;
  private readonly clock: () => string;
  private readonly listeners = new Set<() => void>();
  private doc: WmmDocument = EMPTY_WMM;
  private save: SaveState = { kind: "saved" };
  private notices: WmmNotice[] = [];
  private known: string | null = null;
  private current: WmmSnapshot;

  constructor(options: { readonly storage: StorageLike | null; readonly key: string; readonly clock?: () => string }) {
    this.storage = options.storage;
    this.key = options.key;
    this.clock = options.clock ?? (() => new Date().toISOString());
    const read = this.read();
    if (read.ok) this.adopt(read.raw, true);
    else this.save = { kind: "unsaved", reason: "unavailable" };
    this.current = this.build();
  }

  private read(): { ok: true; raw: string | null } | { ok: false } {
    if (this.storage === null) return { ok: false };
    try {
      return { ok: true, raw: this.storage.getItem(this.key) };
    } catch {
      return { ok: false };
    }
  }

  private backup(raw: string, reason: string): boolean {
    if (this.storage === null) return false;
    try {
      this.storage.setItem(`${this.key}:backup`, JSON.stringify({ savedAt: this.clock(), reason, raw }));
      return true;
    } catch {
      return false;
    }
  }

  private adopt(raw: string | null, initial: boolean): void {
    const parsed = parseWmmDocument(raw);
    switch (parsed.kind) {
      case "empty":
        this.doc = EMPTY_WMM;
        this.known = raw;
        this.save = { kind: "saved" };
        return;
      case "future":
        this.doc = EMPTY_WMM;
        this.known = raw;
        this.save = { kind: "readonly", version: parsed.version };
        return;
      case "malformed": {
        const backedUp = raw !== null && this.backup(raw, parsed.reason);
        if (initial || !this.notices.some((notice) => notice.kind === "malformed")) {
          this.notices.push({ kind: "malformed", reason: parsed.reason, backedUp });
        }
        this.doc = EMPTY_WMM;
        this.known = raw;
        this.save = backedUp ? { kind: "saved" } : { kind: "protected" };
        return;
      }
      case "ok": {
        let protectedNow = false;
        if (parsed.setAside.length > 0 || parsed.migratedFrom !== null) {
          const backedUp = raw !== null && this.backup(raw, "set aside or migrated");
          if (parsed.setAside.length > 0) {
            this.notices.push({
              kind: "set_aside",
              problems: parsed.setAside.map(
                (item) =>
                  `saved matchup ${String(item.index + 1)}: ${item.problem === "duplicate_key" ? "another saved matchup is for the same league and week" : ENTRY_PROBLEM_TEXT[item.problem]}`,
              ),
              backedUp,
            });
            protectedNow = !backedUp;
          }
          if (parsed.migratedFrom !== null) this.notices.push({ kind: "migrated", from: parsed.migratedFrom });
        }
        this.doc = parsed.doc;
        this.known = raw;
        this.save = protectedNow ? { kind: "protected" } : { kind: "saved" };
        return;
      }
    }
  }

  private build(): WmmSnapshot {
    return { doc: this.doc, save: this.save, notices: [...this.notices] };
  }

  private notify(): void {
    this.current = this.build();
    for (const listener of this.listeners) listener();
  }

  snapshot = (): WmmSnapshot => this.current;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  dismiss(kind: WmmNotice["kind"]): void {
    const before = this.notices.length;
    this.notices = this.notices.filter((notice) => notice.kind !== kind);
    if (this.notices.length !== before) this.notify();
  }

  discardUnreadable(): void {
    if (this.save.kind !== "protected") return;
    this.save = { kind: "saved" };
    this.notices = this.notices.filter((notice) => notice.kind !== "malformed" && notice.kind !== "set_aside");
    this.notify();
  }

  reloadFromStorage(): void {
    const read = this.read();
    if (!read.ok) return;
    this.notices = this.notices.filter((notice) => notice.kind !== "diverged" && notice.kind !== "conflict");
    this.adopt(read.raw, false);
    this.notify();
  }

  /** Another tab wrote the key. */
  external(raw: string | null): void {
    if (raw === this.known) return;
    if (this.save.kind === "unsaved") {
      if (!this.notices.some((notice) => notice.kind === "diverged")) {
        this.notices.push({ kind: "diverged" });
        this.notify();
      }
      return;
    }
    if (parseWmmDocument(raw).kind === "malformed") return;
    this.adopt(raw, false);
    this.notify();
  }

  commit(edit: WmmEdit): WmmCommit {
    if (this.save.kind === "readonly") {
      return { ok: false, reason: "readonly", message: "Your matchups were saved by a newer version of this site. Reload the page to edit them." };
    }
    if (this.save.kind === "protected") {
      return { ok: false, reason: "protected", message: "The saved matchups could not be read or backed up, so nothing is written until you choose to replace them." };
    }
    if (this.save.kind === "saved") {
      const read = this.read();
      if (read.ok && read.raw !== this.known) {
        const parsed = parseWmmDocument(read.raw);
        if (parsed.kind === "future") {
          this.adopt(read.raw, false);
          this.notify();
          return { ok: false, reason: "readonly", message: "Another tab saved your matchups with a newer version of this site. Reload the page to edit them." };
        }
        if (parsed.kind === "malformed" && read.raw !== null) this.backup(read.raw, parsed.reason);
        else this.adopt(read.raw, false);
      }
    }
    if (edit.expect !== undefined) {
      const found = this.doc.entries.find(
        (entry) => entryKey(entry.leagueId, entry.season, entry.week) === edit.expect?.key,
      );
      const rev = found?.rev ?? null;
      if (rev !== edit.expect.rev) {
        const message =
          found === undefined
            ? "That matchup was removed in another tab, so the change was not applied."
            : "This week's matchup was changed in another tab, so your last change was not applied. The newer version is shown.";
        this.notices = this.notices.filter((notice) => notice.kind !== "conflict");
        this.notices.push({ kind: "conflict", message });
        this.notify();
        return { ok: false, reason: "conflict", message };
      }
    }
    const next = edit.apply(this.doc);
    if (next === this.doc) return { ok: true };
    const stamped = boundDocument(this.stamp(this.doc, next));
    this.doc = stamped;
    this.write(stamped);
    this.notify();
    return { ok: true };
  }

  private stamp(previous: WmmDocument, next: WmmDocument): WmmDocument {
    const before = new Map(previous.entries.map((entry) => [entryKey(entry.leagueId, entry.season, entry.week), entry]));
    const now = this.clock();
    const entries = next.entries.map((entry): MatchupEntry => {
      const old = before.get(entryKey(entry.leagueId, entry.season, entry.week));
      if (old === entry) return entry;
      return { ...entry, rev: (old?.rev ?? 0) + 1, updatedAt: now };
    });
    return { ...next, revision: previous.revision + 1, entries };
  }

  private write(doc: WmmDocument): void {
    if (this.storage === null) {
      this.save = { kind: "unsaved", reason: "unavailable" };
      return;
    }
    const serialized = serializeWmmDocument(doc);
    try {
      this.storage.setItem(this.key, serialized);
      this.known = serialized;
      this.save = { kind: "saved" };
      this.notices = this.notices.filter((notice) => notice.kind !== "diverged");
    } catch (error) {
      this.save = { kind: "unsaved", reason: isQuota(error) ? "quota" : "error" };
    }
  }
}

// ------------------------------------------------------------------------------- the edits

/**
 * Change this week's entry, creating it when it does not exist yet. `seen` is the entry the
 * reader was looking at (null when there was none), so a stale tab's edit is refused.
 */
export function editEntry(
  store: WmmStore,
  at: { readonly leagueId: string; readonly season: number; readonly week: number },
  seen: MatchupEntry | null,
  change: (entry: MatchupEntry) => MatchupEntry,
): WmmCommit {
  const key = entryKey(at.leagueId, at.season, at.week);
  return store.commit({
    expect: { key, rev: seen?.rev ?? null },
    apply: (doc) => {
      const existing = findEntry(doc, at.leagueId, at.season, at.week);
      const base = existing ?? newEntry(at.leagueId, at.season, at.week);
      const changed = change(base);
      // No change writes nothing, and an untouched new entry is never created.
      if (changed === base) return doc;
      return {
        ...doc,
        entries: existing === null ? [...doc.entries, changed] : doc.entries.map((entry) => (entry === existing ? changed : entry)),
      };
    },
  });
}

/** Start this week's entry from an earlier week's opponent: starters and others only. */
export function reuseEntry(
  store: WmmStore,
  at: { readonly leagueId: string; readonly season: number; readonly week: number },
  from: MatchupEntry,
): WmmCommit {
  return editEntry(store, at, null, (entry) => ({
    ...entry,
    opponent: { name: from.opponent.name, starters: from.opponent.starters, others: from.opponent.others },
  }));
}

export function setWmmPrefs(store: WmmStore, leagueId: string, prefs: Partial<WmmPrefs>): WmmCommit {
  return store.commit({
    apply: (doc) => {
      const current = doc.prefs[leagueId] ?? { yolo: false };
      const next = { ...current, ...prefs };
      if (next.yolo === current.yolo && doc.prefs[leagueId] !== undefined) return doc;
      const rest = Object.fromEntries(Object.entries(doc.prefs).filter(([id]) => id !== leagueId));
      return { ...doc, prefs: { ...rest, [leagueId]: next } };
    },
  });
}

let shared: WmmStore | null = null;

/** The page's one matchup store, created on first use and kept in step with other tabs. */
export function sharedWmmStore(): WmmStore {
  if (shared !== null) return shared;
  const key = wmmStorageKey(import.meta.env.BASE_URL);
  const store = new WmmStore({ storage: browserStorage(), key });
  if (typeof window !== "undefined") {
    window.addEventListener("storage", (event) => {
      if (event.key === key || event.key === null) store.external(event.key === null ? null : event.newValue);
    });
  }
  shared = store;
  return store;
}
