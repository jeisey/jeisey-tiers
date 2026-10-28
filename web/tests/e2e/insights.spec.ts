/**
 * Insights (ADR-116) in a real browser: the tab and what it fetches, deep links and editions,
 * the URL as the store across back, forward and reload, the player card, the share view and its
 * PNG — a real file of the exact pixel size, not a blank one — copying a link, and a link that
 * keeps the GitHub Pages base path.
 */

import { readFileSync } from "node:fs";
import type { AddressInfo } from "node:net";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { stubPortraits } from "./boundary";
import { createStaticServer } from "./static-server.mjs";

const SITE = "/scenario/in-season/";
/** Thursday before the fixture's week-9 Sunday: every game is still to come. */
const BEFORE_KICKOFFS = new Date("2026-11-05T12:00:00Z");
const PUKA = "upside-00-0000012";
const BURROW = "pace-00-0000009";
const LONG = "upside-00-0000095";

test.beforeEach(async ({ page }) => {
  await stubPortraits(page);
});

function pngSize(bytes: Buffer): { readonly width: number; readonly height: number } {
  expect([...bytes.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  expect(bytes.subarray(12, 16).toString("ascii")).toBe("IHDR");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

/** Distinct colours in a sample of the image's pixels: a blank or one-colour file has 1. */
async function distinctColours(page: Page, bytes: Buffer): Promise<number> {
  return page.evaluate(async (base64) => {
    const image = new Image();
    image.src = `data:image/png;base64,${base64}`;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d");
    if (context === null) return 0;
    context.drawImage(image, 0, 0);
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const seen = new Set<number>();
    for (let index = 0; index < data.length; index += 4 * 37) {
      seen.add(((data[index] ?? 0) << 16) | ((data[index + 1] ?? 0) << 8) | (data[index + 2] ?? 0));
    }
    return seen.size;
  }, bytes.toString("base64"));
}

async function downloadPng(page: Page): Promise<{ readonly name: string; readonly bytes: Buffer }> {
  const dialog = page.getByRole("dialog", { name: "Share this story" });
  await expect(dialog.locator(".ins-share-preview[data-ready]")).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), dialog.getByRole("button", { name: "Download PNG" }).click()]);
  const path = await download.path();
  return { name: download.suggestedFilename(), bytes: readFileSync(path) };
}

test.describe("the tab", () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(BEFORE_KICKOFFS);
  });

  test("opens from the default view and fetches its stories and nothing heavy", async ({ page }) => {
    await page.goto(SITE);
    await expect(page.getByRole("heading", { name: /Rest of season/ }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    const requested: string[] = [];
    page.on("request", (request) => requested.push(new URL(request.url()).pathname));
    await page.getByRole("tab", { name: "Insights" }).click();
    await expect(page.getByRole("heading", { name: "Lead stories" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(`${SITE}?view=insights`);
    expect(requested.filter((path) => path.includes("/serve/insights/"))).toHaveLength(1);
    expect(requested.some((path) => path.includes("/serve/insights/PPR."))).toBe(true);
    for (const heavy of ["weekly_projections", "/serve/card/", "skill_tree", "player_usage", "espn_ownership_series", "/insight_evidence/"]) {
      expect(requested.filter((path) => path.includes(heavy)), heavy).toEqual([]);
    }
    // The first lead story is the build's first, with its chart drawn and described.
    const first = page.locator(".ins-story").first();
    await expect(first).toHaveAttribute("data-story", PUKA);
    await expect(first.locator("svg.ins-chart-svg")).toBeVisible();
  });

  test("fetches the evidence slice once, the first time a reader expands a story", async ({ page }) => {
    const evidence: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/insight_evidence/")) evidence.push(new URL(request.url()).pathname);
    });
    await page.goto(`${SITE}?view=insights`);
    await expect(page.locator(".ins-story").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(evidence).toEqual([]);
    const first = page.locator(`#story-${PUKA}`);
    await first.getByRole("button", { name: "Evidence" }).click();
    await expect(first.getByRole("region", { name: "Qualification" })).toBeVisible();
    const second = page.locator(`#story-${BURROW}`);
    await second.getByRole("button", { name: "Evidence" }).click();
    await expect(second.getByRole("region", { name: "Qualification" })).toBeVisible();
    expect(evidence).toHaveLength(1);
    expect(evidence[0]).toMatch(/\/serve\/insight_evidence\/PPR\./);
  });

  test("opens a player's card from a story", async ({ page }) => {
    await page.goto(`${SITE}?view=insights`);
    await page.locator(`#story-${BURROW}`).getByRole("button", { name: "Joe Burrow" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Joe Burrow");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.locator(`#story-${BURROW}`).getByRole("button", { name: "Joe Burrow" })).toBeFocused();
  });

  test("keeps the filter and the ceiling in the URL through back, forward and reload", async ({ page }) => {
    await page.goto(`${SITE}?view=insights`);
    const filter = page.getByRole("radiogroup", { name: "Show" });
    await filter.getByRole("radio", { name: /^This week/ }).click();
    await expect(page).toHaveURL(`${SITE}?view=insights&ins=week`);
    const ceiling = page.getByRole("radiogroup", { name: /ESPN rostered below/ });
    await ceiling.getByRole("radio", { name: /fewer than 25%/ }).click();
    await expect(page).toHaveURL(`${SITE}?view=insights&ins=week&ceil=25`);
    const shown = async (): Promise<string[]> =>
      page.locator(".ins-story").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-story") ?? ""));
    const under25 = await shown();
    expect(under25).not.toContain(PUKA);
    await page.goBack();
    await expect(page).toHaveURL(`${SITE}?view=insights&ins=week`);
    await expect(ceiling.getByRole("radio", { name: /fewer than 50%/ })).toHaveAttribute("aria-checked", "true");
    await expect(page.locator(`#story-${PUKA}`)).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(`${SITE}?view=insights&ins=week&ceil=25`);
    await expect(page.locator(`#story-${PUKA}`)).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("radiogroup", { name: /ESPN rostered below/ }).getByRole("radio", { name: /fewer than 25%/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect.poll(shown).toEqual(under25);
  });
});

test.describe("links and editions", () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(BEFORE_KICKOFFS);
  });

  test("a story link scrolls to its story and focuses it, fetching no evidence", async ({ page }) => {
    const evidence: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/insight_evidence/")) evidence.push(request.url());
    });
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`${SITE}?view=insights&story=${BURROW}&ed=2026w08`);
    const card = page.locator(`#story-${BURROW}`);
    await expect(card.locator(".ins-headline")).toBeFocused();
    await expect(card.locator(".ins-headline")).toBeInViewport();
    await expect(card.getByRole("button", { name: "Evidence" })).toHaveAttribute("aria-expanded", "false");
    await expect(card.getByText("Linked story")).toBeVisible();
    expect(evidence).toEqual([]);
  });

  test("a link from an older edition names both editions and marks the current version", async ({ page }) => {
    await page.goto(`${SITE}?view=insights&story=${PUKA}&ed=2026w07`);
    await expect(page.getByText("This link is from the Week 7 edition; the current edition is Week 8.")).toBeVisible();
    await expect(page.locator(`#story-${PUKA}`).getByText("Updated for Week 8")).toBeVisible();
    await page.goto(`${SITE}?view=insights&story=upside-00-0099999&ed=2026w07`);
    await expect(page.getByText(/This story is no longer in the current edition\./)).toBeVisible();
    await expect(page.getByText(/Updated for/)).toHaveCount(0);
  });

  test("copies a link that opens the same story and edition, and nothing else", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto(`${SITE}?view=insights&teams=10&position=qb`);
    const card = page.locator(`#story-${BURROW}`);
    await card.getByRole("button", { name: "Copy link" }).click();
    await expect(card.getByRole("status")).toHaveText("Link copied.");
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toBe(`http://localhost:4173${SITE}?view=insights&scoring=ppr&story=${BURROW}&ed=2026w08`);
    await card.getByRole("button", { name: "Copy summary" }).click();
    await expect(card.getByRole("status")).toHaveText("Summary copied.");
    const summary = await page.evaluate(() => navigator.clipboard.readText());
    expect(summary).toContain("Caveat: Pace is arithmetic");
    expect(summary).toContain(copied);
  });

  test("a story link keeps the GitHub Pages base path", async ({ page, context }) => {
    const server = createStaticServer({ roots: [{ base: "/jeisey-tiers/", dir: resolve("web/dist-pages-in-season") }] });
    await new Promise<void>((done) => server.listen(0, done));
    const port = (server.address() as AddressInfo).port;
    try {
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      const requested: string[] = [];
      page.on("request", (request) => requested.push(request.url()));
      const site = `http://localhost:${String(port)}/jeisey-tiers/`;
      await page.goto(`${site}?view=insights&story=${BURROW}&ed=2026w08`);
      const card = page.locator(`#story-${BURROW}`);
      await expect(card.locator(".ins-headline")).toBeFocused();
      await card.getByRole("button", { name: "Copy link" }).click();
      await expect(card.getByRole("status")).toHaveText("Link copied.");
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
        `${site}?view=insights&scoring=ppr&story=${BURROW}&ed=2026w08`,
      );
      expect(requested.filter((url) => url.startsWith(`http://localhost:${String(port)}/`) && !url.startsWith(site))).toEqual([]);
    } finally {
      server.close();
    }
  });
});

test.describe("kickoff", () => {
  test("a page left open withdraws a start idea at its kickoff and not before", async ({ page }) => {
    await page.clock.install({ time: new Date("2026-11-08T17:58:00Z") });
    await page.goto(`${SITE}?view=insights`);
    const puka = page.locator(`#story-${PUKA}`);
    await expect(puka).toBeVisible();
    await expect(puka).not.toHaveAttribute("data-withdrawn", /.*/);
    await page.clock.runFor(3 * 60_000);
    await expect(puka).toHaveAttribute("data-withdrawn", "true");
    await expect(puka.getByText(/Kickoff passed — no longer a start idea\./)).toBeVisible();
    // The Sunday-night game is still to come.
    await expect(page.locator("#story-upside-00-0000106")).not.toHaveAttribute("data-withdrawn", /.*/);
  });
});

test.describe("the share view", () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(BEFORE_KICKOFFS);
  });

  test("previews and downloads a real PNG at exactly 1200×675 and 1080×1350", async ({ page }) => {
    await page.goto(`${SITE}?view=insights`);
    const card = page.locator(`#story-${PUKA}`);
    await card.getByRole("button", { name: "Share" }).click();
    await expect(page).toHaveURL(`${SITE}?view=insights&story=${PUKA}&ed=2026w08&share=land`);
    const dialog = page.getByRole("dialog", { name: "Share this story" });
    await expect(dialog.getByRole("radio", { name: /Landscape/ })).toHaveAttribute("aria-checked", "true");
    await expect(dialog.locator(".ins-share-preview")).toHaveAttribute("data-fits", "true");
    await expect(dialog.locator(".ins-share-preview")).toHaveAttribute("data-overflow", "0");

    const landscape = await downloadPng(page);
    expect(landscape.name).toBe(`jeisey-tiers-${PUKA}-2026w08-landscape.png`);
    expect(pngSize(landscape.bytes)).toEqual({ width: 1200, height: 675 });
    expect(landscape.bytes.length).toBeGreaterThan(20_000);
    expect(await distinctColours(page, landscape.bytes)).toBeGreaterThan(40);
    await expect(dialog.getByRole("status")).toContainText("1200 × 675 px");

    await dialog.getByRole("radio", { name: /Portrait/ }).click();
    await expect(page).toHaveURL(`${SITE}?view=insights&story=${PUKA}&ed=2026w08&share=port`);
    await expect(dialog.getByRole("img", { name: /Share card \(portrait\)/ })).toBeVisible();
    const portrait = await downloadPng(page);
    expect(portrait.name).toBe(`jeisey-tiers-${PUKA}-2026w08-portrait.png`);
    expect(pngSize(portrait.bytes)).toEqual({ width: 1080, height: 1350 });
    expect(await distinctColours(page, portrait.bytes)).toBeGreaterThan(40);

    // The preview fits the screen; the file does not depend on it.
    const box = await dialog.getByRole("img", { name: /Share card/ }).boundingBox();
    expect(box?.height ?? 9999).toBeLessThanOrEqual((page.viewportSize()?.height ?? 0) * 0.62);

    // Escape closes it, keeps the story linked, and focus returns to the card's Share button.
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(`${SITE}?view=insights&story=${PUKA}&ed=2026w08`);
    await expect(card.getByRole("button", { name: "Share" })).toBeFocused();
  });

  test("a long name wraps on the card rather than clipping, in both layouts", async ({ page }) => {
    await page.goto(`${SITE}?view=insights&story=${LONG}&ed=2026w08&share=land`);
    const dialog = page.getByRole("dialog", { name: "Share this story" });
    await expect(dialog.locator(".ins-share-preview")).toHaveAttribute("data-overflow", "0");
    expect(pngSize((await downloadPng(page)).bytes)).toEqual({ width: 1200, height: 675 });
    await dialog.getByRole("radio", { name: /Portrait/ }).click();
    await expect(dialog.getByRole("img", { name: /Share card \(portrait\)/ })).toBeVisible();
    await expect(dialog.locator(".ins-share-preview")).toHaveAttribute("data-overflow", "0");
    expect(pngSize((await downloadPng(page)).bytes)).toEqual({ width: 1080, height: 1350 });
  });
});
