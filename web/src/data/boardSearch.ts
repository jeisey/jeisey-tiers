/**
 * What the board search searches, and what choosing a player changes (ADR-111).
 *
 * The pool is the open board's own rows for the reader's preset — rows already in memory, so
 * a search fetches nothing and never loads another preset. Each entry's team is the value the
 * board matches a search against (`matchesSearch`), so the dialog lists exactly what applying
 * the same query would show.
 *
 * Choosing a player applies his name as the search. If another filter would then hide him —
 * the position filter, or the Opportunity Board's signal filters — that filter is cleared, and
 * the change is described in words beside the search; the preset, the ordering and every other
 * setting are left alone.
 */

import { selectOpportunityCandidates } from "./candidates";
import type { Position } from "./contracts";
import { formatValue } from "./format";
import { matchesPosition, type ArtifactIndex } from "./model";
import { searchTermFor, type SearchEntry } from "./playerSearch";
import type { InSeasonBundle } from "./ros";
import {
  POSITION_LABELS,
  SCORING_TO_PRESET,
  leaguePresetId,
  type AppState,
  type ResolvedViewId,
} from "./state";

/** The views whose rows a search filters. Elsewhere there is nothing for it to change. */
export const SEARCH_VIEWS: readonly ResolvedViewId[] = ["tiers", "arbitrage", "ros", "opportunity", "startsit"];

export function searchApplies(view: ResolvedViewId, inSeason: InSeasonBundle | null): boolean {
  if (!SEARCH_VIEWS.includes(view)) return false;
  return view === "tiers" || view === "arbitrage" || inSeason !== null;
}

/** "the rest-of-season board" — for the dialog's help and its no-results line. */
export function boardName(view: ResolvedViewId, inSeason: InSeasonBundle | null): string {
  switch (view) {
    case "tiers":
      return "the tier board";
    case "arbitrage":
      return "the tier and arbitrage boards";
    case "ros":
      return "the rest-of-season board";
    case "opportunity":
      return "the Opportunity Board";
    case "startsit": {
      const week = inSeason?.metadata.weekly?.target_week;
      return week === undefined ? "the week board" : `the week-${String(week)} board`;
    }
    default:
      return "this board";
  }
}

type Preset = Pick<AppState, "teams" | "scoring">;

/** The open board's rows, as search entries, in the board's own order. */
export function boardSearchPool(
  view: ResolvedViewId,
  index: ArtifactIndex,
  inSeason: InSeasonBundle | null,
  preset: Preset,
): readonly SearchEntry[] {
  const leaguePreset = leaguePresetId(preset.teams);
  const scoring = SCORING_TO_PRESET[preset.scoring];
  const team = (value: string | null): string => value ?? "—";
  if (view === "tiers" || view === "arbitrage") {
    const tiers = index.tiersFor(leaguePreset, scoring).map(
      (record): SearchEntry => ({
        id: record.player_id,
        name: record.display_name,
        position: record.position,
        team: record.team,
        status: index.statusFor(record.player_id),
        meta: `${team(record.team)} · fair rank ${String(record.fair_rank)}`,
      }),
    );
    if (view === "tiers") return tiers;
    // The arbitrage board lists a searched player it has no price for under the table, so the
    // tier board's rows are searchable from it too; a priced row comes first.
    const priced = index.arbitrageFor(leaguePreset, scoring).map(
      (record): SearchEntry => ({
        id: record.player_id,
        name: record.display_name,
        position: record.position,
        team: record.team,
        status: index.statusFor(record.player_id),
        meta: `${team(record.team)} · fair rank ${String(record.fair_rank)}`,
      }),
    );
    return [...priced, ...tiers];
  }
  if (inSeason === null) return [];
  const availability = (playerId: string) => inSeason.availabilityFor(playerId);
  if (view === "ros") {
    return inSeason.rosFor(leaguePreset, scoring).map((record) => ({
      id: record.player_id,
      name: record.display_name,
      position: record.position,
      team: record.team,
      availability: availability(record.player_id),
      meta: `${team(record.team)} · RoS ${record.position}${String(record.ros_position_rank)}`,
    }));
  }
  if (view === "opportunity") {
    const projected = inSeason.opportunityFor(leaguePreset, scoring).map(
      (record): SearchEntry => ({
        id: record.player_id,
        name: record.display_name,
        position: record.position,
        team: record.team,
        availability: availability(record.player_id),
        meta: `${team(record.team)} · RoS ${record.position}${String(record.ros_position_rank)}`,
      }),
    );
    // ADR-102: the board matches these on the team it prints (`FA` for a free agent).
    const unprojected = inSeason.unprojectedFor(leaguePreset, scoring).map((record): SearchEntry => {
      const label = inSeason.teamLabel(record.player_id, record.team);
      return {
        id: record.player_id,
        name: record.display_name,
        position: record.position,
        team: label,
        availability: availability(record.player_id),
        meta: `${team(label)} · no projection`,
      };
    });
    return [...projected, ...unprojected];
  }
  if (view === "startsit") {
    return inSeason.weeklyFor(scoring).map((record) => ({
      id: record.player_id,
      name: record.display_name,
      position: record.position,
      team: record.team,
      availability: availability(record.player_id),
      meta:
        record.quantiles === null
          ? `${team(record.team)} · ${record.game_state === "lines_pending" ? "line pending" : "bye"}`
          : `${team(record.team)} · median ${formatValue(record.quantiles.q50)}`,
    }));
  }
  return [];
}

export interface SearchChoice {
  readonly patch: Partial<AppState>;
  /** What else changed so he could be shown, in words; null when nothing did. */
  readonly note: string | null;
}

/**
 * The state change for choosing one player: his name as the search, and any filter that
 * would hide him cleared.
 */
export function chooseSearchPlayer(
  entry: { readonly id: string; readonly name: string; readonly position: Position },
  state: AppState,
  view: ResolvedViewId,
  inSeason: InSeasonBundle | null,
): SearchChoice {
  const search = searchTermFor(entry);
  const changed: string[] = [];
  let next: AppState = { ...state, search };
  const patch: { -readonly [K in keyof AppState]?: AppState[K] } = { search };
  if (!matchesPosition(entry.position, state.position)) {
    patch.position = "all";
    next = { ...next, position: "all" };
    changed.push(`the ${POSITION_LABELS[state.position]} position filter`);
  }
  if (view === "opportunity" && inSeason !== null && (state.only.length > 0 || state.form !== "all")) {
    const shown = (candidate: AppState) =>
      selectOpportunityCandidates(inSeason, candidate).candidates.some((row) => row.row.record.player_id === entry.id);
    const onBoard = inSeason
      .opportunityFor(leaguePresetId(state.teams), SCORING_TO_PRESET[state.scoring])
      .some((record) => record.player_id === entry.id);
    // ADR-113: the breakout filter first — when clearing it alone shows him, the Show only
    // filters stay as the reader set them.
    if (onBoard && !shown(next) && state.form !== "all") {
      const cleared: AppState = { ...next, form: "all" };
      if (shown(cleared) || state.only.length === 0) {
        patch.form = "all";
        next = cleared;
        changed.push("the Breakout filter");
      }
    }
    if (onBoard && !shown(next) && state.only.length > 0) {
      patch.only = [];
      next = { ...next, only: [] };
      changed.push(state.only.length === 1 ? "the Show only filter" : "the Show only filters");
    }
  }
  const note =
    changed.length === 0 ? null : `Cleared ${changed.join(" and ")} to show ${entry.name} (${entry.position}).`;
  return { patch, note };
}
