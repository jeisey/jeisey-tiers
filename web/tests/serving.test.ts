/**
 * The browser's decoder against the Python encoder's own output (ADR-098).
 *
 * `tests/fixtures/artifacts/` holds the golden artifacts *and* the served layout
 * `ffdraft build-fixture-artifacts` packaged beside them. Every served table is decoded here
 * with the same code the page runs and compared, record for record and byte for byte of its
 * JSON, with the matching records of the whole artifact. A decoder that drifted from the
 * encoder — a field order, a joined row, a nested leaf, a dictionary name — fails here, before
 * a browser ever renders a number from it.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  ServedFileError,
  bucketOf,
  decodeTable,
  fetchServed,
  parseIndex,
  parseManifest,
  pruneCache,
  type EnvelopeHeader,
  type Table,
} from "../src/data/serving";

const GOLDEN_DIR = resolve(__dirname, "../../tests/fixtures/artifacts");

type Row = Record<string, unknown>;

function read(path: string): unknown {
  return JSON.parse(readFileSync(resolve(GOLDEN_DIR, path), "utf-8")) as unknown;
}

const manifest = parseManifest(read("manifest.json"));
const names = (read(`serve/players.${manifest.files.players ?? ""}.json`) as { names: Record<string, string> })
  .names;

function envelope(artifact: string): { header: EnvelopeHeader; records: Row[] } {
  const payload = read(`${artifact}.json`) as { records: Row[] } & EnvelopeHeader;
  const header = manifest.artifacts[artifact as keyof typeof manifest.artifacts];
  if (header === undefined) throw new Error(`${artifact} is not in the manifest`);
  return { header, records: payload.records };
}

function served(key: string): Row {
  return read(`serve/${key}.${manifest.files[key] ?? ""}.json`) as Row;
}

function partitionOf(row: Row, partition: string, family = ""): string {
  // ADR-107: the Skill Tree's readings split by the card's bucket, its definitions by position.
  if (family === "skill_tree" || family === "espn_ownership_series") {
    return String(bucketOf(String(row.player_id), manifest.card_buckets)).padStart(2, "0");
  }
  if (family === "skill_tree_definitions") return String(row.position);
  if (partition.includes(".")) return `${String(row.league_preset_id)}.${String(row.scoring_preset)}`;
  if (partition === "all") return "all";
  return String(row.scoring_preset);
}

function project(row: Row, fields: readonly string[]): Row {
  return Object.fromEntries(fields.filter((name) => name in row).map((name) => [name, row[name]]));
}

describe("the golden served layout", () => {
  it("is the manifest the page expects", () => {
    expect(manifest.format).toBe("serving_v1");
    expect(manifest.card_buckets).toBe(64);
    expect(Object.keys(manifest.files).some((key) => key.startsWith("card/"))).toBe(true);
  });

  it("decodes every slice to exactly its artifact's matching records", () => {
    const decoded = new Map<string, Row[]>();
    const keys = Object.keys(manifest.files)
      // ADR-117: an index names files; it is decoded by its own test below.
      .filter((key) => key !== "players" && !key.startsWith("card/") && !key.startsWith("skill_cohort_index/"))
      // The ROS slices first: the Opportunity Board's slices join them.
      .sort((a, b) => Number(!a.startsWith("ros_tiers/")) - Number(!b.startsWith("ros_tiers/")));
    expect(keys.length).toBeGreaterThan(5);
    let joined = 0;
    for (const key of keys) {
      const payload = served(key) as unknown as Table & {
        artifact: string;
        family: string;
        partition: string;
        join?: Table["join"];
      };
      const { header, records } = envelope(payload.artifact);
      let source: Map<string, Row> | undefined;
      if (payload.join !== undefined) {
        joined += payload.join.rows.replace(/0/g, "").length;
        source = new Map(
          (decoded.get(`${payload.join.family}/${payload.partition}`) ?? []).map((row) => [String(row.player_id), row]),
        );
      }
      const rows = decodeTable<Row>(payload, header, names, source);
      decoded.set(key, rows);
      const expected = records
        .filter((row) => partitionOf(row, payload.partition, payload.family) === payload.partition)
        .map((row) => project(row, payload.fields));
      expect(rows.map((row) => JSON.stringify(row))).toEqual(expected.map((row) => JSON.stringify(row)));
    }
    // The golden board exercises the join, or this test would not be testing it.
    expect(joined).toBeGreaterThan(0);
  });

  it("decodes every Skill Tree cohort its index names to exactly that metric's cohort (ADR-117)", () => {
    const indexes = Object.keys(manifest.files).filter((key) => key.startsWith("skill_cohort_index/"));
    expect(indexes.map((key) => key.split("/")[1]).sort()).toEqual(["QB", "RB", "TE", "WR"]);
    const { header, records } = envelope("player_skill_tree");
    let slices = 0;
    let unranked = 0;
    for (const key of indexes) {
      const index = parseIndex(served(key));
      expect(index).not.toBeNull();
      if (index === null) continue;
      expect(index.indexes).toBe("skill_cohort");
      for (const [entry, digest] of Object.entries(index.files)) {
        const [position = "", metric = ""] = entry.split(".");
        expect(position).toBe(index.partition);
        const payload = read(`serve/skill_cohort/${entry}.${digest}.json`) as Table & { family: string };
        expect(payload.family).toBe("skill_cohort");
        const rows = decodeTable<Row>(payload, header, names);
        const expected = records
          .filter(
            (row) =>
              row.position === position &&
              row.metric_id === metric &&
              ["ranked", "below_minimum", "small_cohort"].includes(String(row.state)) &&
              row.source_season === null,
          )
          .map((row) => project(row, payload.fields));
        expect(rows.map((row) => JSON.stringify(row))).toEqual(expected.map((row) => JSON.stringify(row)));
        // Every member has a published name, so a comparison can name him.
        for (const row of rows) expect(names[String(row.player_id)]).toBeTruthy();
        unranked += rows.filter((row) => row.state !== "ranked").length;
        slices += 1;
      }
    }
    expect(slices).toBeGreaterThan(40);
    expect(unranked).toBeGreaterThan(0);
    // The archive is never a cohort slice: it ranks among historical testers.
    expect(indexes.some((key) => Object.keys(parseIndex(served(key))?.files ?? {}).some((entry) => entry.endsWith(".combine_forty")))).toBe(false);
  });

  it("decodes every card shard to exactly the per-player records of its block and bucket", () => {
    const cards = Object.keys(manifest.files).filter((key) => key.startsWith("card/"));
    for (const key of cards) {
      const [, block = "", bucket = ""] = key.split("/");
      const scoring = block.split(".")[1] ?? "";
      const payload = served(key) as { sections: Record<string, Table> };
      for (const [artifact, table] of Object.entries(payload.sections)) {
        const { header, records } = envelope(artifact);
        const rows = decodeTable<Row>(table, header, names);
        const expected = records.filter((row) => {
          if (bucketOf(String(row.player_id), manifest.card_buckets) !== Number(bucket)) return false;
          if (typeof row.league_preset_id === "string") return partitionOf(row, "x.y") === block;
          if (typeof row.scoring_preset === "string") return row.scoring_preset === scoring;
          return true;
        });
        expect(rows.map((row) => JSON.stringify(row))).toEqual(expected.map((row) => JSON.stringify(row)));
      }
    }
  });
});

describe("the card bucket function", () => {
  it("matches the Python packager's test vectors", () => {
    // The same vectors are asserted in tests/contract/test_serving_layout.py.
    expect(bucketOf("", 64)).toBe(0x811c9dc5 % 64);
    expect(bucketOf("gsis:00-0038542", 64)).toBe(1525704982 % 64);
    expect(bucketOf("gsis:00-0023459", 64)).toBe(3737496805 % 64);
  });
});

// ------------------------------------------------------------------ the immutable-file cache

describe("fetchServed and the Cache API (ADR-098)", () => {
  const body = '{"format":"serving_v1","names":{}}\n';
  const digest = createHash("sha256").update(body, "utf8").digest("hex").slice(0, 16);
  const url = `/data/serve/players.${digest}.json`;

  /**
   * A minimal Cache API: enough of `match`, `put`, `delete` and `keys` to observe use. Like the
   * real one it keys by absolute URL, whatever form the request was given in.
   */
  const absolute = (request: string | { url: string }): string =>
    new URL(typeof request === "string" ? request : request.url, location.href).href;
  function fakeCaches(initial: Record<string, string> = {}) {
    const store = new Map(Object.entries(initial).map(([key, value]) => [absolute(key), value]));
    const cache = {
      match: vi.fn((request: string) =>
        Promise.resolve(store.has(absolute(request)) ? new Response(store.get(absolute(request))) : undefined),
      ),
      put: vi.fn(async (request: string, response: Response) => {
        store.set(absolute(request), await response.text());
      }),
      delete: vi.fn((request: string | { url: string }) => Promise.resolve(store.delete(absolute(request)))),
      keys: vi.fn(() => Promise.resolve([...store.keys()].map((key) => ({ url: key })))),
    };
    vi.stubGlobal("caches", { open: vi.fn(() => Promise.resolve(cache)) });
    return { store, cache };
  }

  function network(text: string | null, status = 200) {
    const fetcher = vi.fn(() =>
      Promise.resolve(text === null ? new Response(null, { status }) : new Response(text, { status })),
    );
    vi.stubGlobal("fetch", fetcher);
    return fetcher;
  }

  it("keeps a verified network copy, and serves the next read without the network", async () => {
    const { store } = fakeCaches();
    const fetcher = network(body);
    expect(await fetchServed("players", digest)).toEqual({ format: "serving_v1", names: {} });
    await vi.waitFor(() => {
      expect(store.get(absolute(url))).toBe(body);
    });
    expect(await fetchServed("players", digest)).toEqual({ format: "serving_v1", names: {} });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("never uses a cached copy that does not match its name: it is dropped and refetched", async () => {
    const { store, cache } = fakeCaches({ [url]: '{"format":"serving_v1","names":{"x":"stale"}}\n' });
    const fetcher = network(body);
    expect(await fetchServed("players", digest)).toEqual({ format: "serving_v1", names: {} });
    expect(cache.delete).toHaveBeenCalledWith(url);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => {
      expect(store.get(absolute(url))).toBe(body);
    });
  });

  it("refuses a network copy that does not match its name, and caches nothing", async () => {
    const { store } = fakeCaches();
    network('{"format":"serving_v1","names":{"x":"tampered"}}\n');
    await expect(fetchServed("players", digest)).rejects.toBeInstanceOf(ServedFileError);
    expect(store.size).toBe(0);
  });

  it("reports a missing file as a failure of that file, with its status", async () => {
    fakeCaches();
    network(null, 404);
    await expect(fetchServed("players", digest)).rejects.toMatchObject({ key: "players", status: 404 });
  });

  it("works with no Cache API at all, from the network", async () => {
    vi.stubGlobal("caches", undefined);
    network(body);
    expect(await fetchServed("players", digest)).toEqual({ format: "serving_v1", names: {} });
  });

  it("prunes cached files the current manifest no longer names", async () => {
    const old = "/data/serve/players.0000000000000000.json";
    const { store } = fakeCaches({ [old]: body, [url]: body });
    const manifest = parseManifest({
      format: "serving_v1",
      version: "1.0",
      card_buckets: 64,
      artifacts: {},
      files: { players: digest },
    });
    await pruneCache(manifest);
    expect([...store.keys()].map((key) => new URL(key, location.href).pathname)).toEqual([url]);
  });

  it("keeps the files a cached index of this deploy names, and drops another deploy's (ADR-117)", async () => {
    const index = JSON.stringify({
      format: "serving_v1",
      family: "skill_cohort_index",
      indexes: "skill_cohort",
      partition: "RB",
      files: { "RB.carries": "aaaaaaaaaaaaaaaa" },
    });
    const indexDigest = "bbbbbbbbbbbbbbbb";
    const kept = "/data/serve/skill_cohort/RB.carries.aaaaaaaaaaaaaaaa.json";
    const stale = "/data/serve/skill_cohort/RB.carries.cccccccccccccccc.json";
    const { store } = fakeCaches({
      [url]: body,
      [`/data/serve/skill_cohort_index/RB.${indexDigest}.json`]: index,
      [kept]: "{}",
      [stale]: "{}",
    });
    const current = parseManifest({
      format: "serving_v1",
      version: "1.0",
      card_buckets: 64,
      artifacts: {},
      files: { players: digest, "skill_cohort_index/RB": indexDigest },
    });
    await pruneCache(current);
    const paths = [...store.keys()].map((key) => new URL(key, location.href).pathname).sort();
    expect(paths).toContain(kept);
    expect(paths).not.toContain(stale);
  });
});
