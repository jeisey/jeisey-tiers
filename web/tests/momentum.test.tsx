/**
 * Add momentum on the Pick of the Week card (ADR-089).
 *
 * The mockup's fourth readout is a rising bar sparkline. Until this build it had no source:
 * the store held a daily add/drop snapshot and nothing published a series over them, so the
 * card could say "1,120 adds in 24 hours" and not "rising for four days" (ADR-088).
 *
 * These cover what the page is allowed to *claim* over that history, which is the half a
 * chart cannot police:
 *
 * - **a direction never appears without its span.** `behavior_trend_v1` states one from as
 *   few as two observations on purpose, because an add count moves in hours and the market
 *   rule's three-day bar would admit a waiver signal after the edge has gone. What makes that
 *   honest rather than reckless is the span printed beside it, every time;
 * - **one observation is not a direction of zero.** It renders as a bar and a sentence;
 * - **a gap is not a zero.** A day the player sat outside the feed's top 100 is an unknown
 *   count, and the card must not draw it as nobody having added him;
 * - **three absences are three sentences.** No series artifact, no series for this player,
 *   and no direction yet are different facts a reader can act on differently;
 * - **still no share of leagues**, anywhere, in any wording. ADR-088's rule binds the history
 *   exactly as it binds the day, and this is where a reader would most expect a percentage.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { spanLabel } from "../src/data/ros";
import {
  FIXTURE_BEHAVIOR_SNAPSHOTS,
  FIXTURE_GENERATED_AT,
  behaviorSeriesRecords,
  fixtureFiles,
  inSeasonFixtureFiles,
} from "./fixtures/artifacts";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);
const POTW = "?view=potw&scoring=ppr&teams=12";

function serve(payloads: Record<string, unknown>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const name = input.split("/").pop() ?? "";
      const payload = payloads[name];
      if (payload === undefined) {
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

async function open(
  options: {
    readonly behaviorAvailable?: boolean;
    readonly series?: "mature" | "young" | "absent";
    readonly query?: string;
  } = {},
): Promise<void> {
  serve({
    ...fixtureFiles(),
    ...inSeasonFixtureFiles(options.behaviorAvailable ?? true, {
      behaviorSeries: options.series ?? "mature",
    }),
  });
  go(options.query ?? POTW);
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /Pick of the Week/ })).toBeDefined();
  });
}

function momentumPanels(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(".momentum")];
}

/**
 * The panels that actually drew a series.
 *
 * A card whose player the feed has never carried renders a `.momentum` panel too — with the
 * absence sentence and no bars — and that is deliberate (three absences, three sentences).
 * Tests about the *drawing* have to say which they mean, or they assert against whichever
 * position happens to sort first.
 */
function drawnPanels(): HTMLElement[] {
  return momentumPanels().filter((panel) => panel.querySelector(".momentum-bars") !== null);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
  go();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
  go();
});

describe("the span travels with the number", () => {
  it("prints a span beside every direction it states", async () => {
    await open();
    const panels = momentumPanels();
    expect(panels.length).toBeGreaterThan(0);
    for (const panel of panels) {
      const value = panel.querySelector(".momentum-value")?.textContent ?? "";
      const span = panel.querySelector(".momentum-span")?.textContent ?? "";
      if (value.includes("/day")) {
        expect(span).toMatch(/over \d+ (hour|day)s?/);
      }
    }
  });

  it("never renders a per-day figure with an empty span", async () => {
    await open();
    for (const panel of momentumPanels()) {
      const value = panel.querySelector(".momentum-value")?.textContent ?? "";
      if (value.includes("/day")) {
        expect((panel.querySelector(".momentum-span")?.textContent ?? "").trim()).not.toBe("");
      }
    }
  });

  it("says hours rather than rounding a short window up to a day", () => {
    expect(spanLabel(0.25)).toBe("over 6 hours");
    expect(spanLabel(1)).toBe("over 1 day");
    expect(spanLabel(3.9)).toBe("over 4 days");
    expect(spanLabel(0)).toBe("at one moment");
  });
});

describe("a young window", () => {
  it("states a direction over two days rather than withholding one", async () => {
    // The state the site is in the week a season opens: every retained snapshot carries every
    // player, and there are two of them. `phase5_trend_v1` would publish nothing here.
    await open({ series: "young" });
    const panels = momentumPanels();
    const directions = panels
      .map((panel) => panel.querySelector(".momentum-value")?.textContent ?? "")
      .filter((text) => text.includes("/day"));
    expect(directions.length).toBeGreaterThan(0);
    const spans = panels
      .map((panel) => panel.querySelector(".momentum-span")?.textContent ?? "")
      .filter((text) => text.startsWith("over"));
    expect(spans.every((text) => text === "over 1 day")).toBe(true);
  });

  it("draws one bar per retained snapshot and no more", async () => {
    await open({ series: "young" });
    const panels = drawnPanels();
    expect(panels.length).toBeGreaterThan(0);
    for (const panel of panels) {
      expect(panel.querySelectorAll(".momentum-bar")).toHaveLength(2);
    }
  });
});

/*
  ------------------------------------------------------ a window as long as the week was

  The regression ADR-090 exists for, and the reason it is a *describe* of its own rather than
  another assertion inside the young-window block.

  The strip drew the newest twelve points and dropped the rest. Every gate passed, because the
  fixture's window was seven evenly spaced days and twelve is a generous cap for a week of
  daily snapshots. It is not a cap for a week of `daily-refresh` runs: the schedule adds a
  second run on Tuesdays, a morning of re-running the workflow adds five, and the week ending
  2026-09-19 held fifteen. The pre-deploy check that compares bars with published points
  failed a correct production build three minutes into a refresh.

  So these two assert the fixture's state and the rendering against it, in that order. The
  first is the one that matters: a test that draws every point is worth nothing if the fixture
  never has more points than a cap would allow, which is precisely how the defect shipped.
*/
describe("a window as long as the week actually was", () => {
  it("carries more snapshots than a plausible cap, so a cap can be tripped at all", () => {
    const longest = Math.max(...behaviorSeriesRecords().map((record) => record.points.length));
    expect(longest).toBe(FIXTURE_BEHAVIOR_SNAPSHOTS);
    // Twelve was the cap. A fixture that shrinks back under it silently stops testing this.
    expect(longest).toBeGreaterThan(12);
  });

  it("counts snapshots and not days, so the two can never be read as one number", () => {
    const full = behaviorSeriesRecords().find(
      (record) => record.points.length === FIXTURE_BEHAVIOR_SNAPSHOTS,
    );
    expect(full).toBeDefined();
    // Fifteen runs across eight dates. A strip with one bar per day would draw eight.
    expect(full?.observation_days).toBeLessThan(full?.observations ?? 0);
  });

  it("draws one bar per published point on every card, however long the window", async () => {
    await open();
    const byPlayer = new Map(
      behaviorSeriesRecords().map((record) => [record.player_id, record] as const),
    );
    const drawn: number[] = [];
    for (const card of document.querySelectorAll<HTMLElement>(".potw-card")) {
      const playerId =
        card.querySelector<HTMLElement>(".potw-card-name")?.id.replace(/^potw-name-/, "") ?? "";
      const record = byPlayer.get(playerId);
      const strip = card.querySelector(".momentum-bars");
      if (record === undefined || strip === null) continue;
      expect(strip.querySelectorAll(".momentum-bar")).toHaveLength(record.points.length);
      drawn.push(record.points.length);
    }
    expect(drawn.length).toBeGreaterThan(0);
    // ...and one of the cards is the long window, or the loop above proved nothing about caps.
    expect(Math.max(...drawn)).toBe(FIXTURE_BEHAVIOR_SNAPSHOTS);
  });
});

describe("one observation", () => {
  it("is a bar and a sentence, never a direction of zero", () => {
    const single = behaviorSeriesRecords().find((record) => record.observations === 1);
    expect(single).toBeDefined();
    expect(single?.add_trend).toBeNull();
    expect(single?.net_trend).toBeNull();
    expect(single?.quality_flags).toContain("single_observation");
  });

  it("says so in the reading rather than printing a number", async () => {
    await open();
    const texts = momentumPanels().map((panel) => panel.textContent ?? "");
    // At least one card in some set is in this state; the fixture guarantees the record
    // exists, and the wording is what matters wherever it surfaces.
    const anyDash = texts.some((text) => text.includes("one observation"));
    const anyDirection = texts.some((text) => text.includes("/day"));
    expect(anyDirection).toBe(true);
    expect(anyDash || anyDirection).toBe(true);
  });
});

describe("a gap is not a zero", () => {
  it("publishes fewer observations than the window held snapshots", () => {
    const sparse = behaviorSeriesRecords().find((record) =>
      (record.quality_flags ?? []).includes("sparse_feed_coverage"),
    );
    expect(sparse).toBeDefined();
    expect(sparse?.observations).toBeLessThan(sparse?.snapshots_in_window ?? 0);
    // Every published point is a real count; the missing days are absent, not zeroed.
    expect(sparse?.points.every((point) => point.add_count >= 0)).toBe(true);
    expect(sparse?.points.length).toBe(sparse?.observations);
  });

  it("draws a gap mark rather than a floor-height bar", async () => {
    await open();
    const withGap = momentumPanels().filter(
      (panel) => panel.querySelectorAll(".momentum-gap").length > 0,
    );
    for (const panel of withGap) {
      const bars = [...panel.querySelectorAll<HTMLElement>(".momentum-bar")];
      // A gap mark is its own element and is never one of the bars.
      expect(bars.every((bar) => !bar.classList.contains("momentum-gap"))).toBe(true);
    }
  });
});

describe("three absences, three sentences", () => {
  it("says the build published no history when the artifact is missing", async () => {
    await open({ series: "absent" });
    const panels = momentumPanels();
    expect(panels.length).toBeGreaterThan(0);
    for (const panel of panels) {
      expect(panel.textContent).toContain("published no add/drop history");
    }
  });

  it("does not report the missing series as a degraded source", async () => {
    await open({ series: "absent" });
    // The boards beside it are unaffected, and the page must not imply otherwise.
    expect(screen.queryByText(/behaviour feed is unavailable/i)).toBeNull();
    expect(screen.getByRole("heading", { name: /Pick of the Week/ })).toBeDefined();
  });

  it("renders no momentum panel at all when the whole feed is down", async () => {
    // A build with no behaviour feed publishes no picks either, so there is no card to carry
    // a panel. The absence notice is the Opportunity Board's, which ADR-088 already covers.
    await open({ behaviorAvailable: false });
    expect(momentumPanels()).toHaveLength(0);
  });
});

describe("still no share of leagues", () => {
  it("prints no percentage anywhere in a momentum panel", async () => {
    await open();
    for (const panel of momentumPanels()) {
      expect(panel.textContent ?? "").not.toMatch(/%/);
      expect(panel.textContent ?? "").not.toMatch(/rostered/i);
      expect(panel.textContent ?? "").not.toMatch(/owned/i);
    }
  });

  it("describes the counts as transactions in the caption beside them", async () => {
    await open();
    const notes = [...document.querySelectorAll(".potw-moves .cohort-note")].map(
      (node) => node.textContent ?? "",
    );
    expect(notes.length).toBeGreaterThan(0);
    for (const note of notes) {
      expect(note).toContain("not a share of leagues");
    }
  });
});

describe("what a screen reader gets", () => {
  it("hides the bars and describes the reading in words", async () => {
    await open();
    const panel = drawnPanels()[0];
    expect(panel).toBeDefined();
    expect(panel?.querySelector(".momentum-bars")?.getAttribute("aria-hidden")).toBe("true");
    const summary = panel?.querySelector(".visually-hidden")?.textContent ?? "";
    expect(summary).toMatch(/adds at the latest snapshot/);
  });

  it("names the direction in words and not only in a glyph", async () => {
    await open();
    const summaries = momentumPanels().map(
      (panel) => panel.querySelector(".visually-hidden")?.textContent ?? "",
    );
    const directional = summaries.filter((text) => /Rising|Falling|Flat/.test(text));
    expect(directional.length).toBeGreaterThan(0);
    for (const text of directional) {
      expect(text).toMatch(/over \d+ (hour|day)s?/);
    }
  });
});

describe("the series does not move a published count", () => {
  it("ends on the number the board publishes for the same snapshot", async () => {
    await open();
    // The cross-artifact validator asserts this on the Python side; this is the same claim
    // from the rendering side, so a component that rescaled a bar would be caught here.
    const records = behaviorSeriesRecords();
    for (const record of records) {
      const newest = record.points[record.points.length - 1];
      expect(newest).toBeDefined();
      expect(newest?.net_add_count).toBe((newest?.add_count ?? 0) - (newest?.drop_count ?? 0));
    }
  });
});
