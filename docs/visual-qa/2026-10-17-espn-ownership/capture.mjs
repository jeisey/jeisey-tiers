// Captures for ADR-112 (ESPN roster and start percentages): the Opportunity Board's column,
// ceiling and discovery rule, the card's reading and trend, and the older/stale builds.
// Usage, from the repository root after `npm run e2e:build`:
//   node docs/visual-qa/2026-10-17-espn-ownership/capture.mjs <out dir>
// "Before" is the same Opportunity and card captures against main at 912a299's in-season
// fixture build (`--before web/dist-in-season`, built on that commit).
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";
import { stubPortraits } from "../../../web/tests/e2e/portrait-stub.mjs";
import { createStaticServer } from "../../../web/tests/e2e/static-server.mjs";

const args = process.argv.slice(2);
const before = args[0] === "--before";
const out = before ? args[2] : args[0];
const fresh = before ? args[1] : "web/dist-in-season";
mkdirSync(out, { recursive: true });
const server = createStaticServer({
  roots: [
    { base: "/scenario/in-season/", dir: resolve(fresh) },
    { base: "/scenario/in-season-no-espn/", dir: resolve("web/dist-in-season-no-espn") },
    { base: "/scenario/in-season-espn-stale/", dir: resolve("web/dist-in-season-espn-stale") },
  ],
});
await new Promise((ok) => server.listen(4392, ok));
const site = "http://localhost:4392/scenario";
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined ? {} : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
);
const sizes = [
  ["320", 320, 640, true],
  ["390", 390, 844, true],
  ["short", 390, 560, true],
  ["768", 768, 1024, true],
  ["1024", 1024, 800, false],
  ["1440", 1440, 900, false],
];
const report = {};
const overflow = (page) =>
  page.evaluate(() => ({
    pageX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    clipped: [...document.querySelectorAll("button, [role='radio']")]
      .filter((node) => {
        const box = node.getBoundingClientRect();
        if (box.width === 0 || (box.right <= window.innerWidth + 1 && box.left >= -1)) return false;
        // A control inside a horizontally scrolling strip (the tab bar, the table) is reachable.
        for (let up = node.parentElement; up !== null; up = up.parentElement) {
          if (["auto", "scroll"].includes(getComputedStyle(up).overflowX)) return false;
        }
        return true;
      })
      .map((node) => (node.textContent ?? "").trim().slice(0, 30))
      .filter((text) => text !== "")
      .slice(0, 5),
  }));
for (const [name, width, height, touch] of sizes) {
  const context = await browser.newContext({ viewport: { width, height }, hasTouch: touch, isMobile: touch && width < 768, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await stubPortraits(page);
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });
  const shot = async (key, url, open = async () => {}) => {
    await page.goto(url);
    await page.locator("table.sheet.opp-sheet").first().waitFor();
    await open();
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${out}/${key}-${name}.png`, fullPage: false });
    report[`${key}-${name}`] = await overflow(page);
  };
  await shot("opportunity", `${site}/in-season/?view=opportunity`);
  if (!before) {
    await shot("opportunity-discovery", `${site}/in-season/?view=opportunity&only=role&espn=lt50`, async () => {
      const options = page.getByRole("button", { name: /^Options/ });
      if ((await options.count()) > 0 && (await options.isVisible())) await options.click();
      await page.locator(".opp-discovery").scrollIntoViewIfNeeded();
    });
    await shot("opportunity-table", `${site}/in-season/?view=opportunity&opportunity=espn7`, async () => {
      await page.locator("table.sheet.opp-sheet").scrollIntoViewIfNeeded();
    });
    await shot("opportunity-no-espn-link", `${site}/in-season-no-espn/?view=opportunity&espn=lt25`);
    await shot("opportunity-stale", `${site}/in-season-espn-stale/?view=opportunity&opportunity=espn`, async () => {
      await page.locator("table.sheet.opp-sheet").scrollIntoViewIfNeeded();
    });
  }
  // The card: the riser, with the trend activated (the tab on a phone, the button elsewhere).
  await page.goto(`${site}/in-season/?view=opportunity`);
  await page.getByRole("button", { name: "Jahmyr Cook", exact: true }).first().click();
  const card = page.getByRole("dialog");
  await card.waitFor();
  const usageTab = card.getByRole("tab", { name: "In-season usage" });
  if ((await usageTab.count()) > 0) await usageTab.click();
  if (!before) {
    const show = card.getByRole("button", { name: "Show ESPN trend" });
    if ((await show.count()) > 0) await show.click();
    await card.getByTestId("espn-ownership-chart").waitFor();
    await card.getByTestId("espn-block").scrollIntoViewIfNeeded();
  } else {
    await card.getByRole("heading", { name: "In-season usage" }).first().scrollIntoViewIfNeeded();
  }
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/card-${name}.png` });
  report[`card-${name}`] = {
    ...(await overflow(page)),
    chartOverflow: before
      ? null
      : await card.getByTestId("espn-ownership-chart").evaluate((node) => node.scrollWidth - node.clientWidth),
  };
  if (!before) {
    await card.getByText(/^Exact readings/).click();
    await page.waitForTimeout(150);
    await card.locator(".espn-readings").scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${out}/card-readings-${name}.png` });
    // A first-day player: one point, both changes withheld.
    await page.goto(`${site}/in-season/?view=opportunity`);
    await page.locator("table.sheet.opp-sheet").first().waitFor();
    await page.getByRole("button", { name: "James Cook III", exact: true }).first().click();
    const second = page.getByRole("dialog");
    await second.waitFor();
    const tab = second.getByRole("tab", { name: "In-season usage" });
    if ((await tab.count()) > 0) await tab.click();
    const show = second.getByRole("button", { name: "Show ESPN trend" });
    if ((await show.count()) > 0) await show.click();
    await second.getByTestId("espn-ownership-chart").waitFor();
    await second.getByTestId("espn-block").scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${out}/card-first-day-${name}.png` });
  }
  report[`errors-${name}`] = errors;
  await context.close();
}
writeFileSync(`${out}/measurements.json`, `${JSON.stringify(report, null, 2)}\n`);
await browser.close();
server.close();
const problems = Object.entries(report).filter(([key, value]) =>
  key.startsWith("errors-") ? value.length > 0 : value.pageX > 0 || value.clipped.length > 0 || (value.chartOverflow ?? 0) > 1,
);
console.log(problems.length === 0 ? "0 problems" : JSON.stringify(problems, null, 2));
