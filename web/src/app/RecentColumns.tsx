/**
 * The Opportunity Board's recent-window columns, badge and evidence dialog (ADR-113).
 *
 * `Recent` is the selected window's positional rank (with points per game and games under it)
 * and `vs Szn` is season rank minus that rank — two published orderings of points, compared
 * in places, beside the season and rest-of-season columns and never replacing them. The badge
 * sits on the name, so it stays beside the player on a phone where the name column is pinned;
 * it is a button, and the dialog it opens prints every number the category rests on.
 *
 * Nothing here ranks or classifies: every number is the record's (`data/recent`).
 */

import type { ColumnDef } from "@tanstack/react-table";
import { Fragment, memo } from "react";

import type { SeasonStanding } from "../data/actuals";
import { positionalSortKey } from "../data/actuals";
import type { Position } from "../data/contracts";
import {
  BREAKOUT_GLYPHS,
  BREAKOUT_LABELS,
  badgeAccessibleName,
  badgeOf,
  describeRecentVsSeason,
  formatPlaces,
  formatRecentRank,
  formatSpan,
  recentDetail,
  recentSentence,
  recentVsSeasonPlaces,
  type RecentStanding,
} from "../data/recent";

/** The breakout badge on a name: a button that opens the evidence. Nothing for no badge. */
export const BreakoutBadge = memo(function BreakoutBadge({
  standing,
  playerId,
  onExplain,
}: {
  readonly standing: RecentStanding | undefined;
  readonly playerId: string;
  readonly onExplain: (playerId: string) => void;
}): React.JSX.Element | null {
  const badge = badgeOf(standing);
  if (badge === null || standing === undefined || standing.kind === "unavailable") return null;
  return (
    <button
      type="button"
      className="breakout-badge"
      data-category={badge}
      aria-label={badgeAccessibleName(badge, standing.span)}
      aria-haspopup="dialog"
      onClick={() => {
        onExplain(playerId);
      }}
    >
      <span aria-hidden="true" className="breakout-glyph">
        {BREAKOUT_GLYPHS[badge]}
      </span>
      <span aria-hidden="true">{BREAKOUT_LABELS[badge]}</span>
    </button>
  );
});

/**
 * One cell for the window: the recent rank and, beside it, the signed gap to the season rank;
 * under them points per game and games. An `insufficient` verdict adds a button, because "not
 * enough evidence" deserves its reason as much as a badge does.
 */
const RecentCell = memo(function RecentCell({
  standing,
  season,
  playerId,
  onExplain,
}: {
  readonly standing: RecentStanding | undefined;
  readonly season: SeasonStanding | undefined;
  readonly playerId: string;
  readonly onExplain: (playerId: string) => void;
}): React.JSX.Element {
  const places = recentVsSeasonPlaces(season, standing);
  const span = standing === undefined || standing.kind === "unavailable" ? "the window" : formatSpan(standing.span);
  const sentence = `${recentSentence(standing)}. ${describeRecentVsSeason(places, span)}.`;
  const insufficient =
    standing !== undefined && standing.kind !== "unavailable" && standing.verdict.category === "insufficient";
  return (
    <span
      className="signal-cell recent-cell"
      data-signal="recent"
      data-kind={standing?.kind ?? "none"}
      data-direction={places === null ? "none" : places > 0 ? "up" : places < 0 ? "down" : "flat"}
      title={sentence}
    >
      <span className="signal-line" aria-hidden="true">
        <span className="signal-value">{formatRecentRank(standing)}</span>
        {places !== null && <span className="signal-change">{formatPlaces(places)}</span>}
      </span>
      <span className="signal-detail" aria-hidden="true">
        {recentDetail(standing)
          .split(" · ")
          .map((part, index) => (
            // The space sits between the spans, so the line can break there and nowhere else.
            <Fragment key={part}>
              {index === 0 ? "" : " "}
              <span>{index === 0 ? part : `· ${part}`}</span>
            </Fragment>
          ))}
      </span>
      <span className="visually-hidden">{sentence}</span>
      {insufficient && (
        <button
          type="button"
          className="breakout-insufficient"
          aria-haspopup="dialog"
          aria-label={`Breakout: insufficient evidence in ${span}. Show why`}
          onClick={() => {
            onExplain(playerId);
          }}
        >
          too little data
        </button>
      )}
    </span>
  );
});

/** What a recent header's two sort buttons need from the table, without depending on it. */
export interface SortHandle {
  readonly sorted: false | "asc" | "desc";
  readonly toggle: () => void;
}

/**
 * The window's heading: two sort buttons in one column — the recent rank (best first) and the
 * signed gap to the season rank (largest rise first) — around the window's real weeks. One
 * column rather than two because the laptop table has no room for two (ADR-113 measurements).
 */
export function RecentHeader({
  spanLabel,
  rank,
  gap,
}: {
  readonly spanLabel: string;
  readonly rank: SortHandle;
  readonly gap: SortHandle;
}): React.JSX.Element {
  const mark = (handle: SortHandle): React.JSX.Element => (
    <span className="sort-mark" data-state={handle.sorted === false ? "none" : handle.sorted}>
      {handle.sorted === "desc" ? "▼" : "▲"}
    </span>
  );
  return (
    <span className="recent-head">
      <span className="th-sub">{`Recent ${spanLabel}`}</span>
      <button type="button" data-sort="recent_rank" onClick={rank.toggle} aria-label={`Sort by recent rank in ${spanLabel}`}>
        Rank{mark(rank)}
      </button>
      <button type="button" data-sort="recent_vs_season" onClick={gap.toggle} aria-label={`Sort by recent rank versus season rank in ${spanLabel}`}>
        ±Szn{mark(gap)}
      </button>
    </span>
  );
}

/** The two sortable quantities, for a TanStack table whose rows carry both standings. */
export function recentColumns<Row>(
  recentOf: (row: Row) => RecentStanding | undefined,
  seasonOf: (row: Row) => SeasonStanding | undefined,
  positionOf: (row: Row) => Position,
  playerOf: (row: Row) => string,
  onExplain: (playerId: string) => void,
): ColumnDef<Row>[] {
  return [
    {
      id: "recent_rank",
      // Rendered by `RecentHeader`, which the table supplies (it owns the sort state).
      header: "Recent",
      accessorFn: (row) => {
        const standing = recentOf(row);
        return standing?.kind === "ranked" ? positionalSortKey(positionOf(row), standing.rank) : undefined;
      },
      sortUndefined: "last",
      sortDescFirst: false,
      cell: (context) => (
        <RecentCell
          standing={recentOf(context.row.original)}
          season={seasonOf(context.row.original)}
          playerId={playerOf(context.row.original)}
          onExplain={onExplain}
        />
      ),
      meta: { align: "right", className: "col-recent", recentHeader: true },
    },
    {
      // Never drawn: it exists so the gap sorts as one signed number across positions, largest
      // rise first and the steepest fall first on the second click, with blanks last.
      id: "recent_vs_season",
      header: "±Szn",
      accessorFn: (row) => recentVsSeasonPlaces(seasonOf(row), recentOf(row)) ?? undefined,
      sortUndefined: "last",
      sortDescFirst: true,
    },
  ];
}

