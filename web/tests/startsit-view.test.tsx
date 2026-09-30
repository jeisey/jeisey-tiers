/**
 * The Start/Sit view (ADR-096): what the page *claims*, from a URL a reader could share.
 *
 * The arithmetic is covered by `startsit.test.ts` and the reading by `duel.test.ts`. These
 * cover the sentences: the pick is always paired with the number that justifies it, a pick
 * that is not the likelier to outscore says so rather than printing a contradiction, the
 * reader's margin moves the pick through the URL, and a build without projections says which
 * boards are unaffected.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

describe("what the page will not do", () => {
  it("keeps a ruled-out player off the verdict and says why", async () => {
    await open("?view=startsit&scoring=ppr&teams=12&duel=00-0000011.00-0000017");
    expect(screen.getByText(/Ruled out on the official report — left out of the verdict\./)).toBeDefined();
    expect(verdictText()).toContain("Only one of these players can fill the slot this week.");
  });

  it("says which boards are unaffected when no projections were published", async () => {
    serve("absent");
    await open("?view=startsit");
    expect(screen.getByText("No weekly projections were published with this build.")).toBeDefined();
  });
});
