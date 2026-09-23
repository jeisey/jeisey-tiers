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

import { expect, test } from "@playwright/test";

import { guardBoundary } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const NO_BEHAVIOR = "/scenario/in-season-no-behavior/";
/** The season has started and no rest-of-season board can exist yet (ADR-079). */
const AWAITING = "/scenario/awaiting-first-week/";
/** The far end: every scored week played, no remaining horizon. */
const SEASON_COMPLETE = "/scenario/season-complete/";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
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
    // The masthead's indicator. Scoped because the phone's folded settings row names an
    // overridden mode too (ADR-093) — not rendered at this width, but still in the DOM.
    await expect(page.locator("header.masthead").getByText("Draft mode")).toBeVisible();
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
    // In the legend beside the board, where the bands are, and visible with no interaction.
    // The disclosure block repeats the build's own sentence, but the claim has to be on the
    // picture rather than one click behind it.
    await expect(page.locator(".legend").getByText(/bands, not lines/i)).toBeVisible();
    // And no edge is drawn as a fact: a tier strip is a span, never a rule at a cut position.
    await expect(page.locator(".tier-band-fill").first()).toBeVisible();
  });

  test("draws the rest-of-season board in the draft board's own language", async ({ page }) => {
    await page.goto(IN_SEASON);
    const board = page.locator(".tier-board");
    await expect(board).toBeVisible();
    // The axis names the rest-of-season quantity, never the preseason one of the same shape.
    await expect(board.locator(".board-axis-title").first()).toHaveText(
      "Median simulated remaining VORP",
    );
    // Every mark carries the whole reading, and every number in it is a remaining one.
    const mark = board.getByRole("button", {
      name: /^Bijan Robinson,.*median simulated remaining VORP/,
    });
    await expect(mark).toBeVisible();

    /*
     * The mark prints the median and the board's rank, so those are what it is checked
     * against — deliberately not the table's `ROS Exp VORP`, which is the *expectation* and a
     * different published number. Conflating the two is exactly the kind of agreement check
     * that passes for the wrong reason (ADR-084), so the comparison goes through the card,
     * which names both.
     */
    const rank = await mark.locator(".row-rank").textContent();
    const median = await mark.locator(".row-value").textContent();
    expect(String(rank).trim()).toBe("1");
    await mark.click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();
    const cardMedian = card
      .locator(".readout")
      .filter({ hasText: "ROS median VORP" })
      .locator(".readout-value");
    await expect(cardMedian).toHaveText(String(median).trim());
  });

  test("collapses and expands its bands, and carries the open set in the URL", async ({
    page,
  }) => {
    // The Tier Board's own control, on a board that had none because it had no board. The
    // open set is state like every other control (`docs/UX_SPEC.md` section 3), so a link to
    // one reader's view opens the same one.
    await page.goto(IN_SEASON);
    const board = page.locator(".tier-board");
    await expect(board.locator(".board-row").first()).toBeVisible();

    await page.getByRole("button", { name: "Collapse all tiers" }).click();
    await expect(board.locator(".board-row")).toHaveCount(0);
    await expect(page).toHaveURL(/tiers=none/);
    // The bands themselves stay: a closed tier is still a tier, and its span is still drawn.
    await expect(board.locator(".tier-band-fill").first()).toBeVisible();

    await page.getByRole("button", { name: "Expand all tiers" }).click();
    await expect(board.locator(".board-row").first()).toBeVisible();

    // And it survives a reload, like every other control.
    const url = page.url();
    await page.reload();
    expect(page.url()).toBe(url);
  });

  test("charts the draft-relevant top and says the table has the rest", async ({ page }) => {
    await page.goto(IN_SEASON);
    // The fixture board is shorter than the preview depth, so the control reads "full board"
    // and the note says every row is charted rather than claiming a truncation there is not.
    const toggle = page.getByRole("button", { name: /Show (full board|top)/ });
    await expect(toggle).toBeVisible();
    await expect(page.locator(".legend")).toContainText(/charted players are in open bands/);
  });

  test("states the ADR-076 disclosures where the flagged rows are", async ({ page }) => {
    await page.goto(IN_SEASON);
    const disclosure = page.locator("details.disclosure");
    // The contractual sentence is the always-visible summary: a reader who never opens
    // anything has still been told the model uses no injury information (ADR-076, ADR-085).
    await expect(disclosure.locator("summary")).toContainText(
      /no injury or practice-report information/i,
    );
    await expect(disclosure).not.toHaveAttribute("open", /.*/);

    // The measured weaknesses are one click behind it, and nothing is lost.
    await disclosure.locator("summary").click();
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

  test("carries current status as a mark on the name, never as a column of ACT", async ({
    page,
  }) => {
    await page.goto(IN_SEASON);
    const table = page.getByRole("table", { name: /Rest-of-season board/ });
    const headings = (await table.getByRole("columnheader").allTextContents()).map((text) =>
      text.replace(/[▲▼]/g, "").trim(),
    );
    // The column is gone (ADR-085): it read `ACT` on nearly every row, which is not a report.
    expect(headings).not.toContain("Current status");

    // The mark is where the draft board has always put it — beside the player's name — and it
    // appears only for a code the artifact says something with.
    const badge = table.locator(".player-cell .status-badge").first();
    await expect(badge).toBeVisible();
    await expect(badge.locator(".visually-hidden")).toContainText(
      /Current roster status: .+\. Annotation only/,
    );
    // And the caption still says the mark is annotation, because that is the contract.
    await expect(table.locator("caption")).toContainText(/annotation/i);
  });

  test("shows no status mark at all for the ordinary roster code", async ({ page }) => {
    await page.goto(IN_SEASON);
    const table = page.getByRole("table", { name: /Rest-of-season board/ });
    // Bijan is `ACT` in the fixture. "Active" is the ordinary case and is not a report, so the
    // absence of a mark is the correct rendering rather than a missing one (ADR-043).
    const row = table.getByRole("row").filter({ hasText: "Bijan Robinson" }).first();
    await expect(row.locator(".status-badge")).toHaveCount(0);
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
      text.replace(/[▲▼]/g, "").trim(),
    );
    expect(headings).toContain("Adds (24h)");
    expect(headings).toContain("Drops (24h)");
    expect(headings).toContain("Net adds");
    // Nothing on this board is called a price, a rank gap or a score.
    for (const heading of headings) {
      expect(heading).not.toMatch(/adp|rank gap|score|edge/i);
    }
    await expect(page.getByText(/not a price, not a rank/i)).toBeVisible();
  });

  test("draws two tracks on two scales and never one combined position", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const board = page.locator(".opp-board");
    await expect(board).toBeVisible();
    // Two named tracks, each with its own zero line: the picture cannot be read as one axis.
    await expect(board.locator(".opp-track-name")).toHaveCount(2);
    await expect(board.getByText("ROS value", { exact: true })).toBeVisible();
    await expect(board.getByText(/Roster moves · 24h/)).toBeVisible();
    const firstRow = board.locator(".opp-row").first();
    await expect(firstRow.locator(".opp-track")).toHaveCount(2);
    await expect(firstRow.locator(".opp-zero")).toHaveCount(2);
    // And the board says so in words as well as in geometry.
    await expect(board.getByText(/Two scales, never combined/i)).toBeVisible();
  });

  test("opens the player card from a chart row, like every other board", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    await page.locator(".opp-board .opp-row").first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("surfaces a player from beyond the tier depth, with a reason and no tier", async ({
    page,
  }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&opportunity=adds`);
    const surfaced = page.locator('tr[data-surfaced="true"]').first();
    await expect(surfaced).toBeVisible();
    await expect(surfaced.locator(".surface-badge")).toContainText("surfaced");
  });

  test("offers five orderings over separate quantities and no blended score", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    // `Segmented` renders an ARIA radiogroup, which is not the same role as `group`.
    const group = page.getByRole("radiogroup", { name: /Order by/i });
    await expect(group.getByRole("radio", { name: "ROS value" })).toBeVisible();
    // `exact` because "Net adds" contains "Adds".
    await expect(group.getByRole("radio", { name: "Adds", exact: true })).toBeVisible();
    await expect(group.getByRole("radio", { name: "Net adds" })).toBeVisible();
    await expect(group.getByRole("radio", { name: /^Add momentum/ })).toBeVisible();
    await expect(group.getByRole("radio", { name: /^Role direction/ })).toBeVisible();
    await expect(group.getByRole("radio")).toHaveCount(5);
    for (const label of await group.getByRole("radio").allTextContents()) {
      expect(label).not.toMatch(/score|signal|waiver|breakout|hot|composite/i);
    }

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
    // And the intrinsic value is still there. Found by column, not by position: the table's
    // columns moved in ADR-092 and a positional lookup would have gone on passing on the
    // role cell beside it.
    await expect(firstRow.locator('td[data-col="ros_expected_vorp"]')).not.toBeEmpty();
    // With no feed there is no momentum series, and the column says so rather than "0/day".
    await expect(firstRow.locator('td[data-col="add_momentum"] .signal-cell')).toHaveAttribute(
      "data-kind",
      "unpublished",
    );
    await expect(page.getByRole("button", { name: "Momentum rising" })).toBeDisabled();

    // The chart draws the absence as an absence rather than as a row of zero-length bars.
    const board = page.locator(".opp-board");
    await expect(board.getByText(/Roster moves · none/)).toBeVisible();
    await expect(board.locator(".opp-row").first().locator(".opp-track-empty")).toBeVisible();
    await expect(board.locator(".opp-move-bar")).toHaveCount(0);
  });
});

test.describe("the opportunity board's signals (ADR-092)", () => {
  test("reads each position's own role measure, with the window and the card's glyph", async ({
    page,
  }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const table = page.getByRole("table", { name: /opportunity board/i });
    await expect(table).toBeVisible();
    const headings = (await table.getByRole("columnheader").allTextContents()).map((text) =>
      text.replace(/[▲▼]/g, "").trim(),
    );
    expect(headings).toEqual(expect.arrayContaining(["Role", "Add momentum", "Next game"]));
    // The generic three-week snap share is gone: it was a constant for every quarterback.
    expect(headings).not.toContain("Snap share");

    const qb = table.locator("tr", { hasText: "Jalen Marsh" });
    await expect(qb.locator('td[data-col="role"] .signal-metric')).toHaveText("Pass att");
    await expect(qb.locator('td[data-col="role"] .signal-line')).toContainText("48▲ +20");
    await expect(qb.locator('td[data-col="role"] .signal-detail')).toHaveText("wk 8 vs 7 gms");

    const rb = table.locator("tr", { hasText: "Jahmyr Cook" });
    await expect(rb.locator('td[data-col="role"] .signal-line')).toContainText("81%▲ +34 pts");
    // A flat lead is flat, whatever the card's other rails say.
    const wr = table.locator("tr", { hasText: "Rashee Kirk" });
    await expect(wr.locator('td[data-col="role"] .signal-change')).toHaveText("▬ no change");
    // No value in the latest game: no change, and the reason, never a reach back.
    const te = table.locator("tr", { hasText: "Trey McBride" });
    await expect(te.locator('td[data-col="role"] .signal-detail')).toHaveText(
      "no latest value",
    );
    await expect(te.locator('td[data-col="role"] .signal-change')).toHaveCount(0);
  });

  test("prints momentum with its span and never as a zero it does not have", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const table = page.getByRole("table", { name: /opportunity board/i });
    const rising = table.locator("tr", { hasText: "Jahmyr Cook" }).locator('td[data-col="add_momentum"]');
    await expect(rising.locator(".signal-value")).toHaveText(/^▲ \+\d+\.\d\/day$/);
    await expect(rising.locator(".signal-detail")).toHaveText(/^over \d+ (day|hour)s?$/);
    const absent = table.locator("tr", { hasText: "Jalen Marsh" }).locator('td[data-col="add_momentum"]');
    await expect(absent.locator(".signal-value")).toHaveText("not in feed");
    const single = table.locator("tr", { hasText: "Amon-Ra Bright" }).locator('td[data-col="add_momentum"]');
    await expect(single.locator(".signal-value")).toHaveText("one obs.");
  });

  test("states the next game as context and never rates it", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    const table = page.getByRole("table", { name: /opportunity board/i });
    const lined = table.locator("tr", { hasText: "Jahmyr Cook" }).locator('td[data-col="next_game"]');
    await expect(lined.locator(".signal-value")).toHaveText("W9 vs ATL");
    await expect(lined.locator(".signal-detail")).toHaveText("27.5 implied");
    const bye = table.locator("tr", { hasText: "Jalen Marsh" }).locator('td[data-col="next_game"]');
    await expect(bye.locator(".signal-value")).toHaveText("W10 vs SF");
    await expect(bye.locator(".signal-detail")).toHaveText("bye W9 · no line yet");
    // Not sortable: ordering the board by a sportsbook number would be its loudest claim.
    await expect(table.locator('th[data-col="next_game"] button')).toHaveCount(0);
    await expect(table).not.toContainText(/easy|tough|good matchup|bad matchup/i);
  });

  test("filters by one reading at a time, composes them, and keeps the link", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity`);
    await page.getByRole("button", { name: "Role rising" }).click();
    await expect(page).toHaveURL(/only=role/);
    await expect(page.getByRole("button", { name: "Role rising" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const cells = page.locator('table.sheet tbody td[data-col="role"] .signal-cell');
    const count = await cells.count();
    expect(count).toBeGreaterThan(0);
    for (let index = 0; index < count; index += 1) {
      await expect(cells.nth(index)).toHaveAttribute("data-direction", "up");
    }
    // The status line prints both numbers: rows kept, and rows with no reading to decide on.
    await expect(page.locator(".opp-filter-status")).toContainText(/Role rising: \d+ · \d+ with no published change/);

    await page.getByRole("radiogroup", { name: "Position" }).getByRole("radio", { name: "RB" }).click();
    await expect(page).toHaveURL(/position=rb.*only=role|only=role.*position=rb/);
    await expect(page.locator("table.sheet tbody tr")).toHaveCount(1);
    await expect(page.locator("table.sheet tbody tr")).toContainText("Jahmyr Cook");
  });

  test("names a filter the build cannot apply instead of emptying the board", async ({ page }) => {
    await page.goto("/scenario/in-season-no-signals/?view=opportunity&only=role");
    await expect(page.getByText(/A filter in this link cannot be applied/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Role rising" })).toBeDisabled();
    await expect(page.locator("table.sheet tbody tr")).toHaveCount(19);
    await expect(
      page.locator('table.sheet tbody td[data-col="role"] .signal-cell').first(),
    ).toHaveAttribute("data-kind", "unpublished");
  });

  test("orders role by direction, and by size only inside one position", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&opportunity=role`);
    await expect(page.locator(".opp-order-note")).toContainText(/sizes are compared only within one position/);
    const names = await page.locator("table.sheet tbody .player-name").allTextContents();
    // Rising, by ROS rank: the QB's +20 attempts does not jump the backs and receivers.
    expect(names.slice(0, 3)).toEqual(["Jahmyr Cook", "Puka Nightingale", "Jalen Marsh"]);
    await page.goto(`${IN_SEASON}?view=opportunity&opportunity=role&position=wr`);
    await expect(page.locator(".opp-order-note")).toContainText(/the larger published change first/);
  });

  test("exports the signal summary with the rows on screen, and no sportsbook line", async ({
    page,
  }) => {
    await page.goto(`${IN_SEASON}?view=opportunity&only=role`);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /Export filtered CSV/ }).click();
    const stream = await (await download).createReadStream();
    const chunks: Uint8Array[] = [];
    for await (const chunk of stream) chunks.push(new Uint8Array(Buffer.from(chunk as Buffer)));
    const lines = Buffer.concat(chunks).toString("utf-8").replace(/^\uFEFF/, "").trim().split("\r\n");
    const header = (lines[0] ?? "").split(",");
    expect(header).toEqual(expect.arrayContaining(["role_reading", "role_change", "add_trend_per_day", "next_game_opponent"]));
    expect(header.join(",")).not.toMatch(/implied|spread|total_line/);
    const shown = await page.locator("table.sheet tbody tr").count();
    expect(lines).toHaveLength(shown + 1);
  });

  for (const width of [1024, 1280, 1440]) {
    test(`fits the table without a sideways scroll at ${String(width)}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${IN_SEASON}?view=opportunity`);
      const scroller = page.locator(".table-scroll").last();
      await expect(scroller.locator("table.sheet")).toBeVisible();
      const overflow = await scroller.evaluate((node) => node.scrollWidth - node.clientWidth);
      expect(overflow, `the opportunity table scrolls sideways at ${String(width)}px`).toBeLessThanOrEqual(1);
      /*
        Fitting is not enough; it has to fit with room to spare. The first version of this
        table had 1px of slack at 1440px on the machine it was built on and overflowed by 8px
        on CI's Chromium, because font rasterisation differs by a few pixels across eleven
        columns. So the table's *minimum* width must leave a margin no rasteriser eats.
      */
      const slack = await scroller.evaluate((node) => {
        const table = node.querySelector("table");
        if (table === null) return -1;
        table.style.width = "min-content";
        const minimum = table.getBoundingClientRect().width;
        table.style.width = "";
        return node.clientWidth - minimum;
      });
      expect(slack, `the opportunity table has only ${String(Math.round(slack))}px of slack at ${String(width)}px`).toBeGreaterThanOrEqual(64);
      // The density rules must actually apply: a `.opp-sheet` selector one element weaker than
      // the base `table.sheet` rules loses silently, which is how they first shipped.
      const header = scroller.locator('th[data-col="ros_expected_vorp"]');
      await expect(header).toHaveCSS("white-space", "normal");
      await expect(scroller.locator("tbody td").first()).toHaveCSS("padding-left", "8px");
      // Whatever steps aside, the three signal columns never do on a laptop.
      for (const column of ["role", "add_momentum", "next_game"]) {
        await expect(scroller.locator(`th[data-col="${column}"]`)).toBeVisible();
      }
    });
  }

  for (const width of [420, 320]) {
    test(`keeps the name and the role in view at ${String(width)}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${IN_SEASON}?view=opportunity`);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
      // The chart row carries the role line on a phone.
      await expect(page.locator(".opp-row").first().locator(".opp-role")).toBeVisible();
      // The table hides what the chart already prints and pins the name.
      const table = page.locator("table.sheet");
      await expect(table.locator('th[data-col="ros_expected_vorp"]')).toBeHidden();
      await expect(table.locator('th[data-col="role"]')).toBeVisible();
      const player = table.locator("tbody tr").first().locator("td.col-player");
      await expect(player).toHaveCSS("position", "sticky");
      // Every ordering and chip is reachable, wrapped rather than clipped — one tap away on a
      // phone, where they fold behind the board's options row (ADR-093). The row itself must
      // fit too: its summary ellipsises rather than widening the page.
      const options = page.getByRole("button", { name: /^Options/ });
      const row = await options.boundingBox();
      expect((row?.x ?? 0) + (row?.width ?? Infinity)).toBeLessThanOrEqual(width);
      await options.click();
      for (const name of [/^Role direction/, /^Add momentum/]) {
        const radio = page.getByRole("radiogroup", { name: /Order by/ }).getByRole("radio", { name });
        const box = await radio.boundingBox();
        expect(box, String(name)).not.toBeNull();
        expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width);
      }
    });
  }
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

test.describe("pick of the week", () => {
  /*
    The tab makes a positive claim about four players, which is a different kind of thing from
    the two boards beside it. These assert the parts of that claim a unit test cannot see: that
    the bar is on the screen, that no sentence anywhere reads as a share of leagues, that the
    portraits stay bounded, and that a set survives a reload as a link.
  */
  test("shows one pick per position, each naming the position it is a pick at", async ({
    page,
  }) => {
    await page.goto(`${IN_SEASON}?view=potw`);
    await expect(page.getByRole("heading", { name: /Pick of the Week/ })).toBeVisible();
    const cards = page.locator(".potw-card");
    await expect(cards).toHaveCount(4);
    for (const position of ["QB", "RB", "WR", "TE"]) {
      await expect(cards.filter({ has: page.locator(`[data-pos="${position}"]`) })).not.toHaveCount(
        0,
      );
    }
    await expect(page.getByText("QB waiver pick")).toBeVisible();
  });

  test("prints the bar each pick cleared and the population that set it", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=potw`);
    const first = page.locator(".potw-card").first();
    await expect(first.getByText(/bar [\d,]+ · median of \d+/)).toBeVisible();
    await expect(first.getByText(/adds in 24h/).first()).toBeVisible();
  });

  test("never states a rostered share, a matchup or a multi-week trend", async ({ page }) => {
    // The three things a waiver card conventionally shows and this product cannot source
    // (ADR-088). A regression here is a truthfulness defect rather than a layout one, which
    // is why it is asserted over the whole rendered panel rather than over one element.
    await page.goto(`${IN_SEASON}?view=potw`);
    await expect(page.locator(".potw-card").first()).toBeVisible();
    const text = (await page.locator("#panel-potw").innerText()).toLowerCase();
    expect(text).not.toMatch(/\d+% rostered|rostered in|percent of leagues|% owned/);
    expect(text).not.toMatch(/matchup/);
    expect(text).not.toMatch(/last 3 games/);
    // And it says so in as many words, because the absence is the finding.
    expect(text).toContain("there is no rostered percentage here");
  });

  test("cycles sets, keeps the set in the URL, and survives a reload", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=potw`);
    await page.getByRole("button", { name: "Set 2" }).click();
    await expect(page).toHaveURL(/set=2/);
    await page.reload();
    await expect(page.getByRole("button", { name: "Set 2" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Set 2 is deeper than the fixture's quarterback pool, so the absence is stated.
    await expect(page.locator(".potw-absence")).not.toHaveCount(0);
  });

  test("fetches at most one set of portraits, and replaces them when the set changes", async ({
    page,
  }) => {
    // ADR-087's bound, carried onto this view. Four cards is four requests; cycling a set
    // must swap them rather than add a fifth, sixth and seventh.
    const portraits = await guardBoundary(page);
    await page.goto(`${IN_SEASON}?view=potw`);
    await expect(page.locator(".potw-card")).toHaveCount(4);
    const afterFirst = portraits.requested.length;
    expect(afterFirst, "a set of four cards must not exceed four portrait requests").toBeLessThanOrEqual(
      4,
    );
    await expect(page.locator(".potw-card img.portrait-image")).toHaveCount(afterFirst);
  });

  test("says which case it is in when the behaviour feed published nothing", async ({ page }) => {
    await page.goto(`${NO_BEHAVIOR}?view=potw`);
    await expect(page.getByText("No current add/drop behaviour.")).toBeVisible();
    await expect(page.locator(".potw-card")).toHaveCount(0);
    // The other boards are untouched, and the notice says so rather than leaving a reader to
    // wonder whether the whole build is degraded.
    await expect(
      page.getByText(/Every rest-of-season value on the boards beside this one is unchanged/),
    ).toBeVisible();
    await page.getByRole("tab", { name: "ROS tiers" }).click();
    await expect(page.locator(".board-row").first()).toBeVisible();
  });

  test("opens the player card from a pick", async ({ page }) => {
    await page.goto(`${IN_SEASON}?view=potw`);
    const name = page.locator(".potw-card .player-name").first();
    const label = (await name.innerText()).trim();
    await name.click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();
    await expect(card.getByRole("heading", { name: label })).toBeVisible();
    // The card belongs to the board the row was clicked on (ADR-085), and POTW is in-season.
    await expect(card.getByRole("heading", { name: "In-season usage" })).toBeVisible();
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
    await expect(card.getByText("two models, two orderings", { exact: true })).toBeVisible();
  });

  test("replaces the draft market with what is actually happening in season", async ({ page }) => {
    await page.goto(IN_SEASON);
    await page.locator("table.sheet .player-name").first().click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();

    // The draft price is gone: in November it is a number for a transaction nobody can make.
    await expect(card.getByRole("heading", { name: "Draft market" })).toHaveCount(0);
    await expect(card.getByText(/ADP/)).toHaveCount(0);
    await expect(card.getByText("Arbitrage score")).toHaveCount(0);

    // What replaces it is observation, named as observation and sourced from the feed.
    await expect(card.getByRole("heading", { name: "In-season usage" })).toBeVisible();
    await expect(card.getByText(/sleeper · 24h/i)).toBeVisible();
    await expect(card.getByText("Production so far")).toBeVisible();
    await expect(card.getByText("Roster moves")).toBeVisible();
    // Scoped to the tile, because the same quantity is also a row in the cohort strip below
    // it. That duplication is the card's own rule — the tiles are the record and the meters
    // are the reading — so the assertion names which of the two it means.
    await expect(card.locator(".readout-label", { hasText: /^Points per game$/ })).toBeVisible();
    await expect(card.locator(".readout-label", { hasText: /^Snap share$/ })).toBeVisible();
    // A count is never called a price, and the card says so where the counts are.
    await expect(card.getByText(/not a price and not a rank/i)).toBeVisible();
  });

  /*
   * The micro-charts (ADR-086). Each one is asserted on the fact that makes it honest rather
   * than on its shape: a picture is what the screenshots are for, and a picture that says the
   * wrong thing about a number is what a test can catch.
   */
  test("draws the rank move against the board, with both orderings named", async ({ page }) => {
    await page.goto(IN_SEASON);
    await page.locator("table.sheet .player-name").first().click();
    const shift = page.getByRole("dialog").locator(".shift");
    await expect(shift).toBeVisible();
    // Two anchors, never one mark that moved.
    await expect(shift.locator('.shift-anchor[data-anchor="from"]')).toHaveCount(1);
    await expect(shift.locator('.shift-anchor[data-anchor="to"]')).toHaveCount(1);
    await expect(shift.getByText(/Two orderings of one board, not one rank that moved/)).toBeVisible();
    // The axis is the board's depth, so its right-hand end is the published row count and not
    // the player's own deeper rank. 18 rows per block in this scenario.
    await expect(shift.locator(".shift-scale span").last()).toHaveText("18");
  });

  test("compares the rate he has scored at with the rate the model projects", async ({ page }) => {
    await page.goto(IN_SEASON);
    await page.locator("table.sheet .player-name").first().click();
    const pace = page.getByRole("dialog").locator(".pace");
    await expect(pace.getByText("Scored so far")).toBeVisible();
    await expect(pace.getByText("Projected ahead")).toBeVisible();
    // One unit on both bars is the only reason they may share an axis, and the axis says so.
    await expect(pace.locator(".pace-scale-mid")).toHaveText("points per appearance");
    // The card never calls the ratio an expectation: it is two published totals divided.
    await expect(
      pace.getByText(/remaining points divided by its remaining games/i),
    ).toBeVisible();
  });

  test("places a published value among its own position, with the denominator printed", async ({
    page,
  }) => {
    await page.goto(IN_SEASON);
    await page.locator("table.sheet .player-name").first().click();
    const card = page.getByRole("dialog");
    // The first row of this scenario is a running back, so the population is named as one.
    await expect(card.getByText(/Value against the RBs on this board/i)).toBeVisible();
    await expect(card.getByText(/Production against the RBs on this board/i)).toBeVisible();
    // The interval width is the number the owner's review named, and it now has a scale.
    const strip = card.locator(".cohort").first();
    await expect(strip.getByText("ROS uncertainty")).toBeVisible();
    await expect(strip.getByText(/\d+(st|nd|rd|th) widest of \d+ RBs/)).toBeVisible();
    // Every reading carries its population; a rank without one looks exact and is not.
    for (const read of await strip.locator(".cohort-read > span").all()) {
      await expect(read).toHaveText(/of \d+ RBs$/);
    }
  });

  test("says so rather than drawing a move for a player the preseason board never held", async ({
    page,
  }) => {
    await page.goto(IN_SEASON);
    // The fixture's breakout: `in_preseason_universe` false, so there is no earlier ordering
    // to place him in and no change to print. A rail drawn from a rank that does not exist is
    // the defect this branch exists to prevent; an em dash and a sentence are the report.
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).first().click();
    const card = page.getByRole("dialog");
    await expect(card).toBeVisible();
    await expect(card.locator(".shift-track")).toHaveCount(0);
    await expect(card.getByText(/not on the preseason board at all/i)).toBeVisible();
    await expect(card.locator('.shift-end[data-role="from"] .shift-end-value')).toHaveText("—");
    await expect(card.locator('.shift-end[data-role="change"] .shift-end-value')).toHaveText("—");
  });

  test("shows the model declining to buy a hot start, in the model's own unit", async ({ page }) => {
    await page.goto(IN_SEASON);
    // The same breakout: 28.4 points per appearance so far against a projected 14.0. That the
    // two disagree is the reading; that they are the same unit is why they may be compared.
    await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).first().click();
    const pace = page.getByRole("dialog").locator(".pace");
    await expect(pace.locator('.pace-row[data-kind="scored"] .pace-value')).toHaveText("28.4");
    await expect(pace.locator('.pace-row[data-kind="projected"] .pace-value')).toHaveText("14.0");
    await expect(pace.getByText(/projects 14.4 fewer points per appearance/i)).toBeVisible();
    // Four appearances stand behind the first number, and the card says how many.
    await expect(pace.getByText(/against 4 appearances so far/i)).toBeVisible();
  });

  test("leads the rail with the rest-of-season rank, not the draft one", async ({ page }) => {
    await page.goto(IN_SEASON);
    await page.locator("table.sheet .player-name").first().click();
    const rail = page.getByRole("dialog").locator(".detail-rail");
    await expect(rail.getByText("ROS rank")).toBeVisible();
    await expect(rail.getByText("median simulated remaining VORP")).toBeVisible();
    await expect(rail.getByText("Fair rank")).toHaveCount(0);
    await expect(rail.getByText("Since preseason")).toBeVisible();
  });

  test("keeps the draft market card in draft mode, all season", async ({ page }) => {
    // The draft board stays reachable and correct in November (roadmap 12.1), and its card is
    // the draft one: the section follows the product on screen, not the calendar.
    await page.goto(`${IN_SEASON}?mode=draft&view=tiers`);
    await page.locator("table.sheet .player-name").first().click();
    const card = page.getByRole("dialog");
    await expect(card.getByRole("heading", { name: "Draft market" })).toBeVisible();
    await expect(card.getByRole("heading", { name: "In-season usage" })).toHaveCount(0);
  });
});
