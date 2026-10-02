/**
 * URL state.
 *
 * Two properties matter and both are load-bearing for a shareable board: an unsupported value
 * must normalize rather than throw, and two identical UI states must serialize to identical
 * strings so links are comparable (`docs/UX_SPEC.md` sections 3 and 10).
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_STATE,
  IN_SEASON_VIEWS,
  leaguePresetId,
  parseState,
  resolveMode,
  resolveView,
  serializeState,
  stateHref,
} from "../src/data/state";

describe("parseState", () => {
  it("returns the defaults for an empty query", () => {
    const parsed = parseState("");
    expect(parsed.state).toEqual(DEFAULT_STATE);
    expect(parsed.normalized).toBe(true);
  });

  it("defaults to the PPR twelve-team board, following the season for which board", () => {
    // `auto` rather than `tiers`: one URL has to be correct in both modes, so the default
    // view follows the schedule-derived season state and any explicit view still wins.
    expect(DEFAULT_STATE.view).toBe("auto");
    expect(DEFAULT_STATE.mode).toBe("auto");
    expect(DEFAULT_STATE.scoring).toBe("ppr");
    expect(DEFAULT_STATE.teams).toBe(12);
    expect(DEFAULT_STATE.position).toBe("all");
    expect(DEFAULT_STATE.opportunity).toBe("value");
  });

  it("resolves auto to each mode's own first board, and honours an explicit view", () => {
    expect(resolveView("auto", "draft")).toBe("tiers");
    expect(resolveView("auto", "in_season")).toBe("ros");
    // A named view is reachable from either mode: the other mode's boards are not forbidden.
    expect(resolveView("arbitrage", "in_season")).toBe("arbitrage");
    expect(resolveView("ros", "draft")).toBe("ros");
  });

  it("resolves the mode from the build's season state unless the reader overrode it", () => {
    expect(resolveMode("auto", null)).toBe("draft");
    expect(resolveMode("auto", "in_season")).toBe("in_season");
    expect(resolveMode("draft", "in_season")).toBe("draft");
    expect(resolveMode("in_season", "draft")).toBe("in_season");
  });

  it("reads every supported parameter", () => {
    const parsed = parseState(
      "?view=arbitrage&scoring=half&teams=14&position=rb&search=achane&rail=all&only=role.surfaced&set=3&duel=00-0036389.00-0039164&margin=-12" +
        "&give=00-0000001.00-0000013&goal=ceiling&get=2&range=35&comp=rb.wr&keep=00-0000002.00-0000011&shown=0.1.6.3.4&dealt=7&stamp=0a1b2c3d&ret=1&unavail=1",
    );
    expect(parsed.state).toEqual({
      view: "arbitrage",
      market: "fantasyfootballcalculator_adp",
      scoring: "half",
      teams: 14,
      tiers: null,
      position: "rb",
      search: "achane",
      board: "top",
      rail: "all",
      mode: "auto",
      opportunity: "value",
      only: ["role", "surfaced"],
      set: 3,
      duel: ["gsis:00-0036389", "gsis:00-0039164"],
      margin: -12,
      give: ["gsis:00-0000001", "gsis:00-0000013"],
      goal: "ceiling",
      get: 2,
      range: 35,
      comp: ["rb", "wr"],
      keep: [["gsis:00-0000002", "gsis:00-0000011"]],
      shown: [0, 1, 6, 3, 4],
      dealt: 7,
      stamp: "0a1b2c3d",
      returning: true,
      unavailable: true,
    });
    expect(parsed.normalized).toBe(true);
  });

  it("reads the availability flags only as `1`, and omits them when off (ADR-101)", () => {
    expect(parseState("?ret=yes").normalized).toBe(false);
    expect(parseState("?ret=yes").state.returning).toBe(false);
    expect(serializeState({ ...DEFAULT_STATE, returning: true })).toBe("?ret=1");
    expect(serializeState({ ...DEFAULT_STATE, unavailable: true })).toBe("?unavail=1");
    expect(serializeState(DEFAULT_STATE)).toBe("");
  });

  it("reads the season-mode override and the opportunity ordering", () => {
    const parsed = parseState("?mode=in_season&opportunity=net&view=opportunity");
    expect(parsed.state.mode).toBe("in_season");
    expect(parsed.state.opportunity).toBe("net");
    expect(parsed.state.view).toBe("opportunity");
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
    ["?mode=whenever", "mode"],
    ["?opportunity=vibes", "opportunity"],
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
 * The Opportunity Board's orderings and filters in the URL (ADR-092).
 *
 * The filters are a *set* written as a string, so the string has to be canonical: two links
 * naming the same filters must compare equal, and a token the app does not know must be
 * dropped with a rewrite rather than kept as a silent no-op.
 */
describe("opportunity orderings and filters", () => {
  it("reads the two new orderings", () => {
    expect(parseState("?opportunity=momentum").state.opportunity).toBe("momentum");
    expect(parseState("?opportunity=role").state.opportunity).toBe("role");
    expect(parseState("?opportunity=role").normalized).toBe(true);
  });

  it("offers no blended ordering under any name", () => {
    for (const name of ["score", "signal", "waiver", "breakout", "composite", "hot"]) {
      const parsed = parseState(`?opportunity=${name}`);
      expect(parsed.state.opportunity).toBe("value");
      expect(parsed.normalized).toBe(false);
    }
  });

  it("writes filters in canonical order, whatever order they were switched on", () => {
    expect(serializeState({ ...DEFAULT_STATE, only: ["surfaced", "role"] })).toBe(
      "?only=role.surfaced",
    );
    expect(serializeState({ ...DEFAULT_STATE, only: ["momentum", "role", "momentum"] })).toBe(
      "?only=role.momentum",
    );
  });

  it("omits the parameter when no filter is on", () => {
    expect(serializeState({ ...DEFAULT_STATE, only: [] })).toBe("");
  });

  it("round-trips every filter", () => {
    const state = { ...DEFAULT_STATE, only: ["role", "momentum", "surfaced"] as const };
    expect(parseState(serializeState(state)).state).toEqual(state);
  });

  it("normalizes an out-of-order or duplicated list and drops an unknown token", () => {
    const reordered = parseState("?only=surfaced.role");
    expect(reordered.state.only).toEqual(["role", "surfaced"]);
    expect(reordered.normalized).toBe(false);

    const unknown = parseState("?only=role.hot");
    expect(unknown.state.only).toEqual(["role"]);
    expect(unknown.normalized).toBe(false);
    expect(serializeState(unknown.state)).toBe("?only=role");
  });

  it("has no filter that counts agreeing signals", () => {
    const parsed = parseState("?only=two_of_three.all_positive.strong");
    expect(parsed.state.only).toEqual([]);
    expect(parsed.normalized).toBe(false);
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

describe("trade state (ADR-100 §8)", () => {
  it("defaults are omitted, so the empty Trade tab is a short link", () => {
    expect(serializeState({ ...DEFAULT_STATE, view: "trade" })).toBe("?view=trade");
    expect(DEFAULT_STATE.goal).toBe("value");
    expect(DEFAULT_STATE.get).toBe(1);
    expect(DEFAULT_STATE.range).toBe(20);
  });

  it("round-trips every trade parameter in a fixed order", () => {
    const state = {
      ...DEFAULT_STATE,
      view: "trade" as const,
      give: ["gsis:00-0000001", "gsis:00-0000013"],
      goal: "floor" as const,
      get: 3 as const,
      range: 50 as const,
      comp: ["rb", "wr", "any"] as const,
      keep: [["gsis:00-0000002", "gsis:00-0000011", "gsis:00-0000015"]],
      shown: [0, 5, 2],
      dealt: 6,
      stamp: "deadbeef",
    };
    const query = serializeState(state);
    expect(query).toBe(
      "?view=trade&give=00-0000001.00-0000013&goal=floor&get=3&range=50&comp=rb.wr.any&keep=00-0000002.00-0000011.00-0000015&shown=0.5.2&dealt=6&stamp=deadbeef",
    );
    const parsed = parseState(query);
    expect(parsed.state).toEqual(state);
    expect(parsed.normalized).toBe(true);
  });

  it("keeps the reader's outgoing order but drops malformed, repeated and excess ids", () => {
    const parsed = parseState("?give=00-0000013.bogus.00-0000013.00-0000001.00-0000002.00-0000003");
    expect(parsed.state.give).toEqual(["gsis:00-0000013", "gsis:00-0000001", "gsis:00-0000002"]);
    expect(parsed.normalized).toBe(false);
  });

  it.each([
    ["?goal=moon", { goal: "value" }],
    ["?get=4", { get: 1 }],
    ["?get=2.0", { get: 1 }],
    ["?range=25", { range: 20 }],
    ["?shown=1.1", { shown: [] }],
    ["?shown=1.2.3.4.5.6", { shown: [] }],
    ["?shown=-1", { shown: [] }],
    ["?dealt=x", { dealt: 0 }],
    ["?stamp=XYZ", { stamp: "" }],
  ])("normalizes %s", (query, expected) => {
    const parsed = parseState(query);
    expect(parsed.state).toMatchObject(expected);
    expect(parsed.normalized).toBe(false);
  });

  it("puts a composition in canonical order and drops one that does not fit the count", () => {
    expect(parseState("?get=2&comp=wr.rb").state.comp).toEqual(["rb", "wr"]);
    expect(parseState("?get=2&comp=wr.rb").normalized).toBe(false);
    expect(parseState("?get=2&comp=any.rb").state.comp).toEqual(["rb", "any"]);
    expect(parseState("?get=3&comp=rb.wr").state.comp).toEqual([]);
    expect(parseState("?get=2&comp=any.any").state.comp).toEqual([]);
    expect(parseState("?get=2&comp=rb.k").state.comp).toEqual([]);
  });

  it("canonicalizes kept packages: members sorted, duplicates and excess dropped", () => {
    const parsed = parseState(
      "?keep=00-0000011.00-0000002_00-0000002.00-0000011_00-0000005_00-0000006_00-0000007_junk",
    );
    expect(parsed.state.keep).toEqual([
      ["gsis:00-0000002", "gsis:00-0000011"],
      ["gsis:00-0000005"],
      ["gsis:00-0000006"],
    ]);
    expect(parsed.normalized).toBe(false);
  });

  it("keeps unrelated parameters beside the trade ones", () => {
    const parsed = parseState("?scoring=half&teams=10&duel=00-0036389&view=trade&give=00-0000001");
    expect(parsed.state).toMatchObject({ scoring: "half", teams: 10, duel: ["gsis:00-0036389"], give: ["gsis:00-0000001"] });
    expect(serializeState(parsed.state)).toBe("?view=trade&scoring=half&teams=10&duel=00-0036389&give=00-0000001");
  });

  it("trade is an in-season view", () => {
    expect(IN_SEASON_VIEWS).toContain("trade");
  });
});
