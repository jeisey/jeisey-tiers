/**
 * The player card's micro-charts.
 *
 * Three small pictures that share one stylesheet block, one geometry helper and one rule, and
 * exist because the in-season card was a wall of correct numbers that a reader could not read.
 * `ROS uncertainty 82.1` is the example the owner gave and it is the whole brief in one tile:
 * the number is right, the artifact published it, every gate passed on it, and it answers
 * nothing — 82.1 of what, beside what, is that a lot?
 *
 * None of them is a new quantity. Each takes numbers the build published and gives them a
 * scale:
 *
 * | | what it draws | what makes it honest |
 * |---|---|---|
 * | `RankShift` | the preseason and rest-of-season ranks as two anchors on one rank axis | two anchors, two model names, and the artifact's own `fair_rank_change` — never one rank that moved |
 * | `PaceRail` | points per appearance scored, against points per appearance the model projects | one unit on both bars, which is the only reason they may share an axis |
 * | `CohortStrip` | where a value sits among the same position's rows on the same board | the denominator is printed on every row |
 *
 * **Two of these could have been one, and must not be.** A rank move and a pace check could be
 * averaged into a single "he is hot" score, and the Opportunity Board's own rule says why not:
 * three orderings over unlike quantities and no blend (`AGENTS.md` section 10, ADR-085). The
 * reader is given the readings; the reading is theirs.
 *
 * **Colour is never the channel.** Every direction here is carried by a sign, a word and a
 * position on a track before it is carried by a hue (`docs/UX_SPEC.md` section 12). Each track
 * is `aria-hidden` and each has a printed reading beside it, which is the same construction the
 * Tier Board and the Draft Rail already use: the picture is the second channel, not the first.
 */

import { cohortPercent, cohortReading, type CohortStat } from "../data/cohort";
import { EM_DASH, formatValue } from "../data/format";
import type { Position } from "../data/contracts";

/**
 * A round number at or just above `raw`, so an axis end reads as a value rather than as an
 * arbitrary maximum.
 *
 * The ladder is denser than the Opportunity Board's 1/2/5/10, deliberately. That axis carries
 * *counts*, where a bound between 2 and 5 would label half a roster move; this one carries
 * points per appearance, where the coarse ladder rounds 21.8 up to 50 and draws every bar in
 * the left half of a track that is mostly empty.
 */
const CEILING_LADDER = [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];

function niceCeiling(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const step = CEILING_LADDER.find((candidate) => normalized <= candidate) ?? 10;
  return step * magnitude;
}

/**
 * The preseason rank and the rest-of-season rank, as two anchors on one rank axis.
 *
 * **What the picture is allowed to claim.** ADR-071 is explicit that these are two models over
 * two horizons and may never be averaged, differenced into a single "true" rank, or presented
 * as versions of one number. So the two anchors carry different shapes and their own model
 * names, the connector is annotated with the build's own published `fair_rank_change` rather
 * than with a subtraction performed here, and the caption says in words that this is two
 * orderings of one board. What it adds over three tiles of digits is the thing three tiles of
 * digits cannot show: the *size* of the disagreement, against the depth of the board it
 * happened on.
 *
 * **The axis is the board's own depth, not the two ranks.** Scaling to the player would make
 * every move fill the strip, so a shuffle from fourth to first would draw exactly like a climb
 * from two hundred and forty-fourth to fifty-ninth — which is the "picture of a difference
 * that is not in the data" the Opportunity Board's symmetric axis exists to avoid. Against the
 * board, the anchors' *positions* say where on it he sits and their *separation* says how much
 * the two orderings disagree, and three places at the top is drawn as the small thing it is.
 *
 * Rank 1 is on the left, which is the order a ranked list is read in; moving up the order is
 * therefore a move to the left, and the sign, the words and the anchor shapes all say so
 * without depending on it. The two anchors are offset above and below the centre line so a
 * player both models agree about reads as two marks in one place rather than as one mark.
 */
export function RankShift({
  from,
  to,
  depth: boardDepth,
  change,
  labels,
  position,
  inPreseasonUniverse,
}: {
  /** `preseason_fair_rank`, or null where the build published none. Geometry only. */
  readonly from: number | null;
  readonly to: number;
  /** Published rows on the board this rank is a rank out of. */
  readonly depth: number | null;
  /** The artifact's own `fair_rank_change`. Positive means higher in the newer ordering. */
  readonly change: number | null;
  /**
   * The three values as the product already prints them.
   *
   * Passed in rather than formatted here, for the same reason `TierBoard` takes a `BoardAxis`
   * of strings: a chart that formats its own numbers is a second place a rank can be rounded,
   * and two renderings of one artifact value is how a card comes to disagree with the table
   * that opened it.
   */
  readonly labels: { readonly from: string; readonly to: string; readonly change: string };
  readonly position: Position;
  readonly inPreseasonUniverse: boolean;
}): React.JSX.Element {
  // A rank deeper than the published board is possible where the two boards differ in depth,
  // so the axis takes whichever is larger rather than clipping a real rank off the end.
  const depth = Math.max(boardDepth ?? 0, from ?? 0, to, 2);
  const at = (rank: number): number =>
    Math.max(0, Math.min(100, ((rank - 1) / (depth - 1)) * 100));
  const fromAt = from === null ? null : at(from);
  const toAt = at(to);
  const direction = from === null ? "flat" : to < from ? "up" : to > from ? "down" : "flat";
  const places = from === null ? 0 : Math.abs(from - to);

  return (
    <div className="shift" data-direction={direction}>
      {/*
        The three readouts, each with its own label and its own model name. All three keep the
        words the product has always used for them, because that is what stops the pair reading
        as one rank that moved: the change is the artifact's own `fair_rank_change`, printed by
        the product's own formatter, and nothing here subtracts anything (ADR-071).
      */}
      <div className="shift-head">
        <div className="shift-end" data-role="from">
          <span className="shift-end-label">Preseason fair rank</span>
          <span className="shift-end-value">{labels.from}</span>
          <span className="shift-end-note">draft model</span>
        </div>
        <div className="shift-end" data-role="change">
          <span className="shift-end-label">Change in intrinsic view</span>
          <span
            className="shift-end-value"
            data-kind={
              change === null || change === 0 ? undefined : change > 0 ? "bargain" : "premium"
            }
          >
            {labels.change}
          </span>
          <span className="shift-end-note">two models, two orderings</span>
        </div>
        <div className="shift-end" data-role="to">
          <span className="shift-end-label">Current ROS fair rank</span>
          <span className="shift-end-value" data-strong="true">
            {labels.to}
          </span>
          <span className="shift-end-note">rest-of-season model</span>
        </div>
      </div>

      {fromAt === null ? (
        <p className="shift-note">
          {inPreseasonUniverse
            ? "The build published no preseason rank for him, so there is no earlier position to place him against."
            : "He was not on the preseason board at all, so there is no earlier ordering to place him in."}
        </p>
      ) : (
        <>
          <div className="shift-track" aria-hidden="true">
            <span
              className="shift-span"
              data-direction={direction}
              style={{
                left: `${String(Math.min(fromAt, toAt))}%`,
                width: `${String(Math.max(Math.abs(toAt - fromAt), 0.4))}%`,
              }}
            />
            <span
              className="shift-anchor"
              data-anchor="from"
              style={{ "--at": `${String(fromAt)}%` } as React.CSSProperties}
            />
            <span
              className="shift-anchor"
              data-anchor="to"
              data-pos={position}
              style={{ "--at": `${String(toAt)}%` } as React.CSSProperties}
            />
          </div>
          <div className="shift-scale" aria-hidden="true">
            <span>1</span>
            <span className="shift-scale-mid">rank order on this board, best at the left</span>
            <span>{String(depth)}</span>
          </div>
          <p className="shift-note">
            {direction === "flat"
              ? "Both models place him in the same spot in their own ordering."
              : `${String(places)} place${places === 1 ? "" : "s"} ${
                  direction === "up" ? "higher" : "lower"
                } in the rest-of-season ordering than in the preseason one.`}{" "}
            <span className="muted">Two orderings of one board, not one rank that moved.</span>
          </p>
        </>
      )}
    </div>
  );
}

/**
 * Points per appearance scored so far, against points per appearance the model projects.
 *
 * **This is the card's answer to "was that week real?"** — and it is the model's own answer
 * rather than a verdict invented on the page. `ros_label_v1` splits the target into remaining
 * games, remaining points per appearance and their product, so a projected rate is a quantity
 * the model is built on; `points_per_game_to_date` is the identical quantity measured before
 * the cutoff. Two numbers, one unit, one either side of the cutoff. Where the projection sits
 * below the rate a player has scored at, the model is declining to buy the whole of what has
 * happened, and that is worth a reader's second of attention on a hot start.
 *
 * **One shared axis, because there is one unit.** That is the exact condition the Opportunity
 * Board fails and why it draws two tracks instead (ADR-085): a count of transactions and a
 * projected value have no exchange rate, and these two have the same one.
 *
 * `appearances` is printed rather than implied. A rate over one game and a rate over eight are
 * different claims, and the number of games behind the first bar is the single most useful
 * caveat a reader can be given in week 1.
 */
export function PaceRail({
  scored,
  projected,
  appearances,
  position,
}: {
  readonly scored: number | null;
  readonly projected: number | null;
  readonly appearances: number;
  readonly position: Position;
}): React.JSX.Element {
  const bound = niceCeiling(Math.max(scored ?? 0, projected ?? 0, 1) * 1.05);
  const width = (value: number | null): string =>
    value === null ? "0%" : `${String(Math.max(0, Math.min(100, (value / bound) * 100)))}%`;
  const gap = scored === null || projected === null ? null : projected - scored;
  const games = Math.round(appearances);

  return (
    <div className="pace">
      <div className="pace-row" data-kind="scored">
        <span className="pace-label">Scored so far</span>
        <span className="pace-track" aria-hidden="true">
          <span className="pace-fill" data-kind="scored" data-pos={position} style={{ width: width(scored) }} />
        </span>
        <span className="pace-value">{scored === null ? EM_DASH : formatValue(scored)}</span>
      </div>
      <div className="pace-row" data-kind="projected">
        <span className="pace-label">Projected ahead</span>
        <span className="pace-track" aria-hidden="true">
          <span className="pace-fill" data-kind="projected" style={{ width: width(projected) }} />
        </span>
        <span className="pace-value">{projected === null ? EM_DASH : formatValue(projected)}</span>
      </div>
      <div className="pace-scale" aria-hidden="true">
        <span>0</span>
        <span className="pace-scale-mid">points per appearance</span>
        <span>{formatValue(bound)}</span>
      </div>
      <p className="pace-note">
        {gap === null
          ? projected === null
            ? "The model projects no remaining appearances for him, so there is no rate to compare."
            : "He has not appeared this season, so there is no rate to compare it with."
          : Math.abs(gap) < 0.05
            ? "The model projects the rate he has been scoring at."
            : `The model projects ${formatValue(Math.abs(gap))} ${
                gap < 0 ? "fewer" : "more"
              } points per appearance than he has scored.`}{" "}
        <span className="muted">
          {`Its remaining points divided by its remaining games, against ${
            games === 0 ? "no appearances" : games === 1 ? "one appearance" : `${String(games)} appearances`
          } so far.`}
        </span>
      </p>
    </div>
  );
}

export interface CohortReadingRow {
  readonly key: string;
  readonly label: string;
  readonly stat: CohortStat | null;
  /** How the value itself is printed — a share is a percentage, a VORP is a value. */
  readonly format: (value: number) => string;
  /** The word that makes the order readable: `widest` for an interval, nothing for a value. */
  readonly qualifier?: string | undefined;
}

/**
 * Where this player's published values sit among the same position's rows on the same board.
 *
 * Each row is a track carrying the cohort's middle half as a band, its median as a tick, and
 * this player as a glowing mark — the distribution rail's own vocabulary one step down in
 * scale, so a reader who has understood the P25–P75 band above already understands this.
 *
 * **The denominator is on every row, and the population is the published board rather than the
 * filter.** `docs/UX_SPEC.md` section 7.1A requires a bar to state its denominator; a rank is
 * worse than a bar without one, because it looks exact. And a rank that moved when the reader
 * changed the position control would be a rank about the control.
 *
 * A row whose cohort is too small, or whose value the build did not publish, is **not drawn**
 * — and nothing is lost by that, because the card's readout tiles carry every one of these
 * values already. The tiles are the record and this is the reading: a reading that cannot be
 * made is an absent row, never a mark at zero, and where no row can be made the whole strip
 * withholds itself rather than drawing an empty frame.
 */
export function CohortStrip({
  title,
  noun,
  rows,
  position,
}: {
  readonly title: string;
  /** The population, exactly as it is printed: `WRs`. */
  readonly noun: string;
  readonly rows: readonly CohortReadingRow[];
  readonly position: Position;
}): React.JSX.Element | null {
  // `flatMap` rather than `filter`, because a filter cannot narrow the element type and the
  // alternative is a non-null assertion on a field whose nullability is the whole contract.
  const drawn = rows.flatMap((row) => (row.stat === null ? [] : [{ ...row, stat: row.stat }]));
  if (drawn.length === 0) return null;
  const banded = drawn.some((row) => row.stat.band !== null);

  return (
    <div className="cohort">
      <div className="cohort-head">
        <span className="cohort-title">{title}</span>
        <span className="cohort-meta">published rows, not the filter</span>
      </div>
      <ul className="cohort-rows">
        {drawn.map((row) => {
          const stat = row.stat;
          return (
            <li className="cohort-row" key={row.key}>
              <span className="cohort-label">{row.label}</span>
              <span className="cohort-track" aria-hidden="true">
                {stat.band !== null && (
                  <>
                    <span
                      className="cohort-band"
                      style={{
                        left: `${String(cohortPercent(stat, stat.band.p25))}%`,
                        width: `${String(
                          Math.max(
                            cohortPercent(stat, stat.band.p75) -
                              cohortPercent(stat, stat.band.p25),
                            0.6,
                          ),
                        )}%`,
                      }}
                    />
                    <span
                      className="cohort-mid"
                      style={{ left: `${String(cohortPercent(stat, stat.band.p50))}%` }}
                    />
                  </>
                )}
                <span
                  className="cohort-mark"
                  data-pos={position}
                  style={
                    { "--at": `${String(cohortPercent(stat, stat.value))}%` } as React.CSSProperties
                  }
                />
              </span>
              <span className="cohort-read">
                <b>{row.format(stat.value)}</b>
                <span>{cohortReading(stat, noun, row.qualifier)}</span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="cohort-note">
        {banded
          ? "The mark is this player; where a band is drawn it is the middle half of that cohort and the tick is its median."
          : "The mark is this player, on the cohort's own range. Too few rows here for a middle-half band."}
      </p>
    </div>
  );
}
