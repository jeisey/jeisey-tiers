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
 * | My Leagues (ADR-106), opened from the default view, adds | ≤ 80 kB |
 * | then turning Rising Stars on adds | ≤ 130 kB |
 * | then running Improve adds | ≤ 12 kB |
 * | then switching to a saved league on a preset not yet loaded adds | ≤ 95 kB |
 * | then switching among the three saved leagues again | 0 B |
 * | a cold first visit straight to My Leagues — everything | ≤ 450 kB |
 * | a cold first visit straight to My Leagues — data | ≤ 150 kB |
 * | showing the Skill Tree (ADR-107) on an open card adds | ≤ 25 kB |
 * | then hiding and showing it, or reopening that player's tree | 0 B |
 * | then another player's tree, at another position | ≤ 10 kB |
 * | showing the ESPN trend (ADR-112) on an open card adds | ≤ 15 kB |
 * | then hiding and showing it, or reopening the card and showing it again | 0 B |
 * | Win My Matchup (ADR-110), opened from a league's lineup, adds | ≤ 30 kB |
 * | then the first Simulate (the worker) adds | ≤ 7 kB |
 * | then evaluating changes, switching tools and simulating again | 0 B |
 * | then turning YOLO on adds | ≤ 125 kB |
 * | a cold first visit straight to Win My Matchup — everything / data | ≤ 450 kB / ≤ 150 kB |
 * | Insights (ADR-116), opened from the default view, adds | ≤ 50 kB |
 * | of which the served stories slice (one scoring preset) | ≤ 25 kB |
 * | then expanding a story's Evidence adds — the evidence slice | ≤ 15 kB |
 * | then opening the share view adds — its code | ≤ 8 kB |
 *
 * Insights' budgets are its measured cost on the size model plus a margin (2026-10-27): opening
 * the tab 42.6 kB — code 21.5 kB, stylesheet 2.7 kB, one preset's stories 18.4 kB (82 stories,
 * the late-season worst case); the status slice is the default view's. The evidence slice (10.5
 * kB) loads the first time a reader expands a story, once per preset. The share view's code
 * (6.0 kB: the card builder and the PNG export) loads only when a reader opens it; the faces it
 * embeds are the stylesheet's own files, already in the browser. No other view may fetch a
 * stories or evidence slice.
 *
 * Win My Matchup's budgets are its measured cost on the size model plus a margin (ADR-110
 * records the numbers): its code and stylesheet, then its worker on the first simulation, then
 * YOLO's two files — the Opportunity block and the role series, which Rising Stars already holds
 * when it is on. A direct link must meet the default view's first-visit envelope.
 *
 * The Skill Tree's budgets are separate from the card's on purpose: opening a card fetches none
 * of it (that is `cardAdds`, unchanged), and its code, stylesheet and two data files — his
 * position's definitions and his bucket's readings — load only when a reader asks for them.
 * Measured on the size model and a live week-5 build plus a margin (ADR-107 records both).
 *
 * My Leagues' budgets are its measured cost on the size model plus a margin (ADR-106 records the
 * numbers). Opening it reads the week's projections Start/Sit reads, so it costs about what
 * Start/Sit does plus its own code; Rising Stars reads exactly the Opportunity Board's evidence
 * files (reported below as `opportunityAdds`) and is off until a reader turns it on; a direct
 * link to My Leagues meets the default view's first-visit budgets.
 *
 * My Leagues' scenarios run with three leagues saved in the browser before the page loads: the
 * active one on the default view's preset (12-team PPR), the others on 10-team Half PPR and
 * 14-team Standard, each a full roster from the build's own board.
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
import { leaguesDocument, wmmScenario } from "./wmm-seed.mjs";

export const BUDGETS = {
  firstVisitTotal: 450_000,
  firstVisitData: 150_000,
  startSitAdds: 60_000,
  tradeAdds: 25_000,
  cardAdds: 30_000,
  repeatVisitData: 1_000,
  redeployServedData: 0,
  myLeaguesAdds: 80_000,
  risingStarsAdds: 130_000,
  improveAdds: 12_000,
  leagueSwitchNewPreset: 95_000,
  leagueSwitchRepeat: 0,
  myLeaguesFirstVisitTotal: 450_000,
  myLeaguesFirstVisitData: 150_000,
  skillTreeAdds: 25_000,
  skillTreeRepeat: 0,
  skillTreeSwitch: 10_000,
  ownershipHistoryAdds: 15_000,
  ownershipHistoryRepeat: 0,
  wmmOpenAdds: 30_000,
  wmmSimulateAdds: 7_000,
  wmmRepeat: 0,
  yoloAdds: 125_000,
  wmmFirstVisitTotal: 450_000,
  wmmFirstVisitData: 150_000,
  // ADR-113: the recent-form slice the Opportunity Board adds (one scoring preset) — measured
  // 33.9 kB on the size model's late-season projection (700 records, 8% of windows badged) —
  // and a window switch, which must re-use it.
  recentSlice: 40_000,
  recentWindowSwitch: 0,
  // ADR-116: the Insights tab from the default view (code, stylesheet, one preset's stories), the
  // stories slice alone, and the share view's code.
  insightsAdds: 50_000,
  insightsSlice: 25_000,
  insightsEvidenceAdds: 15_000,
  insightsShareAdds: 8_000,
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

/**
 * Three saved leagues (ADR-106) for a browser context, written before the first page script
 * runs and only once per tab, so the page's own saves are never overwritten by the seed.
 */
function leagueSeed() {
  const ros = JSON.parse(readFileSync(join(dist, "data", "ros_tiers.json"), "utf-8")).records;
  const counts = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 5, IR: 2 };
  const roster = (leaguePreset, scoring) => {
    const rows = ros
      .filter((row) => row.league_preset_id === leaguePreset && row.scoring_preset === scoring)
      .sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
    const by = (position) => rows.filter((row) => row.position === position).map((row) => row.player_id);
    const [qb, rb, wr, te] = [by("QB"), by("RB"), by("WR"), by("TE")];
    const take = (list, index) => list[index] ?? null;
    return {
      QB: [take(qb, 0)],
      RB: [take(rb, 0), take(rb, 12)],
      WR: [take(wr, 0), take(wr, 12)],
      TE: [take(te, 0)],
      FLEX: [take(rb, 24)],
      BN: [take(qb, 12), take(rb, 30), take(wr, 24), take(wr, 30), take(te, 12)],
      IR: [take(rb, 40), null],
    };
  };
  const leagues = [
    ["lg-budget01", "Office", "ppr", 12, "redraft-12", "PPR"],
    ["lg-budget02", "Family", "half", 10, "redraft-10", "HALF"],
    ["lg-budget03", "Friends", "std", 14, "redraft-14", "STD"],
  ].map(([id, name, scoring, teams, leaguePreset, scoringPreset]) => ({
    id,
    name,
    season: ros[0]?.season ?? 2026,
    scoring,
    teams,
    slots: counts,
    roster: roster(leaguePreset, scoringPreset),
    prefs: { risingStars: false, mode: "q50" },
    rev: 1,
    updatedAt: "2026-01-01T00:00:00Z",
  }));
  return {
    key: `jeisey-tiers:my-leagues@${args.basePath}`,
    value: JSON.stringify({ format: "jeisey-tiers.my-leagues", version: 1, revision: 1, activeId: leagues[0].id, leagues }),
  };
}

async function seedLeagues(context) {
  const { key, value } = leagueSeed();
  await context.addInitScript(
    ([storageKey, document]) => {
      if (window.sessionStorage.getItem("budget-seeded") === null) {
        window.localStorage.setItem(storageKey, document);
        window.sessionStorage.setItem("budget-seeded", "1");
      }
    },
    [key, value],
  );
}

/** The workspace has drawn the active league's lineup on `label`'s preset. */
async function leagueShown(page, label) {
  await page.locator(".lg-preset strong", { hasText: label }).waitFor();
  await page.locator(".lg-auto").waitFor();
  await settle(page);
}

const results = {};
const failures = [];
function check(name, value, budget) {
  results[name] = { bytes: value, budget };
  if (value > budget) failures.push(`${name}: ${String(value)} B exceeds ${String(budget)} B`);
}

/** The served-log span of the Insights scenarios, `[first, end)`, or null when none ran. */
let insightsRange = null;
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

  // 3f. The Skill Tree (ADR-107), in a browser of its own: a card opened from the default view
  //     (the card's own cost is `cardAdds` above and must not change), then the tree shown,
  //     hidden and shown, the card closed and reopened, a player at another position, and the
  //     first player again. Only a reader's request fetches anything, and nothing twice.
  try {
    const climber = await browser.newContext();
    const treePage = await newPage(climber);
    const treeLog = record();
    await openDefault(treePage);
    const rows = treePage.locator("table.sheet tbody tr[data-player]");
    const openRow = async (index) => {
      await rows.nth(index).locator(".player-name").first().click();
      await treePage.getByRole("dialog").waitFor();
      await settle(treePage);
    };
    const cardPosition = async () =>
      (await treePage.getByRole("dialog").locator(".pos-tag").first().getAttribute("data-pos")) ?? "";
    const showTree = async () => {
      const before = treeLog.mark();
      await treePage.getByRole("dialog").getByRole("button", { name: "Show skill tree" }).click();
      await treePage.getByRole("dialog").getByRole("group", { name: /skill tree/ }).waitFor();
      await settle(treePage);
      return treeLog.since(before);
    };
    const closeCard = async () => {
      await treePage.keyboard.press("Escape");
      await treePage.getByRole("dialog").waitFor({ state: "hidden" });
    };
    await openRow(0);
    const first = await showTree();
    check("skillTreeAdds", sum(first), BUDGETS.skillTreeAdds);
    results.skillTreeAddsData = sum(first, isData);
    results.skillTreeAddsFiles = first.map((entry) => `${entry.path} ${String(entry.bytes)}`);

    mark = treeLog.mark();
    await treePage.getByRole("dialog").getByRole("button", { name: "Hide skill tree" }).click();
    await showTree();
    await closeCard();
    await openRow(0);
    await showTree();
    check("skillTreeRepeat", sum(treeLog.since(mark)), BUDGETS.skillTreeRepeat);

    // Another player whose position differs from the first one's (cards opened to find him are
    // the card's cost, not the tree's, and fall before the mark).
    const firstPosition = await cardPosition();
    await closeCard();
    for (let other = 1; other < 60; other += 1) {
      await openRow(other);
      if ((await cardPosition()) !== firstPosition) break;
      await closeCard();
    }
    const second = await showTree();
    check("skillTreeSwitch", sum(second), BUDGETS.skillTreeSwitch);
    results.skillTreeSwitchFiles = second.map((entry) => `${entry.path} ${String(entry.bytes)}`);
    await closeCard();
    mark = treeLog.mark();
    await openRow(0);
    await showTree();
    results.skillTreeReturn = sum(treeLog.since(mark));
    if (results.skillTreeReturn > 0) failures.push(`returning to the first player's tree fetched ${String(results.skillTreeReturn)} B`);
    await climber.close();
  } catch (error) {
    failures.push(`the Skill Tree scenarios could not run: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
  }

  // 3g. ESPN's roster/start history (ADR-112), in a browser of its own: a card opened from the
  //     default view (its cost is `cardAdds` and must not change), then the trend shown — one
  //     bucket file — then hidden and shown, and the card closed, reopened and shown again,
  //     which must fetch nothing.
  try {
    const watcher = await browser.newContext();
    const espnPage = await newPage(watcher);
    const espnLog = record();
    await openDefault(espnPage);
    const openFirst = async () => {
      await espnPage.locator("table.sheet tbody tr[data-player] .player-name").first().click();
      await espnPage.getByRole("dialog").waitFor();
      await settle(espnPage);
    };
    const showTrend = async () => {
      const before = espnLog.mark();
      await espnPage.getByRole("dialog").getByRole("button", { name: "Show ESPN trend" }).click();
      // The drawn chart, or the one sentence that replaces it: never a loading note, which
      // would end the wait before the chart's own code has arrived.
      await espnPage
        .getByRole("dialog")
        .locator("[data-testid='espn-ownership-chart'], .espn-history .section-note:has-text('No retained ESPN read')")
        .first()
        .waitFor();
      await settle(espnPage);
      return espnLog.since(before);
    };
    await openFirst();
    const cardOnly = espnLog.since(0).filter((entry) => entry.path.includes("espn_ownership_series"));
    if (cardOnly.length > 0) failures.push("opening a card fetched the ESPN history before it was asked for");
    const shown = await showTrend();
    check("ownershipHistoryAdds", sum(shown), BUDGETS.ownershipHistoryAdds);
    results.ownershipHistoryAddsData = sum(shown, isData);
    results.ownershipHistoryFiles = shown.map((entry) => `${entry.path} ${String(entry.bytes)}`);
    mark = espnLog.mark();
    await espnPage.getByRole("dialog").getByRole("button", { name: "Hide ESPN trend" }).click();
    await showTrend();
    await espnPage.keyboard.press("Escape");
    await espnPage.getByRole("dialog").waitFor({ state: "hidden" });
    await openFirst();
    await showTrend();
    check("ownershipHistoryRepeat", sum(espnLog.since(mark)), BUDGETS.ownershipHistoryRepeat);
    await watcher.close();
  } catch (error) {
    failures.push(`the ESPN history scenarios could not run: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
  }

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

  // My Leagues' scenarios run in browsers of their own, so nothing they do touches the reader
  // the repeat-visit and redeploy checks below follow. One that cannot run is a failure on the
  // list, not a crash, so `--report-only` still prints every other number.
  try {
    // 3c. My Leagues (ADR-106) from the default view: its code and stylesheet, the week's files
    //     for the active league's scoring, and the shared weekly context. The ROS block is the
    //     default view's. Then Rising Stars' evidence, then Improve's code (it reads only what
    //     is loaded), then the two other leagues' presets, then a second round of switches that
    //     must fetch nothing.
    const manager = await browser.newContext();
    await seedLeagues(manager);
    const leaguePage = await newPage(manager);
    const leagueLog = record();
    await openDefault(leaguePage);
    mark = leagueLog.mark();
    await leaguePage.getByRole("tab", { name: "My Leagues" }).click();
    await leagueShown(leaguePage, "12-team PPR");
    const opened = leagueLog.since(mark);
    check("myLeaguesAdds", sum(opened), BUDGETS.myLeaguesAdds);
    results.myLeaguesAddsData = sum(opened, isData);
    results.myLeaguesAddsFiles = opened.map((entry) => `${entry.path} ${String(entry.bytes)}`);

    mark = leagueLog.mark();
    await leaguePage.getByRole("checkbox", { name: "Rising Stars" }).check();
    await leaguePage.waitForFunction(() => {
      const lists = [...document.querySelectorAll(".lg-rising")];
      return lists.length > 0 && lists.every((list) => !(list.textContent ?? "").includes("Loading"));
    });
    await settle(leaguePage);
    const rising = leagueLog.since(mark);
    check("risingStarsAdds", sum(rising), BUDGETS.risingStarsAdds);
    results.risingStarsAddsFiles = rising.map((entry) => `${entry.path} ${String(entry.bytes)}`);

    mark = leagueLog.mark();
    await leaguePage.getByRole("button", { name: "Find upgrades" }).click();
    await leaguePage.getByRole("region", { name: "Upgrade ideas" }).waitFor();
    await settle(leaguePage);
    const improve = leagueLog.since(mark);
    check("improveAdds", sum(improve), BUDGETS.improveAdds);
    results.improveAddsData = sum(improve, isData);

    const switchTo = async (name, label) => {
      const before = leagueLog.mark();
      await leaguePage.getByRole("radio", { name: new RegExp(`^${name}`) }).click();
      await leagueShown(leaguePage, label);
      return sum(leagueLog.since(before));
    };
    const round = [
      ["Family", "10-team Half PPR"],
      ["Friends", "14-team Standard"],
      ["Office", "12-team PPR"],
    ];
    results.leagueSwitchFirst = {};
    for (const [name, label] of round) results.leagueSwitchFirst[name] = await switchTo(name, label);
    check("leagueSwitchNewPreset", Math.max(...Object.values(results.leagueSwitchFirst)), BUDGETS.leagueSwitchNewPreset);
    let repeated = 0;
    for (let cycle = 0; cycle < 2; cycle += 1) {
      for (const [name, label] of round) repeated += await switchTo(name, label);
    }
    check("leagueSwitchRepeat", repeated, BUDGETS.leagueSwitchRepeat);
    await manager.close();

    // Reported, not budgeted: the Opportunity Board opened from the default view, whose evidence
    // files are the ones Rising Stars reads.
    const scout = await browser.newContext();
    const scoutPage = await newPage(scout);
    const scoutLog = record();
    await openDefault(scoutPage);
    mark = scoutLog.mark();
    await scoutPage.getByRole("tab", { name: "Opportunity" }).click();
    await scoutPage.getByRole("table", { name: /opportunity board/i }).waitFor();
    await settle(scoutPage);
    results.opportunityAdds = sum(scoutLog.since(mark));
    results.opportunityAddsData = sum(scoutLog.since(mark), isData);
    // ADR-112: the one ESPN file a view reads, inside the figure above.
    results.opportunityEspnSlice = sum(scoutLog.since(mark), (entry) => entry.path.includes("/espn_ownership/"));
    if (scoutLog.since(mark).some((entry) => entry.path.includes("espn_ownership_series"))) {
      failures.push("opening the Opportunity Board fetched ESPN history files");
    }
    // ADR-113: the recent-form slice is the Opportunity Board's alone. The default view never
    // fetches it, opening the board fetches one scoring preset's slice, and switching windows
    // (and back) re-uses it — no request at all.
    // Every scenario above (first visits, Start/Sit, cards, Trade, My Leagues, Rising Stars,
    // Win My Matchup, YOLO, the ESPN history) ran before this mark.
    if (served.slice(0, mark).some((entry) => entry.path.includes("/recent_form/"))) {
      failures.push("a view other than the Opportunity Board fetched the recent-form slice");
    }
    check(
      "recentSlice",
      sum(scoutLog.since(mark), (entry) => entry.path.includes("/recent_form/")),
      BUDGETS.recentSlice,
    );
    const switchMark = scoutLog.mark();
    const lens = scoutPage.getByRole("radiogroup", { name: "Recent weeks" });
    for (const name of [/^Last 1 /, /^Last 6 /, /^Season to date/, /^Last 2 /, /^Last 4 /, /^Last 3 /]) {
      await lens.getByRole("radio", { name }).click();
      await scoutPage.getByRole("table", { name: /opportunity board/i }).waitFor();
    }
    await settle(scoutPage);
    check("recentWindowSwitch", sum(scoutLog.since(switchMark)), BUDGETS.recentWindowSwitch);
    await scout.close();

    // 3d. A cold first visit straight to My Leagues with the same leagues saved: the shell, the
    //     default preset's ROS block and the workspace — never another league's preset.
    const direct = await browser.newContext();
    await seedLeagues(direct);
    const directPage = await newPage(direct);
    mark = log.mark();
    await directPage.goto(`${site}?view=myleagues`, { waitUntil: "domcontentloaded" });
    await leagueShown(directPage, "12-team PPR");
    const cold = log.since(mark);
    check("myLeaguesFirstVisitTotal", sum(cold), BUDGETS.myLeaguesFirstVisitTotal);
    check("myLeaguesFirstVisitData", sum(cold, isData), BUDGETS.myLeaguesFirstVisitData);
    results.myLeaguesFirstVisitFiles = cold.map((entry) => `${entry.path} ${String(entry.bytes)}`);
    await direct.close();

    // 3e. Reported, not budgeted: a cold visit to My Leagues with nothing saved — the empty
    //     workspace fetches no preset-specific file.
    const newcomer = await browser.newContext();
    const emptyPage = await newPage(newcomer);
    mark = log.mark();
    await emptyPage.goto(`${site}?view=myleagues`, { waitUntil: "domcontentloaded" });
    await emptyPage.getByRole("button", { name: "Create a league" }).waitFor();
    await settle(emptyPage);
    const empty = log.since(mark);
    results.myLeaguesEmptyFirstVisitTotal = sum(empty);
    results.myLeaguesEmptyFirstVisitData = sum(empty, isData);
    await newcomer.close();
  } catch (error) {
    failures.push(`My Leagues' scenarios could not run: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
  }

  // 3g. Win My Matchup (ADR-110), in browsers of their own: a 12-team PPR league (the default
  //     view's block) with a complete opponent drawn from the build's own playable players.
  //     Opening the tool fetches its code and stylesheet only; the first Simulate fetches the
  //     worker; evaluating changes, switching tools and simulating the same inputs again fetch
  //     nothing; YOLO fetches the block's Opportunity rows and the role series. A direct link
  //     meets the first-visit envelope.
  try {
    const scenario = wmmScenario(dist, { base: args.basePath });
    const seedWmm = async (context) => {
      await context.addInitScript(
        ([leaguesKey, leagues, matchupsKey, matchups]) => {
          if (window.sessionStorage.getItem("wmm-seeded") === null) {
            window.localStorage.setItem(leaguesKey, leagues);
            window.localStorage.setItem(matchupsKey, matchups);
            window.sessionStorage.setItem("wmm-seeded", "1");
          }
        },
        [scenario.keys.leagues, leaguesDocument([scenario.league]), scenario.keys.matchups, JSON.stringify(scenario.matchup)],
      );
    };
    const coach = await browser.newContext();
    await seedWmm(coach);
    const wmmPage = await newPage(coach);
    const wmmLog = record();
    await openDefault(wmmPage);
    await wmmPage.getByRole("tab", { name: "My Leagues" }).click();
    await leagueShown(wmmPage, "12-team PPR");
    mark = wmmLog.mark();
    await wmmPage.getByRole("tab", { name: "Win My Matchup" }).click();
    await wmmPage.getByRole("heading", { name: /Win My Matchup — week/ }).waitFor();
    await settle(wmmPage);
    const wmmOpened = wmmLog.since(mark);
    check("wmmOpenAdds", sum(wmmOpened), BUDGETS.wmmOpenAdds);
    results.wmmOpenAddsData = sum(wmmOpened, isData);
    results.wmmOpenAddsFiles = wmmOpened.map((entry) => `${entry.path} ${String(entry.bytes)}`);

    mark = wmmLog.mark();
    await wmmPage.getByRole("button", { name: "Simulate" }).click();
    await wmmPage.locator(".wmm-headline").waitFor();
    await settle(wmmPage);
    const simulated = wmmLog.since(mark);
    check("wmmSimulateAdds", sum(simulated), BUDGETS.wmmSimulateAdds);
    results.wmmSimulateAddsFiles = simulated.map((entry) => `${entry.path} ${String(entry.bytes)}`);

    mark = wmmLog.mark();
    await wmmPage.getByRole("button", { name: "Evaluate lineup changes" }).click();
    await wmmPage.locator(".wmm-changes").waitFor();
    await wmmPage.getByRole("tab", { name: "Lineup" }).click();
    await wmmPage.locator(".lg-auto").waitFor();
    await wmmPage.getByRole("tab", { name: "Win My Matchup" }).click();
    await wmmPage.getByRole("button", { name: "Simulate" }).click();
    await wmmPage.locator(".wmm-headline").waitFor();
    await settle(wmmPage);
    check("wmmRepeat", sum(wmmLog.since(mark)), BUDGETS.wmmRepeat);

    mark = wmmLog.mark();
    await wmmPage.getByRole("checkbox", { name: "YOLO" }).check();
    await wmmPage.locator(".wmm-yolo .wmm-funnel, .wmm-yolo .notice").first().waitFor();
    await settle(wmmPage);
    const yolo = wmmLog.since(mark);
    check("yoloAdds", sum(yolo), BUDGETS.yoloAdds);
    results.yoloAddsFiles = yolo.map((entry) => `${entry.path} ${String(entry.bytes)}`);
    await coach.close();

    const direct = await browser.newContext();
    await seedWmm(direct);
    const directPage = await newPage(direct);
    mark = log.mark();
    await directPage.goto(`${site}?view=myleagues&panel=wmm`, { waitUntil: "domcontentloaded" });
    await directPage.getByRole("heading", { name: /Win My Matchup — week/ }).waitFor();
    await settle(directPage);
    const wmmCold = log.since(mark);
    check("wmmFirstVisitTotal", sum(wmmCold), BUDGETS.wmmFirstVisitTotal);
    check("wmmFirstVisitData", sum(wmmCold, isData), BUDGETS.wmmFirstVisitData);
    await direct.close();
  } catch (error) {
    failures.push(`Win My Matchup's scenarios could not run: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
  }

  // 3h. Insights (ADR-116), in a browser of its own: the tab opened from the default view — its
  //     code, stylesheet and one scoring preset's stories — then the share view, whose code
  //     loads only when a reader opens it. A size model with no stories says so and is skipped.
  try {
    const manifest = JSON.parse(readFileSync(join(dist, "data", "manifest.json"), "utf-8"));
    if (manifest.artifacts?.insights === undefined) {
      results.insightsNote = "this build publishes no insights.json: the Insights budgets were not measured";
    } else {
      const reader2 = await browser.newContext();
      const insightsPage = await newPage(reader2);
      const insightsLog = record();
      await openDefault(insightsPage);
      const start = insightsLog.mark();
      await insightsPage.getByRole("tab", { name: "Insights" }).click();
      await insightsPage.getByRole("heading", { name: "Insights", level: 2 }).waitFor();
      await insightsPage.locator(".ins-story, .ins-state").first().waitFor();
      await settle(insightsPage);
      const opened = insightsLog.since(start);
      check("insightsAdds", sum(opened), BUDGETS.insightsAdds);
      results.insightsAddsData = sum(opened, isData);
      results.insightsAddsFiles = opened.map((entry) => `${entry.path} ${String(entry.bytes)}`);
      check("insightsSlice", sum(opened, (entry) => entry.path.includes("/insights/")), BUDGETS.insightsSlice);
      for (const heavy of ["weekly_projections", "/serve/card/", "skill_tree", "player_usage", "espn_ownership_series", "/insight_evidence/"]) {
        if (opened.some((entry) => entry.path.includes(heavy))) failures.push(`opening Insights fetched ${heavy}`);
      }
      // A story's Evidence: the preset's evidence slice, once — a second story reuses it.
      const evidenceMark = insightsLog.mark();
      const stories = insightsPage.locator(".ins-story");
      if ((await stories.count()) > 0) {
        for (const index of [0, 1]) {
          const story = stories.nth(index);
          if ((await story.count()) === 0) continue;
          await story.getByRole("button", { name: "Evidence" }).click();
          await story.locator(".ins-evidence .ins-table").first().waitFor();
          await story.getByText("Loading the evidence…").waitFor({ state: "detached" });
        }
        await settle(insightsPage);
        const expanded = insightsLog.since(evidenceMark);
        check("insightsEvidenceAdds", sum(expanded), BUDGETS.insightsEvidenceAdds);
        results.insightsEvidenceFiles = expanded.map((entry) => `${entry.path} ${String(entry.bytes)}`);
        if (expanded.filter((entry) => entry.path.includes("/insight_evidence/")).length > 1) {
          failures.push("expanding a second story fetched the evidence slice again");
        }
      }
      const shareMark = insightsLog.mark();
      await insightsPage.locator(".ins-story").first().getByRole("button", { name: "Share" }).click();
      await insightsPage.locator(".ins-share-preview[data-ready]").waitFor();
      await settle(insightsPage);
      const shared = insightsLog.since(shareMark);
      check("insightsShareAdds", sum(shared, (entry) => entry.path.endsWith(".js")), BUDGETS.insightsShareAdds);
      results.insightsShareAddsTotal = sum(shared);
      results.insightsShareFiles = shared.map((entry) => `${entry.path} ${String(entry.status)} ${String(entry.bytes)}`);
      insightsRange = [start, insightsLog.mark()];
      await reader2.close();

      // Reported, not budgeted: a cold first visit straight to a shared story link.
      const linked = await browser.newContext();
      const linkedPage = await newPage(linked);
      const coldMark = log.mark();
      const first = await (async () => {
        await linkedPage.goto(`${site}?view=insights`, { waitUntil: "domcontentloaded" });
        await linkedPage.locator(".ins-story, .ins-state").first().waitFor();
        await settle(linkedPage);
        return log.since(coldMark);
      })();
      results.insightsFirstVisitTotal = sum(first);
      results.insightsFirstVisitData = sum(first, isData);
      insightsRange = [insightsRange[0], log.mark()];
      await linked.close();
    }
  } catch (error) {
    failures.push(`the Insights scenarios could not run: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
  }
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

  // ADR-116: the stories slice is the Insights tab's alone — every scenario above, first visits,
  // cards, Start/Sit, Trade, My Leagues, Win My Matchup, the repeat visit and the redeploys, ran
  // without fetching it.
  const strays = served.filter(
    (entry, index) =>
      (entry.path.includes("/insights/") || entry.path.includes("/insight_evidence/")) &&
      (insightsRange === null || index < insightsRange[0] || index >= insightsRange[1]),
  );
  if (strays.length > 0) failures.push(`a view other than Insights fetched an Insights slice (${strays[0].path})`);
} finally {
  await browser.close();
  server.close();
  rmSync(work, { recursive: true, force: true });
}

const report = { site: args.dist, budgets: BUDGETS, results, failures };
const printable = {
  ...report,
  results: { ...results, firstVisitFiles: undefined, myLeaguesFirstVisitFiles: undefined },
};
console.log(JSON.stringify(printable, null, 1));
if (args.json !== null) writeFileSync(args.json, `${JSON.stringify(report, null, 1)}\n`);
if (failures.length > 0 && !args.reportOnly) process.exit(1);
