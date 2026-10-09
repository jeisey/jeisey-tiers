/**
 * Loading, and the split between critical and degradable.
 *
 * `docs/DATA_CONTRACTS.md` section 13 requires a refusal on an unsupported major version. The
 * point of the split is that an optional artifact going missing must not take the intrinsic
 * board with it — every number in `tiers.json` is correct whether or not a market price exists.
 *
 * Since ADR-098 the page reads a manifest and fetches served slices lazily; `loadBundle` below
 * opens the site and then loads every non-card slice, which is the whole-artifact view these
 * assertions were written against. What a first paint actually fetches is pinned separately,
 * at the end of this file.
 */

import { describe, expect, it, vi } from "vitest";

import { CriticalArtifactError, openSite } from "../src/data/bundle";
import { requiredKeys } from "../src/data/store";
import {
  arbitrageEnvelope,
  buildMetadata,
  inSeasonFixtureFiles,
  opportunityEnvelope,
  playerStatusEnvelope,
  projectionEnvelope,
  rosBuildMetadata,
  rosTierEnvelope,
  tierEnvelope,
} from "./fixtures/artifacts";
import { MISSING, stubSite } from "./site";

type Payloads = Record<string, unknown>;

function serve(payloads: Payloads): void {
  stubSite(payloads);
}

/** Open the site and load every served slice except card shards: the whole board, in memory. */
async function loadBundle(options: { readonly base?: string } = {}) {
  const store = await openSite(options);
  const keys = Object.keys(store.manifest.files).filter((key) => !key.startsWith("card/"));
  await store.ensure(keys);
  return { index: store.boardIndex(keys), degradations: store.degradations, inSeason: store.inSeason(keys) };
}

function everything(overrides: Payloads = {}): Payloads {
  return {
    "build_metadata.json": buildMetadata(),
    "tiers.json": tierEnvelope(),
    "arbitrage.json": arbitrageEnvelope(),
    "player_status.json": playerStatusEnvelope(),
    "projections.json": projectionEnvelope(),
    ...overrides,
  };
}

describe("loadBundle", () => {
  it("loads a complete build with no degradation", async () => {
    serve(everything());
    const bundle = await loadBundle();
    expect(bundle.degradations).toEqual([]);
    expect(bundle.index.hasArbitrage).toBe(true);
    expect(bundle.index.hasPlayerStatus).toBe(true);
    expect(bundle.index.tiersFor("redraft-12", "PPR")).toHaveLength(18);
  });

  it("refuses an incompatible tier contract rather than rendering it", async () => {
    serve(everything({ "tiers.json": tierEnvelope("2.0") }));
    await expect(loadBundle()).rejects.toBeInstanceOf(CriticalArtifactError);
    await loadBundle().catch((error: unknown) => {
      const critical = error as CriticalArtifactError;
      expect(critical.incompatible).toBe(true);
      expect(critical.artifact).toBe("tiers.json");
      expect(critical.expected).toBe("1.0");
      expect(critical.found).toBe("2.0");
    });
  });

  it("refuses an incompatible build metadata contract", async () => {
    serve(everything({ "build_metadata.json": buildMetadata({ schema_version: "3.0" }) }));
    await expect(loadBundle()).rejects.toThrow(/schema version 3.0/);
  });

  it("fails when the tier artifact is missing at all", async () => {
    serve(everything({ "tiers.json": MISSING }));
    await expect(loadBundle()).rejects.toBeInstanceOf(CriticalArtifactError);
  });

  it("degrades gracefully when arbitrage is unavailable", async () => {
    serve(everything({ "arbitrage.json": MISSING }));
    const bundle = await loadBundle();
    expect(bundle.index.hasArbitrage).toBe(false);
    expect(bundle.degradations.map((entry) => entry.artifact)).toEqual(["arbitrage"]);
    expect(bundle.degradations[0]?.reason).toBe("unavailable");
    // The intrinsic board is untouched.
    expect(bundle.index.tiersFor("redraft-12", "PPR")).toHaveLength(18);
  });

  it("degrades gracefully when player status is unavailable", async () => {
    serve(everything({ "player_status.json": MISSING }));
    const bundle = await loadBundle();
    expect(bundle.index.hasPlayerStatus).toBe(false);
    expect(bundle.index.statusFor("gsis:00-0000002")).toBeNull();
    // Every model value survives the loss of the annotation source.
    const tier = bundle.index.tierFor("redraft-12", "PPR", "gsis:00-0000002");
    expect(tier?.p50_vorp).toBeCloseTo(133.6, 1);
  });

  it("degrades gracefully when projections are unavailable", async () => {
    serve(everything({ "projections.json": MISSING }));
    const bundle = await loadBundle();
    expect(bundle.index.hasProjections).toBe(false);
    expect(bundle.index.tiersFor("redraft-12", "PPR")).toHaveLength(18);
    expect(bundle.index.arbitrageFor("redraft-12", "PPR").length).toBeGreaterThan(0);
  });

  it("marks an optional artifact with an unsupported version as incompatible, not merely absent", async () => {
    serve(
      everything({
        "arbitrage.json": { ...arbitrageEnvelope(), schema_version: "2.0" },
      }),
    );
    const bundle = await loadBundle();
    expect(bundle.degradations[0]).toMatchObject({ artifact: "arbitrage", reason: "incompatible" });
  });

  it("reports degradations in a fixed order however the network settles", async () => {
    serve(everything({ "arbitrage.json": MISSING, "player_status.json": MISSING, "projections.json": MISSING }));
    const first = await loadBundle();
    const second = await loadBundle();
    expect(first.degradations.map((entry) => entry.artifact)).toEqual([
      "arbitrage",
      "player_status",
      "projections",
    ]);
    expect(second.degradations).toEqual(first.degradations);
  });

  it("fetches only generated files and never a vendor", async () => {
    serve(everything());
    await loadBundle();
    const calls = vi.mocked(fetch).mock.calls.map((call) => call[0] as string);
    // The manifest, then content-addressed files under `/data/serve/`. The load-bearing half
    // is the second assertion: a vendor host must never appear here, because a static page
    // that fetched a market feed would put a vendor on the critical path (ADR-066). A
    // portrait host (ADR-087) must not either — a portrait is requested by an open card.
    expect(calls[0]).toMatch(/\/data\/manifest\.json$/);
    for (const url of calls.slice(1)) {
      expect(url).toMatch(/\/data\/serve\/[a-z_]+\/?[A-Za-z0-9_.-]*\.[0-9a-f]{16}\.json$|\/data\/serve\/players\.[0-9a-f]{16}\.json$/);
    }
    for (const url of calls) {
      expect(url).not.toMatch(
        /myfantasyleague|sleeper|nflverse|fantasypros|fantasycalc|espncdn/i,
      );
    }
  });

  it("loads the in-season bundle when the build published one", async () => {
    serve({ ...everything(), ...inSeasonFixtureFiles() });
    const bundle = await loadBundle();
    expect(bundle.inSeason).not.toBeNull();
    expect(bundle.inSeason?.throughWeek).toBe(8);
    expect(bundle.inSeason?.derivedMode).toBe("in_season");
    expect(bundle.inSeason?.hasOpportunity).toBe(true);
    expect(bundle.inSeason?.rosFor("redraft-12", "PPR").length).toBeGreaterThan(0);
    // The draft bundle is untouched: the two are independent, and a page can hold both.
    expect(bundle.index.tiersFor("redraft-12", "PPR")).toHaveLength(18);
  });

  it("returns no in-season bundle before kickoff rather than failing the page", async () => {
    serve(everything());
    const bundle = await loadBundle();
    expect(bundle.inSeason).toBeNull();
    // The whole draft product still loads. Absence of an in-season board is the ordinary
    // state in August, not a degradation of anything.
    expect(bundle.degradations).toEqual([]);
    expect(bundle.index.tiersFor("redraft-12", "PPR")).toHaveLength(18);
  });

  it("refuses a rest-of-season board whose disclosures are missing", async () => {
    // ADR-076: the flag may not be shown without the sentences that qualify it, so a bundle
    // that dropped them must not render at all rather than rendering the flag bare.
    const metadata = rosBuildMetadata();
    const stripped = { ...metadata } as Record<string, unknown>;
    delete stripped.disclosures;
    serve({
      ...everything(),
      "ros_build_metadata.json": stripped,
      "ros_tiers.json": rosTierEnvelope(),
      "inseason_opportunity.json": opportunityEnvelope(),
    });
    const bundle = await loadBundle();
    expect(bundle.inSeason).toBeNull();
  });

  it("keeps the rest-of-season board when only the opportunity artifact is missing", async () => {
    const files = inSeasonFixtureFiles();
    serve({ ...everything(), ...files, "inseason_opportunity.json": MISSING });
    const bundle = await loadBundle();
    expect(bundle.inSeason).not.toBeNull();
    expect(bundle.inSeason?.hasOpportunity).toBe(false);
    // Every rest-of-season value survives the loss of the optional board beside it.
    expect(bundle.inSeason?.rosFor("redraft-12", "PPR").length).toBeGreaterThan(0);
  });

  it("carries behaviour columns as null, not zero, when the feed was unavailable", async () => {
    serve({ ...everything(), ...inSeasonFixtureFiles(false) });
    const bundle = await loadBundle();
    const row = bundle.inSeason?.opportunityFor("redraft-12", "PPR")[0];
    expect(row?.behavior_available).toBe(false);
    // A zero would claim "nobody added him". Null says "we do not know", which is true.
    expect(row?.add_count).toBeNull();
    expect(row?.ros_expected_vorp).toBeTypeOf("number");
  });

  it("never modifies an intrinsic value on the Opportunity Board", async () => {
    serve({ ...everything(), ...inSeasonFixtureFiles() });
    const bundle = await loadBundle();
    const inSeason = bundle.inSeason;
    expect(inSeason).not.toBeNull();
    if (inSeason === null) return;
    let compared = 0;
    for (const row of inSeason.opportunityFor("redraft-12", "PPR")) {
      const source = inSeason.rosRecordFor("redraft-12", "PPR", row.player_id);
      if (source === null) {
        // Absent from the board is exactly what a surfaced row is, and it must say so.
        expect(row.outside_tier_board).toBe(true);
        expect(row.surface_reasons.length).toBeGreaterThan(0);
        expect(row.ros_tier).toBeNull();
        continue;
      }
      compared += 1;
      expect(row.ros_fair_rank).toBe(source.ros_fair_rank);
      expect(row.ros_expected_vorp).toBe(source.ros_expected_vorp);
      expect(row.ros_uncertainty).toBe(source.ros_uncertainty);
      expect(row.ros_tier).toBe(source.ros_tier);
    }
    expect(compared).toBeGreaterThan(0);
  });

  it("resolves artifacts under a project Pages base path", async () => {
    serve(everything());
    await loadBundle({ base: "/jeisey-tiers/" });
    const calls = vi.mocked(fetch).mock.calls.map((call) => call[0] as string);
    expect(calls.every((url) => url.startsWith("/jeisey-tiers/data/"))).toBe(true);
  });
});

describe("what a first paint fetches (ADR-098)", () => {
  it("the in-season default view fetches the manifest, the names, one ROS block and one actuals slice", async () => {
    serve({ ...everything(), ...inSeasonFixtureFiles() });
    const store = await openSite();
    await store.ensure(
      requiredKeys(store.manifest, {
        view: "ros",
        leaguePreset: "redraft-12",
        scoring: "PPR",
        cardPlayerId: null,
      }),
    );
    const calls = vi.mocked(fetch).mock.calls.map((call) => call[0] as string);
    expect(calls).toHaveLength(5);
    expect(calls[0]).toBe("/data/manifest.json");
    expect(calls.some((url) => url.includes("/serve/players."))).toBe(true);
    expect(calls.some((url) => url.includes("/serve/ros_tiers/redraft-12.PPR."))).toBe(true);
    // ADR-105: the season actuals for the scoring preset — one slice whatever the league size.
    expect(calls.some((url) => url.includes("/serve/season_actuals/PPR."))).toBe(true);
    // ADR-101: the compact status slice the availability policy reads, and not the full one.
    expect(calls.some((url) => url.includes("/serve/player_availability/all."))).toBe(true);
    expect(calls.some((url) => url.includes("/serve/player_status/"))).toBe(false);
    // Nothing from the draft bundle, and nothing for any other block.
    expect(calls.some((url) => /tiers\/|arbitrage|projections|market_trend/.test(url.replace("ros_tiers", "")))).toBe(false);
    const bundle = store.inSeason(Object.keys(store.manifest.files));
    expect(bundle?.rosFor("redraft-12", "PPR").length).toBeGreaterThan(0);
    expect(bundle?.rosFor("redraft-10", "PPR")).toEqual([]);
  });

  it("the Trade tab needs exactly the ROS block and status slice the default view already loaded (ADR-100, ADR-101)", async () => {
    serve({ ...everything(), ...inSeasonFixtureFiles() });
    const store = await openSite();
    for (const scoring of ["STD", "HALF", "PPR"] as const) {
      for (const leaguePreset of ["redraft-10", "redraft-12", "redraft-14"]) {
        const context = { leaguePreset, scoring, cardPlayerId: null };
        const trade = requiredKeys(store.manifest, { ...context, view: "trade" });
        expect(trade).toEqual(["players", "player_availability/all", `ros_tiers/${leaguePreset}.${scoring}`]);
        // The RoS view reads the same, plus the season actuals for its comparison (ADR-105).
        expect(requiredKeys(store.manifest, { ...context, view: "ros" })).toEqual([
          ...trade,
          `season_actuals/${scoring}`,
        ]);
      }
    }
  });

  it("a Trade tab on a build with no rest-of-season board needs nothing but the names", async () => {
    serve(everything());
    const store = await openSite();
    expect(
      requiredKeys(store.manifest, { view: "trade", leaguePreset: "redraft-12", scoring: "PPR", cardPlayerId: null }),
    ).toEqual(["players"]);
  });

  it("the manifest is always revalidated, and slices are not", async () => {
    serve(everything());
    const store = await openSite();
    await store.ensure(["players"]);
    const [first, second] = vi.mocked(fetch).mock.calls;
    expect((first?.[1])?.cache).toBe("no-cache");
    expect((second?.[1])?.cache).toBeUndefined();
  });

  it("a card fetches one shard, plus the in-season cohort the ROS view lacks", async () => {
    serve({ ...everything(), ...inSeasonFixtureFiles() });
    const store = await openSite();
    const context = { view: "ros" as const, leaguePreset: "redraft-12", scoring: "PPR" as const };
    const board = requiredKeys(store.manifest, { ...context, cardPlayerId: null });
    const card = requiredKeys(store.manifest, { ...context, cardPlayerId: "gsis:00-0000002" });
    const added = card.filter((key) => !board.includes(key));
    expect(added.filter((key) => key.startsWith("card/"))).toHaveLength(1);
    expect(added.filter((key) => !key.startsWith("card/")).sort()).toEqual(
      ["inseason_opportunity_cohort/redraft-12.PPR", "player_usage_cohort/all", "team_matchups/all"].sort(),
    );
  });

  it("refuses when the site has no manifest at all", async () => {
    stubSite(everything(), { manifest: false });
    await expect(openSite()).rejects.toBeInstanceOf(CriticalArtifactError);
  });
});
