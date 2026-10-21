// Captures for ADR-113 (recent form and breakout categories) on the Opportunity Board: the
// default Last 3 lens, the evidence dialog, combined filters, no results, a long name beside a
// badge, an older build with no recent form, and the Season lens.
// Usage, from the repository root after `npm run e2e:build`:
//   node docs/visual-qa/2026-10-21-recent-form/capture.mjs <out dir>
//   node docs/visual-qa/2026-10-21-recent-form/capture.mjs --before <main's web/dist-in-season> <out dir>
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
    { base: "/scenario/in-season-no-recent/", dir: resolve("web/dist-in-season-no-recent") },
  ],
});
await new Promise((ok) => server.listen(4393, ok));
const site = "http://localhost:4393/scenario";
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined ? {} : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
);
const sizes = [
  ["320", 320, 640, true],
  ["390", 390, 844, true],
  ["short", 390, 560, true],
  ["820", 820, 1180, true],
  ["1024", 1024, 800, false],
  ["1440", 1440, 900, false],
];
const report = {};
const measure = (page) =>
  page.evaluate(() => {
    const scroller = [...document.querySelectorAll(".table-scroll")].find((node) => node.querySelector("table.opp-sheet") !== null);
    let slack = null;
    const table = scroller?.querySelector("table");
    if (scroller !== undefined && table !== null && table !== undefined) {
      table.style.width = "min-content";
      slack = Math.round(scroller.clientWidth - table.getBoundingClientRect().width);
      table.style.width = "";
    }
    return {
      pageX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      tableSlack: slack,
      clipped: [...document.querySelectorAll("button, [role='radio']")]
        .filter((node) => {
          const box = node.getBoundingClientRect();
          if (box.width === 0 || (box.right <= window.innerWidth + 1 && box.left >= -1)) return false;
          for (let up = node.parentElement; up !== null; up = up.parentElement) {
            if (["auto", "scroll"].includes(getComputedStyle(up).overflowX)) return false;
          }
          return true;
        })
        .map((node) => (node.textContent ?? "").trim().slice(0, 30))
        .filter((text) => text !== "")
        .slice(0, 5),
      dialogOverflow: (() => {
        const card = document.querySelector("dialog[open] .lg-dialog-card");
        if (card === null) return null;
        const box = card.getBoundingClientRect();
        return { right: Math.round(box.right - window.innerWidth), bottom: Math.round(box.bottom - window.innerHeight) };
      })(),
    };
  });
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
  const openOptions = async () => {
    const options = page.getByRole("button", { name: /^Options/ });
    if ((await options.count()) > 0 && (await options.isVisible())) await options.click();
  };
  const shot = async (key, url, open = async () => {}, scope = "opportunity") => {
    await page.goto(url);
    await page.locator(scope === "opportunity" ? "#opportunity-heading" : "body").first().waitFor();
    await page.waitForTimeout(150);
    await open();
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${out}/${key}-${name}.png`, fullPage: false });
    report[`${key}-${name}`] = await measure(page);
  };
  const toTable = async () => {
    await page.locator("table.sheet.opp-sheet").scrollIntoViewIfNeeded();
  };
  await shot("controls", `${site}/in-season/?view=opportunity`, openOptions);
  await shot("table", `${site}/in-season/?view=opportunity`, toTable);
  if (!before) {
    await shot("dialog", `${site}/in-season/?view=opportunity`, async () => {
      const badge = page.locator('tr[data-player="gsis:00-0000007"] .breakout-badge');
      await badge.scrollIntoViewIfNeeded();
      await badge.click();
      await page.getByRole("dialog").waitFor();
    });
    await shot("long-name", `${site}/in-season/?view=opportunity`, async () => {
      await page.evaluate(() => {
        const button = document.querySelector('tr[data-player="gsis:00-0000007"] .player-name');
        if (button !== null) button.textContent = "Christopher Longnamefellow-Smithson Jr.";
      });
      await page.locator('tr[data-player="gsis:00-0000007"]').scrollIntoViewIfNeeded();
    });
    await shot("combined", `${site}/in-season/?view=opportunity&last=2&form=any&espn=lt75&position=wr`, async () => {
      await openOptions();
    });
    await shot("no-results", `${site}/in-season/?view=opportunity&form=sneaking&position=te`, async () => {
      await page.getByText("No players match.").first().scrollIntoViewIfNeeded();
    });
    await shot("season-lens", `${site}/in-season/?view=opportunity&last=season`, toTable);
    await shot("insufficient", `${site}/in-season/?view=opportunity&last=6`, async () => {
      const button = page.locator(".breakout-insufficient").first();
      await button.scrollIntoViewIfNeeded();
      await button.click();
      await page.getByRole("dialog").waitFor();
    });
    await shot("no-recent", `${site}/in-season-no-recent/?view=opportunity&form=takeover`, openOptions);
  }
  report[`errors-${name}`] = errors;
  await context.close();
}
writeFileSync(`${out}/measurements.json`, `${JSON.stringify(report, null, 2)}\n`);
await browser.close();
server.close();
const problems = Object.entries(report).filter(([key, value]) =>
  key.startsWith("errors-") ? value.length > 0 : value.pageX > 1 || value.clipped.length > 0 || (value.dialogOverflow !== null && value.dialogOverflow.right > 1),
);
console.log(JSON.stringify({ captures: Object.keys(report).length, problems }, null, 1));
process.exitCode = problems.length === 0 ? 0 : 1;
