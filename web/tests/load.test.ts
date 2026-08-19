/**
 * Loader behaviour.
 *
 * The version guard is the point of this module: `docs/DATA_CONTRACTS.md` section 13 says an
 * unsupported major version must produce a clear error, never a best-effort render.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import type { BuildMetadata, TierRecord } from "../src/data/contracts";
import {
  ArtifactShapeError,
  ArtifactVersionError,
  artifactUrl,
  buildAgeHours,
  degradedSources,
  isSupportedVersion,
  loadArtifact,
  loadBuildMetadata,
  majorVersion,
  parseBuildMetadata,
  parseEnvelope,
} from "../src/data/load";

const GOLDEN_DIR = resolve(__dirname, "../../tests/fixtures/artifacts");

function golden(name: string): unknown {
  return JSON.parse(readFileSync(resolve(GOLDEN_DIR, name), "utf-8")) as unknown;
}

function mockFetchOnce(payload: unknown, ok = true): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok,
        status: ok ? 200 : 404,
        json: () => Promise.resolve(payload),
      } as Response),
    ),
  );
}

describe("version handling", () => {
  it("compares major versions only", () => {
    expect(majorVersion("1.4")).toBe("1");
    expect(isSupportedVersion("1.0")).toBe(true);
    expect(isSupportedVersion("1.7")).toBe(true);
    expect(isSupportedVersion("2.0")).toBe(false);
  });

  it("refuses an unsupported major version with an actionable message", () => {
    const payload = { ...(golden("tiers.json") as object), schema_version: "2.0" };
    expect(() => parseEnvelope<TierRecord>(payload, "tiers")).toThrow(ArtifactVersionError);
    try {
      parseEnvelope<TierRecord>(payload, "tiers");
    } catch (error) {
      expect((error as Error).message).toContain("2.0");
      expect((error as Error).message).toContain("Refusing to render");
    }
  });
});

describe("envelope parsing", () => {
  it("accepts the committed golden tier artifact", () => {
    const envelope = parseEnvelope<TierRecord>(golden("tiers.json"), "tiers");
    expect(envelope.records.length).toBe(envelope.record_count);
    expect(envelope.records[0]?.fair_rank).toBe(1);
  });

  it("rejects a payload whose artifact name disagrees", () => {
    expect(() => parseEnvelope<TierRecord>(golden("arbitrage.json"), "tiers")).toThrow(
      ArtifactShapeError,
    );
  });

  it("rejects a record_count that lies about the payload", () => {
    const payload = { ...(golden("tiers.json") as object), record_count: 999 };
    expect(() => parseEnvelope<TierRecord>(payload, "tiers")).toThrow(/disagrees/);
  });

  it("rejects non-objects and missing versions", () => {
    expect(() => parseEnvelope<TierRecord>([], "tiers")).toThrow(ArtifactShapeError);
    expect(() => parseEnvelope<TierRecord>({}, "tiers")).toThrow(/schema_version/);
  });
});

describe("build metadata", () => {
  it("parses the golden metadata", () => {
    const metadata = parseBuildMetadata(golden("build_metadata.json"));
    expect(metadata.arbitrage_mode).toBe("baseline");
    expect(metadata.intrinsic_model_version).toBe("fixture-stub-0");
  });

  it("reports freshness from the artifact, never from a hardcoded date", () => {
    const metadata = parseBuildMetadata(golden("build_metadata.json"));
    const now = new Date("2026-08-18T18:00:00Z");
    expect(buildAgeHours(metadata, now)).toBeCloseTo(6, 5);
  });

  it("treats an unparseable timestamp as infinitely stale", () => {
    const metadata = { generated_at_utc: "nope" } as unknown as BuildMetadata;
    expect(buildAgeHours(metadata)).toBe(Number.POSITIVE_INFINITY);
  });

  it("lists degraded sources for the freshness panel", () => {
    const metadata = parseBuildMetadata(golden("build_metadata.json"));
    expect(degradedSources(metadata).length).toBeGreaterThan(0);
  });
});

describe("artifact urls", () => {
  it("respects a project Pages base path", () => {
    expect(artifactUrl("tiers.json", "/jeisey-tiers/")).toBe("/jeisey-tiers/data/tiers.json");
    expect(artifactUrl("tiers.json", "/jeisey-tiers")).toBe("/jeisey-tiers/data/tiers.json");
    expect(artifactUrl("tiers.json", "/")).toBe("/data/tiers.json");
  });
});

describe("fetching", () => {
  it("loads and narrows an artifact", async () => {
    mockFetchOnce(golden("tiers.json"));
    const envelope = await loadArtifact<TierRecord>("tiers");
    expect(envelope.artifact).toBe("tiers");
  });

  it("surfaces an HTTP failure as an artifact error", async () => {
    mockFetchOnce({}, false);
    await expect(loadBuildMetadata()).rejects.toThrow(ArtifactShapeError);
  });
});
