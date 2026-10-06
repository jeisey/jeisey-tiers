/**
 * The drive rail (ADR-103, ADR-104): a rail like its neighbours — a bar per game on the shares'
 * axis, the latest against the earlier games — with a notch at the random-allocation share and
 * one line for the four-game comparison. Nothing on the card recomputes a count.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import type { DriveBreadth, PlayerUsageRecord, UsageWeek } from "../src/data/contracts";
import { BREADTH_LABELS, breadthReading, formatBreadth } from "../src/data/signals";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles, usageRecords } from "./fixtures/artifacts";
import { required } from "./required";
import { stubSite } from "./site";

function week(number: number, status: UsageWeek["status"]): UsageWeek {
  return {
    week: number,
    status,
    team: status === "bye" ? null : "DET",
    opponent: null,
    snap_share: null,
    target_share: null,
    carry_share: null,
    air_yards_share: null,
    targets: null,
    carries: null,
    pass_attempts: null,
    fantasy_points: null,
  };
}

const RECORD = {
  ...required(usageRecords()[0], "a usage record"),
  position: "RB",
  weeks: [week(1, "played"), week(2, "played"), week(3, "bye"), week(4, "played"), week(5, "played")],
} as PlayerUsageRecord;

/** A back in a series rotation: short of the random notch every week. */
const BLOCK: DriveBreadth = {
  method_version: "drive_breadth_v2",
  metric: "backfield",
  window_rule: 4,
  appearances: 4,
  first_week: 1,
  last_week: 5,
  eligible_drives: 36,
  reached_drives: 21,
  expected_drives: 29.3,
  opportunities: 54,
  breadth_gap_pp: -23.1,
  displayable: true,
  withheld_reason: null,
  compares_with_random: true,
  weeks: [
    { week: 1, eligible_drives: 10, reached_drives: 7, drive_share: 0.7, expected_share: 0.92 },
    { week: 2, eligible_drives: 9, reached_drives: 4, drive_share: 0.444, expected_share: 0.6 },
    { week: 4, eligible_drives: 8, reached_drives: 5, drive_share: 0.625, expected_share: 0.85 },
    // Week 5 was played; its play-by-play is the latest game and reads 5 of 9.
    { week: 5, eligible_drives: 9, reached_drives: 5, drive_share: 0.556, expected_share: 0.77 },
  ],
  change: { latest_week: 5, latest: 0.556, earlier: 0.593, earlier_games: 3, change: -0.037 },
};

describe("the drive rail reading", () => {
  it("is a rail: one bar per week on the record's axis, absences kept, the latest marked", () => {
    const reading = breadthReading(RECORD, BLOCK);
    expect(reading.bars.map((bar) => [bar.week, bar.status, bar.value, bar.latest])).toEqual([
      [1, "played", 0.7, false],
      [2, "played", 0.444, false],
      [3, "bye", null, false],
      [4, "played", 0.625, false],
      [5, "played", 0.556, true],
    ]);
    expect(reading.expected.get(1)).toBe(0.92);
    expect(reading.expected.has(3)).toBe(false);
  });

  it("states the latest share and its change in the share rails' own words", () => {
    const reading = breadthReading(RECORD, BLOCK);
    expect(reading.label).toBe("Drives with a touch");
    expect(reading.question).toBe("Every series, or a rotation?");
    expect(reading.valueText).toBe("56%");
    expect(reading.changeText).toBe("−4 pts");
    expect(reading.direction).toBe("down");
    expect(reading.window).toBe("from 59% · week 5 vs 3 earlier games");
    expect(reading.vsRandom).toBe("wks 1–5: −23 pts vs random");
    expect(reading.sentence).toContain("he had a carry or target on 5 of 9 drives on which a back got the ball");
    expect(reading.sentence).toContain("23 points more bunched than random");
    expect(reading.sentence).toContain("not a forecast");
    expect(reading.sentence).not.toMatch(/\b(trust|safe|script|scheme|coach|predicts?)\b/i);
  });

  it("says level rather than a signed zero, and uses a real minus sign", () => {
    expect(formatBreadth(0.4)).toBe("level");
    expect(formatBreadth(-9.2)).toBe("−9 pts");
    expect(formatBreadth(12.5)).toBe("+13 pts");
  });

  it("keeps the bars when the four-game comparison is withheld, and says which count is short", () => {
    const reading = breadthReading(RECORD, {
      ...BLOCK,
      opportunities: 5,
      displayable: false,
      withheld_reason: "too_few_opportunities",
      breadth_gap_pp: 0.4,
    });
    expect(reading.gap).toBeNull();
    expect(reading.valueText).toBe("56%");
    expect(reading.vsRandom).toBe("vs random: too few carries and targets (5)");
    expect(reading.expected.size).toBe(4);
  });

  it("draws a quarterback's designed-run drives with no comparison to random at all", () => {
    // ADR-104: the QB variant failed the publication rule, so the build says not to compare.
    const reading = breadthReading(
      { ...RECORD, position: "QB" },
      { ...BLOCK, metric: "designed_runs", compares_with_random: false },
    );
    expect(reading.label).toBe("Designed-run drives");
    expect(reading.valueText).toBe("56%");
    expect(reading.expected.size).toBe(0);
    expect(reading.vsRandom).toBeNull();
    expect(reading.gap).toBeNull();
    expect(reading.sentence).not.toContain("random");
  });

  it("reads a latest game without play-by-play as no value, never an older game", () => {
    const reading = breadthReading(RECORD, {
      ...BLOCK,
      weeks: BLOCK.weeks.filter((entry) => entry.week !== 5),
      change: null,
    });
    expect(reading.bars.at(-1)).toMatchObject({ week: 5, status: "played", value: null });
    expect(reading.valueText).toBe("—");
    expect(reading.window).toBe("no drive count for his latest game");
  });

  it("names each position's variant as a question about that position", () => {
    expect(BREADTH_LABELS.designed_runs.label).toBe("Designed-run drives");
    expect(BREADTH_LABELS.designed_runs.question).toBe("Are runs called for him?");
    expect(BREADTH_LABELS.backfield.question).toMatch(/series/);
    expect(BREADTH_LABELS.targets.label).toBe("Drives targeted");
    expect(BREADTH_LABELS.open_field_targets.question).toMatch(/20s/);
  });
});

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

describe("the card's drive rail, against the published bytes", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true) });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("draws the artifact's bars, notches and numbers in the rails' own markup", async () => {
    const record = required(
      usageRecords().find((row) => row.position === "WR" && row.drive_breadth?.displayable === true),
      "a WR with a displayable reading",
    );
    const block = required(record.drive_breadth, "his block");
    window.history.replaceState(null, "", "/?view=ros&scoring=ppr&teams=12");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Rest of season/ })).toBeDefined();
    });
    await userEvent.setup().click(
      required(screen.getAllByRole("button", { name: record.display_name })[0], "his row"),
    );
    const dialog = await waitFor(() => screen.getByRole("dialog"));
    const row = required(
      dialog.querySelector('.usage-rail[data-metric="drive_breadth"]'),
      "the drive rail",
    ) as HTMLElement;
    const expected = breadthReading(record, block);
    // The same structure as every other rail: bars on the week axis, the reading beside them.
    const bars = row.querySelectorAll(".usage-bars > .usage-bar");
    expect(bars.length).toBe(record.weeks.length);
    expect(row.querySelectorAll(".usage-bar-notch").length).toBe(
      block.weeks.filter((entry) => entry.expected_share !== null).length,
    );
    expect(row.querySelector(".breadth-scale")).toBeNull();
    expect(row.querySelector(".usage-rail-value")?.textContent).toBe(expected.valueText);
    expect(row.querySelector(".usage-rail-window")?.textContent).toBe(expected.window);
    expect(row.querySelector(".usage-rail-note")?.textContent).toBe(expected.vsRandom);
    expect(row.textContent).toContain("Drives targeted");
    expect(expected.vsRandom).toContain(formatBreadth(required(block.breadth_gap_pp, "a gap")));
    // Ordered after the role rails, before the points rail.
    const metrics = [...dialog.querySelectorAll(".usage-rail")].map((rail) => rail.getAttribute("data-metric"));
    expect(metrics.slice(-2)).toEqual(["drive_breadth", "fantasy_points"]);
  });
});
