/**
 * Roving tab focus across chart marks.
 *
 * A 300-player board with 300 tab stops is technically "keyboard accessible" and practically
 * unusable — reaching the table below it would take three hundred presses. The pattern the
 * WAI composite-widget guidance describes is one tab stop for the whole group with arrow keys
 * moving inside it, which is what this implements.
 *
 * The table beside each chart remains the definitive accessible equivalent (`docs/UX_SPEC.md`
 * section 12); this makes the chart itself usable too rather than a trap.
 *
 * The mark element is `Element`, not `SVGGElement`: Phase 8 replaced the Tier Board's one
 * SVG row per player with HTML rows carrying a compact interval glyph, and the pattern is
 * the same either way. Nothing here touches an SVG-only API.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** Any element that can hold focus and a `tabindex`. HTML rows and SVG groups both qualify. */
type MarkElement = Element & { focus: () => void };

export interface RovingMarks {
  readonly activeIndex: number;
  readonly markProps: (index: number) => {
    readonly tabIndex: number;
    readonly ref: (node: MarkElement | null) => void;
    readonly onFocus: () => void;
    readonly onKeyDown: (event: React.KeyboardEvent) => void;
  };
}

export function useRovingMarks(count: number, onActivate: (index: number) => void): RovingMarks {
  const [activeIndex, setActiveIndex] = useState(0);
  const nodes = useRef(new Map<number, MarkElement>());
  const pendingFocus = useRef<number | null>(null);

  // Clamp when the population changes under us (a filter, a preset switch).
  const clamped = count === 0 ? 0 : Math.min(activeIndex, count - 1);

  useEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    nodes.current.get(target)?.focus();
  });

  const markProps = useCallback(
    (index: number) => ({
      tabIndex: index === clamped ? 0 : -1,
      ref: (node: MarkElement | null): void => {
        if (node === null) {
          nodes.current.delete(index);
        } else {
          nodes.current.set(index, node);
        }
      },
      onFocus: (): void => {
        setActiveIndex(index);
      },
      onKeyDown: (event: React.KeyboardEvent): void => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onActivate(index);
          return;
        }
        const step =
          event.key === "ArrowDown" || event.key === "ArrowRight"
            ? 1
            : event.key === "ArrowUp" || event.key === "ArrowLeft"
              ? -1
              : event.key === "Home"
                ? -index
                : event.key === "End"
                  ? count - 1 - index
                  : 0;
        if (step === 0) return;
        event.preventDefault();
        const next = Math.max(0, Math.min(count - 1, index + step));
        setActiveIndex(next);
        pendingFocus.current = next;
      },
    }),
    [clamped, count, onActivate],
  );

  return { activeIndex: clamped, markProps };
}
