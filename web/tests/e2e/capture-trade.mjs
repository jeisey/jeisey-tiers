/**
 * Visual QA for the Trade tab (ADR-100) and the six-tab navigation, at 1440, 820, 390 and
 * 320px, on the fixture build or a real one. Each screen is captured and measured: horizontal
 * overflow of the document, any Trade element whose box leaves the section, and whether the
 * active tab is fully inside the tab row.
 *
 *   node web/tests/e2e/static-server.mjs &
 *   node web/tests/e2e/capture-trade.mjs docs/visual-qa/2026-10-02-trade/fixture \
 *     --prefix /scenario/in-season/ [--give 00-0000001]
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

import { stubPortraits } from "./portrait-stub.mjs";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";
const args = process.argv.slice(2);
const outDir = resolve(args[0] ?? "docs/visual-qa/trade");
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const prefix = option("--prefix", "/scenario/in-season/");
const give = option("--give", "00-0000001");

const WIDTHS = [
  [1440, 1000],
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
        ".trade-chip, .trade-picker, .trade-controls .control, .trade-package, .trade-metrics > div, .trade-members li, .trade-package-actions, .trade-actions > *",
      )) {
        const rect = node.getBoundingClientRect();
        if (rect.width === 0) continue;
        if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1) {
          clipped.push(`${node.className} [${Math.round(rect.left)}, ${Math.round(rect.right)}]`);
        }
      }
    }
    // A number cut off by an ellipsis is a wrong number: every readout must show in full.
    const truncated = [];
    if (root) {
      for (const node of root.querySelectorAll(".trade-metrics dd, .trade-outgoing dd, .trade-chip-value, .trade-member-value")) {
        if (node.scrollWidth > node.clientWidth + 1) truncated.push(node.textContent);
      }
    }
    const row = document.querySelector('[role="tablist"][aria-label="Board"]');
    const active = row?.querySelector('[aria-selected="true"]');
    let activeTabVisible = null;
    if (row && active) {
      const r = row.getBoundingClientRect();
      const a = active.getBoundingClientRect();
      activeTabVisible = a.left >= r.left - 1 && a.right <= r.right + 1;
    }
    const tabs = [...(row?.querySelectorAll('[role="tab"]') ?? [])].map((tab) => ({
      text: tab.textContent,
      height: Math.round(tab.getBoundingClientRect().height),
    }));
    return { overflow, clipped: clipped.slice(0, 10), truncated: truncated.slice(0, 10), activeTabVisible, tabs };
  }, scope);
}

for (const [width, height] of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await stubPortraits(page);

  // 1. Empty Trade tab.
  await page.goto(`${BASE}${prefix}?view=trade`, { waitUntil: "networkidle" });
  await page.waitForSelector("section.trade .trade-picker");
  report.push({ screen: "trade-empty", width, ...(await measure(page, "section.trade")) });
  await page.screenshot({ path: `${outDir}/trade-empty-${String(width)}.png`, fullPage: true });

  // 2. Give one, receive two: the full flow.
  await page.goto(`${BASE}${prefix}?view=trade&give=${give}&get=2`, { waitUntil: "networkidle" });
  await page.waitForSelector(".trade-results .trade-package");
  report.push({ screen: "trade-1for2", width, ...(await measure(page, "section.trade")) });
  await page.screenshot({ path: `${outDir}/trade-1for2-${String(width)}.png`, fullPage: true });

  // 3. Ceiling, a kept package and a swap.
  await page.getByRole("radio", { name: "Highest ceiling" }).click();
  await page.locator(".trade-results .trade-keep").first().click();
  await page.locator(".trade-results .trade-swap").first().click();
  await page.waitForSelector(".trade-kept");
  report.push({ screen: "trade-kept", width, ...(await measure(page, "section.trade")) });
  await page.screenshot({ path: `${outDir}/trade-kept-${String(width)}.png`, fullPage: true });

  // 4. The navigation on other tabs: the active tab must be on screen.
  for (const view of ["ros", "opportunity", "potw", "data"]) {
    await page.goto(`${BASE}${prefix}?view=${view}`, { waitUntil: "networkidle" });
    await page.waitForSelector('[role="tabpanel"]');
    await page.waitForTimeout(400);
    report.push({ screen: `nav-${view}`, width, ...(await measure(page, "main")) });
    await page.screenshot({
      path: `${outDir}/nav-${view}-${String(width)}.png`,
      clip: { x: 0, y: 0, width, height: Math.min(height, 260) },
    });
  }
  await context.close();
}

await browser.close();
writeFileSync(`${outDir}/measurements.json`, `${JSON.stringify({ prefix, give, report }, null, 1)}\n`);
const bad = report.filter(
  (entry) =>
    entry.overflow > 1 ||
    entry.clipped.length > 0 ||
    entry.truncated.length > 0 ||
    entry.activeTabVisible === false,
);
console.log(JSON.stringify({ outDir, screens: report.length, problems: bad }, null, 1));
process.exitCode = bad.length === 0 ? 0 : 1;
