// Before/after captures for ADR-111 (the player search dialog, Start/Sit's empty cards and the
// card's phone header). Usage, from the repository root after `npm run e2e:build`:
//   node docs/visual-qa/2026-10-15-search-and-header/capture.mjs web/dist-in-season <out dir>
// "Before" was the same script against main at 18e743e's in-season fixture build.
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";
import { createStaticServer } from "../../../web/tests/e2e/static-server.mjs";

const [dir, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const server = createStaticServer({ roots: [{ base: "/scenario/in-season/", dir: resolve(dir) }] });
await new Promise((ok) => server.listen(4391, ok));
const base = "http://localhost:4391/scenario/in-season";
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined ? {} : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE });
const sizes = [
  ["320", 320, 640, true],
  ["390", 390, 844, true],
  ["short", 390, 560, true],
  ["tablet", 820, 1180, true],
  ["desktop", 1440, 900, false],
];
const report = {};
for (const [name, width, height, touch] of sizes) {
  const context = await browser.newContext({ viewport: { width, height }, hasTouch: touch, isMobile: touch && width < 800, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  // The card, opened from the ROS board.
  await page.goto(`${base}/?view=ros`);
  const who = page.getByRole("button", { name: "Puka Nightingale", exact: true }).first();
  await who.waitFor();
  await who.click();
  const dialog = page.locator("dialog.player-detail");
  await dialog.waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/card-${name}.png` });
  const measure = async () =>
    page.evaluate(() => {
      const rect = (sel) => document.querySelector(sel)?.getBoundingClientRect() ?? null;
      const rail = rect("dialog.player-detail .detail-rail");
      const tabs = rect("dialog.player-detail .detail-tabs");
      const body = rect("dialog.player-detail .detail-body");
      const close = rect("dialog.player-detail .detail-close");
      return {
        rail: rail && Math.round(rail.height),
        tabsTop: tabs && Math.round(tabs.top),
        bodyHeight: body && Math.round(body.height),
        close: close && [Math.round(close.top), Math.round(close.right)],
        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        dialogOverflowX: (() => { const d = document.querySelector("dialog.player-detail .detail-card"); return d ? d.scrollWidth - d.clientWidth : null; })(),
      };
    });
  report[`card-${name}`] = await measure();
  const expand = page.getByRole("button", { name: /Expand details/ });
  if (await expand.count()) {
    await expand.click();
    await page.waitForTimeout(150);
    await page.screenshot({ path: `${out}/card-${name}-expanded.png` });
    report[`card-${name}-expanded`] = await measure();
    const skill = page.getByRole("tab", { name: "Skill tree" });
    if (await skill.count()) {
      await skill.click();
      await page.waitForTimeout(600);
      await page.screenshot({ path: `${out}/card-${name}-expanded-skilltree.png` });
    }
  }
  await page.keyboard.press("Escape");
  // Start/Sit, empty deck.
  await page.goto(`${base}/?view=startsit`);
  await page.locator(".deck").waitFor();
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${out}/startsit-${name}.png` });
  const empty = page.locator(".deck-empty").first();
  if ((await empty.evaluate((n) => n.tagName)) === "BUTTON") {
    await empty.click();
    await page.getByRole("dialog").waitFor();
    await page.keyboard.type("a");
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${out}/startsit-picker-${name}.png` });
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
  }
  // Start/Sit with a pair: the folded empty card.
  await page.goto(`${base}/?view=startsit&duel=00-0000011.00-0000012`);
  await page.locator(".verdict-head").waitFor();
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${out}/startsit-pair-${name}.png` });
  // The search control.
  await page.goto(`${base}/?view=opportunity`);
  await page.locator(".opp-board, .section").first().waitFor();
  const settings = page.getByRole("button", { name: /^Settings/ });
  if (await settings.isVisible()) await settings.click();
  await page.waitForTimeout(150);
  await page.screenshot({ path: `${out}/search-${name}.png` });
  const trigger = page.getByRole("button", { name: /^Search players/ });
  if (await trigger.count()) {
    await trigger.click();
    await page.keyboard.type("an");
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${out}/search-modal-${name}.png` });
    report[`search-modal-${name}`] = await page.evaluate(() => {
      const d = document.querySelector("dialog[open] .lg-dialog-card")?.getBoundingClientRect();
      return { top: d && Math.round(d.top), bottom: d && Math.round(d.bottom), overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    });
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${out}/search-applied-${name}.png` });
  }
  report[`errors-${name}`] = errors;
  await context.close();
}
writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
server.close();
