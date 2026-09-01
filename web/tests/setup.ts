/**
 * jsdom gaps the component tests have to fill.
 *
 * `HTMLDialogElement.showModal` and `close` are unimplemented in jsdom, `ResizeObserver` does
 * not exist there at all, and `matchMedia` is absent. All three are polyfilled here rather
 * than worked around in the components: the production code should use the platform API, and
 * the test environment should be the thing that catches up.
 */

import { afterEach, beforeAll } from "vitest";

/**
 * The media-query stub's state, and the handle a test uses to drive it.
 *
 * The player card's sheet variant is a real branch — artboard 1b renders a tab list, which is
 * a different accessibility tree — so it has to be reachable from a component test rather than
 * only from Playwright. Unmatched queries report `false`, which is the wide variant.
 */
const mediaMatches = new Map<string, boolean>();
const mediaListeners = new Map<string, Set<() => void>>();

export function setMediaQuery(query: string, matches: boolean): void {
  mediaMatches.set(query, matches);
  for (const notify of mediaListeners.get(query) ?? []) notify();
}

afterEach(() => {
  mediaMatches.clear();
});

beforeAll(() => {
  if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
    window.matchMedia = (query: string): MediaQueryList => {
      const listeners = mediaListeners.get(query) ?? new Set<() => void>();
      mediaListeners.set(query, listeners);
      return {
        get matches() {
          return mediaMatches.get(query) ?? false;
        },
        media: query,
        onchange: null,
        addEventListener: (_type: string, listener: () => void) => {
          listeners.add(listener);
        },
        removeEventListener: (_type: string, listener: () => void) => {
          listeners.delete(listener);
        },
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      } as unknown as MediaQueryList;
    };
  }

  if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement): void {
      this.open = true;
    };
    HTMLDialogElement.prototype.show = function show(this: HTMLDialogElement): void {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement): void {
      this.open = false;
      this.dispatchEvent(new Event("close"));
    };
  }

  if (typeof globalThis.ResizeObserver === "undefined") {
    // The charts fall back to their default width without one, which is all the geometry
    // assertions need; this only stops the observer path from throwing.
    globalThis.ResizeObserver = class ResizeObserverStub {
      observe(): void {
        /* no layout in jsdom */
      }
      unobserve(): void {
        /* no layout in jsdom */
      }
      disconnect(): void {
        /* no layout in jsdom */
      }
    };
  }
});
