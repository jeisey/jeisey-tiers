/**
 * The Insights charts as geometry (ADR-116): one drawing per story, rendered twice — as React
 * SVG in the feed and as an SVG string in the share card — so the export cannot disagree with
 * the page. Every function here is pure; text is laid out with a `Measure` the caller supplies
 * (the canvas's own `measureText` with the self-hosted fonts in a browser, an approximation in
 * tests), so a label that would not fit is shortened or moved, never clipped.
 *
 * The rules each chart keeps (AGENTS.md section 11, `docs/UX_SPEC.md`):
 *
 * - **honest scales** — every bar starts at zero, and a share keeps a zero-based scale;
 * - **separate units, separate rows** — never a dual axis: opportunities and points are two
 *   aligned rows on one week axis;
 * - **direct labels** — numbers sit on the marks, and meaning never rests on colour alone (TD
 *   points are hatched *and* named, a strong week is a triangle *and* a bold rank, a bye is a B);
 * - **absence is not zero** — a bye, a game missed and a missing value each print a letter or a
 *   dash, never a floor-height bar.
 */

import type {
  InsightInterval,
  InsightRoom,
  InsightStatLine,
  InsightWeekStrip,
  InsightWithWithout,
} from "../../data/contracts";
import type { InsightStory } from "../../data/insights";

// ------------------------------------------------------------------------------ types

export type FontFace = "sans" | "mono";

export interface TextStyle {
  readonly size: number;
  readonly weight: 400 | 500 | 600 | 700;
  readonly face: FontFace;
  /** Letter spacing in em. */
  readonly tracking?: number;
}

/** A rendered line's width in px. */
export type Measure = (text: string, style: TextStyle) => number;

export type Mark =
  | {
      readonly kind: "rect";
      readonly x: number;
      readonly y: number;
      readonly w: number;
      readonly h: number;
      readonly fill: string;
      readonly stroke?: string;
      readonly strokeWidth?: number;
      readonly dash?: string;
      /** Fill with the drawing's diagonal hatch instead of `fill` (which tints the hatch). */
      readonly hatch?: boolean;
    }
  | {
      readonly kind: "line";
      readonly x1: number;
      readonly y1: number;
      readonly x2: number;
      readonly y2: number;
      readonly stroke: string;
      readonly width: number;
      readonly dash?: string;
    }
  | {
      readonly kind: "text";
      readonly x: number;
      /** The baseline. */
      readonly y: number;
      readonly text: string;
      readonly style: TextStyle;
      readonly fill: string;
      readonly anchor: "start" | "middle" | "end";
    }
  | { readonly kind: "path"; readonly d: string; readonly fill: string; readonly stroke?: string; readonly strokeWidth?: number };

export interface Drawing {
  readonly width: number;
  readonly height: number;
  readonly marks: readonly Mark[];
  /** The hatch's spacing, scaled with the drawing. */
  readonly hatch: number;
}

export interface DrawOptions {
  readonly width: number;
  /** Type and spacing scale: 1 in the feed, larger in the share card. */
  readonly scale: number;
  readonly measure: Measure;
}

/** The board's tokens (`base.css`), resolved, because an exported SVG has no stylesheet. */
export const PALETTE = {
  canvas: "#050b14",
  panel: "#081422",
  tile: "#0b1a2a",
  ink: "#e6f3ff",
  strong: "#c7e6ff",
  accentInk: "#9fd8ff",
  muted: "#8fb2d2",
  faint: "#7e9bb9",
  accent: "#2eccff",
  bright: "#66f1ff",
  fill: "#2563a9",
  good: "#22d19a",
  warn: "#ffb347",
  wash: "rgba(46,204,255,0.08)",
  line: "rgba(46,204,255,0.22)",
  lineStrong: "rgba(46,204,255,0.4)",
} as const;

export const FONT_STACK: Readonly<Record<FontFace, string>> = {
  sans: "'Exo 2', ui-sans-serif, system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
};

/** The CSS font shorthand a canvas measures with. */
export function canvasFont(style: TextStyle): string {
  return `${String(style.weight)} ${String(style.size)}px ${style.face === "mono" ? "'JetBrains Mono'" : "'Exo 2'"}`;
}

/**
 * A width estimate for environments with no canvas (jsdom). Deliberately on the wide side of
 * both faces, so a layout that fits here fits the real fonts too.
 */
export const approximateMeasure: Measure = (text, style) => {
  const per = style.face === "mono" ? 0.62 : style.weight >= 600 ? 0.6 : 0.56;
  return text.length * style.size * (per + (style.tracking ?? 0));
};

/**
 * A measurer over the browser's canvas with the page's fonts. Tracking is added per character,
 * as SVG `letter-spacing` applies it. Falls back to the estimate where no canvas exists.
 */
export function canvasMeasure(): Measure {
  if (typeof document === "undefined" || (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent))) {
    return approximateMeasure;
  }
  const context = document.createElement("canvas").getContext("2d");
  if (context === null) return approximateMeasure;
  const cache = new Map<string, number>();
  return (text, style) => {
    const key = `${canvasFont(style)}|${String(style.tracking ?? 0)}|${text}`;
    const known = cache.get(key);
    if (known !== undefined) return known;
    context.font = canvasFont(style);
    const width = context.measureText(text).width + text.length * (style.tracking ?? 0) * style.size;
    cache.set(key, width);
    return width;
  };
}

/**
 * Greedy word wrap. A word wider than the line is broken after a hyphen where it has one
 * ("Valdes-Scantling"), else between characters — a line is never wider than `maxWidth`.
 */
export function wrapText(text: string, style: TextStyle, maxWidth: number, measure: Measure): string[] {
  const words = text.split(/\s+/).filter((word) => word !== "");
  const pieces: string[] = [];
  for (const word of words) {
    if (measure(word, style) <= maxWidth) {
      pieces.push(word);
      continue;
    }
    const parts = word.split(/(?<=-)/);
    for (const part of parts) {
      if (measure(part, style) <= maxWidth) {
        pieces.push(part);
        continue;
      }
      let chunk = "";
      for (const char of part) {
        if (chunk !== "" && measure(chunk + char, style) > maxWidth) {
          pieces.push(chunk);
          chunk = char;
        } else {
          chunk += char;
        }
      }
      if (chunk !== "") pieces.push(chunk);
    }
  }
  const lines: string[] = [];
  let line = "";
  for (const piece of pieces) {
    const glue = line === "" || line.endsWith("-") ? "" : " ";
    const candidate = `${line}${glue}${piece}`;
    if (line !== "" && measure(candidate, style) > maxWidth) {
      lines.push(line);
      line = piece;
    } else {
      line = candidate;
    }
  }
  if (line !== "") lines.push(line);
  return lines.length === 0 ? [""] : lines;
}

// ---------------------------------------------------------------------------- helpers

const EM_DASH = "—";

function pct(value: number | null, digits = 0): string {
  return value === null ? EM_DASH : `${(value * 100).toFixed(digits)}%`;
}

function games(count: number): string {
  return `${String(count)} game${count === 1 ? "" : "s"}`;
}

/** A round axis end at or above `value`: 1, 2, 2.5, 5 × 10^n. */
export function niceCeil(value: number): number {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (value <= step * power) return step * power;
  }
  return 10 * power;
}

function niceStep(span: number, target = 4): number {
  const raw = span / target;
  const power = 10 ** Math.floor(Math.log10(raw));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (raw <= step * power) return step * power;
  }
  return 10 * power;
}

/** A triangle pointing up, centred on (x, y): the strong-week mark. */
function triangle(x: number, y: number, size: number): string {
  const half = size / 2;
  return `M${(x - half).toFixed(2)} ${(y + half).toFixed(2)}L${(x + half).toFixed(2)} ${(y + half).toFixed(2)}L${x.toFixed(2)} ${(y - half).toFixed(2)}Z`;
}

class Pen {
  readonly marks: Mark[] = [];
  readonly scale: number;
  readonly measure: Measure;

  constructor(scale: number, measure: Measure) {
    this.scale = scale;
    this.measure = measure;
  }

  style(size: number, weight: TextStyle["weight"], face: FontFace, tracking?: number): TextStyle {
    return tracking === undefined ? { size: size * this.scale, weight, face } : { size: size * this.scale, weight, face, tracking };
  }

  text(x: number, y: number, text: string, style: TextStyle, fill: string, anchor: "start" | "middle" | "end" = "start"): void {
    // An end-anchored line ends a pixel inside its edge: a glyph's advance can overhang it.
    this.marks.push({ kind: "text", x: anchor === "end" ? x - this.scale : x, y, text, style, fill, anchor });
  }

  width(text: string, style: TextStyle): number {
    return this.measure(text, style);
  }

  /** Wrapped text from (x, y-top); returns the y below the last line. */
  block(x: number, top: number, text: string, style: TextStyle, maxWidth: number, fill: string, lineHeight = 1.35): number {
    // Two pixels of slack: the canvas that measures and the SVG that draws can differ by one.
    const lines = wrapText(text, style, maxWidth - 2 * this.scale, this.measure);
    let y = top;
    for (const line of lines) {
      // The baseline centres the x-height in the line box.
      this.text(x, y + style.size * (lineHeight / 2 + 0.32), line, style, fill);
      y += style.size * lineHeight;
    }
    return y;
  }
}

// --------------------------------------------------------------------------- week strip

type StripRowKind = "opportunity" | "points" | "share";

/**
 * Weeks on one shared axis, a row per quantity (ADR-116). The volume story reads opportunities
 * over points; the streak story reads points with each week's positional rank over the share
 * row. The window's weeks are shaded and bracketed with their label, the baseline bracketed
 * dashed; a bye is a B and a game missed a D in every row.
 */
export function drawWeekStrip(story: InsightStory, chart: InsightWeekStrip, options: DrawOptions): Drawing {
  const pen = new Pen(options.scale, options.measure);
  const s = options.scale;
  const W = options.width;
  const weeks = chart.weeks;
  const n = weeks.length;
  const col = W / n;
  const barW = Math.max(3 * s, Math.min(col * 0.62, 30 * s));
  const cx = (index: number): number => col * index + col / 2;
  const streak = story.family === "streak_watch";
  const rows: StripRowKind[] = streak
    ? chart.share_label === null
      ? ["points"]
      : ["points", "share"]
    : ["opportunity", "points"];

  const title = pen.style(10.5, 600, "sans", 0.06);
  const value = pen.style(10, 500, "mono");
  const letter = pen.style(11, 700, "mono");
  const axis = pen.style(10, 500, "mono");

  // The window bracket above every row.
  const windowIdx = weeks.map((week, index) => (week.in_window ? index : -1)).filter((index) => index >= 0);
  const baseIdx = weeks.map((week, index) => (!week.in_window && (story.window === null || week.week < story.window.first_week) ? index : -1)).filter((index) => index >= 0);
  const bracketH = 22 * s;
  const background: Mark[] = [];
  const bracketY = 15 * s;
  const bracket = (indices: number[], labels: string[], dashed: boolean, fill: string): void => {
    if (indices.length === 0) return;
    const x1 = col * (indices[0] ?? 0) + 2 * s;
    const x2 = col * ((indices[indices.length - 1] ?? 0) + 1) - 2 * s;
    const dash = dashed ? `${String(3 * s)} ${String(3 * s)}` : undefined;
    pen.marks.push({ kind: "line", x1, y1: bracketY, x2, y2: bracketY, stroke: fill, width: 1.2 * s, ...(dash === undefined ? {} : { dash }) });
    pen.marks.push({ kind: "line", x1, y1: bracketY, x2: x1, y2: bracketY + 5 * s, stroke: fill, width: 1.2 * s });
    pen.marks.push({ kind: "line", x1: x2, y1: bracketY, x2, y2: bracketY + 5 * s, stroke: fill, width: 1.2 * s });
    const label = labels.find((candidate) => pen.width(candidate, axis) <= x2 - x1);
    if (label !== undefined) pen.text((x1 + x2) / 2, bracketY - 4 * s, label, axis, fill, "middle");
  };
  const span = (indices: number[]): string => {
    const first = weeks[indices[0] ?? 0]?.week ?? 0;
    const last = weeks[indices[indices.length - 1] ?? 0]?.week ?? 0;
    return first === last ? `W${String(first)}` : `W${String(first)}–W${String(last)}`;
  };
  if (windowIdx.length > 0) {
    const label = story.window?.label ?? "Window";
    const named = label === span(windowIdx) || label.includes(span(windowIdx));
    bracket(
      windowIdx,
      named ? [`Window · ${label}`, label, "Window"] : [`${label} · ${span(windowIdx)}`, label, span(windowIdx)],
      false,
      PALETTE.bright,
    );
  }
  if (baseIdx.length > 0) {
    bracket(baseIdx, [`Baseline · ${span(baseIdx)}`, "Baseline", span(baseIdx), "Base"], true, PALETTE.muted);
  }

  let y = bracketH;
  const top = y;
  const rowGap = 12 * s;
  // A share keeps an absolute, zero-based scale of at least 0–50%: a 15% share never reads as a
  // full bar.
  const shares = weeks.map((week) => week.share).filter((entry): entry is number => entry !== null);
  const shareDomain = Math.min(1, Math.max(0.5, niceCeil(Math.max(0, ...shares))));

  const fits = (labels: string[], room: number): boolean => labels.every((label) => pen.width(label, value) <= room);

  for (const [rowIndex, kind] of rows.entries()) {
    if (rowIndex > 0) y += rowGap;
    // Title line, with the points row's legend beside it (or under it when it does not fit).
    const rowTitle =
      kind === "opportunity"
        ? `${chart.opportunity_label} by week`
        : kind === "points"
          ? "Fantasy points by week"
          : `${chart.share_label ?? "Share"} by week, scale 0–${String(Math.round(shareDomain * 100))}%`;
    pen.text(0, y + title.size, rowTitle.toUpperCase(), title, PALETTE.muted);
    let titleBottom = y + title.size * 1.5;
    if (kind === "points") {
      const sw = 9 * s;
      const legend = pen.style(10, 500, "sans");
      const items: { label: string; hatch: boolean }[] = [
        { label: "Non-TD", hatch: false },
        { label: "TD (hatched)", hatch: true },
      ];
      const legendWidth = items.reduce((sum, item) => sum + sw + 4 * s + pen.width(item.label, legend) + 10 * s, 0);
      const titleWidth = pen.width(rowTitle.toUpperCase(), title);
      let lx = W - legendWidth + 10 * s;
      let ly = y;
      if (titleWidth + 12 * s + legendWidth > W) {
        lx = 0;
        ly = titleBottom;
        titleBottom += legend.size * 1.5;
      }
      for (const item of items) {
        pen.marks.push({ kind: "rect", x: lx, y: ly + legend.size * 0.15, w: sw, h: sw, fill: PALETTE.accent, ...(item.hatch ? { hatch: true, stroke: PALETTE.accent, strokeWidth: 1 * s } : {}) });
        pen.text(lx + sw + 4 * s, ly + legend.size, item.label, legend, PALETTE.muted);
        lx += sw + 4 * s + pen.width(item.label, legend) + 10 * s;
      }
    }
    y = titleBottom;
    const labelSpace = 14 * s;
    const barArea = kind === "share" ? 34 * s : kind === "opportunity" ? 44 * s : 56 * s;
    const baseline = y + labelSpace + barArea;

    const values = weeks.map((week) =>
      week.status !== "P" ? null : kind === "opportunity" ? week.opportunity : kind === "points" ? week.points : week.share,
    );
    const max = kind === "share" ? shareDomain : Math.max(0, ...values.filter((entry): entry is number => entry !== null));
    const scale = max > 0 ? barArea / max : 0;

    // Labels: as precise as the column allows; else the window's only; else none (the table
    // under Evidence has every exact value).
    const format = (entry: number, precise: boolean): string =>
      kind === "share"
        ? `${(entry * 100).toFixed(0)}${precise ? "%" : ""}`
        : kind === "opportunity" && Number.isInteger(entry)
          ? String(entry)
          : precise
            ? entry.toFixed(1)
            : String(Math.round(entry));
    const present = values.filter((entry): entry is number => entry !== null);
    const room = col - 2 * s;
    let precise = true;
    let windowOnly = false;
    let none = false;
    if (!fits(present.map((entry) => format(entry, true)), room)) {
      precise = false;
      if (!fits(present.map((entry) => format(entry, false)), room)) {
        windowOnly = true;
        const windowValues = values.filter((entry, index): entry is number => entry !== null && weeks[index]?.in_window === true);
        if (!fits(windowValues.map((entry) => format(entry, false)), room)) none = true;
      }
    }

    for (const [index, week] of weeks.entries()) {
      const x = cx(index) - barW / 2;
      if (week.status !== "P") {
        pen.text(cx(index), baseline - 3 * s, week.status, letter, PALETTE.faint, "middle");
        continue;
      }
      const entry = values[index] ?? null;
      if (entry === null) {
        pen.text(cx(index), baseline - 3 * s, EM_DASH, letter, PALETTE.faint, "middle");
        continue;
      }
      const height = Math.max(0, entry) * scale;
      if (kind === "points") {
        const total = Math.max(0, entry);
        const td = Math.min(total, Math.max(0, week.td_points ?? 0));
        const other = total - td;
        if (other > 0) pen.marks.push({ kind: "rect", x, y: baseline - other * scale, w: barW, h: other * scale, fill: PALETTE.accent });
        if (td > 0) {
          pen.marks.push({
            kind: "rect",
            x,
            y: baseline - total * scale,
            w: barW,
            h: td * scale,
            fill: PALETTE.accent,
            hatch: true,
            stroke: PALETTE.accent,
            strokeWidth: 1 * s,
          });
        }
      } else {
        pen.marks.push({
          kind: "rect",
          x,
          y: baseline - height,
          w: barW,
          h: height,
          fill: kind === "opportunity" ? PALETTE.accentInk : PALETTE.fill,
          ...(kind === "share" ? { stroke: PALETTE.accent, strokeWidth: 1 * s } : {}),
        });
      }
      if (!none && (!windowOnly || week.in_window)) {
        pen.text(cx(index), baseline - height - 3 * s, format(entry, precise), value, PALETTE.strong, "middle");
      }
    }
    // The zero line.
    pen.marks.push({ kind: "line", x1: 0, y1: baseline, x2: W, y2: baseline, stroke: PALETTE.line, width: 1 * s });
    y = baseline;

    // The streak's ranks under the points row: a triangle and a bold rank for a strong week.
    if (kind === "points" && streak) {
      const rankStyle = pen.style(10, 500, "mono");
      const strongStyle = pen.style(10, 700, "mono");
      const rankY = y + 13 * s;
      const labels = weeks.map((week) => (week.rank === null ? (week.status === "P" ? EM_DASH : "") : `#${String(week.rank)}`));
      const showRanks = labels.every((label) => pen.width(label, strongStyle) + 10 * s <= col);
      const showBare = !showRanks && labels.every((label) => pen.width(label.replace("#", ""), strongStyle) <= col - 1 * s);
      for (const [index, week] of weeks.entries()) {
        const strong = chart.band !== null && week.rank !== null && week.rank <= chart.band;
        const label = labels[index] ?? "";
        if (strong) {
          pen.marks.push({ kind: "path", d: triangle(cx(index), rankY + 6 * s, 7 * s), fill: PALETTE.warn });
        }
        if (showRanks || showBare) {
          pen.text(cx(index), rankY, showRanks ? label : label.replace("#", ""), strong ? strongStyle : rankStyle, strong ? PALETTE.warn : PALETTE.faint, "middle");
        }
      }
      y = rankY + 12 * s;
      if (chart.band !== null) {
        const legend = pen.style(10, 500, "sans");
        pen.marks.push({ kind: "path", d: triangle(4 * s, y + 6 * s, 7 * s), fill: PALETTE.warn });
        y = pen.block(12 * s, y, `Top-${String(chart.band)} ${story.position} week (ranked 1–${String(chart.band)}); # = weekly ${story.position} rank`, legend, W - 12 * s, PALETTE.muted, 1.4);
        y += 2 * s;
      }
    }
  }

  // The week axis.
  const axisY = y + 13 * s;
  const prefixed = weeks.every((week) => pen.width(`W${String(week.week)}`, axis) <= col - 2 * s);
  for (const [index, week] of weeks.entries()) {
    pen.text(cx(index), axisY, prefixed ? `W${String(week.week)}` : String(week.week), axis, week.in_window ? PALETTE.ink : PALETTE.faint, "middle");
  }
  let bottom = axisY + 4 * s;
  if (weeks.some((week) => week.status !== "P")) {
    const legend = pen.style(10, 500, "sans");
    const note = [weeks.some((week) => week.status === "B") ? "B bye" : null, weeks.some((week) => week.status === "D") ? "D did not play" : null]
      .filter((part): part is string => part !== null)
      .join(" · ");
    bottom = pen.block(0, bottom + 2 * s, prefixed ? note : `Week · ${note}`, legend, W, PALETTE.faint);
  }

  // The window shading sits under everything.
  if (windowIdx.length > 0) {
    const x1 = col * (windowIdx[0] ?? 0);
    const x2 = col * ((windowIdx[windowIdx.length - 1] ?? 0) + 1);
    background.push({ kind: "rect", x: x1, y: top - 2 * s, w: x2 - x1, h: y - top + 18 * s, fill: PALETTE.wash });
  }
  return { width: W, height: Math.ceil(bottom + 2 * s), marks: [...background, ...pen.marks], hatch: 5 * s };
}

// ----------------------------------------------------------------------------- interval

/**
 * This week's distribution against his typical week, on one points scale: the P10–P90 bar
 * with a P50 tick, the typical week lighter beneath it and named, and the three readouts
 * spelled out under the axis — the ceiling as "1 week in 10", never as a probability of a big
 * game.
 */
export function drawInterval(story: InsightStory, chart: InsightInterval, options: DrawOptions): Drawing {
  const pen = new Pen(options.scale, options.measure);
  const s = options.scale;
  const W = options.width;
  const title = pen.style(10.5, 600, "sans", 0.06);
  const value = pen.style(10.5, 600, "mono");
  const axis = pen.style(10, 500, "mono");
  const values = [chart.q10, chart.q50, chart.q90, chart.typical_q10, chart.typical_q50, chart.typical_q90].filter(
    (entry): entry is number => entry !== null,
  );
  const lo = Math.min(0, ...values);
  const hi = niceCeil(Math.max(...values) * 1.05);
  const pad = 4 * s;
  const x = (entry: number): number => pad + ((entry - lo) / (hi - lo)) * (W - 2 * pad);
  const clampAnchor = (at: number, text: string, style: TextStyle): number => {
    const half = pen.width(text, style) / 2;
    return Math.min(W - half, Math.max(half, at));
  };

  let y = 0;
  const row = (
    label: string,
    q10: number | null,
    q50: number | null,
    q90: number | null,
    thickness: number,
    fill: string,
    stroke: string,
  ): void => {
    pen.text(0, y + title.size, label.toUpperCase(), title, PALETTE.muted);
    y += title.size * 1.4;
    if (q10 === null || q50 === null || q90 === null) {
      y = pen.block(0, y, "Not published for this player.", pen.style(11, 500, "sans"), W, PALETTE.faint);
      return;
    }
    // P50 above the bar.
    const midText = q50.toFixed(1);
    y += value.size * 1.25;
    pen.text(clampAnchor(x(q50), midText, value), y - 2 * s, midText, value, PALETTE.ink, "middle");
    const barTop = y + 3 * s;
    pen.marks.push({ kind: "rect", x: x(q10), y: barTop, w: Math.max(1, x(q90) - x(q10)), h: thickness, fill, stroke, strokeWidth: 1 * s });
    pen.marks.push({ kind: "line", x1: x(q50), y1: barTop - 4 * s, x2: x(q50), y2: barTop + thickness + 4 * s, stroke: PALETTE.ink, width: 2.5 * s });
    // P10 and P90 under it, pushed apart when they would touch.
    const lowText = q10.toFixed(1);
    const highText = q90.toFixed(1);
    let lowX = clampAnchor(x(q10), lowText, value);
    let highX = clampAnchor(x(q90), highText, value);
    const need = (pen.width(lowText, value) + pen.width(highText, value)) / 2 + 6 * s;
    if (highX - lowX < need) {
      const middle = (lowX + highX) / 2;
      lowX = clampAnchor(middle - need / 2, lowText, value);
      highX = clampAnchor(middle + need / 2, highText, value);
    }
    const under = barTop + thickness + 4 * s + value.size;
    pen.text(lowX, under, lowText, value, PALETTE.strong, "middle");
    pen.text(highX, under, highText, value, PALETTE.strong, "middle");
    y = under + 6 * s;
  };

  const week = story.target_week === null ? "This week" : `Week ${String(story.target_week)}`;
  row(`${week} · this game`, chart.q10, chart.q50, chart.q90, 14 * s, PALETTE.accent, PALETTE.bright);
  y += 6 * s;
  row("Typical week", chart.typical_q10, chart.typical_q50, chart.typical_q90, 9 * s, PALETTE.fill, PALETTE.accentInk);

  // The points axis.
  y += 4 * s;
  pen.marks.push({ kind: "line", x1: pad, y1: y, x2: W - pad, y2: y, stroke: PALETTE.line, width: 1 * s });
  const step = niceStep(hi - lo);
  for (let tick = Math.ceil(lo / step) * step; tick <= hi + 1e-9; tick += step) {
    const at = x(tick);
    pen.marks.push({ kind: "line", x1: at, y1: y, x2: at, y2: y + 4 * s, stroke: PALETTE.line, width: 1 * s });
    const label = tick + step > hi + 1e-9 ? `${String(Math.round(tick * 10) / 10)} pts` : String(Math.round(tick * 10) / 10);
    pen.text(clampAnchor(at, label, axis), y + 4 * s + axis.size, label, axis, PALETTE.faint, "middle");
  }
  y += 4 * s + axis.size + 10 * s;

  // The three readouts, in a row when they fit, else one per line.
  const label = pen.style(10, 600, "sans", 0.04);
  const number = pen.style(14, 600, "mono");
  const readouts: readonly (readonly [string, number])[] = [
    ["Floor (P10)", chart.q10],
    ["Median (P50)", chart.q50],
    ["Ceiling (1 week in 10)", chart.q90],
  ];
  const cell = W / 3;
  const inRow = readouts.every(([name, entry]) => Math.max(pen.width(name.toUpperCase(), label), pen.width(entry.toFixed(1), number)) <= cell - 8 * s);
  if (inRow) {
    for (const [index, [name, entry]] of readouts.entries()) {
      pen.text(cell * index, y + label.size, name.toUpperCase(), label, PALETTE.muted);
      pen.text(cell * index, y + label.size + 4 * s + number.size, entry.toFixed(1), number, PALETTE.ink);
    }
    y += label.size + 4 * s + number.size + 4 * s;
  } else {
    for (const [name, entry] of readouts) {
      pen.text(0, y + number.size, name.toUpperCase(), label, PALETTE.muted);
      pen.text(W, y + number.size, entry.toFixed(1), number, PALETTE.ink, "end");
      y += number.size * 1.45;
    }
  }
  return { width: W, height: Math.ceil(y + 2 * s), marks: pen.marks, hatch: 5 * s };
}

// ------------------------------------------------------------------------ with / without

const SHARE_UNIT: Readonly<Record<InsightWithWithout["metric"], string>> = {
  target_share: "targets",
  carry_share: "carries",
  pass_share: "pass attempts",
};

/**
 * Each teammate's share with the absent player and without him, as two aligned bars on one
 * zero-based scale, each with its exact game count — a one-game sample says "1 game" beside
 * its bar, and a teammate with no game yet without him says so instead of drawing a zero.
 */
export function drawWithWithout(_story: InsightStory, chart: InsightWithWithout, options: DrawOptions): Drawing {
  const pen = new Pen(options.scale, options.measure);
  const s = options.scale;
  const W = options.width;
  const unit = SHARE_UNIT[chart.metric];
  const head = pen.style(11, 500, "sans");
  const name = pen.style(12, 600, "sans");
  const small = pen.style(10, 600, "sans", 0.06);
  const value = pen.style(10.5, 500, "mono");
  const absent = chart.absent;
  let y = pen.block(
    0,
    0,
    `${absent.name} (${absent.position}): ${pct(absent.share)} of team ${unit} over ${games(absent.games)}, ${absent.per_game.toFixed(1)} per game. ${absent.reason.charAt(0).toUpperCase()}${absent.reason.slice(1)}.`.replace(/\.\.$/, "."),
    head,
    W,
    PALETTE.strong,
  );
  y += 6 * s;

  const shares = chart.rows.flatMap((row) => [row.share_with, row.share_without]).filter((entry): entry is number => entry !== null);
  const max = Math.max(0.05, ...shares);
  const domain = Math.min(1, niceCeil(max * 1.05));
  const labelW = Math.max(pen.width("WITHOUT", small), pen.width("WITH", small)) + 8 * s;
  const valueTexts = chart.rows.flatMap((row) => [
    row.share_with === null ? "no game" : `${pct(row.share_with)} · ${games(row.games_with)}`,
    row.share_without === null ? (row.games_without === 0 ? "no game yet" : "no game") : `${pct(row.share_without)} · ${games(row.games_without)}`,
  ]);
  const valueW = Math.max(...valueTexts.map((text) => pen.width(text, value))) + 8 * s;
  const x0 = labelW;
  const track = Math.max(20 * s, W - labelW - valueW);
  const bar = 11 * s;

  for (const row of chart.rows) {
    y += 6 * s;
    const nameText = `${row.name} · ${row.position}`;
    const latest = row.latest_share === null ? null : `latest ${pct(row.latest_share)}`;
    const nameFits = latest === null || pen.width(nameText, name) + pen.width(latest, value) + 12 * s <= W;
    pen.text(0, y + name.size, nameText, name, PALETTE.ink);
    if (latest !== null) {
      if (nameFits) {
        pen.text(W, y + name.size, latest, value, PALETTE.muted, "end");
      } else {
        y += name.size * 1.3;
        pen.text(0, y + value.size, latest, value, PALETTE.muted);
      }
    }
    y += name.size * 1.45;
    const pair: readonly (readonly [string, number | null, number, boolean])[] = [
      ["WITH", row.share_with, row.games_with, false],
      ["WITHOUT", row.share_without, row.games_without, true],
    ];
    for (const [label, share, count, hatched] of pair) {
      pen.text(0, y + bar * 0.85, label, small, PALETTE.muted);
      pen.marks.push({ kind: "line", x1: x0, y1: y - 1 * s, x2: x0, y2: y + bar + 1 * s, stroke: PALETTE.line, width: 1 * s });
      if (share === null) {
        pen.text(x0 + 4 * s, y + bar * 0.85, count === 0 && hatched ? "no game yet" : "no game", value, PALETTE.faint);
      } else {
        const w = (Math.max(0, share) / domain) * track;
        pen.marks.push({
          kind: "rect",
          x: x0,
          y,
          w,
          h: bar,
          fill: PALETTE.accent,
          ...(hatched ? { hatch: true, stroke: PALETTE.accent, strokeWidth: 1 * s } : {}),
        });
        pen.text(x0 + w + 5 * s, y + bar * 0.85, `${pct(share)} · ${games(count)}`, value, PALETTE.strong);
      }
      y += bar + 5 * s;
    }
  }
  y += 4 * s;
  const legend = pen.style(10, 500, "sans");
  y = pen.block(0, y, `Share of team ${unit} in his games; scale 0–${pct(domain)}. Without = hatched.`, legend, W, PALETTE.faint);
  return { width: W, height: Math.ceil(y + 2 * s), marks: pen.marks, hatch: 5 * s };
}

// --------------------------------------------------------------------------------- room

/**
 * The room, one player per row on one zero-based scale: his share of the team's carries or
 * targets over the window with a tick at his baseline, the count behind it ("18 of 52"), then
 * snap share and red-zone touches as their own figures. Snap shares overlap — teammates share
 * the field — so they are never stacked into slices of a whole.
 */
export function drawRoom(story: InsightStory, chart: InsightRoom, options: DrawOptions): Drawing {
  const pen = new Pen(options.scale, options.measure);
  const s = options.scale;
  const W = options.width;
  const head = pen.style(11, 500, "sans");
  const name = pen.style(12, 600, "sans");
  const value = pen.style(10.5, 500, "mono");
  const detail = pen.style(10.5, 500, "sans");
  // Red-zone counts the build could not read are said to be missing, never drawn as zero.
  const totals = [
    `Team ${chart.metric}: ${String(chart.team_count)} in ${games(chart.team_games)}`,
    chart.team_red_zone === null ? "red zone not available" : `red zone ${String(chart.team_red_zone)}`,
    chart.team_inside_five === null
      ? chart.team_red_zone === null
        ? null
        : "inside the 5 not available"
      : `inside the 5: ${String(chart.team_inside_five)}`,
  ].filter((part): part is string => part !== null);
  let y = pen.block(0, 0, totals.join(" · "), head, W, PALETTE.strong);
  const shares = chart.rows.flatMap((row) => [row.share, row.share_baseline]).filter((entry): entry is number => entry !== null);
  const domain = Math.min(1, niceCeil(Math.max(0.05, ...shares) * 1.05));
  const valueTexts = chart.rows.map((row) => `${pct(row.share)} · ${String(row.count)} of ${String(chart.team_count)}`);
  const valueW = Math.max(...valueTexts.map((text) => pen.width(text, value))) + 8 * s;
  const track = Math.max(24 * s, W - valueW);
  const bar = 12 * s;

  for (const [index, row] of chart.rows.entries()) {
    y += 9 * s;
    const focal = row.player_id === story.player_id;
    pen.text(0, y + name.size, `${row.name} · ${row.position}`, name, focal ? PALETTE.bright : PALETTE.ink);
    const gamesText = `${games(row.window_games)} in window`;
    if (pen.width(`${row.name} · ${row.position}`, name) + pen.width(gamesText, value) + 12 * s <= W) {
      pen.text(W, y + name.size, gamesText, value, PALETTE.faint, "end");
    }
    y += name.size * 1.4;
    // The track, the bar, the baseline tick.
    pen.marks.push({ kind: "rect", x: 0, y, w: track, h: bar, fill: PALETTE.wash });
    if (row.share !== null) {
      pen.marks.push({ kind: "rect", x: 0, y, w: (Math.max(0, row.share) / domain) * track, h: bar, fill: focal ? PALETTE.accent : PALETTE.fill, stroke: PALETTE.accent, strokeWidth: 1 * s });
    }
    if (row.share_baseline !== null) {
      const at = (row.share_baseline / domain) * track;
      pen.marks.push({ kind: "line", x1: at, y1: y - 3 * s, x2: at, y2: y + bar + 3 * s, stroke: PALETTE.warn, width: 2 * s });
    }
    pen.text(track + 6 * s, y + bar * 0.85, valueTexts[index] ?? EM_DASH, value, PALETTE.strong);
    y += bar + 3 * s;
    const parts = [
      row.share_baseline === null ? `Before: ${EM_DASH}` : `Before ${pct(row.share_baseline)} (${games(row.baseline_games)})`,
      `Snaps ${pct(row.snap_share)}${row.snap_share_baseline === null ? "" : ` (before ${pct(row.snap_share_baseline)})`}`,
      chart.team_red_zone === null && row.red_zone === null ? null : `Red zone ${row.red_zone === null ? EM_DASH : String(row.red_zone)}`,
      chart.team_inside_five === null && row.inside_five === null ? null : `inside 5: ${row.inside_five === null ? EM_DASH : String(row.inside_five)}`,
    ].filter((part): part is string => part !== null);
    y = pen.block(0, y, parts.join(" · "), detail, W, PALETTE.muted, 1.3);
  }
  y += 6 * s;
  const legend = pen.style(10, 500, "sans");
  pen.marks.push({ kind: "line", x1: 3 * s, y1: y + 1 * s, x2: 3 * s, y2: y + 11 * s, stroke: PALETTE.warn, width: 2 * s });
  y = pen.block(10 * s, y, `= his baseline share. Bars: share of team ${chart.metric} over the window, scale 0–${pct(domain)}. Snap shares overlap and never add to 100%.`, legend, W - 10 * s, PALETTE.faint);
  return { width: W, height: Math.ceil(y + 2 * s), marks: pen.marks, hatch: 5 * s };
}

// ---------------------------------------------------------------------------- stat line

/**
 * The season's arithmetic in one line — points per game, games of team games, the 17-game pace
 * labelled as arithmetic — then his games as a row of team games (filled where he played), and
 * the two ranks on one rank axis (1 at the left), so a per-game standing the season total hides
 * is a visible gap between two marks.
 */
export function drawStatLine(story: InsightStory, chart: InsightStatLine, options: DrawOptions): Drawing {
  const pen = new Pen(options.scale, options.measure);
  const s = options.scale;
  const W = options.width;
  const line = pen.style(13, 600, "mono");
  const note = pen.style(10.5, 500, "sans");
  const label = pen.style(10, 600, "sans", 0.05);
  let y = pen.block(
    0,
    0,
    `${chart.points_per_game.toFixed(1)} PPG · ${String(chart.games)} of ${String(chart.team_games)} team games · 17-game pace ${chart.pace_17.toFixed(1)}`,
    line,
    W,
    PALETTE.ink,
    1.35,
  );
  y = pen.block(0, y, "Pace is arithmetic: PPG × 17, not a projection.", note, W, PALETTE.faint, 1.35);
  y += 8 * s;

  // His games among his team's: a filled square where he played, an outline where he did not.
  pen.text(0, y + label.size, "GAMES PLAYED", label, PALETTE.muted);
  y += label.size * 1.5;
  const size = Math.min(14 * s, (W - 4 * s) / Math.max(1, chart.team_games) - 4 * s);
  for (let index = 0; index < chart.team_games; index += 1) {
    const played = index < chart.games;
    pen.marks.push({
      kind: "rect",
      x: index * (size + 4 * s),
      y,
      w: size,
      h: size,
      fill: played ? PALETTE.accent : "none",
      stroke: played ? PALETTE.accent : PALETTE.faint,
      strokeWidth: 1 * s,
      ...(played ? {} : { dash: `${String(2 * s)} ${String(2 * s)}` }),
    });
  }
  const after = chart.team_games * (size + 4 * s) + 4 * s;
  const count = `${String(chart.games)} of ${String(chart.team_games)}`;
  if (after + pen.width(count, pen.style(10.5, 600, "mono")) <= W) {
    pen.text(after, y + size * 0.8, count, pen.style(10.5, 600, "mono"), PALETTE.strong);
  }
  y += size + 12 * s;

  // The rank axis: 1 at the left, the cohort's size at the right.
  const cohort = `Ranks among ${String(chart.cohort_size)} ${story.position}s with ${String(chart.cohort_min_games)}+ games`;
  y = pen.block(0, y, cohort, pen.style(10.5, 600, "sans"), W, PALETTE.strong);
  const pad = 8 * s;
  const span = Math.max(1, chart.cohort_size - 1);
  const x = (rank: number): number => pad + ((Math.min(rank, chart.cohort_size) - 1) / span) * (W - 2 * pad);
  const markLabel = pen.style(10.5, 700, "mono");
  const axisY = y + markLabel.size + 12 * s;
  pen.marks.push({ kind: "line", x1: pad, y1: axisY, x2: W - pad, y2: axisY, stroke: PALETTE.lineStrong, width: 1.5 * s });
  const tick = pen.style(10, 500, "mono");
  pen.text(pad, axisY + 6 * s + tick.size, "#1", tick, PALETTE.faint, "start");
  pen.text(W - pad, axisY + 6 * s + tick.size, `#${String(chart.cohort_size)}`, tick, PALETTE.faint, "end");
  const half = (text: string): number => pen.width(text, markLabel) / 2;
  const clamp = (at: number, text: string): number => Math.min(W - half(text) - 1 * s, Math.max(half(text), at));
  const ppgText = `PPG #${String(chart.ppg_rank)}`;
  const ppgX = x(chart.ppg_rank);
  const r = 5 * s;
  pen.marks.push({
    kind: "path",
    d: `M${(ppgX - r).toFixed(2)} ${axisY.toFixed(2)}a${r.toFixed(2)} ${r.toFixed(2)} 0 1 0 ${(2 * r).toFixed(2)} 0a${r.toFixed(2)} ${r.toFixed(2)} 0 1 0 ${(-2 * r).toFixed(2)} 0Z`,
    fill: PALETTE.accent,
  });
  pen.text(clamp(ppgX, ppgText), axisY - 9 * s, ppgText, markLabel, PALETTE.bright, "middle");
  const below = axisY + 6 * s + tick.size * 2.4;
  if (chart.total_rank !== null) {
    const totalText = `Total #${String(chart.total_rank)}`;
    const totalX = x(chart.total_rank);
    pen.marks.push({
      kind: "path",
      d: `M${totalX.toFixed(2)} ${(axisY - r).toFixed(2)}L${(totalX + r).toFixed(2)} ${axisY.toFixed(2)}L${totalX.toFixed(2)} ${(axisY + r).toFixed(2)}L${(totalX - r).toFixed(2)} ${axisY.toFixed(2)}Z`,
      fill: PALETTE.canvas,
      stroke: PALETTE.warn,
      strokeWidth: 2 * s,
    });
    // Below the axis, so the two labels never collide however close the ranks are.
    pen.text(clamp(totalX, totalText), below, totalText, markLabel, PALETTE.warn, "middle");
  } else {
    pen.text(W - pad, below, `Total rank ${EM_DASH}`, markLabel, PALETTE.faint, "end");
  }
  y = below + 6 * s;
  return { width: W, height: Math.ceil(y + 2 * s), marks: pen.marks, hatch: 5 * s };
}

/** The story's chart, drawn at `options.width`. */
export function drawStoryChart(story: InsightStory, options: DrawOptions): Drawing {
  const chart = story.chart;
  switch (chart.type) {
    case "week_strip":
      return drawWeekStrip(story, chart, options);
    case "interval":
      return drawInterval(story, chart, options);
    case "with_without":
      return drawWithWithout(story, chart, options);
    case "room":
      return drawRoom(story, chart, options);
    case "stat_line":
      return drawStatLine(story, chart, options);
  }
}

// ------------------------------------------------------------------------------ to SVG

export function escapeXml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function num(value: number): string {
  return String(Math.round(value * 100) / 100);
}

/** One text mark as an SVG element string. */
export function textElement(mark: Extract<Mark, { kind: "text" }>): string {
  const tracking = mark.style.tracking === undefined ? "" : ` letter-spacing="${num(mark.style.tracking * mark.style.size)}"`;
  return `<text x="${num(mark.x)}" y="${num(mark.y)}" font-family="${escapeXml(FONT_STACK[mark.style.face])}" font-size="${num(mark.style.size)}" font-weight="${String(mark.style.weight)}" fill="${mark.fill}" text-anchor="${mark.anchor}"${tracking}>${escapeXml(mark.text)}</text>`;
}

/** The hatch pattern a drawing's `hatch` rects fill with. */
export function hatchPattern(id: string, spacing: number, color: string = PALETTE.accent): string {
  return `<pattern id="${id}" patternUnits="userSpaceOnUse" width="${num(spacing)}" height="${num(spacing)}" patternTransform="rotate(45)"><rect width="${num(spacing)}" height="${num(spacing)}" fill="${PALETTE.tile}"/><line x1="0" y1="0" x2="0" y2="${num(spacing)}" stroke="${color}" stroke-width="${num(spacing * 0.45)}"/></pattern>`;
}

/** A drawing's marks as SVG element strings, offset to (x, y). */
export function marksToSvg(drawing: Drawing, hatchId: string, x = 0, y = 0): string {
  const parts: string[] = [`<g transform="translate(${num(x)} ${num(y)})">`];
  for (const mark of drawing.marks) {
    switch (mark.kind) {
      case "rect": {
        const fill = mark.hatch === true ? `url(#${hatchId})` : mark.fill;
        const stroke = mark.stroke === undefined ? "" : ` stroke="${mark.stroke}" stroke-width="${num(mark.strokeWidth ?? 1)}"`;
        const dash = mark.dash === undefined ? "" : ` stroke-dasharray="${mark.dash}"`;
        parts.push(`<rect x="${num(mark.x)}" y="${num(mark.y)}" width="${num(Math.max(0, mark.w))}" height="${num(Math.max(0, mark.h))}" fill="${fill}"${stroke}${dash}/>`);
        break;
      }
      case "line": {
        const dash = mark.dash === undefined ? "" : ` stroke-dasharray="${mark.dash}"`;
        parts.push(`<line x1="${num(mark.x1)}" y1="${num(mark.y1)}" x2="${num(mark.x2)}" y2="${num(mark.y2)}" stroke="${mark.stroke}" stroke-width="${num(mark.width)}"${dash}/>`);
        break;
      }
      case "text":
        parts.push(textElement(mark));
        break;
      case "path": {
        const stroke = mark.stroke === undefined ? "" : ` stroke="${mark.stroke}" stroke-width="${num(mark.strokeWidth ?? 1)}"`;
        parts.push(`<path d="${mark.d}" fill="${mark.fill}"${stroke}/>`);
        break;
      }
    }
  }
  parts.push("</g>");
  return parts.join("");
}
