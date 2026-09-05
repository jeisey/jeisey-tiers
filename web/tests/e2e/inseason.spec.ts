/**
 * End-to-end coverage of In-Season mode.
 *
 * Served from a static build whose `data/` holds an in-season bundle, so everything asserted
 * here is what a reader in November would actually see. The ordinary fixture build publishes
 * no in-season bundle on purpose — before kickoff that is the correct product — so this suite
 * runs against its own scenario mounts.
 *
 * The assertions are chosen from the two things that could go wrong quietly:
 *
 * 1. **A rest-of-season number presented as a preseason one.** Every column heading and every
 *    export carries `ROS`, and the two ranks appear side by side in the player card rather
 *    than being reconciled into one.
 * 2. **A disclosure that exists in the artifact and not on the screen.** ADR-076's sentences
 *    are asserted as rendered text, the badge is asserted to carry words as well as colour,
 *    and the behaviour columns are asserted to go blank rather than to zero.
 */

import { expect, test, type Page } from "@playwright/test";

const IN_SEASON = "/scenario/in-season/";
const NO_BEHAVIOR = "/scenario/in-season-no-behavior/";
/** The season has started and no rest-of-season board can exist yet (ADR-079). */
const AWAITING = "/scenario/awaiting-first-week/";
/** The far end: every scored week played, no remaining horizon. */
const SEASON_COMPLETE = "/scenario/season-complete/";

/** Fail the test on any request that leaves the static server. */
function forbidExternalRequests(page: Page): void {
  const escaped: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (
      !url.startsWith("http://localhost") &&
      !url.startsWith("data:") &&
      !url.startsWith("blob:")
    ) {
      escaped.push(url);
    }
  });
  page.on("close", () => {
    expect(escaped, "the browser must fetch only generated artifacts").toEqual([]);
  });
}

test.beforeEach(({ page }) => {
  forbidExternalRequests(page);
});

test.describe("season mode", () => {
  test("opens the rest-of-season board when the build says the season has started", async ({
    page,
  }) => {
    await page.goto(IN_SEASON);
    // The URL names no view. The season decides, which is the whole point of `view=auto`.
    await expect(page.getByRole("heading", { name: /Rest of season/ })).toBeVisible();
    await expect(page.getByText("In-Season mode")).toBeVisible();
    await expect(page.locator(".season-mode-detail")).toHaveText("through week 8");
    await expect(page.getByRole("tab", { name: "ROS tiers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("tab", { name: "Opportunity" })).toBeVisible();
  });

  test("stays on the draft board when the build published no in-season bundle", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
    await expect(page.getByText("Draft mode")).toBeVisible();
    // Nothing to switch to before kickoff, so no switch is offered.
    await expect(page.locator(".season-mode").getByRole("radio")).toHaveCount(0);
  });

  test("keeps the draft board reachable all season, and in the URL", async ({ page }) => {
    await page.goto(`${IN_SEASON}?mode=draft`);
    await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Arbitrage" })).toBeVisible();
    await expect(page.getByText("Draft mode")).toBeVisible();
  });

  test("an explicit view wins over the season's default", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=arbitrage`);
    await expect(page.getByRole("heading", { name: /Arbitrage/ })).toBeVisible();
  });
});

test.describe("the lifecycle windows with no rest-of-season board", () => {
  /*
   * The two windows in which the season has started and the draft board is the only board
   * that exists. Both are ordinary, both last days or weeks, and in both the page has to say
   * something true: the season has begun, and the first (or last) rest-of-season board is not
   * this build's to show. Calling either "Draft mode" would be accurate about the board and
   * wrong about the season, which is exactly the confusion ADR-079 exists to prevent.
   */
  test("says the season has started while it waits for the first board", async ({ page }) => {
    await page.goto(AWAITING);
    // The draft board, because it is the only board this build published.
    await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
    // But not "Draft mode": the season is under way and the indicator says so.
    await expect(page.locator(".season-mode-label")).toHaveText("Season under way");
    await expect(page.getByText("Draft mode")).toHaveCount(0);
    // Scoped to the banner: the chip carries the same sentence for assistive technology,
    // which is deliberate and would otherwise make every one of these a strict-mode violation.
    const banner = page.locator(".season-notice");
    await expect(banner).toContainText("The regular season has started.");
    await expect(banner).toContainText(/first rest-of-season board is published once week 1/i);
    // And it says the draft board is not the casualty of the wait.
    await expect(banner).toContainText(/draft board below is unaffected and current/i);
  });

  test("offers no mode switch while there is nothing to switch to", async ({ page }) => {
    await page.goto(AWAITING);
    await expect(page.locator(".season-mode").getByRole("radio")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "ROS tiers" })).toHaveCount(0);
  });

  test("explains the absent board to anyone who links straight to it", async ({ page }) => {
    await page.goto(`${AWAITING}?view=ros`);
    await expect(page.getByText("No rest-of-season board has been published yet.")).toBeVisible();
  });

  test("says the season is over rather than showing a board of zeros", async ({ page }) => {
    await page.goto(SEASON_COMPLETE);
    await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
    await expect(page.locator(".season-mode-label")).toHaveText("Season complete");
    const banner = page.locator(".season-notice");
    // Not "the regular season has started": at this end of the season that is the wrong
    // sentence beside the right note.
    await expect(banner).toContainText("The fantasy season is over.");
    await expect(banner).toContainText(/no rest-of-season horizon remains/i);
  });
});

test.describe("the ROS tier board", () => {
  test("never labels a rest-of-season value with a preseason name", async ({ page }) => {
    await page.goto(IN_SEASON);
    const table = page.getByRole("table", { name: /Rest-of-season board/ });
    // `allTextContents` does not auto-wait, so the table has to be there first.
    await expect(table).toBeVisible();
    const headings = (await table.getByRole("columnheader").allTextContents()).map((text) =>
      text.replace(/[▲▼]/g, "").trim(),
    );
    expect(headings).toContain("ROS Rank");
    expect(headings).toContain("ROS Tier");
    // The bare preseason names must not appear on this board at all.
    expect(headings).not.toContain("Rank");
    expect(headings).not.toContain("Tier");
    expect(headings).not.toContain("Exp VORP");
  });

  test("says a tier is a band rather than drawing an edge as a fact", async ({ page }) => {
    await page.goto(IN_SEASON);
    await expect(page.getByText(/bands, not lines/i).first()).toBeVisible();
  });

  test("states the ADR-076 disclosures where the flagged rows are", async ({ page }) => {
    await page.goto(IN_SEASON);
    await expect(
      page.getByText(/no injury or practice-report information/i).first(),
    ).toBeVisible();
    await expect(page.getByText(/Ranking quality inside this group is weak/i)).toBeVisible();
    await expect(page.getByText(/has not appeared for 3 or more consecutive weeks/i)).toBeVisible();
  });

  test("carries the long-absence flag in words, not by colour alone", async ({ page }) => {
    await page.goto(IN_SEASON);
    const badge = page.locator(".absence-badge").first();
    await expect(badge).toBeVisible();
    // A week count in the visible text, and a full sentence for assistive technology.
    await expect(badge).toContainText(/\d+w/);
    await expect(badge.locator(".visually-hidden")).toContainText(
      /Has not appeared for \d+ weeks?\. No injury or practice-report information is used\./,
    );
    // Never a status word. The model has no information that would justify one.
    await expect(badge).not.toContainText(/out|questionable|doubtful|injured/i);
  });

  test("keeps current status visually separate from every model input", async ({ page }) => {
    await page.goto(IN_SEASON);
    const table = page.getByRole("table", { name: /Rest-of-season board/ });
    const annotation = table.locator("th.col-annotation");
    await expect(annotation).toHaveText(/Current status/);
    const border = await annotation.evaluate((node) => getComputedStyle(node).borderLeftStyle);
    expect(border).not.toBe("none");
    await expect(table.locator("caption")).toContainText(/annotation/i);
  });

  test("names the cutoff, the model and the draw count with its verdict", async ({ page }) => {
    await page.goto(IN_SEASON);
    await expect(page.getByText("Through week 8 (ros_cutoff_v1)")).toBeVisible();
    await expect(page.getByText("intrinsic-ros-v1", { exact: true })).toBeVisible();
    await expect(page.getByText(/10000 \(declared fallback\)/)).toBeVisible();
    // And the footer names the model that produced what is on screen, not the draft one.
    await expect(page.locator("footer.footer")).toContainText("intrinsic-ros-v1 · phase12_ros_v1");
  });
});

test.describe("the opportunity board", () => {
  test("shows behaviour as counts over a named window, never as a price", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const table = page.getByRole("table", { name: /opportunity board/i });
    await expect(table).toBeVisible();
    const headings = (await table.getByRole("columnheader").allTextContents()).map((text) =>
      text.trim(),
    );
    expect(headings).toContain("Adds (24h)");
    expect(headings).toContain("Drops (24h)");
    expect(headings).toContain("Net adds");
    // Nothing on this board is called a price, a rank gap or a score.
    for (const heading of headings) {
      expect(heading).not.toMatch(/adp|rank gap|score|edge/i);
    }
    await expect(page.getByText(/not a draft price, not a rank/i)).toBeVisible();
  });

  test("surfaces a player from beyond the tier depth, with a reason and no tier", async ({
    page,
  }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&opportunity=adds`);
    const surfaced = page.locator('tr[data-surfaced="true"]').first();
    await expect(surfaced).toBeVisible();
    await expect(surfaced.locator(".surface-badge")).toContainText("surfaced");
  });

  test("offers three orderings and no blended score", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    // `Segmented` renders an ARIA radiogroup, which is not the same role as `group`.
    const group = page.getByRole("radiogroup", { name: /Order by/i });
    await expect(group.getByRole("radio", { name: "ROS value" })).toBeVisible();
    // `exact` because "Net adds" contains "Adds".
    await expect(group.getByRole("radio", { name: "Adds", exact: true })).toBeVisible();
    await expect(group.getByRole("radio", { name: "Net adds" })).toBeVisible();

    await group.getByRole("radio", { name: "Adds", exact: true }).click();
    await expect(page).toHaveURL(/opportunity=adds/);
  });

  test("empties the behaviour columns when the feed is down and keeps every value", async ({
    page,
  }) => {
    await page.goto(`${NO_BEHAVIOR}?view=opportunity`);
    await expect(page.getByText(/No current add\/drop behaviour/i)).toBeVisible();
    await expect(
      page.getByText(/decides which players are visible and never what they are worth/i),
    ).toBeVisible();

    const table = page.getByRole("table", { name: /opportunity board/i });
    const firstRow = table.getByRole("row").nth(1);
    // Blank, not zero: a zero would claim nobody added him.
    await expect(firstRow).toContainText("—");
    // And the intrinsic value is still there.
    await expect(firstRow.locator("td").nth(4)).not.toBeEmpty();
  });
});

test.describe("in-season exports and links", () => {
  test("exports name the board and the cutoff week", async ({ page }) => {
    await page.goto(IN_SEASON);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /Export filtered CSV/ }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^ffdraft-ros_tiers-ppr-12-w08-\d{4}-\d{2}-\d{2}\.csv$/);
  });

  test("the exported rest-of-season columns are all ROS-named", async ({ page }) => {
    await page.goto(IN_SEASON);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /Export filtered CSV/ }).click();
    const stream = await (await download).createReadStream();
    const chunks: Uint8Array[] = [];
    for await (const chunk of stream) chunks.push(new Uint8Array(Buffer.from(chunk as Buffer)));
    const header = Buffer.concat(chunks).toString("utf-8").split("\r\n")[0] ?? "";
    expect(header).toContain("ros_fair_rank");
    expect(header).toContain("long_absence");
    expect(header).toContain("weeks_since_last_game");
    // The bare preseason column name must not be in an in-season export.
    expect(header.split(",")).not.toContain("fair_rank");
  });

  test("the season mode and the ordering survive a reload", async ({ page }) => {
    await page.goto(`${IN_SEASON}?mode=draft&view=tiers`);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
    await expect(page).toHaveURL(/mode=draft/);
  });
});

test.describe("the player card in season", () => {
  test("shows the two ranks side by side rather than reconciling them", async ({ page }) => {
    await page.goto(IN_SEASON);
    // A player's own name, not the sort button in the header row above it.
    await page.locator("table.sheet .player-name").first().click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();
    await expect(card.getByText("Preseason fair rank")).toBeVisible();
    await expect(card.getByText("Current ROS fair rank")).toBeVisible();
    await expect(card.getByText("Change in intrinsic view")).toBeVisible();
    await expect(card.getByText("two models, two orderings")).toBeVisible();
  });
});
