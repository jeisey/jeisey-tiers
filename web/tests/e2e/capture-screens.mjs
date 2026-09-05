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
    // The other half of the Phase-8 responsive decision: at this width the same dialog is a
    // sheet. Captured next to 08 so a reviewer compares the two treatments directly.
    name: "08b-mobile-player-detail-sheet",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "08c-tablet-player-detail",
    path: "/",
    viewport: { width: 900, height: 1100 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Kyle Pitts Sr.", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // A player with no price at all: the card has to say so rather than show an empty market
    // block, and the Phase-8 layout has to survive a missing readout grid.
    name: "08d-unpriced-player-detail",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Zach Ertz", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "12-tiers-all-collapsed",
    path: "/?tiers=none",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "13-tiers-all-expanded",
    path: "/?tiers=0.1.2",
    viewport: { width: 1440, height: 1000 },
    fullPage: true,
  },
  {
    name: "14-tablet-arbitrage-rail",
    path: "/?view=arbitrage&rail=all",
    viewport: { width: 900, height: 1100 },
    fullPage: false,
  },
  {
    name: "15-arbitrage-premiums",
    path: "/?view=arbitrage&rail=premiums",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
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

  /*
   * Phase 9A additions.
   *
   * The design source has three player-card variants and two board treatments, so a review
   * that only looks at a desktop and a phone cannot tell a designed variant from a compressed
   * one. These screens cover the third breakpoint, both tables on a phone, the awkward player
   * records the fixture exists to carry, and the market condition the launch fixture cannot
   * show.
   */
  {
    // Narrow tablet: the last width before the board becomes the stack and the card becomes
    // the sheet. If anything is going to be a squeezed desktop, it is this one.
    name: "16-narrow-tablet-tiers",
    path: "/",
    viewport: { width: 768, height: 1100 },
    fullPage: true,
  },
  {
    name: "17-narrow-tablet-player-detail",
    path: "/",
    viewport: { width: 768, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "18-mobile-player-detail-market-tab",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "Draft market" }).click();
    },
  },
  {
    name: "19-mobile-player-detail-status-tab",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "Current status" }).click();
    },
  },
  {
    // No status record published at all, which is not the same as no designation.
    name: "20-player-detail-no-status-record",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Deebo Gray", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The largest positive rank gap on the fixture board, and an IR designation with it.
    name: "21-player-detail-large-bargain",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Jaylin Lane", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // A structural quarterback premium: the number that broke the Phase-6 rail's axis.
    name: "22-player-detail-large-premium",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Joe Burrow", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "23-mobile-tier-table",
    path: "/",
    viewport: { width: 390, height: 900 },
    fullPage: false,
    async act(page) {
      await page.getByRole("heading", { name: "Tier table" }).scrollIntoViewIfNeeded();
    },
  },
  {
    name: "24-mobile-arbitrage-table",
    path: "/?view=arbitrage",
    viewport: { width: 390, height: 900 },
    fullPage: false,
    async act(page) {
      await page.getByRole("heading", { name: "Arbitrage table" }).scrollIntoViewIfNeeded();
    },
  },
  {
    name: "25-mobile-data",
    path: "/?view=data",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    // The matured market: medium confidence, a measured trend, a sufficient cohort. The launch
    // fixture is uniformly low with a null trend, and a review that only sees that one is the
    // defect Phase 8 found in the test suite.
    name: "26-matured-market-arbitrage",
    path: "/scenario/matured/?view=arbitrage",
    viewport: { width: 1440, height: 1100 },
    fullPage: false,
  },
  {
    name: "27-matured-market-player-detail",
    path: "/scenario/matured/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The other degraded mode: model values intact, every status annotation gone.
    name: "28-degraded-status",
    path: "/scenario/no-status/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
    expectMissingArtifact: true,
  },

  /*
   * Phase 12 — In-Season mode.
   *
   * The default fixture build publishes no in-season bundle, because before kickoff that is
   * the correct product. These screens come from the two in-season scenario builds instead,
   * and they are the ones a review has to look at hardest: every heading here names a
   * rest-of-season quantity, and the two disclosure contracts — ADR-074's tier bands and
   * ADR-076's long absence — are only real if they are legible on the screen.
   */
  {
    name: "29-desktop-ros-tiers",
    path: "/scenario/in-season/",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    // The ADR-076 cohort: the flag, the week count, and the sentences that bound what it means.
    name: "30-desktop-ros-long-absence",
    path: "/scenario/in-season/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator(".absence-badge").first().scrollIntoViewIfNeeded();
    },
  },
  {
    name: "31-desktop-opportunity",
    path: "/scenario/in-season/?view=opportunity",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    name: "32-tablet-ros-tiers",
    path: "/scenario/in-season/?position=rb",
    viewport: { width: 900, height: 1100 },
    fullPage: true,
  },
  {
    name: "33-mobile-ros-tiers",
    path: "/scenario/in-season/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    name: "34-mobile-opportunity",
    path: "/scenario/in-season/?view=opportunity",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    // The behaviour feed is down. Counts go blank rather than to zero, and every intrinsic
    // value is still there — the failure a reader must be able to tell from "nobody added him".
    name: "35-opportunity-behaviour-absent",
    path: "/scenario/in-season-no-behavior/?view=opportunity",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
  },
  {
    // Two models, two orderings, side by side and not reconciled into one number.
    name: "36-inseason-player-detail",
    path: "/scenario/in-season/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "37-inseason-data-methodology",
    path: "/scenario/in-season/?view=data",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    // The draft board stays reachable all season, and says so in the mode indicator.
    name: "38-inseason-draft-mode",
    path: "/scenario/in-season/?mode=draft",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
  },

  /*
   * The two lifecycle windows (ADR-079): the season has started and the draft board is the
   * only board that exists. Worth a picture precisely because the wrong version of these
   * looks fine — a draft board labelled "Draft mode" in November is not visibly broken.
   */
  {
    name: "39-awaiting-first-ros-board",
    path: "/scenario/awaiting-first-week/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "40-season-complete",
    path: "/scenario/season-complete/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
];

/** Artifacts a build is allowed not to publish; see the console filter below. */
const OPTIONAL_ARTIFACTS = /market_trend_series\.json|ros_build_metadata\.json/;

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
    // So does an artifact the contract declares optional. The market trend series exists only
    // once the snapshot window holds enough of them, and the in-season bundle only after the
    // season's first kickoff — before which the draft build is the whole product. The loader
    // treats both absences as normal; the browser still prints a 404, and a 404 for an
    // artifact that is allowed to be missing is not evidence of anything.
    // The console line names no URL, so the resource comes from the message's own location.
    if (/404/.test(message.text()) && OPTIONAL_ARTIFACTS.test(message.location().url)) return;
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
