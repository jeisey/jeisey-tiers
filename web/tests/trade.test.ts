/**
 * The Trade engine (ADR-100): eligibility, the band, the anti-padding rule, the three presets,
 * package floor/ceiling mathematics, the exact search against brute force, the dealing order,
 * and determinism.
 */

import { describe, expect, it } from "vitest";

import type { Position, RosTierRecord } from "../src/data/contracts";
import {
  EMPTY_EXPLORATION,
  MAX_VISITS,
  MEMBER_SHARE_MIN,
  POOL_CAP,
  TRADE_GOALS,
  TRADE_RANGES,
  VISIBLE_PACKAGES,
  buildPackage,
  checkKept,
  comparePackages,
  compositionMatches,
  cornishFisher,
  dealInitial,
  dealingOrder,
  exclusionReason,
  exhausted,
  explorationStamp,
  inBand,
  marginalKnots,
  marginalMoments,
  moreTargets,
  objectiveOf,
  priceRecord,
  qualifies,
  resolveExploration,
  searchTrade,
  sharesHold,
  swapSlot,
  tradeBand,
  tradeHorizon,
  afterKeep,
  type CompSlot,
  type PricedPlayer,
  type TradeCount,
  type TradeGoal,
  type TradePackage,
  type TradeQuery,
} from "../src/data/trade";
import { rosTierRecords } from "./fixtures/artifacts";
import simulation from "./fixtures/trade-simulation.json";

// ------------------------------------------------------------------------------- helpers

function need<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error("fixture value missing");
  return value;
}

const TEMPLATE = need(rosTierRecords()[0]);

interface Shape {
  readonly mean: number;
  /** p10, p25, p50, p75, p90. */
  readonly q?: readonly [number, number, number, number, number];
  readonly points?: number;
  readonly status?: string | null;
  readonly longAbsence?: boolean;
}

function record(id: string, position: Position, shape: Shape): RosTierRecord {
  const m = shape.mean;
  const q = shape.q ?? [m - 30, m - 15, m, m + 15, m + 30];
  return {
    ...TEMPLATE,
    player_id: id,
    display_name: id,
    position,
    ros_expected_vorp: m,
    ros_vorp_p10: q[0],
    ros_vorp_p25: q[1],
    ros_vorp_p50: q[2],
    ros_vorp_p75: q[3],
    ros_vorp_p90: q[4],
    ros_expected_points: shape.points ?? m + 100,
    current_status: shape.status ?? null,
    long_absence: shape.longAbsence ?? false,
  };
}

/** A tiny deterministic generator, so a "random" universe is the same on every run. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

const POSITIONS: readonly Position[] = ["QB", "RB", "WR", "TE"];

function universe(seed: number, size: number): RosTierRecord[] {
  const rand = lcg(seed);
  const out: RosTierRecord[] = [];
  for (let i = 0; i < size; i += 1) {
    const mean = Math.round((rand() * 160 - 20) * 100) / 100;
    const spread = 10 + rand() * 50;
    const skew = rand() * 2 - 1;
    const q: [number, number, number, number, number] = [
      mean - spread * (1.3 - 0.4 * skew),
      mean - spread * (0.6 - 0.2 * skew),
      mean - spread * 0.1 * skew,
      mean + spread * (0.6 + 0.2 * skew),
      mean + spread * (1.3 + 0.4 * skew),
    ];
    const position = POSITIONS[Math.floor(rand() * 4)] ?? "WR";
    const flag = rand();
    out.push(
      record(`gsis:00-${String(1000000 + i).padStart(7, "0")}`, position, {
        mean,
        q,
        status: flag < 0.05 ? "RES" : null,
        longAbsence: flag > 0.95,
      }),
    );
  }
  return out;
}

/** Every combination of `k` of `items`, by index. */
function combinations(n: number, k: number): number[][] {
  const out: number[][] = [];
  const walk = (start: number, chosen: number[]): void => {
    if (chosen.length === k) {
      out.push([...chosen]);
      return;
    }
    for (let i = start; i < n; i += 1) walk(i + 1, [...chosen, i]);
  };
  walk(0, []);
  return out;
}

/** The brute-force reference: every combination, the plain predicate, a full sort. */
function exhaustive(query: TradeQuery): { keys: string[]; count: number } | null {
  const search = searchTrade(query);
  if (search.status !== "ok") return null;
  const outgoingIds = new Set(query.give);
  const priced = query.records.map(priceRecord).filter((p): p is PricedPlayer => p !== null);
  const found: TradePackage[] = [];
  for (const combo of combinations(priced.length, query.get)) {
    const pkg = buildPackage(combo.map((index) => need(priced[index])));
    if (qualifies(pkg, query, search.band, outgoingIds)) found.push(pkg);
  }
  found.sort((a, b) => comparePackages(a, b, query.goal));
  return { keys: found.slice(0, POOL_CAP).map((pkg) => pkg.key), count: found.length };
}

function ids(search: ReturnType<typeof searchTrade>): string[] {
  return search.status === "ok" ? search.pool.map((entry) => entry.pkg.key) : [];
}

// --------------------------------------------------------------------- the marginal (§5)

describe("ros_marginal_pwl_v1", () => {
  it("keeps the published quantiles as knots and matches the published mean exactly", () => {
    for (const [mean, q] of [
      [40, [10, 25, 38, 55, 75]],
      [30, [10, 25, 38, 55, 75]], // published mean below the knots' own: lower tail moves
      [-5, [-30, -15, -6, 4, 14]],
      [12, [0, 0, 0, 20, 40]], // a spike at replacement, as near-replacement rows publish
    ] as const) {
      const knots = marginalKnots(q, mean);
      expect(knots.values.slice(1, 6)).toEqual([...q]);
      for (let i = 1; i < knots.values.length; i += 1) {
        expect(knots.values[i]).toBeGreaterThanOrEqual(knots.values[i - 1] ?? 0);
      }
      // Trapezoid integral of the quantile function is the mean of the distribution.
      let integral = 0;
      for (let i = 1; i < knots.taus.length; i += 1) {
        integral +=
          ((knots.taus[i] ?? 0) - (knots.taus[i - 1] ?? 0)) *
          (((knots.values[i] ?? 0) + (knots.values[i - 1] ?? 0)) / 2);
      }
      expect(integral).toBeCloseTo(mean, 9);
    }
  });

  it("computes the variance and third moment in closed form", () => {
    const q = [5, 20, 30, 50, 90];
    const knots = marginalKnots(q, 38);
    const { m2, m3 } = marginalMoments(knots, 38);
    // Midpoint quadrature over a fine grid of the same quantile function.
    const n = 200_000;
    let s2 = 0;
    let s3 = 0;
    for (let i = 0; i < n; i += 1) {
      const u = (i + 0.5) / n;
      let x = 0;
      for (let k = 1; k < knots.taus.length; k += 1) {
        const a = knots.taus[k - 1] ?? 0;
        const b = knots.taus[k] ?? 0;
        if (u <= b) {
          x = (knots.values[k - 1] ?? 0) + (((knots.values[k] ?? 0) - (knots.values[k - 1] ?? 0)) * (u - a)) / (b - a);
          break;
        }
      }
      s2 += (x - 38) ** 2;
      s3 += (x - 38) ** 3;
    }
    expect(m2).toBeCloseTo(s2 / n, 3);
    expect(m3 / (s3 / n)).toBeCloseTo(1, 4);
  });

  it("Cornish–Fisher is the normal quantile without skew and clamps extreme skew", () => {
    expect(cornishFisher(100, 400, 0, 0.9)).toBeCloseTo(100 + 20 * 1.2815515655446004, 10);
    expect(cornishFisher(100, 400, 0, 0.1)).toBeCloseTo(100 - 20 * 1.2815515655446004, 10);
    expect(cornishFisher(7, 0, 5, 0.9)).toBe(7);
    // γ = 50 clamps to 2: the 10th percentile stays below the mean, the 90th above.
    const k2 = 100;
    const k3 = 50 * k2 ** 1.5;
    expect(cornishFisher(0, k2, k3, 0.1)).toBeLessThan(0);
    expect(cornishFisher(0, k2, k3, 0.9)).toBeGreaterThan(0);
    expect(cornishFisher(0, k2, k3, 0.9)).toBeCloseTo(cornishFisher(0, k2, 2 * k2 ** 1.5, 0.9), 10);
  });
});

// -------------------------------------------- the approximation against the draw loop (§5)

interface SimPlayer {
  readonly player_id: string;
  readonly position: Position;
  readonly ros_expected_vorp: number;
  readonly ros_vorp_p10: number;
  readonly ros_vorp_p25: number;
  readonly ros_vorp_p50: number;
  readonly ros_vorp_p75: number;
  readonly ros_vorp_p90: number;
  readonly ros_expected_points: number;
}
interface SimPackage {
  readonly ids: readonly string[];
  readonly same_position: boolean;
  readonly mean: number;
  readonly p10: number;
  readonly p90: number;
  readonly p10_independent: number;
  readonly p90_independent: number;
}

describe("ros_package_quantiles_v1 against the production draw loop", () => {
  const players = new Map(
    (simulation.players as unknown as SimPlayer[]).map((row) => [
      row.player_id,
      need(priceRecord({ ...TEMPLATE, ...row, display_name: row.player_id })),
    ]),
  );
  const packages = simulation.packages as unknown as SimPackage[];

  function errors(size: number, truth: "joint" | "independent") {
    const rows = packages.filter((pkg) => pkg.ids.length === size);
    const err10: number[] = [];
    const err90: number[] = [];
    const width: number[] = [];
    const naive: number[] = [];
    for (const row of rows) {
      const pkg = buildPackage(row.ids.map((id) => need(players.get(id))));
      const t10 = truth === "joint" ? row.p10 : row.p10_independent;
      const t90 = truth === "joint" ? row.p90 : row.p90_independent;
      err10.push(pkg.p10 - t10);
      err90.push(pkg.p90 - t90);
      width.push(t90 - t10);
      // The mistake ADR-100 forbids: summing individual P90s.
      naive.push(pkg.members.reduce((sum, m) => sum + m.p90, 0) - t90);
      expect(pkg.value).toBeCloseTo(row.mean, 2);
    }
    const mae = (values: number[]): number => values.reduce((s, v) => s + Math.abs(v), 0) / values.length;
    const meanWidth = width.reduce((s, v) => s + v, 0) / width.length;
    return {
      n: rows.length,
      mae10: mae(err10),
      mae90: mae(err90),
      max: Math.max(...err10.map(Math.abs), ...err90.map(Math.abs)),
      bias10: err10.reduce((s, v) => s + v, 0) / err10.length,
      bias90: err90.reduce((s, v) => s + v, 0) / err90.length,
      meanWidth,
      naiveMae90: mae(naive),
    };
  }

  it("single players are the published values exactly", () => {
    for (const row of packages.filter((pkg) => pkg.ids.length === 1)) {
      const pkg = buildPackage([need(players.get(row.ids[0] ?? ""))]);
      expect(pkg.p10).toBe(row.p10);
      expect(pkg.p90).toBe(row.p90);
      expect(pkg.approximate).toBe(false);
    }
  });

  it("pairs and triples land within a small fraction of the interval, and far closer than summed P90s", () => {
    const report: Record<string, unknown> = {};
    for (const size of [2, 3]) {
      for (const truth of ["joint", "independent"] as const) {
        const e = errors(size, truth);
        report[`${String(size)}-${truth}`] = Object.fromEntries(
          Object.entries(e).map(([key, value]) => [key, Number(value.toFixed(3))]),
        );
        // Thresholds: mean error at most 4% of the P10–P90 width, worst case at most 12%.
        expect(e.mae10).toBeLessThan(0.04 * e.meanWidth);
        expect(e.mae90).toBeLessThan(0.04 * e.meanWidth);
        expect(e.max).toBeLessThan(0.12 * e.meanWidth);
        expect(e.naiveMae90).toBeGreaterThan(4 * e.mae90);
      }
    }
    // The measured numbers ADR-100's evidence section quotes.
    console.info("ros_package_quantiles_v1 vs draw loop", JSON.stringify(report));
  });

  it("orders packages by ceiling and floor the way the draws do", () => {
    for (const size of [2, 3]) {
      const rows = packages.filter((pkg) => pkg.ids.length === size);
      const est = rows.map((row) => buildPackage(row.ids.map((id) => need(players.get(id)))));
      let concordant = 0;
      let total = 0;
      for (let i = 0; i < rows.length; i += 1) {
        for (let j = i + 1; j < rows.length; j += 1) {
          const truth = Math.sign((rows[i]?.p90 ?? 0) - (rows[j]?.p90 ?? 0));
          const guess = Math.sign((est[i]?.p90 ?? 0) - (est[j]?.p90 ?? 0));
          if (truth === 0) continue;
          total += 1;
          if (truth === guess) concordant += 1;
        }
      }
      expect(concordant / total).toBeGreaterThan(0.97);
    }
  });
});

// ------------------------------------------------------------------- eligibility (§2)

describe("trade_eligibility_v1", () => {
  it("excludes nonpositive, long-absence, severe-status and unpriced players, and nobody else", () => {
    const none = new Set<string>();
    expect(exclusionReason(record("a", "RB", { mean: 10 }), none)).toBeNull();
    expect(exclusionReason(record("a", "RB", { mean: 0 }), none)).toBe("at_or_below_replacement");
    expect(exclusionReason(record("a", "RB", { mean: -4 }), none)).toBe("at_or_below_replacement");
    expect(exclusionReason(record("a", "RB", { mean: 30, longAbsence: true }), none)).toBe("long_absence");
    for (const code of ["RES", "INA", "PUP", "NFI", "SUS", "CUT", "RET", "res"]) {
      expect(exclusionReason(record("a", "RB", { mean: 30, status: code }), none)).toBe("roster_status");
    }
    // ACT, practice squad and exempt are not "cannot take the field".
    for (const code of ["ACT", "DEV", "E14", "EXE"]) {
      expect(exclusionReason(record("a", "RB", { mean: 30, status: code }), none)).toBeNull();
    }
    expect(exclusionReason(record("a", "RB", { mean: 30 }), new Set(["a"]))).toBe("outgoing");
    expect(exclusionReason({ ...record("a", "RB", { mean: 30 }), ros_vorp_p90: Number.NaN }, none)).toBe("unpriced");
    expect(exclusionReason(record("a", "RB", { mean: 30, q: [10, 30, 20, 40, 50] }), none)).toBe("unpriced");
  });

  it("reads no weekly designation: the engine has no weekly input at all", () => {
    // An Out-this-week player is an ordinary record here; only the roster code and the
    // appearance-based long absence can exclude him (ADR-100 §2).
    const records = [record("star", "RB", { mean: 100 }), record("out-this-week", "WR", { mean: 95 })];
    const search = searchTrade({ records, give: ["star"], goal: "value", get: 1, range: 20, comp: [] });
    expect(ids(search)).toEqual(["out-this-week"]);
  });

  it("lists positive-value exclusions with their reason and counts the rest", () => {
    const records = [
      record("give", "RB", { mean: 100 }),
      record("ok", "WR", { mean: 95 }),
      record("ir", "WR", { mean: 110, status: "RES" }),
      record("gone", "RB", { mean: 90, longAbsence: true }),
      record("waiver", "TE", { mean: -3 }),
    ];
    const search = searchTrade({ records, give: ["give"], goal: "value", get: 1, range: 20, comp: [] });
    expect(search.status).toBe("ok");
    if (search.status !== "ok") return;
    expect(search.excluded.map((row) => [row.record.player_id, row.reason])).toEqual([
      ["ir", "roster_status"],
      ["gone", "long_absence"],
    ]);
    expect(search.belowReplacement).toBe(1);
    expect(ids(search)).toEqual(["ok"]);
  });
});

// ------------------------------------------------------------- the band and its edges (§3)

describe("trade_band_v1", () => {
  it("is inclusive and refuses a nonpositive outgoing value", () => {
    const band = tradeBand(100, 20);
    expect(band).toEqual({ low: 80, high: 120, range: 20 });
    if (band === null) return;
    expect(inBand(80, band)).toBe(true);
    expect(inBand(120, band)).toBe(true);
    expect(inBand(79.99, band)).toBe(false);
    expect(tradeBand(0, 20)).toBeNull();
    expect(tradeBand(-12, 50)).toBeNull();
    expect(tradeBand(Number.NaN, 20)).toBeNull();
  });

  it("does not search from a zero or negative outgoing package, and counts negatives in a sum", () => {
    const records = [
      record("neg", "QB", { mean: -18 }),
      record("zero", "WR", { mean: 0 }),
      record("star", "RB", { mean: 100 }),
      record("a", "WR", { mean: 80 }),
      record("b", "WR", { mean: 64 }),
    ];
    for (const give of [["neg"], ["zero"], ["neg", "zero"]]) {
      expect(searchTrade({ records, give, goal: "value", get: 1, range: 50, comp: [] }).status).toBe("nonpositive");
    }
    // A negative member lowers the package: 100 - 18 = 82, never clamped back to 100.
    const search = searchTrade({ records, give: ["star", "neg"], goal: "value", get: 1, range: 20, comp: [] });
    expect(search.status).toBe("ok");
    if (search.status !== "ok") return;
    expect(search.outgoingPkg.value).toBe(82);
    expect(search.band.low).toBeCloseTo(65.6, 10);
    expect(ids(search)).toEqual(["a"]);
  });

  it("a near-zero positive outgoing value finds only near-replacement assets, never a star", () => {
    const records = [
      record("tiny", "WR", { mean: 0.8, q: [-15, -8, 0, 9, 18] }),
      record("star", "RB", { mean: 120 }),
      record("peer", "TE", { mean: 0.9, q: [-10, -5, 0, 6, 12] }),
    ];
    const search = searchTrade({ records, give: ["tiny"], goal: "ceiling", get: 1, range: 50, comp: [] });
    expect(ids(search)).toEqual(["peer"]);
    const pairs = searchTrade({ records, give: ["tiny"], goal: "value", get: 2, range: 50, comp: [] });
    expect(ids(pairs)).toEqual([]);
  });

  it("unpriced or missing outgoing players are reported, not imputed", () => {
    const records = [record("a", "RB", { mean: 50 }), { ...record("b", "WR", { mean: 40 }), ros_vorp_p50: Number.NaN }];
    expect(searchTrade({ records, give: ["b"], goal: "value", get: 1, range: 20, comp: [] }).status).toBe("unpriced_outgoing");
    const stale = searchTrade({ records, give: ["gsis:00-9999999", "a"], goal: "value", get: 1, range: 20, comp: [] });
    expect(stale.outgoing.missing).toEqual(["gsis:00-9999999"]);
    expect(stale.status).toBe("ok");
    expect(searchTrade({ records, give: ["gsis:00-9999999"], goal: "value", get: 1, range: 20, comp: [] }).status).toBe("no_outgoing");
  });
});

describe("member_share_v1: no filler benefit", () => {
  const records = [
    record("give", "RB", { mean: 100 }),
    record("star", "WR", { mean: 95 }),
    record("filler", "WR", { mean: 9 }),
    record("zero", "TE", { mean: 0 }),
    record("neg", "QB", { mean: -5 }),
    record("mid1", "RB", { mean: 52 }),
    record("mid2", "WR", { mean: 50 }),
    record("small", "TE", { mean: 16 }),
  ];

  it("a star plus a throw-in is not a two-player package", () => {
    const search = searchTrade({ records, give: ["give"], goal: "value", get: 2, range: 20, comp: [] });
    const keys = ids(search);
    expect(keys).not.toContain("filler.star");
    expect(keys.some((key) => key.includes("zero") || key.includes("neg"))).toBe(false);
    // 95 + 16 = 111 has a 14% member and is refused; 52 + 50 qualifies.
    expect(keys).not.toContain("small.star");
    expect(keys).toContain("mid1.mid2");
    for (const key of keys) {
      const pkg = search.status === "ok" ? search.pool.find((e) => e.pkg.key === key)?.pkg : undefined;
      expect(pkg !== undefined && sharesHold(pkg)).toBe(true);
    }
  });

  it("adding a nonpositive member never improves any objective", () => {
    const star = need(priceRecord(need(records[1])));
    const neg = need(priceRecord(need(records[4])));
    const alone = buildPackage([star]);
    const padded = buildPackage([star, neg]);
    expect(padded.value).toBeLessThan(alone.value);
    expect(sharesHold(padded)).toBe(false);
    expect(MEMBER_SHARE_MIN).toBe(0.15);
  });
});

// ---------------------------------------------------------------- presets differ (§4)

describe("the three presets", () => {
  // Three incoming candidates with the same band position but different shapes.
  const records = [
    record("give", "RB", { mean: 100, q: [60, 80, 100, 120, 140] }),
    record("steady", "WR", { mean: 110, q: [95, 103, 110, 117, 125] }), // best floor
    record("boom", "WR", { mean: 100, q: [30, 60, 95, 140, 190] }), // best ceiling
    record("mean", "TE", { mean: 115, q: [70, 92, 112, 136, 160] }), // best expectation
  ];

  it("ROS value, ceiling and floor each lead with a different player", () => {
    const lead = (goal: TradeGoal): string =>
      ids(searchTrade({ records, give: ["give"], goal, get: 1, range: 20, comp: [] }))[0] ?? "";
    expect(lead("value")).toBe("mean");
    expect(lead("ceiling")).toBe("boom");
    expect(lead("floor")).toBe("steady");
  });

  it("keeps the comparable pool fixed across presets: same members, different order", () => {
    const pools = TRADE_GOALS.map((goal) =>
      [...ids(searchTrade({ records, give: ["give"], goal, get: 1, range: 20, comp: [] }))].sort(),
    );
    expect(pools[0]).toEqual(pools[1]);
    expect(pools[1]).toEqual(pools[2]);
  });

  it("reports deltas against the outgoing package in the objective's own units", () => {
    const search = searchTrade({ records, give: ["give"], goal: "ceiling", get: 1, range: 20, comp: [] });
    if (search.status !== "ok") throw new Error("expected a search");
    const boom = search.pool.find((entry) => entry.pkg.key === "boom");
    expect(boom?.objectiveDelta).toBe(190 - 140);
    expect(boom?.valueDelta).toBe(0);
  });

  it("multi-player ceilings are not the sum of individual ceilings", () => {
    const a = need(priceRecord(need(records[2])));
    const b = need(priceRecord(need(records[3])));
    const pkg = buildPackage([a, b]);
    expect(pkg.approximate).toBe(true);
    expect(pkg.value).toBe(215);
    expect(pkg.p90).toBeLessThan(190 + 160);
    expect(pkg.p10).toBeGreaterThan(30 + 70);
  });
});

// ----------------------------------------------- the exact search against brute force (§6)

describe("trade_search_v1 against exhaustive enumeration", () => {
  const comps: Record<TradeCount, CompSlot[][]> = {
    1: [[], ["rb"], ["qb"]],
    2: [[], ["rb", "wr"], ["wr", "any"], ["te", "te"]],
    3: [[], ["rb", "wr", "any"], ["qb", "any", "any"], ["rb", "rb", "wr"]],
  };

  it("finds exactly the qualifying set and the same ranking, for every shape and preset", () => {
    let checked = 0;
    for (const seed of [1, 2, 3, 4]) {
      const records = universe(seed, 26);
      const positives = records.filter((r) => r.ros_expected_vorp > 20);
      for (const giveCount of [1, 2, 3]) {
        const give = positives.slice(seed, seed + giveCount).map((r) => r.player_id);
        for (const get of [1, 2, 3] as const) {
          for (const comp of comps[get]) {
            for (const goal of TRADE_GOALS) {
              for (const range of [10, 35, 50]) {
                const query: TradeQuery = { records, give, goal, get, range, comp };
                const search = searchTrade(query);
                const reference = exhaustive(query);
                if (reference === null) continue;
                expect(search.status).toBe("ok");
                if (search.status !== "ok") continue;
                expect(search.qualifying).toBe(reference.count);
                expect(search.truncated).toBe(false);
                expect(search.pool.map((entry) => entry.pkg.key)).toEqual(reference.keys);
                checked += 1;
              }
            }
          }
        }
      }
    }
    expect(checked).toBeGreaterThan(400);
  });

  it("keeps only the best POOL_CAP but still counts every qualifying package", () => {
    const records = universe(9, 60);
    const give = [...records].sort((a, b) => b.ros_expected_vorp - a.ros_expected_vorp).slice(0, 2).map((r) => r.player_id);
    const query: TradeQuery = { records, give, goal: "ceiling", get: 3, range: 50, comp: [] };
    const search = searchTrade(query);
    const reference = exhaustive(query);
    if (search.status !== "ok" || reference === null) throw new Error("expected a search");
    expect(reference.count).toBeGreaterThan(POOL_CAP);
    expect(search.qualifying).toBe(reference.count);
    expect(search.pool).toHaveLength(POOL_CAP);
    expect(search.pool.map((entry) => entry.pkg.key)).toEqual(reference.keys);
    expect(MAX_VISITS).toBeGreaterThan(reference.count);
  });

  it("never yields a duplicate player, an outgoing player or a permutation", () => {
    const records = universe(5, 40);
    const give = records.filter((r) => r.ros_expected_vorp > 60).slice(0, 2).map((r) => r.player_id);
    const search = searchTrade({ records, give, goal: "value", get: 3, range: 50, comp: [] });
    if (search.status !== "ok") throw new Error("expected a search");
    const keys = search.pool.map((entry) => entry.pkg.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const entry of search.pool) {
      const members = entry.pkg.members.map((m) => m.id);
      expect(new Set(members).size).toBe(3);
      expect(members.some((id) => give.includes(id))).toBe(false);
    }
  });

  it("is deterministic and independent of record order", () => {
    const records = universe(7, 50);
    const give = records.filter((r) => r.ros_expected_vorp > 50).slice(0, 1).map((r) => r.player_id);
    const query: TradeQuery = { records, give, goal: "floor", get: 2, range: 35, comp: [] };
    const first = ids(searchTrade(query));
    expect(ids(searchTrade(query))).toEqual(first);
    expect(ids(searchTrade({ ...query, records: [...records].reverse() }))).toEqual(first);
  });
});

// ---------------------------------------------------------- shapes and presets on the board

describe("every shape on the in-season fixture board", () => {
  const board = rosTierRecords().filter((r) => r.league_preset_id === "redraft-12" && r.scoring_preset === "PPR");

  it("runs every give × receive count, all presets and ranges, and every result qualifies", () => {
    const tradeable = [...board]
      .filter((r) => r.ros_expected_vorp > 0)
      .sort((a, b) => b.ros_expected_vorp - a.ros_expected_vorp);
    let results = 0;
    for (const give of [1, 2, 3]) {
      for (const get of [1, 2, 3] as const) {
        for (const goal of TRADE_GOALS) {
          for (const range of TRADE_RANGES) {
            const outgoing = tradeable.slice(give, give + give).map((r) => r.player_id);
            const search = searchTrade({ records: board, give: outgoing, goal, get, range, comp: [] });
            expect(search.status).toBe("ok");
            if (search.status !== "ok") continue;
            const ids = new Set(outgoing);
            for (const entry of search.pool) {
              expect(qualifies(entry.pkg, { get, comp: [] }, search.band, ids)).toBe(true);
              results += 1;
            }
          }
        }
      }
    }
    expect(results).toBeGreaterThan(50);
  });

  it("Bijan for two finds cross-position packages, and composition filters them", () => {
    const give = ["gsis:00-0000001"];
    const any = searchTrade({ records: board, give, goal: "value", get: 2, range: 35, comp: [] });
    const rbwr = searchTrade({ records: board, give, goal: "value", get: 2, range: 35, comp: ["rb", "wr"] });
    if (any.status !== "ok" || rbwr.status !== "ok") throw new Error("expected searches");
    expect(any.pool.length).toBeGreaterThan(0);
    expect(any.pool.some((entry) => new Set(entry.pkg.members.map((m) => m.record.position)).size > 1)).toBe(true);
    expect(rbwr.pool.length).toBeGreaterThan(0);
    for (const entry of rbwr.pool) {
      expect(entry.pkg.members.map((m) => m.record.position).sort()).toEqual(["RB", "WR"]);
    }
  });

  it("every scoring and league block gives its own numbers", () => {
    const values = new Set<string>();
    for (const league of ["redraft-10", "redraft-12", "redraft-14"]) {
      for (const scoring of ["STD", "HALF", "PPR"]) {
        const block = rosTierRecords().filter((r) => r.league_preset_id === league && r.scoring_preset === scoring);
        const search = searchTrade({ records: block, give: ["gsis:00-0000001"], goal: "value", get: 1, range: 50, comp: [] });
        expect(search.status).toBe("ok");
        if (search.status === "ok") values.add(search.outgoingPkg.value.toFixed(4));
      }
    }
    expect(values.size).toBe(9);
  });

  it("composition matching is a multiset check", () => {
    expect(compositionMatches(["RB", "WR"], ["rb", "wr"])).toBe(true);
    expect(compositionMatches(["WR", "RB"], ["rb", "any"])).toBe(true);
    expect(compositionMatches(["WR", "WR"], ["rb", "any"])).toBe(false);
    expect(compositionMatches(["RB", "RB", "TE"], ["rb", "rb", "any"])).toBe(true);
    expect(compositionMatches(["RB", "TE", "TE"], ["rb", "rb", "any"])).toBe(false);
    expect(compositionMatches(["QB"], [])).toBe(true);
  });
});

// -------------------------------------------------------------------- exploration (§7)

describe("trade_explore_v1", () => {
  const records = universe(11, 70);
  const give = [...records].filter((r) => r.ros_expected_vorp > 0 && !r.long_absence && r.current_status === null)
    .sort((a, b) => b.ros_expected_vorp - a.ros_expected_vorp)
    .slice(0, 1)
    .map((r) => r.player_id);
  const search = searchTrade({ records, give, goal: "value", get: 2, range: 50, comp: [] });
  if (search.status !== "ok") throw new Error("expected a search");
  const order = dealingOrder(search.pool);
  const none = new Set<string>();

  it("deals each package once, leads first", () => {
    expect(order).toHaveLength(search.pool.length);
    expect(new Set(order.map((entry) => entry.pkg.key)).size).toBe(order.length);
    const initial = dealInitial(order, none);
    expect(initial.shown).toHaveLength(VISIBLE_PACKAGES);
    const leads = initial.shown.map((index) => order[index]?.pkg.lead);
    expect(new Set(leads).size).toBe(VISIBLE_PACKAGES);
  });

  it("swap replaces one slot with the next undealt package and never repeats one", () => {
    let state = dealInitial(order, none);
    const seen = new Set(state.shown.map((index) => order[index]?.pkg.key));
    for (let step = 0; step < 12; step += 1) {
      const next = swapSlot(order, state, step % VISIBLE_PACKAGES, none);
      if (next === null) break;
      const added = next.shown[step % VISIBLE_PACKAGES] ?? -1;
      expect(seen.has(order[added]?.pkg.key)).toBe(false);
      seen.add(order[added]?.pkg.key);
      expect(next.shown.filter((_, slot) => slot !== step % VISIBLE_PACKAGES)).toEqual(
        state.shown.filter((_, slot) => slot !== step % VISIBLE_PACKAGES),
      );
      state = next;
    }
  });

  it("keeps a kept package out of the deal and refills its slot", () => {
    const state = dealInitial(order, none);
    const keptKey = order[state.shown[1] ?? 0]?.pkg.key ?? "";
    const kept = new Set([keptKey]);
    const after = afterKeep(order, state, 1, kept);
    expect(after.shown).toHaveLength(VISIBLE_PACKAGES);
    expect(after.shown.map((index) => order[index]?.pkg.key)).not.toContain(keptKey);
    const more = moreTargets(order, after, kept);
    expect(more?.shown.map((index) => order[index]?.pkg.key)).not.toContain(keptKey);
  });

  it("signals exhaustion honestly and resets to the first deal", () => {
    let state = dealInitial(order, none);
    let rounds = 0;
    for (;;) {
      const next = moreTargets(order, state, none);
      if (next === null) break;
      state = next;
      rounds += 1;
    }
    expect(rounds).toBeGreaterThan(0);
    expect(exhausted(order, state, none)).toBe(true);
    expect(swapSlot(order, state, 0, none)).toBeNull();
    expect(dealInitial(order, none)).toEqual(dealInitial(order, none));
  });

  it("restores a URL's exploration only with a matching stamp and valid indices", () => {
    const initial = dealInitial(order, none);
    const swapped = swapSlot(order, initial, 2, none);
    if (swapped === null) throw new Error("expected a swap");
    expect(resolveExploration(order, swapped, true, none)).toEqual({ exploration: swapped, redealt: false });
    expect(resolveExploration(order, swapped, false, none)).toEqual({ exploration: initial, redealt: true });
    expect(resolveExploration(order, { shown: [0, 0], dealt: 5 }, true, none).redealt).toBe(true);
    expect(resolveExploration(order, { shown: [9], dealt: 3 }, true, none).redealt).toBe(true);
    expect(resolveExploration(order, EMPTY_EXPLORATION, true, none)).toEqual({ exploration: initial, redealt: false });
  });

  it("fewer qualifying packages than slots shows fewer, never padding", () => {
    const small = [record("give", "RB", { mean: 100 }), record("x", "WR", { mean: 90 }), record("y", "TE", { mean: 105 })];
    const result = searchTrade({ records: small, give: ["give"], goal: "value", get: 1, range: 20, comp: [] });
    if (result.status !== "ok") throw new Error("expected a search");
    const dealt = dealInitial(dealingOrder(result.pool), none);
    expect(dealt.shown).toHaveLength(2);
  });

  it("the stamp changes with the build and with every search input", () => {
    const base = {
      buildId: "b1",
      leaguePreset: "redraft-12",
      scoring: "PPR",
      give: ["gsis:00-0000001"],
      goal: "value" as const,
      get: 2,
      range: 20,
      comp: [] as CompSlot[],
    };
    const stamp = explorationStamp(base);
    expect(stamp).toMatch(/^[0-9a-f]{8}$/);
    expect(explorationStamp(base)).toBe(stamp);
    for (const change of [
      { buildId: "b2" },
      { scoring: "HALF" },
      { give: ["gsis:00-0000002"] },
      { goal: "ceiling" as const },
      { get: 3 },
      { range: 35 },
      { comp: ["rb", "any"] as CompSlot[] },
    ]) {
      expect(explorationStamp({ ...base, ...change })).not.toBe(stamp);
    }
  });
});

// --------------------------------------------------------------------- kept and horizon

describe("kept packages", () => {
  const records = [
    record("give", "RB", { mean: 100 }),
    record("a", "WR", { mean: 55 }),
    record("b", "TE", { mean: 50 }),
    record("c", "QB", { mean: 98 }),
  ];
  const search = searchTrade({ records, give: ["give"], goal: "value", get: 2, range: 20, comp: [] });

  it("a kept package that still qualifies has no problems", () => {
    expect(checkKept(["a", "b"], records, { get: 2, comp: [] }, search).problems).toEqual([]);
  });

  it("explains why a kept package stopped qualifying", () => {
    expect(checkKept(["a", "b"], records, { get: 3, comp: [] }, search).problems).toContain("wrong_count");
    expect(checkKept(["a", "b"], records, { get: 2, comp: ["rb", "any"] }, search).problems).toContain("composition");
    expect(checkKept(["a", "zzz"], records, { get: 2, comp: [] }, search).problems).toEqual(["not_on_board"]);
    const narrow = searchTrade({ records, give: ["c"], goal: "value", get: 2, range: 10, comp: [] });
    expect(checkKept(["a", "b"], records, { get: 2, comp: [] }, narrow).problems).toEqual([]);
    const moved = searchTrade({ records, give: ["a"], goal: "value", get: 2, range: 10, comp: [] });
    const problems = checkKept(["a", "b"], records, { get: 2, comp: [] }, moved).problems;
    expect(problems).toContain("includes_outgoing");
    expect(problems).toContain("outside_range");
  });
});

describe("tradeHorizon", () => {
  it("states weeks 9–17 for a week-8 cutoff, playoffs included, week 18 excluded", () => {
    const horizon = tradeHorizon(2026, 8, rosTierRecords());
    expect(horizon).toEqual({
      firstWeek: 9,
      lastWeek: 17,
      weeks: 9,
      contractLastWeek: 17,
      excludedWeek: 18,
      playoffFirstWeek: 15,
      agreesWithContract: true,
    });
  });

  it("uses the record's own horizon when it disagrees, and withholds playoff claims", () => {
    const records = rosTierRecords().map((r) => ({ ...r, remaining_horizon_weeks: 6 }));
    const horizon = tradeHorizon(2026, 8, records);
    expect(horizon?.lastWeek).toBe(14);
    expect(horizon?.agreesWithContract).toBe(false);
    expect(horizon?.playoffFirstWeek).toBeNull();
    const bare = rosTierRecords().map((r) => {
      const rest: Record<string, unknown> = { ...r };
      delete rest.remaining_horizon_weeks;
      return rest as unknown as RosTierRecord;
    });
    expect(tradeHorizon(2026, 8, bare)).toBeNull();
  });

  it("objectiveOf reads exactly one statistic per preset", () => {
    const pkg = { value: 1, p10: 2, p90: 3 };
    expect([objectiveOf(pkg, "value"), objectiveOf(pkg, "floor"), objectiveOf(pkg, "ceiling")]).toEqual([1, 2, 3]);
  });
});
