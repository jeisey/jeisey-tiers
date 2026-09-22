/**
 * Cross-check the rendered board against the artifact bytes, on the real 2026 build.
 *
 * The unit and end-to-end suites prove agreement on fixtures. This proves it on the data the
 * site will actually serve, which is the Phase-6 exit gate's own wording.
 */
import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

import { blockPortraits } from "./portrait-stub.mjs";

const BASE = process.argv[2] ?? "http://localhost:4180";
const dataDir = process.argv[3] ?? "web/dist-real/data";
const tiers = JSON.parse(readFileSync(`${dataDir}/tiers.json`, "utf-8"));
const arb = JSON.parse(readFileSync(`${dataDir}/arbitrage.json`, "utf-8"));
const status = JSON.parse(readFileSync(`${dataDir}/player_status.json`, "utf-8"));
/**
 * The retained per-market histories, if this build published any.
 *
 * Optional on purpose: a young store has no history to publish and the board is correct
 * without one. What is *not* optional is that a published history agrees with the card that
 * draws it — the check below opens a card per market and compares the chart's marks with
 * these bytes, because "the chart is right" was the one claim the 2026-09 refreshes could
 * not make (ADR-081).
 */
let seriesRecords = [];
try {
  seriesRecords = JSON.parse(readFileSync(`${dataDir}/market_trend_series.json`, "utf-8")).records;
} catch {
  seriesRecords = [];
}

/**
 * The rest-of-season board, if this build published one.
 *
 * Optional in the same sense the market history is: before kickoff, and in the two windows
 * ADR-079 describes, not publishing one is the correct behaviour. Present, it is not an
 * extra — it is the board a visitor lands on, because `view=auto` resolves to it once the
 * season has started. Its presence here is also how this file knows which board the bare
 * URL should open, which is checked rather than assumed.
 */
let rosRecords = null;
try {
  rosRecords = JSON.parse(readFileSync(`${dataDir}/ros_tiers.json`, "utf-8")).records;
} catch {
  rosRecords = null;
}
const publishedInSeason = rosRecords !== null;

/**
 * The opportunity artifact, which is where a Pick-of-the-Week card's numbers come from.
 *
 * Optional for the same reason the two above are: a build with no behaviour capture publishes
 * no opportunity board, and that is a degradation the product states rather than a defect.
 */
let opportunityRecords = null;
try {
  opportunityRecords = JSON.parse(
    readFileSync(`${dataDir}/inseason_opportunity.json`, "utf-8"),
  ).records;
} catch {
  opportunityRecords = null;
}

/**
 * The retained add/drop window (ADR-089).
 *
 * Optional a level below the board above it: a build can publish an Opportunity Board and no
 * series at all — the feed carried nobody inside the window, or the store was unreadable —
 * and that costs a sparkline rather than a board. Absent here means the momentum checks below
 * do not run, which is correct; a *present* artifact that disagrees with the page is a
 * failure, which is the whole point of reading it.
 */
let behaviorSeries = null;
try {
  behaviorSeries = JSON.parse(
    readFileSync(`${dataDir}/behavior_trend_series.json`, "utf-8"),
  ).records;
} catch {
  behaviorSeries = null;
}

/**
 * The signal layer (ADR-091): observed role week by week, and each team's next game.
 *
 * Optional one level below the boards, like the momentum series: a build whose signal
 * builders failed publishes neither and says so on every card. A *present* artifact that
 * disagrees with the card drawing it is a failure, and so is the one defect the layer exists
 * to remove — a quarterback's card leading with a snap or target share.
 */
let playerUsage = null;
try {
  playerUsage = JSON.parse(readFileSync(`${dataDir}/player_usage.json`, "utf-8")).records;
} catch {
  playerUsage = null;
}
let teamMatchups = null;
try {
  teamMatchups = JSON.parse(readFileSync(`${dataDir}/team_matchups.json`, "utf-8")).records;
} catch {
  teamMatchups = null;
}

const block = tiers.records
  .filter((r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR")
  .sort((a, b) => a.fair_rank - b.fair_rank);

/**
 * Every tier the block publishes, so the board is opened from the artifact rather than from
 * an assumption about how deep the default open set reaches.
 *
 * The Phase-8 board collapses tiers past the draft-relevant top. A checker that assumed the
 * first N players are always rendered would be pinning today's tier sizes — exactly the
 * class of assertion this file was corrected for once already. Reading the ordinals out of
 * `tiers.json` and asking for all of them is the contract-shaped way to say "show me the
 * whole board".
 */
const allTiers = [...new Set(block.map((r) => r.tier_ordinal))].sort((a, b) => a - b).join(".");

/**
 * The draft Tier Board, named rather than assumed, with every tier open.
 *
 * `view` defaults to `auto`, and `auto` is not a synonym for the Tier Board: it resolves to
 * the draft board before kickoff and to the **ROS** board after it (`web/src/data/state.ts`).
 * Omitting the parameter therefore meant "the Tier Board" for exactly as long as the season
 * had not started. On 2026-09-15 it stopped meaning that, and every check in this file ran
 * against the rest-of-season board by accident — no column it looked for existed, so it
 * reported 0 of 40 tier rows, 25 missing chart marks and 57 missing badges against a page
 * that was correct (ADR-084).
 *
 * Naming the view is the same correction this file has taken three times before: assert the
 * contract, not the day's data. What `auto` resolves to is now a check of its own, below.
 */
const OPEN_ALL = `?view=tiers&tiers=${allTiers}`;
const rosBlock = (rosRecords ?? [])
  .filter((r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR")
  .sort((a, b) => a.ros_fair_rank - b.ros_fair_rank);
const arbBlock = arb.records
  .filter((r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR")
  .sort((a, b) => b.arbitrage_score - a.arbitrage_score);
const statusById = new Map(status.records.map((r) => [r.player_id, r]));

/**
 * What the Trend cell must start with, given the artifact's own value.
 *
 * This used to assert an em dash on every row, which was true in Phase 6 only because the
 * store was too young for ADR-042 — three observation days spanning three days — and so
 * every `market_trend` was null. The first build with a real trend then failed a check that
 * was pinning the launch condition rather than the contract. A null trend must still render
 * as an em dash and never as `0`, because an absence of evidence is not evidence of no
 * change; a present one must render its own number, signed, with the direction arrow.
 *
 * Mirrors `formatSigned` and `describeTrend` in `web/src/data/`, including U+2212 MINUS SIGN
 * and the unsigned-zero case.
 */
function expectedTrendCell(trend) {
  if (trend === null || trend === undefined) return "—";
  const magnitude = Math.abs(trend).toFixed(2);
  const value = Number(magnitude) === 0 ? magnitude : `${trend > 0 ? "+" : "\u2212"}${magnitude}`;
  const arrow = trend > 0 ? "↑" : trend < 0 ? "↓" : "";
  return `${arrow}${value}`;
}

/**
 * Column indices read from the header row, never counted by hand.
 *
 * Counting is how the 2026-09-03 daily refresh broke. Phase 10 inserted Dispersion, FP ECR
 * and Spread into the arbitrage table, `Score` and `Trend` slid two columns right, and this
 * file went on reading positions 8 and 9 — so every arbitrage row failed against a build that
 * was correct. Worse, the Trend check had by then been comparing an em dash in the Spread
 * column against the em dash it expected in Trend, and *passed* while measuring nothing: a
 * positional check does not only break loudly, it can agree for the wrong reason.
 *
 * A header lookup says what the check means — "the Score column" — and a renamed or dropped
 * column fails once, by name, listing the headers actually found, instead of silently reading
 * whatever is now next door.
 */
function columnLookup(headerTexts) {
  // The sort indicator lives inside the `th`. It is presentation, not identity.
  const labels = headerTexts.map((text) => text.replace(/[\u25b2\u25bc]/g, "").trim());
  const missing = [];
  return {
    /** `match` exists for a header whose text is data — the ADP column names its source. */
    at(label, match = (text) => text === label) {
      const index = labels.findIndex(match);
      if (index < 0) missing.push(label);
      return index;
    },
    problem(table) {
      if (missing.length === 0) return null;
      return `${table} table: no column headed ${missing.join(", ")} — saw ${labels.join(" | ")}`;
    },
  };
}

const headerTexts = (page) =>
  page.$$eval("table.sheet thead th", (ths) => ths.map((th) => th.textContent.trim()));


/**
 * The market the page is showing, and that source's quote for one record.
 *
 * The verifier used to compare the rendered ADP cell against the flat V1 `market_adp`, which
 * is MyFantasyLeague's. That was correct for exactly as long as there was one market. The
 * first refresh after a second one went live failed all thirty rows against a page that was
 * right: the board defaults to FFC, whose seven-day window prices a riser earlier than MFL's
 * season aggregate (ADR-067).
 *
 * So the source is read from the column heading the page rendered — the same header lookup
 * the column indices come from — and the expected value from that source's own entry in
 * `markets`. A record the selected market did not price has no cell to check; the page shows
 * an em dash, which is a real state rather than a missing number.
 */
function shownSource(header) {
  const label = header.replace(/\u25b2|\u25bc/g, "").trim();
  if (label === "Median ADP") return null; // cross-market: no single source to check against
  for (const [sourceId, name] of Object.entries(MARKET_LABELS)) {
    if (label === `${name} ADP`) return sourceId;
  }
  return null;
}

/** That source's quote, or `null` when it did not price him. */
function quoteFor(record, sourceId) {
  if (sourceId === null) return null;
  const markets = Array.isArray(record.markets) ? record.markets : [];
  return markets.find((entry) => entry.source_id === sourceId) ?? null;
}

/** Kept in step with `web/src/data/multimarket.ts`; a rename there must land here too. */
const MARKET_LABELS = {
  myfantasyleague_adp: "MFL Cumulative",
  fantasyfootballcalculator_adp: "FFC Recent",
};

const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
// This verifier stands between a build and the deployed site, so it may not depend on
// anybody else's uptime. The card falls back to its monogram and every number it checks is
// unaffected (ADR-087).
await blockPortraits(page);
const failures = [];

// --- Tier table rows against the artifact -------------------------------------------------
await page.goto(`${BASE}/${OPEN_ALL}`, { waitUntil: "networkidle" });
await page.waitForSelector("table.sheet tbody tr");
const rows = await page.$$eval("table.sheet tbody tr", (trs) =>
  trs.slice(0, 40).map((tr) => ({
    cells: [...tr.querySelectorAll("td")].map((td) => td.textContent.trim()),
    // The name is the button, and the injury badge is its sibling. Reading the name from its
    // own element rather than stripping the badge out of the cell text is not a tidiness
    // preference: the badge reads `IR · Knee` when a body part is reported and a bare `IR`
    // when one is not, so any strip pattern is a bet on today's injury reports. The badge is
    // checked on its own terms further down.
    name: tr.querySelector(".player-name")?.textContent?.trim() ?? null,
  })),
);
const tierColumn = columnLookup(await headerTexts(page));
const tierAt = {
  rank: tierColumn.at("Rank"),
  expectedVorp: tierColumn.at("Exp VORP"),
  medianVorp: tierColumn.at("Median VORP"),
  interquartile: tierColumn.at("P25\u2013P75 VORP"),
  expectedPoints: tierColumn.at("Exp FP"),
};
const tierProblem = tierColumn.problem("tier");
if (tierProblem !== null) failures.push(tierProblem);
else {
  rows.forEach(({ cells, name }, i) => {
    const record = block[i];
    const expect = (label, got, want) => {
      if (got !== want) {
        failures.push(`tier row ${i + 1} ${label}: rendered ${got}, artifact ${want}`);
      }
    };
    expect("fair_rank", cells[tierAt.rank], String(record.fair_rank));
    expect("name", name, record.display_name);
    expect("expected_vorp", cells[tierAt.expectedVorp], record.expected_vorp.toFixed(1));
    expect("p50_vorp", cells[tierAt.medianVorp], record.p50_vorp.toFixed(1));
    const iqr = `${record.p25_vorp.toFixed(1)} \u2013 ${record.p75_vorp.toFixed(1)}`;
    expect("iqr", cells[tierAt.interquartile], iqr);
    expect("expected_points", cells[tierAt.expectedPoints], record.expected_points.toFixed(1));
  });
}

// --- Tier board rows against the artifact ---------------------------------------------------
const marks = await page.$$eval(".board-row", (gs) => gs.map((g) => g.getAttribute("aria-label")));
for (const record of block.slice(0, 25)) {
  const label = marks.find((l) => l.startsWith(`${record.display_name},`));
  if (!label) {
    failures.push(`tier chart: no mark for ${record.display_name}`);
    continue;
  }
  if (!label.includes(`median simulated VORP ${record.p50_vorp.toFixed(1)}`)) {
    failures.push(`tier chart ${record.display_name}: p50 label disagrees with artifact`);
  }
  if (!label.includes(`P25 to P75 ${record.p25_vorp.toFixed(1)} to ${record.p75_vorp.toFixed(1)}`)) {
    failures.push(`tier chart ${record.display_name}: interval label disagrees with artifact`);
  }
  if (!label.includes(`fair rank ${record.fair_rank}`)) {
    failures.push(`tier chart ${record.display_name}: fair rank label disagrees with artifact`);
  }
}

// --- The board a bare link opens, and the ROS board against its artifact --------------------
//
// Two claims, and the first is the one whose absence let 2026-09-15 happen. Every check above
// names `view=tiers`; nothing named `auto`, so nothing established which board `auto` is. It
// was invisible while the season had not started, because before kickoff the two resolve to
// the same board — a check that agrees for the wrong reason, which this file has met before.
//
// The second claim is the larger gap the failure exposed. The rest-of-season board is what a
// visitor sees from September onward, and until now it was the one published board no
// pre-deploy gate compared against its own bytes. A green refresh could have shipped it
// wrong (ADR-084).
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.waitForSelector("table.sheet thead th");
const defaultHeaders = (await headerTexts(page)).map((text) =>
  text.replace(/[\u25b2\u25bc]/g, "").trim(),
);
// `ROS Rank` is never `Rank` (`web/src/app/RosTable.tsx`), so the heading names the board.
const defaultBoard = defaultHeaders.includes("ROS Rank") ? "ros" : "tiers";
const expectedDefault = publishedInSeason ? "ros" : "tiers";
if (defaultBoard !== expectedDefault) {
  failures.push(
    `default view: a bare link opened the ${defaultBoard} board, but this build ` +
      `${publishedInSeason ? "published a" : "published no"} rest-of-season bundle, so ` +
      `\`view=auto\` should resolve to ${expectedDefault} — saw ${defaultHeaders.join(" | ")}`,
  );
}

let rosRowsChecked = 0;
if (publishedInSeason && defaultBoard === "ros") {
  // No `tiers` parameter: the ROS view renders its rows straight, with no collapsed bands to
  // open (`web/src/app/RosView.tsx`), so asking for one would be inventing a control.
  const rosRendered = await page.$$eval("table.sheet tbody tr", (trs) =>
    trs.slice(0, 40).map((tr) => ({
      cells: [...tr.querySelectorAll("td")].map((td) => td.textContent.trim()),
      // Read from its own element, for the reason the draft board reads it that way: the
      // long-absence badge is the name button's sibling and stripping it would be a bet on
      // today's absences.
      name: tr.querySelector(".player-name")?.textContent?.trim() ?? null,
      // Current status is a badge on the name rather than a column of its own (ADR-085), and
      // it renders only for a code that says something. `null` therefore means two different
      // things — `ACT`, and a status the artifact did not carry — which is why the check below
      // is a contract about noteworthiness rather than a cell comparison.
      status: tr.querySelector(".player-cell .status-badge span[aria-hidden]")?.textContent?.trim() ?? null,
    })),
  );
  const rosColumn = columnLookup(defaultHeaders);
  // `\u0394 vs preseason` and `Weeks since last game` are deliberately absent from this
  // lookup. They render sentences the component chooses — "Played latest week", "No
  // appearances" — and restating that table here would make the check a transcription of the
  // code it checks and a second place to forget it, which is why ADR-082 left the badge
  // abbreviations in `web/src/data/model.ts`. Unlike the badge abbreviations, though, nothing
  // else covers them yet: `rankChangeLabel` is exported from `web/src/data/ros.ts` with no
  // unit test, and the weeks-since cell is inline in `RosTable`. Recorded in `TASKS.md`; the
  // fix belongs in a component test, not here.
  const rosAt = {
    rank: rosColumn.at("ROS Rank"),
    expectedVorp: rosColumn.at("ROS Exp VORP"),
    interquartile: rosColumn.at("ROS P25\u2013P75"),
    expectedPoints: rosColumn.at("Rem FP"),
    expectedGames: rosColumn.at("Rem G"),
    uncertainty: rosColumn.at("Uncertainty"),
  };
  const rosProblem = rosColumn.problem("ROS");
  if (rosProblem !== null) failures.push(rosProblem);
  else {
    rosRowsChecked = rosRendered.length;
    rosRendered.forEach((rendered, i) => {
      const { cells, name } = rendered;
      const record = rosBlock[i];
      if (record === undefined) {
        failures.push(`ROS row ${i + 1}: rendered ${name ?? "?"}, artifact publishes no such row`);
        return;
      }
      const expect = (label, got, want) => {
        if (got !== want) {
          failures.push(`ROS row ${i + 1} ${label}: rendered ${got}, artifact ${want}`);
        }
      };
      expect("ros_fair_rank", cells[rosAt.rank], String(record.ros_fair_rank));
      expect("name", name, record.display_name);
      expect("ros_expected_vorp", cells[rosAt.expectedVorp], record.ros_expected_vorp.toFixed(1));
      const iqr = `${record.ros_vorp_p25.toFixed(1)} \u2013 ${record.ros_vorp_p75.toFixed(1)}`;
      expect("ros_interval", cells[rosAt.interquartile], iqr);
      expect("ros_expected_points", cells[rosAt.expectedPoints], record.ros_expected_points.toFixed(1));
      expect("ros_expected_games", cells[rosAt.expectedGames], record.ros_expected_games.toFixed(1));
      expect("ros_uncertainty", cells[rosAt.uncertainty], record.ros_uncertainty.toFixed(1));

      /*
       * The status badge, as a contract rather than as a list of codes.
       *
       * ADR-082 failed this repository on a badge that was correct, because the check
       * enumerated the roster codes an August feed happened to publish. The rule here is the
       * one that survives a feed publishing something new: the badge exists exactly when the
       * artifact's `current_status` is a code the product treats as noteworthy, and when it
       * exists its text is that code verbatim. `ACT`, `A01` and `DEV` are the ordinary cases
       * and produce nothing — which is the point of the change, not a gap in it.
       */
      const code = (record.current_status ?? "").trim().toUpperCase();
      const noteworthy = code !== "" && !["ACT", "A01", "DEV"].includes(code);
      if (noteworthy && rendered.status === null) {
        failures.push(
          `ROS row ${i + 1}: artifact reports current_status "${code}" and no badge is rendered`,
        );
      }
      if (!noteworthy && rendered.status !== null) {
        failures.push(
          `ROS row ${i + 1}: badge "${rendered.status}" but the artifact's current_status ` +
            `${code === "" ? "is absent" : `is the ordinary code "${code}"`}`,
        );
      }
      if (noteworthy && rendered.status !== null && rendered.status !== code) {
        failures.push(
          `ROS row ${i + 1} current_status: badge reads ${rendered.status}, artifact ${code}`,
        );
      }
    });
  }
}

// --- Arbitrage table and rail against the artifact -----------------------------------------
await page.goto(`${BASE}/?view=arbitrage`, { waitUntil: "networkidle" });
await page.waitForSelector("table.sheet tbody tr");
const arbRows = await page.$$eval("table.sheet tbody tr", (trs) =>
  trs.slice(0, 30).map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent.trim())),
);
const arbColumn = columnLookup(await headerTexts(page));
const arbAt = {
  fairRank: arbColumn.at("Fair Rank"),
  // The selected market names its own column — "FFC Recent ADP", "MFL Cumulative ADP", or
  // "Median ADP" for the cross-market view — so this is the one header matched by shape.
  adp: arbColumn.at("… ADP", (text) => text.endsWith("ADP")),
  score: arbColumn.at("Score"),
  trend: arbColumn.at("Trend"),
};
const arbHeaders = await headerTexts(page);
const arbSource = shownSource(
  arbHeaders.find((text) => text.replace(/\u25b2|\u25bc/g, "").trim().endsWith("ADP")) ?? "",
);
const arbProblem = arbColumn.problem("arbitrage");
if (arbProblem !== null) failures.push(arbProblem);
else {
  arbRows.forEach((cells, i) => {
    const record = arbBlock[i];
    const rank = cells[arbAt.fairRank];
    const adp = cells[arbAt.adp];
    const score = cells[arbAt.score];
    if (rank !== String(record.fair_rank)) {
      failures.push(`arb row ${i + 1} fair_rank: rendered ${rank}, artifact ${record.fair_rank}`);
    }
    // Compared against the market the heading names, falling back to the flat V1 field only
    // when the record carries no `markets` array at all.
    const quote = quoteFor(record, arbSource);
    const wantAdp =
      arbSource === null
        ? record.market_adp.toFixed(1)
        : quote === null
          ? "\u2014"
          : quote.market_adp.toFixed(1);
    if (adp !== wantAdp) {
      failures.push(`arb row ${i + 1} adp: rendered ${adp}, artifact ${wantAdp}`);
    }
    if (score !== record.arbitrage_score.toFixed(1)) {
      const want = record.arbitrage_score.toFixed(1);
      failures.push(`arb row ${i + 1} score: rendered ${score}, artifact ${want}`);
    }
    // The Trend column reads the market the heading names, exactly as the ADP column does.
    // It used to read the flat V1 field — MyFantasyLeague's — so a default FFC board printed
    // one market's price beside another market's movement on every row (ADR-081).
    const trend = expectedTrendCell(
      arbSource === null ? record.market_trend : (quote?.market_trend ?? null),
    );
    if (!cells[arbAt.trend].startsWith(trend)) {
      failures.push(`arb row ${i + 1} trend: rendered ${cells[arbAt.trend]}, artifact wants ${trend}`);
    }
  });
}
const railLabels = await page.$$eval(".rail-row", (gs) => gs.map((g) => g.getAttribute("aria-label")));
for (const record of arbBlock.filter((r) => r.rank_gap > 0).slice(0, 20)) {
  const label = railLabels.find((l) => l.startsWith(`${record.display_name},`));
  if (!label) { failures.push(`rail: no mark for ${record.display_name}`); continue; }
  if (!label.includes(`fair rank ${record.fair_rank}`)) failures.push(`rail ${record.display_name}: fair anchor`);
  const railQuote = quoteFor(record, arbSource);
  const railAdp = arbSource === null ? record.market_adp : (railQuote?.market_adp ?? null);
  if (railAdp !== null && !label.includes(`ADP ${railAdp.toFixed(1)}`)) {
    failures.push(`rail ${record.display_name}: market anchor`);
  }
}

// --- The player card's market history against `market_trend_series.json` ---------------------
//
// Opened once per published market plus the cross view. The comparison is against the *bytes*
// this build wrote, not against a recomputation: a chart that agreed with a fresh calculation
// but not with the artifact would look right in every test and be wrong on the site.
const chartedMarkets = [];
if (seriesRecords.length > 0) {
  const inBlock = seriesRecords.filter(
    (r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR",
  );
  const bySource = new Map();
  for (const record of inBlock) {
    if (!bySource.has(record.market_source_id)) bySource.set(record.market_source_id, new Map());
    bySource.get(record.market_source_id).set(record.player_id, record);
  }
  if (bySource.has("cross")) {
    failures.push("market_trend_series carries a `cross` source; no capture produces one");
  }

  // A player every published market priced, so the selector is the only thing that varies.
  const subject = arbBlock.find((row) =>
    [...bySource.keys()].every((source) => bySource.get(source).has(row.player_id)),
  );
  if (subject === undefined) {
    failures.push("no published player has a retained history in every market");
  } else {
    for (const source of bySource.keys()) {
      const record = bySource.get(source).get(subject.player_id);
      await page.goto(`${BASE}/?view=tiers&market=${source}&scoring=ppr&teams=12`, {
        waitUntil: "networkidle",
      });
      await page.waitForSelector("table.sheet tbody tr");
      await page.getByRole("button", { name: subject.display_name, exact: true }).first().click();
      await page.waitForSelector("dialog[open]");
      const chart = await page.$('[data-testid="market-trend"]');
      if (chart === null) {
        failures.push(`${source}: a published history for ${subject.display_name} draws no chart`);
        continue;
      }
      const drawn = await chart.$$eval("g[data-source]", (gs) =>
        gs.map((g) => g.getAttribute("data-source")),
      );
      if (drawn.join(",") !== source) {
        failures.push(`${source}: the card drew ${drawn.join(",") || "nothing"} instead`);
      }
      // One mark per retained calendar day, latest-of-day, at the artifact's own prices.
      const byDay = new Map();
      for (const point of record.points) byDay.set(point.observed_at.slice(0, 10), point.market_adp);
      const labels = await chart.$$eval("circle[role='button']", (nodes) =>
        nodes.map((node) => node.getAttribute("aria-label") ?? ""),
      );
      if (labels.length !== byDay.size) {
        failures.push(
          `${source}: ${String(labels.length)} marks drawn for ${String(byDay.size)} retained days`,
        );
      }
      for (const [day, adp] of byDay) {
        const readable = new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          timeZone: "UTC",
        });
        if (!labels.some((l) => l.includes(readable) && l.includes(`ADP ${adp.toFixed(1)}`))) {
          failures.push(`${source}: no mark for ${readable} at ADP ${adp.toFixed(1)}`);
        }
      }
      // The latest reading, which is also the ADP the card prints beside the chart.
      const latest = record.points.at(-1)?.market_adp;
      const reading = await chart.$eval(".trend-reading", (node) => node.textContent?.trim() ?? "");
      if (latest !== undefined && !reading.endsWith(latest.toFixed(1))) {
        failures.push(`${source}: chart reads "${reading}", artifact's latest is ${latest.toFixed(1)}`);
      }
      // The slope the legend prints is this market's own, or the reason there is not one.
      const legend = await chart.$eval(".trend-legend", (node) => node.textContent ?? "");
      const wanted =
        record.market_trend === null
          ? "trend collecting"
          : `${record.market_trend > 0 ? "+" : ""}${record.market_trend.toFixed(2)}/day`;
      if (!legend.includes(wanted)) {
        failures.push(`${source}: legend "${legend.trim()}" does not carry ${wanted}`);
      }
      chartedMarkets.push(source);
    }

    // The cross view overlays every real series and invents none.
    await page.goto(`${BASE}/?view=tiers&market=cross&scoring=ppr&teams=12`, {
      waitUntil: "networkidle",
    });
    await page.waitForSelector("table.sheet tbody tr");
    await page.getByRole("button", { name: subject.display_name, exact: true }).first().click();
    await page.waitForSelector("dialog[open]");
    const crossDrawn = await page.$$eval('[data-testid="market-trend"] g[data-source]', (gs) =>
      gs.map((g) => g.getAttribute("data-source")).sort(),
    );
    if (crossDrawn.join(",") !== [...bySource.keys()].sort().join(",")) {
      failures.push(
        `cross view drew ${crossDrawn.join(",") || "nothing"}, expected ${[...bySource.keys()].sort().join(",")}`,
      );
    }
  }
}

// --- Injury badges against the status artifact ----------------------------------------------
await page.goto(`${BASE}/${OPEN_ALL}`, { waitUntil: "networkidle" });
const badges = await page.$$eval("table.sheet tbody tr", (trs) =>
  trs.map((tr) => ({
    name: tr.querySelector(".player-name")?.textContent?.trim(),
    badge: tr.querySelector(".status-badge span[aria-hidden]")?.textContent?.trim() ?? null,
  })),
);
/**
 * Everything the status artifact says about a player, in its own words.
 *
 * A badge is not an injury report. It renders whenever the artifact carries *something*, and
 * a reserve, exempt or inactive roster code is something (ADR-043). This check used to encode
 * that as a list of the badge texts it expected to see — `RES|CUT|E14|INJU|NOTE` — which is a
 * third instance of the species already recorded twice against this file: a verification
 * check must assert the contract, not the day's data. nflverse publishes a code for every
 * non-ordinary roster state, the in-season feed emits `INA` for a player declared inactive,
 * and the 2026-09-12 refresh failed on a badge that was correct.
 *
 * So the condition is re-derived from the bytes instead. `ACT`/`A01`/`DEV` and a Sleeper
 * status of `Active` are the ordinary cases and say nothing; every other value the record
 * carries is an annotation the board is entitled to mark, and the badge must appear for
 * exactly those players.
 *
 * What is deliberately *not* re-derived here is the abbreviation table — `Questionable`
 * renders `Q`, `Injured Reserve` renders `IR`. A copy of it in this file would make the check
 * a transcription of the code it is checking, and a second place to forget. The badge's other
 * half is quoted from the artifact verbatim, so that half is compared literally.
 */
const ORDINARY_ROSTER_STATUS = new Set(["ACT", "A01", "DEV"]);

function annotationsBehind(status) {
  if (!status) return [];
  const carried = [];
  for (const field of ["injury_status", "injury_body_part", "injury_notes", "practice_participation"]) {
    const value = status[field];
    if (value !== null && value !== undefined && String(value).trim() !== "") {
      carried.push(`${field}=${value}`);
    }
  }
  const sleeper = status.sleeper_status;
  if (sleeper && sleeper.toLowerCase() !== "active") carried.push(`sleeper_status=${sleeper}`);
  const roster = status.roster_status;
  if (roster && !ORDINARY_ROSTER_STATUS.has(roster.toUpperCase())) {
    carried.push(`roster_status=${roster}`);
  }
  return carried;
}

/** The badge reads `IR \u00b7 Knee` when a body part is reported and a bare `IR` when one is not. */
function badgeBodyPart(badge) {
  const parts = badge.split(" \u00b7 ");
  return parts.length === 1 ? null : parts.slice(1).join(" \u00b7 ");
}

/**
 * The rendered row carries a name; the artifact is keyed by id. A name the block publishes
 * twice is skipped rather than guessed at, because a wrong join would report a badge failure
 * about a player the row is not.
 */
const recordByName = new Map();
for (const record of block) {
  recordByName.set(record.display_name, recordByName.has(record.display_name) ? null : record);
}

for (const row of badges) {
  const record = recordByName.get(row.name) ?? null;
  if (record === null) continue;
  const statusRecord = statusById.get(record.player_id);
  const carried = annotationsBehind(statusRecord);
  if (row.badge !== null && carried.length === 0) {
    failures.push(`${row.name}: badge "${row.badge}" but the artifact carries no status annotation`);
  }
  if (row.badge === null && carried.length > 0) {
    failures.push(`${row.name}: artifact reports ${carried.join(", ")} but no badge is rendered`);
  }
  if (row.badge !== null && carried.length > 0) {
    const artifactBody = statusRecord?.injury_body_part ?? null;
    const renderedBody = badgeBodyPart(row.badge);
    if (renderedBody !== artifactBody) {
      failures.push(
        `${row.name}: badge "${row.badge}" reports body part ` +
          `${renderedBody === null ? "none" : `"${renderedBody}"`}, artifact has ` +
          `${artifactBody === null ? "none" : `"${artifactBody}"`}`,
      );
    }
  }
}
const withBadge = badges.filter((b) => b.badge !== null).length;

/*
  ------------------------------------------------------------------ pick of the week

  ADR-084's finding, applied to the newest surface: the rest-of-season board shipped with no
  pre-deploy gate comparing it with its artifact, and a correct page then failed a check that
  had never looked at it. This view makes a *positive claim about four named players*, which
  is a stronger thing to publish than a board of rows, so it gets the same treatment.

  **What is asserted, and what deliberately is not.** Every number on a card is compared with
  the artifact's own value for that player — the ADR-084 species. The four properties a pick
  must have are asserted as a contract: the product says "this player is a waiver target", and
  a player the artifact reports on injured reserve, or worth no more than replacement, or
  being net dropped, is not one whatever the selection code believes.

  The *floor* and the *ordering* are not recomputed here. Restating a rule in its own checker
  gives a build two implementations that can disagree, and Phase 9B recorded what that costs:
  a verifier's own bugs look exactly like product findings. `web/tests/potw.test.ts` owns the
  rule; this owns the claim.
*/
/**
 * A drawn momentum strip against its `behavior_trend_series.json` record — on a Pick of the
 * Week card and on a player card alike, because both draw the same component from the same
 * record (ADR-089, ADR-091). Returns failure messages; `who` prefixes each.
 */
function momentumFailures(who, series, strip) {
  const out = [];
  const number = (text) => Number.parseFloat(text.replace(/[^0-9.\-]/g, ""));
  if (series === null) {
    if (strip !== null && strip.bars > 0) {
      out.push(
        `${who}: a momentum strip drew ${String(strip.bars)} bar(s) and the build ` +
          "published no series for him",
      );
    }
    return out;
  }
  if (strip === null) {
    out.push(
      `${who}: the build published ${String(series.observations)} retained ` +
        "observation(s) and the card drew no momentum strip",
    );
    return out;
  }
  if (strip.bars !== series.observations) {
    out.push(
      `${who}: momentum strip drew ${String(strip.bars)} bar(s), artifact ` +
        `publishes ${String(series.observations)} observation(s)`,
    );
  }
  const statesDirection = strip.value.includes("/day");
  if (statesDirection !== (series.add_trend !== null)) {
    out.push(
      `${who}: momentum reads "${strip.value}" while the artifact's add_trend is ` +
        `${String(series.add_trend)}`,
    );
  }
  if (statesDirection) {
    const rendered = number(strip.value);
    if (!Number.isFinite(rendered) || Math.abs(rendered - series.add_trend) > 0.05) {
      out.push(
        `${who}: momentum shows ${String(rendered)}/day, artifact has ` +
          `${String(series.add_trend)}`,
      );
    }
    if (!/over \d+ (hour|day)s?/.test(strip.span)) {
      out.push(
        `${who}: momentum states a direction with no span beside it ` +
          `(span text "${strip.span}")`,
      );
    }
  }
  const gapDrawn = strip.gaps > 0;
  const gapPublished = series.snapshots_in_window > series.observations;
  if (gapDrawn !== gapPublished) {
    out.push(
      `${who}: momentum ${gapDrawn ? "draws" : "draws no"} gap while the artifact ` +
        `publishes ${String(series.observations)} of ` +
        `${String(series.snapshots_in_window)} snapshot(s)`,
    );
  }
  return out;
}

let potwCardsChecked = 0;
if (publishedInSeason && opportunityRecords !== null) {
  await page.goto(`${BASE}/?view=potw&scoring=ppr&teams=12`, { waitUntil: "networkidle" });

  const oppBlock = opportunityRecords.filter(
    (r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR",
  );
  // Names published twice are skipped rather than guessed at — the same rule the badge check
  // uses, and for the same reason: a duplicate name would make a card be compared against a
  // record describing somebody else.
  const oppByName = new Map();
  for (const record of oppBlock) {
    oppByName.set(record.display_name, oppByName.has(record.display_name) ? null : record);
  }

  const potw = await page.$$eval(".potw-card", (cards) =>
    cards.map((card) => ({
      position: card.getAttribute("data-pos"),
      name: card.querySelector(".player-name")?.textContent?.trim() ?? null,
      text: card.textContent ?? "",
      tiles: [...card.querySelectorAll(".potw-tile")].map((tile) => ({
        label: tile.querySelector(".readout-label")?.textContent?.trim() ?? "",
        value: tile.querySelector(".readout-value")?.textContent?.trim() ?? "",
      })),
      momentum: (() => {
        const panel = card.querySelector(".momentum");
        if (panel === null || panel.querySelector(".momentum-bars") === null) return null;
        return {
          bars: panel.querySelectorAll(".momentum-bar").length,
          gaps: panel.querySelectorAll(".momentum-gap").length,
          value: panel.querySelector(".momentum-value")?.textContent?.trim() ?? "",
          span: panel.querySelector(".momentum-span")?.textContent?.trim() ?? "",
        };
      })(),
    })),
  );

  /** A rendered tile's value by its label prefix, or null when the card has no such tile. */
  const tileValue = (card, prefix) =>
    card.tiles.find((tile) => tile.label.startsWith(prefix))?.value ?? null;
  /** `1,240` and `▲ +1,196` both read back as numbers. */
  const asNumber = (text) =>
    text === null ? null : Number.parseFloat(text.replace(/[^0-9.\-]/g, ""));

  for (const card of potw) {
    potwCardsChecked += 1;
    if (card.name === null) {
      failures.push("pick of the week: a card rendered with no player name");
      continue;
    }
    const record = oppByName.get(card.name);
    if (record === undefined) {
      failures.push(
        `pick of the week: "${card.name}" is on screen and is not in the published ` +
          "opportunity board for this block",
      );
      continue;
    }
    if (record === null) continue;

    if (record.position !== card.position) {
      failures.push(
        `${card.name}: card is filed under ${card.position}, artifact says ${record.position}`,
      );
    }

    // The numbers, against the artifact's own.
    const renderedAdds = asNumber(tileValue(card, "Adds"));
    if (renderedAdds !== record.add_count) {
      failures.push(
        `${card.name}: card shows ${String(renderedAdds)} adds, artifact has ` +
          `${String(record.add_count)}`,
      );
    }
    const renderedNet = asNumber(tileValue(card, "Net roster moves"));
    if (renderedNet !== record.net_add_count) {
      failures.push(
        `${card.name}: card shows net ${String(renderedNet)}, artifact has ` +
          `${String(record.net_add_count)}`,
      );
    }
    const renderedVorp = asNumber(tileValue(card, "ROS expected VORP"));
    if (renderedVorp === null || Math.abs(renderedVorp - record.ros_expected_vorp) > 0.05) {
      failures.push(
        `${card.name}: card shows ROS expected VORP ${String(renderedVorp)}, artifact has ` +
          `${String(record.ros_expected_vorp)}`,
      );
    }

    // The four properties the claim itself requires.
    if (record.long_absence) {
      failures.push(`${card.name}: published as a waiver pick while the artifact flags a long absence`);
    }
    if (!ORDINARY_ROSTER_STATUS.has(String(record.current_status ?? "ACT").toUpperCase())) {
      failures.push(
        `${card.name}: published as a waiver pick while the artifact reports status ` +
          `"${String(record.current_status)}"`,
      );
    }
    if (!(record.ros_expected_vorp > 0)) {
      failures.push(
        `${card.name}: published as a waiver pick at ${String(record.ros_expected_vorp)} ` +
          "remaining VORP, which is no better than the wire he would come off",
      );
    }
    if (!(record.net_add_count > 0)) {
      failures.push(
        `${card.name}: published as a waiver pick while the feed is net shedding him ` +
          `(${String(record.net_add_count)})`,
      );
    }

    // The truthfulness invariant, on the deployed bytes rather than in a component test: no
    // card may state or imply a share of leagues, because no source this project publishes
    // from reports one (ADR-088).
    if (/\d+\s*%\s*rostered|rostered in|percent of leagues|%\s*owned/i.test(card.text)) {
      failures.push(`${card.name}: a pick card claims a rostered share, which no source supplies`);
    }

    /*
      ------------------------------------------------- the momentum strip (ADR-089)

      Two claims, and the second is the one the rule is built on.

      **The bars are the artifact's own points.** One bar per published observation and no
      more. A strip that drew a bar for a day the feed skipped would be asserting a count
      nobody retained, which is exactly the zero-for-unknown the artifact refuses to publish.

      **A direction never appears without its span.** `behavior_trend_v1` states one from as
      few as two observations on purpose; what stops that being reckless is that the number
      is always printed beside the window it was measured over. A `/day` figure with no span
      text beside it is the defect the whole rule exists to prevent, so it is a failure here
      rather than a style note.

      The slope is deliberately **not recomputed**. Phase 9B paid for restating a rule in its
      own checker once already: this compares the page with the artifact, and the artifact's
      own arithmetic is `tests/unit/test_behavior_history.py`'s to own.
    */
    if (behaviorSeries !== null) {
      const series = behaviorSeries.find((r) => r.player_id === record.player_id) ?? null;
      failures.push(...momentumFailures(card.name, series, card.momentum));
    }
  }
}

/*
  ------------------------------------------------------------------ the signal layer (ADR-091)

  **What is asserted.** On in-season cards — one per position, from the rest-of-season board —
  every role rail's latest value, published change and bar count against `player_usage.json`,
  the points rail's latest week against the same record, and the next-game block's opponent,
  venue and implied points against `team_matchups.json`, and the card's add-momentum strip
  against `behavior_trend_series.json` by the same rule the pick cards use. On Pick of the
  Week, each role row's
  "earlier → latest" and each matchup line's implied points. And one contract: no
  quarterback's card or pick leads with a snap or target share.

  **What is not.** The change is not recomputed from the weekly values — `role_change_v1` is
  the artifact's rule and `tests/unit/test_signal_usage.py` owns its arithmetic; a checker that
  restated it would be a second implementation that could disagree (Phase 9B). The formatting
  below is restated, as every other check in this file restates `toFixed(1)`, because a
  rendered string can only be compared with a rendered string.
*/
const shareText = (value) => `${String(Math.round(value * 100))}%`;
const metricText = (metric, value) =>
  value === null || value === undefined
    ? "\u2014"
    : metric.endsWith("_share")
      ? shareText(value)
      : String(Math.round(value));
const changeText = (metric, change) => {
  const share = metric.endsWith("_share");
  const magnitude = share ? Math.round(Math.abs(change) * 100) : Math.round(Math.abs(change));
  if (magnitude === 0) return "no change";
  return `${change > 0 ? "+" : "\u2212"}${String(magnitude)}${share ? " pts" : ""}`;
};
const LEADS_WITH_A_SHARE = new Set(["snap_share", "target_share"]);

let signalCardsChecked = 0;
let signalPicksChecked = 0;
let signalMomentumChecked = 0;
if (publishedInSeason && playerUsage !== null) {
  const usageById = new Map(playerUsage.map((record) => [record.player_id, record]));
  const matchupByTeam = new Map((teamMatchups ?? []).map((record) => [record.team, record]));
  const names = new Map();
  for (const record of rosBlock) names.set(record.display_name, names.has(record.display_name) ? null : record);

  // One subject per position: the best-ranked row whose name is unique on the block and who
  // has a usage record with at least one published change, so the change text is exercised.
  const subjects = [];
  for (const position of ["QB", "RB", "WR", "TE"]) {
    const row = rosBlock.find((record) => {
      if (record.position !== position || names.get(record.display_name) !== record) return false;
      const usage = usageById.get(record.player_id);
      return usage !== undefined && Object.values(usage.role_changes).some((c) => c?.change != null);
    });
    if (row !== undefined) subjects.push(row);
  }

  for (const row of subjects) {
    const usage = usageById.get(row.player_id);
    await page.goto(
      `${BASE}/?view=ros&scoring=ppr&teams=12&search=${encodeURIComponent(row.display_name)}`,
      { waitUntil: "networkidle" },
    );
    await page.getByRole("button", { name: row.display_name, exact: true }).first().click();
    await page.waitForSelector("dialog[open]");
    signalCardsChecked += 1;
    const drawn = await page.$eval("dialog[open]", (dialog) => ({
      rails: [...dialog.querySelectorAll(".usage-rail[data-metric]")].map((rail) => ({
        metric: rail.getAttribute("data-metric"),
        value: rail.querySelector(".usage-rail-value")?.textContent?.trim() ?? "",
        change: rail.querySelector(".usage-rail-change")?.textContent?.trim() ?? null,
        bars: rail.querySelectorAll(".usage-bar").length,
      })),
      momentum: (() => {
        const panel = dialog.querySelector(".momentum");
        if (panel === null || panel.querySelector(".momentum-bars") === null) return null;
        return {
          bars: panel.querySelectorAll(".momentum-bar").length,
          gaps: panel.querySelectorAll(".momentum-gap").length,
          value: panel.querySelector(".momentum-value")?.textContent?.trim() ?? "",
          span: panel.querySelector(".momentum-span")?.textContent?.trim() ?? "",
        };
      })(),
      matchup: (() => {
        const panel = dialog.querySelector(".matchup");
        if (panel === null) return null;
        const tile = [...panel.querySelectorAll(".readout")].find((node) =>
          (node.querySelector(".readout-label")?.textContent ?? "").startsWith("Implied team points"),
        );
        return {
          head: panel.querySelector(".matchup-opponent")?.textContent?.trim() ?? "",
          implied: tile?.querySelector(".readout-value")?.textContent?.trim() ?? null,
          text: panel.textContent ?? "",
        };
      })(),
    }));
    const who = `${row.display_name} (${row.position}) card`;

    if (row.position === "QB" && drawn.rails.some((rail) => LEADS_WITH_A_SHARE.has(rail.metric))) {
      failures.push(`${who}: a quarterback's role block leads with a snap or target share`);
    }
    const roleRails = drawn.rails.filter((rail) => rail.metric !== "fantasy_points");
    if (roleRails.length === 0) failures.push(`${who}: the build published a usage record and the card drew no role rail`);
    for (const rail of roleRails) {
      const change = usage.role_changes[rail.metric];
      if (rail.bars !== usage.weeks.length) {
        failures.push(`${who} ${rail.metric}: ${String(rail.bars)} bar slot(s), artifact publishes ${String(usage.weeks.length)} week(s)`);
      }
      const wantValue = change === null ? "\u2014" : metricText(rail.metric, change.latest);
      if (rail.value !== wantValue) {
        failures.push(`${who} ${rail.metric}: latest reads "${rail.value}", artifact ${wantValue}`);
      }
      const wantChange = change?.change == null ? null : changeText(rail.metric, change.change);
      if ((rail.change === null) !== (wantChange === null) || (wantChange !== null && !rail.change.includes(wantChange))) {
        failures.push(`${who} ${rail.metric}: change reads "${String(rail.change)}", artifact ${String(wantChange)}`);
      }
    }
    const points = drawn.rails.find((rail) => rail.metric === "fantasy_points");
    const lastPlayed = [...usage.weeks].reverse().find((week) => week.status === "played");
    const wantPoints = lastPlayed?.fantasy_points?.PPR;
    if (points !== undefined && wantPoints != null && points.value !== wantPoints.toFixed(1)) {
      failures.push(`${who}: latest points read "${points.value}", artifact ${wantPoints.toFixed(1)}`);
    }

    const matchup = matchupByTeam.get(usage.team) ?? null;
    if ((matchup === null) !== (drawn.matchup === null)) {
      failures.push(`${who}: next-game block ${drawn.matchup === null ? "missing" : "drawn"} while team_matchups ${matchup === null ? "publishes none" : "publishes one"} for ${String(usage.team)}`);
    } else if (matchup !== null) {
      const head = `Week ${String(matchup.week)} ${matchup.home_away === "home" ? "vs" : "@"} ${matchup.opponent}`;
      if (drawn.matchup.head !== head) failures.push(`${who}: next game reads "${drawn.matchup.head}", artifact ${head}`);
      const implied = matchup.implied_team_points === null ? "\u2014" : matchup.implied_team_points.toFixed(1);
      if (drawn.matchup.implied !== implied) {
        failures.push(`${who}: implied points read "${String(drawn.matchup.implied)}", artifact ${implied}`);
      }
      if (matchup.implied_team_points !== null && !/No model reads them/.test(drawn.matchup.text)) {
        failures.push(`${who}: sportsbook lines printed without the statement that no model reads them`);
      }
    }
    // The card draws the same momentum component Pick of the Week does, from the same record.
    if (behaviorSeries !== null) {
      const series = behaviorSeries.find((r) => r.player_id === row.player_id) ?? null;
      failures.push(...momentumFailures(who, series, drawn.momentum));
      signalMomentumChecked += 1;
    }
    await page.keyboard.press("Escape");
  }

  // Pick of the Week: the evidence row against the same bytes.
  await page.goto(`${BASE}/?view=potw&scoring=ppr&teams=12`, { waitUntil: "networkidle" });
  const oppByName = new Map();
  for (const record of opportunityRecords ?? []) {
    if (record.league_preset_id !== "redraft-12" || record.scoring_preset !== "PPR") continue;
    oppByName.set(record.display_name, oppByName.has(record.display_name) ? null : record);
  }
  const picks = await page.$$eval(".potw-card", (cards) =>
    cards.map((card) => ({
      position: card.getAttribute("data-pos"),
      name: card.querySelector(".player-name")?.textContent?.trim() ?? null,
      roles: [...card.querySelectorAll(".potw-role[data-metric]")].map((role) => ({
        metric: role.getAttribute("data-metric"),
        text: role.querySelector(".potw-evidence-row")?.textContent ?? "",
      })),
      matchupLine: card.querySelector(".matchup-line")?.textContent ?? null,
    })),
  );
  for (const pick of picks) {
    const record = pick.name === null ? undefined : oppByName.get(pick.name);
    if (record == null) continue;
    signalPicksChecked += 1;
    const usage = usageById.get(record.player_id);
    if (pick.position === "QB" && pick.roles.some((role) => LEADS_WITH_A_SHARE.has(role.metric))) {
      failures.push(`${pick.name}: a quarterback's pick leads with a snap or target share`);
    }
    if (usage === undefined) {
      if (pick.roles.length > 0) failures.push(`${pick.name}: pick draws role rows and the build published no usage record`);
      continue;
    }
    for (const role of pick.roles) {
      const change = usage.role_changes[role.metric];
      if (change === null) continue;
      const want =
        change.earlier === null
          ? metricText(role.metric, change.latest)
          : `${metricText(role.metric, change.earlier)} \u2192 ${metricText(role.metric, change.latest)}`;
      if (!role.text.includes(want)) {
        failures.push(`${pick.name} ${role.metric}: pick reads "${role.text.trim()}", artifact ${want}`);
      }
    }
    const matchup = matchupByTeam.get(usage.team);
    if (matchup !== undefined && matchup.implied_team_points !== null && pick.matchupLine !== null) {
      const want = `implied ${matchup.implied_team_points.toFixed(1)}`;
      if (!pick.matchupLine.includes(want)) {
        failures.push(`${pick.name}: matchup line "${pick.matchupLine}" does not carry ${want}`);
      }
    }
  }
}

await browser.close();
console.log(JSON.stringify({
  tierRowsChecked: rows.length,
  tierBoardRowsRendered: marks.length,
  tierMarksChecked: 25,
  defaultBoard,
  publishedInSeason,
  rosRowsChecked,
  potwCardsChecked,
  behaviorSeriesRecords: behaviorSeries === null ? null : behaviorSeries.length,
  usageRecords: playerUsage === null ? null : playerUsage.length,
  matchupRecords: teamMatchups === null ? null : teamMatchups.length,
  signalCardsChecked,
  signalMomentumChecked,
  signalPicksChecked,
  arbRowsChecked: arbRows.length,
  arbRowsWithTrend: arbBlock.slice(0, arbRows.length).filter((r) => r.market_trend !== null).length,
  trendSeriesRecords: seriesRecords.length,
  trendSeriesSources: [...new Set(seriesRecords.map((r) => r.market_source_id))].sort(),
  chartedMarkets,
  badgesRendered: withBadge,
  failures,
}, null, 1));
process.exitCode = failures.length === 0 ? 0 : 1;
