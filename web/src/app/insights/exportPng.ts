/**
 * The share card's PNG (ADR-116), made in the browser from the same SVG the preview shows.
 *
 * An SVG drawn as an image cannot reach the page's stylesheet, so the self-hosted faces are
 * embedded in it as data URLs — fetched from the same hashed asset URLs the stylesheet already
 * loaded, so the export costs no new download — with the same `unicode-range` split. The image
 * is drawn onto a canvas of exactly the card's pixel size (device pixel ratio 1), so the file
 * is 1200×675 or 1080×1350 whatever the screen. No third-party image is ever drawn: the canvas
 * stays untainted and the file holds nothing the page did not author.
 */

import exoCore from "../../assets/fonts/exo2-core.woff2?url";
import exoExt from "../../assets/fonts/exo2-latin-ext.woff2?url";
import exoRest from "../../assets/fonts/exo2-latin-rest.woff2?url";
import monoCore from "../../assets/fonts/jetbrains-mono-core.woff2?url";
import monoExt from "../../assets/fonts/jetbrains-mono-latin-ext.woff2?url";
import monoRest from "../../assets/fonts/jetbrains-mono-latin-rest.woff2?url";
import logoUrl from "../../assets/jt_logo-96.png";
import { PALETTE, canvasFont, type TextStyle } from "./marks";

/** The stylesheet's faces (`base.css`), with their ranges, for the embedded `@font-face`s. */
const FACES: readonly { readonly family: string; readonly url: string; readonly range: string }[] = [
  {
    family: "Exo 2",
    url: exoCore,
    range: "U+0020-007E, U+00A0, U+00B1, U+00B7, U+00D7, U+2013-2014, U+2018-2019, U+201C-201D, U+2026, U+2039-203A, U+2212",
  },
  {
    family: "Exo 2",
    url: exoRest,
    range:
      "U+000D, U+00A1-00AC, U+00AE-00B0, U+00B2-00B6, U+00B8-00D6, U+00D8-00FF, U+0102, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0300-0301, U+0303-0304, U+0308-0309, U+0323, U+2009, U+200B, U+201A, U+201E, U+2022, U+2032-2033, U+2044, U+20AC, U+2122, U+2215",
  },
  {
    family: "Exo 2",
    url: exoExt,
    range:
      "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
  },
  {
    family: "JetBrains Mono",
    url: monoCore,
    range:
      "U+0020-007E, U+00A0, U+00B1, U+00B7, U+00D7, U+2013-2014, U+2018-2019, U+201C-201D, U+2026, U+2039-203A, U+2191, U+2193, U+2212, U+FEFF",
  },
  {
    family: "JetBrains Mono",
    url: monoRest,
    range:
      "U+000D, U+00A1-00B0, U+00B2-00B6, U+00B8-00D6, U+00D8-00FF, U+0102, U+0131, U+0152-0153, U+02BC, U+02C6, U+02DA, U+02DC, U+0300-0301, U+0303-0304, U+0308-0309, U+0323, U+201A, U+201E, U+2022, U+2032-2033, U+2044, U+20AC, U+2122, U+2215",
  },
  {
    family: "JetBrains Mono",
    url: monoExt,
    range:
      "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
  },
];

function base64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let start = 0; start < bytes.length; start += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  }
  return btoa(binary);
}

async function dataUrl(url: string, type: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${String(response.status)}`);
  return `data:${type};base64,${base64(await response.arrayBuffer())}`;
}

/** `U+0020-007E, U+00A0` → [[0x20, 0x7e], [0xa0, 0xa0]]. */
function ranges(range: string): [number, number][] {
  return range.split(",").map((part) => {
    const [low = "0", high] = part.trim().replace(/^U\+/i, "").split("-");
    const start = Number.parseInt(low, 16);
    return [start, high === undefined ? start : Number.parseInt(high, 16)];
  });
}

/** Whether a face's range holds any character of `text`, as the browser decides which to load. */
function covers(face: (typeof FACES)[number], text: string): boolean {
  const spans = ranges(face.range);
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0;
    if (spans.some(([start, end]) => code >= start && code <= end)) return true;
  }
  return false;
}

const faces = new Map<string, Promise<string | null>>();

/** One face as an embedded `@font-face`, fetched once per page (from the browser's cache). */
function faceRule(face: (typeof FACES)[number]): Promise<string | null> {
  let rule = faces.get(face.url);
  if (rule === undefined) {
    rule = dataUrl(face.url, "font/woff2")
      .then(
        (url) =>
          `@font-face{font-family:'${face.family}';font-style:normal;font-weight:400 700;src:url(${url}) format('woff2');unicode-range:${face.range};}`,
      )
      .catch(() => {
        faces.delete(face.url);
        return null;
      });
    faces.set(face.url, rule);
  }
  return rule;
}

/**
 * The faces a card's text needs, as embedded `@font-face`s — only the subsets whose ranges hold
 * one of its characters, as the page itself loads them — or "" when none can be read (the card
 * still draws, in the fallback faces).
 */
export async function embeddedFontCss(text: string): Promise<string> {
  const needed = FACES.filter((face) => covers(face, text));
  const rules = await Promise.all(needed.map(faceRule));
  return rules.filter((rule): rule is string => rule !== null).join("");
}

let logo: Promise<string | null> | null = null;

/** The site's mark as a data URL, or null (the card draws a plain frame in its place). */
export function logoDataUrl(): Promise<string | null> {
  logo ??= (logoUrl.startsWith("data:") ? Promise.resolve(logoUrl) : dataUrl(logoUrl, "image/png")).catch(() => {
    logo = null;
    return null;
  });
  return logo;
}

/**
 * Wait until the faces a card uses are loaded for its characters, so the lines measured for it
 * are measured in the faces it will be drawn in.
 */
export async function loadFaces(styles: readonly TextStyle[], sample: string): Promise<void> {
  if (typeof document === "undefined" || !("fonts" in document)) return;
  const fonts = document.fonts;
  await Promise.all(styles.map((style) => fonts.load(canvasFont(style), sample).catch(() => [])));
  await fonts.ready;
}

export function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** The SVG drawn onto a canvas of exactly `width`×`height`, as a PNG. */
export async function rasterize(svg: string, width: number, height: number): Promise<Blob> {
  const image = new Image();
  image.width = width;
  image.height = height;
  image.src = svgDataUrl(svg);
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("this browser cannot draw the image");
  context.fillStyle = PALETTE.canvas;
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob === null) reject(new Error("the image could not be encoded"));
      else resolve(blob);
    }, "image/png");
  });
}

/** Save a blob under `filename` through an ordinary download link. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 30_000);
}
