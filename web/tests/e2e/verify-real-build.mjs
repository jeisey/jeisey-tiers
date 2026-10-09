/**
 * Cross-check the rendered board against the artifact bytes, on the real 2026 build.
 *
 * The unit and end-to-end suites prove agreement on fixtures. This proves it on the data the
 * site will actually serve, which is the Phase-6 exit gate's own wording.
 */
import { existsSync, readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

import { blockPortraits } from "./portrait-stub.mjs";

const BASE = process.argv[2] ?? "http://localhost:4180";
const dataDir = process.argv[3] ?? "web/dist-real/data";
const tiers = JSON.parse(readFileSync(`${dataDir}/tiers.json`, "utf-8"));
/**
 * Strict by default: the production refresh always publishes arbitrage. A local real-data build
 * made without the private market store cannot (ADR-099's real-build screenshots), and passes
 * `--allow-missing-arbitrage` to skip only the arbitrage checks, which the output then reports.
 */
const allowMissingArbitrage = process.argv.includes("--allow-missing-arbitrage");
const arb = allowMissingArbitrage && !existsSync(`${dataDir}/arbitrage.json`)
  ? null
  : JSON.parse(readFileSync(`${dataDir}/arbitrage.json`, "utf-8"));
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
 * Season-to-date actuals (ADR-105), if this build published them. Present, every rendered
 * `Szn rank`, `Total pts` and `Avg pts/g` cell, and every chart row's season rank in words,
 * must be this artifact's own value for the row's player — never a number the page computed.
 */
let actualsRecords = null;
try {
  actualsRecords = JSON.parse(readFileSync(`${dataDir}/season_actuals.json`, "utf-8")).records;
} catch {
  actualsRecords = null;
}
const actualsPPR = new Map(
  (actualsRecords ?? []).filter((r) => r.scoring_preset === "PPR").map((r) => [r.player_id, r]),
);
/** The cell text the tables print for one actuals record (one decimal, real minus sign). */
function actualsCells(record) {
  const fixed = (value) => {
    const text = Math.abs(value).toFixed(1);
    return value < 0 && Number(text) !== 0 ? `\u2212${text}` : text;
  };
  if (record === undefined) return { rank: "\u2014 Unavailable", points: "\u2014 Unavailable", perGame: "\u2014 Unavailable" };
  if (record.games_played === 0) {
    return { rank: "\u2014 No appearances", points: "0.0", perGame: "\u2014 No appearances" };
  }
  return {
    rank: `${record.position}${String(record.season_position_rank)}`,
    points: fixed(record.points),
    perGame: fixed(record.points_per_game),
  };
}
/**
 * The tables' signed gap (ADR-105): the artifact's season rank minus the row's RoS positional
 * rank, `+3` / `\u22123` / `0`, or a dash when either rank is missing.
 */
function rosVsSeasonText(rosPositionRank, record) {
  if (record === undefined || record.season_position_rank === null || rosPositionRank === null || rosPositionRank === undefined) {
    return "\u2014";
  }
  const places = record.season_position_rank - rosPositionRank;
  if (places === 0) return "0";
  return places > 0 ? `+${String(places)}` : `\u2212${String(Math.abs(places))}`;
}
/** A rendered gap back to a number; NaN for the dash. */
const gapNumber = (text) => (text === "\u2014" ? Number.NaN : Number(text.replace("\u2212", "-")));
let actualsCellsChecked = 0;
let actualsChartRowsChecked = 0;
let rosVsSeasonCellsChecked = 0;
let weekBoardSortsChecked = 0;

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
/** The in-season metadata: here, for the behaviour snapshot the momentum series speaks for. */
let rosMetadata = null;
try {
  rosMetadata = JSON.parse(readFileSync(`${dataDir}/ros_build_metadata.json`, "utf-8"));
} catch {
  rosMetadata = null;
}

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
const arbBlock = (arb?.records ?? [])
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
      // The signed gap as it is seen: its cell also carries the words for a screen reader.
      gap: tr.querySelector(".ros-vs-season > [aria-hidden='true']")?.textContent?.trim() ?? null,
      // Read from its own element, for the reason the draft board reads it that way: the
      // long-absence badge is the name button's sibling and stripping it would be a bet on
      // today's absences.
      name: tr.querySelector(".player-name")?.textContent?.trim() ?? null,
      // Current status is a badge on the name rather than a column of its own (ADR-085), and
      // it renders only for a code that says something. `null` therefore means two different
      // things — `ACT`, and a status the artifact did not carry — which is why the check below
      // is a contract about noteworthiness rather than a cell comparison.
      // ADR-101: the mark is now the availability policy's reading, not the raw code.
      status: tr.querySelector(".player-cell .availability-badge span[aria-hidden]")?.textContent?.trim() ?? null,
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
  const actualsAt =
    actualsRecords === null
      ? null
      : {
          rank: rosColumn.at("Szn rank"),
          gap: rosColumn.at("RoS vs Szn"),
          points: rosColumn.at("Total pts"),
          perGame: rosColumn.at("Avg pts/g"),
        };
  const rosProblem = rosColumn.problem("ROS");
  if (rosProblem !== null) failures.push(rosProblem);
  else {
    rosRowsChecked = rosRendered.length;
    // Joined by the rendered rank, not by position: the actionable board holds back a player
    // whose season is over (ADR-101) and leaves his rank as a gap rather than renumbering.
    const byRank = new Map(rosBlock.map((r) => [String(r.ros_fair_rank), r]));
    const renderedRanks = new Set(rosRendered.map((r) => r.cells[rosAt.rank]));
    const deepest = Math.max(0, ...rosRendered.map((r) => Number(r.cells[rosAt.rank]) || 0));
    for (const record of rosBlock) {
      if (record.ros_fair_rank > deepest || renderedRanks.has(String(record.ros_fair_rank))) continue;
      const evidence = statusById.get(record.player_id);
      const reserve =
        ["RES", "PUP", "NFI", "SUS", "EXE", "E14"].includes(String(record.current_status ?? evidence?.roster_status ?? "").toUpperCase()) ||
        ["IR", "INJURED RESERVE", "PUP", "NFI", "SUS", "SUSPENDED"].includes(String(evidence?.injury_status ?? "").toUpperCase());
      const retired = String(record.current_status ?? evidence?.roster_status ?? "").toUpperCase() === "RET";
      if (!retired && !(evidence?.availability_override && reserve)) {
        failures.push(
          `ROS rank ${String(record.ros_fair_rank)} (${record.display_name}) is held back from the ` +
            "default board without a corroborated season-ending reading",
        );
      }
    }
    rosRendered.forEach((rendered, i) => {
      const { cells, name } = rendered;
      const record = byRank.get(cells[rosAt.rank]);
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
      if (actualsAt !== null) {
        const want = actualsCells(actualsPPR.get(record.player_id));
        expect("season_position_rank", cells[actualsAt.rank], want.rank);
        expect("season_points", cells[actualsAt.points], want.points);
        expect("season_points_per_game", cells[actualsAt.perGame], want.perGame);
        actualsCellsChecked += 3;
        expect("ros_vs_season", rendered.gap, rosVsSeasonText(record.ros_position_rank, actualsPPR.get(record.player_id)));
        rosVsSeasonCellsChecked += 1;
      }

      /*
       * The availability mark, as a contract rather than as a list of codes (ADR-082, ADR-101).
       *
       * The mark is the availability policy's reading, so the verifier does not transcribe the
       * policy. It asserts the two directions the artifacts decide: a noteworthy roster code is
       * never left unmarked, and a mark on an ordinary code is always explained by the status
       * record — a designation, a non-active Sleeper status, a reserve code, a refused or
       * missing feed record, a reviewed override, or no record at all ("unknown").
       */
      const code = (record.current_status ?? "").trim().toUpperCase();
      const noteworthy = code !== "" && !["ACT", "A01", "DEV"].includes(code);
      if (noteworthy && rendered.status === null) {
        failures.push(
          `ROS row ${i + 1}: artifact reports current_status "${code}" and no availability mark is rendered`,
        );
      }
      if (!noteworthy && rendered.status !== null) {
        const evidence = statusById.get(record.player_id);
        const explained =
          evidence === undefined ||
          evidence.injury_status !== null ||
          (evidence.sleeper_status ?? "").toLowerCase() !== "active" ||
          !["ACT", "A01", "DEV"].includes(String(evidence.roster_status ?? "").toUpperCase()) ||
          (evidence.availability_override ?? null) !== null ||
          evidence.quality_flags.some((flag) => flag.startsWith("sleeper_")) ||
          Date.parse(rosMetadata.generated_at_utc) - Date.parse(evidence.observed_at_utc) > 48 * 3600 * 1000 ||
          code === "";
        if (!explained) {
          failures.push(
            `ROS row ${i + 1}: mark "${rendered.status}" but neither the roster code "${code}" nor ` +
              "the status record says anything",
          );
        }
      }
    });
  }
}

// --- The RoS chart's comparison lane against the artifacts (ADR-105) ----------------------
if (publishedInSeason && defaultBoard === "ros") {
  const lanes = await page.$$eval(".tier-board[data-rank-lane='true'] .board-row", (rows) =>
    rows.slice(0, 60).map((row) => ({
      player: row.getAttribute("data-player"),
      ros: row.querySelector('.rank-value[data-kind="ros"]')?.textContent?.replace(/^RoS/, "").trim() ?? null,
      season: row.querySelector('.rank-value[data-kind="season"]')?.textContent?.replace(/^Szn/, "").trim() ?? null,
      triangle: row.querySelector('.rank-mark[data-kind="season"]') !== null,
      square: row.querySelector('.rank-mark[data-kind="ros"]') !== null,
    })),
  );
  if (lanes.length === 0) failures.push("RoS chart: no comparison lane rendered");
  const rosById = new Map(rosBlock.map((r) => [r.player_id, r]));
  for (const lane of lanes) {
    const record = rosById.get(lane.player);
    if (record === undefined) continue;
    const wantRos = `${record.position}${String(record.ros_position_rank)}`;
    if (lane.ros !== wantRos || !lane.square) failures.push(`RoS chart ${record.display_name}: square ${String(lane.ros)}, artifact ${wantRos}`);
    if (actualsRecords !== null) {
      const actual = actualsPPR.get(lane.player);
      const wantSeason =
        actual === undefined || actual.season_position_rank === null
          ? "\u2014"
          : `${actual.position}${String(actual.season_position_rank)}`;
      if (lane.season !== wantSeason) failures.push(`RoS chart ${record.display_name}: season ${String(lane.season)}, artifact ${wantSeason}`);
      if (lane.triangle !== (wantSeason !== "\u2014")) failures.push(`RoS chart ${record.display_name}: triangle ${lane.triangle ? "drawn" : "missing"}`);
      if (actual !== undefined && actual.position !== record.position) failures.push(`RoS chart ${record.display_name}: ranked as ${actual.position}, board says ${record.position}`);
    }
    actualsChartRowsChecked += 1;
  }
}

// --- Arbitrage table and rail against the artifact -----------------------------------------
let arbRows = [];
if (arb !== null) {
await page.goto(`${BASE}/?view=arbitrage`, { waitUntil: "networkidle" });
await page.waitForSelector("table.sheet tbody tr");
arbRows = await page.$$eval("table.sheet tbody tr", (trs) =>
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
    // Compared at the precision printed: one decimal below 100/day, whole numbers above it
    // (`formatMomentumRate`, ADR-092). A tolerance of half the last printed digit.
    const tolerance = strip.value.includes(".") ? 0.05 : 0.5;
    if (!Number.isFinite(rendered) || Math.abs(rendered - series.add_trend) > tolerance) {
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
    (r) =>
      r.league_preset_id === "redraft-12" &&
      r.scoring_preset === "PPR" &&
      r.model_coverage !== "unprojected",
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
/** The card's four-game gap format (`formatBreadth` in data/signals.ts): whole points, real minus. */
function breadthText(value) {
  const rounded = Math.round(value);
  if (rounded === 0) return "level";
  return `${rounded > 0 ? "+" : "\u2212"}${String(Math.abs(rounded))} pts`;
}

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
let breadthRowsChecked = 0;
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
        notches: rail.querySelectorAll(".usage-bar-notch").length,
        window: rail.querySelector(".usage-rail-window")?.textContent?.trim() ?? "",
        note: rail.querySelector(".usage-rail-note")?.textContent?.trim() ?? null,
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
    const roleRails = drawn.rails.filter(
      (rail) => rail.metric !== "fantasy_points" && rail.metric !== "drive_breadth",
    );
    // ADR-104: the drive rail is a rail — one slot per published week, the latest drive share
    // and its change as the artifact states them, a notch per game only where the build
    // compares with random, and the four-game gap (or why there is none) on its own line.
    const breadthRow = drawn.rails.find((rail) => rail.metric === "drive_breadth") ?? null;
    const block = usage.drive_breadth ?? null;
    if ((block === null) !== (breadthRow === null)) {
      failures.push(`${who}: drive rail ${breadthRow === null ? "missing" : "drawn"} while the artifact ${block === null ? "publishes none" : "publishes one"}`);
    } else if (block !== null) {
      breadthRowsChecked += 1;
      if (breadthRow.bars !== usage.weeks.length) {
        failures.push(`${who} drive rail: ${String(breadthRow.bars)} bar slot(s), artifact publishes ${String(usage.weeks.length)} week(s)`);
      }
      const wantValue = block.change === null ? "\u2014" : shareText(block.change.latest);
      if (breadthRow.value !== wantValue) failures.push(`${who}: drive rail reads "${breadthRow.value}", artifact ${wantValue}`);
      const latestEntry = block.change === null ? null : block.weeks.find((entry) => entry.week === block.change.latest_week);
      if (block.change !== null && (latestEntry === undefined || latestEntry.drive_share !== block.change.latest)) {
        failures.push(`${who}: drive rail change does not start from its own latest week`);
      }
      if (block.change?.change != null && breadthRow.change !== null && !breadthRow.change.endsWith(changeText("drive_share", block.change.change))) {
        failures.push(`${who}: drive rail change "${breadthRow.change}" is not the artifact's ${String(block.change.change)}`);
      }
      const notched = block.compares_with_random
        ? block.weeks.filter((entry) => entry.expected_share !== null && entry.drive_share !== null).length
        : 0;
      if (breadthRow.notches !== notched) {
        failures.push(`${who}: drive rail draws ${String(breadthRow.notches)} notch(es), artifact implies ${String(notched)}`);
      }
      if (!block.compares_with_random) {
        if (breadthRow.note !== null) failures.push(`${who}: drive rail compares a ${row.position} with random`);
      } else if (block.displayable && block.breadth_gap_pp !== null) {
        if (breadthRow.note === null || !breadthRow.note.includes(`${breadthText(block.breadth_gap_pp)} vs random`)) {
          failures.push(`${who}: drive rail note "${String(breadthRow.note)}" does not carry the artifact's gap`);
        }
      } else if (breadthRow.note === null || !breadthRow.note.startsWith("vs random:")) {
        failures.push(`${who}: drive rail does not say why there is no comparison with random`);
      }
      for (const entry of block.weeks) {
        if (entry.eligible_drives > 0 && Math.abs(entry.drive_share - entry.reached_drives / entry.eligible_drives) > 0.0006) {
          failures.push(`${who}: week ${String(entry.week)} drive share ${String(entry.drive_share)} is not ${String(entry.reached_drives)}/${String(entry.eligible_drives)}`);
        }
      }
      if (block.eligible_drives > 0 && block.breadth_gap_pp !== null) {
        const recomputed = (100 * (block.reached_drives - block.expected_drives)) / block.eligible_drives;
        if (Math.abs(recomputed - block.breadth_gap_pp) > 0.06) {
          failures.push(`${who}: published breadth ${String(block.breadth_gap_pp)} is not 100*(A-E)/D = ${recomputed.toFixed(2)}`);
        }
      }
    }
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
      if (
        matchup.implied_team_points !== null &&
        !/No model reads them|models never read them/.test(drawn.matchup.text)
      ) {
        failures.push(`${who}: sportsbook lines printed without the statement of which models read them`);
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

/*
  ------------------------------------------------ the Opportunity Board's signals (ADR-092)

  **What is asserted.** Every row of the Opportunity table and every chart row it draws: the
  role reading (the position's leading metric, its latest value, the published change, the
  glyph and the window) against `player_usage.json`; the add-momentum reading (glyph, slope at
  the printed precision, span) against `behavior_trend_series.json`; the next-game reading
  (week, venue, opponent, a bye before it, implied points or the absence of a line) against
  `team_matchups.json` for the team the card itself reads. Every absence must be the absence
  the artifacts describe — "not in feed" is never a zero, a missing artifact never a record.
  Then the three filters keep exactly the rows their one reading allows, the momentum order
  follows the published slope with every row lacking one after it, the role order across
  mixed positions is categorical with ROS rank inside a category (never a magnitude), and
  Pick of the Week names the same players whatever the board's filters say.

  **What is not.** No slope is refitted and no change is subtracted: `behavior_trend_v1` and
  `role_change_v1` are the Python side's (`test_behavior_history.py`, `test_signal_usage.py`).
  The formatting is restated because a rendered string can only be compared with a rendered
  string, and the position -> leading metric map is restated as the contract it is.
*/
/** A value the page rendered must be one the artifact published; a miss is a thrown failure. */
function required(value, what = "a published record") {
  if (value === undefined || value === null) throw new Error(`verify: expected ${what}`);
  return value;
}
const LEADING_METRIC = { QB: "pass_attempts", RB: "snap_share", WR: "snap_share", TE: "snap_share" };
const METRIC_SHORT = { pass_attempts: "Pass att", snap_share: "Snap" };
const GLYPH = { up: "\u25b2", down: "\u25bc", flat: "\u25ac" };
const printedChange = (metric, change) =>
  metric.endsWith("_share") ? Math.round(Math.abs(change) * 100) : Math.round(Math.abs(change));
const roleDirection = (metric, change) =>
  printedChange(metric, change) === 0 ? "flat" : change > 0 ? "up" : "down";
const momentumDirection = (trend) =>
  Number(Math.abs(trend).toFixed(1)) === 0 ? "flat" : trend > 0 ? "rising" : "falling";
const spanText = (days) => {
  if (!(days > 0)) return "at one moment";
  if (days < 1) {
    const hours = Math.max(1, Math.round(days * 24));
    return `over ${String(hours)} hour${hours === 1 ? "" : "s"}`;
  }
  const whole = Math.round(days);
  return `over ${String(whole)} day${whole === 1 ? "" : "s"}`;
};

let oppRowsChecked = 0;
let faCellsChecked = 0;
let unprojectedRowsChecked = 0;
let oppChartRowsChecked = 0;
let oppFiltersChecked = 0;
if (publishedInSeason && opportunityRecords !== null) {
  // ADR-102: unprojected off-roster rows have no rank and are listed in their own section.
  const unprojectedBlock = opportunityRecords.filter(
    (r) =>
      r.league_preset_id === "redraft-12" &&
      r.scoring_preset === "PPR" &&
      r.model_coverage === "unprojected",
  );
  const oppBlock = opportunityRecords
    .filter(
      (r) =>
        r.league_preset_id === "redraft-12" &&
        r.scoring_preset === "PPR" &&
        r.model_coverage !== "unprojected",
    )
    .sort((a, b) => a.ros_fair_rank - b.ros_fair_rank || a.player_id.localeCompare(b.player_id));
  const oppById = new Map(oppBlock.map((record) => [record.player_id, record]));
  const usageById = new Map((playerUsage ?? []).map((record) => [record.player_id, record]));
  const seriesById = new Map((behaviorSeries ?? []).map((record) => [record.player_id, record]));
  const matchupByTeam = new Map((teamMatchups ?? []).map((record) => [record.team, record]));
  // The snapshot the momentum series speaks for: the build's own, else the newest point. A
  // series whose last point is older ended before it, and is printed as ended (ADR-092).
  const newestPoint = (behaviorSeries ?? [])
    .map((record) => record.points.at(-1)?.observed_at)
    .filter((stamp) => stamp !== undefined)
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;
  const latestSnapshot = rosMetadata?.behavior?.snapshot_at_utc ?? newestPoint;

  /** What the artifacts say a row's three readings must be, in the page's own words. */
  const expectedFor = (record) => {
    const usage = usageById.get(record.player_id) ?? null;
    const metric = LEADING_METRIC[record.position];
    let role;
    if (playerUsage === null) role = { kind: "unpublished", value: "\u2014" };
    else if (usage === null) role = { kind: "no_record", value: "\u2014" };
    else if (usage.appearances === 0) role = { kind: "no_appearance", value: "\u2014" };
    else {
      const change = usage.role_changes[metric];
      if (change === null) role = { kind: "no_latest_value", value: "\u2014", metric };
      else {
        const value = metricText(metric, change.latest);
        if (change.earlier === null || change.change === null) {
          role = { kind: "one_game", value, metric, detail: `wk ${String(change.latest_week)} only` };
        } else {
          const direction = roleDirection(metric, change.change);
          const games = change.earlier_games;
          role = {
            kind: "measured",
            value,
            metric,
            direction,
            change: `${GLYPH[direction]} ${changeText(metric, change.change)}`,
            detail: `wk ${String(change.latest_week)} vs ${String(games)} gm${games === 1 ? "" : "s"}`,
          };
        }
      }
    }

    const series = seriesById.get(record.player_id) ?? null;
    let momentum;
    if (behaviorSeries === null) momentum = { kind: "unpublished" };
    else if (series === null || series.points.length === 0) momentum = { kind: "not_in_feed" };
    else if (series.add_trend === null) momentum = { kind: "one_observation" };
    else {
      const last = series.points.at(-1)?.observed_at ?? null;
      const current =
        last !== null && latestSnapshot !== null && Date.parse(last) >= Date.parse(latestSnapshot);
      const day = last === null
        ? ""
        : new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" }).format(new Date(Date.parse(last)));
      momentum = {
        kind: current ? "measured" : "ended",
        trend: series.add_trend,
        direction: momentumDirection(series.add_trend),
        span: current ? spanText(series.span_days) : `${spanText(series.span_days)} \u00b7 to ${day}`,
      };
    }

    const team = usage?.team ?? record.team ?? null;
    let next;
    if (teamMatchups === null) next = { kind: "unpublished" };
    else if (team === null) next = { kind: "no_team" };
    else {
      const game = matchupByTeam.get(team) ?? null;
      if (game === null) next = { kind: "no_record" };
      else {
        const byes = [...game.upcoming_bye_weeks].sort((a, b) => a - b);
        const bye = byes.find((week) => week < game.week);
        const head =
          `W${String(game.week)} ${game.home_away === "home" ? "vs" : "@"} ${game.opponent}`;
        const posted = game.total_line !== null || game.team_expected_margin !== null;
        const line =
          game.implied_team_points !== null
            ? `${game.implied_team_points.toFixed(1)} implied`
            : posted
              ? `total ${game.total_line === null ? "\u2014" : game.total_line.toFixed(1)}`
              : "no line yet";
        const detail = bye === undefined ? line : `bye W${String(bye)} \u00b7 ${line}`;
        next = { kind: "published", head, detail, team };
      }
    }
    return { role, momentum, next };
  };

  const readTable = () =>
    page.$$eval("table.sheet tbody tr[data-player]", (trs) =>
      trs.map((tr) => {
        const cell = (col) => {
          const node = tr.querySelector(`td[data-col="${col}"] .signal-cell`);
          if (node === null) return null;
          const text = (selector) => node.querySelector(selector)?.textContent?.trim() ?? null;
          return {
            kind: node.getAttribute("data-kind"),
            direction: node.getAttribute("data-direction"),
            metric: text(".signal-metric"),
            value: text(".signal-value"),
            change: text(".signal-change"),
            detail: text(".signal-detail"),
          };
        };
        return {
          id: tr.getAttribute("data-player"),
          role: cell("role"),
          momentum: cell("add_momentum"),
          next: cell("next_game"),
        };
      }),
    );

  await page.goto(`${BASE}/?view=opportunity&scoring=ppr&teams=12`, { waitUntil: "networkidle" });
  await page.waitForSelector("table.sheet tbody tr[data-player]");
  const table = await readTable();

  // ADR-102: a verified free agent's team cell reads FA (never his last club), and the
  // unprojected section lists exactly the block's unprojected rows with their own counts.
  // ADR-105: the Opportunity Board's signed gap is the artifact's season rank minus the
  // row's own RoS positional rank, as it renders in the same row.
  if (actualsRecords !== null) {
    const gaps = await page.$$eval("table.sheet.opp-sheet tbody tr[data-player]", (rows) =>
      rows.map((tr) => ({
        id: tr.getAttribute("data-player"),
        posRank: tr.querySelector(".pos-tag b")?.textContent?.trim() ?? null,
        gap: tr.querySelector(".ros-vs-season > [aria-hidden='true']")?.textContent?.trim() ?? null,
      })),
    );
    for (const row of gaps) {
      const rank = row.posRank === null || row.posRank === "\u2014" ? null : Number(row.posRank);
      const want = rosVsSeasonText(rank, actualsPPR.get(row.id));
      if (row.gap !== want) failures.push(`opportunity row ${String(row.id)}: RoS vs Szn reads ${String(row.gap)}, the artifacts ${want}`);
      rosVsSeasonCellsChecked += 1;
    }
  }

  const teamCells = await page.$$eval("table.sheet.opp-sheet tbody tr[data-player]", (rows) =>
    rows.map((tr) => ({
      id: tr.getAttribute("data-player"),
      fa: tr.querySelector(".team-fa") !== null,
    })),
  );
  for (const cell of teamCells) {
    const unsigned = statusById.get(cell.id)?.employment_status === "unsigned";
    if (unsigned !== cell.fa) {
      failures.push(`opportunity row ${String(cell.id)}: team cell ${cell.fa ? "reads FA" : "does not read FA"} while player_status says ${unsigned ? "unsigned" : "not unsigned"}`);
    }
    if (unsigned) faCellsChecked += 1;
  }
  const unprojectedRows = await page.$$eval(".unprojected-sheet tbody tr", (rows) =>
    rows.map((tr) => ({
      id: tr.getAttribute("data-player-id"),
      cells: [...tr.querySelectorAll("td")].map((td) => (td.textContent ?? "").trim()),
    })),
  );
  // By heading, not by position: the season columns (ADR-105) sit between team and adds. The
  // name is the row's own <th>, so the <td> headings start after "Player".
  const unprojectedHeads = await page.$$eval(".unprojected-sheet thead th", (ths) =>
    ths.slice(1).map((th) => (th.textContent ?? "").trim()),
  );
  const unAt = (label) => unprojectedHeads.indexOf(label);
  for (const label of ["Team", "Adds", "Szn rank", "Total pts", "Avg pts/g"]) {
    if (unprojectedRows.length > 0 && unAt(label) < 0) failures.push(`not-projected section: no column headed ${label}`);
  }
  if (unprojectedRows.length !== unprojectedBlock.length) {
    failures.push(`not-projected section: ${String(unprojectedRows.length)} rows rendered, artifact publishes ${String(unprojectedBlock.length)}`);
  }
  for (const row of unprojectedRows) {
    const record = unprojectedBlock.find((candidate) => candidate.player_id === row.id);
    if (record === undefined) {
      failures.push(`not-projected row ${String(row.id)}: rendered, artifact publishes no such row`);
      continue;
    }
    unprojectedRowsChecked += 1;
    const adds = record.add_count === null ? "\u2014" : record.add_count.toLocaleString("en-US");
    const addsCell = row.cells[unAt("Adds")];
    if (addsCell !== adds) failures.push(`not-projected ${record.display_name}: adds "${addsCell}", artifact ${adds}`);
    const teamCell = row.cells[unAt("Team")] ?? "";
    const wantTeam = record.employment_status === "unsigned" ? "FA \u2014 unsigned free agent" : (record.team ?? "\u2014");
    if (teamCell !== wantTeam && !(record.employment_status === "unsigned" && teamCell.startsWith("FA"))) {
      failures.push(`not-projected ${record.display_name}: team "${teamCell}", artifact ${String(record.team)} / ${String(record.employment_status)}`);
    }
    // ADR-105: genuine actuals beside "No RoS projection" — the artifact's, or the reason not.
    if (actualsRecords !== null) {
      const want = actualsCells(actualsPPR.get(record.player_id));
      const got = [row.cells[unAt("Szn rank")], row.cells[unAt("Total pts")], row.cells[unAt("Avg pts/g")]];
      if (got[0] !== want.rank || got[1] !== want.points || got[2] !== want.perGame) {
        failures.push(`not-projected ${record.display_name}: season ${got.join(" / ")}, artifact ${want.rank} / ${want.points} / ${want.perGame}`);
      }
      actualsCellsChecked += 3;
    }
  }

  if (table.length !== oppBlock.length) {
    failures.push(`opportunity table: ${String(table.length)} rows rendered, artifact block publishes ${String(oppBlock.length)}`);
  }
  table.forEach((row, index) => {
    const who = `opportunity row ${String(index + 1)} (${String(row.id)})`;
    const record = oppById.get(row.id);
    if (record === undefined) {
      failures.push(`${who}: rendered, and the artifact block publishes no such player`);
      return;
    }
    if (oppBlock[index]?.player_id !== row.id) {
      failures.push(`${who}: out of ROS order — the artifact puts ${String(oppBlock[index]?.display_name)} here`);
    }
    oppRowsChecked += 1;
    const want = expectedFor(record);

    // Role.
    const role = row.role;
    if (role === null) failures.push(`${who}: no role cell`);
    else {
      if (role.kind !== want.role.kind) {
        failures.push(`${who} role: reads as "${role.kind}", artifacts say "${want.role.kind}"`);
      }
      if (role.value !== want.role.value) {
        failures.push(`${who} role: latest reads "${role.value}", artifact ${want.role.value}`);
      }
      if (want.role.metric !== undefined && role.metric !== METRIC_SHORT[want.role.metric]) {
        failures.push(`${who} role: leads with "${role.metric}", the ${record.position} contract is ${want.role.metric}`);
      }
      if (record.position === "QB" && role.metric === "Snap") {
        failures.push(`${who}: a quarterback's board row leads with a snap share`);
      }
      const wantChange = want.role.change ?? null;
      if (role.change !== wantChange) {
        failures.push(`${who} role: change reads "${String(role.change)}", artifact ${String(wantChange)}`);
      }
      if ((want.role.direction ?? "none") !== role.direction) {
        failures.push(`${who} role: direction "${String(role.direction)}", artifact ${String(want.role.direction ?? "none")}`);
      }
      if (want.role.detail !== undefined && role.detail !== want.role.detail) {
        failures.push(`${who} role: window reads "${String(role.detail)}", artifact ${want.role.detail}`);
      }
    }

    // Momentum.
    const momentum = row.momentum;
    if (momentum === null) failures.push(`${who}: no momentum cell`);
    else {
      if (momentum.kind !== want.momentum.kind) {
        failures.push(`${who} momentum: reads as "${momentum.kind}", artifacts say "${want.momentum.kind}"`);
      }
      if (want.momentum.kind === "measured" || want.momentum.kind === "ended") {
        const printed = momentum.value ?? "";
        const rendered = Number.parseFloat(printed.replace(/[^0-9.\-]/g, ""));
        const tolerance = printed.includes(".") ? 0.05 : 0.5;
        if (!Number.isFinite(rendered) || Math.abs(rendered - want.momentum.trend) > tolerance) {
          failures.push(`${who} momentum: shows "${printed}", artifact slope ${String(want.momentum.trend)}`);
        }
        if (!printed.startsWith({ rising: "\u25b2", falling: "\u25bc", flat: "\u25ac" }[want.momentum.direction])) {
          failures.push(`${who} momentum: glyph in "${printed}" disagrees with the published ${want.momentum.direction} slope`);
        }
        if (momentum.detail !== want.momentum.span) {
          failures.push(`${who} momentum: a direction printed with span "${String(momentum.detail)}", artifact ${want.momentum.span}`);
        }
      } else if (/\/day|^0(\.0)?$/.test(momentum.value ?? "")) {
        failures.push(`${who} momentum: "${String(momentum.value)}" states a rate the artifacts do not publish (${want.momentum.kind})`);
      }
    }

    // Next game.
    const next = row.next;
    if (next === null) failures.push(`${who}: no next-game cell`);
    else {
      if (next.kind !== want.next.kind) {
        failures.push(`${who} next game: reads as "${next.kind}", artifacts say "${want.next.kind}"`);
      }
      if (want.next.kind === "published") {
        if (next.value !== want.next.head) {
          failures.push(`${who} next game: "${String(next.value)}", team_matchups for ${want.next.team} says "${want.next.head}"`);
        }
        if (next.detail !== want.next.detail) {
          failures.push(`${who} next game: "${String(next.detail)}", team_matchups says "${want.next.detail}"`);
        }
      }
    }
  });

  // The chart draws the same role reading for the rows it charts.
  const chart = await page.$$eval(".opp-board .opp-row[data-player]", (rows) =>
    rows.map((row) => ({
      id: row.getAttribute("data-player"),
      direction: row.querySelector(".opp-role")?.getAttribute("data-direction") ?? null,
      metric: row.querySelector(".opp-role-metric")?.textContent?.trim() ?? null,
      value: row.querySelector(".opp-role-value")?.textContent?.trim() ?? null,
      change: row.querySelector(".opp-role-change")?.textContent?.trim() ?? null,
    })),
  );
  for (const row of chart) {
    const record = oppById.get(row.id);
    if (record === undefined) continue;
    oppChartRowsChecked += 1;
    const want = expectedFor(record).role;
    if (row.value !== want.value || row.change !== (want.change ?? null) || row.direction !== (want.direction ?? "none")) {
      failures.push(
        `opportunity chart ${record.display_name}: role reads "${String(row.value)} ${String(row.change)}" ` +
          `(${String(row.direction)}), artifact "${want.value} ${String(want.change ?? null)}" (${String(want.direction ?? "none")})`,
      );
    }
  }

  // The filters: each keeps exactly the rows its one reading allows.
  const expectIds = (predicate) =>
    oppBlock.filter((record) => predicate(expectedFor(record), record)).map((record) => record.player_id).sort();
  const filterCases = [
    ["role", playerUsage !== null, (want) => want.role.kind === "measured" && want.role.direction === "up"],
    ["momentum", behaviorSeries !== null, (want) => want.momentum.kind === "measured" && want.momentum.direction === "rising"],
    ["surfaced", true, (_want, record) => record.outside_tier_board],
  ];
  for (const [filter, available, predicate] of filterCases) {
    await page.goto(`${BASE}/?view=opportunity&scoring=ppr&teams=12&only=${filter}`, { waitUntil: "networkidle" });
    await page.waitForSelector("section[aria-labelledby='opportunity-table-heading']");
    const shown = (await page.$$eval("table.sheet tbody tr[data-player]", (trs) =>
      trs.map((tr) => tr.getAttribute("data-player")),
    )).sort();
    const want = available ? expectIds(predicate) : oppBlock.map((record) => record.player_id).sort();
    if (JSON.stringify(shown) !== JSON.stringify(want)) {
      failures.push(
        `opportunity filter "${filter}": ${String(shown.length)} rows shown, the artifacts allow ${String(want.length)}` +
          (available ? "" : " (an unavailable filter must not be applied)"),
      );
    }
    oppFiltersChecked += 1;
  }

  // Momentum order: current slopes highest first, then slopes that ended early (by slope),
  // then every row with no slope at all.
  await page.goto(`${BASE}/?view=opportunity&scoring=ppr&teams=12&opportunity=momentum`, { waitUntil: "networkidle" });
  const byMomentum = (await readTable()).map((row) => expectedFor(required(oppById.get(row.id))).momentum);
  const tierOf = (momentum) => (momentum.kind === "measured" ? 0 : momentum.kind === "ended" ? 1 : 2);
  byMomentum.forEach((momentum, index) => {
    const before = byMomentum[index - 1];
    if (before === undefined) return;
    if (tierOf(before) > tierOf(momentum)) {
      failures.push(`momentum order: row ${String(index + 1)} (${momentum.kind}) follows a ${before.kind} row`);
    } else if (tierOf(before) === tierOf(momentum) && tierOf(momentum) < 2 && momentum.trend > before.trend) {
      failures.push(`momentum order: row ${String(index + 1)} slope ${String(momentum.trend)} above ${String(before.trend)}`);
    }
  });

  // Role order across positions: categorical, and ROS rank inside a category — never a size.
  await page.goto(`${BASE}/?view=opportunity&scoring=ppr&teams=12&opportunity=role`, { waitUntil: "networkidle" });
  const byRole = (await readTable()).map((row) => required(oppById.get(row.id)));
  const category = { up: 0, flat: 1, down: 2, none: 3 };
  for (let index = 1; index < byRole.length; index += 1) {
    const a = byRole[index - 1];
    const b = byRole[index];
    const ca = category[expectedFor(a).role.direction ?? "none"];
    const cb = category[expectedFor(b).role.direction ?? "none"];
    if (ca > cb) failures.push(`role order: ${b.display_name} is ahead of its category`);
    if (ca === cb && a.ros_fair_rank > b.ros_fair_rank && new Set(byRole.map((r) => r.position)).size > 1) {
      failures.push(
        `role order: ${a.display_name} above ${b.display_name} inside one category against ROS rank — ` +
          "a magnitude compared across positions",
      );
    }
  }

  // Pick of the Week does not read the board's filters or orderings.
  const pickNames = async (query) => {
    await page.goto(`${BASE}/?view=potw&scoring=ppr&teams=12${query}`, { waitUntil: "networkidle" });
    return page.$$eval(".potw-card .player-name", (nodes) => nodes.map((node) => node.textContent?.trim()));
  };
  const plain = await pickNames("");
  const filtered = await pickNames("&only=role.momentum.surfaced&opportunity=role");
  if (JSON.stringify(plain) !== JSON.stringify(filtered)) {
    failures.push(`pick of the week: picks moved with the board's filters (${plain.join(", ")} vs ${filtered.join(", ")})`);
  }
}

/**
 * The Start/Sit tab (ADR-096), on the real build.
 *
 * Optional like the signal layer: a build whose weekly layer was withheld publishes no
 * `weekly_projections.json`, and the tab says so. A *present* artifact is checked the way the
 * boards are: the deck's numbers are the record's own quantiles, the verdict names one of the
 * two players compared, and the week board lists every published projection for the preset.
 */
let weeklyRecords = null;
try {
  weeklyRecords = JSON.parse(readFileSync(`${dataDir}/weekly_projections.json`, "utf-8")).records;
} catch {
  weeklyRecords = null;
}
let startsitCardsChecked = 0;
let startsitBoardRows = 0;
let whyPanelsChecked = 0;
let whyTermsChecked = 0;
let whyBoardCellsChecked = 0;
/** Exactly `signedPoints` in web/src/data/whyweek.ts: a tenth, a true minus, ±0.0 at zero. */
function signedPoints(value) {
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "±0.0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)}`;
}
if (publishedInSeason && weeklyRecords !== null) {
  // Exactly `formatValue`: `toFixed(1)`, whose binary rounding prints 37.65 as 37.6.
  const one = (value) => value.toFixed(1);
  const ppr = weeklyRecords.filter((r) => r.scoring_preset === "PPR");
  // ADR-101: the verdict check needs two players the availability policy lets play, so it
  // takes them from players whose published evidence is clean — no designation on the report,
  // an active roster code and an active Sleeper record with no injury status, no override.
  const clean = (r) => {
    const evidence = statusById.get(r.player_id);
    return (
      (r.injury?.designation ?? null) === null &&
      evidence !== undefined &&
      evidence.injury_status === null &&
      (evidence.sleeper_status ?? "").toLowerCase() === "active" &&
      ["ACT", "A01", "DEV"].includes(String(evidence.roster_status ?? "").toUpperCase()) &&
      (evidence.availability_override ?? null) === null &&
      !evidence.quality_flags.some((flag) => flag.startsWith("sleeper_"))
    );
  };
  const projected = ppr
    .filter((r) => r.quantiles !== null && clean(r))
    .sort((a, b) => b.quantiles.q50 - a.quantiles.q50 || a.player_id.localeCompare(b.player_id));
  const pair = projected.slice(0, 2);
  if (pair.length === 2) {
    const ids = pair.map((r) => r.player_id.replace(/^gsis:/, "")).join(".");
    await page.goto(`${BASE}/?view=startsit&scoring=ppr&teams=12&duel=${ids}`, { waitUntil: "networkidle" });
    await page.waitForSelector(".verdict-head");
    const cards = await page.$$eval(".deck-card:not(.deck-empty)", (nodes) =>
      nodes.map((node) => ({
        name: node.querySelector(".deck-name")?.textContent?.trim() ?? null,
        median: node.querySelector(".deck-median")?.textContent?.trim() ?? null,
        range: [...node.querySelectorAll(".deck-range dd")].map((dd) => dd.textContent?.trim() ?? ""),
      })),
    );
    for (const [index, record] of pair.entries()) {
      startsitCardsChecked += 1;
      const card = cards[index];
      const q = record.quantiles;
      if (card === undefined) {
        failures.push(`start/sit: no deck card for ${record.display_name}`);
        continue;
      }
      if (card.name !== record.display_name) {
        failures.push(`start/sit: slot ${String(index + 1)} shows ${card.name}, the URL names ${record.display_name}`);
      }
      const expected = [one(q.q10), `${one(q.q25)}–${one(q.q75)}`, one(q.q90)];
      if (card.median !== one(q.q50) || JSON.stringify(card.range) !== JSON.stringify(expected)) {
        failures.push(
          `start/sit: ${record.display_name} draws ${card.median} [${card.range.join(", ")}], ` +
            `the artifact publishes ${one(q.q50)} [${expected.join(", ")}]`,
        );
      }
    }
    const verdict = await page.$eval(".verdict-head", (node) => node.textContent?.trim() ?? "");
    if (!pair.some((record) => verdict === `Start ${record.display_name}`)) {
      failures.push(`start/sit: the verdict "${verdict}" names neither player compared`);
    }
    // "Why this week" (ADR-099): every rendered number is the artifact's own, to the tenth.
    const panels = await page.$$eval(".why-this-week-player", (nodes) =>
      nodes.map((node) => ({
        name: node.querySelector(".why-this-week-name")?.textContent?.trim() ?? null,
        gist: node.querySelector(".why-this-week-gist")?.textContent?.trim() ?? null,
        heads: [...node.querySelectorAll(".why-week-head")].map((head) => ({
          level: head.querySelector(".why-week-level")?.textContent?.trim() ?? "",
          number: head.querySelector(".why-week-number")?.textContent?.trim() ?? "",
        })),
        rows: [...node.querySelectorAll(".why-week-table tbody tr")].map((row) => ({
          group: row.getAttribute("data-group"),
          cells: [...row.querySelectorAll("td")].map((td) => (td.textContent ?? "").replace(/[▲▼●]/g, "").trim()),
        })),
      })),
    );
    for (const record of pair) {
      if (record.explanation === null || record.explanation === undefined) continue;
      const panel = panels.find((entry) => entry.name === record.display_name);
      if (panel === undefined) {
        failures.push(`why this week: no panel for ${record.display_name}`);
        continue;
      }
      whyPanelsChecked += 1;
      const q = record.quantiles;
      const e = record.explanation;
      const gist = `Median ${signedPoints(q.q50 - e.q50.typical)} · ceiling ${signedPoints(q.q90 - e.q90.typical)} vs typical`;
      if (panel.gist !== gist) failures.push(`why this week: ${record.display_name} reads "${panel.gist}", the artifact "${gist}"`);
      const heads = Object.fromEntries(panel.heads.map((head) => [head.level, head.number]));
      for (const [level, key] of [["Median", "q50"], ["Ceiling", "q90"], ["Floor", "q10"]]) {
        if (heads[level] !== one(q[key])) {
          failures.push(`why this week: ${record.display_name} ${level} shows ${String(heads[level])}, the artifact ${one(q[key])}`);
        }
      }
      const material = new Set(
        ["q10", "q50", "q90"].flatMap((key) =>
          Object.entries(e[key].terms)
            .filter(([, value]) => Math.abs(value) >= 0.05)
            .map(([group]) => group),
        ),
      );
      const shown = new Set(panel.rows.map((row) => row.group));
      if ([...material].sort().join() !== [...shown].sort().join()) {
        failures.push(`why this week: ${record.display_name} shows reasons [${[...shown].join(", ")}], the artifact's material terms are [${[...material].join(", ")}]`);
      }
      for (const row of panel.rows) {
        const expected = ["q50", "q90", "q10"].map((key) => signedPoints(e[key].terms[row.group] ?? 0));
        if (JSON.stringify(row.cells) !== JSON.stringify(expected)) {
          failures.push(`why this week: ${record.display_name} ${String(row.group)} reads [${row.cells.join(", ")}], the artifact [${expected.join(", ")}]`);
        }
        whyTermsChecked += 1;
      }
    }
  }
  await page.goto(`${BASE}/?view=startsit&scoring=ppr&teams=12`, { waitUntil: "networkidle" });
  await page.waitForSelector(".weekboard-table tbody tr");
  const more = page.locator(".weekboard-more");
  if ((await more.count()) > 0 && (await more.textContent())?.startsWith("Show all")) await more.click();
  startsitBoardRows = await page.locator(".weekboard-table tbody tr").count();
  if (startsitBoardRows !== ppr.length) {
    failures.push(`start/sit: the week board lists ${String(startsitBoardRows)} rows, the artifact ${String(ppr.length)}`);
  }
  // The board's "vs typical" cell is the artifact's median minus its typical median.
  const cells = await page.$$eval(".weekboard-table tbody tr", (rows) =>
    rows.map((row) => ({
      name: row.querySelector(".wb-player .player-name")?.textContent?.trim() ?? "",
      why: row.querySelector(".wb-why-cell")?.getAttribute("title") ?? null,
    })),
  );
  for (const record of ppr) {
    if (record.quantiles === null || record.explanation == null) continue;
    const named = cells.filter((entry) => entry.why !== null && entry.name === record.display_name);
    if (named.length !== 1) continue; // two players sharing a name cannot be told apart here
    const cell = named[0];
    const expected = signedPoints(record.quantiles.q50 - record.explanation.q50.typical);
    if (!cell.why.startsWith(`${expected} median`)) {
      failures.push(`week board: ${record.display_name} reads "${cell.why}", the artifact ${expected}`);
    }
    whyBoardCellsChecked += 1;
  }

  /*
   * Column sorting (ADR-105 follow-up), on the real board's length: sorted before paging, so
   * the first row of a sort on the paged board is the first row of the whole board, and a
   * missing value sorts last in both directions.
   */
  if (actualsRecords !== null) {
    await page.goto(`${BASE}/?view=startsit&scoring=ppr&teams=12`, { waitUntil: "networkidle" });
    await page.waitForSelector(".weekboard-table tbody tr");
    const readGaps = () =>
      page.$$eval(".weekboard-table tbody tr", (rows) =>
        rows.map((row) => row.querySelector(".ros-vs-season > [aria-hidden='true']")?.textContent?.trim() ?? ""),
      );
    const gapButton = page.locator("table.weekboard-table th[data-col='ros_vs_season'] button");
    for (const direction of ["descending", "ascending"]) {
      await gapButton.click();
      const sort = await page.locator("table.weekboard-table th[data-col='ros_vs_season']").getAttribute("aria-sort");
      if (sort !== direction) failures.push(`week board: RoS vs Szn reads aria-sort ${String(sort)}, expected ${direction}`);
      const paged = await readGaps();
      const showAll = page.locator(".weekboard-more");
      if ((await showAll.count()) > 0 && (await showAll.textContent())?.startsWith("Show all")) await showAll.click();
      const all = (await readGaps()).map(gapNumber);
      const known = all.filter((value) => !Number.isNaN(value));
      const ordered = [...known].sort((a, b) => (direction === "descending" ? b - a : a - b));
      if (JSON.stringify(known) !== JSON.stringify(ordered)) failures.push(`week board: RoS vs Szn ${direction} is out of order`);
      if (all.slice(known.length).some((value) => !Number.isNaN(value))) failures.push(`week board: a blank RoS vs Szn sorts before a number (${direction})`);
      if (known.length > 0 && gapNumber(paged[0] ?? "") !== ordered[0]) {
        failures.push(`week board: the first page of the ${direction} sort starts at ${String(paged[0])}, the whole board at ${String(ordered[0])}`);
      }
      if ((await showAll.count()) > 0 && (await showAll.textContent())?.startsWith("Show the top")) await showAll.click();
      weekBoardSortsChecked += 1;
    }
  }
}

// The Trade tab (ADR-100): every package it renders is checked against the artifact bytes —
// its value is the sum of its members' published expected values, it is inside the printed
// band, it has the requested count, no member is the outgoing player, and no member is one the
// eligibility rule excludes.
let tradePackagesChecked = 0;
if (publishedInSeason) {
  // ADR-101: reserve-type and roster-less codes, a Sleeper reserve list and a reviewed
  // season-ending override all keep a player out by default; `INA` (inactive for one game)
  // and a one-week designation do not.
  const severe = new Set(["RES", "PUP", "NFI", "SUS", "EXE", "E14", "CUT", "RET"]);
  const sleeperReserve = new Set(["IR", "INJURED RESERVE", "PUP", "NFI", "SUS", "SUSPENDED", "COV"]);
  const byName = new Map(rosBlock.map((r) => [r.display_name, r]));
  const outgoing = rosBlock.find((r) => r.ros_expected_vorp > 0);
  if (outgoing !== undefined) {
    const range = 35;
    const get = 2;
    await page.goto(
      `${BASE}/?view=trade&scoring=ppr&teams=12&give=${outgoing.player_id.replace(/^gsis:/, "")}&get=${String(get)}&range=${String(range)}`,
      { waitUntil: "networkidle" },
    );
    await page.waitForSelector("section.trade");
    const packages = await page.$$eval(".trade-results > .trade-package", (nodes) =>
      nodes.map((node) => ({
        names: [...node.querySelectorAll(".trade-members .player-name")].map((n) => n.textContent?.trim() ?? ""),
        values: [...node.querySelectorAll(".trade-members .trade-member-value")].map((n) => n.textContent?.trim() ?? ""),
        value: node.querySelector(".trade-metrics > div dd")?.firstChild?.textContent?.trim() ?? "",
      })),
    );
    const low = outgoing.ros_expected_vorp * (1 - range / 100);
    const high = outgoing.ros_expected_vorp * (1 + range / 100);
    for (const pkg of packages) {
      const members = pkg.names.map((name) => byName.get(name));
      if (members.some((m) => m === undefined) || new Set(pkg.names).size !== pkg.names.length) {
        continue; // a name the block holds twice cannot be told apart here
      }
      const sum = members.reduce((total, m) => total + m.ros_expected_vorp, 0);
      if (pkg.value !== sum.toFixed(1)) failures.push(`trade: ${pkg.names.join(" + ")} reads ${pkg.value}, the artifact sums to ${sum.toFixed(1)}`);
      members.forEach((m, index) => {
        if (pkg.values[index] !== m.ros_expected_vorp.toFixed(1)) failures.push(`trade: ${m.display_name} reads ${pkg.values[index]}, the artifact ${m.ros_expected_vorp.toFixed(1)}`);
        if (m.player_id === outgoing.player_id) failures.push(`trade: ${m.display_name} is both given and received`);
        const evidence = statusById.get(m.player_id);
        if (
          !(m.ros_expected_vorp > 0) ||
          m.long_absence ||
          severe.has(String(m.current_status ?? "").toUpperCase()) ||
          sleeperReserve.has(String(evidence?.injury_status ?? "").toUpperCase()) ||
          (evidence?.availability_override ?? null) !== null
        ) {
          failures.push(`trade: ${m.display_name} is not an eligible target`);
        }
      });
      if (members.length !== get) failures.push(`trade: ${pkg.names.join(" + ")} has ${String(members.length)} players, asked for ${String(get)}`);
      if (sum < low - 1e-6 || sum > high + 1e-6) failures.push(`trade: ${pkg.names.join(" + ")} at ${sum.toFixed(2)} is outside ${low.toFixed(2)}–${high.toFixed(2)}`);
      tradePackagesChecked += 1;
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
  seasonActualsRecords: actualsRecords === null ? null : actualsRecords.length,
  actualsCellsChecked,
  actualsChartRowsChecked,
  rosVsSeasonCellsChecked,
  weekBoardSortsChecked,
  potwCardsChecked,
  behaviorSeriesRecords: behaviorSeries === null ? null : behaviorSeries.length,
  usageRecords: playerUsage === null ? null : playerUsage.length,
  matchupRecords: teamMatchups === null ? null : teamMatchups.length,
  signalCardsChecked,
  signalMomentumChecked,
  signalPicksChecked,
  oppRowsChecked,
  faCellsChecked,
  unprojectedRowsChecked,
  breadthRowsChecked,
  oppChartRowsChecked,
  oppFiltersChecked,
  weeklyRecords: weeklyRecords === null ? null : weeklyRecords.length,
  startsitCardsChecked,
  startsitBoardRows,
  whyPanelsChecked,
  whyTermsChecked,
  whyBoardCellsChecked,
  tradePackagesChecked,
  arbitrage: arb === null ? "absent (--allow-missing-arbitrage)" : "checked",
  arbRowsChecked: arbRows.length,
  arbRowsWithTrend: arbBlock.slice(0, arbRows.length).filter((r) => r.market_trend !== null).length,
  trendSeriesRecords: seriesRecords.length,
  trendSeriesSources: [...new Set(seriesRecords.map((r) => r.market_source_id))].sort(),
  chartedMarkets,
  badgesRendered: withBadge,
  failures,
}, null, 1));
process.exitCode = failures.length === 0 ? 0 : 1;
