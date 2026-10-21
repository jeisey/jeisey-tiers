/**
 * The Opportunity Board's recent-weeks lens and breakout badges in a real browser (ADR-113).
 *
 * Direct links, reload, back/forward and preset changes; the badge's evidence by keyboard and
 * by touch; the export matching the view in its sort order; phone widths with the name pinned;
 * an older build that has none of it; and axe with the evidence dialog open.
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { stubPortraits } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const NO_RECENT = "/scenario/in-season-no-recent/";

test.beforeEach(async ({ page }) => {
  await stubPortraits(page);
});

function table(page: Page) {
  return page.locator("table.sheet.opp-sheet");
}

function lens(page: Page) {
  return page.getByRole("radiogroup", { name: "Recent weeks" });
}

async function readCsv(page: Page): Promise<string[]> {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Export filtered CSV/ }).click();
  const stream = await (await download).createReadStream();
  const chunks: Uint8Array[] = [];
  for await (const chunk of stream) chunks.push(new Uint8Array(Buffer.from(chunk as Buffer)));
  return Buffer.concat(chunks).toString("utf-8").replace(/^\uFEFF/, "").trim().split("\r\n");
}

test.describe("the recent-weeks lens", () => {
  test("defaults to Last 3, names its weeks, and a badge opens its evidence by keyboard", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${IN_SEASON}?view=opportunity`);
    await expect(lens(page).getByRole("radio", { name: /Last 3 completed weeks, W6–W8/ })).toHaveAttribute("aria-checked", "true");
    await expect(table(page).locator('th[data-col="recent_rank"]')).toContainText("Recent W6–8");
    await expect(page.locator(".opp-breakout-census")).toContainText("Breakouts in W6–8: 1 Takeover");
    const badge = table(page).getByRole("button", { name: /^Takeover in W6–W8/ });
    await badge.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("TE15 season → TE3 in W6–W8 (+12 places)");
    await expect(dialog).toContainText("Games used: W6 TE3");
    await expect(dialog).toContainText("snap share 70.6% over 3 games");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(badge).toBeFocused();
  });

  test("switches windows through the URL, survives reload and back/forward, and follows the preset", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const ertz = table(page).locator('tr[data-player="gsis:00-0000007"]');
    await expect(ertz.locator(".breakout-badge")).toHaveAttribute("data-category", "takeover");
    await lens(page).getByRole("radio", { name: /^Last 1 completed weeks/ }).click();
    await expect(page).toHaveURL(/last=1/);
    await expect(ertz.locator(".breakout-badge")).toHaveAttribute("data-category", "eyebrow");
    await page.reload();
    await expect(ertz.locator(".breakout-badge")).toHaveAttribute("data-category", "eyebrow");
    await lens(page).getByRole("radio", { name: /^Season to date only/ }).click();
    await expect(page).toHaveURL(/last=season/);
    await expect(table(page).locator('th[data-col="recent_rank"]')).toHaveCount(0);
    await expect(table(page).locator(".breakout-badge")).toHaveCount(0);
    await page.goBack();
    await expect(page).toHaveURL(/last=1/);
    await expect(ertz.locator(".breakout-badge")).toHaveAttribute("data-category", "eyebrow");
    await page.goBack();
    await expect(page).not.toHaveURL(/last=/);
    await expect(ertz.locator(".breakout-badge")).toHaveAttribute("data-category", "takeover");
    // Standard scoring: his season rank is TE3 there, so the same weeks are no rise at all.
    await page.goto(`${IN_SEASON}?view=opportunity&scoring=std`);
    await expect(table(page).locator('tr[data-player="gsis:00-0000007"] .breakout-badge')).toHaveCount(0);
  });

  test("normalizes a malformed link and keeps the board whole", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&last=5&form=great`);
    await expect(page).not.toHaveURL(/last=|form=/);
    await expect(lens(page).getByRole("radio", { name: /Last 3 completed weeks/ })).toHaveAttribute("aria-checked", "true");
  });

  test("filters by category from a link, composes with position and the ESPN ceiling, and exports the view", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${IN_SEASON}?view=opportunity&form=any`);
    const names = () => table(page).locator("tbody tr .player-name").allTextContents();
    await expect.poll(names).toEqual(["Zach Ertz"]);
    await expect(page.locator(".opp-filter-status")).toContainText("Any signal: 1");
    await page.goto(`${IN_SEASON}?view=opportunity&form=any&position=wr`);
    await expect(page.getByText("No players match.").first()).toBeVisible();
    await page.goto(`${IN_SEASON}?view=opportunity&form=any&last=2&espn=lt75`);
    await expect.poll(names).toContain("Rashee Kirk");
    for (const name of await names()) expect(["Rashee Kirk", "Zach Ertz"]).toContain(name);
    const lines = await readCsv(page);
    const header = (lines[0] ?? "").split(",");
    const at = (column: string) => header.indexOf(column);
    expect(lines).toHaveLength((await table(page).locator("tbody tr").count()) + 1);
    for (const line of lines.slice(1)) {
      const cells = line.split(",");
      expect(cells[at("recent_window")]).toBe("2");
      expect(["takeover", "sneaking", "eyebrow"]).toContain(cells[at("breakout_category")]);
    }
  });

  test("sorts the gap and the rank with blanks last, and the export follows the visible order", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const gapSort = table(page).getByRole("button", { name: /^Sort by recent rank versus season rank/ });
    await gapSort.click();
    await expect(table(page).locator('th[data-col="recent_rank"]')).toHaveAttribute("aria-sort", "descending");
    const shown = await table(page).locator("tbody tr").evaluateAll((rows) => rows.map((row) => row.getAttribute("data-player")));
    const gaps = await table(page)
      .locator('tbody td[data-col="recent_rank"] .signal-cell')
      .evaluateAll((cells) => cells.map((cell) => cell.querySelector(".signal-change")?.textContent ?? null));
    const numbers = gaps.filter((gap): gap is string => gap !== null).map((gap) => Number(gap.replace("−", "-").replace("+", "")));
    expect(numbers).toEqual([...numbers].sort((a, b) => b - a));
    const firstBlank = gaps.indexOf(null);
    if (firstBlank >= 0) expect(gaps.slice(firstBlank).every((gap) => gap === null)).toBe(true);
    expect(shown[0]).toBe("gsis:00-0000007");
    const lines = await readCsv(page);
    const ids = lines.slice(1).map((line) => line.split(",")[3]);
    const shownNames = await table(page).locator("tbody tr .player-name").allTextContents();
    expect(ids).toEqual(shownNames);
    await gapSort.click();
    await expect(table(page).locator('th[data-col="recent_rank"]')).toHaveAttribute("aria-sort", "ascending");
    const rankSort = table(page).getByRole("button", { name: /^Sort by recent rank in/ });
    await rankSort.click();
    await expect(table(page).locator('th[data-col="recent_rank"]')).toHaveAttribute("aria-sort", "ascending");
  });
});

test.describe("on a phone", () => {
  test.use({ hasTouch: true, isMobile: true });
  for (const [width, height] of [
    [320, 568],
    [390, 844],
  ] as const) {
    test(`keeps the name, the badge and its evidence usable at ${String(width)}px`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto(`${IN_SEASON}?view=opportunity`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
      const row = table(page).locator('tr[data-player="gsis:00-0000007"]');
      const badge = row.getByRole("button", { name: /^Takeover in W6–W8/ });
      await badge.scrollIntoViewIfNeeded();
      await expect(badge).toBeVisible();
      // The badge sits in the pinned name column, so it never scrolls away with the readings.
      await expect(row.locator("td.col-player")).toHaveCSS("position", "sticky");
      const box = await badge.boundingBox();
      expect(box).not.toBeNull();
      expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width);
      await badge.tap();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toContainText("TE15 season → TE3");
      const card = await dialog.locator(".lg-dialog-card").boundingBox();
      expect((card?.x ?? 0) + (card?.width ?? 0)).toBeLessThanOrEqual(width + 1);
      await dialog.getByRole("button", { name: "Close" }).tap();
      await expect(dialog).toBeHidden();
      // The folded options name the lens and its missing evidence.
      await expect(page.getByRole("button", { name: /^Options/ })).toHaveAccessibleName(/Last 3 W6–8 · \d+ without evidence/);
    });
  }
});

test.describe("an older build", () => {
  test("renders the existing board, disables the controls and names a link's filter", async ({ page }) => {
    await page.goto(`${NO_RECENT}?view=opportunity&form=takeover&last=6`);
    await expect(page.getByText("The breakout filter in this link cannot be applied here.")).toBeVisible();
    await expect(page.getByText(/Recent weeks: This build published no recent-form windows/)).toBeVisible();
    for (const radio of await lens(page).getByRole("radio").all()) {
      const name = (await radio.textContent()) ?? "";
      if (name !== "Season") await expect(radio).toBeDisabled();
    }
    await expect(table(page).locator("tbody tr").first()).toBeVisible();
    await expect(table(page).locator('th[data-col="recent_rank"]')).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Download full CSV · season only" })).toBeVisible();
  });
});

test("axe finds nothing with the evidence dialog open", async ({ page }) => {
  await page.goto(`${IN_SEASON}?view=opportunity`);
  await table(page).getByRole("button", { name: /^Takeover in W6–W8/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(" ")).join(", ")}`)).toEqual([]);
});
