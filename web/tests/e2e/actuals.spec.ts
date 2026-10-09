/**
 * Season-to-date actuals beside rest-of-season value, in a real browser (ADR-105).
 *
 * What only a browser can show: the comparison lane's marks do not overlap or clip at desktop,
 * 390 and 320 pixels; a card opened by keyboard, or from any tab by a direct link, carries the
 * complete actuals without another tab having been visited; the card's headshot keeps its
 * shape and its header stays on screen with the rank tags in it; the week board sorts by any
 * column; and the new surfaces scan clean.
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { guardBoundary } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
/** RoS QB1, season QB4 on the fixture. */
const ALLEN = "gsis:00-0000008";
/** RoS RB1 and season RB1: two marks at one rank. */
const BIJAN = "gsis:00-0000001";
/** RoS WR2, season WR7: the widest gap on the fixture board. */
const SWIFT = "gsis:00-0000003";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

async function box(page: Page, selector: string) {
  const handle = page.locator(selector).first();
  const found = await handle.boundingBox();
  if (found === null) throw new Error(`no box for ${selector}`);
  return found;
}

for (const width of [1440, 390, 320]) {
  test(`the comparison lane is whole and readable at ${String(width)}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${IN_SEASON}?view=ros&scoring=ppr&teams=12`);
    await expect(page.locator(".tier-board[data-rank-lane='true'] .board-row").first()).toBeVisible();
    // No sideways page scroll.
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);

    for (const player of [ALLEN, BIJAN, SWIFT]) {
      const row = await box(page, `.board-row[data-player="${player}"]`);
      const lane = await box(page, `.board-row[data-player="${player}"] .row-ranklane`);
      const square = await box(page, `.board-row[data-player="${player}"] .rank-mark[data-kind="ros"]`);
      const triangle = await box(page, `.board-row[data-player="${player}"] .rank-mark[data-kind="season"]`);
      // Inside the lane, never clipped.
      for (const mark of [square, triangle]) {
        expect(mark.x).toBeGreaterThanOrEqual(lane.x - 0.5);
        expect(mark.x + mark.width).toBeLessThanOrEqual(lane.x + lane.width + 0.5);
      }
      // Two tracks: the triangle sits below the square, so equal ranks never hide each other.
      expect(triangle.y).toBeGreaterThanOrEqual(square.y + square.height - 1);
      // The words fit inside the row.
      const words = await box(page, `.board-row[data-player="${player}"] .row-rankvalues`);
      expect(words.x + words.width).toBeLessThanOrEqual(row.x + row.width + 0.5);
    }
    await expect(page.locator(`.board-row[data-player="${ALLEN}"] .rank-value[data-kind="ros"]`)).toContainText("QB1");
    await expect(page.locator(`.board-row[data-player="${ALLEN}"] .rank-value[data-kind="season"]`)).toContainText("QB4");
    // Equal ranks: the same x, two marks.
    const bijanSquare = await box(page, `.board-row[data-player="${BIJAN}"] .rank-mark[data-kind="ros"]`);
    const bijanTriangle = await box(page, `.board-row[data-player="${BIJAN}"] .rank-mark[data-kind="season"]`);
    expect(Math.abs(bijanSquare.x + bijanSquare.width / 2 - (bijanTriangle.x + bijanTriangle.width / 2))).toBeLessThan(1);
  });
}

test("a row opens its card from the keyboard, with both ranks in the identity block", async ({ page }) => {
  await page.goto(`${IN_SEASON}?view=ros&scoring=ppr&teams=12`);
  const row = page.locator(`.board-row[data-player="${ALLEN}"]`);
  await row.focus();
  await page.keyboard.press("Enter");
  const pair = page.getByRole("dialog").getByTestId("rank-pair");
  await expect(pair).toContainText("RoS rank");
  await expect(pair).toContainText("QB1");
  await expect(pair).toContainText("Season rank");
  await expect(pair).toContainText("QB4");
  await expect(page.getByRole("dialog").getByTestId("rank-pair-meta")).toContainText(
    "RoS is 3 places above his season-to-date rank.",
  );
});

/*
 * The headshot is a flex item in a scrolling column, and every flex item shrinks by default:
 * the first in-season card let a long rail squash it to a 50px strip on a live build. At the
 * dialog's full 48rem the in-season rail fits with a square headshot; on a shorter screen the
 * headshot yields first, down to a 9rem floor that still shows the face, and only then does
 * the rail scroll.
 */
const FLOOR = 144;
for (const [width, height] of [
  [1272, 816],
  [1100, 800],
  [1440, 900],
  [1280, 720],
  [1280, 640],
] as const) {
  test(`the in-season card keeps its headshot whole at ${String(width)}x${String(height)}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto(`${IN_SEASON}?view=ros&scoring=ppr&teams=12`);
    await page.getByRole("button", { name: "Josh Allen", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("rank-pair")).toBeVisible();
    const portrait = await box(page, "dialog[open] .portrait");
    expect(portrait.width).toBeGreaterThan(200);
    expect(portrait.height).toBeGreaterThanOrEqual(FLOOR - 0.5);
    const overflow = await page.evaluate(() => {
      const rail = document.querySelector("dialog[open] .detail-rail");
      return rail === null ? null : rail.scrollHeight - rail.clientHeight;
    });
    if (height >= 800) {
      // The dialog's full 48rem: a square headshot and the whole rail without a scroll.
      expect(Math.abs(portrait.height - portrait.width)).toBeLessThanOrEqual(1);
    }
    if (height >= 720) {
      expect(overflow).toBeLessThanOrEqual(1);
      await expect(dialog.locator(".rail-status")).toBeInViewport();
    } else {
      // Shorter than the rail can fit: the headshot stops at its floor and the rail scrolls.
      expect(portrait.height).toBeLessThanOrEqual(FLOOR + 0.5);
    }
    // The tags sit in the identity row, the same height as the row's other tags.
    const tag = await box(page, "dialog[open] .detail-subtitle > .detail-posrank");
    const chip = await box(page, "dialog[open] .rank-chip[data-kind='season']");
    expect(Math.abs(chip.height - tag.height)).toBeLessThanOrEqual(1);
  });
}

for (const [width, height] of [
  [390, 844],
  [390, 664],
  [320, 568],
] as const) {
  test(`the phone sheet's header is on screen at ${String(width)}x${String(height)}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto(`${IN_SEASON}?view=ros&scoring=ppr&teams=12`);
    await page.getByRole("button", { name: "Josh Allen", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("rank-pair")).toBeVisible();
    const sheet = await box(page, "dialog[open]");
    expect(sheet.y).toBeGreaterThanOrEqual(0);
    expect(sheet.y + sheet.height).toBeLessThanOrEqual(height + 0.5);
    await expect(dialog.getByRole("button", { name: /close/i })).toBeInViewport();
    await expect(dialog.getByRole("heading", { name: "Josh Allen" })).toBeInViewport();
    await expect(dialog.getByTestId("rank-pair")).toBeInViewport();
    const portrait = await box(page, "dialog[open] .portrait");
    expect(Math.abs(portrait.height - portrait.width)).toBeLessThanOrEqual(1);
    // No tag is cut off at the sheet's right edge.
    const chip = await box(page, "dialog[open] .rank-chip[data-kind='season']");
    expect(chip.x + chip.width).toBeLessThanOrEqual(width);
  });
}

for (const width of [1440, 390]) {
  test(`the week board sorts by a selected column at ${String(width)}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${IN_SEASON}?view=startsit&scoring=ppr&teams=12`);
    const table = page.locator("table.weekboard-table");
    await expect(table.locator("tbody tr").first()).toBeVisible();
    const gap = table.getByRole("button", { name: /RoS vs\s+Szn/ });
    await gap.click();
    await expect(table.locator("th[data-col='ros_vs_season']")).toHaveAttribute("aria-sort", "descending");
    await expect(table.locator("tbody tr").first().locator(".player-name")).toHaveText("Ja'Marr Swift");
    await expect(page.locator(".weekboard-sorted")).toContainText("Sorted by RoS vs Szn, descending");
    await gap.click();
    await expect(table.locator("th[data-col='ros_vs_season']")).toHaveAttribute("aria-sort", "ascending");
    // A this-week column: blanks last, and a player who cannot play this week sorts with
    // them, as on the board's own order — he is not one of the choices.
    await table.getByRole("button", { name: /^Median/ }).click();
    const medians = await table.locator("tbody tr").evaluateAll((rows) =>
      rows.map((row) => ({
        text: row.querySelector("td.wb-median")?.textContent?.trim() ?? "",
        muted: row.getAttribute("data-availability") === "muted",
      })),
    );
    const playable = medians.filter((m) => !m.muted && m.text !== "—");
    expect(medians.slice(0, playable.length)).toEqual(playable);
    const known = playable.map((m) => Number(m.text));
    expect(known).toEqual([...known].sort((a, b) => b - a));
    expect(medians.slice(playable.length).every((m) => m.muted || m.text === "—")).toBe(true);
    await page.getByRole("button", { name: /^Back to Startable order/ }).click();
    await expect(table.locator("th[data-col='startable']")).toHaveAttribute("aria-sort", "descending");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

for (const width of [1280, 1440]) {
  test(`the week board fits without a sideways scroll at ${String(width)}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${IN_SEASON}?view=startsit&scoring=ppr&teams=12`);
    const scroller = page.locator(".weekboard-scroll");
    await expect(scroller.locator("tbody tr").first()).toBeVisible();
    const overflow = await scroller.evaluate((node) => node.scrollWidth - node.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

for (const view of ["startsit", "opportunity", "ros"]) {
  test(`a direct link to ${view} opens a card with complete actuals`, async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=${view}&scoring=ppr&teams=12`);
    await page.getByRole("button", { name: "Josh Allen", exact: true }).first().click();
    await expect(page.getByRole("dialog").getByTestId("rank-pair")).toContainText("QB4");
  });
}

test("the scoring preset is part of the reading", async ({ page }) => {
  await page.goto(`${IN_SEASON}?view=ros&scoring=std&teams=12`);
  await page.getByRole("button", { name: "Josh Allen", exact: true }).first().click();
  await expect(page.getByRole("dialog").getByTestId("rank-pair-meta")).toContainText("Standard · through week 8");
});

for (const width of [1280, 320]) {
  test(`the RoS board and an open card scan clean at ${String(width)}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${IN_SEASON}?view=ros&scoring=ppr&teams=12`);
    await expect(page.locator(".tier-board .board-row").first()).toBeVisible();
    const board = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(board.violations.map((v) => `${v.id}: ${String(v.nodes.length)}`)).toEqual([]);
    await page.getByRole("button", { name: "Josh Allen", exact: true }).first().click();
    await expect(page.getByRole("dialog").getByTestId("rank-pair")).toBeVisible();
    const card = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(card.violations.map((v) => `${v.id}: ${String(v.nodes.length)}`)).toEqual([]);
  });
}

test("the week board and the unprojected list scan clean on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(`${IN_SEASON}?view=startsit&scoring=ppr&teams=12`);
  await expect(page.locator(".weekboard-table")).toBeVisible();
  await expect(page.locator(".wb-sub-ranks").first()).toBeVisible();
  const week = await new AxeBuilder({ page }).include(".weekboard").withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(week.violations.map((v) => v.id)).toEqual([]);
  // Sorted, with the status line showing, too.
  await page.locator("table.weekboard-table").getByRole("button", { name: /^Szn rank/ }).click();
  const sorted = await new AxeBuilder({ page }).include(".weekboard").withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(sorted.violations.map((v) => v.id)).toEqual([]);
  await page.goto(`${IN_SEASON}?view=opportunity&scoring=ppr&teams=12`);
  await expect(page.locator("table.unprojected-sheet")).toBeVisible();
  const list = await new AxeBuilder({ page }).include("table.unprojected-sheet").withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(list.violations.map((v) => v.id)).toEqual([]);
});
