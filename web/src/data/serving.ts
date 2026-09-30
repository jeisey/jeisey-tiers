/**
 * The served layout, from the browser's side (ADR-098).
 *
 * The site no longer downloads whole artifacts. It reads one small file by a fixed name —
 * `data/manifest.json`, always revalidated — and then only the content-addressed files that
 * the open view, block and card need. `src/ffdraft/artifacts/serving.py` writes them; this file
 * reads them, and nothing else in the app knows the format.
 *
 * Three rules, each the browser half of a rule the Python validator enforces:
 *
 * 1. **The decoder reconstructs, it never computes.** A decoded record is the artifact's own
 *    record: the same fields, in the same order, holding the same JSON values. The validator
 *    proves every served file decodes to exactly its artifact subset before a deploy, and
 *    `web/tests/serving.test.ts` decodes files the Python encoder wrote.
 * 2. **A hashed file is immutable.** Its name carries the first 16 hex digits of its SHA-256,
 *    so the bytes at that URL can never change. The page keeps a copy in the Cache API and
 *    reuses it on a later visit without asking the network, and it checks the digest of every
 *    byte it uses — from the network or from the cache — so a corrupt copy is refetched rather
 *    than rendered.
 * 3. **Only the manifest decides what is current.** It is fetched with `cache: "no-cache"`,
 *    so a reader never pairs an old manifest with a new deploy, and a cached slice is used
 *    only when the current manifest names its exact hash. Nothing here can show data from an
 *    older deploy once a newer manifest has been read.
 */

import type { ArtifactName } from "./contracts";
import { artifactUrl } from "./load";

export const SERVING_FORMAT = "serving_v1";
export const SERVING_VERSION = "1.0";
export const MANIFEST_FILENAME = "manifest.json";

/** The Cache API bucket for content-addressed data. Versioned with the format. */
const CACHE_NAME = "jeisey-tiers-data-serving-v1";

/** One source artifact's envelope, without its records. */
export interface EnvelopeHeader {
  readonly schema_version: string;
  readonly artifact: string;
  readonly record_schema?: string;
  readonly build_id: string;
  readonly generated_at_utc: string;
  readonly record_count: number;
  readonly [key: string]: unknown;
}

export interface Manifest {
  readonly format: string;
  readonly version: string;
  readonly card_buckets: number;
  readonly artifacts: Readonly<Partial<Record<ArtifactName, EnvelopeHeader>>>;
  /** `build_metadata.json`, verbatim. Parsed and version-checked by `parseBuildMetadata`. */
  readonly build_metadata?: unknown;
  /** `ros_build_metadata.json`, verbatim, when the build published an in-season bundle. */
  readonly ros_build_metadata?: unknown;
  /** Served key (`ros_tiers/redraft-12.PPR`, `card/redraft-12.PPR/07`) → content hash. */
  readonly files: Readonly<Record<string, string>>;
}

export class ManifestError extends Error {
  constructor(detail: string) {
    super(`data/manifest.json is not a manifest this build can read: ${detail}`);
    this.name = "ManifestError";
  }
}

/** A served file this manifest names could not be read. Usually a deploy landed mid-visit. */
export class ServedFileError extends Error {
  readonly key: string;
  readonly status: number | null;

  constructor(key: string, detail: string, status: number | null = null) {
    super(`served file ${key} could not be read: ${detail}`);
    this.name = "ServedFileError";
    this.key = key;
    this.status = status;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseManifest(payload: unknown): Manifest {
  if (!isObject(payload)) throw new ManifestError("payload is not an object");
  if (payload.format !== SERVING_FORMAT) {
    throw new ManifestError(`format ${String(payload.format)}, expected ${SERVING_FORMAT}`);
  }
  const version = typeof payload.version === "string" ? payload.version : "";
  if (version.split(".")[0] !== SERVING_VERSION.split(".")[0]) {
    throw new ManifestError(`version ${version}, expected ${SERVING_VERSION}`);
  }
  if (!isObject(payload.files) || !isObject(payload.artifacts)) {
    throw new ManifestError("missing files or artifacts");
  }
  if (typeof payload.card_buckets !== "number" || payload.card_buckets < 1) {
    throw new ManifestError("missing card_buckets");
  }
  return payload as unknown as Manifest;
}

/** `serve/<key>.<hash>.json`, under the artifact base path. */
export function servedUrl(key: string, digest: string, base?: string): string {
  return artifactUrl(`serve/${key}.${digest}.json`, base);
}

/**
 * FNV-1a (32-bit) over the id's UTF-8 bytes, modulo `buckets`: which card shard holds a
 * player. The Python packager computes the same function; both are pinned by one test vector.
 */
export function bucketOf(playerId: string, buckets: number): number {
  let value = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(playerId)) {
    value ^= byte;
    value = Math.imul(value, 0x01000193) >>> 0;
  }
  return value % buckets;
}

export function blockKey(leaguePreset: string, scoring: string): string {
  return `${leaguePreset}.${scoring}`;
}

export function cardKey(leaguePreset: string, scoring: string, playerId: string, buckets: number): string {
  return `card/${blockKey(leaguePreset, scoring)}/${String(bucketOf(playerId, buckets)).padStart(2, "0")}`;
}

// ------------------------------------------------------------------------------- decoding

type Json = unknown;
type Row = Record<string, Json>;

/** One column-major table, as written by `encode_table`. */
export interface Table {
  readonly count: number;
  readonly fields: readonly string[];
  readonly absent?: Readonly<Record<string, readonly number[]>>;
  readonly envelope?: readonly string[];
  readonly names?: string;
  readonly nested?: Readonly<Record<string, Shape>>;
  readonly constants?: Readonly<Record<string, Json>>;
  readonly columns: Readonly<Record<string, readonly Json[]>>;
  readonly join?: { readonly family: string; readonly fields: readonly string[]; readonly rows: string };
}

interface Shape {
  readonly [key: string]: Shape | null;
}

function rebuild(
  prefix: string,
  shape: Shape,
  index: number,
  constants: Readonly<Record<string, Json>>,
  columns: Readonly<Record<string, readonly Json[]>>,
): Row {
  const out: Row = {};
  for (const [key, sub] of Object.entries(shape)) {
    const path = `${prefix}.${key}`;
    if (sub !== null) out[key] = rebuild(path, sub, index, constants, columns);
    else if (path in constants) out[key] = constants[path];
    else out[key] = columns[path]?.[index] ?? null;
  }
  return out;
}

/**
 * One table → records. The mirror of `decode_table` in `serving.py`, line for line.
 *
 * `joinSource` is the already-decoded table this one joins (the ROS rows of the same block
 * for the Opportunity Board), keyed by player.
 */
export function decodeTable<T>(
  table: Table,
  envelope: EnvelopeHeader,
  names: Readonly<Record<string, string>>,
  joinSource?: ReadonlyMap<string, Row>,
): T[] {
  const absent = new Map(
    Object.entries(table.absent ?? {}).map(([name, rows]) => [name, new Set(rows)] as const),
  );
  const constants = table.constants ?? {};
  const envelopeFields = new Set(table.envelope ?? []);
  const nested = table.nested ?? {};
  const join = table.join;
  const joinFields = new Set(join?.fields ?? []);
  if (join !== undefined && joinSource === undefined) {
    throw new Error(`table joins ${join.family} but no source rows were given`);
  }
  const records: T[] = [];
  for (let index = 0; index < table.count; index += 1) {
    const values: Row = {};
    for (const name of table.fields) {
      if (absent.get(name)?.has(index) === true) continue;
      const shape = nested[name];
      if (shape !== undefined) values[name] = rebuild(name, shape, index, constants, table.columns);
      else if (name in constants) values[name] = constants[name];
      else if (envelopeFields.has(name)) values[name] = envelope[name];
      else if (name === table.names) values[name] = null;
      else values[name] = table.columns[name]?.[index] ?? null;
    }
    const joined = join?.rows[index] === "1";
    if (joined) {
      const source = joinSource?.get(String(values.player_id));
      if (source === undefined) throw new Error(`joined row ${String(values.player_id)} has no source`);
      for (const name of joinFields) values[name] = source[name];
    }
    if (table.names !== undefined && table.names in values && !(joined && joinFields.has(table.names))) {
      const name = names[String(values.player_id)];
      if (name === undefined) throw new Error(`no dictionary name for ${String(values.player_id)}`);
      values[table.names] = name;
    }
    const record: Row = {};
    for (const name of table.fields) if (name in values) record[name] = values[name];
    records.push(record as T);
  }
  return records;
}

// ------------------------------------------------------------------------------- fetching

async function openCache(): Promise<Cache | null> {
  try {
    if (typeof caches === "undefined") return null;
    return await caches.open(CACHE_NAME);
  } catch {
    // Private windows, blocked storage, an insecure context: the network is the only copy.
    return null;
  }
}

function subtle(): SubtleCrypto | null {
  try {
    return typeof crypto !== "undefined" && typeof crypto.subtle?.digest === "function" ? crypto.subtle : null;
  } catch {
    return null;
  }
}

async function digestOf(bytes: ArrayBuffer, digest: string): Promise<boolean | null> {
  const engine = subtle();
  if (engine === null) return null;
  const hash = new Uint8Array(await engine.digest("SHA-256", bytes));
  let hex = "";
  for (const byte of hash.subarray(0, digest.length / 2)) hex += byte.toString(16).padStart(2, "0");
  return hex === digest;
}

function parseBytes(bytes: ArrayBuffer): unknown {
  return JSON.parse(new TextDecoder().decode(bytes));
}

/**
 * Read one content-addressed file: from the Cache API when the page already holds it, from
 * the network otherwise, verified against the hash the current manifest names either way.
 *
 * Fails closed. A digest that does not match is never rendered: a cached copy is dropped and
 * refetched; a network copy is an error.
 */
export async function fetchServed(key: string, digest: string, base?: string): Promise<unknown> {
  const url = servedUrl(key, digest, base);
  const cache = await openCache();
  if (cache !== null) {
    try {
      const hit = await cache.match(url);
      if (hit !== undefined) {
        const bytes = await hit.arrayBuffer();
        if ((await digestOf(bytes, digest)) === true) return parseBytes(bytes);
        await cache.delete(url);
      }
    } catch {
      /* fall through to the network */
    }
  }
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" } });
  } catch (error) {
    throw new ServedFileError(key, error instanceof Error ? error.message : String(error));
  }
  if (!response.ok) throw new ServedFileError(key, `HTTP ${String(response.status)}`, response.status);
  const bytes = await response.arrayBuffer();
  const verified = await digestOf(bytes, digest);
  if (verified === false) throw new ServedFileError(key, "content does not match its hash");
  // Only a verified copy is kept: without SubtleCrypto there is nothing to check a cached copy
  // against later, so the page leaves caching to HTTP.
  if (cache !== null && verified === true) {
    cache
      .put(url, new Response(bytes, { headers: { "Content-Type": "application/json" } }))
      .catch(() => undefined);
  }
  return parseBytes(bytes);
}

/** The manifest, always revalidated: the one file whose name does not change. */
export async function fetchManifest(base?: string): Promise<Manifest> {
  const url = artifactUrl(MANIFEST_FILENAME, base);
  const response = await fetch(url, { cache: "no-cache", headers: { Accept: "application/json" } });
  if (!response.ok) throw new ManifestError(`HTTP ${String(response.status)} for ${url}`);
  return parseManifest((await response.json()) as unknown);
}

/**
 * Drop cached files the current manifest no longer names, so the cache holds one deploy's
 * worth of data rather than every deploy's. Best effort, off the critical path.
 */
export async function pruneCache(manifest: Manifest, base?: string): Promise<void> {
  const cache = await openCache();
  if (cache === null) return;
  try {
    const keep = new Set(
      Object.entries(manifest.files).map(([key, digest]) => new URL(servedUrl(key, digest, base), location.href).href),
    );
    for (const request of await cache.keys()) {
      if (!keep.has(request.url)) await cache.delete(request);
    }
  } catch {
    /* nothing to prune, or storage refused: both harmless */
  }
}
