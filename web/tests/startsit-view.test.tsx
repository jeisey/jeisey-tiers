/**
 * The Start/Sit view (ADR-096): what the page *claims*, from a URL a reader could share.
 *
 * The arithmetic is covered by `startsit.test.ts` and the reading by `duel.test.ts`. These
 * cover the sentences: the pick is always paired with the number that justifies it, a pick
 * that is not the likelier to outscore says so rather than printing a contradiction, the
 * reader's margin moves the pick through the URL, and a build without projections says which
 * boards are unaffected.
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { required } from "./required";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
const DUEL = "?view=startsit&scoring=ppr&teams=12&duel=00-0000011.00-0000012";

function serve(signals: "present" | "absent" = "present"): void {
  const payloads: Record<string, unknown> = {
    ...fixtureFiles(),
    ...inSeasonFixtureFiles(true, { signals }),
  };
  stubSite(payloads);
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

async function open(query = DUEL): Promise<void> {
  go(query);
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /Start\/Sit/ })).toBeDefined();
  });
}

function verdictText(): string {
  return required(document.querySelector(".verdict"), "document.querySelector('.verdict')").textContent ?? "";
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
  go();
  serve();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
  go();
});

describe("the verdict, as printed", () => {
  it("names the week, the pick, and both halves of a skewed call", async () => {
    await open();
    expect(screen.getByRole("heading", { name: /Start\/Sit — week 9/ })).toBeDefined();
    const text = verdictText();
    expect(text).toContain("Start Puka Nightingale");
    // Cook outscores him more often than not; the page must say so, and say why Puka anyway.
    expect(text).toMatch(/Jahmyr Cook outscores him \d+% of the time, but his range wins more matchups: [\d.]+% vs [\d.]+% chance to win the week/);
    expect(text).toContain("Jahmyr Cook has the higher median");
    expect(text).toMatch(/Flip point If you are projected to win by more than [\d.]+ without this slot, start Jahmyr Cook/);
    expect(text).not.toContain("He outscores");
  });

  it("moves the pick with the reader's margin, through the URL", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open();
    await user.click(screen.getByRole("radio", { name: "Projected to win by 20 without this slot" }));
    await waitFor(() => {
      expect(window.location.search).toContain("margin=20");
    });
    const text = verdictText();
    expect(text).toContain("Start Jahmyr Cook");
    expect(text).toMatch(/He outscores Puka Nightingale \d+% of the time/);
    expect(text).toMatch(/win by less than [\d.]+ without this slot, start Puka Nightingale — you need his ceiling/);
  });

  it("adds a player from the week board and keeps the reader's order", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open();
    await user.click(screen.getByRole("button", { name: "Add Ja'Marr Swift to the comparison" }));
    await waitFor(() => {
      expect(window.location.search).toContain("duel=00-0000011.00-0000012.00-0000003");
    });
    expect(screen.getByLabelText(/Slot C: Ja'Marr Swift/)).toBeDefined();
  });
});

describe("the empty deck cards (ADR-111)", () => {
  const empties = (): HTMLElement[] =>
    screen.getAllByRole("button", { name: "Add a player to the comparison" });
  const picker = (): HTMLElement => screen.getByRole("dialog", { name: "Add a player to the comparison" });
  const field = (): HTMLElement => screen.getByRole("combobox", { name: /Add a player to the week-9 comparison/ });

  it("are buttons, every one, and each opens the picker", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open("?view=startsit");
    expect(empties()).toHaveLength(4);
    for (const index of [0, 1, 2, 3]) {
      const card = empties()[index];
      if (card === undefined) throw new Error("missing card");
      expect(card.tagName).toBe("BUTTON");
      await user.click(card);
      expect(picker()).toBeDefined();
      expect(document.activeElement).toBe(field());
      await user.click(within(picker()).getByRole("button", { name: "Cancel" }));
      // Cancel leaves the comparison untouched and gives focus back to the card.
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(window.location.search).toBe("?view=startsit");
      expect(document.activeElement).toBe(empties()[index]);
    }
  });

  it("adds the chosen player once, in the reader's order, from the keyboard", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open();
    expect(empties()).toHaveLength(2);
    const last = empties()[1];
    if (last === undefined) throw new Error("missing card");
    last.focus();
    await user.keyboard("{Enter}");
    expect(within(picker()).getByText(/He joins the comparison as C\./)).toBeDefined();
    await user.type(field(), "swift");
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(window.location.search).toContain("duel=00-0000011.00-0000012.00-0000003");
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText(/Slot C: Ja'Marr Swift/)).toBeDefined();
    expect(empties()).toHaveLength(1);
  });

  it("lists a chosen or bye player with the reason, and will not choose him", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open();
    const before = window.location.search;
    const card = empties()[0];
    if (card === undefined) throw new Error("missing card");
    await user.click(card);
    await user.type(field(), "puka");
    const chosen = within(picker()).getByRole("option", { name: /Puka Nightingale/ });
    expect(chosen.getAttribute("aria-disabled")).toBe("true");
    expect(chosen.textContent).toContain("Already in the comparison");
    await user.click(chosen);
    await user.keyboard("{Enter}");
    // Choosing him again neither duplicates him nor takes him out.
    expect(window.location.search).toBe(before);
    expect(picker()).toBeDefined();
    await user.clear(field());
    await user.type(field(), "ertz");
    const pending = within(picker()).getByRole("option", { name: /Zach Ertz/ });
    expect(pending.getAttribute("aria-disabled")).toBe("true");
    expect(pending.textContent).toContain("Line pending: nothing to compare");
  });

  it("stops at four, and a link's unprojected players are removed only on request", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    // Three projected players and one id this build has no projection for: four places taken.
    await open("?view=startsit&duel=00-0000011.00-0000012.00-0000003.00-9999999");
    const card = screen.getByRole("button", { name: "Add a player to the comparison" });
    expect(card.hasAttribute("disabled")).toBe(true);
    expect(card.textContent).toMatch(/Full: the players in this link with no projection/);
    await user.click(screen.getByRole("button", { name: "Remove it from the link" }));
    await waitFor(() => {
      expect(window.location.search).toContain("duel=00-0000011.00-0000012.00-0000003");
    });
    expect(window.location.search).not.toContain("9999999");
    expect(screen.getByRole("button", { name: "Add a player to the comparison" }).hasAttribute("disabled")).toBe(false);
  });

  it("are gone when the comparison is full", async () => {
    await open("?view=startsit&duel=00-0000011.00-0000012.00-0000003.00-0000002");
    expect(screen.queryByRole("button", { name: "Add a player to the comparison" })).toBeNull();
  });
});

describe("what the page will not do", () => {
  it("keeps a ruled-out player off the verdict and says why", async () => {
    await open("?view=startsit&scoring=ppr&teams=12&duel=00-0000011.00-0000017");
    expect(screen.getByText(/Out this week — left out of the verdict\./)).toBeDefined();
    expect(verdictText()).toContain("Only one of these players can fill the slot this week.");
  });

  it("never lets a player whose season is over win, and keeps him inspectable (ADR-101)", async () => {
    // Derrick Hampton carries a reviewed season-ending override and is on IR in the fixture.
    await open("?view=startsit&scoring=ppr&teams=12&duel=00-0000014.00-0000011");
    expect(screen.getByText(/Out for the season — left out of the verdict\./)).toBeDefined();
    expect(verdictText()).toContain("Only one of these players can fill the slot this week.");
  });

  it("labels a Questionable verdict as conditional", async () => {
    await open("?view=startsit&scoring=ppr&teams=12&duel=00-0000002.00-0000011");
    expect(verdictText()).toMatch(/If active: Amon-Ra Bright is questionable/);
  });

  it("says which boards are unaffected when no projections were published", async () => {
    serve("absent");
    await open("?view=startsit");
    expect(screen.getByText("No weekly projections were published with this build.")).toBeDefined();
  });
});
