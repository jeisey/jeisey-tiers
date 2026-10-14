/**
 * The Skill Tree on the in-season player card, in a real browser (ADR-107).
 *
 * What only a browser can show:
 *
 * * **laziness on the wire** — opening a card requests no Skill Tree code, style or data; the
 *   section's button (desktop) or tab (phone) does, once, and a second activation or a return
 *   to a player already read requests nothing;
 * * **the four trees**, each with its own branches and node count, and a sparse player whose
 *   unranked and uncovered readings say so in words;
 * * **keyboard and touch** — one tab stop, arrows between nodes, Enter for the detail, Close
 *   back to the node, Escape still closing the dialog and returning focus to the row;
 * * **geometry** — four, two or one branch columns by the pane's width, nothing wider than the
 *   pane or the page at 320 through 1440 pixels and on short screens, the headshot untouched;
 * * a clean axe scan of the open tree, and no transitions under reduced motion.
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { guardBoundary } from "./boundary";

const IN_SEASON = "/scenario/in-season/";
const NO_TREE = "/scenario/in-season-no-skill-tree/";
const BOARD = "?view=ros&scoring=ppr&teams=12";

/** One board player per position, and the number of nodes his tree draws. */
const TREES = [
  { position: "QB", name: "Joe Burrow", nodes: 13, branch: "Passing volume" },
  { position: "RB", name: "Bijan Robinson", nodes: 13, branch: "Ground workload" },
  { position: "WR", name: "Puka Nightingale", nodes: 14, branch: "Target earning" },
  { position: "TE", name: "Kyle Pitts Sr.", nodes: 13, branch: "Usage" },
] as const;

/** Four games, three readings Next Gen Stats does not cover, six below their minimums. */
const SPARSE = "Amon-Ra Bright";

test.beforeEach(async ({ page }) => {
  await guardBoundary(page);
});

/** Every request the page makes from now on whose URL belongs to the Skill Tree. */
function treeRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (/\/data\/serve\/skill_tree|\/assets\/SkillTree-/.test(url)) seen.push(new URL(url).pathname);
  });
  return seen;
}

async function openCard(page: Page, name: string, prefix = IN_SEASON): Promise<Locator> {
  if (!page.url().includes(prefix)) {
    await page.goto(`${prefix}${BOARD}`);
    await expect(page.getByRole("heading", { name: /Rest of season/ })).toBeVisible();
  }
  await page.getByRole("button", { name, exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name, exact: true })).toBeVisible();
  return dialog;
}

async function showTree(dialog: Locator): Promise<Locator> {
  await dialog.getByRole("button", { name: "Show skill tree" }).click();
  const tree = dialog.getByRole("group", { name: /skill tree/ });
  await expect(tree).toBeVisible();
  return tree;
}

async function closeCard(page: Page): Promise<void> {
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
}

test.describe("loading", () => {
  test("opening a card requests nothing of the tree; its button loads code, style and two files", async ({
    page,
  }) => {
    const requests = treeRequests(page);
    const dialog = await openCard(page, "Joe Burrow");
    await expect(dialog.getByRole("heading", { name: "Skill tree" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(requests).toEqual([]);

    await showTree(dialog);
    await page.waitForLoadState("networkidle");
    const data = requests.filter((path) => path.includes("/data/serve/"));
    expect(data.filter((path) => path.includes("/skill_tree_definitions/QB."))).toHaveLength(1);
    expect(data.filter((path) => /\/skill_tree\/\d\d\./.test(path))).toHaveLength(1);
    expect(data).toHaveLength(2);
    expect(requests.some((path) => /SkillTree-.*\.js$/.test(path))).toBe(true);
  });

  test("a second activation, a new player and a return to the first fetch only what is new", async ({ page }) => {
    const requests = treeRequests(page);
    let dialog = await openCard(page, "Joe Burrow");
    await showTree(dialog);
    await page.waitForLoadState("networkidle");

    // Hide and show again: nothing.
    let mark = requests.length;
    await dialog.getByRole("button", { name: "Hide skill tree" }).click();
    await showTree(dialog);
    await page.waitForLoadState("networkidle");
    expect(requests.slice(mark)).toEqual([]);

    // A new card starts closed and fetches nothing until asked.
    await closeCard(page);
    mark = requests.length;
    dialog = await openCard(page, "Josh Allen");
    await expect(dialog.getByRole("button", { name: "Show skill tree" })).toHaveAttribute("aria-expanded", "false");
    await page.waitForLoadState("networkidle");
    expect(requests.slice(mark)).toEqual([]);
    // Another quarterback: the definitions are already read; at most his bucket's shard.
    await showTree(dialog);
    await page.waitForLoadState("networkidle");
    const second = requests.slice(mark);
    expect(second.filter((path) => path.includes("skill_tree_definitions"))).toEqual([]);
    expect(second.length).toBeLessThanOrEqual(1);
    await expect(dialog.locator(".st-window")).toContainText("5 games played");

    // Back to the first player: everything is in memory.
    await closeCard(page);
    mark = requests.length;
    dialog = await openCard(page, "Joe Burrow");
    await showTree(dialog);
    await page.waitForLoadState("networkidle");
    expect(requests.slice(mark)).toEqual([]);
    await expect(dialog.locator(".st-window")).toContainText("8 games played");
  });

  test("a build with no tree has no section, and everything else on the card", async ({ page }) => {
    const requests = treeRequests(page);
    const dialog = await openCard(page, "Joe Burrow", NO_TREE);
    await expect(dialog.getByRole("heading", { name: "In-season usage" })).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Skill tree" })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Show skill tree" })).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(requests).toEqual([]);
  });
});

test.describe("the four trees", () => {
  for (const tree of TREES) {
    test(`${tree.position}: ${String(tree.nodes)} nodes in four branches, each with its own detail`, async ({
      page,
    }) => {
      const dialog = await openCard(page, tree.name);
      const group = await showTree(dialog);
      await expect(group.locator(".st-branch")).toHaveCount(4);
      await expect(group.getByRole("heading", { name: tree.branch })).toBeVisible();
      await expect(group.getByRole("button")).toHaveCount(tree.nodes);
      // The core names the position; the legend says what a segment means.
      await expect(dialog.locator(".st-core-text")).toHaveText(tree.position);
      await expect(dialog.locator(".st-legend")).toContainText("each segment is 20 points");
      await expect(dialog.locator(".st-legend")).toContainText("No overall rating");
      // The archive plaque is labelled as history, never as current speed.
      await expect(dialog.locator(".st-archive-label")).toHaveText(/historical context, not current speed/);

      const first = group.getByRole("button").first();
      await first.click();
      await expect(first).toHaveAttribute("aria-expanded", "true");
      const detail = dialog.getByRole("region", { name: /: details$/ });
      await expect(detail).toBeVisible();
      for (const term of ["What it is", "How to read it", "Ranked against", "Window", "Formula", "Source", "Limitations"]) {
        await expect(detail.getByText(term, { exact: true })).toBeVisible();
      }
      await expect(detail).toContainText("2026 regular season");
    });
  }

  test("a sparse player's readings say why they are unranked, in words", async ({ page }) => {
    const dialog = await openCard(page, SPARSE);
    const group = await showTree(dialog);
    await expect(dialog.locator(".st-window")).toContainText("4 games played");
    // Below a minimum: the value and its sample, no rank and no lit segment.
    const unranked = group.locator('.st-node[data-state="below_minimum"]');
    expect(await unranked.count()).toBeGreaterThan(0);
    await expect(unranked.first().locator(".st-node-standing")).toHaveText(/^Unranked · \d+ of \d+ /);
    await expect(unranked.first().locator('.st-seg[data-on="true"]')).toHaveCount(0);
    // Not covered by a source: no value at all, and the source named.
    const uncovered = group.locator('.st-node[data-state="not_covered"]');
    expect(await uncovered.count()).toBeGreaterThan(0);
    await expect(uncovered.first()).toHaveAttribute("data-empty", "true");
    await expect(uncovered.first().locator(".st-node-value")).toHaveText("—");
    await expect(uncovered.first().locator(".st-node-standing")).toHaveText("Not in Next Gen Stats");
    // Its detail gives the build's own reason.
    await uncovered.first().click();
    await expect(dialog.getByRole("region", { name: /: details$/ })).toContainText(
      "Next Gen Stats publishes no season summary for him",
    );
  });
});

test.describe("keyboard", () => {
  test("one tab stop, arrows between nodes, Enter for the detail, Close back to the node", async ({ page }) => {
    const dialog = await openCard(page, "Bijan Robinson");
    const toggle = dialog.getByRole("button", { name: "Show skill tree" });
    await toggle.focus();
    await page.keyboard.press("Enter");
    const group = dialog.getByRole("group", { name: /skill tree/ });
    await expect(group).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Hide skill tree" })).toBeFocused();

    // Tab enters the tree on its first node, and only one node is a tab stop.
    await page.keyboard.press("Tab");
    const nodes = group.getByRole("button");
    await expect(nodes.first()).toBeFocused();
    await expect(group.locator('button[tabindex="0"]')).toHaveCount(1);

    await page.keyboard.press("ArrowDown");
    await expect(nodes.nth(1)).toBeFocused();
    await page.keyboard.press("ArrowRight");
    const second = group.locator(".st-branch").nth(1).getByRole("button");
    await expect(second.nth(1)).toBeFocused();
    await page.keyboard.press("End");
    await expect(nodes.last()).toBeFocused();
    await page.keyboard.press("Home");
    await expect(nodes.first()).toBeFocused();

    await page.keyboard.press("Enter");
    const detail = dialog.getByRole("region", { name: /: details$/ });
    await expect(detail).toBeVisible();
    await detail.getByRole("button", { name: /^Close/ }).click();
    await expect(detail).toHaveCount(0);
    await expect(nodes.first()).toBeFocused();
    await expect(nodes.first()).toHaveAttribute("aria-expanded", "false");

    // Space toggles as well as Enter.
    await page.keyboard.press("Space");
    await expect(nodes.first()).toHaveAttribute("aria-expanded", "true");
  });

  test("Escape inside the tree still closes the dialog and returns focus to the row", async ({ page }) => {
    await page.goto(`${IN_SEASON}${BOARD}`);
    const trigger = page.getByRole("button", { name: "Joe Burrow", exact: true }).first();
    await trigger.click();
    const dialog = page.getByRole("dialog");
    const group = await showTree(dialog);
    await group.getByRole("button").nth(2).click();
    await expect(dialog.getByRole("region", { name: /: details$/ })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("Tab never reaches the page behind the dialog with the tree open", async ({ page }) => {
    const dialog = await openCard(page, "Kyle Pitts Sr.");
    await showTree(dialog);
    // As in the smoke suite: focus may leave the document for the browser's own chrome at the
    // end of a modal's tab ring (`activeElement` is then <body>), never for the page behind.
    for (let step = 0; step < 40; step += 1) {
      await page.keyboard.press("Tab");
      const where = await page.evaluate(() => {
        const open = document.querySelector("dialog[open]");
        const active = document.activeElement;
        if (open === null) return "no dialog";
        if (active === null || active === document.body) return "browser chrome";
        return open.contains(active) ? "inside" : `escaped to ${active.tagName}.${active.className}`;
      });
      expect(where, `after ${String(step + 1)} tabs`).toMatch(/^(inside|browser chrome)$/);
    }
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("is a tab, loads when tapped, and stacks its branches with the detail inside its branch", async ({
    page,
  }) => {
    const requests = treeRequests(page);
    const dialog = await openCard(page, "Puka Nightingale");
    const tab = dialog.getByRole("tab", { name: "Skill tree" });
    await expect(tab).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(requests).toEqual([]);
    await tab.tap();
    const group = dialog.getByRole("group", { name: /skill tree/ });
    await expect(group).toBeVisible();
    await expect(dialog.locator(".st")).toHaveAttribute("data-columns", "1");
    // One column: every branch starts where the one above it did.
    const lefts = await group.locator(".st-branch").evaluateAll((branches) =>
      branches.map((branch) => Math.round(branch.getBoundingClientRect().left)),
    );
    expect(new Set(lefts).size).toBe(1);

    const node = group.locator(".st-branch").nth(2).getByRole("button").first();
    await node.scrollIntoViewIfNeeded();
    await node.tap();
    const detail = group.locator(".st-branch").nth(2).getByRole("region", { name: /: details$/ });
    await expect(detail).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("keeps the tab when the reader moves to another player", async ({ page }) => {
    let dialog = await openCard(page, "Puka Nightingale");
    await dialog.getByRole("tab", { name: "Skill tree" }).tap();
    await expect(dialog.getByRole("group", { name: /skill tree/ })).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: /^Close/ }).first().tap();
    await expect(page.getByRole("dialog")).toBeHidden();
    dialog = await openCard(page, "Joe Burrow");
    // A new card starts on its first tab, and the tree is one tap away.
    await expect(dialog.getByRole("tab", { name: "Skill tree" })).toHaveAttribute("aria-selected", "false");
    await dialog.getByRole("tab", { name: "Skill tree" }).tap();
    await expect(dialog.locator(".st-core-text")).toHaveText("QB");
  });
});

/** Every box in the tree inside the tree, the tree inside the dialog, the page not scrolling sideways. */
async function measure(page: Page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const tree = document.querySelector("dialog[open] .st");
    const dialog = document.querySelector("dialog[open]");
    if (tree === null || dialog === null) return null;
    const bounds = tree.getBoundingClientRect();
    const outside: string[] = [];
    for (const node of tree.querySelectorAll(".st-node, .st-branch-head, .st-detail, .st-archive, .st-legend")) {
      const rect = node.getBoundingClientRect();
      if (rect.width === 0) continue;
      if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1) outside.push(node.className);
    }
    const clipped: string[] = [];
    for (const node of tree.querySelectorAll(".st-node-value, .st-node-label, .st-node-standing")) {
      if (node.scrollWidth > node.clientWidth + 1) clipped.push(node.textContent ?? "");
    }
    const box = dialog.getBoundingClientRect();
    return {
      overflow: doc.scrollWidth - doc.clientWidth,
      columns: tree.getAttribute("data-columns"),
      outside,
      clipped,
      treeWiderThanDialog: bounds.right > box.right + 1 || bounds.left < box.left - 1,
      dialogFits: box.left >= -1 && box.right <= window.innerWidth + 1,
    };
  });
}

test.describe("geometry", () => {
  const SIZES = [
    [1440, 900, "4"],
    [1280, 720, "4"],
    [1280, 640, "4"],
    [1024, 768, "4"],
    [768, 1024, "4"],
    [390, 844, "1"],
    [390, 600, "1"],
    [320, 640, "1"],
  ] as const;
  for (const [width, height, columns] of SIZES) {
    test(`fits at ${String(width)}x${String(height)} with ${columns} column(s)`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      const dialog = await openCard(page, "Puka Nightingale");
      if (width < 768) await dialog.getByRole("tab", { name: "Skill tree" }).click();
      else await showTree(dialog);
      const group = dialog.getByRole("group", { name: /skill tree/ });
      await expect(group).toBeVisible();
      // A detail open, too: the widest thing the tree draws.
      await group.getByRole("button").nth(5).click();
      await expect(dialog.getByRole("region", { name: /: details$/ })).toBeVisible();
      const result = await measure(page);
      expect(result).not.toBeNull();
      expect(result?.overflow).toBeLessThanOrEqual(0);
      expect(result?.columns).toBe(columns);
      expect(result?.outside).toEqual([]);
      expect(result?.clipped).toEqual([]);
      expect(result?.treeWiderThanDialog).toBe(false);
      expect(result?.dialogFits).toBe(true);
    });
  }

  test("opening the tree leaves the headshot and the rail as they were", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const dialog = await openCard(page, "Joe Burrow");
    const portrait = dialog.locator(".portrait").first();
    const before = await portrait.boundingBox();
    await showTree(dialog);
    const after = await portrait.boundingBox();
    expect(before).not.toBeNull();
    expect(after?.width).toBeCloseTo(before?.width ?? 0, 0);
    expect(after?.height).toBeCloseTo(before?.height ?? 0, 0);
  });
});

test("the open tree and an open detail scan clean", async ({ page }) => {
  const dialog = await openCard(page, SPARSE);
  const group = await showTree(dialog);
  await group.getByRole("button").first().click();
  const results = await new AxeBuilder({ page }).include("dialog[open] .st").analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${String(violation.nodes.length)}`)).toEqual([]);
});

test("reduced motion: no transitions on nodes or the lit path", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const dialog = await openCard(page, "Joe Burrow");
  const group = await showTree(dialog);
  await group.getByRole("button").first().click();
  const durations = await group.locator(".st-node").evaluateAll((nodes) =>
    nodes.map((node) => getComputedStyle(node).transitionDuration),
  );
  // The site-wide rule shortens every transition to 0.01ms; the tree's own rule removes them.
  for (const duration of durations) {
    expect(duration.split(",").every((part) => Number.parseFloat(part) <= 0.00001)).toBe(true);
  }
  // Nothing animates continuously anywhere in the tree.
  const animated = await page.evaluate(
    () => document.getAnimations().filter((animation) => (animation.effect as KeyframeEffect | null)?.target?.closest?.(".st") != null).length,
  );
  expect(animated).toBe(0);
});
