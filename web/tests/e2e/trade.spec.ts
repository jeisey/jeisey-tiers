/**
 * End-to-end coverage of the Trade tab (ADR-100), against the static in-season build.
 *
 * What the component tests cannot see: the lazily loaded chunk and the payload it adds, the
 * shared link across reload and Back/Forward in a real history, keyboard use of the picker,
 * and the layout at every width that matters (1440, 820, 390, 320).
 */

import { expect, test, type Page } from "@playwright/test";

import { guardBoundary } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const BIJAN = "00-0000001";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

function packageNames(page: Page): Promise<string[]> {
  return page.locator(".trade-results > .trade-package").evaluateAll((items) =>
    items.map((item) => item.getAttribute("aria-label") ?? ""),
  );
}

test.describe("the tab", () => {
  test("sits third and loads its own code and no data beyond the default view's", async ({ page }) => {
    await page.goto(IN_SEASON);
    await expect(page.getByRole("heading", { name: /Rest of season/ }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    const requests: string[] = [];
    page.on("request", (request) => requests.push(new URL(request.url()).pathname));
    const tabs = page.getByRole("tablist", { name: "Board" }).getByRole("tab");
    await expect(tabs.nth(2)).toHaveText("Trade");
    await tabs.nth(2).click();
    await expect(page).toHaveURL(/view=trade/);
    await expect(page.getByRole("heading", { name: "Trade targets" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(requests.filter((path) => path.includes("/data/"))).toEqual([]);
    expect(requests.filter((path) => /TradeView-.*\.js$/.test(path))).toHaveLength(1);
  });

  test("on a build with no rest-of-season board, says so and the draft board is unaffected", async ({ page }) => {
    await page.goto("/jeisey-tiers/?view=trade");
    await expect(page.getByText("No rest-of-season board has been published yet.")).toBeVisible();
    await page.goto("/jeisey-tiers/");
    await expect(page.getByRole("heading", { name: "Tier board" }).first()).toBeVisible();
  });
});

test.describe("the flow", () => {
  test("give one, receive two: picker by keyboard, results, and a shared link that reloads identically", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=trade`);
    const picker = page.getByRole("combobox", { name: "Add a player you would give" });
    await picker.focus();
    await page.keyboard.type("Bijan");
    await expect(page.getByRole("option", { name: /Bijan Robinson/ })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`give=${BIJAN}`));
    await page.getByRole("radio", { name: "Receive 2 players" }).click();
    await expect(page).toHaveURL(/get=2/);
    await expect(page.getByText("Give 1 · Receive 2")).toBeVisible();
    await expect(page.locator(".trade-results > .trade-package").first()).toBeVisible();
    const names = await packageNames(page);
    expect(names.length).toBeGreaterThan(0);
    expect(names.length).toBeLessThanOrEqual(5);
    await expect(page.getByText("Model-based targets.")).toHaveCount(1);

    await page.reload();
    await expect(page.locator(".trade-results > .trade-package").first()).toBeVisible();
    expect(await packageNames(page)).toEqual(names);
  });

  test("swap, keep, Back and Forward walk the exploration through history", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=trade&give=${BIJAN}&get=2&range=50`);
    await expect(page.locator(".trade-results > .trade-package")).toHaveCount(5);
    const first = await packageNames(page);
    await page.getByRole("button", { name: "Swap package 3 for another" }).click();
    await expect(page).toHaveURL(/shown=/);
    const swapped = await packageNames(page);
    expect(swapped[2]).not.toBe(first[2]);

    await page.locator(".trade-results > .trade-package").first().getByRole("button", { name: "Keep" }).click();
    await expect(page.getByText("Kept (1 of 3)")).toBeVisible();

    await page.goBack();
    await expect(page.getByText("Kept (1 of 3)")).toHaveCount(0);
    expect(await packageNames(page)).toEqual(swapped);
    await page.goBack();
    expect(await packageNames(page)).toEqual(first);
    await page.goForward();
    expect(await packageNames(page)).toEqual(swapped);
  });

  test("the preset changes the order, not the comparable pool", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=trade&give=${BIJAN}&get=2&range=50`);
    const count = await page.locator(".trade-count").textContent();
    for (const name of ["Highest ceiling", "Highest floor", "ROS value"]) {
      await page.getByRole("radio", { name }).click();
      await expect(page.locator(".trade-count")).toHaveText(count ?? "");
    }
  });

  test("a member opens the existing player card", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=trade&give=${BIJAN}&get=2&range=35`);
    await page.locator(".trade-results .trade-members .player-name").first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});

test.describe("layout", () => {
  for (const [width, height] of [
    [1440, 1000],
    [820, 1180],
    [390, 844],
    [320, 800],
  ] as const) {
    test(`fits ${String(width)}px without sideways scroll, with the active tab on screen`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(`${IN_SEASON}?view=trade&give=${BIJAN}&get=3&range=50`);
      await expect(page.locator(".trade-results > .trade-package").first()).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
      const active = page.getByRole("tab", { name: "Trade" });
      await expect(active).toBeInViewport({ ratio: 1 });
      const box = await active.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    });
  }
});
