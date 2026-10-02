/**
 * The Trade tab's engine: comparable rest-of-season value first, the reader's preference second
 * (ADR-100, `trade_targets_v1`).
 *
 * Pure and deterministic: published `ros_tiers` records of one block in, ranked packages out.
 * Nothing here reads React, the DOM, a clock or a random number, and nothing here changes a
 * published value — a single player's floor and ceiling are his published P10 and P90, and a
 * package's expected value is the sum of published expectations.
 *
 * The parts, in ADR order:
 *
 * 1. `tradeHorizon` — the weeks every number covers.
 * 2. `exclusionReason` — `trade_eligibility_v1`.
 * 3. `tradeBand` — `trade_band_v1`, and `member_share_v1` inside the search.
 * 4. `objectiveOf` / `comparePackages` — the three presets and the tie-breaks.
 * 5. `marginalKnots` / `marginalMoments` / `cornishFisher` — `ros_package_quantiles_v1`.
 * 6. `searchTrade` — `trade_search_v1`, exact and pruned.
 * 7. `dealingOrder`, `dealInitial`, `swapSlot`, `moreTargets`, `keepSlot` — `trade_explore_v1`.
 */

import type { Position, RosTierRecord } from "./contracts";
import { COMP_SLOTS, type CompSlot, type TradeCount, type TradeGoal } from "./state";

export { canonicalComp } from "./state";
import { MEMBER_SHARE_MIN, POOL_CAP, TAIL_FACTOR } from "./tradeMethod";
export {
  MEMBER_SHARE_MIN,
  POOL_CAP,
  TAIL_FACTOR,
  TRADE_DISTRIBUTION_VERSION,
  TRADE_METHOD_VERSION,
} from "./tradeMethod";

// ------------------------------------------------------------------------------- constants


export {
  COMP_SLOTS,
  DEFAULT_TRADE_RANGE,
  MAX_GIVE,
  MAX_KEEP,
  TRADE_COUNTS,
  TRADE_GOALS,
  TRADE_RANGES,
} from "./state";
export type { CompSlot, TradeCount, TradeGoal, TradeRange } from "./state";

export const VISIBLE_PACKAGES = 5;


/** A search that would visit more packages than this stops and says so. */
export const MAX_VISITS = 4_000_000;

/** Roster codes that mean a player cannot take the field (ADR-088 gate 5, ADR-100 §2). */
export const SEVERE_ROSTER_CODES: ReadonlySet<string> = new Set([
  "RES",
  "INA",
  "PUP",
  "NFI",
  "SUS",
  "CUT",
  "RET",
]);

/** The Cornish–Fisher skewness clamp, inside the expansion's monotone range. */
export const SKEW_CLAMP = 2;
/** Φ⁻¹(0.9). */
export const Z90 = 1.2815515655446004;

/** The published VORP quantile levels and their record fields. */
export const VORP_LEVELS = [0.1, 0.25, 0.5, 0.75, 0.9] as const;

const SLOT_POSITION: Readonly<Record<Exclude<CompSlot, "any">, Position>> = {
  qb: "QB",
  rb: "RB",
  wr: "WR",
  te: "TE",
};

// ------------------------------------------------------------------------------- horizon

/** The scored weeks behind every number on the tab (ADR-100 §1). */
export interface TradeHorizon {
  readonly firstWeek: number;
  readonly lastWeek: number;
  readonly weeks: number;
  /** The contract's last scored week (`fantasy_horizon`): 17 from 2021, 16 before. */
  readonly contractLastWeek: number;
  /** The NFL week the contract excludes: 18 from 2021, 17 before. */
  readonly excludedWeek: number;
  /** First week of `season_state_v1`'s three-week fantasy postseason, when it is inside. */
  readonly playoffFirstWeek: number | null;
  /** Whether the record's own horizon ends where the contract says it does. */
  readonly agreesWithContract: boolean;
}

export function tradeHorizon(
  season: number,
  throughWeek: number,
  records: readonly RosTierRecord[],
): TradeHorizon | null {
  const remaining = records.find(
    (record) => typeof record.remaining_horizon_weeks === "number",
  )?.remaining_horizon_weeks;
  if (remaining === undefined || !Number.isInteger(remaining) || remaining < 1) return null;
  const regular = season >= 2021 ? 18 : 17;
  const contractLastWeek = regular - 1;
  const firstWeek = throughWeek + 1;
  const lastWeek = throughWeek + remaining;
  const playoffStart = Math.max(1, contractLastWeek - 2);
  return {
    firstWeek,
    lastWeek,
    weeks: remaining,
    contractLastWeek,
    excludedWeek: regular,
    playoffFirstWeek: lastWeek >= playoffStart && lastWeek === contractLastWeek ? Math.max(firstWeek, playoffStart) : null,
    agreesWithContract: lastWeek === contractLastWeek,
  };
}

// ------------------------------------------------------------------- the marginal (§5)

export interface Knots {
  readonly taus: readonly number[];
  readonly values: readonly number[];
}

function vorpQuantiles(record: RosTierRecord): readonly number[] {
  return [
    record.ros_vorp_p10,
    record.ros_vorp_p25,
    record.ros_vorp_p50,
    record.ros_vorp_p75,
    record.ros_vorp_p90,
  ];
}

/**
 * `ros_marginal_pwl_v1`: the piecewise-linear quantile function through the five published
 * quantiles, tail knots at 0 and 1 by `TAIL_FACTOR`, and one tail moved so the mean is the
 * published expectation exactly.
 */
export function marginalKnots(quantiles: readonly number[], mean: number): Knots {
  const [q10 = 0, q25 = 0, , q75 = 0, q90 = 0] = quantiles;
  const values = [q10 - TAIL_FACTOR * (q25 - q10), ...quantiles, q90 + TAIL_FACTOR * (q90 - q75)];
  const taus = [0, ...VORP_LEVELS, 1];
  const gap = mean - integrate(taus, values);
  // A linear end segment of width 0.1 moves its integral by 0.05 per unit of its outer knot.
  if (gap > 0) values[values.length - 1] = (values[values.length - 1] ?? 0) + gap / 0.05;
  else if (gap < 0) values[0] = (values[0] ?? 0) + gap / 0.05;
  return { taus, values };
}

function integrate(taus: readonly number[], values: readonly number[]): number {
  let total = 0;
  for (let i = 1; i < taus.length; i += 1) {
    total += ((taus[i] ?? 0) - (taus[i - 1] ?? 0)) * (((values[i] ?? 0) + (values[i - 1] ?? 0)) / 2);
  }
  return total;
}

/**
 * Mean, variance and third central moment of `Q(U)`, `U` uniform, in closed form.
 *
 * Over a linear segment from `y0` to `y1` (centred on the mean) of probability width `w`,
 * `∫ y^n = w · (y1^(n+1) − y0^(n+1)) / ((n+1)(y1 − y0))`, written as the symmetric sum so a
 * flat segment needs no special case and nothing cancels catastrophically.
 */
export function marginalMoments(knots: Knots, mean: number): { m2: number; m3: number } {
  let m2 = 0;
  let m3 = 0;
  for (let i = 1; i < knots.taus.length; i += 1) {
    const w = (knots.taus[i] ?? 0) - (knots.taus[i - 1] ?? 0);
    const a = (knots.values[i - 1] ?? 0) - mean;
    const b = (knots.values[i] ?? 0) - mean;
    m2 += (w * (b * b + a * b + a * a)) / 3;
    m3 += (w * (b * b * b + b * b * a + b * a * a + a * a * a)) / 4;
  }
  return { m2, m3 };
}

/** The one-term Cornish–Fisher quantile of a sum with cumulants `κ₁, κ₂, κ₃`. */
export function cornishFisher(k1: number, k2: number, k3: number, level: 0.1 | 0.9): number {
  if (!(k2 > 0)) return k1;
  const sigma = Math.sqrt(k2);
  const gamma = Math.max(-SKEW_CLAMP, Math.min(SKEW_CLAMP, k3 / (k2 * sigma)));
  const z = level === 0.9 ? Z90 : -Z90;
  return k1 + sigma * (z + ((z * z - 1) * gamma) / 6);
}

// ------------------------------------------------------------------------- players (§2)

/** One player as the engine reads him: published fields plus his marginal's cumulants. */
export interface PricedPlayer {
  readonly record: RosTierRecord;
  readonly id: string;
  /** `ros_expected_vorp`. */
  readonly value: number;
  readonly points: number;
  readonly p10: number;
  readonly p90: number;
  readonly m2: number;
  readonly m3: number;
}

/** `items[index]`, which must exist: an index the engine computed itself. */
function at<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new RangeError(`no item at ${String(index)}`);
  return item;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Null when the record cannot be priced: a missing or non-finite field, or crossed quantiles. */
export function priceRecord(record: RosTierRecord): PricedPlayer | null {
  const quantiles = vorpQuantiles(record);
  if (!finite(record.ros_expected_vorp) || !finite(record.ros_expected_points)) return null;
  if (!quantiles.every(finite)) return null;
  for (let i = 1; i < quantiles.length; i += 1) {
    if ((quantiles[i] ?? 0) < (quantiles[i - 1] ?? 0)) return null;
  }
  const knots = marginalKnots(quantiles, record.ros_expected_vorp);
  const { m2, m3 } = marginalMoments(knots, record.ros_expected_vorp);
  return {
    record,
    id: record.player_id,
    value: record.ros_expected_vorp,
    points: record.ros_expected_points,
    p10: record.ros_vorp_p10,
    p90: record.ros_vorp_p90,
    m2,
    m3,
  };
}

export type ExclusionReason =
  | "unpriced"
  | "outgoing"
  | "at_or_below_replacement"
  | "long_absence"
  | "roster_status";

export function severeStatus(status: string | null | undefined): string | null {
  if (status === null || status === undefined) return null;
  const code = status.trim().toUpperCase();
  return SEVERE_ROSTER_CODES.has(code) ? code : null;
}

/** `trade_eligibility_v1` for an incoming candidate; null means eligible. First failing rule. */
export function exclusionReason(
  record: RosTierRecord,
  outgoing: ReadonlySet<string>,
): ExclusionReason | null {
  if (priceRecord(record) === null) return "unpriced";
  if (outgoing.has(record.player_id)) return "outgoing";
  if (!(record.ros_expected_vorp > 0)) return "at_or_below_replacement";
  if (record.long_absence) return "long_absence";
  if (severeStatus(record.current_status) !== null) return "roster_status";
  return null;
}

// ------------------------------------------------------------------------- packages (§4)

export interface TradePackage {
  /** Members by expected value descending, then id ascending. */
  readonly members: readonly PricedPlayer[];
  /** Member ids sorted ascending and joined with `.`: one package, one key. */
  readonly key: string;
  /** `Σ ros_expected_vorp`, exact. */
  readonly value: number;
  /** `Σ ros_expected_points`, exact; supporting information only. */
  readonly points: number;
  /** Published for one player; `ros_package_quantiles_v1` for two or three. */
  readonly p10: number;
  readonly p90: number;
  readonly approximate: boolean;
  /** The best single member's expected value. */
  readonly top: number;
  /** The best single member's id: the package's lead in the dealing order. */
  readonly lead: string;
}

export function packageKey(ids: readonly string[]): string {
  return [...ids].sort().join(".");
}

function memberOrder(a: PricedPlayer, b: PricedPlayer): number {
  if (a.value !== b.value) return b.value - a.value;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function buildPackage(players: readonly PricedPlayer[]): TradePackage {
  const members = [...players].sort(memberOrder);
  let value = 0;
  let points = 0;
  let m2 = 0;
  let m3 = 0;
  for (const member of members) {
    value += member.value;
    points += member.points;
    m2 += member.m2;
    m3 += member.m3;
  }
  const single = members.length === 1 ? members[0] : undefined;
  const lead = members[0];
  return {
    members,
    key: packageKey(members.map((member) => member.id)),
    value,
    points,
    p10: single !== undefined ? single.p10 : cornishFisher(value, m2, m3, 0.1),
    p90: single !== undefined ? single.p90 : cornishFisher(value, m2, m3, 0.9),
    approximate: single === undefined,
    top: lead?.value ?? 0,
    lead: lead?.id ?? "",
  };
}

export function objectiveOf(pkg: Pick<TradePackage, "value" | "p10" | "p90">, goal: TradeGoal): number {
  return goal === "value" ? pkg.value : goal === "ceiling" ? pkg.p90 : pkg.p10;
}

/** The ranking: objective, expected value, best single asset (all descending), then key. */
export function comparePackages(a: TradePackage, b: TradePackage, goal: TradeGoal): number {
  const fa = objectiveOf(a, goal);
  const fb = objectiveOf(b, goal);
  if (fa !== fb) return fb - fa;
  if (a.value !== b.value) return b.value - a.value;
  if (a.top !== b.top) return b.top - a.top;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

// ------------------------------------------------------------------------- the band (§3)

export interface TradeBand {
  readonly low: number;
  readonly high: number;
  readonly range: number;
}

/** Null when the outgoing value is at or below replacement: there is no percentage of it. */
export function tradeBand(outgoingValue: number, range: number): TradeBand | null {
  if (!finite(outgoingValue) || outgoingValue <= 0) return null;
  const r = range / 100;
  return { low: outgoingValue * (1 - r), high: outgoingValue * (1 + r), range };
}

function tolerance(band: TradeBand): number {
  return 1e-9 * Math.max(1, Math.abs(band.high));
}

export function inBand(value: number, band: TradeBand): boolean {
  const eps = tolerance(band);
  return value >= band.low - eps && value <= band.high + eps;
}

/** `member_share_v1`: the smallest member carries at least 15% (packages of two or three). */
export function sharesHold(pkg: Pick<TradePackage, "members" | "value">): boolean {
  if (pkg.members.length < 2) return true;
  return shareOk(Math.min(...pkg.members.map((member) => member.value)), pkg.value);
}

/** The share predicate itself, shared by `sharesHold` and the search's inner loops. */
function shareOk(smallest: number, total: number): boolean {
  return smallest > 0 && smallest >= MEMBER_SHARE_MIN * total - 1e-9 * Math.max(1, Math.abs(total));
}

/** Every named slot is covered by a distinct member at that position. */
export function compositionMatches(positions: readonly Position[], comp: readonly CompSlot[]): boolean {
  if (comp.length === 0) return true;
  if (comp.length !== positions.length) return false;
  for (const slot of COMP_SLOTS) {
    if (slot === "any") continue;
    const need = comp.filter((value) => value === slot).length;
    if (need === 0) continue;
    const have = positions.filter((position) => position === SLOT_POSITION[slot]).length;
    if (have < need) return false;
  }
  return true;
}

export function compositionLabel(comp: readonly CompSlot[], count: number): string {
  if (comp.length !== count || comp.every((slot) => slot === "any")) return "Any positions";
  return comp.map((slot) => (slot === "any" ? "Any" : SLOT_POSITION[slot])).join(" + ");
}

// ------------------------------------------------------------------------- the search (§6)

export interface TradeQuery {
  readonly records: readonly RosTierRecord[];
  readonly give: readonly string[];
  readonly goal: TradeGoal;
  readonly get: TradeCount;
  readonly range: number;
  readonly comp: readonly CompSlot[];
}

export interface OutgoingPackage {
  /** The outgoing players found and priced in the block, in the reader's order. */
  readonly players: readonly PricedPlayer[];
  /** Ids the block does not hold (a stale or foreign link). */
  readonly missing: readonly string[];
  /** Records the block holds but cannot price. */
  readonly unpriced: readonly RosTierRecord[];
  /** Null when no outgoing player is priced. */
  readonly pkg: TradePackage | null;
}

export interface Exclusion {
  readonly record: RosTierRecord;
  readonly reason: ExclusionReason;
}

export interface RankedPackage {
  readonly pkg: TradePackage;
  /** 1-based rank in the comparable pool under the active preset. */
  readonly rank: number;
  readonly objective: number;
  /** `f(S) − f(O)` in value points. */
  readonly objectiveDelta: number;
  /** `E[S] − E[O]` in value points. */
  readonly valueDelta: number;
}

export type TradeSearch =
  | { readonly status: "no_outgoing"; readonly outgoing: OutgoingPackage }
  | { readonly status: "unpriced_outgoing"; readonly outgoing: OutgoingPackage }
  | { readonly status: "nonpositive"; readonly outgoing: OutgoingPackage }
  | {
      readonly status: "ok";
      readonly outgoing: OutgoingPackage;
      readonly outgoingPkg: TradePackage;
      readonly band: TradeBand;
      /** The best `POOL_CAP` qualifying packages, ranked. */
      readonly pool: readonly RankedPackage[];
      /** Every qualifying package, counted. */
      readonly qualifying: number;
      readonly truncated: boolean;
      readonly eligible: number;
      /** Positive-value players kept out by rules 1, 4 and 5, by expected value. */
      readonly excluded: readonly Exclusion[];
      /** Players at or below replacement in the block. */
      readonly belowReplacement: number;
    };

export function outgoingPackage(
  records: readonly RosTierRecord[],
  give: readonly string[],
): OutgoingPackage {
  const byId = new Map(records.map((record) => [record.player_id, record]));
  const players: PricedPlayer[] = [];
  const missing: string[] = [];
  const unpriced: RosTierRecord[] = [];
  for (const id of give) {
    const record = byId.get(id);
    if (record === undefined) {
      missing.push(id);
      continue;
    }
    const priced = priceRecord(record);
    if (priced === null) unpriced.push(record);
    else players.push(priced);
  }
  return { players, missing, unpriced, pkg: players.length === 0 ? null : buildPackage(players) };
}

/** First index in a descending array whose value is `<= x`. */
function firstAtMost(values: Float64Array, x: number, from: number): number {
  let lo = from;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((values[mid] ?? 0) <= x) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/** One past the last index in a descending array whose value is `>= x`. */
function endAtLeast(values: Float64Array, x: number, from: number): number {
  let lo = from;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((values[mid] ?? 0) >= x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

const POSITION_CODE: Readonly<Record<Position, number>> = { QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DST: 5 };

/**
 * `trade_search_v1`. Exact: every qualifying package is counted, the best `POOL_CAP` kept.
 *
 * Members are taken in expected-value order (index i < j < k), so a set is generated once;
 * the last member's admissible values are a contiguous index range found by binary search,
 * and each loop stops as soon as its best completion cannot reach the band.
 */
export function searchTrade(query: TradeQuery): TradeSearch {
  const outgoing = outgoingPackage(query.records, query.give);
  if (query.give.length === 0) return { status: "no_outgoing", outgoing };
  if (outgoing.unpriced.length > 0) return { status: "unpriced_outgoing", outgoing };
  if (outgoing.pkg === null) return { status: "no_outgoing", outgoing };
  const band = tradeBand(outgoing.pkg.value, query.range);
  if (band === null) return { status: "nonpositive", outgoing };

  const outgoingIds = new Set(outgoing.players.map((player) => player.id));
  const eligible: PricedPlayer[] = [];
  const excluded: Exclusion[] = [];
  let belowReplacement = 0;
  for (const record of query.records) {
    const reason = exclusionReason(record, outgoingIds);
    if (reason === null) {
      const priced = priceRecord(record);
      if (priced !== null) eligible.push(priced);
    } else if (reason === "at_or_below_replacement") {
      belowReplacement += 1;
    } else if (reason !== "outgoing") {
      excluded.push({ record, reason });
    }
  }
  excluded.sort(
    (a, b) =>
      (b.record.ros_expected_vorp || 0) - (a.record.ros_expected_vorp || 0) ||
      (a.record.player_id < b.record.player_id ? -1 : 1),
  );
  eligible.sort(memberOrder);

  // A composition with no `any` slot can only use the positions it names.
  const comp = query.comp.length === query.get ? query.comp : [];
  const named = new Set(comp.filter((slot) => slot !== "any").map((slot) => SLOT_POSITION[slot]));
  const pool = comp.length > 0 && !comp.includes("any")
    ? eligible.filter((player) => named.has(player.record.position))
    : eligible;

  const n = pool.length;
  const v = new Float64Array(n);
  const m2 = new Float64Array(n);
  const m3 = new Float64Array(n);
  const pos = new Int8Array(n);
  for (let i = 0; i < n; i += 1) {
    const player = at(pool, i);
    v[i] = player.value;
    m2[i] = player.m2;
    m3[i] = player.m3;
    pos[i] = POSITION_CODE[player.record.position];
  }
  const need = new Int8Array(6);
  for (const slot of comp) {
    if (slot !== "any") need[POSITION_CODE[SLOT_POSITION[slot]]] = (need[POSITION_CODE[SLOT_POSITION[slot]]] ?? 0) + 1;
  }
  const constrained = need.some((count) => count > 0);
  const counts = new Int8Array(6);
  // Members are passed as numbers, `-1` for an absent one: the inner loops allocate nothing.
  const matches = (a: number, b: number, c: number): boolean => {
    if (!constrained) return true;
    counts.fill(0);
    counts[pos[a] ?? 0] = (counts[pos[a] ?? 0] ?? 0) + 1;
    if (b >= 0) counts[pos[b] ?? 0] = (counts[pos[b] ?? 0] ?? 0) + 1;
    if (c >= 0) counts[pos[c] ?? 0] = (counts[pos[c] ?? 0] ?? 0) + 1;
    for (let p = 0; p < 6; p += 1) if ((counts[p] ?? 0) < (need[p] ?? 0)) return false;
    return true;
  };

  const eps = tolerance(band);
  const low = band.low - eps;
  const high = band.high + eps;
  const s = MEMBER_SHARE_MIN;
  const shareRatio = s / (1 - s);

  // Bounded best-N: a buffer trimmed to POOL_CAP whenever it doubles; `floor` is the worst
  // kept candidate once trimmed, so most candidates are rejected with one comparison.
  let kept: TradePackage[] = [];
  let floor: TradePackage | null = null;
  let qualifying = 0;
  let visits = 0;
  let truncated = false;
  const goal = query.goal;
  const objectiveFast = (k1: number, k2: number, k3: number): number =>
    goal === "value" ? k1 : cornishFisher(k1, k2, k3, goal === "ceiling" ? 0.9 : 0.1);
  let worst = Number.NEGATIVE_INFINITY;
  const trim = (): void => {
    kept.sort((a, b) => comparePackages(a, b, goal));
    kept = kept.slice(0, POOL_CAP);
    floor = kept.length >= POOL_CAP ? (kept[kept.length - 1] ?? null) : null;
    worst = floor === null ? Number.NEGATIVE_INFINITY : objectiveOf(floor, goal);
  };
  const offer = (a: number, b: number, c: number, k1: number, k2: number, k3: number): void => {
    qualifying += 1;
    if (floor !== null) {
      // One player's floor and ceiling are published; two or three use the cumulant rule.
      const f = b < 0 ? objectiveOf(at(pool, a), goal) : objectiveFast(k1, k2, k3);
      if (f < worst) return;
    }
    const members = [at(pool, a)];
    if (b >= 0) members.push(at(pool, b));
    if (c >= 0) members.push(at(pool, c));
    const pkg = buildPackage(members);
    if (floor !== null && comparePackages(pkg, floor, goal) >= 0) return;
    kept.push(pkg);
    if (kept.length >= 2 * POOL_CAP) trim();
  };

  if (query.get === 1) {
    for (let i = firstAtMost(v, high, 0); i < n && (v[i] ?? 0) >= low; i += 1) {
      visits += 1;
      if (matches(i, -1, -1)) offer(i, -1, -1, v[i] ?? 0, m2[i] ?? 0, m3[i] ?? 0);
    }
  } else if (query.get === 2) {
    outer: for (let i = 0; i + 1 < n; i += 1) {
      const vi = v[i] ?? 0;
      if (vi + (v[i + 1] ?? 0) < low) break;
      const start = firstAtMost(v, high - vi, i + 1);
      const end = endAtLeast(v, Math.max(low - vi, shareRatio * vi - eps), i + 1);
      for (let j = start; j < end; j += 1) {
        visits += 1;
        if (visits > MAX_VISITS) {
          truncated = true;
          break outer;
        }
        if (!shareOk(v[j] ?? 0, vi + (v[j] ?? 0)) || !matches(i, j, -1)) continue;
        offer(i, j, -1, vi + (v[j] ?? 0), (m2[i] ?? 0) + (m2[j] ?? 0), (m3[i] ?? 0) + (m3[j] ?? 0));
      }
    }
  } else {
    const jFloorRatio = s / (1 - 2 * s);
    outer: for (let i = 0; i + 2 < n; i += 1) {
      const vi = v[i] ?? 0;
      if (vi + (v[i + 1] ?? 0) + (v[i + 2] ?? 0) < low) break;
      for (let j = i + 1; j + 1 < n; j += 1) {
        const vj = v[j] ?? 0;
        if (vi + vj + (v[j + 1] ?? 0) < low) break;
        if (vj < jFloorRatio * vi - eps) break;
        if (vi + vj >= high) continue;
        const start = firstAtMost(v, high - vi - vj, j + 1);
        const end = endAtLeast(v, Math.max(low - vi - vj, shareRatio * (vi + vj) - eps), j + 1);
        for (let k = start; k < end; k += 1) {
          visits += 1;
          if (visits > MAX_VISITS) {
            truncated = true;
            break outer;
          }
          if (!shareOk(v[k] ?? 0, vi + vj + (v[k] ?? 0)) || !matches(i, j, k)) continue;
          offer(
            i,
            j,
            k,
            vi + vj + (v[k] ?? 0),
            (m2[i] ?? 0) + (m2[j] ?? 0) + (m2[k] ?? 0),
            (m3[i] ?? 0) + (m3[j] ?? 0) + (m3[k] ?? 0),
          );
        }
      }
    }
  }
  trim();

  const outgoingPkg = outgoing.pkg;
  const ranked = kept.map((pkg, index) => ({
    pkg,
    rank: index + 1,
    objective: objectiveOf(pkg, goal),
    objectiveDelta: objectiveOf(pkg, goal) - objectiveOf(outgoingPkg, goal),
    valueDelta: pkg.value - outgoingPkg.value,
  }));
  return {
    status: "ok",
    outgoing,
    outgoingPkg,
    band,
    pool: ranked,
    qualifying,
    truncated,
    eligible: eligible.length,
    excluded,
    belowReplacement,
  };
}

/** Does `pkg` qualify for `query` against `outgoing`? The search's predicate, written plainly. */
export function qualifies(
  pkg: TradePackage,
  query: Pick<TradeQuery, "get" | "comp">,
  band: TradeBand,
  outgoingIds: ReadonlySet<string>,
): boolean {
  if (pkg.members.length !== query.get) return false;
  if (new Set(pkg.members.map((member) => member.id)).size !== pkg.members.length) return false;
  if (pkg.members.some((member) => exclusionReason(member.record, outgoingIds) !== null)) return false;
  if (!inBand(pkg.value, band)) return false;
  if (!sharesHold(pkg)) return false;
  const comp = query.comp.length === query.get ? query.comp : [];
  return compositionMatches(pkg.members.map((member) => member.record.position), comp);
}

// -------------------------------------------------------------------- exploration (§7)

/**
 * The dealing order: packages stable-sorted by how many better-ranked packages share their
 * lead, then by rank. Each package appears exactly once.
 */
export function dealingOrder(pool: readonly RankedPackage[]): readonly RankedPackage[] {
  const seen = new Map<string, number>();
  const tagged = pool.map((entry) => {
    const occurrence = seen.get(entry.pkg.lead) ?? 0;
    seen.set(entry.pkg.lead, occurrence + 1);
    return { entry, occurrence };
  });
  tagged.sort((a, b) => a.occurrence - b.occurrence || a.entry.rank - b.entry.rank);
  return tagged.map((item) => item.entry);
}

/** Which dealt-order entries fill the five slots, and how many have been dealt. */
export interface Exploration {
  readonly shown: readonly number[];
  readonly dealt: number;
}

export const EMPTY_EXPLORATION: Exploration = { shown: [], dealt: 0 };

function nextUndealt(
  order: readonly RankedPackage[],
  from: number,
  kept: ReadonlySet<string>,
): number | null {
  for (let index = from; index < order.length; index += 1) {
    if (!kept.has(order[index]?.pkg.key ?? "")) return index;
  }
  return null;
}

export function dealInitial(order: readonly RankedPackage[], kept: ReadonlySet<string>): Exploration {
  const shown: number[] = [];
  let dealt = 0;
  while (shown.length < VISIBLE_PACKAGES) {
    const next = nextUndealt(order, dealt, kept);
    if (next === null) break;
    shown.push(next);
    dealt = next + 1;
  }
  return { shown, dealt: shown.length === 0 ? 0 : dealt };
}

/** Replace one slot with the next undealt package; null when the order is used up. */
export function swapSlot(
  order: readonly RankedPackage[],
  exploration: Exploration,
  slot: number,
  kept: ReadonlySet<string>,
): Exploration | null {
  if (slot < 0 || slot >= exploration.shown.length) return null;
  const next = nextUndealt(order, exploration.dealt, kept);
  if (next === null) return null;
  const shown = [...exploration.shown];
  shown[slot] = next;
  return { shown, dealt: next + 1 };
}

/** Replace every slot with the next undealt packages; null when none is left. */
export function moreTargets(
  order: readonly RankedPackage[],
  exploration: Exploration,
  kept: ReadonlySet<string>,
): Exploration | null {
  const shown: number[] = [];
  let dealt = exploration.dealt;
  while (shown.length < VISIBLE_PACKAGES) {
    const next = nextUndealt(order, dealt, kept);
    if (next === null) break;
    shown.push(next);
    dealt = next + 1;
  }
  return shown.length === 0 ? null : { shown, dealt };
}

/** After keeping the package in `slot`: deal a replacement into it, or drop the slot. */
export function afterKeep(
  order: readonly RankedPackage[],
  exploration: Exploration,
  slot: number,
  kept: ReadonlySet<string>,
): Exploration {
  const swapped = swapSlot(order, exploration, slot, kept);
  if (swapped !== null) return swapped;
  return { shown: exploration.shown.filter((_, index) => index !== slot), dealt: exploration.dealt };
}

/**
 * The exploration a URL describes, if it is valid against the current order; otherwise the
 * first deal, with `redealt` set when the URL named an exploration that could not be honoured.
 */
export function resolveExploration(
  order: readonly RankedPackage[],
  requested: Exploration,
  stampMatches: boolean,
  kept: ReadonlySet<string>,
): { readonly exploration: Exploration; readonly redealt: boolean } {
  const named = requested.shown.length > 0 || requested.dealt > 0;
  if (!named) return { exploration: dealInitial(order, kept), redealt: false };
  const valid =
    stampMatches &&
    requested.dealt <= order.length &&
    new Set(requested.shown).size === requested.shown.length &&
    requested.shown.every(
      (index) =>
        Number.isInteger(index) &&
        index >= 0 &&
        index < requested.dealt &&
        !kept.has(order[index]?.pkg.key ?? ""),
    );
  if (valid) return { exploration: requested, redealt: false };
  return { exploration: dealInitial(order, kept), redealt: true };
}

/** True when nothing undealt remains. */
export function exhausted(
  order: readonly RankedPackage[],
  exploration: Exploration,
  kept: ReadonlySet<string>,
): boolean {
  return nextUndealt(order, exploration.dealt, kept) === null;
}

// --------------------------------------------------------------------------- kept packages

export type KeptProblem =
  | "not_on_board"
  | "unpriced"
  | "includes_outgoing"
  | "ineligible"
  | "wrong_count"
  | "composition"
  | "member_share"
  | "outside_range"
  | "no_search";

export interface KeptPackage {
  readonly ids: readonly string[];
  readonly key: string;
  /** Null when a member is missing or cannot be priced. */
  readonly pkg: TradePackage | null;
  readonly problems: readonly KeptProblem[];
}

/** Re-check a kept package against the current block and inputs (ADR-100 §7). */
export function checkKept(
  ids: readonly string[],
  records: readonly RosTierRecord[],
  query: Pick<TradeQuery, "get" | "comp">,
  search: TradeSearch,
): KeptPackage {
  const byId = new Map(records.map((record) => [record.player_id, record]));
  const problems: KeptProblem[] = [];
  const players: PricedPlayer[] = [];
  for (const id of ids) {
    const record = byId.get(id);
    if (record === undefined) {
      if (!problems.includes("not_on_board")) problems.push("not_on_board");
      continue;
    }
    const priced = priceRecord(record);
    if (priced === null) {
      if (!problems.includes("unpriced")) problems.push("unpriced");
      continue;
    }
    players.push(priced);
  }
  const key = packageKey(ids);
  if (problems.length > 0) return { ids, key, pkg: null, problems };
  const pkg = buildPackage(players);
  const outgoingIds = new Set(search.outgoing.players.map((player) => player.id));
  if (pkg.members.some((member) => outgoingIds.has(member.id))) problems.push("includes_outgoing");
  if (pkg.members.some((member) => {
    const reason = exclusionReason(member.record, outgoingIds);
    return reason !== null && reason !== "outgoing";
  })) {
    problems.push("ineligible");
  }
  if (pkg.members.length !== query.get) problems.push("wrong_count");
  const comp = query.comp.length === query.get ? query.comp : [];
  if (pkg.members.length === query.get && !compositionMatches(pkg.members.map((member) => member.record.position), comp)) {
    problems.push("composition");
  }
  if (!sharesHold(pkg)) problems.push("member_share");
  if (search.status !== "ok") problems.push("no_search");
  else if (!inBand(pkg.value, search.band)) problems.push("outside_range");
  return { ids, key, pkg, problems };
}

export const KEPT_PROBLEM_TEXT: Readonly<Record<KeptProblem, string>> = {
  not_on_board: "a player is not on this board",
  unpriced: "a player has no published value",
  includes_outgoing: "it includes a player you are giving",
  ineligible: "a player is no longer a target (status, absence or value)",
  wrong_count: "it is not the number of players you asked to receive",
  composition: "it does not match the positions you asked for",
  member_share: "a player carries under 15% of its value",
  outside_range: "its value is outside your value range",
  no_search: "there is no outgoing value to compare it with",
};

export const EXCLUSION_TEXT: Readonly<Record<ExclusionReason, string>> = {
  unpriced: "No published value",
  outgoing: "You are giving him",
  at_or_below_replacement: "At or below replacement",
  long_absence: "Long absence",
  roster_status: "Roster status",
};

// ------------------------------------------------------------------------------- stamp

/** FNV-1a 32-bit, as eight hex digits. */
export function fnv1a(text: string): string {
  let hash = 0x811c9dc5;
  const bytes = new TextEncoder().encode(text);
  for (const byte of bytes) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

/** The exploration's identity: the build, the block and every search input (ADR-100 §8). */
export function explorationStamp(parts: {
  readonly buildId: string;
  readonly leaguePreset: string;
  readonly scoring: string;
  readonly give: readonly string[];
  readonly goal: TradeGoal;
  readonly get: number;
  readonly range: number;
  readonly comp: readonly CompSlot[];
}): string {
  return fnv1a(
    [
      parts.buildId,
      parts.leaguePreset,
      parts.scoring,
      parts.give.join(","),
      parts.goal,
      String(parts.get),
      String(parts.range),
      parts.comp.join(","),
    ].join("|"),
  );
}
