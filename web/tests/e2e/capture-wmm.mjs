/**
 * Visual QA for Win My Matchup (ADR-110) at 320, 390, 768, 1024, 1280 and 1440px, plus two
 * short heights (390×600, 1280×720), on the fixture's in-season build. Each screen is captured
 * and measured: horizontal overflow of the document, any WMM element whose box leaves the
 * section, numbers cut off by an ellipsis, a dialog larger than the viewport, and whether the
 * chart's plot stays inside its figure.
 *
 * The page clock is set as `wmm.spec.ts` sets it: within 48 hours of the fixture's behaviour
 * snapshot and before every week-9 kickoff, so YOLO's feed is current and nothing is locked; the
 * finals screen moves it to Sunday afternoon, when two starters have kicked off.
 *
 *   npm run e2e:build
 *   node web/tests/e2e/static-server.mjs &
 *   node web/tests/e2e/capture-wmm.mjs docs/visual-qa/2026-10-15-win-my-matchup/fixture
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

import { stubPortraits } from "./portrait-stub.mjs";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";
const PREFIX = "/scenario/in-season/";
const outDir = resolve(process.argv[2] ?? "docs/visual-qa/win-my-matchup");
const FRESH = new Date("2026-08-22T12:00:00Z");
const SUNDAY = new Date("2026-11-08T19:00:00Z");

const SCREENS = [
  [1440, 1000],
  [1280, 900],
  [1280, 720],
  [1024, 900],
  [768, 1024],
  [390, 844],
  [390, 600],
  [320, 800],
];

const SHORT = new Set(["390x600", "1280x720"]);

const g = (short) => `gsis:00-00000${short}`;
const COUNTS = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 5, IR: 2 };

/** The e2e league `MATCH` (leagues-seed.ts): a bye, three "if active" starters, a rising pickup unowned. */
function leaguesDocument() {
  const roster = { QB: [g("09")], RB: [g("01"), g("16")], WR: [g("12"), g("06")], TE: [g("04")], FLEX: [g("17")], BN: [g("07"), g("10")] };
  return JSON.stringify({
    format: "jeisey-tiers.my-leagues",
    version: 1,
    revision: 1,
    activeId: "lg-match01",
    leagues: [
      {
        id: "lg-match01",
        name: "Match",
        season: 2026,
        scoring: "ppr",
        teams: 12,
        slots: COUNTS,
        roster: Object.fromEntries(Object.entries(COUNTS).map(([group, count]) => [group, Array.from({ length: count }, (_, i) => roster[group]?.[i] ?? null)])),
        prefs: { risingStars: false, mode: "q50" },
        rev: 1,
        updatedAt: "2026-08-21T00:00:00Z",
      },
    ],
  });
}

/** Its complete week-9 opponent (`matchOpponent()`), every absence confirmed as 0. */
function matchupDocument() {
  return JSON.stringify({
    format: "jeisey-tiers.win-my-matchup",
    version: 1,
    revision: 1,
    prefs: {},
    entries: [
      {
        leagueId: "lg-match01",
        season: 2026,
        week: 9,
        opponent: { name: "Rival", starters: { QB: [g("18")], RB: [g("13"), g("14")], WR: [g("02"), g("15")], TE: [null], FLEX: [g("03")] }, others: [] },
        confirmedEmpty: { mine: [], theirs: ["TE:0"] },
        countZero: [g("16"), g("04"), g("17"), g("13"), g("14"), g("15"), g("03")],
        finals: {},
        marks: {},
        rev: 1,
        updatedAt: "2026-08-21T00:00:00Z",
      },
    ],
  });
}

mkdirSync(outDir, { recursive: true });
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const report = [];
const errors = [];

async function measure(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const overflow = doc.scrollWidth - doc.clientWidth;
    const root = document.querySelector("section.wmm");
    const bounds = root?.getBoundingClientRect();
    const clipped = [];
    if (root && bounds) {
      for (const node of root.querySelectorAll(
        ".wmm-slot, .wmm-run-actions > *, .wmm-headline, .wmm-chart, .wmm-totals, .wmm-change, .wmm-yolo-card, .wmm-funnel, .wmm-legend, .notice",
      )) {
        const rect = node.getBoundingClientRect();
        if (rect.width === 0) continue;
        if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1) {
          clipped.push(`${node.className} [${Math.round(rect.left)}, ${Math.round(rect.right)}]`);
        }
      }
    }
    const truncated = [];
    for (const node of document.querySelectorAll(".wmm-headline *, .wmm-totals *, .wmm-quantiles, .wmm-evidence dd")) {
      if (getComputedStyle(node).textOverflow === "ellipsis" && node.scrollWidth > node.clientWidth + 1) truncated.push(node.textContent);
    }
    const dialog = document.querySelector("dialog[open]");
    let dialogFits = null;
    if (dialog) {
      const box = dialog.getBoundingClientRect();
      dialogFits = box.left >= 0 && box.right <= window.innerWidth + 1 && box.top >= 0 && box.bottom <= window.innerHeight + 1;
    }
    const figure = document.querySelector(".wmm-chart");
    const plot = document.querySelector(".wmm-chart svg");
    let chartFits = null;
    if (figure && plot) {
      const f = figure.getBoundingClientRect();
      const p = plot.getBoundingClientRect();
      chartFits = p.left >= f.left - 1 && p.right <= f.right + 1;
    }
    return { overflow, clipped: clipped.slice(0, 10), truncated: truncated.slice(0, 10), dialogFits, chartFits };
  });
}

async function openPage(width, height, clock) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  await context.addInitScript(
    ([leaguesKey, leagues, matchupsKey, matchups]) => {
      if (window.sessionStorage.getItem("seeded") === null) {
        window.localStorage.setItem(leaguesKey, leagues);
        window.localStorage.setItem(matchupsKey, matchups);
        window.sessionStorage.setItem("seeded", "1");
      }
    },
    [`jeisey-tiers:my-leagues@${PREFIX}`, leaguesDocument(), `jeisey-tiers:win-my-matchup@${PREFIX}`, matchupDocument()],
  );
  const page = await context.newPage();
  await page.clock.setFixedTime(clock);
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`${String(width)}x${String(height)}: ${message.text()}`);
  });
  await stubPortraits(page);
  await page.goto(`${BASE}${PREFIX}?view=myleagues&panel=wmm`, { waitUntil: "networkidle" });
  await page.waitForSelector(".wmm-run", { timeout: 15_000 });
  return { context, page };
}

async function shot(page, screen, tag, wantFull) {
  // A short screen is about what fits in it: those are viewport images only.
  const fullPage = wantFull && !SHORT.has(tag);
  // A full-page image paints the sticky header where the page is scrolled to: start at the top.
  if (fullPage) await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(250);
  report.push({ screen, size: tag, ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/${screen}-${tag}.png`, fullPage });
}

for (const [width, height] of SCREENS) {
  const tag = `${String(width)}x${String(height)}`;
  const { context, page } = await openPage(width, height, FRESH);

  // 1. Ready: both lineups, the readiness line, Simulate — nothing has run.
  await shot(page, "01-ready", tag, true);

  // 2. The opponent picker for an open slot.
  await page.getByRole("button", { name: /^Change the opponent's QB/ }).click();
  await page.getByRole("dialog").getByRole("combobox").fill("a");
  await page.waitForTimeout(200);
  await shot(page, "02-opponent-picker", tag, false);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");

  // 3. The result: headline, margin chart, totals, slot groups.
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await page.waitForSelector(".wmm-group-table");
  // What the reader sees where they pressed Simulate, then the whole page.
  await shot(page, "03-result-in-view", tag, false);
  await shot(page, "03-result", tag, true);

  // 4. YOLO on, changes and pickups evaluated, a pickup previewed over the baseline.
  await page.getByRole("checkbox", { name: "YOLO" }).check();
  await page.getByRole("button", { name: "Evaluate changes and pickups" }).click();
  await page.waitForSelector(".wmm-changes");
  const preview = page.getByRole("list", { name: "Potential pickups" }).getByRole("button", { name: "Preview" }).first();
  if ((await preview.count()) > 0) {
    await preview.click();
    await page.waitForSelector(".wmm-legend[data-side=overlay]");
  }
  await shot(page, "04-changes-yolo-preview", tag, true);

  // 5. The pickup confirmation: availability confirmed by the reader, nothing applied yet.
  const add = page.getByRole("button", { name: "Add to my roster…" }).first();
  if ((await add.count()) > 0) {
    await add.click();
    await page.waitForSelector("dialog[open]");
    await shot(page, "05-pickup-confirm", tag, false);
    await page.keyboard.press("Escape");
  }
  await context.close();

  // 6. Sunday afternoon: two starters kicked off, the finals scenario with one final entered.
  if (width === 390 || width === 1440) {
    const sunday = await openPage(width, height, SUNDAY);
    const finals = sunday.page.getByRole("radio", { name: /With final scores/ });
    if ((await finals.count()) > 0) {
      await finals.click();
      const input = sunday.page.locator(".wmm-finals input").first();
      if ((await input.count()) > 0) {
        await input.fill("17.4");
        await sunday.page.getByRole("button", { name: /^Save final for/ }).first().click();
      }
    }
    await shot(sunday.page, "06-sunday-finals", tag, true);
    await sunday.context.close();
  }
}

await browser.close();
writeFileSync(`${outDir}/measurements.json`, `${JSON.stringify({ prefix: PREFIX, report, consoleErrors: errors }, null, 1)}\n`);
const bad = report.filter(
  (entry) => entry.overflow > 1 || entry.clipped.length > 0 || entry.truncated.length > 0 || entry.dialogFits === false || entry.chartFits === false,
);
console.log(JSON.stringify({ outDir, screens: report.length, problems: bad, consoleErrors: errors }, null, 1));
process.exitCode = bad.length === 0 && errors.length === 0 ? 0 : 1;
