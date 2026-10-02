/**
 * The payload budgets, measured in a real browser against a server that behaves like GitHub
 * Pages (ADR-098).
 *
 * The server is `static-server.mjs` in its Pages mode: gzip at level 5 for the types Pages
 * compresses, a weak ETag of mtime and size, `Last-Modified`, and bodiless 304s — every header
 * docs/OPERATIONS.md section 17 records the live site sending. `max-age` is 0 here rather than
 * 600, so the browser revalidates at once: that is the visit a returning reader makes the next
 * day, without the test waiting ten minutes.
 *
 * Every byte counted is a response body as the server sent it — gzip-5 where Pages would
 * compress, 0 for a 304 — counted at the server, which is the only place the wire is certain
 * (a browser reports a revalidated response with the cached body's size). A file the page read
 * from its Cache API made no request and costs 0.
 *
 * | scenario | budget |
 * |---|---|
 * | first visit, in-season default view — everything | ≤ 450 kB |
 * | first visit, in-season default view — data (`/data/`) | ≤ 150 kB |
 * | then opening Start/Sit adds | ≤ 60 kB |
 * | then opening Trade adds (ADR-100) | ≤ 25 kB |
 * | opening a player card from the default view adds | ≤ 30 kB |
 * | a repeat visit to the same deploy — data | ≤ 1 kB (≈ 0) |
 * | a redeploy of unchanged data — served data files | 0 B |
 *
 * It also proves the fail-safe property the cache depends on: after a deploy that changes one
 * player's name, a reader holding the old deploy's files in their cache sees the new name.
 *
 * kB is 1,000 bytes. The build it runs on is a copy, so the redeploys it simulates never touch
 * the directory it was given.
 *
 *   node web/tests/e2e/verify-budget.mjs --dist web/dist-size-model --base-path /jeisey-tiers/ \
 *        [--port 4190] [--json budget.json] [--report-only]
 *
 * `--report-only` prints every number and exits 0 whatever they are: the daily refresh uses it
 * on the real build so a budget miss is reported loudly in the run summary without holding a
 * correct board back (the CI gate on the size model is what blocks a regression).
 */

import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { chromium } from "@playwright/test";

import { createStaticServer } from "./static-server.mjs";

export const BUDGETS = {
  firstVisitTotal: 450_000,
  firstVisitData: 150_000,
  startSitAdds: 60_000,
  tradeAdds: 25_000,
  cardAdds: 30_000,
  repeatVisitData: 1_000,
  redeployServedData: 0,
};

function parseArgs(argv) {
  const args = { dist: null, basePath: "/", port: 4190, json: null, reportOnly: false };
  for (let i = 0; i < argv.length; i += 1) {
    const [flag, inline] = argv[i].split("=");
    if (flag === "--report-only") {
      args.reportOnly = true;
      continue;
    }
    const value = inline ?? argv[++i];
    if (flag === "--dist") args.dist = value;
    else if (flag === "--base-path") args.basePath = value.endsWith("/") ? value : `${value}/`;
    else if (flag === "--port") args.port = Number(value);
    else if (flag === "--json") args.json = value;
    else throw new Error(`unknown option ${flag}`);
  }
  if (args.dist === null) throw new Error("--dist is required");
  return args;
}

const repo = resolve(new URL("../../..", import.meta.url).pathname);
const args = parseArgs(process.argv.slice(2));
const work = mkdtempSync(join(tmpdir(), "budget-"));
const dist = join(work, "dist");
cpSync(resolve(repo, args.dist), dist, { recursive: true });

const served = [];
const server = createStaticServer({
  roots: [{ base: args.basePath, dir: dist }],
  pages: { maxAge: 0, onServe: (entry) => served.push(entry) },
});
await new Promise((ok) => server.listen(args.port, ok));
const origin = `http://localhost:${String(args.port)}`;
const site = `${origin}${args.basePath}`;

// The portrait host is the one third party a card names (ADR-087). It is not this site's
// bandwidth and no gate may depend on its uptime, so every other host fails to resolve.
// Deliberately not `page.route`: Playwright turns Chromium's HTTP cache off whenever routing
// is on, and the cache is exactly what a repeat visit measures.
const launch = {
  args: ["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE localhost"],
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined
    ? {}
    : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }),
};
const browser = await chromium.launch(launch);

/** The server's log: `mark()` a point, `since()` everything sent after it. */
function record() {
  return {
    mark: () => served.length,
    since: (mark) => served.slice(mark),
  };
}

function sum(entries, predicate = () => true) {
  return entries.filter(predicate).reduce((total, entry) => total + entry.bytes, 0);
}

const isData = (entry) => entry.path.startsWith(`${args.basePath}data/`);
const isServed = (entry) => entry.path.startsWith(`${args.basePath}data/serve/`);

async function settle(page) {
  await page.waitForLoadState("networkidle");
}

async function newPage(context) {
  return context.newPage();
}

async function openDefault(page) {
  await page.goto(site, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: /Rest of season/ }).first().waitFor();
  await settle(page);
}

function touchAll(directory, when) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) touchAll(path, when);
    else utimesSync(path, when, when);
  }
}

const results = {};
const failures = [];
function check(name, value, budget) {
  results[name] = { bytes: value, budget };
  if (value > budget) failures.push(`${name}: ${String(value)} B exceeds ${String(budget)} B`);
}

try {
  // 1-2. A cold first visit to the in-season default view, then Start/Sit.
  const reader = await browser.newContext();
  const page = await newPage(reader);
  const log = record();
  await openDefault(page);
  const first = log.since(0);
  check("firstVisitTotal", sum(first), BUDGETS.firstVisitTotal);
  check("firstVisitData", sum(first, isData), BUDGETS.firstVisitData);
  results.firstVisitRequests = first.length;
  results.firstVisitFiles = first.map((entry) => `${entry.path} ${String(entry.status)} ${String(entry.bytes)}`);

  let mark = log.mark();
  await page.getByRole("tab", { name: "Start/Sit" }).click();
  await page.getByRole("heading", { name: /Start\/Sit/ }).first().waitFor();
  await settle(page);
  check("startSitAdds", sum(log.since(mark)), BUDGETS.startSitAdds);

  // 2b. Then Trade (ADR-100): its code only — it reads the ROS block already loaded.
  mark = log.mark();
  await page.getByRole("tab", { name: "Trade" }).click();
  await page.getByRole("heading", { name: "Trade targets" }).first().waitFor();
  await settle(page);
  const trade = log.since(mark);
  check("tradeAdds", sum(trade), BUDGETS.tradeAdds);
  results.tradeAddsData = sum(trade, isData);

  // 3. A player card, opened from the default view in a fresh browser.
  const other = await browser.newContext();
  const cardPage = await newPage(other);
  const cardLog = record();
  await openDefault(cardPage);
  mark = cardLog.mark();
  await cardPage.locator("table.sheet tbody tr[data-player] .player-name").first().click();
  await cardPage.getByRole("dialog").waitFor();
  await settle(cardPage);
  check("cardAdds", sum(cardLog.since(mark)), BUDGETS.cardAdds);
  await other.close();

  // 3a. Reported, not budgeted: a cold first visit straight to a shared Trade link.
  const trader = await browser.newContext();
  const tradePage = await newPage(trader);
  mark = log.mark();
  await tradePage.goto(`${site}?view=trade`, { waitUntil: "domcontentloaded" });
  await tradePage.getByRole("heading", { name: "Trade targets" }).first().waitFor();
  await settle(tradePage);
  const tradeCold = log.since(mark);
  results.tradeFirstVisitTotal = sum(tradeCold);
  results.tradeFirstVisitData = sum(tradeCold, isData);
  await trader.close();

  // 3b. Reported, not budgeted: a cold first visit to the draft board (the preseason default).
  const drafter = await browser.newContext();
  const draftPage = await newPage(drafter);
  mark = log.mark();
  await draftPage.goto(`${site}?mode=draft`, { waitUntil: "domcontentloaded" });
  await draftPage.getByRole("heading", { name: "Tier board" }).first().waitFor();
  await settle(draftPage);
  const draft = log.since(mark);
  results.draftFirstVisitTotal = sum(draft);
  results.draftFirstVisitData = sum(draft, isData);
  await drafter.close();

  // 4. The same reader returns to the same deploy.
  mark = log.mark();
  await openDefault(page);
  const repeat = log.since(mark);
  check("repeatVisitData", sum(repeat, isData), BUDGETS.repeatVisitData);
  results.repeatVisitTotal = sum(repeat);

  // 5. A redeploy with identical data. Pages resets every file's mtime, so every ETag changes
  //    and HTTP revalidation re-sends every byte; the content-addressed files are read from the
  //    page's own cache and never requested at all.
  touchAll(dist, new Date(Date.now() + 3_600_000));
  mark = log.mark();
  await openDefault(page);
  const redeploy = log.since(mark);
  check("redeployServedData", sum(redeploy, isServed), BUDGETS.redeployServedData);
  results.redeployManifest = sum(redeploy, (entry) => entry.path.endsWith("/manifest.json"));
  results.redeployTotal = sum(redeploy);

  // 6. Fail safe: a deploy that changes a player's name. The reader's cache still holds the old
  //    deploy's files; the page must show the new name, from the new files.
  const data = join(dist, "data");
  const ros = JSON.parse(readFileSync(join(data, "ros_tiers.json"), "utf-8"));
  const target = ros.records[0];
  const renamed = "Zz Fresh-Deploy Check";
  for (const name of readdirSync(data)) {
    if (!name.endsWith(".json") || name === "manifest.json") continue;
    const path = join(data, name);
    if (!statSync(path).isFile()) continue;
    const payload = JSON.parse(readFileSync(path, "utf-8"));
    if (!Array.isArray(payload.records)) continue;
    for (const record of payload.records) {
      if (record.player_id === target.player_id && "display_name" in record) record.display_name = renamed;
    }
    writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`);
  }
  execFileSync("uv", ["run", "--frozen", "ffdraft", "package-site-data", data], {
    cwd: repo,
    stdio: ["ignore", "ignore", "inherit"],
  });
  await openDefault(page);
  const fresh = await page.getByText(renamed).count();
  results.freshDeployShown = fresh > 0;
  if (fresh === 0) failures.push("after a redeploy the page did not show the new deploy's data");
  await reader.close();
} finally {
  await browser.close();
  server.close();
  rmSync(work, { recursive: true, force: true });
}

const report = { site: args.dist, budgets: BUDGETS, results, failures };
const printable = { ...report, results: { ...results, firstVisitFiles: undefined } };
console.log(JSON.stringify(printable, null, 1));
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(report, null, 1)}\n`);
if (failures.length > 0 && !args.reportOnly) process.exit(1);
