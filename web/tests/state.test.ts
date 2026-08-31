/**
 * URL state.
 *
 * Two properties matter and both are load-bearing for a shareable board: an unsupported value
 * must normalize rather than throw, and two identical UI states must serialize to identical
 * strings so links are comparable (`docs/UX_SPEC.md` sections 3 and 10).
 */

import { describe, expect, it } from "vitest";

import { DEFAULT_STATE, leaguePresetId, parseState, serializeState, stateHref } from "../src/data/state";

describe("parseState", () => {
  it("returns the defaults for an empty query", () => {
    const parsed = parseState("");
    expect(parsed.state).toEqual(DEFAULT_STATE);
    expect(parsed.normalized).toBe(true);
  });

  it("defaults to the PPR twelve-team tier board", () => {
    expect(DEFAULT_STATE.view).toBe("tiers");
    expect(DEFAULT_STATE.scoring).toBe("ppr");
    expect(DEFAULT_STATE.teams).toBe(12);
    expect(DEFAULT_STATE.position).toBe("all");
  });

  it("reads every supported parameter", () => {
    const parsed = parseState("?view=arbitrage&scoring=half&teams=14&position=rb&search=achane&rail=all");
    expect(parsed.state).toEqual({
      view: "arbitrage",
      scoring: "half",
      teams: 14,
      tiers: null,
      position: "rb",
      search: "achane",
      board: "top",
      rail: "all",
    });
    expect(parsed.normalized).toBe(true);
  });

  it("accepts case variation without treating it as invalid", () => {
    const parsed = parseState("?scoring=PPR&position=WR");
    expect(parsed.state.scoring).toBe("ppr");
    expect(parsed.state.position).toBe("wr");
    expect(parsed.normalized).toBe(true);
  });

  it.each([
    ["?view=nonsense", "view"],
    ["?scoring=superflex", "scoring"],
    ["?teams=11", "teams"],
    ["?teams=twelve", "teams"],
    ["?position=k", "position"],
    ["?rail=sideways", "rail"],
    ["?board=everything", "board"],
  ])("normalizes %s rather than crashing", (query) => {
    const parsed = parseState(query);
    expect(parsed.normalized).toBe(false);
    // Whatever was wrong, the resulting state is the default and is fully usable.
    expect(parsed.state).toEqual(DEFAULT_STATE);
  });

  it("flags an unknown parameter so the URL gets rewritten without it", () => {
    const parsed = parseState("?utm_source=twitter");
    expect(parsed.normalized).toBe(false);
    expect(serializeState(parsed.state)).toBe("");
  });

  it("trims and bounds a pathological search string", () => {
    const parsed = parseState(`?search=${encodeURIComponent(`  ${"a".repeat(200)}  `)}`);
    expect(parsed.state.search).toHaveLength(64);
  });
});

describe("serializeState", () => {
  it("omits defaults entirely", () => {
    expect(serializeState(DEFAULT_STATE)).toBe("");
  });

  it("writes parameters in a fixed order regardless of how the state was built", () => {
    const a = serializeState({ ...DEFAULT_STATE, position: "rb", view: "arbitrage", scoring: "std" });
    const b = serializeState({ ...DEFAULT_STATE, scoring: "std", view: "arbitrage", position: "rb" });
    expect(a).toBe(b);
    expect(a).toBe("?view=arbitrage&scoring=std&position=rb");
  });

  it("round-trips through parseState", () => {
    const state = { ...DEFAULT_STATE, view: "data" as const, teams: 10 as const, search: "burrow" };
    expect(parseState(serializeState(state)).state).toEqual(state);
  });

  it("drops an empty search rather than writing search=", () => {
    expect(serializeState({ ...DEFAULT_STATE, search: "" })).toBe("");
  });

  it("keeps the served path when building a link", () => {
    expect(stateHref({ ...DEFAULT_STATE, position: "te" }, "/jeisey-tiers/")).toBe(
      "/jeisey-tiers/?position=te",
    );
  });
});

describe("leaguePresetId", () => {
  it("maps a team count to the published preset id", () => {
    expect(leaguePresetId(10)).toBe("redraft-10");
    expect(leaguePresetId(12)).toBe("redraft-12");
    expect(leaguePresetId(14)).toBe("redraft-14");
  });
});

/**
 * Open tiers in the URL.
 *
 * The regression here is small and was real: an earlier draft required a *positive* tier
 * ordinal, which quietly dropped the first tier out of every shared link, because
 * `schemas/tier_record.schema.json` declares `tier_ordinal` with `minimum: 0` and the first
 * tier is 0. A bound taken from an assumption rather than from the contract.
 */
describe("open tier state", () => {
  it("round-trips the zero-based first tier", () => {
    const parsed = parseState("?tiers=0.1.2");
    expect(parsed.state.tiers).toEqual([0, 1, 2]);
    expect(parsed.normalized).toBe(true);
    expect(serializeState({ ...DEFAULT_STATE, tiers: [0, 1, 2] })).toBe("?tiers=0.1.2");
  });

  it("distinguishes 'every tier closed' from 'the board chooses'", () => {
    expect(parseState("?tiers=none").state.tiers).toEqual([]);
    expect(parseState("").state.tiers).toBeNull();
    expect(serializeState({ ...DEFAULT_STATE, tiers: [] })).toBe("?tiers=none");
    expect(serializeState({ ...DEFAULT_STATE, tiers: null })).toBe("");
  });

  it("sorts and deduplicates so one open set is one string", () => {
    expect(serializeState({ ...DEFAULT_STATE, tiers: [3, 0, 3, 1] })).toBe("?tiers=0.1.3");
  });

  it("normalizes an unsorted or duplicated list rather than trusting it", () => {
    const parsed = parseState("?tiers=2.0.2");
    expect(parsed.state.tiers).toEqual([0, 2]);
    expect(parsed.normalized).toBe(false);
  });

  it("rejects junk and falls back to letting the board choose", () => {
    const parsed = parseState("?tiers=abc");
    expect(parsed.state.tiers).toBeNull();
    expect(parsed.normalized).toBe(false);
  });

  it("bounds the list so a pathological URL cannot drive the board", () => {
    expect(parseState("?tiers=0.1.10000").state.tiers).toEqual([0, 1]);
  });
});
