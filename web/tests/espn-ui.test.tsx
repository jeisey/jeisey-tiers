/**
 * ESPN roster/start readings in the rendered page (ADR-112): the Opportunity Board's column,
 * ceiling and discovery rule, the shared-link handling for a build that cannot apply them, and
 * the card's reading with its lazily loaded history.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import type { EspnFixtureMode } from "./fixtures/espn";
import { required } from "./required";
import { setMediaQuery } from "./setup";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
const SHEET = "(max-width: 767px)";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function serve(espn: EspnFixtureMode = "present"): void {
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true, { espn }) });
}

function requests(fragment: string): string[] {
  const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
  return calls.map((call) => String(call[0])).filter((url) => url.includes(fragment));
}

async function openBoard(query: string): Promise<void> {
  window.history.replaceState(null, "", `/?view=opportunity&scoring=ppr&teams=12${query}`);
  render(<App now={FIXTURE_NOW} />);
  await waitFor(
    () => {
      expect(screen.getByRole("heading", { name: /Opportunity — through week/ })).toBeDefined();
    },
    { timeout: 10_000 },
  );
}

async function openCard(name: string): Promise<HTMLElement> {
  fireEvent.click(required(screen.getAllByRole("button", { name })[0], name));
  await waitFor(
    () => {
      expect(screen.getByRole("heading", { name })).toBeDefined();
    },
    { timeout: 10_000 },
  );
  return screen.getByRole("dialog");
}

describe("on the Opportunity Board", () => {
  it("shows ESPN's column and ceiling, loads the summary slice and never the history", async () => {
    serve();
    await openBoard("");
    expect(screen.getAllByRole("button", { name: /ESPN rost/ }).length).toBeGreaterThan(0);
    const group = screen.getByRole("radiogroup", { name: "ESPN rostered" });
    expect(within(group).getAllByRole("radio").map((radio) => radio.textContent)).toEqual([
      "All",
      "<10%",
      "<25%",
      "<50%",
      "<75%",
    ]);
    expect(requests("/espn_ownership/").length).toBe(1);
    expect(requests("/espn_ownership_series/")).toEqual([]);
    expect(screen.getByText(/ESPN's percentages describe ESPN leagues, not yours/)).toBeDefined();
  });

  it("labels the discovery rule plainly and lists each condition", async () => {
    serve();
    await openBoard("&only=role&espn=lt50");
    const rule = await screen.findByText("Role rising + rostered below 50% on ESPN");
    const block = required(rule.closest(".opp-discovery"), "the discovery block") as HTMLElement;
    expect(within(block).getByText(/^Role rising: \d+ of \d+/)).toBeDefined();
    expect(within(block).getByText(/^Rostered below 50% on ESPN: \d+ of \d+/)).toBeDefined();
    expect(within(block).getByText(/Supporting evidence, not part of the rule/)).toBeDefined();
    expect(screen.getAllByRole("button", { name: "Jalen Marsh" }).length).toBeGreaterThan(0);
  });

  it("disables the ceiling and says why when a shared link names it on an older build", async () => {
    serve("absent");
    await openBoard("&espn=lt25");
    expect(screen.getByText("The ESPN filter in this link cannot be applied to this build.")).toBeDefined();
    const group = screen.getByRole("radiogroup", { name: "ESPN rostered" });
    for (const radio of within(group).getAllByRole("radio").slice(1)) {
      expect((radio as HTMLButtonElement).disabled).toBe(true);
    }
    // The board is not emptied: every row is still on it.
    expect(screen.queryByText("No players match.")).toBeNull();
    expect(screen.getByText(/ESPN roster percentages: not in this build/)).toBeDefined();
  });

  it("treats a stale build as unusable for the filter while still printing its values", async () => {
    serve("stale");
    await openBoard("&espn=lt50");
    expect(screen.getByText("The ESPN filter in this link cannot be applied to this build.")).toBeDefined();
    expect(screen.getAllByText(/past the freshness bound/).length).toBeGreaterThan(0);
    // Values stay visible, labelled stale rather than dropped or refreshed.
    expect(document.querySelector("dl[data-espn=\"stale\"]")?.textContent).toMatch(/stale/);
  });
});

describe("on the player card", () => {
  it("states the reading at once and fetches the history only on activation", async () => {
    serve();
    await openBoard("");
    const dialog = await openCard("Jahmyr Cook");
    expect(
      within(dialog).getByText("Rostered on ESPN: 18% → 31% in 7 days (+13 percentage points)."),
    ).toBeDefined();
    expect(within(dialog).getByText(/read in ESPN period 9/)).toBeDefined();
    expect(requests("/espn_ownership_series/")).toEqual([]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Show ESPN trend" }));
    const chart = await within(dialog).findByTestId("espn-ownership-chart", {}, { timeout: 10_000 });
    expect(requests("/espn_ownership_series/").length).toBe(1);
    // Exact readings without hover: a table of every read, and focusable points.
    expect(within(chart).getByText("Exact readings (9)")).toBeDefined();
    expect(within(chart).getAllByRole("button", { name: /rostered 31% of ESPN leagues/ }).length).toBe(1);
    // Rostered and started on separate, labelled panels.
    expect(within(chart).getByText("Rostered %")).toBeDefined();
    expect(within(chart).getByText("Started %")).toBeDefined();
  });

  it("names a roster-only reading's missing start share instead of a zero", async () => {
    serve();
    await openBoard("");
    const dialog = await openCard("Jaylin Lane");
    const block = within(dialog).getByTestId("espn-block");
    expect(within(block).getByText("unknown, not 0%")).toBeDefined();
  });

  it("says first-day history is one point, without inventing a trend", async () => {
    serve();
    await openBoard("");
    const dialog = await openCard("James Cook III");
    expect(within(dialog).getByText(/no 7-day change \(new since baseline\)/)).toBeDefined();
    fireEvent.click(within(dialog).getByRole("button", { name: "Show ESPN trend" }));
    expect(await within(dialog).findByText(/One retained read so far/, {}, { timeout: 10_000 })).toBeDefined();
  });

  it("is part of the In-season usage tab on a phone, loading when that tab is chosen", async () => {
    setMediaQuery(SHEET, true);
    serve();
    await openBoard("");
    const dialog = await openCard("Jahmyr Cook");
    expect(requests("/espn_ownership_series/")).toEqual([]);
    fireEvent.click(within(dialog).getByRole("tab", { name: "In-season usage" }));
    expect(await within(dialog).findByTestId("espn-ownership-chart", {}, { timeout: 10_000 })).toBeDefined();
    expect(within(dialog).queryByRole("button", { name: "Show ESPN trend" })).toBeNull();
  });
});
