/**
 * The market-trend mini chart (Phase 10, ADR-066).
 *
 * The three things worth testing are the three the roadmap names, and each of them is a way
 * the chart could be quietly wrong rather than visibly broken:
 *
 * - **Orientation.** Lower ADP means earlier, which means hotter. Drawn naively the line
 *   would fall as demand rose, and nobody would notice until they misread a card.
 * - **Sparse history.** Two points make a line that implies a trend the store cannot
 *   support, so below three points the component says so in words.
 * - **Accessibility.** The direction has to survive greyscale and a screen reader, so it is
 *   in the caption text and the SVG title, not only in the stroke colour.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MIN_TREND_POINTS, MarketTrend, type TrendPoint } from "../src/charts/MarketTrend";

afterEach(cleanup);

function series(adps: readonly number[]): TrendPoint[] {
  return adps.map((market_adp, index) => ({
    observed_at: `2026-08-${String(27 + index).padStart(2, "0")}T12:00:00Z`,
    market_adp,
  }));
}

describe("orientation", () => {
  it("draws a rising line when the ADP falls, because falling ADP means earlier", () => {
    // 40 -> 30 is a player being drafted ten picks earlier: more expensive, more wanted.
    render(<MarketTrend points={series([40, 36, 33, 30])} label="FFC Recent" trend={2.5} />);
    const path = document.querySelector(".trend-line");
    expect(path?.getAttribute("data-kind")).toBe("earlier");

    const d = path?.getAttribute("d") ?? "";
    const ys = [...d.matchAll(/[ML]\s*[\d.]+\s+([\d.]+)/g)].map((match) => Number(match[1]));
    expect(ys.length).toBe(4);
    // Smaller y is higher on screen. The last point must sit above the first.
    expect(ys.at(-1) ?? 0).toBeLessThan(ys.at(0) ?? 0);
  });

  it("draws a falling line when the ADP rises", () => {
    render(<MarketTrend points={series([30, 34, 38, 42])} label="FFC Recent" trend={-2.5} />);
    const path = document.querySelector(".trend-line");
    expect(path?.getAttribute("data-kind")).toBe("later");
    const d = path?.getAttribute("d") ?? "";
    const ys = [...d.matchAll(/[ML]\s*[\d.]+\s+([\d.]+)/g)].map((match) => Number(match[1]));
    expect(ys.at(-1) ?? 0).toBeGreaterThan(ys.at(0) ?? 0);
  });

  it("says which direction it means, in words rather than only in colour", () => {
    render(<MarketTrend points={series([40, 36, 33, 30])} label="FFC Recent" trend={2.5} />);
    expect(screen.getByText(/moving earlier/)).toBeDefined();

    cleanup();
    render(<MarketTrend points={series([30, 34, 38, 42])} label="FFC Recent" trend={-2.5} />);
    expect(screen.getByText(/moving later/)).toBeDefined();
  });
});

describe("sparse history", () => {
  it.each([0, 1, 2])("says there is not enough history at %i points", (count) => {
    render(
      <MarketTrend points={series([40, 39, 38].slice(0, count))} label="FFC Recent" trend={null} />,
    );
    const empty = screen.getByTestId("market-trend-empty");
    expect(empty.textContent).toMatch(/Not enough retained FFC Recent history/);
    expect(document.querySelector(".trend-line")).toBeNull();
  });

  it("draws once it has the minimum the rule needs", () => {
    render(<MarketTrend points={series([40, 39, 38])} label="FFC Recent" trend={1} />);
    expect(screen.getByTestId("market-trend")).toBeDefined();
    expect(MIN_TREND_POINTS).toBe(3);
  });

  it("names the source, so switching markets cannot silently relabel a series", () => {
    render(<MarketTrend points={[]} label="MFL Cumulative" trend={null} />);
    expect(screen.getByTestId("market-trend-empty").textContent).toContain("MFL Cumulative");
  });
});

describe("accessibility", () => {
  it("gives the whole movement as one readable sentence", () => {
    render(<MarketTrend points={series([40, 36, 33, 30])} label="FFC Recent" trend={2.5} />);
    const figure = screen.getByTestId("market-trend");
    const image = within(figure).getByRole("img");
    expect(image.getAttribute("aria-labelledby")).toBeTruthy();
    const title = figure.querySelector("title")?.textContent ?? "";
    expect(title).toContain("FFC Recent ADP moved from 40.0 to 30.0");
    expect(title).toContain("earlier, so more expensive");
  });

  it("labels every point with its date and price, so a keyboard can read them", () => {
    render(<MarketTrend points={series([40, 36, 33])} label="FFC Recent" trend={1} />);
    const points = screen.getAllByRole("button");
    expect(points).toHaveLength(3);
    expect(points[0]?.getAttribute("aria-label")).toMatch(/Aug 27: ADP 40\.0/);
    expect(points.every((point) => point.getAttribute("tabindex") === "0")).toBe(true);
  });

  it("prints the latest reading without needing a hover", () => {
    render(<MarketTrend points={series([40, 36, 33])} label="FFC Recent" trend={1} />);
    // Touch devices have no hover and a title attribute is not reachable by keyboard, so
    // the current value is in the caption for everyone.
    expect(screen.getByText("Latest 33.0")).toBeDefined();
  });
});

describe("edge cases", () => {
  it("handles a perfectly flat series without dividing by zero", () => {
    render(<MarketTrend points={series([40, 40, 40, 40])} label="FFC Recent" trend={0} />);
    const d = document.querySelector(".trend-line")?.getAttribute("d") ?? "";
    expect(d).not.toContain("NaN");
    expect(screen.getByText("unchanged")).toBeDefined();
  });

  it("sorts points by time, so an out-of-order artifact still reads left to right", () => {
    const ordered = series([40, 36, 33]);
    const shuffled: TrendPoint[] = [ordered[2], ordered[0], ordered[1]].filter(
      (point): point is TrendPoint => point !== undefined,
    );
    render(<MarketTrend points={shuffled} label="FFC Recent" trend={1} />);
    const title = screen.getByTestId("market-trend").querySelector("title")?.textContent ?? "";
    expect(title).toContain("from 40.0 to 33.0");
  });

  it("omits the slope readout when the rule could not compute one", () => {
    render(<MarketTrend points={series([40, 36, 33])} label="FFC Recent" trend={null} />);
    expect(document.querySelector(".trend-slope")).toBeNull();
  });
});
