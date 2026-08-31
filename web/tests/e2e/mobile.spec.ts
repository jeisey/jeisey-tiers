/**
 * Mobile.
 *
 * The same product at a smaller size, not a second one (`docs/UX_SPEC.md` section 11). Nothing
 * core may need hover, the controls have to stay reachable while the board scrolls, and the
 * tables scroll horizontally rather than shrinking below legibility.
 *
 * Phase 8 added the responsive player card. At this width the dialog is a sheet rather than a
 * centred card, and the assertions below check the properties that decision was made for:
 * it reaches the bottom edge, it fills the width, the primary readouts are above the fold,
 * and the close control is a real target — not that it happens to have a particular height.
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
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Annotation only — not a model input.")).toBeVisible();
  await page.getByRole("button", { name: "Close player detail" }).click();
  await expect(dialog).toBeHidden();

  // Controls stay put while the board scrolls under them.
  await page.mouse.wheel(0, 900);
  await expect(page.getByRole("radio", { name: "PPR", exact: true })).toBeInViewport();
});

test("the player card becomes a sheet, with the draft-critical readouts above the fold", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  const viewport = page.viewportSize();
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  // Full width, anchored to the bottom edge: a sheet, not a card floating in a margin.
  expect(box?.width ?? 0).toBeGreaterThanOrEqual((viewport?.width ?? 0) - 1);
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeGreaterThanOrEqual((viewport?.height ?? 0) - 1);

  // What a drafter needs while the clock runs is visible without scrolling the sheet.
  for (const label of ["Fair rank", "Tier", "MFL ADP", "Value gap"]) {
    await expect(dialog.getByText(label, { exact: true })).toBeInViewport();
  }

  // The close control is a real touch target (WCAG 2.2 AA target size is 24x24).
  const close = await page.getByRole("button", { name: "Close player detail" }).boundingBox();
  expect(close?.width ?? 0).toBeGreaterThanOrEqual(24);
  expect(close?.height ?? 0).toBeGreaterThanOrEqual(24);

  // Escape still dismisses it: the sheet is a native modal dialog wearing a different skin.
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("the arbitrage rail stacks cleanly on a phone", async ({ page }) => {
  await page.goto("/?view=arbitrage");
  await expect(page.getByRole("heading", { name: "Draft rail" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.locator(".draft-rail").first()).toBeVisible();
  expect(await page.locator(".rail-fill").count()).toBeGreaterThan(0);

  // The columns must not collide. A name running under the delta bar, or a bar running
  // through the signed number that explains it, is the failure mode a narrow viewport
  // produces and a wide one hides. Grid columns cannot overlap by construction, so what is
  // actually worth asserting is that every one of them still has a usable width and that
  // they are laid out left to right in the order a reader expects.
  const geometry = await page.evaluate(() => {
    const row = document.querySelector(".rail-row");
    if (row === null) return null;
    const rect = (selector: string): { left: number; right: number } | null => {
      const node = row.querySelector(selector);
      if (node === null) return null;
      const box = node.getBoundingClientRect();
      return { left: box.left, right: box.right };
    };
    return {
      name: rect(".rail-name"),
      delta: rect(".rail-delta"),
      gap: rect(".rail-gap"),
    };
  });
  expect(geometry).not.toBeNull();
  expect(geometry?.name?.right ?? 0).toBeLessThanOrEqual(geometry?.delta?.left ?? 0);
  expect(geometry?.delta?.right ?? 0).toBeLessThanOrEqual((geometry?.gap?.left ?? 0) + 1);
  expect((geometry?.delta?.right ?? 0) - (geometry?.delta?.left ?? 0)).toBeGreaterThan(40);

  await expect(
    page.getByText(/Every priced row on this board carries low market-data confidence/i),
  ).toBeVisible();
  // The board itself has to be reachable on a phone, not buried under explanation.
  await expect(page.getByRole("heading", { name: "Draft rail" })).toBeInViewport();
});

test("a tier can be opened and closed with a thumb", async ({ page }) => {
  await page.goto("/");
  const heads = page.locator(".tier-head");
  await expect(heads.first()).toBeVisible();
  // The header is the toggle, so it is the target, and it has to be big enough to hit.
  const box = await heads.first().boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);

  const before = await page.locator(".board-row").count();
  await heads.first().click();
  expect(await page.locator(".board-row").count()).toBeLessThan(before);
});
