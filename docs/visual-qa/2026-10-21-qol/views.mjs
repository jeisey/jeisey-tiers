// The boards before and after ADR-114/ADR-115: the copy moved to Data, the bye filter, and the
// Opportunity Board's per-side counts. Usage, from the repository root after `npm run e2e:build`:
//   node docs/visual-qa/2026-10-21-qol/views.mjs web/dist-in-season <out dir>
// "Before" is the same script against main at ee863cc's in-season fixture build (the bye
// links then simply show every player, because main has no filter).
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";
import { createStaticServer } from "../../../web/tests/e2e/static-server.mjs";

const [dir, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const server = createStaticServer({ roots: [{ base: "/scenario/in-season/", dir: resolve(dir) }] });
await new Promise((ok) => server.listen(4393, ok));
const base = "http://localhost:4393/scenario/in-season";
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined ? {} : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
);
const sizes = [
  ["320", 320, 640, true],
  ["390", 390, 844, true],
  ["412", 412, 839, true],
  ["768", 768, 1024, true],
  ["1024", 1024, 768, false],
  ["1440", 1440, 900, false],
];
const views = [
  ["ros", "?view=ros", null],
  ["ros-table", "?view=ros", "#ros-table-heading"],
  ["ros-nobye", "?view=ros&nobye=1", "#ros-table-heading"],
  ["startsit-nobye", "?view=startsit&nobye=1", ".weekboard"],
  ["opportunity", "?view=opportunity", null],
  ["opportunity-table", "?view=opportunity", "#opportunity-table-heading"],
  ["potw", "?view=potw", null],
  ["data-guide", "?view=data", "#guide-heading"],
];
const report = {};
for (const [size, width, height, touch] of sizes) {
  const context = await browser.newContext({ viewport: { width, height }, hasTouch: touch, isMobile: touch && width < 800, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  for (const [name, query, anchor] of views) {
    await page.goto(`${base}/${query}`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(250);
    if (anchor !== null) {
      const target = page.locator(anchor).first();
      if ((await target.count()) > 0) await target.scrollIntoViewIfNeeded();
      await page.waitForTimeout(150);
    }
    await page.screenshot({ path: `${out}/${name}-${size}.png` });
    report[`${name}-${size}`] = await page.evaluate(() => ({
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      captions: [...document.querySelectorAll("table.sheet caption")].map((c) => (c.textContent ?? "").trim().length),
      byeNote: document.querySelector(".bye-note")?.textContent?.trim() ?? null,
    }));
  }
  report[`errors-${size}`] = errors;
  await context.close();
}
report.browser = browser.version();
writeFileSync(`${out}/views-report.json`, `${JSON.stringify(report, null, 2)}\n`);
const overflow = Object.entries(report).filter(([, v]) => typeof v === "object" && v !== null && "overflowX" in v && v.overflowX > 0);
console.log(JSON.stringify({ overflow, errors: Object.entries(report).filter(([k, v]) => k.startsWith("errors") && v.length > 0) }, null, 2));
await browser.close();
server.close();
