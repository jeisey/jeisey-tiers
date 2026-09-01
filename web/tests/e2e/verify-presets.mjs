/**
 * Verify every supported scoring x league-size preset, in the artifacts and in the browser.
 *
 * `verify-real-build.mjs` proves that what the browser renders equals the bytes the build
 * wrote, and it does that in depth — cell by cell — for **one** block, PPR/redraft-12. This
 * file is the other axis: shallower per block, but across all **nine**. The failure it exists
 * to catch is a preset that is fine in the artifact and dead in the product, or fine for the
 * default board and broken for the eight nobody looks at.
 *
 * That combination is not hypothetical here. `redraft-14` joined the supported set during
 * Phase 7 and the whole coverage gate is a `min` across the nine blocks precisely because "a
 * mean would hide the case this gate exists to catch: eight healthy presets and one that lost
 * its cohort".
 *
 * Two passes, in this order, because the cheaper one localises the failure:
 *
 *   1. **Artifacts.** Read `tiers`, `projections`, `arbitrage` and `build_metadata` off disk
 *      and check each block's own structure: rows present, fair ranks unique and a complete
 *      1..N run, tiers present and **contiguous in fair-rank order** (AGENTS.md section 9),
 *      tier ordinals zero-based per `schemas/tier_record.schema.json`, projections and
 *      arbitrage present, and every arbitrage row joining a tier row.
 *   2. **Browser.** Drive all nine URLs and check the product actually resolves each one: the
 *      board, the tier table and the arbitrage table populate, the two controls report the
 *      requested state, the rank-1 name on screen is the artifact's rank-1 name for *that*
 *      block, and nothing logs a console error, throws, refuses a contract or reports a
 *      degraded artifact.
 *
 * Usage:
 *
 *   node web/tests/e2e/verify-presets.mjs                                  # web/dist at /
 *   node web/tests/e2e/verify-presets.mjs --dist web/dist --base-path /jeisey-tiers/
 *   node web/tests/e2e/verify-presets.mjs --url https://jeisey.github.io/jeisey-tiers \
 *                                         --data web/public/data
 *
 * With `--url` no server is started, so this runs against a deployed site; the artifacts are
 * still read from disk, because the point is to compare the page with the bytes the build
 * produced. Exit status is 0 only when every block passes both passes.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

import { createStaticServer } from "./static-server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../..");

/** The launch matrix. `docs/DATA_CONTRACTS.md`: three scorings x three league sizes. */
const SCORINGS = [
  { value: "std", preset: "STD", label: "Standard" },
  { value: "half", preset: "HALF", label: "Half PPR" },
  { value: "ppr", preset: "PPR", label: "PPR" },
];
const TEAM_COUNTS = [10, 12, 14];

function parseArgs(argv) {
  const args = { dist: "web/dist", data: null, basePath: "/", port: 4181, url: null };
  for (let i = 0; i < argv.length; i += 1) {
    const [flag, inline] = argv[i].split("=");
    const value = inline ?? argv[++i];
    switch (flag) {
      case "--dist":
        args.dist = value;
        break;
      case "--data":
        args.data = value;
        break;
      case "--base-path":
        args.basePath = value.endsWith("/") ? value : `${value}/`;
        break;
      case "--port":
        args.port = Number(value);
        break;
      case "--url":
        args.url = value.replace(/\/$/, "");
        break;
      default:
        throw new Error(`unknown option ${flag}`);
    }
  }
  args.data ??= `${args.dist}/data`;
  return args;
}

const args = parseArgs(process.argv.slice(2));
const dataDir = resolve(repo, args.data);
if (!existsSync(`${dataDir}/tiers.json`)) {
  console.error(`no artifacts at ${dataDir}. Build the site with web/public/data/ populated.`);
  process.exit(2);
}

const read = (name) => JSON.parse(readFileSync(`${dataDir}/${name}`, "utf-8"));
const tiers = read("tiers.json");
const projections = read("projections.json");
const arbitrage = read("arbitrage.json");
const metadata = read("build_metadata.json");

const failures = [];
const fail = (block, message) => failures.push(`[${block}] ${message}`);

// --------------------------------------------------------------------- pass 1: artifacts

const summary = [];

for (const scoring of SCORINGS) {
  for (const teams of TEAM_COUNTS) {
    const preset = `redraft-${teams}`;
    const name = `${scoring.preset}/${preset}`;
    const match = (record) =>
      record.league_preset_id === preset && record.scoring_preset === scoring.preset;

    const tierRows = tiers.records.filter(match).sort((a, b) => a.fair_rank - b.fair_rank);
    // A projection is a points forecast, so it varies by scoring and not by league size —
    // `player_projection.schema.json` carries no `league_preset_id`. Matching it on the block
    // key would report every projection missing, which is a bug in the checker rather than a
    // finding about the build.
    const projectionRows = projections.records.filter(
      (record) => record.scoring_preset === scoring.preset,
    );
    const arbRows = arbitrage.records.filter(match);

    if (tierRows.length === 0) {
      fail(name, "the tier artifact publishes no rows for this block");
      continue;
    }
    if (projectionRows.length === 0) fail(name, "the projection artifact publishes no rows");
    if (arbRows.length === 0) fail(name, "the arbitrage artifact publishes no rows");

    // Fair rank is the board's identity: a duplicate or a hole means two players share a
    // position on the board, or one is missing from it.
    const ranks = tierRows.map((row) => row.fair_rank);
    const unique = new Set(ranks);
    if (unique.size !== ranks.length) {
      fail(name, `fair ranks are not unique: ${ranks.length} rows, ${unique.size} distinct`);
    }
    for (let i = 0; i < ranks.length; i += 1) {
      if (ranks[i] !== i + 1) {
        fail(name, `fair rank is not a complete 1..N run: position ${i + 1} holds ${ranks[i]}`);
        break;
      }
    }

    // Tiers are discovered, contiguous in fair-rank order, and zero-based.
    const ordinals = tierRows.map((row) => row.tier_ordinal);
    const distinct = [...new Set(ordinals)];
    if (distinct.length === 0) fail(name, "no tier is published");
    if (Math.min(...distinct) !== 0) {
      fail(name, `tier ordinals are not zero-based: lowest is ${Math.min(...distinct)}`);
    }
    for (let i = 1; i < ordinals.length; i += 1) {
      const step = ordinals[i] - ordinals[i - 1];
      if (step !== 0 && step !== 1) {
        fail(
          name,
          `tiers are not contiguous in fair-rank order: rank ${ranks[i]} moves tier by ${step}`,
        );
        break;
      }
    }

    // An arbitrage row that names a player the board does not rank has nothing to be a gap
    // against.
    const boardIds = new Set(tierRows.map((row) => row.player_id));
    const orphans = arbRows.filter((row) => !boardIds.has(row.player_id));
    if (orphans.length > 0) {
      fail(name, `${orphans.length} arbitrage row(s) name a player this block does not rank`);
    }

    summary.push({
      block: name,
      tierRows: tierRows.length,
      tiers: distinct.length,
      projections: projectionRows.length,
      arbitrageRows: arbRows.length,
      topPlayer: tierRows[0].display_name,
      openAll: [...distinct].sort((a, b) => a - b).join("."),
    });
  }
}

if (summary.length !== 9) {
  failures.push(`expected nine preset blocks in the artifacts, found ${summary.length}`);
}

// ----------------------------------------------------------------------- pass 2: browser

let server = null;
let base = args.url;
if (base === null) {
  const distDir = resolve(repo, args.dist);
  if (!existsSync(distDir)) {
    console.error(`no build at ${distDir}`);
    process.exit(2);
  }
  server = createStaticServer({ roots: [{ base: args.basePath, dir: distDir }] });
  await new Promise((ready) => server.listen(args.port, ready));
  base = `http://localhost:${args.port}${args.basePath.replace(/\/$/, "")}`;
}

const origin = new URL(base).origin;
const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});

try {
  for (const row of summary) {
    const [presetName, presetId] = row.block.split("/");
    const scoring = SCORINGS.find((s) => s.preset === presetName);
    const teams = Number(presetId.replace("redraft-", ""));
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

    // Anything the page logs as an error, or throws, is a defect in this block even if the
    // DOM still fills in. A silently caught contract mismatch would render an empty board.
    const noise = [];
    page.on("console", (message) => {
      if (message.type() === "error") noise.push(`console: ${message.text()}`);
    });
    page.on("pageerror", (error) => noise.push(`pageerror: ${error.message}`));
    // `docs/ARCHITECTURE.md` section 3.2: no vendor and no private store in the render path.
    // Asserted per block rather than once, because a preset-specific code path is exactly
    // where a stray fetch would hide.
    page.on("request", (request) => {
      const url = request.url();
      if (!url.startsWith(origin) && !url.startsWith("data:") && !url.startsWith("blob:")) {
        noise.push(`request left the site: ${url}`);
      }
    });

    try {
      // `tiers=` opens every tier the block publishes, so the board is read from the
      // artifact rather than from an assumption about how deep the default open set reaches.
      const query = `?scoring=${scoring.value}&teams=${teams}&tiers=${row.openAll}`;
      await page.goto(`${base}/${query}`, { waitUntil: "networkidle" });
      await page.waitForSelector("table.sheet tbody tr", { timeout: 20000 });

      const seen = await page.evaluate(() => ({
        boardRows: document.querySelectorAll(".board-row").length,
        tableRows: document.querySelectorAll("table.sheet tbody tr").length,
        firstName: document.querySelector("table.sheet tbody tr .player-name")?.textContent?.trim() ?? null,
        // A radio carries no group attribute of its own, so each group is found through the
        // `aria-labelledby` label the control renders, and its checked option read from there.
        ...(() => {
          const groups = {};
          for (const group of document.querySelectorAll('[role="radiogroup"]')) {
            const label = document.getElementById(group.getAttribute("aria-labelledby"));
            const checked = group.querySelector('[role="radio"][aria-checked="true"]');
            groups[(label?.textContent ?? "").trim().toLowerCase()] =
              checked?.getAttribute("aria-label") ?? null;
          }
          return { scoring: groups.scoring ?? null, teams: groups.teams ?? null };
        })(),
        refusal: document.querySelector('[role="alert"]')?.textContent?.trim() ?? null,
        degraded: document.body.textContent.includes("Degraded artifacts."),
      }));

      if (seen.refusal !== null) fail(row.block, `the page refused: ${seen.refusal}`);
      if (seen.degraded) fail(row.block, "the page reports a degraded artifact");
      if (seen.boardRows === 0) fail(row.block, "the tier board rendered no rows");
      if (seen.tableRows === 0) fail(row.block, "the tier table rendered no rows");
      if (seen.firstName !== row.topPlayer) {
        fail(row.block, `rank 1 renders ${seen.firstName}, artifact says ${row.topPlayer}`);
      }
      // The controls are the product's own report of which block it is showing. If they
      // disagree with the URL, every number on the page belongs to a different league.
      if (seen.scoring !== scoring.label) {
        fail(row.block, `scoring control reads ${seen.scoring}, expected ${scoring.label}`);
      }
      if (seen.teams !== `${teams}-team league`) {
        fail(row.block, `teams control reads ${seen.teams}, expected ${teams}-team league`);
      }

      // Arbitrage is a separate artifact and may legitimately be absent; where the artifact
      // has rows for this block, the view must show them.
      await page.goto(`${base}/?view=arbitrage&scoring=${scoring.value}&teams=${teams}`, {
        waitUntil: "networkidle",
      });
      await page.waitForSelector("table.sheet tbody tr", { timeout: 20000 });
      const arbRendered = await page.$$eval("table.sheet tbody tr", (trs) => trs.length);
      if (row.arbitrageRows > 0 && arbRendered === 0) {
        fail(row.block, `arbitrage artifact has ${row.arbitrageRows} rows and the view is empty`);
      }
      row.arbitrageRendered = arbRendered;

      if (noise.length > 0) fail(row.block, `browser reported: ${noise.join("; ")}`);
    } catch (error) {
      fail(row.block, `did not resolve: ${error.message}`);
    } finally {
      await page.close();
    }
  }
} finally {
  await browser.close();
  if (server !== null) server.close();
}

// ------------------------------------------------------------------------------- report

console.log(`build ${metadata.build_id ?? metadata.current?.build_id ?? "(unknown)"}`);
console.log(`verified ${summary.length} preset blocks against ${dataDir} and ${base}\n`);
const width = Math.max(...summary.map((row) => row.block.length));
console.log(
  `${"block".padEnd(width)}  ${"tiers".padStart(6)} ${"rows".padStart(6)} ${"proj".padStart(6)} ${"arb".padStart(6)} ${"shown".padStart(6)}  top`,
);
for (const row of summary) {
  console.log(
    `${row.block.padEnd(width)}  ${String(row.tiers).padStart(6)} ${String(row.tierRows).padStart(6)} ` +
      `${String(row.projections).padStart(6)} ${String(row.arbitrageRows).padStart(6)} ` +
      `${String(row.arbitrageRendered ?? "-").padStart(6)}  ${row.topPlayer}`,
  );
}

if (failures.length > 0) {
  console.error(`\n${failures.length} failure(s):`);
  for (const message of failures) console.error(`  ${message}`);
  process.exit(1);
}
console.log("\nall nine preset blocks pass both the artifact and the browser checks");
