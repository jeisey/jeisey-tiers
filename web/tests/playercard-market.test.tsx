/**
 * The player card's Draft Market section, per selected market (ADR-081).
 *
 * **What production exposed.** The card resolved its numbers with `??`:
 * `selected?.rank_gap ?? arbitrage.rank_gap`, and in four places the flat `market_trend`
 * outright. The flat fields are MyFantasyLeague's. So with FFC selected, an FFC trend that
 * was legitimately null — real observations, not yet three days of elapsed span — silently
 * became MyFantasyLeague's slope, printed under an FFC heading, beside a chart that said
 * "0 snapshots so far" because the history index had been asked for a `cross` source that no
 * capture produces.
 *
 * Every test here fails on that card. They are grouped by the question each answers:
 *
 * | question                                   | why it could go wrong quietly            |
 * |--------------------------------------------|------------------------------------------|
 * | does the chart show the selected source?    | one market's line relabelled as another  |
 * | does a null slope stay null?                | `??` deletes the measurement             |
 * | does cross overlay real series?             | a synthetic average nobody captured      |
 * | does an absent source degrade honestly?     | a borrowed number reads as this market's |
 * | do the numbers come from the artifact?      | a chart recomputed in the browser        |
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import {
  FIXTURE_GENERATED_AT,
  arbitrageEnvelope,
  arbitrageRecords,
  buildMetadata,
  marketTrendSeriesEnvelope,
  marketTrendSeriesRecords,
  playerStatusEnvelope,
  projectionEnvelope,
  tierEnvelope,
} from "./fixtures/artifacts";
import type { MarketCondition } from "./fixtures/artifacts";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

const FFC = "fantasyfootballcalculator_adp";
const MFL = "myfantasyleague_adp";

/** Priced by both markets on every block, so the selector is the only thing that varies. */
const DUAL_PRICED = "Bijan Robinson";
/** Priced by MyFantasyLeague alone, which is the graceful-degradation case. */
const MFL_ONLY = "Joe Burrow";

type Payloads = Record<string, unknown>;
const MISSING = Symbol("missing");

function serve(condition: MarketCondition = "matured", overrides: Payloads = {}): void {
  const payloads: Payloads = {
    "build_metadata.json": buildMetadata({}, condition),
    "tiers.json": tierEnvelope(),
    "arbitrage.json": arbitrageEnvelope(condition),
    "market_trend_series.json": marketTrendSeriesEnvelope(condition),
    "player_status.json": playerStatusEnvelope(),
    "projections.json": projectionEnvelope(),
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const name = input.split("/").pop() ?? "";
      const payload = payloads[name];
      if (payload === undefined || payload === MISSING) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve(null),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(payload),
      } as Response);
    }),
  );
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

/** Open one player's card with a given market selected, and hand back the dialog. */
async function openCard(player: string, market: string): Promise<HTMLElement> {
  go(`?market=${market}&scoring=ppr&teams=12`);
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Tier board" })).toBeDefined();
  });
  await userEvent.setup().click(screen.getByRole("button", { name: player }));
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: player })).toBeDefined();
  });
  return screen.getByRole("dialog");
}

/** The record the artifact published for one player, market and block. */
function seriesFor(player: string, sourceId: string, condition: MarketCondition = "matured") {
  const row = arbitrageRecords(condition).find(
    (record) =>
      record.display_name === player &&
      record.league_preset_id === "redraft-12" &&
      record.scoring_preset === "PPR",
  );
  expect(row, `no ${player} row in the fixture`).toBeTruthy();
  return marketTrendSeriesRecords(condition).find(
    (record) =>
      record.player_id === row?.player_id &&
      record.market_source_id === sourceId &&
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
// The chart shows the selected source's history, and only that
// --------------------------------------------------------------------------------------

describe("a single market is selected", () => {
  it("draws FFC's retained history, never MyFantasyLeague's", async () => {
    const dialog = await openCard(DUAL_PRICED, FFC);
    const chart = within(dialog).getByTestId("market-trend");

    const ffc = seriesFor(DUAL_PRICED, FFC);
    const mfl = seriesFor(DUAL_PRICED, MFL);
    expect(ffc).toBeTruthy();
    expect(mfl).toBeTruthy();

    const groups = [...chart.querySelectorAll("g[data-source]")].map((group) =>
      group.getAttribute("data-source"),
    );
    expect(groups).toEqual([FFC]);
    // The two markets disagree by construction, so reading the wrong one is visible.
    const latestFfc = ffc?.points.at(-1)?.market_adp ?? 0;
    const latestMfl = mfl?.points.at(-1)?.market_adp ?? 0;
    expect(latestFfc).not.toBeCloseTo(latestMfl, 1);
    expect(within(chart).getByText(`FFC Recent ${latestFfc.toFixed(1)}`)).toBeDefined();
  });

  it("draws MyFantasyLeague's retained history when MyFantasyLeague is selected", async () => {
    const dialog = await openCard(DUAL_PRICED, MFL);
    const chart = within(dialog).getByTestId("market-trend");

    const mfl = seriesFor(DUAL_PRICED, MFL);
    const groups = [...chart.querySelectorAll("g[data-source]")].map((group) =>
      group.getAttribute("data-source"),
    );
    expect(groups).toEqual([MFL]);
    expect(
      within(chart).getByText(`MFL Cumulative ${(mfl?.points.at(-1)?.market_adp ?? 0).toFixed(1)}`),
    ).toBeDefined();
  });

  it("charts a history whose span is too short to fit, while the slope stays collecting", async () => {
    // FFC's fixture window is five observations over four calendar days spanning 62 hours:
    // `phase5_trend_v1` declines, and the chart still has something true to draw.
    const ffc = seriesFor(DUAL_PRICED, FFC);
    expect(ffc?.market_trend).toBeNull();
    expect((ffc?.points ?? []).length).toBeGreaterThan(2);

    const dialog = await openCard(DUAL_PRICED, FFC);
    expect(within(dialog).getByTestId("market-trend")).toBeDefined();
    expect(within(dialog).queryByTestId("market-trend-empty")).toBeNull();
    const readout = within(dialog).getByText("FFC Recent trend").closest(".readout");
    expect(readout?.textContent).toContain("collecting");
  });

  it("never fills a selected market's null slope in from another market", async () => {
    const mfl = seriesFor(DUAL_PRICED, MFL);
    // The fixture's whole point: MyFantasyLeague *has* a slope, so a fallback would show it.
    expect(mfl?.market_trend).not.toBeNull();

    const dialog = await openCard(DUAL_PRICED, FFC);
    const readout = within(dialog).getByText("FFC Recent trend").closest(".readout");
    expect(readout?.textContent).not.toContain(String(mfl?.market_trend ?? ""));
    expect(readout?.querySelector(".readout-value")?.textContent).toContain("—");
  });

  it("takes ADP, gap, cohort, snapshot and window from the selected market too", async () => {
    const dialog = await openCard(DUAL_PRICED, FFC);
    const row = arbitrageRecords("matured").find(
      (record) =>
        record.display_name === DUAL_PRICED &&
        record.league_preset_id === "redraft-12" &&
        record.scoring_preset === "PPR",
    );
    const ffc = (row?.markets ?? []).find((entry) => entry.source_id === FFC);
    const mfl = (row?.markets ?? []).find((entry) => entry.source_id === MFL);
    expect(ffc && mfl).toBeTruthy();

    const text = dialog.textContent ?? "";
    expect(within(dialog).getByText("FFC Recent ADP")).toBeDefined();
    expect(text).toContain((ffc?.market_adp ?? 0).toFixed(1));
    // The window is FFC's rolling week, not MyFantasyLeague's season aggregate.
    expect(within(dialog).getByText("Aggregation window").closest(".readout")?.textContent).toContain(
      "7-day recent window",
    );
    // ...and the cohort is FFC's, which MyFantasyLeague's string would not match.
    expect(within(dialog).getByText("Cohort").closest(".readout")?.textContent).toContain(
      ffc?.market_cohort_detail ?? "",
    );
    expect(within(dialog).getByText("Cohort").closest(".readout")?.textContent).not.toContain(
      "IS_KEEPER",
    );
  });
});

// --------------------------------------------------------------------------------------
// Cross overlays the real markets and invents nothing
// --------------------------------------------------------------------------------------

describe("the cross-market view", () => {
  it("overlays both markets' histories on one chart", async () => {
    const dialog = await openCard(DUAL_PRICED, "cross");
    const chart = within(dialog).getByTestId("market-trend");
    const groups = [...chart.querySelectorAll("g[data-source]")].map((group) =>
      group.getAttribute("data-source"),
    );
    expect(groups).toEqual([FFC, MFL]);
    expect(within(chart).getByText("FFC Recent")).toBeDefined();
    expect(within(chart).getByText("MFL Cumulative")).toBeDefined();
  });

  /**
   * The trap, baited. The App used to pass the *selection* — the literal string `cross` —
   * into an index keyed by real source ids, which could only ever miss. Serving a `cross`
   * record proves the fix is "overlay the real series", not "look up a different key": a
   * card that still asked for a cross source would find one here and draw it.
   */
  it("ignores a `cross` record even when the artifact contains one", async () => {
    const real = marketTrendSeriesRecords("matured");
    const planted = real
      .filter((record) => record.market_source_id === MFL)
      .map((record) => ({
        ...record,
        market_source_id: "cross",
        points: record.points.map((point) => ({ ...point, market_adp: 999 })),
      }));
    serve("matured", {
      "market_trend_series.json": {
        schema_version: "1.0",
        artifact: "market_trend_series",
        record_schema: "market_trend_series",
        build_id: "fixture-20260821T120000Z",
        generated_at_utc: FIXTURE_GENERATED_AT,
        record_count: real.length + planted.length,
        records: [...real, ...planted],
      },
    });
    const dialog = await openCard(DUAL_PRICED, "cross");
    const chart = within(dialog).getByTestId("market-trend");
    const groups = [...chart.querySelectorAll("g[data-source]")].map((group) =>
      group.getAttribute("data-source"),
    );
    expect(groups).toEqual([FFC, MFL]);
    expect(chart.textContent).not.toContain("999");
  });

  it("shows no single cross-market slope, and lists each market's own instead", async () => {
    const dialog = await openCard(DUAL_PRICED, "cross");
    const readout = within(dialog).getByText("Market trend").closest(".readout");
    expect(readout?.querySelector(".readout-value")?.textContent).toContain("—");
    expect(readout?.textContent).toContain("per market, below");

    const chart = within(dialog).getByTestId("market-trend");
    const legend = chart.querySelector(".trend-legend");
    const mfl = seriesFor(DUAL_PRICED, MFL);
    expect(legend?.textContent).toContain("trend collecting");
    expect(legend?.textContent).toContain(`${(mfl?.market_trend ?? 0).toFixed(2)}/day`);
  });

  it("shows the one market that has history when the other has none", async () => {
    const dialog = await openCard(MFL_ONLY, "cross");
    const chart = within(dialog).getByTestId("market-trend");
    const groups = [...chart.querySelectorAll("g[data-source]")].map((group) =>
      group.getAttribute("data-source"),
    );
    expect(groups).toEqual([MFL]);
  });
});

// --------------------------------------------------------------------------------------
// Degrading honestly
// --------------------------------------------------------------------------------------

describe("a market that did not price him", () => {
  it("says so, and lists the market that did, instead of borrowing a number", async () => {
    const dialog = await openCard(MFL_ONLY, FFC);
    expect(within(dialog).getByText(/No current FFC Recent ADP for him/)).toBeDefined();
    // The number FFC does not have must not appear under an FFC heading...
    expect(within(dialog).queryByText("FFC Recent ADP")).toBeNull();
    // ...and the market that does price him is still on the card.
    const table = within(dialog).getByRole("table");
    expect(within(table).getByText("MFL Cumulative")).toBeDefined();
  });

  it("keeps the chart truthful rather than empty by accident", async () => {
    const dialog = await openCard(MFL_ONLY, MFL);
    expect(within(dialog).getByTestId("market-trend")).toBeDefined();
  });
});

describe("a build with no retained history at all", () => {
  it("says nothing has been captured yet, naming the market it means", async () => {
    serve("matured", { "market_trend_series.json": MISSING });
    const dialog = await openCard(DUAL_PRICED, FFC);
    const empty = within(dialog).getByTestId("market-trend-empty");
    expect(empty.textContent).toContain("FFC Recent");
    // The rest of the market section is unaffected: a missing chart is not a missing price.
    expect(within(dialog).getByText("FFC Recent ADP")).toBeDefined();
  });
});

// --------------------------------------------------------------------------------------
// The numbers come from the artifact
// --------------------------------------------------------------------------------------

describe("provenance", () => {
  it("plots the artifact's own dates and prices, recomputing nothing", async () => {
    const dialog = await openCard(DUAL_PRICED, MFL);
    const chart = within(dialog).getByTestId("market-trend");
    const record = seriesFor(DUAL_PRICED, MFL);
    const labels = [...chart.querySelectorAll("circle[role='button']")].map((mark) =>
      mark.getAttribute("aria-label"),
    );

    expect(labels).toHaveLength(record?.points.length ?? 0);
    for (const point of record?.points ?? []) {
      const day = new Date(point.observed_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      });
      expect(
        labels.some(
          (label) =>
            label?.includes(day) === true &&
            label.includes(`ADP ${point.market_adp.toFixed(1)}`),
        ),
        `no mark for ${day} at ${String(point.market_adp)}`,
      ).toBe(true);
    }
  });

  it("calls no vendor: every fetch is a same-origin artifact", async () => {
    await openCard(DUAL_PRICED, "cross");
    // The stub above is only ever called with a string URL, which is what the loader passes.
    const calls = vi
      .mocked(globalThis.fetch)
      .mock.calls.map(([input]) => input)
      .filter((input): input is string => typeof input === "string");
    expect(calls.length).toBeGreaterThan(0);
    for (const url of calls) {
      expect(url).not.toMatch(/^https?:\/\//);
      expect(url).toMatch(/\.json$/);
    }
  });
});
