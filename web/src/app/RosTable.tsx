/**
 * The rest-of-season table: the canonical form of the in-season board.
 *
 * The same truth surface the Tier table is, over a different quantity, and the column names
 * say so on every line. **`ROS Rank` is never `Rank`.** A rest-of-season fair rank comes from
 * a different model, over the weeks that are left, against a different replacement baseline —
 * the best player nobody *rosters* rather than the best nobody starts (ADR-071). A reader who
 * saw a bare "Rank" here would reasonably read it as the draft one, and the two are not
 * comparable.
 *
 * Two disclosures are structural rather than decorative:
 *
 * **Long absence is a fact about appearances, never a status** (ADR-076). The badge says
 * "Has not appeared for N weeks", carries a text label as well as a shape, and sits in its own
 * column beside `weeks_since_last_game` so the claim is checkable. It is never rendered by
 * colour alone, and it is never worded as a designation the model has no information about.
 *
 * **The current status column is annotation.** It is separated from every model-derived column
 * by a rule and labelled as such: nothing in it reached the model.
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

import { PositionTag, TierTag } from "../components/primitives";
import { formatRange, formatRank, formatValue } from "../data/format";
import { longAbsenceLabel, rankChangeLabel, type RosRow } from "../data/ros";

export const ROS_TABLE_CAPTION =
  "Rest-of-season board. Every column is a rest-of-season quantity computed at the cutoff " +
  "week shown above — none of them is the preseason value of the same name. Sorting " +
  "re-orders these rows without changing the published ROS rank.";

interface Scale {
  readonly min: number;
  readonly range: number;
  readonly widestUncertainty: number;
}

function pct(value: number, scale: Scale): number {
  if (scale.range <= 0) return 0;
  return Math.max(0, Math.min(100, ((value - scale.min) / scale.range) * 100));
}

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

export function rosTableScale(rows: readonly RosRow[]): Scale {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  let widestUncertainty = 0;
  for (const { record } of rows) {
    min = Math.min(min, record.ros_vorp_p25);
    max = Math.max(max, record.ros_vorp_p75);
    widestUncertainty = Math.max(widestUncertainty, record.ros_uncertainty);
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { min: 0, range: 1, widestUncertainty: 1 };
  }
  return { min, range: max - min || 1, widestUncertainty };
}

/**
 * The long-absence badge.
 *
 * Text first, then a shape, then — last and never alone — a colour. `AGENTS.md` section 11
 * forbids meaning carried by colour alone, and this is the flag where getting that wrong
 * would matter most: a reader who cannot see the colour must still get the whole message,
 * and the whole message is a sentence about appearances.
 */
export function LongAbsenceBadge({ row }: { readonly row: RosRow }): React.JSX.Element | null {
  if (!row.record.long_absence) return null;
  const label = longAbsenceLabel(row.record);
  return (
    <span className="absence-badge" data-flag="long-absence" title={label}>
      <span aria-hidden="true">◷</span>
      <span className="absence-weeks">{`${String(Math.round(row.record.weeks_since_last_game))}w`}</span>
      <span className="visually-hidden">{`${label}. No injury or practice-report information is used.`}</span>
    </span>
  );
}

function rosColumns(onSelect: (playerId: string) => void, scale: Scale): ColumnDef<RosRow>[] {
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
            <LongAbsenceBadge row={row} />
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
      id: "ros_tier",
      header: "ROS Tier",
      accessorFn: (row) => row.record.ros_tier ?? Number.MAX_SAFE_INTEGER,
      cell: (context) => {
        const label = context.row.original.record.ros_tier_label;
        return label === null ? <span className="muted">—</span> : <TierTag label={label} />;
      },
      meta: { width: "5rem" },
    },
    {
      id: "ros_expected_vorp",
      header: "ROS Exp VORP",
      accessorFn: (row) => row.record.ros_expected_vorp,
      cell: (context) => formatValue(context.row.original.record.ros_expected_vorp),
      meta: { align: "right", width: "7rem" },
    },
    {
      id: "ros_interval",
      header: "ROS P25–P75",
      accessorFn: (row) => row.record.ros_vorp_p75 - row.record.ros_vorp_p25,
      cell: (context) => (
        <span className="muted">
          {formatRange(
            context.row.original.record.ros_vorp_p25,
            context.row.original.record.ros_vorp_p75,
          )}
        </span>
      ),
      meta: {
        align: "right",
        width: "8.5rem",
        track: (row: RosRow) =>
          intervalGradient(
            row.record.ros_vorp_p25,
            row.record.ros_vorp_p50,
            row.record.ros_vorp_p75,
            scale,
          ),
      },
    },
    {
      id: "ros_expected_points",
      header: "Rem FP",
      accessorFn: (row) => row.record.ros_expected_points,
      cell: (context) => formatValue(context.row.original.record.ros_expected_points),
      meta: { align: "right", width: "5.5rem" },
    },
    {
      id: "ros_expected_games",
      header: "Rem G",
      accessorFn: (row) => row.record.ros_expected_games,
      cell: (context) => (
        <span className="muted">
          {context.row.original.record.ros_expected_games.toFixed(1)}
        </span>
      ),
      meta: { align: "right", width: "4.5rem" },
    },
    {
      id: "ros_uncertainty",
      header: "Uncertainty",
      accessorFn: (row) => row.record.ros_uncertainty,
      cell: (context) => (
        <span className="muted">{formatValue(context.row.original.record.ros_uncertainty)}</span>
      ),
      meta: {
        align: "right",
        width: "6.5rem",
        track: (row: RosRow) =>
          uncertaintyGradient(row.record.ros_uncertainty, scale.widestUncertainty),
      },
    },
    {
      id: "fair_rank_change",
      header: "Δ vs preseason",
      accessorFn: (row) => row.record.fair_rank_change ?? 0,
      cell: (context) => {
        const change = context.row.original.record.fair_rank_change;
        return (
          <span className="muted" data-change={change === null || change === undefined ? "none" : change > 0 ? "up" : change < 0 ? "down" : "flat"}>
            {rankChangeLabel(change)}
          </span>
        );
      },
      meta: { align: "right", width: "7rem" },
    },
    {
      id: "weeks_since_last_game",
      header: "Weeks since last game",
      accessorFn: (row) => row.record.weeks_since_last_game,
      cell: (context) => {
        const record = context.row.original.record;
        if (!record.has_played_this_season) {
          return <span className="muted">No appearances</span>;
        }
        const weeks = Math.round(record.weeks_since_last_game);
        return <span className="muted">{weeks === 0 ? "Played latest week" : String(weeks)}</span>;
      },
      meta: { align: "right", width: "9rem" },
    },
    {
      id: "current_status",
      header: "Current status",
      accessorFn: (row) => row.record.current_status ?? "",
      cell: (context) => (
        <span className="muted annotation-cell">
          {context.row.original.record.current_status ?? "—"}
        </span>
      ),
      meta: { width: "7rem", className: "col-annotation" },
    },
  ];
}

interface ColumnMeta {
  readonly align?: "right";
  readonly className?: string;
  readonly width?: string;
  readonly track?: (row: RosRow) => string;
}

export function RosTable({
  rows,
  onSelect,
  selectedPlayerId,
  visibleRowsRef,
}: {
  readonly rows: readonly RosRow[];
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly visibleRowsRef?: RefObject<readonly RosRow[]>;
}): React.JSX.Element {
  const [sorting, setSorting] = useState<SortingState>([{ id: "ros_fair_rank", desc: false }]);
  const scale = useMemo(() => rosTableScale(rows), [rows]);
  const columns = useMemo(() => rosColumns(onSelect, scale), [onSelect, scale]);
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
          {ROS_TABLE_CAPTION}{" "}
          {`Showing ${String(rows.length)} player${rows.length === 1 ? "" : "s"}. `}
          Interval and uncertainty bars are scaled against the widest on the rows shown.
          &ldquo;Current status&rdquo; is annotation: no value in it reached the model.
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
