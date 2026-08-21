/**
 * The measured width of an element, for charts that must size themselves.
 *
 * SVG geometry needs a number, and a responsive layout only knows one after paint. A
 * `ResizeObserver` keeps the number current without a resize listener firing on every pixel of
 * a drag, and the fallback covers jsdom, where no observer exists and the tests only need the
 * component to render at a stable width.
 */

import { useEffect, useState, type RefObject } from "react";

export function useElementWidth(ref: RefObject<HTMLElement | null>, fallback = 960): number {
  const [width, setWidth] = useState(fallback);

  useEffect(() => {
    const node = ref.current;
    if (node === null) return;
    if (typeof ResizeObserver === "undefined") {
      const measured = node.getBoundingClientRect().width;
      if (measured > 0) setWidth(measured);
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry === undefined) return;
      const measured = entry.contentRect.width;
      // Zero happens while a tab is hidden; keeping the previous width avoids a chart that
      // collapses and then re-lays-out every time the user switches back.
      if (measured > 0) setWidth(measured);
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [ref]);

  return width;
}

/** True when the viewer asked the operating system for less motion. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = (): void => {
      setReduced(query.matches);
    };
    query.addEventListener("change", update);
    return () => {
      query.removeEventListener("change", update);
    };
  }, []);

  return reduced;
}
