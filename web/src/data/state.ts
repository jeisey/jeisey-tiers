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

export interface AppState {
  readonly view: ViewId;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  readonly position: PositionFilter;
  readonly search: string;
  /** Tier Board density switch. Local to the chart but shareable, like every other control. */
  readonly board: "top" | "full";
  readonly rail: RailMode;
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
  rail: "bargains",
};

/** Parameter order is fixed so two identical states serialize to identical strings. */
const PARAM_ORDER = ["view", "scoring", "teams", "position", "search", "board", "rail"] as const;

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
      rail: rail.value,
    },
    normalized,
  };
}

/** `?scoring=half&position=rb` — defaults omitted, order fixed, empty string when default. */
export function serializeState(state: AppState): string {
  const params = new URLSearchParams();
  for (const key of PARAM_ORDER) {
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
