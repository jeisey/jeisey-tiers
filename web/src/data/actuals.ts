/**
 * Season-to-date actuals, read one way everywhere (ADR-105).
 *
 * The build publishes `season_actuals_v1`: each player's actual points, games played, points
 * per game and his rank by points among **every** player at his position who has appeared,
 * computed before any board's depth, filter, search or page existed. This module is the only
 * place the site turns one of those records into words, so the RoS chart, the three tables,
 * the card and the filtered CSVs cannot disagree about what "QB4" or "—" means.
 *
 * **Three states, never merged.**
 *
 * - `ranked` — he has appeared; every number is the artifact's.
 * - `no_appearances` — the build knows he has not played: 0 points, no rate, no rank.
 * - `unavailable` — the build published no actuals for him (withheld, older build, a player
 *   with no canonical id). Printed as unavailable, never as a zero and never filled from the
 *   preseason board or from the model's own to-date fields.
 *
 * **Nothing is ranked here.** A season rank is read from the record; this file never sorts
 * loaded rows into a rank, which would rank the page rather than the league.
 */

import type { Position, SeasonActualsMetadata, SeasonActualsRow } from "./contracts";
import { EM_DASH } from "./format";

export type SeasonStanding =
  | {
      readonly kind: "ranked";
      readonly position: Position;
      readonly rank: number;
      readonly points: number;
      readonly games: number;
      readonly perGame: number;
    }
  | { readonly kind: "no_appearances"; readonly position: Position }
  | { readonly kind: "unavailable"; readonly reason: string };

/** Whether this build's actuals can be read at all, and why not when they cannot. */
export interface ActualsAvailability {
  readonly published: boolean;
  readonly reason: string;
}

export const ACTUALS_NOT_PUBLISHED = "Season actuals were not published with this build.";

export function actualsAvailability(
  metadata: SeasonActualsMetadata | null | undefined,
  artifactPublished: boolean,
): ActualsAvailability {
  if (metadata === null || metadata === undefined || !artifactPublished) {
    return { published: false, reason: ACTUALS_NOT_PUBLISHED };
  }
  if (metadata.status !== "published") {
    return {
      published: false,
      reason:
        "Season actuals are withheld for this build: upstream data was incomplete " +
        "through the cutoff, so no ranks are shown rather than ranks over fewer players.",
    };
  }
  return { published: true, reason: "" };
}

/** One player's standing, from his record (or its absence) and the build's availability. */
export function seasonStanding(
  row: SeasonActualsRow | null | undefined,
  availability: ActualsAvailability,
): SeasonStanding {
  if (!availability.published) return { kind: "unavailable", reason: availability.reason };
  if (row === null || row === undefined) {
    return { kind: "unavailable", reason: "No season actuals are published for this player." };
  }
  if (row.games_played <= 0 || row.season_position_rank === null || row.points_per_game === null) {
    return { kind: "no_appearances", position: row.position };
  }
  return {
    kind: "ranked",
    position: row.position,
    rank: row.season_position_rank,
    points: row.points,
    games: row.games_played,
    perGame: row.points_per_game,
  };
}

/** One decimal, a real minus sign, and never "-0.0". */
function points(value: number): string {
  const text = Math.abs(value).toFixed(1);
  return value < 0 && Number(text) !== 0 ? `−${text}` : text;
}

/** `QB4`, or an em dash for no appearances and for unavailable. */
export function formatSeasonRank(standing: SeasonStanding): string {
  return standing.kind === "ranked" ? `${standing.position}${String(standing.rank)}` : EM_DASH;
}

/** Total points: a known zero prints as `0.0`, a missing value as an em dash. */
export function formatSeasonPoints(standing: SeasonStanding): string {
  if (standing.kind === "ranked") return points(standing.points);
  return standing.kind === "no_appearances" ? "0.0" : EM_DASH;
}

export function formatSeasonPerGame(standing: SeasonStanding): string {
  return standing.kind === "ranked" ? points(standing.perGame) : EM_DASH;
}

export function formatSeasonGames(standing: SeasonStanding): string {
  if (standing.kind === "ranked") return String(standing.games);
  return standing.kind === "no_appearances" ? "0" : EM_DASH;
}

/** Why a season cell is empty, in words: the cell's accessible and visible qualifier. */
export function seasonAbsence(standing: SeasonStanding): string | null {
  if (standing.kind === "no_appearances") return "No appearances";
  if (standing.kind === "unavailable") return "Unavailable";
  return null;
}

/** A RoS positional rank as it is printed beside a season rank: `QB15`. */
export function formatRosPositionRank(position: Position, rank: number | null | undefined): string {
  return rank === null || rank === undefined ? EM_DASH : `${position}${String(rank)}`;
}

/**
 * The distance between a RoS positional rank and a season positional rank, in places.
 *
 * `below` means the RoS rank is the larger number (a worse place) than the season rank. It is
 * a difference between two orderings of two different quantities — points already scored and
 * modelled value from here — never a movement over time.
 */
export interface RankGap {
  readonly places: number;
  readonly direction: "below" | "above" | "same";
}

export function rankGap(
  rosPositionRank: number | null | undefined,
  standing: SeasonStanding,
): RankGap | null {
  if (rosPositionRank === null || rosPositionRank === undefined) return null;
  if (standing.kind !== "ranked") return null;
  const places = rosPositionRank - standing.rank;
  if (places === 0) return { places: 0, direction: "same" };
  return { places: Math.abs(places), direction: places > 0 ? "below" : "above" };
}

/** The card's neutral statement of the gap: "RoS is 11 places below his season-to-date rank." */
export function rankGapSentence(gap: RankGap): string {
  if (gap.direction === "same") return "RoS and season-to-date ranks are the same.";
  return (
    `RoS is ${String(gap.places)} place${gap.places === 1 ? "" : "s"} ${gap.direction} ` +
    "his season-to-date rank."
  );
}

/**
 * The tables' signed form of the same distance: season rank minus RoS positional rank, in
 * places. Positive when RoS ranks him higher (a smaller number) than his production so far —
 * the card's "RoS is 7 places above" is `+7` — and negative when lower. Null when either rank
 * is missing: no projection, no appearances or no published actuals is not a gap of zero.
 */
export function rosVsSeasonPlaces(
  rosPositionRank: number | null | undefined,
  standing: SeasonStanding | undefined,
): number | null {
  if (rosPositionRank === null || rosPositionRank === undefined) return null;
  if (standing?.kind !== "ranked") return null;
  return standing.rank - rosPositionRank;
}

/** `+7`, `−10` with a real minus sign, `0`, or an em dash when there is no gap to state. */
export function formatRosVsSeason(places: number | null): string {
  if (places === null) return EM_DASH;
  if (places === 0) return "0";
  return places > 0 ? `+${String(places)}` : `−${String(Math.abs(places))}`;
}

/** The cell's words, for a screen reader and a tooltip: never a sign alone. */
export function describeRosVsSeason(places: number | null): string {
  if (places === null) return "No gap: one of the two ranks is missing";
  if (places === 0) return "RoS rank and season rank are the same";
  const count = Math.abs(places);
  return `RoS rank is ${String(count)} place${count === 1 ? "" : "s"} ${places > 0 ? "above" : "below"} season rank`;
}

/** Sort order of the four positions, for grouping positional ranks in mixed views. */
const POSITION_ORDER: Readonly<Record<string, number>> = { QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DST: 5 };

/**
 * A sort key for a positional rank in a mixed-position table: grouped by position, then by
 * rank, so QB4 never sorts between RB3 and RB5 as if the two standings were one. Undefined for
 * a missing rank, which the tables sort last in either direction.
 */
export function positionalSortKey(
  position: Position,
  rank: number | null | undefined,
): number | undefined {
  if (rank === null || rank === undefined) return undefined;
  return (POSITION_ORDER[position] ?? 9) * 100_000 + rank;
}

/** The value a numeric actuals column sorts by; undefined (sorted last) when there is none. */
export function seasonPointsSortKey(standing: SeasonStanding): number | undefined {
  if (standing.kind === "ranked") return standing.points;
  return standing.kind === "no_appearances" ? 0 : undefined;
}

export function seasonPerGameSortKey(standing: SeasonStanding): number | undefined {
  return standing.kind === "ranked" ? standing.perGame : undefined;
}

/**
 * The four values a filtered CSV row carries — the record's own, exactly as the full CSV
 * writes them: a known zero is `0` points over `0` games with no rate or rank, and an
 * unavailable standing is four empty cells.
 */
export function seasonCsvCells(standing: SeasonStanding | undefined): readonly (number | null)[] {
  if (standing === undefined || standing.kind === "unavailable") return [null, null, null, null];
  if (standing.kind === "no_appearances") return [null, 0, 0, null];
  return [standing.rank, standing.points, standing.games, standing.perGame];
}

/** The column names those cells go under, identical to the full CSVs' (ADR-105). */
export const SEASON_CSV_COLUMNS = [
  "season_position_rank",
  "season_points",
  "season_games_played",
  "season_points_per_game",
] as const;

/**
 * The filtered exports' one derived column, after the four above: season rank minus RoS
 * positional rank, empty when either is missing. The full CSVs carry both ranks and leave the
 * subtraction to the reader; the browser's exports mirror the table, which shows it.
 */
export const ROS_VS_SEASON_CSV_COLUMN = "ros_vs_season_places";

/** Short column labels and their definitions, shared by every table. */
export const SEASON_COLUMN_LABELS = {
  rank: "Szn rank",
  points: "Total pts",
  perGame: "Avg pts/g",
  rosVsSeason: "RoS vs Szn",
} as const;
