/**
 * Win My Matchup end to end (ADR-110), against the static in-season build.
 *
 * What the component tests cannot see: the lazy chunk and the real module worker (served under
 * a non-root base path), what is fetched and when, real localStorage across a reload, the clock
 * against kickoff, and the reader's whole flow — opponent → Simulate → groups → YOLO → preview →
 * confirm → apply → Undo → reload → league switch — in one browser session.
 *
 * The page clock is set within 48 hours of the fixture's behaviour snapshot (2026-08-21) and
 * before every week-9 kickoff (2026-11-08), so YOLO's net adds are current and nothing is locked.
 */

import { expect, test, type Page } from "@playwright/test";

import { guardBoundary } from "./boundary";
import { IN_SEASON, MATCH, MATCHUP_KEY, KEY, g, matchOpponent, seed, seedMatchups } from "./leagues-seed";

const FRESH = new Date("2026-08-22T12:00:00Z");

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

function requests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => {
    seen.push(new URL(request.url()).pathname);
  });
  return seen;
}

async function stored<T>(page: Page, key: string): Promise<T> {
  return JSON.parse((await page.evaluate((name) => window.localStorage.getItem(name), key)) ?? "null") as T;
}

const headline = (page: Page) => page.locator(".wmm-headline");

test.describe("what it loads, and when", () => {
  test("its code loads on opening it, YOLO's files only when YOLO is on, and the worker only on Simulate", async ({ page }) => {
    await page.clock.setFixedTime(FRESH);
    await seed(page, [MATCH]);
    await seedMatchups(page, matchOpponent());
    const seen = requests(page);
    await page.goto(`${IN_SEASON}?view=myleagues`);
    await expect(page.getByRole("tab", { name: "Lineup" })).toHaveAttribute("aria-selected", "true");
    await page.waitForLoadState("networkidle");
    expect(seen.filter((path) => /WinMyMatchup|matchup\.worker/.test(path))).toEqual([]);

    await page.getByRole("tab", { name: "Win My Matchup" }).click();
    await expect(page.getByRole("heading", { name: "Win My Matchup — week 9" })).toBeVisible();
    await expect(page).toHaveURL(/panel=wmm/);
    await page.waitForLoadState("networkidle");
    expect(seen.some((path) => /\/assets\/WinMyMatchup-.*\.js$/.test(path))).toBe(true);
    expect(seen.some((path) => path.includes("matchup.worker"))).toBe(false);
    expect(seen.some((path) => /inseason_opportunity\/|player_usage\//.test(path))).toBe(false);
    // Nothing has been simulated, and opening the view wrote nothing.
    await expect(headline(page)).toHaveCount(0);

    await page.getByRole("button", { name: "Simulate" }).click();
    await expect(headline(page)).toContainText("of 8,192 simulated games");
    // The worker chunk is served under the deployment's base path.
    expect(seen.some((path) => path.startsWith(IN_SEASON) && /matchup\.worker-.*\.js$/.test(path))).toBe(true);

    await page.getByRole("checkbox", { name: "YOLO" }).check();
    await expect(page.getByRole("list", { name: "Potential pickups" })).toBeVisible();
    expect(seen.some((path) => path.includes("inseason_opportunity/redraft-12.PPR"))).toBe(true);
    expect(seen.some((path) => path.includes("player_usage/all"))).toBe(true);
    expect(seen.some((path) => path.includes("behavior_trend_series"))).toBe(false);
  });
});

test.describe("the reader's flow", () => {
  test("opponent → Simulate → groups → YOLO → preview → confirm → apply → Undo → reload → league switch", async ({ page }) => {
    await page.clock.setFixedTime(FRESH);
    await seed(page, [MATCH, { id: "lg-other001", name: "Other", roster: { QB: [g("09")] } }]);
    await page.goto(`${IN_SEASON}?view=myleagues&panel=wmm`);
    await expect(page.getByRole("heading", { name: "Win My Matchup — week 9" })).toBeVisible();

    // The opponent, entered through the shared picker; my players are never offered.
    const entries: [string, string][] = [
      ["QB", "Marsh"],
      ["RB 1", "James Cook III"],
      ["RB 2", "Hampton"],
      ["WR 1", "Bright"],
      ["WR 2", "Meadows"],
      ["FLEX", "Swift"],
    ];
    for (const [slot, query] of entries) {
      await page.getByRole("button", { name: `Set the opponent's ${slot}` }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByRole("combobox")).toBeFocused();
      await page.keyboard.type(query);
      await expect(dialog.getByRole("option").first()).toBeVisible();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
    await page.getByRole("button", { name: "Set the opponent's TE" }).click();
    await page.getByRole("dialog").getByRole("combobox").fill("Burrow");
    await expect(page.getByRole("dialog").getByRole("option")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // Incomplete until every absence and the empty TE are decided.
    await expect(page.getByRole("button", { name: "Simulate" })).toBeDisabled();
    await expect(page.locator(".wmm-ready")).toContainText("Simulate needs");
    await page.getByRole("button", { name: "Leave the opponent's TE empty: it counts 0" }).click();
    for (let guard = 0; guard < 12; guard += 1) {
      const zero = page.getByRole("button", { name: /^Count .* as 0$/ });
      if ((await zero.count()) === 0) break;
      await zero.first().click();
    }
    await expect(page.locator(".wmm-ready")).toContainText("Ready: 7 starters a side.");
    await expect(page.locator(".wmm-ready")).toContainText('1 "if active"');

    // Simulate: the headline, the noise, the chart and the groups, all from one run.
    await page.getByRole("button", { name: "Simulate" }).click();
    await expect(headline(page)).toContainText("your modelled lineup wins");
    await expect(headline(page)).toContainText("Simulation noise ±");
    await expect(page.getByRole("figure")).toBeVisible();
    const groups = page.getByRole("table", { name: "Slot groups: your lineup against theirs" });
    for (const group of ["QB", "RB", "WR", "TE", "FLEX"]) await expect(groups.getByRole("rowheader", { name: new RegExp(`^${group}`) })).toBeVisible();
    await expect(page.getByText(/not head-to-head contests between paired players/)).toBeVisible();

    // YOLO: a gated, evidenced potential pickup, availability unverified.
    await page.getByRole("checkbox", { name: "YOLO" }).check();
    const pickups = page.getByRole("list", { name: "Potential pickups" });
    const card = pickups.locator("li", { hasText: "Jahmyr Cook" });
    await expect(card).toContainText("For RB 2, replacing Omarion Vance");
    await expect(card).toContainText("684 (bar 684)");
    await expect(card).toContainText("Availability unverified.");
    await page.getByRole("button", { name: "Evaluate changes and pickups" }).click();
    await expect(card).toContainText(/Chance to win\s*(\d+%|>99%|<1%)/);
    await card.getByRole("button", { name: "Preview" }).click();
    await expect(page.locator(".wmm-legend[data-side=overlay]")).toContainText("Jahmyr Cook (YOLO)");
    await expect(page.getByRole("table", { name: "Slot groups with Jahmyr Cook (YOLO)" })).toBeVisible();

    // Nothing changed the roster so far.
    const before = await stored<{ leagues: { roster: Record<string, (string | null)[]> }[] }>(page, KEY);
    expect(before.leagues[0]?.roster.RB).toEqual([g("01"), g("16")]);

    // Add him: availability must be confirmed; the incumbent moves to a free bench slot.
    await card.getByRole("button", { name: "Add to my roster…" }).click();
    const confirm = page.getByRole("dialog", { name: "Add Jahmyr Cook" });
    await expect(confirm.getByRole("button", { name: "Add to my roster" })).toBeDisabled();
    await confirm.getByRole("checkbox").check();
    await confirm.getByRole("button", { name: "Add to my roster" }).click();
    await expect(page.locator(".wmm-applied")).toContainText("Added Jahmyr Cook at RB 2.");
    const after = await stored<{ leagues: { roster: Record<string, (string | null)[]> }[] }>(page, KEY);
    expect(after.leagues[0]?.roster.RB).toEqual([g("01"), g("11")]);
    expect(after.leagues[0]?.roster.BN).toContain(g("16"));
    // The old result is gone: it described another lineup.
    await expect(headline(page)).toHaveCount(0);
    await page.getByRole("button", { name: "Undo" }).click();
    const undone = await stored<{ leagues: { roster: Record<string, (string | null)[]> }[] }>(page, KEY);
    expect(undone.leagues[0]?.roster.RB).toEqual([g("01"), g("16")]);

    // Saved: ids, confirmations, the mark and the YOLO preference — no result, no name.
    const saved = await stored<{ entries: { marks: Record<string, string> }[]; prefs: Record<string, { yolo: boolean }> }>(page, MATCHUP_KEY);
    expect(saved.entries[0]?.marks[g("11")]).toBe("available");
    expect(saved.prefs[MATCH.id]?.yolo).toBe(true);
    const raw = await page.evaluate((key) => window.localStorage.getItem(key), MATCHUP_KEY);
    expect(raw).not.toMatch(/Jahmyr|"win"|histogram/);

    // A reload keeps the inputs and shows no result until asked.
    await page.reload();
    await expect(page.getByRole("heading", { name: "Win My Matchup — week 9" })).toBeVisible();
    await expect(page.locator(".wmm-ready")).toContainText("Ready: 7 starters a side.");
    await expect(headline(page)).toHaveCount(0);
    await page.getByRole("button", { name: "Simulate" }).click();
    await expect(headline(page)).toBeVisible();

    // Another league: none of this league's opponent or numbers.
    await page.getByRole("radio", { name: /Other/ }).click();
    await expect(page.getByRole("heading", { name: "Win My Matchup — week 9" })).toBeVisible();
    await expect(headline(page)).toHaveCount(0);
    await expect(page.getByText("Hampton")).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: "YOLO" })).not.toBeChecked();
    await page.getByRole("radio", { name: /Match/ }).click();
    await expect(page.locator(".wmm-ready")).toContainText("Ready");
    await expect(headline(page)).toHaveCount(0);
  });
});

test.describe("weeks, locks and finals", () => {
  test("last week's opponent is offered for reuse, never its result", async ({ page }) => {
    await page.clock.setFixedTime(FRESH);
    await seed(page, [MATCH]);
    await seedMatchups(page, matchOpponent(8));
    await page.goto(`${IN_SEASON}?view=myleagues&panel=wmm`);
    await expect(page.getByText("Week 9 has no opponent yet.")).toBeVisible();
    await expect(page.getByText(/last saved matchup was week 8 against Rival/)).toBeVisible();
    await expect(headline(page)).toHaveCount(0);
    await page.getByRole("button", { name: "Reuse that opponent's lineup for week 9" }).click();
    await expect(page.getByText("Week 9 has no opponent yet.")).toHaveCount(0);
    await expect(page.locator(".wmm-side").nth(1)).toContainText("Jalen Marsh");
    // Week-specific decisions are not carried over.
    await expect(page.getByRole("button", { name: "Simulate" })).toBeDisabled();
  });

  test("a kicked-off starter is simulated from his pregame projection, or from a confirmed final, in separate scenarios", async ({ page }) => {
    // ATL at DET has kicked off (Bijan Robinson); the later games have not.
    await page.clock.setFixedTime(new Date("2026-11-08T19:00:00Z"));
    await seed(page, [MATCH]);
    await seedMatchups(page, matchOpponent());
    await page.goto(`${IN_SEASON}?view=myleagues&panel=wmm`);
    const bijan = page.locator(".wmm-slot", { hasText: "Bijan Robinson" });
    await expect(bijan).toContainText("simulated from his pregame projection");
    await page.getByRole("button", { name: "Simulate" }).click();
    await expect(headline(page)).toContainText("Pregame projection");
    await page.getByLabel("Final fantasy points for Bijan Robinson").fill("31.4");
    await page.getByRole("button", { name: "Save final for Bijan Robinson" }).click();
    await page.getByRole("radio", { name: /With final scores/ }).click();
    await expect(bijan).toContainText("Final 31.40");
    await expect(headline(page)).toHaveCount(0);
    await page.getByRole("button", { name: "Simulate" }).click();
    await expect(headline(page)).toContainText("With 1 final score");
    await expect(page.getByText(/This is not live scoring/)).toBeVisible();
  });
});
