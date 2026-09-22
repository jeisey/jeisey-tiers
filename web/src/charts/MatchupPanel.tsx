/**
 * The next game, as context (ADR-091).
 *
 * **Context, and the panel says so in the sentence the artifact carries.** The spread, the
 * total and the implied points are sportsbook numbers. They are printed here because "who
 * does he play and what kind of game is it expected to be" is part of a this-week decision,
 * and they move nothing: no projection, VORP, rank, tier or pick reads them. The build
 * metadata's `sportsbook_context_statement` is printed beneath them wherever they appear, so
 * the interface cannot show a line without also saying what it is not.
 *
 * **Every number is the artifact's own.** The spread arrives already expressed from this
 * team's side; the implied points arrive computed. The split bar draws the two implied scores
 * as two parts of the posted total — a picture of three published numbers, stating nothing
 * the three printed beside it do not.
 *
 * **An unposted line is not a pick'em.** Lines appear about two weeks ahead; before that the
 * panel says they are not posted, rather than drawing an even split.
 */

import { EM_DASH, formatEastern, formatValue } from "../data/format";
import { impliedSplit, matchupReading } from "../data/signals";
import type { TeamMatchupRecord } from "../data/contracts";

function restLabel(record: TeamMatchupRecord): string {
  if (record.team_rest_days === null) return EM_DASH;
  const theirs =
    record.opponent_rest_days === null ? "" : ` v ${String(record.opponent_rest_days)}`;
  return `${String(record.team_rest_days)}${theirs} days`;
}

export function MatchupPanel({
  record,
  team,
  statement,
  compact = false,
}: {
  readonly record: TeamMatchupRecord;
  readonly team: string;
  /** The build metadata's `sportsbook_context_statement`, verbatim. */
  readonly statement: string | null;
  /** Pick of the Week's evidence row: the head line and the split, no tiles. */
  readonly compact?: boolean;
}): React.JSX.Element {
  const reading = matchupReading(record);
  const split = impliedSplit(record);
  return (
    <div className="matchup" data-lines={reading.linesPosted ? "posted" : "unposted"}>
      <p className="matchup-head">
        <strong className="matchup-opponent">{`Week ${String(record.week)} ${reading.opponentLabel}`}</strong>
        <span className="matchup-when">{formatEastern(record.kickoff_utc)}</span>
        {record.neutral_site && <span className="matchup-flag">neutral site</span>}
      </p>

      {split !== null && (
        <div className="matchup-split" aria-hidden="true">
          <span
            className="matchup-split-team"
            style={{ width: `${String(Math.round(split.team * 1000) / 10)}%` }}
          >
            {`${team} ${formatValue(record.implied_team_points)}`}
          </span>
          <span className="matchup-split-opponent">
            {`${record.opponent} ${formatValue(record.implied_opponent_points)}`}
          </span>
        </div>
      )}

      {compact ? (
        <p className="matchup-line">
          {reading.linesPosted
            ? `${team} implied ${formatValue(record.implied_team_points)} · ${reading.spreadLabel ?? "no spread posted"} · total ${formatValue(record.total_line)}`
            : "No line posted yet — sportsbooks post about two weeks ahead."}
        </p>
      ) : (
        <div className="readout-grid matchup-tiles">
          <div className="readout" data-size="sm">
            <span className="readout-label">Implied team points</span>
            <span className="readout-value">{formatValue(record.implied_team_points)}</span>
            <span className="readout-hint">
              {reading.linesPosted ? "sportsbook, not this model" : "no line posted yet"}
            </span>
          </div>
          <div className="readout" data-size="sm">
            <span className="readout-label">Spread</span>
            <span className="readout-value">{reading.spreadLabel ?? EM_DASH}</span>
            <span className="readout-hint">{`${team} side`}</span>
          </div>
          <div className="readout" data-size="sm">
            <span className="readout-label">Game total</span>
            <span className="readout-value">{formatValue(record.total_line)}</span>
            <span className="readout-hint">both teams</span>
          </div>
          <div className="readout" data-size="sm">
            <span className="readout-label">Rest</span>
            <span className="readout-value">{restLabel(record)}</span>
            <span className="readout-hint">{record.roof ?? "roof not published"}</span>
          </div>
        </div>
      )}

      {reading.byeBeforeGame !== null && (
        <p className="matchup-bye">{`On bye in week ${String(reading.byeBeforeGame)}.`}</p>
      )}
      {!compact && reading.byeBeforeGame === null && reading.nextBye !== null && (
        <p className="matchup-bye">{`Bye still ahead: week ${String(reading.nextBye)}.`}</p>
      )}
      {reading.linesPosted && statement !== null && (
        <p className="cohort-note matchup-statement">
          {compact
            ? "Sportsbook context, read by no model."
            : `${statement} Lines as retrieved ${formatEastern(record.lines_retrieved_at_utc)}.`}
        </p>
      )}
    </div>
  );
}
