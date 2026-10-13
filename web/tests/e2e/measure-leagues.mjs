/**
 * My Leagues' interaction cost and memory (ADR-106), on a production-sized board in a
 * mobile-like browser: a Pixel-7 viewport with the CPU throttled 4× through the DevTools
 * protocol, as `measure-trade.mjs` measures the Trade tab.
 *
 * Three saved leagues on three different presets, each a full 16-player roster drawn from the
 * production-shaped board (`production-board.mjs`). It records:
 *
 * - **optimize** — Auto Start/Sit alone, the `leagues-optimize` performance entries;
 * - **mode** — a Median/Floor/Ceiling click until the new proposal has painted;
 * - **edit** — a roster edit through the slot dialog (pick a player) until it has painted;
 * - **search** — a keystroke in the slot picker until its suggestions have painted;
 * - **improve** — Improve's run (`leagues-improve`) and the click-to-results time;
 * - **rising** — Rising Stars turned on (first with its files fetched, then held) and off;
 * - **switch** — a league switch until the workspace shows that league, first and repeated;
 * - **heap** — JS heap after garbage collection, across repeated three-league cycles, so
 *   growth from retained indexes or results would show.
 *
 * Targets: 200 ms for every click or keystroke inside a league (the Trade tab's). A league
 * switch changes the scoring and size in force and so replaces every number on the page: its
 * median must meet the same 200 ms, and its worst of the repeated switches 400 ms, since one
 * slow frame in a dozen is this container's noise as often as the app's (the Start/Sit tab's
 * own scoring control takes 320–380 ms on this board and profile, and the ROS board's takes
 * seconds, before and after ADR-106). Improve's bounded search: 1,000 ms (it shows a
 * "Searching…" status first). Heap: no growth across repeated cycles beyond 2 MB.
 *
 *   npm run e2e:size-model
 *   node web/tests/e2e/measure-leagues.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--throttle 4] [--json leagues-perf.json]
 */

import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium, devices } from "@playwright/test";

import { makeProductionShaped } from "./production-board.mjs";
import { createStaticServer } from "./static-server.mjs";

const args = { dist: "web/dist-size-model", basePath: "/jeisey-tiers/", throttle: 4, json: null, port: 4192, cycles: 5 };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i += 1) {
  const flag = argv[i];
  const value = argv[++i];
  if (flag === "--dist") args.dist = value;
  else if (flag === "--base-path") args.basePath = value.endsWith("/") ? value : `${value}/`;
  else if (flag === "--throttle") args.throttle = Number(value);
  else if (flag === "--json") args.json = value;
  else if (flag === "--port") args.port = Number(value);
  else if (flag === "--cycles") args.cycles = Number(value);
  else throw new Error(`unknown option ${flag}`);
}

const TARGET_MS = 200;
const SWITCH_WORST_MS = 400;
const IMPROVE_TARGET_MS = 1000;
const HEAP_GROWTH_LIMIT = 2_000_000;
const repo = resolve(new URL("../../..", import.meta.url).pathname);
const work = mkdtempSync(join(tmpdir(), "leagues-perf-"));
const dist = join(work, "dist");
cpSync(resolve(args.dist), dist, { recursive: true });
makeProductionShaped(dist, repo);

const ros = JSON.parse(readFileSync(`${dist}/data/ros_tiers.json`, "utf-8")).records;
const COUNTS = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 5, IR: 2 };

/** A plausible full roster from one block: starters from the top, bench and IR deeper. */
function rosterFor(leaguePreset, scoring, offset) {
  const rows = ros
    .filter((r) => r.league_preset_id === leaguePreset && r.scoring_preset === scoring)
    .sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
  const by = (position) => rows.filter((r) => r.position === position).map((r) => r.player_id);
  const qb = by("QB");
  const rb = by("RB");
  const wr = by("WR");
  const te = by("TE");
  return {
    QB: [qb[offset]],
    RB: [rb[offset], rb[offset + 12]],
    WR: [wr[offset], wr[offset + 12]],
    TE: [te[offset]],
    FLEX: [rb[offset + 24]],
    BN: [qb[offset + 12], rb[offset + 30], wr[offset + 24], wr[offset + 30], te[offset + 12]],
    IR: [rb[offset + 40], null],
  };
}

const leagues = [
  { id: "lg-perf0001", name: "Office", scoring: "ppr", teams: 12, preset: ["redraft-12", "PPR"] },
  { id: "lg-perf0002", name: "Family", scoring: "half", teams: 10, preset: ["redraft-10", "HALF"] },
  { id: "lg-perf0003", name: "Friends", scoring: "std", teams: 14, preset: ["redraft-14", "STD"] },
].map((league, index) => ({
  id: league.id,
  name: league.name,
  season: 2026,
  scoring: league.scoring,
  teams: league.teams,
  slots: COUNTS,
  roster: rosterFor(league.preset[0], league.preset[1], index * 2),
  prefs: { risingStars: false, mode: "q50" },
  rev: 1,
  updatedAt: "2026-10-13T00:00:00Z",
}));
const KEY = `jeisey-tiers:my-leagues@${args.basePath}`;
const doc = JSON.stringify({ format: "jeisey-tiers.my-leagues", version: 1, revision: 1, activeId: leagues[0].id, leagues });

const server = createStaticServer({ roots: [{ base: args.basePath, dir: dist }] });
await new Promise((ok) => server.listen(args.port, ok));
const site = `http://localhost:${String(args.port)}${args.basePath}`;
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const context = await browser.newContext({ ...devices["Pixel 7"] });
await context.addInitScript(
  ([key, value]) => {
    if (window.sessionStorage.getItem("seeded") === null) {
      window.localStorage.setItem(key, value);
      window.sessionStorage.setItem("seeded", "1");
    }
  },
  [KEY, doc],
);
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send("Emulation.setCPUThrottlingRate", { rate: args.throttle });
await cdp.send("HeapProfiler.enable");

/** Click, then wait until `ready` holds and two frames have painted. */
async function timed(selector, readyText) {
  return page.evaluate(
    async ([target, text]) => {
      const element = document.querySelector(target);
      if (element === null) return null;
      const start = performance.now();
      element.click();
      for (let i = 0; i < 400; i += 1) {
        if (text === null || (document.querySelector("section.leagues")?.textContent ?? "").includes(text)) break;
        await new Promise((ok) => setTimeout(ok, 5));
      }
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
      return performance.now() - start;
    },
    [selector, readyText],
  );
}

async function entries(name) {
  return page.evaluate((entry) => performance.getEntriesByName(entry).map((e) => e.duration), name);
}

async function heap() {
  await cdp.send("HeapProfiler.collectGarbage");
  const usage = await cdp.send("Runtime.getHeapUsage");
  return usage.usedSize;
}

const result = {};
try {
  await page.goto(site, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /Rest of season/ }).first().waitFor();
  // Opening the workspace after the default view: code, stylesheet, the week's files.
  let start = Date.now();
  await page.getByRole("tab", { name: "My Leagues" }).click();
  await page.locator(".lg-auto").waitFor();
  result.openMs = Date.now() - start;

  result.optimizeMs = (await entries("leagues-optimize")).map(Math.round);
  result.modeClickMs = Math.round(
    Math.max(
      (await timed('[role="radio"][aria-label^="Floor"]', "individual floors")) ?? 0,
      (await timed('[role="radio"][aria-label^="Ceiling"]', "individual ceilings")) ?? 0,
      (await timed('[role="radio"][aria-label^="Median"]', "individual medians")) ?? 0,
    ),
  );

  // A keystroke in the picker, and a pick that edits the roster.
  await page.getByRole("button", { name: /^Add a player to IR/ }).first().click();
  const box = page.getByRole("dialog").getByRole("combobox");
  await box.focus();
  result.searchKeyMs = Math.round(
    await page.evaluate(async () => {
      const input = document.querySelector('dialog[open] [role="combobox"]');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      const start = performance.now();
      setter.call(input, "a");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      for (let i = 0; i < 200 && document.querySelector('dialog[open] [role="option"]') === null; i += 1) {
        await new Promise((ok) => setTimeout(ok, 2));
      }
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
      return performance.now() - start;
    }),
  );
  result.editMs = Math.round(
    await page.evaluate(async () => {
      const option = document.querySelector('dialog[open] [role="option"]');
      const start = performance.now();
      option.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
      for (let i = 0; i < 400 && document.querySelector("dialog[open]") !== null; i += 1) {
        await new Promise((ok) => setTimeout(ok, 2));
      }
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
      return performance.now() - start;
    }),
  );

  // Improve: lazy chunk, bounded search, results.
  start = Date.now();
  await page.getByRole("button", { name: "Find upgrades" }).click();
  await page.getByRole("region", { name: "Upgrade ideas" }).waitFor({ timeout: 30_000 });
  result.improveClickMs = Date.now() - start;
  result.improveRunMs = (await entries("leagues-improve")).map(Math.round);
  result.improveFoot = (await page.locator(".lg-improve-foot").textContent())?.replace(/\s+/g, " ").trim() ?? null;

  // Rising Stars on (reported: the first time includes fetching the Opportunity evidence), then
  // off and on again with the files held, which is the selection and its lists alone.
  const risingMs = async () =>
    Math.round(
      await page.evaluate(async () => {
        const box = [...document.querySelectorAll('input[type="checkbox"]')].find((node) =>
          (node.closest("label")?.textContent ?? "").includes("Rising Stars"),
        );
        const begin = performance.now();
        box.click();
        const done = () => {
          const lists = [...document.querySelectorAll(".lg-rising")];
          return box.checked
            ? lists.length > 0 && lists.every((list) => !(list.textContent ?? "").includes("Loading"))
            : lists.length === 0;
        };
        for (let i = 0; i < 4000 && !done(); i += 1) await new Promise((ok) => setTimeout(ok, 2));
        await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
        return performance.now() - begin;
      }),
    );
  result.risingFirstOnMs = await risingMs();
  result.risingOffMs = await risingMs();
  result.risingOnMs = await risingMs();

  // Three-league switching: the first visit to each preset fetches its block; every later
  // switch reuses immutable files and must not grow the heap.
  const switchMs = [];
  const heaps = [];
  for (let cycle = 0; cycle < args.cycles; cycle += 1) {
    for (const league of [leagues[1], leagues[2], leagues[0]]) {
      const label = `${String(league.teams)}-team ${league.scoring === "ppr" ? "PPR" : league.scoring === "half" ? "Half PPR" : "Standard"}`;
      // Timed inside the page, click to painted workspace, so the protocol's round trips under
      // a throttled CPU are not counted as the app's.
      const ms = await page.evaluate(
        async ([name, text]) => {
          const option = [...document.querySelectorAll('.lg-switch-option[role="radio"]')].find((node) =>
            (node.textContent ?? "").includes(name),
          );
          if (option === undefined) return null;
          const begin = performance.now();
          option.click();
          const ready = () =>
            document.querySelector(".lg-preset strong")?.textContent === text && document.querySelector(".lg-auto") !== null;
          for (let i = 0; i < 2000 && !ready(); i += 1) await new Promise((ok) => setTimeout(ok, 2));
          await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
          return ready() ? performance.now() - begin : null;
        },
        [league.name, label],
      );
      if (ms === null) throw new Error(`switching to ${league.name} did not show ${label}`);
      switchMs.push({ cycle, league: league.name, ms: Math.round(ms) });
    }
    heaps.push(await heap());
  }
  result.switchFirstMs = switchMs.filter((entry) => entry.cycle === 0).map((entry) => entry.ms);
  result.switchRepeatMs = switchMs.filter((entry) => entry.cycle > 0).map((entry) => `${entry.league} ${String(entry.ms)}`);
  const repeats = switchMs.filter((entry) => entry.cycle > 0).map((entry) => entry.ms).sort((a, b) => a - b);
  result.switchRepeatMedianMs = repeats[Math.floor(repeats.length / 2)];
  result.switchRepeatMaxMs = repeats.at(-1);
  result.heapBytes = heaps;
  result.heapGrowthAfterFirstCycle = heaps.length > 1 ? heaps.at(-1) - heaps[1] : 0;
  result.optimizeMsAll = (await entries("leagues-optimize")).map(Math.round);
} finally {
  await browser.close();
  server.close();
  rmSync(work, { recursive: true, force: true });
}

const summary = {
  site: args.dist,
  throttle: `${String(args.throttle)}x CPU, Pixel 7 viewport`,
  leagues: leagues.map((league) => `${league.name}: ${league.scoring} ${String(league.teams)}, 16 players`),
  targets: {
    clickMs: TARGET_MS,
    switchMedianMs: TARGET_MS,
    switchWorstMs: SWITCH_WORST_MS,
    improveMs: IMPROVE_TARGET_MS,
    heapGrowthBytes: HEAP_GROWTH_LIMIT,
  },
  worst: {
    optimizeMs: Math.max(...result.optimizeMsAll),
    modeClickMs: result.modeClickMs,
    searchKeyMs: result.searchKeyMs,
    editMs: result.editMs,
    improveRunMs: Math.max(...result.improveRunMs),
    risingToggleMs: Math.max(result.risingOffMs, result.risingOnMs),
    switchRepeatMedianMs: result.switchRepeatMedianMs,
    switchRepeatMaxMs: result.switchRepeatMaxMs,
  },
  ...result,
};
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(summary, null, 1)}\n`);
console.log(JSON.stringify(summary, null, 1));
const over =
  summary.worst.optimizeMs > TARGET_MS ||
  summary.worst.modeClickMs > TARGET_MS ||
  summary.worst.searchKeyMs > TARGET_MS ||
  summary.worst.editMs > TARGET_MS ||
  summary.worst.risingToggleMs > TARGET_MS ||
  summary.worst.switchRepeatMedianMs > TARGET_MS ||
  summary.worst.switchRepeatMaxMs > SWITCH_WORST_MS ||
  summary.worst.improveRunMs > IMPROVE_TARGET_MS ||
  result.heapGrowthAfterFirstCycle > HEAP_GROWTH_LIMIT;
process.exitCode = over ? 1 : 0;
