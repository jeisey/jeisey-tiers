/**
 * Win My Matchup's inputs and recommendations (ADR-110 §2, §5, §6): every starter slot's stated
 * condition, the completeness gate, the compact engine input and its fingerprint, normal-mode
 * proposals, and the YOLO gates — with the owner's acceptance case (an eligible RB2 at q90 17,
 * a rising RB with qualifying net adds at q90 22: "+5 ceiling") on synthetic players.
 */

import { describe, expect, it } from "vitest";

import { readAvailability, type Availability } from "../src/data/availability";
import type { OpportunityRecord, PlayerUsageRecord, Position, WeeklyProjectionRecord } from "../src/data/contracts";
import { DEFAULT_SLOTS, emptyRoster, type Roster, type SavedLeague, type SlotCounts, type SlotGroup } from "../src/data/leagueContract";
import type { WeekContext } from "../src/data/lineup";
import { meaningfulDelta, type SimResult } from "../src/data/matchup";
import { simulateMatchup } from "../src/data/matchupEngine";
import {
  MAX_NORMAL_PROPOSALS,
  buildSimInput,
  latentCorrelations,
  normalProposals,
  normalProposalSteps,
  opponentLineup,
  readSetup,
  startersSignature,
  type Identity,
  type Proposal,
  type Scenario,
  type SetupInput,
} from "../src/data/matchupSetup";
import { InSeasonBundle } from "../src/data/ros";
import { distributionRule } from "../src/data/startsit";
import { emptyStarters, newEntry, type MatchupEntry } from "../src/data/wmmContract";
import {
  YOLO_MAX,
  YOLO_PER_POSITION,
  netAddBar,
  selectYolo,
  yoloProposal,
  type YoloSelection,
} from "../src/data/yolo";
import { opportunityRecords, rosBuildMetadata, rosTierRecords, usageRecords } from "./fixtures/artifacts";
import { required } from "./required";

const WEEK = 9;
/** Within 48 hours of the fixture's behaviour snapshot (2026-08-21T14:38Z), before every kickoff. */
const NOW = Date.parse("2026-08-22T12:00:00Z");
const KICKOFF = "2026-11-08T18:00:00Z";
const RULE = distributionRule(null);
const IDENTITY: Identity = { buildId: "test", modelVersion: "weekly-startsit-v1", scoring: "PPR", week: WEEK, leagueId: "lg-test01" };

interface Spec {
  readonly name?: string;
  readonly position: Position;
  /** q10, q50, q90; the other four quantiles are spread around them. */
  readonly q: readonly [number, number, number];
  readonly team?: string;
  readonly game?: string;
  readonly state?: WeeklyProjectionRecord["game_state"];
  readonly kickoff?: string | null;
  readonly week?: number;
  readonly designation?: "Out" | "Doubtful" | "Questionable" | null;
  readonly noRecord?: boolean;
}

function weeklyRecord(id: string, spec: Spec): WeeklyProjectionRecord {
  const [q10, q50, q90] = spec.q;
  const state = spec.state ?? "upcoming";
  const bye = state === "bye";
  const team = spec.team ?? `T${id.slice(-3)}`;
  return {
    schema_version: "1.1",
    build_id: "test",
    season: 2026,
    through_week: WEEK - 1,
    target_week: spec.week ?? WEEK,
    player_id: id,
    display_name: spec.name ?? id,
    position: spec.position,
    team,
    scoring_preset: "PPR",
    model_version: "weekly-startsit-v1",
    game_state: state,
    game: bye
      ? null
      : {
          game_id: spec.game ?? `g-${team}`,
          opponent: "OPP",
          home_away: "home",
          neutral_site: false,
          kickoff_utc: spec.kickoff === undefined ? KICKOFF : spec.kickoff,
          roof: null,
          total_line: 45,
          team_margin: 1,
          team_points: 23,
        },
    quantiles:
      bye || state === "lines_pending"
        ? null
        : { q05: q10 - (q50 - q10) * 0.25, q10, q25: (q10 + q50) / 2, q50, q75: (q50 + q90) / 2, q90, q95: q90 + (q90 - q50) * 0.2 },
    drivers: null,
    explanation: null,
    opponent: null,
    injury: spec.designation == null ? null : { week: WEEK, designation: spec.designation, practice_status: null, primary_injury: null },
  };
}

function availabilityOf(spec: Spec | undefined): Availability {
  return readAvailability({
    status: {
      player_id: "x",
      roster_status: "ACT",
      sleeper_status: "Active",
      injury_status: spec?.designation ?? null,
      observed_at_utc: "2026-08-22T10:00:00Z",
      quality_flags: [],
    },
    referenceTime: "2026-08-22T11:00:00Z",
    season: 2026,
  });
}

function contextFor(specs: Readonly<Record<string, Spec>>, now = NOW): WeekContext {
  return {
    weeklyFor: (id) => {
      const spec = specs[id];
      return spec === undefined || spec.noRecord === true ? null : weeklyRecord(id, spec);
    },
    availabilityFor: (id) => (specs[id] === undefined ? null : availabilityOf(specs[id])),
    positionOf: (id) => specs[id]?.position ?? null,
    targetWeek: WEEK,
    now,
  };
}

const g = (n: number): string => `gsis:00-0000${String(n).padStart(3, "0")}`;

function rosterOf(groups: Partial<Record<SlotGroup, (string | null)[]>>, counts: SlotCounts = DEFAULT_SLOTS): Roster {
  const roster = emptyRoster(counts) as Record<SlotGroup, (string | null)[]>;
  for (const [group, ids] of Object.entries(groups) as [SlotGroup, (string | null)[]][]) {
    ids.forEach((id, index) => {
      roster[group][index] = id;
    });
  }
  return roster;
}

function league(roster: Roster, slots: SlotCounts = DEFAULT_SLOTS): SavedLeague {
  return { id: "lg-test01", name: "Test", season: 2026, scoring: "ppr", teams: 12, slots, roster, prefs: { risingStars: false, mode: "q50" }, rev: 1, updatedAt: "" };
}

function opponent(starters: Partial<Record<"QB" | "RB" | "WR" | "TE" | "FLEX", (string | null)[]>>, others: string[] = []): MatchupEntry {
  const base = newEntry("lg-test01", 2026, WEEK);
  return { ...base, opponent: { name: "Rival", starters: { ...emptyStarters(), ...starters }, others } };
}

// A complete pair of lineups on the default slots: 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX.
const SPECS: Record<string, Spec> = {
  [g(1)]: { position: "QB", q: [12, 19, 27], team: "AAA", game: "G1" },
  [g(2)]: { position: "RB", q: [6, 13, 20] },
  [g(3)]: { position: "RB", q: [5, 10, 17] },
  [g(4)]: { position: "WR", q: [5, 12, 21], team: "AAA", game: "G1" },
  [g(5)]: { position: "WR", q: [4, 10, 18] },
  [g(6)]: { position: "TE", q: [2, 7, 13] },
  [g(7)]: { position: "WR", q: [4, 11, 19] },
  // Bench.
  [g(8)]: { position: "RB", q: [3, 8, 21] },
  [g(9)]: { position: "WR", q: [6, 11, 15] },
  // Opponent.
  [g(11)]: { position: "QB", q: [13, 20, 28], team: "BBB", game: "G1" },
  [g(12)]: { position: "RB", q: [6, 12, 19] },
  [g(13)]: { position: "RB", q: [5, 11, 18] },
  [g(14)]: { position: "WR", q: [5, 12, 20] },
  [g(15)]: { position: "WR", q: [4, 10, 17] },
  [g(16)]: { position: "TE", q: [2, 6, 12] },
  [g(17)]: { position: "RB", q: [4, 9, 16] },
};
const MINE = rosterOf({ QB: [g(1)], RB: [g(2), g(3)], WR: [g(4), g(5)], TE: [g(6)], FLEX: [g(7)], BN: [g(8), g(9)] });
const THEIRS = opponent({ QB: [g(11)], RB: [g(12), g(13)], WR: [g(14), g(15)], TE: [g(16)], FLEX: [g(17)] });

function setupInput(overrides: Partial<SetupInput> = {}, specs: Readonly<Record<string, Spec>> = SPECS): SetupInput {
  return { league: league(MINE), entry: THEIRS, context: contextFor(specs), scenario: "pregame", ...overrides };
}

function simulate(input: SetupInput, proposals: readonly Proposal[] = []): { result: SimResult; ids: readonly string[] } {
  const setup = readSetup(input);
  const built = buildSimInput(setup, proposals, RULE, latentCorrelations(rosBuildMetadata({}, true).weekly), IDENTITY);
  return { result: simulateMatchup(built.input), ids: built.variantIds };
}

describe("every starter slot is in one stated condition", () => {
  it("a complete pair of lineups is simulable, and nothing is a silent zero", () => {
    const setup = readSetup(setupInput());
    expect(setup.complete).toBe(true);
    expect(setup.mine.map((line) => line.kind)).toEqual(Array(7).fill("modelled"));
    expect(setup.theirs.every((line) => line.kind === "modelled")).toBe(true);
  });

  it("an empty slot blocks until the reader confirms it empty, and then counts 0", () => {
    const roster = rosterOf({ QB: [g(1)], RB: [g(2), g(3)], WR: [g(4), g(5)], TE: [null], FLEX: [g(7)] });
    const open = readSetup(setupInput({ league: league(roster) }));
    expect(open.complete).toBe(false);
    expect(open.blocking.map((line) => [line.side, line.slot.group, line.fix])).toEqual([["mine", "TE", "fill"]]);
    const confirmed = readSetup(setupInput({ league: league(roster), entry: { ...THEIRS, confirmedEmpty: { mine: ["TE:0"], theirs: [] } } }));
    expect(confirmed.complete).toBe(true);
    expect(confirmed.mine.find((line) => line.slot.group === "TE")).toMatchObject({ kind: "empty", fixed: 0 });
  });

  it("a missing, pending, other-week or unknown distribution blocks — never a fallback", () => {
    const specs: Record<string, Spec> = {
      ...SPECS,
      [g(5)]: { position: "WR", q: [4, 10, 18], noRecord: true },
      [g(6)]: { position: "TE", q: [2, 7, 13], state: "lines_pending" },
      [g(7)]: { position: "WR", q: [4, 11, 19], week: WEEK + 1 },
    };
    const setup = readSetup(setupInput({}, specs));
    expect(setup.complete).toBe(false);
    expect(setup.blocking.map((line) => line.id)).toEqual([g(5), g(6), g(7)]);
    expect(setup.blocking.every((line) => line.fix === "replace")).toBe(true);
    const unknown = rosterOf({ QB: [g(1)], RB: [g(2), g(3)], WR: [g(4), "gsis:00-9999999"], TE: [g(6)], FLEX: [g(7)] });
    expect(readSetup(setupInput({ league: league(unknown) })).blocking.map((line) => line.id)).toEqual(["gsis:00-9999999"]);
  });

  it("a bye is a known zero; out or doubtful blocks until counted as 0; questionable plays 'if active'", () => {
    const specs: Record<string, Spec> = {
      ...SPECS,
      [g(3)]: { position: "RB", q: [5, 10, 17], state: "bye" },
      [g(5)]: { position: "WR", q: [4, 10, 18], designation: "Out" },
      [g(6)]: { position: "TE", q: [2, 7, 13], designation: "Questionable" },
    };
    const setup = readSetup(setupInput({}, specs));
    const by = (id: string) => required(setup.mine.find((line) => line.id === id), id);
    expect(by(g(3))).toMatchObject({ kind: "bye", fixed: 0 });
    expect(by(g(5))).toMatchObject({ kind: "blocking", fix: "count_zero" });
    expect(by(g(6))).toMatchObject({ kind: "modelled", conditional: true });
    expect(by(g(6)).note).toMatch(/If active/);
    const zeroed = readSetup(setupInput({ entry: { ...THEIRS, countZero: [g(5)] } }, specs));
    expect(zeroed.complete).toBe(true);
    expect(zeroed.mine.find((line) => line.id === g(5))).toMatchObject({ kind: "zero", fixed: 0 });
  });

  it("a locked starter is simulated from his pregame projection, or from a confirmed final in that scenario", () => {
    const specs: Record<string, Spec> = { ...SPECS, [g(2)]: { position: "RB", q: [6, 13, 20], kickoff: "2026-08-22T10:00:00Z" } };
    const entry: MatchupEntry = { ...THEIRS, finals: { [g(2)]: 31.4 } };
    const pregame = readSetup(setupInput({ entry }, specs));
    expect(pregame.mine.find((line) => line.id === g(2))).toMatchObject({ kind: "modelled", locked: true });
    expect(pregame.lockedStarters.map((line) => line.id)).toEqual([g(2)]);
    const finals = readSetup(setupInput({ entry, scenario: "finals" as Scenario }, specs));
    expect(finals.mine.find((line) => line.id === g(2))).toMatchObject({ kind: "final", fixed: 31.4 });
    // A final counts exactly once and replaces the projection.
    const { result } = simulate(setupInput({ entry, scenario: "finals" }, specs));
    const qb = required(required(result.variants[0], "base").groups, "groups").find((group) => group.group === "RB");
    expect(required(qb, "RB").mine.p10).toBeGreaterThanOrEqual(31.4 + 4.9);
    // Without a final and without a distribution, the slot blocks.
    const noDist: Record<string, Spec> = { ...specs, [g(2)]: { position: "RB", q: [6, 13, 20], kickoff: "2026-08-22T10:00:00Z", state: "lines_pending" } };
    expect(readSetup(setupInput({}, noDist)).blocking.map((line) => line.fix)).toEqual(["final"]);
  });

  it("a player on both teams blocks; overflow and the wrong position block too", () => {
    const both = opponent({ QB: [g(11)], RB: [g(12), g(13)], WR: [g(14), g(15)], TE: [g(16)], FLEX: [g(8)] });
    const setup = readSetup(setupInput({ entry: both }));
    expect(setup.overlaps).toEqual([g(8)]);
    expect(setup.complete).toBe(false);
    expect(setup.theirs.find((line) => line.id === g(8))).toMatchObject({ kind: "blocking", fix: "resolve_overlap" });
    const wrong = opponent({ QB: [g(12)], RB: [g(11), g(13)], WR: [g(14), g(15)], TE: [g(16)], FLEX: [g(17)] });
    expect(readSetup(setupInput({ entry: wrong })).blocking.map((line) => line.id)).toEqual([g(12), g(11)]);
    const laid = opponentLineup(opponent({ RB: [g(12), g(13), g(17)] }), DEFAULT_SLOTS);
    expect(laid.overflow).toEqual([{ group: "RB", id: g(17) }]);
  });
});

describe("the engine's input", () => {
  it("lists each modelled player once, fixed slots as points, and refuses an incomplete setup", () => {
    const setup = readSetup(setupInput());
    const built = buildSimInput(setup, [], RULE, {}, IDENTITY);
    expect(built.input.players).toHaveLength(14);
    expect(new Set(built.input.players.map((player) => player.key)).size).toBe(14);
    expect(built.input.variants[0]?.slots.filter((slot) => slot.group === "FLEX")).toHaveLength(1);
    const open = readSetup(setupInput({ league: league(rosterOf({ QB: [g(1)] })) }));
    expect(() => buildSimInput(open, [], RULE, {}, IDENTITY)).toThrow(/not complete/);
  });

  it("fingerprints every input a result depends on", () => {
    const base = buildSimInput(readSetup(setupInput()), [], RULE, {}, IDENTITY).fingerprint;
    expect(buildSimInput(readSetup(setupInput()), [], RULE, {}, IDENTITY).fingerprint).toBe(base);
    const changes = [
      buildSimInput(readSetup(setupInput({ scenario: "finals" })), [], RULE, {}, IDENTITY).fingerprint,
      buildSimInput(readSetup(setupInput()), [], RULE, { "opponents:any": 0.03 }, IDENTITY).fingerprint,
      buildSimInput(readSetup(setupInput()), [], RULE, {}, { ...IDENTITY, buildId: "next" }).fingerprint,
      buildSimInput(readSetup(setupInput()), [], RULE, {}, { ...IDENTITY, week: 10 }).fingerprint,
      buildSimInput(readSetup(setupInput()), [], RULE, {}, { ...IDENTITY, leagueId: "lg-other01" }).fingerprint,
      buildSimInput(readSetup(setupInput()), [], RULE, {}, IDENTITY, { draws: 4096 }).fingerprint,
      buildSimInput(
        readSetup(setupInput({ entry: opponent({ QB: [g(11)], RB: [g(12), g(17)], WR: [g(14), g(15)], TE: [g(16)], FLEX: [g(13)] }) })),
        [],
        RULE,
        {},
        IDENTITY,
      ).fingerprint,
    ];
    for (const fingerprint of changes) expect(fingerprint).not.toBe(base);
    // Reordering the opponent's two backs does not change the starters, only the slot labels.
    expect(changes[6]).not.toBe(base);
  });
});

describe("normal-mode proposals", () => {
  it("evaluates the Auto Start/Sit proposals and single bench swaps, deduplicated and bounded", () => {
    const input = setupInput();
    const setup = readSetup(input);
    const proposals = normalProposals(input, setup.mine);
    expect(proposals.length).toBeGreaterThan(0);
    expect(proposals.length).toBeLessThanOrEqual(MAX_NORMAL_PROPOSALS);
    // Built in pieces (the page builds them between frames), the same list.
    const steps = normalProposalSteps(input, setup.mine);
    let pieces = 0;
    let step = steps.next();
    while (step.done !== true) {
      pieces += 1;
      step = steps.next();
    }
    expect(pieces).toBeGreaterThanOrEqual(3);
    expect(step.value).toEqual(proposals);
    const signatures = proposals.map((proposal) => startersSignature(proposal.mine));
    expect(new Set(signatures).size).toBe(signatures.length);
    expect(signatures).not.toContain(startersSignature(setup.mine));
    // The bench RB's ceiling (21) beats the RB2's (17): starting him is offered — by the Ceiling
    // objective here, so the identical single swap is a duplicate and is not evaluated twice.
    expect(proposals.some((proposal) => proposal.moves.some((move) => move.id === g(8) && move.to.group !== "BN"))).toBe(true);
    expect(proposals.map((proposal) => proposal.id)).toContain("auto-q90");
    for (const proposal of proposals) expect(proposal.roster.IR).toEqual(MINE.IR);
  });

  it("never moves a locked or pinned starter", () => {
    const specs: Record<string, Spec> = {
      ...SPECS,
      [g(3)]: { position: "RB", q: [1, 2, 3], kickoff: "2026-08-22T10:00:00Z" },
    };
    const input = setupInput({}, specs);
    const proposals = normalProposals(input, readSetup(input).mine);
    for (const proposal of proposals) expect(proposal.roster.RB[1]).toBe(g(3));
  });

  it("ranks by the chance to win: trailing badly, the ceiling swap beats the median lineup", () => {
    // My RB2 is steady (q50 10, q90 12); the bench back is boom-or-bust (q50 9, q90 24). Against
    // a much stronger opponent, the higher-variance back wins more often despite the lower median.
    const specs: Record<string, Spec> = {
      ...SPECS,
      [g(3)]: { position: "RB", q: [8.5, 10, 12] },
      [g(8)]: { position: "RB", q: [0.5, 9, 24] },
      [g(11)]: { position: "QB", q: [22, 30, 38], team: "BBB", game: "G1" },
      [g(12)]: { position: "RB", q: [12, 18, 25] },
      [g(14)]: { position: "WR", q: [10, 17, 25] },
    };
    const input = setupInput({}, specs);
    const setup = readSetup(input);
    const proposals = normalProposals(input, setup.mine);
    const ceilingSwap = required(proposals.find((proposal) => proposal.moves.some((move) => move.id === g(8) && move.to.group === "RB")), "the swap");
    const { result, ids } = simulate(input, proposals);
    const base = required(result.variants[0], "base");
    const swap = required(result.variants[ids.indexOf(ceilingSwap.id) + 1], "swap result");
    expect(base.win).toBeLessThan(0.3);
    expect(required(swap.paired, "paired").win).toBeGreaterThan(0);
    expect(meaningfulDelta(required(swap.paired, "paired"))).toBe(true);
    // The median objective would never make this swap.
    const median = proposals.find((proposal) => proposal.id === "auto-q50");
    expect(median?.moves.some((move) => move.id === g(8)) ?? false).toBe(false);
  });
});

// ------------------------------------------------------------------------------------- YOLO

/** Synthetic Opportunity rows for one block: net adds by id, everyone with behaviour. */
function opportunityRows(net: Readonly<Record<string, { position: Position; net: number | null; name?: string }>>, behavior = true): OpportunityRecord[] {
  const template = required(opportunityRecords(true).find((row) => row.league_preset_id === "redraft-12" && row.scoring_preset === "PPR"), "template");
  return Object.entries(net).map(([id, spec], index) => ({
    ...template,
    player_id: id,
    display_name: spec.name ?? id,
    position: spec.position,
    team: `T${id.slice(-3)}`,
    ros_fair_rank: 100 + index,
    behavior_available: behavior,
    add_count: spec.net === null ? null : spec.net + 50,
    drop_count: spec.net === null ? null : 50,
    net_add_count: spec.net,
  }));
}

/** A usage record whose snap share rose (`up`), fell, or that has a single game. */
function usage(id: string, position: Position, shape: "up" | "down" | "one"): PlayerUsageRecord {
  const template = required(usageRecords().find((row) => row.player_id === "gsis:00-0000011"), "rising usage template");
  const change =
    shape === "one"
      ? { latest_week: 8, latest: 0.5, earlier: null, earlier_games: 0, change: null }
      : { latest_week: 8, latest: shape === "up" ? 0.72 : 0.35, earlier: shape === "up" ? 0.4 : 0.6, earlier_games: 3, change: shape === "up" ? 0.32 : -0.25 };
  return {
    ...template,
    player_id: id,
    display_name: id,
    position,
    team: `T${id.slice(-3)}`,
    appearances: 4,
    role_changes: { ...template.role_changes, snap_share: change, pass_attempts: position === "QB" ? { ...change, latest: 35, earlier: 28, change: shape === "up" ? 7 : -7 } : null },
  };
}

function yoloBundle(rows: OpportunityRecord[], usages: PlayerUsageRecord[], options: { behavior?: boolean; usage?: boolean } = {}): InSeasonBundle {
  return new InSeasonBundle({
    metadata: rosBuildMetadata({}, options.behavior ?? true),
    rosTiers: rosTierRecords(),
    opportunity: rows,
    opportunityDegradation: null,
    usage: options.usage === false ? null : usages,
    weekly: [],
    status: [],
  });
}

// The acceptance case: my RB2 is an eligible starter with q90 17; a rising RB with qualifying
// net adds projects q90 22. RB1 and FLEX have higher ceilings, so RB2 is the slot.
const YOLO_SPECS: Record<string, Spec> = {
  ...SPECS,
  [g(2)]: { position: "RB", q: [7, 14, 20] },
  [g(3)]: { position: "RB", q: [5, 10, 17] },
  [g(7)]: { position: "WR", q: [5, 12, 19.5] },
  [g(8)]: { position: "RB", q: [3, 7, 12] },
  [g(901)]: { name: "Test Back Ceiling", position: "RB", q: [2, 11, 22] },
  [g(902)]: { name: "Test Back Quiet", position: "RB", q: [3, 12, 25] },
  [g(903)]: { name: "Test Back Flat", position: "RB", q: [3, 12, 26] },
  [g(904)]: { name: "Test Back Hurt", position: "RB", q: [3, 12, 27], designation: "Out" },
  [g(905)]: { name: "Test Back Locked", position: "RB", q: [3, 12, 28], kickoff: "2026-08-22T09:00:00Z" },
  [g(906)]: { name: "Test Back Low", position: "RB", q: [3, 9, 16] },
};
// Twelve backs with positive net adds: the bar is the median, (500 + 600) / 2 = 550.
const RB_POOL: Record<string, { position: Position; net: number }> = {
  [g(901)]: { position: "RB", net: 9000 },
  [g(902)]: { position: "RB", net: 350 },
  [g(903)]: { position: "RB", net: 8000 },
  [g(904)]: { position: "RB", net: 7000 },
  [g(905)]: { position: "RB", net: 6500 },
  [g(906)]: { position: "RB", net: 6000 },
  [g(907)]: { position: "RB", net: 100 },
  [g(908)]: { position: "RB", net: 200 },
  [g(909)]: { position: "RB", net: 300 },
  [g(910)]: { position: "RB", net: 400 },
  [g(911)]: { position: "RB", net: 500 },
  [g(912)]: { position: "RB", net: 600 },
};
const RB_USAGE = [
  usage(g(901), "RB", "up"),
  usage(g(902), "RB", "up"),
  usage(g(903), "RB", "down"),
  usage(g(904), "RB", "up"),
  usage(g(905), "RB", "up"),
  usage(g(906), "RB", "up"),
];

function yolo(
  input: SetupInput,
  bundle: InSeasonBundle,
  owned: Iterable<string> = [],
  marks: Readonly<Record<string, "available" | "unavailable">> = {},
): YoloSelection {
  return selectYolo({
    bundle,
    leaguePreset: "redraft-12",
    scoring: "PPR",
    context: input.context,
    baseline: readSetup(input).mine,
    owned: new Set(owned),
    marks,
  });
}

describe("YOLO", () => {
  const input = setupInput({}, YOLO_SPECS);
  const bundle = yoloBundle(opportunityRows(RB_POOL), RB_USAGE);

  it("the acceptance case: a rising back with qualifying net adds is '+5 ceiling' over RB2 (17 → 22)", () => {
    const selection = yolo(input, bundle);
    expect(selection.kind).toBe("ready");
    if (selection.kind !== "ready") return;
    const pick = required(selection.candidates.find((candidate) => candidate.id === g(901)), "the ceiling back");
    expect(pick.slot.slot).toEqual({ group: "RB", index: 1 });
    expect(pick.incumbentQ90).toBe(17);
    expect(pick.q90).toBe(22);
    expect(pick.ceilingGain).toBe(5);
    expect(pick.netAdds).toBe(9000);
    const rb = required(selection.funnels.find((funnel) => funnel.position === "RB"), "RB funnel");
    expect(rb.bar).toEqual({ position: "RB", pool: 12, threshold: 550 });
    expect(pick.bar.threshold).toBe(550);
    expect(pick.role.direction).toBe("up");
  });

  it("admits only high net adds, a rising role, a playable week and a higher ceiling", () => {
    const selection = yolo(input, bundle);
    if (selection.kind !== "ready") throw new Error("expected ready");
    const ids = selection.candidates.map((candidate) => candidate.id);
    expect(ids).toEqual([g(901)]);
    const rb = required(selection.funnels.find((funnel) => funnel.position === "RB"), "RB funnel");
    // 901, 903–906 and 912 clear 550; 912 has no role series and 903's role fell; 904 is out
    // and 905 has kicked off; 906's ceiling (16) beats nobody's.
    expect(rb).toMatchObject({ highAdds: 6, rising: 4, playable: 2, unowned: 2, ceiling: 1 });
    expect(ids).not.toContain(g(902)); // rising and the highest ceiling, but net adds under the bar
  });

  it("a small pool, a missing count, a missing or stale feed and no role series qualify nobody", () => {
    const small = yoloBundle(opportunityRows({ [g(901)]: { position: "RB", net: 9000 }, [g(902)]: { position: "RB", net: 800 } }), RB_USAGE);
    const tiny = yolo(input, small);
    if (tiny.kind !== "ready") throw new Error("expected ready");
    expect(tiny.candidates).toEqual([]);
    expect(tiny.funnels.find((funnel) => funnel.position === "RB")?.bar).toEqual({ position: "RB", pool: 2, threshold: null });
    expect(netAddBar(opportunityRows({ [g(901)]: { position: "RB", net: null } }), "RB").pool).toBe(0);
    expect(yolo(input, yoloBundle(opportunityRows(RB_POOL, false), RB_USAGE, { behavior: false }))).toMatchObject({ kind: "unavailable", reason: "behavior_missing" });
    const later = setupInput({ context: contextFor(YOLO_SPECS, Date.parse("2026-08-24T12:00:00Z")) }, YOLO_SPECS);
    expect(yolo(later, bundle)).toMatchObject({ kind: "unavailable", reason: "behavior_stale" });
    expect(yolo(input, yoloBundle(opportunityRows(RB_POOL), RB_USAGE, { usage: false }))).toMatchObject({ kind: "unavailable", reason: "no_usage" });
  });

  it("excludes my roster, every known opponent player and players marked unavailable", () => {
    for (const owned of [[g(901)], ["gsis:00-0000999", g(901)]]) {
      const selection = yolo(input, bundle, owned);
      if (selection.kind !== "ready") throw new Error("expected ready");
      expect(selection.candidates).toEqual([]);
    }
    const marked = yolo(input, bundle, [], { [g(901)]: "unavailable" });
    if (marked.kind !== "ready") throw new Error("expected ready");
    expect(marked.candidates).toEqual([]);
    expect(marked.markedUnavailable).toEqual([g(901)]);
    const confirmed = yolo(input, bundle, [], { [g(901)]: "available" });
    if (confirmed.kind !== "ready") throw new Error("expected ready");
    expect(confirmed.candidates[0]?.mark).toBe("available");
  });

  it("caps the list per position and overall, deterministically", () => {
    const pool: Record<string, { position: Position; net: number }> = {};
    const specs: Record<string, Spec> = { ...YOLO_SPECS };
    const usages: PlayerUsageRecord[] = [];
    // Per position, five high net-add risers above five quiet rows: ten qualify in all.
    for (let i = 0; i < 20; i += 1) {
      const id = g(930 + i);
      const position: Position = i % 2 === 0 ? "RB" : "WR";
      const high = i < 10;
      pool[id] = { position, net: high ? 10_000 + i : 10 + i };
      specs[id] = { position, q: [3, 12, 30 + (i % 3)] };
      usages.push(usage(id, position, "up"));
    }
    const many = yoloBundle(opportunityRows(pool), usages);
    const selection = yolo(setupInput({}, specs), many);
    if (selection.kind !== "ready") throw new Error("expected ready");

    expect(selection.candidates.length).toBeLessThanOrEqual(YOLO_MAX);
    for (const position of ["RB", "WR"]) {
      expect(selection.candidates.filter((candidate) => candidate.position === position).length).toBeLessThanOrEqual(YOLO_PER_POSITION);
    }
    const again = yolo(setupInput({}, specs), many);
    if (again.kind !== "ready") throw new Error("expected ready");
    expect(again.candidates.map((candidate) => candidate.id)).toEqual(selection.candidates.map((candidate) => candidate.id));
    expect(selection.beyondCap).toBeGreaterThan(0);
    const gains = selection.candidates.map((candidate) => candidate.ceilingGain);
    expect([...gains].sort((a, b) => b - a)).toEqual(gains);
  });

  it("builds the legal lineup: the incumbent to a free bench slot, or a drop when the bench is full", () => {
    const selection = yolo(input, bundle);
    if (selection.kind !== "ready") throw new Error("expected ready");
    const pick = required(selection.candidates[0], "pick");
    const proposal = yoloProposal(pick, input);
    expect(proposal.roster.RB).toEqual([g(2), g(901)]);
    expect(proposal.needsDrop).toBe(false);
    expect(proposal.benchTo).toEqual({ group: "BN", index: 2 });
    expect(proposal.roster.BN[2]).toBe(g(3));
    const full = rosterOf({ QB: [g(1)], RB: [g(2), g(3)], WR: [g(4), g(5)], TE: [g(6)], FLEX: [g(7)], BN: [g(8), g(9), "gsis:00-0000921", "gsis:00-0000922", "gsis:00-0000923"] });
    const fullInput = { ...input, league: league(full) };
    const crowded = yoloProposal(pick, fullInput);
    expect(crowded.needsDrop).toBe(true);
    expect(crowded.mine.find((line) => line.slot.group === "RB" && line.slot.index === 1)?.id).toBe(g(901));
  });

  it("a QB pickup never takes FLEX", () => {
    const qbPool: Record<string, { position: Position; net: number }> = {};
    const specs: Record<string, Spec> = { ...YOLO_SPECS };
    const usages: PlayerUsageRecord[] = [];
    for (let i = 0; i < 5; i += 1) {
      const id = g(960 + i);
      qbPool[id] = { position: "QB", net: 1000 + i };
      specs[id] = { position: "QB", q: [10, 18, 40] };
      usages.push(usage(id, "QB", "up"));
    }
    const selection = yolo(setupInput({}, specs), yoloBundle(opportunityRows(qbPool), usages));
    if (selection.kind !== "ready") throw new Error("expected ready");
    expect(selection.candidates.length).toBeGreaterThan(0);
    for (const candidate of selection.candidates) expect(candidate.slot.slot.group).toBe("QB");
  });

  it("a higher ceiling can lower the chance to win, and the comparison says so", () => {
    // A heavy favourite: my lineup is far ahead. The YOLO back has the same median as a very
    // steady incumbent and a far wider range: the team's 90th percentile rises, and so does the
    // chance of a bad week — the favourite wins less often.
    const specs: Record<string, Spec> = {
      ...YOLO_SPECS,
      [g(3)]: { position: "RB", q: [14.5, 15, 15.5] },
      [g(901)]: { name: "Test Back Ceiling", position: "RB", q: [3, 15, 30] },
      [g(11)]: { position: "QB", q: [6, 11, 16], team: "BBB", game: "G1" },
      [g(12)]: { position: "RB", q: [2, 6, 10] },
      [g(14)]: { position: "WR", q: [2, 6, 10] },
    };
    const favoured = setupInput({}, specs);
    const selection = yolo(favoured, bundle);
    if (selection.kind !== "ready") throw new Error("expected ready");
    const pick = required(selection.candidates.find((candidate) => candidate.id === g(901)), "the ceiling back");
    expect(pick.ceilingGain).toBe(14.5);
    const proposal = yoloProposal(pick, favoured);
    const { result } = simulate(favoured, [proposal]);
    const delta = required(required(result.variants[1], "yolo").paired, "paired");
    expect(delta.p90).toBeGreaterThan(0);
    expect(delta.win).toBeLessThan(0);
    expect(meaningfulDelta(delta)).toBe(true);
  });
});
