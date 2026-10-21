/**
 * The recent-weeks lens's interaction cost and memory (ADR-113), on the production-sized size
 * model in a mobile-like browser: a Pixel-7 viewport with the CPU throttled 4× through the
 * DevTools protocol, as `measure-skilltree.mjs` measures the Skill Tree.
 *
 * - **interaction latency** — the browser's Event Timing entry (input to next paint) for a tap on
 *   a window, beside the same measure for the board's own *Order by* control (the baseline: what
 *   any change of the board's selection already costs);
 * - **time to table** — from the tap until the table shows the chosen window and two frames have
 *   painted;
 * - **long tasks** — main-thread tasks over 50 ms during the window taps, against the baseline;
 * - **requests** — a window switch must fetch nothing (one cached slice serves every window);
 * - **heap** — JS heap after garbage collection across repeated cycles through every window.
 *
 * Targets: window latency no slower than 1.25× the slowest baseline tap (or within 200 ms); no
 * long task in a window tap beyond the baseline's own worst; 0 requests per switch; heap growth
 * under 1 MB across cycles.
 *
 *   npm run e2e:size-model
 *   node web/tests/e2e/measure-recent.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--throttle 4] [--cycles 4] [--json recent-perf.json]
 */

import { cpSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium, devices } from "@playwright/test";

import { createStaticServer } from "./static-server.mjs";

const args = { dist: "web/dist-size-model", basePath: "/jeisey-tiers/", throttle: 4, json: null, port: 4194, cycles: 4 };
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

const TARGETS = { interactionMs: 200, interactionVsBaseline: 1.25, heapGrowthBytes: 1_000_000, requestsPerSwitch: 0 };
const work = mkdtempSync(join(tmpdir(), "recent-perf-"));
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
await context.addInitScript(() => {
  window.__events = [];
  window.__long = [];
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) window.__events.push({ name: entry.name, start: entry.startTime, duration: entry.duration });
  }).observe({ type: "event", durationThreshold: 16, buffered: true });
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) window.__long.push({ start: entry.startTime, duration: entry.duration });
  }).observe({ type: "longtask", buffered: true });
});
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
let requests = 0;
page.on("request", (request) => {
  if (request.url().includes("/data/")) requests += 1;
});

async function settle() {
  await page.evaluate(() => new Promise((ok) => requestIdleCallback(() => ok(undefined), { timeout: 2000 })));
  await page.waitForTimeout(250);
}

/** Tap, wait until `ready()` holds in the page and two frames painted; latency and long tasks. */
async function tap(locator, ready) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (box === null) throw new Error("tap target has no box");
  await settle();
  const before = await page.evaluate(() => [performance.now(), window.__events.length, window.__long.length]);
  const fetched = requests;
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  const elapsed = await page.evaluate(
    async ([start, source]) => {
      const check = new Function(`return (${source})();`);
      for (let frame = 0; frame < 600 && !check(); frame += 1) await new Promise((ok) => requestAnimationFrame(ok));
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
      return check() ? performance.now() - start : null;
    },
    [before[0], ready],
  );
  await page.waitForTimeout(200);
  const [latency, longest] = await page.evaluate(
    ([start, count, longCount]) => [
      Math.max(
        16,
        ...window.__events
          .slice(count)
          .filter((entry) => entry.start >= start - 1 && ["pointerdown", "pointerup", "click"].includes(entry.name))
          .map((entry) => entry.duration),
      ),
      Math.max(0, ...window.__long.slice(longCount).map((entry) => entry.duration)),
    ],
    before,
  );
  return { elapsed, latency, longest, requests: requests - fetched };
}

async function heap() {
  await cdp.send("HeapProfiler.collectGarbage");
  return (await cdp.send("Runtime.getHeapUsage")).usedSize;
}

const lensRadio = (name) => page.getByRole("radiogroup", { name: "Recent weeks" }).getByRole("radio", { name });
const order = (name) => page.getByRole("radiogroup", { name: "Order by" }).getByRole("radio", { name, exact: true });
const showing = (label) =>
  label === null
    ? `() => document.querySelector("table.opp-sheet") !== null && document.querySelector("table.opp-sheet[data-recent]") === null`
    : `() => document.querySelector('th[data-col="recent_rank"] .th-sub')?.textContent === ${JSON.stringify(`Recent ${label}`)}`;
const checked = (name) =>
  `() => [...document.querySelectorAll('[role="radiogroup"] [role="radio"]')].some((r) => r.getAttribute("aria-checked") === "true" && r.textContent === ${JSON.stringify(name)})`;

const result = { baselineLatencyMs: [], baselineLongestMs: [], windowLatencyMs: [], windowElapsedMs: [], windowLongestMs: [], windowRequests: [], heapBytes: [] };
const failures = [];
try {
  await page.goto(`${site}?view=opportunity`, { waitUntil: "networkidle" });
  await page.getByRole("table", { name: /opportunity board/i }).waitFor();
  await page.getByRole("button", { name: /^Options/ }).tap();
  const meta = await page.evaluate(async () => {
    const manifest = await (await fetch("data/manifest.json")).json();
    return manifest.ros_build_metadata?.recent_form?.windows ?? null;
  });
  // A build without recent form (main, for the before figure) measures the baseline only.
  const label = (key) => {
    const w = meta[key];
    return w.first_week === w.last_week ? `W${w.last_week}` : `W${w.first_week}–${w.last_week}`;
  };
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: args.throttle });
  requests = 0;

  for (let round = 0; round < 2; round += 1) {
    for (const name of ["Adds", "ROS value"]) {
      const step = await tap(order(name), checked(name));
      result.baselineLatencyMs.push(step.latency);
      result.baselineLongestMs.push(step.longest);
    }
  }
  result.heapBytes.push(await heap());
  if (meta === null) throw new Error("baseline only: this build has no recent_form metadata");
  const sequence = [
    ["1", /^Last 1 completed/],
    ["6", /^Last 6 completed/],
    [null, /^Season to date/],
    ["2", /^Last 2 completed/],
    ["4", /^Last 4 completed/],
    ["3", /^Last 3 completed/],
  ];
  for (let cycle = 0; cycle < args.cycles; cycle += 1) {
    for (const [key, name] of sequence) {
      const step = await tap(lensRadio(name), showing(key === null ? null : label(key)));
      if (step.elapsed === null) failures.push(`window ${String(key)} never showed`);
      result.windowLatencyMs.push(step.latency);
      result.windowElapsedMs.push(step.elapsed);
      result.windowLongestMs.push(step.longest);
      result.windowRequests.push(step.requests);
    }
    result.heapBytes.push(await heap());
  }
  // The badge's dialog, on a badge the build actually gives (if any in this window).
  const badge = page.locator(".breakout-badge").first();
  if ((await badge.count()) > 0) {
    const step = await tap(badge, `() => document.querySelector("dialog[open] .breakout-explain") !== null`);
    result.badgeDialogLatencyMs = step.latency;
    result.badgeDialogMs = step.elapsed;
  }
} catch (error) {
  failures.push(error instanceof Error ? error.message.split("\n")[0] : String(error));
} finally {
  await browser.close();
  server.close();
  rmSync(work, { recursive: true, force: true });
}

const max = (values) => Math.max(0, ...values.filter((value) => typeof value === "number"));
const baseline = max(result.baselineLatencyMs);
const allowed = Math.max(TARGETS.interactionMs, baseline * TARGETS.interactionVsBaseline);
if (max(result.windowLatencyMs) > allowed) failures.push(`window tap latency ${String(max(result.windowLatencyMs))} ms > ${String(allowed)} ms`);
if (max(result.windowLongestMs) > Math.max(50, max(result.baselineLongestMs))) {
  failures.push(`a window tap ran a ${String(max(result.windowLongestMs))} ms task; the baseline's worst was ${String(max(result.baselineLongestMs))} ms`);
}
if (max(result.windowRequests) > TARGETS.requestsPerSwitch) failures.push(`a window switch made ${String(max(result.windowRequests))} data request(s)`);
const growth = (result.heapBytes.at(-1) ?? 0) - (result.heapBytes[1] ?? result.heapBytes[0] ?? 0);
result.heapGrowthBytes = growth;
if (growth > TARGETS.heapGrowthBytes) failures.push(`heap grew ${String(growth)} B across ${String(args.cycles)} cycles`);
const report = { throttle: args.throttle, cycles: args.cycles, targets: TARGETS, allowedLatencyMs: allowed, ...result, failures };
console.log(JSON.stringify(report, null, 1));
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(report, null, 1)}\n`);
process.exitCode = failures.length === 0 ? 0 : 1;
