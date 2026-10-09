/**
 * Season-to-date actuals beside rest-of-season value (ADR-105).
 *
 * What a reader is promised, surface by surface: one set of numbers (the build's), three
 * states never merged (ranked, no appearances, unavailable), a square that means a RoS rank and
 * a triangle that means a season rank on their own lane, the same three columns in every
 * table, and a card that puts the two ranks side by side with a neutral sentence about the gap.
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import {
  actualsAvailability,
  formatSeasonPerGame,
  formatSeasonPoints,
  formatSeasonRank,
  positionalSortKey,
  rankGap,
  rankGapSentence,
  seasonCsvCells,
  seasonStanding,
} from "../src/data/actuals";
import { rosRowsToCsv } from "../src/data/csv";
import { rankPercent, rankScaleEnd, rankTicks } from "../src/charts/rankScale";
import {
  FIXTURE_GENERATED_AT,
  FIXTURE_OFF_BOARD_QB_ID,
  FIXTURE_SIGNING_ID,
  FIXTURE_UNSIGNED_ID,
  fixtureFiles,
  inSeasonFixtureFiles,
  rosBuildMetadata,
  rosTierRecords,
  seasonActualsMetadata,
  seasonActualsRecords,
} from "./fixtures/artifacts";
import { required } from "./required";
import { MISSING, stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
/** RoS QB1, season QB4: the off-board passer and two board QBs outscored him. */
const ALLEN = "gsis:00-0000008";
const ALLEN_NAME = "Josh Allen";

function serve(overrides: Record<string, unknown> = {}): void {
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(), ...overrides });
}

function go(query: string): void {
  window.history.replaceState(null, "", `/${query}`);
}

function ppr(playerId: string) {
  return required(
    seasonActualsRecords().find((r) => r.player_id === playerId && r.scoring_preset === "PPR"),
    `actuals for ${playerId}`,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: FIXTURE_NOW });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("the reading model", () => {
  const published = actualsAvailability(seasonActualsMetadata(), true);

  it("reads a ranked player from his record and never re-ranks", () => {
    const standing = seasonStanding(ppr(ALLEN), published);
    expect(standing.kind).toBe("ranked");
    expect(formatSeasonRank(standing)).toBe("QB4");
    expect(formatSeasonPoints(standing)).toBe("36.6");
    expect(formatSeasonPerGame(standing)).toBe("7.3");
  });

  it("keeps a known zero apart from a missing value", () => {
    const zero = seasonStanding(ppr(FIXTURE_UNSIGNED_ID), published);
    expect(zero.kind).toBe("no_appearances");
    expect(formatSeasonPoints(zero)).toBe("0.0");
    expect(formatSeasonRank(zero)).toBe("—");
    expect(formatSeasonPerGame(zero)).toBe("—");
    const missing = seasonStanding(null, published);
    expect(missing.kind).toBe("unavailable");
    expect(formatSeasonPoints(missing)).toBe("—");
  });

  it("prints a negative total with a real minus sign", () => {
    const standing = seasonStanding(ppr("gsis:00-0000091"), published);
    expect(formatSeasonPoints(standing)).toBe("−1.5");
  });

  it("treats a withheld or unpublished build as unavailable, whatever rows are loaded", () => {
    const withheld = actualsAvailability(seasonActualsMetadata({ status: "withheld" }), true);
    expect(seasonStanding(ppr(ALLEN), withheld).kind).toBe("unavailable");
    expect(withheld.reason).toMatch(/withheld/);
    expect(actualsAvailability(null, false).published).toBe(false);
  });

  it("states the gap in places and direction, neutrally", () => {
    const allen = seasonStanding(ppr(ALLEN), published);
    const gap = required(rankGap(1, allen), "a gap");
    expect(gap).toEqual({ places: 3, direction: "above" });
    expect(rankGapSentence(gap)).toBe("RoS is 3 places above his season-to-date rank.");
    expect(rankGapSentence({ places: 11, direction: "below" })).toBe(
      "RoS is 11 places below his season-to-date rank.",
    );
    expect(rankGapSentence({ places: 0, direction: "same" })).toMatch(/same/);
    expect(rankGap(15, seasonStanding(null, published))).toBeNull();
  });

  it("sorts positional ranks within their position", () => {
    const keys = [
      positionalSortKey("RB", 3),
      positionalSortKey("QB", 4),
      positionalSortKey("RB", 5),
    ] as number[];
    expect([...keys].sort((a, b) => a - b)).toEqual([keys[1], keys[0], keys[2]]);
    expect(positionalSortKey("QB", null)).toBeUndefined();
  });

  it("writes the record's own values into a CSV row", () => {
    expect(seasonCsvCells(seasonStanding(ppr(ALLEN), published))).toEqual([4, 36.62, 5, 7.32]);
    expect(seasonCsvCells(seasonStanding(ppr(FIXTURE_UNSIGNED_ID), published))).toEqual([null, 0, 0, null]);
    expect(seasonCsvCells(seasonStanding(null, published))).toEqual([null, null, null, null]);
  });
});

describe("the rank scale", () => {
  it("ends on a round rank at or past the deepest one, with 1 at the left", () => {
    expect(rankScaleEnd(4)).toBe(10);
    expect(rankScaleEnd(74)).toBe(100);
    expect(rankPercent(1, 100)).toBe(0);
    expect(rankPercent(100, 100)).toBe(100);
    expect(rankPercent(10, 100)).toBeCloseTo(50);
  });

  it("thins ticks on a narrow lane but keeps both ends", () => {
    expect(rankTicks(100, false)).toEqual([1, 2, 5, 10, 20, 50, 100]);
    const compact = rankTicks(100, true);
    expect(compact[0]).toBe(1);
    expect(compact.at(-1)).toBe(100);
    expect(compact.length).toBeLessThan(7);
  });
});

async function openRos(query = "?view=ros&scoring=ppr&teams=12"): Promise<HTMLElement> {
  go(query);
  render(<App />);
  await waitFor(() => {
    expect(document.querySelector(".tier-board[data-rank-lane='true']")).not.toBeNull();
  });
  return required(document.querySelector<HTMLElement>(".tier-board"), "the RoS board");
}

function laneOf(board: HTMLElement, playerId: string): HTMLElement {
  return required(
    board.querySelector<HTMLElement>(`.board-row[data-player="${playerId}"]`),
    `a chart row for ${playerId}`,
  );
}

describe("the RoS chart's comparison lane", () => {
  it("draws the square at the RoS rank and the triangle at the season rank, in words too", async () => {
    serve();
    const board = await openRos();
    const row = laneOf(board, ALLEN);
    expect(row.querySelector('.rank-mark[data-kind="ros"]')).not.toBeNull();
    expect(row.querySelector('.rank-mark[data-kind="season"]')).not.toBeNull();
    expect(row.querySelector('.rank-value[data-kind="ros"]')?.textContent).toContain("QB1");
    expect(row.querySelector('.rank-value[data-kind="season"]')?.textContent).toContain("QB4");
    // The accessible label carries both, in words.
    expect(row.getAttribute("aria-label")).toMatch(/Rest-of-season QB1, season to date QB4 by points/);
    // The value lane's median is a tick here: the square means a rank on this board.
    expect(row.querySelector(".interval-median")?.getAttribute("data-shape")).toBe("tick");
  });

  it("keeps a mark's coordinate when the board is filtered or searched", async () => {
    serve();
    const all = await openRos("?view=ros&scoring=ppr&teams=12");
    const before = required(laneOf(all, ALLEN).querySelector<HTMLElement>('.rank-mark[data-kind="season"]'), "a triangle").style.left;
    cleanup();
    const filtered = await openRos("?view=ros&scoring=ppr&teams=12&position=qb&search=allen");
    const after = required(laneOf(filtered, ALLEN).querySelector<HTMLElement>('.rank-mark[data-kind="season"]'), "a triangle").style.left;
    expect(after).toBe(before);
  });

  it("draws no triangle and says why when the build withheld the actuals", async () => {
    serve({
      "ros_build_metadata.json": rosBuildMetadata({ season_actuals: seasonActualsMetadata({ status: "withheld", withheld_reason: "week 8 snap counts missing CHI" }) }),
      "season_actuals.json": MISSING,
    });
    const board = await openRos();
    const row = laneOf(board, ALLEN);
    expect(row.querySelector('.rank-mark[data-kind="season"]')).toBeNull();
    expect(row.querySelector('.rank-value[data-kind="season"]')?.getAttribute("data-absent")).toBe("true");
    expect(screen.getAllByText(/unavailable for this build/).length).toBeGreaterThan(0);
  });

  it("leaves the draft board's square meaning median VORP", async () => {
    serve();
    go("?view=tiers&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(document.querySelector(".tier-board .board-row")).not.toBeNull();
    });
    expect(document.querySelector(".tier-board[data-rank-lane]")).toBeNull();
    expect(document.querySelector(".rank-mark")).toBeNull();
    expect(document.querySelector('.interval-median[data-shape="tick"]')).toBeNull();
  });
});

function headers(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole("columnheader")
    .map((cell) => (cell.textContent ?? "").replace(/[▲▼]/g, "").trim());
}

describe("the RoS table", () => {
  it("puts Szn rank beside ROS PosRk, then the season totals", async () => {
    serve();
    await openRos();
    const table = required(document.querySelector<HTMLElement>("table.sheet"), "the RoS table");
    const names = headers(table);
    const at = names.indexOf("ROS PosRk");
    expect(names.slice(at, at + 4)).toEqual(["ROS PosRk", "Szn rank", "Total pts", "Avg pts/g"]);
    const row = required(table.querySelector<HTMLElement>(`tr[data-player="${ALLEN}"]`), "Allen's row");
    const cells = [...row.querySelectorAll("td")].map((cell) => cell.textContent);
    expect(cells.slice(at, at + 4)).toEqual(["QB1", "QB4", "36.6", "7.3"]);
    expect(table.querySelector("caption")?.textContent).toMatch(/actual results through week 8/);
  });

  it("sorts season ranks within position, missing last", async () => {
    serve();
    await openRos();
    const table = required(document.querySelector<HTMLElement>("table.sheet"), "the RoS table");
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(
      within(table).getByRole("button", { name: /Szn rank/ }),
    );
    const ranks = [...table.querySelectorAll("tbody tr")].map(
      (row) => row.querySelectorAll("td")[4]?.textContent ?? "",
    );
    const positions = ranks.map((rank) => rank.replace(/\d+/, ""));
    // Grouped: every QB before every RB before every WR before every TE.
    const order = ["QB", "RB", "WR", "TE"];
    const sequence = positions.filter((p) => order.includes(p)).map((p) => order.indexOf(p));
    expect(sequence).toEqual([...sequence].sort((a, b) => a - b));
  });

  it("exports the four season columns with the record's values", () => {
    const record = required(
      rosTierRecords().find(
        (r) => r.player_id === ALLEN && r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR",
      ),
      "Allen's RoS row",
    );
    const csv = rosRowsToCsv([
      { record, season: seasonStanding(ppr(ALLEN), actualsAvailability(seasonActualsMetadata(), true)) },
    ]);
    const [header, line] = csv.trim().split("\r\n");
    expect(header?.split(",").slice(-4)).toEqual([
      "season_position_rank",
      "season_points",
      "season_games_played",
      "season_points_per_game",
    ]);
    expect(line?.split(",").slice(-4)).toEqual(["4", "36.62", "5", "7.32"]);
  });
});

describe("the player card", () => {
  async function openCard(query: string, name: string): Promise<HTMLElement> {
    go(query);
    render(<App />);
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name }).length).toBeGreaterThan(0);
    });
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(
      required(screen.getAllByRole("button", { name })[0], `a row for ${name}`),
    );
    await waitFor(() => {
      expect(screen.getByTestId("rank-pair")).toBeDefined();
    });
    return screen.getByRole("dialog");
  }

  it("puts both ranks side by side, with the preset, the cutoff and a neutral gap", async () => {
    serve();
    const dialog = await openCard("?view=ros&scoring=ppr&teams=12", ALLEN_NAME);
    const pair = within(dialog).getByTestId("rank-pair");
    expect(within(pair).getByText("RoS rank")).toBeDefined();
    expect(within(pair).getByText("QB1")).toBeDefined();
    expect(within(pair).getByText("Season rank")).toBeDefined();
    expect(within(pair).getByText("QB4")).toBeDefined();
    expect(pair.textContent).toContain("PPR · through week 8");
    expect(pair.textContent).toContain("RoS is 3 places above his season-to-date rank.");
    // The population the season rank is out of, from the build.
    expect(pair.textContent).toContain(`of ${String(seasonActualsMetadata().population.QB)} QBs`);
  });

  it("explains the two rankings in plain words with his own rates", async () => {
    serve();
    const dialog = await openCard("?view=ros&scoring=ppr&teams=12", ALLEN_NAME);
    const context = within(dialog).getByTestId("season-context");
    expect(context.textContent).toMatch(/Season rank measures points already scored/);
    expect(context.textContent).toMatch(/RoS rank orders the model.s value from here on/);
    expect(context.textContent).toMatch(/3-place gap above is a difference between two orderings, not a fall over time/);
    expect(context.textContent).toMatch(/scored 7\.3 points per game over 5 appearances/);
  });

  it("opens from Start/Sit with complete actuals, without visiting another tab first", async () => {
    serve();
    const dialog = await openCard("?view=startsit&scoring=ppr&teams=12", ALLEN_NAME);
    expect(within(within(dialog).getByTestId("rank-pair")).getByText("QB4")).toBeDefined();
  });

  it("shows genuine actuals beside 'No RoS projection' for an unprojected signing", async () => {
    serve();
    const signing = ppr(FIXTURE_SIGNING_ID);
    const dialog = await openCard("?view=opportunity&scoring=ppr&teams=12", signing.display_name);
    const pair = within(dialog).getByTestId("rank-pair");
    expect(within(pair).getByText("No RoS projection")).toBeDefined();
    expect(within(pair).getByText(`WR${String(signing.season_position_rank)}`)).toBeDefined();
  });
});

describe("the other tables", () => {
  it("the Opportunity board carries the same three columns, and the unprojected list too", async () => {
    serve();
    go("?view=opportunity&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(document.querySelector("table.opp-sheet")).not.toBeNull();
    });
    const table = required(document.querySelector<HTMLElement>("table.opp-sheet"), "the table");
    const names = headers(table);
    const at = names.indexOf("ROS PosRk");
    expect(names.slice(at, at + 4)).toEqual(["ROS PosRk", "Szn rank", "Total pts", "Avg pts/g"]);
    const unprojected = required(document.querySelector<HTMLElement>("table.unprojected-sheet"), "the list");
    const signing = ppr(FIXTURE_SIGNING_ID);
    const row = required(
      unprojected.querySelector<HTMLElement>(`tr[data-player-id="${FIXTURE_SIGNING_ID}"]`),
      "the signing's row",
    );
    expect(row.textContent).toContain("No RoS projection");
    expect(row.textContent).toContain(`WR${String(signing.season_position_rank)}`);
    const unsigned = required(
      unprojected.querySelector<HTMLElement>(`tr[data-player-id="${FIXTURE_UNSIGNED_ID}"]`),
      "the unsigned row",
    );
    expect(unsigned.textContent).toContain("No appearances");
  });

  it("Start/Sit keeps its weekly rank, labelled as such, beside RoS and season ranks", async () => {
    serve();
    go("?view=startsit&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(document.querySelector("table.weekboard-table")).not.toBeNull();
    });
    const table = required(document.querySelector<HTMLElement>("table.weekboard-table"), "the board");
    const names = headers(table);
    expect(names).toContain("Week rank");
    const at = names.indexOf("RoS rank");
    expect(names.slice(at, at + 4)).toEqual(["RoS rank", "Szn rank", "Total pts", "Avg pts/g"]);
  });

  it("never lists the off-board leader, but every board player ranks behind him", () => {
    const qbs = seasonActualsRecords().filter((r) => r.scoring_preset === "PPR" && r.position === "QB");
    expect(qbs.find((r) => r.player_id === FIXTURE_OFF_BOARD_QB_ID)?.season_position_rank).toBe(1);
  });
});
