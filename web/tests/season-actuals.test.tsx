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
  describeRosVsSeason,
  formatRosVsSeason,
  formatSeasonPerGame,
  formatSeasonPoints,
  formatSeasonRank,
  positionalSortKey,
  rankGap,
  rankGapSentence,
  rosVsSeasonPlaces,
  seasonCsvCells,
  seasonStanding,
} from "../src/data/actuals";
import { rosRowsToCsv } from "../src/data/csv";
import { sortWeekBoard } from "../src/data/duel";
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

  it("signs the tables' gap the way the card words it, and has none without both ranks", () => {
    const allen = seasonStanding(ppr(ALLEN), published);
    // RoS QB1, season QB4: RoS is 3 places above, so +3.
    expect(rosVsSeasonPlaces(1, allen)).toBe(3);
    expect(formatRosVsSeason(rosVsSeasonPlaces(1, allen))).toBe("+3");
    expect(describeRosVsSeason(3)).toBe("RoS rank is 3 places above season rank");
    // RoS QB15, season QB5 (the motivating case): 10 places below, with a real minus sign.
    expect(rosVsSeasonPlaces(15, { kind: "ranked", position: "QB", rank: 5, points: 85.32, games: 4, perGame: 21.33 })).toBe(-10);
    expect(formatRosVsSeason(-10)).toBe("−10");
    expect(describeRosVsSeason(-1)).toBe("RoS rank is 1 place below season rank");
    expect(formatRosVsSeason(0)).toBe("0");
    // Missing either rank is no gap, never a zero.
    expect(rosVsSeasonPlaces(null, allen)).toBeNull();
    expect(rosVsSeasonPlaces(4, seasonStanding(ppr(FIXTURE_UNSIGNED_ID), published))).toBeNull();
    expect(rosVsSeasonPlaces(4, seasonStanding(null, published))).toBeNull();
    expect(formatRosVsSeason(null)).toBe("—");
  });

  it("sorts a board column with blanks last either way and ties in the arriving order", () => {
    const rows = [
      { id: "a", v: 2 },
      { id: "b", v: null },
      { id: "c", v: 5 },
      { id: "d", v: 2 },
      { id: "e", v: Number.NEGATIVE_INFINITY },
      { id: "f", v: -3 },
    ];
    const ids = (desc: boolean) => sortWeekBoard(rows, (row) => row.v, desc).map((row) => row.id);
    expect(ids(true)).toEqual(["c", "a", "d", "f", "b", "e"]);
    expect(ids(false)).toEqual(["f", "a", "d", "c", "b", "e"]);
    const names = sortWeekBoard([{ n: "Zay" }, { n: "amon" }, { n: "Bijan" }], (row) => row.n, false);
    expect(names.map((row) => row.n)).toEqual(["amon", "Bijan", "Zay"]);
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
    .map((cell) => (cell.textContent ?? "").replace(/[▲▼]/g, "").replace(/\s+/g, " ").trim());
}

/** A cell as it is seen: the signed gap's hidden words left out. */
function seen(cell: Element): string {
  const signed = cell.querySelector(".ros-vs-season > [aria-hidden='true']");
  return signed === null ? (cell.textContent ?? "") : (signed.textContent ?? "");
}

describe("the RoS table", () => {
  it("puts Szn rank beside ROS PosRk, the signed gap between them, then the season totals", async () => {
    serve();
    await openRos();
    const table = required(document.querySelector<HTMLElement>("table.sheet"), "the RoS table");
    const names = headers(table);
    const at = names.indexOf("ROS PosRk");
    expect(names.slice(at, at + 5)).toEqual(["ROS PosRk", "Szn rank", "RoS vs Szn", "Total pts", "Avg pts/g"]);
    const row = required(table.querySelector<HTMLElement>(`tr[data-player="${ALLEN}"]`), "Allen's row");
    const cells = [...row.querySelectorAll("td")].map(seen);
    expect(cells.slice(at, at + 5)).toEqual(["QB1", "QB4", "+3", "36.6", "7.3"]);
    // The sign is never the only carrier: the words are in the cell for a screen reader.
    expect(row.querySelectorAll("td")[at + 2]?.textContent).toContain("RoS rank is 3 places above season rank");
    expect(table.querySelector("caption")?.textContent).toMatch(/actual results through week 8/);
    expect(table.querySelector("caption")?.textContent).toMatch(/RoS vs Szn is Szn rank minus RoS rank/);
  });

  it("sorts the signed gap widest-first, blanks last, and reverses on a second click", async () => {
    serve();
    await openRos();
    const table = required(document.querySelector<HTMLElement>("table.sheet"), "the RoS table");
    const column = headers(table).indexOf("RoS vs Szn");
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const gaps = (): number[] =>
      [...table.querySelectorAll("tbody tr")]
        .map((row) => seen(required(row.querySelectorAll("td")[column], "a gap cell")))
        .map((text) => (text === "—" ? Number.NaN : Number(text.replace("−", "-"))));
    await user.click(within(table).getByRole("button", { name: /RoS vs Szn/ }));
    const down = gaps();
    const known = down.filter((value) => !Number.isNaN(value));
    expect(known[0]).toBe(Math.max(...known));
    expect(known).toEqual([...known].sort((a, b) => b - a));
    expect(down.slice(0, known.length).every((value) => !Number.isNaN(value))).toBe(true);
    await user.click(within(table).getByRole("button", { name: /RoS vs Szn/ }));
    const up = gaps().filter((value) => !Number.isNaN(value));
    expect(up).toEqual([...up].sort((a, b) => a - b));
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

  it("exports the four season columns with the record's values, then the signed gap", () => {
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
    expect(header?.split(",").slice(-5)).toEqual([
      "season_position_rank",
      "season_points",
      "season_games_played",
      "season_points_per_game",
      "ros_vs_season_places",
    ]);
    expect(line?.split(",").slice(-5)).toEqual(["4", "36.62", "5", "7.32", "3"]);
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

  it("puts both ranks side by side as identity tags, with the preset, the cutoff and a neutral gap", async () => {
    serve();
    const dialog = await openCard("?view=ros&scoring=ppr&teams=12", ALLEN_NAME);
    const pair = within(dialog).getByTestId("rank-pair");
    // Two tags in the identity row, styled as its other tags, each with its words for a
    // screen reader and its chart glyph.
    expect(pair.closest(".detail-subtitle")).not.toBeNull();
    const chips = [...pair.querySelectorAll(".rank-chip")];
    expect(chips.map((chip) => chip.getAttribute("data-kind"))).toEqual(["ros", "season"]);
    expect(chips.every((chip) => chip.classList.contains("detail-posrank"))).toBe(true);
    expect(within(pair).getByText("RoS rank")).toBeDefined();
    expect(within(pair).getByText("QB1")).toBeDefined();
    expect(within(pair).getByText("Season rank")).toBeDefined();
    expect(within(pair).getByText("QB4")).toBeDefined();
    // The bare RoS tag is gone: the labelled one says the same number once.
    const subtitle = required(pair.closest<HTMLElement>(".detail-subtitle"), "the identity row");
    expect([...subtitle.querySelectorAll(":scope > .detail-posrank")].map((tag) => tag.textContent)).not.toContain("QB1");
    const meta = within(dialog).getByTestId("rank-pair-meta");
    expect(meta.textContent).toContain("PPR · through week 8");
    expect(meta.textContent).toContain("RoS is 3 places above his season-to-date rank.");
    // The population the season rank is out of, from the build, on the tag and in the section.
    const population = `of ${String(seasonActualsMetadata().population.QB)} QBs`;
    expect(chips[1]?.getAttribute("title")).toContain(population);
  });

  it("explains the two rankings in plain words with his own rates", async () => {
    serve();
    const dialog = await openCard("?view=ros&scoring=ppr&teams=12", ALLEN_NAME);
    const context = within(dialog).getByTestId("season-context");
    expect(context.textContent).toMatch(/Season rank measures points already scored/);
    expect(context.textContent).toContain(
      `among the ${String(seasonActualsMetadata().population.QB)} QBs who have appeared`,
    );
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
    // "RoS rank: Not projected" to a screen reader; the tag's title says it in full.
    expect(within(pair).getByText("Not projected")).toBeDefined();
    expect(pair.querySelector(".rank-chip[data-kind='ros']")?.getAttribute("title")).toBe("No RoS projection");
    expect(within(pair).getByText(`WR${String(signing.season_position_rank)}`)).toBeDefined();
  });
});

describe("the other tables", () => {
  it("the Opportunity board carries the same columns, and the unprojected list its three", async () => {
    serve();
    go("?view=opportunity&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(document.querySelector("table.opp-sheet")).not.toBeNull();
    });
    const table = required(document.querySelector<HTMLElement>("table.opp-sheet"), "the table");
    const names = headers(table);
    const at = names.indexOf("ROS PosRk");
    expect(names.slice(at, at + 5)).toEqual(["ROS PosRk", "Szn rank", "RoS vs Szn", "Total pts", "Avg pts/g"]);
    const allen = required(table.querySelector<HTMLElement>(`tr[data-player-id="${ALLEN}"], tr[data-player="${ALLEN}"]`), "Allen's row");
    expect(seen(required(allen.querySelectorAll("td")[at + 2], "his gap"))).toBe("+3");
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
    expect(names.slice(at, at + 5)).toEqual(["RoS rank", "Szn rank", "RoS vs Szn", "Total pts", "Avg pts/g"]);
  });

  it("Start/Sit sorts by any column a reader selects, before paging, and an Order by restores it", async () => {
    serve();
    go("?view=startsit&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(document.querySelector("table.weekboard-table tbody tr")).not.toBeNull();
    });
    const table = required(document.querySelector<HTMLElement>("table.weekboard-table"), "the board");
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const names = headers(table);
    // Every heading but the compare column's is a sort button.
    const sortable = within(table).getAllByRole("columnheader").filter((cell) => cell.querySelector("button") !== null);
    expect(sortable).toHaveLength(names.length - 1);
    const column = (label: string): string[] =>
      [...table.querySelectorAll("tbody tr")].map((row) =>
        seen(required(row.querySelectorAll("td")[names.indexOf(label)], `a ${label} cell`)),
      );
    const players = (): string[] =>
      [...table.querySelectorAll("tbody tr .player-name")].map((name) => name.textContent ?? "");
    const before = players();

    await user.click(within(table).getByRole("button", { name: /RoS vs\s+Szn/ }));
    const header = required(within(table).getByRole("button", { name: /RoS vs\s+Szn/ }).closest("th"), "its heading");
    expect(header.getAttribute("aria-sort")).toBe("descending");
    const gaps = column("RoS vs Szn").filter((text) => text !== "—").map((text) => Number(text.replace("−", "-")));
    expect(gaps).toEqual([...gaps].sort((a, b) => b - a));
    expect(players()[0]).toBe("Ja'Marr Swift");
    const sortedBy = required(document.querySelector(".weekboard-sorted"), "the sorted-by line");
    expect(sortedBy.getAttribute("role")).toBe("status");
    expect(sortedBy.textContent).toMatch(/Sorted by RoS vs Szn, descending/);

    // A rank reads best-first on the first click, grouped by position.
    await user.click(within(table).getByRole("button", { name: /^Szn rank/ }));
    const seasonRanks = column("Szn rank").filter((text) => text !== "—");
    const order = ["QB", "RB", "WR", "TE"];
    const keys = seasonRanks.map((rank) => order.indexOf(rank.replace(/\d+/, "")) * 1000 + Number(rank.replace(/\D+/, "")));
    expect(keys).toEqual([...keys].sort((a, b) => a - b));

    // A name sorts A to Z.
    await user.click(within(table).getByRole("button", { name: /^Player/ }));
    const sortedNames = players();
    expect(sortedNames).toEqual([...sortedNames].sort((a, b) => a.localeCompare(b)));

    // An Order by choice is the board's own order again, and its column carries the mark.
    await user.click(screen.getByRole("radio", { name: /Chance of a startable week/ }));
    expect(players()).toEqual(before);
    expect(sortedBy.textContent).toBe("");
    const startable = required(within(table).getByRole("button", { name: /^Startable/ }).closest("th"), "Startable");
    expect(startable.getAttribute("aria-sort")).toBe("descending");
    // A click on the marked column reverses it rather than re-applying the same order.
    await user.click(within(table).getByRole("button", { name: /^Startable/ }));
    expect(startable.getAttribute("aria-sort")).toBe("ascending");
  });

  it("never lists the off-board leader, but every board player ranks behind him", () => {
    const qbs = seasonActualsRecords().filter((r) => r.scoring_preset === "PPR" && r.position === "QB");
    expect(qbs.find((r) => r.player_id === FIXTURE_OFF_BOARD_QB_ID)?.season_position_rank).toBe(1);
  });
});
