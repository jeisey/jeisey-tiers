/**
 * The Arbitrage table.
 *
 * Default sort is `arbitrage_score` descending, which is the published ordering.
 *
 * Two columns the UX spec lists are deliberately **absent**: expected surplus VORP and
 * P(positive surplus). V1 is a deterministic baseline and those fields are null on every row;
 * a header with 238 empty cells under it implies a quantity that was measured and lost rather
 * than one that was never claimed (ADR-010, and the spec's own "omit or explain, do not
 * fabricate" rule).
 *
 * `confidence` is market-data quality. It is not a probability, not model confidence, and not
 * a claim about the player (ADR-041) — the column header says so and the view above explains
 * the shared reason once rather than putting an unexplained pill on every row.
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

import { ConfidenceMeter, PositionTag, StatusBadge } from "../components/primitives";
import { EM_DASH, formatAdp, formatRank, formatScore, formatSigned } from "../data/format";
import { CONFIDENCE_SHORT, describeGap, describeTrend } from "../data/market";
import type { ArbitrageRow } from "../data/model";

export const ARBITRAGE_TABLE_CAPTION =
  "Deterministic market-gap board: the model's fair rank compared with MyFantasyLeague ADP. " +
  "Confidence describes how much draft evidence stands behind the price, not how likely the " +
  "player is to be a bargain.";

interface ColumnMeta {
  readonly align?: "right";
  readonly className?: string;
  readonly width?: string;
}

function arbitrageColumns(onSelect: (playerId: string) => void): ColumnDef<ArbitrageRow>[] {
  return [
    {
      id: "arbitrage_rank",
      header: "#",
      accessorFn: (row) => row.arbitrageRank,
      cell: (context) => <span className="muted">{formatRank(context.row.original.arbitrageRank)}</span>,
      meta: { align: "right", width: "3rem" },
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
      id: "team",
      header: "Team",
      accessorFn: (row) => row.record.team ?? "",
      cell: (context) => <span className="muted">{context.row.original.record.team ?? EM_DASH}</span>,
      meta: { width: "3.5rem" },
    },
    {
      id: "fair_rank",
      header: "Fair Rank",
      accessorFn: (row) => row.record.fair_rank,
      cell: (context) => formatRank(context.row.original.record.fair_rank),
      meta: { align: "right", width: "5rem" },
    },
    {
      id: "market_adp",
      header: "MFL ADP",
      accessorFn: (row) => row.record.market_adp,
      cell: (context) => formatAdp(context.row.original.record.market_adp),
      meta: { align: "right", width: "5rem" },
    },
    {
      id: "adp_range",
      header: "ADP Low–High",
      enableSorting: false,
      cell: (context) => {
        const record = context.row.original.record;
        if (record.market_adp_low === null || record.market_adp_high === null) {
          return <span className="faint">{EM_DASH}</span>;
        }
        return (
          <span className="muted">
            {`${formatAdp(record.market_adp_low)}–${formatAdp(record.market_adp_high)}`}
          </span>
        );
      },
      meta: { align: "right", width: "6.5rem" },
    },
    {
      id: "rank_gap",
      header: "Value Gap",
      accessorFn: (row) => row.record.rank_gap,
      cell: (context) => {
        const record = context.row.original.record;
        const gap = describeGap(record.rank_gap);
        return (
          <span className="dir" data-kind={gap.kind}>
            <span aria-hidden="true">{formatSigned(record.rank_gap)}</span>
            <span className="visually-hidden">{gap.sentence}</span>
          </span>
        );
      },
      meta: { align: "right", width: "5.5rem" },
    },
    {
      id: "arbitrage_score",
      header: "Score",
      accessorFn: (row) => row.record.arbitrage_score,
      cell: (context) => formatScore(context.row.original.record.arbitrage_score),
      meta: { align: "right", width: "4.5rem" },
    },
    {
      id: "market_trend",
      header: "Trend",
      accessorFn: (row) => row.record.market_trend ?? Number.NEGATIVE_INFINITY,
      cell: (context) => {
        const trend = context.row.original.record.market_trend;
        const described = describeTrend(trend);
        if (trend === null) {
          // Never `0`, never "Flat": an absence of evidence must not be dressed as evidence of
          // no change (ADR-042).
          return (
            <>
              <span className="faint" aria-hidden="true">
                {EM_DASH}
              </span>
              <span className="visually-hidden">Trend collecting — not enough observation days yet</span>
            </>
          );
        }
        return (
          <span className="dir" data-kind={described.direction === "earlier" ? "premium" : "bargain"}>
            <span aria-hidden="true">
              {described.direction === "earlier" ? "↑" : described.direction === "later" ? "↓" : ""}
              {formatSigned(trend, 2)}
            </span>
            <span className="visually-hidden">{described.text}</span>
          </span>
        );
      },
      meta: { align: "right", width: "5.5rem" },
    },
    {
      id: "confidence",
      header: "Market data",
      accessorFn: (row) => row.record.confidence,
      cell: (context) => {
        const record = context.row.original.record;
        return (
          <>
            <span className="muted" aria-hidden="true">
              <ConfidenceMeter
                confidence={record.confidence}
                label={CONFIDENCE_SHORT[record.confidence]}
              />
            </span>
            <span className="visually-hidden">
              {`${CONFIDENCE_SHORT[record.confidence]} market-data quality — how much draft evidence stands behind this price`}
            </span>
          </>
        );
      },
      meta: { width: "6rem" },
    },
  ];
}

export function ArbitrageTable({
  rows,
  onSelect,
  selectedPlayerId,
  visibleRowsRef,
}: {
  readonly rows: readonly ArbitrageRow[];
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly visibleRowsRef?: RefObject<readonly ArbitrageRow[]>;
}): React.JSX.Element {
  const [sorting, setSorting] = useState<SortingState>([{ id: "arbitrage_score", desc: true }]);
  const columns = useMemo(() => arbitrageColumns(onSelect), [onSelect]);
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
          {ARBITRAGE_TABLE_CAPTION}{" "}
          {`Showing ${String(rows.length)} priced player${rows.length === 1 ? "" : "s"}.`}
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
                    className={sortable ? meta.className : `plain ${meta.className ?? ""}`}
                    style={{ width: meta.width, textAlign: meta.align }}
                    aria-sort={
                      sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
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
