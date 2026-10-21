/**
 * ADR-115's interactions, measured on the production-sized size model in a Pixel 7 viewport with
 * the CPU throttled through the DevTools protocol (as `measure-recent.mjs` measures ADR-113):
 *
 * - **bye filter** — Event Timing latency of the ROS and Start/Sit checkbox, beside the same
 *   board's Position control (the baseline: what any selection change already costs); requests on
 *   the first enable (ROS fetches the ~4 kB schedule slice once) and on every later toggle (0);
 * - **card cycles** — open a card, visit every tab, expand and collapse the header, close it;
 *   repeated, with the JS heap after garbage collection before and after;
 * - **filter cycles** — the bye filter on and off repeatedly, heap before and after.
 *
 * A build without the bye filter (main before ADR-115) reports the baseline and card cycles only.
 *
 *   npm run e2e:size-model
 *   node web/tests/e2e/measure-qol.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--throttle 4] [--cycles 6] [--json qol-perf.json]
 */

import { cpSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium, devices } from "@playwright/test";

import { createStaticServer } from "./static-server.mjs";

const args = { dist: "web/dist-size-model", basePath: "/jeisey-tiers/", throttle: 4, json: null, port: 4196, cycles: 6 };
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

const work = mkdtempSync(join(tmpdir(), "qol-perf-"));
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
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) window.__events.push({ name: entry.name, duration: entry.duration });
  }).observe({ type: "event", durationThreshold: 16, buffered: true });
});
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
let requests = 0;
page.on("request", (request) => {
  if (request.url().includes("/data/")) requests += 1;
});

async function settle() {
  await page.evaluate(() => new Promise((ok) => requestIdleCallback(() => ok(undefined), { timeout: 2000 })));
  await page.waitForTimeout(200);
}

async function heap() {
  await cdp.send("HeapProfiler.collectGarbage");
  await cdp.send("HeapProfiler.collectGarbage");
  const { usedSize } = await cdp.send("Runtime.getHeapUsage");
  return usedSize;
}

/** The slowest Event Timing entry for one interaction, in ms. */
async function latency(action) {
  await page.evaluate(() => {
    window.__events.length = 0;
  });
  await action();
  await settle();
  return page.evaluate(() => Math.max(0, ...window.__events.filter((e) => e.name === "click" || e.name === "pointerup").map((e) => e.duration)));
}

async function openSettings() {
  const toggle = page.getByRole("button", { name: /^Settings/ });
  if ((await toggle.count()) > 0 && (await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
}

await cdp.send("Emulation.setCPUThrottlingRate", { rate: args.throttle });
const result = { throttle: args.throttle, cycles: args.cycles, browser: browser.version() };

for (const view of ["ros", "startsit"]) {
  await page.goto(`${site}?view=${view}`, { waitUntil: "networkidle" });
  await settle();
  await openSettings();
  const position = page.getByRole("radiogroup", { name: "Position" });
  const baseline = [];
  for (let i = 0; i < 3; i += 1) {
    baseline.push(await latency(() => position.getByRole("radio", { name: "RB" }).click()));
    baseline.push(await latency(() => position.getByRole("radio", { name: "All positions" }).click()));
  }
  const entry = { baselineMaxMs: Math.max(...baseline), baselineMs: baseline };
  // The same cycle count through the existing control, so retained growth can be told apart
  // from what any selection change on this board already costs.
  const positionHeapBefore = await heap();
  const positionTrace = [];
  for (let i = 0; i < args.cycles; i += 1) {
    await position.getByRole("radio", { name: "RB" }).click();
    await settle();
    await position.getByRole("radio", { name: "All positions" }).click();
    await settle();
    positionTrace.push((await heap()) - positionHeapBefore);
  }
  entry.positionCycleHeapTrace = positionTrace;
  entry.positionCycleHeapGrowth = (await heap()) - positionHeapBefore;
  const bye = page.getByRole("checkbox", { name: /byes|bye-week/i });
  if ((await bye.count()) > 0) {
    const before = requests;
    const first = await latency(() => bye.click());
    entry.firstEnableRequests = requests - before;
    entry.firstEnableMs = first;
    const toggles = [];
    const steady = requests;
    const heapBefore = await heap();
    const heapTrace = [];
    for (let i = 0; i < args.cycles; i += 1) {
      toggles.push(await latency(() => bye.click()));
      toggles.push(await latency(() => bye.click()));
      heapTrace.push((await heap()) - heapBefore);
    }
    entry.filterCycleHeapTrace = heapTrace;
    entry.toggleMs = toggles;
    entry.toggleMaxMs = Math.max(...toggles);
    entry.laterToggleRequests = requests - steady;
    entry.filterCycleHeapGrowth = (await heap()) - heapBefore;
  }
  result[view] = entry;
}

// Card cycles on the ROS board: open, every tab, expand and collapse, close.
await page.goto(`${site}?view=ros`, { waitUntil: "networkidle" });
await settle();
const firstName = page.locator("table.sheet tbody tr[data-player] .player-cell button").first();
const cycleOnce = async () => {
  await firstName.click();
  const dialog = page.locator("dialog.player-detail[open]");
  await dialog.waitFor();
  const tabs = dialog.getByRole("tab");
  for (let t = 0; t < (await tabs.count()); t += 1) {
    await tabs.nth(t).click();
    await page.waitForTimeout(60);
  }
  const expand = dialog.getByRole("button", { name: /Expand details/ });
  if ((await expand.count()) > 0) {
    await expand.click();
    await dialog.getByRole("button", { name: /Collapse details/ }).click();
  }
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" }).catch(() => undefined);
  await page.waitForTimeout(100);
};
await cycleOnce();
await settle();
const cardHeapBefore = await heap();
const cardStart = Date.now();
for (let i = 0; i < args.cycles; i += 1) await cycleOnce();
result.cardCycles = { cycles: args.cycles, ms: Date.now() - cardStart, heapGrowth: (await heap()) - cardHeapBefore };

console.log(JSON.stringify(result, null, 2));
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(result, null, 2)}\n`);
await browser.close();
server.close();
rmSync(work, { recursive: true, force: true });
