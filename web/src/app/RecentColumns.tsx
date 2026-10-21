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

import { Modal } from "../components/Modal";
import type { SeasonStanding } from "../data/actuals";
import { positionalSortKey } from "../data/actuals";
import type { Position, RecentFormMetadata } from "../data/contracts";
import {
  BREAKOUT_GLYPHS,
  BREAKOUT_LABELS,
  badgeAccessibleName,
  badgeOf,
  breakoutExplanation,
  categoryDefinition,
  describeRecentVsSeason,
  formatPlaces,
  formatPoints,
  formatRecentRank,
  formatSpan,
  recentDetail,
  recentSentence,
  recentVsSeasonPlaces,
  type RecentStanding,
} from "../data/recent";

/** The breakout badge on a name: a button that opens the evidence. Nothing for no badge. */
export function BreakoutBadge({
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
}

function RecentRankCell({ standing }: { readonly standing: RecentStanding | undefined }): React.JSX.Element {
  const sentence = recentSentence(standing);
  return (
    <span
      className="signal-cell recent-cell"
      data-signal="recent"
      data-kind={standing?.kind ?? "none"}
      title={sentence}
    >
      <span className="signal-line" aria-hidden="true">
        <span className="signal-value">{formatRecentRank(standing)}</span>
      </span>
      <span className="signal-detail" aria-hidden="true">
        {recentDetail(standing)}
      </span>
      <span className="visually-hidden">{sentence}</span>
    </span>
  );
}

/**
 * The signed gap, and under it the category state when it is not a plain "no": an
 * `insufficient` verdict is a button too, because "not enough evidence" deserves its reason
 * as much as a badge does.
 */
function RecentGapCell({
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
  const words = describeRecentVsSeason(places, span);
  const insufficient =
    standing !== undefined && standing.kind !== "unavailable" && standing.verdict.category === "insufficient";
  return (
    <span
      className="signal-cell recent-gap"
      data-signal="recent-gap"
      data-direction={places === null ? "none" : places > 0 ? "up" : places < 0 ? "down" : "flat"}
      title={words}
    >
      <span className="signal-line" aria-hidden="true">
        <span className="signal-value">{formatPlaces(places)}</span>
      </span>
      <span className="visually-hidden">{words}</span>
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
}

/** The two recent columns, for a TanStack table whose rows carry both standings. */
export function recentColumns<Row>(
  recentOf: (row: Row) => RecentStanding | undefined,
  seasonOf: (row: Row) => SeasonStanding | undefined,
  positionOf: (row: Row) => Position,
  playerOf: (row: Row) => string,
  spanLabel: string,
  onExplain: (playerId: string) => void,
): ColumnDef<Row>[] {
  return [
    {
      id: "recent_rank",
      header: () => (
        <>
          Recent <span className="th-sub">{spanLabel}</span>
        </>
      ),
      accessorFn: (row) => {
        const standing = recentOf(row);
        return standing?.kind === "ranked" ? positionalSortKey(positionOf(row), standing.rank) : undefined;
      },
      sortUndefined: "last",
      sortDescFirst: false,
      cell: (context) => <RecentRankCell standing={recentOf(context.row.original)} />,
      meta: { align: "right", width: "5.2rem", className: "col-recent" },
    },
    {
      id: "recent_vs_season",
      header: () => (
        <>
          vs Szn <span className="th-sub">{spanLabel}</span>
        </>
      ),
      accessorFn: (row) => recentVsSeasonPlaces(seasonOf(row), recentOf(row)) ?? undefined,
      sortUndefined: "last",
      // Largest rise first; the second click puts the steepest fall on top.
      sortDescFirst: true,
      cell: (context) => (
        <RecentGapCell
          standing={recentOf(context.row.original)}
          season={seasonOf(context.row.original)}
          playerId={playerOf(context.row.original)}
          onExplain={onExplain}
        />
      ),
      meta: { align: "right", width: "4.6rem", className: "col-recent" },
    },
  ];
}

/** The evidence behind one player's category in the selected window, in a dialog. */
export function BreakoutDialog({
  name,
  standing,
  season,
  meta,
  onClose,
}: {
  readonly name: string;
  readonly standing: RecentStanding;
  readonly season: SeasonStanding | undefined;
  readonly meta: RecentFormMetadata;
  readonly onClose: () => void;
}): React.JSX.Element {
  if (standing.kind === "unavailable") {
    return (
      <Modal title={`${name} — recent form`} onClose={onClose}>
        <p>{standing.reason}</p>
      </Modal>
    );
  }
  const badge = badgeOf(standing);
  const category = standing.verdict.category;
  const explanation = breakoutExplanation(standing, season, meta);
  const title =
    badge === null
      ? `${name} — ${category === "insufficient" ? "insufficient evidence" : "no breakout"}`
      : `${name} — ${BREAKOUT_LABELS[badge]}`;
  return (
    <Modal title={title} onClose={onClose}>
      <div className="breakout-explain" data-category={category}>
        <p className="breakout-explain-head">
          {badge !== null && (
            <span className="breakout-badge" data-category={badge} aria-hidden="true">
              <span className="breakout-glyph">{BREAKOUT_GLYPHS[badge]}</span>
              {BREAKOUT_LABELS[badge]}
            </span>
          )}{" "}
          <strong>{explanation.headline}</strong>
        </p>
        {badge !== null && <p className="muted">{categoryDefinition(meta, category)}</p>}
        <ul className="breakout-explain-lines">
          {explanation.lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {standing.kind === "ranked" && (
          <p className="muted">
            {`${formatPoints(standing.points)} points, ${String(standing.games)} game${standing.games === 1 ? "" : "s"}, ${formatPoints(standing.perGame)} per game in ${formatSpan(standing.span)}.`}
          </p>
        )}
        <p className="muted breakout-explain-foot">{explanation.footnote}</p>
      </div>
    </Modal>
  );
}
