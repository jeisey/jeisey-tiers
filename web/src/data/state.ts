/**
 * Deterministic URL query state.
 *
 * `docs/UX_SPEC.md` section 3 requires the view, scoring, league size, position filter and
 * search to survive reload and back/forward. They live in `URLSearchParams` rather than a
 * router: three tabs do not justify a routing dependency, and GitHub Pages has no SPA
 * fallback to configure this way (`docs/ARCHITECTURE.md` section 10).
 *
 * Two rules make the parameter set predictable:
 *
 * - **normalize, never crash.** An unsupported value falls back to the default and the URL is
 *   rewritten with `replaceState`, so a hand-typed link lands somewhere valid (UX spec 10).
 * - **defaults are omitted.** A URL only names what differs from the default, and the
 *   parameters are always written in the same order, so the same UI state is always the same
 *   string and links are comparable.
 */

import type { ScoringPreset } from "./contracts";

/**
 * Every panel the product can show, plus `auto`.
 *
 * `auto` is the default and it is what makes one URL correct in both modes: a link with no
 * `view` parameter opens the Tier Board before kickoff and the ROS Tier Board after it,
 * because the season decides, not the link. Naming a view explicitly always wins — a link to
 * the Arbitrage Board in November still opens the Arbitrage Board.
 */
export const VIEWS = [
  "auto",
  "tiers",
  "arbitrage",
  "ros",
  "startsit",
  "opportunity",
  "potw",
  "trade",
  "data",
] as const;
export type ViewId = (typeof VIEWS)[number];

/** A concrete panel, after `auto` has been resolved against the season. */
export type ResolvedViewId = Exclude<ViewId, "auto">;

/** The product modes, plus the `auto` that follows the schedule-derived season state. */
export const MODES = ["auto", "draft", "in_season"] as const;
export type ModeId = (typeof MODES)[number];

/**
 * How the Opportunity Board is ordered. Five orderings over separate quantities, never one
 * blended score (ADR-085, ADR-092).
 *
 * `momentum` orders by the published add-trend slope, which every row states in one unit
 * (transactions per day). `role` is **categorical first** — rising, flat, falling, no reading
 * — and compares the size of a change only among rows that all share one position, because a
 * quarterback's change is in pass attempts and everyone else's is in share points
 * (`compareRole` in `data/candidates.ts` owns the rule and refuses the mixed case).
 */
export const OPPORTUNITY_SORTS = ["value", "adds", "net", "momentum", "role"] as const;
export type OpportunitySort = (typeof OPPORTUNITY_SORTS)[number];

/**
 * The Opportunity Board's filters (ADR-092). Each is one predicate over one published signal,
 * and several compose by AND:
 *
 * - `role` — the position's leading role metric has a published upward `role_change_v1`;
 * - `momentum` — the published `behavior_trend_v1` add slope is positive;
 * - `surfaced` — the row is published from beyond the tier depth (`outside_tier_board`).
 *
 * There is deliberately no filter that counts how many of these hold. "Two of three" is a
 * score with the arithmetic hidden in a chip.
 */
export const OPPORTUNITY_FILTERS = ["role", "momentum", "surfaced"] as const;
export type OpportunityFilter = (typeof OPPORTUNITY_FILTERS)[number];

export const DRAFT_VIEWS: readonly ResolvedViewId[] = ["tiers", "arbitrage"];
export const IN_SEASON_VIEWS: readonly ResolvedViewId[] = [
  "ros",
  "startsit",
  "trade",
  "opportunity",
  "potw",
];

/**
 * How many players one Start/Sit comparison holds (ADR-096). Four is the most a lineup slot
 * is ever genuinely contested between, and the most a phone can lay side by side.
 */
export const MAX_DUEL = 4;

/**
 * The matchup margin a URL may name, in fantasy points either way. A bound on a reader's
 * posture, not on a model: past forty the win probability of every choice is ~0 or ~1 and
 * the comparison has nothing left to say.
 */
export const MARGIN_BOUND = 40;

/** A canonical GSIS id without its namespace, as the `duel` parameter writes it. */
const GSIS_SHORT = /^\d{2}-\d{7}$/;

/**
 * The deepest Pick-of-the-Week set a URL may name.
 *
 * A bound, not a contract, for the same reason `MAX_TIER_ORDINAL` is one: it stops a
 * pathological query string driving an unbounded index into the view. How many sets actually
 * exist depends on how many candidates cleared the week's bar, so the real clamp happens
 * against the build in `clampSet` — a parser may not depend on a build, because a link shared
 * from one has to parse against the next.
 */
export const MAX_POTW_SET = 5;

/**
 * The Trade tab's controls (ADR-100 §8). Defined here, beside the parser, so the URL contract
 * has one home and the entry bundle never imports the engine to read a constant.
 */
export const TRADE_GOALS = ["value", "ceiling", "floor"] as const;
export type TradeGoal = (typeof TRADE_GOALS)[number];

/** The value range either side of the outgoing value, in percent. ±20 is a UX default. */
export const TRADE_RANGES = [10, 20, 35, 50] as const;
export type TradeRange = (typeof TRADE_RANGES)[number];
export const DEFAULT_TRADE_RANGE: TradeRange = 20;

export const TRADE_COUNTS = [1, 2, 3] as const;
export type TradeCount = (typeof TRADE_COUNTS)[number];

/** Composition slots, in canonical order; `any` matches every position. */
export const COMP_SLOTS = ["qb", "rb", "wr", "te", "any"] as const;
export type CompSlot = (typeof COMP_SLOTS)[number];

export const MAX_GIVE = 3;
export const MAX_KEEP = 3;
/** The five suggestion slots. */
export const MAX_SHOWN = 5;
/**
 * A bound on a dealt-order index a URL may name. Above the engine's 200-package pool on
 * purpose: the real bound is the build's pool, checked where the pool is in hand, because a
 * parser may not depend on a build.
 */
export const MAX_DEALT = 999;

export const SCORING_VALUES = ["std", "half", "ppr"] as const;
export type ScoringValue = (typeof SCORING_VALUES)[number];

export const TEAM_COUNTS = [10, 12, 14] as const;
export type TeamCount = (typeof TEAM_COUNTS)[number];

export const POSITION_FILTERS = ["all", "qb", "rb", "wr", "te"] as const;
export type PositionFilter = (typeof POSITION_FILTERS)[number];

export const RAIL_MODES = ["bargains", "premiums", "all"] as const;
export type RailMode = (typeof RAIL_MODES)[number];

/**
 * The largest tier ordinal a URL may name.
 *
 * A bound, not a contract: it stops a pathological query string driving an unbounded list
 * into the board, and it is far above any segmentation this product has produced (the 2026
 * board publishes nine tiers). It is deliberately not derived from the current build, because
 * a link shared from one build must still parse against the next one.
 */
export const MAX_TIER_ORDINAL = 99;

export interface AppState {
  readonly view: ViewId;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  readonly position: PositionFilter;
  readonly search: string;
  /** Tier Board depth switch. Local to the chart but shareable, like every other control. */
  readonly board: "top" | "full";
  /**
   * The tier ordinals the board has open, or `null` for "whatever the board decides".
   *
   * Null rather than a computed default, because the sensible default depends on the tier
   * sizes the build published and those change with every rebuild. Writing a resolved list
   * into the URL on first paint would freeze one build's tier structure into a shared link.
   */
  readonly tiers: readonly number[] | null;
  readonly rail: RailMode;
  /**
   * Which ADP market the Arbitrage board compares against, or `cross` for the spread view.
   *
   * A free string rather than a union, because the selectable set is derived from what the
   * build published — a union here would have to be edited every time a source is enabled or
   * withdrawn, and would reject a valid link from a build that had one more source than this
   * bundle knows about. `ArbitrageView` falls back to the default when the named market is
   * not on the current board, so a stale link degrades rather than breaking.
   */
  readonly market: string;
  /**
   * Which product mode to show, or `auto` to follow the season state the build derived.
   *
   * A manual override rather than a preference: the draft board stays reproducible and
   * reachable all season (roadmap 12.1), and a reader who wants it in November should not
   * have to know that the site decided otherwise.
   */
  readonly mode: ModeId;
  /** The Opportunity Board's ordering. */
  readonly opportunity: OpportunitySort;
  /**
   * The Opportunity Board's active filters, in canonical order, or empty for none. Written as
   * `only=role.momentum`; the order is fixed so one set of filters is one string.
   */
  readonly only: readonly OpportunityFilter[];
  /**
   * Which Pick-of-the-Week set is on screen, 1-based.
   *
   * A depth into each position's eligible pool rather than a tier: set 3 is the third-ranked
   * acquirable player at each position, and the three players in it have nothing to do with
   * one another beyond sharing that depth.
   */
  readonly set: number;
  /**
   * The players on the Start/Sit comparison, in the order they were added, as canonical
   * `gsis:` ids. Written as `duel=00-0036389.00-0039164`: the namespace is implied, because
   * only GSIS players have a weekly projection, and the order is the reader's own.
   */
  readonly duel: readonly string[];
  /**
   * The reader's matchup margin from every *other* slot, in points (their team minus the
   * opponent's). Zero is an even matchup. It is what turns "who scores more" into "who is
   * more likely to win me the week" (ADR-096).
   */
  readonly margin: number;
  /** Trade: the outgoing players, in the reader's order, as canonical `gsis:` ids (≤ 3). */
  readonly give: readonly string[];
  /** Trade: which preset ranks the comparable pool. */
  readonly goal: TradeGoal;
  /** Trade: how many players to receive. */
  readonly get: TradeCount;
  /** Trade: the value range, percent either side of the outgoing expected value. */
  readonly range: TradeRange;
  /** Trade: the incoming composition, canonical; empty means any positions. */
  readonly comp: readonly CompSlot[];
  /** Trade: kept packages, each its members' canonical ids sorted (≤ 3 packages). */
  readonly keep: readonly (readonly string[])[];
  /** Trade: dealt-order indices on the five suggestion slots; empty means the first deal. */
  readonly shown: readonly number[];
  /** Trade: how many packages of the dealt order have been dealt. */
  readonly dealt: number;
  /** Trade: the exploration's identity (build, block and inputs); empty when none. */
  readonly stamp: string;
}

/**
 * PPR at twelve teams is the default board.
 *
 * `config/league-defaults.yaml` marks `redraft-12` as the default league preset and declares
 * no default scoring preset, so the league size comes from the config and the scoring choice
 * is the product's (PPR is the most common redraft format and the hardest of the three for
 * the model, per the Phase-3 report).
 */
export const DEFAULT_STATE: AppState = {
  view: "auto",
  scoring: "ppr",
  teams: 12,
  position: "all",
  search: "",
  board: "top",
  tiers: null,
  rail: "bargains",
  /**
   * FFC Recent is the draft-week default (roadmap 10.6): it is scoring-exact and it responds
   * to the market of the last few days, which is the one a reader drafting today is actually
   * bidding into. MyFantasyLeague remains one click away and unchanged.
   *
   * A named source, never a silent average. The cross-market view exists and has to be
   * chosen.
   */
  market: "fantasyfootballcalculator_adp",
  mode: "auto",
  opportunity: "value",
  only: [],
  set: 1,
  duel: [],
  margin: 0,
  give: [],
  goal: "value",
  get: 1,
  range: DEFAULT_TRADE_RANGE,
  comp: [],
  keep: [],
  shown: [],
  dealt: 0,
  stamp: "",
};

/** Parameter order is fixed so two identical states serialize to identical strings. */
const PARAM_ORDER = [
  "view",
  "scoring",
  "teams",
  "position",
  "search",
  "board",
  "tiers",
  "rail",
  "market",
  "mode",
  "opportunity",
  "only",
  "set",
  "duel",
  "margin",
  "give",
  "goal",
  "get",
  "range",
  "comp",
  "keep",
  "shown",
  "dealt",
  "stamp",
] as const;

export const SCORING_TO_PRESET: Readonly<Record<ScoringValue, ScoringPreset>> = {
  std: "STD",
  half: "HALF",
  ppr: "PPR",
};

export const SCORING_LABELS: Readonly<Record<ScoringValue, string>> = {
  std: "Standard",
  half: "Half PPR",
  ppr: "PPR",
};

export const POSITION_LABELS: Readonly<Record<PositionFilter, string>> = {
  all: "All",
  qb: "QB",
  rb: "RB",
  wr: "WR",
  te: "TE",
};

export function leaguePresetId(teams: TeamCount): string {
  return `redraft-${String(teams)}`;
}

function oneOf<T extends string>(
  raw: string | null,
  allowed: readonly T[],
  fallback: T,
): { value: T; valid: boolean } {
  if (raw === null) return { value: fallback, valid: true };
  const lowered = raw.toLowerCase();
  const match = allowed.find((candidate) => candidate === lowered);
  return match === undefined ? { value: fallback, valid: false } : { value: match, valid: true };
}

export interface ParsedState {
  readonly state: AppState;
  /**
   * True when every supplied parameter was understood. False means the caller should replace
   * the URL with `serializeState(state)` so the address bar stops showing an invalid value.
   */
  readonly normalized: boolean;
}

export function parseState(search: string): ParsedState {
  const params = new URLSearchParams(search);
  let normalized = true;
  const note = (valid: boolean): void => {
    if (!valid) normalized = false;
  };

  const view = oneOf(params.get("view"), VIEWS, DEFAULT_STATE.view);
  note(view.valid);
  const scoring = oneOf(params.get("scoring"), SCORING_VALUES, DEFAULT_STATE.scoring);
  note(scoring.valid);
  const position = oneOf(params.get("position"), POSITION_FILTERS, DEFAULT_STATE.position);
  note(position.valid);
  const board = oneOf(params.get("board"), ["top", "full"] as const, DEFAULT_STATE.board);
  note(board.valid);
  const rail = oneOf(params.get("rail"), RAIL_MODES, DEFAULT_STATE.rail);
  note(rail.valid);
  const mode = oneOf(params.get("mode"), MODES, DEFAULT_STATE.mode);
  note(mode.valid);
  const opportunity = oneOf(
    params.get("opportunity"),
    OPPORTUNITY_SORTS,
    DEFAULT_STATE.opportunity,
  );
  note(opportunity.valid);

  // The Pick-of-the-Week set. Bounded here only against `MAX_POTW_SET`; the real bound is how
  // many sets the build produced, which `clampSet` applies where the build is in hand.
  const rawSet = params.get("set");
  let set = DEFAULT_STATE.set;
  if (rawSet !== null) {
    const parsed = Number.parseInt(rawSet, 10);
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= MAX_POTW_SET) {
      set = parsed;
    } else {
      normalized = false;
    }
  }

  const rawTeams = params.get("teams");
  let teams: TeamCount = DEFAULT_STATE.teams;
  if (rawTeams !== null) {
    const parsed = Number.parseInt(rawTeams, 10);
    const match = TEAM_COUNTS.find((count) => count === parsed);
    if (match === undefined) {
      normalized = false;
    } else {
      teams = match;
    }
  }

  // Search is free text, so there is nothing to reject; it is only trimmed and bounded so a
  // pathological URL cannot drive an unbounded filter string into the table.
  const search_ = (params.get("search") ?? "").trim().slice(0, 64);

  // The market selection is validated for *shape*, not membership: which sources exist is a
  // property of the build, not of this parser, and rejecting a source this bundle has not
  // heard of would break a link from a build with one more source than this one. The view
  // falls back to the default when the named market is absent from the current board.
  const rawMarket = params.get("market");
  let market = DEFAULT_STATE.market;
  if (rawMarket !== null) {
    const candidate = rawMarket.trim().toLowerCase();
    if (/^[a-z0-9_]{1,64}$/.test(candidate)) {
      market = candidate;
    } else {
      normalized = false;
    }
  }

  // `tiers=0.1.4` — the open tier ordinals, deduplicated and ordered so two URLs describing
  // the same open set are the same string. An empty list is meaningful (every tier closed)
  // and is written as `tiers=none`; an absent parameter means "let the board choose".
  //
  // **Ordinals are zero-based.** `schemas/tier_record.schema.json` declares
  // `tier_ordinal` with `minimum: 0`, and the first tier really is 0. An earlier draft of
  // this parser required a positive integer and silently dropped the first tier from every
  // shared link — a bound taken from an assumption rather than from the contract, which is
  // the exact mistake Phase 8 exists to find.
  const rawTiers = params.get("tiers");
  let tiers: readonly number[] | null = DEFAULT_STATE.tiers;
  if (rawTiers !== null) {
    if (rawTiers === "none") {
      tiers = [];
    } else {
      const parsed = rawTiers
        .split(".")
        .map((part) => Number.parseInt(part, 10))
        .filter((value) => Number.isInteger(value) && value >= 0 && value <= MAX_TIER_ORDINAL);
      if (parsed.length === 0) {
        normalized = false;
      } else {
        tiers = [...new Set(parsed)].sort((a, b) => a - b);
        if (serializeTiers(tiers) !== rawTiers) normalized = false;
      }
    }
  }

  // `only=role.momentum` — the Opportunity Board's filters. A token the app does not know is
  // dropped and the URL rewritten, and the survivors are put in canonical order, so two links
  // naming the same filters are the same string.
  const rawOnly = params.get("only");
  let only: readonly OpportunityFilter[] = DEFAULT_STATE.only;
  if (rawOnly !== null) {
    const tokens = rawOnly.toLowerCase().split(".").filter((token) => token !== "");
    only = OPPORTUNITY_FILTERS.filter((filter) => tokens.includes(filter));
    if (serializeFilters(only) !== rawOnly) normalized = false;
  }

  // `duel=00-0036389.00-0039164` — the Start/Sit comparison. Order is the reader's and is
  // kept; a duplicate or a malformed id is dropped and the URL rewritten, and anything past
  // four players is ignored rather than truncating silently in the middle.
  const rawDuel = params.get("duel");
  let duel: readonly string[] = DEFAULT_STATE.duel;
  if (rawDuel !== null) {
    const tokens = rawDuel.split(".").filter((token) => token !== "");
    const valid: string[] = [];
    for (const token of tokens) {
      const id = `gsis:${token}`;
      if (GSIS_SHORT.test(token) && !valid.includes(id) && valid.length < MAX_DUEL) {
        valid.push(id);
      }
    }
    duel = valid;
    if (serializeDuel(duel) !== rawDuel) normalized = false;
  }

  const rawMargin = params.get("margin");
  let margin = DEFAULT_STATE.margin;
  if (rawMargin !== null) {
    const parsed = Number.parseInt(rawMargin, 10);
    if (
      Number.isInteger(parsed) &&
      String(parsed) === rawMargin.trim() &&
      Math.abs(parsed) <= MARGIN_BOUND
    ) {
      margin = parsed;
    } else {
      normalized = false;
    }
  }

  // The Trade tab (ADR-100 §8). Every token is validated for shape here; whether an id is on
  // the board, or an index inside the build's pool, is decided where the build is in hand.
  const give = parseIdList(params.get("give"), MAX_GIVE);
  if (!give.valid) normalized = false;

  const goal = oneOf(params.get("goal"), TRADE_GOALS, DEFAULT_STATE.goal);
  note(goal.valid);

  const get = oneOfNumber(params.get("get"), TRADE_COUNTS, DEFAULT_STATE.get);
  note(get.valid);
  const range = oneOfNumber(params.get("range"), TRADE_RANGES, DEFAULT_STATE.range);
  note(range.valid);

  // `comp=rb.wr` — one slot per received player, canonical order. A slot count that differs
  // from `get` cannot describe this search and is dropped; all-`any` is the default and omitted.
  const rawComp = params.get("comp");
  let comp: readonly CompSlot[] = DEFAULT_STATE.comp;
  if (rawComp !== null) {
    const tokens = rawComp.toLowerCase().split(".");
    const slots = tokens.filter((token): token is CompSlot =>
      (COMP_SLOTS as readonly string[]).includes(token),
    );
    if (slots.length === tokens.length && slots.length === get.value) {
      comp = slots.every((slot) => slot === "any") ? [] : canonicalComp(slots);
    }
    if (serializeComp(comp) !== rawComp) normalized = false;
  }

  // `keep=00-0000013.00-0000002_00-0000011` — packages `_`-separated, members `.`-separated.
  const rawKeep = params.get("keep");
  let keep: readonly (readonly string[])[] = DEFAULT_STATE.keep;
  if (rawKeep !== null) {
    const packages: string[][] = [];
    const seen = new Set<string>();
    for (const chunk of rawKeep.split("_")) {
      const members = parseIdList(chunk, 3);
      if (!members.valid || members.ids.length === 0) continue;
      const sorted = [...members.ids].sort();
      const key = sorted.join(".");
      if (seen.has(key) || packages.length >= MAX_KEEP) continue;
      seen.add(key);
      packages.push(sorted);
    }
    keep = packages;
    if (serializeKeep(keep) !== rawKeep) normalized = false;
  }

  const rawShown = params.get("shown");
  let shown: readonly number[] = DEFAULT_STATE.shown;
  if (rawShown !== null) {
    const tokens = rawShown.split(".");
    const values = tokens.map((token) => Number.parseInt(token, 10));
    const valid =
      tokens.length <= MAX_SHOWN &&
      values.every((value, index) => String(value) === tokens[index] && value >= 0 && value <= MAX_DEALT) &&
      new Set(values).size === values.length;
    if (valid) shown = values;
    else normalized = false;
  }

  const rawDealt = params.get("dealt");
  let dealt = DEFAULT_STATE.dealt;
  if (rawDealt !== null) {
    const parsed = Number.parseInt(rawDealt, 10);
    if (String(parsed) === rawDealt && parsed >= 0 && parsed <= MAX_DEALT + 1) dealt = parsed;
    else normalized = false;
  }

  const rawStamp = params.get("stamp");
  let stamp = DEFAULT_STATE.stamp;
  if (rawStamp !== null) {
    if (/^[0-9a-f]{8}$/.test(rawStamp)) stamp = rawStamp;
    else normalized = false;
  }

  // A parameter the app does not know is dropped rather than preserved: keeping it would make
  // two URLs describing the same state compare unequal.
  for (const key of params.keys()) {
    if (!(PARAM_ORDER as readonly string[]).includes(key)) normalized = false;
  }

  return {
    state: {
      view: view.value,
      scoring: scoring.value,
      teams,
      position: position.value,
      search: search_,
      board: board.value,
      tiers,
      market,
      rail: rail.value,
      mode: mode.value,
      opportunity: opportunity.value,
      only,
      set,
      duel,
      margin,
      give: give.ids,
      goal: goal.value,
      get: get.value,
      range: range.value,
      comp,
      keep,
      shown,
      dealt,
      stamp,
    },
    normalized,
  };
}

function oneOfNumber<T extends number>(
  raw: string | null,
  allowed: readonly T[],
  fallback: T,
): { value: T; valid: boolean } {
  if (raw === null) return { value: fallback, valid: true };
  const parsed = Number.parseInt(raw, 10);
  const match = allowed.find((candidate) => candidate === parsed && String(parsed) === raw);
  return match === undefined ? { value: fallback, valid: false } : { value: match, valid: true };
}

/**
 * `00-0036389.00-0039164` → canonical ids, order kept. A malformed or repeated id is dropped
 * and anything past `limit` ignored; `valid` is false whenever anything was dropped.
 */
function parseIdList(raw: string | null, limit: number): { ids: readonly string[]; valid: boolean } {
  if (raw === null) return { ids: [], valid: true };
  const tokens = raw.split(".").filter((token) => token !== "");
  const ids: string[] = [];
  for (const token of tokens) {
    const id = `gsis:${token}`;
    if (GSIS_SHORT.test(token) && !ids.includes(id) && ids.length < limit) ids.push(id);
  }
  return { ids, valid: ids.length === tokens.length && tokens.length > 0 };
}

/** Named positions in QB, RB, WR, TE order, then `any`. */
export function canonicalComp(slots: readonly CompSlot[]): CompSlot[] {
  return [...slots].sort((a, b) => COMP_SLOTS.indexOf(a) - COMP_SLOTS.indexOf(b));
}

export function serializeComp(comp: readonly CompSlot[]): string {
  return canonicalComp(comp).join(".");
}

/** Kept packages in shelf order; each package's members sorted, so one package is one string. */
export function serializeKeep(keep: readonly (readonly string[])[]): string {
  return keep.map((members) => serializeDuel([...members].sort())).join("_");
}

/** `["gsis:00-0036389", "gsis:00-0039164"]` -> `00-0036389.00-0039164`, order kept. */
export function serializeDuel(duel: readonly string[]): string {
  return duel.map((id) => id.replace(/^gsis:/, "")).join(".");
}

/** `[1, 2, 5]` -> `1.2.5`; the empty set -> `none`, which is a state and not an absence. */
export function serializeTiers(tiers: readonly number[]): string {
  return tiers.length === 0 ? "none" : [...new Set(tiers)].sort((a, b) => a - b).join(".");
}

/** `["momentum", "role"]` -> `role.momentum`: canonical order, duplicates dropped. */
export function serializeFilters(filters: readonly OpportunityFilter[]): string {
  return OPPORTUNITY_FILTERS.filter((filter) => filters.includes(filter)).join(".");
}

/** `?scoring=half&position=rb` — defaults omitted, order fixed, empty string when default. */
export function serializeState(state: AppState): string {
  const params = new URLSearchParams();
  for (const key of PARAM_ORDER) {
    if (key === "tiers") {
      if (state.tiers !== null) params.set(key, serializeTiers(state.tiers));
      continue;
    }
    if (key === "only") {
      const filters = serializeFilters(state.only);
      if (filters !== "") params.set(key, filters);
      continue;
    }
    if (key === "duel" || key === "give") {
      if (state[key].length > 0) params.set(key, serializeDuel(state[key]));
      continue;
    }
    if (key === "comp") {
      if (state.comp.length > 0) params.set(key, serializeComp(state.comp));
      continue;
    }
    if (key === "keep") {
      if (state.keep.length > 0) params.set(key, serializeKeep(state.keep));
      continue;
    }
    if (key === "shown") {
      if (state.shown.length > 0) params.set(key, state.shown.join("."));
      continue;
    }
    const value = state[key];
    if (value === DEFAULT_STATE[key]) continue;
    if (key === "search" && state.search === "") continue;
    params.set(key, String(value));
  }
  const rendered = params.toString();
  return rendered === "" ? "" : `?${rendered}`;
}

/**
 * The panel to render, given the state and the mode actually in force.
 *
 * `auto` resolves to each mode's own first board. A view the current mode does not own is
 * still honoured — the two boards a mode does not list are reachable, not forbidden — with
 * one exception: `data` is shared by both modes and always resolves to itself.
 */
export function resolveView(view: ViewId, mode: Exclude<ModeId, "auto">): ResolvedViewId {
  if (view !== "auto") return view;
  return mode === "in_season" ? "ros" : "tiers";
}

/**
 * The mode actually in force: the reader's override, or the season state the build derived.
 *
 * `derived` is null when no in-season bundle was published, which is the ordinary state
 * before kickoff — there is nothing to switch to, so draft mode is the only answer.
 */
export function resolveMode(
  mode: ModeId,
  derived: "draft" | "in_season" | null,
): "draft" | "in_season" {
  if (mode !== "auto") return mode;
  return derived ?? "draft";
}

/** The full address to push, keeping whatever path the site is served from. */
export function stateHref(state: AppState, pathname: string): string {
  return `${pathname}${serializeState(state)}`;
}
