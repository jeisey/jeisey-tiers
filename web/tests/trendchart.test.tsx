/**
 * The market-history mini chart (Phase 10, ADR-066; corrected by ADR-081).
 *
 * Four things worth testing, and each is a way the chart could be quietly wrong rather than
 * visibly broken:
 *
 * - **Orientation.** Lower ADP means earlier, which means hotter. Drawn naively the line
 *   would fall as demand rose, and nobody would notice until they misread a card.
 * - **Sparse history is drawn, not withheld.** The first version refused below three points,
 *   conflating "we can show what we observed" with "we may estimate a slope". A market with
 *   seven real snapshots consequently read "0 snapshots so far" in production, and the two
 *   questions are separated here by assertion rather than by comment.
 * - **Several markets stay several markets.** The cross view overlays real series; nothing is
 *   averaged, each names itself, and they are distinguishable without colour.
 * - **Accessibility.** Direction and identity have to survive greyscale and a screen reader,
 *   so both are in the caption text, the legend and the SVG title.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  MarketTrend,
  pointsByDay,
  type TrendPoint,
  type TrendSeries,
} from "../src/charts/MarketTrend";

afterEach(cleanup);

function points(adps: readonly number[], startDay = 27): TrendPoint[] {
  return adps.map((market_adp, index) => ({
    observed_at: `2026-08-${String(startDay + index).padStart(2, "0")}T12:00:00Z`,
    market_adp,
  }));
}

function series(
  adps: readonly number[],
  overrides: Partial<TrendSeries> = {},
): TrendSeries[] {
  return [
    {
      sourceId: "fantasyfootballcalculator_adp",
      label: "FFC Recent",
      points: points(adps),
      trend: null,
      ...overrides,
    },
  ];
}

/** The plotted lines, excluding the legend's swatches, which reuse the same stroke class. */
function chartLines(): Element[] {
  return [...document.querySelectorAll(".trend-chart > svg .trend-line")];
}

function pathYs(element: Element | null): number[] {
  const d = element?.getAttribute("d") ?? "";
  return [...d.matchAll(/[ML]\s*[\d.]+\s+([\d.]+)/g)].map((match) => Number(match[1]));
}

describe("orientation", () => {
  it("draws a rising line when the ADP falls, because falling ADP means earlier", () => {
    // 40 -> 30 is a player being drafted ten picks earlier: more expensive, more wanted.
    render(<MarketTrend series={series([40, 36, 33, 30], { trend: 2.5 })} label="FFC Recent" />);
    const path = chartLines()[0] ?? null;
    expect(path?.getAttribute("data-kind")).toBe("earlier");

    const ys = pathYs(path);
    expect(ys.length).toBe(4);
    // Smaller y is higher on screen. The last point must sit above the first.
    expect(ys.at(-1) ?? 0).toBeLessThan(ys.at(0) ?? 0);
  });

  it("draws a falling line when the ADP rises", () => {
    render(<MarketTrend series={series([30, 34, 38, 42], { trend: -2.5 })} label="FFC Recent" />);
    const path = chartLines()[0] ?? null;
    expect(path?.getAttribute("data-kind")).toBe("later");
    const ys = pathYs(path);
    expect(ys.at(-1) ?? 0).toBeGreaterThan(ys.at(0) ?? 0);
  });

  it("says which direction it means, in words rather than only in colour", () => {
    render(<MarketTrend series={series([40, 36, 33, 30], { trend: 2.5 })} label="FFC Recent" />);
    expect(screen.getByText(/moving earlier/)).toBeDefined();

    cleanup();
    render(<MarketTrend series={series([30, 34, 38, 42], { trend: -2.5 })} label="FFC Recent" />);
    expect(screen.getByText(/moving later/)).toBeDefined();
  });

  it("spaces the marks by date, so an irregular capture cadence is not drawn as an even one", () => {
    const uneven: TrendSeries[] = [
      {
        sourceId: "myfantasyleague_adp",
        label: "MFL Cumulative",
        trend: null,
        points: [
          { observed_at: "2026-08-27T12:00:00Z", market_adp: 40 },
          { observed_at: "2026-08-28T12:00:00Z", market_adp: 38 },
          { observed_at: "2026-09-03T12:00:00Z", market_adp: 36 },
        ],
      },
    ];
    render(<MarketTrend series={uneven} label="MFL Cumulative" />);
    const d = chartLines()[0]?.getAttribute("d") ?? "";
    const xs = [...d.matchAll(/[ML]\s*([\d.]+)\s+[\d.]+/g)].map((match) => Number(match[1]));
    // One day, then six. An index axis would put the middle mark halfway across.
    const first = (xs[1] ?? 0) - (xs[0] ?? 0);
    const second = (xs[2] ?? 0) - (xs[1] ?? 0);
    expect(second).toBeGreaterThan(first * 3);
  });
});

describe("sparse history is a history", () => {
  it("draws a single retained observation as a point rather than calling it nothing", () => {
    render(<MarketTrend series={series([40])} label="FFC Recent" />);
    expect(screen.getByTestId("market-trend")).toBeDefined();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    // One observation is a reading, not a line: a zero-length path would render nothing.
    expect(chartLines()).toHaveLength(0);
  });

  it("draws two retained observations as two facts and the line between them", () => {
    render(<MarketTrend series={series([40, 36])} label="FFC Recent" />);
    expect(pathYs(chartLines()[0] ?? null)).toHaveLength(2);
  });

  it("keeps the slope collecting while it draws the history the slope cannot yet use", () => {
    // Exactly the production state: real observations, span too short for `phase5_trend_v1`.
    render(<MarketTrend series={series([40, 39, 38], { trend: null })} label="FFC Recent" />);
    expect(screen.getByTestId("market-trend")).toBeDefined();
    expect(screen.getByText("trend collecting")).toBeDefined();
  });

  it("says there is no history only when there is genuinely none, and names the market", () => {
    render(<MarketTrend series={series([])} label="FFC Recent" />);
    const empty = screen.getByTestId("market-trend-empty");
    expect(empty.textContent).toMatch(/No retained FFC Recent history/);
    expect(chartLines()).toHaveLength(0);
  });

  it("names the market from the selection, not from the series it does not have", () => {
    render(<MarketTrend series={[]} label="MFL Cumulative" />);
    expect(screen.getByTestId("market-trend-empty").textContent).toContain("MFL Cumulative");
  });
});

describe("one point per day", () => {
  it("keeps the latest observation of each calendar day", () => {
    const reduced = pointsByDay([
      { observed_at: "2026-09-03T18:18:49Z", market_adp: 24.5 },
      { observed_at: "2026-09-03T19:01:39Z", market_adp: 24.4 },
      { observed_at: "2026-09-03T20:48:21Z", market_adp: 24.2 },
      { observed_at: "2026-09-04T11:25:33Z", market_adp: 24.0 },
    ]);
    expect(reduced.map((point) => point.market_adp)).toEqual([24.2, 24.0]);
  });

  it("is presentation only: three captures on one afternoon draw as one day", () => {
    const sameDay: TrendSeries[] = [
      {
        sourceId: "fantasyfootballcalculator_adp",
        label: "FFC Recent",
        trend: null,
        points: [
          { observed_at: "2026-09-03T18:18:49Z", market_adp: 24.5 },
          { observed_at: "2026-09-03T19:01:39Z", market_adp: 24.4 },
          { observed_at: "2026-09-03T20:48:21Z", market_adp: 24.2 },
        ],
      },
    ];
    render(<MarketTrend series={sameDay} label="FFC Recent" />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button").getAttribute("aria-label")).toContain("24.2");
  });
});

describe("the cross-market view", () => {
  const ffc: TrendSeries = {
    sourceId: "fantasyfootballcalculator_adp",
    label: "FFC Recent",
    trend: null,
    points: points([28, 27, 26]),
  };
  const mfl: TrendSeries = {
    sourceId: "myfantasyleague_adp",
    label: "MFL Cumulative",
    trend: -0.4,
    points: points([31, 32, 33]),
  };
  const both: TrendSeries[] = [ffc, mfl];

  it("overlays both markets' real series on one dated axis", () => {
    render(<MarketTrend series={both} label="market" />);
    const groups = document.querySelectorAll("g[data-source]");
    expect([...groups].map((group) => group.getAttribute("data-source"))).toEqual([
      "fantasyfootballcalculator_adp",
      "myfantasyleague_adp",
    ]);
  });

  it("never averages them into a series no capture produced", () => {
    render(<MarketTrend series={both} label="market" />);
    expect(chartLines()).toHaveLength(2);
    expect(document.querySelector('g[data-source="cross"]')).toBeNull();
  });

  it("tells the two apart without colour: a stroke pattern and a named legend row", () => {
    render(<MarketTrend series={both} label="market" />);
    const lines = chartLines();
    const dashes = lines.map((line) => line.getAttribute("stroke-dasharray"));
    expect(new Set(dashes).size).toBe(2);
    expect(screen.getByText("FFC Recent")).toBeDefined();
    expect(screen.getByText("MFL Cumulative")).toBeDefined();
  });

  it("gives each market its own slope, or its own reason for not having one", () => {
    render(<MarketTrend series={both} label="market" />);
    expect(screen.getByText("trend collecting")).toBeDefined();
    expect(screen.getByText("-0.40/day")).toBeDefined();
  });

  it("shows the one market that has history when the other has none", () => {
    render(
      <MarketTrend
        series={[ffc, { ...mfl, points: [] }]}
        label="market"
      />,
    );
    const groups = [...document.querySelectorAll("g[data-source]")];
    expect(groups.map((group) => group.getAttribute("data-source"))).toEqual([
      "fantasyfootballcalculator_adp",
    ]);
    expect(screen.queryByText("MFL Cumulative")).toBeNull();
  });
});

describe("accessibility", () => {
  it("gives the whole movement as one readable sentence, per market", () => {
    render(<MarketTrend series={series([40, 36, 33, 30], { trend: 2.5 })} label="FFC Recent" />);
    const figure = screen.getByTestId("market-trend");
    // `group` rather than `img`: the marks inside are focusable buttons, and `img` declares
    // its subtree presentational, which hides every per-day reading from a screen reader.
    const plot = within(figure).getByRole("group");
    expect(plot.getAttribute("aria-labelledby")).toBeTruthy();
    const title = figure.querySelector("title")?.textContent ?? "";
    expect(title).toContain("FFC Recent ADP moved from 40.0 to 30.0");
    expect(title).toContain("earlier, so more expensive");
  });

  it("labels every point with its market, date and price, so a keyboard can read them", () => {
    render(<MarketTrend series={series([40, 36, 33], { trend: 1 })} label="FFC Recent" />);
    const marks = screen.getAllByRole("button");
    expect(marks).toHaveLength(3);
    expect(marks[0]?.getAttribute("aria-label")).toMatch(/FFC Recent, Aug 27: ADP 40\.0/);
    expect(marks.every((mark) => mark.getAttribute("tabindex") === "0")).toBe(true);
  });

  it("prints the latest reading without needing a hover", () => {
    render(<MarketTrend series={series([40, 36, 33], { trend: 1 })} label="FFC Recent" />);
    // Touch devices have no hover and a title attribute is not reachable by keyboard, so
    // the current value is in the caption for everyone.
    expect(screen.getByText("FFC Recent 33.0")).toBeDefined();
  });

  it("names the days the axis spans, because 'ADP by day' is the claim", () => {
    render(<MarketTrend series={series([40, 36, 33], { trend: 1 })} label="FFC Recent" />);
    const axis = document.querySelector(".trend-axis");
    expect(axis?.textContent).toContain("Aug 27");
    expect(axis?.textContent).toContain("Aug 29");
  });
});

describe("edge cases", () => {
  it("handles a perfectly flat series without dividing by zero", () => {
    render(<MarketTrend series={series([40, 40, 40, 40], { trend: 0 })} label="FFC Recent" />);
    const d = chartLines()[0]?.getAttribute("d") ?? "";
    expect(d).not.toContain("NaN");
    expect(screen.getByText("unchanged")).toBeDefined();
  });

  it("sorts points by time, so an out-of-order artifact still reads left to right", () => {
    const ordered = points([40, 36, 33]);
    const shuffled = [ordered[2], ordered[0], ordered[1]].filter(
      (point): point is TrendPoint => point !== undefined,
    );
    render(<MarketTrend series={series([], { points: shuffled })} label="FFC Recent" />);
    const title = screen.getByTestId("market-trend").querySelector("title")?.textContent ?? "";
    expect(title).toContain("from 40.0 to 33.0");
  });

  it("says 'collecting' rather than printing a slope the rule did not compute", () => {
    render(<MarketTrend series={series([40, 36, 33], { trend: null })} label="FFC Recent" />);
    expect(screen.getByText("trend collecting")).toBeDefined();
    expect(document.querySelector(".trend-slope")?.textContent).toBe("trend collecting");
  });
});
