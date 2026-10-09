/**
 * The season-to-date columns, defined once for every table that carries them (ADR-105).
 *
 * `Szn rank`, `RoS vs Szn`, `Total pts` and `Avg pts/g` read the same standing
 * (`data/actuals`) with the same labels, precision, sort rules and absence wording on the RoS
 * table, the Opportunity Board and the Start/Sit week board. They are context beside the
 * model's order, never a new one: no table sorts by them unless the reader asks.
 *
 * **Sorting.** A positional rank sorts grouped by position, then by rank, so in an
 * all-positions view QB4 never lands between RB3 and RB5 as though the two standings were one.
 * `RoS vs Szn` is a signed count of places and sorts as one number across positions, largest
 * first, so the widest gaps either way are one click from the top. A missing value sorts last
 * in either direction.
 */

import type { ColumnDef } from "@tanstack/react-table";

import {
  SEASON_COLUMN_LABELS,
  describeRosVsSeason,
  formatRosVsSeason,
  formatSeasonPerGame,
  formatSeasonPoints,
  formatSeasonRank,
  positionalSortKey,
  rosVsSeasonPlaces,
  seasonAbsence,
  seasonPerGameSortKey,
  seasonPointsSortKey,
  type SeasonStanding,
} from "../data/actuals";
import type { Position } from "../data/contracts";

/** A cell that prints a value, or an em dash with the reason for screen readers and a title. */
function Absent({ standing }: { readonly standing: SeasonStanding }): React.JSX.Element {
  const reason = seasonAbsence(standing) ?? "";
  return (
    <span className="muted season-absent" title={reason}>
      —<span className="visually-hidden">{` ${reason}`}</span>
    </span>
  );
}

export function SeasonRankCell({ standing }: { readonly standing: SeasonStanding | undefined }): React.JSX.Element {
  if (standing === undefined) return <span className="muted">—</span>;
  if (standing.kind !== "ranked") return <Absent standing={standing} />;
  return <span className="season-rank">{formatSeasonRank(standing)}</span>;
}

export function SeasonPointsCell({ standing }: { readonly standing: SeasonStanding | undefined }): React.JSX.Element {
  if (standing === undefined) return <span className="muted">—</span>;
  if (standing.kind === "unavailable") return <Absent standing={standing} />;
  return <span>{formatSeasonPoints(standing)}</span>;
}

export function SeasonPerGameCell({ standing }: { readonly standing: SeasonStanding | undefined }): React.JSX.Element {
  if (standing === undefined) return <span className="muted">—</span>;
  if (standing.kind !== "ranked") return <Absent standing={standing} />;
  return <span>{formatSeasonPerGame(standing)}</span>;
}

/**
 * The signed gap between the two ranks: `+7` when RoS ranks him seven places higher than his
 * production so far. The sign carries the direction and the hidden words say it, so the cell
 * means the same thing without colour.
 */
export function RosVsSeasonCell({ places }: { readonly places: number | null }): React.JSX.Element {
  const words = describeRosVsSeason(places);
  return (
    <span
      className={places === null ? "muted ros-vs-season" : "ros-vs-season"}
      data-direction={places === null ? "none" : places > 0 ? "above" : places < 0 ? "below" : "same"}
      title={words}
    >
      <span aria-hidden="true">{formatRosVsSeason(places)}</span>
      <span className="visually-hidden">{words}</span>
    </span>
  );
}

/** Sort a positional rank within its position; `undefined` (sorted last) when absent. */
export function positionalRankAccessor(
  position: Position,
  rank: number | null | undefined,
): number | undefined {
  return positionalSortKey(position, rank);
}

/** The four columns, for a TanStack table whose rows carry a standing, a position and a RoS rank. */
export function seasonColumns<Row>(
  standingOf: (row: Row) => SeasonStanding | undefined,
  positionOf: (row: Row) => Position,
  rosRankOf: (row: Row) => number | null | undefined,
  /** A class for the two totals, for a table whose narrow widths step columns aside. */
  totalsClass = "",
): ColumnDef<Row>[] {
  const totals = ["col-season", totalsClass].filter(Boolean).join(" ");
  const places = (row: Row): number | null => rosVsSeasonPlaces(rosRankOf(row), standingOf(row));
  return [
    {
      id: "season_position_rank",
      header: SEASON_COLUMN_LABELS.rank,
      accessorFn: (row) => {
        const standing = standingOf(row);
        return standing?.kind === "ranked"
          ? positionalSortKey(positionOf(row), standing.rank)
          : undefined;
      },
      sortUndefined: "last",
      // A rank reads best-first: 1, 2, 3 on the first click.
      sortDescFirst: false,
      cell: (context) => <SeasonRankCell standing={standingOf(context.row.original)} />,
      meta: { align: "right", width: "5rem", className: "col-season" },
    },
    {
      id: "ros_vs_season",
      header: SEASON_COLUMN_LABELS.rosVsSeason,
      accessorFn: (row) => places(row) ?? undefined,
      sortUndefined: "last",
      // The largest positive gap first; the second click puts the most negative on top.
      sortDescFirst: true,
      cell: (context) => <RosVsSeasonCell places={places(context.row.original)} />,
      meta: { align: "right", width: "5rem", className: "col-season" },
    },
    {
      id: "season_points",
      header: SEASON_COLUMN_LABELS.points,
      accessorFn: (row) => {
        const standing = standingOf(row);
        return standing === undefined ? undefined : seasonPointsSortKey(standing);
      },
      sortUndefined: "last",
      sortDescFirst: true,
      cell: (context) => <SeasonPointsCell standing={standingOf(context.row.original)} />,
      meta: { align: "right", width: "5rem", className: totals },
    },
    {
      id: "season_points_per_game",
      header: SEASON_COLUMN_LABELS.perGame,
      accessorFn: (row) => {
        const standing = standingOf(row);
        return standing === undefined ? undefined : seasonPerGameSortKey(standing);
      },
      sortUndefined: "last",
      sortDescFirst: true,
      cell: (context) => <SeasonPerGameCell standing={standingOf(context.row.original)} />,
      meta: { align: "right", width: "5.2rem", className: totals },
    },
  ];
}

/** The caption sentence every table with these columns carries, from the build's cutoff. */
export function seasonCaption(throughWeek: number, scoringLabel: string, unavailable: string | null): string {
  if (unavailable !== null) return `Szn rank, RoS vs Szn, Total pts and Avg pts/g: ${unavailable}`;
  return (
    `Szn rank, Total pts and Avg pts/g are actual results through week ${String(throughWeek)} ` +
    `in ${scoringLabel} scoring, not projections: Szn rank orders every player at the position ` +
    "who has appeared by points scored (ties share a rank), whichever board lists him; Avg " +
    "pts/g counts only games he appeared in. RoS vs Szn is Szn rank minus RoS rank in places: " +
    "+7 means the rest-of-season model ranks him 7 places higher than his production so far, " +
    "−7 lower. A dash means no appearances or no data."
  );
}
