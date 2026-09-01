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

/**
 * The masthead's freshness chip, selected by the invariant half of its accessible name.
 *
 * Its visible label is the freshness *state* — "build note", "build is a day old", "build is
 * stale" — which depends on the wall clock at the moment the browser runs, so a test that
 * matches on it starts failing on a date nobody chose. Which label each age produces is
 * asserted directly, against an injected clock, in `tests/app.test.tsx`; a build served from
 * disk cannot be handed one. The tests below are about where the chip goes and where it sits
 * in the tab order, so they select the part of the name that never changes.
 */
function statusChip(page: Page) {
  return page.getByRole("button", { name: /Open the data and methodology view/ });
}

test.describe("default tier experience", () => {
  test("renders the board, the freshness stamp and the tier table", async ({ page }) => {
    await openBoard(page);
    await expect(page.getByText("Aug 21 · 10:38 AM ET")).toBeVisible();
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    await expect(table.getByRole("row")).toHaveCount(19);
    await expect(table.getByRole("row").nth(1)).toContainText("Bijan Robinson");
    await expect(page.getByText("Median simulated VORP", { exact: true })).toBeVisible();
  });

  test("presents tiers as soft groups with no hard boundary or cliff claim", async ({ page }) => {
    await openBoard(page);
    await expect(page.getByText(/exact tier edges are statistically soft/i)).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/value cliff/i);
    // Lane separation is a filled surface, never a stroked rule between tiers, and the tier
    // header's band is the tier's own P25-P75 span rather than a cut position (ADR-046).
    await expect(page.locator(".tier-lane")).toHaveCount(3);
    await expect(page.locator(".tier-head-band")).toHaveCount(3);
  });

  /**
   * The tier band and the player bars are one track, measured rather than assumed.
   *
   * "Adjacent tier bands overlap" is a claim about the measurement (ADR-035), and it is only
   * true of the *picture* if the band and the bars are drawn on the same pixels. Phase 9A
   * broke this twice while restyling — once by numbering the strip's grid columns off by one,
   * and once by naming a grid area `span`, which is a reserved keyword, so the rule was
   * dropped silently and the band shrank to two thirds of the track. Neither showed up in any
   * other check, and neither is visible without a ruler.
   */
  test("draws the tier band on exactly the track the player bars use", async ({ page }) => {
    await openBoard(page);
    for (const width of [1440, 900, 390]) {
      await page.setViewportSize({ width, height: 900 });
      const box = await page.evaluate(() => {
        const rect = (root: ParentNode | null, selector: string) => {
          const el = root?.querySelector(selector);
          if (el === null || el === undefined) return null;
          const r = el.getBoundingClientRect();
          // A `display: none` element still answers `querySelector` and reports a zero box.
          if (r.width === 0) return null;
          return { left: Math.round(r.left), right: Math.round(r.right) };
        };
        const lane = document.querySelector(".tier-lane");
        return {
          band: rect(lane, ".tier-head-band"),
          bar: rect(lane, ".board-row .row-interval"),
          // The tick strip is hidden in the stack variant, where artboard 2b has no shared
          // axis; where it *is* drawn it has to be the same track too.
          axis: rect(document, ".board-scale-track"),
        };
      });
      const at = `at ${String(width)}px`;
      expect(box.band, `no band ${at}`).not.toBeNull();
      expect(box.bar, `no bar ${at}`).not.toBeNull();
      expect(Math.abs((box.band?.left ?? 0) - (box.bar?.left ?? 0)), `band left ${at}`)
        .toBeLessThanOrEqual(1);
      expect(Math.abs((box.band?.right ?? 0) - (box.bar?.right ?? 0)), `band right ${at}`)
        .toBeLessThanOrEqual(1);
      if (box.axis !== null) {
        expect(Math.abs(box.axis.left - (box.bar?.left ?? 0)), `axis left ${at}`)
          .toBeLessThanOrEqual(1);
        expect(Math.abs(box.axis.right - (box.bar?.right ?? 0)), `axis right ${at}`)
          .toBeLessThanOrEqual(1);
      }
    }
  });

  test("collapses and expands a tier, and puts the open set in the URL", async ({ page }) => {
    await openBoard(page);
    const firstTier = page.locator(".tier-head").first();
    await expect(firstTier).toHaveAttribute("aria-expanded", "true");
    const openRows = await page.locator(".board-row").count();
    expect(openRows).toBeGreaterThan(0);

    await firstTier.click();
    await expect(page).toHaveURL(/tiers=/);
    await expect(firstTier).toHaveAttribute("aria-expanded", "false");
    expect(await page.locator(".board-row").count()).toBeLessThan(openRows);

    await page.getByRole("button", { name: /Expand all tiers/ }).click();
    await expect(page.locator(".tier-head[aria-expanded='false']")).toHaveCount(0);

    // Shareable: a reload lands on the same open set rather than the default.
    await page.reload();
    await expect(page.locator(".tier-head[aria-expanded='false']")).toHaveCount(0);
  });

  test("keeps the whole board reachable in the table even when every tier is collapsed", async ({
    page,
  }) => {
    await page.goto("/?tiers=none");
    await expect(page.locator(".board-row")).toHaveCount(0);
    const table = page.getByRole("table", { name: /Intrinsic tier board/ });
    await expect(table.getByRole("row")).toHaveCount(18 + 1);
  });

  test("expands from the default chart depth to the full board", async ({ page }) => {
    await openBoard(page);
    // The fixture board is shorter than the preview depth, so the control offers the full board
    // and the row count is unchanged — the point is that the chart never invents a different rank.
    const marksBefore = await page.locator(".board-row").count();
    await page.getByRole("button", { name: /Show full board/ }).click();
    await expect(page).toHaveURL(/board=full/);
    expect(await page.locator(".board-row").count()).toBe(marksBefore);
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

  test("states the market condition once, from metadata", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    // The condition and what the label means are stated outright, with the evidence beside
    // them as readouts rather than as three stacked panels above the board.
    await expect(
      page.getByText(/Every priced row on this board carries low market-data confidence/i),
    ).toBeVisible();
    await expect(page.getByText(/not a probability that a player is a bargain/)).toBeVisible();
    await expect(page.getByText(/125 drafts against the 300/)).toBeVisible();
    await expect(page.getByText(/drafts per player/)).toBeVisible();
    await expect(page.getByText(/below the frozen bar/)).toBeVisible();
  });

  test("renders a missing trend as collecting, never as zero", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    await expect(page.locator(".market-fact-value").filter({ hasText: "collecting" })).toBeVisible();
    const table = page.getByRole("table", { name: /market-gap board/i });
    const trendCell = table.getByRole("row").nth(1).locator("td").nth(9);
    await expect(trendCell).toContainText("—");
    await expect(trendCell).not.toContainText(/flat|no movement/i);
  });

  test("switches the rail between bargains, premiums and all", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    await expect(page.getByRole("heading", { name: "Draft rail" })).toBeVisible();
    const rail = page.getByRole("radiogroup", { name: "Draft rail population" });
    const bargains = await page.locator(".rail-fill[data-kind='bargain']").count();
    expect(bargains).toBeGreaterThan(0);
    await expect(page.locator(".rail-fill[data-kind='premium']")).toHaveCount(0);

    await rail.getByRole("radio", { name: "Premiums" }).click();
    await expect(page).toHaveURL(/rail=premiums/);
    await expect(page.locator(".rail-fill[data-kind='bargain']")).toHaveCount(0);

    await rail.getByRole("radio", { name: "All" }).click();
    await expect(page).toHaveURL(/rail=all/);
    expect(await page.locator(".rail-fill").count()).toBeGreaterThan(bargains);
  });

  test("states bargain direction in words as well as sign", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    // Direction survives without colour: a side, a word on the row, and the full sentence in
    // the row's accessible name.
    await expect(page.locator(".rail-gap-word").first()).toHaveText(/later|earlier|even/);
    await expect(page.getByText(/picks later than his fair rank/).first()).toBeAttached();
    await expect(page.locator(".rail-row").first()).toHaveAttribute(
      "aria-label",
      /picks (later|earlier) than his fair rank/,
    );
  });

  test("draws rail rows at the arbitrage record's own numbers", async ({ page }) => {
    await page.goto("/?view=arbitrage");
    const table = page.getByRole("table", { name: /market-gap board/i });
    const topRow = table.getByRole("row").nth(1);
    const name = (await topRow.locator("td").nth(1).textContent())?.trim() ?? "";
    const fair = (await topRow.locator("td").nth(4).textContent())?.trim() ?? "";
    const adp = (await topRow.locator("td").nth(5).textContent())?.trim() ?? "";
    const label = await page
      .locator(".rail-row")
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
  test("opens from a table row and marks status as annotation only", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Amon-Ra Bright" })).toBeVisible();
    await expect(dialog.getByText("Questionable", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Hamstring").first()).toBeVisible();
    await expect(dialog.getByText("Annotation only — not a model input.")).toBeVisible();
    await expect(dialog).not.toContainText(/injury.adjusted|priced in|accounts for this injury/i);
    // The paragraph that used to sit here now lives once in Data.
    await expect(dialog).not.toContainText(/The board above was produced without any of these fields/);
  });

  test("leads with the readouts a drafter needs, not with methodology", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
    const dialog = page.getByRole("dialog");
    for (const label of [
      "Fair rank",
      "Position rank",
      "Tier",
      "Median VORP",
      "Uncertainty",
      "MFL ADP",
      "Value gap",
      "Arbitrage score",
      "Market trend",
      "Market data",
    ]) {
      await expect(dialog.getByText(label, { exact: true })).toBeVisible();
    }
    // The three paragraphs the Phase-8 review named are gone from the card.
    await expect(dialog).not.toContainText(/cannot filter drafts to this exact scoring/);
    await expect(dialog).not.toContainText(/It is not a probability that the player is a bargain/);
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
    // Phase 9A took the design source's own status headline in place of Phase 8's
    // "None reported" field. Same claim, same number of words, reads as a sentence.
    await expect(dialog.getByText("No injury designation reported")).toBeVisible();
    await expect(dialog).not.toContainText(/\bhealthy\b/i);
    await expect(dialog).not.toContainText(/\bcleared\b/i);
  });

  test("handles a player with no status record at all", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Deebo Gray", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/No status record was published for this player/)).toBeVisible();
    await expect(dialog.getByText("Fair rank", { exact: true })).toBeVisible();
  });

  test("returns focus to the row that opened it", async ({ page }) => {
    await openBoard(page);
    const trigger = page.getByRole("button", { name: "Bijan Robinson", exact: true });
    await trigger.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("says a player has no current ADP rather than hiding him", async ({ page }) => {
    await openBoard(page);
    await page.getByRole("button", { name: "Zach Ertz", exact: true }).click();
    await expect(page.getByRole("dialog").getByText(/No current MyFantasyLeague ADP/)).toBeVisible();
  });

  test("opens from a board row with the keyboard", async ({ page }) => {
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
    await statusChip(page).click();
    await expect(page).toHaveURL(/view=data/);
  });
});

test.describe("degraded artifacts", () => {
  test("keeps the tier board when the market artifact is gone", async ({ page }) => {
    await openBoard(page, "/scenario/no-market/");
    await expect(page.getByRole("table", { name: /Intrinsic tier board/ }).getByRole("row")).toHaveCount(19);
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

    await expect(page.getByRole("table", { name: /Intrinsic tier board/ }).getByRole("row")).toHaveCount(19);
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

/*
 * The Phase-9B release treatment: the owner's logo in place of the typeset wordmark, a favicon
 * generated from the same artwork, and both export controls centring their label.
 *
 * Each of the three is asserted the way it can actually fail. The logo is a *measured* aspect
 * ratio rather than a rendered `<img>`, because a stretched logo still renders. The favicon is
 * a *fetched status* at the project base path, because a root-relative href resolves perfectly
 * in development and 404s only once deployed. The label is a *geometry comparison* against its
 * own button box, because the defect the owner reported — an anchor that is `display: inline`,
 * where `height` does nothing and `text-align` never reaches the text — is invisible to any
 * assertion on the string.
 */
test.describe("release brand and export treatment", () => {
  const VIEWPORTS = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "tablet", width: 900, height: 1000 },
    { name: "mobile", width: 390, height: 844 },
  ] as const;

  test("shows the logo as the only masthead brand, beside freshness and status", async ({
    page,
  }) => {
    await openBoard(page);
    const logo = page.locator("header.masthead img.masthead-logo");
    await expect(logo).toBeVisible();
    await expect(logo).toHaveAttribute("alt", "Jeisey Tiers");
    // The image is the document's h1, so the page has one top-level heading and its
    // accessible name is the product.
    await expect(page.getByRole("heading", { level: 1, name: "Jeisey Tiers" })).toBeVisible();

    // The Phase-9A wordmark is gone, not merely hidden behind the picture.
    await expect(page.locator("header.masthead")).not.toContainText("jeisey-tiers");
    await expect(page.locator("header.masthead")).not.toContainText("Tiers & arbitrage");
    await expect(page.locator(".wordmark, .wordmark-sub, .masthead-glyph")).toHaveCount(0);

    // Everything the masthead carried besides the brand still does.
    await expect(page.getByText("Aug 21 · 10:38 AM ET")).toBeVisible();
    await expect(statusChip(page)).toBeVisible();
    await statusChip(page).click();
    await expect(page).toHaveURL(/view=data/);
    await expect(page.getByRole("heading", { name: "What this is" })).toBeVisible();
  });

  for (const viewport of VIEWPORTS) {
    test(`keeps the logo, freshness and status on one masthead at ${viewport.name}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await openBoard(page);

      const logo = page.locator("img.masthead-logo");
      const box = await logo.boundingBox();
      expect(box, "the logo must be laid out").not.toBeNull();
      if (box === null) return;

      // The artwork is 434x145. A rendered ratio that drifts from it is a stretched logo.
      expect(box.width / box.height).toBeCloseTo(434 / 145, 1);
      // Big enough to read as a brand, small enough not to own the viewport.
      expect(box.height).toBeGreaterThanOrEqual(32);
      expect(box.width).toBeLessThanOrEqual(viewport.width * 0.6);

      // Freshness and status stay on screen rather than being pushed out by the mark.
      for (const target of [page.getByText("Aug 21 · 10:38 AM ET"), statusChip(page)]) {
        const meta = await target.boundingBox();
        expect(meta).not.toBeNull();
        if (meta === null) continue;
        expect(meta.x).toBeGreaterThanOrEqual(0);
        expect(meta.x + meta.width).toBeLessThanOrEqual(viewport.width + 1);
      }

      // The masthead may not be what makes the document scroll sideways.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }

  test("serves the favicon under the project base path, not only the root", async ({ page }) => {
    await page.goto("/jeisey-tiers/");
    const hrefs = await page
      .locator('link[rel="icon"], link[rel="apple-touch-icon"]')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("href") ?? ""));

    expect(hrefs.length).toBeGreaterThan(0);
    for (const href of hrefs) {
      // A root-relative href is the failure this test exists for: it works locally and 404s
      // on Pages. Every icon must sit under the base the page was served from.
      expect(href.startsWith("/jeisey-tiers/")).toBe(true);
      const response = await page.request.get(href);
      expect(response.status(), `${href} must be served`).toBe(200);
      expect(Number(response.headers()["content-length"] ?? "1")).toBeGreaterThan(0);
    }

    await expect(page).toHaveTitle(/Jeisey Tiers/);
  });

  for (const viewport of [VIEWPORTS[0], VIEWPORTS[2]]) {
    test(`centres both export labels at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await openBoard(page);

      const controls = [
        page.getByRole("link", { name: "Download full CSV" }),
        page.getByRole("button", { name: /Export filtered CSV/ }),
      ];

      for (const control of controls) {
        const offsets = await control.evaluate((node) => {
          const frame = node.getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(node);
          const label = range.getBoundingClientRect();
          return {
            dx: (label.left + label.right) / 2 - (frame.left + frame.right) / 2,
            dy: (label.top + label.bottom) / 2 - (frame.top + frame.bottom) / 2,
            labelWidth: label.width,
            frameHeight: frame.height,
          };
        });

        expect(offsets.labelWidth, "the label must have been measured").toBeGreaterThan(0);
        // Half a track of trailing letter-spacing is the only offset allowed; anything larger
        // is a layout bug rather than typography.
        expect(Math.abs(offsets.dx)).toBeLessThanOrEqual(1.5);
        expect(Math.abs(offsets.dy)).toBeLessThanOrEqual(1.5);
        // The frame is a real control box, which is what an `display: inline` anchor was not.
        expect(offsets.frameHeight).toBeGreaterThanOrEqual(36);
      }
    });
  }

  test("keeps a visible focus ring on both export controls", async ({ page }) => {
    await openBoard(page);
    for (const control of [
      page.getByRole("link", { name: "Download full CSV" }),
      page.getByRole("button", { name: /Export filtered CSV/ }),
    ]) {
      await control.focus();
      await expect(control).toBeFocused();
      const width = await control.evaluate((node) => getComputedStyle(node).outlineWidth);
      expect(Number.parseFloat(width)).toBeGreaterThan(0);
    }
  });
});

test.describe("accessibility", () => {
  test("keyboard reaches the controls, the tabs and the table in order", async ({ page }) => {
    await openBoard(page);
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: /Skip to the board/ })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(statusChip(page)).toBeFocused();
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
    await expect(page.locator(".tier-board .visually-hidden").first()).toContainText(
      /table below carries the same values/,
    );
    await page.goto("/?view=arbitrage");
    await expect(page.locator(".draft-rail .visually-hidden").first()).toContainText(/same numbers/);
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
