/**
 * My Leagues end to end (ADR-106), against the static in-season build.
 *
 * What the component tests cannot see: the lazy workspace and what it fetches (and when), real
 * localStorage across a reload and across two tabs, the clock against kickoff, storage the
 * browser refuses, the native dialog's keyboard behaviour, and the whole reader's flow in one
 * browser session.
 */

import { expect, test, type Page } from "@playwright/test";

import { guardBoundary } from "./boundary";
import { IN_SEASON, KEY, OFFICE, g, seed } from "./leagues-seed";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

function dataRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.includes("/data/")) seen.push(path);
  });
  return seen;
}

test.describe("the tab and what it loads", () => {
  test("sits second; a cold visit with no league loads the workspace and no week or block file", async ({ page }) => {
    const requests = dataRequests(page);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await expect(page.getByRole("heading", { name: "My Leagues" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Create a league" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const tabs = page.getByRole("tablist", { name: "Board" }).getByRole("tab");
    await expect(tabs.nth(1)).toHaveAccessibleName("My Leagues");
    expect(requests.filter((path) => /weekly_projections|ros_tiers|season_actuals/.test(path))).toEqual([]);
  });

  test("with a league, loads only that league's block and scoring", async ({ page }) => {
    await seed(page, [{ ...OFFICE, scoring: "half", teams: 10 }]);
    const requests = dataRequests(page);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await expect(page.getByText("10-team Half PPR", { exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const blockFiles = requests.filter((path) => /ros_tiers\/|weekly_projections\/|season_actuals\//.test(path));
    expect(blockFiles.length).toBeGreaterThan(0);
    for (const path of blockFiles) expect(path).toMatch(/redraft-10\.HALF|\/HALF\./);
    await expect(page).toHaveURL(/scoring=half/);
    await expect(page).toHaveURL(/teams=10/);
  });

  test("leaves every other tool's link alone: the league governs only its own workspace", async ({ page }) => {
    await seed(page, [{ ...OFFICE, scoring: "half" }]);
    await page.goto(`${IN_SEASON}?view=ros&scoring=std`);
    await expect(page.getByRole("heading", { name: /Rest of season/ }).first()).toBeVisible();
    await expect(page).toHaveURL(/scoring=std/);
    await expect(page.getByRole("radiogroup", { name: "Scoring" }).getByRole("radio", { name: "Standard" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});

test.describe("the reader's flow", () => {
  test("create → roster by keyboard → reload → optimise → apply/undo → second league → switch → Improve → Rising Stars", async ({
    page,
  }) => {
    const requests = dataRequests(page);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await page.getByRole("button", { name: "Create a league" }).click();
    const create = page.getByRole("dialog", { name: "New league" });
    await create.getByLabel("League name").fill("Office");
    await create.getByRole("button", { name: "Create league" }).click();
    await expect(page.getByRole("radio", { name: /Office/ })).toHaveAttribute("aria-checked", "true");

    // The roster, through the slot picker, by keyboard only.
    const entries: [string, string][] = [
      ["QB", "Burrow"],
      ["RB 1", "Bijan"],
      ["RB 2", "Omarion"],
      ["WR 1", "Puka"],
      ["WR 2", "Deebo"],
      ["TE", "Ertz"],
      ["FLEX", "Kirk"],
      ["Bench 1", "Jaylin"],
      ["Bench 2", "Amon"],
    ];
    for (const [slot, query] of entries) {
      const add = page.getByRole("button", { name: `Add a player to ${slot}` });
      await add.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByRole("combobox")).toBeFocused();
      await page.keyboard.type(query);
      await expect(dialog.getByRole("option").first()).toBeVisible();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
    await expect(page.locator(".lg-slot .player-name")).toHaveCount(9);
    // Saved ids, never names, and nothing in the URL.
    const saved = await page.evaluate((key) => window.localStorage.getItem(key), KEY);
    expect(saved).toContain("gsis:00-0000001");
    expect(saved).not.toContain("Bijan");
    expect(page.url()).not.toContain("0000001");

    await page.reload();
    await expect(page.locator(".lg-slot .player-name")).toHaveCount(9);

    // Auto Start/Sit: a proposal, applied only on request, with undo.
    const moves = page.getByRole("list", { name: "Proposed changes" });
    await expect(moves).toContainText("Start Amon-Ra Bright at WR 2");
    await expect(moves).toContainText("if active");
    await expect(page.locator(".lg-auto")).toContainText("not the team's joint median");
    await page.getByRole("button", { name: /^Apply \d+ change/ }).click();
    await expect(page.locator(".lg-auto-none")).toHaveText("Your lineup is already the best legal lineup for the median.");
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(page.getByRole("list", { name: "Proposed changes" })).toBeVisible();

    // A second league on another preset: the shell loads its block; switching back reuses.
    await page.getByRole("button", { name: "New league" }).click();
    const second = page.getByRole("dialog", { name: "New league" });
    await second.getByLabel("League name").fill("Family");
    await second.getByRole("radio", { name: "Half PPR" }).check();
    await second.getByRole("radio", { name: "10 teams" }).check();
    await second.getByRole("button", { name: "Create league" }).click();
    await expect(page.getByText("10-team Half PPR", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(/scoring=half&teams=10/);
    await page.waitForLoadState("networkidle");
    expect(requests.some((path) => path.includes("ros_tiers/redraft-10.HALF"))).toBe(true);
    const before = requests.length;
    await page.getByRole("radio", { name: /Office/ }).click();
    await expect(page.getByText("12-team PPR", { exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(requests.slice(before).filter((path) => path.includes("/serve/"))).toEqual([]);

    // Improve: lazy, slot-relative, and a real package judged after the trade.
    const improveChunk = requests.length;
    await page.getByRole("button", { name: "Find upgrades" }).click();
    const result = page.getByRole("region", { name: "Upgrade ideas" });
    await expect(result).toBeVisible();
    await expect(result).toContainText("Give Deebo Gray + Omarion Vance");
    await expect(result).toContainText("receive Jahmyr Cook");
    await expect(result).toContainText("Median lineup");
    await expect(result).toContainText("hypothetical");
    expect(requests.slice(improveChunk).filter((path) => path.includes("/data/"))).toEqual([]);

    // Rising Stars: remembered per league; the FLEX list crosses positions on snap share.
    await page.getByRole("radio", { name: /Family/ }).click();
    await page.getByRole("checkbox", { name: "Rising Stars" }).check();
    const flex = page.locator('.lg-group[data-group="FLEX"] .lg-rising');
    await expect(flex.locator("li")).toHaveCount(2);
    await expect(flex.locator("li").first()).toContainText("Jahmyr Cook");
    await expect(flex.locator("li").nth(1)).toContainText("Puka Nightingale");
    await expect(flex).toContainText("Snap");
    await expect(flex).toContainText("Adds");
    await expect(page.locator('.lg-group[data-group="QB"] .lg-rising')).toContainText("None right now");
    await page.reload();
    await expect(page.getByRole("checkbox", { name: "Rising Stars" })).toBeChecked();
    await page.getByRole("radio", { name: /Office/ }).click();
    await expect(page.getByRole("checkbox", { name: "Rising Stars" })).not.toBeChecked();
  });

  test("holds at three leagues", async ({ page }) => {
    await seed(page, [
      OFFICE,
      { id: "lg-family01", name: "Family", roster: {} },
      { id: "lg-friends1", name: "Friends", roster: {} },
    ]);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await expect(page.getByRole("button", { name: "New league" })).toBeDisabled();
    await expect(page.getByText("Up to 3 leagues. Delete one to add another.")).toBeVisible();
  });
});

test.describe("rules a reader can see", () => {
  test("a game that has kicked off is locked: the starter stays, the bench player is not promoted", async ({ page }) => {
    // 19:00 UTC: the 18:00 games (ATL–DET, LAR–BAL) have started; BUF–CIN at 21:25 has not.
    await page.clock.install({ time: new Date("2026-11-08T19:00:00Z") });
    await seed(page, [OFFICE]);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await expect(page.locator(".lg-slot", { hasText: "Bijan Robinson" })).toContainText("Locked.");
    await expect(page.locator(".lg-slot", { hasText: "Amon-Ra Bright" })).toContainText("Locked.");
    await expect(page.locator(".lg-auto")).not.toContainText("Start Amon-Ra Bright");
    // WR 2's bye cannot be covered by a locked bench player, and says so.
    await expect(page.getByRole("list", { name: "Slots that cannot be filled" })).toContainText("WR 2");
    // Before kickoff, the same roster promotes him.
    await page.clock.setFixedTime(new Date("2026-11-08T12:00:00Z"));
    await page.reload();
    await expect(page.getByRole("list", { name: "Proposed changes" })).toContainText("Start Amon-Ra Bright at WR 2");
  });

  test("works when the browser refuses storage, and says nothing is saved", async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        get() {
          throw new DOMException("blocked", "SecurityError");
        },
      });
    });
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await expect(page.getByText("Not saved.")).toBeVisible();
    await page.getByRole("button", { name: "Create a league" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Create league" }).click();
    await expect(page.getByRole("radio", { name: /League 1/ })).toBeVisible();
  });

  test("another tab's change arrives without a reload", async ({ page, context }) => {
    await seed(page, [OFFICE]);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await expect(page.getByRole("radio", { name: /Office/ })).toBeVisible();
    const other = await context.newPage();
    await guardBoundary(other);
    await other.goto(`${IN_SEASON}?view=myleagues`);
    await other.getByRole("button", { name: "League settings" }).click();
    const dialog = other.getByRole("dialog");
    await dialog.getByLabel("League name").fill("Renamed elsewhere");
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("radio", { name: /Renamed elsewhere/ })).toBeVisible();
  });

  test("Escape clears the search first, then closes the dialog and returns focus", async ({ page }) => {
    await seed(page, [OFFICE]);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    const add = page.getByRole("button", { name: "Add a player to Bench 3" });
    await add.click();
    const box = page.getByRole("dialog").getByRole("combobox");
    await box.fill("cook");
    await page.keyboard.press("Escape");
    await expect(box).toHaveValue("");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(add).toBeFocused();
  });

  test("a slot's week shows the matchup, the defense and why, and opens Start/Sit prefilled", async ({ page }) => {
    await seed(page, [{ ...OFFICE, roster: { ...OFFICE.roster, BN: [g("10"), g("02"), g("11")] } }]);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await page.getByRole("button", { name: "Show Bijan Robinson's week" }).click();
    const detail = page.locator(".lg-slot", { hasText: "Bijan Robinson" }).locator(".lg-detail");
    await expect(detail).toContainText("@ DET");
    await expect(detail).toContainText("Defense vs RBs");
    await expect(detail).toContainText("Why this week");
    await detail.getByRole("button", { name: /Compare Bijan Robinson with/ }).click();
    await expect(page).toHaveURL(/view=startsit/);
    await expect(page).toHaveURL(/duel=00-0000001/);
  });
});
