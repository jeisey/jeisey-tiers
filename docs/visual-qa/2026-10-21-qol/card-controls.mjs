// The phone card's close (✕) and Expand/Collapse controls, measured and captured (ADR-115).
//
// Usage, from the repository root after `npm run e2e:build`:
//   node docs/visual-qa/2026-10-21-qol/card-controls.mjs web/dist-in-season <out dir>
// "Before" is the same script against main at ee863cc's in-season fixture build.
//
// For every viewport it opens three cards — Puka Nightingale (the reported case), Kyle Pitts Sr.
// (an Out badge and a suffix) and "Bijan Robinson (surfaced)" (the longest name, opened from the
// Opportunity Board) — and measures both controls in both header states, on every tab, and
// again with the panel scrolled to its end. It records the two rectangles, the gap between them
// (negative is an overlap) and any page, card or rail overflow. Screenshots are taken of the
// reported case at every width, compact and expanded.
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";
import { createStaticServer } from "../../../web/tests/e2e/static-server.mjs";

const [dir, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const server = createStaticServer({ roots: [{ base: "/scenario/in-season/", dir: resolve(dir) }] });
await new Promise((ok) => server.listen(4392, ok));
const base = "http://localhost:4392/scenario/in-season";
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined ? {} : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
);
const sizes = [
  ["320", 320, 640, true],
  ["390", 390, 844, true],
  ["412-pixel7", 412, 839, true],
  ["390x560-short", 390, 560, true],
  ["768", 768, 1024, true],
  ["1024", 1024, 768, false],
  ["1440", 1440, 900, false],
];
const cards = [
  { key: "puka", view: "ros", name: "Puka Nightingale" },
  { key: "pitts", view: "ros", name: "Kyle Pitts Sr." },
  { key: "surfaced", view: "opportunity", name: "Bijan Robinson (surfaced)" },
];

const measure = (page) =>
  page.evaluate(() => {
    const box = (selector) => {
      const node = document.querySelector(selector);
      if (node === null) return null;
      const r = node.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return null;
      return { x0: +r.left.toFixed(2), x1: +r.right.toFixed(2), y0: +r.top.toFixed(2), y1: +r.bottom.toFixed(2) };
    };
    const close = box("dialog.player-detail .detail-close");
    const toggle = box("dialog.player-detail .detail-expand");
    let gap = null;
    let overlap = null;
    if (close !== null && toggle !== null) {
      const dx = Math.max(close.x0 - toggle.x1, toggle.x0 - close.x1);
      const dy = Math.max(close.y0 - toggle.y1, toggle.y0 - close.y1);
      // The separation between the two rectangles; negative on both axes is an overlap.
      gap = +Math.max(dx, dy).toFixed(2);
      overlap = dx < 0 && dy < 0 ? [+(-dx).toFixed(2), +(-dy).toFixed(2)] : null;
    }
    const overflow = (selector) => {
      const node = document.querySelector(selector);
      return node === null ? null : node.scrollWidth - node.clientWidth;
    };
    const inView = (rect) =>
      rect !== null && rect.y0 >= 0 && rect.x0 >= 0 && rect.x1 <= window.innerWidth && rect.y1 <= window.innerHeight;
    return {
      close,
      toggle,
      gap,
      overlap,
      closeInView: inView(close),
      toggleInView: toggle === null ? null : inView(toggle),
      pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      cardOverflowX: overflow("dialog.player-detail .detail-card"),
      railOverflowX: overflow("dialog.player-detail .detail-rail"),
      expanded: document.querySelector("dialog.player-detail .detail-expand")?.getAttribute("aria-expanded") ?? null,
    };
  });

const report = {};
for (const [size, width, height, touch] of sizes) {
  const context = await browser.newContext({
    viewport: { width, height },
    hasTouch: touch,
    isMobile: touch && width < 800,
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  for (const card of cards) {
    const key = `${size}/${card.key}`;
    await page.goto(`${base}/?view=${card.view}`);
    const trigger = page.getByRole("button", { name: card.name, exact: true }).first();
    await trigger.waitFor();
    await trigger.click();
    await page.locator("dialog.player-detail[open]").waitFor();
    await page.waitForTimeout(250);
    const entry = { compact: await measure(page), tabs: {}, scrolled: null, expanded: null };
    if (card.key === "puka") await page.screenshot({ path: `${out}/card-${size}.png` });
    const tabs = page.locator("dialog.player-detail .detail-tabs [role=tab]");
    const states = (await page.locator("dialog.player-detail .detail-expand").count()) > 0 ? ["compact", "expanded"] : ["static"];
    for (const state of states) {
      if (state === "expanded") {
        await page.locator("dialog.player-detail .detail-expand").click();
        await page.waitForTimeout(150);
        entry.expanded = await measure(page);
        if (card.key === "puka") await page.screenshot({ path: `${out}/card-${size}-expanded.png` });
      }
      const count = await tabs.count();
      for (let index = 0; index < count; index += 1) {
        const tab = tabs.nth(index);
        const label = (await tab.textContent())?.trim() ?? String(index);
        await tab.click();
        await page.waitForTimeout(120);
        entry.tabs[`${state}:${label}`] = await measure(page);
      }
      await page.evaluate(() => {
        const body = document.querySelector("dialog.player-detail .detail-body");
        if (body !== null) body.scrollTop = body.scrollHeight;
        const rail = document.querySelector("dialog.player-detail .detail-rail");
        if (rail !== null) rail.scrollTop = rail.scrollHeight;
      });
      await page.waitForTimeout(120);
      entry[`scrolled-${state}`] = await measure(page);
      if (card.key === "puka" && state !== "static") await page.screenshot({ path: `${out}/card-${size}-${state}-scrolled.png` });
    }
    // Escape closes, and the header is compact again on the next open (ADR-111).
    await page.keyboard.press("Escape");
    await page.waitForTimeout(100);
    entry.closedByEscape = (await page.locator("dialog.player-detail[open]").count()) === 0;
    entry.focusReturned = await page.evaluate(() => document.activeElement?.textContent?.trim() ?? null);
    report[key] = entry;
  }
  report[`${size}/errors`] = errors;
  await context.close();
}

// The worst case across every measurement: the smallest gap and any overlap or overflow.
const all = [];
for (const [key, entry] of Object.entries(report)) {
  if (key.endsWith("/errors")) continue;
  for (const [where, value] of Object.entries(entry)) {
    if (value === null || typeof value !== "object") continue;
    if (where === "tabs") for (const [tab, m] of Object.entries(value)) all.push([`${key} ${tab}`, m]);
    else all.push([`${key} ${where}`, value]);
  }
}
const withGap = all.filter(([, m]) => m.gap !== null && m.gap !== undefined);
const worst = withGap.reduce((low, item) => (low === null || item[1].gap < low[1].gap ? item : low), null);
report.summary = {
  measurements: all.length,
  withBothControls: withGap.length,
  overlaps: withGap.filter(([, m]) => m.overlap !== null).map(([where, m]) => [where, m.overlap]),
  smallestGap: worst === null ? null : [worst[0], worst[1].gap],
  pageOverflow: all.filter(([, m]) => m.pageOverflowX > 0).map(([where]) => where),
  cardOverflow: all.filter(([, m]) => (m.cardOverflowX ?? 0) > 0).map(([where]) => where),
  closeOutOfView: all.filter(([, m]) => m.closeInView === false).map(([where]) => where),
  browser: browser.version(),
};
writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report.summary, null, 2));
await browser.close();
server.close();
