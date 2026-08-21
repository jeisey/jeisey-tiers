/**
 * Visual QA capture.
 *
 * `docs/UX_SPEC.md` section 14 names the screens a Phase-6 review has to look at. This script
 * takes them from a real static build so the review sees what a visitor sees, and writes them
 * to `docs/visual-qa/<date>/` where they are committed as evidence alongside the source probes
 * and the market-cohort reports.
 *
 * It captures the *fixture* build by default, so a review is reproducible and two runs of the
 * same code produce the same images; pass `--real` to point it at a build made from the live
 * artifacts instead.
 *
 *   node web/tests/e2e/build-fixtures.ts       # or: npm run e2e:build
 *   node web/tests/e2e/static-server.mjs &
 *   node web/tests/e2e/capture-screens.mjs docs/visual-qa/2026-08-21
 */

import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";

/** Viewport, path and any interaction each required screen needs. */
const SCREENS = [
  {
    name: "01-desktop-tiers-ppr-12-all",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: true,
  },
  {
    name: "02-tablet-tiers-rb",
    path: "/?position=rb",
    viewport: { width: 900, height: 1100 },
    fullPage: true,
  },
  {
    name: "03-desktop-arbitrage-draft-rail",
    path: "/?view=arbitrage",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    name: "04-desktop-data-methodology",
    path: "/?view=data",
    viewport: { width: 1440, height: 1000 },
    fullPage: true,
  },
  {
    name: "05-mobile-tiers",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    name: "06-mobile-arbitrage",
    path: "/?view=arbitrage",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    name: "07-degraded-market",
    path: "/scenario/no-market/?view=arbitrage",
    viewport: { width: 1440, height: 800 },
    fullPage: false,
    // The whole point of this screen is an artifact that is not there.
    expectMissingArtifact: true,
  },
  {
    name: "08-player-injury-detail",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "09-schema-refusal",
    path: "/scenario/bad-schema/",
    viewport: { width: 1440, height: 700 },
    fullPage: false,
  },
  {
    name: "10-pages-base-path",
    path: "/jeisey-tiers/?view=arbitrage&position=qb",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "11-keyboard-focus",
    path: "/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: /median simulated VORP/ }).first().focus();
    },
  },
];

const outDir = resolve(process.argv[2] ?? "docs/visual-qa/local");
mkdirSync(outDir, { recursive: true });

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const problems = [];

for (const screen of SCREENS) {
  const page = await browser.newPage({ viewport: screen.viewport });
  page.on("pageerror", (error) => problems.push(`${screen.name}: ${String(error)}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    // A scenario that withholds an artifact necessarily logs the browser's own 404 line.
    if (screen.expectMissingArtifact && /404/.test(message.text())) return;
    problems.push(`${screen.name}: ${message.text()}`);
  });
  await page.goto(`${BASE}${screen.path}`, { waitUntil: "networkidle" });
  if (screen.act) await screen.act(page);
  await page.waitForTimeout(250);

  // A page that scrolls sideways is a defect, not a screenshot note.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 1) problems.push(`${screen.name}: horizontal overflow of ${String(overflow)}px`);

  await page.screenshot({ path: resolve(outDir, `${screen.name}.png`), fullPage: screen.fullPage });
  await page.close();
  process.stdout.write(`captured ${screen.name}\n`);
}

await browser.close();

if (problems.length > 0) {
  process.stderr.write(`\n${problems.join("\n")}\n`);
  process.exitCode = 1;
}
