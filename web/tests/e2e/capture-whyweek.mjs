/**
 * Visual QA for "Why this week" (ADR-099): the Start/Sit tab, the player card's "This week"
 * block and the week board, at 1440, 1024, 820, 390 and 320px, on the fixture build or a real
 * one. Each screen is captured and measured: horizontal overflow of the document, and any
 * explanation element whose box leaves the section it sits in. The last session's phone
 * defects showed up only on real data, so the same script runs against both.
 *
 *   node web/tests/e2e/static-server.mjs &                       # fixtures, or a real dist
 *   node web/tests/e2e/capture-whyweek.mjs docs/visual-qa/2026-10-01/fixture \
 *     --prefix /scenario/in-season/
 *   node web/tests/e2e/capture-whyweek.mjs docs/visual-qa/2026-10-01/real --prefix / \
 *     --data web/public/data
 *
 * With `--data`, the pair compared is the two highest PPR medians in that build's
 * `weekly_projections.json`; without it, the fixture's pair.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

import { stubPortraits } from "./portrait-stub.mjs";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";
const args = process.argv.slice(2);
const outDir = resolve(args[0] ?? "docs/visual-qa/whyweek");
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const prefix = option("--prefix", "/scenario/in-season/");
const dataDir = option("--data", null);

let pair = "00-0000011.00-0000012";
if (dataDir !== null) {
  const records = JSON.parse(readFileSync(`${dataDir}/weekly_projections.json`, "utf-8")).records;
  const top = records
    .filter((r) => r.scoring_preset === "PPR" && r.quantiles !== null && r.explanation)
    .sort((a, b) => b.quantiles.q50 - a.quantiles.q50 || a.player_id.localeCompare(b.player_id))
    .slice(0, 2);
  pair = top.map((r) => r.player_id.replace(/^gsis:/, "")).join(".");
}

const WIDTHS = [
  [1440, 1000],
  [1024, 900],
  [820, 1180],
  [390, 844],
  [320, 800],
];

mkdirSync(outDir, { recursive: true });
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const report = [];

async function measure(page, scope) {
  return page.evaluate((selector) => {
    const doc = document.documentElement;
    const overflow = doc.scrollWidth - doc.clientWidth;
    const root = document.querySelector(selector);
    const bounds = root?.getBoundingClientRect();
    const clipped = [];
    if (bounds) {
      for (const node of root.querySelectorAll(
        ".why-week, .why-week-heads, .why-week-table, .why-week-context li, .why-week-compact, .wb-why-cell, .why-week-attribution",
      )) {
        const rect = node.getBoundingClientRect();
        if (rect.width === 0) continue;
        if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1) {
          clipped.push(`${node.className} [${Math.round(rect.left)}, ${Math.round(rect.right)}]`);
        }
      }
    }
    return { overflow, clipped: clipped.slice(0, 10) };
  }, scope);
}

for (const [width, height] of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await stubPortraits(page);

  // 1. The Start/Sit tab with a pair, the pick's "Why this week" open.
  await page.goto(`${BASE}${prefix}?view=startsit&scoring=ppr&teams=12&duel=${pair}`, { waitUntil: "networkidle" });
  await page.waitForSelector(".verdict-head");
  const why = page.locator(".why-this-week");
  if ((await why.count()) > 0) await why.first().scrollIntoViewIfNeeded();
  report.push({ screen: "startsit", width, ...(await measure(page, "section.startsit")) });
  await page.screenshot({ path: `${outDir}/startsit-${String(width)}.png`, fullPage: true });

  // 2. The week board's "vs typical" column.
  const board = page.locator(".weekboard-table");
  if ((await board.count()) > 0) {
    await board.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${outDir}/weekboard-${String(width)}.png`, fullPage: false });
  }

  // 3. The player card's "This week" block.
  await page.locator(".deck-name").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  const tab = dialog.getByRole("tab", { name: /this week/i });
  if ((await tab.count()) > 0) await tab.first().click();
  const block = dialog.locator(".why-week").first();
  if ((await block.count()) > 0) await block.scrollIntoViewIfNeeded();
  report.push({ screen: "card", width, ...(await measure(page, '[role="dialog"]')) });
  await page.screenshot({ path: `${outDir}/card-${String(width)}.png`, fullPage: false });
  await context.close();
}

await browser.close();
writeFileSync(`${outDir}/measurements.json`, `${JSON.stringify({ prefix, pair, report }, null, 1)}\n`);
const bad = report.filter((entry) => entry.overflow > 1 || entry.clipped.length > 0);
console.log(JSON.stringify({ outDir, pair, screens: report.length, problems: bad }, null, 1));
process.exitCode = bad.length === 0 ? 0 : 1;
