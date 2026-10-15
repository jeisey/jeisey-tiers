/**
 * Win My Matchup's simulation engine (ADR-110, `matchup_sim_v1`): two entered lineups, one
 * seeded joint simulation, and the probability picture a manager can read.
 *
 * **What it answers.** How often my modelled lineup outscores the opponent's, by how much, which
 * slot groups carry or expose me, and how much a proposed lineup changes that — all from one set
 * of simulated games, so every number on the page is read off the same draws.
 *
 * **The model is the published one.** Each player's outcome is a draw from his own seven
 * published `weekly-startsit-v1` quantiles under `quantile_distribution_v1` (the knots
 * `startsit.ts` builds, tails included): q90 is an upside percentile, not a ceiling, and a
 * negative week stays negative. Players in one NFL game are joined by a Gaussian copula with the
 * build's **latent** same-game correlation (`rho`, never the Spearman value it was converted
 * from), across both fantasy teams; different games are independent. Nothing here adds the
 * Start/Sit margin uncertainty (two simulated lineups already carry it), multiplies a projection
 * by an appearance rate, or multiplies group probabilities together.
 *
 * **A block that is not a valid joint correlation is not repaired.** Pairwise entries need not
 * form a positive-definite matrix. A game whose block fails Cholesky is simulated independently
 * and the result names it; there is no nearest-matrix projection and no invented value.
 *
 * **Seeded, and coupled.** Player `p`'s uniform in draw `d` is a hash of `(seed, p's id, d)`, so
 * the same inputs give the same answer, the order of slots or players changes nothing, and every
 * proposal reuses the baseline's draws (common random numbers). Within a game, a proposal's block
 * lists the baseline's players first, in canonical order, then its new players: the baseline
 * players' latent values are then the leading Cholesky block, identical in every variant, and a
 * swap's effect is measured on the same simulated games rather than on a reroll.
 *
 * **Ties** are totals equal to the hundredth of a point. Win, tie and loss are kept apart.
 *
 * This module is the contract — versions, bounds, input and result shapes — and the wording the
 * page prints. The engine itself is `matchupEngine.ts`, which the worker runs and the sliced
 * main-thread fallback imports only when the worker cannot run, so the view's chunk does not
 * carry a second copy of it.
 *
 * Pure: no DOM, no React, no store.
 */

/** Bump when how a draw, a total, a tie or a summary is computed changes. */
export const MATCHUP_ENGINE_VERSION = "matchup_sim_v1";
/** The fixed seed: one set of simulated games for one set of inputs (ADR-110 §3). */
export const MATCHUP_SEED = 20261015;
/** Simulated games per run. Frozen by ADR-110's convergence measurement (see Evidence). */
export const MATCHUP_DRAWS = 8192;
/** The hard cap: the engine refuses more. */
export const MATCHUP_MAX_DRAWS = 65536;
/** Baseline plus proposals, per run. */
export const MATCHUP_MAX_VARIANTS = 32;
/** Unique players a run may name: both lineups, a roster's bench and the YOLO candidates. */
export const MATCHUP_MAX_PLAYERS = 64;
/** Starters a side may field: 2 QB, 4 RB, 4 WR, 2 TE, 3 FLEX (ADR-106's bounds). */
export const MATCHUP_MAX_SLOTS = 15;
/** The largest margin histogram. */
export const MATCHUP_MAX_BINS = 48;

export const SIM_GROUPS = ["QB", "RB", "WR", "TE", "FLEX"] as const;
export type SimGroup = (typeof SIM_GROUPS)[number];

export interface SimPlayer {
  /** Canonical player id: what the generator is keyed by. */
  readonly key: string;
  /** Inverse-CDF knots: probabilities ascending from 0 to 1, values non-decreasing. */
  readonly taus: readonly number[];
  readonly values: readonly number[];
  /** The NFL game id, or null when he has none (then he joins no correlation block). */
  readonly game: string | null;
  readonly team: string;
  readonly position: string;
}

export interface SimSlot {
  readonly group: SimGroup;
  /** Index into `players`, or -1 for a fixed contribution. */
  readonly player: number;
  /** Points counted once when `player` is -1: a confirmed final, a bye or a confirmed zero. */
  readonly fixed: number;
}

export interface SimVariant {
  readonly id: string;
  readonly slots: readonly SimSlot[];
  /** Keep per-group distributions (the baseline, and a previewed proposal). */
  readonly detail: boolean;
}

export interface SimInput {
  readonly version: string;
  readonly seed: number;
  readonly draws: number;
  readonly players: readonly SimPlayer[];
  /** Latent same-game correlations by key: `teammates:QB-WR`, `opponents:any`. */
  readonly correlation: Readonly<Record<string, number>>;
  readonly opponent: readonly SimSlot[];
  /** `variants[0]` is my baseline; the rest are proposals compared against it. */
  readonly variants: readonly SimVariant[];
}

export interface Spread {
  readonly p10: number;
  readonly p25: number;
  readonly p50: number;
  readonly p75: number;
  readonly p90: number;
  readonly mean: number;
}

export interface GroupComparison {
  readonly group: SimGroup;
  readonly slots: number;
  readonly mine: Spread;
  readonly theirs: Spread;
  /** P(my group's total is higher), from the same draws. */
  readonly ahead: number;
  readonly tie: number;
}

export interface PairedDelta {
  /** P(win) of this variant minus the baseline's, on the same draws. */
  readonly win: number;
  /** Its numerical standard error, from the paired differences. */
  readonly se: number;
  /** My total's median and 90th percentile, this variant minus the baseline. */
  readonly p50: number;
  readonly p90: number;
}

export interface VariantResult {
  readonly id: string;
  readonly win: number;
  readonly tie: number;
  readonly loss: number;
  /** Numerical standard error of `win` (binomial). Not the model's uncertainty. */
  readonly se: number;
  readonly mine: Spread;
  readonly margin: Spread;
  /** Margin counts on the run's shared bins. */
  readonly histogram: readonly number[];
  readonly groups: readonly GroupComparison[] | null;
  readonly paired: PairedDelta | null;
  /** A correlation block that held in the baseline failed with this variant's players added. */
  readonly couplingReduced: boolean;
}

export interface SimNote {
  readonly kind: "unmeasured_pair" | "block_fallback";
  /** The correlation key, or the game id. */
  readonly subject: string;
  /** The variant ids it applies to; empty for the baseline (and so every variant). */
  readonly variants: readonly string[];
}

export interface SimResult {
  readonly version: string;
  readonly seed: number;
  readonly draws: number;
  readonly theirs: Spread;
  /**
   * Margin bins shared by every lineup in the run, spanning the baseline's and each detailed
   * lineup's 0.5th–99.5th percentiles: `[start + i·width, start + (i+1)·width)`; the first and
   * last absorb the tails.
   */
  readonly bins: { readonly start: number; readonly width: number; readonly count: number };
  readonly variants: readonly VariantResult[];
  readonly notes: readonly SimNote[];
}

// ---------------------------------------------------------------------------- reading it

/** A probability as the headline prints it: whole percent, with honest extremes. */
export function percentLabel(probability: number): string {
  if (!Number.isFinite(probability)) return "—";
  if (probability < 0.005) return "<1%";
  if (probability > 0.995) return ">99%";
  return `${String(Math.round(probability * 100))}%`;
}

/** A tie's probability: to a tenth of a point, "<0.1%" below that. */
export function tieLabel(probability: number): string {
  if (!Number.isFinite(probability)) return "—";
  if (probability === 0) return "0%";
  if (probability < 0.001) return "<0.1%";
  return `${(probability * 100).toFixed(1)}%`;
}

/** ±1.96·SE in percentage points, the simulation noise around a probability. */
export function noisePoints(se: number): number {
  return 1.96 * se * 100;
}

/** ADR-110 §3: a difference is reported only past both the noise band and half a point. */
export function meaningfulDelta(delta: PairedDelta): boolean {
  return Math.abs(delta.win) > 1.96 * delta.se && Math.abs(delta.win) >= 0.005;
}
