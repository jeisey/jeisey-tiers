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

  // The three columns must not collide. A name running under the first anchor, or a rail
  // running through the sentence that explains it, is the failure mode a narrow viewport
  // produces and a wide one hides.
  const geometry = await page.evaluate(() => {
    const svg = document.querySelector(".chart-frame svg");
    if (svg === null) return null;
    const right = (selector: string): number =>
      Math.max(
        ...[...svg.querySelectorAll(selector)].map((node) => {
          const box = (node as SVGGraphicsElement).getBBox();
          return box.x + box.width;
        }),
      );
    const left = (selector: string): number =>
      Math.min(
        ...[...svg.querySelectorAll(selector)].map((node) => (node as SVGGraphicsElement).getBBox().x),
      );
    return {
      nameRight: right("text.rail-name"),
      anchorLeft: left("path.rail-fair"),
      markRight: right("circle.rail-market"),
      gapLeft: left("text.rail-gap"),
    };
  });
  expect(geometry).not.toBeNull();
  expect(geometry?.nameRight ?? 0).toBeLessThanOrEqual(geometry?.anchorLeft ?? 0);
  expect(geometry?.markRight ?? 0).toBeLessThanOrEqual(geometry?.gapLeft ?? 0);
  await expect(page.getByText(/Every row on this board reads low market-data confidence/i)).toBeVisible();
  // The board itself has to be reachable on a phone, not buried under explanation.
  await expect(page.getByRole("heading", { name: "Draft rail" })).toBeInViewport();
});
