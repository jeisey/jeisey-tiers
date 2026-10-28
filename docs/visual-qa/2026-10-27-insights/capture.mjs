// Captures for ADR-116 (Insights): the feed at six widths (including a short phone), an expanded
// story, the share view, and real PNG exports downloaded from the share view — landscape and
// portrait for every chart form, including a long name — plus a JSON of overflow and clipping
// checks: page overflow, buttons pushed off screen, the first headline's position, and every
// text element of each share card measured against the card's own bounds.
//
// Usage, from the repository root after `npm run e2e:build`:
//   node docs/visual-qa/2026-10-27-insights/capture.mjs [out dir]
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { chromium } from "@playwright/test";
import { stubPortraits } from "../../../web/tests/e2e/portrait-stub.mjs";
import { createStaticServer } from "../../../web/tests/e2e/static-server.mjs";

const out = resolve(process.argv[2] ?? "docs/visual-qa/2026-10-27-insights");
mkdirSync(join(out, "screens"), { recursive: true });
mkdirSync(join(out, "exports"), { recursive: true });
const server = createStaticServer({
  roots: [
    { base: "/scenario/in-season/", dir: resolve("web/dist-in-season") },
    { base: "/scenario/in-season-insights-degraded/", dir: resolve("web/dist-in-season-insights-degraded") },
  ],
});
await new Promise((ok) => server.listen(4394, ok));
const site = "http://localhost:4394/scenario/in-season/";
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined ? {} : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
);
// Thursday before the fixture's week-9 Sunday: every week-9 game is still to come.
const NOW = new Date("2026-11-05T12:00:00Z");

const sizes = [
  ["320", 320, 640, true],
  ["390", 390, 844, true],
  ["short-390x560", 390, 560, true],
  ["768", 768, 1024, true],
  ["1024", 1024, 800, false],
  ["1440", 1440, 900, false],
];

const measurePage = (page) =>
  page.evaluate(() => {
    const first = document.querySelector(".ins-story .ins-headline");
    const box = first?.getBoundingClientRect() ?? null;
    return {
      pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      firstHeadlineTop: box === null ? null : Math.round(box.top),
      viewportHeight: window.innerHeight,
      offscreenButtons: [...document.querySelectorAll("button, [role='radio']")]
        .filter((node) => {
          const rect = node.getBoundingClientRect();
          if (rect.width === 0 || (rect.right <= window.innerWidth + 1 && rect.left >= -1)) return false;
          for (let up = node.parentElement; up !== null; up = up.parentElement) {
            if (["auto", "scroll"].includes(getComputedStyle(up).overflowX)) return false;
          }
          return true;
        })
        .map((node) => (node.textContent ?? "").trim().slice(0, 30)),
      smallTargets: window.innerWidth < 768
        ? [...document.querySelectorAll(".ins-chip, .ins-find, .ins-actions .button, .ins-player")]
            .filter((node) => node.getBoundingClientRect().height > 0 && node.getBoundingClientRect().height < 44)
            .map((node) => (node.textContent ?? "").trim().slice(0, 30))
        : [],
      // Chart labels that run past their own drawing.
      chartTextOutside: [...document.querySelectorAll(".ins-chart-svg")].reduce((count, svg) => {
        const width = svg.viewBox.baseVal.width;
        const height = svg.viewBox.baseVal.height;
        for (const text of svg.querySelectorAll("text")) {
          const b = text.getBBox();
          if (b.x < -0.5 || b.x + b.width > width + 0.5 || b.y < -0.5 || b.y + b.height > height + 0.5) count += 1;
        }
        return count;
      }, 0),
    };
  });

/** Every text element of the share card, laid out in the page with its fonts, against its box. */
const measureCard = (page) =>
  page.evaluate(async () => {
    const image = document.querySelector(".ins-share-preview[data-ready] img");
    const src = image?.getAttribute("src") ?? "";
    const svgText = decodeURIComponent(src.slice(src.indexOf(",") + 1));
    const holder = document.createElement("div");
    holder.style.cssText = "position:absolute;left:-20000px;top:0";
    holder.innerHTML = svgText;
    document.body.append(holder);
    await document.fonts.ready;
    const root = holder.querySelector("svg");
    const width = Number(root?.getAttribute("width"));
    const height = Number(root?.getAttribute("height"));
    const clipped = [];
    const boxes = [];
    for (const text of root?.querySelectorAll("text") ?? []) {
      const b = text.getBBox();
      const g = text.closest("g[transform]");
      const match = /translate\(([-\d.]+) ([-\d.]+)\)/.exec(g?.getAttribute("transform") ?? "");
      const dx = match === null ? 0 : Number(match[1]);
      const dy = match === null ? 0 : Number(match[2]);
      const box = { x: b.x + dx, y: b.y + dy, w: b.width, h: b.height, text: text.textContent };
      boxes.push(box);
      if (box.x < -0.5 || box.y < -0.5 || box.x + box.w > width + 0.5 || box.y + box.h > height + 0.5) clipped.push(box.text);
    }
    // Two text boxes of the card body overlapping each other (charts' own labels excluded).
    let overlaps = 0;
    const pairs = [];
    const body = boxes.filter((box) => box.w > 0);
    for (let i = 0; i < body.length; i += 1) {
      for (let j = i + 1; j < body.length; j += 1) {
        const a = body[i];
        const b = body[j];
        const ix = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
        const iy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        // Glyph boxes of consecutive lines of one block touch by design (line height < box
        // height); an overlap counts when it is a third of the smaller box or more.
        if (ix > 2 && iy > Math.min(a.h, b.h) / 3) {
          overlaps += 1;
          if (pairs.length < 5) pairs.push([a.text, b.text]);
        }
      }
    }
    holder.remove();
    const preview = document.querySelector(".ins-share-preview");
    return {
      width,
      height,
      texts: boxes.length,
      clipped,
      overlaps,
      overlapPairs: pairs,
      fits: preview?.getAttribute("data-fits"),
      scale: Number(preview?.getAttribute("data-scale")),
      layoutOverflow: Number(preview?.getAttribute("data-overflow")),
    };
  });

const report = { capturedAt: new Date().toISOString(), clock: NOW.toISOString(), screens: {}, exports: {} };
for (const [name, width, height, touch] of sizes) {
  const context = await browser.newContext({ viewport: { width, height }, hasTouch: touch, isMobile: touch && width < 768, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.clock.setFixedTime(NOW);
  await stubPortraits(page);
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(`${site}?view=insights`);
  await page.locator(".ins-story").first().waitFor();
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: join(out, "screens", `feed-${name}.png`) });
  report.screens[`feed-${name}`] = { ...(await measurePage(page)), errors };
  if (["390", "1440"].includes(name)) {
    await page.screenshot({ path: join(out, "screens", `feed-${name}-full.png`), fullPage: true });
    // An expanded story: the Evidence open on a role battle with null red-zone counts.
    const card = page.locator("#story-role-was-receiving");
    await card.getByRole("button", { name: "Evidence" }).click();
    // The evidence slice loads on this first expand.
    await card.getByRole("region", { name: "Qualification" }).waitFor();
    await card.screenshot({ path: join(out, "screens", `story-expanded-${name}.png`) });
    // The share view.
    await page.goto(`${site}?view=insights&story=volume-00-0000002&ed=2026w08&share=land`);
    await page.locator(".ins-share-preview[data-ready]").waitFor();
    await page.screenshot({ path: join(out, "screens", `share-landscape-${name}.png`) });
    await page.getByRole("radio", { name: /Portrait/ }).click();
    await page.locator(".ins-share-preview[data-ready] img[width='1080']").waitFor();
    // Let the layout control's 160ms transition settle before the capture.
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(out, "screens", `share-portrait-${name}.png`) });
    report.screens[`share-${name}`] = await measurePage(page);
  }
  if (name === "390") {
    // Withdrawn at kickoff, the edition notice, a degraded build, filtered to nothing.
    const later = await browser.newContext({ viewport: { width, height }, hasTouch: true, isMobile: true });
    const latePage = await later.newPage();
    await latePage.clock.setFixedTime(new Date("2026-11-08T18:05:00Z"));
    await latePage.goto(`${site}?view=insights&ins=week`);
    await latePage.locator(".ins-story").first().waitFor();
    await latePage.locator("#story-upside-00-0000012").screenshot({ path: join(out, "screens", "story-withdrawn-kickoff-390.png") });
    await latePage.locator("#story-upside-00-0000015").screenshot({ path: join(out, "screens", "story-withdrawn-policy-390.png") });
    await latePage.goto(`${site}?view=insights&story=upside-00-0000012&ed=2026w07`);
    await latePage.locator(".ins-link-notice").waitFor();
    await latePage.screenshot({ path: join(out, "screens", "edition-mismatch-390.png") });
    await latePage.goto("http://localhost:4394/scenario/in-season-insights-degraded/?view=insights");
    await latePage.locator(".ins-degraded").waitFor();
    await latePage.screenshot({ path: join(out, "screens", "degraded-390.png") });
    await later.close();
  }
  await context.close();
}

// Real PNG exports: every chart form, both layouts, at device scale 1 (the file's own size).
const stories = [
  ["upside-00-0000012", "upside"],
  ["upside-00-0000095", "upside-long-name"],
  ["volume-00-0000002", "volume-lagging"],
  ["volume-00-0000011", "volume-shrinking"],
  ["streak-00-0000006", "streak-touchdowns"],
  ["opening-00-0000004", "opening-one-game"],
  ["opening-00-0000014", "opening-prospective"],
  ["role-buf-backfield", "role-backfield"],
  ["role-was-receiving", "role-receiving-nulls"],
  ["pace-00-0000009", "pace"],
];
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, acceptDownloads: true });
const page = await context.newPage();
await page.clock.setFixedTime(NOW);
await stubPortraits(page);
for (const [id, label] of stories) {
  for (const layout of ["land", "port"]) {
    await page.goto(`${site}?view=insights&story=${id}&ed=2026w08&share=${layout}`);
    await page.locator(`.ins-share-preview[data-ready] img[width='${layout === "land" ? "1200" : "1080"}']`).waitFor();
    const checks = await measureCard(page);
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download PNG" }).click()]);
    const file = join(out, "exports", `${label}-${layout === "land" ? "landscape" : "portrait"}.png`);
    await download.saveAs(file);
    const bytes = readFileSync(file);
    report.exports[`${label}-${layout}`] = {
      file: file.slice(out.length + 1),
      suggested: download.suggestedFilename(),
      png: { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20), bytes: bytes.length },
      ...checks,
    };
  }
}
await context.close();
await browser.close();
server.close();

const summary = {
  pageOverflow: Object.values(report.screens).filter((entry) => entry.pageOverflowX > 1).length,
  offscreenButtons: Object.values(report.screens).reduce((sum, entry) => sum + entry.offscreenButtons.length, 0),
  smallTargets: Object.values(report.screens).reduce((sum, entry) => sum + (entry.smallTargets?.length ?? 0), 0),
  chartTextOutside: Object.values(report.screens).reduce((sum, entry) => sum + (entry.chartTextOutside ?? 0), 0),
  shareClippedText: Object.values(report.exports).reduce((sum, entry) => sum + entry.clipped.length, 0),
  shareTextOverlaps: Object.values(report.exports).reduce((sum, entry) => sum + entry.overlaps, 0),
  shareLayoutOverflow: Object.values(report.exports).reduce((sum, entry) => sum + entry.layoutOverflow, 0),
  exportsWrongSize: Object.values(report.exports).filter(
    (entry) => entry.png.width !== entry.width || entry.png.height !== entry.height,
  ).length,
};
writeFileSync(join(out, "checks.json"), `${JSON.stringify({ summary, ...report }, null, 1)}\n`);
console.log(JSON.stringify(summary, null, 1));
