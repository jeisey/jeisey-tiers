/**
 * The player search in a dialog, and Start/Sit's add-player picker (ADR-111), against the
 * static in-season build.
 *
 * What the unit tests cannot see: real `<dialog>` Escape and focus return, the board actually
 * filtered behind a closed dialog, back and forward through real history, and the empty deck
 * cards at the widths where the deck folds.
 */

import { expect, test, type Page } from "@playwright/test";

import { guardBoundary } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const PAIR = "duel=00-0000011.00-0000012";
const FOUR = "duel=00-0000011.00-0000012.00-0000003.00-0000002";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

const trigger = (page: Page) => page.getByRole("button", { name: /^Search players/ });
const field = (page: Page) => page.getByRole("combobox", { name: /Search players on/ });

async function openSearch(page: Page): Promise<void> {
  await trigger(page).click();
  await expect(field(page)).toBeFocused();
}

test.describe("the board search", () => {
  for (const [view, board, player] of [
    ["ros", "the rest-of-season board", "Puka Nightingale"],
    ["startsit", "the week-9 board", "Jahmyr Cook"],
    ["opportunity", "the Opportunity Board", "Bijan Robinson"],
  ] as const) {
    test(`on ${view}: apply, clear, cancel, back and forward`, async ({ page }) => {
      await page.goto(`${IN_SEASON}?view=${view}`);
      await openSearch(page);
      const dialog = page.getByRole("dialog", { name: "Search players" });
      await expect(dialog.getByText(`Choose a player to show him on ${board}`)).toBeVisible();

      // A partial query lists its matches and changes nothing until it is applied.
      const query = player.split(" ")[0]?.slice(0, 4).toLowerCase() ?? "";
      await field(page).fill(query);
      await expect(dialog.getByRole("option", { name: new RegExp(player) }).first()).toBeVisible();
      await expect(page).not.toHaveURL(/search=/);
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(new RegExp(`search=${query}`));
      await expect(dialog).toBeHidden();
      // Focus is back on the control that opened it, which prints the search.
      await expect(trigger(page)).toBeFocused();
      await expect(trigger(page)).toContainText(`“${query}”`);
      await expect(page.locator(".active-search")).toContainText(`“${query}”`);

      // Cancel never applies the unfinished query.
      await page.getByRole("button", { name: "Change" }).click();
      await expect(field(page)).toHaveValue(query);
      await field(page).fill("zz");
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(page).toHaveURL(new RegExp(`search=${query}`));
      await expect(page.getByRole("button", { name: "Change" })).toBeFocused();

      // Choosing one player applies his name, by keyboard.
      await openSearch(page);
      await field(page).fill(player.toLowerCase());
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(new RegExp(`search=${player.replace(" ", "\\+")}`));
      await expect(page.getByRole("button", { name: player, exact: true }).first()).toBeVisible();

      // One history entry per applied search: back returns to the partial query, then none.
      await page.goBack();
      await expect(page).toHaveURL(new RegExp(`search=${query}$`));
      await page.goBack();
      await expect(page).not.toHaveURL(/search=/);
      await expect(page.locator(".active-search")).toHaveCount(0);
      await page.goForward();
      await expect(page.locator(".active-search")).toContainText(`“${query}”`);

      await page.getByRole("button", { name: "Clear search" }).click();
      await expect(page).not.toHaveURL(/search=/);
      await expect(trigger(page)).toBeFocused();
    });
  }

  test("a chosen player is never hidden by the position filter, and the page says why", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=ros&scoring=half&position=qb`);
    await openSearch(page);
    await field(page).fill("puka");
    await page.getByRole("option", { name: /Puka Nightingale/ }).click();
    await expect(page).toHaveURL(/\?view=ros&scoring=half&search=Puka\+Nightingale$/);
    await expect(page.locator(".active-search")).toContainText(
      "Cleared the QB position filter to show Puka Nightingale (WR).",
    );
    await expect(page.getByRole("button", { name: "Puka Nightingale", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("radio", { name: "Half PPR" })).toHaveAttribute("aria-checked", "true");
  });

  test("a shared search link opens on the board with its search shown", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&search=pitts`);
    await expect(trigger(page)).toContainText("“pitts”");
    await expect(page.locator(".active-search")).toContainText("“pitts”");
    await expect(page.getByRole("button", { name: "Kyle Pitts Sr.", exact: true }).first()).toBeVisible();
  });

  test("is not offered where no board reads it", async ({ page }) => {
    for (const view of ["potw", "trade", "data"]) {
      await page.goto(`${IN_SEASON}?view=${view}`);
      await expect(page.getByRole("tab", { selected: true })).toBeVisible();
      await expect(trigger(page)).toHaveCount(0);
      await page.keyboard.press("/");
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
  });

  test("fits a 320px phone above its keyboard, with no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto(`${IN_SEASON}?view=ros`);
    await expect(page.locator(".search-trigger")).toBeAttached();
    await expect(async () => {
      await page.keyboard.press("/");
      await expect(field(page)).toBeFocused({ timeout: 500 });
    }).toPass();
    await field(page).fill("a");
    const card = await page.locator("dialog[open] .lg-dialog-card").boundingBox();
    // Top-anchored: the query and the first results sit in the top half, clear of a keyboard.
    expect(card?.y ?? Infinity).toBeLessThanOrEqual(16);
    const box = await field(page).boundingBox();
    expect((box?.y ?? Infinity) + (box?.height ?? 0)).toBeLessThan(568 / 2);
    await expect(page.getByRole("option").first()).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  });
});

test.describe("Start/Sit's empty cards", () => {
  const empty = (page: Page) => page.getByRole("button", { name: "Add a player to the comparison" });
  const picker = (page: Page) => page.getByRole("dialog", { name: "Add a player to the comparison" });
  const pickerField = (page: Page) => page.getByRole("combobox", { name: /Add a player to the week-9 comparison/ });

  for (const width of [1440, 390]) {
    test(`open the picker, add once, cancel, and stop at four at ${String(width)}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${IN_SEASON}?view=startsit`);
      // Every empty card on screen is a button: four on a desktop, one on a folded deck.
      const visible = width === 1440 ? 4 : 1;
      await expect(empty(page).filter({ visible: true })).toHaveCount(visible);
      for (let index = 0; index < visible; index += 1) {
        await empty(page).filter({ visible: true }).nth(index).click();
        await expect(pickerField(page)).toBeFocused();
        await picker(page).getByRole("button", { name: "Cancel" }).click();
        await expect(picker(page)).toBeHidden();
      }
      await expect(page).toHaveURL(/\?view=startsit$/);

      // Space on a focused card, then Enter on the active result.
      await empty(page).filter({ visible: true }).first().focus();
      await page.keyboard.press("Space");
      await expect(picker(page).getByText("He joins the comparison as A.")).toBeVisible();
      await pickerField(page).fill("jahmyr");
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(/duel=00-0000011$/);
      await expect(page.getByLabel(/Slot A: Jahmyr Cook/)).toBeVisible();

      // He is listed again, with the reason, and choosing him changes nothing.
      await empty(page).filter({ visible: true }).first().click();
      await pickerField(page).fill("jahmyr");
      const chosen = picker(page).getByRole("option", { name: /Jahmyr Cook/ });
      await expect(chosen).toHaveAttribute("aria-disabled", "true");
      // `force`: an option marked aria-disabled is not actionable for Playwright, which is the
      // point; the click is still delivered, and must change nothing.
      await chosen.click({ force: true });
      await expect(picker(page)).toBeVisible();
      await page.keyboard.press("Escape");
      await page.keyboard.press("Escape");
      await expect(picker(page)).toBeHidden();
      await expect(page).toHaveURL(/duel=00-0000011$/);

      await empty(page).filter({ visible: true }).first().click();
      await pickerField(page).fill("puka");
      await picker(page).getByRole("option", { name: /Puka Nightingale/ }).click();
      await expect(page).toHaveURL(/duel=00-0000011\.00-0000012$/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    });
  }

  test("a full comparison offers no empty card, and the week board's + still works", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=startsit&${FOUR}`);
    await expect(empty(page)).toHaveCount(0);
    await page.getByRole("button", { name: "Remove Puka Nightingale from the comparison" }).first().click();
    await expect(empty(page)).toHaveCount(1);
    await page.getByRole("button", { name: "Add Puka Nightingale to the comparison" }).first().click();
    await expect(page).toHaveURL(/duel=00-0000011\.00-0000003\.00-0000002\.00-0000012$/);
  });

  test("on a phone with a verdict, the folded empty row still adds", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await page.goto(`${IN_SEASON}?view=startsit&${PAIR}`);
    await empty(page).filter({ visible: true }).click();
    await pickerField(page).fill("swift");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/duel=00-0000011\.00-0000012\.00-0000003$/);
  });
});
