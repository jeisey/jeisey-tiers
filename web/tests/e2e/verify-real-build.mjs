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
const arbBlock = arb.records
  .filter((r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR")
  .sort((a, b) => b.arbitrage_score - a.arbitrage_score);
const statusById = new Map(status.records.map((r) => [r.player_id, r]));

const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const failures = [];

// --- Tier table rows against the artifact -------------------------------------------------
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.waitForSelector("table.sheet tbody tr");
const rows = await page.$$eval("table.sheet tbody tr", (trs) =>
  trs.slice(0, 40).map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent.trim())),
);
rows.forEach((cells, i) => {
  const record = block[i];
  const expect = (label, got, want) => {
    if (got !== want) failures.push(`tier row ${i + 1} ${label}: rendered ${got}, artifact ${want}`);
  };
  expect("fair_rank", cells[0], String(record.fair_rank));
  expect("name", cells[1].replace(/\s*(Q|D|OUT|IR|PUP|NFI|SUS|NOTE)\s*·.*$/, "").replace(/Current status.*$/, "").trim(),
    record.display_name);
  expect("expected_vorp", cells[6], record.expected_vorp.toFixed(1));
  expect("p50_vorp", cells[7], record.p50_vorp.toFixed(1));
  expect("iqr", cells[8], `${record.p25_vorp.toFixed(1)} – ${record.p75_vorp.toFixed(1)}`);
  expect("expected_points", cells[9], record.expected_points.toFixed(1));
});

// --- Tier chart marks against the artifact -------------------------------------------------
const marks = await page.$$eval("svg g.player-mark", (gs) => gs.map((g) => g.getAttribute("aria-label")));
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
arbRows.forEach((cells, i) => {
  const record = arbBlock[i];
  if (cells[4] !== String(record.fair_rank)) failures.push(`arb row ${i + 1} fair_rank`);
  if (cells[5] !== record.market_adp.toFixed(1)) failures.push(`arb row ${i + 1} adp`);
  if (cells[8] !== record.arbitrage_score.toFixed(1)) failures.push(`arb row ${i + 1} score`);
  if (!cells[9].startsWith("—")) failures.push(`arb row ${i + 1} trend is not an em dash: ${cells[9]}`);
});
const railLabels = await page.$$eval("svg g.player-mark", (gs) => gs.map((g) => g.getAttribute("aria-label")));
for (const record of arbBlock.filter((r) => r.rank_gap > 0).slice(0, 20)) {
  const label = railLabels.find((l) => l.startsWith(`${record.display_name},`));
  if (!label) { failures.push(`rail: no mark for ${record.display_name}`); continue; }
  if (!label.includes(`fair rank ${record.fair_rank}`)) failures.push(`rail ${record.display_name}: fair anchor`);
  if (!label.includes(`ADP ${record.market_adp.toFixed(1)}`)) failures.push(`rail ${record.display_name}: market anchor`);
}

// --- Injury badges against the status artifact ----------------------------------------------
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
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
  tierMarksChecked: 25,
  arbRowsChecked: arbRows.length,
  badgesRendered: withBadge,
  failures,
}, null, 1));
process.exitCode = failures.length === 0 ? 0 : 1;
