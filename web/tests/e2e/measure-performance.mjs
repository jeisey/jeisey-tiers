/**
 * Frontend performance, measured on a production-scale board.
 *
 * The committed fixture board is eighteen players, which proves layout and proves nothing
 * about cost. Production is 2,700 tier rows across nine preset blocks, ~1,900 arbitrage rows
 * and ~3,400 projections, and the interactions that matter — sorting three hundred rows,
 * expanding every tier, opening a card — only become measurable at that size.
 *
 * So this script synthesises an artifact set at production dimensions, serves a real static
 * build of it, and times the things a drafter actually does. The *values* are nonsense; the
 * *shape* is production's, which is the only property a performance measurement needs.
 *
 *   node web/tests/e2e/measure-performance.mjs [--out docs/visual-qa/<date>/performance.json]
 *
 * Nothing here is a gate. AGENTS.md is explicit that complexity is justified by measured
 * benefit, and the corollary is that a number nobody looks at justifies nothing either — so
 * this prints a table and writes a JSON record, and a human decides whether anything in it is
 * a problem.
 */

import { mkdirSync, mkdtempSync, cpSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

import { createStaticServer } from "./static-server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../..");

const LEAGUES = ["redraft-10", "redraft-12", "redraft-14"];
const SCORING = ["STD", "HALF", "PPR"];
const POSITIONS = ["QB", "RB", "WR", "TE"];
const BOARD_DEPTH = 300;
const BUILD_ID = "perf-20260831T000000Z";
const GENERATED_AT = "2026-08-31T11:26:56Z";
const SNAPSHOT_AT = "2026-08-31T11:25:57Z";

/** Deterministic pseudo-random, so two runs measure the same board. */
function rng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

const random = rng(20260831);
const players = Array.from({ length: BOARD_DEPTH }, (_, index) => {
  const position = POSITIONS[index % POSITIONS.length];
  return {
    id: `gsis:00-${String(index).padStart(7, "0")}`,
    // Long, realistic names: a 300-row board of "Player 1" would not exercise text layout.
    name: `${["Jamarcus", "Christian", "Amon-Ra", "Jaxon", "De'Von", "Bijan"][index % 6]} ${
      ["Smith-Njigba", "Robinson", "St. Brown", "Achane", "McCaffrey", "Higgins III"][index % 6]
    }`,
    position,
    team: ["ATL", "DET", "CIN", "SF", "BUF", "KC", "LAR", "BAL"][index % 8],
  };
});

function tierRecords() {
  const records = [];
  for (const league of LEAGUES) {
    for (const scoring of SCORING) {
      players.forEach((player, index) => {
        const p50 = 150 - index * 0.62 + random() * 2;
        // Nine tiers with the real board's shape: 8 / 14 / 25 / 33 / 29 / 42 / 45 / 69 / 35.
        const sizes = [8, 14, 25, 33, 29, 42, 45, 69, 35];
        let ordinal = 0;
        let cumulative = 0;
        for (const [tier, size] of sizes.entries()) {
          cumulative += size;
          if (index < cumulative) {
            ordinal = tier;
            break;
          }
        }
        records.push({
          schema_version: "1.1",
          build_id: BUILD_ID,
          league_preset_id: league,
          scoring_preset: scoring,
          player_id: player.id,
          display_name: player.name,
          team: player.team,
          position: player.position,
          fair_rank: index + 1,
          position_rank: Math.floor(index / 4) + 1,
          tier_ordinal: ordinal,
          tier_label: `Tier ${String(ordinal + 1)}`,
          expected_vorp: Number((p50 - 6).toFixed(4)),
          p10_vorp: Number((p50 - 62).toFixed(4)),
          p25_vorp: Number((p50 - 34).toFixed(4)),
          p50_vorp: Number(p50.toFixed(4)),
          p75_vorp: Number((p50 + 38).toFixed(4)),
          p90_vorp: Number((p50 + 66).toFixed(4)),
          expected_points: Number((p50 + 92).toFixed(4)),
          uncertainty: Number((92 + random() * 20).toFixed(4)),
          quality_flags: index % 17 === 0 ? ["rookie"] : [],
        });
      });
    }
  }
  return records;
}

function arbitrageRecords() {
  const records = [];
  for (const league of LEAGUES) {
    for (const scoring of SCORING) {
      players.forEach((player, index) => {
        // ~72% of the board is priced, matching the production ratio.
        if (index % 7 === 3) return;
        const adp = Math.max(1, index + 1 + (random() - 0.45) * 40);
        records.push({
          schema_version: "1.1",
          build_id: BUILD_ID,
          league_preset_id: league,
          scoring_preset: scoring,
          player_id: player.id,
          display_name: player.name,
          team: player.team,
          position: player.position,
          fair_rank: index + 1,
          market_adp: Number(adp.toFixed(4)),
          market_rank: Math.max(1, Math.round(adp / 2)),
          rank_gap: Number((adp - (index + 1)).toFixed(4)),
          regional_value_gap: Number(Math.log(adp / (index + 1)).toFixed(6)),
          arbitrage_mode: "baseline",
          arbitrage_score: Number((random() * 100).toFixed(2)),
          expected_surplus_vorp: null,
          p_positive_surplus: null,
          market_trend: index % 11 === 0 ? null : Number(((random() - 0.5) * 0.9).toFixed(4)),
          market_sample_size: 400 + Math.round(random() * 200),
          market_adp_sd: null,
          market_adp_low: Number(Math.max(1, adp - 18).toFixed(4)),
          market_adp_high: Number((adp + 44).toFixed(4)),
          market_source_id: "myfantasyleague_adp",
          market_cohort_id: "no-keeper",
          market_cohort_detail: "IS_KEEPER=N (approximate cohort)",
          market_snapshot_at_utc: SNAPSHOT_AT,
          confidence: index % 13 === 0 ? "low" : "medium",
          quality_flags: ["cohort_approximate"],
        });
      });
    }
  }
  return records;
}

function projectionRecords() {
  const records = [];
  for (const scoring of SCORING) {
    players.forEach((player, index) => {
      const points = 260 - index * 0.7;
      records.push({
        schema_version: "1.0",
        build_id: BUILD_ID,
        player_id: player.id,
        display_name: player.name,
        team: player.team,
        position: player.position,
        scoring_preset: scoring,
        expected_points: Number(points.toFixed(4)),
        p10_points: Number((points - 90).toFixed(4)),
        p25_points: Number((points - 44).toFixed(4)),
        p50_points: Number((points - 6).toFixed(4)),
        p75_points: Number((points + 48).toFixed(4)),
        p90_points: Number((points + 102).toFixed(4)),
        uncertainty_points: 96.4,
        quality_flags: [],
      });
    });
  }
  return records;
}

function statusRecords() {
  return players.slice(0, 316).map((player, index) => ({
    schema_version: "1.0",
    build_id: BUILD_ID,
    season: 2026,
    player_id: player.id,
    display_name: player.name,
    position: player.position,
    current_team: player.team,
    roster_status: "ACT",
    sleeper_status: "Active",
    injury_status: index % 5 === 0 ? "Questionable" : null,
    injury_body_part: index % 5 === 0 ? "Hamstring" : null,
    injury_notes: null,
    injury_start_date: null,
    practice_participation: null,
    practice_description: null,
    depth_chart_position: player.position,
    depth_chart_order: (index % 3) + 1,
    observed_at_utc: SNAPSHOT_AT,
    source_ids: ["nflreadpy", "sleeper"],
    quality_flags: [],
  }));
}

function envelope(artifact, recordSchema, records) {
  return {
    schema_version: "1.0",
    artifact,
    record_schema: recordSchema,
    build_id: BUILD_ID,
    generated_at_utc: GENERATED_AT,
    record_count: records.length,
    records,
    ...(artifact === "arbitrage" ? { arbitrage_mode: "baseline" } : {}),
  };
}

function metadata() {
  return {
    schema_version: "1.0",
    build_id: BUILD_ID,
    generated_at_utc: GENERATED_AT,
    git_sha: "0000000",
    season: 2026,
    intrinsic_model_version: "intrinsic-cb-hurdle-v1",
    arbitrage_mode: "baseline",
    arbitrage_model_version: null,
    arbitrage_method_version: "a0_rank_gap_v1",
    market: {
      source_id: "myfantasyleague_adp",
      snapshot_key: "2026-08-31T11-25-57Z",
      snapshot_at_utc: SNAPSHOT_AT,
      source_as_of_utc: null,
      cohort_rule_version: "phase5_cohort_v2",
      confidence_rubric_version: "phase5_confidence_v1",
      trend_rule_version: "phase5_trend_v1",
      trend_available: true,
      trend_history_snapshots: 7,
      assignments: LEAGUES.flatMap((league) =>
        SCORING.map((scoring) => ({
          scoring_preset: scoring,
          league_size: Number(league.split("-")[1]),
          cohort_id: "no-keeper",
          exact: false,
          sufficient: true,
          source_format_detail: "IS_KEEPER=N (approximate cohort)",
          failed_clauses: [],
        })),
      ),
      unpriced_top_players: 5,
    },
    player_status: {
      players: 316,
      sleeper_available: true,
      sleeper_matched: 311,
      sleeper_identity_conflicts: 5,
      observed_at_utc: SNAPSHOT_AT,
      source_ids: ["nflreadpy", "sleeper"],
    },
    supported_presets: LEAGUES,
    sources: [
      {
        source_id: "myfantasyleague_adp",
        status: "warning",
        retrieved_at_utc: SNAPSHOT_AT,
        source_as_of_utc: null,
        record_count: 1492,
        warnings: ["cohort_approximate"],
      },
      {
        source_id: "nflreadpy",
        status: "warning",
        retrieved_at_utc: GENERATED_AT,
        source_as_of_utc: null,
        record_count: 762239,
        warnings: [],
      },
    ],
    quality_gate: { status: "pass", critical_failures: 0, warnings: 3 },
    warnings: ["tiers are published having not passed the frozen tier stability gate"],
    methodology_version: "phase4_intrinsic_v1",
  };
}

// ---- build the site -----------------------------------------------------------------------

const outArg = process.argv.indexOf("--out");
const outPath = outArg === -1 ? null : resolve(repo, process.argv[outArg + 1]);

const dist = mkdtempSync(join(tmpdir(), "ffdraft-perf-"));
cpSync(resolve(repo, "web/dist"), dist, { recursive: true });
const dataDir = join(dist, "data");
mkdirSync(dataDir, { recursive: true });

const files = {
  "build_metadata.json": metadata(),
  "tiers.json": envelope("tiers", "tier_record", tierRecords()),
  "arbitrage.json": envelope("arbitrage", "arbitrage_record", arbitrageRecords()),
  "projections.json": envelope("projections", "player_projection", projectionRecords()),
  "player_status.json": envelope("player_status", "player_status", statusRecords()),
};
const bytes = {};
for (const [name, payload] of Object.entries(files)) {
  const body = `${JSON.stringify(payload)}\n`;
  writeFileSync(join(dataDir, name), body, "utf-8");
  bytes[name] = body.length;
}

const server = createStaticServer({ roots: [{ base: "/", dir: dist }] });
await new Promise((ready) => server.listen(4188, ready));
const base = "http://localhost:4188";

const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});

/** Median of five, so one scheduling hiccup does not become the headline. */
async function median(label, run) {
  const samples = [];
  for (let i = 0; i < 5; i += 1) samples.push(await run());
  samples.sort((a, b) => a - b);
  return { label, ms: Number(samples[2].toFixed(1)), min: Number(samples[0].toFixed(1)), max: Number(samples[4].toFixed(1)) };
}

const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const results = [];

// Cold load: navigation start to the first rendered board row.
results.push(
  await median("cold load to first board row", async () => {
    const fresh = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const started = Date.now();
    await fresh.goto(`${base}/`, { waitUntil: "commit" });
    await fresh.locator(".board-row").first().waitFor();
    const elapsed = Date.now() - started;
    await fresh.close();
    return elapsed;
  }),
);

await page.goto(`${base}/`, { waitUntil: "networkidle" });
await page.locator(".board-row").first().waitFor();

const shape = await page.evaluate(() => ({
  domNodes: document.querySelectorAll("*").length,
  boardHeightPx: Math.round(
    document.querySelector(".tier-board")?.getBoundingClientRect().height ?? 0,
  ),
  tableRows: document.querySelectorAll("table.sheet tbody tr").length,
  boardRows: document.querySelectorAll(".board-row").length,
  svgNodes: document.querySelectorAll("svg *").length,
}));

// Sorting three hundred rows by a numeric column.
results.push(
  await median("sort the 300-row tier table", async () => {
    const started = Date.now();
    await page.getByRole("button", { name: /Median VORP/ }).click();
    await page.waitForFunction(
      () => document.querySelector("th[aria-sort='descending'], th[aria-sort='ascending']") !== null,
    );
    return Date.now() - started;
  }),
);

// Expanding every tier: 100 board rows appear at once on the default depth.
results.push(
  await median("expand all tiers", async () => {
    await page.goto(`${base}/?tiers=none`, { waitUntil: "networkidle" });
    const started = Date.now();
    await page.getByRole("button", { name: /Expand all tiers/ }).click();
    await page.locator(".board-row").first().waitFor();
    return Date.now() - started;
  }),
);

// The whole board charted: 300 rows in the board plus 300 in the table.
results.push(
  await median("switch to the full 300-player board", async () => {
    await page.goto(`${base}/?tiers=0.1.2.3.4.5.6.7.8`, { waitUntil: "networkidle" });
    const started = Date.now();
    await page.getByRole("button", { name: /Show full board/ }).click();
    await page.waitForFunction(() => document.querySelectorAll(".board-row").length > 250);
    return Date.now() - started;
  }),
);

const fullBoardShape = await page.evaluate(() => ({
  domNodes: document.querySelectorAll("*").length,
  boardRows: document.querySelectorAll(".board-row").length,
  boardHeightPx: Math.round(
    document.querySelector(".tier-board")?.getBoundingClientRect().height ?? 0,
  ),
}));

// A position filter over the whole index.
results.push(
  await median("filter to one position", async () => {
    await page.goto(`${base}/?position=all`, { waitUntil: "networkidle" });
    await page.locator(".board-row").first().waitFor();
    const started = Date.now();
    await page.getByRole("radio", { name: "WR" }).click();
    await page.waitForFunction(() => window.location.search.includes("position=wr"));
    return Date.now() - started;
  }),
);

// Search, past the 220ms debounce the control declares.
results.push(
  await median("search, after the declared debounce", async () => {
    await page.goto(`${base}/`, { waitUntil: "networkidle" });
    await page.locator(".board-row").first().waitFor();
    const started = Date.now();
    await page.getByLabel("Player search").fill("robinson");
    await page.waitForFunction(() => window.location.search.includes("search=robinson"));
    return Date.now() - started;
  }),
);

// Opening the card, which joins four artifacts for one player.
results.push(
  await median("open the player card", async () => {
    await page.goto(`${base}/`, { waitUntil: "networkidle" });
    await page.locator(".board-row").first().waitFor();
    const started = Date.now();
    await page.locator("table.sheet .player-name").first().click();
    await page.getByRole("dialog").waitFor();
    const elapsed = Date.now() - started;
    await page.keyboard.press("Escape");
    return elapsed;
  }),
);

// The arbitrage view: rail plus a table of every priced row.
results.push(
  await median("render the arbitrage view", async () => {
    const started = Date.now();
    await page.goto(`${base}/?view=arbitrage`, { waitUntil: "commit" });
    await page.locator(".rail-row").first().waitFor();
    return Date.now() - started;
  }),
);

await browser.close();
server.close();

const record = {
  generated_at_utc: new Date().toISOString(),
  board: {
    tier_rows: files["tiers.json"].record_count,
    arbitrage_rows: files["arbitrage.json"].record_count,
    projection_rows: files["projections.json"].record_count,
    status_rows: files["player_status.json"].record_count,
  },
  artifact_bytes: bytes,
  default_view: shape,
  full_board_view: fullBoardShape,
  timings_ms: results,
};

const pad = (value, width) => String(value).padStart(width);
process.stdout.write("\nArtifacts served (uncompressed)\n");
for (const [name, size] of Object.entries(bytes)) {
  process.stdout.write(`  ${name.padEnd(24)} ${pad((size / 1024).toFixed(0), 7)} KB\n`);
}
process.stdout.write("\nDOM\n");
process.stdout.write(`  default view    ${pad(shape.domNodes, 7)} nodes, ${shape.boardRows} board rows, ${shape.tableRows} table rows, board ${shape.boardHeightPx}px tall\n`);
process.stdout.write(`  full 300 board  ${pad(fullBoardShape.domNodes, 7)} nodes, ${fullBoardShape.boardRows} board rows, board ${fullBoardShape.boardHeightPx}px tall\n`);
process.stdout.write(`  svg elements    ${pad(shape.svgNodes, 7)}\n`);
process.stdout.write("\nInteraction, median of five (min-max)\n");
for (const item of results) {
  process.stdout.write(`  ${item.label.padEnd(38)} ${pad(item.ms, 6)} ms  (${item.min}-${item.max})\n`);
}

if (outPath !== null) {
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, `${JSON.stringify(record, null, 1)}\n`, "utf-8");
  process.stdout.write(`\nwrote ${outPath}\n`);
}
