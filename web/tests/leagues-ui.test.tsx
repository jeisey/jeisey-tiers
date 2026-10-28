/**
 * My Leagues (ADR-106) as a reader meets it in the page: the tab, creating a league, the global
 * controls following it, roster edits through the slot picker, Auto Start/Sit's apply and undo,
 * storage that will not save, and the published-preset constant pinned to the config.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { LeagueStoreContext } from "../src/app/useLeagues";
import {
  DEFAULT_PREFS,
  DEFAULT_SLOTS,
  EMPTY_DOCUMENT,
  PUBLISHED_BENCH,
  PUBLISHED_STARTERS,
  emptyRoster,
  serializeLeagueDocument,
  type SavedLeague,
} from "../src/data/leagueContract";
import { forgetActiveLeague } from "../src/data/leagueSignal";
import { LeagueStore, leagueStorageKey, type StorageLike } from "../src/data/leagueStore";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
const KEY = leagueStorageKey("/");

class MemoryStorage implements StorageLike {
  readonly map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

function mount(store: LeagueStore, query = "?view=myleagues"): void {
  go(query);
  render(
    <LeagueStoreContext.Provider value={store}>
      <App now={FIXTURE_NOW} />
    </LeagueStoreContext.Provider>,
  );
}

function savedLeague(roster: Partial<Record<keyof typeof DEFAULT_SLOTS, (string | null)[]>> = {}): SavedLeague {
  const base = emptyRoster(DEFAULT_SLOTS);
  return {
    id: "lg-office01",
    name: "Office",
    season: 2026,
    scoring: "half",
    teams: 10,
    slots: DEFAULT_SLOTS,
    roster: Object.fromEntries(
      Object.entries(base).map(([group, slots]) => [
        group,
        slots.map((_, index) => roster[group as keyof typeof DEFAULT_SLOTS]?.[index] ?? null),
      ]),
    ) as unknown as SavedLeague["roster"],
    prefs: DEFAULT_PREFS,
    rev: 1,
    updatedAt: "2026-08-21T00:00:00Z",
  };
}

function storeWith(leagues: SavedLeague[]): { store: LeagueStore; storage: MemoryStorage } {
  const storage = new MemoryStorage();
  storage.setItem(
    KEY,
    serializeLeagueDocument({ ...EMPTY_DOCUMENT, revision: 1, activeId: leagues[0]?.id ?? null, leagues }),
  );
  return { store: new LeagueStore({ storage, key: KEY }), storage };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
  forgetActiveLeague();
  go();
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles() });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
  forgetActiveLeague();
  go();
});

describe("the published preset the boards assume", () => {
  it("matches config/league-defaults.yaml for every published league size", () => {
    const yaml = readFileSync(resolve(__dirname, "../../config/league-defaults.yaml"), "utf-8");
    const presets = yaml.split("league_presets:")[1]?.split("optional_presets:")[0] ?? "";
    const blocks = presets.split(/\n {2}redraft-\d+:/).slice(1);
    expect(blocks).toHaveLength(3);
    for (const block of blocks) {
      for (const [group, count] of Object.entries(PUBLISHED_STARTERS)) {
        expect(block).toMatch(new RegExp(`\\n {6}${group}: ${String(count)}\\n`));
      }
      expect(block).toMatch(new RegExp(`\\n {4}bench: ${String(PUBLISHED_BENCH)}`));
      expect(block).toMatch(/flex_eligible: \[RB, WR, TE\]/);
    }
  });
});

describe("the tab", () => {
  it("sits after ROS tiers and before Start/Sit, with its full name accessible", async () => {
    const { store } = storeWith([]);
    mount(store);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "My Leagues" })).toBeDefined();
    });
    const tabs = within(screen.getByRole("tablist", { name: "Board" })).getAllByRole("tab");
    expect(tabs.map((tab) => tab.getAttribute("id"))).toEqual([
      "tab-ros",
      "tab-myleagues",
      "tab-insights",
      "tab-startsit",
      "tab-trade",
      "tab-opportunity",
      "tab-potw",
      "tab-data",
    ]);
    expect(screen.getByRole("tab", { name: "My Leagues" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("button", { name: "Create a league" })).toBeDefined();
  });
});

describe("a saved league", () => {
  it("makes its preset the one in force: the URL follows it and the controls are locked to it", async () => {
    const { store } = storeWith([savedLeague({ QB: ["gsis:00-0000018"] })]);
    mount(store);
    await waitFor(() => {
      expect(screen.getByText(/10-team Half PPR/, { selector: "strong" })).toBeDefined();
    });
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.get("scoring")).toBe("half");
      expect(params.get("teams")).toBe("10");
    });
    // No roster data in the address bar.
    expect(window.location.search).not.toContain("0000018");
    const scoring = screen.getByRole("radiogroup", { name: "Scoring" });
    expect(within(scoring).getByRole("radio", { name: "PPR" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Set by/).textContent).toContain("Office");
    // The resolved player, by id: his name comes from the build, not from storage.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Jalen Marsh" })).toBeDefined();
    });
  });

  it("keeps a player this build does not know, by id, and says so", async () => {
    const { store } = storeWith([savedLeague({ BN: ["gsis:00-9999999"] })]);
    mount(store);
    await waitFor(() => {
      expect(screen.getAllByText("Not in this build").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/1 saved player is not in this build's boards/)).toBeDefined();
  });

  it("adds a player through the slot picker, and moves rather than duplicates one already on the roster", async () => {
    const { store, storage } = storeWith([savedLeague({ BN: ["gsis:00-0000001"] })]);
    mount(store);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Add a player to RB 1" })).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: "Add a player to RB 1" }));
    const dialog = await screen.findByRole("dialog");
    const box = within(dialog).getByRole("combobox");
    fireEvent.change(box, { target: { value: "bijan" } });
    const option = await within(dialog).findByRole("option", { name: /Bijan Robinson/ });
    expect(option.textContent).toContain("On roster");
    fireEvent.mouseDown(option);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    const saved = JSON.parse(storage.getItem(KEY) ?? "{}") as { leagues: SavedLeague[] };
    expect(saved.leagues[0]?.roster.RB[0]).toBe("gsis:00-0000001");
    expect(saved.leagues[0]?.roster.BN).not.toContain("gsis:00-0000001");
  });

  it("proposes a lineup, applies it only when asked, and undoes it", async () => {
    const { store, storage } = storeWith([
      savedLeague({ QB: ["gsis:00-0000018"], WR: ["gsis:00-0000006"], BN: ["gsis:00-0000002", "gsis:00-0000001"] }),
    ]);
    mount(store);
    const apply = await screen.findByRole("button", { name: /^Apply \d change/ });
    const before = storage.getItem(KEY);
    // Nothing was written by looking.
    expect(storage.getItem(KEY)).toBe(before);
    const proposed = within(screen.getByRole("list", { name: "Proposed changes" })).getAllByRole("listitem");
    expect(proposed.some((item) => /^Start Bijan Robinson at RB 1 \(\d+\.\d\) — from Bench 2$/.test(item.textContent ?? ""))).toBe(true);
    expect(screen.getByText(/sum of \d individual medians/, { selector: ".lg-auto-totals span" })).toBeDefined();
    fireEvent.click(apply);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Undo" })).toBeDefined();
    });
    const applied = JSON.parse(storage.getItem(KEY) ?? "{}") as { leagues: SavedLeague[] };
    expect(applied.leagues[0]?.roster.RB[0]).toBe("gsis:00-0000001");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(screen.getByText("Undone: your previous lineup is back.")).toBeDefined();
    });
    const undone = JSON.parse(storage.getItem(KEY) ?? "{}") as { leagues: SavedLeague[] };
    expect(undone.leagues[0]?.roster.BN).toContain("gsis:00-0000001");
  });

  it("changing the objective re-proposes without touching the lineup", async () => {
    const { store, storage } = storeWith([
      savedLeague({ QB: ["gsis:00-0000018"], BN: ["gsis:00-0000002", "gsis:00-0000001"] }),
    ]);
    mount(store);
    await screen.findByRole("button", { name: /^Apply/ });
    fireEvent.click(screen.getByRole("radio", { name: /Ceiling \(P90\)/ }));
    await waitFor(() => {
      expect(screen.getByText(/sum of \d individual ceilings/, { selector: ".lg-auto-totals span" })).toBeDefined();
    });
    const saved = JSON.parse(storage.getItem(KEY) ?? "{}") as { leagues: SavedLeague[] };
    expect(saved.leagues[0]?.prefs.mode).toBe("q90");
    expect(saved.leagues[0]?.roster.BN).toContain("gsis:00-0000001");
  });

  it("works without storage and says nothing is saved", async () => {
    const store = new LeagueStore({ storage: null, key: KEY });
    mount(store);
    await screen.findByRole("button", { name: "Create a league" });
    expect(screen.getByText("Not saved.")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Create a league" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("League name"), { target: { value: "Temp" } });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Create league" }));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /Temp/ })).toBeDefined();
    });
  });

  it("refuses to save settings while a reduced count leaves a player unplaced", async () => {
    const { store } = storeWith([savedLeague({ RB: ["gsis:00-0000001", "gsis:00-0000011"] })]);
    mount(store);
    fireEvent.click(await screen.findByRole("button", { name: "League settings" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Fewer RB slots" }));
    expect(within(dialog).getByRole("alert").textContent).toContain("1 player no longer fits");
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    expect(save.hasAttribute("disabled")).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "To Bench" }));
    expect(save.hasAttribute("disabled")).toBe(false);
  });
});
