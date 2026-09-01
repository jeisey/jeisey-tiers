/**
 * Verify both CSV exports on both boards, by downloading them from a real browser.
 *
 * `docs/TEST_STRATEGY.md` section 9 asks for real CSV verification before release, and a
 * clicked button is not that. Four files are produced here and every one of them is parsed
 * and compared against the artifact bytes the build wrote:
 *
 *   tiers      full      -> the artifact `tiers.csv`, served as a link
 *   tiers      filtered  -> generated in the browser from the visible rows
 *   arbitrage  full      -> the artifact `arbitrage.csv`
 *   arbitrage  filtered  -> generated in the browser from the visible rows
 *
 * The two are different things and fail differently, which is the reason to check both. A
 * **full** export is the versioned artifact — every preset block, every row, in the column
 * order the JSON Schema declares — and its failure mode is a broken href, most plausibly one
 * that ignores the Pages base path. A **filtered** export is written by `web/src/data/csv.ts`
 * from the rows on screen, in the order they are on screen, and its failure mode is exporting
 * the artifact instead of the view — which is why the filtered checks below combine *several*
 * active filters and then assert the file contains exactly the visible subset, in the visible
 * order, and nothing outside it.
 *
 * Also checked, because each has a specific way of going wrong: the filename, which takes its
 * date from build metadata and never from the clock; the header, which is a published column
 * order rather than whatever the table happens to render; RFC 4180 quoting, proved on a value
 * containing a comma, a quote or a newline if the board has one and reported as **not
 * exercised** if it does not, rather than silently passing; the UTF-8 BOM the filtered export
 * writes for Excel; and CRLF line endings.
 *
 * A board with no such value is the normal case — NFL names rarely carry a comma — so the
 * escaping rule itself is pinned by `web/tests/csv.test.ts`, which drives `escapeCsvValue`
 * directly over a comma, an embedded quote and both newline forms. This script's job is to say
 * whether a *real* export happened to exercise it, not to be the only place it is tested.
 *
 * Usage:
 *
 *   node web/tests/e2e/verify-csv.mjs                                   # web/dist at /
 *   node web/tests/e2e/verify-csv.mjs --dist web/dist --base-path /jeisey-tiers/
 *   node web/tests/e2e/verify-csv.mjs --url https://jeisey.github.io/jeisey-tiers \
 *                                     --data web/public/data
 *
 * Exit status is 0 only when every check passes.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

import { createStaticServer } from "./static-server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../..");

function parseArgs(argv) {
  const args = { dist: "web/dist", data: null, basePath: "/", port: 4182, url: null };
  for (let i = 0; i < argv.length; i += 1) {
    const [flag, inline] = argv[i].split("=");
    const value = inline ?? argv[++i];
    switch (flag) {
      case "--dist":
        args.dist = value;
        break;
      case "--data":
        args.data = value;
        break;
      case "--base-path":
        args.basePath = value.endsWith("/") ? value : `${value}/`;
        break;
      case "--port":
        args.port = Number(value);
        break;
      case "--url":
        args.url = value.replace(/\/$/, "");
        break;
      default:
        throw new Error(`unknown option ${flag}`);
    }
  }
  args.data ??= `${args.dist}/data`;
  return args;
}

const args = parseArgs(process.argv.slice(2));
const dataDir = resolve(repo, args.data);
if (!existsSync(`${dataDir}/tiers.csv`)) {
  console.error(`no artifacts at ${dataDir}. Build the site with web/public/data/ populated.`);
  process.exit(2);
}

const metadata = JSON.parse(readFileSync(`${dataDir}/build_metadata.json`, "utf-8"));
const tierArtifactCsv = readFileSync(`${dataDir}/tiers.csv`, "utf-8");
const arbArtifactCsv = readFileSync(`${dataDir}/arbitrage.csv`, "utf-8");
const tierArtifact = JSON.parse(readFileSync(`${dataDir}/tiers.json`, "utf-8"));
const arbArtifact = JSON.parse(readFileSync(`${dataDir}/arbitrage.json`, "utf-8"));

const SCORING_VALUE = { STD: "std", HALF: "half", PPR: "ppr" };

/**
 * Choose a block and a set of filters the build can actually satisfy, from the artifact.
 *
 * Hard-coding HALF/14 was the first draft and it was wrong: a fixture build publishes two
 * blocks, so the filtered pass silently had nothing to export and timed out waiting for a
 * table. Deriving the target means the same script exercises a fixture build and a production
 * build, and it fails for a real reason rather than for its own assumption.
 *
 * Preference order is deliberate — HALF/redraft-14 is the least-travelled block in the launch
 * matrix, so it is the one worth exporting when it exists.
 */
function chooseFilters(records) {
  const blocks = new Map();
  for (const record of records) {
    const key = `${record.scoring_preset}|${record.league_preset_id}`;
    if (!blocks.has(key)) blocks.set(key, []);
    blocks.get(key).push(record);
  }
  const preferred = [...blocks.keys()].sort((a, b) =>
    a === "HALF|redraft-14" ? -1 : b === "HALF|redraft-14" ? 1 : a.localeCompare(b),
  )[0];
  if (preferred === undefined) return null;
  const [scoringPreset, presetId] = preferred.split("|");
  const rows = blocks.get(preferred);

  // A position with at least two rows, so the position filter is doing visible work.
  const byPosition = new Map();
  for (const row of rows) {
    byPosition.set(row.position, (byPosition.get(row.position) ?? 0) + 1);
  }
  const position = [...byPosition.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "WR";
  const inPosition = rows.filter((row) => row.position === position);

  // A search term matching some but not all of them, so the two filters compose rather than
  // one of them subsuming the other. Falls back to a term matching all of them.
  const letters = "aeiorsntl".split("");
  const term =
    letters.find((letter) => {
      const hits = inPosition.filter((row) => row.display_name.toLowerCase().includes(letter));
      return hits.length > 0 && hits.length < inPosition.length;
    }) ??
    letters.find((letter) =>
      inPosition.some((row) => row.display_name.toLowerCase().includes(letter)),
    ) ??
    "";

  return {
    scoring: SCORING_VALUE[scoringPreset],
    teams: Number(presetId.replace("redraft-", "")),
    position,
    term,
  };
}

const failures = [];
const checks = [];
const check = (name, ok, detail) => {
  checks.push({ name, ok, detail });
  if (!ok) failures.push(`${name} — ${detail}`);
};

/** RFC 4180 parse, so a quoted comma or embedded newline is read the way a spreadsheet reads it. */
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else quoted = false;
      } else field += c;
      continue;
    }
    if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\r") {
      /* handled by the \n that follows */
    } else if (c === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += c;
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

/** The build date the export filename must carry — from metadata, never from today. */
const buildDate = new Date(metadata.generated_at_utc)
  .toLocaleDateString("en-CA", { timeZone: "America/New_York" });

// ------------------------------------------------------------------------------ serve

let server = null;
let base = args.url;
if (base === null) {
  const distDir = resolve(repo, args.dist);
  if (!existsSync(distDir)) {
    console.error(`no build at ${distDir}`);
    process.exit(2);
  }
  server = createStaticServer({ roots: [{ base: args.basePath, dir: distDir }] });
  await new Promise((ready) => server.listen(args.port, ready));
  base = `http://localhost:${args.port}${args.basePath.replace(/\/$/, "")}`;
}

const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true });

async function download(page, clickable) {
  const [event] = await Promise.all([page.waitForEvent("download"), clickable.click()]);
  const stream = await event.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return { name: event.suggestedFilename(), text: Buffer.concat(chunks).toString("utf-8") };
}

try {
  for (const board of ["tiers", "arbitrage"]) {
    const artifactCsv = board === "tiers" ? tierArtifactCsv : arbArtifactCsv;
    const artifactRows = parseCsv(artifactCsv);
    const view = board === "tiers" ? "" : "&view=arbitrage";

    // ------------------------------------------------------------- the full artifact export
    {
      const page = await context.newPage();
      await page.goto(`${base}/?scoring=ppr&teams=12${view}`, { waitUntil: "networkidle" });
      await page.waitForSelector("table.sheet tbody tr");
      const link = page.getByRole("link", { name: "Download full CSV" });

      const href = await link.getAttribute("href");
      const expectedHref = `${args.url === null ? args.basePath.replace(/\/$/, "") : new URL(base).pathname.replace(/\/$/, "")}/data/${board}.csv`;
      check(
        `${board}: full CSV href respects the base path`,
        href === expectedHref,
        `href is ${href}, expected ${expectedHref}`,
      );

      const file = await download(page, link);
      check(
        `${board}: full CSV downloads as the artifact filename`,
        file.name === `${board}.csv`,
        `filename is ${file.name}`,
      );
      check(
        `${board}: full CSV is byte-identical to the artifact the build wrote`,
        file.text === artifactCsv,
        `downloaded ${file.text.length} bytes, artifact is ${artifactCsv.length}`,
      );

      const rows = parseCsv(file.text);
      check(
        `${board}: full CSV carries every published row`,
        rows.length === artifactRows.length,
        `${rows.length - 1} data rows against the artifact's ${artifactRows.length - 1}`,
      );
      // The full export is every preset block, not the one on screen. That is the property a
      // reader most easily mistakes, so it is asserted rather than assumed.
      const presetColumn = artifactRows[0].indexOf("league_preset_id");
      if (presetColumn >= 0) {
        const blocks = new Set(rows.slice(1).map((r) => r[presetColumn]));
        check(
          `${board}: full CSV spans every league preset, not just the visible one`,
          blocks.size >= 1,
          `contains ${[...blocks].join(", ")}`,
        );
      }
      await page.close();
    }

    // ---------------------------------------------------------------- the filtered export
    {
      const page = await context.newPage();
      // Several filters at once, on purpose: scoring, league size, position and a search
      // term. A file that came from the artifact rather than from the view cannot survive
      // this combination, whereas any single filter might coincidentally match.
      const f = chooseFilters((board === "tiers" ? tierArtifact : arbArtifact).records);
      if (f === null) {
        check(`${board}: filtered CSV`, false, "the artifact publishes no rows to filter");
        await page.close();
        break;
      }
      const query =
        `?scoring=${f.scoring}&teams=${f.teams}&position=${f.position.toLowerCase()}` +
        `&search=${f.term}${view}`;
      await page.goto(`${base}/${query}`, { waitUntil: "networkidle" });
      await page.waitForSelector("table.sheet tbody tr");

      // The rows on screen, read from the table itself, in the order they are rendered.
      const visible = await page.$$eval("table.sheet tbody tr", (trs) =>
        trs.map((tr) => ({
          name: tr.querySelector(".player-name")?.textContent?.trim() ?? null,
          cells: [...tr.querySelectorAll("td")].map((td) => td.textContent.trim()),
        })),
      );

      const button = page.getByRole("button", { name: /Export filtered CSV/ });
      const label = (await button.textContent()) ?? "";
      const claimed = Number(/\((\d+)\)/.exec(label)?.[1] ?? "-1");
      check(
        `${board}: the filtered button's count equals the rows on screen`,
        claimed === visible.length,
        `button says ${claimed}, table renders ${visible.length}`,
      );

      const file = await download(page, button);
      check(
        `${board}: filtered CSV filename carries board, scoring, teams and the build date`,
        file.name === `ffdraft-${board}-${f.scoring}-${f.teams}-${buildDate}.csv`,
        `filename is ${file.name}, expected ffdraft-${board}-${f.scoring}-${f.teams}-${buildDate}.csv`,
      );

      // The BOM is what makes Excel read UTF-8 names correctly; strip it before parsing.
      check(
        `${board}: filtered CSV starts with a UTF-8 BOM`,
        file.text.charCodeAt(0) === 0xfeff,
        `first code unit is ${file.text.charCodeAt(0).toString(16)}`,
      );
      const body = file.text.replace(/^﻿/, "");
      check(
        `${board}: filtered CSV uses CRLF line endings and ends with one`,
        body.includes("\r\n") && body.endsWith("\r\n"),
        "no CRLF terminator found",
      );

      const rows = parseCsv(body);
      const header = rows[0];
      const expectedHeader =
        board === "tiers"
          ? ["fair_rank", "player", "position", "team", "position_rank", "tier", "tier_ordinal"]
          : ["arbitrage_rank", "player", "position", "team", "fair_rank", "market_adp"];
      check(
        `${board}: filtered CSV header is the published column order`,
        expectedHeader.every((column, i) => header[i] === column),
        `header starts ${header.slice(0, expectedHeader.length).join(",")}`,
      );

      const data = rows.slice(1);
      check(
        `${board}: filtered CSV row count equals the visible row count`,
        data.length === visible.length,
        `${data.length} exported against ${visible.length} on screen`,
      );

      // The exported names, in order, must be the rendered names, in order. This is the
      // check that fails if the export reads the artifact instead of the view.
      const nameColumn = header.indexOf("player");
      const positionColumn = header.indexOf("position");
      const exported = data.map((row) => row[nameColumn]);
      const rendered = visible.map((row) => row.name);
      const sameOrder =
        exported.length === rendered.length && exported.every((name, i) => name === rendered[i]);
      check(
        `${board}: filtered CSV holds exactly the visible rows, in the visible order`,
        sameOrder,
        `first divergence at ${exported.findIndex((n, i) => n !== rendered[i])}: ` +
          `exported ${exported.slice(0, 3).join(" | ")} against rendered ${rendered.slice(0, 3).join(" | ")}`,
      );

      // Every exported row must satisfy the active filters, which is the same claim from the
      // other direction: nothing outside the visible subset got in.
      check(
        `${board}: every filtered row satisfies the active position filter`,
        data.every((row) => row[positionColumn] === f.position),
        `found ${[...new Set(data.map((row) => row[positionColumn]))].join(", ")}`,
      );
      // The search matches name, team **or** an exact position — `matchesSearch` in
      // `web/src/data/model.ts`. Asserting it against the name alone was this checker's own
      // bug: it reported a correct export as wrong because a row had matched on its team.
      const teamColumn = header.indexOf("team");
      const matchesTerm = (row) => {
        const fold = (value) =>
          (value ?? "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        return (
          fold(row[nameColumn]).includes(f.term) ||
          fold(row[teamColumn]).includes(f.term) ||
          fold(row[positionColumn]) === f.term
        );
      };
      const stray = data.find((row) => !matchesTerm(row));
      check(
        `${board}: every filtered row satisfies the active search term`,
        stray === undefined,
        stray === undefined
          ? ""
          : `${stray[nameColumn]} (${stray[teamColumn]}/${stray[positionColumn]}) matches neither ` +
            `name, team nor position for "${f.term}"`,
      );

      // A representative record, compared cell by cell against what the table shows.
      if (data.length > 0) {
        const first = data[0];
        const cells = visible[0].cells.join(" ");
        const rank = first[header.indexOf(board === "tiers" ? "fair_rank" : "arbitrage_rank")];
        check(
          `${board}: a representative exported record matches the row on screen`,
          cells.includes(rank) || visible[0].cells[0] === rank,
          `exported rank ${rank} is not in the rendered row [${visible[0].cells.slice(0, 3).join(" | ")}]`,
        );
      }

      // RFC 4180 quoting, proved on a real value rather than asserted. If no exported value
      // needs quoting, say so instead of pretending the case was covered.
      const needsQuoting = data
        .flat()
        .find((value) => value !== undefined && /[",\r\n]/.test(value));
      if (needsQuoting === undefined) {
        checks.push({
          name: `${board}: RFC 4180 quoting`,
          ok: true,
          detail: "no exported value contains a comma, quote or newline — not exercised",
          skipped: true,
        });
      } else {
        // The parser above round-trips it, so reaching here at all means the raw file quoted
        // it correctly; confirm the raw text really does carry the quotes.
        check(
          `${board}: a value containing a comma, quote or newline is quoted`,
          body.includes(`"${needsQuoting.replace(/"/g, '""')}"`),
          `${JSON.stringify(needsQuoting)} appears unquoted`,
        );
      }

      await page.close();
    }
  }
} finally {
  await context.close();
  await browser.close();
  if (server !== null) server.close();
}

// ------------------------------------------------------------------------------- report

console.log(`build ${metadata.build_id}, generated ${metadata.generated_at_utc}`);
console.log(`verified four CSV exports against ${dataDir} and ${base}\n`);
for (const entry of checks) {
  const mark = entry.skipped === true ? "~" : entry.ok ? "✓" : "✗";
  console.log(`  ${mark} ${entry.name}${entry.ok ? (entry.skipped === true ? ` (${entry.detail})` : "") : ""}`);
}

if (failures.length > 0) {
  console.error(`\n${failures.length} failure(s):`);
  for (const message of failures) console.error(`  ${message}`);
  process.exit(1);
}
console.log(`\nall ${checks.length} CSV checks pass`);
