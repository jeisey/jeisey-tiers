/**
 * ESPN roster/start readings on the Opportunity Board and the card (ADR-112), against the
 * fixture *artifacts*:
 *
 * | defect | the test that fails on it |
 * |---|---|
 * | a missing reading treated as 0% | "never lets an absent, invalid or stale reading pass a ceiling" |
 * | a boundary rounded across a ceiling | "applies strict ceilings at their exact boundaries" |
 * | an unavailable source emptying the board | "leaves the board whole when the build cannot apply it" |
 * | an unknown sorted between two readings | "sorts every row without a current reading last" |
 * | a relative-growth or ratio claim | "states changes in percentage points with their span" |
 * | ESPN moving Pick of the Week or any value | "changes no board value and no ordering it does not own" |
 */

import { describe, expect, it } from "vitest";

import { selectOpportunityCandidates, type OpportunityCandidate } from "../src/data/candidates";
import { espnCsvCells, opportunityRowsToCsv } from "../src/data/csv";
import {
  changeSentence,
  compareRostered,
  espnAvailability,
  espnCell,
  formatEspnPercent,
  formatPp,
  passesCeiling,
} from "../src/data/espn";
import { selectPotwBoard } from "../src/data/potw";
import { InSeasonBundle } from "../src/data/ros";
import { DEFAULT_STATE, type AppState } from "../src/data/state";
import {
  behaviorSeriesRecords,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  teamMatchupRecords,
  usageRecords,
} from "./fixtures/artifacts";
import { espnOwnershipMetadata, espnOwnershipRecords, type EspnFixtureMode } from "./fixtures/espn";
import { required } from "./required";

function bundle(mode: EspnFixtureMode = "present"): InSeasonBundle {
  const meta = espnOwnershipMetadata(mode);
  return new InSeasonBundle({
    metadata: rosBuildMetadata(meta === null ? {} : { espn_ownership: meta }),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(true),
    opportunityDegradation: null,
    behaviorSeries: behaviorSeriesRecords(),
    usage: usageRecords(),
    matchups: teamMatchupRecords(),
    espn: mode === "present" || mode === "stale" ? espnOwnershipRecords(mode) : null,
  });
}

function select(patch: Partial<AppState> = {}, source = bundle()) {
  return selectOpportunityCandidates(source, { ...DEFAULT_STATE, view: "opportunity", ...patch });
}

function names(rows: readonly OpportunityCandidate[]): string[] {
  return rows.map((row) => row.row.record.display_name);
}

function row(name: string, source = bundle()): OpportunityCandidate {
  return required(
    select({}, source).candidates.find((candidate) => candidate.row.record.display_name === name),
    name,
  );
}

describe("the readings", () => {
  it("truncates a board cell so it never contradicts a ceiling, and keeps 0% a reading", () => {
    expect(formatEspnPercent(9.99)).toBe("9.9%");
    expect(formatEspnPercent(10)).toBe("10%");
    expect(formatEspnPercent(74.99)).toBe("74%");
    expect(formatEspnPercent(50)).toBe("50%");
    expect(formatEspnPercent(0)).toBe("0%");
    expect(formatEspnPercent(null)).toBe("—");
  });

  it("states changes in percentage points with their span", () => {
    expect(formatPp(13.0)).toBe("+13.0 pp");
    expect(formatPp(-0.84)).toBe("−0.8 pp");
    expect(formatPp(0.02)).toBe("±0.0 pp");
    const riser = row("Jahmyr Cook");
    expect(riser.espn.kind).toBe("observed");
    if (riser.espn.kind !== "observed") return;
    const sentence = changeSentence(riser.espn.rostered, riser.espn.record.rostered_change_7d);
    expect(sentence).toBe("Rostered on ESPN: 18% → 31% in 7 days (+13 percentage points).");
    expect(sentence).not.toMatch(/%\s*(growth|increase)|times|ratio/i);
  });

  it("names every absence and never prints one as 0%", () => {
    const states = Object.fromEntries(
      select().candidates.map((candidate) => [candidate.row.record.display_name, candidate.espn.kind]),
    );
    expect(states["Deebo Gray"]).toBe("absent");
    expect(states["Derrick Hampton"]).toBe("absent");
    expect(states["Bijan Robinson (surfaced)"]).toBe("absent");
    for (const name of ["Deebo Gray", "Derrick Hampton", "Bijan Robinson (surfaced)"]) {
      const cell = espnCell(row(name).espn);
      expect(cell.rostered).not.toMatch(/^0/);
      expect(cell.sentence).not.toMatch(/(rostered in|started in) 0%/i);
    }
    // Roster-only: the start share is unknown, never zero.
    const rosterOnly = espnCell(row("Jaylin Lane").espn);
    expect(rosterOnly.started).toBe("not listed");
    // A real zero is a reading.
    expect(espnCell(row("Omarion Vance").espn).rostered).toBe("0%");
  });

  it("reads an older bundle as unpublished and an empty step as unavailable", () => {
    expect(espnAvailability(undefined, false).kind).toBe("unpublished");
    expect(espnAvailability(espnOwnershipMetadata("unavailable"), false).kind).toBe("unavailable");
    expect(espnAvailability(espnOwnershipMetadata("stale"), true).kind).toBe("stale");
    expect(espnAvailability(espnOwnershipMetadata("present"), true, false).kind).toBe("incompatible");
  });
});

describe("the ESPN roster ceiling", () => {
  it("applies strict ceilings at their exact boundaries", () => {
    const below10 = names(select({ espn: 10 }).candidates);
    expect(below10).toContain("James Cook III"); // 9.99%
    expect(below10).toContain("Omarion Vance"); // 0%
    expect(below10).not.toContain("Zay Meadows"); // exactly 10%
    expect(names(select({ espn: 25 }).candidates)).not.toContain("Jaylin Lane"); // exactly 25%
    expect(names(select({ espn: 50 }).candidates)).not.toContain("Zach Ertz"); // exactly 50%
    const below75 = names(select({ espn: 75 }).candidates);
    expect(below75).toContain("Trey McBride"); // 74.99%
    expect(below75).not.toContain("Kyle Pitts Sr."); // exactly 75%
  });

  it("never lets an absent, invalid or stale reading pass a ceiling, and counts them apart", () => {
    const selection = select({ espn: 75 });
    const shown = names(selection.candidates);
    for (const name of ["Deebo Gray", "Derrick Hampton", "Bijan Robinson (surfaced)"]) {
      expect(shown).not.toContain(name);
    }
    const report = required(selection.ceiling, "a ceiling report");
    expect(report.usable).toBe(true);
    expect(report.withoutReading).toBeGreaterThanOrEqual(3);
    expect(report.passing).toBe(selection.candidates.length);
    for (const candidate of select().candidates) {
      if (candidate.espn.kind !== "observed") expect(passesCeiling(candidate.espn, 75)).toBe(false);
    }
  });

  it("leaves the board whole when the build cannot apply it, and says why", () => {
    const whole = select().candidates.length;
    for (const mode of ["absent", "unavailable", "stale"] as const) {
      const selection = select({ espn: 25 }, bundle(mode));
      expect(selection.candidates.length).toBe(whole);
      const report = required(selection.ceiling, "a ceiling report");
      expect(report.usable).toBe(false);
      expect(report.reason).toMatch(/not applied/);
    }
  });

  it("composes with position, search and the role filter as one transparent AND", () => {
    const discovery = select({ only: ["role"], espn: 50 });
    const roleOnly = names(select({ only: ["role"] }).candidates);
    const ceilingOnly = names(select({ espn: 50 }).candidates);
    expect(names(discovery.candidates)).toEqual(roleOnly.filter((name) => ceilingOnly.includes(name)));
    expect(names(discovery.candidates)).toContain("Jalen Marsh");
    const qbs = names(select({ only: ["role"], espn: 50, position: "qb" }).candidates);
    expect(qbs).toEqual(["Jalen Marsh"]);
    // Supporting evidence is two separate counts in two units, never a combined score.
    expect(discovery.evidence.espnMeasured).toBeLessThanOrEqual(discovery.candidates.length);
    expect(discovery.evidence.sleeperMeasured).toBeLessThanOrEqual(discovery.candidates.length);
  });
});

describe("the orderings", () => {
  it("sorts by rostered share, highest first, with every row without a current reading last", () => {
    const ordered = select({ opportunity: "espn" }).candidates;
    const kinds = ordered.map((candidate) => candidate.espn.kind);
    const firstMissing = kinds.findIndex((kind) => kind !== "observed");
    expect(firstMissing).toBeGreaterThan(0);
    expect(kinds.slice(firstMissing).every((kind) => kind !== "observed")).toBe(true);
    const values = ordered.slice(0, firstMissing).map((candidate) =>
      candidate.espn.kind === "observed" ? candidate.espn.rostered : -1,
    );
    expect(values).toEqual([...values].sort((a, b) => b - a));
    // Deterministic on a tie: the board's own order (ROS rank, then id) decides.
    const again = select({ opportunity: "espn" }).candidates;
    expect(names(again)).toEqual(names(ordered));
    for (let index = 1; index < ordered.length; index += 1) {
      const previous = ordered[index - 1];
      const current = ordered[index];
      if (previous === undefined || current === undefined) continue;
      if (compareRostered(previous.espn, current.espn) === 0) {
        expect(previous.row.record.ros_fair_rank).toBeLessThanOrEqual(current.row.record.ros_fair_rank);
      }
    }
  });

  it("sorts by the 7-day change in points, measured first", () => {
    const ordered = select({ opportunity: "espn7" }).candidates;
    expect(ordered[0]?.row.record.display_name).toBe("Jahmyr Cook");
    const changes = ordered.map((candidate) =>
      candidate.espn.kind === "observed" && candidate.espn.record.rostered_change_7d.state === "measured"
        ? candidate.espn.record.rostered_change_7d.change_pp
        : null,
    );
    const firstNull = changes.indexOf(null);
    expect(changes.slice(firstNull).every((value) => value === null)).toBe(true);
  });
});

describe("the boundary with everything else", () => {
  it("changes no board value and no ordering it does not own", () => {
    const withEspn = select({ opportunity: "role" }, bundle("present"));
    const without = select({ opportunity: "role" }, bundle("absent"));
    expect(names(withEspn.candidates)).toEqual(names(without.candidates));
    expect(withEspn.candidates.map((c) => c.row.record)).toEqual(without.candidates.map((c) => c.row.record));
    const picks = (source: InSeasonBundle) => selectPotwBoard(source, { ...DEFAULT_STATE, view: "potw" });
    expect(JSON.stringify(picks(bundle("present")))).toBe(JSON.stringify(picks(bundle("absent"))));
  });

  it("exports the published fields, naming each absence", () => {
    const csv = opportunityRowsToCsv(select().candidates);
    expect(csv.split("\n")[0]).toContain("espn_percent_rostered");
    expect(espnCsvCells(row("Deebo Gray").espn)[0]).toBe("not_published");
    expect(espnCsvCells(row("Deebo Gray").espn)[1]).toBeNull();
    expect(espnCsvCells(row("Zach Ertz", bundle("absent")).espn)[0]).toBe("unavailable");
    const riser = espnCsvCells(row("Jahmyr Cook").espn);
    expect(riser.slice(0, 2)).toEqual(["observed", 31]);
    expect(riser[4]).toBe(13);
  });
});
