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

import { PositionTag, RosStatusBadge } from "../components/primitives";
import { formatRank, formatValue } from "../data/format";
import { longAbsenceLabel, type OpportunityRow } from "../data/ros";

export const OPPORTUNITY_TABLE_CAPTION =
  "In-season opportunity board. Add and drop counts are transactions over the requested " +
  "window; they are never converted into a draft position and never differenced against the " +
  "rest-of-season rank. A row marked “surfaced” is published because current evidence made " +
  "him relevant, and carries no tier. The mark beside a name is the roster status the build " +
  "recorded: annotation, and no input to any number here.";

interface Scale {
  /** The largest rest-of-season value on the rows shown; the value bar's denominator. */
  readonly widestValue: number;
  /** The largest add OR drop count on the rows shown; one denominator for both columns. */
  readonly widestCount: number;
}

export function opportunityTableScale(rows: readonly OpportunityRow[]): Scale {
  let widestValue = 0;
  let widestCount = 0;
  for (const { record } of rows) {
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
): ColumnDef<OpportunityRow>[] {
  return [
    {
      id: "ros_fair_rank",
      header: "ROS Rank",
      accessorFn: (row) => row.record.ros_fair_rank,
      cell: (context) => formatRank(context.row.original.record.ros_fair_rank),
      meta: { align: "right", width: "4.5rem" },
    },
    {
      id: "player",
      header: "Player",
      accessorFn: (row) => row.record.display_name,
      cell: (context) => {
        const record = context.row.original.record;
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
      id: "position",
      header: "Pos",
      accessorFn: (row) => row.record.position,
      cell: (context) => <PositionTag position={context.row.original.record.position} />,
      meta: { width: "3rem" },
    },
    {
      id: "ros_position_rank",
      header: "ROS PosRk",
      accessorFn: (row) => row.record.ros_position_rank,
      cell: (context) => (
        <span className="muted">
          {context.row.original.record.position}
          {formatRank(context.row.original.record.ros_position_rank)}
        </span>
      ),
      meta: { align: "right", width: "5.5rem" },
    },
    {
      id: "team",
      header: "Team",
      accessorFn: (row) => row.record.team ?? "",
      cell: (context) => <span className="muted">{context.row.original.record.team ?? "—"}</span>,
      meta: { width: "3.5rem" },
    },
    {
      id: "ros_expected_vorp",
      header: "ROS Exp VORP",
      accessorFn: (row) => row.record.ros_expected_vorp,
      cell: (context) => formatValue(context.row.original.record.ros_expected_vorp),
      meta: {
        align: "right",
        width: "7rem",
        track: (row: OpportunityRow) =>
          barGradient(
            Math.abs(row.record.ros_expected_vorp) / scale.widestValue,
            "rgb(46 204 255 / 55%)",
            "rgb(46 204 255 / 10%)",
          ),
      },
    },
    {
      id: "add_count",
      header: `Adds${windowSuffix}`,
      accessorFn: (row) => row.record.add_count ?? -1,
      cell: (context) => countCell(context.row.original.record.add_count),
      meta: {
        align: "right",
        width: "6rem",
        // No bar at all when the feed said nothing: a zero-width bar and "nobody added him"
        // look identical, and only one of them is a reading.
        track: (row: OpportunityRow) =>
          row.record.add_count === null || row.record.add_count === undefined
            ? undefined
            : barGradient(
                row.record.add_count / scale.widestCount,
                "rgb(34 209 154 / 60%)",
                "rgb(34 209 154 / 12%)",
              ),
      },
    },
    {
      id: "drop_count",
      header: `Drops${windowSuffix}`,
      accessorFn: (row) => row.record.drop_count ?? -1,
      cell: (context) => countCell(context.row.original.record.drop_count),
      meta: {
        align: "right",
        width: "6rem",
        track: (row: OpportunityRow) =>
          row.record.drop_count === null || row.record.drop_count === undefined
            ? undefined
            : barGradient(
                row.record.drop_count / scale.widestCount,
                "rgb(255 138 128 / 60%)",
                "rgb(255 138 128 / 12%)",
              ),
      },
    },
    {
      id: "net_add_count",
      header: "Net adds",
      accessorFn: (row) => row.record.net_add_count ?? Number.NEGATIVE_INFINITY,
      cell: (context) => {
        const net = context.row.original.record.net_add_count;
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
      meta: { align: "right", width: "6rem" },
    },
    {
      id: "snap_share_last3",
      header: "Snap share",
      accessorFn: (row) => row.record.snap_share_last3 ?? -1,
      cell: (context) => {
        const share = context.row.original.record.snap_share_last3;
        return share === null || share === undefined ? (
          <span className="muted">—</span>
        ) : (
          `${String(Math.round(share * 100))}%`
        );
      },
      meta: {
        align: "right",
        width: "6rem",
        // A share has its own bounded scale: the bar is the percentage itself, not a
        // proportion of the widest on the board.
        track: (row: OpportunityRow) =>
          row.record.snap_share_last3 === null || row.record.snap_share_last3 === undefined
            ? undefined
            : barGradient(
                row.record.snap_share_last3,
                "rgb(46 204 255 / 45%)",
                "rgb(46 204 255 / 10%)",
              ),
      },
    },
    {
      id: "weeks_since_last_game",
      header: "Weeks since last game",
      accessorFn: (row) => row.record.weeks_since_last_game,
      cell: (context) => {
        const weeks = Math.round(context.row.original.record.weeks_since_last_game);
        return <span className="muted">{weeks === 0 ? "Played latest week" : String(weeks)}</span>;
      },
      meta: { align: "right", width: "9rem" },
    },
  ];
}

interface ColumnMeta {
  readonly align?: "right";
  readonly className?: string;
  readonly width?: string;
  readonly track?: (row: OpportunityRow) => string | undefined;
}

export function OpportunityTable({
  rows,
  windowSuffix,
  onSelect,
  selectedPlayerId,
  visibleRowsRef,
}: {
  readonly rows: readonly OpportunityRow[];
  /** The declared window, e.g. ` (24h)`, appended to the two count headings. */
  readonly windowSuffix: string;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly visibleRowsRef?: RefObject<readonly OpportunityRow[]>;
}): React.JSX.Element {
  const [sorting, setSorting] = useState<SortingState>([]);
  const scale = useMemo(() => opportunityTableScale(rows), [rows]);
  const columns = useMemo(
    () => opportunityColumns(onSelect, scale, windowSuffix),
    [onSelect, scale, windowSuffix],
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
      <table className="sheet">
        <caption>
          {OPPORTUNITY_TABLE_CAPTION}{" "}
          {`Showing ${String(rows.length)} player${rows.length === 1 ? "" : "s"}. `}
          Add and drop bars are scaled against the largest count on the rows shown; the value
          bar against the largest rest-of-season value; the snap-share bar is the percentage
          itself.
        </caption>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const meta = (header.column.columnDef.meta ?? {}) as ColumnMeta;
                const sorted = header.column.getIsSorted();
                return (
                  <th
                    key={header.id}
                    scope="col"
                    className={meta.className}
                    style={{ width: meta.width, textAlign: meta.align }}
                    aria-sort={
                      sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                    }
                  >
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
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr
              key={row.original.record.player_id}
              data-selected={row.original.record.player_id === selectedPlayerId}
              data-player={row.original.record.player_id}
              data-surfaced={row.original.record.outside_tier_board ? "true" : undefined}
              data-long-absence={row.original.record.long_absence ? "true" : undefined}
            >
              {row.getVisibleCells().map((cell) => {
                const meta = (cell.column.columnDef.meta ?? {}) as ColumnMeta;
                const track = meta.track?.(row.original);
                return (
                  <td
                    key={cell.id}
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
