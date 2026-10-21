/**
 * Reading Sleeper add/drop counts one side at a time (ADR-114).
 *
 * Sleeper's add and drop feeds are two separate top-100 lists, and 100 is a ceiling rather than
 * a choice (measured 2026-10-21). Most board players are in neither and many are in one, so a
 * side is one of: observed (a count, possibly a real zero), outside the feed's top 100 (unknown,
 * at most the feed's smallest count), unreachable (no verified Sleeper id), stale or
 * unavailable. Before ADR-114 every unobserved side was published as 0, which made a player in
 * the add feed and absent from the drop feed read as "no drops at all".
 *
 * Every surface that prints, sorts, filters or gates on a count reads it through here, so the
 * rule lives once:
 *
 * * an exact net exists only when both sides were observed;
 * * with one side outside its feed, the net is a **bound** — `≥ +531,586` — and is printed and
 *   sorted as one, never as a count;
 * * nothing here turns an unobserved side into a number.
 */

import type { BehaviorSideState, OpportunityRecord } from "./contracts";

export type BehaviorSide = "add" | "drop";

export interface SideReading {
  readonly state: BehaviorSideState;
  /** Set only when observed. */
  readonly count: number | null;
  /** Set only when outside a retrieved feed: the feed's floor, an upper bound. */
  readonly max: number | null;
}

type BehaviorRow = Pick<
  OpportunityRecord,
  | "behavior_available"
  | "add_count"
  | "drop_count"
  | "net_add_count"
  | "add_state"
  | "drop_state"
  | "add_count_max"
  | "drop_count_max"
  | "add_rank"
  | "drop_rank"
>;

/**
 * One side of a row. A 1.3 row says its state; a 1.2 row (an older build) does not, and wrote
 * 0 for an absence, so a 0 with no feed rank there reads as *outside the feed* — with no bound,
 * because the build did not keep one — rather than as a measured zero.
 */
export function sideOf(record: BehaviorRow, side: BehaviorSide): SideReading {
  const count = (side === "add" ? record.add_count : record.drop_count) ?? null;
  const state = side === "add" ? record.add_state : record.drop_state;
  if (state !== undefined) {
    const max = (side === "add" ? record.add_count_max : record.drop_count_max) ?? null;
    return { state, count: state === "observed" ? count : null, max: state === "not_in_feed" ? max : null };
  }
  if (!record.behavior_available || count === null) return { state: "unavailable", count: null, max: null };
  const rank = (side === "add" ? record.add_rank : record.drop_rank) ?? null;
  if (count === 0 && rank === null) return { state: "not_in_feed", count: null, max: null };
  return { state: "observed", count, max: null };
}

export type NetReading =
  | { readonly kind: "exact"; readonly value: number }
  /** One side observed, the other outside its feed: the net lies in [min, max]. */
  | { readonly kind: "bounded"; readonly min: number; readonly max: number; readonly known: BehaviorSide }
  | { readonly kind: "unknown" };

export function netAdds(record: BehaviorRow): NetReading {
  const adds = sideOf(record, "add");
  const drops = sideOf(record, "drop");
  if (adds.count !== null && drops.count !== null) return { kind: "exact", value: adds.count - drops.count };
  if (adds.count !== null && drops.max !== null) {
    return { kind: "bounded", min: adds.count - drops.max, max: adds.count, known: "add" };
  }
  if (drops.count !== null && adds.max !== null) {
    return { kind: "bounded", min: -drops.count, max: adds.max - drops.count, known: "drop" };
  }
  return { kind: "unknown" };
}

/**
 * The number a net cell prints and sorts by: the exact net, or the bound it shows — the floor
 * when the adds are known (`≥`), the ceiling when the drops are (`≤`). Null when neither.
 */
export function netSortValue(net: NetReading): number | null {
  if (net.kind === "exact") return net.value;
  if (net.kind === "bounded") return net.known === "add" ? net.min : net.max;
  return null;
}

/**
 * The least the net can be: the exact net, or a bound's floor. Null when nothing bounds it from
 * below (neither side observed, or only the drops). What a threshold on net adds compares with,
 * so a one-sided row clears a bar only when it provably does.
 */
export function netLowerBound(record: BehaviorRow): number | null {
  const net = netAdds(record);
  if (net.kind === "exact") return net.value;
  return net.kind === "bounded" && net.known === "add" ? net.min : null;
}

/** True only when the net is provably positive: exact and above zero, or bounded above zero. */
export function netIsPositive(record: BehaviorRow): boolean {
  const net = netAdds(record);
  if (net.kind === "exact") return net.value > 0;
  return net.kind === "bounded" && net.min > 0;
}

const INTEGER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function signed(value: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${INTEGER.format(Math.abs(value))}`;
}

/** The net as text: `+280,000`, `≥ +531,586`, `≤ −62,556`, or `—`. */
export function formatNet(net: NetReading): string {
  if (net.kind === "exact") return signed(net.value);
  if (net.kind === "bounded") return net.known === "add" ? `≥ ${signed(net.min)}` : `≤ ${signed(net.max)}`;
  return "—";
}

/** One side as cell text: the count, `≤ 17,444` for a player outside the feed, or `—`. */
export function formatSide(reading: SideReading): string {
  if (reading.count !== null) return INTEGER.format(reading.count);
  if (reading.max !== null) return `≤ ${INTEGER.format(reading.max)}`;
  return "—";
}

const FEED_NAME: Readonly<Record<BehaviorSide, string>> = { add: "adds", drop: "drops" };

/** A side in words, for an accessible label or a sentence. */
export function describeSide(reading: SideReading, side: BehaviorSide): string {
  const feed = FEED_NAME[side];
  switch (reading.state) {
    case "observed":
      return `${INTEGER.format(reading.count ?? 0)} ${feed}`;
    case "not_in_feed":
      return reading.max === null
        ? `not in Sleeper's top 100 ${feed}`
        : `not in Sleeper's top 100 ${feed} (at most ${INTEGER.format(reading.max)})`;
    case "no_sleeper_id":
      return `${feed} unknown: no verified Sleeper id`;
    case "ambiguous_sleeper_id":
      return `${feed} unknown: ambiguous Sleeper id`;
    case "stale":
      return `${feed} unknown: Sleeper snapshot is stale`;
    case "unavailable":
      return `${feed} unavailable`;
  }
}

/** The net in words. A bound says it is one and why. */
export function describeNet(record: BehaviorRow): string {
  const net = netAdds(record);
  if (net.kind === "exact") return `net ${signed(net.value)}`;
  if (net.kind === "bounded") {
    return net.known === "add"
      ? `net at least ${signed(net.min)} (drops not in Sleeper's top 100)`
      : `net at most ${signed(net.max)} (adds not in Sleeper's top 100)`;
  }
  return "net unknown";
}
