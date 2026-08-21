/**
 * The Tier table: the canonical, accessible, sortable form of the intrinsic board.
 *
 * This is the truth surface. The Tier Board beside it is checked against these numbers, and
 * every value in both comes straight out of `tiers.json` — the browser filters, joins and
 * formats and never computes a VORP (`docs/ARCHITECTURE.md` section 3.2).
 *
 * Sorting is table state and nothing more. Changing it re-orders these rows; it does not
 * change fair rank, which stays the published ordering the chart is drawn in.
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

import { PositionTag, StatusBadge, TierTag } from "../components/primitives";
import { formatRange, formatRank, formatValue } from "../data/format";
import type { TierRow } from "../data/model";

export const TIER_TABLE_CAPTION =
  "Intrinsic tier board. Fair rank is the published order; sorting this table re-orders the " +
  "rows without changing it. Every value is read from the tier artifact.";

function tierColumns(onSelect: (playerId: string) => void): ColumnDef<TierRow>[] {
  return [
    {
      id: "fair_rank",
      header: "Rank",
      accessorFn: (row) => row.record.fair_rank,
      cell: (context) => formatRank(context.row.original.record.fair_rank),
      meta: { align: "right", width: "3.5rem" },
    },
    {
      id: "player",
      header: "Player",
      accessorFn: (row) => row.record.display_name,
      cell: (context) => {
        const row = context.row.original;
        return (
          <span className="player-cell">
            <button
              type="button"
              className="player-name"
              onClick={() => {
                onSelect(row.record.player_id);
              }}
            >
              {row.record.display_name}
            </button>
            <StatusBadge status={row.status} />
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
      id: "position_rank",
      header: "PosRk",
      accessorFn: (row) => row.record.position_rank,
      cell: (context) => (
        <span className="muted">
          {context.row.original.record.position}
          {formatRank(context.row.original.record.position_rank)}
        </span>
      ),
      meta: { align: "right", width: "4rem" },
    },
    {
      id: "team",
      header: "Team",
      accessorFn: (row) => row.record.team ?? "",
      cell: (context) => <span className="muted">{context.row.original.record.team ?? "—"}</span>,
      meta: { width: "3.5rem" },
    },
    {
      id: "tier",
      header: "Tier",
      accessorFn: (row) => row.record.tier_ordinal,
      cell: (context) => <TierTag label={context.row.original.record.tier_label} />,
      meta: { width: "4rem" },
    },
    {
      id: "expected_vorp",
      header: "Exp VORP",
      accessorFn: (row) => row.record.expected_vorp,
      cell: (context) => formatValue(context.row.original.record.expected_vorp),
      meta: { align: "right", width: "5.5rem" },
    },
    {
      id: "p50_vorp",
      header: "Median VORP",
      accessorFn: (row) => row.record.p50_vorp,
      cell: (context) => formatValue(context.row.original.record.p50_vorp),
      meta: { align: "right", width: "6.5rem" },
    },
    {
      id: "interquartile",
      header: "P25–P75 VORP",
      accessorFn: (row) => row.record.p75_vorp - row.record.p25_vorp,
      cell: (context) => (
        <span className="muted">
          {formatRange(context.row.original.record.p25_vorp, context.row.original.record.p75_vorp)}
        </span>
      ),
      meta: { align: "right", width: "8.5rem" },
    },
    {
      id: "expected_points",
      header: "Exp FP",
      accessorFn: (row) => row.record.expected_points,
      cell: (context) => formatValue(context.row.original.record.expected_points),
      meta: { align: "right", width: "5rem" },
    },
    {
      id: "uncertainty",
      header: "Uncertainty",
      accessorFn: (row) => row.record.uncertainty,
      cell: (context) => (
        <span className="muted">{formatValue(context.row.original.record.uncertainty)}</span>
      ),
      meta: { align: "right", width: "6rem" },
    },
  ];
}

interface ColumnMeta {
  readonly align?: "right";
  readonly className?: string;
  readonly width?: string;
}

export function TierTable({
  rows,
  onSelect,
  selectedPlayerId,
  visibleRowsRef,
}: {
  readonly rows: readonly TierRow[];
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  /**
   * The visible order, mirrored into a ref so the filtered export writes exactly what is on
   * screen. A ref rather than a state callback: the export needs the rows at click time, and
   * pushing an array up into parent state on every render would loop.
   */
  readonly visibleRowsRef?: RefObject<readonly TierRow[]>;
}): React.JSX.Element {
  const [sorting, setSorting] = useState<SortingState>([{ id: "fair_rank", desc: false }]);
  const columns = useMemo(() => tierColumns(onSelect), [onSelect]);
  const data = useMemo(() => [...rows], [rows]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    // Fair rank is unique, so an unstable secondary order cannot appear; ties elsewhere fall
    // back to the incoming fair-rank order, which is deterministic.
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
          {TIER_TABLE_CAPTION} {`Showing ${String(rows.length)} player${rows.length === 1 ? "" : "s"}.`}
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
            >
              {row.getVisibleCells().map((cell) => {
                const meta = (cell.column.columnDef.meta ?? {}) as ColumnMeta;
                return (
                  <td
                    key={cell.id}
                    className={[meta.align === "right" ? "num" : "", meta.className ?? ""]
                      .filter(Boolean)
                      .join(" ")}
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
