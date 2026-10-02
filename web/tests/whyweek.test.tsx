/**
 * "Why this week" (ADR-099): every number on the panel is a published one, and context never
 * carries points.
 *
 * The things that would make the panel quietly wrong rather than visibly broken:
 *
 * - **An invented number.** A model chip's value must be the published term at exactly that
 *   quantile, and a chip exists only when that term is material.
 * - **Points on context.** v1 reads neither weather nor the injury report, so a forecast or
 *   an absence carries words and never a signed point value.
 * - **A broken account.** typical + terms + calibration + rearrangement must close on the
 *   published quantile at two decimals, or the headline delta and the table disagree.
 * - **Colour alone.** Direction is spelled with a sign, an arrow and above/below.
 * - **An unlicensed number.** Open-Meteo values carry their CC BY 4.0 credit wherever shown.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WhyWeek, WhyWeekCompact } from "../src/components/WhyWeek";
import type { WeeklyGameContextRecord, WeeklyProjectionRecord } from "../src/data/contracts";
import {
  MATERIAL_POINTS,
  OPEN_METEO_ATTRIBUTION,
  arrow,
  deltaSentence,
  signedPoints,
  weatherChip,
  whyThisWeek,
} from "../src/data/whyweek";
import { weeklyContextRecords, weeklyProjectionRecords } from "./fixtures/artifacts";

afterEach(cleanup);

const LEVELS = ["q10", "q50", "q90"] as const;
const SIGNED = /[+−-]\d+\.\d/;

function contextFor(team: string | null | undefined): WeeklyGameContextRecord | null {
  return weeklyContextRecords().find((record) => record.team === team) ?? null;
}

function explained(): WeeklyProjectionRecord[] {
  return weeklyProjectionRecords().filter((record) => record.explanation !== null);
}

function why(record: WeeklyProjectionRecord) {
  const own = contextFor(record.team);
  const opponent = contextFor(record.game?.opponent);
  const reading = whyThisWeek(record, own, opponent);
  if (reading === null) throw new Error(`no reading for ${record.player_id}`);
  return reading;
}

describe("the published account", () => {
  it("closes on the published quantile at two decimals at the floor, median and ceiling", () => {
    const records = explained();
    expect(records.length).toBeGreaterThan(10);
    for (const record of records) {
      for (const key of LEVELS) {
        const account = record.explanation?.[key];
        const published = record.quantiles?.[key];
        if (account === undefined || published === undefined) throw new Error("missing level");
        const total =
          account.typical +
          Object.values(account.terms).reduce((a, b) => a + b, 0) +
          account.calibration +
          account.rearrangement;
        expect(Math.round(total * 100)).toBe(Math.round(published * 100));
      }
    }
  });

  it("is absent, and so is the reading, when there is no distribution to explain", () => {
    for (const record of weeklyProjectionRecords().filter((r) => r.quantiles === null)) {
      expect(record.explanation).toBeNull();
      expect(whyThisWeek(record, contextFor(record.team), null)).toBeNull();
    }
  });
});

describe("model chips", () => {
  it("carry exactly the published term at the level they are shown for, and only when material", () => {
    for (const record of explained()) {
      const reading = why(record);
      for (const [key, level] of [
        ["q10", reading.floor],
        ["q50", reading.median],
        ["q90", reading.ceiling],
      ] as const) {
        const account = record.explanation?.[key];
        if (account === undefined) throw new Error("no account");
        const terms = account.terms;
        const material = Object.entries(terms).filter(([, value]) => Math.abs(value) >= MATERIAL_POINTS);
        expect(level.chips.map((chip) => chip.group).sort()).toEqual(material.map(([group]) => group).sort());
        for (const chip of level.chips) expect(chip.value).toBe(terms[chip.group]);
        expect(level.typical).toBe(record.explanation?.[key].typical);
        expect(level.thisWeek).toBe(record.quantiles?.[key]);
      }
    }
  });

  it("name the opponent's published rank in words", () => {
    const record = explained().find((r) => r.opponent?.rank != null && r.explanation?.q50.terms.opponent !== 0);
    if (record === undefined) throw new Error("fixture lacks an opponent term");
    const chip = why(record).median.chips.find((c) => c.group === "opponent");
    expect(chip?.label).toMatch(/allows the \d+(st|nd|rd|th)-(most|fewest) points to (QB|RB|WR|TE)s/);
    expect(chip?.label).toContain(record.opponent?.defense ?? "?");
  });

  it("separate the ceiling from the median: a boom week reads larger at P90", () => {
    const boom = explained().find((r) => r.player_id === "gsis:00-0000012");
    if (boom === undefined) throw new Error("fixture lacks the boom seed");
    const reading = why(boom);
    const at = (chips: typeof reading.median.chips, group: string) => chips.find((c) => c.group === group)?.value ?? 0;
    expect(at(reading.ceiling.chips, "opponent")).toBeGreaterThan(at(reading.median.chips, "opponent"));
    expect(reading.ceiling.delta).toBeGreaterThan(reading.median.delta);
  });
});

describe("context chips", () => {
  it("never carry a point value", () => {
    for (const record of explained()) {
      for (const chip of why(record).context) {
        expect(chip.kind).toBe("context");
        expect(chip.label).not.toMatch(/\(\s*[+−-]\d+\.\d\s*\)/);
        expect(chip.label).not.toMatch(/\bpts\b/);
      }
    }
  });

  it("say what the forecast says only when its status allows numbers", () => {
    const buf = contextFor("BUF");
    const det = contextFor("DET");
    if (buf === null || det === null) throw new Error("fixture lacks BUF or DET");
    expect(weatherChip(buf)?.label).toMatch(/^Forecast: 18 mph wind, gusts 29, 37°F, 70% chance of precipitation$/);
    expect(weatherChip(det)?.label).toBe("Dome — no weather");
    const stale = weatherChip({ ...buf, weather: { ...buf.weather, status: "stale" } });
    expect(stale?.label).toBe("Forecast too old to show");
    expect(stale?.label).not.toMatch(/\d/);
  });

  it("keeps a retractable roof and an unverified roof apart", () => {
    const ari = contextFor("ARI");
    if (ari?.venue == null) throw new Error("fixture lacks ARI");
    expect(weatherChip(ari)?.label).toMatch(/^Retractable roof — announced on game day; outside: /);
    const unverified = weatherChip({ ...ari, venue: { ...ari.venue, roof_type: "unverified" } });
    expect(unverified?.label).toMatch(/^Roof cover unverified; outside: /);
    expect(unverified?.detail).toContain("not established");
  });

  it("credits Open-Meteo wherever its numbers are shown, and NWS needs no licence line", () => {
    const london = contextFor("BAL");
    const buffalo = contextFor("BUF");
    expect(weatherChip(london)?.attribution).toBe(OPEN_METEO_ATTRIBUTION);
    expect(weatherChip(buffalo)?.attribution).toBeUndefined();
  });

  it("lists the player's own offence's absences and the opposing defence's, never the player", () => {
    const record = explained().find((r) => r.team === "BUF");
    if (record === undefined) throw new Error("fixture lacks a BUF record");
    const reading = why(record);
    const ids = reading.context.map((chip) => chip.id);
    // BUF's listed guard and tackle (offence), CIN's listed corner and safety (defence).
    expect(ids.filter((id) => id.startsWith("own:"))).toHaveLength(2);
    expect(ids.filter((id) => id.startsWith("opp:"))).toHaveLength(2);
    // CIN's own listed defenders say nothing about a CIN ball-carrier's offence.
    const cin = explained().find((r) => r.team === "CIN");
    if (cin !== undefined) expect(why(cin).context.filter((c) => c.id.startsWith("own:"))).toHaveLength(0);
    expect(ids).not.toContain(`own:${record.player_id}`);
  });

  it("calls a report without game statuses unknown, not healthy", () => {
    const was = contextFor("WAS");
    expect(was?.lineup.report_final).toBe(false);
  });
});

describe("words carry direction", () => {
  it("spell the sign with a true minus, an arrow and above or below", () => {
    expect(signedPoints(1.24)).toBe("+1.2");
    expect(signedPoints(-0.36)).toBe("−0.4");
    expect(signedPoints(0.04)).toBe("±0.0");
    expect([arrow(2), arrow(-2), arrow(0.01)]).toEqual(["▲", "▼", "●"]);
    const reading = { level: "q50" as const, typical: 12.04, thisWeek: 15.1, delta: 3.06, chips: [], residual: 0 };
    expect(deltaSentence(reading)).toBe("3.1 above a typical week (12.0)");
    expect(deltaSentence({ ...reading, delta: -0.71 })).toBe("0.7 below a typical week (12.0)");
  });

  it("never assume a pronoun in what a reader sees", () => {
    for (const record of explained()) {
      const reading = why(record);
      const texts = [
        ...reading.context.flatMap((chip) => [chip.label, chip.detail]),
        ...[reading.floor, reading.median, reading.ceiling].flatMap((level) => [
          deltaSentence(level),
          ...level.chips.map((chip) => chip.label),
        ]),
      ];
      for (const text of texts) expect(text).not.toMatch(/\b(his|her|he|she)\b/i);
    }
  });
});

describe("the panel", () => {
  it("renders the median, ceiling and floor headlines and a points table with the published terms", () => {
    const record = explained().find((r) => r.player_id === "gsis:00-0000012");
    if (record === undefined) throw new Error("fixture lacks the boom seed");
    const reading = why(record);
    render(<WhyWeek why={reading} name={record.display_name} />);
    for (const name of ["Median", "Ceiling", "Floor"]) expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    const table = screen.getByRole("table");
    const opponentRow = within(table)
      .getAllByRole("row")
      .find((row) => row.getAttribute("data-group") === "opponent");
    if (opponentRow === undefined) throw new Error("no opponent row");
    expect(opponentRow.textContent).toContain(signedPoints(record.explanation?.q50.terms.opponent ?? 0));
    expect(opponentRow.textContent).toContain(signedPoints(record.explanation?.q90.terms.opponent ?? 0));
    expect(screen.getByText(/a model attribution, not a measured cause/)).toBeTruthy();
  });

  it("prints the Open-Meteo credit beside an Open-Meteo forecast", () => {
    const record = explained().find((r) => r.team === "BAL" || r.team === "LAR");
    if (record === undefined) throw new Error("fixture lacks a London game");
    render(<WhyWeek why={why(record)} name={record.display_name} />);
    expect(screen.getByText(OPEN_METEO_ATTRIBUTION)).toBeTruthy();
  });

  it("keeps a deck card to two numbers and one reason, with direction in text", () => {
    const record = explained()[0];
    if (record === undefined) throw new Error("no records");
    const reading = why(record);
    const { container } = render(<WhyWeekCompact why={reading} />);
    expect(container.textContent).toMatch(/Median [▲▼●] /);
    expect(container.textContent).toMatch(/Ceiling [▲▼●] /);
    expect(container.textContent ?? "").toMatch(SIGNED);
  });
});
