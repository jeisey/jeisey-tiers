/**
 * The in-season signal layer on the card and on Pick of the Week (ADR-091).
 *
 * The rules a screenshot cannot check and a component test can:
 *
 * | rule | why it is load-bearing |
 * |---|---|
 * | position decides which role readings lead | a quarterback's snap and target share are constants, and the card used to rank them |
 * | every printed value and change is the artifact's own | a change subtracted in the browser can disagree with the one the build published |
 * | an absence is a sentence, never a zero | a missing snap row, a missing record and a missing artifact are three different facts |
 * | the sportsbook numbers travel with their statement | a line printed without "read by no model" is a line that reads like a projection |
 * | Pick of the Week's selection does not move | the evidence explains a pick; it never chooses one |
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import type { PlayerUsageRecord } from "../src/data/contracts";
import { buildPotwBoard } from "../src/data/potw";
import { InSeasonBundle } from "../src/data/ros";
import {
  ROLE_METRICS_BY_POSITION,
  formatChange,
  formatMetric,
  impliedSplit,
  matchupReading,
  roleReading,
  ROLE_METRIC_SPECS,
} from "../src/data/signals";
import {
  FIXTURE_GENERATED_AT,
  FIXTURE_NO_USAGE_PLAYER_ID,
  FIXTURE_SIGNALS,
  fixtureFiles,
  inSeasonFixtureFiles,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  teamMatchupRecords,
  usageRecords,
} from "./fixtures/artifacts";
import { required } from "./required";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

const QB = "Josh Allen";
const RISING_RB = "Jahmyr Cook";
const DECLINING_WR = "Deebo Gray";
const NO_SNAP_TE = "Trey McBride";

function usageFor(name: string): PlayerUsageRecord {
  return required(
    usageRecords().find((record) => record.display_name === name),
    `a usage record for ${name}`,
  );
}

function serve(options: { readonly signals?: "present" | "absent" } = {}): void {
  const payloads: Record<string, unknown> = {
    ...fixtureFiles(),
    ...inSeasonFixtureFiles(true, options),
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

async function openCard(player: string): Promise<HTMLElement> {
  go("?view=ros&scoring=ppr&teams=12");
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

function bundle(withSignals = true): InSeasonBundle {
  return new InSeasonBundle({
    metadata: rosBuildMetadata(),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(),
    opportunityDegradation: null,
    usage: withSignals ? usageRecords() : null,
    matchups: withSignals ? teamMatchupRecords() : null,
  });
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

// ------------------------------------------------------------------------- the data layer

describe("which readings a position leads with", () => {
  it("never leads a quarterback with a snap or target share", () => {
    expect(ROLE_METRICS_BY_POSITION.QB).toEqual(["pass_attempts", "carries"]);
    expect(ROLE_METRICS_BY_POSITION.RB).toContain("carry_share");
    expect(ROLE_METRICS_BY_POSITION.WR).toContain("air_yards_share");
    expect(ROLE_METRICS_BY_POSITION.TE).not.toContain("carry_share");
  });

  it("copies the published change and draws a bar per week", () => {
    const record = usageFor(RISING_RB);
    const reading = roleReading(record, "snap_share");
    expect(reading.change).toEqual(record.role_changes.snap_share);
    expect(reading.bars).toHaveLength(record.weeks.length);
    expect(reading.direction).toBe("up");
    expect(reading.axisMax).toBe(1);
  });

  it("never draws a direction the printed change does not have", () => {
    for (const record of usageRecords()) {
      for (const metric of ROLE_METRICS_BY_POSITION[record.position]) {
        const reading = roleReading(record, metric);
        const text = formatChange(reading.spec, reading.change?.change);
        if (text === "no change") expect(reading.direction).toBe("flat");
        if (text.startsWith("+")) expect(reading.direction).toBe("up");
        if (text.startsWith("\u2212")) expect(reading.direction).toBe("down");
      }
    }
  });

  it("states a share's change in percentage points and a count's in its own unit", () => {
    expect(formatChange(ROLE_METRIC_SPECS.snap_share, 0.184)).toBe("+18 pts");
    expect(formatChange(ROLE_METRIC_SPECS.snap_share, -0.25)).toBe("−25 pts");
    expect(formatChange(ROLE_METRIC_SPECS.snap_share, 0.004)).toBe("no change");
    expect(formatChange(ROLE_METRIC_SPECS.pass_attempts, 3)).toBe("+3");
    expect(formatMetric(ROLE_METRIC_SPECS.target_share, 0.2)).toBe("20%");
  });

  it("reads the spread from the team's own side and never turns an unposted line into a pick'em", () => {
    const records = teamMatchupRecords();
    const det = required(records.find((r) => r.team === "DET"), "DET");
    const atl = required(records.find((r) => r.team === "ATL"), "ATL");
    expect(matchupReading(det).spreadLabel).toBe("Favoured by 3.5");
    expect(matchupReading(atl).spreadLabel).toBe("Underdog by 3.5");
    const even = required(records.find((r) => r.team === "BAL"), "BAL");
    expect(matchupReading(even).spreadLabel).toBe("Pick'em");
    const unposted = required(records.find((r) => r.team === "ARI"), "ARI");
    expect(matchupReading(unposted).spreadLabel).toBeNull();
    expect(matchupReading(unposted).linesPosted).toBe(false);
    expect(impliedSplit(unposted)).toBeNull();
  });
});

// ------------------------------------------------------------------------------ the card

describe("the in-season card's role block", () => {
  it("draws a quarterback's attempts and no snap or target tiles", async () => {
    const dialog = await openCard(QB);
    const rails = required(dialog.querySelector<HTMLElement>(".usage-rails"), "the role rails");
    const metrics = [...rails.querySelectorAll<HTMLElement>(".usage-rail")].map(
      (rail) => rail.dataset.metric,
    );
    expect(metrics).toEqual(["pass_attempts", "carries", "fantasy_points"]);
    expect(within(dialog).queryByText("Snap share")).toBeNull();
    // Once as the record's tile and once as its cohort reading (ADR-086: the tile stays).
    expect(within(dialog).getAllByText("EPA per dropback").length).toBeGreaterThan(0);
  });

  it("prints the artifact's own latest value, change and window for a rising back", async () => {
    const dialog = await openCard(RISING_RB);
    const record = usageFor(RISING_RB);
    const change = required(record.role_changes.carry_share, "a carry-share change");
    const rail = required(
      dialog.querySelector<HTMLElement>('.usage-rail[data-metric="carry_share"]'),
      "the carry-share rail",
    );
    expect(rail.querySelector(".usage-rail-value")?.textContent).toBe(
      formatMetric(ROLE_METRIC_SPECS.carry_share, change.latest),
    );
    expect(rail.querySelector(".usage-rail-change")?.textContent).toContain(
      formatChange(ROLE_METRIC_SPECS.carry_share, change.change),
    );
    expect(rail.dataset.direction).toBe("up");
    expect(rail.textContent).toContain(`vs ${String(change.earlier_games)} earlier games`);
    // One bar slot per published week, no more and no fewer.
    expect(rail.querySelectorAll(".usage-bar")).toHaveLength(record.weeks.length);
  });

  it("marks a declining role with a glyph and a signed number, not colour alone", async () => {
    const dialog = await openCard(DECLINING_WR);
    const rail = required(
      dialog.querySelector<HTMLElement>('.usage-rail[data-metric="snap_share"]'),
      "the snap-share rail",
    );
    expect(rail.dataset.direction).toBe("down");
    expect(rail.querySelector(".usage-rail-change")?.textContent).toMatch(/▼ −\d+ pts/);
  });

  it("withholds a change when the latest game has no snap row", async () => {
    const dialog = await openCard(NO_SNAP_TE);
    const rail = required(
      dialog.querySelector<HTMLElement>('.usage-rail[data-metric="snap_share"]'),
      "the snap-share rail",
    );
    expect(rail.textContent).toContain("no value in his latest game");
    expect(rail.querySelector(".usage-rail-change")).toBeNull();
    expect(rail.querySelector('.usage-bar[data-status="no_value"]')).not.toBeNull();
  });

  it("draws an absence as a mark, never a floor-height bar", async () => {
    const absent = "James Cook III";
    const dialog = await openCard(absent);
    const marks = dialog.querySelectorAll(
      '.usage-rail[data-metric="snap_share"] .usage-bar[data-status="did_not_play"]',
    );
    const missed = usageFor(absent).weeks.filter((week) => week.status === "did_not_play");
    expect(missed.length).toBeGreaterThan(0);
    expect(marks).toHaveLength(missed.length);
  });

  it("says a player has no usage record rather than drawing zeros", async () => {
    const name = required(
      opportunityRecords().find((r) => r.player_id === FIXTURE_NO_USAGE_PLAYER_ID),
      "the unpublished player",
    ).display_name;
    const dialog = await openCard(name);
    expect(within(dialog).getByText("No week-by-week role is published for him on this build.")).toBeDefined();
  });

  it("says the build published no role series when the artifact is absent", async () => {
    vi.unstubAllGlobals();
    serve({ signals: "absent" });
    const dialog = await openCard(RISING_RB);
    expect(dialog.querySelector(".usage-rails")).toBeNull();
    expect(within(dialog).getByText(/This build published no week-by-week role series/)).toBeDefined();
    expect(within(dialog).getByText("This build published no schedule context.")).toBeDefined();
  });
});

describe("a card for a player the draft board never held", () => {
  it("is headed by his in-season name, position and team rather than 'Player'", async () => {
    go("?view=opportunity&scoring=ppr&teams=12");
    render(<App />);
    const surfaced = required(
      opportunityRecords().find(
        (row) =>
          row.outside_tier_board && row.league_preset_id === "redraft-12" && row.scoring_preset === "PPR",
      ),
      "a surfaced row",
    );
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: surfaced.display_name }).length).toBeGreaterThan(0);
    });
    await userEvent.setup().click(
      required(screen.getAllByRole("button", { name: surfaced.display_name })[0], "the surfaced row"),
    );
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: surfaced.display_name })).toBeDefined();
    });
    // And the in-season panel, not the draft market: his role is what he was surfaced for.
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByText("Draft market")).toBeNull();
    expect(dialog.querySelector(".usage-rails")).not.toBeNull();
    expect(within(dialog).getByText(/no\s+projection or pace is published for him/)).toBeDefined();
  });
});

describe("the in-season card's next-game block", () => {
  it("prints the artifact's implied points and spread with the context statement", async () => {
    const dialog = await openCard(RISING_RB);
    const matchup = required(teamMatchupRecords().find((r) => r.team === "DET"), "DET");
    const panel = required(dialog.querySelector<HTMLElement>(".matchup"), "the matchup panel");
    expect(panel.textContent).toContain(`Week ${String(matchup.week)} vs ATL`);
    expect(panel.textContent).toContain((matchup.implied_team_points ?? 0).toFixed(1));
    expect(panel.textContent).toContain("Favoured by 3.5");
    expect(panel.textContent).toContain(FIXTURE_SIGNALS.sportsbook_context_statement);
  });

  it("says an unposted line is unposted", async () => {
    const dialog = await openCard("Trey McBride");
    const panel = required(dialog.querySelector<HTMLElement>(".matchup"), "the matchup panel");
    expect(panel.dataset.lines).toBe("unposted");
    expect(panel.textContent).toContain("no line posted yet");
    expect(panel.querySelector(".matchup-split")).toBeNull();
  });

  it("carries add momentum on the card, not only on Pick of the Week", async () => {
    const dialog = await openCard(RISING_RB);
    expect(dialog.querySelector(".momentum")).not.toBeNull();
  });
});

// -------------------------------------------------------------------- Pick of the Week

describe("Pick of the Week's evidence", () => {
  it("selects exactly the same picks with and without the signal layer", () => {
    const leagues = [...new Set(opportunityRecords().map((r) => r.league_preset_id))];
    expect(leagues.length).toBeGreaterThan(1);
    for (const league of leagues) {
      for (const scoring of ["PPR", "HALF", "STD"] as const) {
        const withSignals = buildPotwBoard(bundle(true), league, scoring);
        const without = buildPotwBoard(bundle(false), league, scoring);
        const ids = (board: typeof withSignals) =>
          board.sets.map((set) => set.picks.map((pick) => pick.opportunity.player_id));
        expect(ids(withSignals).flat().length).toBeGreaterThan(0);
        expect(ids(withSignals)).toEqual(ids(without));
      }
    }
  });

  it("says which artifact is missing when the build published neither", async () => {
    vi.unstubAllGlobals();
    serve({ signals: "absent" });
    go("?view=potw&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(screen.getAllByRole("article").length).toBeGreaterThan(0);
    });
    for (const card of screen.getAllByRole("article")) {
      const role = required(card.querySelector<HTMLElement>('[data-evidence="role"]'), "role block");
      const next = required(card.querySelector<HTMLElement>('[data-evidence="matchup"]'), "next game");
      expect(within(role).getByText("This build published no role series.")).toBeDefined();
      // Not "no next game for his team", which would claim a schedule was read and was empty.
      expect(within(next).getByText("This build published no schedule context.")).toBeDefined();
    }
  });

  it("draws role, production and next game as three separate blocks", async () => {
    go("?view=potw&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(screen.getAllByRole("article").length).toBeGreaterThan(0);
    });
    const card = required(screen.getAllByRole("article")[0], "the first pick");
    const kinds = [...card.querySelectorAll<HTMLElement>(".potw-evidence-block")].map(
      (block) => block.dataset.evidence,
    );
    expect(kinds).toEqual(["role", "production", "matchup"]);
  });

  it("states a role reason only when the leading role grew", () => {
    const board = buildPotwBoard(bundle(true), "redraft-12", "PPR");
    for (const set of board.sets) {
      for (const pick of set.picks) {
        const lead = ROLE_METRICS_BY_POSITION[pick.position][0];
        const change = lead === undefined ? null : pick.usage?.role_changes[lead];
        const stated = pick.reasons.some((reason) => / up from .* in week \d+/.test(reason));
        expect(stated).toBe(change?.change != null && change.change > 0);
      }
    }
  });
});
