/**
 * The portrait's own state across player switches (ADR-087, portrait_population_v1).
 *
 * `playercard-portrait.test.tsx` drives the whole App and switches players by closing one
 * card and opening another. These render the component alone and change its `imageUrl` in
 * place — what an already-open card does when its subject changes without remounting — so the
 * three states (`pending`, `loaded`, `failed`) are asserted directly:
 *
 * | question                                                   | the failure it rules out              |
 * |------------------------------------------------------------|---------------------------------------|
 * | does a failure from one player stick to the next?           | the next card's real picture hidden    |
 * | does "loaded" from one player carry to the next?            | the monogram hidden over an empty frame|
 * | does a failed picture ask again on every render?            | a retry loop against the provider      |
 * | does a player with no published address request anything?  | a request with no address              |
 *
 * Written to probe for a defect before touching the component; every case passes on the
 * component as it stands, so `PlayerPortrait.tsx` is unchanged.
 */

import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { PlayerPortrait } from "../src/components/PlayerPortrait";
import {
  FIXTURE_GENERATED_AT,
  FIXTURE_UNSIGNED_ID,
  fixtureFiles,
  inSeasonFixtureFiles,
  playerHeadshotEnvelope,
} from "./fixtures/artifacts";
import { required } from "./required";
import { stubSite } from "./site";

const COUSINS = "https://a.espncdn.com/i/headshots/nfl/players/full/14880.png";
const GIBBS = "https://a.espncdn.com/i/headshots/nfl/players/full/4429795.png";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function frame(container: HTMLElement): HTMLElement {
  const element = container.querySelector<HTMLElement>(".portrait");
  if (element === null) throw new Error("no portrait frame");
  return element;
}

function image(container: HTMLElement): HTMLImageElement | null {
  return container.querySelector("img.portrait-image");
}

describe("switching the player in place", () => {
  it("does not carry a failure to the next player", () => {
    const { container, rerender } = render(<PlayerPortrait name="Jahmyr Gibbs" position="RB" imageUrl={GIBBS} />);
    act(() => {
      image(container)?.dispatchEvent(new Event("error"));
    });
    expect(image(container)).toBeNull();
    expect(frame(container).getAttribute("data-state")).toBe("monogram");

    rerender(<PlayerPortrait name="Kirk Cousins" position="QB" imageUrl={COUSINS} />);
    expect(image(container)?.getAttribute("src")).toBe(COUSINS);
    expect(frame(container).getAttribute("data-state")).toBe("pending");
    expect(container.querySelector(".portrait-monogram")?.textContent).toBe("KC");
  });

  it("does not carry a painted picture to the next player", () => {
    const { container, rerender } = render(<PlayerPortrait name="Jahmyr Gibbs" position="RB" imageUrl={GIBBS} />);
    act(() => {
      image(container)?.dispatchEvent(new Event("load"));
    });
    expect(frame(container).getAttribute("data-state")).toBe("loaded");

    rerender(<PlayerPortrait name="Kirk Cousins" position="QB" imageUrl={COUSINS} />);
    // Pending, so the monogram shows until *this* player's picture paints.
    expect(frame(container).getAttribute("data-state")).toBe("pending");
    // A new element, not the old one with a new `src`: the old face is never left painted.
    expect(container.querySelectorAll("img.portrait-image")).toHaveLength(1);
    expect(image(container)?.getAttribute("src")).toBe(COUSINS);
  });

  it("asks again for a player it failed on, after showing someone else", () => {
    const { container, rerender } = render(<PlayerPortrait name="Kirk Cousins" position="QB" imageUrl={COUSINS} />);
    act(() => {
      image(container)?.dispatchEvent(new Event("error"));
    });
    rerender(<PlayerPortrait name="Jahmyr Gibbs" position="RB" imageUrl={GIBBS} />);
    rerender(<PlayerPortrait name="Kirk Cousins" position="QB" imageUrl={COUSINS} />);
    expect(image(container)?.getAttribute("src")).toBe(COUSINS);
    expect(frame(container).getAttribute("data-state")).toBe("pending");
  });
});

describe("no retry loop", () => {
  it("stays on the monogram when the same card re-renders after a failure", () => {
    const { container, rerender } = render(<PlayerPortrait name="Kirk Cousins" position="QB" imageUrl={COUSINS} />);
    act(() => {
      image(container)?.dispatchEvent(new Event("error"));
    });
    for (let index = 0; index < 5; index += 1) {
      rerender(<PlayerPortrait name="Kirk Cousins" position="QB" imageUrl={COUSINS} />);
    }
    // No element, so no request: one refusal from the provider is the answer for this card.
    expect(image(container)).toBeNull();
    expect(frame(container).getAttribute("data-state")).toBe("monogram");
  });
});

describe("a player with no published address", () => {
  it("renders no image at all, and picks one up when the next player has one", () => {
    const { container, rerender } = render(<PlayerPortrait name="Gunnar Oakes" position="TE" imageUrl={null} />);
    expect(image(container)).toBeNull();
    expect(frame(container).getAttribute("data-state")).toBe("monogram");
    expect(container.querySelector(".portrait-monogram")?.textContent).toBe("GO");

    rerender(<PlayerPortrait name="Kirk Cousins" position="QB" imageUrl={COUSINS} />);
    expect(image(container)?.getAttribute("src")).toBe(COUSINS);
    expect(image(container)?.getAttribute("referrerpolicy")).toBe("no-referrer");
  });
});

// --------------------------------------------------------------------------------------
// The whole path, for a player the tier board never named (the 2026-11-06 Cousins trace)

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
/** A fictional provider id for the fixture's verified free agent, who is on no draft board. */
const ASHBY_PORTRAIT = "https://a.espncdn.com/i/headshots/nfl/players/full/4000090.png";

/** The browser fixture's portraits, widened as `portrait_population_v1` widens production's. */
function widenedHeadshots(): ReturnType<typeof playerHeadshotEnvelope> {
  const base = playerHeadshotEnvelope();
  const first = required(base.records[0], "a fixture portrait");
  const records = [
    ...base.records,
    { ...first, player_id: FIXTURE_UNSIGNED_ID, provider_player_id: "4000090", image_url: ASHBY_PORTRAIT },
  ];
  return { ...base, records, record_count: records.length };
}

async function openAshby(): Promise<HTMLElement> {
  window.history.replaceState(null, "", "/?view=opportunity&scoring=ppr&teams=12&search=Ashby");
  render(<App />);
  const section = await waitFor(() =>
    required(screen.getByRole("heading", { name: "Not projected" }).closest("section"), "the Not projected section"),
  );
  await userEvent.setup().click(within(section).getByRole("button", { name: "Darnell Ashby" }));
  const dialog = await waitFor(() => screen.getByRole("dialog"));
  expect(within(dialog).getByRole("heading", { name: "Darnell Ashby" })).toBeDefined();
  return dialog;
}

describe("an in-season card for a player off every draft board", () => {
  it("draws the portrait the build published for him", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true), "player_headshots.json": widenedHeadshots() });
    const dialog = await openAshby();
    const picture = required(dialog.querySelector<HTMLImageElement>("img.portrait-image"), "his portrait");
    expect(picture.getAttribute("src")).toBe(ASHBY_PORTRAIT);
    expect(picture.getAttribute("referrerpolicy")).toBe("no-referrer");
    // Only the opened card names the third-party host; the board drew no picture.
    expect(document.querySelectorAll("img.portrait-image")).toHaveLength(1);
  });

  it("draws the monogram when the build published none (the defect, reproduced)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
    // The browser fixture's own portrait set is the draft board's, as production's was.
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true) });
    const dialog = await openAshby();
    expect(dialog.querySelector("img.portrait-image")).toBeNull();
    expect(dialog.querySelector(".portrait-monogram")?.textContent).toBe("DA");
  });
});
