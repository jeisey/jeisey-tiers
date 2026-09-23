/**
 * The Opportunity table: the canonical, sortable, accessible form of the in-season board.
 *
 * Phase 12 hand-rolled this as a plain `<table>` while every other board on the site ran on
 * TanStack with position chips, sortable headers and the design's micro-glyphs. The result
 * read as a different product on the same page — the owner's word was "bland" — so it is the
 * Tier table's construction now, over the Opportunity Board's quantities (ADR-085).
 *
 * The cell glyphs carry the rules the board is built on, and they are not decoration:
 *
 * **A count is drawn as a count.** The adds and drops bars are scaled against the largest
 * count on the rows shown, which is stated in the caption. They are never rescaled into a
 * draft position, never differenced against `ros_fair_rank`, and a null is an em dash with no
 * bar rather than a zero-length one — the feed saying nothing and the feed saying zero are
 * different facts.
 *
 * **Adds and drops share one scale, and value has its own.** The two quantities have no
 * common unit. Giving the transaction columns one denominator between them makes eight adds
 * and eight drops the same length, which is true; giving them the *value* column's
 * denominator would be meaningless.
 *
 * **Current status is a mark on the name, not a column** — the same change and the same
 * reason as `RosTable`.
 *
 * **Three signal columns, each one published reading** (ADR-092). *Role* is the position's
 * leading measure from `player_usage.json` — pass attempts for a quarterback, snap share for
 * everyone else — as its latest value, the card's own glyph and change, and the window.
 * *Add momentum* is `behavior_trend_series.json`'s slope with its span. *Next game* is
 * `team_matchups.json`'s opponent and, when a line is posted, the implied team points —
 * sportsbook context, never a rating. They replace the generic three-week snap share, which
 * was a constant for every quarterback, and the weeks-since column, whose one useful reading
 * the long-absence mark on the name and the role window already carry.
 *
 * **No column sorts incomparable magnitudes.** Role sorts rising → flat → falling and compares
 * the size of a change only when every row shown is one position (`compareRole`); a row with
 * no reading sorts last in both directions, because an unknown is not a small number.
 */

import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useEffect, useMemo, useState, type RefObject } from "react";

import { RosStatusBadge } from "../components/primitives";
import {
  compareMomentum,
  compareRole,
  momentumCell,
  nextGameCell,
  roleCell,
  roleCategory,
  type OpportunityCandidate,
  type RoleOrdering,
} from "../data/candidates";
import { formatRank, formatValue } from "../data/format";
import { longAbsenceLabel } from "../data/ros";

export const OPPORTUNITY_TABLE_CAPTION =
  "In-season opportunity board. Add and drop counts are transactions over the requested " +
  "window; they are never converted into a draft position and never differenced against the " +
  "rest-of-season rank. A row marked “surfaced” is published because current evidence made " +
  "him relevant, and carries no tier. The mark beside a name is the roster status the build " +
  "recorded: annotation, and no input to any number here. Role is the position's leading " +
  "measure — pass attempts for a quarterback, snap share otherwise — in his latest game " +
  "against the average of his earlier games. Add momentum is the published slope of his add " +
  "count over the retained window. Next game is sportsbook context read by no model, and no " +
  "column rates an opponent.";

interface Scale {
  /** The largest rest-of-season value on the rows shown; the value bar's denominator. */
  readonly widestValue: number;
  /** The largest add OR drop count on the rows shown; one denominator for both columns. */
  readonly widestCount: number;
}

export function opportunityTableScale(rows: readonly OpportunityCandidate[]): Scale {
  let widestValue = 0;
  let widestCount = 0;
  for (const {
    row: { record },
  } of rows) {
    widestValue = Math.max(widestValue, Math.abs(record.ros_expected_vorp));
    widestCount = Math.max(widestCount, record.add_count ?? 0, record.drop_count ?? 0);
  }
  return { widestValue: widestValue || 1, widestCount: widestCount || 1 };
}

/** A proportional bar under the number printed above it, as `background-image` on the cell. */
function barGradient(share: number, colour: string, wash: string): string {
  const width = Math.max(0, Math.min(100, share * 100));
  return (
    `linear-gradient(90deg, ${colour} 0 ${String(width)}%, ` +
    `${wash} ${String(width)}% 100%)`
  );
}

function countCell(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
}

function opportunityColumns(
  onSelect: (playerId: string) => void,
  scale: Scale,
  windowSuffix: string,
  roleOrdering: RoleOrdering,
): ColumnDef<OpportunityCandidate>[] {
  return [
    {
      id: "ros_fair_rank",
      header: "ROS Rank",
      accessorFn: (row) => row.row.record.ros_fair_rank,
      cell: (context) => formatRank(context.row.original.row.record.ros_fair_rank),
      meta: { align: "right", className: "col-low col-mid" },
    },
    {
      id: "player",
      header: "Player",
      accessorFn: (row) => row.row.record.display_name,
      cell: (context) => {
        const record = context.row.original.row.record;
        return (
          <span className="player-cell">
            <button
              type="button"
              className="player-name"
              onClick={() => {
                onSelect(record.player_id);
              }}
            >
              {record.display_name}
            </button>
            {record.outside_tier_board && (
              <span
                className="surface-badge"
                title="Surfaced by current evidence; published without a tier"
              >
                surfaced
              </span>
            )}
            <RosStatusBadge status={record.current_status} />
            {record.long_absence && (
              <span
                className="absence-badge"
                data-flag="long-absence"
                title={longAbsenceLabel(record)}
              >
                <span aria-hidden="true">◷</span>
                <span className="absence-weeks">
                  {`${String(Math.round(record.weeks_since_last_game))}w`}
                </span>
                <span className="visually-hidden">
                  {`${longAbsenceLabel(record)}. No injury or practice-report information is used.`}
                </span>
              </span>
            )}
          </span>
        );
      },
      meta: { className: "col-player" },
    },
    {
      /*
        Position and rest-of-season position rank in one tag, the chart's own `RB12` — two
        columns that printed the position twice are one column that prints it once. Sorted by
        position, then by rank inside it, so a click groups the board rather than interleaving
        four positions' twelfth players.
      */
      id: "ros_position_rank",
      header: "ROS PosRk",
      accessorFn: (row) =>
        `${row.row.record.position}|${String(row.row.record.ros_position_rank).padStart(4, "0")}`,
      cell: (context) => {
        const record = context.row.original.row.record;
        return (
          <span className="pos-tag" data-pos={record.position}>
            {record.position}
            <b>{formatRank(record.ros_position_rank)}</b>
          </span>
        );
      },
    },
    {
      id: "team",
      header: "Team",
      accessorFn: (row) => row.row.record.team ?? "",
      cell: (context) => (
        <span className="muted">{context.row.original.row.record.team ?? "—"}</span>
      ),
      meta: { width: "3.5rem", className: "col-mid" },
    },
    {
      id: "ros_expected_vorp",
      header: "ROS Exp VORP",
      accessorFn: (row) => row.row.record.ros_expected_vorp,
      cell: (context) => formatValue(context.row.original.row.record.ros_expected_vorp),
      meta: {
        align: "right",
        width: "5.5rem",
        // On a phone the chart above prints this value, with its bar, on every row it draws;
        // the table's narrow form leads with the readings the chart does not carry.
        className: "col-low",
        track: (row: OpportunityCandidate) =>
          barGradient(
            Math.abs(row.row.record.ros_expected_vorp) / scale.widestValue,
            "rgb(46 204 255 / 55%)",
            "rgb(46 204 255 / 10%)",
          ),
      },
    },
    {
      /*
        The position's leading role measure, as the card prints it: latest value, the card's
        glyph and change, and the window underneath. A row with no reading sorts last whichever
        way the column is sorted, and magnitudes are compared only when every row shown is one
        position — a quarterback's `+6` is attempts and a back's `+18 pts` is share points.
      */
      id: "role",
      header: "Role",
      accessorFn: (row) => (row.role.kind === "measured" ? roleCategory(row.role) : undefined),
      sortingFn: (a, b) => compareRole(b.original, a.original, roleOrdering),
      sortUndefined: "last",
      sortDescFirst: true,
      cell: (context) => {
        const candidate = context.row.original;
        const cell = roleCell(candidate.role, candidate.row.record.position);
        return (
          <span
            className="signal-cell"
            data-signal="role"
            data-kind={candidate.role.kind}
            data-direction={cell.direction ?? "none"}
            title={cell.sentence}
          >
            <span className="signal-line" aria-hidden="true">
              <span className="signal-metric">{cell.metric}</span>
              <span className="signal-value">{cell.value}</span>
              {cell.change !== null && <span className="signal-change">{cell.change}</span>}
            </span>
            {cell.detail !== "" && (
              <span className="signal-detail" aria-hidden="true">
                {cell.detail}
              </span>
            )}
            <span className="visually-hidden">{cell.sentence}</span>
          </span>
        );
      },
    },
    {
      id: "add_count",
      header: `Adds${windowSuffix}`,
      accessorFn: (row) => row.row.record.add_count ?? -1,
      cell: (context) => countCell(context.row.original.row.record.add_count),
      meta: {
        align: "right",
        // No bar at all when the feed said nothing: a zero-width bar and "nobody added him"
        // look identical, and only one of them is a reading.
        track: (row: OpportunityCandidate) =>
          row.row.record.add_count === null || row.row.record.add_count === undefined
            ? undefined
            : barGradient(
                row.row.record.add_count / scale.widestCount,
                "rgb(34 209 154 / 60%)",
                "rgb(34 209 154 / 12%)",
              ),
      },
    },
    {
      id: "drop_count",
      header: `Drops${windowSuffix}`,
      accessorFn: (row) => row.row.record.drop_count ?? -1,
      cell: (context) => countCell(context.row.original.row.record.drop_count),
      meta: {
        align: "right",
        className: "col-mid",
        track: (row: OpportunityCandidate) =>
          row.row.record.drop_count === null || row.row.record.drop_count === undefined
            ? undefined
            : barGradient(
                row.row.record.drop_count / scale.widestCount,
                "rgb(255 138 128 / 60%)",
                "rgb(255 138 128 / 12%)",
              ),
      },
    },
    {
      id: "net_add_count",
      header: "Net adds",
      accessorFn: (row) => row.row.record.net_add_count ?? Number.NEGATIVE_INFINITY,
      cell: (context) => {
        const net = context.row.original.row.record.net_add_count;
        return (
          <span
            data-change={
              net === null || net === undefined
                ? "none"
                : net > 0
                  ? "up"
                  : net < 0
                    ? "down"
                    : "flat"
            }
          >
            {net === null || net === undefined ? "—" : net > 0 ? `+${String(net)}` : String(net)}
          </span>
        );
      },
      meta: { align: "right" },
    },
    {
      /*
        The published slope and its span, always together (ADR-089). The same glyph and the
        same printed rate as the card's strip, from the same function, so the two cannot
        disagree. A row with no slope sorts last in both directions: "not in the feed" and "one
        observation" are unknowns, not small numbers.
      */
      id: "add_momentum",
      header: "Add momentum",
      accessorFn: (row) =>
        row.momentum.kind === "measured" ? (row.momentum.momentum.trend ?? undefined) : undefined,
      sortingFn: (a, b) => compareMomentum(b.original, a.original),
      sortUndefined: "last",
      sortDescFirst: true,
      cell: (context) => {
        const candidate = context.row.original;
        const cell = momentumCell(candidate.momentum);
        return (
          <span
            className="signal-cell"
            data-signal="momentum"
            data-kind={candidate.momentum.kind}
            data-direction={cell.direction ?? "none"}
            title={cell.sentence}
          >
            <span className="signal-line" aria-hidden="true">
              <span className="signal-value">{cell.value}</span>
            </span>
            {cell.span !== "" && (
              <span className="signal-detail" aria-hidden="true">
                {cell.span}
              </span>
            )}
            <span className="visually-hidden">{cell.sentence}</span>
          </span>
        );
      },
    },
    {
      /*
        The next game as context. Not sortable: the one number in it is a sportsbook's, and a
        column that ordered the board by it would be the board's most prominent claim about
        matchups made out of a number no model reads (ADR-091). A reader who wants it sees it.
      */
      id: "next_game",
      header: "Next game",
      enableSorting: false,
      accessorFn: (row) => row.nextGame.kind,
      cell: (context) => {
        const candidate = context.row.original;
        const cell = nextGameCell(candidate.nextGame);
        return (
          <span
            className="signal-cell"
            data-signal="next"
            data-kind={candidate.nextGame.kind}
            data-lines={cell.linesPosted ? "posted" : "unposted"}
            title={cell.sentence}
          >
            <span className="signal-line" aria-hidden="true">
              <span className="signal-value">{cell.head}</span>
            </span>
            {cell.detail !== "" && (
              <span className="signal-detail" aria-hidden="true">
                {cell.detail}
              </span>
            )}
            <span className="visually-hidden">{cell.sentence}</span>
          </span>
        );
      },
    },
  ];
}

interface ColumnMeta {
  readonly align?: "right";
  readonly className?: string;
  readonly width?: string;
  readonly track?: (row: OpportunityCandidate) => string | undefined;
}

export function OpportunityTable({
  rows,
  windowSuffix,
  roleOrdering,
  onSelect,
  selectedPlayerId,
  visibleRowsRef,
}: {
  readonly rows: readonly OpportunityCandidate[];
  /** The declared window, e.g. ` (24h)`, appended to the two count headings. */
  readonly windowSuffix: string;
  /** Whether a role sort may compare magnitudes: only when every row shown is one position. */
  readonly roleOrdering: RoleOrdering;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly visibleRowsRef?: RefObject<readonly OpportunityCandidate[]>;
}): React.JSX.Element {
  const [sorting, setSorting] = useState<SortingState>([]);
  const scale = useMemo(() => opportunityTableScale(rows), [rows]);
  const columns = useMemo(
    () => opportunityColumns(onSelect, scale, windowSuffix, roleOrdering),
    [onSelect, scale, windowSuffix, roleOrdering],
  );
  const data = useMemo(() => [...rows], [rows]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    enableSortingRemoval: false,
  });

  const sortedRows = table.getRowModel().rows;
  const visible = useMemo(() => sortedRows.map((row) => row.original), [sortedRows]);
  useEffect(() => {
    if (visibleRowsRef !== undefined) visibleRowsRef.current = visible;
  }, [visible, visibleRowsRef]);

  return (
    <div className="table-scroll">
      <table className="sheet opp-sheet">
        <caption>
          {OPPORTUNITY_TABLE_CAPTION}{" "}
          {`Showing ${String(rows.length)} player${rows.length === 1 ? "" : "s"}. `}
          Add and drop bars are scaled against the largest count on the rows shown; the value
          bar against the largest rest-of-season value.
        </caption>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const meta = (header.column.columnDef.meta ?? {}) as ColumnMeta;
                const sorted = header.column.getIsSorted();
                const sortable = header.column.getCanSort();
                return (
                  <th
                    key={header.id}
                    scope="col"
                    className={[meta.className ?? "", sortable ? "" : "plain"]
                      .filter(Boolean)
                      .join(" ")}
                    data-col={header.id}
                    style={{ width: meta.width, textAlign: meta.align }}
                    aria-sort={
                      !sortable
                        ? undefined
                        : sorted === "asc"
                          ? "ascending"
                          : sorted === "desc"
                            ? "descending"
                            : "none"
                    }
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        style={{ justifyContent: meta.align === "right" ? "flex-end" : undefined }}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <span className="sort-mark" data-state={sorted === false ? "none" : sorted}>
                          {sorted === "desc" ? "▼" : "▲"}
                        </span>
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr
              key={row.original.row.record.player_id}
              data-selected={row.original.row.record.player_id === selectedPlayerId}
              data-player={row.original.row.record.player_id}
              data-surfaced={row.original.row.record.outside_tier_board ? "true" : undefined}
              data-long-absence={row.original.row.record.long_absence ? "true" : undefined}
            >
              {row.getVisibleCells().map((cell) => {
                const meta = (cell.column.columnDef.meta ?? {}) as ColumnMeta;
                const track = meta.track?.(row.original);
                return (
                  <td
                    key={cell.id}
                    data-col={cell.column.id}
                    className={[
                      meta.align === "right" ? "num" : "",
                      track === undefined ? "" : "cell-track",
                      meta.className ?? "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    style={track === undefined ? undefined : { backgroundImage: track }}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
