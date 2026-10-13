/**
 * Visual QA for My Leagues (ADR-106) at 320, 390, 768, 1024, 1280 and 1440px and a short phone
 * (390×600), on the fixture build or a real one. Each screen is captured and measured:
 * horizontal overflow of the document, any workspace element whose box leaves the section,
 * numbers cut off by an ellipsis, a dialog wider or taller than the viewport, and whether the
 * active tab is fully inside the tab row.
 *
 *   node web/tests/e2e/static-server.mjs &
 *   node web/tests/e2e/capture-leagues.mjs docs/visual-qa/2026-10-13-my-leagues/fixture \
 *     [--prefix /scenario/in-season/] [--roster gsis:00-0000009,...]
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

import { stubPortraits } from "./portrait-stub.mjs";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";
const args = process.argv.slice(2);
const outDir = resolve(args[0] ?? "docs/visual-qa/my-leagues");
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const prefix = option("--prefix", "/scenario/in-season/");
const KEY = `jeisey-tiers:my-leagues@${prefix}`;
// QB, RB, RB, WR, WR, TE, FLEX, then bench: the fixture roster every e2e flow uses.
const roster = option(
  "--roster",
  ["09", "01", "16", "12", "06", "07", "17", "10", "02", "11"].map((id) => `gsis:00-00000${id}`).join(","),
).split(",");

const SCREENS = [
  [1440, 1000],
  [1280, 900],
  [1024, 900],
  [768, 1024],
  [390, 844],
  [390, 600],
  [320, 800],
];

function documentFor(ids) {
  const counts = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 5, IR: 2 };
  let cursor = 0;
  const roster = Object.fromEntries(
    Object.entries(counts).map(([group, count]) => [
      group,
      Array.from({ length: count }, () => (group === "IR" ? null : (ids[cursor++] ?? null))),
    ]),
  );
  const league = (id, name, extra) => ({
    id,
    name,
    season: 2026,
    scoring: "ppr",
    teams: 12,
    slots: counts,
    roster,
    prefs: { risingStars: true, mode: "q50" },
    rev: 1,
    updatedAt: "2026-10-13T00:00:00Z",
    ...extra,
  });
  return JSON.stringify({
    format: "jeisey-tiers.my-leagues",
    version: 1,
    revision: 1,
    activeId: "lg-office01",
    leagues: [
      league("lg-office01", "Office"),
      league("lg-family01", "Family league with a long name", { scoring: "half", teams: 10, roster: Object.fromEntries(Object.entries(counts).map(([group, count]) => [group, Array.from({ length: count }, () => null)])) }),
    ],
  });
}

mkdirSync(outDir, { recursive: true });
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const report = [];

async function measure(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const overflow = doc.scrollWidth - doc.clientWidth;
    const root = document.querySelector("section.leagues");
    const bounds = root?.getBoundingClientRect();
    const clipped = [];
    if (root && bounds) {
      for (const node of root.querySelectorAll(
        ".lg-slot, .lg-switch-option, .lg-bar-actions > *, .lg-auto, .lg-rising, .lg-need, .lg-package, .lg-detail, .lg-preset-links",
      )) {
        const rect = node.getBoundingClientRect();
        if (rect.width === 0) continue;
        if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1) {
          clipped.push(`${node.className} [${Math.round(rect.left)}, ${Math.round(rect.right)}]`);
        }
      }
    }
    const truncated = [];
    for (const node of document.querySelectorAll(".lg-quantiles, .lg-auto-totals span, .lg-package-line, .lg-target-meta")) {
      if (node.scrollWidth > node.clientWidth + 1) truncated.push(node.textContent);
    }
    const dialog = document.querySelector("dialog[open]");
    let dialogFits = null;
    if (dialog) {
      const box = dialog.getBoundingClientRect();
      dialogFits = box.left >= 0 && box.right <= window.innerWidth + 1 && box.top >= 0 && box.bottom <= window.innerHeight + 1;
    }
    const row = document.querySelector('[role="tablist"][aria-label="Board"]');
    const active = row?.querySelector('[aria-selected="true"]');
    let activeTabVisible = null;
    if (row && active) {
      const r = row.getBoundingClientRect();
      const a = active.getBoundingClientRect();
      activeTabVisible = a.left >= r.left - 1 && a.right <= r.right + 1;
    }
    return { overflow, clipped: clipped.slice(0, 10), truncated: truncated.slice(0, 10), dialogFits, activeTabVisible };
  });
}

for (const [width, height] of SCREENS) {
  const tag = `${String(width)}x${String(height)}`;
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  await context.addInitScript(
    ([key, value]) => {
      if (window.sessionStorage.getItem("seeded") === null) {
        window.localStorage.setItem(key, value);
        window.sessionStorage.setItem("seeded", "1");
      }
    },
    [KEY, documentFor(roster)],
  );
  const page = await context.newPage();
  await stubPortraits(page);

  // 1. The workspace: switcher, Auto Start/Sit, the roster with Rising Stars beside it.
  await page.goto(`${BASE}${prefix}?view=myleagues`, { waitUntil: "networkidle" });
  await page.waitForSelector(".lg-slot");
  await page.waitForTimeout(300);
  report.push({ screen: "workspace", size: tag, ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/workspace-${tag}.png`, fullPage: true });

  // 2. Improve, and one slot's week open.
  await page.getByRole("button", { name: "Find upgrades" }).click();
  await page.waitForSelector(".lg-improve-result");
  const week = page.locator(".lg-more").first();
  await week.click();
  await page.waitForTimeout(200);
  report.push({ screen: "improve-detail", size: tag, ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/improve-detail-${tag}.png`, fullPage: true });

  // 3. The slot picker with suggestions.
  await page.getByRole("button", { name: /^Add a player to Bench/ }).first().click();
  await page.getByRole("dialog").getByRole("combobox").fill("co");
  await page.waitForTimeout(150);
  report.push({ screen: "picker", size: tag, ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/picker-${tag}.png` });
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");

  // 4. The settings dialog with an overflow to resolve.
  await page.getByRole("button", { name: "League settings" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Fewer RB slots" }).click();
  await page.waitForTimeout(150);
  report.push({ screen: "settings", size: tag, ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/settings-${tag}.png` });
  await page.keyboard.press("Escape");

  // 5. The empty second league.
  await page.getByRole("radio", { name: /Family league/ }).click();
  await page.waitForSelector(".lg-slot");
  await page.waitForTimeout(300);
  report.push({ screen: "empty-league", size: tag, ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/empty-league-${tag}.png`, fullPage: width >= 768 });
  await context.close();
}

await browser.close();
writeFileSync(`${outDir}/measurements.json`, `${JSON.stringify({ prefix, roster, report }, null, 1)}\n`);
const bad = report.filter(
  (entry) =>
    entry.overflow > 1 ||
    entry.clipped.length > 0 ||
    entry.truncated.length > 0 ||
    entry.dialogFits === false ||
    entry.activeTabVisible === false,
);
console.log(JSON.stringify({ outDir, screens: report.length, problems: bad }, null, 1));
process.exitCode = bad.length === 0 ? 0 : 1;
