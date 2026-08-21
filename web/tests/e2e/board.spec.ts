/**
 * End-to-end coverage of the draft sheet.
 *
 * The suite runs against a static build with fixed fixture artifacts, so a number asserted here
 * is a number a user would see. Every test guards the browser boundary: a request to any host
 * other than the local static server fails the test, which is how `docs/ARCHITECTURE.md`
 * section 3.2 stops being a convention and starts being a check.
 */

import { expect, test, type Page } from "@playwright/test";

/** Fail the test on any request that leaves the static server. No vendor call may exist. */
function forbidExternalRequests(page: Page): void {
  const escaped: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("http://localhost") && !url.startsWith("data:") && !url.startsWith("blob:")) {
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

async function openBoard(page: Page, path = "/"): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
}

test.describe("default tier experience", () => {
  test("renders the board, the freshness stamp and the tier table", async ({ page }) => {
    await openBoard(page);
    await expect(page.getByText("Aug 21 · 10:38 AM ET")).toBeVisible();
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    await expect(table.getByRole("row")).toHaveCount(11);
    await expect(table.getByRole("row").nth(1)).toContainText("Bijan Robinson");
    await expect(page.getByText("Median simulated VORP", { exact: true })).toBeVisible();
  });

  test("presents tiers as soft groups with no hard boundary or cliff claim", async ({ page }) => {
    await openBoard(page);
    await expect(page.getByText(/exact tier edges are statistically soft/i)).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/value cliff/i);
    // Lane separation is a filled band, never a stroked rule between tiers.
    await expect(page.locator("svg .lane-band")).toHaveCount(3);
  });

  test("expands from the default chart depth to the full board", async ({ page }) => {
    await openBoard(page);
    // The fixture board is shorter than the preview depth, so the control offers the full board
    // and the row count is unchanged — the point is that the chart never invents a different rank.
    const marksBefore = await page.locator("svg g.player-mark").count();
    await page.getByRole("button", { name: /Show full board/ }).click();
    await expect(page).toHaveURL(/board=full/);
    expect(await page.locator("svg g.player-mark").count()).toBe(marksBefore);
  });
});

test.describe("global controls and URL state", () => {
  test("writes every control into the URL and survives a reload", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("radio", { name: "Standard" }).click();
    await page.getByRole("radio", { name: "14-team league" }).click();
    await page.getByRole("radio", { name: "RB" }).click();
    await expect(page).toHaveURL(/scoring=std/);
    await expect(page).toHaveURL(/teams=14/);
    await expect(page).toHaveURL(/position=rb/);

    await page.reload();
    await expect(page.getByRole("radio", { name: "Standard" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByRole("radio", { name: "14-team league" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByRole("radio", { name: "RB" })).toHaveAttribute("aria-checked", "true");
  });

  test("back and forward walk the boards that were actually looked at", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("radio", { name: "WR" }).click();
    await expect(page).toHaveURL(/position=wr/);
    await page.getByRole("tab", { name: "Arbitrage" }).click();
    await expect(page).toHaveURL(/view=arbitrage/);

    await page.goBack();
    await expect(page).toHaveURL(/position=wr/);
    await expect(page).not.toHaveURL(/view=arbitrage/);
    await page.goForward();
    await expect(page).toHaveURL(/view=arbitrage/);
  });

  test("normalizes an unsupported URL instead of failing", async ({ page }) => {
    await page.goto("/?view=leaderboard&scoring=superflex&teams=11&position=k&utm_source=x");
    await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("radio", { name: "PPR", exact: true })).toHaveAttribute("aria-checked", "true");
  });

  test("changing scoring changes the board it is showing", async ({ page }) => {
    await openBoard(page);
    const first = page.getByRole("table", { name: /Intrinsic tier board/ }).getByRole("row").nth(1);
    const ppr = await first.textContent();
    await page.getByRole("radio", { name: "Standard" }).click();
    await expect(page).toHaveURL(/scoring=std/);
    // Same players, re-valued: the row is still there and its numbers moved.
    await expect(first).toBeVisible();
    expect(await first.textContent()).not.toBe(ppr);
  });
});

test.describe("search", () => {
  test("finds a player and shares the search in the URL", async ({ page }) => {
    await openBoard(page);
    await page.getByLabel("Player search").fill("burrow");
    await expect(page).toHaveURL(/search=burrow/);
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    await expect(table.getByRole("row")).toHaveCount(2);
    await expect(table).toContainText("Joe Burrow");
  });

  test("still finds a player who has no market price", async ({ page }) => {
    await openBoard(page, "/?search=ertz");
    await expect(page.getByRole("table", { name: /Intrinsic tier board/ })).toContainText("Zach Ertz");
    await page.getByRole("tab", { name: "Arbitrage" }).click();
    await expect(page.getByText("On the tier board, but not priced")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/0 results/i);
  });
});

test.describe("tier table", () => {
  test("sorts on a header click and marks the sorted column", async ({ page }) => {
    await openBoard(page);
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    await table.getByRole("button", { name: /Exp FP/ }).click();
    await expect(table.getByRole("columnheader", { name: /Exp FP/ })).toHaveAttribute(
      "aria-sort",
      /ascending|descending/,
    );
    // Fair rank remains the artifact's rank; only the row order moved.
    await expect(table.getByRole("row").nth(1).locator("td").first()).not.toBeEmpty();
  });

  test("agrees with the chart on the same player's median VORP", async ({ page }) => {
    await openBoard(page);
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    const medianCell = table.getByRole("row").nth(1).locator("td").nth(7);
    const tableValue = (await medianCell.textContent())?.trim();
    const mark = page.getByRole("button", { name: /^Bijan Robinson,.*median simulated VORP/ });
    const label = await mark.getAttribute("aria-label");
    expect(label).toContain(`median simulated VORP ${String(tableValue)}`);
  });
});

test.describe("export", () => {
  test("downloads the full CSV artifact the build wrote", async ({ page }) => {
    await openBoard(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download full CSV" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("tiers.csv");
  });

  test("exports exactly the filtered rows, named from the build date", async ({ page }) => {
    await openBoard(page, "/?position=te");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: /Export filtered CSV \(3\)/ }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("ffdraft-tiers-ppr-12-2026-08-21.csv");
    const stream = await download.createReadStream();
    const chunks: Uint8Array[] = [];
    for await (const chunk of stream) chunks.push(new Uint8Array(Buffer.from(chunk as Buffer)));
    const csv = Buffer.concat(chunks).toString("utf-8");
    const lines = csv.trim().split("\r\n");
    expect(lines).toHaveLength(4);
    expect(lines[0]).toContain("fair_rank,player,position");
    for (const line of lines.slice(1)) expect(line).toContain(",TE,");
  });
});

test.describe("arbitrage", () => {
  test("sorts by arbitrage score and names MyFantasyLeague as the source", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    await expect(page.getByRole("heading", { name: "Arbitrage table" })).toBeVisible();
    await expect(page.getByText(/Deterministic market-gap baseline/)).toBeVisible();
    await expect(
      page.getByText(/fair rank against MyFantasyLeague ADP/),
    ).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/consensus adp/i);
    const table = page.getByRole("table", { name: /market-gap board/i });
    await expect(table.getByRole("columnheader", { name: "Score" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  test("explains the shared low-confidence condition once, from metadata", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    // The condition and what the label means are stated outright; the evidence is one click
    // away rather than three stacked panels above the board.
    await expect(page.getByText(/Every row on this board reads low market-data confidence/i)).toBeVisible();
    await expect(page.getByText(/not a probability that a player is a bargain/)).toBeVisible();
    await page.getByText("Why, and what the market evidence actually is").click();
    await expect(page.getByText(/125 drafts against the 300/)).toBeVisible();
    await expect(page.getByText(/median priced player here was selected in/)).toBeVisible();
  });

  test("renders a missing trend as collecting, never as zero", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    await page.getByText("Why, and what the market evidence actually is").click();
    await expect(page.getByText(/Trend collecting/).first()).toBeVisible();
    const table = page.getByRole("table", { name: /market-gap board/i });
    const trendCell = table.getByRole("row").nth(1).locator("td").nth(9);
    await expect(trendCell).toContainText("—");
    await expect(trendCell).not.toContainText(/flat|no movement/i);
  });

  test("switches the rail between bargains, premiums and all", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    await expect(page.getByRole("heading", { name: "Draft rail" })).toBeVisible();
    const rail = page.getByRole("radiogroup", { name: "Draft rail population" });
    const bargains = await page.locator("svg .rail-connector[data-kind='bargain']").count();
    expect(bargains).toBeGreaterThan(0);
    await expect(page.locator("svg .rail-connector[data-kind='premium']")).toHaveCount(0);

    await rail.getByRole("radio", { name: "Premiums" }).click();
    await expect(page).toHaveURL(/rail=premiums/);
    await expect(page.locator("svg .rail-connector[data-kind='bargain']")).toHaveCount(0);

    await rail.getByRole("radio", { name: "All" }).click();
    await expect(page).toHaveURL(/rail=all/);
    expect(await page.locator("svg .rail-connector").count()).toBeGreaterThan(bargains);
  });

  test("states bargain direction in words as well as sign", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    await expect(page.locator("svg text.rail-gap").first()).toContainText(/picks later|picks earlier/);
    await expect(page.getByText(/picks later than his fair rank/).first()).toBeAttached();
  });

  test("draws rail anchors at the arbitrage record's own numbers", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    const table = page.getByRole("table", { name: /market-gap board/i });
    const topRow = table.getByRole("row").nth(1);
    const name = (await topRow.locator("td").nth(1).textContent())?.trim() ?? "";
    const fair = (await topRow.locator("td").nth(4).textContent())?.trim() ?? "";
    const adp = (await topRow.locator("td").nth(5).textContent())?.trim() ?? "";
    const label = await page
      .locator("svg g.player-mark")
      .filter({ hasText: name.slice(0, 8) })
      .first()
      .getAttribute("aria-label");
    expect(label).toContain(`fair rank ${fair}`);
    expect(label).toContain(`ADP ${adp}`);
  });

  test("exports the filtered arbitrage rows", async ({ page }) => {
    await page.goto("/?view=arbitrage&position=qb");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: /Export filtered CSV/ }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("ffdraft-arbitrage-ppr-12-2026-08-21.csv");
  });
});

test.describe("player detail", () => {
  test("opens from a table row and discloses that status is annotation only", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Amon-Ra Bright" })).toBeVisible();
    await expect(dialog.getByText("Questionable")).toBeVisible();
    await expect(dialog.getByText("Hamstring").first()).toBeVisible();
    await expect(dialog.getByText(/not included in the projection or the model/)).toBeVisible();
    await expect(dialog).not.toContainText(/injury.adjusted|priced in|accounts for this injury/i);
  });

  test("closes on Escape and returns the page to the board", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Bijan Robinson", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
  });

  test("says nothing about health for a player with no designation", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Bijan Robinson", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/absence of a report, not a clearance/)).toBeVisible();
    await expect(dialog).not.toContainText(/\bhealthy\b/i);
  });

  test("handles a player with no status record at all", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Deebo Gray", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/No current status record was published/)).toBeVisible();
    await expect(dialog.getByText("Fair rank", { exact: true })).toBeVisible();
  });

  test("says a player has no current ADP rather than hiding him", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Zach Ertz", exact: true }).click();
    await expect(page.getByRole("dialog").getByText(/No current MyFantasyLeague ADP/)).toBeVisible();
  });

  test("opens from a chart mark with the keyboard", async ({ page }) => {
    await openBoard(page);
    const mark = page.getByRole("button", { name: /^Bijan Robinson,.*median simulated VORP/ });
    await mark.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog").getByRole("heading", { name: "Bijan Robinson" })).toBeVisible();
  });
});

test.describe("data and methodology", () => {
  test("reports the model, the sources and the limitations from metadata", async ({ page }) => {
    await page.goto("/?view=data");
    await expect(page.getByRole("heading", { name: "Current build" })).toBeVisible();
    await expect(page.getByText("intrinsic-cb-hurdle-v1").first()).toBeVisible();
    await expect(page.getByText("baseline · a0_rank_gap_v1")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Freshness and source status" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Current limitations" })).toBeVisible();
    await expect(page.getByText(/Exact tier edges are soft/)).toBeVisible();
    await expect(page.getByText(/Injury and roster status is annotation only/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sources and attribution" })).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/fantasypros|fantasycalc/i);
  });

  test("is reachable from the header status chip", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: /build note/ }).click();
    await expect(page).toHaveURL(/view=data/);
  });
});

test.describe("degraded artifacts", () => {
  test("keeps the tier board when the market artifact is gone", async ({ page }) => {
    await openBoard(page, "/scenario/no-market/");
    await expect(page.getByRole("table", { name: /Intrinsic tier board/ }).getByRole("row")).toHaveCount(11);
    await page.getByRole("tab", { name: "Arbitrage" }).click();
    await expect(page.getByText(/Market comparison unavailable/)).toBeVisible();
    await expect(page.getByText(/tier board is unaffected/)).toBeVisible();
  });

  test("keeps every model value when the status artifact is gone", async ({ page }) => {
    await openBoard(page, "/scenario/no-status/");
    await expect(page.locator(".status-badge")).toHaveCount(0);
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    await expect(table.getByRole("row").nth(1).locator("td").nth(7)).toHaveText("135.4");
    await page.goto("/scenario/no-status/?view=data");
    await expect(page.getByText("Degraded artifacts.")).toBeVisible();
    await expect(page.getByText(/annotations are absent/)).toBeVisible();
  });

  test("refuses an unsupported schema and renders no board", async ({ page }) => {
    await page.goto("/scenario/bad-schema/");
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("Incompatible data contract")).toBeVisible();
    await expect(page.getByText("2.0", { exact: true })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
  });
});

test.describe("project Pages base path", () => {
  test("loads assets, artifacts and CSV links under /jeisey-tiers/", async ({ page }) => {
    const requested: string[] = [];
    page.on("request", (request) => requested.push(new URL(request.url()).pathname));
    await openBoard(page, "/jeisey-tiers/");

    await expect(page.getByRole("table", { name: /Intrinsic tier board/ }).getByRole("row")).toHaveCount(11);
    expect(requested.some((path) => path.startsWith("/jeisey-tiers/assets/"))).toBe(true);
    expect(requested.some((path) => path === "/jeisey-tiers/data/tiers.json")).toBe(true);
    // No absolute `/data/...` assumption may survive under a base path.
    expect(requested.filter((path) => path.startsWith("/data/"))).toEqual([]);

    await expect(page.getByRole("link", { name: "Download full CSV" })).toHaveAttribute(
      "href",
      "/jeisey-tiers/data/tiers.csv",
    );
  });

  test("keeps query state on the base path across a reload", async ({ page }) => {
    await page.goto("/jeisey-tiers/?view=arbitrage&position=qb");
    await expect(page.getByRole("heading", { name: "Arbitrage table" })).toBeVisible();
    await page.reload();
    await expect(page).toHaveURL("/jeisey-tiers/?view=arbitrage&position=qb");
    await expect(page.getByRole("radio", { name: "QB" })).toHaveAttribute("aria-checked", "true");
  });
});

test.describe("accessibility", () => {
  test("keyboard reaches the controls, the tabs and the table in order", async ({ page }) => {
    await openBoard(page);
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: /Skip to the board/ })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: /build note/ })).toBeFocused();
    await page.keyboard.press("Tab");
    // The group's one tab stop is the *selected* option, per the roving-tabindex pattern.
    await expect(page.getByRole("radio", { name: "PPR", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("radio", { name: "12-team league" })).toBeFocused();
  });

  test("shows a visible focus ring on a chart mark", async ({ page }) => {
    await openBoard(page);
    const mark = page.getByRole("button", { name: /^Bijan Robinson,.*median simulated VORP/ });
    await mark.focus();
    const outline = await mark.evaluate((node) => getComputedStyle(node).outlineWidth);
    expect(Number.parseFloat(outline)).toBeGreaterThan(0);
  });

  test("gives both charts a text description and a table equivalent", async ({ page }) => {
    await openBoard(page);
    await expect(page.locator("svg[role='img'] desc").first()).toContainText(/table below carries the same values/);
    await page.goto("/?view=arbitrage");
    await expect(page.locator("svg[role='img'] desc").first()).toContainText(/same numbers/);
  });

  test("runs no animation when the viewer asks for reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openBoard(page);
    const durations = await page.evaluate(() =>
      [...document.querySelectorAll("*")]
        .map((node) => getComputedStyle(node).transitionDuration)
        .filter((value) => value !== "" && value !== "0s"),
    );
    // The stylesheet collapses every transition to 0.01ms under reduced motion.
    for (const duration of durations) expect(Number.parseFloat(duration)).toBeLessThan(0.001);
    await expect(page.locator("svg animate, svg animateTransform")).toHaveCount(0);
  });
});
