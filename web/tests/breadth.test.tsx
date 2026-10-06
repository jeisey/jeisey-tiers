/**
 * The drive-breadth row (ADR-103): its words, its withheld state, and the rendered card
 * against the published bytes. Nothing on the card recomputes a count.
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import type { DriveBreadth } from "../src/data/contracts";
import { BREADTH_LABELS, breadthReading, formatBreadth } from "../src/data/signals";
import {
  FIXTURE_GENERATED_AT,
  fixtureBreadthReference,
  fixtureFiles,
  inSeasonFixtureFiles,
  usageRecords,
} from "./fixtures/artifacts";
import { required } from "./required";
import { stubSite } from "./site";

const BLOCK: DriveBreadth = {
  method_version: "drive_breadth_v1",
  metric: "targets",
  window_rule: 4,
  appearances: 4,
  first_week: 5,
  last_week: 8,
  eligible_drives: 40,
  reached_drives: 30,
  expected_drives: 25.0,
  opportunities: 36,
  breadth_gap_pp: 12.5,
  displayable: true,
  withheld_reason: null,
};

describe("the breadth reading", () => {
  it("prints the published gap with its denominator, window and the position's median", () => {
    const reading = breadthReading(BLOCK, { players: 9, p25: -2, p50: 0.4, p75: 2 }, "WR");
    expect(reading.valueText).toBe("+12.5 pp");
    expect(reading.window).toBe("30 of 40 drives · wks 5–8 · WR median +0.4 pp");
    expect(reading.sentence).toContain("reached 30 of 40 team drives");
    expect(reading.sentence).toContain("about 25.0");
    expect(reading.sentence).toContain("not a forecast");
  });

  it("uses a real minus sign and says bunched, never better or worse", () => {
    const reading = breadthReading({ ...BLOCK, reached_drives: 20, breadth_gap_pp: -12.5 }, null, "WR");
    expect(reading.valueText).toBe("−12.5 pp");
    expect(reading.sentence).toContain("more bunched");
    expect(reading.sentence).toContain("neither sign is better");
    expect(reading.sentence).not.toMatch(/\b(trust|safe|script|scheme|coach|predicts?)\b/i);
    expect(formatBreadth(0.04)).toBe("0.0 pp");
  });

  it("withholds below the minimums instead of showing a zero that reads as average", () => {
    const reading = breadthReading(
      { ...BLOCK, opportunities: 5, displayable: false, withheld_reason: "too_few_opportunities", breadth_gap_pp: 3.1 },
      null,
      "WR",
    );
    expect(reading.value).toBeNull();
    expect(reading.valueText).toBe("—");
    expect(reading.window).toBe("too few for a reading: fewer than 6 targets (5)");
    expect(reading.sentence).toContain("not the same as average");
  });

  it("names each position's variant in its own terms", () => {
    expect(BREADTH_LABELS.rushing.label).toBe("Rushing breadth");
    expect(BREADTH_LABELS.backfield.question).toMatch(/series/);
    expect(BREADTH_LABELS.open_field_targets.noun).toBe("targets outside the red zone");
  });
});

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

describe("the card's breadth row, against the published bytes", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true) });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("draws exactly the artifact's number and counts", async () => {
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
      "the breadth row",
    ) as HTMLElement;
    const reference = fixtureBreadthReference()?.WR ?? null;
    const expected = breadthReading(block, reference, "WR");
    expect(within(row).getByText(expected.valueText)).toBeDefined();
    expect(row.textContent).toContain(`${String(block.reached_drives)} of ${String(block.eligible_drives)} drives`);
    expect(row.textContent).toContain("Target breadth");
    expect(formatBreadth(required(block.breadth_gap_pp, "a gap"))).toBe(expected.valueText);
  });
});
