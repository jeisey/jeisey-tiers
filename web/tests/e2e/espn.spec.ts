/**
 * ESPN roster and start percentages in the built site (ADR-112): the Opportunity Board's column,
 * ceiling, URL state, discovery rule and export; a build without ESPN and a stale one; and the
 * card's reading with its history fetched only on activation.
 */

import { expect, test } from "@playwright/test";

import { guardBoundary } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const NO_ESPN = "/scenario/in-season-no-espn/";
const STALE = "/scenario/in-season-espn-stale/";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

test.describe("the ESPN roster ceiling", () => {
  test("filters strictly below the chosen share, round-trips the URL and composes with role", async ({
    page,
  }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const rows = page.locator("table.sheet.opp-sheet tbody tr");
    await expect(rows).toHaveCount(19);
    const all = await rows.count();
    const ceiling = page.getByRole("radiogroup", { name: "ESPN rostered" });
    await ceiling.getByRole("radio", { name: /strictly fewer than 10%/ }).click();
    await expect(page).toHaveURL(/espn=lt10/);
    await expect(rows.first()).toBeVisible();
    await expect(page.locator(".opp-filter-status")).toContainText("Rostered below 10% on ESPN");
    const names = await page.locator("table.sheet.opp-sheet tbody .player-name").allTextContents();
    expect(names).toContain("James Cook III"); // 9.99%
    expect(names).not.toContain("Zay Meadows"); // exactly 10%
    expect(names.length).toBeLessThan(all);
    await expect(page.locator(".opp-filter-status")).toContainText(/Rostered below 10% on ESPN: \d+ · \d+ with no current ESPN reading/);
    await page.reload();
    await expect(page.getByRole("radiogroup", { name: "ESPN rostered" }).getByRole("radio", { checked: true })).toHaveText("<10%");

    await page.goto(`${IN_SEASON}?view=opportunity&only=role&espn=lt50`);
    await expect(page.locator(".opp-discovery")).toContainText("Role rising + rostered below 50% on ESPN");
    await expect(page.locator(".opp-discovery-conditions li")).toHaveCount(2);
    await expect(rows.filter({ hasText: "Jalen Marsh" })).toHaveCount(1);
  });

  test("orders by ESPN share with every row without a current reading last", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&opportunity=espn`);
    await expect(page.locator("table.sheet.opp-sheet tbody tr")).toHaveCount(19);
    const kinds = await page
      .locator('table.sheet.opp-sheet tbody td[data-col="espn"] .signal-cell')
      .evaluateAll((cells) => cells.map((cell) => cell.getAttribute("data-kind")));
    const firstMissing = kinds.findIndex((kind) => kind !== "observed");
    expect(firstMissing).toBeGreaterThan(0);
    expect(kinds.slice(firstMissing).every((kind) => kind !== "observed")).toBe(true);
  });

  test("exports the ESPN columns with the rows on screen", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&espn=lt25`);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /Export filtered CSV/ }).click();
    const stream = await (await download).createReadStream();
    const chunks: Uint8Array[] = [];
    for await (const chunk of stream) chunks.push(new Uint8Array(Buffer.from(chunk as Buffer)));
    const lines = Buffer.concat(chunks).toString("utf-8").replace(/^\uFEFF/, "").trim().split("\r\n");
    const header = (lines[0] ?? "").split(",");
    // ESPN's twelve columns, then ADR-113's fourteen recent-window columns.
    expect(header.slice(-26)[0]).toBe("espn_reading");
    expect(header).toContain("espn_rostered_change_7d_pp");
    expect(lines).toHaveLength((await page.locator("table.sheet.opp-sheet tbody tr").count()) + 1);
  });

  test("an older build disables the ceiling, says why and keeps the board whole", async ({ page }) => {
    await page.goto(`${NO_ESPN}?view=opportunity&espn=lt25`);
    await expect(page.getByText("The ESPN filter in this link cannot be applied to this build.")).toBeVisible();
    await expect(page.locator("table.sheet.opp-sheet tbody tr")).toHaveCount(19);
    await expect(page.getByRole("radiogroup", { name: "ESPN rostered" }).getByRole("radio", { name: /fewer than 25%/ })).toBeDisabled();
    await expect(
      page.locator('table.sheet.opp-sheet tbody td[data-col="espn"] .signal-cell').first(),
    ).toHaveAttribute("data-kind", "unavailable");
  });

  test("a stale build prints its values muted and applies no ceiling", async ({ page }) => {
    await page.goto(`${STALE}?view=opportunity&espn=lt50`);
    await expect(page.getByText("The ESPN filter in this link cannot be applied to this build.")).toBeVisible();
    await expect(page.locator("table.sheet.opp-sheet tbody tr")).toHaveCount(19);
    await expect(
      page.locator('table.sheet.opp-sheet tbody td[data-col="espn"] .signal-cell[data-kind="stale"]').first(),
    ).toHaveAttribute("data-current", "false");
  });
});

test.describe("the card's ESPN reading", () => {
  test("states the change at once and fetches the history only when asked", async ({ page }) => {
    const history: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("espn_ownership_series")) history.push(request.url());
    });
    await page.goto(`${IN_SEASON}?view=opportunity`);
    expect(history).toEqual([]);
    await page.getByRole("button", { name: "Jahmyr Cook", exact: true }).first().click();
    const card = page.getByRole("dialog");
    await expect(card.getByText("Rostered on ESPN: 18% → 31% in 7 days (+13 percentage points).")).toBeVisible();
    expect(history).toEqual([]);
    await card.getByRole("button", { name: "Show ESPN trend" }).click();
    const chart = card.getByTestId("espn-ownership-chart");
    await expect(chart).toBeVisible();
    expect(history).toHaveLength(1);
    // Two panels with labelled percent scales, a week rule, a gap-free riser, exact readings.
    await expect(chart.locator(".espn-panel")).toHaveCount(2);
    await expect(chart.locator(".espn-ticks").first()).toContainText("%");
    await expect(chart.locator(".espn-period-label")).toHaveText(["P9"]);
    await chart.locator("circle.espn-point").first().focus();
    await expect(chart.locator(".espn-reading")).toContainText(/rostered \d/);
    // Hide, show, close and reopen: nothing is fetched twice.
    await card.getByRole("button", { name: "Hide ESPN trend" }).click();
    await card.getByRole("button", { name: "Show ESPN trend" }).click();
    await expect(chart).toBeVisible();
    expect(history).toHaveLength(1);
  });

  test("draws a gap as a gap for a player ESPN missed on some reads", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    await page.getByRole("button", { name: "Zay Meadows", exact: true }).first().click();
    const card = page.getByRole("dialog");
    await card.getByRole("button", { name: "Show ESPN trend" }).click();
    const chart = card.getByTestId("espn-ownership-chart");
    await expect(chart).toBeVisible();
    await expect(chart.locator(".espn-gap").first()).toBeAttached();
    await expect(chart.locator(".espn-reading")).toContainText(/gap/);
  });

  for (const width of [320, 390, 768, 1024, 1440]) {
    test(`fits the card and the board without page overflow at ${String(width)}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width < 500 ? 740 : 900 });
      await page.goto(`${IN_SEASON}?view=opportunity&only=role&espn=lt50`);
      await expect(page.locator(".opp-discovery")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
      await page.getByRole("button", { name: "Jalen Marsh", exact: true }).first().click();
      const card = page.getByRole("dialog");
      if (width < 768) await card.getByRole("tab", { name: "In-season usage" }).click();
      else await card.getByRole("button", { name: "Show ESPN trend" }).click();
      await expect(card.getByTestId("espn-ownership-chart")).toBeVisible();
      const chartOverflow = await card
        .getByTestId("espn-ownership-chart")
        .evaluate((node) => node.scrollWidth - node.clientWidth);
      expect(chartOverflow).toBeLessThanOrEqual(1);
    });
  }
});
