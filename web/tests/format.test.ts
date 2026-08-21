/**
 * Formatting.
 *
 * One module produces every number the UI shows, so these tests pin the shapes a reader
 * depends on: ranks are whole, values carry one decimal, a sign is explicit, and a missing
 * value renders as an em dash rather than as a zero.
 */

import { describe, expect, it } from "vitest";

import {
  EM_DASH,
  easternIsoDate,
  formatAdp,
  formatAge,
  formatEastern,
  formatEasternDate,
  formatInteger,
  formatRange,
  formatRank,
  formatScore,
  formatSigned,
  formatValue,
} from "../src/data/format";

describe("numeric formatting", () => {
  it("renders ranks as integers", () => {
    expect(formatRank(12)).toBe("12");
    expect(formatRank(12.6)).toBe("13");
  });

  it("renders ADP with one decimal", () => {
    expect(formatAdp(10.512)).toBe("10.5");
    expect(formatAdp(2)).toBe("2.0");
  });

  it("renders VORP and points with one decimal", () => {
    expect(formatValue(135.4197)).toBe("135.4");
    expect(formatScore(99.79)).toBe("99.8");
  });

  it("renders a signed gap with an explicit sign", () => {
    expect(formatSigned(8.51)).toBe("+8.5");
    expect(formatSigned(-30.14)).toBe("−30.1");
    expect(formatSigned(0)).toBe("0.0");
  });

  it("renders a compact range", () => {
    expect(formatRange(53.81, 209.68)).toBe("53.8 – 209.7");
  });

  it("renders a thousands separator on counts", () => {
    expect(formatInteger(12240)).toBe("12,240");
  });

  it.each([
    [null],
    [undefined],
    [Number.NaN],
    [Number.POSITIVE_INFINITY],
  ])("renders %s as an em dash, never a zero", (value) => {
    expect(formatValue(value)).toBe(EM_DASH);
    expect(formatRank(value)).toBe(EM_DASH);
    expect(formatSigned(value)).toBe(EM_DASH);
    expect(formatInteger(value)).toBe(EM_DASH);
  });

  it("renders a half-open range as an em dash rather than half a range", () => {
    expect(formatRange(3, null)).toBe(EM_DASH);
    expect(formatRange(null, 9)).toBe(EM_DASH);
  });
});

describe("time formatting", () => {
  it("renders the build stamp in Eastern, not the viewer's zone", () => {
    // 2026-08-21T14:38:00Z is 10:38 in America/New_York (EDT, UTC-4).
    expect(formatEastern("2026-08-21T14:38:00Z")).toBe("Aug 21 · 10:38 AM ET");
  });

  it("renders an Eastern calendar date", () => {
    expect(formatEasternDate("2026-08-21T14:38:00Z")).toBe("Aug 21, 2026");
  });

  it("derives an export date from the build stamp, in Eastern", () => {
    expect(easternIsoDate("2026-08-21T14:38:00Z")).toBe("2026-08-21");
    // 03:30 UTC is still the previous evening in Eastern; the filename must say so.
    expect(easternIsoDate("2026-08-21T03:30:00Z")).toBe("2026-08-20");
  });

  it("refuses to guess at an unparseable timestamp", () => {
    expect(formatEastern("not a time")).toBe(EM_DASH);
    expect(formatEastern(null)).toBe(EM_DASH);
    expect(easternIsoDate(null)).toBe("unknown-date");
  });

  it("describes age in words", () => {
    expect(formatAge(0.4)).toBe("less than an hour ago");
    expect(formatAge(1)).toBe("1 hour ago");
    expect(formatAge(5.2)).toBe("5 hours ago");
    expect(formatAge(30)).toBe("1 day ago");
    expect(formatAge(80)).toBe("3 days ago");
  });
});
