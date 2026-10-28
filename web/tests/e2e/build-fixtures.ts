/**
 * Write the deterministic fixture artifacts into a built site, and produce both builds.
 *
 * Two things happen here and both are Phase-7 insurance:
 *
 * 1. The site is built twice — once at `/` and once at `/jeisey-tiers/` — so the project Pages
 *    base path is exercised now rather than discovered after a deploy
 *    (`docs/ARCHITECTURE.md` section 11).
 * 2. Each `dist/data/` is replaced with the fixture artifacts, so an end-to-end run asserts on
 *    fixed numbers rather than on whatever the last real build happened to produce.
 */

import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type * as Fixtures from "../fixtures/artifacts";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../..");

// The fixture module is TypeScript; `tsx`-free loading is not available, so the fixtures are
// re-exported through a tiny build step instead: vite is already a dependency and can bundle
// one module to a temporary ESM file.
async function loadFixtures(): Promise<typeof Fixtures> {
  const { build } = await import("vite");
  const outDir = resolve(repo, "node_modules/.cache/ffdraft-e2e");
  await build({
    root: repo,
    logLevel: "error",
    configFile: false,
    build: {
      outDir,
      emptyOutDir: true,
      lib: {
        entry: resolve(repo, "web/tests/fixtures/artifacts.ts"),
        formats: ["es"],
        fileName: "artifacts",
      },
      ssr: true,
      minify: false,
      write: true,
    },
  });
  return (await import(resolve(outDir, "artifacts.js"))) as typeof Fixtures;
}

function viteBuild(base: string, outDir: string): void {
  execFileSync(
    process.execPath,
    [resolve(repo, "node_modules/vite/bin/vite.js"), "build", "--outDir", outDir, "--base", base],
    { cwd: repo, stdio: "inherit", env: { ...process.env, VITE_BASE_PATH: base } },
  );
}

/** Artifacts a scenario deliberately withholds are simply not written; the server then 404s. */
function writeArtifacts(dataDir: string, files: Record<string, unknown>): void {
  rmSync(dataDir, { recursive: true, force: true });
  mkdirSync(dataDir, { recursive: true });
  for (const [name, payload] of Object.entries(files)) {
    writeFileSync(resolve(dataDir, name), `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
  }
}

/**
 * Lay a data directory out the way the deployed site serves it (ADR-098): the manifest, the
 * per-block slices and the card shards, written by the **production** packager. The page
 * reads nothing else, so every end-to-end spec exercises the real encoder against these
 * fixtures — the same code `daily-refresh.yml` runs on the real board.
 */
function packageSiteData(dataDir: string): void {
  execFileSync("uv", ["run", "--frozen", "ffdraft", "package-site-data", dataDir], {
    cwd: repo,
    stdio: ["ignore", "ignore", "inherit"],
  });
}

/** A tiny CSV so the full-download link resolves to a real file under both base paths. */
function writeCsv(dataDir: string, name: string, header: string): void {
  writeFileSync(resolve(dataDir, name), `${header}\r\n`, "utf-8");
}

export async function prepare(): Promise<void> {
  const fixtures = await loadFixtures();

  const targets = [
    { base: "/", out: "web/dist" },
    { base: "/jeisey-tiers/", out: "web/dist-base" },
  ];

  for (const target of targets) {
    viteBuild(target.base, resolve(repo, target.out));
    const dataDir = resolve(repo, target.out, "data");
    writeArtifacts(dataDir, fixtures.fixtureFiles());
    writeCsv(dataDir, "tiers.csv", "fair_rank,display_name");
    writeCsv(dataDir, "arbitrage.csv", "fair_rank,display_name");
    packageSiteData(dataDir);
  }

  /*
   * ADR-116: the project-Pages build at `/jeisey-tiers/` with the in-season bundle, for the
   * Insights share-link test (a copied link must keep the Pages base path). The app is the
   * `dist-base` build copied unchanged — only its data differs — so it costs no Vite build. It
   * is not in the static server's mounts (`/jeisey-tiers/` is the draft site there); the spec
   * serves it itself, at the same base, on a port of its own.
   */
  const pagesInSeason = resolve(repo, "web/dist-pages-in-season");
  rmSync(pagesInSeason, { recursive: true, force: true });
  cpSync(resolve(repo, "web/dist-base"), pagesInSeason, { recursive: true });
  writeArtifacts(resolve(pagesInSeason, "data"), { ...fixtures.fixtureFiles(), ...fixtures.inSeasonFixtureFiles() });
  for (const [name, header] of [
    ["tiers.csv", "fair_rank,display_name"],
    ["arbitrage.csv", "fair_rank,display_name"],
    ["ros_tiers.csv", "ros_fair_rank,player"],
    ["inseason_opportunity.csv", "ros_fair_rank,player"],
  ] as const) {
    writeCsv(resolve(pagesInSeason, "data"), name, header);
  }
  packageSiteData(resolve(pagesInSeason, "data"));

  /** A build that simply does not publish one artifact; the server then 404s it. */
  const omit = (name: string): Record<string, unknown> =>
    Object.fromEntries(Object.entries(fixtures.fixtureFiles()).filter(([key]) => key !== name));

  // Scenario variants, served from their own directories so a test picks one by URL rather
  // than by mutating shared state.
  const scenarios: Record<string, Record<string, unknown>> = {
    "no-market": omit("arbitrage.json"),
    "no-status": omit("player_status.json"),
    /*
     * In-season, with everything. The mode, the tabs, the ROS board, the Opportunity board
     * and the ADR-076 disclosures are only reachable from a build that published an
     * in-season bundle, and the ordinary fixture build deliberately does not — because
     * before kickoff, not publishing one is the correct behaviour.
     */
    "in-season": { ...fixtures.fixtureFiles(), ...fixtures.inSeasonFixtureFiles() },
    /*
     * In season, with the optional behaviour feed down. The Opportunity Board must publish
     * every intrinsic value and empty behaviour columns, which is the degradation roadmap
     * 12.5 requires and the one a user is most likely to actually meet.
     */
    "in-season-no-behavior": {
      ...fixtures.fixtureFiles(),
      ...fixtures.inSeasonFixtureFiles(false),
    },
    /*
     * In season, with the signal layer withheld (ADR-091). The ROS build publishes neither
     * signal artifact when either builder fails, and every board, card and pick must still
     * render — each missing block saying which artifact is absent rather than drawing zeros.
     */
    "in-season-no-signals": {
      ...fixtures.fixtureFiles(),
      ...fixtures.inSeasonFixtureFiles(true, { signals: "absent" }),
    },
    /*
     * In season, from a build that published no Skill Tree (an older deploy, or a failed
     * enrichment, ADR-107): the card has no Skill Tree section and nothing else changes.
     */
    "in-season-no-skill-tree": {
      ...fixtures.fixtureFiles(),
      ...fixtures.inSeasonFixtureFiles(true, { skillTree: "absent" }),
    },
    /*
     * ADR-112: an older deploy with no ESPN block at all, and a build whose newest ESPN
     * capture is past the freshness bound. Both must disable the ESPN ceiling, say why, and
     * leave every board whole — never read an unknown as 0%.
     */
    "in-season-no-espn": {
      ...fixtures.fixtureFiles(),
      ...fixtures.inSeasonFixtureFiles(true, { espn: "absent" }),
    },
    "in-season-espn-stale": {
      ...fixtures.fixtureFiles(),
      ...fixtures.inSeasonFixtureFiles(true, { espn: "stale" }),
    },
    /*
     * ADR-113: an older deploy with no recent-form artifact or metadata block. The board must
     * render whole, the window and breakout controls disabled with their reason, and a link's
     * breakout filter named rather than applied.
     */
    "in-season-no-recent": {
      ...fixtures.fixtureFiles(),
      ...fixtures.inSeasonFixtureFiles(true, { recent: "absent" }),
    },
    /*
     * ADR-116: a build whose upside family could not be made (no current ESPN readings). The
     * Insights tab must name the family and its reason, and publish every other family.
     */
    "in-season-insights-degraded": {
      ...fixtures.fixtureFiles(),
      ...fixtures.inSeasonFixtureFiles(true, { insights: "degraded" }),
    },
    /*
     * The *other* market condition, as its own site.
     *
     * `MARKET_CONDITIONS` exists because Phase 8 found every market-sensitive test written
     * against a uniformly `low` board with a null trend, a state production had already left.
     * The component tests exercise both; without a build there was no way to *look* at the
     * matured one, so a visual review could only ever see the launch condition.
     */
    /*
     * The two lifecycle windows in which the season has started and no rest-of-season board
     * exists yet — opening week, and after the last scored week. Both are the *draft* bundle
     * with a season-state block that says the season has begun, which is exactly the state
     * ADR-079 exists to make sayable.
     */
    "awaiting-first-week": fixtures.lifecycleFixtureFiles("awaiting_first_week"),
    "season-complete": fixtures.lifecycleFixtureFiles("season_complete"),
    matured: fixtures.fixtureFiles("matured"),
    /*
     * A matured board whose second market has **no retained history at all**.
     *
     * The state a newly enabled source is in on its first morning, and the one production
     * was mistaken for: a current FFC price with nothing behind it. The card must name the
     * market it has nothing for rather than showing another market's line, and the rest of
     * the market section must be unaffected — a missing chart is not a missing price
     * (ADR-081).
     */
    "no-ffc-history": {
      ...fixtures.fixtureFiles("matured"),
      "market_trend_series.json": {
        ...fixtures.marketTrendSeriesEnvelope("matured"),
        records: fixtures
          .marketTrendSeriesRecords("matured")
          .filter((record) => record.market_source_id !== "fantasyfootballcalculator_adp"),
      },
    },
    "bad-schema": {
      ...fixtures.fixtureFiles(),
      "tiers.json": { ...fixtures.tierEnvelope(), schema_version: "2.0" },
    },
  };

  for (const [name, files] of Object.entries(scenarios)) {
    // Each scenario is built at its own base path, so its asset and data URLs resolve inside
    // its own mount. Built at "/" they would silently read the healthy build's artifacts.
    viteBuild(`/scenario/${name}/`, resolve(repo, `web/dist-${name}`));
    const dataDir = resolve(repo, `web/dist-${name}`, "data");
    writeArtifacts(dataDir, files);
    writeCsv(dataDir, "tiers.csv", "fair_rank,display_name");
    writeCsv(dataDir, "arbitrage.csv", "fair_rank,display_name");
    writeCsv(dataDir, "ros_tiers.csv", "ros_fair_rank,player");
    writeCsv(dataDir, "inseason_opportunity.csv", "ros_fair_rank,player");
    packageSiteData(dataDir);
  }
}

/**
 * The size model (ADR-098): the app with a real-sized, synthetic data set in it, for the
 * payload budget gate (`verify-budget.mjs`). Built only when asked — it is the one build no
 * behavioural spec reads — with `E2E_SIZE_MODEL=1` or `npm run e2e:size-model`.
 */
export function prepareSizeModel(): void {
  const out = resolve(repo, "web/dist-size-model");
  viteBuild("/jeisey-tiers/", out);
  execFileSync(
    "uv",
    ["run", "--frozen", "python", "scripts/size_model.py", "--out", resolve(out, "data")],
    { cwd: repo, stdio: ["ignore", "ignore", "inherit"] },
  );
}

if (import.meta.url === `file://${process.argv[1] ?? ""}`) {
  await prepare();
}
