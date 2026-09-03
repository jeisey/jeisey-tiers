/**
 * Cross-check the rendered board against the artifact bytes, on the real 2026 build.
 *
 * The unit and end-to-end suites prove agreement on fixtures. This proves it on the data the
 * site will actually serve, which is the Phase-6 exit gate's own wording.
 */
import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const BASE = process.argv[2] ?? "http://localhost:4180";
const dataDir = process.argv[3] ?? "web/dist-real/data";
const tiers = JSON.parse(readFileSync(`${dataDir}/tiers.json`, "utf-8"));
const arb = JSON.parse(readFileSync(`${dataDir}/arbitrage.json`, "utf-8"));
const status = JSON.parse(readFileSync(`${dataDir}/player_status.json`, "utf-8"));

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
const OPEN_ALL = `?tiers=${allTiers}`;
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
    const trend = expectedTrendCell(record.market_trend);
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

// --- Injury badges against the status artifact ----------------------------------------------
await page.goto(`${BASE}/${OPEN_ALL}`, { waitUntil: "networkidle" });
const badges = await page.$$eval("table.sheet tbody tr", (trs) =>
  trs.map((tr) => ({
    name: tr.querySelector(".player-name")?.textContent?.trim(),
    badge: tr.querySelector(".status-badge span[aria-hidden]")?.textContent?.trim() ?? null,
  })),
);
for (const row of badges) {
  const record = block.find((r) => r.display_name === row.name);
  if (!record) continue;
  const s = statusById.get(record.player_id);
  const designation = s?.injury_status ?? null;
  if (designation === null && row.badge !== null && !/^(RES|CUT|E14|INJU|NOTE)/.test(row.badge)) {
    failures.push(`${row.name}: badge "${row.badge}" but the artifact reports no injury status`);
  }
  if (designation !== null && row.badge === null) {
    failures.push(`${row.name}: artifact reports ${designation} but no badge is rendered`);
  }
}
const withBadge = badges.filter((b) => b.badge !== null).length;

await browser.close();
console.log(JSON.stringify({
  tierRowsChecked: rows.length,
  tierBoardRowsRendered: marks.length,
  tierMarksChecked: 25,
  arbRowsChecked: arbRows.length,
  arbRowsWithTrend: arbBlock.slice(0, arbRows.length).filter((r) => r.market_trend !== null).length,
  badgesRendered: withBadge,
  failures,
}, null, 1));
process.exitCode = failures.length === 0 ? 0 : 1;
