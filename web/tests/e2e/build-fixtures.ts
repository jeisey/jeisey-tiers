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
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
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
  }

  /** A build that simply does not publish one artifact; the server then 404s it. */
  const omit = (name: string): Record<string, unknown> =>
    Object.fromEntries(Object.entries(fixtures.fixtureFiles()).filter(([key]) => key !== name));

  // Scenario variants, served from their own directories so a test picks one by URL rather
  // than by mutating shared state.
  const scenarios: Record<string, Record<string, unknown>> = {
    "no-market": omit("arbitrage.json"),
    "no-status": omit("player_status.json"),
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
  }
}

if (import.meta.url === `file://${process.argv[1] ?? ""}`) {
  await prepare();
}
