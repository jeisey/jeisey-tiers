/**
 * The Pick of the Week view (ADR-088).
 *
 * The engine's own tests cover which players are chosen. These cover what the page then
 * *claims*, which is the half a selection rule cannot police:
 *
 * - it prints the bar it used, so a reader who disagrees with a pick can see what produced it;
 * - it never prints, implies, or leaves room to infer a share of leagues — there is no such
 *   number in any source this project may publish from, and a waiver card is exactly where a
 *   reader would expect one;
 * - a position with no pick says which of three things happened rather than rendering nothing;
 * - the portraits are bounded: at most one set's worth, replaced rather than accumulated when
 *   a reader cycles, because ADR-087's whole point is that this product makes one third-party
 *   request per opened card and not three hundred per board.
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { required } from "./required";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
const POTW = "?view=potw&scoring=ppr&teams=12";

function serve(behaviorAvailable = true): void {
  const payloads: Record<string, unknown> = {
    ...fixtureFiles(),
    ...inSeasonFixtureFiles(behaviorAvailable),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const name = input.split("/").pop() ?? "";
      const payload = payloads[name];
      if (payload === undefined) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve(null),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(payload),
      } as Response);
    }),
  );
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

async function open(query = POTW): Promise<void> {
  go(query);
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /Pick of the Week/ })).toBeDefined();
  });
}

/** Every rendered pick card, in document order. */
function cards(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(".potw-card")];
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

describe("the tab", () => {
  it("is in the in-season tab set and not in the draft one", async () => {
    await open("?view=potw&mode=in_season");
    expect(screen.getByRole("tab", { name: /POTW/ })).toBeDefined();
    cleanup();

    go("?view=tiers&mode=draft");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Tiers/ })).toBeDefined();
    });
    expect(screen.queryByRole("tab", { name: /POTW/ })).toBeNull();
  });

  it("keeps the set in the URL so a pick is shareable", async () => {
    await open();
    await userEvent.setup().click(screen.getByRole("button", { name: "Set 2" }));
    await waitFor(() => {
      expect(window.location.search).toContain("set=2");
    });
  });

  it("opens the deepest set a build has rather than an empty panel when a link overshoots", async () => {
    // The fixture publishes three sets. A link naming five is normalized down, not refused.
    await open("?view=potw&scoring=ppr&teams=12&set=5");
    expect(cards().length).toBeGreaterThan(0);
  });
});

describe("a pick card", () => {
  it("shows one player per position with the position named in words", async () => {
    await open();
    const positions = cards().map((card) => card.dataset.pos);
    expect(positions).toEqual(["QB", "RB", "WR", "TE"]);
    // The seal says which position the "#1" is a #1 *at*. Four cards each reading a bare "#1"
    // would read as a ranking of the four against each other, which they are not.
    expect(within(required(cards()[0], "the first pick card")).getByText(/QB waiver pick/)).toBeDefined();
  });

  it("prints the bar the pick cleared, and the population that set it", async () => {
    await open();
    const card = required(cards()[0], "the first pick card");
    // "bar 345 · median of 3" — the threshold and its denominator, both on screen.
    expect(within(card).getByText(/bar [\d,]+ · median of \d+/)).toBeDefined();
    expect(within(card).getByText(/adds in 24h/)).toBeDefined();
  });

  it("states the add volume as transactions and never as a share of leagues", async () => {
    await open();
    for (const card of cards()) {
      const text = card.textContent ?? "";
      expect(text, "a card must not claim a rostered share").not.toMatch(
        /rostered|% owned|owned in|percent of leagues/i,
      );
      // ADR-088 refused the mock-up's matchup rating because nothing sourced it; ADR-091
      // sources the next game as context. What stays refused is a *rating* — a grade the
      // artifact never published.
      expect(text, "a card must not invent a matchup rating").not.toMatch(
        /matchup (rating|grade)|(easy|tough|favou?rable|good|bad) matchup/i,
      );
      expect(text, "a card must not claim a multi-week trend").not.toMatch(/last 3 games/i);
    }
  });

  it("labels the projected rate as the division it is", async () => {
    await open();
    expect(
      within(required(cards()[0], "the first pick card")).getByText(
        "remaining points ÷ remaining games",
      ),
    ).toBeDefined();
  });

  it("says a share the feed did not publish is absent rather than zero", async () => {
    await open();
    const withoutShare = cards().find((card) =>
      (card.textContent ?? "").includes("not published"),
    );
    if (withoutShare !== undefined) {
      expect(within(withoutShare).getAllByText("—").length).toBeGreaterThan(0);
    }
  });

  it("opens the player card from the pick's name", async () => {
    await open();
    const name = within(required(cards()[0], "the first pick card")).getByRole("button");
    const label = name.textContent ?? "";
    await userEvent.setup().click(name);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });
    // Scoped to the dialog: the card's own heading carries the same name, which is the point
    // — the card the reader clicked and the dialog that opened describe one player.
    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: label })).toBeDefined();
  });
});

describe("the position filter", () => {
  it("narrows to one card and writes the shared control, not a second one", async () => {
    await open();
    const chiprow = required(
      document.querySelector<HTMLElement>(".potw-chiprow"),
      "the in-view position chip row",
    );
    const rb = within(chiprow).getByRole("button", { name: "RB" });
    await userEvent.setup().click(rb);
    await waitFor(() => {
      expect(cards()).toHaveLength(1);
    });
    expect(cards()[0]?.dataset.pos).toBe("RB");
    // The same `position` parameter every other board reads.
    expect(window.location.search).toContain("position=rb");
  });
});

describe("what it says when there is no pick", () => {
  it("names the missing position and the reason, rather than rendering an empty frame", async () => {
    // The fixture's QB pool is one deep, so set 2 has no quarterback.
    await open("?view=potw&scoring=ppr&teams=12&set=2");
    const absence = document.querySelector(".potw-absence");
    expect(absence?.textContent).toMatch(/QB/);
    expect(absence?.textContent).toMatch(/cleared the bar this week/);
  });

  it("explains a behaviour outage in the build's own words and defends the other boards", async () => {
    cleanup();
    vi.unstubAllGlobals();
    serve(false);
    await open();
    expect(screen.getByText(/No current add\/drop behaviour/)).toBeDefined();
    expect(
      screen.getByText(/Every rest-of-season value on the boards beside this one is unchanged/),
    ).toBeDefined();
    expect(cards()).toHaveLength(0);
  });
});

describe("the methodology on the page", () => {
  it("states the rule in the reader's own words, including that a count is not a share", async () => {
    await open();
    expect(screen.getByText(/How a pick is chosen/)).toBeDefined();
    expect(screen.getByText(/There is no rostered percentage here/)).toBeDefined();
    // The rule version travels with the picks, like every other versioned rule in this product.
    expect(screen.getByText(/potw_selection_v1/)).toBeDefined();
  });

  it("says the add count decides membership and never the ordering", async () => {
    await open();
    expect(
      screen.getByText(/the add count decides membership and never the ordering/i),
    ).toBeDefined();
  });
});

describe("the portrait boundary", () => {
  it("renders at most one set's portraits, and replaces them rather than accumulating", async () => {
    await open();
    const first = document.querySelectorAll("img.portrait-image").length;
    expect(first).toBeLessThanOrEqual(4);

    await userEvent.setup().click(screen.getByRole("button", { name: "Set 2" }));
    await waitFor(() => {
      expect(window.location.search).toContain("set=2");
    });
    // Cycling a set swaps the cards; it must not leave the previous set's images behind.
    expect(document.querySelectorAll("img.portrait-image").length).toBeLessThanOrEqual(4);
  });

  it("reserves the frame with a monogram for a player with no published portrait", async () => {
    await open();
    // Every card has a frame whether or not a picture was published for the player.
    expect(document.querySelectorAll(".potw-card .portrait").length).toBe(cards().length);
    expect(document.querySelectorAll(".potw-card .portrait-monogram").length).toBe(
      cards().length,
    );
  });
});
