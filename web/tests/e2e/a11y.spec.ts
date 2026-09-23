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

import { stubPortraits } from "./boundary";

/*
 * No test in this repository reaches a third party. The player card fetches its portrait from
 * one declared host; this serves it locally instead, so the suite neither depends on a
 * provider's uptime nor makes a request on a reader's behalf every time CI runs (ADR-087).
 */
test.beforeEach(async ({ page }) => {
  await stubPortraits(page);
});


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
    // The in-season product, on its own builds. Both boards are charts this suite had never
    // seen: the rest-of-season board did not exist before ADR-085 and the opportunity board
    // was a bare table, so neither had ever been scanned.
    ["the rest-of-season board", "/scenario/in-season/?view=ros", ".board-row"],
    ["the rest-of-season board, disclosure open", "/scenario/in-season/?view=ros", ".board-row"],
    ["the opportunity board", "/scenario/in-season/?view=opportunity", ".opp-row"],
    [
      "the opportunity board with no behaviour feed",
      "/scenario/in-season-no-behavior/?view=opportunity",
      ".opp-track-empty",
    ],
    // ADR-092: three toggle chips, two new orderings and three signal columns, including the
    // state where a shared link names a filter the build cannot apply.
    [
      "the opportunity board, filtered and ordered by role",
      "/scenario/in-season/?view=opportunity&only=role.momentum&opportunity=role",
      ".opp-filters",
    ],
    [
      "the opportunity board, a filter the build cannot apply",
      "/scenario/in-season-no-signals/?view=opportunity&only=role",
      ".notice",
    ],
    // Pick of the Week (ADR-088). A different construction again — cards rather than rows,
    // four portraits, and a set switcher — so neither board's scan says anything about it.
    ["pick of the week", "/scenario/in-season/?view=potw", ".potw-card"],
    ["pick of the week, one position", "/scenario/in-season/?view=potw&position=rb", ".potw-card"],
    [
      "pick of the week with no behaviour feed",
      "/scenario/in-season-no-behavior/?view=potw",
      ".notice",
    ],
    // A set deep enough that a position has run out of candidates. The absence list is its own
    // DOM and it is the state a quiet week actually produces.
    ["pick of the week, a position with no pick", "/scenario/in-season/?view=potw&set=2", ".potw-absence"],
  ] as const) {
    test(`${name} has no WCAG A or AA violations`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.locator(landmark).first()).toBeVisible();
      // A collapsed `details` hides its contents from axe as well as from the reader, so the
      // disclosure is scanned open too — the sentences inside it are a contract (ADR-076) and
      // an unreachable contract is not met.
      if (name.endsWith("disclosure open")) {
        await page.locator("details.disclosure summary").click();
        await expect(page.getByText(/Ranking quality inside this group is weak/i)).toBeVisible();
      }
      expect(describe(await scan(page))).toEqual([]);
    });
  }

  /*
   * The phone's folded controls (ADR-093). A different DOM state from every scan above, which
   * run at desktop width where the summary rows are not rendered: here they are the only
   * controls on screen when folded, and the whole control strip is inside a scroll box when
   * open. Both states are scanned, on the draft board and on the board with two folds.
   */
  for (const [name, path, landmark] of [
    ["the tier board", "/", ".board-row"],
    ["the opportunity board", "/scenario/in-season/?view=opportunity&only=role", ".opp-row"],
  ] as const) {
    test(`${name} on a phone scans clean folded and open`, async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.locator(landmark).first()).toBeVisible();
      const settings = page.getByRole("button", { name: /^Settings/ });
      await expect(settings).toBeVisible();
      expect(describe(await scan(page)), "folded").toEqual([]);

      await settings.click();
      const options = page.getByRole("button", { name: /^Options/ });
      if ((await options.count()) > 0) await options.click();
      await expect(page.getByRole("radiogroup", { name: "Scoring" })).toBeVisible();
      expect(describe(await scan(page)), "open").toEqual([]);
    });
  }

  test("the player card has no violations while it is open", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(describe(await scan(page))).toEqual([]);
  });

  test("the in-season player card has no violations either", async ({ page }) => {
    // A different set of sections and a different rail (ADR-085), so scanning the draft card
    // says nothing about this one.
    await page.goto("/scenario/in-season/?view=ros");
    await page.locator("table.sheet .player-name").first().click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();
    await expect(card.getByRole("heading", { name: "In-season usage" })).toBeVisible();
    // The three micro-charts are on this card (ADR-086); the scan covers them here.
    await expect(card.locator(".shift-track")).toHaveCount(1);
    await expect(card.locator(".pace")).toHaveCount(1);
    await expect(card.locator(".cohort")).toHaveCount(2);
    expect(describe(await scan(page))).toEqual([]);
  });

  test("the in-season card scans clean for a player with no rank move to draw", async ({
    page,
  }) => {
    // A different DOM, not a different style: the rail is replaced by a sentence and two of
    // its three readouts are em dashes. A scan of the card that *has* a move says nothing
    // about the card that does not, which is the same reasoning as the test above it.
    await page.goto("/scenario/in-season/?view=ros");
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).first().click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();
    await expect(card.locator(".shift-track")).toHaveCount(0);
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

  test("the opportunity board's rows are one tab stop with a visible focus ring", async ({
    page,
  }) => {
    // The same composite-widget pattern the Tier Board uses, on a board the check predates.
    await page.goto("/scenario/in-season/?view=opportunity");
    const rows = page.locator(".opp-board .opp-row");
    await expect(rows.first()).toBeVisible();
    const stops = await rows.evaluateAll((nodes) =>
      nodes.filter((node) => node.getAttribute("tabindex") === "0").length,
    );
    expect(stops, "the opportunity board is not one tab stop").toBe(1);

    await rows.first().focus();
    const visible = await rows.first().evaluate((element) => {
      const style = getComputedStyle(element);
      return style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0;
    });
    expect(visible, "an opportunity row has no visible focus indicator").toBe(true);

    // Arrow keys walk the board rather than leaving it.
    await page.keyboard.press("ArrowDown");
    const active = await page.evaluate(() => document.activeElement?.className ?? "");
    expect(active).toContain("opp-row");
  });

  test("a folded panel is a disclosure a keyboard can drive, one tab stop from the tabs", async ({
    page,
  }) => {
    // ADR-093. The row names what it controls, says whether it is open, and a closed panel's
    // controls are out of the tab order rather than focusable while invisible.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/scenario/in-season/?view=ros");
    await expect(page.locator(".board-row").first()).toBeVisible();
    const settings = page.getByRole("button", { name: /^Settings/ });
    const controls = await settings.getAttribute("aria-controls");
    expect(controls).toBe("board-settings");
    await expect(page.locator(`#${controls ?? ""}`)).toHaveCount(1);

    await settings.focus();
    await page.keyboard.press("Tab");
    // Folded, the next stop after the row is the tab strip — no invisible radio in between.
    await expect(page.getByRole("tab", { name: "ROS tiers" })).toBeFocused();

    await settings.focus();
    await page.keyboard.press("Enter");
    await expect(settings).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("radiogroup", { name: "Season mode" }).getByRole("radio", { checked: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(settings).toBeFocused();
    await expect(settings).toHaveAttribute("aria-expanded", "false");

    // The row is a real touch target, not a line of text.
    const box = await settings.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);
  });

  test("the page reflows at 320 CSS pixels without a horizontal scrollbar", async ({ page }) => {
    // WCAG 2.1 "Reflow": 320 CSS pixels wide is what 400% zoom of a 1280px viewport reduces
    // to, and it is the width the spec actually names.
    await page.setViewportSize({ width: 320, height: 800 });
    for (const path of [
      "/",
      "/?view=arbitrage",
      "/?view=data",
      // The in-season boards, which are two charts built after this check existed.
      "/scenario/in-season/?view=ros",
      "/scenario/in-season/?view=opportunity",
      // Five orderings and three chips have to wrap, not clip (ADR-092).
      "/scenario/in-season/?view=opportunity&only=role.momentum.surfaced&opportunity=momentum",
      // Pick of the Week is the widest thing this product draws per unit of content — a
      // portrait column beside a tile grid — so it is the surface most likely to push a
      // number off the edge rather than wrap it (ADR-088).
      "/scenario/in-season/?view=potw",
      "/scenario/in-season/?view=potw&position=te",
    ]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} reflows badly at 320px`).toBeLessThanOrEqual(1);

      // …and with every folded panel open (ADR-093). The folded summary rows ellipsise, and
      // the first draft of them pushed this page 164px sideways from inside a clipped row.
      await page.getByRole("button", { name: /^Settings/ }).click();
      const options = page.getByRole("button", { name: /^Options/ });
      if ((await options.count()) > 0) await options.click();
      const open = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(open, `${path} reflows badly at 320px with its panels open`).toBeLessThanOrEqual(1);
    }
  });

  test("the in-season card's micro-charts reflow at 320 pixels too", async ({ page }) => {
    // The card is a `<dialog>` over the page, so the check above never opens one and a
    // three-column meter row inside it could overflow with the page behind it reflowing
    // perfectly. Each meter stacks at the sheet breakpoint; this is the width that proves it.
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto("/scenario/in-season/?view=ros");
    await page.waitForLoadState("networkidle");
    await page.locator("table.sheet .player-name").first().click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();
    for (const tab of ["Rest of season", "In-season usage"]) {
      await card.getByRole("tab", { name: tab }).click();
      const body = card.locator(".detail-body");
      await expect(body).toBeVisible();
      const overflow = await body.evaluate((node) => node.scrollWidth - node.clientWidth);
      expect(overflow, `${tab} overflows its pane at 320px`).toBeLessThanOrEqual(1);
      const page_ = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(page_, `${tab} reflows badly at 320px`).toBeLessThanOrEqual(1);
    }
  });
});
