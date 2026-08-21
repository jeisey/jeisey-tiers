/**
 * Mobile.
 *
 * The same product at a smaller size, not a second one (`docs/UX_SPEC.md` section 11). Nothing
 * core may need hover, the controls have to stay reachable while the board scrolls, and the
 * tables scroll horizontally rather than shrinking below legibility.
 */

import { expect, test } from "@playwright/test";

test("the whole product is usable on a phone without hover", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();

  // The page itself must not scroll sideways; the table inside it may.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  const scroller = page.locator(".table-scroll").first();
  expect(await scroller.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);

  // Player detail opens on tap, which is the only pointer a phone has.
  await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
  await expect(page.getByRole("dialog").getByText(/not included in the projection/)).toBeVisible();
  await page.getByRole("button", { name: "Close player detail" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();

  // Controls stay put while the board scrolls under them.
  await page.mouse.wheel(0, 900);
  await expect(page.getByRole("radio", { name: "PPR", exact: true })).toBeInViewport();
});

test("the arbitrage rail stacks cleanly on a phone", async ({ page }) => {
  await page.goto("/?view=arbitrage");
  await expect(page.getByRole("heading", { name: "Draft rail" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  // A horizontal rule has zero height, which the visibility heuristic reads as hidden; the
  // chart's own box is what a reader actually sees.
  await expect(page.locator(".chart-frame svg").first()).toBeVisible();
  expect(await page.locator("svg .rail-connector").count()).toBeGreaterThan(0);
  await expect(page.getByText(/Every row on this board reads low market-data confidence/i)).toBeVisible();
  // The board itself has to be reachable on a phone, not buried under explanation.
  await expect(page.getByRole("heading", { name: "Draft rail" })).toBeInViewport();
});
