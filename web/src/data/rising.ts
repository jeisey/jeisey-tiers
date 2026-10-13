/**
 * Rising Stars for a saved league (ADR-106, `rising_stars_v1`): a short list of players beside
 * each lineup group whose role is growing **and** whose adds are growing now.
 *
 * **Membership is the Opportunity Board's own conjunction**, read through its own predicates
 * (`passesFilter` in `candidates.ts`): a measured upward `role_change_v1` on the position's
 * leading metric AND a measured rising `behavior_trend_v1` add slope whose window reaches the
 * latest snapshot. Neither alone qualifies: a high add count is not evidence that a role is
 * growing, and a missing, one-observation, ended-window or unpublished momentum reading is not
 * a rising one. Nothing here counts how many signals hold, and there is no blended score.
 *
 * **Order.** A single-position list orders by the size of the published role change
 * (`roleMagnitudeOrder`, the Opportunity Board's guard), then projected players before
 * unprojected ones, then rest-of-season rank, then id. FLEX lists backs, receivers and tight
 * ends together and orders them with `flexRoleMagnitudeOrder`, which compares only snap-share
 * changes (the one shared leading metric and unit); quarterbacks never enter FLEX.
 *
 * **Exclusions.** Every player on the league's roster (starters, bench and IR), and anyone the
 * availability policy will not suggest as an acquisition (`tradeTargetBlock`: out for the
 * season, on a reserve list, released or unsigned). Ownership elsewhere is unknown and never
 * claimed: these are not "available on waivers", only not on this roster.
 */

import { tradeTargetBlock, type Availability } from "./availability";
import {
  flexRoleMagnitudeOrder,
  momentumCell,
  opportunityCandidate,
  passesFilter,
  roleCell,
  roleMagnitudeOrder,
  type MomentumCell,
  type OpportunityCandidate,
  type RoleCell,
} from "./candidates";
import type { OpportunityRecord, Position, ScoringPreset, UnprojectedRecord } from "./contracts";
import { isUnprojected, type InSeasonBundle } from "./ros";

export const RISING_RULE_VERSION = "rising_stars_v1";
/** How many names a group shows. Short on purpose: it sits beside a lineup. */
export const RISING_LIMIT = 3;

export const RISING_GROUPS = ["QB", "RB", "WR", "TE", "FLEX"] as const;
export type RisingGroup = (typeof RISING_GROUPS)[number];

export interface RisingStar {
  readonly candidate: OpportunityCandidate;
  readonly record: OpportunityRecord | UnprojectedRecord;
  /** False for an off-roster player with no model output (ADR-102): no projection is shown. */
  readonly projected: boolean;
  readonly availability: Availability;
  readonly role: RoleCell;
  readonly momentum: MomentumCell;
}

export type RisingSignal = "opportunity" | "role" | "momentum";

export type RisingSelection =
  /** A signal this rule needs was not published: the lists cannot be read, not "nobody rose". */
  | { readonly kind: "unavailable"; readonly missing: readonly RisingSignal[] }
  | {
      readonly kind: "ready";
      readonly groups: Readonly<Record<RisingGroup, readonly RisingStar[]>>;
      /** Rows that passed both predicates before roster and availability exclusions. */
      readonly qualifying: number;
      /** Of those, on this league's roster. */
      readonly owned: number;
      /** Of those, held back by the availability policy. */
      readonly unavailable: number;
    };

function projectedFirst(a: RisingStar, b: RisingStar): number {
  if (a.projected !== b.projected) return a.projected ? -1 : 1;
  if (a.projected && b.projected) {
    const ra = (a.record as OpportunityRecord).ros_fair_rank;
    const rb = (b.record as OpportunityRecord).ros_fair_rank;
    if (ra !== rb) return ra - rb;
  }
  return a.record.player_id < b.record.player_id ? -1 : a.record.player_id > b.record.player_id ? 1 : 0;
}

/**
 * Every row that passes both predicates for one block, before the roster is known: each
 * group's full list in its final order, and who the availability policy holds back. Building
 * the candidates is the costly part and depends only on the published files, so it is done once
 * per loaded bundle and block rather than on every roster edit or league switch. The orders
 * are total (they end on player id), so dropping the roster's players afterwards selects exactly
 * what sorting the remainder would.
 */
interface RisingPool {
  readonly qualifying: readonly string[];
  readonly blocked: ReadonlySet<string>;
  readonly ordered: Readonly<Record<RisingGroup, readonly RisingStar[]>>;
}

const pools = new WeakMap<InSeasonBundle, Map<string, RisingPool>>();

function risingPool(bundle: InSeasonBundle, leaguePreset: string, scoring: ScoringPreset): RisingPool {
  const key = `${leaguePreset}|${scoring}`;
  const cached = pools.get(bundle)?.get(key);
  if (cached !== undefined) return cached;
  const rows: (OpportunityRecord | UnprojectedRecord)[] = [
    ...bundle.opportunityFor(leaguePreset, scoring),
    ...bundle.unprojectedFor(leaguePreset, scoring),
  ];
  const qualifying: string[] = [];
  const blocked = new Set<string>();
  const byPosition = new Map<Position, RisingStar[]>();
  for (const record of rows) {
    // The same candidate the Opportunity Board builds; an unprojected row carries every field
    // the two predicates read (identity, position, team), and none of the values they do not.
    const candidate = opportunityCandidate(bundle, { record: record as OpportunityRecord, rank: 0 });
    if (!passesFilter(candidate, "role") || !passesFilter(candidate, "momentum")) continue;
    qualifying.push(record.player_id);
    const availability = bundle.availabilityFor(record.player_id);
    if (tradeTargetBlock(availability, false) !== null) {
      blocked.add(record.player_id);
      continue;
    }
    const star: RisingStar = {
      candidate,
      record,
      projected: !isUnprojected(record),
      availability,
      role: roleCell(candidate.role, record.position),
      momentum: momentumCell(candidate.momentum),
    };
    const bucket = byPosition.get(record.position) ?? [];
    bucket.push(star);
    byPosition.set(record.position, bucket);
  }
  const single = (position: Position): RisingStar[] =>
    [...(byPosition.get(position) ?? [])].sort(
      (a, b) => roleMagnitudeOrder(a.candidate, b.candidate, { magnitudes: true, position }) || projectedFirst(a, b),
    );
  const flex = [...(byPosition.get("RB") ?? []), ...(byPosition.get("WR") ?? []), ...(byPosition.get("TE") ?? [])].sort(
    (a, b) => flexRoleMagnitudeOrder(a.candidate, b.candidate) || projectedFirst(a, b),
  );
  const pool: RisingPool = {
    qualifying,
    blocked,
    ordered: { QB: single("QB"), RB: single("RB"), WR: single("WR"), TE: single("TE"), FLEX: flex },
  };
  const forBundle = pools.get(bundle) ?? new Map<string, RisingPool>();
  forBundle.set(key, pool);
  pools.set(bundle, forBundle);
  return pool;
}

export function selectRisingStars(
  bundle: InSeasonBundle,
  leaguePreset: string,
  scoring: ScoringPreset,
  roster: ReadonlySet<string>,
): RisingSelection {
  const missing: RisingSignal[] = [];
  if (!bundle.hasOpportunity) missing.push("opportunity");
  if (!bundle.hasUsage) missing.push("role");
  if (!bundle.hasBehaviorSeries) missing.push("momentum");
  if (missing.length > 0) return { kind: "unavailable", missing };

  const pool = risingPool(bundle, leaguePreset, scoring);
  // A rostered player counts as owned whatever the availability policy says of him.
  const owned = pool.qualifying.filter((id) => roster.has(id)).length;
  const unavailable = [...pool.blocked].filter((id) => !roster.has(id)).length;
  const take = (stars: readonly RisingStar[]): RisingStar[] => {
    const shown: RisingStar[] = [];
    for (const star of stars) {
      if (shown.length === RISING_LIMIT) break;
      if (!roster.has(star.record.player_id)) shown.push(star);
    }
    return shown;
  };
  return {
    kind: "ready",
    groups: {
      QB: take(pool.ordered.QB),
      RB: take(pool.ordered.RB),
      WR: take(pool.ordered.WR),
      TE: take(pool.ordered.TE),
      FLEX: take(pool.ordered.FLEX),
    },
    qualifying: pool.qualifying.length,
    owned,
    unavailable,
  };
}

export const RISING_SIGNAL_TEXT: Readonly<Record<RisingSignal, string>> = {
  opportunity: "the Opportunity Board",
  role: "the week-by-week role series",
  momentum: "the add-momentum series",
};
