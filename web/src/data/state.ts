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

export const VIEWS = ["tiers", "arbitrage", "data"] as const;
export type ViewId = (typeof VIEWS)[number];

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
  view: "tiers",
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
    },
    normalized,
  };
}

/** `[1, 2, 5]` -> `1.2.5`; the empty set -> `none`, which is a state and not an absence. */
export function serializeTiers(tiers: readonly number[]): string {
  return tiers.length === 0 ? "none" : [...new Set(tiers)].sort((a, b) => a - b).join(".");
}

/** `?scoring=half&position=rb` — defaults omitted, order fixed, empty string when default. */
export function serializeState(state: AppState): string {
  const params = new URLSearchParams();
  for (const key of PARAM_ORDER) {
    if (key === "tiers") {
      if (state.tiers !== null) params.set(key, serializeTiers(state.tiers));
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

/** The full address to push, keeping whatever path the site is served from. */
export function stateHref(state: AppState, pathname: string): string {
  return `${pathname}${serializeState(state)}`;
}
