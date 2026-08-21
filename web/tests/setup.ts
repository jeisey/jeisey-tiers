/**
 * jsdom gaps the component tests have to fill.
 *
 * `HTMLDialogElement.showModal` and `close` are unimplemented in jsdom, and `ResizeObserver`
 * does not exist there at all. Both are polyfilled here rather than worked around in the
 * components: the production code should use the platform API, and the test environment should
 * be the thing that catches up.
 */

import { beforeAll } from "vitest";

beforeAll(() => {
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
