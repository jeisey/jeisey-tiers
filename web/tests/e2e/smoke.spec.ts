/**
 * Cross-browser smoke.
 *
 * Phase 6 chose Chromium as the primary end-to-end engine and left the other two unmeasured.
 * That was a defensible cost decision then and it is not one now: the Phase-8 redesign moved
 * the Tier Board and the Draft Rail off SVG onto CSS grid, `color-mix()`, container-relative
 * percentage geometry and a `<dialog>` presented two different ways. Every one of those has a
 * different history in Gecko and WebKit than in Blink, and WebKit shipped `<dialog>` and
 * `::backdrop` most recently of the three.
 *
 * This file is deliberately **not** the full suite run three times. Tripling twenty-odd
 * behavioural specs would triple the slowest gate in the repository to re-prove logic that is
 * engine-independent — sorting a table and parsing a query string do not vary by browser. What
 * varies is layout, focus, dialog semantics, downloads and the primary flows that string them
 * together, so that is what runs everywhere.
 *
 * `docs/TEST_STRATEGY.md` section 8.2 records the split.
 */

import { expect, test, type Page } from "@playwright/test";

/** The board is ready when the tier table has rendered its rows from the artifact. */
async function ready(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
  await expect(
    page.getByRole("table", { name: /Intrinsic tier board/ }).getByRole("row").nth(1),
  ).toContainText("Bijan Robinson");
}

test.describe("primary flows", () => {
  test("loads the board and renders the artifact's own values", async ({ page }) => {
    await page.goto("/");
    await ready(page);
    // A value that only exists in the artifact, so a blank board cannot pass.
    await expect(page.getByRole("table", { name: /Intrinsic tier board/ })).toContainText("135.4");
    await expect(page.locator(".board-row").first()).toContainText("Bijan Robinson");
  });

  test("the page never scrolls sideways", async ({ page }) => {
    for (const path of ["/", "/?view=arbitrage", "/?view=data"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} overflows horizontally`).toBeLessThanOrEqual(1);
    }
  });

  test("tier collapse survives a reload through the URL", async ({ page }) => {
    await page.goto("/");
    await ready(page);
    const open = await page.locator(".board-row").count();
    await page.locator(".tier-head").first().click();
    await expect(page).toHaveURL(/tiers=/);
    expect(await page.locator(".board-row").count()).toBeLessThan(open);
    await page.reload();
    await expect(page.locator(".tier-head").first()).toHaveAttribute("aria-expanded", "false");
  });

  test("controls filter the board and write themselves into the URL", async ({ page }) => {
    await page.goto("/");
    await ready(page);
    await page.getByRole("radio", { name: "RB" }).click();
    await expect(page).toHaveURL(/position=rb/);
    const positions = await page.locator(".board-row .row-pos").allTextContents();
    expect(positions.length).toBeGreaterThan(0);
    expect(positions.every((text) => text.startsWith("RB"))).toBe(true);
  });

  test("search narrows the table", async ({ page }) => {
    await page.goto("/");
    await ready(page);
    await page.getByLabel("Player search").fill("burrow");
    await expect(page).toHaveURL(/search=burrow/);
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    await expect(table.getByRole("row")).toHaveCount(2);
    await expect(table).toContainText("Joe Burrow");
  });

  test("the arbitrage view renders the rail and the table", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    await expect(page.getByRole("heading", { name: "Draft rail" })).toBeVisible();
    expect(await page.locator(".rail-fill").count()).toBeGreaterThan(0);
    await expect(page.getByRole("table", { name: /market-gap board/i })).toBeVisible();
    // Direction is a word, not only a colour or a side.
    await expect(page.locator(".rail-gap-word").first()).toHaveText(/later|earlier|even/);
  });

  test("the data view reports the build it loaded", async ({ page }) => {
    await page.goto("/?view=data");
    await expect(page.getByRole("heading", { name: "Current build" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "fixture-20260821T120000Z" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Current limitations" })).toBeVisible();
  });
});

/**
 * The dialog, which is where the engines differ most.
 *
 * `showModal()`, focus trapping, `::backdrop`, Escape-to-close and focus restoration are five
 * separate pieces of the same feature, and WebKit was the last of the three to ship it.
 */
test.describe("the player card", () => {
  test("opens, traps focus, closes on Escape and restores focus", async ({ page }) => {
    await page.goto("/");
    await ready(page);
    const trigger = page.getByRole("button", { name: "Amon-Ra Bright", exact: true });
    await trigger.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Amon-Ra Bright" })).toBeVisible();
    await expect(dialog.getByText("Fair rank", { exact: true })).toBeVisible();

    // Tab may never reach an element of the page behind the dialog. It *may* leave the
    // document entirely — every engine hands focus to its own browser chrome at the end of a
    // modal's tab ring, and `document.activeElement` is then `<body>` — so the assertion is
    // about the page, not about the ring.
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press("Tab");
      const where = await page.evaluate(() => {
        const open = document.querySelector("dialog[open]");
        const active = document.activeElement;
        if (open === null) return "no dialog";
        if (active === null || active === document.body) return "browser chrome";
        return open.contains(active) ? "inside" : `escaped to ${active.tagName}.${active.className}`;
      });
      expect(where, `after ${String(i + 1)} tabs`).toMatch(/^(inside|browser chrome)$/);
    }

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("opens from a board row with the keyboard", async ({ page }) => {
    await page.goto("/");
    await ready(page);
    await page.getByRole("button", { name: /^Bijan Robinson,.*median simulated VORP/ }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog").getByRole("heading", { name: "Bijan Robinson" })).toBeVisible();
  });

  /**
   * The three design variants, on three engines.
   *
   * The card is one DOM whose *shape* changes with the viewport — a two-pane rail on a desktop,
   * a header band on a tablet, a tab bar on a phone (`docs/DESIGN_SOURCE_MAP.md` section 4).
   * Layout is the part that varies most between engines, and the tab bar is a genuine
   * accessibility-tree difference rather than a rearrangement, so both are worth three runs.
   */
  test("takes its three design variants from the viewport", async ({ page }) => {
    await page.goto("/");
    await ready(page);
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // Desktop, artboard 1c: the identity rail is a column beside the detail pane.
    await page.setViewportSize({ width: 1440, height: 950 });
    const side = await dialog.evaluate((node) => {
      const rail = node.querySelector(".detail-rail")?.getBoundingClientRect();
      const main = node.querySelector(".detail-main")?.getBoundingClientRect();
      return rail && main ? { beside: rail.right <= main.left + 1 } : null;
    });
    expect(side?.beside, "the rail should sit beside the detail pane on a desktop").toBe(true);
    await expect(dialog.getByRole("tablist")).toHaveCount(0);

    // Tablet, artboard 1a: the rail becomes a band above it, and the sections still stack.
    await page.setViewportSize({ width: 900, height: 950 });
    const stacked = await dialog.evaluate((node) => {
      const rail = node.querySelector(".detail-rail")?.getBoundingClientRect();
      const main = node.querySelector(".detail-main")?.getBoundingClientRect();
      return rail && main ? { above: rail.bottom <= main.top + 1 } : null;
    });
    expect(stacked?.above, "the rail should sit above the detail pane on a tablet").toBe(true);
    await expect(dialog.getByRole("tablist")).toHaveCount(0);

    // Phone, artboard 1b: three tabs, one panel.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(dialog.getByRole("tablist")).toBeVisible();
    await expect(dialog.getByRole("tab")).toHaveCount(3);
    await expect(dialog.getByRole("tabpanel")).toHaveCount(1);
    await dialog.getByRole("tab", { name: "Draft market" }).click();
    // Labelled with whichever market the page is showing, so it is matched by shape.
    // Pinning one source's name here is what let the card sit on MyFantasyLeague while
    // the table showed FFC, with every test still green (ADR-067).
    await expect(dialog.locator(".readout-label").filter({ hasText: / ADP$/ })).toBeVisible();
  });
});

test("exports the filtered rows as CSV", async ({ page }) => {
  await page.goto("/?position=te");
  await expect(page.getByRole("heading", { name: "Tier table" })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Export filtered CSV/ }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("ffdraft-tiers-ppr-12-2026-08-21.csv");
});

test("serves correctly from the project Pages base path", async ({ page }) => {
  await page.goto("/jeisey-tiers/?view=arbitrage");
  await expect(page.getByRole("heading", { name: "Draft rail" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download full CSV" })).toHaveAttribute(
    "href",
    "/jeisey-tiers/data/arbitrage.csv",
  );
});

/**
 * Reduced motion.
 *
 * There is no animation to disable, which is the point: the assertion is that no engine
 * introduces one through a transition on a control, and that the preference is honoured
 * rather than merely unneeded.
 */
test.describe("reduced motion", () => {
  test("nothing animates when the viewer asks for less motion", async ({ page }) => {
    // Emulated on the page rather than declared with `test.use`, so the assertion is about
    // this navigation and reads in one place.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await ready(page);
    // Reported as element descriptions rather than a count, so a failure says *what* moved.
    const moving = await page.evaluate(() => {
      const duration = (value: string): number =>
        Math.max(
          0,
          ...value.split(",").map((part) => {
            const seconds = Number.parseFloat(part);
            if (!Number.isFinite(seconds)) return 0;
            return /\dms/.test(part.trim()) ? seconds / 1000 : seconds;
          }),
        );
      return [...document.querySelectorAll("*")]
        .filter((node) => {
          const style = getComputedStyle(node);
          return (
            duration(style.animationDuration) > 0.05 || duration(style.transitionDuration) > 0.05
          );
        })
        .map((node) => `${node.tagName}.${node.className}`);
    });
    expect(moving).toEqual([]);
  });
});
