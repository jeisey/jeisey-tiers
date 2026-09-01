/**
 * Smoke the deployed site, from the outside.
 *
 * Every other verifier in this directory checks a build. This one checks a **deployment**, and
 * the difference is the whole point: a build that is correct on disk can still be served from
 * the wrong base path, miss a file the packager never copied, or answer 404 for an asset the
 * module graph never referenced. Those failures are invisible to `npm run build` and to every
 * gate that runs before `actions/deploy-pages`.
 *
 * It takes nothing on trust from the repository. The artifacts it compares against are
 * **downloaded from the site itself**, into `--out`, so the other verifiers can then be run
 * with `--url <site> --data <out>` and be comparing the page against the bytes that page was
 * actually served — not against a local rebuild that might differ.
 *
 * What it checks, and why each one is here rather than covered elsewhere:
 *
 *   * the root document answers 200, and its title is the product's;
 *   * every `<script>`, `<link rel=stylesheet>` and icon href resolves **under the site's own
 *     base path** and answers 200 with a non-empty body — the icons especially, because they
 *     are the one asset class referenced from `index.html` rather than from the module graph,
 *     so a root-relative href would work in development and 404 only here;
 *   * the vendored fonts the stylesheet asks for answer 200 — they are same-origin by design
 *     (`docs/SECURITY_LICENSE.md` section 8) and a missing one is a silent fallback to a
 *     system stack rather than an error;
 *   * the logo actually decoded, read as `naturalWidth` off the live `<img>`, because a broken
 *     image still renders an `<img>` element;
 *   * all five public artifacts answer 200 and parse;
 *   * the three views render, a player card opens, and a shared query-state link survives a
 *     reload — the state contract, exercised where it is actually deployed;
 *   * the phone viewport renders the board without a horizontal scrollbar;
 *   * nothing logs a console error or throws;
 *   * and **no request leaves the site's origin** — no vendor, no private store, no font CDN.
 *     `docs/ARCHITECTURE.md` section 3.2 as a check on the deployed page rather than on a
 *     local server.
 *
 * Usage:
 *
 *   node web/tests/e2e/verify-live.mjs --url https://jeisey.github.io/jeisey-tiers \
 *                                      --out live-artifacts
 *
 * Exit status is 0 only when every check passes. Against the real site this can only run on a
 * runner — the development sandbox's egress policy blocks it (ADR-009) — but every check is
 * written against a served origin rather than a filesystem, so pointing it at a local static
 * server exercises the whole script.
 *
 * All HTTP goes through Playwright's request context rather than Node's `fetch`. That is the
 * same network stack the page itself uses, so an asset this file reports as served is an asset
 * the browser can really fetch, under the same redirect and content-type handling — rather than
 * one a second HTTP client happens to like.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

function parseArgs(argv) {
  const args = { url: null, out: "live-artifacts" };
  for (let i = 0; i < argv.length; i += 1) {
    const [flag, inline] = argv[i].split("=");
    const value = inline ?? argv[++i];
    if (flag === "--url") args.url = value.replace(/\/$/, "");
    else if (flag === "--out") args.out = value;
    else throw new Error(`unknown option ${flag}`);
  }
  if (args.url === null) throw new Error("--url is required");
  return args;
}

const args = parseArgs(process.argv.slice(2));
const site = args.url;
const origin = new URL(site).origin;
const basePath = `${new URL(site).pathname.replace(/\/$/, "")}/`;
const outDir = resolve(process.cwd(), args.out);
mkdirSync(outDir, { recursive: true });

const failures = [];
const checks = [];
const check = (name, ok, detail = "") => {
  checks.push({ name, ok, detail });
  if (!ok) failures.push(`${name}${detail === "" ? "" : ` — ${detail}`}`);
};

const ARTIFACTS = ["tiers", "projections", "arbitrage", "player_status", "build_metadata"];

const exe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const api = await browser.newContext();

/** One GET through the browser's own stack: status, byte count and content type. */
async function get(url) {
  try {
    const response = await api.request.get(url.startsWith("http") ? url : `${origin}${url}`);
    const body = await response.body();
    return {
      status: response.status(),
      bytes: body.byteLength,
      text: () => body.toString("utf-8"),
      type: response.headers()["content-type"] ?? null,
    };
  } catch (error) {
    return { status: 0, bytes: 0, text: () => "", type: null, error: error.message };
  }
}

// ------------------------------------------------------------------ the document and its assets

const root = await get(`${site}/`);
const html = root.text();
check("the root page answers 200", root.status === 200, `status ${root.status}`);
check(
  "the document title is the product's",
  /<title>[^<]*Jeisey Tiers/i.test(html),
  `title is ${/<title>([^<]*)<\/title>/i.exec(html)?.[1] ?? "(absent)"}`,
);

/** Every URL `index.html` asks the browser for, with the attribute that named it. */
const referenced = [
  ...[...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => ["script", m[1]]),
  ...[...html.matchAll(/<link[^>]+rel="stylesheet"[^>]*href="([^"]+)"/g)].map((m) => ["stylesheet", m[1]]),
  ...[...html.matchAll(/<link[^>]+rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"/g)].map((m) => ["icon", m[1]]),
];
check("the document references a script, a stylesheet and at least one icon",
  ["script", "stylesheet", "icon"].every((kind) => referenced.some(([k]) => k === kind)),
  `found ${referenced.map(([k]) => k).join(", ") || "nothing"}`);

for (const [kind, href] of referenced) {
  // A URL that does not start with the deployed base path is the exact failure this smoke
  // exists for: it resolves locally and 404s once the site is served from a subdirectory.
  check(
    `${kind} ${href} is under the deployed base path`,
    href.startsWith(basePath) || href.startsWith(site),
    `expected a path under ${basePath}`,
  );
  const result = await get(href);
  check(
    `${kind} ${href} is served`,
    result.status === 200 && result.bytes > 0,
    `status ${result.status}, ${result.bytes} bytes${result.error === undefined ? "" : `, ${result.error}`}`,
  );
}

// The stylesheet's own font requests. Vendored and same-origin by design; a missing one
// degrades silently to a system stack, which no other check would notice.
const cssHref = referenced.find(([kind]) => kind === "stylesheet")?.[1];
if (cssHref !== undefined) {
  const css = (await get(cssHref)).text();
  const fonts = [...new Set([...css.matchAll(/url\(([^)]+\.woff2?)\)/g)].map((m) => m[1].replace(/["']/g, "")))];
  check("the stylesheet vendors its fonts rather than linking a CDN",
    fonts.length > 0 && fonts.every((url) => !/^https?:/.test(url) || url.startsWith(origin)),
    `font urls: ${fonts.join(", ") || "none found"}`);
  for (const font of fonts) {
    const result = await get(font);
    check(`font ${font.split("/").pop()} is served`, result.status === 200 && result.bytes > 0,
      `status ${result.status}`);
  }
}

// ------------------------------------------------------------------------- the public artifacts

for (const name of ARTIFACTS) {
  const response = await get(`${site}/data/${name}.json`);
  const text = response.status === 200 ? response.text() : "";
  let parsed = null;
  try {
    parsed = JSON.parse(text);
  } catch {
    /* reported below */
  }
  check(`data/${name}.json is served and parses`, response.status === 200 && parsed !== null,
    `status ${response.status}, ${text.length} bytes`);
  if (parsed !== null) writeFileSync(`${outDir}/${name}.json`, text);
}
for (const name of ["tiers", "arbitrage", "projections", "player_status"]) {
  const response = await get(`${site}/data/${name}.csv`);
  const text = response.status === 200 ? response.text() : "";
  check(`data/${name}.csv is served`, response.status === 200 && text.length > 0,
    `status ${response.status}`);
  if (text.length > 0) writeFileSync(`${outDir}/${name}.csv`, text);
}

// -------------------------------------------------------------------------------- the browser

/** Attach the noise collectors every page in this file shares. */
function watch(page, noise) {
  page.on("console", (message) => {
    if (message.type() === "error") noise.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => noise.push(`pageerror: ${error.message}`));
  page.on("requestfailed", (request) => noise.push(`failed: ${request.url()}`));
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(origin) && !url.startsWith("data:") && !url.startsWith("blob:")) {
      noise.push(`request left the site: ${url}`);
    }
  });
}

try {
  const noise = [];
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  watch(page, noise);

  await page.goto(`${site}/`, { waitUntil: "networkidle" });
  await page.waitForSelector("table.sheet tbody tr", { timeout: 30000 });

  // A broken image still renders an `<img>`; `naturalWidth` is what says it decoded.
  const logo = await page.evaluate(() => {
    const node = document.querySelector("img.masthead-logo");
    if (node === null) return null;
    return { src: node.currentSrc || node.src, width: node.naturalWidth, height: node.naturalHeight };
  });
  check("the masthead logo element exists", logo !== null, "img.masthead-logo not found");
  if (logo !== null) {
    check("the masthead logo actually decoded", logo.width > 0 && logo.height > 0,
      `naturalWidth ${logo.width}, naturalHeight ${logo.height}`);
    check("the masthead logo is served from the deployed base path",
      logo.src.startsWith(`${origin}${basePath}`), `src is ${logo.src}`);
    check("the masthead logo keeps the artwork's aspect ratio",
      Math.abs(logo.width / logo.height - 434 / 145) < 0.05,
      `ratio ${(logo.width / logo.height).toFixed(3)}`);
  }
  check("the old wordmark is gone from the deployed masthead",
    !(await page.locator("header.masthead").innerText()).includes("jeisey-tiers"),
    "the header still contains the Phase-9A wordmark");

  // The three views.
  for (const [view, heading] of [
    ["", "Tier board"],
    ["?view=arbitrage", "Arbitrage table"],
    ["?view=data", "What this is"],
  ]) {
    await page.goto(`${site}/${view}`, { waitUntil: "networkidle" });
    const visible = await page
      .getByRole("heading", { name: heading })
      .isVisible()
      .catch(() => false);
    check(`the ${view === "" ? "tiers" : view.replace("?view=", "")} view renders`, visible,
      `"${heading}" not visible`);
  }

  // A player card, opened the way a drafter opens one.
  await page.goto(`${site}/`, { waitUntil: "networkidle" });
  await page.waitForSelector("table.sheet tbody tr .player-name");
  await page.locator("table.sheet tbody tr .player-name").first().click();
  const dialog = await page.locator("dialog[open]").isVisible().catch(() => false);
  check("a player card opens from a table row", dialog, "no open dialog after clicking a name");
  await page.keyboard.press("Escape");

  // A shared link, and the same link after a reload — the state contract where it is deployed.
  const shared = `${site}/?view=arbitrage&scoring=half&teams=14&position=rb`;
  await page.goto(shared, { waitUntil: "networkidle" });
  const beforeReload = await page.url();
  await page.reload({ waitUntil: "networkidle" });
  const afterReload = await page.url();
  check("a shared query-state link survives a reload", beforeReload === afterReload && afterReload === shared,
    `${beforeReload} -> ${afterReload}`);
  const restored = await page.evaluate(() => {
    const groups = {};
    for (const group of document.querySelectorAll('[role="radiogroup"]')) {
      const label = document.getElementById(group.getAttribute("aria-labelledby"));
      groups[(label?.textContent ?? "").trim().toLowerCase()] =
        group.querySelector('[role="radio"][aria-checked="true"]')?.getAttribute("aria-label") ?? null;
    }
    return groups;
  });
  check("the reloaded page restores the shared state",
    restored.scoring === "Half PPR" && restored.teams === "14-team league" && restored.position === "RB",
    JSON.stringify(restored));

  await page.close();

  // A phone. Reflow is the check: WCAG names 320px and the board is used one-handed.
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  watch(phone, noise);
  await phone.goto(`${site}/`, { waitUntil: "networkidle" });
  await phone.waitForSelector("table.sheet tbody tr", { timeout: 30000 });
  const overflow = await phone.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  check("the deployed board reflows on a phone without a horizontal scrollbar", overflow <= 0,
    `${overflow}px of horizontal overflow at 390px`);
  const phoneLogo = await phone.evaluate(() => {
    const node = document.querySelector("img.masthead-logo");
    return node === null ? null : { width: node.naturalWidth, box: node.getBoundingClientRect().height };
  });
  check("the logo decodes and is legible on a phone",
    phoneLogo !== null && phoneLogo.width > 0 && phoneLogo.box >= 30,
    JSON.stringify(phoneLogo));
  await phone.close();

  check("the deployed page makes no request that leaves its own origin, and logs nothing",
    noise.length === 0, noise.slice(0, 6).join("; "));
} finally {
  await api.close();
  await browser.close();
}

// ------------------------------------------------------------------------------------ report

console.log(`live smoke of ${site}`);
console.log(`artifacts downloaded to ${outDir}\n`);
for (const entry of checks) {
  console.log(`  ${entry.ok ? "✓" : "✗"} ${entry.name}`);
}
if (failures.length > 0) {
  console.error(`\n${failures.length} failure(s):`);
  for (const message of failures) console.error(`  ${message}`);
  process.exit(1);
}
console.log(`\nall ${checks.length} live checks pass`);
