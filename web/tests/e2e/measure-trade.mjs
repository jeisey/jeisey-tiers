/**
 * The Trade tab's interaction cost (ADR-100), on a production-sized board in a mobile-like
 * browser: a Pixel-7 viewport with the CPU throttled 4× through the DevTools protocol.
 *
 * For each scenario it records two numbers:
 *
 * - **search** — the engine alone, the `trade-search` performance entry the view writes;
 * - **interaction** — a control click until the page has painted the new results (click,
 *   then two animation frames), which includes React's render of the tab.
 *
 * Swap and More targets are measured the same way. The target is 200 ms for both.
 *
 * **The board.** A copy of the size model with its rest-of-season values made
 * production-shaped (`production-board.mjs`, shared with `measure-leagues.mjs`).
 *
 *   npm run e2e:size-model
 *   node web/tests/e2e/measure-trade.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--throttle 4] [--json trade-perf.json]
 */

import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium, devices } from "@playwright/test";

import { makeProductionShaped } from "./production-board.mjs";
import { createStaticServer } from "./static-server.mjs";

const args = { dist: "web/dist-size-model", basePath: "/jeisey-tiers/", throttle: 4, json: null, port: 4191 };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i += 1) {
  const flag = argv[i];
  const value = argv[++i];
  if (flag === "--dist") args.dist = value;
  else if (flag === "--base-path") args.basePath = value.endsWith("/") ? value : `${value}/`;
  else if (flag === "--throttle") args.throttle = Number(value);
  else if (flag === "--json") args.json = value;
  else if (flag === "--port") args.port = Number(value);
  else throw new Error(`unknown option ${flag}`);
}

const TARGET_MS = 200;
const repo = resolve(new URL("../../..", import.meta.url).pathname);
const work = mkdtempSync(join(tmpdir(), "trade-perf-"));
const dist = join(work, "dist");
cpSync(resolve(args.dist), dist, { recursive: true });

makeProductionShaped(dist, repo);

const records = JSON.parse(readFileSync(`${dist}/data/ros_tiers.json`, "utf-8")).records.filter(
  (r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR",
);
// Outgoing players across the value range: distinct values, best first.
const ladder = [...records]
  .filter((r) => r.ros_expected_vorp > 0)
  .sort((a, b) => b.ros_expected_vorp - a.ros_expected_vorp || a.player_id.localeCompare(b.player_id));
const pick = (fraction) => ladder[Math.min(ladder.length - 1, Math.floor(fraction * ladder.length))];
const short = (r) => r.player_id.replace(/^gsis:/, "");
const GIVES = {
  star: [pick(0)],
  starter: [pick(0.15)],
  depth: [pick(0.5)],
  "two starters": [pick(0.05), pick(0.25)],
  "three pieces": [pick(0.1), pick(0.3), pick(0.6)],
};

const server = createStaticServer({ roots: [{ base: args.basePath, dir: dist }] });
await new Promise((ok) => server.listen(args.port, ok));
const site = `http://localhost:${String(args.port)}${args.basePath}`;
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const context = await browser.newContext({ ...devices["Pixel 7"] });
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send("Emulation.setCPUThrottlingRate", { rate: args.throttle });

async function lastSearch() {
  return page.evaluate(() => {
    const entries = performance.getEntriesByName("trade-search");
    return entries.at(-1)?.duration ?? null;
  });
}

/** Click, then wait two frames: the time until the new results are on screen. */
async function timedClick(selector) {
  return page.evaluate(async (target) => {
    const element = document.querySelector(target);
    if (element === null) return null;
    const start = performance.now();
    element.click();
    await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    return performance.now() - start;
  }, selector);
}

const rows = [];
try {
  for (const [name, give] of Object.entries(GIVES)) {
    for (const get of [1, 2, 3]) {
      for (const range of [20, 50]) {
        await page.goto(`${site}?view=trade&give=${give.map(short).join(".")}&get=${String(get)}&range=${String(range)}`, {
          waitUntil: "networkidle",
        });
        await page.getByRole("heading", { name: "Trade targets" }).waitFor();
        const qualifying = (await page.locator(".trade-count").textContent().catch(() => null)) ?? "none";
        const load = await lastSearch();
        // A preset change re-runs the search through the same click path a reader uses.
        const ceilingClick = await timedClick('[role="radio"][aria-label="Highest ceiling"]');
        const ceilingSearch = await lastSearch();
        const floorClick = await timedClick('[role="radio"][aria-label="Highest floor"]');
        const swap = await timedClick(".trade-results .trade-swap:not([disabled])");
        const more = await timedClick(".trade-actions .button:not([disabled])");
        rows.push({
          give: name,
          get,
          range,
          qualifying: qualifying.split(" · ")[0],
          searchMs: load === null ? null : Math.round(load),
          ceilingSearchMs: ceilingSearch === null ? null : Math.round(ceilingSearch),
          presetClickMs: ceilingClick === null ? null : Math.round(Math.max(ceilingClick, floorClick ?? 0)),
          swapMs: swap === null ? null : Math.round(swap),
          moreMs: more === null ? null : Math.round(more),
        });
      }
    }
  }
} finally {
  await browser.close();
  server.close();
  rmSync(work, { recursive: true, force: true });
}

const worst = (key) => Math.max(...rows.map((row) => row[key] ?? 0));
const summary = {
  site: args.dist,
  board: `${String(records.length)} ROS rows (redraft-12 PPR), ${String(ladder.length)} with positive value, production-shaped values over the size model's rows`,
  throttle: `${String(args.throttle)}x CPU, Pixel 7 viewport`,
  targetMs: TARGET_MS,
  worst: {
    searchMs: Math.max(worst("searchMs"), worst("ceilingSearchMs")),
    presetClickMs: worst("presetClickMs"),
    swapMs: worst("swapMs"),
    moreMs: worst("moreMs"),
  },
  rows,
};
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(summary, null, 1)}\n`);
console.log(JSON.stringify(summary, null, 1));
const over = Object.values(summary.worst).some((ms) => ms > TARGET_MS);
process.exitCode = over ? 1 : 0;
