/**
 * The Skill Tree's interaction cost and memory (ADR-107), on the production-sized size model in
 * a mobile-like browser: a Pixel-7 viewport with the CPU throttled 4× through the DevTools
 * protocol, as `measure-leagues.mjs` measures My Leagues.
 *
 * Two kinds of number, both from real taps:
 *
 * - **interaction latency** — the browser's own Event Timing entry for the tap (input to the
 *   next paint, the INP measure), for the card's own tabs (the baseline: what any change inside
 *   this dialog costs with ≈ 37,000 DOM nodes behind it), the Skill Tree tab and a node's detail;
 * - **time to tree** — from the tap until the tree is on screen and two frames have painted:
 *   **cold** (the lazy chunk, its stylesheet, the position's definitions and the player's bucket
 *   shard, fetched and decoded, "Loading the skill tree…" on screen meanwhile), **repeat** (the
 *   same player again after another tab: everything in memory) and **switch** (another player's
 *   card, then his tree: a new shard, and new definitions when the position changes);
 * - **heap** — JS heap after garbage collection across repeated cycles of six players' trees.
 *
 * Targets: every interaction's latency within 200 ms (a "good" INP) or, if the card's own tabs
 * already exceed that on this profile, no slower than the slowest of their (non-first) switches
 * in the same run. A switch's activation
 * is the first tap in a freshly opened card. That tap used to cost far more than any later one,
 * whichever tab it hit, until ADR-109 dropped the opening tap's stale caret. It is still held to
 * the like-for-like first tap on one of the card's own tabs, and its time to tree (median) to that
 * first tap plus 500 ms for the tree's own
 * fetch, decode and render. Time to tree 1,500 ms cold and 500 ms for a repeat; heap growth under
 * 1 MB across cycles.
 *
 *   npm run e2e:size-model
 *   node web/tests/e2e/measure-skilltree.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--throttle 4] [--json skilltree-perf.json]
 */

import { cpSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium, devices } from "@playwright/test";

import { createStaticServer } from "./static-server.mjs";

const args = { dist: "web/dist-size-model", basePath: "/jeisey-tiers/", throttle: 4, json: null, port: 4193, cycles: 4 };
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

const TARGETS = {
  interactionMs: 200,
  /** A fresh card's first tap: no slower than 1.25× the first tap on one of its own tabs. */
  interactionVsBaseline: 1.25,
  coldMs: 1500,
  /** Over a fresh card's first tap: the tree's own fetch, decode and render. */
  switchTreeOverFirstTapMs: 500,
  repeatTreeMs: 500,
  heapGrowthBytes: 1_000_000,
};
const work = mkdtempSync(join(tmpdir(), "skilltree-perf-"));
const dist = join(work, "dist");
cpSync(resolve(args.dist), dist, { recursive: true });

const server = createStaticServer({ roots: [{ base: args.basePath, dir: dist }] });
await new Promise((ok) => server.listen(args.port, ok));
const site = `http://localhost:${String(args.port)}${args.basePath}`;
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch({
  args: ["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE localhost"],
  ...(executablePath ? { executablePath } : {}),
});
const context = await browser.newContext({ ...devices["Pixel 7"] });
// Every interaction's Event Timing entry, from the first script on.
await context.addInitScript(() => {
  window.__events = [];
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      window.__events.push({ name: entry.name, start: entry.startTime, duration: entry.duration });
    }
  }).observe({ type: "event", durationThreshold: 16, buffered: true });
});
const page = await context.newPage();
const cdp = await context.newCDPSession(page);

async function settle() {
  await page.evaluate(() => new Promise((ok) => requestIdleCallback(() => ok(undefined), { timeout: 2000 })));
  await page.waitForTimeout(250);
}

/**
 * Tap `locator`, wait until `ready` (a selector) is on screen and two frames have painted, then
 * return the time to that point and the interaction's Event Timing latency (16 ms resolution:
 * below the threshold the browser records nothing, reported as 16).
 *
 * Nothing of Playwright's runs on the page's main thread inside the timed window: the target is
 * resolved and scrolled into view first, the tap is a raw touch at its centre, and readiness is a
 * plain `querySelector` checked once a frame. (Its role engine walks every node on each query —
 * on this board, under throttling, that was most of a second inside the measurement.)
 */
async function tap(locator, ready) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (box === null) throw new Error("tap target has no box");
  await settle();
  const before = await page.evaluate(() => [performance.now(), window.__events.length]);
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  const elapsed = await page.evaluate(
    async ([start, selector]) => {
      for (let frame = 0; frame < 600 && document.querySelector(selector) === null; frame += 1) {
        await new Promise((ok) => requestAnimationFrame(ok));
      }
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
      return document.querySelector(selector) === null ? null : performance.now() - start;
    },
    [before[0], ready],
  );
  await page.waitForTimeout(200);
  const latency = await page.evaluate(
    ([start, count]) =>
      Math.max(
        16,
        ...window.__events
          .slice(count)
          .filter((entry) => entry.start >= start - 1 && ["pointerdown", "pointerup", "click"].includes(entry.name))
          .map((entry) => entry.duration),
      ),
    before,
  );
  return { elapsed, latency };
}

async function heap() {
  await cdp.send("HeapProfiler.collectGarbage");
  const usage = await cdp.send("Runtime.getHeapUsage");
  return usage.usedSize;
}

const dialog = page.getByRole("dialog");
const tab = (name) => dialog.getByRole("tab", { name, exact: true });
// The phone board's rows are themselves the buttons that open a card.
const rows = page.locator(".board-row[data-player]");
async function openCard(index) {
  await rows.nth(index).tap();
  await dialog.getByRole("tablist").waitFor();
}
async function closeCard() {
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
}

const TREE = "dialog[open] .st-grid";
const SELECTED = 'dialog[open] [role="tab"][aria-selected="true"]';
const DETAIL = 'dialog[open] .st-detail[role="region"]';
const result = { baselineTabLatencyMs: [], nodeLatencyMs: [], switchTreeMs: [], switchLatencyMs: [] };
const failures = [];
try {
  await page.goto(site, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /Rest of season/ }).first().waitFor();
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: args.throttle });

  await openCard(0);
  for (let round = 0; round < 2; round += 1) {
    for (const name of ["Rest of season", "This week", "In-season usage", "Current status", "Intrinsic value"]) {
      result.baselineTabLatencyMs.push((await tap(tab(name), SELECTED)).latency);
    }
  }
  const cold = await tap(tab("Skill tree"), TREE);
  result.coldMs = cold.elapsed;
  result.coldLatencyMs = cold.latency;
  for (const index of [0, 3, 6]) {
    const node = dialog.locator(".st-grid .st-node").nth(index);
    result.nodeLatencyMs.push((await tap(node, DETAIL)).latency);
    await node.tap();
  }
  await tap(tab("Intrinsic value"), SELECTED);
  const repeat = await tap(tab("Skill tree"), TREE);
  result.repeatTreeMs = repeat.elapsed;
  result.repeatLatencyMs = repeat.latency;
  await closeCard();

  for (const index of [1, 2, 3, 4, 5]) {
    await openCard(index);
    const step = await tap(tab("Skill tree"), TREE);
    result.switchTreeMs.push(step.elapsed);
    result.switchLatencyMs.push(step.latency);
    await closeCard();
  }
  // The like-for-like baseline for a switch: the first tap on a freshly opened card, on one of
  // the card's own tabs (other players, so nothing of theirs is warm).
  result.firstTapBaselineLatencyMs = [];
  for (const index of [6, 7, 8, 9, 10]) {
    await openCard(index);
    result.firstTapBaselineLatencyMs.push((await tap(tab("Rest of season"), SELECTED)).latency);
    await closeCard();
  }

  // The heap profiler slows every allocation while enabled, so it is on only for this phase.
  await cdp.send("HeapProfiler.enable");
  const heaps = [await heap()];
  for (let cycle = 0; cycle < args.cycles; cycle += 1) {
    for (const index of [0, 1, 2, 3, 4, 5]) {
      await openCard(index);
      await tab("Skill tree").tap();
      await page.locator(TREE).waitFor();
      await dialog.locator(".st-grid .st-node").nth(1).tap();
      await page.locator(DETAIL).waitFor();
      await closeCard();
    }
    heaps.push(await heap());
  }
  result.heapBytes = heaps;
  result.heapGrowthAfterFirstCycle = heaps.length > 2 ? heaps.at(-1) - heaps[1] : 0;
} catch (error) {
  failures.push(`could not run: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
} finally {
  await browser.close();
  server.close();
  rmSync(work, { recursive: true, force: true });
}

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length === 0 ? Number.POSITIVE_INFINITY : sorted[Math.floor(sorted.length / 2)];
};
// The first tap in a card is excluded from the tab baseline: it is the fresh-card cost below.
result.baselineMedianLatencyMs = median(result.baselineTabLatencyMs.slice(1));
// No tap in the tree slower than a "good" INP, or than the card's own slowest tab switch in the
// same run, whichever is larger: the tree may not be the slowest thing on the card.
result.interactionLimitMs = Math.max(TARGETS.interactionMs, ...result.baselineTabLatencyMs.slice(1));
result.firstTapBaselineMedianMs = median(result.firstTapBaselineLatencyMs ?? []);
result.switchLimitMs = Math.max(TARGETS.interactionMs, result.firstTapBaselineMedianMs * TARGETS.interactionVsBaseline);
const latencies = [
  ["cold activation", result.coldLatencyMs, result.interactionLimitMs],
  ["repeat activation", result.repeatLatencyMs, result.interactionLimitMs],
  ["a node", median(result.nodeLatencyMs), result.interactionLimitMs],
  ["a switch's activation (a fresh card's first tap)", median(result.switchLatencyMs), result.switchLimitMs],
];
for (const [what, value, limit] of latencies) {
  if ((value ?? Infinity) > limit) failures.push(`${what}: ${String(value)} ms latency (limit ${String(Math.round(limit))})`);
}
if ((result.coldMs ?? Infinity) > TARGETS.coldMs) failures.push(`cold time to tree ${String(result.coldMs)} ms`);
if ((result.repeatTreeMs ?? Infinity) > TARGETS.repeatTreeMs) failures.push(`repeat time to tree ${String(result.repeatTreeMs)} ms`);
result.switchTreeLimitMs = result.firstTapBaselineMedianMs + TARGETS.switchTreeOverFirstTapMs;
if (median(result.switchTreeMs) > result.switchTreeLimitMs) {
  failures.push(`a switch's time to tree ${String(median(result.switchTreeMs))} ms (median; limit ${String(Math.round(result.switchTreeLimitMs))})`);
}
if ((result.heapGrowthAfterFirstCycle ?? 0) > TARGETS.heapGrowthBytes) failures.push(`heap grew ${String(result.heapGrowthAfterFirstCycle)} B`);

const round = (value) => (typeof value === "number" ? Math.round(value) : value);
const report = {
  dist: args.dist,
  throttle: args.throttle,
  targets: TARGETS,
  result: Object.fromEntries(Object.entries(result).map(([key, value]) => [key, Array.isArray(value) ? value.map(round) : round(value)])),
  failures,
};
console.log(JSON.stringify(report, null, 1));
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(report, null, 1)}\n`);
process.exitCode = failures.length === 0 ? 0 : 1;
