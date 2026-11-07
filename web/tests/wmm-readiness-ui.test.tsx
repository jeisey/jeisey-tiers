/**
 * Win My Matchup's readiness in the page, on a Friday (the 2026-11-06 report): Thursday's LAR @ BAL
 * has kicked off and the rest of week 9 has not. With a healthy build, "With final scores"
 * simulates the completed starters' finals and everyone else's projection; with the outage build
 * (every upcoming game without lines) Simulate stays off, no decision is demanded for the
 * starters the build could not project, and the outage is explained once with the build's
 * freshness and an honest way to read a newer build. Also: a run whose inputs change before it
 * answers is dropped, and Start/Sit labels lines the build retained.
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
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles, type WeeklyFixtureMode } from "./fixtures/artifacts";
import { stubSite } from "./site";

/** Friday 2026-11-06, 10:00 AM ET. */
const FRIDAY = new Date("2026-11-06T15:00:00Z");
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

// Thursday (LAR @ BAL): Derrick Hampton (14) and Puka Nightingale (12) mine, Zay Meadows (15,
// doubtful) theirs. Byes: Deebo Gray (06), Jalen Marsh (18). Sunday: Joe Burrow (09), Jahmyr Cook
// (11) and Bijan Robinson (01) mine, Amon-Ra Bright (02, questionable) theirs. The fixture has no
// healthy lined TE, so both TE slots are confirmed empty; their reserve-list and doubtful
// starters are confirmed as 0 — decisions already made, so only the data can block.
const LEAGUE: SavedLeague = {
  id: "lg-friday01",
  name: "Friday",
  season: 2026,
  scoring: "ppr",
  teams: 12,
  slots: DEFAULT_SLOTS,
  roster: (() => {
    const roster = emptyRoster(DEFAULT_SLOTS) as unknown as Record<string, (string | null)[]>;
    const set: Readonly<Record<string, readonly string[]>> = {
      QB: [g("09")],
      RB: [g("14"), g("11")],
      WR: [g("12"), g("06")],
      FLEX: [g("01")],
      BN: [g("18")],
    };
    for (const [group, ids] of Object.entries(set)) ids.forEach((id, index) => { (roster[group] ?? [])[index] = id; });
    return roster as unknown as SavedLeague["roster"];
  })(),
  prefs: DEFAULT_PREFS,
  rev: 1,
  updatedAt: "2026-11-05T00:00:00Z",
};

function matchup(finals: Readonly<Record<string, number>>) {
  return {
    ...EMPTY_WMM,
    entries: [
      {
        ...newEntry("lg-friday01", 2026, 9),
        opponent: {
          name: "Rival",
          starters: { ...emptyStarters(), QB: [g("08")], RB: [g("13"), g("16")], WR: [g("15"), g("02")], TE: [null], FLEX: [g("03")] },
          others: [],
        },
        confirmedEmpty: { mine: ["TE:0"], theirs: ["TE:0"] },
        countZero: [g("08"), g("13"), g("16"), g("03")],
        finals,
        rev: 1,
        updatedAt: "2026-11-06T00:00:00Z",
      },
    ],
  };
}

function mount(mode: WeeklyFixtureMode, finals: Readonly<Record<string, number>>): MemoryStorage {
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true, { weekly: mode }) });
  const storage = new MemoryStorage();
  storage.setItem(LEAGUES, serializeLeagueDocument({ ...EMPTY_DOCUMENT, revision: 1, activeId: LEAGUE.id, leagues: [LEAGUE] }));
  storage.setItem(MATCHUPS, serializeWmmDocument(matchup(finals)));
  window.history.replaceState(null, "", "/?view=myleagues&panel=wmm");
  render(
    <LeagueStoreContext.Provider value={new LeagueStore({ storage, key: LEAGUES })}>
      <WmmStoreContext.Provider value={new WmmStore({ storage, key: MATCHUPS })}>
        <App now={FRIDAY} />
      </WmmStoreContext.Provider>
    </LeagueStoreContext.Provider>,
  );
  return storage;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FRIDAY });
  forgetActiveLeague();
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

async function openWmm(): Promise<void> {
  await screen.findByRole("heading", { name: "Win My Matchup — week 9" }, { timeout: 10_000 });
}

function ready(): HTMLElement {
  const element = document.querySelector(".wmm-ready");
  if (!(element instanceof HTMLElement)) throw new Error("no readiness line");
  return element;
}

describe("Friday, with a healthy build", () => {
  it("simulates finals for the completed Thursday starters and projections for everyone else", async () => {
    mount("friday", { [g("14")]: 21.3, [g("12")]: 0, [g("15")]: -1.2 });
    await openWmm();
    fireEvent.click(screen.getByRole("radio", { name: /With final scores/ }));
    await waitFor(() => {
      expect(simulateButton().disabled).toBe(false);
    });
    expect(ready().textContent).toBe('Ready: 7 starters a side. 7 count as a known 0. 1 "if active".');
    const slot = (name: string): HTMLElement => {
      const row = screen.getAllByText(name).map((node) => node.closest("li")).find((li) => li?.classList.contains("wmm-slot"));
      if (row == null) throw new Error(`no row for ${name}`);
      return row;
    };
    expect(slot("Derrick Hampton").textContent).toContain("Final 21.30");
    expect(slot("Puka Nightingale").textContent).toContain("Final 0.00");
    expect(slot("Zay Meadows").textContent).toContain("Final -1.20");
    for (const name of ["Joe Burrow", "Jahmyr Cook", "Bijan Robinson", "Amon-Ra Bright"]) expect(slot(name).getAttribute("data-kind")).toBe("modelled");
    fireEvent.click(simulateButton());
    expect(await screen.findByText(/your modelled lineup wins, of 8,192 simulated games/, {}, { timeout: 10_000 })).toBeTruthy();
    expect(document.querySelector(".wmm-headline")?.textContent).toContain("With 3 final scores");
  });

  it("drops a run whose inputs change before it answers, and caches nothing for it", async () => {
    mount("friday", { [g("14")]: 21.3, [g("15")]: -1.2 });
    await openWmm();
    fireEvent.click(screen.getByRole("radio", { name: /With final scores/ }));
    await waitFor(() => {
      expect(simulateButton().disabled).toBe(false);
    });
    // Press Simulate, then change the scenario before the run can answer.
    act(() => {
      fireEvent.click(simulateButton());
      fireEvent.click(screen.getByRole("radio", { name: /Pregame projection/ }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.queryByText(/your modelled lineup wins/)).toBeNull();
    // Back to the scenario that was pressed: its run was cancelled, so there is no answer for it.
    fireEvent.click(screen.getByRole("radio", { name: /With final scores/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.queryByText(/your modelled lineup wins/)).toBeNull();
    expect(simulateButton().disabled).toBe(false);
    fireEvent.click(simulateButton());
    expect(await screen.findByText(/your modelled lineup wins/, {}, { timeout: 10_000 })).toBeTruthy();
  });
});

describe("Friday, with the outage build (every upcoming game without lines)", () => {
  it("keeps Simulate off, demands no decision for the data gaps, and explains the outage once with freshness", async () => {
    const storage = mount("outage", { [g("14")]: 21.3, [g("15")]: -1.2 });
    await openWmm();
    fireEvent.click(screen.getByRole("radio", { name: /With final scores/ }));
    await waitFor(() => {
      expect(ready().getAttribute("data-ready")).toBe("false");
    });
    expect(simulateButton().disabled).toBe(true);
    const text = ready().textContent;
    // Not "Simulate needs 4 decisions": nothing here is the reader's to decide.
    expect(text).not.toMatch(/decision/);
    expect(text).toContain("4 starters have no projection in this build: nothing here is yours to decide, and Simulate stays off until a build publishes them.");
    expect(text).toContain("No sportsbook line in this build (4): Your QB (Joe Burrow); Your RB 2 (Jahmyr Cook); Your FLEX (Bijan Robinson); Their WR 2 (Amon-Ra Bright).");
    // The explanation, the freshness and the provenance are said once.
    expect(text.split("A missing line is never filled in.")).toHaveLength(2);
    expect(text).toContain("This build: Aug 21 · 10:38 AM ET");
    expect(text).toContain("through week 8, projecting week 9.");
    expect(text).toContain("Its lines: 1 of 5 games from the schedule it read Nov 3 · 7:00 AM ET, 0 retained from an earlier pregame reading (at most 48 hours old), 4 with none.");
    expect(within(ready()).getByRole("button", { name: "Reload" })).toBeTruthy();
    expect(text).toContain("a newer build has them only if its sources do");
    // The old catch-all sentence is gone from every row.
    expect(document.body.textContent).not.toContain("No line is posted for his game yet");
    // Rows say what is missing, not that a decision is needed; Thursday's starters stand.
    const rows = [...document.querySelectorAll<HTMLElement>(".wmm-slot")];
    expect(rows.filter((row) => row.textContent.includes("No projection"))).toHaveLength(4);
    expect(rows.filter((row) => row.textContent.includes("Needs a decision"))).toHaveLength(0);
    expect(rows.find((row) => row.textContent.includes("Derrick Hampton"))?.textContent).toContain("Final 21.30");
    expect(rows.find((row) => row.textContent.includes("Zay Meadows"))?.textContent).toContain("Final -1.20");
    expect(rows.find((row) => row.textContent.includes("Puka Nightingale"))?.textContent).toContain("Game kicked off, no final entered: simulated from his pregame projection");
    // Nothing was written by reading it.
    expect(storage.map.get(MATCHUPS)).toBe(serializeWmmDocument(matchup({ [g("14")]: 21.3, [g("15")]: -1.2 })));
  });

  it("an older build with no line provenance says so instead of guessing", async () => {
    const files = { ...fixtureFiles(), ...inSeasonFixtureFiles(true, { weekly: "outage" }) };
    const ros = files["ros_build_metadata.json"] as { weekly: Record<string, unknown> };
    const older = Object.fromEntries(Object.entries(ros.weekly).filter(([key]) => key !== "lines" && key !== "unmodelled"));
    stubSite({ ...files, "ros_build_metadata.json": { ...ros, weekly: older } });
    const storage = new MemoryStorage();
    storage.setItem(LEAGUES, serializeLeagueDocument({ ...EMPTY_DOCUMENT, revision: 1, activeId: LEAGUE.id, leagues: [LEAGUE] }));
    storage.setItem(MATCHUPS, serializeWmmDocument(matchup({ [g("15")]: -1.2 })));
    window.history.replaceState(null, "", "/?view=myleagues&panel=wmm");
    render(
      <LeagueStoreContext.Provider value={new LeagueStore({ storage, key: LEAGUES })}>
        <WmmStoreContext.Provider value={new WmmStore({ storage, key: MATCHUPS })}>
          <App now={FRIDAY} />
        </WmmStoreContext.Provider>
      </LeagueStoreContext.Provider>,
    );
    await openWmm();
    expect(ready().textContent).toContain("It published no record of where its lines came from.");
    expect(simulateButton().disabled).toBe(true);
  });

  it("the Lineup tab groups the outage once and does not claim every game kicked off", async () => {
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true, { weekly: "outage" }) });
    const storage = new MemoryStorage();
    storage.setItem(LEAGUES, serializeLeagueDocument({ ...EMPTY_DOCUMENT, revision: 1, activeId: LEAGUE.id, leagues: [LEAGUE] }));
    window.history.replaceState(null, "", "/?view=myleagues");
    render(
      <LeagueStoreContext.Provider value={new LeagueStore({ storage, key: LEAGUES })}>
        <App now={FRIDAY} />
      </LeagueStoreContext.Provider>,
    );
    const left = await screen.findByRole("list", { name: "Players left in place" }, { timeout: 10_000 });
    const items = within(left).getAllByRole("listitem");
    const outage = items.filter((item) => item.textContent.startsWith("No sportsbook line in this build:"));
    expect(outage).toHaveLength(1);
    expect(outage[0]?.textContent).toContain("QB (Joe Burrow); RB 2 (Jahmyr Cook); FLEX (Bijan Robinson), left where you put them.");
    expect(screen.queryByText(/had kicked off when this build ran/)).toBeNull();
  });
});

describe("Start/Sit", () => {
  it("labels retained lines where the projection is shown", async () => {
    vi.setSystemTime(new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000));
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles() });
    window.history.replaceState(null, "", "/?view=startsit&scoring=ppr&teams=12&duel=00-0000016.00-0000011");
    render(<App />);
    const card = await screen.findByRole("article", { name: "Slot A: Omarion Vance" }, { timeout: 10_000 });
    expect(card.textContent).toContain("Lines as of Nov 2 · 5:53 PM ET (retained; the schedule had none at this build)");
    const other = screen.getByRole("article", { name: "Slot B: Jahmyr Cook" });
    expect(other.textContent).not.toContain("retained");
  });
});
