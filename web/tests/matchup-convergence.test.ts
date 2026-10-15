/**
 * ADR-110 §3's convergence measurement: is the draw count enough? Offline only.
 *
 * Skipped unless `MATCHUP_CONVERGENCE` names a `weekly_projections.json` (a live build's, for
 * realistic distributions, games and teams) and `MATCHUP_METADATA` its `ros_build_metadata.json`
 * (for the latent correlations and the tail rule). Writes the report to `MATCHUP_REPORT`.
 *
 *   MATCHUP_CONVERGENCE=…/weekly_projections.json MATCHUP_METADATA=…/ros_build_metadata.json \
 *   MATCHUP_REPORT=docs/experiments/win-my-matchup-2026-10-15/convergence.json \
 *     npx vitest run tests/matchup-convergence.test.ts
 *
 * For each of `MATCHUPS` random two-team matchups (1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX a side, drawn
 * from each position's weekly decision pool) and one single-player swap per matchup, it records
 * at each candidate draw count: the seed-to-seed SD of the headline across `SEEDS` seeds against
 * the binomial SE, the paired SE of the swap's ΔP(win), and whether the rounded headline equals a
 * 1,048,576-draw reference within ±1 point. It also times the runs (unthrottled, this machine).
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

import { describe, expect, it } from "vitest";

import type { RosWeeklyMetadata, WeeklyProjectionRecord } from "../src/data/contracts";
import { MATCHUP_ENGINE_VERSION, simulateMatchup, type SimInput, type SimPlayer, type SimSlot } from "../src/data/matchup";
import { distributionRule, knots, quantileValues } from "../src/data/startsit";

const SOURCE = process.env.MATCHUP_CONVERGENCE;
const METADATA = process.env.MATCHUP_METADATA;
const REPORT = process.env.MATCHUP_REPORT;
const MATCHUPS = Number(process.env.MATCHUP_COUNT ?? 60);
const SEEDS = 20;
const COUNTS = [8192, 16384, 32768];
const REFERENCE = 1_048_576;
const POOL: Readonly<Record<string, number>> = { QB: 24, RB: 48, WR: 60, TE: 24 };

/** A small deterministic generator for choosing lineups (not the engine's). */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

describe.skipIf(SOURCE === undefined || METADATA === undefined)("convergence (offline)", () => {
  it("measures the draw count against ADR-110's rule", { timeout: 3_600_000 }, () => {
    const records = (JSON.parse(readFileSync(SOURCE ?? "", "utf-8")) as { records: WeeklyProjectionRecord[] }).records;
    const metadata = (JSON.parse(readFileSync(METADATA ?? "", "utf-8")) as { weekly: RosWeeklyMetadata; build_id: string }).weekly;
    const rule = distributionRule(metadata);
    const correlation = Object.fromEntries(
      Object.entries(metadata.correlation.pairs ?? {}).map(([key, entry]) => [key, entry.rho]),
    );
    const ppr = records.filter((record) => record.scoring_preset === "PPR" && record.quantiles !== null && record.game !== null);
    const pools = new Map<string, WeeklyProjectionRecord[]>();
    for (const position of Object.keys(POOL)) {
      pools.set(
        position,
        ppr
          .filter((record) => record.position === position)
          .sort((a, b) => (b.quantiles?.q50 ?? 0) - (a.quantiles?.q50 ?? 0))
          .slice(0, POOL[position]),
      );
    }
    const asPlayer = (record: WeeklyProjectionRecord): SimPlayer => {
      const { taus, values } = knots(quantileValues(record) ?? [], rule);
      return { key: record.player_id, taus, values, game: record.game?.game_id ?? null, team: record.team, position: record.position };
    };

    const random = lcg(20261015);
    const rows: Record<string, unknown>[] = [];
    const summary: Record<number, { sdRatio: number[]; pairedSe: number[]; withinOne: number; headlineHalfWidth: number[]; ms: number[] }> = {};
    for (const count of COUNTS) summary[count] = { sdRatio: [], pairedSe: [], withinOne: 0, headlineHalfWidth: [], ms: [] };

    for (let m = 0; m < MATCHUPS; m += 1) {
      const used = new Set<string>();
      const take = (position: string): WeeklyProjectionRecord => {
        const pool = (pools.get(position) ?? []).filter((record) => !used.has(record.player_id));
        const pick = pool[Math.floor(random() * pool.length)];
        if (pick === undefined) throw new Error(`pool ${position} exhausted`);
        used.add(pick.player_id);
        return pick;
      };
      const team = (): { records: WeeklyProjectionRecord[]; groups: SimSlot["group"][] } => {
        const flexPosition = ["RB", "WR", "TE"][Math.floor(random() * 3)] ?? "WR";
        return {
          records: [take("QB"), take("RB"), take("RB"), take("WR"), take("WR"), take("TE"), take(flexPosition)],
          groups: ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
        };
      };
      const mine = team();
      const theirs = team();
      const swapIndex = 1 + Math.floor(random() * 6);
      const swapPosition = mine.records[swapIndex]?.position ?? "WR";
      const swapIn = take(swapPosition);
      const all = [...mine.records, ...theirs.records, swapIn];
      const players = all.map(asPlayer);
      const mySlots: SimSlot[] = mine.groups.map((group, index) => ({ group, player: index, fixed: 0 }));
      const theirSlots: SimSlot[] = theirs.groups.map((group, index) => ({ group, player: 7 + index, fixed: 0 }));
      const swapped = mySlots.map((slot, index) => (index === swapIndex ? { ...slot, player: 14 } : slot));
      const make = (draws: number, seed: number): SimInput => ({
        version: MATCHUP_ENGINE_VERSION,
        seed,
        draws,
        players,
        correlation,
        opponent: theirSlots,
        variants: [
          { id: "base", slots: mySlots, detail: false },
          { id: "swap", slots: swapped, detail: false },
        ],
      });
      // The reference: 16 independent seeds at the engine's cap, averaged — 1,048,576 draws
      // without lifting the cap the page runs under.
      let refWin = 0;
      let refDelta = 0;
      const parts = REFERENCE / 65536;
      for (let part = 0; part < parts; part += 1) {
        const reference = simulateMatchup(make(65536, 1000 + part)).variants;
        refWin += (reference[0]?.win ?? 0) / parts;
        refDelta += (reference[1]?.paired?.win ?? 0) / parts;
      }
      const row: Record<string, unknown> = { matchup: m, referenceWin: refWin, referenceDelta: refDelta, swap: swapPosition };
      for (const count of COUNTS) {
        const wins: number[] = [];
        const deltas: number[] = [];
        const pairedSes: number[] = [];
        let within = 0;
        for (let seed = 1; seed <= SEEDS; seed += 1) {
          const started = performance.now();
          const result = simulateMatchup(make(count, seed));
          summary[count]?.ms.push(performance.now() - started);
          const base = result.variants[0];
          const swap = result.variants[1];
          wins.push(base?.win ?? 0);
          deltas.push(swap?.paired?.win ?? 0);
          pairedSes.push(swap?.paired?.se ?? 0);
          if (Math.abs(Math.round((base?.win ?? 0) * 100) - Math.round(refWin * 100)) <= 1) within += 1;
        }
        const mean = wins.reduce((sum, value) => sum + value, 0) / SEEDS;
        const sd = Math.sqrt(wins.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (SEEDS - 1));
        const binomial = Math.sqrt((refWin * (1 - refWin)) / count);
        const deltaMean = deltas.reduce((sum, value) => sum + value, 0) / SEEDS;
        const deltaSd = Math.sqrt(deltas.reduce((sum, value) => sum + (value - deltaMean) ** 2, 0) / (SEEDS - 1));
        const meanPairedSe = pairedSes.reduce((sum, value) => sum + value, 0) / SEEDS;
        summary[count]?.sdRatio.push(binomial > 0 ? sd / binomial : 1);
        summary[count]?.pairedSe.push(meanPairedSe);
        summary[count]?.headlineHalfWidth.push(1.96 * binomial * 100);
        if (summary[count] !== undefined) summary[count].withinOne += within;
        row[`n${String(count)}`] = {
          seedSd: sd,
          binomialSe: binomial,
          deltaSd,
          meanPairedSe,
          withinOneOfReference: within / SEEDS,
        };
      }
      rows.push(row);
    }

    const median = (values: number[]): number => {
      const sorted = [...values].sort((a, b) => a - b);
      return sorted[Math.floor(sorted.length / 2)] ?? Number.NaN;
    };
    const verdicts = COUNTS.map((count) => {
      const entry = summary[count];
      if (entry === undefined) return { count };
      const worstHalfWidth = 1.96 * Math.sqrt(0.25 / count) * 100;
      const sdRatioMedian = median(entry.sdRatio);
      const pairedSeMedian = median(entry.pairedSe) * 100;
      const withinOne = entry.withinOne / (MATCHUPS * SEEDS);
      return {
        count,
        worstCaseHalfWidthPts: worstHalfWidth,
        rule1HalfWidth: worstHalfWidth <= 1.1,
        seedSdOverBinomialMedian: sdRatioMedian,
        seedSdOverBinomialRange: [Math.min(...entry.sdRatio), Math.max(...entry.sdRatio)],
        rule1Spread: Math.abs(sdRatioMedian - 1) <= 0.2,
        pairedSeMedianPts: pairedSeMedian,
        rule2: pairedSeMedian <= 0.5,
        withinOnePointOfReference: withinOne,
        rule3: withinOne >= 0.95,
        msPerRunMedian: median(entry.ms),
      };
    });
    const report = {
      adr: "ADR-110",
      engine: MATCHUP_ENGINE_VERSION,
      source: { build_id: records[0]?.build_id, target_week: records[0]?.target_week, scoring: "PPR" },
      matchups: MATCHUPS,
      seeds: SEEDS,
      reference_draws: REFERENCE,
      verdicts,
      rows,
    };
    if (REPORT !== undefined) {
      mkdirSync(dirname(REPORT), { recursive: true });
      writeFileSync(REPORT, `${JSON.stringify(report, null, 1)}\n`);
    }
    console.log(JSON.stringify(verdicts, null, 1));
    expect(verdicts.length).toBe(COUNTS.length);
  });
});
