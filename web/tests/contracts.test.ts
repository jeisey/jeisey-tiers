/**
 * Cross-language contract test.
 *
 * The Python serializers and these TypeScript types are two independent descriptions of the
 * same public contract, and two descriptions drift. This test pins both to the JSON Schemas
 * and to the committed golden artifacts, so a field added, renamed or reordered on either
 * side fails here rather than showing up as an empty table column.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ARTIFACT_FIELDS,
  ARTIFACT_FILENAMES,
  ARTIFACT_SCHEMA_VERSION,
  BUILD_METADATA_FILENAME,
  type ArtifactName,
} from "../src/data/contracts";

const REPO_ROOT = resolve(__dirname, "../..");
const SCHEMA_DIR = resolve(REPO_ROOT, "schemas");
const GOLDEN_DIR = resolve(REPO_ROOT, "tests/fixtures/artifacts");

const SCHEMA_BY_ARTIFACT: Readonly<Record<ArtifactName, string>> = {
  tiers: "tier_record",
  arbitrage: "arbitrage_record",
  projections: "player_projection",
  market_snapshot: "market_snapshot",
};

function readJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, "utf-8")) as Record<string, unknown>;
}

function schemaProperties(name: string): string[] {
  const schema = readJson(resolve(SCHEMA_DIR, `${name}.schema.json`));
  return Object.keys(schema.properties as Record<string, unknown>);
}

const ARTIFACTS = Object.keys(ARTIFACT_FIELDS) as ArtifactName[];

describe("TypeScript record types match the JSON Schemas", () => {
  it.each(ARTIFACTS)("%s field list equals the schema property order", (artifact) => {
    expect([...ARTIFACT_FIELDS[artifact]]).toEqual(
      schemaProperties(SCHEMA_BY_ARTIFACT[artifact]),
    );
  });

  it.each(ARTIFACTS)("%s golden records carry exactly the declared fields", (artifact) => {
    const envelope = readJson(resolve(GOLDEN_DIR, ARTIFACT_FILENAMES[artifact]));
    const records = envelope.records as Record<string, unknown>[];
    expect(records.length).toBeGreaterThan(0);
    for (const record of records) {
      expect(Object.keys(record)).toEqual([...ARTIFACT_FIELDS[artifact]]);
    }
  });

  it.each(ARTIFACTS)("%s golden envelope declares the supported version", (artifact) => {
    const envelope = readJson(resolve(GOLDEN_DIR, ARTIFACT_FILENAMES[artifact]));
    expect(envelope.schema_version).toBe(ARTIFACT_SCHEMA_VERSION);
    expect(envelope.artifact).toBe(artifact);
  });
});

describe("build metadata", () => {
  it("declares the supported version and the fields the shell reads", () => {
    const metadata = readJson(resolve(GOLDEN_DIR, BUILD_METADATA_FILENAME));
    expect(metadata.schema_version).toBe(ARTIFACT_SCHEMA_VERSION);
    for (const field of [
      "build_id",
      "generated_at_utc",
      "season",
      "intrinsic_model_version",
      "arbitrage_mode",
      "supported_presets",
      "sources",
      "quality_gate",
      "warnings",
    ]) {
      expect(metadata).toHaveProperty(field);
    }
  });

  it("matches the build_metadata schema's property set", () => {
    const metadata = readJson(resolve(GOLDEN_DIR, BUILD_METADATA_FILENAME));
    const declared = new Set(schemaProperties("build_metadata"));
    for (const key of Object.keys(metadata)) {
      expect(declared.has(key)).toBe(true);
    }
  });
});
