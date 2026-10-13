/**
 * Improve: a saved roster's weakest starting needs, and concrete ways to fill them (ADR-106,
 * `improve_v1`). Loaded lazily, with the trade engine it reuses.
 *
 * ## The weakness rule
 *
 * Weakness is **slot-relative**, never raw points (a quarterback's 18 and a tight end's 9 are
 * not on one scale):
 *
 * - **This week** — a starter slot's *startable chance*: the probability, from the occupant's
 *   published `weekly-startsit-v1` quantiles, of a week at or above the published startable
 *   threshold for his position in this league size and scoring (`ros_build_metadata.weekly
 *   .startable`: the points of the last starter in a typical week). The same reading the
 *   Start/Sit week board orders by. An empty slot, or one whose occupant cannot play, has a
 *   chance of 0. A slot below **50%** — less likely than not to give a startable week — is a
 *   weekly need. A slot whose occupant's week is unknown (no projection, pending line) is not
 *   rated and not called a need.
 * - **Rest of season** — the occupant's published rest-of-season positional rank against the
 *   starters a league of this size uses at that slot: teams × the league's own starters at the
 *   position, and for FLEX his rank among backs, receivers and tight ends against teams × all
 *   of their starter and FLEX slots. Outside that line, or no published value, is a
 *   rest-of-season need.
 *
 * A weekly need whose occupant is inside the rest-of-season line is **temporary** (a bye, an
 * injury designation, a hard week); a rest-of-season need is a **roster need**. Both
 * benchmarks were built for the published preset lineup (1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX) and
 * say so when the league starts a different one: nothing is recomputed for a custom roster.
 *
 * ## What is suggested, in order
 *
 * 1. **The bench** — when Auto Start/Sit (median) would put someone else in the slot, that move
 *    first. Needs that remain after the bench is used get the next two.
 * 2. **Targets** — players not on this roster (starters, bench or IR) who fit the slot, pass the
 *    trade engine's eligibility (`trade_eligibility_v1` with the availability policy) and would
 *    fix the need: a rest-of-season rank inside the line for a roster need; a playable week
 *    with a startable chance of at least 50% and above the occupant's for a temporary one.
 *    Ordered by published expected rest-of-season VORP. Ownership outside this roster is
 *    unknown and never claimed.
 * 3. **Packages** — "give A (+ B), receive C (+ D)", outgoing players only from this roster,
 *    priced with the trade engine (`priceRecord`, `buildPackage`), inside its default ±20%
 *    comparable-value band, with its 15% member share on either side of two. Each is
 *    evaluated by removing the outgoing players, adding the incoming ones and re-running the
 *    median Auto Start/Sit on the result. A package is kept only if the roster fits (starters +
 *    bench), no starter group ends with more empty or non-playing slots than it had (a hole
 *    moved is not a hole fixed), and the need it was built for is fixed without
 *    creating another: for a temporary need fewer starters sit below the 50% line and the
 *    median lineup sum rises, with no new roster need; for a roster need the number of starters outside their line falls (which refuses a
 *    package that only moves the need to another slot), and the weekly change is printed —
 *    a target on bye this week can still fix the roster.
 *
 * The weekly lineup sum, the slots that change and the packages' rest-of-season values are
 * printed as separate quantities. Nothing divides season value into weeks or blends value,
 * adds and lineup gain into one number.
 *
 * ## Bounds
 *
 * Three needs, six targets each, give sets of one or two roster players, receive sets of one
 * or two targets, and at most `MAX_EVALUATIONS` lineup re-optimisations per run; the run says
 * when it stopped early. The caller memoises by roster, block and clock minute.
 */

import { tradeOutgoing, type Availability } from "./availability";
import type { Position, RosTierRecord } from "./contracts";
import {
  FLEX_ELIGIBLE,
  SLOT_GROUPS,
  STARTER_GROUPS,
  isStarterGroup,
  rosterIds,
  slotAccepts,
  startersDiffer,
  type Roster,
  type SavedLeague,
  type SlotGroup,
} from "./leagueContract";
import {
  optimizeLineup,
  readWeek,
  type LineupProposal,
  type PlayerWeek,
  type WeekContext,
} from "./lineup";
import { slotKey, type SlotRef } from "./roster";
import { gridFromQuantiles, probAtLeast, quantileValues, type DistributionRule } from "./startsit";
import {
  DEFAULT_TRADE_RANGE,
  MEMBER_SHARE_MIN,
  buildPackage,
  exclusionReason,
  inBand,
  priceRecord,
  sharesHold,
  tradeBand,
  type PricedPlayer,
  type TradePackage,
} from "./trade";

export const IMPROVE_RULE_VERSION = "improve_v1";
export const WEEKLY_NEED_BELOW = 0.5;
export const MAX_NEEDS = 3;
export const MAX_TARGETS = 6;
export const SHOWN_TARGETS = 5;
export const PACKAGES_PER_NEED = 3;
export const MAX_EVALUATIONS = 1500;

export interface ImproveInput {
  readonly league: SavedLeague;
  /** The league's published rest-of-season block. */
  readonly records: readonly RosTierRecord[];
  readonly week: WeekContext;
  /** The published startable threshold for a position in this league size and scoring. */
  readonly threshold: (position: Position) => number | null;
  readonly rule: DistributionRule;
  readonly availabilityFor: (playerId: string) => Availability;
  /** The value band, in percent either side; the Trade tab's default. */
  readonly range?: number;
}

export interface Standing {
  readonly slot: SlotRef;
  readonly id: string | null;
  readonly week: PlayerWeek | null;
  /** P(startable week); 0 for an empty or non-playing slot; null when his week is unknown. */
  readonly chance: number | null;
  readonly threshold: number | null;
  readonly ros: RosTierRecord | null;
  /** Positional rank, or for FLEX the rank among RB/WR/TE; null without a published value. */
  readonly rank: number | null;
  /** The rest-of-season starter line for this slot in a league of this size. */
  readonly line: number;
  readonly weeklyNeed: boolean;
  readonly rosterNeed: boolean;
}

export interface Target {
  readonly record: RosTierRecord;
  readonly week: PlayerWeek;
  readonly chance: number | null;
  readonly rank: number | null;
  readonly availability: Availability;
}

export interface PackageIdea {
  readonly key: string;
  readonly give: readonly PricedPlayer[];
  readonly get: readonly PricedPlayer[];
  readonly outgoing: TradePackage;
  readonly incoming: TradePackage;
  /** Median lineup sums (points), before and after, each a sum of individual medians. */
  readonly before: number;
  readonly after: number;
  /** Starter slots whose player changes in the re-optimised lineup. */
  readonly affected: readonly { readonly slot: SlotRef; readonly from: string | null; readonly to: string | null }[];
  /** Starters outside their rest-of-season line, before and after. */
  readonly rosterNeedsBefore: number;
  readonly rosterNeedsAfter: number;
  /** Starters below a 50% startable chance (holes included), before and after. */
  readonly weeklyNeedsBefore: number;
  readonly weeklyNeedsAfter: number;
  readonly notes: readonly string[];
  /** Outgoing players whose availability is not clean (the trade engine's warning). */
  readonly warnings: readonly string[];
}

export interface Need {
  readonly slot: SlotRef;
  /** The slot as the reader has it now. */
  readonly current: Standing;
  /** The slot after the median Auto Start/Sit uses the bench. */
  readonly best: Standing;
  readonly benchUpgrade: boolean;
  /** Still a need after the bench is used. */
  readonly remaining: boolean;
  readonly kind: "temporary" | "roster";
  readonly targets: readonly Target[];
  readonly packages: readonly PackageIdea[];
}

export interface ImproveResult {
  readonly needs: readonly Need[];
  readonly standings: readonly Standing[];
  readonly baseline: LineupProposal;
  /** The league starts a different lineup from the one the published numbers assume. */
  readonly customStarters: boolean;
  readonly evaluations: number;
  readonly truncated: boolean;
  /** Packages that matched on value but were rejected, by reason. */
  readonly rejected: Readonly<Record<"capacity" | "hole" | "no_gain" | "new_need", number>>;
  readonly range: number;
}

// ------------------------------------------------------------------------------- readings

function chanceOf(week: PlayerWeek | null, group: SlotGroup, input: ImproveInput): { chance: number | null; threshold: number | null } {
  if (week === null) return { chance: 0, threshold: null };
  const position = week.position;
  const threshold = position === null ? null : input.threshold(position);
  if (week.kind === "sidelined") return { chance: 0, threshold };
  if (week.kind === "pinned") return { chance: null, threshold };
  if (position === null || !slotAccepts(group, position)) return { chance: 0, threshold };
  const record = week.record;
  const quantiles = record === null ? null : quantileValues(record);
  if (quantiles === null || threshold === null) return { chance: null, threshold };
  return { chance: probAtLeast(gridFromQuantiles(quantiles, input.rule), threshold), threshold };
}

/** RB/WR/TE ranked together by published rest-of-season fair rank: the FLEX line's scale. */
function flexRanks(records: readonly RosTierRecord[]): Map<string, number> {
  const ranks = new Map<string, number>();
  [...records]
    .filter((record) => FLEX_ELIGIBLE.includes(record.position))
    .sort((a, b) => a.ros_fair_rank - b.ros_fair_rank || (a.player_id < b.player_id ? -1 : 1))
    .forEach((record, index) => ranks.set(record.player_id, index + 1));
  return ranks;
}

export function rosterLine(group: SlotGroup, league: SavedLeague): number {
  if (group === "FLEX") {
    return league.teams * (league.slots.RB + league.slots.WR + league.slots.TE + league.slots.FLEX);
  }
  return league.teams * league.slots[group];
}

interface Readings {
  readonly byId: ReadonlyMap<string, RosTierRecord>;
  readonly flex: ReadonlyMap<string, number>;
  readonly weeks: Map<string, PlayerWeek>;
}

function weekFor(id: string, readings: Readings, input: ImproveInput): PlayerWeek {
  const known = readings.weeks.get(id);
  if (known !== undefined) return known;
  const week = readWeek(id, input.week);
  readings.weeks.set(id, week);
  return week;
}

function rankFor(id: string, group: SlotGroup, readings: Readings): number | null {
  const record = readings.byId.get(id);
  if (record === undefined) return null;
  return group === "FLEX" ? (readings.flex.get(id) ?? null) : record.ros_position_rank;
}

function standing(slot: SlotRef, id: string | null, input: ImproveInput, readings: Readings): Standing {
  const week = id === null ? null : weekFor(id, readings, input);
  const { chance, threshold } = chanceOf(week, slot.group, input);
  const ros = id === null ? null : (readings.byId.get(id) ?? null);
  const rank = id === null ? null : rankFor(id, slot.group, readings);
  const line = rosterLine(slot.group, input.league);
  return {
    slot,
    id,
    week,
    chance,
    threshold,
    ros,
    rank,
    line,
    weeklyNeed: chance !== null && chance < WEEKLY_NEED_BELOW,
    // An empty slot is a hole in both senses; an unvalued occupant has no rank to clear.
    rosterNeed: id === null || rank === null || rank > line,
  };
}

function standings(roster: Roster, input: ImproveInput, readings: Readings): Standing[] {
  const out: Standing[] = [];
  for (const group of STARTER_GROUPS) {
    for (let index = 0; index < input.league.slots[group]; index += 1) {
      out.push(standing({ group, index }, roster[group][index] ?? null, input, readings));
    }
  }
  return out;
}

function needOrder(a: Standing, b: Standing): number {
  const ca = a.chance ?? 2;
  const cb = b.chance ?? 2;
  if (ca !== cb) return ca - cb;
  if (a.rosterNeed !== b.rosterNeed) return a.rosterNeed ? -1 : 1;
  return (
    STARTER_GROUPS.indexOf(a.slot.group as (typeof STARTER_GROUPS)[number]) -
      STARTER_GROUPS.indexOf(b.slot.group as (typeof STARTER_GROUPS)[number]) || a.slot.index - b.slot.index
  );
}

function isNeed(entry: Standing): boolean {
  return entry.weeklyNeed || entry.rosterNeed;
}

// ------------------------------------------------------------------------------- targets

function targetsFor(
  need: Standing,
  owned: ReadonlySet<string>,
  input: ImproveInput,
  readings: Readings,
): Target[] {
  const out: Target[] = [];
  const policy = { availability: input.availabilityFor, includeReturning: false };
  for (const record of input.records) {
    if (owned.has(record.player_id)) continue;
    if (!slotAccepts(need.slot.group, record.position)) continue;
    if (exclusionReason(record, owned, policy) !== null) continue;
    const week = weekFor(record.player_id, readings, input);
    const { chance } = chanceOf(week, need.slot.group, input);
    const rank = rankFor(record.player_id, need.slot.group, readings);
    const fixesRoster = rank !== null && rank <= need.line;
    const fixesWeek =
      week.kind === "candidate" &&
      chance !== null &&
      chance >= WEEKLY_NEED_BELOW &&
      chance > (need.chance ?? 0);
    if (need.rosterNeed ? !fixesRoster : !fixesWeek) continue;
    out.push({ record, week, chance, rank, availability: input.availabilityFor(record.player_id) });
  }
  out.sort(
    (a, b) =>
      b.record.ros_expected_vorp - a.record.ros_expected_vorp ||
      (a.record.player_id < b.record.player_id ? -1 : 1),
  );
  return out.slice(0, MAX_TARGETS);
}

// ------------------------------------------------------------------------------ packages

interface GiveSet {
  readonly players: readonly PricedPlayer[];
  readonly pkg: TradePackage;
  readonly fromIr: number;
  readonly warnings: readonly string[];
}

function giveSets(roster: Roster, input: ImproveInput, readings: Readings): GiveSet[] {
  const singles: { player: PricedPlayer; ir: boolean; warning: string | null }[] = [];
  for (const group of SLOT_GROUPS) {
    for (const id of roster[group]) {
      if (id === null) continue;
      const record = readings.byId.get(id);
      if (record === undefined) continue;
      const priced = priceRecord(record);
      if (priced === null || !(priced.value > 0)) continue;
      const availability = input.availabilityFor(id);
      const reading = tradeOutgoing(availability);
      if (reading === "blocked") continue;
      singles.push({
        player: priced,
        ir: group === "IR",
        warning: reading === "warn" ? `${record.display_name}: ${availability.headline.toLowerCase()}` : null,
      });
    }
  }
  const sets: GiveSet[] = [];
  const make = (members: typeof singles): GiveSet => ({
    players: members.map((member) => member.player),
    pkg: buildPackage(members.map((member) => member.player)),
    fromIr: members.filter((member) => member.ir).length,
    warnings: members.flatMap((member) => (member.warning === null ? [] : [member.warning])),
  });
  singles.forEach((single, i) => {
    sets.push(make([single]));
    for (let j = i + 1; j < singles.length; j += 1) {
      const other = singles[j];
      if (other === undefined) continue;
      const set = make([single, other]);
      if (sharesHold(set.pkg)) sets.push(set);
    }
  });
  return sets.sort((a, b) => a.pkg.value - b.pkg.value || (a.pkg.key < b.pkg.key ? -1 : 1));
}

/** Indices of `sets` (sorted by value) whose outgoing value admits `incoming` in the band. */
function compatible(sets: readonly GiveSet[], incoming: number, range: number): GiveSet[] {
  const r = range / 100;
  const low = incoming / (1 + r);
  const high = incoming / (1 - r);
  let lo = 0;
  let hi = sets.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((sets[mid]?.pkg.value ?? 0) < low * (1 - 1e-9)) lo = mid + 1;
    else hi = mid;
  }
  const out: GiveSet[] = [];
  for (let index = lo; index < sets.length; index += 1) {
    const set = sets[index];
    if (set === undefined || set.pkg.value > high * (1 + 1e-9)) break;
    const band = tradeBand(set.pkg.value, range);
    if (band !== null && inBand(incoming, band)) out.push(set);
  }
  return out;
}

/** The roster after a trade, incoming players on open bench (then starter) slots; null if full. */
function tradedRoster(
  roster: Roster,
  league: SavedLeague,
  give: ReadonlySet<string>,
  get: readonly PricedPlayer[],
): Roster | null {
  const next: Record<SlotGroup, (string | null)[]> = {
    QB: [...roster.QB],
    RB: [...roster.RB],
    WR: [...roster.WR],
    TE: [...roster.TE],
    FLEX: [...roster.FLEX],
    BN: [...roster.BN],
    IR: [...roster.IR],
  };
  for (const group of Object.keys(next) as SlotGroup[]) {
    next[group] = next[group].map((id) => (id !== null && give.has(id) ? null : id));
  }
  for (const player of get) {
    const order: SlotGroup[] = ["BN", ...STARTER_GROUPS];
    let placed = false;
    for (const group of order) {
      if (group !== "BN" && !slotAccepts(group, player.record.position)) continue;
      const index = next[group].indexOf(null);
      if (index >= 0 && index < league.slots[group]) {
        next[group][index] = player.id;
        placed = true;
        break;
      }
    }
    if (!placed) return null;
  }
  return next;
}

/** Starter slots without a player who counts, per group: where a lineup's holes are. */
function holesByGroup(proposal: LineupProposal): Map<SlotGroup, number> {
  const holes = new Map<SlotGroup, number>();
  for (const line of proposal.starters) {
    if (line.score === null) holes.set(line.slot.group, (holes.get(line.slot.group) ?? 0) + 1);
  }
  return holes;
}

/** Starters outside their rest-of-season line (or empty, or unvalued). No grids are built. */
function rosterNeedCount(roster: Roster, input: ImproveInput, readings: Readings): number {
  let count = 0;
  for (const group of STARTER_GROUPS) {
    const line = rosterLine(group, input.league);
    for (let index = 0; index < input.league.slots[group]; index += 1) {
      const id = roster[group][index] ?? null;
      const rank = id === null ? null : rankFor(id, group, readings);
      if (rank === null || rank > line) count += 1;
    }
  }
  return count;
}

// ---------------------------------------------------------------------------------- run

export function improveRoster(input: ImproveInput): ImproveResult {
  const league = input.league;
  const range = input.range ?? DEFAULT_TRADE_RANGE;
  const readings: Readings = {
    byId: new Map(input.records.map((record) => [record.player_id, record])),
    flex: flexRanks(input.records),
    weeks: new Map(),
  };
  const baseline = optimizeLineup(league.roster, league.slots, input.week, "q50");
  for (const [id, week] of baseline.weeks) readings.weeks.set(id, week);
  const current = standings(league.roster, input, readings);
  const best = standings(baseline.roster, input, readings);
  const bestByKey = new Map(best.map((entry) => [slotKey(entry.slot), entry]));
  const owned = new Set(rosterIds(league.roster));

  const flagged = current
    .map((entry) => ({ current: entry, best: bestByKey.get(slotKey(entry.slot)) ?? entry }))
    .filter((pair) => isNeed(pair.current) || isNeed(pair.best))
    .sort((a, b) => needOrder(a.best, b.best) || needOrder(a.current, b.current))
    .slice(0, MAX_NEEDS);

  const rejected = { capacity: 0, hole: 0, no_gain: 0, new_need: 0 };
  let evaluations = 0;
  let truncated = false;
  const sets = giveSets(league.roster, input, readings);
  const needsBefore = rosterNeedCount(baseline.roster, input, readings);
  const holesBefore = holesByGroup(baseline);
  const weeklyBefore = best.filter((entry) => entry.weeklyNeed).length;
  const targetLists = flagged.map((pair) =>
    isNeed(pair.best) ? targetsFor(pair.best, owned, input, readings) : [],
  );

  // One package is listed once, under the first (weakest) need it fixes.
  const listed = new Set<string>();
  const needs: Need[] = flagged.map((pair, needIndex) => {
    const remaining = isNeed(pair.best);
    const benchUpgrade = pair.best.id !== pair.current.id && (pair.best.chance ?? 0) > (pair.current.chance ?? 0);
    const kind: Need["kind"] = (remaining ? pair.best : pair.current).rosterNeed ? "roster" : "temporary";
    const targets = targetLists[needIndex] ?? [];
    const packages: PackageIdea[] = [];
    if (remaining && targets.length > 0) {
      const receiveSets: PricedPlayer[][] = [];
      const priced = targets
        .map((target) => priceRecord(target.record))
        .filter((player): player is PricedPlayer => player !== null);
      for (const player of priced) receiveSets.push([player]);
      targetLists.forEach((others, otherIndex) => {
        if (otherIndex === needIndex) return;
        for (const player of priced) {
          for (const other of others) {
            if (other.record.player_id === player.id) continue;
            const second = priceRecord(other.record);
            if (second !== null) receiveSets.push([player, second]);
          }
        }
      });
      const seen = new Set<string>();
      for (const get of receiveSets) {
        if (truncated) break;
        const incoming = buildPackage(get);
        if (get.length > 1 && !sharesHold(incoming)) continue;
        for (const set of compatible(sets, incoming.value, range)) {
          const key = `${set.pkg.key}>${incoming.key}`;
          if (seen.has(key)) continue;
          seen.add(key);
          if (evaluations >= MAX_EVALUATIONS) {
            truncated = true;
            break;
          }
          evaluations += 1;
          const give = new Set(set.players.map((player) => player.id));
          const nonIrBefore = owned.size - league.roster.IR.filter((id) => id !== null).length;
          const nonIrAfter = nonIrBefore - (set.players.length - set.fromIr) + get.length;
          const capacity = STARTER_GROUPS.reduce((sum, group) => sum + league.slots[group], 0) + league.slots.BN;
          const traded = nonIrAfter > capacity ? null : tradedRoster(league.roster, league, give, get);
          if (traded === null) {
            rejected.capacity += 1;
            continue;
          }
          const weeks = new Map<string, PlayerWeek>();
          for (const group of SLOT_GROUPS) {
            if (group === "IR") continue;
            for (const id of traded[group]) if (id !== null) weeks.set(id, weekFor(id, readings, input));
          }
          const after = optimizeLineup(traded, league.slots, input.week, "q50", weeks);
          // No group may end with more holes than it had: a package that fills RB 2 by
          // emptying WR 2 has moved the hole, not fixed it.
          const holesAfter = holesByGroup(after);
          if (
            after.filled < baseline.filled ||
            [...holesAfter].some(([group, count]) => count > (holesBefore.get(group) ?? 0))
          ) {
            rejected.hole += 1;
            continue;
          }
          const needsAfter = rosterNeedCount(after.roster, input, readings);
          const gain = after.total - baseline.total;
          const weeklyAfter = standings(after.roster, input, readings).filter((entry) => entry.weeklyNeed).length;
          // A roster need is fixed when fewer starters sit outside their line afterwards — which
          // also refuses a package that only moves the need to another slot. Its weekly change
          // is printed, not required: a target on bye this week can still fix the roster.
          // A temporary need is fixed when fewer starters sit below the startable line and the
          // median lineup sum rises, without a new roster need.
          if (kind === "roster" ? needsAfter >= needsBefore : needsAfter > needsBefore) {
            rejected.new_need += 1;
            continue;
          }
          if (kind === "temporary" && !(gain > 0.005 && weeklyAfter < weeklyBefore)) {
            rejected.no_gain += 1;
            continue;
          }
          const affected: PackageIdea["affected"][number][] = [];
          for (const group of STARTER_GROUPS) {
            for (let index = 0; index < league.slots[group]; index += 1) {
              const from = baseline.roster[group][index] ?? null;
              const to = after.roster[group][index] ?? null;
              if (from !== to) affected.push({ slot: { group, index }, from, to });
            }
          }
          const notes: string[] = [];
          const change = get.length - set.players.length;
          if (change > 0) notes.push(`Uses ${String(change)} open roster spot${change === 1 ? "" : "s"}.`);
          if (change < 0) notes.push(`Frees ${String(-change)} roster spot${change === -1 ? "" : "s"}.`);
          if (set.fromIr > 0) notes.push("Includes a player from your IR slot.");
          packages.push({
            key,
            give: set.players,
            get,
            outgoing: set.pkg,
            incoming,
            before: baseline.total,
            after: after.total,
            affected,
            rosterNeedsBefore: needsBefore,
            rosterNeedsAfter: needsAfter,
            weeklyNeedsBefore: weeklyBefore,
            weeklyNeedsAfter: weeklyAfter,
            notes,
            warnings: set.warnings,
          });
        }
      }
    }
    packages.sort(
      (a, b) =>
        a.rosterNeedsAfter - b.rosterNeedsAfter ||
        b.after - a.after ||
        b.incoming.value - b.outgoing.value - (a.incoming.value - a.outgoing.value) ||
        (a.key < b.key ? -1 : 1),
    );
    return {
      slot: pair.current.slot,
      current: pair.current,
      best: pair.best,
      benchUpgrade,
      remaining,
      kind,
      targets: targets.slice(0, SHOWN_TARGETS),
      packages: packages
        .filter((idea) => {
          if (listed.has(idea.key)) return false;
          listed.add(idea.key);
          return true;
        })
        .slice(0, PACKAGES_PER_NEED),
    };
  });

  return {
    needs,
    standings: current,
    baseline,
    customStarters: startersDiffer(league.slots),
    evaluations,
    truncated,
    rejected,
    range,
  };
}

/** Whether a slot group is a starter group a need can be about (for callers' type narrowing). */
export function isNeedGroup(group: SlotGroup): boolean {
  return isStarterGroup(group);
}

export { MEMBER_SHARE_MIN };
