/**
 * Win My Matchup in the page (ADR-110): the league's tool tab, opponent entry through the shared
 * picker, the completeness gate, a simulation that runs only when asked (here on the sliced
 * main-thread fallback: jsdom has no Worker), results that disappear when their inputs change,
 * YOLO's potential pickups, the week rollover and a league switch that shows no other league's
 * numbers.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { WmmStoreContext } from "../src/app/leagues/wmmContext";
import { LeagueStoreContext } from "../src/app/useLeagues";
import { DEFAULT_PREFS, DEFAULT_SLOTS, EMPTY_DOCUMENT, emptyRoster, serializeLeagueDocument, type SavedLeague } from "../src/data/leagueContract";
import { forgetActiveLeague } from "../src/data/leagueSignal";
import { LeagueStore, leagueStorageKey, type StorageLike } from "../src/data/leagueStore";
import { EMPTY_WMM, emptyStarters, newEntry, serializeWmmDocument } from "../src/data/wmmContract";
import { WmmStore, wmmStorageKey } from "../src/data/wmmStore";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
const LEAGUES = leagueStorageKey("/");
const MATCHUPS = wmmStorageKey("/");
const g = (n: string): string => `gsis:00-00000${n}`;

class MemoryStorage implements StorageLike {
  readonly map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
}

function league(id: string, name: string, roster: Partial<Record<keyof typeof DEFAULT_SLOTS, (string | null)[]>>): SavedLeague {
  const base = emptyRoster(DEFAULT_SLOTS);
  return {
    id,
    name,
    season: 2026,
    scoring: "ppr",
    teams: 12,
    slots: DEFAULT_SLOTS,
    roster: Object.fromEntries(
      Object.entries(base).map(([group, slots]) => [group, slots.map((_, index) => roster[group as keyof typeof DEFAULT_SLOTS]?.[index] ?? null)]),
    ) as unknown as SavedLeague["roster"],
    prefs: DEFAULT_PREFS,
    rev: 1,
    updatedAt: "2026-08-21T00:00:00Z",
  };
}

const OFFICE = league("lg-office01", "Office", {
  QB: [g("09")],
  RB: [g("01"), g("16")],
  WR: [g("12"), g("06")],
  TE: [g("04")],
  FLEX: [g("17")],
  BN: [g("07"), g("10")],
});
const FAMILY = league("lg-family01", "Family", { QB: [g("09")], RB: [g("01")] });

/** A complete opponent for week 9: one "if active" receiver, a bye, zeros and an empty TE. */
function opponentDocument(week = 9) {
  return {
    ...newEntry("lg-office01", 2026, week),
    opponent: {
      name: "Rival",
      starters: { ...emptyStarters(), QB: [g("18")], RB: [g("13"), g("14")], WR: [g("02"), g("15")], TE: [null], FLEX: [g("03")] },
      others: [],
    },
    confirmedEmpty: { mine: [], theirs: week === 9 ? ["TE:0"] : [] },
    countZero: week === 9 ? [g("16"), g("04"), g("17"), g("13"), g("14"), g("15"), g("03")] : [],
    rev: 1,
    updatedAt: "2026-08-21T00:00:00Z",
  };
}

function stores(leagues: SavedLeague[], wmm = EMPTY_WMM) {
  const storage = new MemoryStorage();
  storage.setItem(LEAGUES, serializeLeagueDocument({ ...EMPTY_DOCUMENT, revision: 1, activeId: leagues[0]?.id ?? null, leagues }));
  if (wmm !== EMPTY_WMM) storage.setItem(MATCHUPS, serializeWmmDocument(wmm));
  return {
    storage,
    leagues: new LeagueStore({ storage, key: LEAGUES }),
    matchups: new WmmStore({ storage, key: MATCHUPS }),
  };
}

function mount(parts: ReturnType<typeof stores>, query = "?view=myleagues&panel=wmm"): void {
  window.history.replaceState(null, "", `/${query}`);
  render(
    <LeagueStoreContext.Provider value={parts.leagues}>
      <WmmStoreContext.Provider value={parts.matchups}>
        <App now={FIXTURE_NOW} />
      </WmmStoreContext.Provider>
    </LeagueStoreContext.Provider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
  forgetActiveLeague();
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles() });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
  forgetActiveLeague();
  window.history.replaceState(null, "", "/");
});

function simulateButton(): HTMLButtonElement {
  const button = screen.getByRole("button", { name: "Simulate" });
  if (!(button instanceof HTMLButtonElement)) throw new Error("Simulate is not a button");
  return button;
}

async function openWmm(): Promise<HTMLElement> {
  return screen.findByRole("heading", { name: "Win My Matchup — week 9" }, { timeout: 10_000 });
}

describe("the tool tab", () => {
  it("is a tab inside the league, carried in the URL, and runs nothing until asked", async () => {
    const parts = stores([OFFICE], { ...EMPTY_WMM, entries: [opponentDocument()] });
    mount(parts, "?view=myleagues");
    const tabs = await screen.findByRole("tablist", { name: "League tools" }, { timeout: 10_000 });
    expect(within(tabs).getByRole("tab", { name: "Lineup" }).getAttribute("aria-selected")).toBe("true");
    // Not a top-level destination.
    expect(within(screen.getByRole("tablist", { name: "Board" })).queryByRole("tab", { name: /Matchup/ })).toBeNull();
    fireEvent.click(within(tabs).getByRole("tab", { name: "Win My Matchup" }));
    await openWmm();
    expect(window.location.search).toContain("panel=wmm");
    expect(screen.getByText(/kickers and team defenses are not modelled/)).toBeTruthy();
    expect(screen.queryByText(/your modelled lineup wins/)).toBeNull();
    // Opening it wrote nothing.
    expect(parts.storage.map.get(MATCHUPS)).toBe(serializeWmmDocument({ ...EMPTY_WMM, entries: [opponentDocument()] }));
  });
});

describe("opponent entry and completeness", () => {
  it("enters the opponent by id through the picker, never offering my players, and blocks until complete", async () => {
    const parts = stores([OFFICE]);
    mount(parts);
    await openWmm();
    expect(simulateButton().disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Set the opponent's QB" }));
    const dialog = await screen.findByRole("dialog");
    const box = within(dialog).getByRole("combobox");
    // Joe Burrow is on my roster: never offered to the opponent.
    fireEvent.change(box, { target: { value: "Burrow" } });
    expect(within(dialog).queryAllByRole("option")).toHaveLength(0);
    fireEvent.change(box, { target: { value: "Marsh" } });
    const option = await within(dialog).findByRole("option", { name: /Jalen Marsh/ });
    fireEvent.mouseDown(option);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    const saved = parts.storage.map.get(MATCHUPS) ?? "";
    expect(saved).toContain(g("18"));
    expect(saved).not.toContain("Marsh");
    expect(screen.getByText(/Simulate needs \d+ decisions/)).toBeTruthy();
    expect(simulateButton().disabled).toBe(true);
    // The saved leagues were not touched.
    expect(parts.storage.map.get(LEAGUES)).toBe(serializeLeagueDocument({ ...EMPTY_DOCUMENT, revision: 1, activeId: "lg-office01", leagues: [OFFICE] }));
  });

  it("an empty slot counts 0 only once the reader confirms it", async () => {
    const parts = stores([OFFICE], { ...EMPTY_WMM, entries: [{ ...opponentDocument(), confirmedEmpty: { mine: [], theirs: [] } }] });
    mount(parts);
    await openWmm();
    expect(screen.getByText(/Their TE: This starting slot is empty/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Leave the opponent's TE empty: it counts 0" }));
    await waitFor(() => {
      expect(simulateButton().disabled).toBe(false);
    });
  });
});

describe("simulating", () => {
  it("runs on request, shows win, tie and loss with the noise and the groups, and drops the result when inputs change", async () => {
    const parts = stores([OFFICE], { ...EMPTY_WMM, entries: [opponentDocument()] });
    mount(parts);
    await openWmm();
    fireEvent.click(screen.getByRole("button", { name: "Simulate" }));
    const headline = await screen.findByText(/your modelled lineup wins, of 8,192 simulated games/, {}, { timeout: 10_000 });
    expect(headline).toBeTruthy();
    expect(screen.getByText(/Simulation noise ±\d\.\d pts \(95%\)/)).toBeTruthy();
    expect(screen.getByText(/Tie /)).toBeTruthy();
    expect(screen.getByText(/not calibrated as team probabilities/)).toBeTruthy();
    // The slot groups paint a frame after the headline (ADR-110 §9).
    const groups = await screen.findByRole("table", { name: /Slot groups/ });
    expect(within(groups).getByRole("rowheader", { name: /FLEX/ })).toBeTruthy();
    expect(screen.getByRole("figure")).toBeTruthy();
    // An input change hides the old answer rather than presenting it as current.
    fireEvent.click(screen.getByRole("button", { name: "Stop leaving the opponent's TE empty" }));
    await waitFor(() => {
      expect(screen.queryByText(/your modelled lineup wins/)).toBeNull();
    });
    expect(simulateButton().disabled).toBe(true);
    // Restoring the same inputs shows the remembered result again, without a new run.
    fireEvent.click(screen.getByRole("button", { name: "Leave the opponent's TE empty: it counts 0" }));
    expect(await screen.findByText(/your modelled lineup wins/)).toBeTruthy();
  });

  it("YOLO lists a rising, highly added pickup with its evidence and leaves availability unverified", async () => {
    const parts = stores([OFFICE], { ...EMPTY_WMM, entries: [opponentDocument()], prefs: { "lg-office01": { yolo: true } } });
    mount(parts);
    await openWmm();
    const pickups = await screen.findByRole("list", { name: "Potential pickups" }, { timeout: 10_000 });
    const card = within(pickups).getByText("Jahmyr Cook").closest("li");
    expect(card).not.toBeNull();
    if (card === null) return;
    expect(within(card).getByText(/For RB 2, replacing Omarion Vance/)).toBeTruthy();
    expect(within(card).getByText(/684 \(bar 684\)/)).toBeTruthy();
    expect(within(card).getByText(/Availability unverified/)).toBeTruthy();
    expect(screen.getByText(/Potential pickups — availability unverified/)).toBeTruthy();
    // Marking him unavailable moves him out of the list, and it is saved for this week only.
    fireEvent.click(within(card).getByRole("button", { name: "Mark unavailable" }));
    await waitFor(() => {
      expect(screen.queryByRole("list", { name: "Potential pickups" })).toBeNull();
    });
    expect(parts.storage.map.get(MATCHUPS)).toContain('"unavailable"');
  });
});

describe("weeks and leagues", () => {
  it("offers last week's opponent for reuse, never last week's result", async () => {
    const parts = stores([OFFICE], { ...EMPTY_WMM, entries: [{ ...opponentDocument(8), week: 8 }] });
    mount(parts);
    await openWmm();
    expect(screen.getByText("Week 9 has no opponent yet.")).toBeTruthy();
    expect(screen.getByText(/last saved matchup was week 8 against Rival/)).toBeTruthy();
    expect(screen.queryByText(/your modelled lineup wins/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reuse that opponent's lineup for week 9" }));
    await waitFor(() => {
      expect(screen.queryByText("Week 9 has no opponent yet.")).toBeNull();
    });
    const saved = JSON.parse(parts.storage.map.get(MATCHUPS) ?? "{}") as { entries: { week: number; countZero: string[] }[] };
    expect(saved.entries.map((entry) => entry.week).sort()).toEqual([8, 9]);
    expect(saved.entries.find((entry) => entry.week === 9)?.countZero).toEqual([]);
  });

  it("a league switch shows no other league's numbers", async () => {
    const parts = stores([OFFICE, FAMILY], { ...EMPTY_WMM, entries: [opponentDocument()] });
    mount(parts);
    await openWmm();
    fireEvent.click(screen.getByRole("button", { name: "Simulate" }));
    await screen.findByText(/your modelled lineup wins/, {}, { timeout: 10_000 });
    await act(async () => {
      fireEvent.click(screen.getByRole("radio", { name: /Family/ }));
      await Promise.resolve();
    });
    await openWmm();
    expect(screen.queryByText(/your modelled lineup wins/)).toBeNull();
    expect(screen.queryByText("Rival")).toBeNull();
  });
});
