/**
 * The Trade tab (ADR-100) as a reader meets it: from a URL, through the controls, into the
 * player card. The arithmetic is `trade.test.ts`; these cover the sentences, the URL and the
 * exploration flow.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
const BIJAN = "00-0000001";

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

async function open(query: string): Promise<void> {
  go(query);
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Trade targets" })).toBeDefined();
  });
}

function packages(): HTMLElement[] {
  const list = screen.queryByRole("list", { name: /Suggested packages/ });
  return list === null ? [] : within(list).getAllByRole("listitem").filter((item) => item.classList.contains("trade-package"));
}

function packageNames(): string[] {
  return packages().map((item) => item.getAttribute("aria-label") ?? "");
}

function params(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
  go();
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles() });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
  go();
});

describe("navigation", () => {
  it("is a sixth in-season tab, third in order, and Opportunity keeps its full accessible name", async () => {
    await open("?view=trade");
    const tabs = within(screen.getByRole("tablist", { name: "Board" })).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "ROS tiers",
      "Start/Sit",
      "Trade",
      "OpportunityOpp",
      "POTW",
      "Data",
    ]);
    expect(screen.getByRole("tab", { name: "Opportunity" })).toBeDefined();
    expect(screen.getByRole("tab", { name: "Trade" }).getAttribute("aria-selected")).toBe("true");
  });

  it("arrow keys move into and out of the tab, and focus follows", async () => {
    go("?view=startsit");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Start/Sit" }).getAttribute("aria-selected")).toBe("true");
    });
    const startsit = screen.getByRole("tab", { name: "Start/Sit" });
    startsit.focus();
    fireEvent.keyDown(startsit, { key: "ArrowRight" });
    await waitFor(() => {
      expect(params().get("view")).toBe("trade");
    });
    await waitFor(() => {
      expect(document.activeElement?.id).toBe("tab-trade");
    });
  });

  it("without an in-season bundle the tab says so and the draft board is untouched", async () => {
    stubSite(fixtureFiles());
    go("?view=trade");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("No rest-of-season board has been published yet.")).toBeDefined();
    });
  });
});

describe("choosing what to give", () => {
  it("adds from the search, refuses duplicates, caps at three and removes", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open("?view=trade");
    expect(screen.getByText(/Add one to three players you would trade away/)).toBeDefined();

    const box = screen.getByRole("combobox", { name: "Add a player you would give" });
    await user.type(box, "Bijan");
    const listbox = screen.getByRole("listbox", { name: "Players" });
    expect(within(listbox).getAllByRole("option")[0]?.textContent).toContain("Bijan Robinson");
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(params().get("give")).toBe(BIJAN);
    });

    // Already given: not offered again.
    await user.type(box, "Bijan");
    expect(screen.queryByRole("option", { name: /Bijan Robinson/ })).toBeNull();
    await user.clear(box);

    for (const name of ["Puka", "Trey"]) {
      await user.type(box, name);
      await user.keyboard("{Enter}");
    }
    await waitFor(() => {
      expect(params().get("give")?.split(".")).toHaveLength(3);
    });
    expect(screen.getByRole("combobox", { name: "Add a player you would give" }).hasAttribute("disabled")).toBe(true);

    await user.click(screen.getByRole("button", { name: "Remove Bijan Robinson from what you give" }));
    await waitFor(() => {
      expect(params().get("give")?.split(".")).toHaveLength(2);
    });
    expect(params().get("give")).not.toContain(BIJAN);
  });

  it("a link with an id this board does not hold says so and counts it for nothing", async () => {
    await open(`?view=trade&give=00-0999999.${BIJAN}`);
    expect(screen.getByText(/1 player in this link is not on this board/)).toBeDefined();
    expect(packages().length).toBeGreaterThan(0);
  });

  it("an outgoing value at or below replacement generates nothing and says why", async () => {
    await open("?view=trade&give=00-0000009"); // Joe Burrow, negative on the fixture board
    expect(screen.getByText("Nothing to trade for.")).toBeDefined();
    expect(packages()).toHaveLength(0);
  });
});

describe("the results", () => {
  it("states the shape, the horizon and the one disclaimer, then up to five packages of the requested size", async () => {
    await open(`?view=trade&give=${BIJAN}&get=2&range=35`);
    expect(screen.getByText("Give 1 · Receive 2")).toBeDefined();
    expect(screen.getByText("Needs 1 open roster spot")).toBeDefined();
    expect(screen.getByText(/Weeks 9–17 \(9 weeks\), including weeks 15–17/)).toBeDefined();
    expect(screen.getByText(/NFL week 18 is not counted. There is no playoff-only projection/)).toBeDefined();
    expect(screen.getAllByText("Model-based targets.")).toHaveLength(1);
    const items = packages();
    expect(items.length).toBeGreaterThan(0);
    expect(items.length).toBeLessThanOrEqual(5);
    for (const item of items) {
      expect(within(item).getAllByRole("button", { name: /./ }).filter((b) => b.classList.contains("player-name"))).toHaveLength(2);
      expect(within(item).getByText(/inside ±35%/)).toBeDefined();
      // Two players: approximate floors and ceilings, marked.
      expect(item.textContent).toMatch(/~-?\d/);
    }
    expect(screen.getByRole("status", { name: "" }).textContent ?? "").toMatch(/packages? shown of \d+ that qualify, ranked by ROS value/);
  });

  it("switching to ceiling re-ranks the same comparable pool and prints the ceiling comparison", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open(`?view=trade&give=${BIJAN}&get=2&range=35`);
    const count = screen.getByText(/packages? qualify/).textContent;
    await user.click(screen.getByRole("radio", { name: "Highest ceiling" }));
    await waitFor(() => {
      expect(params().get("goal")).toBe("ceiling");
    });
    expect(screen.getByText(/packages? qualify/).textContent).toBe(count);
    for (const item of packages()) expect(item.textContent).toMatch(/Ceiling ~[\d.]+ vs your [\d.]+/);
  });

  it("filters by composition", async () => {
    await open(`?view=trade&give=${BIJAN}&get=2&range=50&comp=rb.wr`);
    const items = packages();
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      const tags = [...item.querySelectorAll(".trade-members .pos-tag")].map((tag) => tag.textContent).sort();
      expect(tags).toEqual(["RB", "WR"]);
    }
    expect(screen.getByText("RB + WR")).toBeDefined();
  });

  it("explains an empty pool and broadens only when asked", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open(`?view=trade&give=${BIJAN}&get=3&range=10&comp=qb.qb.qb`);
    expect(screen.getByText("No package qualifies.")).toBeDefined();
    expect(params().get("range")).toBe("10");
    await user.click(screen.getByRole("button", { name: "Widen to ±20%" }));
    await waitFor(() => {
      expect(params().get("range")).toBeNull();
    });
    expect(screen.getByRole("button", { name: "Any positions" })).toBeDefined();
  });

  it("lists players who are not targets, with the reason", async () => {
    await open(`?view=trade&give=${BIJAN}`);
    const details = document.querySelector("details.trade-excluded");
    expect(details).not.toBeNull();
    expect(details?.textContent).toMatch(/Long absence: has not appeared for 3 weeks/);
  });

  it("a player's name opens his card", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open(`?view=trade&give=${BIJAN}&get=2&range=35`);
    const first = packages()[0];
    if (first === undefined) throw new Error("no package");
    const name = first.querySelector<HTMLButtonElement>(".trade-members .player-name");
    if (name === null) throw new Error("no name");
    await user.click(name);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });
  });
});

describe("exploring", () => {
  it("swap replaces one package, writes a reproducible URL, and Back undoes it", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open(`?view=trade&give=${BIJAN}&get=2&range=50`);
    const before = packageNames();
    expect(before.length).toBe(5);
    await user.click(screen.getByRole("button", { name: "Swap package 2 for another" }));
    await waitFor(() => {
      expect(params().get("shown")).not.toBeNull();
    });
    const after = packageNames();
    expect(after[1]).not.toBe(before[1]);
    expect(after.filter((_, index) => index !== 1)).toEqual(before.filter((_, index) => index !== 1));
    expect(params().get("stamp")).toMatch(/^[0-9a-f]{8}$/);

    // The same URL renders the same selection.
    const url = window.location.search;
    cleanup();
    await open(url);
    expect(packageNames()).toEqual(after);

    window.history.back();
    await waitFor(() => {
      expect(params().get("shown")).toBeNull();
    });
  });

  it("keep pins a package through More targets and a control change, until it stops qualifying", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open(`?view=trade&give=${BIJAN}&get=2&range=50`);
    const kept = packageNames()[0] ?? "";
    const first = packages()[0];
    if (first === undefined) throw new Error("no package");
    await user.click(within(first).getByRole("button", { name: "Keep" }));
    await waitFor(() => {
      expect(params().get("keep")).not.toBeNull();
    });
    expect(screen.getByText("Kept (1 of 3)")).toBeDefined();
    expect(packageNames()).not.toContain(kept);

    await user.click(screen.getByRole("button", { name: "More targets" }));
    expect(screen.getByText("Kept (1 of 3)")).toBeDefined();

    await user.click(screen.getByRole("radio", { name: "Highest floor" }));
    await waitFor(() => {
      expect(params().get("goal")).toBe("floor");
    });
    const shelf = screen.getByText("Kept (1 of 3)").closest(".trade-kept");
    expect(shelf?.textContent).not.toContain("No longer qualifies");

    await user.click(screen.getByRole("radio", { name: "Receive 3 players" }));
    await waitFor(() => {
      expect(params().get("get")).toBe("3");
    });
    expect(screen.getByText("Kept (1 of 3)").closest(".trade-kept")?.textContent).toContain(
      "No longer qualifies: it is not the number of players you asked to receive",
    );

    await user.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => {
      expect(params().get("keep")).toBeNull();
    });
    expect(screen.queryByText(/^Kept \(/)).toBeNull();
  });

  it("a link made on another board is re-dealt from the start, and says so", async () => {
    await open(`?view=trade&give=${BIJAN}&get=2&range=50&shown=4.5&dealt=6&stamp=00000000`);
    expect(screen.getByText("Re-dealt from the start.")).toBeDefined();
    expect(packageNames()).toHaveLength(5);
  });

  it("More targets eventually runs out and says so", async () => {
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await open(`?view=trade&give=${BIJAN}&get=2&range=50`);
    const more = screen.getByRole("button", { name: "More targets" });
    for (let i = 0; i < 40 && !more.hasAttribute("disabled"); i += 1) await user.click(more);
    expect(more.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/has been dealt\. Widen the value range/)).toBeDefined();
  });
});

describe("the Data view", () => {
  it("documents the method beside the rest-of-season build", async () => {
    go("?view=data&mode=in_season");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Trade targets — method" })).toBeDefined();
    });
    const section = screen.getByRole("heading", { name: "Trade targets — method" }).closest("section");
    expect(section?.textContent).toContain("trade_targets_v1");
    expect(section?.textContent).toContain("ros_package_quantiles_v1");
    expect(section?.textContent).toContain("±20% of expected value");
    expect(section?.textContent).toContain("there is no playoff-only projection");
  });
});
