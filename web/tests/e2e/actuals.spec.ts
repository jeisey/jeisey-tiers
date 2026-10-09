/**
 * Season-to-date actuals beside rest-of-season value, in a real browser (ADR-105).
 *
 * What only a browser can show: the comparison lane's marks do not overlap or clip at desktop,
 * 390 and 320 pixels; a card opened by keyboard, or from any tab by a direct link, carries the
 * complete actuals without another tab having been visited; and the new surfaces scan clean.
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
  await expect(pair).toContainText("RoS is 3 places above his season-to-date rank.");
});

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
  await expect(page.getByRole("dialog").getByTestId("rank-pair")).toContainText("Standard · through week 8");
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
  await page.goto(`${IN_SEASON}?view=opportunity&scoring=ppr&teams=12`);
  await expect(page.locator("table.unprojected-sheet")).toBeVisible();
  const list = await new AxeBuilder({ page }).include("table.unprojected-sheet").withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(list.violations.map((v) => v.id)).toEqual([]);
});
