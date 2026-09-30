/**
 * Serve fixture artifacts to a component test the way the deployed site serves them (ADR-098).
 *
 * The page reads `data/manifest.json` and the content-addressed files it names, never a whole
 * artifact. Every component test used to stub `fetch` with a map of whole artifacts; it now
 * hands the same map to `stubSite`, which lays it out as manifest, slices and card shards and
 * answers the page's requests from that layout.
 *
 * **A test encoder, not the encoder.** Production files are written by
 * `src/ffdraft/artifacts/serving.py`, and `web/tests/serving.test.ts` decodes files that
 * encoder wrote. This one writes the plainest valid form of the same format — every field a
 * column, no dictionary, no join — so a component test exercises the real loader, store and
 * decoder against its own fixtures without Python. The families and card sections are the
 * Python module's, and the end-to-end suite, which runs the Python encoder over these same
 * fixtures, is what would notice the two lists drifting apart.
 */

import { createHash } from "node:crypto";

import { vi } from "vitest";

import { bucketOf } from "../src/data/serving";

interface Envelope {
  readonly records?: readonly Record<string, unknown>[];
  readonly [key: string]: unknown;
}

/** Sentinel for "this build did not publish that artifact". */
export const MISSING = Symbol("missing");

const CARD_BUCKETS = 64;

const FAMILIES: readonly {
  readonly name: string;
  readonly artifact: string;
  readonly partition: "block" | "scoring" | "all";
  readonly only?: readonly string[];
}[] = [
  { name: "tiers", artifact: "tiers", partition: "block" },
  { name: "arbitrage", artifact: "arbitrage", partition: "block" },
  { name: "player_status", artifact: "player_status", partition: "all" },
  { name: "ros_tiers", artifact: "ros_tiers", partition: "block" },
  { name: "inseason_opportunity", artifact: "inseason_opportunity", partition: "block" },
  {
    name: "inseason_opportunity_cohort",
    artifact: "inseason_opportunity",
    partition: "block",
    only: [
      "league_preset_id",
      "scoring_preset",
      "player_id",
      "position",
      "add_count",
      "drop_count",
      "snap_share_last3",
      "target_share_last3",
    ],
  },
  { name: "weekly_projections", artifact: "weekly_projections", partition: "scoring" },
  { name: "team_matchups", artifact: "team_matchups", partition: "all" },
  { name: "behavior_trend_series", artifact: "behavior_trend_series", partition: "all" },
  { name: "player_usage", artifact: "player_usage", partition: "all" },
  {
    name: "player_usage_cohort",
    artifact: "player_usage",
    partition: "all",
    only: ["player_id", "position", "touchdown_points_share", "pass_epa_per_dropback"],
  },
  { name: "player_headshots", artifact: "player_headshots", partition: "all" },
];

const CARD_SECTIONS: readonly (readonly [string, "block" | "scoring" | "all"])[] = [
  ["tiers", "block"],
  ["arbitrage", "block"],
  ["market_trend_series", "block"],
  ["projections", "scoring"],
  ["player_status", "all"],
  ["player_headshots", "all"],
  ["ros_tiers", "block"],
  ["inseason_opportunity", "block"],
  ["weekly_projections", "scoring"],
  ["player_usage", "all"],
  ["behavior_trend_series", "all"],
];

const FILENAMES: Readonly<Record<string, string>> = {
  tiers: "tiers.json",
  arbitrage: "arbitrage.json",
  market_trend_series: "market_trend_series.json",
  projections: "projections.json",
  player_status: "player_status.json",
  ros_tiers: "ros_tiers.json",
  inseason_opportunity: "inseason_opportunity.json",
  player_headshots: "player_headshots.json",
  behavior_trend_series: "behavior_trend_series.json",
  player_usage: "player_usage.json",
  team_matchups: "team_matchups.json",
  weekly_projections: "weekly_projections.json",
};

function partitionKey(record: Record<string, unknown>, partition: "block" | "scoring" | "all"): string | null {
  if (partition === "all") return "all";
  if (partition === "scoring") return typeof record.scoring_preset === "string" ? record.scoring_preset : null;
  if (typeof record.league_preset_id !== "string" || typeof record.scoring_preset !== "string") return null;
  return `${record.league_preset_id}.${record.scoring_preset}`;
}

function table(records: readonly Record<string, unknown>[], only?: readonly string[]): Record<string, unknown> {
  const fields: string[] = [];
  for (const record of records) {
    for (const key of Object.keys(record)) {
      if (!fields.includes(key) && (only === undefined || only.includes(key))) fields.push(key);
    }
  }
  const absent: Record<string, number[]> = {};
  const columns: Record<string, unknown[]> = {};
  for (const name of fields) {
    columns[name] = records.map((record, index) => {
      if (!(name in record)) (absent[name] ??= []).push(index);
      return record[name] ?? null;
    });
  }
  return { count: records.length, fields, ...(Object.keys(absent).length > 0 ? { absent } : {}), columns };
}

function header(envelope: Envelope): Record<string, unknown> {
  return Object.fromEntries(Object.entries(envelope).filter(([key]) => key !== "records"));
}

/** The served layout of a map of whole artifacts: served path → payload, plus the manifest. */
export function layoutOf(payloads: Readonly<Record<string, unknown>>): {
  readonly manifest: Record<string, unknown>;
  readonly files: ReadonlyMap<string, string>;
} {
  const envelopes = new Map<string, Envelope>();
  for (const [artifact, filename] of Object.entries(FILENAMES)) {
    const payload = payloads[filename];
    if (payload !== undefined && payload !== MISSING) envelopes.set(artifact, payload as Envelope);
  }
  const files = new Map<string, string>();
  const entries: Record<string, string> = {};
  const add = (key: string, payload: unknown): void => {
    const text = `${JSON.stringify(payload)}\n`;
    const digest = createHash("sha256").update(text, "utf8").digest("hex").slice(0, 16);
    files.set(`serve/${key}.${digest}.json`, text);
    entries[key] = digest;
  };
  add("players", { format: "serving_v1", names: {} });

  for (const family of FAMILIES) {
    const envelope = envelopes.get(family.artifact);
    if (envelope === undefined) continue;
    const groups = new Map<string, Record<string, unknown>[]>();
    for (const record of envelope.records ?? []) {
      const key = partitionKey(record, family.partition);
      if (key === null) continue;
      const group = groups.get(key) ?? [];
      group.push(record);
      groups.set(key, group);
    }
    for (const [key, rows] of groups) {
      add(`${family.name}/${key}`, {
        format: "serving_v1",
        family: family.name,
        artifact: family.artifact,
        partition: key,
        ...table(rows, family.only),
      });
    }
  }

  const blocks = new Set<string>();
  for (const [artifact, partition] of CARD_SECTIONS) {
    if (partition !== "block") continue;
    for (const record of envelopes.get(artifact)?.records ?? []) {
      const key = partitionKey(record, "block");
      if (key !== null) blocks.add(key);
    }
  }
  for (const block of blocks) {
    const scoring = block.split(".")[1] ?? "";
    const buckets = new Map<number, Map<string, Record<string, unknown>[]>>();
    for (const [artifact, partition] of CARD_SECTIONS) {
      const want = partition === "block" ? block : partition === "scoring" ? scoring : "all";
      for (const record of envelopes.get(artifact)?.records ?? []) {
        if (partitionKey(record, partition) !== want) continue;
        const bucket = bucketOf(String(record.player_id), CARD_BUCKETS);
        const sections = buckets.get(bucket) ?? new Map<string, Record<string, unknown>[]>();
        const rows = sections.get(artifact) ?? [];
        rows.push(record);
        sections.set(artifact, rows);
        buckets.set(bucket, sections);
      }
    }
    for (const [bucket, sections] of buckets) {
      add(`card/${block}/${String(bucket).padStart(2, "0")}`, {
        format: "serving_v1",
        family: "card",
        partition: `${block}/${String(bucket).padStart(2, "0")}`,
        sections: Object.fromEntries([...sections].map(([artifact, rows]) => [artifact, table(rows)])),
      });
    }
  }

  const manifest: Record<string, unknown> = {
    format: "serving_v1",
    version: "1.0",
    card_buckets: CARD_BUCKETS,
    artifacts: Object.fromEntries([...envelopes].map(([artifact, envelope]) => [artifact, header(envelope)])),
    files: entries,
  };
  const build = payloads["build_metadata.json"];
  if (build !== undefined && build !== MISSING) manifest.build_metadata = build;
  const ros = payloads["ros_build_metadata.json"];
  if (ros !== undefined && ros !== MISSING) manifest.ros_build_metadata = ros;
  return { manifest, files };
}

/**
 * Stub `fetch` with the served layout of `payloads` (filename → whole artifact, or `MISSING`).
 * `manifest: false` answers the manifest with a 404, as a site with no data would.
 */
export function stubSite(
  payloads: Readonly<Record<string, unknown>>,
  options: { readonly manifest?: boolean } = {},
): void {
  const { manifest, files } = layoutOf(payloads);
  const manifestText = JSON.stringify(manifest);
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const path = input.replace(/^.*?\/data\//, "");
      if (path === "manifest.json" && options.manifest !== false) {
        return Promise.resolve(new Response(manifestText, { status: 200 }));
      }
      const body = files.get(path);
      if (body === undefined) return Promise.resolve(new Response(null, { status: 404 }));
      return Promise.resolve(new Response(body, { status: 200 }));
    }),
  );
}
