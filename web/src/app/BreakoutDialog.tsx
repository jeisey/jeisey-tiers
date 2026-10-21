/**
 * The evidence behind a breakout badge, in a dialog (ADR-113). Lazily loaded the first time a
 * reader opens one: the board itself never needs this code or its sentences.
 */

import { Modal } from "../components/Modal";
import type { SeasonStanding } from "../data/actuals";
import type { RecentFormMetadata } from "../data/contracts";
import {
  BREAKOUT_GLYPHS,
  BREAKOUT_LABELS,
  badgeOf,
  formatPoints,
  formatSpan,
  type RecentStanding,
} from "../data/recent";
import { breakoutExplanation, categoryDefinition } from "../data/recentEvidence";

/** The evidence behind one player's category in the selected window, in a dialog. */
export default function BreakoutDialog({
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
