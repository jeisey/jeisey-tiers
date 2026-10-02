/**
 * End-to-end coverage of the Start/Sit tab (ADR-096), against the static in-season build.
 *
 * What a unit test cannot see and this suite can:
 *
 * 1. **The reader's loop through the URL.** Add from the week board, set a margin, remove from
 *    the deck — each a URL change that reloads to the same screen, because a start/sit call is
 *    something people paste into a league chat.
 * 2. **Layout at every width that matters.** The deck, the verdict and the distribution chart
 *    must fit a 320px phone without horizontal scroll and use a 1440px desktop without a
 *    stretched single column. Widths: 1440 desktop, 1024 small laptop, 820 tablet portrait,
 *    390 phone, 320 WCAG reflow.
 */

import { expect, test } from "@playwright/test";

import { guardBoundary } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const NO_WEEKLY = "/scenario/in-season-no-signals/";
const PAIR = "duel=00-0000011.00-0000012";
const FOUR = "duel=00-0000011.00-0000012.00-0000003.00-0000002";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

test.describe("the tab", () => {
  test("sits second, after the board it is read against", async ({ page }) => {
    await page.goto(IN_SEASON);
    const tabs = page.getByRole("tablist", { name: "Board" }).getByRole("tab");
    await expect(tabs.nth(0)).toHaveText(/ROS tiers/);
    await expect(tabs.nth(1)).toHaveText("Start/Sit");
    await tabs.nth(1).click();
    await expect(page).toHaveURL(/view=startsit/);
    await expect(page.getByRole("heading", { name: /Start\/Sit — week 9/ })).toBeVisible();
  });

  test("builds a comparison from the week board, and the URL carries it", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=startsit`);
    // No players: four open slots and no verdict at all.
    await expect(page.locator(".deck-card.deck-empty")).toHaveCount(4);
    await expect(page.locator(".verdict")).toHaveCount(0);
    await page.getByRole("button", { name: "Add Jahmyr Cook to the comparison" }).first().click();
    await expect(page.locator(".verdict-empty")).toHaveText("Add a second player to get a verdict.");
    await page.getByRole("button", { name: "Add Puka Nightingale to the comparison" }).first().click();
    await expect(page).toHaveURL(/duel=00-0000011\.00-0000012/);
    await expect(page.locator(".verdict-head")).toHaveText("Start Puka Nightingale");

    // A reload of the shared link is the same screen.
    await page.reload();
    await expect(page.locator(".verdict-head")).toHaveText("Start Puka Nightingale");
    await expect(page.getByLabel(/Slot A: Jahmyr Cook/)).toBeVisible();
    await expect(page.getByLabel(/Slot B: Puka Nightingale/)).toBeVisible();
  });

  test("moves the pick with the reader's margin", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=startsit&${PAIR}`);
    await expect(page.locator(".verdict-head")).toHaveText("Start Puka Nightingale");
    await expect(page.locator(".verdict")).toContainText("Jahmyr Cook outscores him");
    await page.getByRole("radio", { name: "Projected to win by 20 without this slot" }).click();
    await expect(page).toHaveURL(/margin=20/);
    await expect(page.locator(".verdict-head")).toHaveText("Start Jahmyr Cook");
    await expect(page.locator(".verdict-flip")).toContainText("you need his ceiling");
  });

  test("removes a player from the deck", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=startsit&${FOUR}`);
    await expect(page.locator(".deck-card:not(.deck-empty)")).toHaveCount(4);
    await expect(page.locator(".h2h")).toBeVisible();
    await page.getByRole("button", { name: "Remove Ja'Marr Swift from the comparison" }).first().click();
    await expect(page).toHaveURL(/duel=00-0000011\.00-0000012\.00-0000002(&|$)/);
    await expect(page.locator(".deck-card:not(.deck-empty)")).toHaveCount(3);
  });

  test("says which boards are unaffected when a build publishes no projections", async ({
    page,
  }) => {
    await page.goto(`${NO_WEEKLY}?view=startsit`);
    await expect(page.getByText("No weekly projections were published with this build.")).toBeVisible();
  });

  test("the player card carries this week's projection", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=startsit&${PAIR}`);
    await page.locator(".deck-name").first().click();
    const card = page.getByRole("dialog");
    await expect(card.getByRole("heading", { name: "This week" })).toBeVisible();
    // ADR-099: the card's block reads this week against a typical week, with the attribution
    // statement, and never puts points on context.
    await expect(card.locator(".why-week-head").first()).toContainText("typical week");
    await expect(card.getByText(/a model attribution, not a measured cause/)).toBeVisible();
  });

  test("explains the pick's week at the median and the ceiling, in words", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=startsit&${PAIR}`);
    const open = page.locator(".why-this-week-player[open]");
    await expect(open).toHaveCount(1);
    await expect(open.locator(".why-this-week-gist")).toContainText(/Median [+−±]\d\.\d · ceiling [+−±]\d\.\d vs typical/);
    await expect(open.locator(".why-week-table th[scope=col]").nth(2)).toHaveText("Ceiling");
    // Context chips carry words, never a signed point value. The pick plays in London, so its
    // forecast is Open-Meteo's and carries the licence credit.
    const chips = await open.locator(".why-week-context li .why-week-context-text").allTextContents();
    expect(chips.length).toBeGreaterThan(0);
    expect(chips.join(" ")).toMatch(/Forecast: \d+ mph wind/);
    await expect(open.locator(".why-week-attribution")).toHaveText("Weather data by Open-Meteo.com (CC BY 4.0)");
    // The lines reason names the team's typical implied total from the published context.
    await expect(open.locator(".why-week-table")).toContainText(/\(usually \d+\.\d\)/);
    for (const text of chips) {
      expect(text).not.toMatch(/\([+−-]\d+\.\d\)/);
    }
  });

  test("the week board says how each median compares with a typical week", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=startsit`);
    const cells = page.locator(".weekboard-table .wb-why-cell");
    await expect(cells.first()).toBeVisible();
    const label = await cells.first().getAttribute("title");
    await expect(cells.first().locator(".visually-hidden")).toHaveText(label ?? "");
    expect(label ?? "").toMatch(/^[+−±]\d\.\d median against a typical week/);
  });
});

test.describe("layout", () => {
  for (const [width, height] of [
    [1440, 900],
    [1024, 768],
    [820, 1180],
    [390, 844],
    [320, 800],
  ] as const) {
    test(`fits ${String(width)}px without horizontal scroll, four players deep`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto(`${IN_SEASON}?view=startsit&${FOUR}`);
      await expect(page.locator(".verdict-head")).toBeVisible();
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `start/sit overflows at ${String(width)}px`).toBeLessThanOrEqual(1);

      // Nothing inside the section is clipped sideways either: every card, the verdict and the
      // chart sit inside the section's own box.
      const section = await page.locator("section.startsit").boundingBox();
      for (const selector of [
        ".deck-card",
        ".verdict",
        ".startsit-figure svg",
        ".why-this-week",
        ".why-week-heads",
        ".why-week-table",
        ".why-week-context li",
      ]) {
        const boxes = await page.locator(selector).evaluateAll((nodes) =>
          nodes.map((node) => {
            const rect = node.getBoundingClientRect();
            return { left: rect.left, right: rect.right };
          }),
        );
        for (const box of boxes) {
          expect(box.left, `${selector} starts left of the section`).toBeGreaterThanOrEqual((section?.x ?? 0) - 1);
          expect(box.right, `${selector} ends right of the section`).toBeLessThanOrEqual(
            (section?.x ?? 0) + (section?.width ?? 0) + 1,
          );
        }
      }
    });
  }

  test("uses the width on a desktop: the deck is one row of four", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${IN_SEASON}?view=startsit&${FOUR}`);
    // The view is lazy-loaded: wait for the cards before measuring them.
    await expect(page.locator(".deck-card:not(.deck-empty)")).toHaveCount(4);
    const tops = await page
      .locator(".deck-card:not(.deck-empty)")
      .evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);
  });

  test("stacks on a phone: two cards a row, never one squeezed row of four", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${IN_SEASON}?view=startsit&${FOUR}`);
    await expect(page.locator(".deck-card:not(.deck-empty)")).toHaveCount(4);
    const tops = await page
      .locator(".deck-card:not(.deck-empty)")
      .evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBeGreaterThanOrEqual(2);
  });

  test("on a phone, a chosen pair puts the verdict on the first screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${IN_SEASON}?view=startsit&${PAIR}`);
    await expect(page.locator(".verdict-head")).toBeVisible();
    // The empty slots step aside on a phone once there is a verdict to read.
    await expect(page.locator(".deck-card.deck-empty").first()).toBeHidden();
    const box = await page.locator(".verdict-head").boundingBox();
    expect(box?.y ?? Infinity).toBeLessThan(844);
    // No range is clipped inside a half-width card.
    const clipped = await page
      .locator(".deck-range dd")
      .evaluateAll((nodes) => nodes.filter((node) => node.scrollWidth > node.clientWidth + 1).length);
    expect(clipped).toBe(0);
  });

  // Six tabs since ADR-100: one row from 360px ("Opportunity" prints as "Opp" below 560px),
  // a sideways scroll below that with the active tab revealed, and never a wrapped label.
  test("the six in-season tabs fit one row from 360px, each on one line", async ({ page }) => {
    for (const width of [320, 360, 390, 480, 768]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(`${IN_SEASON}?view=startsit`);
      const tabs = page.getByRole("tablist", { name: "Board" });
      await expect(tabs.getByRole("tab")).toHaveCount(6);
      const fit = await tabs.evaluate((node) => node.scrollWidth - node.clientWidth);
      if (width >= 360) expect(fit, `the tabs scroll at ${String(width)}px`).toBeLessThanOrEqual(1);
      await expect(tabs.getByRole("tab", { name: "Start/Sit" })).toBeInViewport({ ratio: 1 });
      const heights = await tabs
        .getByRole("tab")
        .evaluateAll((nodes) => [...new Set(nodes.map((node) => Math.round(node.getBoundingClientRect().height)))]);
      expect(heights, `a tab label wraps at ${String(width)}px`).toHaveLength(1);
    }
  });

  test("honours reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(`${IN_SEASON}?view=startsit&${PAIR}`);
    // Wait for the lazy view, or this would pass vacuously over no elements.
    await expect(page.locator(".shield-cells").first()).toBeVisible();
    const durations = await page
      .locator(".shield-cells, .startsit-figure svg *")
      .evaluateAll((nodes) =>
        nodes.map((node) => Number.parseFloat(getComputedStyle(node).transitionDuration) || 0),
      );
    expect(Math.max(0, ...durations)).toBeLessThanOrEqual(0.01);
  });
});
