/**
 * The Opportunity Board's candidate: one published row, joined to the signal artifacts
 * beside it, with every absence named (ADR-092).
 *
 * **Why this exists.** ADR-091 taught the player card and Pick of the Week to read observed
 * role, add momentum and the next game; the Opportunity Board — the one surface a manager
 * scans five hundred players on — could read none of them. A reader could learn that a back's
 * snap share went 6% → 41% only by opening his card, which is the one thing a scanning surface
 * exists to spare them. This module is the join, once, for every row.
 *
 * **What it computes: nothing.** Every number a candidate carries is a published field read
 * back verbatim:
 *
 * | reading | artifact | field |
 * |---|---|---|
 * | role | `player_usage.json` | `role_changes[<the position's leading metric>]` |
 * | momentum | `behavior_trend_series.json` | `add_trend`, `span_days`, `observations`, `snapshots_in_window` |
 * | next game | `team_matchups.json` | the team's `next_game_v1` record |
 *
 * The direction beside a role change is `roleReading`'s (the card's own function), and the
 * direction beside a slope is `momentumDirection` (the strip's own function), so the board and
 * the card cannot disagree about one player. No slope is refitted, no change is subtracted and
 * no line is re-expressed here.
 *
 * **Absences are kinds, not nulls.** "The build published no role series", "it published one
 * without him", "his latest game has no value for this measure" and "he has one game and so
 * no change" are four different facts, and a reader acts differently on each. Every signal is
 * a discriminated union so a renderer cannot print one as another — and nothing that is not a
 * published reading can pass a filter or sort as one.
 *
 * **There is no score.** A candidate carries three readings side by side and no quantity
 * derived from more than one of them (AGENTS.md section 10). Each filter below is one
 * predicate over one reading; each sort orders by one published quantity.
 */

import type { OpportunityRecord, PlayerUsageRecord, Position, RoleMetric } from "./contracts";
import { EM_DASH, formatEasternDay, formatValue } from "./format";
import { matchesPosition, matchesSearch } from "./model";
import {
  MOMENTUM_GLYPH,
  behaviorMomentum,
  formatMomentumRate,
  momentumDirection,
  type BehaviorMomentum,
  type InSeasonBundle,
  type MomentumDirection,
  type OpportunityRow,
} from "./ros";
import {
  DIRECTION_GLYPH,
  ROLE_METRICS_BY_POSITION,
  ROLE_METRIC_SPECS,
  formatChange,
  formatMetric,
  matchupReading,
  roleReading,
  roleSentence,
  type ChangeDirection,
  type MatchupReading,
  type RoleReading,
} from "./signals";
import {
  OPPORTUNITY_FILTERS,
  SCORING_TO_PRESET,
  leaguePresetId,
  type AppState,
  type OpportunityFilter,
  type OpportunitySort,
} from "./state";

// ------------------------------------------------------------------------------ the readings

/**
 * The one role metric a board row has room for: the first of the position's own ordered list.
 *
 * Not a second position map. `ROLE_METRICS_BY_POSITION` already says what leads — pass
 * attempts for a quarterback, snap share for everyone else — and the card, Pick of the Week
 * and this board all read the same list, so "what leads" has one definition.
 */
export function primaryRoleMetric(position: Position): RoleMetric | null {
  return ROLE_METRICS_BY_POSITION[position][0] ?? null;
}

export type RoleSignal =
  /** The build published no `player_usage.json`. */
  | { readonly kind: "unpublished" }
  /** It published one, and no record for this player. */
  | { readonly kind: "no_record" }
  /** A position with no role metric (kickers, defences: in the contract, on no board). */
  | { readonly kind: "no_metric" }
  /** A record with no appearance this season: nothing to read. */
  | { readonly kind: "no_appearance"; readonly usage: PlayerUsageRecord; readonly metric: RoleMetric }
  /**
   * He appeared, and his latest game has no value for this measure — a snap row the bridge
   * could not match. `role_change_v1` withholds the change rather than reaching back.
   */
  | {
      readonly kind: "no_latest_value";
      readonly usage: PlayerUsageRecord;
      readonly reading: RoleReading;
    }
  /** A latest value and no earlier game to compare it with: a level, never a direction. */
  | { readonly kind: "one_game"; readonly usage: PlayerUsageRecord; readonly reading: RoleReading }
  /** A published change, with the direction the card prints beside it. */
  | {
      readonly kind: "measured";
      readonly usage: PlayerUsageRecord;
      readonly reading: RoleReading;
      readonly direction: ChangeDirection;
    };

export type MomentumSignal =
  /** The build published no `behavior_trend_series.json` (feed down, or no retained window). */
  | { readonly kind: "unpublished" }
  /**
   * It published one and the trending feed carried him in no retained snapshot. Unknown — the
   * feed is a top-100 list — and never zero.
   */
  | { readonly kind: "not_in_feed" }
  /** One observation: a count, and no direction, because a line needs two points. */
  | { readonly kind: "one_observation"; readonly momentum: BehaviorMomentum }
  /**
   * A published slope over a window that **ended before the latest snapshot**: the feed
   * carried him earlier in the week and has not since. The slope is the artifact's and is
   * printed, with its span and the day it ended; it is not a *current* reading, so it passes
   * no filter and sorts after every current one. Treating the silence since as zero would
   * invent a collapse (ADR-089); treating the old slope as today's would invent a surge.
   */
  | {
      readonly kind: "ended";
      readonly momentum: BehaviorMomentum;
      readonly direction: MomentumDirection;
      /** The newest point's `observed_at`: when the feed last carried him. */
      readonly lastObserved: string;
    }
  /** A published slope whose window reaches the latest snapshot. */
  | {
      readonly kind: "measured";
      readonly momentum: BehaviorMomentum;
      readonly direction: MomentumDirection;
    };

export type NextGameSignal =
  /** The build published no `team_matchups.json`. */
  | { readonly kind: "unpublished" }
  /** The row carries no team to read a game for. */
  | { readonly kind: "no_team" }
  /** Published, and nothing for his team — its horizon is over, or the build could not name it. */
  | { readonly kind: "no_record"; readonly team: string }
  | { readonly kind: "published"; readonly reading: MatchupReading };

export interface OpportunityCandidate {
  /** The published row, unmodified. Every intrinsic and behaviour count is read from here. */
  readonly row: OpportunityRow;
  readonly role: RoleSignal;
  readonly momentum: MomentumSignal;
  readonly nextGame: NextGameSignal;
}

/**
 * The team whose next game a player's card and row both read.
 *
 * The usage record's team first — it is the team `team_matchups.json` is keyed for, and the
 * one a traded player's recent games were played on — then the board row's. The card, Pick of
 * the Week and this board all ask this one function, so a player cannot be shown two
 * different next games on two surfaces.
 */
export function signalTeam(
  usage: PlayerUsageRecord | null,
  ...fallbacks: readonly (string | null | undefined)[]
): string | null {
  if (usage?.team != null) return usage.team;
  for (const team of fallbacks) if (team != null) return team;
  return null;
}

export function roleSignal(
  bundle: InSeasonBundle,
  record: Pick<OpportunityRecord, "player_id" | "position">,
): RoleSignal {
  if (!bundle.hasUsage) return { kind: "unpublished" };
  const usage = bundle.usageFor(record.player_id);
  if (usage === null) return { kind: "no_record" };
  // The board row's position, which is the one the reader filtered and the chart labelled.
  const metric = primaryRoleMetric(record.position);
  if (metric === null) return { kind: "no_metric" };
  if (usage.appearances === 0) return { kind: "no_appearance", usage, metric };
  const reading = roleReading(usage, metric);
  const change = reading.change;
  if (change === null) return { kind: "no_latest_value", usage, reading };
  if (change.earlier === null || change.change === null || reading.direction === null) {
    return { kind: "one_game", usage, reading };
  }
  return { kind: "measured", usage, reading, direction: reading.direction };
}

export function momentumSignal(bundle: InSeasonBundle, playerId: string): MomentumSignal {
  if (!bundle.hasBehaviorSeries) return { kind: "unpublished" };
  const momentum = behaviorMomentum(bundle, playerId);
  if (momentum === null) return { kind: "not_in_feed" };
  const direction = momentumDirection(momentum.trend);
  if (direction === null) return { kind: "one_observation", momentum };
  const lastObserved = momentum.record.points.at(-1)?.observed_at ?? null;
  const latest = bundle.latestBehaviorSnapshot;
  // Current only when the window provably reaches the latest snapshot. A build that recorded
  // no snapshot time cannot prove it, and an unprovable "current" is a claim, not a reading.
  const current =
    lastObserved !== null && latest !== null && Date.parse(lastObserved) >= Date.parse(latest);
  if (!current) {
    return { kind: "ended", momentum, direction, lastObserved: lastObserved ?? "" };
  }
  return { kind: "measured", momentum, direction };
}

export function nextGameSignal(bundle: InSeasonBundle, team: string | null): NextGameSignal {
  if (!bundle.hasMatchups) return { kind: "unpublished" };
  if (team === null) return { kind: "no_team" };
  const record = bundle.matchupFor(team);
  if (record === null) return { kind: "no_record", team };
  return { kind: "published", reading: matchupReading(record) };
}

export function opportunityCandidate(
  bundle: InSeasonBundle,
  row: OpportunityRow,
): OpportunityCandidate {
  const { record } = row;
  const usage = bundle.hasUsage ? bundle.usageFor(record.player_id) : null;
  return {
    row,
    role: roleSignal(bundle, record),
    momentum: momentumSignal(bundle, record.player_id),
    nextGame: nextGameSignal(bundle, signalTeam(usage, record.team)),
  };
}

// ------------------------------------------------------------------------------- the filters

/** Is the artifact a filter reads in this build? `surfaced` reads the board row itself. */
export function filterAvailable(bundle: InSeasonBundle, filter: OpportunityFilter): boolean {
  switch (filter) {
    case "role":
      return bundle.hasUsage;
    case "momentum":
      return bundle.hasBehaviorSeries;
    case "surfaced":
      return true;
  }
}

/**
 * Does the candidate carry a published reading this filter can be decided on?
 *
 * The point of asking separately: a filter keeps the rows whose reading says yes, and a row
 * with no reading is not a "no". The view counts the two apart and prints both, so "12 rising"
 * is never mistaken for "12 rising and everyone else falling".
 */
export function hasEvidence(candidate: OpportunityCandidate, filter: OpportunityFilter): boolean {
  switch (filter) {
    case "role":
      return candidate.role.kind === "measured";
    case "momentum":
      return candidate.momentum.kind === "measured";
    case "surfaced":
      return true;
  }
}

/** One predicate over one published reading. Never a count of how many predicates hold. */
export function passesFilter(candidate: OpportunityCandidate, filter: OpportunityFilter): boolean {
  switch (filter) {
    case "role":
      return candidate.role.kind === "measured" && candidate.role.direction === "up";
    case "momentum":
      return candidate.momentum.kind === "measured" && candidate.momentum.direction === "rising";
    case "surfaced":
      return candidate.row.record.outside_tier_board;
  }
}

export interface FilterReport {
  readonly filter: OpportunityFilter;
  /** False when the build did not publish the artifact the filter reads; it is then not applied. */
  readonly available: boolean;
  /** Among the rows the position and search controls leave, how many pass this filter alone. */
  readonly passing: number;
  /**
   * …and how many carry no reading the filter could decide — excluded, and not as a "no". For
   * momentum that includes a slope whose window ended before the latest snapshot.
   */
  readonly withoutReading: number;
}

// --------------------------------------------------------------------------------- the sorts

function compareByValue(a: OpportunityCandidate, b: OpportunityCandidate): number {
  return (
    a.row.record.ros_fair_rank - b.row.record.ros_fair_rank ||
    a.row.record.player_id.localeCompare(b.row.record.player_id)
  );
}

/** Current slopes first, then slopes whose window ended early, then no slope at all. */
function momentumTier(signal: MomentumSignal): number {
  return signal.kind === "measured" ? 0 : signal.kind === "ended" ? 1 : 2;
}

/**
 * The published add slope, highest first, then every row without a current one.
 *
 * All slopes are in one unit — transactions per day, from one feed, over one window — so this
 * is a legitimate numeric ordering. A slope whose window ended before the latest snapshot
 * sorts after every current one (by its own slope), and a row with no slope at all (one
 * observation, never in the feed, no series published) after those, **whatever the sign of
 * the slopes above it**: an unknown is not a zero, so it is never placed between a rising
 * and a falling player.
 */
export function compareMomentum(a: OpportunityCandidate, b: OpportunityCandidate): number {
  const byTier = momentumTier(a.momentum) - momentumTier(b.momentum);
  if (byTier !== 0) return byTier;
  const ta = "direction" in a.momentum ? a.momentum.momentum.trend : null;
  const tb = "direction" in b.momentum ? b.momentum.momentum.trend : null;
  if (ta !== null && tb !== null && ta !== tb) return tb - ta;
  return compareByValue(a, b);
}

/** Rising first. A row with no published change is its own category, last — never "flat". */
const ROLE_CATEGORY: Readonly<Record<ChangeDirection | "none", number>> = {
  up: 0,
  flat: 1,
  down: 2,
  none: 3,
};

export function roleCategory(signal: RoleSignal): ChangeDirection | "none" {
  return signal.kind === "measured" ? signal.direction : "none";
}

/**
 * Whether a role ordering may compare the *size* of two changes, and for which position.
 *
 * A quarterback's leading change is in pass attempts; everyone else's is in share points. The
 * two have no common unit, so a single ordering by magnitude across them would rank "+6
 * attempts" against "+18 points of snap share" as though one were bigger. Magnitudes are
 * therefore compared only when **every row being ordered shares one position** — which is
 * what a single-position filter produces — and otherwise the ordering is categorical only.
 */
export interface RoleOrdering {
  readonly magnitudes: boolean;
  readonly position: Position | null;
}

export function roleOrderingFor(candidates: readonly OpportunityCandidate[]): RoleOrdering {
  const positions = new Set(candidates.map((candidate) => candidate.row.record.position));
  const [only] = positions;
  return positions.size === 1 && only !== undefined
    ? { magnitudes: true, position: only }
    : { magnitudes: false, position: null };
}

/**
 * The role ordering: rising, flat, falling, no reading — then, within a category, the size of
 * the published change **only** where `ordering` allows it, and the rest-of-season rank
 * otherwise.
 *
 * The guard is enforced here as well as in `roleOrderingFor`: magnitudes are compared only
 * between two rows at the ordering's own position whose readings are in the same metric. A
 * caller that hands in a permissive ordering over mixed rows still gets a categorical sort —
 * the invalid comparison is impossible rather than merely avoided.
 */
export function compareRole(
  a: OpportunityCandidate,
  b: OpportunityCandidate,
  ordering: RoleOrdering,
): number {
  const byCategory = ROLE_CATEGORY[roleCategory(a.role)] - ROLE_CATEGORY[roleCategory(b.role)];
  if (byCategory !== 0) return byCategory;
  if (
    ordering.magnitudes &&
    a.role.kind === "measured" &&
    b.role.kind === "measured" &&
    a.row.record.position === ordering.position &&
    b.row.record.position === ordering.position &&
    a.role.reading.spec.metric === b.role.reading.spec.metric
  ) {
    const ca = a.role.reading.change?.change ?? null;
    const cb = b.role.reading.change?.change ?? null;
    if (ca !== null && cb !== null && ca !== cb) return cb - ca;
  }
  return compareByValue(a, b);
}

function sortCandidates(
  candidates: readonly OpportunityCandidate[],
  sort: OpportunitySort,
): OpportunityCandidate[] {
  const sorted = [...candidates];
  switch (sort) {
    case "adds":
      sorted.sort(
        (a, b) =>
          (b.row.record.add_count ?? -1) - (a.row.record.add_count ?? -1) || compareByValue(a, b),
      );
      break;
    case "net":
      sorted.sort(
        (a, b) =>
          (b.row.record.net_add_count ?? Number.NEGATIVE_INFINITY) -
            (a.row.record.net_add_count ?? Number.NEGATIVE_INFINITY) || compareByValue(a, b),
      );
      break;
    case "momentum":
      sorted.sort(compareMomentum);
      break;
    case "role": {
      const ordering = roleOrderingFor(candidates);
      sorted.sort((a, b) => compareRole(a, b, ordering));
      break;
    }
    case "value":
      sorted.sort(compareByValue);
      break;
  }
  return sorted;
}

// ----------------------------------------------------------------------------- the selection

export interface OpportunitySelection {
  /** The rows on screen, in the chosen order. */
  readonly candidates: readonly OpportunityCandidate[];
  /** Rows the position and search controls leave, before any signal filter. */
  readonly matched: number;
  /** One report per filter the reader has switched on, in canonical order. */
  readonly filters: readonly FilterReport[];
  /** Filters the reader switched on that this build cannot apply, named rather than dropped. */
  readonly unavailable: readonly OpportunityFilter[];
  /** The role ordering in force, so the view can say whether magnitudes were compared. */
  readonly roleOrdering: RoleOrdering;
}

/**
 * The Opportunity Board's rows: position and search, then the reader's signal filters, then
 * the chosen ordering. Both the chart and the table render exactly this list, and the filtered
 * export writes it in this order.
 *
 * A filter whose artifact this build did not publish is **not applied**, and is reported in
 * `unavailable`. Applying it would empty the board, which reads as "nobody's role grew" — a
 * claim built out of a missing file.
 */
export function selectOpportunityCandidates(
  bundle: InSeasonBundle,
  state: AppState,
): OpportunitySelection {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const matched = bundle
    .opportunityFor(leaguePreset, scoring)
    .filter(
      (record) =>
        matchesPosition(record.position, state.position) && matchesSearch(record, state.search),
    )
    .map((record) => opportunityCandidate(bundle, { record, rank: 0 }));

  const active = OPPORTUNITY_FILTERS.filter((filter) => state.only.includes(filter));
  const applied = active.filter((filter) => filterAvailable(bundle, filter));
  const reports = active.map((filter) => ({
    filter,
    available: filterAvailable(bundle, filter),
    passing: matched.filter((candidate) => passesFilter(candidate, filter)).length,
    withoutReading: matched.filter((candidate) => !hasEvidence(candidate, filter)).length,
  }));

  const kept = matched.filter((candidate) =>
    applied.every((filter) => passesFilter(candidate, filter)),
  );
  const sorted = sortCandidates(kept, state.opportunity);
  return {
    candidates: sorted.map((candidate, index) => ({
      ...candidate,
      row: { record: candidate.row.record, rank: index + 1 },
    })),
    matched: matched.length,
    filters: reports,
    unavailable: active.filter((filter) => !filterAvailable(bundle, filter)),
    roleOrdering: roleOrderingFor(kept),
  };
}

// -------------------------------------------------------------------------------- the words

/**
 * `wk 2 vs 1 gm`, `wk 8 vs 7 gms`, `wk 2 only` — the window a board cell has room for.
 * The card prints the long form (`changeWindow`), and every board cell carries it in its
 * accessible sentence.
 */
export function shortChangeWindow(reading: RoleReading): string {
  const change = reading.change;
  if (change === null) return EM_DASH;
  const games = change.earlier_games;
  if (games === 0 || change.earlier === null) return `wk ${String(change.latest_week)} only`;
  return `wk ${String(change.latest_week)} vs ${String(games)} gm${games === 1 ? "" : "s"}`;
}

export interface RoleCell {
  /** `Snap`, `Pass att`. */
  readonly metric: string;
  /** `41%`, `34`, or an em dash. */
  readonly value: string;
  readonly direction: ChangeDirection | null;
  /** `▲ +35 pts` — the card's own glyph and wording — or null when no change is published. */
  readonly change: string | null;
  /** `wk 2 vs 1 gm`, or the reason there is nothing to read. */
  readonly detail: string;
  /** The whole reading as a sentence, for a screen reader and a tooltip. */
  readonly sentence: string;
}

export function roleCell(signal: RoleSignal, position: Position): RoleCell {
  const metric = primaryRoleMetric(position);
  const spec = metric === null ? null : ROLE_METRIC_SPECS[metric];
  const label = spec?.short ?? "Role";
  const none = (detail: string, sentence: string): RoleCell => ({
    metric: label,
    value: EM_DASH,
    direction: null,
    change: null,
    detail,
    sentence,
  });
  switch (signal.kind) {
    case "unpublished":
      return none("not published", "This build published no week-by-week role series.");
    case "no_record":
      return none("no record", "No week-by-week role is published for him on this build.");
    case "no_metric":
      return none("", "No role measure is defined for this position.");
    case "no_appearance":
      return none("no games", "He has not appeared this season, so there is no role to read.");
    case "no_latest_value":
    case "one_game":
    case "measured": {
      const { reading } = signal;
      const change = reading.change;
      const direction = signal.kind === "measured" ? signal.direction : null;
      return {
        metric: reading.spec.short,
        value: change === null ? EM_DASH : formatMetric(reading.spec, change.latest),
        direction,
        change:
          direction === null || change?.change == null
            ? null
            : `${DIRECTION_GLYPH[direction]} ${formatChange(reading.spec, change.change)}`,
        detail: change === null ? "no latest value" : shortChangeWindow(reading),
        sentence: roleSentence(reading),
      };
    }
  }
}

export interface MomentumCell {
  readonly direction: MomentumDirection | null;
  /** `▲ +40.0/day`, `one obs.`, `not in feed`, or an em dash. */
  readonly value: string;
  /**
   * `over 7 days` — printed beside every slope, never optional (ADR-089) — and, for a window
   * that ended before the latest snapshot, the day it ended: `over 10 hours · to Sep 16`.
   */
  readonly span: string;
  readonly sentence: string;
}

export function momentumCell(signal: MomentumSignal): MomentumCell {
  switch (signal.kind) {
    case "unpublished":
      return {
        direction: null,
        value: EM_DASH,
        span: "",
        sentence: "This build published no add-momentum series.",
      };
    case "not_in_feed":
      return {
        direction: null,
        value: "not in feed",
        span: "",
        sentence:
          "The trending feed carried him in no retained snapshot, so there is no count and no " +
          "direction — unknown, not zero.",
      };
    case "one_observation":
      return {
        direction: null,
        value: "one obs.",
        span: "no direction yet",
        sentence: "One observation so far, so there is no direction yet — a direction needs two.",
      };
    case "measured":
    case "ended": {
      const { momentum, direction } = signal;
      const missing =
        momentum.missing > 0
          ? ` The feed did not carry him in ${String(momentum.missing)} of ` +
            `${String(momentum.record.snapshots_in_window)} snapshots; those have no count, not zero.`
          : "";
      const ended =
        signal.kind === "ended"
          ? ` His last observation was ${formatEasternDay(signal.lastObserved)}; the feed has ` +
            "not carried him since, so this is not a current reading."
          : "";
      return {
        direction,
        value: `${MOMENTUM_GLYPH[direction]} ${formatMomentumRate(momentum.trend)}`,
        span:
          signal.kind === "ended"
            ? `${momentum.spanLabel} · to ${formatEasternDay(signal.lastObserved)}`
            : momentum.spanLabel,
        sentence:
          `Adds ${direction} at ${formatMomentumRate(momentum.trend).replace("/day", "")} per ` +
          `day, ${momentum.spanLabel}, from ${String(momentum.record.observations)} ` +
          `observations.${ended}${missing}`,
      };
    }
  }
}

export interface NextGameCell {
  /** `W3 vs CHI`, or an absence. */
  readonly head: string;
  /** `25.5 implied`, `bye W9 · no line yet`, or an absence's reason. */
  readonly detail: string;
  readonly linesPosted: boolean;
  readonly sentence: string;
}

/**
 * The next game in a board cell: who, where, and the implied team points when a line is
 * posted. **Context and nothing else** — there is no word here for an easy or a hard game,
 * because nothing this project publishes measures an opponent (ADR-088, ADR-091).
 */
export function nextGameCell(signal: NextGameSignal): NextGameCell {
  switch (signal.kind) {
    case "unpublished":
      return {
        head: EM_DASH,
        detail: "",
        linesPosted: false,
        sentence: "This build published no schedule context.",
      };
    case "no_team":
      return { head: EM_DASH, detail: "", linesPosted: false, sentence: "No team on this row." };
    case "no_record":
      return {
        head: "none published",
        detail: "",
        linesPosted: false,
        sentence: `No next game is published for ${signal.team} on this build.`,
      };
    case "published": {
      const { reading } = signal;
      const { record } = reading;
      const head = `W${String(record.week)} ${reading.opponentLabel}`;
      const implied = record.implied_team_points;
      const line =
        implied !== null
          ? `${formatValue(implied)} implied`
          : reading.linesPosted
            ? `total ${formatValue(record.total_line)}`
            : "no line yet";
      // A bye before the game leads the second line: it is why the week number skips one.
      const detail =
        reading.byeBeforeGame === null ? line : `bye W${String(reading.byeBeforeGame)} · ${line}`;
      const venue = record.neutral_site ? ", at a neutral site" : "";
      const byeText =
        reading.byeBeforeGame === null ? "" : ` On bye in week ${String(reading.byeBeforeGame)} first.`;
      const lines =
        implied !== null
          ? ` Sportsbook implied team points ${formatValue(implied)}, total ` +
            `${formatValue(record.total_line)}: context, read by no model.`
          : " No line posted yet.";
      return {
        head,
        detail,
        linesPosted: reading.linesPosted,
        sentence: `Next game week ${String(record.week)} ${reading.opponentLabel}${venue}.${byeText}${lines}`,
      };
    }
  }
}
