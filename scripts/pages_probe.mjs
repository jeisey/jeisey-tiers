/**
 * Probe how GitHub Pages serves this site, and what the published payload is made of.
 *
 * Two jobs, one file, because both answer the same question — what does a visit cost — and
 * both have to run on a runner: the development sandbox cannot reach `*.github.io` (ADR-009).
 *
 *   node scripts/pages_probe.mjs headers --url https://jeisey.github.io/jeisey-tiers \
 *                                         --out probe
 *   node scripts/pages_probe.mjs fields  --data probe/data
 *
 * `headers` requests the root document, one script, one stylesheet, the fonts, the logo, the
 * data manifest (when there is one) and every data file, each under three `Accept-Encoding`
 * values, then repeats the request conditionally (`If-None-Match`, `If-Modified-Since`). It uses
 * Node's `https` module rather than `fetch`, because `fetch` decompresses and would report the
 * decoded size instead of the bytes on the wire. The data files it downloads are written under
 * `--out/data` so `fields` can read the exact served bytes.
 *
 * `fields` reports, per data file: raw, gzip-6 and brotli-11 sizes; the size of each
 * league × scoring block; and, per record field, how many compressed bytes the file loses when
 * that field is removed. It is a measurement script: it prints and never fails on a number.
 *
 * Only the standard library. Nothing here writes anywhere but `--out`.
 */

import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { request } from "node:https";
import { join } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

const HEADER_NAMES = [
  "content-type",
  "content-encoding",
  "content-length",
  "cache-control",
  "expires",
  "etag",
  "last-modified",
  "age",
  "vary",
  "x-cache",
  "x-cache-hits",
  "x-served-by",
  "x-github-request-id",
  "access-control-allow-origin",
  "strict-transport-security",
  "server",
  "via",
];

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const args = { command, url: null, out: "probe", data: null };
  for (let i = 0; i < rest.length; i += 1) {
    const [flag, inline] = rest[i].split("=");
    const value = inline ?? rest[++i];
    if (flag === "--url") args.url = value.replace(/\/$/, "");
    else if (flag === "--out") args.out = value;
    else if (flag === "--data") args.data = value;
    else throw new Error(`unknown option ${flag}`);
  }
  return args;
}

/** One GET, measured on the wire. Resolves to status, selected headers and wire/body bytes. */
function get(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const started = performance.now();
    const req = request(url, { method: "GET", headers: { "User-Agent": "jeisey-tiers-pages-probe", ...headers } }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const body = Buffer.concat(chunks);
        const picked = {};
        for (const name of HEADER_NAMES) {
          if (res.headers[name] !== undefined) picked[name] = res.headers[name];
        }
        resolve({
          url,
          status: res.statusCode,
          headers: picked,
          wireBytes: body.length,
          ms: Math.round(performance.now() - started),
          body,
        });
      });
      res.on("error", reject);
    });
    req.on("error", reject);
    req.end();
  });
}

function decoded(result) {
  const encoding = result.headers["content-encoding"];
  if (encoding === undefined) return result.body;
  // Decompression only for saving the bytes; the measurement is `wireBytes`.
  return null;
}

async function headersCommand(args) {
  if (args.url === null) throw new Error("--url is required");
  const site = args.url;
  const outData = join(args.out, "data");
  mkdirSync(outData, { recursive: true });
  const report = { site, measured_at_utc: new Date().toISOString(), resources: [] };

  const root = await get(`${site}/`, { "Accept-Encoding": "identity" });
  const html = root.body.toString("utf8");
  const assetUrls = [...html.matchAll(/(?:src|href)="([^"]+)"/g)]
    .map((match) => match[1])
    .filter((href) => !href.startsWith("http") || href.startsWith(site))
    .map((href) => (href.startsWith("http") ? href : new URL(href, `${site}/`).toString()));
  const css = assetUrls.filter((url) => url.endsWith(".css"));
  const fonts = [];
  for (const sheet of css) {
    const text = (await get(sheet, { "Accept-Encoding": "identity" })).body.toString("utf8");
    for (const match of text.matchAll(/url\(([^)]+)\)/g)) {
      const ref = match[1].replace(/["']/g, "");
      if (ref.startsWith("data:")) continue;
      fonts.push(new URL(ref, sheet).toString());
    }
  }

  // The data files the site serves. A manifest, when present, names them; otherwise the
  // historical fixed set is tried.
  const dataNames = [
    "build_metadata.json",
    "tiers.json",
    "arbitrage.json",
    "projections.json",
    "player_status.json",
    "player_headshots.json",
    "market_trend_series.json",
    "ros_build_metadata.json",
    "ros_tiers.json",
    "inseason_opportunity.json",
    "behavior_trend_series.json",
    "player_usage.json",
    "team_matchups.json",
    "weekly_projections.json",
    "tiers.csv",
    "arbitrage.csv",
    "ros_tiers.csv",
    "inseason_opportunity.csv",
  ];
  const manifest = await get(`${site}/data/manifest.json`, { "Accept-Encoding": "identity" });
  const sliceUrls = [];
  if (manifest.status === 200) {
    writeFileSync(join(outData, "manifest.json"), manifest.body);
    try {
      const parsed = JSON.parse(manifest.body.toString("utf8"));
      for (const entry of Object.values(parsed.files ?? {})) {
        if (typeof entry?.path === "string") sliceUrls.push(`${site}/data/${entry.path}`);
      }
    } catch {
      /* reported as a resource below */
    }
  }

  const targets = [
    { kind: "document", url: `${site}/` },
    ...assetUrls.map((url) => ({ kind: "asset", url })),
    ...fonts.map((url) => ({ kind: "font", url })),
    ...dataNames.map((name) => ({ kind: "data", url: `${site}/data/${name}`, name })),
    { kind: "manifest", url: `${site}/data/manifest.json` },
    ...sliceUrls.slice(0, 12).map((url) => ({ kind: "slice", url })),
  ];

  for (const target of targets) {
    const entry = { kind: target.kind, url: target.url };
    const br = await get(target.url, { "Accept-Encoding": "br, gzip" });
    const gz = await get(target.url, { "Accept-Encoding": "gzip" });
    const id = await get(target.url, { "Accept-Encoding": "identity" });
    entry.status = br.status;
    entry.br_request = { encoding: br.headers["content-encoding"] ?? "identity", wire: br.wireBytes };
    entry.gzip_request = { encoding: gz.headers["content-encoding"] ?? "identity", wire: gz.wireBytes };
    entry.identity_bytes = id.wireBytes;
    entry.headers = br.headers;
    const etag = br.headers.etag;
    if (etag !== undefined) {
      const conditional = await get(target.url, { "Accept-Encoding": "br, gzip", "If-None-Match": etag });
      entry.if_none_match = { status: conditional.status, wire: conditional.wireBytes };
    }
    const modified = br.headers["last-modified"];
    if (modified !== undefined) {
      const conditional = await get(target.url, { "Accept-Encoding": "br, gzip", "If-Modified-Since": modified });
      entry.if_modified_since = { status: conditional.status, wire: conditional.wireBytes };
    }
    if (target.kind === "data" && id.status === 200) {
      const body = decoded(id);
      if (body !== null) writeFileSync(join(outData, target.name), body);
    }
    report.resources.push(entry);
  }

  // A burst of requests for one small file: does the edge rate-limit a single client quickly?
  const burst = [];
  for (let i = 0; i < 40; i += 1) burst.push(get(`${site}/data/build_metadata.json`, { "Accept-Encoding": "gzip" }));
  const results = await Promise.all(burst);
  report.burst_40_parallel = results.reduce((acc, result) => {
    acc[result.status] = (acc[result.status] ?? 0) + 1;
    return acc;
  }, {});

  writeFileSync(join(args.out, "headers.json"), `${JSON.stringify(report, null, 1)}\n`);
  printHeaders(report);
}

function printHeaders(report) {
  console.log(`# Pages probe — ${report.site} at ${report.measured_at_utc}`);
  for (const entry of report.resources) {
    const h = entry.headers ?? {};
    console.log(
      [
        entry.kind.padEnd(8),
        String(entry.status).padEnd(4),
        `br-req:${entry.br_request.encoding}/${entry.br_request.wire}`,
        `gz-req:${entry.gzip_request.encoding}/${entry.gzip_request.wire}`,
        `id:${entry.identity_bytes}`,
        `cc:${h["cache-control"] ?? "-"}`,
        `etag:${h.etag ?? "-"}`,
        `lm:${h["last-modified"] ?? "-"}`,
        `inm:${entry.if_none_match ? `${entry.if_none_match.status}/${entry.if_none_match.wire}` : "-"}`,
        `ims:${entry.if_modified_since ? `${entry.if_modified_since.status}/${entry.if_modified_since.wire}` : "-"}`,
        `vary:${h.vary ?? "-"}`,
        `x-cache:${h["x-cache"] ?? "-"}`,
        `ct:${h["content-type"] ?? "-"}`,
        entry.url,
      ].join("  "),
    );
  }
  console.log(`burst of 40 parallel GETs: ${JSON.stringify(report.burst_40_parallel)}`);
  const sample = report.resources.find((entry) => entry.kind === "data" && entry.status === 200);
  if (sample !== undefined) console.log(`sample data headers: ${JSON.stringify(sample.headers)}`);
}

// ---------------------------------------------------------------------------------- fields

const gzip = (buffer) => gzipSync(buffer, { level: 6 }).length;
const brotli = (buffer) =>
  brotliCompressSync(buffer, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }).length;

function decimals(value) {
  if (typeof value !== "number" || Number.isInteger(value)) return 0;
  const text = String(value);
  const dot = text.indexOf(".");
  if (text.includes("e")) return 17;
  return dot < 0 ? 0 : text.length - dot - 1;
}

function fieldsCommand(args) {
  if (args.data === null) throw new Error("--data is required");
  const summary = { files: {} };
  let totalRaw = 0;
  let totalGzip = 0;
  let totalBrotli = 0;
  for (const name of readdirSync(args.data).sort()) {
    if (!name.endsWith(".json") && !name.endsWith(".csv")) continue;
    const bytes = readFileSync(join(args.data, name));
    const entry = { raw: bytes.length, gzip: gzip(bytes), brotli: brotli(bytes) };
    totalRaw += entry.raw;
    totalGzip += entry.gzip;
    totalBrotli += entry.brotli;
    summary.files[name] = entry;
    if (!name.endsWith(".json")) continue;
    let payload;
    try {
      payload = JSON.parse(bytes.toString("utf8"));
    } catch {
      continue;
    }
    if (!Array.isArray(payload.records)) {
      entry.top_keys = Object.keys(payload);
      entry.key_bytes = Object.fromEntries(
        Object.entries(payload).map(([key, value]) => [key, JSON.stringify(value).length]),
      );
      continue;
    }
    const records = payload.records;
    entry.records = records.length;
    entry.players = new Set(records.map((record) => record.player_id)).size;
    // Blocks.
    const blocks = new Map();
    for (const record of records) {
      const key = [record.league_preset_id, record.scoring_preset].filter((part) => part !== undefined).join("|") || "all";
      const bucket = blocks.get(key) ?? [];
      bucket.push(record);
      blocks.set(key, bucket);
    }
    entry.blocks = {};
    for (const [key, rows] of blocks) {
      const text = Buffer.from(JSON.stringify({ ...payload, records: rows }));
      entry.blocks[key] = { records: rows.length, raw: text.length, gzip: gzip(text) };
    }
    // Field costs, measured on the file as the build writes it (indent as served).
    const indent = bytes.toString("utf8").startsWith("{\n") ? detectIndent(bytes.toString("utf8")) : undefined;
    const baseline = Buffer.from(JSON.stringify(payload, null, indent));
    const baseGzip = gzip(baseline);
    entry.reserialized_gzip = baseGzip;
    const keys = new Set();
    for (const record of records) for (const key of Object.keys(record)) keys.add(key);
    entry.fields = {};
    for (const key of keys) {
      const without = records.map((record) => {
        const copy = { ...record };
        delete copy[key];
        return copy;
      });
      const text = Buffer.from(JSON.stringify({ ...payload, records: without }, null, indent));
      const values = records.map((record) => record[key]);
      const types = [...new Set(values.map((value) => (value === null ? "null" : Array.isArray(value) ? "array" : typeof value)))];
      const maxDecimals = Math.max(0, ...values.map(decimals));
      const distinct = new Set(values.map((value) => JSON.stringify(value))).size;
      entry.fields[key] = {
        gzip_saved: baseGzip - gzip(text),
        raw_saved: baseline.length - text.length,
        types,
        max_decimals: maxDecimals,
        distinct,
      };
    }
    entry.sample = records[0];
  }
  summary.total = { raw: totalRaw, gzip: totalGzip, brotli: totalBrotli };
  console.log(JSON.stringify(summary));
}

function detectIndent(text) {
  const match = /^\{\n( +)"/.exec(text);
  return match === null ? undefined : match[1].length;
}

const args = parseArgs(process.argv.slice(2));
if (args.command === "headers") await headersCommand(args);
else if (args.command === "fields") fieldsCommand(args);
else throw new Error("usage: pages_probe.mjs headers|fields ...");
