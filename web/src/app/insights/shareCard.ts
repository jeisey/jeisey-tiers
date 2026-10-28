/**
 * The share card (ADR-116): one story as an SVG document at an exact pixel size, landscape
 * 1200×675 or portrait 1080×1350, reflowed for each rather than stretched. The preview on the
 * page is this document and the downloaded PNG is this document rasterised, so what a reader
 * sees is what they send.
 *
 * Pure: the caller supplies a `Measure` (the canvas's `measureText` with the self-hosted fonts
 * loaded) and every line is wrapped to its box with it. The type scale steps down until the
 * whole card fits, so nothing is ever clipped; `texts` lists every line placed, with its
 * measured width and its box, so a test (and the visual-QA capture) can prove it.
 *
 * Every card carries the headline, the player and team, the window or week, the scoring, the
 * chart, the caveat, the attribution, the edition and build time, and the site's name.
 */

import { BASIS_LABELS, kicker, type InsightStory } from "../../data/insights";
import { chartCaption } from "./chartText";
import {
  FONT_STACK,
  PALETTE,
  drawStoryChart,
  escapeXml,
  hatchPattern,
  marksToSvg,
  wrapText,
  type Measure,
  type TextStyle,
} from "./marks";

export type ShareLayoutId = "land" | "port";

export const SHARE_SIZES: Readonly<Record<ShareLayoutId, { readonly width: number; readonly height: number }>> = {
  land: { width: 1200, height: 675 },
  port: { width: 1080, height: 1350 },
};

export interface ShareInput {
  readonly story: InsightStory;
  readonly layout: ShareLayoutId;
  readonly measure: Measure;
  /** `Pat Doe · WR · KC · vs LAC · Sun, Nov 8, 8:20 PM ET` without the name. */
  readonly context: readonly string[];
  /** Why a `this_week` story no longer stands, or null. */
  readonly withdrawn: string | null;
  /** `Week 8 edition · built Aug 21 · 10:38 AM ET`. */
  readonly edition: string;
  /** `Last 3 weeks · W6–W8, baseline W1–W5`. */
  readonly window: string;
  /** `PPR scoring` or `Same in every scoring`. */
  readonly scoring: string;
  readonly sources: readonly string[];
}

/** One placed line: its text, its measured width and the box it had to fit. */
export interface PlacedText {
  readonly text: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly maxWidth: number;
  readonly size: number;
  readonly anchor: "start" | "end";
}

export interface ShareCard {
  readonly layout: ShareLayoutId;
  readonly width: number;
  readonly height: number;
  /** The type scale the card fitted at (1 = full size). */
  readonly scale: number;
  readonly fits: boolean;
  readonly texts: readonly PlacedText[];
  /** The complete document. `fontCss` embeds the faces; `logoHref` is a data URL or null. */
  readonly toSvg: (fontCss: string, logoHref: string | null) => string;
}

interface Composer {
  readonly parts: string[];
  readonly texts: PlacedText[];
  line(x: number, y: number, text: string, style: TextStyle, fill: string, maxWidth: number, anchor?: "start" | "end"): void;
  /** Wrapped text from `top`; the y below its last line. `maxLines` overflowing fails the fit. */
  block(x: number, top: number, text: string, style: TextStyle, maxWidth: number, fill: string, lineHeight: number, maxLines?: number): number;
  overflowed: boolean;
}

function composer(measure: Measure): Composer {
  const parts: string[] = [];
  const texts: PlacedText[] = [];
  const self: Composer = {
    parts,
    texts,
    overflowed: false,
    line(x, y, text, style, fill, maxWidth, anchor = "start") {
      const width = measure(text, style);
      if (width > maxWidth + 0.5) self.overflowed = true;
      texts.push({ text, x, y, width, maxWidth, size: style.size, anchor });
      const tracking = style.tracking === undefined ? "" : ` letter-spacing="${(style.tracking * style.size).toFixed(2)}"`;
      parts.push(
        `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" font-family="${escapeXml(FONT_STACK[style.face])}" font-size="${style.size.toFixed(2)}" font-weight="${String(style.weight)}" fill="${fill}" text-anchor="${anchor}"${tracking}>${escapeXml(text)}</text>`,
      );
    },
    block(x, top, text, style, maxWidth, fill, lineHeight, maxLines) {
      const lines = wrapText(text, style, maxWidth, measure);
      if (maxLines !== undefined && lines.length > maxLines) self.overflowed = true;
      let y = top;
      for (const line of lines) {
        self.line(x, y + style.size * (lineHeight / 2 + 0.32), line, style, fill, maxWidth);
        y += style.size * lineHeight;
      }
      return y;
    },
  };
  return self;
}

function sans(size: number, weight: TextStyle["weight"], tracking?: number): TextStyle {
  return tracking === undefined ? { size, weight, face: "sans" } : { size, weight, face: "sans", tracking };
}
function mono(size: number, weight: TextStyle["weight"], tracking?: number): TextStyle {
  return tracking === undefined ? { size, weight, face: "mono" } : { size, weight, face: "mono", tracking };
}

/** A frame with the HUD's two cut corners. */
function frame(width: number, height: number, inset: number, notch: number): string {
  const a = inset;
  const r = width - inset;
  const b = height - inset;
  return `<path d="M${String(a)} ${String(a)}H${String(r - notch)}L${String(r)} ${String(a + notch)}V${String(b)}H${String(a + notch)}L${String(a)} ${String(b - notch)}Z" fill="none" stroke="${PALETTE.line}" stroke-width="1.5"/>`;
}

interface Laid {
  readonly composer: Composer;
  readonly fits: boolean;
  readonly logo: { readonly x: number; readonly y: number; readonly size: number };
}

/** The facts as a two-column grid; returns the y below it. */
function facts(c: Composer, story: InsightStory, x: number, top: number, width: number, k: number, labelSize: number, valueSize: number): number {
  const gap = 18 * k;
  const cell = (width - gap) / 2;
  let y = top;
  for (let row = 0; row < story.facts.length; row += 2) {
    let bottom = y;
    for (let column = 0; column < 2; column += 1) {
      const fact = story.facts[row + column];
      if (fact === undefined) continue;
      const cx = x + column * (cell + gap);
      const label = sans(labelSize * k, 600, 0.05);
      const tag = mono((labelSize - 1) * k, 700, 0.08);
      const tagText = BASIS_LABELS[fact.basis].toUpperCase();
      let cy = c.block(cx, y, fact.label.toUpperCase(), label, cell, PALETTE.muted, 1.3, 3);
      c.line(cx, cy + tag.size * 0.95, tagText, tag, fact.basis === "observed" ? PALETTE.good : fact.basis === "model" ? PALETTE.accentInk : PALETTE.warn, cell);
      cy += tag.size * 1.45;
      cy = c.block(cx, cy, fact.value, mono(valueSize * k, 600), cell, PALETTE.ink, 1.2, 2);
      bottom = Math.max(bottom, cy);
    }
    y = bottom + 12 * k;
  }
  return y;
}

/** The counterpoint and caveat, each a label over its text. */
function notes(c: Composer, story: InsightStory, x: number, top: number, width: number, size: number, k: number): number {
  let y = top;
  const label = sans(11 * k, 700, 0.12);
  if (story.counterpoint !== null) {
    c.line(x, y + label.size, "WHAT COULD UNDERMINE IT", label, PALETTE.warn, width);
    y = c.block(x, y + label.size * 1.5, story.counterpoint, sans(size * k, 500), width, PALETTE.strong, 1.35);
    y += 8 * k;
  }
  c.line(x, y + label.size, "CAVEAT", label, PALETTE.accentInk, width);
  y = c.block(x, y + label.size * 1.5, story.caveat, sans(size * k, 500), width, PALETTE.strong, 1.35);
  return y;
}

function layLandscape(input: ShareInput, k: number): Laid {
  const { width: W, height: H } = SHARE_SIZES.land;
  const { story, measure } = input;
  const c = composer(measure);
  const P = 44;
  const inner = W - 2 * P;

  // Header: the kicker, and the edition at the right (under it when both do not fit).
  const kick = sans(14 * k, 700, 0.12);
  const ed = mono(12 * k, 500);
  const kickText = kicker(story).toUpperCase();
  const kickW = measure(kickText, kick);
  const edW = measure(input.edition, ed);
  let y = P;
  if (kickW + edW + 24 <= inner) {
    c.line(P, y + kick.size, kickText, kick, PALETTE.bright, inner - edW - 24);
    c.line(W - P, y + kick.size, input.edition, ed, PALETTE.faint, edW + 1, "end");
    y += kick.size * 1.5;
  } else {
    y = c.block(P, y, kickText, kick, inner, PALETTE.bright, 1.35);
    y = c.block(P, y, input.edition, ed, inner, PALETTE.faint, 1.35);
  }
  y += 8 * k;
  y = c.block(P, y, story.headline, sans(34 * k, 700), inner, PALETTE.ink, 1.12, 3);
  y += 6 * k;
  y = c.block(P, y, [story.display_name, ...input.context].join(" · "), sans(17 * k, 600), inner, PALETTE.strong, 1.3, 2);
  if (input.withdrawn !== null) {
    y = c.block(P, y + 4 * k, `Withdrawn — ${input.withdrawn}`, sans(15 * k, 700), inner, PALETTE.warn, 1.3, 2);
  }
  y += 14 * k;

  // Body: the reading and the facts at the left, the chart at the right.
  const leftW = 452;
  const gutter = 36;
  const rightX = P + leftW + gutter;
  const rightW = W - P - rightX;
  const tag = mono(11 * k, 700, 0.12);
  c.line(P, y + tag.size, "READING", tag, PALETTE.accentInk, leftW);
  let left = c.block(P, y + tag.size * 1.6, story.dek, sans(16 * k, 500), leftW, PALETTE.strong, 1.38);
  left = facts(c, story, P, left + 14 * k, leftW, k, 10.5, 18);

  const caption = sans(11 * k, 600, 0.06);
  let right = c.block(rightX, y, chartCaption(story).toUpperCase(), caption, rightW, PALETTE.muted, 1.3, 2);
  right += 6 * k;
  const drawing = drawStoryChart(story, { width: rightW, scale: 1.2 * k, measure });
  c.parts.push(marksToSvg(drawing, "ins-hatch", rightX, right));
  for (const mark of drawing.marks) {
    if (mark.kind !== "text") continue;
    const width = measure(mark.text, mark.style);
    const start = mark.anchor === "start" ? mark.x : mark.anchor === "end" ? mark.x - width : mark.x - width / 2;
    c.texts.push({ text: mark.text, x: rightX + start, y: right + mark.y, width, maxWidth: rightW - Math.max(0, start), size: mark.style.size, anchor: "start" });
    if (start < -0.5 || start + width > rightW + 0.5) c.overflowed = true;
  }
  right += drawing.height;
  y = Math.max(left, right) + 10 * k;

  // The counterpoint and caveat side by side when there is a counterpoint, else full width.
  const noteSize = 13.5;
  if (story.counterpoint !== null) {
    const half = (inner - gutter) / 2;
    const label = sans(11 * k, 700, 0.12);
    c.line(P, y + label.size, "WHAT COULD UNDERMINE IT", label, PALETTE.warn, half);
    const a = c.block(P, y + label.size * 1.5, story.counterpoint, sans(noteSize * k, 500), half, PALETTE.strong, 1.35);
    c.line(P + half + gutter, y + label.size, "CAVEAT", label, PALETTE.accentInk, half);
    const b = c.block(P + half + gutter, y + label.size * 1.5, story.caveat, sans(noteSize * k, 500), half, PALETTE.strong, 1.35);
    y = Math.max(a, b);
  } else {
    y = notes(c, story, P, y, inner, noteSize, k);
  }

  // Footer: attribution at the left, the site at the right.
  const foot = mono(10.5 * Math.max(k, 0.9), 500);
  const brandW = 190;
  const lines = [
    `${input.window} · ${input.scoring} · ${story.edition}`,
    `Sources: ${input.sources.join(" · ")}`,
  ];
  const wrapped = lines.flatMap((line) => wrapText(line, foot, inner - brandW, measure));
  const footH = wrapped.length * foot.size * 1.4;
  const footTop = H - P + 10 - footH;
  const fits = y + 12 * k <= footTop - 10;
  c.parts.push(`<line x1="${String(P)}" y1="${(footTop - 8).toFixed(1)}" x2="${String(W - P)}" y2="${(footTop - 8).toFixed(1)}" stroke="${PALETTE.line}" stroke-width="1"/>`);
  let fy = footTop;
  for (const line of wrapped) {
    c.line(P, fy + foot.size * 1.05, line, foot, PALETTE.faint, inner - brandW);
    fy += foot.size * 1.4;
  }
  const brand = sans(13, 700, 0.14);
  const logoSize = 26;
  c.line(W - P, footTop + logoSize / 2 + brand.size * 0.36, "JEISEY TIERS", brand, PALETTE.strong, brandW - logoSize - 10, "end");
  const logo = { x: W - P - measure("JEISEY TIERS", brand) - 10 - logoSize, y: footTop, size: logoSize };
  return { composer: c, fits: fits && !c.overflowed, logo };
}

function layPortrait(input: ShareInput, k: number): Laid {
  const { width: W, height: H } = SHARE_SIZES.port;
  const { story, measure } = input;
  const c = composer(measure);
  const P = 56;
  const inner = W - 2 * P;
  let y = P;
  y = c.block(P, y, kicker(story).toUpperCase(), sans(17 * k, 700, 0.12), inner, PALETTE.bright, 1.35);
  y = c.block(P, y + 2 * k, input.edition, mono(14 * k, 500), inner, PALETTE.faint, 1.35);
  y += 14 * k;
  y = c.block(P, y, story.headline, sans(48 * k, 700), inner, PALETTE.ink, 1.1, 4);
  y += 10 * k;
  y = c.block(P, y, [story.display_name, ...input.context].join(" · "), sans(23 * k, 600), inner, PALETTE.strong, 1.3, 3);
  if (input.withdrawn !== null) {
    y = c.block(P, y + 6 * k, `Withdrawn — ${input.withdrawn}`, sans(20 * k, 700), inner, PALETTE.warn, 1.3, 3);
  }
  y += 22 * k;
  const tag = mono(13 * k, 700, 0.12);
  c.line(P, y + tag.size, "READING", tag, PALETTE.accentInk, inner);
  y = c.block(P, y + tag.size * 1.6, story.dek, sans(22 * k, 500), inner, PALETTE.strong, 1.38);
  y = facts(c, story, P, y + 22 * k, inner, k, 13, 25);
  y += 8 * k;
  y = c.block(P, y, chartCaption(story).toUpperCase(), sans(13 * k, 600, 0.06), inner, PALETTE.muted, 1.3, 2);
  y += 8 * k;
  const drawing = drawStoryChart(story, { width: inner, scale: 1.55 * k, measure });
  c.parts.push(marksToSvg(drawing, "ins-hatch", P, y));
  for (const mark of drawing.marks) {
    if (mark.kind !== "text") continue;
    const width = measure(mark.text, mark.style);
    const start = mark.anchor === "start" ? mark.x : mark.anchor === "end" ? mark.x - width : mark.x - width / 2;
    c.texts.push({ text: mark.text, x: P + start, y: y + mark.y, width, maxWidth: inner - Math.max(0, start), size: mark.style.size, anchor: "start" });
    if (start < -0.5 || start + width > inner + 0.5) c.overflowed = true;
  }
  y += drawing.height + 22 * k;
  y = notes(c, story, P, y, inner, 18, k);

  const foot = mono(13 * Math.max(k, 0.9), 500);
  const lines = [`${input.window} · ${input.scoring} · ${story.edition}`, `Sources: ${input.sources.join(" · ")}`];
  const wrapped = lines.flatMap((line) => wrapText(line, foot, inner, measure));
  const brandH = 34;
  const footH = wrapped.length * foot.size * 1.4 + brandH + 12;
  const footTop = H - P - footH + 10;
  const fits = y + 16 * k <= footTop - 12;
  c.parts.push(`<line x1="${String(P)}" y1="${(footTop - 10).toFixed(1)}" x2="${String(W - P)}" y2="${(footTop - 10).toFixed(1)}" stroke="${PALETTE.line}" stroke-width="1"/>`);
  let fy = footTop;
  for (const line of wrapped) {
    c.line(P, fy + foot.size * 1.05, line, foot, PALETTE.faint, inner);
    fy += foot.size * 1.4;
  }
  const brand = sans(16, 700, 0.14);
  const logoSize = brandH;
  const brandY = fy + 12;
  c.line(P + logoSize + 12, brandY + logoSize / 2 + brand.size * 0.36, "JEISEY TIERS", brand, PALETTE.strong, inner - logoSize - 12);
  return { composer: c, fits: fits && !c.overflowed, logo: { x: P, y: brandY, size: logoSize } };
}

/**
 * The card at the largest type scale that fits (1.32 down to 0.62 in steps of 0.02): a short
 * story is set large enough to read at the size it is shared, a long one smaller, and nothing is
 * cut. The last attempt is returned even when it does not fit, with `fits: false`.
 */
export function buildShareCard(input: ShareInput): ShareCard {
  const size = SHARE_SIZES[input.layout];
  const lay = input.layout === "land" ? layLandscape : layPortrait;
  let laid: Laid | null = null;
  let scale = 1;
  for (let k = 1.32; k >= 0.62 - 1e-9; k -= 0.02) {
    scale = Math.round(k * 100) / 100;
    laid = lay(input, scale);
    if (laid.fits) break;
  }
  const final = laid ?? lay(input, 0.62);
  const body = final.composer.parts.join("");
  const hatch = hatchPattern("ins-hatch", 6);
  return {
    layout: input.layout,
    width: size.width,
    height: size.height,
    scale,
    fits: final.fits,
    texts: final.composer.texts,
    toSvg: (fontCss, logoHref) => {
      const style = fontCss === "" ? "" : `<style>${fontCss}</style>`;
      const logo =
        logoHref === null
          ? `<rect x="${String(final.logo.x)}" y="${String(final.logo.y)}" width="${String(final.logo.size)}" height="${String(final.logo.size)}" fill="none" stroke="${PALETTE.accent}" stroke-width="1.5"/>`
          : `<image href="${escapeXml(logoHref)}" x="${String(final.logo.x)}" y="${String(final.logo.y)}" width="${String(final.logo.size)}" height="${String(final.logo.size)}" preserveAspectRatio="xMidYMid meet"/>`;
      return (
        `<svg xmlns="http://www.w3.org/2000/svg" width="${String(size.width)}" height="${String(size.height)}" viewBox="0 0 ${String(size.width)} ${String(size.height)}">` +
        `<defs>${style}${hatch}</defs>` +
        `<rect width="${String(size.width)}" height="${String(size.height)}" fill="${PALETTE.canvas}"/>` +
        frame(size.width, size.height, 14, 22) +
        `<rect x="14" y="14" width="96" height="3" fill="${PALETTE.accent}"/>` +
        body +
        logo +
        `</svg>`
      );
    },
  };
}
