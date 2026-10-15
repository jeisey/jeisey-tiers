/**
 * Win My Matchup's interaction cost and memory (ADR-110 §9), on a production-shaped board in a
 * mobile-like browser: a Pixel-7 viewport with the CPU throttled through the DevTools protocol,
 * as `measure-leagues.mjs` measures My Leagues.
 *
 * The matchup is the largest the workspace allows — 15 starters a side (2 QB, 4 RB, 4 WR, 2 TE,
 * 3 FLEX) and a ten-player bench — drawn from the build's own playable players
 * (`wmm-seed.mjs`). The behaviour snapshot is re-stamped to an hour ago on the measured copy, so
 * YOLO's gates read a current feed. It records:
 *
 * - **open** — the tab click until the view is painted (its chunk fetched from a local server);
 * - **simulate** — *Simulate* until the headline has painted: the first (worker fetched and
 *   started) and warm runs after an opponent edit;
 * - **pick** — an opponent pick through the picker until the dialog has closed and painted;
 * - **evaluate** — *Evaluate changes and pickups* until the ranked list has painted, with the
 *   number of lineups evaluated;
 * - **preview** — a proposal's preview until its overlay has painted;
 * - **cancel** — *Cancel* on a running simulation until *Simulate* is usable again;
 * - **long tasks** — every main-thread long task (PerformanceObserver) inside those windows;
 * - **fallback** — the same simulation with no `Worker`: its time and longest task;
 * - **cleanup and heap** — no worker left after a league switch, and JS heap after GC across
 *   repeated switch-and-simulate cycles.
 *
 * Targets (frozen in ADR-110 before implementation): simulate ≤ 500 ms, evaluate ≤ 1,500 ms, no
 * long task > 50 ms in a run window, cancel ≤ 100 ms, pick ≤ 200 ms, heap growth ≤ 2 MB.
 *
 *   npm run e2e:size-model
 *   node web/tests/e2e/measure-wmm.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--throttle 4] [--json wmm-perf.json] [--cycles 4] [--profile dir]
 *
 * `--profile dir` also writes a Chrome trace of each measured run window (open it in DevTools'
 * Performance panel) and reports its longest main-thread task with what filled it.
 */

import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { execFileSync } from "node:child_process";

import { chromium, devices } from "@playwright/test";

import { makeProductionShaped } from "./production-board.mjs";
import { createStaticServer } from "./static-server.mjs";
import { MAX_COUNTS, leaguesDocument, wmmScenario } from "./wmm-seed.mjs";

const args = { dist: "web/dist-size-model", basePath: "/jeisey-tiers/", throttle: 4, json: null, port: 4193, cycles: 4, profile: null };
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
  else if (flag === "--profile") args.profile = resolve(value);
  else throw new Error(`unknown option ${flag}`);
}

const TARGETS = { simulateMs: 500, evaluateMs: 1500, longTaskMs: 50, cancelMs: 100, pickMs: 200, heapGrowthBytes: 2_000_000 };
const repo = resolve(new URL("../../..", import.meta.url).pathname);
const work = mkdtempSync(join(tmpdir(), "wmm-perf-"));
const dist = join(work, "dist");
cpSync(resolve(args.dist), dist, { recursive: true });
makeProductionShaped(dist, repo);
// A current behaviour snapshot, so YOLO's gates run rather than reporting a stale feed.
const metadataPath = join(dist, "data", "ros_build_metadata.json");
const metadata = JSON.parse(readFileSync(metadataPath, "utf-8"));
metadata.behavior = { ...metadata.behavior, snapshot_at_utc: new Date(Date.now() - 3_600_000).toISOString().replace(/\.\d+Z$/, "Z") };
writeFileSync(metadataPath, `${JSON.stringify(metadata)}\n`);
execFileSync("uv", ["run", "--frozen", "ffdraft", "package-site-data", join(dist, "data")], { cwd: repo, stdio: ["ignore", "ignore", "inherit"] });

const main = wmmScenario(dist, { counts: MAX_COUNTS, base: args.basePath, leagueId: "lg-wmmperf1", name: "Maximal" });
const other = { ...main.league, id: "lg-wmmperf2", name: "Second", roster: { ...main.league.roster } };
// A different FLEX for every edit, so no run is answered from the view's cache of recent results.
const flexSpares = [...(main.spare.WR ?? []), ...(main.spare.RB ?? [])];
if (flexSpares.length < 6) throw new Error("the build has too few spare receivers and backs to vary the opponent's FLEX");

const server = createStaticServer({ roots: [{ base: args.basePath, dir: dist }] });
await new Promise((ok) => server.listen(args.port, ok));
const site = `http://localhost:${String(args.port)}${args.basePath}`;
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});

const leagueDoc = leaguesDocument([main.league, other]);
const matchupDoc = JSON.stringify(main.matchup);

async function openPage({ worker = true } = {}) {
  const context = await browser.newContext({ ...devices["Pixel 7"] });
  await context.addInitScript(
    ([leaguesKey, leagues, matchupsKey, matchups, keepWorker]) => {
      if (window.sessionStorage.getItem("seeded") === null) {
        window.localStorage.setItem(leaguesKey, leagues);
        window.localStorage.setItem(matchupsKey, matchups);
        window.sessionStorage.setItem("seeded", "1");
      }
      if (!keepWorker) window.Worker = undefined;
      window.__longTasks = [];
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__longTasks.push({ start: entry.startTime, duration: entry.duration });
      }).observe({ type: "longtask", buffered: true });
      // Long animation frames say what a long frame was made of: scripts, then style and layout.
      window.__frames = [];
      try {
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            window.__frames.push({
              start: entry.startTime,
              duration: entry.duration,
              scriptMs: Math.round((entry.renderStart || entry.startTime + entry.duration) - entry.startTime),
              renderMs: entry.renderStart ? Math.round(entry.startTime + entry.duration - entry.renderStart) : 0,
              styleAndLayoutMs: entry.styleAndLayoutStart ? Math.round(entry.startTime + entry.duration - entry.styleAndLayoutStart) : 0,
              scripts: entry.scripts.map((script) => `${script.invoker} ${String(Math.round(script.duration))} ms`),
            });
          }
        }).observe({ type: "long-animation-frame", buffered: true });
      } catch {
        // Not every engine has long-animation-frame entries.
      }
    },
    [main.keys.leagues, leagueDoc, main.keys.matchups, matchupDoc, worker],
  );
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: args.throttle });
  await cdp.send("HeapProfiler.enable");
  return { context, page, cdp };
}


/**
 * The longest main-thread task in a Chrome trace and what filled it: self time by trace event
 * (layout, style, paint, script, compile, garbage collection) and by script function.
 */
function longestTask(trace) {
  const events = trace.traceEvents.filter((event) => event.ph === "X" && typeof event.dur === "number");
  const names = new Map(trace.traceEvents.filter((event) => event.ph === "M" && event.name === "thread_name").map((event) => [`${String(event.pid)}:${String(event.tid)}`, event.args.name]));
  const tasks = events.filter((event) => event.name === "RunTask" && names.get(`${String(event.pid)}:${String(event.tid)}`) === "CrRendererMain");
  const task = tasks.sort((a, b) => b.dur - a.dur)[0];
  if (task === undefined) return null;
  const inside = events
    .filter((event) => event.pid === task.pid && event.tid === task.tid && event.ts >= task.ts && event.ts + event.dur <= task.ts + task.dur)
    .sort((a, b) => a.ts - b.ts || b.dur - a.dur);
  const self = new Map();
  const functions = new Map();
  const stack = [];
  for (const event of inside) {
    while (stack.length > 0 && stack.at(-1).ts + stack.at(-1).dur <= event.ts) stack.pop();
    const parent = stack.at(-1);
    if (parent !== undefined) self.set(parent.name, (self.get(parent.name) ?? 0) - event.dur);
    self.set(event.name, (self.get(event.name) ?? 0) + event.dur);
    if (event.name === "FunctionCall") {
      const data = event.args?.data ?? {};
      const where = `${data.functionName || "(anonymous)"} ${String(data.url ?? "").split("/").at(-1)}`;
      functions.set(where, (functions.get(where) ?? 0) + event.dur);
    }
    stack.push(event);
  }
  const top = (map) => [...map].filter(([, us]) => us > 500).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, us]) => `${(us / 1000).toFixed(1)} ms ${name}`);
  return { longestTaskMs: Math.round(task.dur / 1000), self: top(self), scripts: top(functions) };
}

/** Run `action` in the page and wait until `ready()` holds and two frames painted; ms and window. */
async function timed(page, action, ready, label = null) {
  const profiling = args.profile !== null && label !== null;
  if (profiling) {
    await browser.startTracing(page, {
      categories: ["toplevel", "devtools.timeline", "disabled-by-default-devtools.timeline", "v8", "v8.execute", "blink.user_timing"],
    });
  }
  const outcome = await page.evaluate(
    async ([actionSource, readySource]) => {
      const run = new Function(actionSource);
      const done = new Function(`return (${readySource})`);
      const start = performance.now();
      run();
      for (let i = 0; i < 6000 && !done(); i += 1) await new Promise((ok) => setTimeout(ok, 2));
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
      const end = performance.now();
      // Any frame still owed (a later paint stage) is inside the long-task window too.
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(ok, 0))));
      const settled = performance.now();
      const longest = Math.max(0, ...window.__longTasks.filter((task) => task.start + task.duration >= start && task.start <= settled).map((task) => task.duration));
      const frame = window.__frames
        .filter((entry) => entry.start + entry.duration >= start && entry.start <= settled)
        .sort((a, b) => b.duration - a.duration)[0];
      const longestFrame = frame === undefined ? null : { ...frame, start: undefined, duration: Math.round(frame.duration) };
      return { ms: Math.round(end - start), longTask: Math.round(longest), longestFrame, ok: done() };
    },
    [action, ready],
  );
  if (profiling) {
    const trace = (await browser.stopTracing()).toString("utf-8");
    mkdirSync(args.profile, { recursive: true });
    writeFileSync(join(args.profile, `${label}.json`), trace);
    outcome.trace = longestTask(JSON.parse(trace));
  }
  return outcome;
}

/**
 * The worker's own compute time for the latest run of `kind` (the view's `wmm-<kind>` measure
 * carries it), and the click-to-paint time with that compute scaled to the throttled CPU: CDP's
 * throttle slows the page's main thread but not a dedicated worker (measured below), so a phone's
 * worker would take about `throttle` times as long.
 */
async function withWorkerCost(page, kind, outcome) {
  const detail = await page.evaluate((name) => performance.getEntriesByName(name).at(-1)?.detail ?? null, `wmm-${kind}`);
  if (detail === null) return outcome;
  const scaled = detail.where === "worker" ? outcome.ms + (args.throttle - 1) * detail.computeMs : outcome.ms;
  return { ...outcome, where: detail.where, computeMs: detail.computeMs, variants: detail.variants, throttledEstimateMs: Math.round(scaled) };
}

const clickButton = (name) => `[...document.querySelectorAll("button")].find((node) => node.textContent.trim() === ${JSON.stringify(name)} && !node.disabled).click()`;
// A result paints in three frames (ADR-110 §9): it is complete once the slot-group table is in.
const RESULT = `document.querySelector(".wmm-group-table") !== null && document.querySelector('[aria-live="polite"]') === null`;

async function heap(cdp) {
  await cdp.send("HeapProfiler.collectGarbage");
  return (await cdp.send("Runtime.getHeapUsage")).usedSize;
}

/** Change the opponent's first FLEX to `id` through the picker; returns the pick timing. */
async function pickFlex(page, id) {
  const name = nameOf(id);
  const query = name.split(" ").at(-1) ?? name;
  await page.getByRole("button", { name: /^Change the opponent's FLEX 1/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox").fill(query.slice(0, -1));
  const key = await page.evaluate(async (last) => {
    const input = document.querySelector('dialog[open] [role="combobox"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    const start = performance.now();
    setter.call(input, input.value + last);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    for (let i = 0; i < 500 && document.querySelector('dialog[open] [role="option"]') === null; i += 1) await new Promise((ok) => setTimeout(ok, 2));
    await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    return performance.now() - start;
  }, query.slice(-1));
  const pick = await page.evaluate(async (wanted) => {
    const options = [...document.querySelectorAll('dialog[open] [role="option"]')];
    const option = options.find((node) => node.textContent.includes(wanted)) ?? options[0];
    const start = performance.now();
    option.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    for (let i = 0; i < 500 && document.querySelector("dialog[open]") !== null; i += 1) await new Promise((ok) => setTimeout(ok, 2));
    await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    return performance.now() - start;
  }, name);
  return { keyMs: Math.round(key), pickMs: Math.round(pick) };
}

let names = null;
function nameOf(id) {
  names ??= new Map(JSON.parse(readFileSync(join(dist, "data", "weekly_projections.json"), "utf-8")).records.map((record) => [record.player_id, record.display_name]));
  return names.get(id) ?? id;
}

const result = {};
try {
  const { page, cdp, context } = await openPage();
  await page.goto(`${site}?view=myleagues`, { waitUntil: "networkidle" });
  await page.locator(".lg-auto").waitFor();
  result.entriesBeforeAsked = await page.evaluate(() => performance.getEntries().filter((entry) => entry.name.startsWith("wmm-")).length);
  const open = await timed(page, clickButton("Win My Matchup"), `document.querySelector(".wmm-ready") !== null`);
  result.openMs = open.ms;
  result.workersBeforeSimulate = page.workers().length;
  await page.waitForLoadState("networkidle");
  result.ready = (await page.locator(".wmm-ready").innerText()).replace(/\s+/g, " ");

  const first = await withWorkerCost(page, "simulate", await timed(page, clickButton("Simulate"), RESULT, "simulate-first"));
  result.simulateFirst = first;
  result.workersAfterSimulate = page.workers().length;
  // Whether the CPU throttle reaches the worker too: the same loop timed in both.
  const spin = () => {
    const begun = performance.now();
    let sum = 0;
    for (let i = 0; i < 20_000_000; i += 1) sum += i % 7;
    return [performance.now() - begun, sum];
  };
  const [worker] = page.workers();
  if (worker !== undefined) result.spinMs = { page: Math.round((await page.evaluate(spin))[0]), worker: Math.round((await worker.evaluate(spin))[0]) };

  const warm = [];
  const picks = [];
  for (let index = 0; index < 4; index += 1) {
    picks.push(await pickFlex(page, flexSpares[index]));
    warm.push(await withWorkerCost(page, "simulate", await timed(page, clickButton("Simulate"), RESULT, `simulate-warm-${String(index + 1)}`)));
  }
  result.simulateWarm = warm;
  result.picks = picks;

  await page.getByRole("checkbox", { name: "YOLO" }).check();
  await page.locator(".wmm-yolo .wmm-funnel, .wmm-yolo .notice").first().waitFor({ timeout: 60_000 });
  result.yoloFunnel = (await page.locator(".wmm-yolo").innerText()).split("\n").filter((line) => /bar |too few|stale|missing/.test(line)).slice(0, 6);
  const evaluate = await withWorkerCost(
    page,
    "changes",
    await timed(page, clickButton("Evaluate changes and pickups"), `document.querySelector(".wmm-changes") !== null`, "evaluate"),
  );
  result.evaluate = evaluate;
  const evaluatedHelp = page.locator(".wmm-changes .lg-help").first();
  result.evaluated = (await evaluatedHelp.count()) > 0 ? ((await evaluatedHelp.innerText()).match(/Best of (\d+)/)?.[1] ?? null) : "0";
  result.yoloCandidates = await page.locator(".wmm-yolo-card").count();
  result.prepareMs = await page.evaluate(() => performance.getEntriesByName("wmm-prepare").map((entry) => Math.round(entry.duration)));
  result.changesRunMs = await page.evaluate(() => performance.getEntriesByName("wmm-changes").map((entry) => Math.round(entry.duration)));
  const previewButton = page.locator(".wmm-change-list").first().getByRole("button", { name: "Preview" }).first();
  if ((await previewButton.count()) > 0) {
    result.preview = await withWorkerCost(page, "preview", await timed(page, `document.querySelector(".wmm-change-list button[aria-pressed]").click()`, `document.querySelector(".wmm-legend[data-side=overlay]") !== null`, "preview"));
  }

  // Cancel: invalidate, start, cancel at once.
  await pickFlex(page, flexSpares[4]);
  result.cancel = await page.evaluate(async () => {
    const find = (name) => [...document.querySelectorAll("button")].find((node) => node.textContent.trim() === name);
    find("Simulate").click();
    for (let i = 0; i < 200 && find("Cancel") === undefined; i += 1) await new Promise((ok) => setTimeout(ok, 1));
    const cancel = find("Cancel");
    if (cancel === undefined) return { ms: null, note: "the run finished before Cancel could be pressed" };
    const start = performance.now();
    cancel.click();
    for (let i = 0; i < 500 && (find("Simulate") === undefined || find("Simulate").disabled); i += 1) await new Promise((ok) => setTimeout(ok, 1));
    await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    return { ms: Math.round(performance.now() - start), headline: document.querySelector(".wmm-headline") !== null };
  });

  // Cleanup and memory: switch leagues and back, simulating each time.
  const heaps = [];
  const workersAfterSwitch = [];
  const switchMs = [];
  for (let cycle = 0; cycle < args.cycles; cycle += 1) {
    switchMs.push((await timed(page, `[...document.querySelectorAll('.lg-switch-option')].find((node) => node.textContent.includes("Second")).click()`, `document.querySelector(".wmm-ready") !== null && document.querySelector(".lg-switch-option[aria-checked=true]").textContent.includes("Second")`)).ms);
    workersAfterSwitch.push(page.workers().length);
    switchMs.push((await timed(page, `[...document.querySelectorAll('.lg-switch-option')].find((node) => node.textContent.includes("Maximal")).click()`, `document.querySelector(".wmm-ready") !== null && document.querySelector(".lg-switch-option[aria-checked=true]").textContent.includes("Maximal")`)).ms);
    await timed(page, clickButton("Simulate"), RESULT);
    heaps.push(await heap(cdp));
  }
  result.switchMs = switchMs;
  result.workersAfterSwitch = workersAfterSwitch;
  result.heapBytes = heaps;
  result.heapGrowthAfterFirstCycle = heaps.length > 1 ? heaps.at(-1) - heaps[0] : 0;
  await context.close();

  // The fallback: no Worker at all.
  const fallback = await openPage({ worker: false });
  await fallback.page.goto(`${site}?view=myleagues&panel=wmm`, { waitUntil: "networkidle" });
  await fallback.page.locator(".wmm-ready").waitFor();
  result.fallback = await timed(fallback.page, clickButton("Simulate"), `document.querySelector(".wmm-group-table") !== null`, "fallback-simulate");
  result.fallbackEvaluate = await timed(fallback.page, clickButton("Evaluate lineup changes"), `document.querySelector(".wmm-changes") !== null`, "fallback-evaluate");
  await fallback.context.close();
} finally {
  await browser.close();
  server.close();
  rmSync(work, { recursive: true, force: true });
}

const runs = [result.simulateFirst, ...(result.simulateWarm ?? []), result.evaluate, result.preview].filter(Boolean);
const summary = {
  site: args.dist,
  throttle: `${String(args.throttle)}x CPU, Pixel 7 viewport`,
  matchup: "15 starters a side (2 QB, 4 RB, 4 WR, 2 TE, 3 FLEX), 10 on the bench",
  targets: TARGETS,
  worst: {
    simulateMs: Math.max(...[result.simulateFirst, ...(result.simulateWarm ?? [])].map((run) => run?.throttledEstimateMs ?? run?.ms ?? 0)),
    evaluateMs: result.evaluate?.throttledEstimateMs ?? result.evaluate?.ms ?? null,
    longTaskInRunsMs: Math.max(0, ...runs.map((run) => run.longTask)),
    cancelMs: result.cancel?.ms ?? null,
    pickMs: Math.max(...(result.picks ?? []).map((pick) => Math.max(pick.keyMs, pick.pickMs))),
    heapGrowthBytes: result.heapGrowthAfterFirstCycle,
  },
  ...result,
};
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(summary, null, 1)}\n`);
console.log(JSON.stringify(summary, null, 1));
const over =
  summary.worst.simulateMs > TARGETS.simulateMs ||
  (summary.worst.evaluateMs ?? 0) > TARGETS.evaluateMs ||
  summary.worst.longTaskInRunsMs > TARGETS.longTaskMs ||
  (summary.worst.cancelMs ?? 0) > TARGETS.cancelMs ||
  summary.worst.pickMs > TARGETS.pickMs ||
  summary.worst.heapGrowthBytes > TARGETS.heapGrowthBytes ||
  result.workersAfterSwitch.some((count) => count !== 0) ||
  result.entriesBeforeAsked !== 0;
process.exitCode = over ? 1 : 0;
