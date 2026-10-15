/**
 * The Win My Matchup engine (ADR-110, `matchup_sim_v1`): the statistical properties the page's
 * numbers rest on, each against an independent reference — an exact enumeration, Start/Sit's
 * Python-golden-tested arithmetic, or a symmetry that must hold draw for draw.
 */

import { describe, expect, it } from "vitest";

import {
  MATCHUP_ENGINE_VERSION,
  MATCHUP_MAX_DRAWS,
  MATCHUP_SEED,
  choleskyFactor,
  createRun,
  marginBins,
  meaningfulDelta,
  percentLabel,
  simulateMatchup,
  tieLabel,
  uniformAt,
  playerStream,
  validateSimInput,
  type SimGroup,
  type SimInput,
  type SimPlayer,
  type SimResult,
  type SimSlot,
  type VariantResult,
} from "../src/data/matchup";
import { distributionRule, gridFromQuantiles, knots, probGreater, probGreaterCorrelated } from "../src/data/startsit";
import { required } from "./required";

/** The `index`th lineup of a result. */
function variant(result: SimResult, index = 0): VariantResult {
  return required(result.variants[index], `variant ${String(index)}`);
}

const RULE = distributionRule(null);
/** The build's latent correlations (live metadata, 2026-10-15). */
const LIVE_RHO: Record<string, number> = {
  "opponents:any": 0.0292,
  "teammates:QB-RB": 0.005,
  "teammates:QB-TE": 0.2673,
  "teammates:QB-WR": 0.3191,
  "teammates:RB-RB": -0.098,
  "teammates:RB-TE": -0.0445,
  "teammates:RB-WR": -0.0218,
  "teammates:TE-WR": -0.0329,
  "teammates:WR-WR": 0.0405,
};

function published(key: string, quantiles: readonly number[], options: Partial<SimPlayer> = {}): SimPlayer {
  const { taus, values } = knots(quantiles, RULE);
  return { key, taus, values, game: options.game ?? `g-${key}`, team: options.team ?? `T-${key}`, position: options.position ?? "WR" };
}

function constant(key: string, points: number, options: Partial<SimPlayer> = {}): SimPlayer {
  return { key, taus: [0, 1], values: [points, points], game: options.game ?? null, team: options.team ?? "X", position: options.position ?? "RB" };
}

/** Low or high with probability ½ each: an exact small-support distribution. */
function twoPoint(key: string, low: number, high: number, options: Partial<SimPlayer> = {}): SimPlayer {
  return {
    key,
    taus: [0, 0.5, 0.5, 1],
    values: [low, low, high, high],
    game: options.game ?? null,
    team: options.team ?? `T-${key}`,
    position: options.position ?? "WR",
  };
}

const slot = (group: SimGroup, player: number, fixed = 0): SimSlot => ({ group, player, fixed });

function input(players: SimPlayer[], mine: SimSlot[], theirs: SimSlot[], extra: Partial<SimInput> = {}): SimInput {
  return {
    version: MATCHUP_ENGINE_VERSION,
    seed: MATCHUP_SEED,
    draws: 8192,
    players,
    correlation: LIVE_RHO,
    opponent: theirs,
    variants: [{ id: "base", slots: mine, detail: true }],
    ...extra,
  };
}

// Realistic published shapes (PPR): seven quantiles q05…q95.
const QB = [8.1, 10.6, 14.6, 19.0, 23.3, 27.4, 30.2];
const RB = [2.4, 4.0, 7.3, 11.6, 16.2, 21.0, 24.4];
const WR = [1.8, 3.4, 6.9, 11.4, 16.6, 21.9, 25.6];
const TE = [0.6, 1.6, 3.9, 7.1, 10.8, 14.6, 17.3];
const NEG = [-1.2, 0.4, 3.0, 6.5, 10.1, 13.8, 16.2];

function standardTeam(prefix: string, shapes = { QB, RB, WR, TE }): { players: SimPlayer[]; slots: (offset: number) => SimSlot[] } {
  const players = [
    published(`${prefix}qb`, shapes.QB, { position: "QB" }),
    published(`${prefix}rb1`, shapes.RB, { position: "RB" }),
    published(`${prefix}rb2`, shapes.RB, { position: "RB" }),
    published(`${prefix}wr1`, shapes.WR, { position: "WR" }),
    published(`${prefix}wr2`, shapes.WR, { position: "WR" }),
    published(`${prefix}te`, shapes.TE, { position: "TE" }),
    published(`${prefix}fx`, shapes.WR, { position: "WR" }),
  ];
  const groups: SimGroup[] = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"];
  return { players, slots: (offset) => groups.map((group, index) => slot(group, offset + index)) };
}

/** Within `k` binomial standard errors of `expected` at `draws` (plus a small absolute floor). */
function near(actual: number, expected: number, draws: number, k = 4.5, floor = 0.002): void {
  const se = Math.sqrt(Math.max(expected * (1 - expected), 1e-6) / draws);
  expect(Math.abs(actual - expected)).toBeLessThanOrEqual(k * se + floor);
}

describe("validation", () => {
  const base = (): SimInput => input([constant("a", 10), constant("b", 9)], [slot("RB", 0)], [slot("RB", 1)]);

  it("accepts a well-formed input", () => {
    expect(validateSimInput(base())).toBeNull();
  });

  it("refuses the wrong engine version, too many draws, and bad seeds", () => {
    expect(validateSimInput({ ...base(), version: "matchup_sim_v0" })).toMatch(/version/);
    expect(validateSimInput({ ...base(), draws: MATCHUP_MAX_DRAWS + 1 })).toMatch(/draws/);
    expect(validateSimInput({ ...base(), draws: 0 })).toMatch(/draws/);
    expect(validateSimInput({ ...base(), seed: 1.5 })).toMatch(/seed/);
    expect(() => createRun({ ...base(), draws: MATCHUP_MAX_DRAWS + 1 })).toThrow(/draws/);
  });

  it("refuses decreasing or non-finite knots, and knots that do not span 0–1", () => {
    const bad = { ...constant("a", 10), values: [10, 9] };
    expect(validateSimInput({ ...base(), players: [bad, constant("b", 9)] })).toMatch(/decrease/);
    const nan = { ...constant("a", 10), values: [Number.NaN, 1] };
    expect(validateSimInput({ ...base(), players: [nan, constant("b", 9)] })).toMatch(/finite/);
    const short = { ...constant("a", 10), taus: [0.1, 1] };
    expect(validateSimInput({ ...base(), players: [short, constant("b", 9)] })).toMatch(/span/);
  });

  it("refuses a player twice in one lineup, on both teams, or out of range", () => {
    expect(validateSimInput({ ...base(), variants: [{ id: "base", slots: [slot("RB", 0), slot("FLEX", 0)], detail: true }] })).toMatch(/twice/);
    expect(validateSimInput({ ...base(), opponent: [slot("RB", 0)] })).toMatch(/shares a player/);
    expect(validateSimInput({ ...base(), opponent: [slot("RB", 7)] })).toMatch(/out of range/);
    expect(validateSimInput({ ...base(), opponent: [] })).toMatch(/no starters/);
  });

  it("refuses a correlation outside (−1, 1) and duplicate keys", () => {
    expect(validateSimInput({ ...base(), correlation: { "opponents:any": 1 } })).toMatch(/correlation/);
    expect(validateSimInput({ ...base(), players: [constant("a", 1), constant("a", 2)] })).toMatch(/unique/);
  });
});

describe("the generator", () => {
  it("is a function of the seed, the player's id and the draw only", () => {
    const stream = playerStream(MATCHUP_SEED, "gsis:00-0000001");
    expect(uniformAt(stream, 17)).toBe(uniformAt(playerStream(MATCHUP_SEED, "gsis:00-0000001"), 17));
    expect(uniformAt(stream, 17)).not.toBe(uniformAt(stream, 18));
    expect(uniformAt(stream, 17)).not.toBe(uniformAt(playerStream(MATCHUP_SEED + 1, "gsis:00-0000001"), 17));
  });

  it("is uniform enough: mean, variance and two players' correlation", () => {
    const a = playerStream(MATCHUP_SEED, "a");
    const b = playerStream(MATCHUP_SEED, "b");
    const n = 65536;
    let sa = 0;
    let saa = 0;
    let sab = 0;
    let sb = 0;
    for (let d = 0; d < n; d += 1) {
      const ua = uniformAt(a, d);
      const ub = uniformAt(b, d);
      expect(ua).toBeGreaterThan(0);
      expect(ua).toBeLessThan(1);
      sa += ua;
      sb += ub;
      saa += ua * ua;
      sab += ua * ub;
    }
    expect(Math.abs(sa / n - 0.5)).toBeLessThan(0.006);
    expect(Math.abs(saa / n - sa * sa / n / n - 1 / 12)).toBeLessThan(0.002);
    const cov = sab / n - (sa / n) * (sb / n);
    expect(Math.abs(cov * 12)).toBeLessThan(0.02);
  });
});

describe("reproducibility and invariance", () => {
  const me = standardTeam("m");
  const them = standardTeam("o");
  const players = [...me.players, ...them.players];
  const baseInput = input(players, me.slots(0), them.slots(7));

  it("gives the same story every time", () => {
    expect(simulateMatchup(baseInput)).toEqual(simulateMatchup(baseInput));
  });

  it("does not depend on the order of players or slots", () => {
    const order = players.map((_, index) => index).reverse();
    const shuffled = order.map((index) => required(players[index], "player"));
    const remap = (s: SimSlot): SimSlot => ({ ...s, player: s.player < 0 ? -1 : order.indexOf(s.player) });
    const reordered = input(
      shuffled,
      [...me.slots(0)].reverse().map(remap),
      [...them.slots(7)].map(remap).sort((a, b) => b.player - a.player),
    );
    const a = variant(simulateMatchup(baseInput), 0);
    const b = variant(simulateMatchup(reordered), 0);
    expect(b.win).toBe(a.win);
    expect(b.tie).toBe(a.tie);
    expect(b.mine).toEqual(a.mine);
    expect(b.groups?.map((group) => [group.group, group.ahead])).toEqual(a.groups?.map((group) => [group.group, group.ahead]));
  });

  it("probabilities are finite and sum to one", () => {
    const result = variant(simulateMatchup(baseInput), 0);
    for (const value of [result.win, result.tie, result.loss]) {
      expect(Number.isFinite(value)).toBe(true);
      expect(value).toBeGreaterThanOrEqual(0);
    }
    expect(result.win + result.tie + result.loss).toBeCloseTo(1, 12);
    expect(result.histogram.reduce((sum, count) => sum + count, 0)).toBe(8192);
  });

  it("swapping the two teams swaps win and loss exactly", () => {
    const swapped = input(players, them.slots(7), me.slots(0));
    const a = variant(simulateMatchup(baseInput), 0);
    const b = variant(simulateMatchup(swapped), 0);
    expect(b.win).toBe(a.loss);
    expect(b.loss).toBe(a.win);
    expect(b.tie).toBe(a.tie);
  });

  it("two identically distributed lineups are a coin flip", () => {
    const result = variant(simulateMatchup({ ...baseInput, draws: 32768 }), 0);
    near(result.win, 0.5, 32768);
    expect(result.tie).toBeLessThan(0.002);
  });
});

describe("deterministic lineups, ties and fixed scores", () => {
  it("a dominant deterministic lineup always wins, and no margin uncertainty is added", () => {
    const result = variant(simulateMatchup(input([constant("a", 10), constant("b", 9.99)], [slot("RB", 0)], [slot("RB", 1)])), 0);
    expect(result.win).toBe(1);
    expect(result.tie).toBe(0);
    expect(result.mine.p10).toBe(10);
    expect(result.margin.p50).toBeCloseTo(0.01, 10);
  });

  it("equal totals to the hundredth are ties, and never half-wins", () => {
    const result = variant(simulateMatchup(
      input([constant("a", 10.004), constant("b", 9.996)], [slot("RB", 0)], [slot("RB", 1)]),
    ), 0);
    expect(result.tie).toBe(1);
    expect(result.win).toBe(0);
    expect(result.loss).toBe(0);
  });

  it("fixed contributions count once, in their own group, and FLEX once", () => {
    const players = [constant("a", 7), constant("b", 3), constant("c", 12)];
    const mine = [slot("QB", -1, 21.36), slot("RB", 0), slot("FLEX", 1)];
    const theirs = [slot("QB", -1, 0), slot("RB", 2), slot("FLEX", -1, 0)];
    const result = variant(simulateMatchup(input(players, mine, theirs)), 0);
    expect(result.mine.p50).toBeCloseTo(31.36, 10);
    expect(result.win).toBe(1);
    const groups = new Map(result.groups?.map((group) => [group.group, group]));
    expect(groups.get("QB")?.mine.p50).toBeCloseTo(21.36, 10);
    expect(groups.get("FLEX")?.mine.p50).toBeCloseTo(3, 10);
    expect(groups.get("RB")?.ahead).toBe(0);
    expect(groups.get("FLEX")?.ahead).toBe(1);
    expect(groups.get("QB")?.ahead).toBe(1);
    expect([...groups.keys()]).toEqual(["QB", "RB", "FLEX"]);
  });
});

describe("an exact small-support oracle", () => {
  /** Enumerate every outcome of independent two-point players. */
  function exact(mine: [number, number][], theirs: [number, number][]): { win: number; tie: number } {
    const all = [...mine, ...theirs];
    let win = 0;
    let tie = 0;
    const outcomes = 2 ** all.length;
    for (let mask = 0; mask < outcomes; mask += 1) {
      let a = 0;
      let b = 0;
      all.forEach(([low, high], index) => {
        const value = (mask >> index) & 1 ? high : low;
        if (index < mine.length) a += value;
        else b += value;
      });
      const ah = Math.round(a * 100);
      const bh = Math.round(b * 100);
      if (ah > bh) win += 1;
      else if (ah === bh) tie += 1;
    }
    return { win: win / outcomes, tie: tie / outcomes };
  }

  it("matches enumeration for independent players, ties included", () => {
    const mine: [number, number][] = [
      [0, 10],
      [2, 6],
      [-1, 9],
    ];
    const theirs: [number, number][] = [
      [3, 8],
      [0, 12],
      [1, 5],
    ];
    const players = [...mine, ...theirs].map(([low, high], index) => twoPoint(`p${String(index)}`, low, high));
    const draws = 65536;
    const result = variant(simulateMatchup(
      input(
        players,
        mine.map((_, index) => slot("WR", index)),
        theirs.map((_, index) => slot("WR", mine.length + index)),
        { draws },
      ),
    ), 0);
    const truth = exact(mine, theirs);
    expect(truth.tie).toBeGreaterThan(0.02);
    near(result.win, truth.win, draws);
    near(result.tie, truth.tie, draws);
  });

  it("matches the bivariate-normal orthant probability for one same-game pair across teams", () => {
    // Opponents in one game, latent ρ = 0.5: P(both high) = ¼ + asin ρ / 2π.
    const rho = 0.5;
    const players = [
      twoPoint("me", 0, 10, { game: "G", team: "AAA" }),
      twoPoint("them", 0, 10, { game: "G", team: "BBB" }),
    ];
    const draws = 65536;
    const result = variant(simulateMatchup(
      input(players, [slot("WR", 0)], [slot("WR", 1)], { draws, correlation: { "opponents:any": rho } }),
    ), 0);
    const both = 0.25 + Math.asin(rho) / (2 * Math.PI);
    near(result.tie, 2 * both, draws);
    near(result.win, 0.5 - both, draws);
  });
});

describe("agreement with Start/Sit's arithmetic", () => {
  it("one player against one: P(win) + ½ P(tie) is probGreater", () => {
    const a = [4.1, 6.0, 9.4, 13.9, 19.0, 24.6, 28.8];
    const b = [6.0, 7.7, 10.6, 14.2, 18.1, 22.0, 24.6];
    const draws = 65536;
    const result = variant(simulateMatchup(
      input([published("a", a), published("b", b)], [slot("WR", 0)], [slot("WR", 1)], { draws }),
    ), 0);
    const reference = probGreater(gridFromQuantiles(a, RULE), gridFromQuantiles(b, RULE));
    near(result.win + 0.5 * result.tie, reference, draws, 4.5, 0.004);
  });

  it("same-game teammates: agrees with the copula grid (probGreaterCorrelated)", () => {
    const qb = [8.1, 10.6, 14.6, 19.0, 23.3, 27.4, 30.2];
    const wr = [5.0, 7.4, 11.9, 17.1, 22.6, 28.1, 31.9];
    const draws = 65536;
    const players = [
      published("qb", qb, { game: "G", team: "CIN", position: "QB" }),
      published("wr", wr, { game: "G", team: "CIN", position: "WR" }),
    ];
    const result = variant(simulateMatchup(input(players, [slot("QB", 0)], [slot("QB", 1)], { draws })), 0);
    const reference = probGreaterCorrelated(qb, wr, required(LIVE_RHO["teammates:QB-WR"], "QB-WR rho"), RULE);
    near(result.win + 0.5 * result.tie, reference, draws, 4.5, 0.004);
    // And it is not the independent answer: the correlation is used, at its latent value.
    const independent = probGreater(gridFromQuantiles(qb, RULE), gridFromQuantiles(wr, RULE));
    expect(Math.abs(reference - independent)).toBeGreaterThan(0.01);
  });
});

describe("the marginals as published", () => {
  it("reconstructs the published quantiles, tails and negative weeks", () => {
    const draws = 65536;
    const result = variant(simulateMatchup(
      input([published("x", NEG), constant("zero", 0)], [slot("WR", 0)], [slot("WR", 1)], { draws }),
    ), 0);
    expect(Math.abs(result.mine.p10 - required(NEG[1], "quantile"))).toBeLessThan(0.15);
    expect(Math.abs(result.mine.p25 - required(NEG[2], "quantile"))).toBeLessThan(0.15);
    expect(Math.abs(result.mine.p50 - required(NEG[3], "quantile"))).toBeLessThan(0.15);
    expect(Math.abs(result.mine.p90 - required(NEG[5], "quantile"))).toBeLessThan(0.15);
    // q05 is negative, so between 5% and 10% of his weeks lose points, and those count.
    expect(result.loss).toBeGreaterThan(0.05);
    expect(result.loss).toBeLessThan(0.1);
  });

  it("draws reach past q90 up to the published upper tail knot, never beyond", () => {
    const { values } = knots(WR, RULE);
    const draws = 65536;
    const run = simulateMatchup(input([published("x", WR), constant("c", 21.9)], [slot("WR", 0)], [slot("WR", 1)], { draws }));
    const first = variant(run, 0);
    // P(above q90) ≈ 10%: the ceiling is an upside percentile, not a cap.
    near(first.win, 0.1, draws, 4.5, 0.003);
    const upper = required(values[values.length - 1], "upper knot");
    expect(first.mine.p90).toBeLessThan(upper);
    expect(run.bins.start + run.bins.width * run.bins.count).toBeLessThanOrEqual(upper + run.bins.width * 2);
  });
});

describe("correlation blocks", () => {
  it("cross-team teammates move together: a narrower margin than independence", () => {
    // My QB against the opponent's receiver from the same NFL team.
    const draws = 32768;
    const shared = [
      published("qb", QB, { game: "G", team: "CIN", position: "QB" }),
      published("wr", WR, { game: "G", team: "CIN", position: "WR" }),
    ];
    const apart = [
      published("qb", QB, { game: "G1", team: "CIN", position: "QB" }),
      published("wr", WR, { game: "G2", team: "LAR", position: "WR" }),
    ];
    const together = variant(simulateMatchup(input(shared, [slot("QB", 0)], [slot("WR", 1)], { draws })), 0);
    const independent = variant(simulateMatchup(input(apart, [slot("QB", 0)], [slot("WR", 1)], { draws })), 0);
    expect(together.margin.p90 - together.margin.p10).toBeLessThan(independent.margin.p90 - independent.margin.p10 - 0.5);
  });

  it("a block that is not a valid correlation matrix is simulated independently and named", () => {
    const three = ["a", "b", "c"].map((key) => published(key, WR, { game: "G", team: "KC", position: "WR" }));
    const opponent = [published("o", WR, { game: "H", team: "X", position: "WR" })];
    const players = [...three, ...opponent];
    const broken = input(players, [slot("WR", 0), slot("WR", 1), slot("FLEX", 2)], [slot("WR", 3)], {
      correlation: { "teammates:WR-WR": -0.9 },
    });
    const independent = input(players, [slot("WR", 0), slot("WR", 1), slot("FLEX", 2)], [slot("WR", 3)], { correlation: {} });
    const a = simulateMatchup(broken);
    const b = simulateMatchup(independent);
    expect(a.notes).toContainEqual({ kind: "block_fallback", subject: "G", variants: [] });
    expect(a.variants[0]?.win).toBe(b.variants[0]?.win);
    expect(variant(a, 0).mine).toEqual(variant(b, 0).mine);
  });

  it("names a same-game pair the build did not measure, and treats it as independent", () => {
    const players = [
      published("qb1", QB, { game: "G", team: "KC", position: "QB" }),
      published("qb2", QB, { game: "G", team: "KC", position: "QB" }),
    ];
    const result = simulateMatchup(input(players, [slot("QB", 0)], [slot("QB", 1)]));
    expect(result.notes).toContainEqual({ kind: "unmeasured_pair", subject: "teammates:QB-QB", variants: [] });
  });

  it("factors a positive-definite matrix and refuses one that is not", () => {
    expect(choleskyFactor([[1, 0.3], [0.3, 1]])).not.toBeNull();
    expect(
      choleskyFactor([
        [1, -0.9, -0.9],
        [-0.9, 1, -0.9],
        [-0.9, -0.9, 1],
      ]),
    ).toBeNull();
  });
});

describe("proposals on common random numbers", () => {
  const me = standardTeam("m");
  const them = standardTeam("o");
  const bench = [
    published("bench-rb", [3.0, 5.2, 8.6, 12.6, 17.0, 21.6, 24.8], { position: "RB" }),
    // A receiver in my quarterback's game: joins a correlation block in the proposal.
    published("bench-wr", [1.0, 2.5, 6.0, 11.0, 17.5, 24.0, 28.5], { game: "g-mqb", team: "T-mqb", position: "WR" }),
  ];
  const players = [...me.players, ...them.players, ...bench];
  const baseline = me.slots(0);
  const swapRb = baseline.map((s, index) => (index === 2 ? slot("RB", 14) : s));
  const swapWr = baseline.map((s, index) => (index === 4 ? slot("WR", 15) : s));
  const one = input(players, baseline, them.slots(7));
  const many: SimInput = {
    ...one,
    variants: [
      { id: "base", slots: baseline, detail: true },
      { id: "same", slots: [...baseline].reverse(), detail: false },
      { id: "rb", slots: swapRb, detail: false },
      { id: "wr", slots: swapWr, detail: true },
    ],
  };

  it("the baseline's numbers do not move when proposals are evaluated beside it", () => {
    const alone = variant(simulateMatchup(one), 0);
    const beside = variant(simulateMatchup(many), 0);
    // Only the histogram's bins may widen to fit a detailed proposal; every number is the same.
    expect({ ...beside, histogram: [] }).toEqual({ ...alone, histogram: [] });
    expect(beside.histogram.reduce((sum, count) => sum + count, 0)).toBe(8192);
    const quiet = variant(simulateMatchup({ ...many, variants: many.variants.map((item) => ({ ...item, detail: item.id === "base" })) }), 0);
    expect(quiet).toEqual(alone);
  });

  it("bins fit every drawn lineup: a previewed proposal's tail is not piled into an edge bin", () => {
    const boost = published("boost", [30, 35, 45, 60, 75, 90, 100], { position: "RB" });
    const lifted: SimInput = {
      ...one,
      players: [...players, boost],
      variants: [
        { id: "base", slots: baseline, detail: true },
        { id: "boost", slots: baseline.map((s, index) => (index === 2 ? slot("RB", players.length) : s)), detail: true },
      ],
    };
    const result = simulateMatchup(lifted);
    const top = required(variant(result, 1).histogram.at(-1), "last bin");
    expect(top / 8192).toBeLessThan(0.02);
  });

  it("an identical lineup differs by exactly zero", () => {
    const same = variant(simulateMatchup(many), 1);
    expect(same.paired).toEqual({ win: 0, se: 0, p50: 0, p90: 0 });
  });

  it("a single swap's difference has a small paired error, even when it joins a correlation block", () => {
    const result = simulateMatchup(many);
    const rb = variant(result, 2);
    const wr = variant(result, 3);
    expect(rb.couplingReduced).toBe(false);
    expect(wr.couplingReduced).toBe(false);
    // Paired SE well below an unpaired comparison's √2 · binomial SE: only the swapped
    // player's draws differ between the two lineups.
    for (const proposal of [rb, wr]) {
      expect(required(proposal.paired, "paired").se).toBeLessThan(0.75 * Math.SQRT2 * proposal.se);
    }
    expect(wr.groups).not.toBeNull();
  });

  it("agrees with a higher-draw reference within its paired error", () => {
    const low = required(variant(simulateMatchup(many), 2).paired, "paired");
    const high = required(variant(simulateMatchup({ ...many, draws: 65536 }), 2).paired, "paired");
    expect(Math.abs(low.win - high.win)).toBeLessThanOrEqual(4.5 * low.se + 0.001);
  });

  it("flags a proposal whose block fails only once its new player joins", () => {
    // Baseline: two receivers in game G (valid). The proposal adds a third: not positive definite.
    const g = ["a", "b", "c"].map((key) => published(key, WR, { game: "G", team: "KC", position: "WR" }));
    const opp = published("o", WR, { game: "H", team: "X", position: "WR" });
    const players2 = [...g, opp];
    const result = simulateMatchup({
      ...input(players2, [slot("WR", 0), slot("WR", 1)], [slot("WR", 3)], { correlation: { "teammates:WR-WR": -0.6 } }),
      variants: [
        { id: "base", slots: [slot("WR", 0), slot("WR", 1)], detail: false },
        { id: "third", slots: [slot("WR", 0), slot("WR", 2)], detail: false },
      ],
    });
    expect(variant(result, 1).couplingReduced).toBe(true);
    expect(result.notes).toContainEqual({ kind: "block_fallback", subject: "G", variants: ["third"] });
  });
});

describe("slicing and wording", () => {
  it("a run stepped in slices equals one run at once", () => {
    const me = standardTeam("m");
    const them = standardTeam("o");
    const data = input([...me.players, ...them.players], me.slots(0), them.slots(7));
    const run = createRun(data);
    while (!run.step(500)) {
      expect(run.done()).toBeLessThan(8192);
    }
    expect(run.result()).toEqual(simulateMatchup(data));
    expect(() => createRun(data).result()).toThrow(/not finished/);
  });

  it("bins put zero on an edge and stay bounded", () => {
    const margins = Int32Array.from({ length: 1000 }, (_, index) => (index - 300) * 7);
    const bins = marginBins(margins);
    expect(bins.count).toBeLessThanOrEqual(48);
    expect(Math.round(bins.start / bins.width)).toBe(bins.start / bins.width);
    const deterministic = marginBins(Int32Array.from([1000, 1000, 1000]));
    expect(deterministic.count).toBeGreaterThan(0);
    expect(deterministic.start).toBeLessThanOrEqual(0);
  });

  it("words probabilities without false precision", () => {
    expect(percentLabel(0.6249)).toBe("62%");
    expect(percentLabel(0.004)).toBe("<1%");
    expect(percentLabel(0.9961)).toBe(">99%");
    expect(tieLabel(0)).toBe("0%");
    expect(tieLabel(0.0004)).toBe("<0.1%");
    expect(tieLabel(0.0123)).toBe("1.2%");
    expect(meaningfulDelta({ win: 0.004, se: 0.0005, p50: 0, p90: 0 })).toBe(false);
    expect(meaningfulDelta({ win: 0.02, se: 0.012, p50: 0, p90: 0 })).toBe(false);
    expect(meaningfulDelta({ win: 0.02, se: 0.004, p50: 0, p90: 0 })).toBe(true);
  });
});
