/**
 * Auto Start/Sit (ADR-106, `lineup_assignment_v1`): an exhaustive oracle over small rosters,
 * exact FLEX use, deterministic ties that keep the reader's lineup, incomplete lineups with
 * their reasons, IR exclusion, kickoff locks, conditional injuries, bye and pending weeks, and
 * records for another target week.
 */

import { describe, expect, it } from "vitest";

import type { Availability } from "../src/data/availability";
import { readAvailability } from "../src/data/availability";
import type { Position, WeeklyProjectionRecord } from "../src/data/contracts";
import {
  DEFAULT_SLOTS,
  emptyRoster,
  type LineupMode,
  type Roster,
  type SlotCounts,
  type SlotGroup,
} from "../src/data/leagueContract";
import {
  compareObjective,
  hungarian,
  objectiveOf,
  optimizeLineup,
  pairValue,
  readWeek,
  readWeeks,
  type AssignmentProblem,
  type Objective,
  type WeekContext,
} from "../src/data/lineup";
import { rosterIds as rosterIdsForTest } from "../src/data/leagueContract";
import { checkRoster } from "../src/data/roster";
import { required } from "./required";

const WEEK = 9;
const NOW = Date.parse("2026-11-08T12:00:00Z");
const EARLY = "2026-11-08T18:00:00Z";
const LATE = "2026-11-09T01:20:00Z";

interface Spec {
  readonly position: Position;
  readonly q50: number;
  readonly q10?: number;
  readonly q90?: number;
  readonly state?: WeeklyProjectionRecord["game_state"];
  readonly kickoff?: string | null;
  readonly week?: number;
  readonly designation?: "Out" | "Doubtful" | "Questionable" | null;
  readonly noRecord?: boolean;
  readonly unknown?: boolean;
}

function record(id: string, spec: Spec): WeeklyProjectionRecord {
  const q50 = spec.q50;
  const q10 = spec.q10 ?? Math.round(q50 * 0.5 * 100) / 100;
  const q90 = spec.q90 ?? Math.round(q50 * 1.6 * 100) / 100;
  const state = spec.state ?? "upcoming";
  const bye = state === "bye";
  return {
    schema_version: "1.1",
    build_id: "test",
    season: 2026,
    through_week: WEEK - 1,
    target_week: spec.week ?? WEEK,
    player_id: id,
    display_name: id,
    position: spec.position,
    team: "BUF",
    scoring_preset: "PPR",
    model_version: "weekly-startsit-v1",
    game_state: state,
    game: bye
      ? null
      : {
          game_id: "g",
          opponent: "MIA",
          home_away: "home",
          neutral_site: false,
          kickoff_utc: spec.kickoff === undefined ? EARLY : spec.kickoff,
          roof: null,
          total_line: 45,
          team_margin: 3,
          team_points: 24,
        },
    quantiles:
      bye || state === "lines_pending"
        ? null
        : { q05: q10 - 1, q10, q25: (q10 + q50) / 2, q50, q75: (q50 + q90) / 2, q90, q95: q90 + 1 },
    drivers: null,
    explanation: null,
    opponent: null,
    injury: spec.designation === undefined || spec.designation === null ? null : { week: WEEK, designation: spec.designation, practice_status: null, primary_injury: null },
  };
}

const HEALTHY: Availability = readAvailability({
  status: {
    player_id: "x",
    roster_status: "ACT",
    sleeper_status: "Active",
    injury_status: null,
    observed_at_utc: "2026-11-08T10:00:00Z",
    quality_flags: [],
  },
  referenceTime: "2026-11-08T11:00:00Z",
  season: 2026,
});

function availabilityFor(spec: Spec | undefined): Availability {
  if (spec?.designation == null) return HEALTHY;
  return readAvailability({
    status: {
      player_id: "x",
      roster_status: "ACT",
      sleeper_status: "Active",
      injury_status: spec.designation,
      observed_at_utc: "2026-11-08T10:00:00Z",
      quality_flags: [],
    },
    referenceTime: "2026-11-08T11:00:00Z",
    season: 2026,
  });
}

function contextFor(specs: Readonly<Record<string, Spec>>, now = NOW): WeekContext {
  return {
    weeklyFor: (id) => {
      const spec = specs[id];
      return spec === undefined || spec.noRecord === true ? null : record(id, spec);
    },
    availabilityFor: (id) => availabilityFor(specs[id]),
    positionOf: (id) => (specs[id]?.unknown === true ? null : (specs[id]?.position ?? null)),
    targetWeek: WEEK,
    now,
  };
}

function roster(counts: SlotCounts, groups: Partial<Record<SlotGroup, (string | null)[]>>): Roster {
  const base = emptyRoster(counts);
  const out: Record<string, (string | null)[]> = {};
  for (const [group, slots] of Object.entries(base)) {
    const given = groups[group as SlotGroup] ?? [];
    out[group] = slots.map((_, index) => given[index] ?? null);
  }
  return out as unknown as Roster;
}

const SMALL: SlotCounts = { QB: 1, RB: 1, WR: 1, TE: 0, FLEX: 1, BN: 3, IR: 1 };

// ------------------------------------------------------------------------------ the oracle

/** Every complete placement, enumerated; the best objective under `compareObjective`. */
function oracle(problem: AssignmentProblem): Objective | null {
  let best: Objective | null = null;
  const used = new Array<boolean>(problem.slots.length).fill(false);
  const assignment: number[] = [];
  const visit = (index: number): void => {
    if (index === problem.players.length) {
      const objective = objectiveOf(problem, assignment);
      if (best === null || compareObjective(objective, best) > 0) best = objective;
      return;
    }
    const player = problem.players[index];
    if (player === undefined) return;
    problem.slots.forEach((slot, slotIndex) => {
      if (used[slotIndex] === true) return;
      if (pairValue(player, slot, problem) === null) return;
      used[slotIndex] = true;
      assignment.push(slotIndex);
      visit(index + 1);
      assignment.pop();
      used[slotIndex] = false;
    });
  };
  visit(0);
  return best;
}

/** A tiny deterministic generator (mulberry32). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("the solver against an exhaustive oracle", () => {
  it("matches the oracle's objective on 400 random small rosters, in every mode", () => {
    const random = rng(20261013);
    const positions: Position[] = ["QB", "RB", "WR", "TE"];
    const modes: LineupMode[] = ["q50", "q10", "q90"];
    for (let trial = 0; trial < 400; trial += 1) {
      const counts: SlotCounts = {
        QB: 1,
        RB: 1 + Math.floor(random() * 2),
        WR: 1 + Math.floor(random() * 2),
        TE: Math.floor(random() * 2),
        FLEX: Math.floor(random() * 3),
        BN: 1 + Math.floor(random() * 3),
        IR: 1,
      };
      const specs: Record<string, Spec> = {};
      const total = counts.QB + counts.RB + counts.WR + counts.TE + counts.FLEX + counts.BN;
      const playerCount = Math.min(total, 3 + Math.floor(random() * (total - 2)));
      const ids: string[] = [];
      for (let i = 0; i < playerCount; i += 1) {
        const id = `gsis:00-00000${String(10 + i)}`;
        ids.push(id);
        const roll = random();
        specs[id] = {
          position: positions[Math.floor(random() * 4)] ?? "RB",
          // Coarse values make ties common, which is where tie-breaking has to be right.
          q50: Math.round(random() * 6) * 2,
          q10: Math.round(random() * 4),
          q90: Math.round(random() * 8) * 3,
          state: roll < 0.08 ? "bye" : roll < 0.12 ? "lines_pending" : "upcoming",
          kickoff: roll > 0.92 ? "2026-11-08T08:00:00Z" : EARLY,
          designation: roll > 0.85 && roll <= 0.92 ? (random() < 0.5 ? "Out" : "Questionable") : null,
        };
      }
      // A legal random current roster: place each player in a random slot that accepts him.
      const groups: Record<string, (string | null)[]> = Object.fromEntries(
        (Object.keys(counts) as SlotGroup[]).map((group) => [group, new Array<string | null>(counts[group]).fill(null)]),
      );
      for (const id of ids) {
        const position = specs[id]?.position ?? "RB";
        const open = (Object.keys(counts) as SlotGroup[])
          .filter((group) => group !== "IR")
          .flatMap((group) =>
            (groups[group] ?? []).map((occupant, index) => ({ group, index, occupant })),
          )
          .filter(
            ({ group, occupant }) =>
              occupant === null &&
              (group === "BN" ||
                group === position ||
                (group === "FLEX" && position !== "QB")),
          );
        const choice = open[Math.floor(random() * open.length)];
        if (choice === undefined) continue;
        (groups[choice.group] ?? [])[choice.index] = id;
      }
      const current = groups as unknown as Roster;
      const context = contextFor(specs);
      for (const mode of modes) {
        const proposal = optimizeLineup(current, counts, context, mode);
        // Rebuild the problem the proposal solved, for the oracle.
        const weeks = readWeeks(current, context);
        const players = (Object.keys(counts) as SlotGroup[])
          .filter((group) => group !== "IR")
          .flatMap((group) =>
            (current[group] ?? []).flatMap((id, index) =>
              id === null ? [] : [{ id, slot: { group, index } }],
            ),
          )
          .map((entry) => ({ week: weeks.get(entry.id), current: entry.slot }))
          .filter((entry) => entry.week !== undefined && entry.week.kind !== "locked" && entry.week.kind !== "pinned")
          .map((entry) => ({ week: required(entry.week, entry.current.group), current: entry.current }));
        const fixedSlots = new Set(
          proposal.fixed.map((week) => {
            for (const group of Object.keys(counts) as SlotGroup[]) {
              const index = current[group].indexOf(week.id);
              if (index >= 0) return `${group}:${String(index)}`;
            }
            return "";
          }),
        );
        const slots = (Object.keys(counts) as SlotGroup[])
          .filter((group) => group !== "IR")
          .flatMap((group) => Array.from({ length: counts[group] }, (_, index) => ({ group, index })))
          .filter((slot) => !fixedSlots.has(`${slot.group}:${String(slot.index)}`));
        const candidates = players.filter((player) => player.week.kind === "candidate").map((player) => player.week.id).sort();
        const preference = new Map(candidates.map((id, index) => [id, candidates.length - 1 - index]));
        const best = oracle({ players, slots, preference, mode });
        expect(best).not.toBeNull();
        expect(compareObjective(proposal.objective, required(best, "the oracle's best"))).toBe(0);
        // Every proposal is a legal roster of the same players, with IR untouched.
        expect(checkRoster(proposal.roster, counts, context.positionOf)).toEqual([]);
        expect(rosterIdsForTest(proposal.roster).sort()).toEqual(rosterIdsForTest(current).sort());
        expect(proposal.roster.IR).toEqual(current.IR);
      }
    }
  });

  it("solves a textbook assignment", () => {
    const cost = [
      [4, 1, 3],
      [2, 0, 5],
      [3, 2, 2],
    ];
    const assignment = hungarian(cost, 3);
    const total = assignment.reduce((sum, column, row) => sum + (cost[row]?.[column] ?? 0), 0);
    expect(total).toBe(5);
  });

  it("refuses a forbidden-only row rather than inventing a placement", () => {
    expect(() => hungarian([[Infinity, Infinity]], 2)).toThrow("no feasible assignment");
  });
});

describe("what the lineup maximises", () => {
  it("uses FLEX on the best remaining back, receiver or tight end, never on a quarterback", () => {
    const specs: Record<string, Spec> = {
      qb1: { position: "QB", q50: 20 },
      qb2: { position: "QB", q50: 19 },
      rb1: { position: "RB", q50: 12 },
      rb2: { position: "RB", q50: 11 },
      wr1: { position: "WR", q50: 9 },
      te1: { position: "TE", q50: 10 },
    };
    const current = roster(SMALL, { QB: ["qb1"], RB: ["rb2"], WR: ["wr1"], FLEX: ["te1"], BN: ["qb2", "rb1"] });
    const proposal = optimizeLineup(current, SMALL, contextFor(specs), "q50");
    // Both backs start; the one already at RB stays there (the reader's lineup wins the tie)
    // and the bench back takes FLEX from the tight end. The second QB never gets near FLEX.
    expect(proposal.roster.RB).toEqual(["rb2"]);
    expect(proposal.roster.FLEX).toEqual(["rb1"]);
    expect(proposal.roster.QB).toEqual(["qb1"]);
    expect(proposal.roster.BN).toContain("qb2");
    expect(proposal.total).toBeCloseTo(20 + 12 + 9 + 11, 6);
  });

  it("assigns jointly: a greedy slot-by-slot pick would waste the FLEX", () => {
    // A slot-by-slot pick that filled FLEX first would spend the 15-point back there and leave
    // the RB slot to a 6-point back; and the second tight end (7) belongs in FLEX over him.
    const counts: SlotCounts = { QB: 1, RB: 1, WR: 1, TE: 1, FLEX: 1, BN: 3, IR: 0 };
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      rb: { position: "RB", q50: 15 },
      rb2: { position: "RB", q50: 6 },
      wr: { position: "WR", q50: 10 },
      te: { position: "TE", q50: 8 },
      te2: { position: "TE", q50: 7 },
    };
    const current = roster(counts, { QB: ["qb"], BN: ["rb", "rb2", "wr"], TE: ["te2"], FLEX: ["te"] });
    const proposal = optimizeLineup(current, counts, contextFor(specs), "q50");
    expect(proposal.roster.TE).toEqual(["te2"]);
    expect(proposal.roster.FLEX).toEqual(["te"]);
    expect(proposal.total).toBeCloseTo(18 + 15 + 10 + 8 + 7, 6);
    expect(proposal.moves.map((move) => move.id).sort()).toEqual(["rb", "wr"]);
  });

  it("follows the chosen quantile: floor and ceiling can pick different players", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      steady: { position: "RB", q50: 10, q10: 7, q90: 13 },
      boom: { position: "RB", q50: 10, q10: 2, q90: 22 },
      wr: { position: "WR", q50: 9 },
    };
    const counts: SlotCounts = { QB: 1, RB: 1, WR: 1, TE: 0, FLEX: 0, BN: 2, IR: 0 };
    const current = roster(counts, { QB: ["qb"], RB: ["steady"], WR: ["wr"], BN: ["boom"] });
    const floor = optimizeLineup(current, counts, contextFor(specs), "q10");
    const ceiling = optimizeLineup(current, counts, contextFor(specs), "q90");
    expect(floor.roster.RB).toEqual(["steady"]);
    expect(ceiling.roster.RB).toEqual(["boom"]);
    // A tie on the median keeps the reader's choice.
    expect(optimizeLineup(current, counts, contextFor(specs), "q50").moves).toEqual([]);
  });

  it("keeps the reader's lineup on a tie, including which identical slot each player is in", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      a: { position: "RB", q50: 10 },
      b: { position: "RB", q50: 10 },
      c: { position: "RB", q50: 10 },
      wr: { position: "WR", q50: 9 },
    };
    const counts: SlotCounts = { QB: 1, RB: 2, WR: 1, TE: 0, FLEX: 0, BN: 2, IR: 0 };
    const current = roster(counts, { QB: ["qb"], RB: ["c", "b"], WR: ["wr"], BN: ["a"] });
    const proposal = optimizeLineup(current, counts, contextFor(specs), "q50");
    expect(proposal.moves).toEqual([]);
    expect(proposal.roster.RB).toEqual(["c", "b"]);
  });

  it("breaks a tie between two bench players by canonical id, and places a newcomer deterministically", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      "gsis:00-0000002": { position: "RB", q50: 10 },
      "gsis:00-0000001": { position: "RB", q50: 10 },
      wr: { position: "WR", q50: 9 },
    };
    const counts: SlotCounts = { QB: 1, RB: 1, WR: 1, TE: 0, FLEX: 0, BN: 2, IR: 0 };
    const current = roster(counts, { QB: ["qb"], WR: ["wr"], BN: ["gsis:00-0000002", "gsis:00-0000001"] });
    const first = optimizeLineup(current, counts, contextFor(specs), "q50");
    const swapped = roster(counts, { QB: ["qb"], WR: ["wr"], BN: ["gsis:00-0000001", "gsis:00-0000002"] });
    const second = optimizeLineup(swapped, counts, contextFor(specs), "q50");
    expect(first.roster.RB).toEqual(["gsis:00-0000001"]);
    expect(second.roster.RB).toEqual(["gsis:00-0000001"]);
  });
});

describe("who may be started", () => {
  it("never touches IR, even when IR holds the best player", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      star: { position: "RB", q50: 25 },
      rb: { position: "RB", q50: 8 },
      wr: { position: "WR", q50: 9 },
    };
    const current = roster(SMALL, { QB: ["qb"], RB: ["rb"], WR: ["wr"], IR: ["star"] });
    const proposal = optimizeLineup(current, SMALL, contextFor(specs), "q50");
    expect(proposal.roster.IR).toEqual(["star"]);
    expect(proposal.weeks.has("star")).toBe(false);
    expect(proposal.roster.RB).toEqual(["rb"]);
  });

  it("benches a bye and an out player when a replacement exists, and keeps one when none does", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      byeRb: { position: "RB", q50: 14, state: "bye" },
      outWr: { position: "WR", q50: 12, designation: "Out" },
      benchRb: { position: "RB", q50: 7 },
    };
    const counts: SlotCounts = { QB: 1, RB: 1, WR: 1, TE: 0, FLEX: 0, BN: 2, IR: 0 };
    const current = roster(counts, { QB: ["qb"], RB: ["byeRb"], WR: ["outWr"], BN: ["benchRb"] });
    const proposal = optimizeLineup(current, counts, contextFor(specs), "q50");
    expect(proposal.roster.RB).toEqual(["benchRb"]);
    expect(proposal.roster.WR).toEqual(["outWr"]);
    expect(proposal.gaps).toEqual([
      { slot: { group: "WR", index: 0 }, kind: "gap", reason: "Out this week. No eligible replacement on your roster." },
    ]);
    expect(proposal.filled).toBe(2);
    expect(proposal.total).toBeCloseTo(25, 6);
  });

  it("does not start a doubtful player, and starts a questionable one only if active", () => {
    const context = contextFor({
      d: { position: "RB", q50: 20, designation: "Doubtful" },
      q: { position: "RB", q50: 20, designation: "Questionable" },
    });
    expect(readWeek("d", context)).toMatchObject({ kind: "sidelined" });
    expect(readWeek("q", context)).toMatchObject({ kind: "candidate", conditional: true });
  });

  it("locks a game that has kicked off: a started starter stays, a started bench player is not promoted", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18, kickoff: LATE },
      startedStarter: { position: "RB", q50: 3, kickoff: EARLY },
      startedBench: { position: "RB", q50: 20, kickoff: EARLY },
      lateBench: { position: "WR", q50: 15, kickoff: LATE },
      wr: { position: "WR", q50: 5, kickoff: LATE },
    };
    const counts: SlotCounts = { QB: 1, RB: 1, WR: 1, TE: 0, FLEX: 0, BN: 3, IR: 0 };
    const current = roster(counts, { QB: ["qb"], RB: ["startedStarter"], WR: ["wr"], BN: ["startedBench", "lateBench"] });
    const after = Date.parse("2026-11-08T19:00:00Z");
    const proposal = optimizeLineup(current, counts, contextFor(specs, after), "q50");
    expect(proposal.roster.RB).toEqual(["startedStarter"]);
    expect(proposal.roster.BN).toContain("startedBench");
    expect(proposal.roster.WR).toEqual(["lateBench"]);
    expect(proposal.fixed.map((week) => week.id).sort()).toEqual(["startedBench", "startedStarter"]);
    // The locked starter's published median still counts toward the sum.
    expect(proposal.total).toBeCloseTo(18 + 3 + 15, 6);
  });

  it("locks every game from the build's own kicked-off state, whatever the clock says", () => {
    const context = contextFor({ k: { position: "RB", q50: 10, state: "kicked_off" } }, Date.parse("2026-01-01T00:00:00Z"));
    expect(readWeek("k", context).kind).toBe("locked");
  });

  it("leaves unknown weeks where they are: no record, pending line, unknown kickoff, unresolved id, another week", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      noRecord: { position: "RB", q50: 0, noRecord: true },
      pending: { position: "WR", q50: 0, state: "lines_pending" },
      noKickoff: { position: "RB", q50: 9, kickoff: null },
      unresolved: { position: "RB", q50: 0, unknown: true },
      otherWeek: { position: "WR", q50: 9, week: WEEK + 1 },
      benchRb: { position: "RB", q50: 30 },
      benchWr: { position: "WR", q50: 30 },
    };
    const counts: SlotCounts = { QB: 1, RB: 2, WR: 2, TE: 0, FLEX: 0, BN: 4, IR: 0 };
    const current = roster(counts, {
      QB: ["qb"],
      RB: ["noRecord", "noKickoff"],
      WR: ["pending", "otherWeek"],
      BN: ["benchRb", "benchWr", "unresolved"],
    });
    const context = contextFor(specs);
    for (const id of ["noRecord", "pending", "noKickoff", "unresolved", "otherWeek"]) {
      expect(readWeek(id, context).kind).toBe("pinned");
    }
    const proposal = optimizeLineup(current, counts, context, "q50");
    expect(proposal.moves).toEqual([]);
    expect(proposal.gaps.every((gap) => gap.kind === "unscored")).toBe(true);
    expect(proposal.total).toBeCloseTo(18, 6);
  });

  it("reports an empty slot nobody on the roster can fill, with the reason", () => {
    const specs: Record<string, Spec> = {
      qb: { position: "QB", q50: 18 },
      te: { position: "TE", q50: 6, state: "bye" },
    };
    const counts: SlotCounts = { QB: 1, RB: 1, WR: 1, TE: 1, FLEX: 0, BN: 1, IR: 0 };
    const current = roster(counts, { QB: ["qb"], BN: ["te"] });
    const proposal = optimizeLineup(current, counts, contextFor(specs), "q50");
    const reasons = Object.fromEntries(proposal.gaps.map((gap) => [gap.slot.group, gap.reason]));
    expect(reasons.RB).toBe("Nobody on your roster can fill this slot.");
    expect(reasons.TE).toBe("No eligible player: te (Bye in week 9).");
    expect(proposal.filled).toBe(1);
    expect(proposal.starterSlots).toBe(4);
  });

  it("is a no-op on an empty roster", () => {
    const proposal = optimizeLineup(emptyRoster(DEFAULT_SLOTS), DEFAULT_SLOTS, contextFor({}), "q50");
    expect(proposal.moves).toEqual([]);
    expect(proposal.total).toBe(0);
    expect(proposal.gaps).toHaveLength(7);
  });
});
