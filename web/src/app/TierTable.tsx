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

/**
 * The two micro-glyphs the design source puts in its table cells, drawn as a background
 * gradient **on the cell itself**.
 *
 * The first draft nested two spans per glyph, which is 1,200 extra nodes on a 300-row board —
 * measured, and exactly the cost AGENTS.md and the Phase-9A brief say a decorative motif may
 * not impose. A gradient on the `<td>` renders identically and adds nothing to the DOM: the
 * cell's own text is the accessible content, and the bar is a second channel for the number
 * printed above it.
 *
 * Because the bar lives in `background-image`, every rule that paints a cell has to set
 * `background-color` rather than the `background` shorthand, which would reset it. The
 * stylesheet says so where those rules are.
 */
function intervalGradient(p25: number, p50: number, p75: number, scale: Scale): string {
  const track = "rgb(46 204 255 / 10%)";
  const band = "rgb(46 204 255 / 40%)";
  const median = "var(--accent-bright)";
  const a = pct(p25, scale);
  const b = Math.max(pct(p75, scale), a + 0.5);
  const m = Math.min(Math.max(pct(p50, scale), a), b);
  const m0 = Math.max(a, m - 0.9);
  const m1 = Math.min(b, m + 0.9);
  return (
    `linear-gradient(90deg, ${track} 0 ${String(a)}%, ${band} ${String(a)}% ${String(m0)}%, ` +
    `${median} ${String(m0)}% ${String(m1)}%, ${band} ${String(m1)}% ${String(b)}%, ` +
    `${track} ${String(b)}% 100%)`
  );
}

function uncertaintyGradient(value: number, widest: number): string {
  const share = widest <= 0 ? 0 : Math.max(0, Math.min(100, (value / widest) * 100));
  return (
    `linear-gradient(90deg, rgb(255 179 71 / 55%) 0 ${String(share)}%, ` +
    `rgb(255 179 71 / 14%) ${String(share)}% 100%)`
  );
}

interface Scale {
  readonly min: number;
  readonly range: number;
  /** The widest `uncertainty` on the rows in scope; the amber bar's denominator. */
  readonly widestUncertainty: number;
}

function pct(value: number, scale: Scale): number {
  if (scale.range <= 0) return 0;
  return Math.max(0, Math.min(100, ((value - scale.min) / scale.range) * 100));
}

/**
 * The shared scale for the two glyphs, measured over the rows currently in scope.
 *
 * Deliberately not a fixed constant: a position-filtered board of tight ends would otherwise
 * draw every bar as a stub. The caption says what the scale is, which is what makes a relative
 * bar readable rather than misleading.
 */
export function tableScale(rows: readonly TierRow[]): Scale {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  let widestUncertainty = 0;
  for (const { record } of rows) {
    min = Math.min(min, record.p25_vorp);
    max = Math.max(max, record.p75_vorp);
    widestUncertainty = Math.max(widestUncertainty, record.uncertainty);
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { min: 0, range: 1, widestUncertainty: 1 };
  }
  return { min, range: max - min || 1, widestUncertainty };
}

function tierColumns(onSelect: (playerId: string) => void, scale: Scale): ColumnDef<TierRow>[] {
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
      meta: {
        align: "right",
        width: "8.5rem",
        track: (row: TierRow) =>
          intervalGradient(row.record.p25_vorp, row.record.p50_vorp, row.record.p75_vorp, scale),
      },
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
      meta: {
        align: "right",
        width: "6.5rem",
        track: (row: TierRow) =>
          uncertaintyGradient(row.record.uncertainty, scale.widestUncertainty),
      },
    },
  ];
}

interface ColumnMeta {
  readonly align?: "right";
  readonly className?: string;
  readonly width?: string;
  /** A micro-glyph painted as the cell's own background; see `intervalGradient`. */
  readonly track?: (row: TierRow) => string;
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
  const scale = useMemo(() => tableScale(rows), [rows]);
  const columns = useMemo(() => tierColumns(onSelect, scale), [onSelect, scale]);
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
          {TIER_TABLE_CAPTION}{" "}
          {`Showing ${String(rows.length)} player${rows.length === 1 ? "" : "s"}. `}
          {/* The design source's own caption for its relative bars, kept because a relative
              bar without its denominator is the thing that misleads. */}
          Interval and uncertainty bars are scaled against the widest on the rows shown — a long
          amber bar means the projection is thin, not that the player is bad.
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
