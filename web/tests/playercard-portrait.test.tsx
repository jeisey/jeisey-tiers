/**
 * The player card's portrait (ADR-087).
 *
 * This is the first element in the product that fetches from another origin, so most of what
 * is asserted here is about *when* and *whether*, not about how it looks:
 *
 * | question                                  | why it could go wrong quietly                |
 * |-------------------------------------------|----------------------------------------------|
 * | does a page load request a portrait?      | a third party lands on the critical path     |
 * | does the address come from the artifact?  | a frontend quietly picks its own host        |
 * | is a missing crosswalk row survivable?    | a broken-image glyph, or an empty frame      |
 * | does a failed request degrade?            | the same, for a provider 404                 |
 * | does switching players switch pictures?   | one player's face under another's name       |
 * | does it say anything to a screen reader?  | "photo of X" read straight after "X"         |
 *
 * The last one is the reason `alt=""` is asserted rather than assumed: an image whose name is
 * the player's would make his heading read twice, and an image with a *description* would be
 * claiming the picture carries information. It does not; every fact about the player is text
 * within a few pixels of it.
 */

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { initialsOf } from "../src/components/PlayerPortrait";
import {
  FIXTURE_GENERATED_AT,
  arbitrageEnvelope,
  buildMetadata,
  marketTrendSeriesEnvelope,
  playerHeadshotEnvelope,
  playerHeadshotRecords,
  playerStatusEnvelope,
  projectionEnvelope,
  tierEnvelope,
} from "./fixtures/artifacts";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

/** A seed with a portrait, and the one seed deliberately without one. */
const WITH_PORTRAIT = "Bijan Robinson";
const WITHOUT_PORTRAIT = "Deebo Gray";

type Payloads = Record<string, unknown>;
const MISSING = Symbol("missing");

function serve(overrides: Payloads = {}): void {
  const payloads: Payloads = {
    "build_metadata.json": buildMetadata({}, "matured"),
    "tiers.json": tierEnvelope(),
    "arbitrage.json": arbitrageEnvelope("matured"),
    "market_trend_series.json": marketTrendSeriesEnvelope("matured"),
    "player_status.json": playerStatusEnvelope(),
    "player_headshots.json": playerHeadshotEnvelope(),
    "projections.json": projectionEnvelope(),
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const name = input.split("/").pop() ?? "";
      const payload = payloads[name];
      if (payload === undefined || payload === MISSING) {
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) } as Response);
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) } as Response);
    }),
  );
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

async function openBoard(): Promise<ReturnType<typeof userEvent.setup>> {
  go("?scoring=ppr&teams=12");
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Tier board" })).toBeDefined();
  });
  return userEvent.setup();
}

async function openCard(player: string): Promise<HTMLElement> {
  const user = await openBoard();
  await user.click(screen.getByRole("button", { name: player }));
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: player })).toBeDefined();
  });
  return screen.getByRole("dialog");
}

/** The address the artifact published for one player. */
function publishedUrlFor(player: string): string {
  const row = tierEnvelope().records.find((record) => record.display_name === player);
  expect(row, `no ${player} row in the fixture`).toBeTruthy();
  const headshot = playerHeadshotRecords().find((record) => record.player_id === row?.player_id);
  expect(headshot, `no published portrait for ${player}`).toBeTruthy();
  return headshot?.image_url ?? "";
}

function portraitIn(dialog: HTMLElement): HTMLImageElement | null {
  return dialog.querySelector("img.portrait-image");
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

// --------------------------------------------------------------------------------------
// Where the request happens, and where it does not

describe("the browser boundary", () => {
  it("loads a board without requesting any portrait", async () => {
    await openBoard();
    const requested = vi.mocked(fetch).mock.calls.map((call) => call[0] as string);
    expect(requested.some((url) => url.includes("espncdn"))).toBe(false);
    // The crosswalk itself is a generated file and is fetched; the pictures it names are not.
    expect(requested.some((url) => url.endsWith("player_headshots.json"))).toBe(true);
  });

  it("puts no portrait on the board itself, only on the card", async () => {
    await openBoard();
    expect(document.querySelectorAll("img.portrait-image")).toHaveLength(0);
  });

  it("renders exactly one portrait when a card is open", async () => {
    await openCard(WITH_PORTRAIT);
    expect(document.querySelectorAll("img.portrait-image")).toHaveLength(1);
  });
});

// --------------------------------------------------------------------------------------
// The address is the artifact's, not the frontend's

describe("the published address", () => {
  it("renders the exact URL the build published", async () => {
    const dialog = await openCard(WITH_PORTRAIT);
    expect(portraitIn(dialog)?.getAttribute("src")).toBe(publishedUrlFor(WITH_PORTRAIT));
  });

  it("sends no referrer, so the provider is not told which page the reader was on", async () => {
    const dialog = await openCard(WITH_PORTRAIT);
    expect(portraitIn(dialog)?.getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("does not block on the picture", async () => {
    const dialog = await openCard(WITH_PORTRAIT);
    expect(portraitIn(dialog)?.getAttribute("loading")).toBe("lazy");
    expect(portraitIn(dialog)?.getAttribute("decoding")).toBe("async");
  });
});

// --------------------------------------------------------------------------------------
// Every way there can be no picture looks the same

describe("absence", () => {
  it("draws a monogram for a player the crosswalk does not reach", async () => {
    const dialog = await openCard(WITHOUT_PORTRAIT);
    expect(portraitIn(dialog)).toBeNull();
    expect(dialog.querySelector(".portrait-monogram")?.textContent).toBe("DG");
  });

  it("draws a monogram when the whole artifact is absent", async () => {
    serve({ "player_headshots.json": MISSING });
    const dialog = await openCard(WITH_PORTRAIT);
    expect(portraitIn(dialog)).toBeNull();
    expect(dialog.querySelector(".portrait-monogram")?.textContent).toBe("BR");
  });

  it("does not report a missing portrait artifact as a degraded source", async () => {
    // Decoration, so its absence is not a fact about the board and the Data panel does not
    // list it beside a market outage. Every number is unaffected and the page says so by
    // saying nothing.
    serve({ "player_headshots.json": MISSING });
    await openCard(WITH_PORTRAIT);
    expect(document.body.textContent).not.toMatch(/player_headshots/);
  });

  it("falls back to the monogram when the provider refuses the request", async () => {
    const dialog = await openCard(WITH_PORTRAIT);
    const image = portraitIn(dialog);
    expect(image).not.toBeNull();
    // jsdom loads nothing, so the failure is fired rather than awaited. What matters is that
    // the component treats an `error` as "there is no picture" rather than leaving a broken
    // image in a card a reader is looking at.
    act(() => {
      image?.dispatchEvent(new Event("error"));
    });
    await waitFor(() => {
      expect(portraitIn(dialog)).toBeNull();
    });
    expect(dialog.querySelector(".portrait-monogram")?.textContent).toBe("BR");
  });

  it("keeps the monogram visible while the picture is still in flight", async () => {
    // The gap between "requested" and "painted" is exactly when the monogram is earning its
    // place; hiding it on having a URL would leave an empty frame for the length of the
    // request.
    const dialog = await openCard(WITH_PORTRAIT);
    expect(dialog.querySelector(".portrait")?.getAttribute("data-state")).toBe("pending");
    expect(dialog.querySelector(".portrait-monogram")?.textContent).toBe("BR");
  });

  it("hides the monogram once the picture has painted, not before", async () => {
    // A cut-out has a transparent ground, so letters left behind it show through around the
    // player's shoulders. The stylesheet keys off this attribute.
    const dialog = await openCard(WITH_PORTRAIT);
    act(() => {
      portraitIn(dialog)?.dispatchEvent(new Event("load"));
    });
    await waitFor(() => {
      expect(dialog.querySelector(".portrait")?.getAttribute("data-state")).toBe("loaded");
    });
    // Still in the DOM and still `aria-hidden`; the stylesheet, not React, takes it away.
    expect(dialog.querySelector(".portrait-monogram")).not.toBeNull();
  });

  it("reserves the frame either way, so nothing moves when a picture arrives", async () => {
    const withPortrait = await openCard(WITH_PORTRAIT);
    expect(withPortrait.querySelector(".portrait")).not.toBeNull();
    cleanup();
    serve();
    const without = await openCard(WITHOUT_PORTRAIT);
    expect(without.querySelector(".portrait")).not.toBeNull();
  });
});

// --------------------------------------------------------------------------------------
// One player at a time

describe("switching players", () => {
  it("does not leave the previous player's face under the next player's name", async () => {
    const user = await openBoard();
    await user.click(screen.getByRole("button", { name: WITH_PORTRAIT }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: WITH_PORTRAIT })).toBeDefined();
    });
    const first = portraitIn(screen.getByRole("dialog"))?.getAttribute("src");

    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Josh Allen" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Josh Allen" })).toBeDefined();
    });
    const second = portraitIn(screen.getByRole("dialog"))?.getAttribute("src");

    expect(second).toBe(publishedUrlFor("Josh Allen"));
    expect(second).not.toBe(first);
  });

  it("clears a failure from the previous player", async () => {
    const user = await openBoard();
    await user.click(screen.getByRole("button", { name: WITH_PORTRAIT }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: WITH_PORTRAIT })).toBeDefined();
    });
    act(() => {
      portraitIn(screen.getByRole("dialog"))?.dispatchEvent(new Event("error"));
    });
    await waitFor(() => {
      expect(portraitIn(screen.getByRole("dialog"))).toBeNull();
    });

    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Josh Allen" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Josh Allen" })).toBeDefined();
    });
    // One provider 404 is not evidence about the next player.
    expect(portraitIn(screen.getByRole("dialog"))?.getAttribute("src")).toBe(
      publishedUrlFor("Josh Allen"),
    );
  });
});

// --------------------------------------------------------------------------------------
// It says nothing, on purpose

describe("what a screen reader gets", () => {
  it("presents the picture as decoration rather than as a second heading", async () => {
    const dialog = await openCard(WITH_PORTRAIT);
    const image = portraitIn(dialog);
    expect(image?.getAttribute("alt")).toBe("");
    expect(image?.getAttribute("aria-label")).toBeNull();
    // `alt=""` removes it from the accessibility tree, so no image should be reachable by
    // role inside the card at all.
    expect(dialog.querySelectorAll("img[alt]:not([alt=''])")).toHaveLength(0);
  });

  it("hides the monogram and the veil too", async () => {
    const dialog = await openCard(WITHOUT_PORTRAIT);
    expect(dialog.querySelector(".portrait-monogram")?.getAttribute("aria-hidden")).toBe("true");
    expect(dialog.querySelector(".portrait-veil")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("still names the player once, in the heading", async () => {
    await openCard(WITH_PORTRAIT);
    expect(screen.getAllByRole("heading", { name: WITH_PORTRAIT })).toHaveLength(1);
  });
});

// --------------------------------------------------------------------------------------
// The monogram itself

describe("initialsOf", () => {
  it("takes the first and last name", () => {
    expect(initialsOf("Bijan Robinson")).toBe("BR");
    expect(initialsOf("Amon-Ra Bright")).toBe("AB");
  });

  it("handles a middle name by ignoring it", () => {
    expect(initialsOf("James Cook III")).toBe("JI");
  });

  it("handles one word", () => {
    expect(initialsOf("Ocho")).toBe("O");
  });

  it("never renders empty, because an empty frame reads as a bug", () => {
    expect(initialsOf("")).toBe("—");
    expect(initialsOf("   ")).toBe("—");
  });
});
