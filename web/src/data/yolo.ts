/**
 * YOLO waiver mode (ADR-110 §6, `yolo_ceiling_v1`): potential pickups who could raise this
 * week's ceiling at one of my starting slots, chosen by published gates and ordered by one
 * published difference.
 *
 * **Gates, all required, in this order** (the funnel is reported position by position):
 *
 * 1. **High net adds** in the current behaviour snapshot. The population is the league block's
 *    published Opportunity rows at his position with a provably positive net — the exact net,
 *    or the floor of a one-sided bound (ADR-114: a drop count outside Sleeper's top 100 is never
 *    read as zero); the bar is the ceiling of that population's median; a population under five,
 *    a missing feed, a snapshot older than 48 hours at the reader's clock, or a missing count
 *    qualifies nobody.
 * 2. **Rising role**: the Opportunity Board's own `role` predicate (`passesFilter`).
 * 3. **Playable this week**: `readWeek` says candidate (a distribution for this week and scoring,
 *    an upcoming game, a future kickoff) and the availability policy would feature him
 *    (`featureable`, Pick of the Week's rule).
 * 4. **Not known to be owned**: not on my roster, not entered for the opponent, not marked
 *    unavailable by the reader.
 * 5. **A higher ceiling**: his q90 above the q90 of the incumbent at a starting slot he can fill
 *    and whose occupant can move.
 *
 * **Ordering** is the ceiling gain (his q90 minus the incumbent's), then his q90, then id. Role
 * and net adds decide eligibility only; they never move a projection or enter the ordering, and
 * nothing here is Rising Stars' add-momentum rule, which stays as it was.
 */

import { netLowerBound } from "./behavior";
import { featureable } from "./availability";
import { opportunityCandidate, passesFilter, roleCell, type RoleCell } from "./candidates";
import { quantileAt } from "./cohort";
import type { OpportunityRecord, Position, ScoringPreset, UnprojectedRecord } from "./contracts";
import { readWeek, type LineupMove, type PlayerWeek, type WeekContext } from "./lineup";
import { slotAccepts, type Roster } from "./leagueContract";
import { incumbentQuantile, movableOccupant, proposalReadings, type Proposal, type SetupInput, type SlotReading } from "./matchupSetup";
import type { SlotRef } from "./roster";
import type { InSeasonBundle } from "./ros";
import type { Mark } from "./wmmContract";

export const YOLO_RULE_VERSION = "yolo_ceiling_v1";
/** The smallest positive-net-add population that may set a bar. */
export const YOLO_POOL_MINIMUM = 5;
/** Where the bar sits in that population: its median. */
export const YOLO_BAR_QUANTILE = 0.5;
/** A behaviour snapshot older than this at the reader's clock is not current. */
export const YOLO_BEHAVIOR_MAX_AGE_HOURS = 48;
export const YOLO_PER_POSITION = 3;
export const YOLO_MAX = 8;
export const YOLO_POSITIONS: readonly Position[] = ["QB", "RB", "WR", "TE"];

export interface NetAddBar {
  readonly position: Position;
  /** Rows at the position with a positive net-add count: the printed population. */
  readonly pool: number;
  /** The net adds a candidate must reach; null when the pool is under the minimum. */
  readonly threshold: number | null;
}

export interface YoloFunnel {
  readonly position: Position;
  readonly bar: NetAddBar;
  /** At or above the bar. */
  readonly highAdds: number;
  /** …with a rising role. */
  readonly rising: number;
  /** …playable this week. */
  readonly playable: number;
  /** …not on either roster or marked unavailable. */
  readonly unowned: number;
  /** …with a higher ceiling than an incumbent. */
  readonly ceiling: number;
}

export interface YoloCandidate {
  readonly id: string;
  readonly name: string;
  readonly position: Position;
  readonly team: string | null;
  readonly week: PlayerWeek;
  readonly netAdds: number;
  readonly bar: NetAddBar;
  readonly role: RoleCell;
  /** The slot he would take, and who is there now. */
  readonly slot: SlotReading;
  readonly q50: number;
  readonly q90: number;
  readonly incumbentQ50: number;
  readonly incumbentQ90: number;
  /** His q90 minus the incumbent's: the ordering. */
  readonly ceilingGain: number;
  readonly mark: Mark | null;
}

export type YoloUnavailable = "no_opportunity" | "no_usage" | "behavior_missing" | "behavior_stale";

export type YoloSelection =
  | { readonly kind: "unavailable"; readonly reason: YoloUnavailable; readonly snapshotAt: string | null }
  | {
      readonly kind: "ready";
      readonly snapshotAt: string;
      readonly lookbackHours: number | null;
      readonly funnels: readonly YoloFunnel[];
      /** Ranked and capped: what gets simulated. */
      readonly candidates: readonly YoloCandidate[];
      /** Qualifiers beyond the per-position or overall cap. */
      readonly beyondCap: number;
      /** Players who passed every other gate and were marked unavailable by the reader. */
      readonly markedUnavailable: readonly string[];
    };

export const YOLO_UNAVAILABLE_TEXT: Readonly<Record<YoloUnavailable, string>> = {
  no_opportunity: "This build published no Opportunity Board, so there are no net-add counts to read.",
  no_usage: "This build published no week-by-week role series, so no rising role can be read.",
  behavior_missing: "The add/drop feed was missing from this build, so no player has net-add evidence — not \"nobody is being added\".",
  behavior_stale: "The add/drop snapshot is more than 48 hours old, so its net adds are not current. Reload after the next refresh.",
};

/** A position's bar from the block's rows (projected and unprojected) with positive net adds. */
export function netAddBar(rows: readonly (OpportunityRecord | UnprojectedRecord)[], position: Position): NetAddBar {
  const values: number[] = [];
  for (const row of rows) {
    if (row.position !== position || !row.behavior_available) continue;
    // ADR-114: the exact net, or the floor of a one-sided bound — never a zero-filled side.
    const net = netLowerBound(row);
    if (typeof net === "number" && Number.isFinite(net) && net > 0) values.push(net);
  }
  if (values.length < YOLO_POOL_MINIMUM) return { position, pool: values.length, threshold: null };
  values.sort((a, b) => a - b);
  return { position, pool: values.length, threshold: Math.ceil(quantileAt(values, YOLO_BAR_QUANTILE)) };
}

export interface YoloInput {
  /** A bundle with the block's Opportunity rows and the role series loaded. */
  readonly bundle: InSeasonBundle;
  readonly leaguePreset: string;
  readonly scoring: ScoringPreset;
  readonly context: WeekContext;
  /** My starters as the baseline reads them. */
  readonly baseline: readonly SlotReading[];
  /** Everyone known to be owned: my whole roster and every opponent player entered. */
  readonly owned: ReadonlySet<string>;
  readonly marks: Readonly<Record<string, Mark>>;
}

function compareCandidates(a: YoloCandidate, b: YoloCandidate): number {
  return b.ceilingGain - a.ceilingGain || b.q90 - a.q90 || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

export function selectYolo(input: YoloInput): YoloSelection {
  const { bundle, leaguePreset, scoring, context } = input;
  if (!bundle.hasOpportunity) return { kind: "unavailable", reason: "no_opportunity", snapshotAt: null };
  if (!bundle.hasUsage) return { kind: "unavailable", reason: "no_usage", snapshotAt: null };
  const behavior = bundle.metadata.behavior ?? null;
  const snapshotAt = behavior?.snapshot_at_utc ?? null;
  if (behavior === null || !behavior.available || snapshotAt === null || Number.isNaN(Date.parse(snapshotAt))) {
    return { kind: "unavailable", reason: "behavior_missing", snapshotAt };
  }
  if (context.now - Date.parse(snapshotAt) > YOLO_BEHAVIOR_MAX_AGE_HOURS * 3_600_000) {
    return { kind: "unavailable", reason: "behavior_stale", snapshotAt };
  }
  const rows: (OpportunityRecord | UnprojectedRecord)[] = [
    ...bundle.opportunityFor(leaguePreset, scoring),
    ...bundle.unprojectedFor(leaguePreset, scoring),
  ];
  const funnels: YoloFunnel[] = [];
  const qualified: YoloCandidate[] = [];
  const markedUnavailable: string[] = [];
  for (const position of YOLO_POSITIONS) {
    const bar = netAddBar(rows, position);
    const counts = { highAdds: 0, rising: 0, playable: 0, unowned: 0, ceiling: 0 };
    const threshold = bar.threshold;
    if (threshold !== null) {
      const slots = input.baseline.filter((line) => movableOccupant(line) && slotAccepts(line.slot.group, position));
      for (const record of rows) {
        if (record.position !== position || !record.behavior_available) continue;
        const net = netLowerBound(record);
        if (typeof net !== "number" || !Number.isFinite(net) || net <= 0 || net < threshold) continue;
        counts.highAdds += 1;
        const candidate = opportunityCandidate(bundle, { record: record as OpportunityRecord, rank: 0 });
        if (!passesFilter(candidate, "role")) continue;
        counts.rising += 1;
        const week = readWeek(record.player_id, context);
        const availability = bundle.availabilityFor(record.player_id);
        if (week.kind !== "candidate" || week.record?.quantiles == null || !featureable(availability)) continue;
        counts.playable += 1;
        if (input.owned.has(record.player_id)) continue;
        const mark = input.marks[record.player_id] ?? null;
        if (mark === "unavailable") {
          markedUnavailable.push(record.player_id);
          continue;
        }
        counts.unowned += 1;
        const q90 = week.record.quantiles.q90;
        const q50 = week.record.quantiles.q50;
        let best: { line: SlotReading; gain: number; q50: number; q90: number } | null = null;
        for (const line of slots) {
          const incumbent90 = incumbentQuantile(line, "q90");
          const incumbent50 = incumbentQuantile(line, "q50");
          if (incumbent90 === null || incumbent50 === null) continue;
          const gain = q90 - incumbent90;
          if (gain > 0 && (best === null || gain > best.gain)) best = { line, gain, q50: incumbent50, q90: incumbent90 };
        }
        if (best === null) continue;
        counts.ceiling += 1;
        qualified.push({
          id: record.player_id,
          name: record.display_name,
          position,
          team: record.team,
          week,
          netAdds: net,
          bar,
          role: roleCell(candidate.role, position),
          slot: best.line,
          q50,
          q90,
          incumbentQ50: best.q50,
          incumbentQ90: best.q90,
          ceilingGain: Math.round(best.gain * 100) / 100,
          mark,
        });
      }
    }
    funnels.push({ position, bar, ...counts });
  }
  qualified.sort(compareCandidates);
  const perPosition = new Map<Position, number>();
  const candidates: YoloCandidate[] = [];
  for (const candidate of qualified) {
    const taken = perPosition.get(candidate.position) ?? 0;
    if (taken >= YOLO_PER_POSITION || candidates.length >= YOLO_MAX) continue;
    perPosition.set(candidate.position, taken + 1);
    candidates.push(candidate);
  }
  return {
    kind: "ready",
    snapshotAt,
    lookbackHours: behavior.lookback_hours,
    funnels,
    candidates,
    beyondCap: qualified.length - candidates.length,
    markedUnavailable: markedUnavailable.sort(),
  };
}

/**
 * The roster a YOLO pickup implies: he takes the slot, and the incumbent moves to the first
 * empty bench slot. With no empty bench slot someone must be dropped, which the reader chooses
 * when applying; until then the incumbent is shown as leaving the roster. Only the starters
 * reach the simulation, so the drop never changes the comparison.
 */
export function yoloProposal(candidate: YoloCandidate, input: SetupInput): Proposal & { readonly needsDrop: boolean; readonly benchTo: SlotRef | null } {
  const roster = input.league.roster;
  const slot = candidate.slot.slot;
  const incumbent = candidate.slot.id;
  const starters = [...roster[slot.group]];
  starters[slot.index] = candidate.id;
  let next: Roster = { ...roster, [slot.group]: starters };
  const moves: LineupMove[] = [{ id: candidate.id, from: { group: "BN", index: -1 }, to: slot }];
  let benchTo: SlotRef | null = null;
  let needsDrop = false;
  if (incumbent !== null) {
    const free = roster.BN.indexOf(null);
    if (free >= 0) {
      benchTo = { group: "BN", index: free };
      const bench = [...roster.BN];
      bench[free] = incumbent;
      next = { ...next, BN: bench };
      moves.push({ id: incumbent, from: slot, to: benchTo });
    } else {
      needsDrop = true;
    }
  }
  return {
    id: `yolo-${candidate.id}`,
    kind: "yolo",
    label: "YOLO pickup",
    roster: next,
    moves,
    mine: proposalReadings(next, input),
    needsDrop,
    benchTo,
  };
}
