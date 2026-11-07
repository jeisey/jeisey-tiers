/**
 * Win My Matchup's readiness on a Friday (the 2026-11-06 failure): a Thursday game has kicked off
 * and the rest of the week has not. Built on records shaped like that build's — the Thursday
 * starters `kicked_off` with their lines and pregame quantiles, a bye, and every other game either
 * lined (a healthy build) or `lines_pending` (the outage, every upcoming total and spread null).
 *
 * What it holds in place:
 * * finals replace a completed starter's distribution exactly once, upcoming starters on both
 *   sides use their projections, and no final is ever taken for a game that has not kicked off;
 * * a starter the build gave no usable projection is a data gap with a cause code, never a
 *   reader's decision, and still blocks Simulate — no zero, mean, final or ROS stand-in;
 * * week, build, scenario, final and clock changes all change what is current: readings, the
 *   engine fingerprint, and which players a lineup change may move.
 */

import { describe, expect, it } from "vitest";

import { readAvailability, type Availability } from "../src/data/availability";
import type { Position, WeeklyProjectionRecord } from "../src/data/contracts";
import { retainedLinesNote } from "../src/data/format";
import { DEFAULT_SLOTS, emptyRoster, type Roster, type SavedLeague, type SlotGroup } from "../src/data/leagueContract";
import { DATA_CAUSES, isDataCause, optimizeLineup, readWeek, type WeekContext } from "../src/data/lineup";
import { simulateMatchup } from "../src/data/matchupEngine";
import {
  buildSimInput,
  normalProposals,
  readSetup,
  type Identity,
  type Scenario,
  type SetupInput,
  type SlotReading,
} from "../src/data/matchupSetup";
import { distributionRule } from "../src/data/startsit";
import { emptyStarters, newEntry, type MatchupEntry } from "../src/data/wmmContract";
import { required } from "./required";

const WEEK = 9;
const BUILD = "2026w08-intrinsic-ros-v1-20261106T123207Z";
/** Friday 2026-11-06, 10:00 AM ET: Thursday's JAX @ BAL is over, Sunday's games are ahead. */
const FRIDAY = Date.parse("2026-11-06T15:00:00Z");
const THURSDAY = "2026-11-06T01:15:00Z";
const SUNDAY = "2026-11-08T18:00:00Z";
const RULE = distributionRule(null);
const IDENTITY: Identity = { buildId: BUILD, modelVersion: "weekly-startsit-v1", scoring: "HALF", week: WEEK, leagueId: "lg-friday01" };

type Shape = "thursday" | "sunday" | "bye";

interface Spec {
  readonly position: Position;
  readonly team: string;
  readonly shape: Shape;
  /** q10, q50, q90. */
  readonly q: readonly [number, number, number];
  readonly designation?: "Out" | "Doubtful" | "Questionable";
}

// Thursday: JAX @ BAL. Sunday: four other games. One bye.
const SPECS: Readonly<Record<string, Spec>> = {
  // Mine.
  lamar: { position: "QB", team: "BAL", shape: "thursday", q: [0.48, 9.88, 19.65] },
  rb1: { position: "RB", team: "DET", shape: "sunday", q: [6, 12, 20] },
  rb2: { position: "RB", team: "CIN", shape: "sunday", q: [4, 9, 16] },
  jaxwr: { position: "WR", team: "JAX", shape: "thursday", q: [3, 8, 15] },
  wr2: { position: "WR", team: "DET", shape: "sunday", q: [5, 11, 19] },
  te: { position: "TE", team: "PIT", shape: "bye", q: [0, 0, 0] },
  flex: { position: "WR", team: "KC", shape: "sunday", q: [4, 10, 18] },
  // Bench: a Sunday back with a far higher ceiling, and a Thursday back nobody may move in.
  benchrb: { position: "RB", team: "LAC", shape: "sunday", q: [7, 14, 26] },
  benchthu: { position: "RB", team: "BAL", shape: "thursday", q: [9, 16, 28] },
  // Theirs.
  stafford: { position: "QB", team: "LA", shape: "sunday", q: [11, 18, 26] },
  jaxrb: { position: "RB", team: "JAX", shape: "thursday", q: [5, 11, 19] },
  orb2: { position: "RB", team: "KC", shape: "sunday", q: [4, 10, 17] },
  owr1: { position: "WR", team: "LA", shape: "sunday", q: [6, 12, 21] },
  owr2: { position: "WR", team: "CIN", shape: "sunday", q: [4, 10, 17] },
  ote: { position: "TE", team: "LAC", shape: "sunday", q: [2, 6, 12] },
  balwr: { position: "WR", team: "BAL", shape: "thursday", q: [4, 9, 17] },
};

const GAMES: Readonly<Record<string, readonly [string, string, string]>> = {
  BAL: ["2026_09_JAX_BAL", "JAX", "home"],
  JAX: ["2026_09_JAX_BAL", "BAL", "away"],
  DET: ["2026_09_ATL_DET", "ATL", "home"],
  CIN: ["2026_09_CIN_BUF", "BUF", "away"],
  KC: ["2026_09_LAC_KC", "LAC", "home"],
  LAC: ["2026_09_LAC_KC", "KC", "away"],
  LA: ["2026_09_LA_WAS", "WAS", "away"],
};

type Mode = "healthy" | "outage";

interface Options {
  readonly mode?: Mode;
  /** Per-player record overrides. */
  readonly patch?: Readonly<Record<string, Partial<WeeklyProjectionRecord>>>;
  readonly missing?: readonly string[];
  /** Records as an older (1.1) build wrote them: no line provenance at all. */
  readonly legacy?: boolean;
}

function record(id: string, spec: Spec, options: Options): WeeklyProjectionRecord {
  const [q10, q50, q90] = spec.q;
  const thursday = spec.shape === "thursday";
  const pending = options.mode === "outage" && spec.shape === "sunday";
  const bye = spec.shape === "bye";
  const lined = !bye && !pending;
  const [gameId, opponent, side] = GAMES[spec.team] ?? [`2026_09_${spec.team}`, "OPP", "home"];
  const base: WeeklyProjectionRecord = {
    schema_version: options.legacy === true ? "1.1" : "1.2",
    build_id: BUILD,
    season: 2026,
    through_week: WEEK - 1,
    target_week: WEEK,
    player_id: id,
    display_name: id,
    position: spec.position,
    team: spec.team,
    scoring_preset: "HALF",
    model_version: "weekly-startsit-v1",
    game_state: bye ? "bye" : pending ? "lines_pending" : thursday ? "kicked_off" : "upcoming",
    game: bye
      ? null
      : {
          game_id: gameId,
          opponent,
          home_away: side === "home" ? "home" : "away",
          neutral_site: false,
          kickoff_utc: thursday ? THURSDAY : SUNDAY,
          roof: "outdoors",
          total_line: lined ? 44.5 : null,
          team_margin: lined ? (side === "home" ? 3 : -3) : null,
          team_points: lined ? (side === "home" ? 23.75 : 20.75) : null,
          ...(options.legacy === true
            ? {}
            : { line_source: lined ? "schedule" : null, lines_observed_at_utc: lined ? "2026-11-06T12:27:56Z" : null }),
        },
    quantiles: lined
      ? { q05: q10 - (q50 - q10) * 0.25, q10, q25: (q10 + q50) / 2, q50, q75: (q50 + q90) / 2, q90, q95: q90 + (q90 - q50) * 0.2 }
      : null,
    drivers: null,
    explanation: null,
    opponent: null,
    injury: spec.designation === undefined ? null : { week: WEEK, designation: spec.designation, practice_status: null, primary_injury: null },
  };
  return { ...base, ...(options.patch?.[id] ?? {}) };
}

function availability(spec: Spec | undefined): Availability {
  return readAvailability({
    status: {
      player_id: "x",
      roster_status: "ACT",
      sleeper_status: "Active",
      injury_status: spec?.designation ?? null,
      observed_at_utc: "2026-11-06T12:00:00Z",
      quality_flags: [],
    },
    referenceTime: "2026-11-06T12:32:07Z",
    season: 2026,
  });
}

function contextFor(options: Options = {}, now = FRIDAY): WeekContext {
  return {
    weeklyFor: (id) => {
      const spec = SPECS[id];
      if (spec === undefined || options.missing?.includes(id) === true) return null;
      return record(id, spec, options);
    },
    availabilityFor: (id) => (SPECS[id] === undefined ? null : availability(SPECS[id])),
    positionOf: (id) => SPECS[id]?.position ?? null,
    targetWeek: WEEK,
    buildId: BUILD,
    now,
  };
}

function rosterOf(groups: Partial<Record<SlotGroup, (string | null)[]>>): Roster {
  const roster = emptyRoster(DEFAULT_SLOTS) as Record<SlotGroup, (string | null)[]>;
  for (const [group, ids] of Object.entries(groups) as [SlotGroup, (string | null)[]][]) {
    ids.forEach((id, index) => {
      roster[group][index] = id;
    });
  }
  return roster;
}

const MINE = rosterOf({ QB: ["lamar"], RB: ["rb1", "rb2"], WR: ["jaxwr", "wr2"], TE: ["te"], FLEX: ["flex"], BN: ["benchrb", "benchthu"] });
const LEAGUE: SavedLeague = {
  id: "lg-friday01",
  name: "Friday",
  season: 2026,
  scoring: "half",
  teams: 12,
  slots: DEFAULT_SLOTS,
  roster: MINE,
  prefs: { risingStars: false, mode: "q50" },
  rev: 1,
  updatedAt: "",
};

function opponent(finals: Readonly<Record<string, number>> = {}, extra: Partial<MatchupEntry> = {}): MatchupEntry {
  return {
    ...newEntry("lg-friday01", 2026, WEEK),
    opponent: {
      name: "Rival",
      starters: { ...emptyStarters(), QB: ["stafford"], RB: ["jaxrb", "orb2"], WR: ["owr1", "owr2"], TE: ["ote"], FLEX: ["balwr"] },
      others: [],
    },
    finals,
    ...extra,
  };
}

const FINALS = { lamar: 23.45, jaxwr: 0, jaxrb: -1.5 };

function input(scenario: Scenario, options: Options = {}, entry: MatchupEntry = opponent(FINALS), now = FRIDAY): SetupInput {
  return { league: LEAGUE, entry, context: contextFor(options, now), scenario };
}

const by = (lines: readonly SlotReading[], id: string): SlotReading => required(lines.find((line) => line.id === id), id);

function simulate(setupInput: SetupInput) {
  const built = buildSimInput(readSetup(setupInput), [], RULE, {}, IDENTITY);
  return { result: simulateMatchup(built.input), fingerprint: built.fingerprint };
}

describe("a Friday with completed Thursday starters and valid Sunday projections", () => {
  it("with final scores: Simulate is ready, finals replace the Thursday starters, Sunday starters are modelled", () => {
    const setup = readSetup(input("finals"));
    expect(setup.complete).toBe(true);
    expect(setup.decisions).toEqual([]);
    expect(setup.dataGaps).toEqual([]);
    expect(by(setup.mine, "lamar")).toMatchObject({ kind: "final", fixed: 23.45, cause: null });
    // Zero and negative finals are finals, not "no final".
    expect(by(setup.mine, "jaxwr")).toMatchObject({ kind: "final", fixed: 0 });
    expect(by(setup.theirs, "jaxrb")).toMatchObject({ kind: "final", fixed: -1.5 });
    // A completed starter without an entered final keeps his pregame projection, and says so.
    const balwr = by(setup.theirs, "balwr");
    expect(balwr).toMatchObject({ kind: "modelled", locked: true });
    expect(balwr.note).toBe("Game kicked off, no final entered: simulated from his pregame projection; the current score is not used.");
    // Every Sunday starter on both sides is modelled from his own projection: no final asked.
    for (const id of ["rb1", "rb2", "wr2", "flex", "stafford", "orb2", "owr1", "owr2", "ote"]) {
      expect(by([...setup.mine, ...setup.theirs], id)).toMatchObject({ kind: "modelled", locked: false });
    }
    expect(by(setup.mine, "te")).toMatchObject({ kind: "bye", fixed: 0 });
  });

  it("counts each final exactly once, in place of his simulated points", () => {
    const { result } = simulate(input("finals"));
    const base = required(result.variants[0], "base");
    const qb = required(required(base.groups, "groups").find((group) => group.group === "QB"), "QB");
    // The QB group is his final and nothing else: no draw added, no final counted twice.
    expect([qb.mine.p10, qb.mine.p50, qb.mine.p90, qb.mine.mean]).toEqual([23.45, 23.45, 23.45, 23.45]);
    // Ten more points of final move my total by exactly ten, draw for draw.
    const higher = simulate(input("finals", {}, opponent({ ...FINALS, lamar: 33.45 }))).result;
    const moved = required(higher.variants[0], "base");
    expect(moved.mine.mean - base.mine.mean).toBeCloseTo(10, 2);
    expect(moved.mine.p50 - base.mine.p50).toBeCloseTo(10, 2);
    expect(higher.theirs).toEqual(result.theirs);
    // A negative final lowers their total by its size against a zero final.
    const zeroed = simulate(input("finals", {}, opponent({ ...FINALS, jaxrb: 0 }))).result;
    expect(zeroed.theirs.mean - result.theirs.mean).toBeCloseTo(1.5, 2);
  });

  it("pregame simulates every starter, Thursday's included, from his pregame distribution", () => {
    const setup = readSetup(input("pregame"));
    expect(setup.complete).toBe(true);
    expect(by(setup.mine, "lamar")).toMatchObject({ kind: "modelled", locked: true });
    expect(by(setup.mine, "lamar").note).toBe("Game kicked off: simulated from his pregame projection; the current score is not used.");
    const qb = required(required(simulate(input("pregame")).result.variants[0]?.groups, "groups").find((group) => group.group === "QB"), "QB");
    expect(qb.mine.p90).toBeGreaterThan(qb.mine.p10);
    // Each scenario is its own answer.
    expect(simulate(input("pregame")).fingerprint).not.toBe(simulate(input("finals")).fingerprint);
  });

  it("never moves a Thursday starter, and never moves a Thursday bench player in", () => {
    const context = contextFor();
    for (const mode of ["q50", "q10", "q90"] as const) {
      const proposal = optimizeLineup(MINE, DEFAULT_SLOTS, context, mode);
      expect(proposal.roster.QB).toEqual(["lamar"]);
      expect(proposal.roster.WR[0]).toBe("jaxwr");
      expect(proposal.roster.BN).toContain("benchthu");
      expect(proposal.moves.some((move) => move.id === "benchthu" || move.id === "lamar" || move.id === "jaxwr")).toBe(false);
    }
    const proposals = normalProposals(input("finals"), readSetup(input("finals")).mine);
    // The Sunday bench back's ceiling is worth evaluating; the Thursday ones never move.
    expect(proposals.some((proposal) => proposal.moves.some((move) => move.id === "benchrb"))).toBe(true);
    for (const proposal of proposals) {
      expect(proposal.roster.QB).toEqual(["lamar"]);
      expect(proposal.roster.WR[0]).toBe("jaxwr");
      expect(proposal.moves.some((move) => move.id === "benchthu")).toBe(false);
    }
  });

  it("takes no final for a game that has not kicked off, and does not read kickoff as completion", () => {
    // A final saved for a Sunday starter is ignored on Friday: he stays modelled.
    const early = readSetup(input("finals", {}, opponent({ ...FINALS, rb1: 30 })));
    expect(by(early.mine, "rb1")).toMatchObject({ kind: "modelled", fixed: 0 });
    // On Sunday after kickoff he is locked; with no final he is still his pregame projection.
    const sunday = Date.parse("2026-11-08T18:30:00Z");
    const during = readSetup(input("finals", {}, opponent(FINALS), sunday));
    expect(by(during.mine, "rb1")).toMatchObject({ kind: "modelled", locked: true });
    expect(by(during.mine, "rb1").note).toMatch(/no final entered/);
  });
});

describe("the 2026-11-06 outage: every upcoming game without lines", () => {
  it("blocks Simulate on data alone: zero decisions, every upcoming starter a lines_pending data gap", () => {
    const setup = readSetup(input("finals", { mode: "outage", legacy: true }));
    expect(setup.complete).toBe(false);
    expect(setup.decisions).toEqual([]);
    expect(setup.dataGaps.map((line) => line.id).sort()).toEqual(["flex", "orb2", "ote", "owr1", "owr2", "rb1", "rb2", "stafford", "wr2"]);
    expect(setup.dataGaps.every((line) => line.cause === "lines_pending" && line.kind === "blocking")).toBe(true);
    expect(by(setup.mine, "rb1").note).toBe("No sportsbook line in this build.");
    // The Thursday starters are unaffected: their finals and pregame projection stand.
    expect(by(setup.mine, "lamar")).toMatchObject({ kind: "final", fixed: 23.45 });
    expect(by(setup.theirs, "balwr")).toMatchObject({ kind: "modelled", locked: true });
    // Nothing stands in: no fixed value, no engine input.
    expect(setup.dataGaps.every((line) => line.fixed === 0)).toBe(true);
    expect(() => buildSimInput(setup, [], RULE, {}, IDENTITY)).toThrow(/not complete/);
  });

  it("a final, a zero or a confirmation for an outage starter does not unblock him", () => {
    const entry = opponent({ ...FINALS, rb1: 12, stafford: 20 }, { countZero: ["rb2", "owr1"], confirmedEmpty: { mine: ["RB:0"], theirs: ["QB:0"] } });
    const setup = readSetup(input("finals", { mode: "outage" }, entry));
    for (const id of ["rb1", "rb2", "stafford", "owr1"]) expect(by([...setup.mine, ...setup.theirs], id)).toMatchObject({ kind: "blocking", cause: "lines_pending" });
    expect(setup.complete).toBe(false);
  });

  it("leaves outage players where they are in Auto Start/Sit, with the cause on each gap", () => {
    const proposal = optimizeLineup(MINE, DEFAULT_SLOTS, contextFor({ mode: "outage" }), "q50");
    expect(proposal.moves).toEqual([]);
    const unscored = proposal.gaps.filter((gap) => gap.kind === "unscored");
    expect(unscored.map((gap) => gap.cause)).toEqual(["lines_pending", "lines_pending", "lines_pending", "lines_pending"]);
    const week = readWeek("rb1", contextFor({ mode: "outage" }));
    expect(week).toMatchObject({ kind: "pinned", cause: "lines_pending" });
    expect(week.reason).toBe("No projection: this build had no sportsbook line for his game. Left where you put him.");
    expect(week.reason).not.toMatch(/posted/);
  });

  it("when a Sunday game kicks off without a projection, entering its final is the reader's decision", () => {
    const sunday = Date.parse("2026-11-08T22:00:00Z");
    const pregame = readSetup(input("pregame", { mode: "outage" }, opponent(FINALS), sunday));
    expect(by(pregame.mine, "rb1")).toMatchObject({ kind: "blocking", fix: "final", cause: "final_needed" });
    expect(by(pregame.mine, "rb1").note).toBe(
      "His game has kicked off with no projection (no sportsbook line in this build). Use “With final scores” and enter his final score once the game is over.",
    );
    expect(pregame.decisions.map((line) => line.id)).toContain("rb1");
    const entered = readSetup(input("finals", { mode: "outage" }, opponent({ ...FINALS, rb1: 14.2 }), sunday));
    expect(by(entered.mine, "rb1")).toMatchObject({ kind: "final", fixed: 14.2 });
  });
});

describe("every cause is named, and data causes are kept apart from decisions", () => {
  it("unmodelled, no record, another week, another build and an unknown kickoff are data gaps", () => {
    const options: Options = {
      missing: ["rb2"],
      patch: {
        rb1: { game_state: "unmodelled", quantiles: null },
        wr2: { target_week: WEEK + 1 },
        flex: { build_id: "2026w08-intrinsic-ros-v1-20261105T225300Z" },
        stafford: { game: { ...required(record("stafford", required(SPECS.stafford, "s"), {}).game, "game"), kickoff_utc: null } },
      },
    };
    const setup = readSetup(input("finals", options));
    const causes: Record<string, string | null> = Object.fromEntries([...setup.mine, ...setup.theirs].map((line) => [line.id ?? "", line.cause]));
    expect(causes).toMatchObject({ rb1: "unmodelled", rb2: "no_record", wr2: "other_week", flex: "other_build", stafford: "kickoff_unknown" });
    expect(setup.dataGaps).toHaveLength(5);
    expect(setup.decisions).toEqual([]);
    expect(by(setup.mine, "rb1").note).toBe("No prediction from the model.");
    // An id the build cannot resolve is the build's too.
    const unknown = readSetup({ ...input("finals"), league: { ...LEAGUE, roster: { ...MINE, RB: ["gsis:00-9999999", "rb2"] } } });
    expect(by(unknown.mine, "gsis:00-9999999")).toMatchObject({ cause: "unresolved", kind: "blocking" });
    expect(unknown.decisions).toEqual([]);
  });

  it("the reader's decisions keep their causes: empty, absent, overlap, position", () => {
    const roster = { ...MINE, RB: [null, "rb2"], WR: ["jaxwr", "benchthu"] };
    const absent = { ...SPECS };
    const entry = opponent(FINALS);
    const setup = readSetup({
      league: { ...LEAGUE, roster: { ...roster, BN: ["benchrb", "orb2"] } },
      entry,
      context: {
        ...contextFor(),
        availabilityFor: (id) => (id === "flex" ? availability({ ...required(absent.flex, "flex"), designation: "Out" }) : availability(absent[id])),
      },
      scenario: "finals",
    });
    const causes = setup.decisions.map((line) => line.cause).sort();
    expect(causes).toEqual(["absent", "empty", "overlap", "position"]);
    expect(setup.dataGaps).toEqual([]);
    expect(DATA_CAUSES.every((cause) => isDataCause(cause))).toBe(true);
    expect(["empty", "absent", "final_needed", "overlap", "position", null].some((cause) => isDataCause(cause))).toBe(false);
  });
});

describe("what is current", () => {
  it("the engine fingerprint follows a data refresh, a kickoff, a final and the scenario", () => {
    const base = simulate(input("finals")).fingerprint;
    expect(simulate(input("finals")).fingerprint).toBe(base);
    // The same build id with a refreshed distribution is a different input.
    const refreshed = simulate(input("finals", { patch: { rb1: { quantiles: { q05: 4, q10: 6.5, q25: 9, q50: 12, q75: 16, q90: 20, q95: 21.6 } } } })).fingerprint;
    expect(refreshed).not.toBe(base);
    // A final edit, and a zero final against none.
    expect(simulate(input("finals", {}, opponent({ ...FINALS, lamar: 23.46 }))).fingerprint).not.toBe(base);
    expect(simulate(input("finals", {}, opponent({ ...FINALS, balwr: 0 }))).fingerprint).not.toBe(base);
    expect(simulate(input("pregame")).fingerprint).not.toBe(base);
    // A Sunday kickoff passing locks his slot: the same numbers, but a lineup change may no
    // longer move him, so what was evaluated before is not current.
    const sunday = Date.parse("2026-11-08T18:30:00Z");
    expect(simulate(input("finals", {}, opponent(FINALS), sunday)).fingerprint).not.toBe(base);
  });
});

describe("line provenance", () => {
  it("labels retained lines with their observation time, and only those", () => {
    expect(
      retainedLinesNote({ line_source: "retained", lines_observed_at_utc: "2026-11-05T22:53:00Z" }),
    ).toBe("Lines as of Nov 5 · 5:53 PM ET (retained; the schedule had none at this build)");
    expect(retainedLinesNote({ line_source: "schedule", lines_observed_at_utc: "2026-11-06T12:27:56Z" })).toBeNull();
    // An older build says nothing: unknown, never assumed to be the schedule's or retained.
    expect(retainedLinesNote({})).toBeNull();
    expect(retainedLinesNote(null)).toBeNull();
    expect(retainedLinesNote({ line_source: "retained", lines_observed_at_utc: null })).toBe(
      "Lines from an earlier reading (retained; the schedule had none at this build)",
    );
  });
});
