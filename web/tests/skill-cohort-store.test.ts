/**
 * ADR-117: the store's Skill Tree cohort loader against the golden served layout.
 *
 * A comparison fetches the position's small index (named by the manifest) and then the one
 * metric slice it names, verified against the index's hash. Nothing else: no player bucket, no
 * other metric. Repeated opens reuse the decoded rows; a metric the build serves no cohort for,
 * and an older build that serves no index at all, resolve to null rather than to an error.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseManifest, type Manifest } from "../src/data/serving";
import { DataStore, requiredKeys, skillCohortIndexKey, skillCohortKey } from "../src/data/store";

const GOLDEN_DIR = resolve(__dirname, "../../tests/fixtures/artifacts");

function read(path: string): string {
  return readFileSync(resolve(GOLDEN_DIR, path), "utf-8");
}

const golden = parseManifest(JSON.parse(read("manifest.json")) as unknown);

/** A fetch that serves the golden `serve/` directory and records every path asked for. */
function servedFromGolden(): { readonly paths: string[] } {
  const paths: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL) => {
      const path = new URL(String(input), "http://localhost/").pathname;
      paths.push(path);
      const relative = path.replace(/^.*\/data\//, "");
      try {
        return Promise.resolve(new Response(read(relative), { status: 200 }));
      } catch {
        return Promise.resolve(new Response(null, { status: 404 }));
      }
    }),
  );
  return { paths };
}

function cohortSource(manifest: Manifest = golden) {
  const store = new DataStore(manifest);
  const source = store.skillTreeSource();
  if (source === null) throw new Error("the golden build publishes a Skill Tree");
  return { store, source };
}

describe("the Skill Tree cohort loader (ADR-117)", () => {
  beforeEach(() => {
    vi.stubGlobal("caches", undefined);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is never part of what a view or a card needs", () => {
    for (const view of ["ros", "opportunity", "startsit", "potw", "myleagues", "tiers"] as const) {
      const keys = requiredKeys(golden, {
        view,
        leaguePreset: "redraft-12",
        scoring: "PPR",
        cardPlayerId: "gsis:00-0000002",
      });
      expect(keys.some((key) => key.startsWith("skill_cohort"))).toBe(false);
    }
    expect(Object.keys(golden.files).some((key) => key.startsWith("skill_cohort/"))).toBe(false);
    expect(skillCohortIndexKey(golden, "RB")).toBe("skill_cohort_index/RB");
  });

  it("fetches the position's index and one metric slice, once, and decodes the cohort", async () => {
    const { paths } = servedFromGolden();
    const { source } = cohortSource();
    expect(source.hasCohorts("RB")).toBe(true);
    const [first, again] = await Promise.all([
      source.loadCohort("RB", "yards_per_carry"),
      source.loadCohort("RB", "yards_per_carry"),
    ]);
    expect(first).not.toBeNull();
    expect(again?.rows).toBe(first?.rows);
    const fetched = paths.filter((path) => path.includes("/serve/"));
    expect(fetched.filter((path) => path.includes("/skill_cohort_index/RB."))).toHaveLength(1);
    expect(fetched.filter((path) => path.includes("/skill_cohort/RB.yards_per_carry."))).toHaveLength(1);
    expect(fetched.some((path) => path.includes("/skill_tree/") || path.includes("/card/"))).toBe(false);

    const rows = first?.rows ?? [];
    const ranked = rows.filter((row) => row.state === "ranked");
    expect(ranked.length).toBeGreaterThanOrEqual(5);
    for (const row of ranked) expect(row.cohort_size).toBe(ranked.length);
    for (const row of rows) {
      expect(row.position).toBe("RB");
      expect(row.metric_id).toBe("yards_per_carry");
      expect(typeof row.value).toBe("number");
    }
    expect(new Set(rows.map((row) => row.player_id)).size).toBe(rows.length);

    // A second metric at the same position reuses the index.
    await source.loadCohort("RB", "carries");
    expect(paths.filter((path) => path.includes("/skill_cohort_index/"))).toHaveLength(1);
    expect(paths.filter((path) => path.includes("/skill_cohort/RB.carries."))).toHaveLength(1);
  });

  it("names every member through the published dictionary", async () => {
    servedFromGolden();
    const { store, source } = cohortSource();
    await store.ensure(["players"]);
    const cohort = await source.loadCohort("QB", "cpoe");
    for (const row of cohort?.rows ?? []) expect(source.nameOf(String(row.player_id))).toBeTruthy();
  });

  it("resolves null for a metric with no cohort and for a build that serves no index", async () => {
    servedFromGolden();
    const { source } = cohortSource();
    expect(await source.loadCohort("WR", "combine_forty")).toBeNull();
    expect(await source.loadCohort("WR", "no_such_metric")).toBeNull();

    const older = parseManifest({
      ...golden,
      files: Object.fromEntries(Object.entries(golden.files).filter(([key]) => !key.startsWith("skill_cohort_index/"))),
    });
    const { source: old } = cohortSource(older);
    expect(old.hasCohorts("RB")).toBe(false);
    expect(await old.loadCohort("RB", "carries")).toBeNull();
  });

  it("refuses a slice whose bytes do not match the hash its index names", async () => {
    const index = JSON.parse(read(`serve/skill_cohort_index/RB.${golden.files["skill_cohort_index/RB"] ?? ""}.json`)) as {
      files: Record<string, string>;
    };
    const digest = index.files["RB.carries"] ?? "";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const path = new URL(String(input), "http://localhost/").pathname;
        const relative = path.replace(/^.*\/data\//, "");
        if (relative.includes(skillCohortKey("RB", "carries"))) {
          return Promise.resolve(new Response('{"format":"serving_v1","tampered":true}', { status: 200 }));
        }
        return Promise.resolve(new Response(read(relative), { status: 200 }));
      }),
    );
    expect(digest).toMatch(/^[0-9a-f]{16}$/);
    const { source } = cohortSource();
    await expect(source.loadCohort("RB", "carries")).rejects.toThrow(/does not match its hash/);
  });
});
