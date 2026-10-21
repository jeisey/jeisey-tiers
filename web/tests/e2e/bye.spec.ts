/**
 * "Hide bye-week players" on the ROS and Start/Sit boards, in a real browser (ADR-115).
 *
 * The fixture's week 9 byes are SF (Deebo Gray) and PHI (Jalen Marsh), on both boards from the
 * same schedule. Direct links, reload, back/forward, the filtered export, a search that matches
 * only a hidden player, a Start/Sit comparison holding a bye player, the phone's folded row, and
 * an older build with no schedule.
 */

import { expect, test, type Page } from "@playwright/test";

import { stubPortraits } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const NO_SIGNALS = "/scenario/in-season-no-signals/";

test.beforeEach(async ({ page }) => {
  await stubPortraits(page);
});

function rosRows(page: Page) {
  return page.locator("#ros-table-heading").locator("xpath=ancestor::section").locator("table.sheet tbody tr");
}

function checkbox(page: Page) {
  return page.getByRole("checkbox", { name: /Hide week 9 byes|Hide bye-week players/ });
}

async function readCsv(page: Page): Promise<string[]> {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Export filtered CSV/ }).click();
  const stream = await (await download).createReadStream();
  const chunks: Uint8Array[] = [];
  for await (const chunk of stream) chunks.push(new Uint8Array(Buffer.from(chunk as Buffer)));
  return Buffer.concat(chunks).toString("utf-8").replace(/^\uFEFF/, "").trim().split("\r\n");
}

test.describe("the bye filter on the ROS board", () => {
  test("is off by default, hides the week's byes through the URL, and survives reload and back/forward", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${IN_SEASON}?view=ros`);
    await expect(checkbox(page)).not.toBeChecked();
    await expect(rosRows(page).filter({ hasText: "Puka Nightingale" })).toHaveCount(1);
    const before = await rosRows(page).count();
    await expect(rosRows(page).filter({ hasText: "Deebo Gray" })).toHaveCount(1);

    await checkbox(page).check();
    await expect(page).toHaveURL(/nobye=1/);
    await expect(rosRows(page).filter({ hasText: "Deebo Gray" })).toHaveCount(0);
    await expect(rosRows(page).filter({ hasText: "Jalen Marsh" })).toHaveCount(0);
    await expect(rosRows(page)).toHaveCount(before - 2);
    await expect(page.locator(".bye-note")).toContainText("2 week 9 bye players hidden.");
    // The ranks are the model's: nothing is renumbered.
    await expect(page.getByRole("status").filter({ hasText: /of \d+ rows/ })).toContainText(`${String(before - 2)} of`);

    const csv = await readCsv(page);
    expect(csv).toHaveLength(before - 2 + 1);
    expect(csv.join("\n")).not.toContain("Deebo Gray");

    await page.reload();
    await expect(checkbox(page)).toBeChecked();
    await expect(rosRows(page).filter({ hasText: "Deebo Gray" })).toHaveCount(0);

    await page.goBack();
    await expect(checkbox(page)).not.toBeChecked();
    await expect(rosRows(page).filter({ hasText: "Deebo Gray" })).toHaveCount(1);
    await page.goForward();
    await expect(checkbox(page)).toBeChecked();

    await page.getByRole("button", { name: "Show bye-week players" }).first().click();
    await expect(page).not.toHaveURL(/nobye/);
    await expect(rosRows(page)).toHaveCount(before);
  });

  test("a search does not override it; the board says why it is empty and how to clear it", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${IN_SEASON}?view=ros&search=Deebo&nobye=1`);
    await expect(page.locator(".bye-note")).toHaveCount(1);
    await expect(page.locator(".bye-note")).toContainText("“Deebo” matches only 1 week 9 bye player, hidden by the bye filter.");
    await expect(page.getByText("No players match.")).toHaveCount(0);
    await page.getByRole("button", { name: "Show bye-week players" }).click();
    await expect(rosRows(page).filter({ hasText: "Deebo Gray" })).toHaveCount(1);
  });

  test("an older build with no schedule disables it, says why, and hides nobody", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${NO_SIGNALS}?view=ros&nobye=1`);
    await expect(checkbox(page)).toBeDisabled();
    await expect(page.locator(".bye-filter-reason")).toHaveText("Unavailable: this build published no schedule");
    await expect(page.locator(".bye-note")).toContainText("Bye filter unavailable: this build published no schedule. Every player is shown.");
    await expect(rosRows(page).filter({ hasText: "Deebo Gray" })).toHaveCount(1);
  });

  test("it is named in the phone's folded settings row", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${IN_SEASON}?view=ros&nobye=1`);
    await expect(page.getByRole("button", { name: /^Settings/ })).toContainText("Byes hidden");
    await page.goto(`${IN_SEASON}?view=opportunity&nobye=1`);
    await expect(page.getByRole("button", { name: /^Settings/ })).not.toContainText("Byes hidden");
  });
});

test.describe("the bye filter on Start/Sit", () => {
  test("hides the week board's byes before paging and leaves the comparison whole", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    // Deebo Gray (bye) and Jahmyr Cook in the comparison.
    await page.goto(`${IN_SEASON}?view=startsit&duel=00-0000006.00-0000011`);
    const board = page.locator(".weekboard-table tbody tr");
    await expect(board.filter({ hasText: "Jahmyr Cook" })).toHaveCount(1);
    const before = await board.count();
    await expect(board.filter({ hasText: "Deebo Gray" })).toHaveCount(1);
    await checkbox(page).check();
    await expect(page).toHaveURL(/nobye=1/);
    await expect(board.filter({ hasText: "Deebo Gray" })).toHaveCount(0);
    await expect(board).toHaveCount(before - 2);
    await expect(page.locator(".bye-note")).toContainText("2 week 9 bye players hidden.");
    // The comparison is the reader's: he stays in it, with the existing bye explanation.
    await expect(page.locator(".deck")).toContainText("Deebo Gray");
    await expect(page.locator(".deck")).toContainText(/Bye/);
  });
});
