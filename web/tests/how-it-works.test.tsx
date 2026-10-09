/**
 * "How it works" on the Data page: the plain-English model boards.
 *
 * What these pin: the section lives on the Data page and nowhere else, the arrows cycle and
 * wrap, the arrow keys work from inside the carousel, every board can be reached directly,
 * and the one measured number the boards print comes from the build — with no in-season build
 * the start/sit board says it in words and prints no percentage.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

async function openData(inSeason: boolean): Promise<HTMLElement> {
  stubSite({ ...fixtureFiles(), ...(inSeason ? inSeasonFixtureFiles(true) : {}) });
  go("?view=data");
  render(<App now={FIXTURE_NOW} />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "How it works" })).toBeDefined();
  });
  // The boards are their own chunk, loaded with the Data page.
  return screen.findByRole("region", { name: "How the models work" });
}

function boardTitle(carousel: HTMLElement): string {
  return within(carousel).getByRole("heading", { level: 3 }).textContent ?? "";
}

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
  go();
});

describe("How it works", () => {
  it("opens on the mission map and cycles both ways, wrapping at the ends", async () => {
    const user = userEvent.setup();
    const carousel = await openData(false);
    expect(boardTitle(carousel)).toBe("Mission map");

    await user.click(within(carousel).getByRole("button", { name: "Next board" }));
    expect(boardTitle(carousel)).toBe("The draft model");

    await user.click(within(carousel).getByRole("button", { name: "Previous board" }));
    await user.click(within(carousel).getByRole("button", { name: "Previous board" }));
    expect(boardTitle(carousel)).toBe("Rules of engagement");

    await user.click(within(carousel).getByRole("button", { name: "Next board" }));
    expect(boardTitle(carousel)).toBe("Mission map");
  });

  it("moves with the arrow keys from inside the carousel", async () => {
    const carousel = await openData(false);
    const next = within(carousel).getByRole("button", { name: "Next board" });
    fireEvent.keyDown(next, { key: "ArrowRight" });
    fireEvent.keyDown(next, { key: "ArrowRight" });
    expect(boardTitle(carousel)).toBe("Simulation, value and tiers");
    fireEvent.keyDown(next, { key: "ArrowLeft" });
    expect(boardTitle(carousel)).toBe("The draft model");
  });

  it("reaches every board directly and marks the current one", async () => {
    const user = userEvent.setup();
    const carousel = await openData(false);
    const dots = within(carousel).getAllByRole("button", { name: /^Board \d+:/ });
    expect(dots).toHaveLength(9);
    await user.click(within(carousel).getByRole("button", { name: "Board 7: Start/Sit v2" }));
    expect(boardTitle(carousel)).toBe("Start/Sit v2");
    expect(
      within(carousel).getByRole("button", { name: "Board 7: Start/Sit v2" }).getAttribute("aria-current"),
    ).toBe("true");
    // Status is a word, not a colour.
    expect(within(carousel).getByText("Shadow ops")).toBeDefined();
  });

  it("prints the start/sit holdout accuracy only from the build that published it", async () => {
    const user = userEvent.setup();
    const carousel = await openData(true);
    await user.click(within(carousel).getByRole("button", { name: "Board 6: Start/Sit v1" }));
    expect(within(carousel).getByText(/picked the better of two players 67% of the time, against 65%/)).toBeDefined();
  });

  it("says it in words when no in-season build is published", async () => {
    const user = userEvent.setup();
    const carousel = await openData(false);
    await user.click(within(carousel).getByRole("button", { name: "Board 6: Start/Sit v1" }));
    const record = within(carousel).getByText(/more often than every simple shortcut/);
    expect(record.textContent).not.toMatch(/\d+%/);
  });

  it("lives on the Data page only", async () => {
    stubSite(fixtureFiles());
    go("?view=tiers");
    render(<App now={FIXTURE_NOW} />);
    await waitFor(() => {
      expect(document.querySelector("main")).not.toBeNull();
    });
    expect(screen.queryByRole("heading", { name: "How it works" })).toBeNull();
    expect(screen.queryByRole("region", { name: "How the models work" })).toBeNull();
  });
});
