/**
 * Visual QA for the Skill Tree (ADR-107) at 1440, 1280, 1024, 768, 390 and 320px and two short
 * screens (1280×640, 390×600), on the fixture build or a real one. Each screen is captured and
 * measured: horizontal overflow of the document, any tree element whose box leaves the tree, a
 * node label, value or standing cut off, a tree wider than its dialog, a tab cut off, and the
 * branch-column count the pane chose.
 *
 *   node web/tests/e2e/static-server.mjs &
 *   node web/tests/e2e/capture-skilltree.mjs docs/visual-qa/2026-10-14-skill-tree/fixture \
 *     [--prefix /scenario/in-season/] [--players "Joe Burrow,Bijan Robinson,..."]
 *
 * `--players` takes one name per tree in QB, RB, WR, TE order, then a sparse player.
 * `--screens real` captures the shorter real-build set (1440, 390 and 320 only).
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

import { stubPortraits } from "./portrait-stub.mjs";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";
const args = process.argv.slice(2);
const outDir = resolve(args[0] ?? "docs/visual-qa/skill-tree");
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const prefix = option("--prefix", "/scenario/in-season/");
const [QB, RB, WR, TE, SPARSE] = option(
  "--players",
  "Joe Burrow,Bijan Robinson,Puka Nightingale,Kyle Pitts Sr.,Amon-Ra Bright",
).split(",");

/** [width, height, player, slug, node to open (index), whether to capture the full tree] */
const SCREENS = [
  [1440, 1000, QB, "qb", 2],
  [1440, 1000, RB, "rb", 6],
  [1440, 1000, WR, "wr", 9],
  [1440, 1000, TE, "te", 0],
  [1440, 1000, SPARSE, "sparse-wr", 4],
  [1280, 900, RB, "rb", 3],
  [1280, 640, WR, "wr-short", 1],
  [1024, 900, TE, "te", 5],
  [768, 1024, QB, "qb", 7],
  [390, 844, RB, "rb", 4],
  [390, 600, WR, "wr-short", 2],
  [320, 800, QB, "qb", 1],
];

const screens =
  option("--screens", "full") === "real"
    ? SCREENS.filter(([width, height]) => [1440, 390, 320].includes(width) && height !== 600)
    : SCREENS;

mkdirSync(outDir, { recursive: true });
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const report = [];

async function measure(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const dialog = document.querySelector("dialog[open]");
    const tree = dialog?.querySelector(".st");
    if (!dialog || !tree) return { missing: true };
    const bounds = tree.getBoundingClientRect();
    const outside = [];
    for (const node of tree.querySelectorAll(".st-node, .st-branch-head, .st-detail, .st-archive, .st-legend, .st-withheld")) {
      const rect = node.getBoundingClientRect();
      if (rect.width === 0) continue;
      if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1) outside.push(node.className);
    }
    const clipped = [];
    for (const node of tree.querySelectorAll(".st-node-label, .st-node-value, .st-node-standing, .st-detail-more-value")) {
      if (node.scrollWidth > node.clientWidth + 1) clipped.push(node.textContent);
    }
    const tabs = [...dialog.querySelectorAll('[role="tab"]')].filter((tab) => tab.scrollWidth > tab.clientWidth + 1);
    const box = dialog.getBoundingClientRect();
    return {
      overflow: doc.scrollWidth - doc.clientWidth,
      columns: Number(tree.getAttribute("data-columns")),
      outside: outside.slice(0, 10),
      clipped: clipped.slice(0, 10),
      clippedTabs: tabs.map((tab) => tab.textContent),
      treeInsideDialog: bounds.left >= box.left - 1 && bounds.right <= box.right + 1,
      nodes: tree.querySelectorAll(".st-grid .st-node").length,
    };
  });
}

for (const [width, height, player, slug, node] of screens) {
  const tag = `${String(width)}x${String(height)}`;
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await stubPortraits(page);
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  // The board's own search, so a player deep on a real board is on screen to open.
  await page.goto(`${BASE}${prefix}?view=ros&scoring=ppr&teams=12&search=${encodeURIComponent(player)}`, {
    waitUntil: "networkidle",
  });
  await page
    .getByRole("button", { name: player, exact: true })
    .and(page.locator(":visible"))
    .first()
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  if (width < 768) await dialog.getByRole("tab", { name: "Skill tree" }).click();
  else await dialog.getByRole("button", { name: "Show skill tree" }).click();
  const group = dialog.getByRole("group", { name: /skill tree/ });
  await group.waitFor();
  await page.waitForTimeout(250);

  // 1. The tree, scrolled to the top of its section.
  await dialog.locator(".st").evaluate((element) => element.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(150);
  report.push({ screen: `${slug}-tree`, size: tag, player, errors: [...errors], ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/${slug}-tree-${tag}.png` });

  // 2. One node's detail open, scrolled into view.
  const target = group.getByRole("button").nth(node);
  await target.click();
  const detail = dialog.getByRole("region", { name: /: details$/ });
  await detail.waitFor();
  await target.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(150);
  report.push({ screen: `${slug}-detail`, size: tag, player, errors: [...errors], ...(await measure(page)) });
  await page.screenshot({ path: `${outDir}/${slug}-detail-${tag}.png` });
  await context.close();
}

// The card from a build that published no tree: nothing in its place (fixture scenario only).
if (option("--screens", "full") !== "real") {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await stubPortraits(page);
  await page.goto(`${BASE}/scenario/in-season-no-skill-tree/?view=ros&scoring=ppr&teams=12`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: QB, exact: true }).first().click();
  await page.getByRole("dialog").waitFor();
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${outDir}/no-tree-card-1440x1000.png` });
  const present = await page.getByRole("dialog").getByRole("heading", { name: "Skill tree" }).count();
  report.push({ screen: "no-tree-card", size: "1440x1000", player: QB, skillTreeSection: present });
  await context.close();
}

await browser.close();
writeFileSync(`${outDir}/measurements.json`, `${JSON.stringify({ prefix, report }, null, 1)}\n`);
const bad = report.filter(
  (entry) =>
    entry.missing === true ||
    (entry.overflow ?? 0) > 0 ||
    (entry.outside?.length ?? 0) > 0 ||
    (entry.clipped?.length ?? 0) > 0 ||
    (entry.clippedTabs?.length ?? 0) > 0 ||
    entry.treeInsideDialog === false ||
    (entry.errors?.length ?? 0) > 0 ||
    (entry.screen === "no-tree-card" && entry.skillTreeSection !== 0),
);
console.log(JSON.stringify({ outDir, screens: report.length, problems: bad }, null, 1));
process.exitCode = bad.length === 0 ? 0 : 1;
