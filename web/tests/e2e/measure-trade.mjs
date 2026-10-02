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
 * **The board.** The size model (ADR-098) is built to have production's *bytes*, not its
 * values: its quantiles are drawn independently and often cross, so many of its rows are
 * correctly unpriced. This script therefore copies the build and rewrites every `ros_tiers`
 * row's value fields into a production-shaped board — 500 rows a block, expected value
 * falling from ~150 to ~−15 with ~170 above replacement, monotone right-skewed quantiles, 6%
 * long absences and 4% reserve codes — then re-packages it with the production packager.
 *
 *   npm run e2e:size-model
 *   node web/tests/e2e/measure-trade.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--throttle 4] [--json trade-perf.json]
 */

import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium, devices } from "@playwright/test";

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

/** Deterministic jitter in [-0.5, 0.5). */
function jitter(seed) {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x) - 0.5;
}

function realistic(record, index, factor) {
  const mean = (170 * Math.exp(-index / 70) - 15 + 4 * jitter(index + 1)) * factor;
  const sigma = 0.35 * Math.abs(mean) + 12;
  const round = (value) => Number(value.toFixed(4));
  return {
    ...record,
    ros_expected_vorp: round(mean),
    ros_vorp_p10: round(mean - 1.35 * sigma),
    ros_vorp_p25: round(mean - 0.67 * sigma),
    ros_vorp_p50: round(mean - 0.05 * sigma),
    ros_vorp_p75: round(mean + 0.65 * sigma),
    ros_vorp_p90: round(mean + 1.3 * sigma),
    ros_expected_points: round(mean + (record.position === "QB" ? 150 : 100)),
    long_absence: index % 17 === 5,
    current_status: index % 23 === 7 ? "RES" : null,
  };
}

{
  const path = join(dist, "data", "ros_tiers.json");
  const envelope = JSON.parse(readFileSync(path, "utf-8"));
  const blocks = new Map();
  for (const record of envelope.records) {
    const key = `${record.league_preset_id}|${record.scoring_preset}`;
    if (!blocks.has(key)) blocks.set(key, []);
    blocks.get(key).push(record);
  }
  const out = [];
  let blockIndex = 0;
  for (const rows of blocks.values()) {
    rows.sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
    const factor = 1 + 0.03 * blockIndex;
    rows.forEach((record, index) => out.push(realistic(record, index, factor)));
    blockIndex += 1;
  }
  envelope.records = out;
  writeFileSync(path, `${JSON.stringify(envelope)}\n`);
  execFileSync("uv", ["run", "--frozen", "ffdraft", "package-site-data", join(dist, "data")], {
    cwd: repo,
    stdio: ["ignore", "ignore", "inherit"],
  });
}

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
