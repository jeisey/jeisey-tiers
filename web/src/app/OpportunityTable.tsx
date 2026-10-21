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
import { useEffect, useMemo, useState, type ReactNode, type RefObject } from "react";

import { RosStatusBadge, TeamCell } from "../components/primitives";
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
import {
  describeNet,
  describeSide,
  formatNet,
  netAdds,
  netSortValue,
  sideOf,
  type BehaviorSide,
} from "../data/behavior";
import type { OpportunityRecord } from "../data/contracts";
import { compareRostered, espnCell } from "../data/espn";
import { formatRank, formatValue } from "../data/format";
import { longAbsenceLabel, rosValue } from "../data/ros";
import { BreakoutBadge, RecentHeader, recentColumns } from "./RecentColumns";
import { positionalRankAccessor, seasonColumns } from "./SeasonColumns";

/**
 * The table's caption: what it is and how many rows it shows. What each column means is on the
 * Data tab under "Reading the boards" (ADR-115).
 */
export const OPPORTUNITY_TABLE_CAPTION = "In-season opportunity board.";

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
    widestValue = Math.max(widestValue, Math.abs(rosValue(record)));
    widestCount = Math.max(widestCount, sideOf(record, "add").count ?? 0, sideOf(record, "drop").count ?? 0);
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

/** `+13.0`, `−0.4`, `±0.0`: percentage points in a cell whose caption names the unit. */
function signedPoints(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "±0.0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)}`;
}

/**
 * A count, or a dash that says why there is none (ADR-114). Outside a feed's top 100 is the
 * ordinary state for most rows, so it is a quiet dash with its bound in the label rather than
 * a `≤ N` repeated down the board.
 */
function countCell(record: OpportunityRecord, side: BehaviorSide): ReactNode {
  const reading = sideOf(record, side);
  if (reading.count !== null) return String(reading.count);
  const label = describeSide(reading, side);
  return (
    <span className="count-absent" data-state={reading.state} title={label}>
      <span aria-hidden="true">—</span>
      <span className="visually-hidden">{label}</span>
    </span>
  );
}

/** An exact net as the column has always printed it: `+1430`, `-12`, `0`. */
function signedCount(value: number): string {
  return value > 0 ? `+${String(value)}` : String(value);
}

/** Observed counts first; a player outside the feed sorts just below its floor; then unknowns. */
function countSortValue(record: OpportunityRecord, side: BehaviorSide): number {
  const reading = sideOf(record, side);
  if (reading.count !== null) return reading.count;
  if (reading.max !== null) return reading.max - 0.5;
  return -1;
}

/** The recent lens a table renders (ADR-113): null in the Season lens or without the artifact. */
export interface RecentColumnsSpec {
  /** `W3–5`: the selected window's real weeks, printed under both headings. */
  readonly spanLabel: string;
  readonly onExplain: (playerId: string) => void;
}

function opportunityColumns(
  onSelect: (playerId: string) => void,
  scale: Scale,
  windowSuffix: string,
  roleOrdering: RoleOrdering,
  recent: RecentColumnsSpec | null,
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
            <RosStatusBadge status={record.current_status} playerId={record.player_id} />
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
            {recent !== null && (
              <BreakoutBadge
                standing={context.row.original.recent}
                playerId={record.player_id}
                onExplain={recent.onExplain}
              />
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
        positionalRankAccessor(row.row.record.position, row.row.record.ros_position_rank),
      sortDescFirst: false,
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
    // ADR-105: the season-to-date cluster, Szn rank immediately beside ROS PosRk.
    // Below 1280px the two totals step aside with the team and drops (the card and the CSV
    // carry them); Szn rank stays beside ROS PosRk at every width.
    ...seasonColumns<OpportunityCandidate>(
      (row) => row.season,
      (row) => row.row.record.position,
      (row) => row.row.record.ros_position_rank,
      // The two totals step aside below 1440px too: the ESPN column needs their room, and the
      // card and both exports carry them (ADR-112).
      "col-mid col-wide",
    ),
    // ADR-113: the selected recent window beside the season cluster, only when one is chosen.
    ...(recent === null
      ? []
      : recentColumns<OpportunityCandidate>(
          (row) => row.recent,
          (row) => row.season,
          (row) => row.row.record.position,
          (row) => row.row.record.player_id,
          recent.onExplain,
        )),
    {
      id: "team",
      header: "Team",
      accessorFn: (row) => row.row.record.team ?? "",
      cell: (context) => (
        <TeamCell
          team={context.row.original.row.record.team}
          playerId={context.row.original.row.record.player_id}
        />
      ),
      meta: { width: "3.5rem", className: "col-mid" },
    },
    {
      // The median the rank orders by, and the number the rest-of-season board draws; the mean
      // stays in the export (ADR-097).
      id: "ros_vorp_p50",
      header: "ROS Med VORP",
      accessorFn: (row) => rosValue(row.row.record),
      cell: (context) => formatValue(rosValue(context.row.original.row.record)),
      meta: {
        align: "right",
        width: "5.5rem",
        // On a phone the chart above prints this value, with its bar, on every row it draws;
        // the table's narrow form leads with the readings the chart does not carry.
        className: "col-low",
        track: (row: OpportunityCandidate) =>
          barGradient(
            Math.abs(rosValue(row.row.record)) / scale.widestValue,
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
      accessorFn: (row) => countSortValue(row.row.record, "add"),
      cell: (context) => countCell(context.row.original.row.record, "add"),
      meta: {
        align: "right",
        // No bar at all when the feed said nothing: a zero-width bar and "nobody added him"
        // look identical, and only one of them is a reading.
        track: (row: OpportunityCandidate) =>
          row.row.record.add_count === null || row.row.record.add_count === undefined || sideOf(row.row.record, "add").count === null
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
      accessorFn: (row) => countSortValue(row.row.record, "drop"),
      cell: (context) => countCell(context.row.original.row.record, "drop"),
      meta: {
        align: "right",
        className: "col-mid",
        track: (row: OpportunityCandidate) =>
          row.row.record.drop_count === null || row.row.record.drop_count === undefined || sideOf(row.row.record, "drop").count === null
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
      // ADR-114: exact only with both sides observed; a one-sided net prints and sorts as the
      // bound it is (`≥ +531,586`), and a row with neither sorts last.
      accessorFn: (row) => netSortValue(netAdds(row.row.record)) ?? Number.NEGATIVE_INFINITY,
      cell: (context) => {
        const record = context.row.original.row.record;
        const net = netAdds(record);
        const change =
          net.kind === "exact"
            ? net.value > 0
              ? "up"
              : net.value < 0
                ? "down"
                : "flat"
            : net.kind === "bounded"
              ? net.min > 0
                ? "up"
                : net.max < 0
                  ? "down"
                  : "none"
              : "none";
        const text = formatNet(net);
        return (
          <span data-change={change} data-net={net.kind} title={net.kind === "exact" ? undefined : describeNet(record)}>
            <span aria-hidden={net.kind !== "exact"}>{net.kind === "exact" ? signedCount(net.value) : text}</span>
            {net.kind !== "exact" && <span className="visually-hidden">{describeNet(record)}</span>}
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
        ESPN's public roster share (ADR-112): rostered %, its 7-day change in percentage points,
        and underneath the start share and the 1-day change. ESPN leagues, not the reader's, and
        crowd interest, not value — printed beside the Sleeper counts and never combined with
        them. Sorted by rostered %, and a row with no current reading sorts last in both
        directions: "not listed by ESPN" is an unknown, never 0%.
      */
      id: "espn",
      header: "ESPN rost",
      accessorFn: (row) => (row.espn.kind === "observed" ? row.espn.rostered : undefined),
      sortingFn: (a, b) => compareRostered(b.original.espn, a.original.espn),
      sortUndefined: "last",
      sortDescFirst: true,
      cell: (context) => {
        const candidate = context.row.original;
        const cell = espnCell(candidate.espn);
        const reading = candidate.espn.kind === "observed" || candidate.espn.kind === "stale" ? candidate.espn : null;
        const week = reading?.record.rostered_change_7d ?? null;
        const day = reading?.record.rostered_change_1d ?? null;
        const measured = (change: typeof week): number | null =>
          change?.state === "measured" ? change.change_pp : null;
        const week7 = measured(week);
        const day1 = measured(day);
        const direction = week7 === null ? "none" : week7 > 0 ? "up" : week7 < 0 ? "down" : "flat";
        /*
          Compact on purpose: the share, then `7d +13.0` (points; the caption says so), and
          underneath ESPN's start share and the 1-day change. A change the rule withholds is
          left out of the cell and named in its sentence, so no long phrase widens the column.
        */
        return (
          <span
            className="signal-cell"
            data-signal="espn"
            data-kind={candidate.espn.kind}
            data-direction={direction}
            data-current={cell.current ? "true" : "false"}
            title={cell.sentence}
          >
            <span className="signal-line" aria-hidden="true">
              <span className="signal-value">{cell.rostered}</span>
              {week7 !== null && <span className="signal-change">{`7d ${signedPoints(week7)}`}</span>}
            </span>
            {reading !== null && (
              <span className="signal-detail" aria-hidden="true">
                {/* A no-break space keeps "1d" with its figure when a narrow column wraps. */}
                {`st\u00a0${cell.started}`}
                {day1 === null ? "" : ` · 1d\u00a0${signedPoints(day1)}`}
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
  /** ADR-113: the recent column's heading holds two sort buttons of its own. */
  readonly recentHeader?: boolean;
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
  seasonNote,
  recent = null,
  recentNote,
}: {
  readonly rows: readonly OpportunityCandidate[];
  /** The declared window, e.g. ` (24h)`, appended to the two count headings. */
  readonly windowSuffix: string;
  /** Whether a role sort may compare magnitudes: only when every row shown is one position. */
  readonly roleOrdering: RoleOrdering;
  readonly onSelect: (playerId: string) => void;
  readonly selectedPlayerId: string | null;
  readonly visibleRowsRef?: RefObject<readonly OpportunityCandidate[]>;
  /** What the season columns are, for the caption (ADR-105). */
  readonly seasonNote?: string;
  /** The recent window's columns (ADR-113); null in the Season lens. */
  readonly recent?: RecentColumnsSpec | null;
  /** What the recent columns are, for the caption. */
  readonly recentNote?: string;
}): React.JSX.Element {
  const [sorting, setSorting] = useState<SortingState>([]);
  const scale = useMemo(() => opportunityTableScale(rows), [rows]);
  const columns = useMemo(
    () => opportunityColumns(onSelect, scale, windowSuffix, roleOrdering, recent),
    [onSelect, scale, windowSuffix, roleOrdering, recent],
  );
  const data = useMemo(() => [...rows], [rows]);

  // A sort on a recent column ends with the window: switching to Season drops it rather than
  // leaving the table ordered by a column it no longer has.
  const activeSorting = useMemo(
    () => sorting.filter((sort) => columns.some((column) => column.id === sort.id)),
    [sorting, columns],
  );

  const table = useReactTable({
    data,
    columns,
    // The gap column is sorted through the recent heading and never drawn (ADR-113).
    state: { sorting: activeSorting, columnVisibility: { recent_vs_season: false } },
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
      <table className="sheet opp-sheet" data-recent={recent === null ? undefined : "on"}>
        <caption>
          {OPPORTUNITY_TABLE_CAPTION}{" "}
          {seasonNote === undefined ? "" : `${seasonNote} `}
          {recentNote === undefined ? "" : `${recentNote} `}
          {`Showing ${String(rows.length)} player${rows.length === 1 ? "" : "s"}.`}
        </caption>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const meta = (header.column.columnDef.meta ?? {}) as ColumnMeta;
                if (meta.recentHeader === true && recent !== null) {
                  const gapColumn = table.getColumn("recent_vs_season");
                  const handle = (column: typeof gapColumn) => ({
                    sorted: column?.getIsSorted() ?? false,
                    toggle: () => {
                      column?.toggleSorting();
                    },
                  });
                  const rank = handle(header.column);
                  const gap = handle(gapColumn);
                  const active = rank.sorted !== false ? rank.sorted : gap.sorted;
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      className={meta.className}
                      data-col={header.id}
                      style={{ textAlign: "right" }}
                      aria-sort={active === "asc" ? "ascending" : active === "desc" ? "descending" : "none"}
                    >
                      <RecentHeader spanLabel={recent.spanLabel} rank={rank} gap={gap} />
                    </th>
                  );
                }
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
