/**
 * Subscribe to a CSS media query from React.
 *
 * The player card's three variants are chosen by viewport, and two of them are pure CSS. The
 * third is not: artboard 1b puts its three sections behind a tab bar, and a tab bar is a
 * different accessibility tree — `role="tablist"`, one visible panel, arrow-key movement —
 * rather than a different arrangement of the same one. Showing or hiding tabs with CSS would
 * leave a screen reader on a phone hearing three tabs that control nothing, and every section
 * announced at once.
 *
 * So the branch is explicit and here, using the same breakpoint the stylesheet uses. Keep the
 * two in step; `web/src/styles/base.css` says so at its 767px block.
 *
 * `useSyncExternalStore` rather than `useState` + an effect: a media query *is* an external
 * store, the subscription is the store's own `change` event, and reading it during render is
 * what stops the first paint being the wrong variant.
 *
 * `matchMedia` is absent in some server and test environments; the hook reports `false` there,
 * which resolves to the wide variant — the one that renders every section.
 */

import { useCallback, useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = matchQuery(query);
      if (list === null) return () => undefined;
      list.addEventListener("change", onChange);
      return () => {
        list.removeEventListener("change", onChange);
      };
    },
    [query],
  );
  const read = useCallback(() => matchQuery(query)?.matches ?? false, [query]);
  // The server snapshot is the wide variant, which is also what a build with no `matchMedia`
  // renders — so hydration cannot disagree with the first client paint.
  return useSyncExternalStore(subscribe, read, () => false);
}

function matchQuery(query: string): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(query);
}
