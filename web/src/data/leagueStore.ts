/**
 * The saved leagues, at runtime: one store per page over one localStorage key (ADR-106).
 *
 * The contract (`leagueContract.ts`) says what a payload is; this file decides when one is
 * read and written, and what the page says when storage misbehaves. Five rules:
 *
 * 1. **Only user changes are written.** `commit` is called by an edit, never by a render, a
 *    data load or a recommendation. A page that only reads leagues never writes the key.
 * 2. **A failed write keeps the edit.** Storage that is unavailable (a private window, blocked
 *    site data) or full keeps the change in memory, and the snapshot says it is not saved.
 * 3. **Nothing unreadable is silently replaced.** A payload this build cannot read is copied to
 *    a backup key before anything else is written; if even the backup cannot be written, the
 *    store refuses to write until the reader explicitly chooses to start over. A payload from a
 *    newer build is never written over at all.
 * 4. **A stale tab cannot overwrite a newer edit.** Every league carries a revision. An edit
 *    names the revision it was made against; before writing, the store re-reads storage, and an
 *    edit to a league another tab has moved on since is refused and reported, not applied.
 *    Edits to different leagues do not conflict.
 * 5. **Which league is open is this tab's.** Switching leagues in one tab does not switch them
 *    in another; the choice is also saved, so the next visit opens it.
 */

import {
  EMPTY_DOCUMENT,
  LEAGUE_PROBLEM_TEXT,
  parseLeagueDocument,
  serializeLeagueDocument,
  type LeagueDocument,
  type SavedLeague,
} from "./leagueContract";

/** The slice of `Storage` the store uses; tests hand in their own. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export type SaveState =
  /** The last change is in this browser's storage. */
  | { readonly kind: "saved" }
  /** Edits work, and live only in this tab until storage accepts a write. */
  | { readonly kind: "unsaved"; readonly reason: "unavailable" | "quota" | "error" }
  /** A newer build wrote the leagues. Nothing is written until the page is reloaded. */
  | { readonly kind: "readonly"; readonly version: number }
  /**
   * The stored data could not be read and no backup could be kept. Nothing is written until
   * the reader chooses to replace it (`discardUnreadable`).
   */
  | { readonly kind: "protected" };

export type LeagueNotice =
  | {
      readonly kind: "set_aside";
      readonly problems: readonly string[];
      readonly backedUp: boolean;
    }
  | { readonly kind: "malformed"; readonly reason: string; readonly backedUp: boolean }
  | { readonly kind: "migrated"; readonly from: number }
  | { readonly kind: "conflict"; readonly message: string }
  /** Another tab saved while this one holds edits that are not saved. */
  | { readonly kind: "diverged" };

export interface LeagueSnapshot {
  readonly doc: LeagueDocument;
  /** The league this tab has open, or null when there is none. */
  readonly activeId: string | null;
  readonly save: SaveState;
  readonly notices: readonly LeagueNotice[];
}

export type CommitResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: "readonly" | "protected" | "conflict"; readonly message: string };

export interface Edit {
  /** The league the edit was made against, and its revision then. Omit for document edits. */
  readonly expect?: { readonly leagueId: string; readonly rev: number };
  /** The change, applied to the freshest document. Return the same object for "no change". */
  readonly apply: (doc: LeagueDocument) => LeagueDocument;
  /** Make this league the tab's open one after the edit. */
  readonly activate?: string;
}

export function leagueStorageKey(base: string): string {
  return `jeisey-tiers:my-leagues@${base}`;
}

function isQuota(error: unknown): boolean {
  if (typeof DOMException !== "undefined" && error instanceof DOMException) {
    return error.name === "QuotaExceededError" || error.name === "NS_ERROR_DOM_QUOTA_REACHED";
  }
  return error instanceof Error && /quota/i.test(error.message);
}

export class LeagueStore {
  private readonly storage: StorageLike | null;
  private readonly key: string;
  private readonly clock: () => string;
  private readonly listeners = new Set<() => void>();
  private doc: LeagueDocument = EMPTY_DOCUMENT;
  private save: SaveState = { kind: "saved" };
  private notices: LeagueNotice[] = [];
  private localActive: string | null = null;
  /** The serialized document storage last held as far as this tab knows. */
  private known: string | null = null;
  private current: LeagueSnapshot;

  constructor(options: {
    readonly storage: StorageLike | null;
    readonly key: string;
    readonly clock?: () => string;
  }) {
    this.storage = options.storage;
    this.key = options.key;
    this.clock = options.clock ?? (() => new Date().toISOString());
    this.load();
    this.current = this.build();
  }

  // ------------------------------------------------------------------------- reading

  private read(): { ok: true; raw: string | null } | { ok: false } {
    if (this.storage === null) return { ok: false };
    try {
      return { ok: true, raw: this.storage.getItem(this.key) };
    } catch {
      return { ok: false };
    }
  }

  /** Copy an unreadable payload aside. True when the copy is in storage. */
  private backup(raw: string, reason: string): boolean {
    if (this.storage === null) return false;
    try {
      this.storage.setItem(
        `${this.key}:backup`,
        JSON.stringify({ savedAt: this.clock(), reason, raw }),
      );
      return true;
    } catch {
      return false;
    }
  }

  private load(): void {
    const read = this.read();
    if (!read.ok) {
      this.doc = EMPTY_DOCUMENT;
      this.save = { kind: "unsaved", reason: "unavailable" };
      return;
    }
    this.adopt(read.raw, true);
  }

  /** Take a stored payload as the document. `initial` decides whether problems are noticed. */
  private adopt(raw: string | null, initial: boolean): void {
    const parsed = parseLeagueDocument(raw);
    switch (parsed.kind) {
      case "empty":
        this.doc = EMPTY_DOCUMENT;
        this.known = raw;
        this.save = { kind: "saved" };
        return;
      case "future":
        this.doc = EMPTY_DOCUMENT;
        this.known = raw;
        this.save = { kind: "readonly", version: parsed.version };
        return;
      case "malformed": {
        const backedUp = raw !== null && this.backup(raw, parsed.reason);
        if (initial || !this.notices.some((notice) => notice.kind === "malformed")) {
          this.notices.push({ kind: "malformed", reason: parsed.reason, backedUp });
        }
        this.doc = EMPTY_DOCUMENT;
        this.known = raw;
        this.save = backedUp ? { kind: "saved" } : { kind: "protected" };
        return;
      }
      case "ok": {
        if (parsed.setAside.length > 0 || parsed.migratedFrom !== null) {
          const backedUp = raw !== null && this.backup(raw, "set aside or migrated");
          if (parsed.setAside.length > 0) {
            this.notices.push({
              kind: "set_aside",
              problems: parsed.setAside.map(
                (entry) => `saved league ${String(entry.index + 1)}: ${LEAGUE_PROBLEM_TEXT[entry.problem]}`,
              ),
              backedUp,
            });
            if (!backedUp) this.save = { kind: "protected" };
          }
          if (parsed.migratedFrom !== null) this.notices.push({ kind: "migrated", from: parsed.migratedFrom });
        }
        this.doc = parsed.doc;
        this.known = raw;
        if (this.save.kind !== "protected") this.save = { kind: "saved" };
        if (this.localActive !== null && !parsed.doc.leagues.some((league) => league.id === this.localActive)) {
          this.localActive = null;
        }
        return;
      }
    }
  }

  private build(): LeagueSnapshot {
    const ids = new Set(this.doc.leagues.map((league) => league.id));
    const activeId =
      this.localActive !== null && ids.has(this.localActive)
        ? this.localActive
        : this.doc.activeId !== null && ids.has(this.doc.activeId)
          ? this.doc.activeId
          : (this.doc.leagues[0]?.id ?? null);
    return { doc: this.doc, activeId, save: this.save, notices: [...this.notices] };
  }

  private notify(): void {
    this.current = this.build();
    for (const listener of this.listeners) listener();
  }

  // ------------------------------------------------------------------------- public

  snapshot = (): LeagueSnapshot => this.current;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Open a league in this tab. Saved as the default for the next visit, best effort. */
  activate(leagueId: string): void {
    if (!this.doc.leagues.some((league) => league.id === leagueId)) return;
    this.localActive = leagueId;
    this.notify();
    if (this.doc.activeId !== leagueId) {
      this.commit({ apply: (doc) => ({ ...doc, activeId: leagueId }) });
    }
  }

  dismiss(kind: LeagueNotice["kind"]): void {
    const before = this.notices.length;
    this.notices = this.notices.filter((notice) => notice.kind !== kind);
    if (this.notices.length !== before) this.notify();
  }

  /** The reader chose to replace unreadable data that could not be backed up. */
  discardUnreadable(): void {
    if (this.save.kind !== "protected") return;
    this.save = { kind: "saved" };
    this.notices = this.notices.filter((notice) => notice.kind !== "malformed" && notice.kind !== "set_aside");
    this.notify();
  }

  /** Re-read storage and take what it holds, dropping edits that were never saved. */
  reloadFromStorage(): void {
    const read = this.read();
    if (!read.ok) return;
    this.notices = this.notices.filter((notice) => notice.kind !== "diverged" && notice.kind !== "conflict");
    this.adopt(read.raw, false);
    this.notify();
  }

  /** Another tab wrote the key (a `storage` event). */
  external(raw: string | null): void {
    if (raw === this.known) return;
    if (this.save.kind === "unsaved") {
      // This tab holds edits storage never accepted; adopting would lose them silently.
      if (!this.notices.some((notice) => notice.kind === "diverged")) {
        this.notices.push({ kind: "diverged" });
        this.notify();
      }
      return;
    }
    const parsed = parseLeagueDocument(raw);
    // Garbage written by someone else is not adopted; the next commit backs it up first.
    if (parsed.kind === "malformed") return;
    this.adopt(raw, false);
    this.notify();
  }

  commit(edit: Edit): CommitResult {
    if (this.save.kind === "readonly") {
      return {
        ok: false,
        reason: "readonly",
        message: "Your leagues were saved by a newer version of this site. Reload the page to edit them.",
      };
    }
    if (this.save.kind === "protected") {
      return {
        ok: false,
        reason: "protected",
        message: "The saved data could not be read or backed up, so nothing is written until you choose to replace it.",
      };
    }
    // Rebase onto what storage holds now: another tab may have written since our last look.
    if (this.save.kind === "saved") {
      const read = this.read();
      if (read.ok && read.raw !== this.known) {
        const parsed = parseLeagueDocument(read.raw);
        if (parsed.kind === "future") {
          this.adopt(read.raw, false);
          this.notify();
          return {
            ok: false,
            reason: "readonly",
            message: "Another tab saved your leagues with a newer version of this site. Reload the page to edit them.",
          };
        }
        if (parsed.kind === "malformed" && read.raw !== null) {
          this.backup(read.raw, parsed.reason);
        } else {
          this.adopt(read.raw, false);
        }
      }
    }
    if (edit.expect !== undefined) {
      const league = this.doc.leagues.find((candidate) => candidate.id === edit.expect?.leagueId);
      if (league?.rev !== edit.expect.rev) {
        const message =
          league === undefined
            ? "That league was deleted in another tab, so the change was not applied."
            : `“${league.name}” was changed in another tab, so your last change was not applied. The newer version is shown.`;
        this.notices = this.notices.filter((notice) => notice.kind !== "conflict");
        this.notices.push({ kind: "conflict", message });
        this.notify();
        return { ok: false, reason: "conflict", message };
      }
    }
    const next = edit.apply(this.doc);
    if (next === this.doc && edit.activate === undefined) return { ok: true };
    const stamped = this.stamp(this.doc, next);
    if (edit.activate !== undefined) this.localActive = edit.activate;
    this.doc = stamped;
    this.write(stamped);
    this.notify();
    return { ok: true };
  }

  /** Bump the document revision, and each changed league's revision and time. */
  private stamp(previous: LeagueDocument, next: LeagueDocument): LeagueDocument {
    const before = new Map(previous.leagues.map((league) => [league.id, league]));
    const now = this.clock();
    const leagues = next.leagues.map((league): SavedLeague => {
      const old = before.get(league.id);
      if (old === league) return league;
      return { ...league, rev: (old?.rev ?? 0) + 1, updatedAt: now };
    });
    return { ...next, revision: previous.revision + 1, leagues };
  }

  private write(doc: LeagueDocument): void {
    if (this.storage === null) {
      this.save = { kind: "unsaved", reason: "unavailable" };
      return;
    }
    const serialized = serializeLeagueDocument(doc);
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

/** `window.localStorage`, or null where touching it throws (blocked site data, sandboxing). */
export function browserStorage(): StorageLike | null {
  try {
    if (typeof window === "undefined") return null;
    const storage = window.localStorage;
    // Some browsers expose the object and throw on first use.
    storage.getItem("jeisey-tiers:probe");
    return storage;
  } catch {
    return null;
  }
}

let shared: LeagueStore | null = null;

/** The page's one store, created on first use and kept in step with other tabs. */
export function sharedLeagueStore(): LeagueStore {
  if (shared !== null) return shared;
  const key = leagueStorageKey(import.meta.env.BASE_URL);
  const storage = browserStorage();
  const store = new LeagueStore({ storage, key });
  if (typeof window !== "undefined") {
    window.addEventListener("storage", (event) => {
      if (event.key === key || event.key === null) store.external(event.key === null ? null : event.newValue);
    });
  }
  shared = store;
  return store;
}
