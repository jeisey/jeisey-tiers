/**
 * Loading, and the split between critical and degradable.
 *
 * `docs/DATA_CONTRACTS.md` section 13 requires a refusal on an unsupported major version. The
 * point of the split is that an optional artifact going missing must not take the intrinsic
 * board with it — every number in `tiers.json` is correct whether or not a market price exists.
 */

import { describe, expect, it, vi } from "vitest";

import { CriticalArtifactError, loadBundle } from "../src/data/bundle";
import {
  arbitrageEnvelope,
  buildMetadata,
  playerStatusEnvelope,
  projectionEnvelope,
  tierEnvelope,
} from "./fixtures/artifacts";

type Payloads = Record<string, unknown>;

/** Sentinel for "this build did not publish that artifact". */
const MISSING = Symbol("missing");

function serve(payloads: Payloads): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const name = input.split("/").pop() ?? "";
      const payload = payloads[name];
      if (payload === undefined || payload === MISSING) {
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) } as Response);
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) } as Response);
    }),
  );
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

  it("fetches only generated artifacts and never a vendor", async () => {
    serve(everything());
    await loadBundle();
    const calls = vi.mocked(fetch).mock.calls.map((call) => call[0] as string);
    expect(calls).toHaveLength(5);
    for (const url of calls) {
      expect(url).toMatch(/\/data\/[a-z_]+\.json$/);
      expect(url).not.toMatch(/myfantasyleague|sleeper|nflverse|fantasypros|fantasycalc/i);
    }
  });

  it("resolves artifacts under a project Pages base path", async () => {
    serve(everything());
    await loadBundle({ base: "/jeisey-tiers/" });
    const calls = vi.mocked(fetch).mock.calls.map((call) => call[0] as string);
    expect(calls.every((url) => url.startsWith("/jeisey-tiers/data/"))).toBe(true);
  });
});
