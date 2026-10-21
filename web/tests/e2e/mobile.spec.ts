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

import { expect, test, type Page } from "@playwright/test";

import { stubPortraits } from "./boundary";
import { IN_SEASON, MATCH, OFFICE, matchOpponent, seed, seedMatchups } from "./leagues-seed";

/*
 * No test in this repository reaches a third party. The player card fetches its portrait from
 * one declared host; this serves it locally instead, so the suite neither depends on a
 * provider's uptime nor makes a request on a reader's behalf every time CI runs (ADR-087).
 */
test.beforeEach(async ({ page }) => {
  await stubPortraits(page);
});


/*
 * ADR-109. The tap that opens a card leaves a collapsed caret in the document; on the in-season
 * board the browser then spent ~400 ms (4x CPU) re-canonicalising it on the first tap inside
 * the card. The card drops that caret as it opens, so the first tab tap is as quick as the rest.
 */
test("opening a card by tap leaves no stray caret behind", async ({ page }) => {
  await page.goto(`${IN_SEASON}?view=ros`);
  const row = page.locator(".board-row[data-player]").first();
  await row.tap();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("tablist")).toBeVisible();
  expect(await page.evaluate(() => window.getSelection()?.type ?? "None")).not.toBe("Caret");
  await dialog.getByRole("tab", { name: "Current status" }).tap();
  await expect(dialog.getByRole("tab", { name: "Current status" })).toHaveAttribute("aria-selected", "true");
});

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
  // The sheet is artboard 1b: three tabs rather than one long scroll. The annotation-only
  // disclosure is on the status tab, which is one tap — and tapping it is also the check that
  // the tab bar works with a thumb.
  await dialog.getByRole("tab", { name: "Current status" }).click();
  await expect(dialog.getByText("Annotation only — not a model input.")).toBeVisible();
  await page.getByRole("button", { name: "Close player detail" }).click();
  await expect(dialog).toBeHidden();

  // Controls stay reachable while the board scrolls under them: the summary row that opens
  // them stays on screen, and one tap puts them on screen too (ADR-093). They used to stay
  // resident instead, which cost 30% of the viewport for as long as the board scrolled.
  await page.mouse.wheel(0, 900);
  const settings = page.getByRole("button", { name: /^Settings/ });
  await expect(settings).toBeInViewport();
  await settings.click();
  await expect(page.getByRole("radio", { name: "PPR", exact: true })).toBeInViewport();
});

/*
 * The phone's control bands fold (ADR-093).
 *
 * The owner's screenshot of the Opportunity Board was half navigation: four sticky controls
 * and the tabs took 248px of an 839px phone at all times, and the board's own orderings and
 * filters pushed its chart to the bottom of the first screen. The budget below is what the
 * fold is for, measured rather than described: a sticky block that grows back past it is the
 * regression, whatever the reason.
 */
test.describe("folded controls on a phone (ADR-093)", () => {
  /** The sticky block's ceiling. One 40px summary row plus the 44px tab strip and rules. */
  const STICKY_BUDGET = 96;

  /**
   * Scroll the page and wait until the sticky block is actually stuck.
   *
   * `mouse.wheel` "does not wait for the scrolling to finish before returning", so measuring
   * straight after it races the scroll: under load the first draft of the sideways test read
   * the block at its unscrolled position (389px down a 320px screen) and failed, and passed
   * alone. Scrolling to an offset and polling for the stuck position removes the race.
   */
  async function scrollUntilStuck(page: Page, y: number): Promise<void> {
    await page.evaluate((top) => {
      window.scrollTo(0, top);
    }, y);
    await expect
      .poll(async () => (await page.locator(".sticky-controls").boundingBox())?.y ?? Infinity)
      .toBeLessThanOrEqual(1);
  }

  /**
   * A summary row's accessible name: its label, then its items read as a list. The commas are
   * the screen reader's separators (the dots are hidden from it), and the name computation may
   * pad them with spaces, so the match is on the words and their order.
   */
  const summaryName = (label: string, ...items: (string | RegExp)[]): RegExp =>
    new RegExp(
      `^${label} ` +
        items
          .map((item) =>
            typeof item === "string" ? item.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") : item.source,
          )
          .join("\\s*,\\s*") +
        "$",
    );

  for (const [name, path, chart] of [
    ["the tier board", "/", ".tier-board"],
    ["the arbitrage board", "/?view=arbitrage", ".draft-rail"],
    ["the rest-of-season board", "/scenario/in-season/?view=ros", ".tier-board"],
    ["the opportunity board", "/scenario/in-season/?view=opportunity", ".opp-board"],
    ["pick of the week", "/scenario/in-season/?view=potw", ".potw-grid"],
    ["start/sit", "/scenario/in-season/?view=startsit&duel=00-0000011.00-0000012", ".verdict"],
    ["trade", "/scenario/in-season/?view=trade&give=00-0000001&get=2&range=35", ".trade-results"],
  ] as const) {
    test(`${name} keeps its sticky chrome to one row and the tabs`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator(chart).first()).toBeVisible();
      const viewport = page.viewportSize();
      const height = viewport?.height ?? 0;

      // Folded by default, and the row says what the folded controls are set to.
      const settings = page.getByRole("button", { name: /^Settings/ });
      await expect(settings).toHaveAttribute("aria-expanded", "false");
      await expect(page.locator("#board-settings")).toBeHidden();

      // Scrolled, the sticky block is the summary row and the tabs, and nothing more.
      await scrollUntilStuck(page, 1200);
      await expect(settings).toBeInViewport();
      await expect(page.getByRole("tablist", { name: "Board" })).toBeInViewport();
      const sticky = await page.locator(".sticky-controls").boundingBox();
      expect(sticky?.height ?? Infinity).toBeLessThanOrEqual(STICKY_BUDGET);
      expect(sticky?.height ?? Infinity).toBeLessThanOrEqual(height * 0.12);
    });
  }

  for (const [name, path, chart] of [
    ["the tier board", "/", ".tier-board"],
    ["the rest-of-season board", "/scenario/in-season/?view=ros", ".tier-board"],
    ["the opportunity board", "/scenario/in-season/?view=opportunity", ".opp-board"],
    ["pick of the week", "/scenario/in-season/?view=potw", ".potw-grid"],
    ["start/sit", "/scenario/in-season/?view=startsit&duel=00-0000011.00-0000012", ".deck"],
  ] as const) {
    test(`${name} starts in the first screen, not under its controls`, async ({ page }) => {
      await page.goto(path);
      const box = await page.locator(chart).first().boundingBox();
      const height = page.viewportSize()?.height ?? 0;
      // The Opportunity chart started at 716px of 839 before the fold — 85% of the way down
      // the first screen. The board is the product; it gets at least the lower half of it.
      expect(box?.y ?? Infinity, `${name} is pushed down the first screen`).toBeLessThanOrEqual(
        height * 0.6,
      );
    });
  }

  test("the settings row opens, prints the state it hides, and closes with Escape", async ({
    page,
  }) => {
    await page.goto("/scenario/in-season/?view=opportunity");
    const settings = page.getByRole("button", { name: /^Settings/ });
    await expect(settings).toHaveAccessibleName(summaryName("Settings", "PPR", "12 teams", "All positions"));
    await expect(settings).toHaveAttribute("aria-controls", "board-settings");

    await settings.click();
    await expect(settings).toHaveAttribute("aria-expanded", "true");
    // The season-mode switch folds with the controls rather than taking a band of its own.
    for (const group of ["Season mode", "Scoring", "Teams", "Position"]) {
      await expect(page.getByRole("radiogroup", { name: group })).toBeInViewport();
    }
    await expect(page.getByRole("button", { name: /^Search players/ })).toBeInViewport();

    // A change is on the board and in the summary at once; the panel stays open for the next.
    await page.getByRole("radio", { name: "Half PPR" }).click();
    await page.getByRole("radio", { name: "RB" }).click();
    await expect(page).toHaveURL(/scoring=half/);
    await expect(settings).toHaveAccessibleName(summaryName("Settings", "Half", "12 teams", "RB"));
    await expect(settings).toHaveAttribute("aria-expanded", "true");

    // Escape inside the panel folds it and hands focus back to the row that opened it.
    await page.getByRole("radio", { name: "RB" }).focus();
    await page.keyboard.press("Escape");
    await expect(settings).toHaveAttribute("aria-expanded", "false");
    await expect(settings).toBeFocused();
    await expect(page.locator("#board-settings")).toBeHidden();
    // Folded is not reset: the board is still the one the reader chose.
    await expect(page).toHaveURL(/scoring=half&position=rb/);
  });

  test("a shared link's search, filters and mode are named while folded", async ({ page }) => {
    // A folded control whose value you cannot see is a filter you can forget is on.
    await page.goto(
      "/scenario/in-season/?view=opportunity&scoring=std&position=rb&search=cook" +
        "&mode=in_season&opportunity=momentum&only=role.momentum",
    );
    await expect(page.locator(".opp-board")).toBeVisible();
    await expect(page.getByRole("button", { name: /^Settings/ })).toHaveAccessibleName(
      summaryName("Settings", "STD", "12 teams", "RB", "“cook”", "In-season mode"),
    );
    const options = page.getByRole("button", { name: /^Options/ });
    await expect(options).toHaveAccessibleName(
      summaryName("Options", "By Momentum", "Role rising + Momentum rising", /All \d+/, /Last 3 W6–8 · \d+ without evidence/),
    );
    // The filters' census never folds (ADR-092): how many pass, and how many had no reading.
    await expect(page.locator(".opp-filter-status")).toBeInViewport();
    await expect(page.locator(".opp-breakout-census")).toContainText(/Breakouts in W6–8/);
    await expect(page.locator(".opp-filter-status")).toContainText(/Role rising: \d+/);
  });

  test("the opportunity board's orderings and filters fold behind one row", async ({ page }) => {
    await page.goto("/scenario/in-season/?view=opportunity");
    const options = page.getByRole("button", { name: /^Options/ });
    await expect(options).toHaveAttribute("aria-expanded", "false");
    await expect(options).toHaveAttribute("aria-controls", "opp-order-options opp-filter-options");
    await expect(options).toHaveAccessibleName(
      // ADR-113: the recent-weeks lens, its real weeks and its missing evidence close the row.
      summaryName("Options", "By ROS value", "No filters", /All \d+/, /Last 3 W6–8 · \d+ without evidence/),
    );
    await expect(page.getByRole("radiogroup", { name: "Order by" })).toBeHidden();
    await expect(page.getByRole("button", { name: "Role rising", exact: true })).toBeHidden();
    await expect(page.locator(".opp-filter-status")).toBeVisible();

    await options.click();
    await expect(options).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("radiogroup", { name: "Order by" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Show full board/ })).toBeVisible();
    await page.getByRole("button", { name: "Role rising", exact: true }).click();
    await page.getByRole("radio", { name: "Adds", exact: true }).click();
    await expect(page).toHaveURL(/opportunity=adds&only=role/);
    await expect(options).toHaveAccessibleName(
      summaryName("Options", "By Adds", "Role rising", /All \d+/, /Last 3 W6–8 · \d+ without evidence/),
    );

    await options.click();
    await expect(page.getByRole("radiogroup", { name: "Order by" })).toBeHidden();
    // Folding hides the controls, not what they did. (`getByRole` skips a hidden node, so
    // the folded chip is read by its own attribute.)
    await expect(page.locator('.opp-filter[data-filter="role"]')).toBeHidden();
    await expect(page.locator('.opp-filter[data-filter="role"]')).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page).toHaveURL(/only=role/);
  });

  test("an open panel on a phone held sideways never buries the tabs", async ({ page }) => {
    // 568x320 — a small phone on its side — is below the sheet breakpoint and shorter than
    // the open panel. A sticky block taller than the screen cannot be scrolled to, so the
    // panel scrolls inside itself instead and the tabs stay on screen however long it is.
    await page.setViewportSize({ width: 568, height: 320 });
    await page.goto("/scenario/in-season/?view=ros");
    await expect(page.locator(".tier-board")).toBeVisible();
    await page.getByRole("button", { name: /^Settings/ }).click();
    await scrollUntilStuck(page, 800);
    const sticky = await page.locator(".sticky-controls").boundingBox();
    expect((sticky?.y ?? 0) + (sticky?.height ?? Infinity)).toBeLessThanOrEqual(320);
    await expect(page.getByRole("tablist", { name: "Board" })).toBeInViewport({ ratio: 1 });
    const panel = page.locator("#board-settings");
    expect(await panel.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
    // Every control is still reachable, by scrolling the panel rather than the page.
    const te = page.getByRole("radiogroup", { name: "Position" }).getByRole("radio", { name: "TE" });
    await te.scrollIntoViewIfNeeded();
    await expect(te).toBeInViewport();
    await expect(page.getByRole("button", { name: /^Search players/ })).toBeAttached();
  });
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

  /*
   * ADR-111: the header opens compact — the name, position and team, any status worth stating,
   * the close control and *Expand details* — so the tabs and their panel get the screen. What a
   * drafter reads next (fair rank, the market verdict, the arbitrage score, the status line) is
   * one tap away on the same control, and the tabs are on screen either way.
   */
  const expand = dialog.getByRole("button", { name: "Expand details" });
  await expect(expand).toBeInViewport();
  await expect(expand).toHaveAttribute("aria-expanded", "false");
  await expect(dialog.getByRole("heading", { name: "Amon-Ra Bright" })).toBeInViewport();
  await expect(dialog.locator(".detail-compact-identity")).toContainText("WR");
  await expect(dialog.locator(".detail-compact-identity")).toContainText("DET");
  // Questionable is a status worth stating, so it stays on the compact line.
  await expect(dialog.locator(".detail-compact-identity .status-badge")).toBeVisible();
  await expect(dialog.getByText("Fair rank", { exact: true })).toBeHidden();
  await expect(dialog.getByRole("tab", { name: "Draft market" })).toBeInViewport();

  await expand.click();
  await expect(dialog.getByRole("button", { name: "Collapse details" })).toHaveAttribute("aria-expanded", "true");
  for (const label of ["Fair rank", "Arbitrage score", "Status"]) {
    await expect(dialog.getByText(label, { exact: true })).toBeInViewport();
  }
  // The verdict names the market whose gap it prints, so it is matched by shape: the rail
  // used to show the flat V1 gap — MyFantasyLeague's — beneath a sentence computed from the
  // selected market, and the two disagreed whenever the selector was not on MFL (ADR-081).
  await expect(dialog.locator(".rail-verdict-label").filter({ hasText: / verdict$/ })).toBeInViewport();
  // ...and the rest is one tap away, on a tab that is itself a touch target.
  await expect(dialog.getByRole("tab", { name: "Draft market" })).toBeInViewport();

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

/*
 * Seven in-season tabs (ADR-100, ADR-106). The row scrolls rather than shrinking anything:
 * every tab keeps a 44px target, "Opportunity" prints as "Opp" and "My Leagues" as "Leagues"
 * with their full accessible names, and the active tab is scrolled fully into view whichever
 * it is.
 */
test("seven tabs: full tap targets, short labels with full names, the active tab on screen", async ({
  page,
}) => {
  for (const view of ["ros", "myleagues", "startsit", "trade", "opportunity", "potw", "data"]) {
    await page.goto(`/scenario/in-season/?view=${view}`);
    const tablist = page.getByRole("tablist", { name: "Board" });
    await expect(tablist).toBeVisible();
    const active = tablist.locator('[aria-selected="true"]');
    await expect(active).toBeInViewport({ ratio: 1 });
    for (const tab of await tablist.getByRole("tab").all()) {
      expect((await tab.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
  }
  const opportunity = page.getByRole("tab", { name: "Opportunity" });
  await expect(opportunity).toHaveAccessibleName("Opportunity");
  await expect(opportunity.locator(".tab-label-short")).toBeVisible();
  const leagues = page.getByRole("tab", { name: "My Leagues" });
  await expect(leagues).toHaveAccessibleName("My Leagues");
  await expect(leagues.locator(".tab-label-short")).toHaveText("Leagues");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});

/*
 * My Leagues on a phone (ADR-106): readable stacked slots with their actions under each one,
 * the switcher and primary actions within reach, dialogs that fit the screen, and no sideways
 * page scroll anywhere — including with every optional section open.
 */
test("My Leagues stacks its slots on a phone and nothing scrolls the page sideways", async ({ page }) => {
  await seed(page, [OFFICE, { id: "lg-family01", name: "Family", scoring: "half", roster: {} }]);
  await page.goto(`${IN_SEASON}?view=myleagues`);
  const slot = page.locator(".lg-slot", { hasText: "Bijan Robinson" });
  await expect(slot).toBeVisible();
  // The actions sit under the player, not squeezed beside him.
  const name = await slot.locator(".player-name").boundingBox();
  const edit = await slot.getByRole("button", { name: /^Edit/ }).boundingBox();
  expect((edit?.y ?? 0) >= (name?.y ?? 0) + (name?.height ?? 0)).toBe(true);
  expect(edit?.height ?? 0).toBeGreaterThanOrEqual(40);
  await page.getByRole("checkbox", { name: "Rising Stars" }).check();
  await page.getByRole("button", { name: "Find upgrades" }).click();
  await expect(page.getByRole("region", { name: "Upgrade ideas" })).toBeVisible();
  await page.getByRole("button", { name: "Show Bijan Robinson's week" }).click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  // The slot dialog fits the screen, its search is usable, and a pick lands in the slot.
  await page.getByRole("button", { name: "Add a player to Bench 3" }).tap();
  const dialog = page.getByRole("dialog");
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect((box?.x ?? -1) >= 0 && (box?.width ?? 0) <= (viewport?.width ?? 0)).toBe(true);
  await dialog.getByRole("combobox").fill("jahmyr");
  await dialog.getByRole("option", { name: /Jahmyr Cook/ }).tap();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".lg-slot", { hasText: "Jahmyr Cook" })).toBeVisible();

  // The settings dialog, with its steppers, fits too.
  await page.getByRole("button", { name: "League settings" }).tap();
  const settings = page.getByRole("dialog");
  const settingsBox = await settings.boundingBox();
  expect((settingsBox?.width ?? 0) <= (viewport?.width ?? 0)).toBe(true);
  const inner = await settings.locator(".lg-dialog-body").evaluate((node) => node.scrollWidth - node.clientWidth);
  expect(inner).toBeLessThanOrEqual(1);
});

/*
 * Win My Matchup on a phone (ADR-110): the two lineups stack, every slot's actions sit under
 * it, the chart fits the screen, the group table scrolls inside itself, and nothing scrolls
 * the page sideways — with a result, YOLO and a preview on screen.
 */
test("Win My Matchup stacks on a phone, its chart fits, and nothing scrolls the page sideways", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-08-22T12:00:00Z"));
  await seed(page, [MATCH]);
  await seedMatchups(page, matchOpponent());
  await page.goto(`${IN_SEASON}?view=myleagues&panel=wmm`);
  const sides = page.locator(".wmm-side");
  const [mine, theirs] = await Promise.all([sides.nth(0).boundingBox(), sides.nth(1).boundingBox()]);
  expect((theirs?.y ?? 0) >= (mine?.y ?? 0) + (mine?.height ?? 0) - 1).toBe(true);
  await page.getByRole("button", { name: "Simulate" }).tap();
  await expect(page.locator(".wmm-headline")).toBeVisible();
  await page.getByRole("checkbox", { name: "YOLO" }).check();
  await page.getByRole("button", { name: "Evaluate changes and pickups" }).tap();
  await page.getByRole("list", { name: "Potential pickups" }).getByRole("button", { name: "Preview" }).first().tap();
  await expect(page.locator(".wmm-legend[data-side=overlay]")).toBeVisible();
  const viewport = page.viewportSize();
  const chart = await page.locator(".wmm-chart svg").boundingBox();
  expect((chart?.x ?? -1) >= 0 && (chart?.x ?? 0) + (chart?.width ?? 0) <= (viewport?.width ?? 0) + 1).toBe(true);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const simulate = await page.getByRole("button", { name: "Simulate" }).boundingBox();
  expect(simulate?.height ?? 0).toBeGreaterThanOrEqual(40);
});

/*
 * ADR-111: the card's header on a phone. Compact by default, one tap to expand, the choice held
 * across every tab (the Skill Tree's included) and reset when the card closes; the close control
 * and the tabs never leave the screen, at a phone's width and at a short one.
 */
for (const viewport of [
  { width: 412, height: 839 },
  { width: 320, height: 568 },
]) {
  test(`the card's header collapses and expands at ${String(viewport.width)}x${String(viewport.height)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/scenario/in-season/?view=ros");
    await page.getByRole("button", { name: "Puka Nightingale", exact: true }).first().tap();
    const dialog = page.getByRole("dialog");
    const close = dialog.getByRole("button", { name: "Close player detail" });
    const rail = dialog.locator(".detail-rail");
    const body = dialog.locator(".detail-body");
    await expect(dialog.getByRole("button", { name: "Expand details" })).toBeInViewport({ ratio: 1 });
    await expect(close).toBeInViewport({ ratio: 1 });
    const compact = { rail: (await rail.boundingBox())?.height ?? 0, body: (await body.boundingBox())?.height ?? 0 };
    // A couple of rows, not a miniature of the whole header.
    expect(compact.rail).toBeLessThanOrEqual(100);
    await expect(dialog.locator(".rail-hero")).toBeHidden();
    await expect(dialog.locator(".portrait")).toBeHidden();

    await dialog.getByRole("button", { name: "Expand details" }).tap();
    const toggle = dialog.getByRole("button", { name: "Collapse details" });
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(dialog.getByText("ROS overall rank", { exact: true })).toBeVisible();
    const expanded = (await rail.boundingBox())?.height ?? 0;
    expect(expanded).toBeGreaterThan(compact.rail + 100);
    // Capped, so the tabs stay on a short screen.
    expect(expanded).toBeLessThanOrEqual(viewport.height * 0.51);

    const tabs = dialog.getByRole("tab");
    const names = await tabs.allTextContents();
    expect(names).toContain("Skill tree");
    for (const name of names) {
      const tab = dialog.getByRole("tab", { name, exact: true });
      await tab.tap();
      await expect(tab).toHaveAttribute("aria-selected", "true");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(tab).toBeInViewport({ ratio: 1 });
      await expect(close).toBeInViewport({ ratio: 1 });
    }
    await dialog.getByRole("tab", { name: "Skill tree", exact: true }).tap();
    await expect(dialog.getByRole("group", { name: /skill tree/ })).toBeVisible();
    await toggle.tap();
    await expect(dialog.getByRole("button", { name: "Expand details" })).toBeFocused();
    await expect(dialog.getByRole("tab", { name: "Skill tree", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(dialog.getByRole("group", { name: /skill tree/ })).toBeVisible();

    const overflow = await page.evaluate(() => {
      const card = document.querySelector(".detail-card");
      return {
        page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        card: card === null ? 0 : card.scrollWidth - card.clientWidth,
      };
    });
    expect(overflow.page).toBeLessThanOrEqual(0);
    expect(overflow.card).toBeLessThanOrEqual(0);

    // Closing resets it: Escape still closes, and the next card opens compact.
    await dialog.getByRole("button", { name: "Expand details" }).tap();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await page.getByRole("button", { name: "Puka Nightingale", exact: true }).first().tap();
    await expect(page.getByRole("dialog").getByRole("button", { name: "Expand details" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
}

/*
 * ADR-115. The close control and *Expand/Collapse details* are two separate targets with a clear
 * gap, in both header states, on every tab, after the panel and the rail scroll, and for a long
 * name with a badge. A viewport-visibility check passed while the two rectangles overlapped by
 * 6.4 x 25.8 px (Pixel 7, 2026-10-21), because both were on screen — only intersecting them
 * catches it. The gutter the rail reserves is derived from the close control, so the gap is the
 * stylesheet's `--space-2`; 4px is the floor this asserts.
 */
const MIN_CONTROL_GAP = 4;

async function controlGap(page: Page): Promise<{ gap: number; tapSize: number }> {
  return page.evaluate(() => {
    const close = document.querySelector("dialog.player-detail .detail-close")?.getBoundingClientRect();
    const toggle = document.querySelector("dialog.player-detail .detail-expand")?.getBoundingClientRect();
    if (close === undefined || toggle === undefined) return { gap: Number.NaN, tapSize: 0 };
    const dx = Math.max(close.left - toggle.right, toggle.left - close.right);
    const dy = Math.max(close.top - toggle.bottom, toggle.top - close.bottom);
    return { gap: Math.max(dx, dy), tapSize: Math.min(close.width, close.height, toggle.height) };
  });
}

for (const viewport of [
  { width: 412, height: 839 },
  { width: 390, height: 844 },
  { width: 390, height: 560 },
  { width: 320, height: 568 },
]) {
  test(`the card's close and expand controls never touch at ${String(viewport.width)}x${String(viewport.height)}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    for (const [view, name] of [
      ["ros", "Puka Nightingale"],
      ["ros", "Kyle Pitts Sr."],
      ["opportunity", "Bijan Robinson (surfaced)"],
    ] as const) {
      await page.goto(`/scenario/in-season/?view=${view}`);
      await page.getByRole("button", { name, exact: true }).first().tap();
      const dialog = page.getByRole("dialog");
      const tabs = dialog.getByRole("tab");
      for (const expanded of [false, true]) {
        if (expanded) await dialog.getByRole("button", { name: "Expand details" }).tap();
        for (const tab of await tabs.allTextContents()) {
          await dialog.getByRole("tab", { name: tab, exact: true }).tap();
          const reading = await controlGap(page);
          expect(reading.gap, `${name}, ${expanded ? "expanded" : "compact"}, ${tab}`).toBeGreaterThanOrEqual(MIN_CONTROL_GAP);
          // No target was shrunk to make room.
          expect(reading.tapSize).toBeGreaterThanOrEqual(32);
        }
        await page.evaluate(() => {
          for (const selector of [".detail-body", ".detail-rail"]) {
            const node = document.querySelector(`dialog.player-detail ${selector}`);
            if (node !== null) node.scrollTop = node.scrollHeight;
          }
        });
        expect((await controlGap(page)).gap, `${name} scrolled`).toBeGreaterThanOrEqual(MIN_CONTROL_GAP);
        await expect(dialog.getByRole("button", { name: "Close player detail" })).toBeInViewport({ ratio: 1 });
      }
      // The reported overlap ate into the toggle's own row: the rail still has room to spare.
      const slack = await page.evaluate(() => {
        const rail = document.querySelector("dialog.player-detail .detail-rail");
        return rail === null ? 0 : rail.clientWidth - rail.scrollWidth;
      });
      expect(slack).toBeGreaterThanOrEqual(0);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
    }
  });
}
