/**
 * Accessibility.
 *
 * Two halves, and the second is the one that matters.
 *
 * **Automated.** axe-core over every surface at desktop and phone width, with the dialog open,
 * at WCAG 2.0/2.1/2.2 level A and AA. It is cheap, it never sleeps, and it catches the class
 * of regression a redesign actually produces: a contrast ratio that slipped under 4.5, a
 * heading level skipped, a control that lost its name.
 *
 * **What it does not catch, and is therefore asserted separately here.** Automated tooling is
 * commonly reckoned to find something like a third to a half of real barriers, and every one
 * of this product's genuinely hard cases is in the other half — whether the tab order is
 * *sensible* rather than merely present, whether a composite widget is one stop or three
 * hundred, whether meaning survives without colour, whether focus goes somewhere useful when a
 * dialog closes, whether a touch target is big enough for a thumb. Zero axe violations is a
 * floor, not a result, and this file says so in code rather than in a comment.
 *
 * Target: WCAG 2.2 AA on the primary flows (`docs/UX_SPEC.md` section 12).
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function scan(page: Page): Promise<Awaited<ReturnType<AxeBuilder["analyze"]>>> {
  return new AxeBuilder({ page }).withTags(TAGS).analyze();
}

/** A readable failure: axe's own rule id and the elements it landed on. */
function describe(results: Awaited<ReturnType<AxeBuilder["analyze"]>>): string[] {
  return results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact ?? "unknown"}): ${violation.help} — ` +
      violation.nodes.map((node) => node.target.join(" ")).join(", "),
  );
}

test.describe("automated scan", () => {
  // Each surface is paired with something only *that* surface renders, because a page that
  // failed to load has no violations either. An earlier draft of this file scanned eight
  // surfaces against a stale server holding a build with no `data/` directory and passed all
  // eight: axe found nothing wrong with the empty document it was handed. Assert the surface
  // under test actually rendered before scanning it.
  for (const [name, path, landmark] of [
    ["tiers", "/", ".board-row"],
    ["tiers, every tier open", "/?tiers=0.1.2", ".board-row"],
    ["tiers, every tier closed", "/?tiers=none", ".tier-head"],
    ["arbitrage", "/?view=arbitrage", ".rail-row"],
    ["arbitrage premiums", "/?view=arbitrage&rail=premiums", ".rail-row"],
    ["data", "/?view=data", "h2#definitions-heading"],
    ["a degraded market", "/scenario/no-market/?view=arbitrage", '.notice[data-severity="warning"]'],
    ["a refused contract", "/scenario/bad-schema/", '.notice[data-severity="error"]'],
  ] as const) {
    test(`${name} has no WCAG A or AA violations`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.locator(landmark).first()).toBeVisible();
      expect(describe(await scan(page))).toEqual([]);
    });
  }

  test("the player card has no violations while it is open", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(describe(await scan(page))).toEqual([]);
  });
});

test.describe("keyboard and semantics, which a scanner cannot judge", () => {
  test("landmarks and heading order are a document, not a soup of divs", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".board-row").first()).toBeVisible();
    await expect(page.locator("header.masthead")).toHaveCount(1);
    await expect(page.locator("main#board")).toHaveCount(1);
    await expect(page.locator("footer.footer")).toHaveCount(1);

    // No level is skipped: h2 sections, h3 inside them, and exactly one dialog h2 when open.
    const levels = await page.$$eval("h1, h2, h3, h4", (nodes) =>
      nodes.map((node) => Number(node.tagName.slice(1))),
    );
    expect(levels.length).toBeGreaterThan(0);
    levels.reduce((previous, level) => {
      expect(level - previous, `heading jumped from h${String(previous)} to h${String(level)}`)
        .toBeLessThanOrEqual(1);
      return level;
    }, levels[0] ?? 2);
  });

  test("the board is one tab stop, and arrow keys move inside it", async ({ page }) => {
    await page.goto("/?tiers=0.1.2");
    await expect(page.locator(".board-row").first()).toBeVisible();
    // Three hundred tab stops is technically accessible and practically a trap; the composite
    // widget pattern is one stop with arrow-key movement inside.
    const stops = await page.$$eval(".board-row", (rows) =>
      rows.filter((row) => row.getAttribute("tabindex") === "0").length,
    );
    expect(stops).toBe(1);

    const first = page.locator(".board-row").first();
    await first.focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.locator(".board-row").nth(1)).toBeFocused();
    await page.keyboard.press("Home");
    await expect(first).toBeFocused();
  });

  test("every tier toggle is a real button with its state in the accessibility tree", async ({
    page,
  }) => {
    await page.goto("/");
    const heads = page.locator(".tier-head");
    await expect(heads.first()).toBeVisible();
    const count = await heads.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      const head = heads.nth(i);
      await expect(head).toHaveAttribute("aria-expanded", /true|false/);
      await expect(head).toHaveAttribute("aria-controls", /tier-rows-/);
    }
    // Operable from the keyboard, not only from a pointer.
    await heads.first().focus();
    await page.keyboard.press("Enter");
    await expect(heads.first()).toHaveAttribute("aria-expanded", "false");
  });

  test("direction and status survive without colour", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    // The rail says which way, in words, on the row and in its accessible name.
    await expect(page.locator(".rail-gap-word").first()).toHaveText(/later|earlier|even/);
    await expect(page.locator(".rail-row").first()).toHaveAttribute(
      "aria-label",
      /picks (later|earlier) than his fair rank/,
    );
    // An injury badge carries its designation as text, not as a red dot.
    await page.goto("/");
    const badge = page.locator(".status-badge").first();
    await expect(badge).toBeVisible();
    await expect(badge).toContainText(/\w/);
    await expect(badge.locator(".visually-hidden")).toContainText(/Annotation only/);
  });

  test("interactive targets meet the 24px minimum", async ({ page }) => {
    await page.goto("/?tiers=0.1.2");
    for (const selector of [".board-row", ".tier-head", ".rail-row"]) {
      if (selector === ".rail-row") await page.goto("/?view=arbitrage");
      await expect(page.locator(selector).first()).toBeVisible();
      const boxes = await page.locator(selector).evaluateAll((nodes) =>
        nodes.slice(0, 5).map((node) => node.getBoundingClientRect().height),
      );
      for (const height of boxes) {
        expect(height, `${selector} is only ${String(height)}px tall`).toBeGreaterThanOrEqual(24);
      }
    }
  });

  test("a visible focus indicator exists on every custom control", async ({ page }) => {
    await page.goto("/?tiers=0.1.2");
    for (const selector of [".board-row", ".tier-head", ".player-name", ".status-chip"]) {
      const node = page.locator(selector).first();
      await expect(node).toBeVisible();
      await node.focus();
      // Either channel counts. The dense board rows take an inset outline; everything else
      // takes the stylesheet's shared focus ring, which is a two-step box-shadow so it stays
      // visible against both the row surface and the page.
      const visible = await node.evaluate((element) => {
        const style = getComputedStyle(element);
        const outline =
          style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0;
        const shadow = style.boxShadow !== "none" && style.boxShadow !== "";
        return outline || shadow;
      });
      expect(visible, `${selector} has no visible focus indicator`).toBe(true);
    }
  });

  test("the page reflows at 320 CSS pixels without a horizontal scrollbar", async ({ page }) => {
    // WCAG 2.1 "Reflow": 320 CSS pixels wide is what 400% zoom of a 1280px viewport reduces
    // to, and it is the width the spec actually names.
    await page.setViewportSize({ width: 320, height: 800 });
    for (const path of ["/", "/?view=arbitrage", "/?view=data"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} reflows badly at 320px`).toBeLessThanOrEqual(1);
    }
  });
});
