/**
 * A story's chart in the feed (ADR-116): the shared drawing (`marks.ts`) rendered as React SVG
 * at the figure's measured width. The drawing is decoration for assistive technology — the
 * figure carries a visible caption and a sentence that says what it shows, and the exact
 * values are a table under the card's Evidence.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { useElementWidth } from "../../components/useElementWidth";
import type { InsightStory } from "../../data/insights";
import { chartCaption, chartSentence } from "./chartText";
import { PALETTE, canvasMeasure, drawStoryChart, FONT_STACK, type Drawing, type Measure } from "./marks";

let shared: Measure | null = null;
let fontsVersion = 0;
const fontListeners = new Set<() => void>();
let fontsWatched = false;

/** One measurer for every chart on the page; its cache outlives a re-render. */
function pageMeasure(): Measure {
  shared ??= canvasMeasure();
  return shared;
}

/**
 * Lay the charts out again whenever a face finishes loading. A face loads when a page first
 * prints one of its characters — the chart's own labels included — so a drawing laid out
 * against a fallback face is laid out again against the real one, rather than keeping widths
 * measured in the wrong font.
 */
function watchFonts(): void {
  if (fontsWatched || typeof document === "undefined" || !("fonts" in document)) return;
  fontsWatched = true;
  const bump = (): void => {
    shared = null;
    fontsVersion += 1;
    for (const listener of fontListeners) listener();
  };
  document.fonts.addEventListener("loadingdone", bump);
  void Promise.all(
    ["500 11px 'Exo 2'", "600 11px 'Exo 2'", "500 11px 'JetBrains Mono'", "700 11px 'JetBrains Mono'"].map((font) =>
      document.fonts.load(font).catch(() => []),
    ),
  ).then(bump);
}

function useFontsVersion(): number {
  const [version, setVersion] = useState(fontsVersion);
  useEffect(() => {
    watchFonts();
    const listener = (): void => {
      setVersion(fontsVersion);
    };
    fontListeners.add(listener);
    return () => {
      fontListeners.delete(listener);
    };
  }, []);
  return version;
}

export function ChartSvg({ drawing, hatchId }: { readonly drawing: Drawing; readonly hatchId: string }): React.JSX.Element {
  return (
    <svg
      className="ins-chart-svg"
      width={drawing.width}
      height={drawing.height}
      viewBox={`0 0 ${String(drawing.width)} ${String(drawing.height)}`}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <pattern
          id={hatchId}
          patternUnits="userSpaceOnUse"
          width={drawing.hatch}
          height={drawing.hatch}
          patternTransform="rotate(45)"
        >
          <rect width={drawing.hatch} height={drawing.hatch} fill={PALETTE.tile} />
          <line x1={0} y1={0} x2={0} y2={drawing.hatch} stroke={PALETTE.accent} strokeWidth={drawing.hatch * 0.45} />
        </pattern>
      </defs>
      {drawing.marks.map((mark, index) => {
        const key = String(index);
        switch (mark.kind) {
          case "rect":
            return (
              <rect
                key={key}
                x={mark.x}
                y={mark.y}
                width={Math.max(0, mark.w)}
                height={Math.max(0, mark.h)}
                fill={mark.hatch === true ? `url(#${hatchId})` : mark.fill}
                stroke={mark.stroke}
                strokeWidth={mark.strokeWidth}
                strokeDasharray={mark.dash}
              />
            );
          case "line":
            return (
              <line
                key={key}
                x1={mark.x1}
                y1={mark.y1}
                x2={mark.x2}
                y2={mark.y2}
                stroke={mark.stroke}
                strokeWidth={mark.width}
                strokeDasharray={mark.dash}
              />
            );
          case "text":
            return (
              <text
                key={key}
                x={mark.x}
                y={mark.y}
                fill={mark.fill}
                fontFamily={FONT_STACK[mark.style.face]}
                fontSize={mark.style.size}
                fontWeight={mark.style.weight}
                letterSpacing={mark.style.tracking === undefined ? undefined : mark.style.tracking * mark.style.size}
                textAnchor={mark.anchor}
              >
                {mark.text}
              </text>
            );
          case "path":
            return <path key={key} d={mark.d} fill={mark.fill} stroke={mark.stroke} strokeWidth={mark.strokeWidth} />;
        }
      })}
    </svg>
  );
}

export function ChartFigure({ story }: { readonly story: InsightStory }): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const measured = useElementWidth(ref, 560);
  const fonts = useFontsVersion();
  const width = Math.max(240, Math.floor(measured));
  const drawing = useMemo(
    () => drawStoryChart(story, { width, scale: 1, measure: pageMeasure() }),
    // `fonts` re-lays the drawing out once the real faces are in.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [story, width, fonts],
  );
  const id = useId();
  const sentenceId = `${id}-sentence`;
  const caption = chartCaption(story);
  return (
    <figure className="ins-figure" data-chart={story.chart.type} aria-describedby={sentenceId}>
      <figcaption className="ins-figcaption">{caption}</figcaption>
      <div className="ins-chart" ref={ref}>
        <ChartSvg drawing={drawing} hatchId={`${id.replace(/[^a-zA-Z0-9_-]/g, "")}-hatch`} />
      </div>
      <p className="visually-hidden" id={sentenceId}>
        {chartSentence(story)}
      </p>
    </figure>
  );
}
