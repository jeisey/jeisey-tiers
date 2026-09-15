/**
 * The in-season player card's micro-charts (ADR-086).
 *
 * **What the owner reported, in one line: the numbers were right and unreadable.** The card
 * published `ROS uncertainty 82.1` — correct to the digit, validated by the artifact gate,
 * rendered by a passing test — and a reader had no way to know whether 82.1 was a wide
 * interval or a narrow one. Three pictures answer that, and each one is only honest under a
 * rule that a component test can check and a screenshot cannot:
 *
 * | picture | the rule it must not break |
 * |---|---|
 * | `RankShift` | two anchors, two model names, the artifact's own change — never one rank that moved (ADR-071) |
 * | `PaceRail` | one unit on both bars, and the ratio never called an expectation |
 * | `CohortStrip` | the population printed on every reading, from the published board rather than the filter |
 *
 * The fixture carries the states these exist for, which is the lesson this repository has now
 * learned four times (ADR-081, ADR-082, ADR-084, ADR-085): a breakout with no preseason rank
 * at all, a player scoring at twice the rate the model projects, a player the model expects to
 * improve, and a row whose usage shares the feed never published.
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { opportunityRecords, rosTierRecords } from "./fixtures/artifacts";
import { required } from "./required";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

/** The fixture's breakout: never on the preseason board, scoring far above the projection. */
const BREAKOUT = "Amon-Ra Bright";
/** A player both boards hold, whose two orderings disagree by three places. */
const ORDINARY = "Bijan Robinson";
/** The model expects more from him per appearance than he has produced. */
const IMPROVING = "Ja'Marr Swift";

function serve(behaviorAvailable = true): void {
  const payloads: Record<string, unknown> = {
    ...fixtureFiles(),
    ...inSeasonFixtureFiles(behaviorAvailable),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const name = input.split("/").pop() ?? "";
      const payload = payloads[name];
      if (payload === undefined) {
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) } as Response);
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) } as Response);
    }),
  );
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

async function openCard(player: string, query = "?view=ros&scoring=ppr&teams=12"): Promise<HTMLElement> {
  go(query);
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /Rest of season/ })).toBeDefined();
  });
  await userEvent.setup().click(
    required(screen.getAllByRole("button", { name: player })[0], `a row button for ${player}`),
  );
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: player })).toBeDefined();
  });
  return screen.getByRole("dialog");
}

/** The published row a card is claiming to describe. */
function rosRow(player: string) {
  const row = rosTierRecords().find(
    (record) =>
      record.display_name === player &&
      record.league_preset_id === "redraft-12" &&
      record.scoring_preset === "PPR",
  );
  return required(row, `a ${player} row in the fixture`);
}

function opportunityRow(player: string) {
  return opportunityRecords().find(
    (record) =>
      record.display_name === player &&
      record.league_preset_id === "redraft-12" &&
      record.scoring_preset === "PPR",
  );
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
// The rank move: two orderings, never one rank
// --------------------------------------------------------------------------------------

describe("the rank-move rail", () => {
  it("prints both ranks and the artifact's own change, each with its model named", async () => {
    const dialog = await openCard(ORDINARY);
    const row = rosRow(ORDINARY);
    const shift = required(
      dialog.querySelector<HTMLElement>(".shift"),
      "the rank-move rail",
    );
    const read = (role: string): string =>
      shift.querySelector(`.shift-end[data-role="${role}"] .shift-end-value`)?.textContent ?? "";
    expect(read("from")).toBe(String(row.preseason_fair_rank));
    expect(read("to")).toBe(String(row.ros_fair_rank));
    // The change is the artifact's field, not a subtraction the card performed.
    expect(read("change")).toBe(`+${String(row.fair_rank_change)}`);
    expect(within(shift).getByText("draft model")).toBeDefined();
    expect(within(shift).getByText("rest-of-season model")).toBeDefined();
    expect(within(shift).getByText("two models, two orderings")).toBeDefined();
  });

  it("draws two anchors of different kinds, so neither can read as one mark that moved", async () => {
    const dialog = await openCard(ORDINARY);
    expect(dialog.querySelectorAll('.shift-anchor[data-anchor="from"]')).toHaveLength(1);
    expect(dialog.querySelectorAll('.shift-anchor[data-anchor="to"]')).toHaveLength(1);
    expect(
      screen.getByText(/Two orderings of one board, not one rank that moved/),
    ).toBeDefined();
  });

  it("scales the axis to the published board, not to the player's own two ranks", async () => {
    const dialog = await openCard(ORDINARY);
    const ends = dialog.querySelectorAll(".shift-scale span");
    expect(ends[0]?.textContent).toBe("1");
    // 18 rows per block in the fixture. Against the two ranks alone the axis would end at 4,
    // and a three-place shuffle at the top of a board would be drawn as a full-width move.
    expect(ends[2]?.textContent).toBe("18");
  });

  it("refuses to draw a move for a player the preseason board never held", async () => {
    const dialog = await openCard(BREAKOUT);
    expect(rosRow(BREAKOUT).preseason_fair_rank).toBeNull();
    expect(dialog.querySelectorAll(".shift-track")).toHaveLength(0);
    expect(
      within(dialog).getByText(/not on the preseason board at all/i),
    ).toBeDefined();
    // Null and null, never a zero standing in for "we did not know".
    const shift = required(dialog.querySelector(".shift"), "the rank-move rail");
    expect(shift.querySelector('.shift-end[data-role="from"] .shift-end-value')?.textContent).toBe("—");
    expect(shift.querySelector('.shift-end[data-role="change"] .shift-end-value')?.textContent).toBe("—");
  });
});

// --------------------------------------------------------------------------------------
// Pace: one unit either side of the cutoff
// --------------------------------------------------------------------------------------

describe("the pace rail", () => {
  it("draws the observed rate against the model's, from the artifact's own totals", async () => {
    const dialog = await openCard(BREAKOUT);
    const row = rosRow(BREAKOUT);
    const pace = required(dialog.querySelector(".pace"), "the pace rail");
    const value = (kind: string): string =>
      pace.querySelector(`.pace-row[data-kind="${kind}"] .pace-value`)?.textContent ?? "";
    expect(value("scored")).toBe(
      required(row.points_per_game_to_date, "a published scoring rate").toFixed(1),
    );
    expect(value("projected")).toBe(
      (row.ros_expected_points / row.ros_expected_games).toFixed(1),
    );
  });

  it("says which way the model disagrees, and by how much", async () => {
    const dialog = await openCard(BREAKOUT);
    // The breakout has been scoring at roughly twice the rate the model projects for him.
    expect(within(dialog).getByText(/fewer points per appearance than he has scored/i)).toBeDefined();
  });

  it("says so the other way round too, where the model expects an improvement", async () => {
    const dialog = await openCard(IMPROVING);
    expect(within(dialog).getByText(/more points per appearance than he has scored/i)).toBeDefined();
  });

  it("never calls the ratio an expectation — it is two published totals divided", async () => {
    const dialog = await openCard(BREAKOUT);
    expect(
      within(dialog).getByText(/remaining points divided by its remaining games/i),
    ).toBeDefined();
    // "Expected points per game" would claim a per-appearance estimate the artifact does not
    // publish, and the ratio of two expectations is not the expectation of the ratio.
    expect(within(dialog).queryByText(/expected points per (game|appearance)/i)).toBeNull();
  });

  it("states how many appearances stand behind the observed rate", async () => {
    const dialog = await openCard(BREAKOUT);
    const row = rosRow(BREAKOUT);
    expect(row.games_played_to_date).toBe(4);
    expect(within(dialog).getByText(/against 4 appearances so far/i)).toBeDefined();
  });
});

// --------------------------------------------------------------------------------------
// The cohort strip: a rank is nothing without its population
// --------------------------------------------------------------------------------------

describe("the cohort strip", () => {
  it("gives the interval width the scale the owner's review said it lacked", async () => {
    const dialog = await openCard(ORDINARY);
    const strip = required(
      dialog.querySelectorAll<HTMLElement>(".cohort")[0],
      "the value cohort strip",
    );
    const uncertainty = within(strip).getByText("ROS uncertainty");
    const row = required(uncertainty.closest(".cohort-row"), "the interval-width row");
    expect(row.querySelector(".cohort-read b")?.textContent).toBe(
      rosRow(ORDINARY).ros_uncertainty.toFixed(1),
    );
    // The direction word is what makes a rank over a spread readable without a legend.
    expect(row.querySelector(".cohort-read span")?.textContent).toMatch(
      /^\d+(st|nd|rd|th) widest of \d+ RBs$/,
    );
  });

  it("prints a population on every reading it draws", async () => {
    const dialog = await openCard(ORDINARY);
    const readings = dialog.querySelectorAll(".cohort-read > span");
    expect(readings.length).toBeGreaterThan(0);
    for (const reading of readings) {
      expect(reading.textContent).toMatch(/ of \d+ RBs$/);
    }
  });

  it("names the position it is comparing against, not the board", async () => {
    const dialog = await openCard(ORDINARY);
    expect(within(dialog).getByText(/Value against the RBs on this board/i)).toBeDefined();
    expect(within(dialog).getByText(/Production against the RBs on this board/i)).toBeDefined();
  });

  it("compares against the published board rather than the reader's filter", async () => {
    // The position control selects what to show; it is not a question about what a player's
    // interval width should be compared with. Filtering to one position must not change a
    // single reading on his card.
    const all = await openCard(ORDINARY, "?view=ros&scoring=ppr&teams=12");
    const unfiltered = [...all.querySelectorAll(".cohort-read")].map((node) => node.textContent);
    cleanup();
    const filtered = await openCard(ORDINARY, "?view=ros&scoring=ppr&teams=12&position=rb");
    expect([...filtered.querySelectorAll(".cohort-read")].map((node) => node.textContent)).toEqual(
      unfiltered,
    );
  });

  it("draws no row at all for a share the feed did not publish", async () => {
    const silent = rosTierRecords().find((record) => {
      const row = opportunityRecords().find(
        (candidate) =>
          candidate.player_id === record.player_id &&
          candidate.league_preset_id === "redraft-12" &&
          candidate.scoring_preset === "PPR",
      );
      return (
        record.league_preset_id === "redraft-12" &&
        record.scoring_preset === "PPR" &&
        row?.snap_share_last3 == null
      );
    });
    const player = required(silent, "a fixture row whose usage shares the feed never published");
    const dialog = await openCard(player.display_name);
    expect(opportunityRow(player.display_name)?.snap_share_last3).toBeNull();
    // The tile stays and reads as an em dash; the cohort row is absent, because placing a
    // value nobody published among its peers would be placing a number that does not exist.
    const usage = required(
      dialog.querySelectorAll<HTMLElement>(".cohort")[1],
      "the production cohort strip",
    );
    expect(within(usage).queryByText("Snap share")).toBeNull();
    expect(dialog.querySelectorAll(".readout-label")).not.toHaveLength(0);
  });
});

// --------------------------------------------------------------------------------------
// The roster-moves strip, on the board's own axis
// --------------------------------------------------------------------------------------

describe("the roster-moves strip", () => {
  it("names the axis it drew the bars on", async () => {
    const dialog = await openCard(ORDINARY);
    expect(
      within(dialog).getByText(/85th percentile of its non-zero counts/i),
    ).toBeDefined();
  });

  it("says the feed published nothing rather than drawing a zero, when it did not", async () => {
    cleanup();
    serve(false);
    const dialog = await openCard(ORDINARY);
    expect(dialog.querySelectorAll(".opp-track-empty")).toHaveLength(1);
    expect(
      within(dialog).getByText(/published nothing for this build, so the strip is empty/i),
    ).toBeDefined();
  });
});
