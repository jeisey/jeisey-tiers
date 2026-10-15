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
 * Pure: no DOM, no React, no store. The worker (`matchup.worker.ts`) and the sliced fallback in
 * `matchupClient.ts` both drive `createRun`.
 */

import { interp, normalCdf, normalQuantile } from "./startsit";

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
/** A Cholesky pivot at or below this is "not positive definite". */
const PIVOT_FLOOR = 1e-9;

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
  /** Margin bins: `[start + i·width, start + (i+1)·width)`; the first and last absorb the tails. */
  readonly bins: { readonly start: number; readonly width: number; readonly count: number };
  readonly variants: readonly VariantResult[];
  readonly notes: readonly SimNote[];
}

// ------------------------------------------------------------------------------ validation

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** `Array.isArray` without narrowing the typed input to `any[]`: the input crossed a worker boundary. */
function isList(value: unknown): boolean {
  return Array.isArray(value);
}

function checkSlots(slots: readonly SimSlot[], players: number, label: string): string | null {
  if (!isList(slots) || slots.length === 0) return `${label} has no starters`;
  if (slots.length > MATCHUP_MAX_SLOTS) return `${label} has more than ${String(MATCHUP_MAX_SLOTS)} starters`;
  const seen = new Set<number>();
  for (const slot of slots) {
    if (!(SIM_GROUPS as readonly string[]).includes(slot.group)) return `${label} names an unknown slot group`;
    if (!Number.isInteger(slot.player) || slot.player < -1 || slot.player >= players) {
      return `${label} names a player out of range`;
    }
    if (!finite(slot.fixed) || Math.abs(slot.fixed) > 1000) return `${label} has an invalid fixed score`;
    if (slot.player >= 0) {
      if (seen.has(slot.player)) return `${label} starts one player twice`;
      seen.add(slot.player);
    }
  }
  return null;
}

/** The first reason an input cannot be simulated, or null. Never throws. */
export function validateSimInput(input: SimInput): string | null {
  if (input.version !== MATCHUP_ENGINE_VERSION) return `engine version ${input.version} is not ${MATCHUP_ENGINE_VERSION}`;
  if (!Number.isInteger(input.seed)) return "the seed is not an integer";
  if (!Number.isInteger(input.draws) || input.draws < 1 || input.draws > MATCHUP_MAX_DRAWS) {
    return `draws must be 1–${String(MATCHUP_MAX_DRAWS)}`;
  }
  const players = input.players;
  if (!isList(players) || players.length > MATCHUP_MAX_PLAYERS) return "too many players";
  const keys = new Set<string>();
  for (const player of players) {
    if (typeof player.key !== "string" || player.key === "" || keys.has(player.key)) return "player keys must be unique";
    keys.add(player.key);
    const { taus, values } = player;
    if (!isList(taus) || !isList(values) || taus.length < 2 || taus.length !== values.length) return `${player.key}: malformed knots`;
    if (taus[0] !== 0 || taus[taus.length - 1] !== 1) return `${player.key}: knots must span 0 to 1`;
    for (let i = 0; i < taus.length; i += 1) {
      const tau = taus[i];
      const value = values[i];
      if (!finite(tau) || !finite(value)) return `${player.key}: a knot is not finite`;
      if (i > 0 && (tau < (taus[i - 1] ?? 0) || value < (values[i - 1] ?? 0))) {
        return `${player.key}: knots must not decrease`;
      }
    }
  }
  for (const [key, rho] of Object.entries(input.correlation)) {
    if (!finite(rho) || Math.abs(rho) >= 1) return `correlation ${key} is not in (−1, 1)`;
  }
  const opponentProblem = checkSlots(input.opponent, players.length, "the opponent's lineup");
  if (opponentProblem !== null) return opponentProblem;
  if (!isList(input.variants) || input.variants.length === 0) return "no lineup to simulate";
  if (input.variants.length > MATCHUP_MAX_VARIANTS) return `more than ${String(MATCHUP_MAX_VARIANTS)} lineups`;
  const opponentPlayers = new Set(input.opponent.filter((slot) => slot.player >= 0).map((slot) => slot.player));
  const ids = new Set<string>();
  for (const variant of input.variants) {
    if (ids.has(variant.id)) return "lineup ids must be unique";
    ids.add(variant.id);
    const problem = checkSlots(variant.slots, players.length, `lineup ${variant.id}`);
    if (problem !== null) return problem;
    if (variant.slots.some((slot: SimSlot) => slot.player >= 0 && opponentPlayers.has(slot.player))) {
      return `lineup ${variant.id} shares a player with the opponent`;
    }
  }
  return null;
}

// ------------------------------------------------------------------------------ randomness

/** FNV-1a over UTF-16 code units. */
function hashKey(key: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i += 1) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** `lowbias32`: a 32-bit integer hash with good avalanche. */
function mix32(input: number): number {
  let x = input >>> 0;
  x ^= x >>> 16;
  x = Math.imul(x, 0x7feb352d);
  x ^= x >>> 15;
  x = Math.imul(x, 0x846ca68b);
  x ^= x >>> 16;
  return x >>> 0;
}

/** A player's stream, from the seed and his id only. */
export function playerStream(seed: number, key: string): number {
  return mix32(mix32(seed >>> 0) ^ hashKey(key));
}

/** His uniform in draw `draw`: strictly inside (0, 1), never exactly 0, ½ or 1. */
export function uniformAt(stream: number, draw: number): number {
  const word = mix32(stream ^ mix32(Math.imul(draw + 1, 0x9e3779b9) ^ 0x632be5ab));
  return (word + 0.5) / 4294967296;
}

// ---------------------------------------------------------------------------- correlation

/** The correlation key for two players in one game, Start/Sit's rule (`pairCorrelation`). */
export function correlationKey(a: SimPlayer, b: SimPlayer): string {
  return a.team === b.team ? `teammates:${[a.position, b.position].sort().join("-")}` : "opponents:any";
}

/** Lower-triangular Cholesky factor, or null when a pivot is not safely positive. */
export function choleskyFactor(matrix: readonly (readonly number[])[]): number[][] | null {
  const n = matrix.length;
  const lower = Array.from({ length: n }, () => new Array<number>(n).fill(0));
  for (let i = 0; i < n; i += 1) {
    const row = lower[i] ?? [];
    for (let j = 0; j <= i; j += 1) {
      let sum = matrix[i]?.[j] ?? 0;
      const other = lower[j] ?? [];
      for (let k = 0; k < j; k += 1) sum -= (row[k] ?? 0) * (other[k] ?? 0);
      if (i === j) {
        if (!(sum > PIVOT_FLOOR)) return null;
        row[j] = Math.sqrt(sum);
      } else {
        row[j] = sum / (other[j] ?? 1);
      }
    }
  }
  return lower;
}

/** One game's players in block order, its factor (null: independent), and why. */
interface Block {
  readonly game: string;
  readonly members: readonly number[];
  readonly factor: readonly (readonly number[])[] | null;
  readonly failed: boolean;
}

function blockMatrix(
  members: readonly number[],
  players: readonly SimPlayer[],
  correlation: Readonly<Record<string, number>>,
  unmeasured: Set<string>,
): number[][] {
  return members.map((a, i) =>
    members.map((b, j) => {
      if (i === j) return 1;
      const pa = players[a];
      const pb = players[b];
      if (pa === undefined || pb === undefined) return 0;
      const key = correlationKey(pa, pb);
      const rho = correlation[key];
      if (rho === undefined) {
        unmeasured.add(key);
        return 0;
      }
      return rho;
    }),
  );
}

function canonical(players: readonly SimPlayer[]) {
  return (a: number, b: number): number => {
    const ka = players[a]?.key ?? "";
    const kb = players[b]?.key ?? "";
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  };
}

/** Group active players by game, canonical order within each; a lone player is no block. */
function gamesOf(active: readonly number[], players: readonly SimPlayer[]): Map<string, number[]> {
  const games = new Map<string, number[]>();
  for (const index of [...active].sort(canonical(players))) {
    const game = players[index]?.game ?? null;
    if (game === null) continue;
    const members = games.get(game) ?? [];
    members.push(index);
    games.set(game, members);
  }
  return games;
}

function buildBlock(
  game: string,
  members: readonly number[],
  players: readonly SimPlayer[],
  correlation: Readonly<Record<string, number>>,
  unmeasured: Set<string>,
): Block {
  const matrix = blockMatrix(members, players, correlation, unmeasured);
  const allZero = matrix.every((row, i) => row.every((value, j) => i === j || value === 0));
  if (allZero) return { game, members, factor: null, failed: false };
  const factor = choleskyFactor(matrix);
  return { game, members, factor, failed: factor === null };
}

// ------------------------------------------------------------------------------- the plan

/** How one variant reads a player's value in a draw. */
interface Override {
  readonly player: number;
  /** Null: independent (his own uniform). Otherwise his latent row over `cols`' innovations. */
  readonly row: Float64Array | null;
  readonly cols: Int32Array | null;
}

interface VariantPlan {
  readonly id: string;
  readonly detail: boolean;
  readonly slotPlayer: Int32Array;
  readonly slotFixed: Float64Array;
  readonly slotGroup: Uint8Array;
  /** 1 where the slot reads this variant's own value rather than the baseline's. */
  readonly slotOwn: Uint8Array;
  readonly overrides: readonly Override[];
  readonly couplingReduced: boolean;
}

function slotArrays(slots: readonly SimSlot[]) {
  return {
    slotPlayer: Int32Array.from(slots.map((slot) => slot.player)),
    slotFixed: Float64Array.from(slots.map((slot) => (slot.player >= 0 ? 0 : slot.fixed))),
    slotGroup: Uint8Array.from(slots.map((slot) => SIM_GROUPS.indexOf(slot.group))),
  };
}

function activeOf(slots: readonly SimSlot[]): number[] {
  return slots.filter((slot) => slot.player >= 0).map((slot) => slot.player);
}

/** A player's latent row: the block factor's row, over the block members' innovations. */
function latentRow(block: Block, position: number): { row: Float64Array; cols: Int32Array } {
  const factorRow = block.factor?.[position] ?? [];
  const row = new Float64Array(position + 1);
  const cols = new Int32Array(position + 1);
  for (let k = 0; k <= position; k += 1) {
    row[k] = factorRow[k] ?? 0;
    cols[k] = block.members[k] ?? 0;
  }
  return { row, cols };
}

interface Plan {
  readonly streams: Uint32Array;
  /** Players whose innovation (a normal) some block reads. */
  readonly needsNormal: Uint8Array;
  /** Baseline-active players: computed once per draw. */
  readonly baseActive: Int32Array;
  /** For each baseline-active player: null (independent) or his latent row. */
  readonly baseRows: readonly ({ row: Float64Array; cols: Int32Array } | null)[];
  readonly opponent: ReturnType<typeof slotArrays>;
  readonly variants: readonly VariantPlan[];
  readonly notes: readonly SimNote[];
}

function makePlan(input: SimInput): Plan {
  const { players, correlation } = input;
  const unmeasured = new Set<string>();
  const notes: SimNote[] = [];
  const opponentActive = activeOf(input.opponent);
  const baseline = input.variants[0];
  if (baseline === undefined) throw new Error("no baseline");
  const baseActiveList = [...new Set([...opponentActive, ...activeOf(baseline.slots)])].sort(canonical(players));
  const baseSet = new Set(baseActiveList);
  const needsNormal = new Uint8Array(players.length);

  const baseGames = gamesOf(baseActiveList, players);
  const baseBlocks = new Map<string, Block>();
  for (const [game, members] of baseGames) {
    if (members.length < 2) continue;
    const block = buildBlock(game, members, players, correlation, unmeasured);
    baseBlocks.set(game, block);
    if (block.failed) notes.push({ kind: "block_fallback", subject: game, variants: [] });
  }
  const baseRowByPlayer = new Map<number, { row: Float64Array; cols: Int32Array }>();
  for (const block of baseBlocks.values()) {
    if (block.factor === null) continue;
    block.members.forEach((member, position) => {
      baseRowByPlayer.set(member, latentRow(block, position));
      needsNormal[member] = 1;
    });
  }
  const baseRows = baseActiveList.map((player) => baseRowByPlayer.get(player) ?? null);

  const variants: VariantPlan[] = input.variants.map((variant, index) => {
    const arrays = slotArrays(variant.slots);
    if (index === 0) {
      return { id: variant.id, detail: variant.detail, ...arrays, slotOwn: new Uint8Array(variant.slots.length), overrides: [], couplingReduced: false };
    }
    const fresh = activeOf(variant.slots).filter((player) => !baseSet.has(player)).sort(canonical(players));
    const freshGames = gamesOf(fresh, players);
    const overrides: Override[] = [];
    const own = new Set<number>();
    let couplingReduced = false;
    // New players with no game, or alone in a game no baseline player is in, are independent.
    for (const player of fresh) {
      const game = players[player]?.game ?? null;
      const baseMembers = game === null ? [] : (baseGames.get(game) ?? []);
      const freshMembers = game === null ? [player] : (freshGames.get(game) ?? [player]);
      if (game === null || baseMembers.length + freshMembers.length < 2) {
        overrides.push({ player, row: null, cols: null });
        own.add(player);
      }
    }
    for (const [game, freshMembers] of freshGames) {
      const baseMembers = baseGames.get(game) ?? [];
      if (baseMembers.length + freshMembers.length < 2) continue;
      const members = [...baseMembers, ...freshMembers];
      const block = buildBlock(game, members, players, correlation, unmeasured);
      const baseBlock = baseBlocks.get(game);
      if (block.factor === null) {
        // Independent: the new players read their own uniforms. When the baseline's block held
        // and this one did not, the baseline players lose their correlation here too.
        for (const member of freshMembers) {
          overrides.push({ player: member, row: null, cols: null });
          own.add(member);
        }
        if (block.failed && baseBlock !== undefined && baseBlock.factor !== null) {
          couplingReduced = true;
          for (const member of baseMembers) {
            overrides.push({ player: member, row: null, cols: null });
            own.add(member);
          }
        }
        if (block.failed) notes.push({ kind: "block_fallback", subject: game, variants: [variant.id] });
        continue;
      }
      // The baseline members lead the block: their rows are the baseline's own, unchanged.
      freshMembers.forEach((member, offset) => {
        const { row, cols } = latentRow(block, baseMembers.length + offset);
        overrides.push({ player: member, row, cols });
        own.add(member);
        for (const col of cols) needsNormal[col] = 1;
      });
    }
    const slotOwn = Uint8Array.from(variant.slots.map((slot) => (slot.player >= 0 && own.has(slot.player) ? 1 : 0)));
    return { id: variant.id, detail: variant.detail, ...arrays, slotOwn, overrides, couplingReduced };
  });

  for (const key of [...unmeasured].sort()) notes.push({ kind: "unmeasured_pair", subject: key, variants: [] });
  return {
    streams: Uint32Array.from(players.map((player) => playerStream(input.seed, player.key))),
    needsNormal,
    baseActive: Int32Array.from(baseActiveList),
    baseRows,
    opponent: slotArrays(input.opponent),
    variants,
    notes,
  };
}

// -------------------------------------------------------------------------------- the run

function toHundredths(points: number): number {
  return Math.round(points * 100);
}

/** Type-7 quantile of hundredths, in points. */
function quantileOf(sorted: Int32Array, q: number): number {
  const n = sorted.length;
  if (n === 0) return Number.NaN;
  const position = (n - 1) * q;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const low = sorted[lower] ?? 0;
  const high = sorted[upper] ?? 0;
  return (low + (high - low) * (position - lower)) / 100;
}

function spreadOf(values: Int32Array): Spread {
  const sorted = Int32Array.from(values).sort();
  let total = 0;
  for (const value of values) total += value;
  return {
    p10: quantileOf(sorted, 0.1),
    p25: quantileOf(sorted, 0.25),
    p50: quantileOf(sorted, 0.5),
    p75: quantileOf(sorted, 0.75),
    p90: quantileOf(sorted, 0.9),
    mean: values.length === 0 ? Number.NaN : total / values.length / 100,
  };
}

const NICE_WIDTHS = [0.5, 1, 2, 2.5, 5, 10, 20, 25, 50];

/** Shared margin bins from the baseline's margins: zero is always an edge. */
export function marginBins(margins: Int32Array): SimResult["bins"] {
  const sorted = Int32Array.from(margins).sort();
  const low = quantileOf(sorted, 0.005);
  const high = quantileOf(sorted, 0.995);
  const span = Math.max(high - low, 1);
  const width = NICE_WIDTHS.find((candidate) => span / candidate <= MATCHUP_MAX_BINS - 2) ?? 100;
  let start = Math.floor(Math.min(low, 0) / width) * width;
  let end = Math.ceil(Math.max(high, 0) / width) * width;
  if (end <= start) end = start + width;
  let count = Math.round((end - start) / width);
  // Keep the bins centred on what was simulated when a bound had to stretch to include zero.
  while (count > MATCHUP_MAX_BINS) {
    if (Math.abs(start) > Math.abs(end)) start += width;
    else end -= width;
    count -= 1;
  }
  return { start, width, count };
}

function histogramOf(margins: Int32Array, bins: SimResult["bins"]): number[] {
  const counts = new Array<number>(bins.count).fill(0);
  const startH = toHundredths(bins.start);
  const widthH = toHundredths(bins.width);
  for (const margin of margins) {
    const index = Math.min(bins.count - 1, Math.max(0, Math.floor((margin - startH) / widthH)));
    counts[index] = (counts[index] ?? 0) + 1;
  }
  return counts;
}

export interface Run {
  readonly draws: number;
  /** Draws simulated so far. */
  done(): number;
  /** Simulate up to `count` more draws. True when every draw is done. */
  step(count: number): boolean;
  /** The summary; throws if called before every draw is done. */
  result(): SimResult;
}

/** Set up one run. Validates first; throws with the reason when the input is unusable. */
export function createRun(input: SimInput): Run {
  const problem = validateSimInput(input);
  if (problem !== null) throw new Error(problem);
  const plan = makePlan(input);
  const n = input.draws;
  const playerCount = input.players.length;
  const knots = input.players.map((player) => ({ taus: player.taus, values: player.values }));

  const uniform = new Float64Array(playerCount);
  const normal = new Float64Array(playerCount);
  const base = new Float64Array(playerCount);
  const own = new Float64Array(playerCount);
  const groupCount = SIM_GROUPS.length;
  const theirGroups = new Float64Array(groupCount);
  const myGroups = new Float64Array(groupCount);

  const anyDetail = plan.variants.some((variant) => variant.detail);
  const theirTotals = new Int32Array(n);
  const theirGroupTotals = anyDetail ? Array.from({ length: groupCount }, () => new Int32Array(n)) : null;
  const myTotals = plan.variants.map(() => new Int32Array(n));
  const myGroupTotals = plan.variants.map((variant) =>
    variant.detail ? Array.from({ length: groupCount }, () => new Int32Array(n)) : null,
  );
  const wins = new Uint8Array(n * plan.variants.length);
  const counts = plan.variants.map(() => ({ win: 0, tie: 0 }));
  const groupAhead = plan.variants.map(() => new Float64Array(groupCount));
  const groupTie = plan.variants.map(() => new Float64Array(groupCount));
  // A group is compared when either side starts anyone in it (both sides share the league's
  // slot counts, so in practice the two counts agree).
  const groupSlots = new Int32Array(groupCount);
  const mySlots = new Int32Array(groupCount);
  for (const group of plan.opponent.slotGroup) groupSlots[group] = (groupSlots[group] ?? 0) + 1;
  for (const group of plan.variants[0]?.slotGroup ?? []) mySlots[group] = (mySlots[group] ?? 0) + 1;
  for (let g = 0; g < groupCount; g += 1) groupSlots[g] = Math.max(groupSlots[g] ?? 0, mySlots[g] ?? 0);

  let next = 0;

  const valueOf = (player: number, u: number): number => {
    const set = knots[player];
    return set === undefined ? 0 : interp(u, set.taus, set.values);
  };
  const latent = (row: Float64Array, cols: Int32Array): number => {
    let z = 0;
    for (let k = 0; k < row.length; k += 1) z += (row[k] ?? 0) * (normal[cols[k] ?? 0] ?? 0);
    return z;
  };

  const baseActive = plan.baseActive;
  const baseRows = plan.baseRows;
  const streams = plan.streams;
  const needsNormal = plan.needsNormal;
  const opp = plan.opponent;
  const variantPlans = plan.variants;
  const variantCount = variantPlans.length;

  const simulateDraw = (draw: number): void => {
    for (let p = 0; p < playerCount; p += 1) {
      const u = uniformAt(streams[p] ?? 0, draw);
      uniform[p] = u;
      if (needsNormal[p] === 1) normal[p] = normalQuantile(u);
    }
    for (let index = 0; index < baseActive.length; index += 1) {
      const player = baseActive[index] ?? 0;
      const row = baseRows[index] ?? null;
      base[player] = row === null ? valueOf(player, uniform[player] ?? 0.5) : valueOf(player, normalCdf(latent(row.row, row.cols)));
    }
    // The opponent: the same in every variant.
    theirGroups.fill(0);
    let theirs = 0;
    for (let s = 0; s < opp.slotPlayer.length; s += 1) {
      const player = opp.slotPlayer[s] ?? -1;
      const value = player >= 0 ? (base[player] ?? 0) : (opp.slotFixed[s] ?? 0);
      theirs += value;
      const group = opp.slotGroup[s] ?? 0;
      theirGroups[group] = (theirGroups[group] ?? 0) + value;
    }
    const theirH = toHundredths(theirs);
    theirTotals[draw] = theirH;
    if (theirGroupTotals !== null) {
      for (let g = 0; g < groupCount; g += 1) (theirGroupTotals[g] ?? theirTotals)[draw] = toHundredths(theirGroups[g] ?? 0);
    }
    for (let v = 0; v < variantCount; v += 1) {
      const variant = variantPlans[v];
      if (variant === undefined) continue;
      for (const override of variant.overrides) {
        own[override.player] =
          override.row === null || override.cols === null
            ? valueOf(override.player, uniform[override.player] ?? 0.5)
            : valueOf(override.player, normalCdf(latent(override.row, override.cols)));
      }
      myGroups.fill(0);
      let mine = 0;
      const slotPlayer = variant.slotPlayer;
      const slotOwn = variant.slotOwn;
      const slotFixed = variant.slotFixed;
      const slotGroup = variant.slotGroup;
      for (let s = 0; s < slotPlayer.length; s += 1) {
        const player = slotPlayer[s] ?? -1;
        const value = player < 0 ? (slotFixed[s] ?? 0) : slotOwn[s] === 1 ? (own[player] ?? 0) : (base[player] ?? 0);
        mine += value;
        const group = slotGroup[s] ?? 0;
        myGroups[group] = (myGroups[group] ?? 0) + value;
      }
      const mineH = toHundredths(mine);
      (myTotals[v] ?? theirTotals)[draw] = mineH;
      const tally = counts[v];
      if (tally !== undefined) {
        if (mineH > theirH) {
          tally.win += 1;
          wins[v * n + draw] = 1;
        } else if (mineH === theirH) {
          tally.tie += 1;
        }
      }
      const groups = myGroupTotals[v];
      if (groups !== null && groups !== undefined) {
        const ahead = groupAhead[v];
        const tie = groupTie[v];
        for (let g = 0; g < groupCount; g += 1) {
          const a = toHundredths(myGroups[g] ?? 0);
          const b = toHundredths(theirGroups[g] ?? 0);
          (groups[g] ?? theirTotals)[draw] = a;
          if (ahead !== undefined && a > b) ahead[g] = (ahead[g] ?? 0) + 1;
          else if (tie !== undefined && a === b) tie[g] = (tie[g] ?? 0) + 1;
        }
      }
    }
  };

  return {
    draws: n,
    done: () => next,
    step(count: number): boolean {
      const end = Math.min(n, next + Math.max(0, Math.floor(count)));
      for (; next < end; next += 1) simulateDraw(next);
      return next >= n;
    },
    result(): SimResult {
      if (next < n) throw new Error("the run is not finished");
      const baseTotals = myTotals[0] ?? theirTotals;
      const baseMargins = new Int32Array(n);
      for (let d = 0; d < n; d += 1) baseMargins[d] = (baseTotals[d] ?? 0) - (theirTotals[d] ?? 0);
      const bins = marginBins(baseMargins);
      const baseSpread = spreadOf(baseTotals);
      const variants = plan.variants.map((variant, v): VariantResult => {
        const totals = myTotals[v] ?? baseTotals;
        const margins = new Int32Array(n);
        for (let d = 0; d < n; d += 1) margins[d] = (totals[d] ?? 0) - (theirTotals[d] ?? 0);
        const tally = counts[v] ?? { win: 0, tie: 0 };
        const win = tally.win / n;
        const tie = tally.tie / n;
        const mine = v === 0 ? baseSpread : spreadOf(totals);
        let paired: PairedDelta | null = null;
        if (v > 0) {
          let sum = 0;
          let squares = 0;
          for (let d = 0; d < n; d += 1) {
            const diff = (wins[v * n + d] ?? 0) - (wins[d] ?? 0);
            sum += diff;
            squares += diff * diff;
          }
          const mean = sum / n;
          const variance = n > 1 ? Math.max(0, (squares - n * mean * mean) / (n - 1)) : 0;
          paired = { win: mean, se: Math.sqrt(variance / n), p50: mine.p50 - baseSpread.p50, p90: mine.p90 - baseSpread.p90 };
        }
        const groupTotals = myGroupTotals[v];
        const groups =
          groupTotals === null || groupTotals === undefined || theirGroupTotals === null
            ? null
            : SIM_GROUPS.flatMap((group, g): GroupComparison[] =>
                (groupSlots[g] ?? 0) === 0
                  ? []
                  : [
                      {
                        group,
                        slots: groupSlots[g] ?? 0,
                        mine: spreadOf(groupTotals[g] ?? theirTotals),
                        theirs: spreadOf(theirGroupTotals[g] ?? theirTotals),
                        ahead: (groupAhead[v]?.[g] ?? 0) / n,
                        tie: (groupTie[v]?.[g] ?? 0) / n,
                      },
                    ],
              );
        return {
          id: variant.id,
          win,
          tie,
          loss: Math.max(0, 1 - win - tie),
          se: Math.sqrt((win * (1 - win)) / n),
          mine,
          margin: spreadOf(margins),
          histogram: histogramOf(margins, bins),
          groups,
          paired,
          couplingReduced: variant.couplingReduced,
        };
      });
      return {
        version: MATCHUP_ENGINE_VERSION,
        seed: input.seed,
        draws: n,
        theirs: spreadOf(theirTotals),
        bins,
        variants,
        notes: plan.notes,
      };
    },
  };
}

/** Run to completion. */
export function simulateMatchup(input: SimInput): SimResult {
  const run = createRun(input);
  run.step(run.draws);
  return run.result();
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
