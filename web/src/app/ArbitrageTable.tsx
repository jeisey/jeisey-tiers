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
import {
  CROSS_MARKET,
  adpFor,
  comparisonFor,
  disagreementFor,
  gapFor,
  marketLabel,
} from "../data/multimarket";
import type { ArbitrageRow } from "../data/model";

export const ARBITRAGE_TABLE_CAPTION =
  "Deterministic market-gap board: the model's fair rank compared with the selected ADP " +
  "market. Columns appear only for the markets this build actually published. " +
  "Confidence describes how much draft evidence stands behind the price, not how likely the " +
  "player is to be a bargain.";

interface ColumnMeta {
  readonly align?: "right";
  readonly className?: string;
  readonly width?: string;
}

/**
 * Which optional market columns this build has any data for.
 *
 * A column of nothing but em dashes is a promise the artifact cannot keep. It shipped once —
 * FP ECR and Spread rendered `\u2014` on every row of the live board for a source the pipeline
 * never captured — and the lesson is not "remember to check": it is that presence should be
 * read from the data rather than remembered. A column whose every row is empty is not
 * rendered at all, so a market that is absent, stale or newly added is handled the same way
 * without anyone editing this file.
 */
/**
 * Columns that may legitimately be absent, because the *source* behind them may be.
 *
 * Trend is deliberately not here. Its empty state is specified rather than accidental — a
 * null trend must read as an em dash and never as `0`, because an absence of evidence is not
 * evidence of no change (ADR-042) — and `verify-real-build.mjs` checks that cell on every
 * build. A column with a defined meaning when empty is not the same thing as a column for a
 * market the build never captured.
 */
const OPTIONAL_COLUMNS: ReadonlySet<string> = new Set(["adp_range", "market_spread"]);

function populatedColumns(rows: readonly ArbitrageRow[], market: string): ReadonlySet<string> {
  const present = new Set<string>();
  for (const { record } of rows) {
    const comparison = comparisonFor(record, market);
    const sd = comparison?.market_adp_sd ?? null;
    const low = comparison?.market_adp_low ?? record.market_adp_low;
    const high = comparison?.market_adp_high ?? record.market_adp_high;
    if (sd !== null || (low !== null && high !== null)) present.add("adp_range");
    if (disagreementFor(record) !== null) present.add("market_spread");
    if (present.size === OPTIONAL_COLUMNS.size) break;
  }
  return present;
}

function arbitrageColumns(
  onSelect: (playerId: string) => void,
  market: string,
  populated: ReadonlySet<string>,
): ColumnDef<ArbitrageRow>[] {
  const defined: ColumnDef<ArbitrageRow>[] = [
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
      // The header names the source, because the number changes with the selector and a
      // column called "ADP" would leave a reader unable to say which market they are reading.
      header: market === CROSS_MARKET ? "Median ADP" : `${marketLabel(market)} ADP`,
      accessorFn: (row) => adpFor(row.record, market) ?? Number.POSITIVE_INFINITY,
      cell: (context) => {
        const value = adpFor(context.row.original.record, market);
        return value === null ? <span className="faint">{EM_DASH}</span> : formatAdp(value);
      },
      meta: { align: "right", width: "6rem" },
    },
    {
      id: "adp_range",
      // Dispersion, whichever kind this source publishes. FFC has a genuine standard
      // deviation; MyFantasyLeague has two extreme order statistics. They are shown
      // differently and labelled differently, because they are different quantities and
      // presenting them under one heading would invite a comparison that means nothing.
      header: "Dispersion",
      enableSorting: false,
      cell: (context) => {
        const record = context.row.original.record;
        const comparison = comparisonFor(record, market);
        const sd = comparison?.market_adp_sd ?? null;
        if (sd !== null) {
          return (
            <span className="muted">
              <span aria-hidden="true">{`\u00b1${sd.toFixed(1)}`}</span>
              <span className="visually-hidden">{`standard deviation ${sd.toFixed(1)} picks`}</span>
            </span>
          );
        }
        const low = comparison?.market_adp_low ?? record.market_adp_low;
        const high = comparison?.market_adp_high ?? record.market_adp_high;
        if (low === null || high === null) {
          return <span className="faint">{EM_DASH}</span>;
        }
        return (
          <span className="muted">
            <span aria-hidden="true">{`${formatAdp(low)}\u2013${formatAdp(high)}`}</span>
            <span className="visually-hidden">
              {`observed range ${formatAdp(low)} to ${formatAdp(high)}`}
            </span>
          </span>
        );
      },
      meta: { align: "right", width: "6.5rem" },
    },
    {
      id: "rank_gap",
      header: "Value Gap",
      accessorFn: (row) => gapFor(row.record, market) ?? Number.NEGATIVE_INFINITY,
      cell: (context) => {
        const value = gapFor(context.row.original.record, market);
        if (value === null) return <span className="faint">{EM_DASH}</span>;
        const gap = describeGap(value);
        return (
          <span className="dir" data-kind={gap.kind}>
            <span aria-hidden="true">{formatSigned(value)}</span>
            <span className="visually-hidden">{gap.sentence}</span>
          </span>
        );
      },
      meta: { align: "right", width: "5.5rem" },
    },
    {
      id: "market_spread",
      // The number a single-source board could not produce. Null - not zero - when only one
      // market priced him: zero would claim the markets agree when only one of them spoke.
      header: "Spread",
      accessorFn: (row) => disagreementFor(row.record) ?? Number.NEGATIVE_INFINITY,
      cell: (context) => {
        const spread = disagreementFor(context.row.original.record);
        if (spread === null) return <span className="faint">{EM_DASH}</span>;
        return (
          <span className="muted">
            <span aria-hidden="true">{spread.toFixed(1)}</span>
            <span className="visually-hidden">
              {`${spread.toFixed(1)} picks between the earliest and latest market`}
            </span>
          </span>
        );
      },
      meta: { align: "right", width: "5rem" },
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
  return defined.filter(
    (column) =>
      !OPTIONAL_COLUMNS.has(String(column.id)) || populated.has(String(column.id)),
  );
}

export function ArbitrageTable({
  rows,
  onSelect,
  selectedPlayerId,
  visibleRowsRef,
  market = CROSS_MARKET,
}: {
  readonly rows: readonly ArbitrageRow[];
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly visibleRowsRef?: RefObject<readonly ArbitrageRow[]>;
  /** Which ADP market the price and gap columns read. Defaults to the cross-market view. */
  readonly market?: string;
}): React.JSX.Element {
  const [sorting, setSorting] = useState<SortingState>([{ id: "arbitrage_score", desc: true }]);
  const populated = useMemo(() => populatedColumns(rows, market), [rows, market]);
  const columns = useMemo(
    () => arbitrageColumns(onSelect, market, populated),
    [onSelect, market, populated],
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
