/**
 * One player-detail surface, reachable from every board.
 *
 * The Tier table, the Tier Board, the Arbitrage table and the Draft Rail all open this same
 * dialog. There is deliberately no second tooltip system: a hover-only affordance would put
 * the intrinsic, market and status detail out of reach on a phone and behind a mouse for
 * keyboard users, and the UX spec requires no core function depend on hover. The design
 * source's own hover peek (artboard 1c, left) is not implemented for that reason; its content
 * — fair rank, ADP, gap, the VORP band, the status line — is the first thing in the rail.
 *
 * **Phase 9A: three variants, each grounded in a real artboard.** One DOM; the layout and one
 * explicit branch choose between them (`docs/DESIGN_SOURCE_MAP.md` section 4):
 *
 * | viewport | artboard | shape |
 * |---|---|---|
 * | >=1100px | **1c** click state | a 17rem identity rail beside the detail pane |
 * | 768-1099px | **1a** tactical dossier | the rail becomes a header band, sections stack |
 * | <768px | **1b** segmented scope | a full-height sheet, three tabs, no long scroll |
 *
 * The rail is always in the DOM and always carries the accessible title, so no variant has to
 * duplicate the heading. Native `<dialog>` + `showModal()` supplies focus trapping, Escape and
 * an inert background in all three, which is why the responsive decision costs no
 * accessibility.
 *
 * **What is deliberately *not* taken from the design.** Its cards end sections with paragraphs
 * of methodology — what confidence is a statement about, why the cohort is approximate, the
 * standing status disclosure. All three are true and none is about *this* player, so on a
 * three-hundred-player board they are three hundred copies of the same three paragraphs. The
 * owner's Phase-8 review asked for exactly those to go and ADR-058 records the rule: state
 * methodology once, in Data; a repeated surface carries only what stops a number being
 * misread. The short markers stay — `approximate cohort` under the ADP, `Annotation only` under
 * the status fields — and Data carries the rest.
 *
 * Two things that are easy to get wrong and are therefore still explicit here:
 *
 * - a status row reading "none reported" is the absence of a report, not a clearance — the
 *   word "healthy" appears nowhere in this product (ADR-043);
 * - `Market data` is a statement about how much draft evidence stands behind the price, not a
 *   probability and not model confidence (ADR-041).
 */

import { useEffect, useId, useRef, useState } from "react";

import { ConfidenceMeter, PositionTag, StatusBadge, TierTag } from "../components/primitives";
import { PlayerPortrait } from "../components/PlayerPortrait";
import { useMediaQuery } from "../components/useMediaQuery";
import { CohortStrip, PaceRail, RankShift, type CohortReadingRow } from "../charts/CardMeters";
import { MarketTrend, type TrendSeries } from "../charts/MarketTrend";
import type {
  ArbitrageRecord,
  CrossMarketSummary,
  ExpertConsensus,
  MarketComparison,
  MarketTrendSeriesRecord,
  OpportunityRecord,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  RosBehaviorMetadata,
  RosDisclosures,
  RosTierRecord,
  TierRecord,
} from "../data/contracts";
import {
  CROSS_MARKET,
  consensusOf,
  crossMarketOf,
  crossMarketSummaryText,
  historiesFor,
  marketLabel,
  marketView,
  marketsOf,
  windowLabel,
} from "../data/multimarket";
import {
  EM_DASH,
  formatAdp,
  formatEastern,
  formatInteger,
  formatRank,
  formatScore,
  formatSigned,
  formatValue,
} from "../data/format";
import { ordinal } from "../data/cohort";
import { explainFlags, playerLevelFlags } from "../data/flags";
import { CONFIDENCE_SHORT, describeGap, describeTrend, marketSourceLabel } from "../data/market";
import { hasMeaningfulStatus, isNoteworthyRosterStatus, statusBadge } from "../data/model";
import {
  longAbsenceLabel,
  projectedRemainingRate,
  rankChangeLabel,
  scoredRate,
  type RosCohortContext,
} from "../data/ros";

/** The stylesheet's sheet breakpoint. Keep in step with `base.css`. */
const SHEET_QUERY = "(max-width: 767px)";

export interface PlayerDetailData {
  readonly playerId: string;
  readonly tier: TierRecord | null;
  readonly arbitrage: ArbitrageRecord | null;
  readonly status: PlayerStatusRecord | null;
  /**
   * The published address of this player's portrait, or null.
   *
   * A string rather than the record, because the card has no business with the provider or
   * its id: the build decided which provider and validated which host, and the card's only
   * question is whether there is a picture to draw (ADR-087).
   */
  readonly headshotUrl?: string | null;
  readonly projection: PlayerProjectionRecord | null;
  /** True when the arbitrage artifact loaded but holds no row for this player. */
  readonly marketAvailable: boolean;
  /**
   * Whether the cohort pricing this preset is exact for it, from `build_metadata`.
   *
   * The arbitrage record carries the cohort's filters but not the exactness verdict — that is
   * a per-preset judgement the selection rule reaches and publishes in the build's assignment
   * table. Null when the build published no assignment for the preset.
   */
  readonly cohortExact: boolean | null;
  /** The ADP market the reader has selected. Decides which comparison leads the card. */
  readonly market?: string;
  /**
   * Every market's retained ADP history for this player, unfiltered.
   *
   * The card selects from these rather than being handed one series, because the
   * cross-market view needs all of them and the selection is not a source: an index keyed by
   * source id can never hold a `cross` record, and asking it for one is how the cross view
   * came to have no chart at all (ADR-081).
   */
  readonly trendSeries?: readonly MarketTrendSeriesRecord[];
  /**
   * This player's rest-of-season row, when an in-season bundle is loaded.
   *
   * Shown as its own block, never merged into the preseason numbers above it: the roadmap's
   * detail panel asks for "Preseason Fair Rank / Current ROS Fair Rank / Change in intrinsic
   * value" as three separate readouts, because the useful thing is precisely that they are
   * different quantities that moved.
   */
  readonly ros?: RosTierRecord | null;
  /** ADR-076's sentences, from the in-season artifact. Required wherever the flag is shown. */
  readonly rosDisclosures?: RosDisclosures | null;
  /**
   * This player's Opportunity Board row, when an in-season bundle published one.
   *
   * Behaviour, and only behaviour: counts of roster transactions over a declared window, plus
   * the usage shares the board already carries. Never differenced against a rank, never
   * converted into a price.
   */
  readonly opportunity?: OpportunityRecord | null;
  /** The behaviour feed's own account of itself — source, window, snapshot time. */
  readonly behavior?: RosBehaviorMetadata | null;
  /**
   * Where this player's published values sit among the same position's rows on this board.
   *
   * Assembled in `data/ros` from the published block, never from the reader's filtered view,
   * and never recomputed here: a card is a renderer, and a rank that moved when someone
   * changed the position control would be a rank about the control. Null before kickoff and
   * whenever the cohort is too small to be one — both ordinary states, both drawn as an
   * absence rather than as a zero.
   */
  readonly rosCohort?: RosCohortContext | null;
  /**
   * Whether this card was opened from an in-season board (ADR-085).
   *
   * It decides which of two sections occupies the same slot: a draft ADP comparison, or what
   * is actually happening to the player this week. In November the first is a price nobody
   * can act on — the draft is over — so it is replaced rather than sat beside it.
   *
   * **The board decides, not the calendar.** A row on the Tier Board is a draft-model row and
   * its market comparison is the draft market, whatever month it is; the draft board stays
   * reachable all season (roadmap 12.1) and a reader who asked for it asked for its card too.
   * So this is true for the rest-of-season and opportunity views only — which also makes
   * ADR-079's two lifecycle windows, in season with no board at all, correct without a second
   * condition.
   */
  readonly inSeason?: boolean;
}

/**
 * A labelled numeric readout — the unit of the HUD, and the design source's most repeated
 * component. The hairline between tiles is the grid's own 1px gap, not a border.
 *
 * `strong` promotes the values a drafter reads first. `hint` is at most three words; it is not
 * a place for methodology.
 */
function Readout({
  label,
  value,
  hint,
  kind,
  strong = false,
  size,
  srSuffix,
}: {
  readonly label: string;
  readonly value: React.ReactNode;
  readonly hint?: string | undefined;
  readonly kind?: "bargain" | "premium" | "even" | undefined;
  readonly strong?: boolean;
  /** `sm` for a long string value — a cohort id, not a number. */
  readonly size?: "sm" | undefined;
  /** Extra words for assistive technology only, when the visible value is a glyph or sign. */
  readonly srSuffix?: string | undefined;
}): React.JSX.Element {
  return (
    <div className="readout" data-strong={strong} data-kind={kind} data-size={size}>
      <span className="readout-label">{label}</span>
      <span className="readout-value">
        {value}
        {srSuffix !== undefined && <span className="visually-hidden">{` ${srSuffix}`}</span>}
      </span>
      {hint !== undefined && <span className="readout-hint">{hint}</span>}
    </div>
  );
}

/**
 * Every market and expert reference for one player, side by side.
 *
 * Its own component because it is shown in two situations that are otherwise opposites: when
 * the selected market priced him, beneath that market's own numbers, and when it did not, in
 * place of them. The second is the case that matters — a reader told "FFC does not price him"
 * still needs to see that MyFantasyLeague does, and the alternative to showing it is the
 * borrowed number this card used to print (ADR-081).
 */
function MarketComparisonTable({
  name,
  fairRank,
  markets,
  consensus,
  cross,
  selection,
}: {
  readonly name: string;
  readonly fairRank: number;
  readonly markets: Readonly<Record<string, MarketComparison>>;
  readonly consensus: ExpertConsensus | null;
  readonly cross: CrossMarketSummary | null;
  readonly selection: string;
}): React.JSX.Element | null {
  const entries = Object.values(markets);
  if (entries.length === 0 && consensus === null) return null;
  return (
    <div className="market-compare">
      <table className="compare-table">
        <caption className="visually-hidden">
          {`Every published market and expert reference for ${name}, each compared with the model's fair rank of ${formatRank(fairRank)}.`}
        </caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Reading</th>
            <th scope="col">vs fair rank</th>
            <th scope="col">Trend</th>
            <th scope="col">Window</th>
          </tr>
        </thead>
        <tbody>
          {[...entries]
            .sort((a, b) => a.source_id.localeCompare(b.source_id))
            .map((entry) => {
              const entryGap = describeGap(entry.rank_gap);
              return (
                <tr
                  key={entry.source_id}
                  data-selected={entry.source_id === selection ? "true" : undefined}
                >
                  <th scope="row">{marketLabel(entry.source_id)}</th>
                  <td>{`ADP ${formatAdp(entry.market_adp)}`}</td>
                  <td className="dir" data-kind={entryGap.kind}>
                    <span aria-hidden="true">{formatSigned(entry.rank_gap)}</span>
                    <span className="visually-hidden">{entryGap.sentence}</span>
                  </td>
                  {/* Each market's own slope, in the one place a comparison belongs. The
                      cross-market view has no scalar of its own precisely because this column
                      does the comparing (ADR-081). */}
                  <td className="muted">
                    {entry.market_trend === null ? (
                      <>
                        <span className="faint" aria-hidden="true">{EM_DASH}</span>
                        <span className="visually-hidden">
                          {`${marketLabel(entry.source_id)}: trend collecting`}
                        </span>
                      </>
                    ) : (
                      <>
                        <span aria-hidden="true">{formatSigned(entry.market_trend, 2)}</span>
                        <span className="visually-hidden">
                          {describeTrend(entry.market_trend).text}
                        </span>
                      </>
                    )}
                  </td>
                  <td className="muted">
                    {windowLabel(entry.aggregation_window_type, entry.aggregation_window_days)}
                  </td>
                </tr>
              );
            })}
          {consensus !== null && (
            <tr data-signal="ecr">
              <th scope="row">{marketLabel(consensus.source_id)}</th>
              <td>{`Rank ${String(consensus.ecr)}`}</td>
              <td className="dir" data-kind={describeGap(consensus.ecr_gap).kind}>
                <span aria-hidden="true">{formatSigned(consensus.ecr_gap)}</span>
                <span className="visually-hidden">
                  {`the expert consensus ranks him ${Math.abs(consensus.ecr_gap).toFixed(0)} places ${consensus.ecr_gap > 0 ? "lower" : "higher"} than the model`}
                </span>
              </td>
              {/* A ranking has no ADP to have a slope over. */}
              <td className="faint" aria-hidden="true">{EM_DASH}</td>
              <td className="muted">expert consensus, not a price</td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="section-note">{crossMarketSummaryText(cross)}</p>
    </div>
  );
}

/** Fields Sleeper publishes as keys with null values in the preseason are simply left out. */
function OptionalReadout({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string | number | null | undefined;
}): React.JSX.Element | null {
  if (value === null || value === undefined || value === "") return null;
  return <Readout label={label} value={value} />;
}

/**
 * The section header from the design source: a mono index, the heading, a rule fading right,
 * and a badge naming what kind of thing the section is.
 *
 * The index is assigned over the sections actually rendered rather than hard-coded, because a
 * player with no market price has no section 02.
 */
function DetailSection({
  index,
  id,
  title,
  badge,
  badgeTone,
  tabbed,
  children,
}: {
  readonly index: number;
  readonly id: string;
  readonly title: string;
  readonly badge?: React.ReactNode;
  readonly badgeTone?: "warn" | "good" | undefined;
  /** In the sheet variant each section is a tab panel rather than a peer section. */
  readonly tabbed: boolean;
  readonly children: React.ReactNode;
}): React.JSX.Element {
  const headingId = `${id}-heading`;
  return (
    <section
      className="detail-section"
      {...(tabbed
        ? { role: "tabpanel", id: `${id}-panel`, "aria-labelledby": `${id}-tab`, tabIndex: 0 }
        : { "aria-labelledby": headingId })}
    >
      <div className="detail-section-head">
        <span className="detail-section-index" aria-hidden="true">
          {String(index).padStart(2, "0")}
        </span>
        {/*
          In the sheet variant the tab above already names the panel, and repeating the title
          under it reads as a duplicate. The heading stays in the accessibility tree — it is
          hidden, not removed — so heading navigation still works.
        */}
        <h3 id={headingId} className={tabbed ? "visually-hidden" : undefined}>
          {title}
        </h3>
        <span className="detail-section-rule" aria-hidden="true" />
        {badge !== undefined && (
          <span className="detail-section-badge" data-tone={badgeTone}>
            {badge}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

/**
 * The simulated-interval rail from artboards 1b and 1c.
 *
 * Every coordinate is an artifact quantile placed on a P10-P90 scale. Nothing is computed: the
 * component is handed five numbers and turns them into positions.
 */
function Distribution({
  p10,
  p25,
  p50,
  p75,
  p90,
  title,
  meta,
}: {
  readonly p10: number;
  readonly p25: number;
  readonly p50: number;
  readonly p75: number;
  readonly p90: number;
  readonly title: string;
  readonly meta: string;
}): React.JSX.Element {
  const range = p90 - p10 || 1;
  const at = (value: number): number => Math.max(0, Math.min(100, ((value - p10) / range) * 100));
  const left = at(p25);
  const width = Math.max(at(p75) - left, 0.6);
  return (
    <div className="dist">
      <div className="dist-head">
        <span className="dist-title">{title}</span>
        <span className="dist-meta">{meta}</span>
      </div>
      <div className="dist-track" aria-hidden="true">
        <span
          className="dist-band"
          style={{ left: `${String(left)}%`, width: `${String(width)}%` }}
        />
        <span className="dist-median" style={{ left: `${String(at(p50))}%` }} />
      </div>
      <div className="dist-scale" aria-hidden="true">
        <span>{formatValue(p10)}</span>
        <span>
          <b>{`${formatValue(p25)} – ${formatValue(p75)}`}</b>
          {` · P50 ${formatValue(p50)}`}
        </span>
        <span>{formatValue(p90)}</span>
      </div>
    </div>
  );
}

/**
 * The in-season usage panel (ADR-085).
 *
 * It occupies the slot `Draft market` holds before kickoff, and it is a replacement rather
 * than an addition. A draft ADP is a price for a transaction nobody can make any more: in
 * November the draft is over, the number moves only because next August's mocks have started,
 * and a card that leads with it is answering a question the reader stopped asking in
 * September. What they ask instead is what the player has actually done and what the wire is
 * doing about him, and both are in artifacts this build already publishes.
 *
 * Every rule the Opportunity Board runs on holds here too, because they are the same numbers:
 *
 * - **a count is a count.** Adds and drops are transactions over the window the artifact
 *   declares, never a price, never a rank, and never differenced against one;
 * - **two quantities, never combined.** Production to date is in points and roster moves are
 *   in transactions; they sit in separate blocks with separate headings for the same reason
 *   the board draws them on separate tracks;
 * - **nothing here is a model input.** These are observations about what happened, shown
 *   beside an estimate that did not read them.
 */
function InSeasonUsage({
  ros,
  opportunity,
  behavior,
  cohort,
}: {
  readonly ros: RosTierRecord;
  readonly opportunity: OpportunityRecord | null;
  readonly behavior: RosBehaviorMetadata | null;
  readonly cohort: RosCohortContext | null;
}): React.JSX.Element {
  const window = opportunity?.behavior_lookback_hours ?? behavior?.lookback_hours ?? null;
  const windowText = window === null ? "the declared window" : `${String(window)}h`;
  const feedUp = opportunity?.behavior_available === true;
  const adds = opportunity?.add_count ?? null;
  const drops = opportunity?.drop_count ?? null;
  const net = opportunity?.net_add_count ?? null;
  /*
    The symmetric bound for the strip below, from the board rather than from this player.

    It used to be `max(adds, drops)` for this row alone, on the reasoning that a card has no
    population to scale against. It has one: the board the reader just came from. Scaling to
    the player's own larger count made every strip the same picture — whoever had more adds
    than drops filled the right half exactly, whether that was four transactions or four
    hundred thousand — so the shape carried no magnitude at all. The board's own `movesBound`
    puts the two strips on one scale, and a count past it is clipped with a chevron and its
    real number printed beside it, exactly as the board does. The bound is named in the
    caption, because a bar whose denominator is not stated is a bar that cannot be read.
  */
  const bound = cohort?.movesAxis ?? Math.max(1, adds ?? 0, drops ?? 0);
  const addsWidth = Math.min(50, ((adds ?? 0) / bound) * 50);
  const dropsWidth = Math.min(50, ((drops ?? 0) / bound) * 50);

  const perGame = scoredRate(ros);
  const projected = projectedRemainingRate(ros);

  const usageRows: readonly CohortReadingRow[] = [
    {
      key: "rate",
      label: "Points per game",
      stat: cohort?.scoredRate ?? null,
      format: formatValue,
    },
    {
      key: "snap",
      label: "Snap share",
      stat: cohort?.snapShare ?? null,
      format: (value) => `${String(Math.round(value * 100))}%`,
    },
    {
      key: "target",
      label: "Target share",
      stat: cohort?.targetShare ?? null,
      format: (value) => `${String(Math.round(value * 100))}%`,
    },
  ];

  return (
    <>
      {/* The verdict line, in the same slot the market verdict occupies in draft mode. It is a
          sentence about transactions and says nothing about value. */}
      <div
        className="market-verdict"
        data-kind={
          !feedUp || net === null ? "even" : net > 0 ? "bargain" : net < 0 ? "premium" : "even"
        }
      >
        <strong>
          {/*
            Three absences, and they are three different facts. "He is not on the opportunity
            board" is not "the feed said nothing", and neither is "nobody moved on him" — the
            last of those is a reading and the first two are the lack of one.
          */}
          {opportunity === null
            ? "He is not on this build's opportunity board."
            : !feedUp
              ? "No add or drop activity is published for this build."
              : (adds ?? 0) === 0 && (drops ?? 0) === 0
                ? `No rosters added or dropped him in the last ${windowText}.`
                : `${formatInteger(adds ?? 0)} roster${(adds ?? 0) === 1 ? "" : "s"} added him and ` +
                  `${formatInteger(drops ?? 0)} dropped him in the last ${windowText}.`}
        </strong>{" "}
        <span>
          {feedUp
            ? "A count of transactions, not a price and not a rank."
            : "Every value on this card is unaffected: behaviour decides who is visible, never what he is worth."}
        </span>
      </div>

      <div className="detail-subhead">
        <span>Production so far</span>
        <span className="detail-subhead-note">{`weeks 1–${String(ros.through_week)}`}</span>
      </div>

      {/*
        Pace: what he has scored per appearance, against what the model projects per remaining
        appearance. The card's answer to the question a hot start actually raises — one the
        artifact can answer in its own units, because `ros_label_v1` is built on points per
        appearance and `points_per_game_to_date` is the same quantity before the cutoff.
      */}
      <PaceRail
        scored={perGame}
        projected={projected}
        appearances={ros.games_played_to_date}
        position={ros.position}
      />

      <div className="readout-grid">
        <Readout
          label="Games played"
          value={ros.has_played_this_season ? formatValue(ros.games_played_to_date) : "None"}
          strong
        />
        <Readout label="Fantasy points" value={formatValue(ros.points_to_date)} hint="to date" />
        <Readout
          label="Points per game"
          value={perGame === null ? EM_DASH : formatValue(perGame)}
          hint={perGame === null ? "no appearances" : "per appearance"}
        />
        <Readout
          label="Weeks since last game"
          value={
            !ros.has_played_this_season
              ? "No appearances"
              : Math.round(ros.weeks_since_last_game) === 0
                ? "Played latest"
                : String(Math.round(ros.weeks_since_last_game))
          }
        />
        {/*
          The tile grid is the record and the meters below are the reading, which is why these
          two published shares keep a tile of their own. A cohort reading needs a cohort, and a
          board with two wide receivers on it has none; the value a build published must not
          disappear because the population it would be compared against is too small.
        */}
        <Readout
          label="Snap share"
          value={
            opportunity?.snap_share_last3 == null
              ? EM_DASH
              : `${String(Math.round(opportunity.snap_share_last3 * 100))}%`
          }
          hint="last 3 games"
        />
        <Readout
          label="Target share"
          value={
            opportunity?.target_share_last3 == null
              ? EM_DASH
              : `${String(Math.round(opportunity.target_share_last3 * 100))}%`
          }
          hint="last 3 games"
        />
      </div>

      {/* Production and workload against the same position on the same board. Snap and target
          share are the reading that separates a week built on volume from one built on a long
          touchdown, and neither is legible as a bare percentage. */}
      <CohortStrip
        title={
          cohort === null
            ? "Production against this board"
            : `Production against the ${cohort.noun} on this board`
        }
        noun={cohort?.noun ?? "players"}
        rows={usageRows}
        position={ros.position}
      />

      <div className="detail-subhead">
        <span>Roster moves</span>
        <span className="detail-subhead-note">
          {feedUp ? `${windowText} window` : "feed unavailable"}
        </span>
      </div>

      {/* The board's own diverging strip, for one player: drops left of centre, adds right, on
          the board's own symmetric scale. Never colour alone — the counts are printed beneath
          it and the whole reading is in the card's text. */}
      <div className="opp-track" data-track="moves" data-card="true" aria-hidden="true">
        <span className="opp-zero" style={{ left: "50%" }} />
        {feedUp ? (
          <>
            <span
              className="opp-move-bar"
              data-kind="drop"
              style={{ left: `${String(50 - dropsWidth)}%`, width: `${String(dropsWidth)}%` }}
            />
            <span
              className="opp-move-bar"
              data-kind="add"
              style={{ left: "50%", width: `${String(addsWidth)}%` }}
            />
            {(adds ?? 0) > bound && (
              <span className="opp-overflow" data-kind="add">
                ›
              </span>
            )}
            {(drops ?? 0) > bound && (
              <span className="opp-overflow" data-kind="drop">
                ‹
              </span>
            )}
          </>
        ) : (
          <span className="opp-track-empty" />
        )}
      </div>
      <p className="cohort-note">
        {feedUp
          ? `Drops left of centre, adds right, on the board's own axis of ±${formatInteger(bound)}` +
            (cohort?.movesAxis == null ? "" : " — the 85th percentile of its non-zero counts") +
            ". A chevron marks a count past it; the numbers below are the reading."
          : "The behaviour feed published nothing for this build, so the strip is empty rather than zero."}
      </p>

      <div className="readout-grid">
        <Readout
          label="Drops"
          value={drops === null ? EM_DASH : formatInteger(drops)}
          hint={feedUp ? windowText : "not published"}
        />
        <Readout
          label="Adds"
          value={adds === null ? EM_DASH : formatInteger(adds)}
          hint={feedUp ? windowText : "not published"}
          strong
        />
        <Readout
          label="Net adds"
          value={net === null ? EM_DASH : net > 0 ? `+${formatInteger(net)}` : formatInteger(net)}
          kind={net === null || net === 0 ? "even" : net > 0 ? "bargain" : "premium"}
        />
        <Readout
          label="Add rank"
          value={opportunity?.add_rank == null ? EM_DASH : formatRank(opportunity.add_rank)}
          hint="on the feed"
        />
        <Readout
          label="Behaviour source"
          value={opportunity?.behavior_source_id ?? behavior?.source_id ?? EM_DASH}
          size="sm"
        />
        <Readout
          label="Snapshot"
          value={formatEastern(opportunity?.behavior_snapshot_at_utc ?? behavior?.snapshot_at_utc)}
          hint="retrieved"
          size="sm"
        />
      </div>

      {opportunity?.outside_tier_board === true && (
        <p className="status-annotation">
          Published from beyond the tier depth because current evidence made him relevant, so he
          carries a rest-of-season value and no tier.
        </p>
      )}
    </>
  );
}

export function PlayerDetail({
  data,
  onClose,
  onOpenData,
}: {
  readonly data: PlayerDetailData | null;
  readonly onClose: () => void;
  /** Where the methodology went. One link, not a paragraph on every card. */
  readonly onOpenData?: (() => void) | undefined;
}): React.JSX.Element | null {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const returnFocusTo = useRef<HTMLElement | null>(null);
  const sheet = useMediaQuery(SHEET_QUERY);
  const [tab, setTab] = useState(0);
  const baseId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;
    if (data !== null && !dialog.open) {
      // Remember the trigger before the dialog takes focus. Browsers restore focus on
      // `close()` themselves, but the trigger here is a row that a filter or a sort can
      // unmount, so the restore is done explicitly and defensively.
      const active = document.activeElement;
      returnFocusTo.current =
        active instanceof HTMLElement && active !== document.body ? active : null;
      // `showModal` gives focus trapping, Escape-to-close and inert background for free, which
      // is a great deal more correct than any hand-rolled overlay.
      dialog.showModal();
    }
    if (data === null && dialog.open) dialog.close();
  }, [data]);

  // A new player in an already-open dialog starts on the first tab, not wherever the last one
  // was left — the sections differ between players, so the index does not carry over. Adjusted
  // during render rather than in an effect: React re-renders immediately with tab 0 instead of
  // painting the previous player's tab first.
  const playerId = data?.playerId ?? null;
  const [lastPlayerId, setLastPlayerId] = useState(playerId);
  if (lastPlayerId !== playerId) {
    setLastPlayerId(playerId);
    setTab(0);
  }

  useEffect(() => {
    if (data !== null) return;
    const target = returnFocusTo.current;
    returnFocusTo.current = null;
    if (target?.isConnected === true) target.focus();
  }, [data]);

  if (data === null) return null;

  const { tier, arbitrage, status, projection, ros, rosDisclosures, opportunity } = data;
  // The in-season card, and only when there is in-season data to put in it. An in-season view
  // with no rest-of-season row cannot happen — the view is not offered without a bundle — but
  // the row is what the panel is made of, so it is what the branch tests.
  const inSeasonCard = data.inSeason === true && ros != null;
  // Where this player sits among his own position on this board. Null before kickoff, and on
  // any board whose cohort is too small to be one; every consumer treats that as an absence.
  const cohort = data.rosCohort ?? null;
  const market = data.market ?? CROSS_MARKET;
  // One resolution, once. Every number in this card and its rail comes from `view`; nothing
  // below reaches past it to a flat field, because the flat fields are MyFantasyLeague's and
  // reading them under an FFC heading is the defect this card had (ADR-067, ADR-081).
  const view = marketView(arbitrage, market);
  const selected = view?.comparison ?? null;
  const consensus = arbitrage === null ? null : consensusOf(arbitrage);
  const cross = arbitrage === null ? null : crossMarketOf(arbitrage);
  const everyMarket = arbitrage === null ? {} : marketsOf(arbitrage);
  // The chart's series, named by the market each came from. There is no `cross` series to
  // look up: the cross-market view overlays the real ones.
  const chartSeries: readonly TrendSeries[] = historiesFor(data.trendSeries ?? [], market).map(
    (record) => ({
      sourceId: record.market_source_id,
      label: marketLabel(record.market_source_id),
      points: record.points,
      trend: record.market_trend,
    }),
  );
  const name = tier?.display_name ?? arbitrage?.display_name ?? status?.display_name ?? "Player";
  const position = tier?.position ?? arbitrage?.position ?? status?.position ?? null;
  const team = tier?.team ?? arbitrage?.team ?? status?.current_team ?? null;
  const gap = selected === null ? null : describeGap(selected.rank_gap);
  // Null under `cross` by construction, and null when the selected market genuinely has no
  // slope yet. Both read as "collecting"; neither borrows another market's number.
  const trend = view === null ? null : describeTrend(view.trend);
  // Labelled by the source the number actually came from. Under the cross-market view the
  // comparison resolves to one real source, and calling that "Cross-market ADP" would name a
  // market the figure did not come from.
  const shownMarket = selected?.source_id ?? market;
  const badge = statusBadge(status);
  const meaningful = hasMeaningfulStatus(status);
  // Build-level market flags — an approximate cohort, a thin cohort, a trend still collecting —
  // describe the board, not the player, and Data explains each one once.
  const flags = explainFlags([
    ...playerLevelFlags(tier?.quality_flags ?? []),
    ...playerLevelFlags(arbitrage?.quality_flags ?? []),
  ]);

  /** Sections actually rendered, in order. The index and the tab list both follow this. */
  const sections: readonly ("intrinsic" | "ros" | "usage" | "market" | "status")[] = [
    ...(tier !== null ? (["intrinsic"] as const) : []),
    ...(ros != null ? (["ros"] as const) : []),
    // One slot, two panels, and the season decides which. See `PlayerDetailData.inSeason`.
    inSeasonCard ? ("usage" as const) : ("market" as const),
    "status",
  ];
  // The tab label is the panel's own heading, word for word: a tab that says something else
  // is a second name for the same thing. It also keeps `Status` unambiguous — that word is the
  // rail's verdict label, and one string should mean one control.
  const tabLabels: Readonly<Record<string, string>> = {
    intrinsic: "Intrinsic value",
    ros: "Rest of season",
    usage: "In-season usage",
    market: "Draft market",
    status: "Current status",
  };
  const activeTab = Math.min(tab, sections.length - 1);

  const sectionNodes = sections.map((kind, position_) => {
    const index = position_ + 1;
    const id = `${baseId}-${kind}`;
    if (kind === "intrinsic" && tier !== null) {
      return (
        <DetailSection key={kind} index={index} id={id} title="Intrinsic value" badge="Model" tabbed={sheet}>
          <div className="readout-grid">
            <Readout
              label="Position rank"
              value={`${tier.position}${formatRank(tier.position_rank)}`}
            />
            <Readout label="Tier" value={tier.tier_label} hint="group, not a cut" />
            <Readout label="Median VORP" value={formatValue(tier.p50_vorp)} hint="P50" strong />
            <Readout label="Uncertainty" value={formatValue(tier.uncertainty)} hint="points" />
            <Readout label="Expected VORP" value={formatValue(tier.expected_vorp)} />
            <Readout
              label="P25 – P75 VORP"
              value={`${formatValue(tier.p25_vorp)} – ${formatValue(tier.p75_vorp)}`}
            />
            <Readout label="Expected points" value={formatValue(tier.expected_points)} />
            {projection !== null && (
              <Readout
                label="P25 – P75 points"
                value={`${formatValue(projection.p25_points)} – ${formatValue(projection.p75_points)}`}
              />
            )}
            {projection?.expected_games !== null && projection?.expected_games !== undefined && (
              <Readout label="Expected games" value={formatValue(projection.expected_games)} />
            )}
          </div>
          <Distribution
            title="Simulated VORP · P10 → P90"
            meta={`Position rank ${tier.position}${formatRank(tier.position_rank)}`}
            p10={tier.p10_vorp}
            p25={tier.p25_vorp}
            p50={tier.p50_vorp}
            p75={tier.p75_vorp}
            p90={tier.p90_vorp}
          />
        </DetailSection>
      );
    }
    if (kind === "ros" && ros != null) {
      /*
        The roadmap's own recommended panel, in its own section: preseason fair rank, current
        rest-of-season fair rank, and the change between them — three readouts rather than one,
        because the useful fact is that two *different* quantities disagree, and a single
        "rank" would erase that. The change is labelled as a difference between two models'
        orderings wherever it appears.
      */
      return (
        <DetailSection
          key={kind}
          index={index}
          id={id}
          title="Rest of season"
          badge={`Week ${String(ros.through_week)}`}
          tabbed={sheet}
        >
          {/*
            The two ranks, and the distance between them as a picture rather than as a third
            digit. The board a reader just left is 500 rows deep; "+185" says how far he moved
            and nothing about how far that is, which is the whole difference between a number
            and a reading.
          */}
          <RankShift
            from={ros.preseason_fair_rank ?? null}
            to={ros.ros_fair_rank}
            depth={cohort?.boardDepth ?? null}
            change={ros.fair_rank_change ?? null}
            labels={{
              from: formatRank(ros.preseason_fair_rank),
              to: formatRank(ros.ros_fair_rank),
              change: rankChangeLabel(ros.fair_rank_change),
            }}
            position={ros.position}
            inPreseasonUniverse={ros.in_preseason_universe}
          />

          <div className="readout-grid">
            <Readout
              label="ROS position rank"
              value={`${ros.position}${formatRank(ros.ros_position_rank)}`}
            />
            <Readout
              label="ROS tier"
              value={ros.ros_tier_label ?? EM_DASH}
              hint={
                cohort?.tier == null
                  ? "band, not a cut"
                  : `${ordinal(cohort.tier.place)} of ${String(cohort.tier.size)} · band, not a cut`
              }
            />
            <Readout label="ROS median VORP" value={formatValue(ros.ros_vorp_p50)} hint="P50" strong />
            <Readout
              label="ROS P25 – P75 VORP"
              value={`${formatValue(ros.ros_vorp_p25)} – ${formatValue(ros.ros_vorp_p75)}`}
            />
            <Readout label="Remaining points" value={formatValue(ros.ros_expected_points)} />
            <Readout
              label="Remaining games"
              value={ros.ros_expected_games.toFixed(1)}
              hint={
                ros.team_remaining_scheduled_games == null
                  ? "expected appearances"
                  : `of ${String(ros.team_remaining_scheduled_games)} team games left`
              }
            />
            {/* The number the owner's review named. It is the P25–P75 width and nothing else,
                so the hint says so and the strip below gives it the scale a digit cannot. */}
            <Readout
              label="ROS uncertainty"
              value={formatValue(ros.ros_uncertainty)}
              hint="P25 – P75 width"
            />
            <Readout
              label="Weeks remaining"
              value={
                ros.remaining_horizon_weeks === undefined
                  ? EM_DASH
                  : String(ros.remaining_horizon_weeks)
              }
              hint="in the horizon"
            />
            {/* Production lives in `In-season usage`, which is not rendered on a card opened
                from the draft board. There it has nowhere else to be, so it stays here. */}
            {!inSeasonCard && (
              <>
                <Readout label="Games played to date" value={formatValue(ros.games_played_to_date)} />
                <Readout
                  label="Weeks since last game"
                  value={
                    ros.has_played_this_season
                      ? String(Math.round(ros.weeks_since_last_game))
                      : "No appearances"
                  }
                />
              </>
            )}
          </div>
          <Distribution
            title="Simulated remaining VORP · P10 → P90"
            meta={`Through week ${String(ros.through_week)}`}
            p10={ros.ros_vorp_p10}
            p25={ros.ros_vorp_p25}
            p50={ros.ros_vorp_p50}
            p75={ros.ros_vorp_p75}
            p90={ros.ros_vorp_p90}
          />
          {/* The scale the three headline numbers above are missing. "82.1" is not a reading;
              "the ninth-widest interval of the ninety-six WRs on this board" is the same
              published number and an answer. */}
          <CohortStrip
            title={
              cohort === null
                ? "Value against this board"
                : `Value against the ${cohort.noun} on this board`
            }
            noun={cohort?.noun ?? "players"}
            rows={[
              {
                key: "vorp",
                label: "ROS median VORP",
                stat: cohort?.vorp ?? null,
                format: formatValue,
              },
              {
                key: "points",
                label: "Remaining points",
                stat: cohort?.remainingPoints ?? null,
                format: formatValue,
              },
              {
                key: "uncertainty",
                label: "ROS uncertainty",
                stat: cohort?.uncertainty ?? null,
                format: formatValue,
                qualifier: "widest",
              },
            ]}
            position={ros.position}
          />
          {ros.long_absence && (
            <div className="notice" data-severity="info" role="note" style={{ marginTop: "0.75rem" }}>
              <strong>{longAbsenceLabel(ros)}</strong>
              <p style={{ marginTop: "0.5rem" }}>
                {rosDisclosures?.long_absence_statement ??
                  "This estimate uses no injury or practice-report information."}
              </p>
              <p style={{ marginTop: "0.5rem" }}>
                {rosDisclosures?.long_absence_ordering_weakness ??
                  "Ranking quality inside this group is weak."}
              </p>
            </div>
          )}
        </DetailSection>
      );
    }
    if (kind === "usage" && ros != null) {
      return (
        <DetailSection
          key={kind}
          index={index}
          id={id}
          title="In-season usage"
          badge={
            <>
              <span className="detail-badge-label">Observed</span>
              {opportunity?.behavior_available === true
                ? `${opportunity.behavior_source_id ?? "feed"} · ${
                    opportunity.behavior_lookback_hours == null
                      ? "window unknown"
                      : `${String(opportunity.behavior_lookback_hours)}h`
                  }`
                : "no behaviour feed"}
            </>
          }
          tabbed={sheet}
        >
          <InSeasonUsage
            ros={ros}
            opportunity={opportunity ?? null}
            behavior={data.behavior ?? null}
            cohort={cohort}
          />
        </DetailSection>
      );
    }
    if (kind === "market") {
      return (
        <DetailSection
          key={kind}
          index={index}
          id={id}
          title="Draft market"
          badgeTone={arbitrage === null ? undefined : "warn"}
          /*
           * The design source's section badge reads "MEDIUM CONFIDENCE". The word "confidence"
           * on its own is the misreading ADR-041 exists to prevent — it is market-*data*
           * quality, not a probability about the player — so the badge keeps Phase 8's label
           * and takes the design's meter and sample count.
           */
          badge={
            arbitrage === null ? undefined : (
              <>
                <span className="detail-badge-label">Market data</span>
                {/* The count is source-specific — FFC's rolling window and MyFantasyLeague's
                    season aggregate are backed by different numbers of drafts — so it comes
                    from the selected market rather than from the flat V1 field. A market
                    that publishes no count says so instead of borrowing one. */}
                <ConfidenceMeter
                  confidence={arbitrage.confidence}
                  label={`${CONFIDENCE_SHORT[arbitrage.confidence]} · ${
                    selected?.market_sample_size == null
                      ? "sample not published"
                      : `${formatInteger(selected.market_sample_size)} drafts`
                  }`}
                />
              </>
            )
          }
          tabbed={sheet}
        >
          {arbitrage === null ? (
            <p className="detail-empty">
              {data.marketAvailable
                ? `No current ${marketLabel(market)} ADP. He is fully ranked on the tier board; there is simply no market price to compare against.`
                : "The market comparison is unavailable for this build."}
            </p>
          ) : selected === null ? (
            /*
             * The selected market did not price him — and another one may well have. Saying
             * so, and then still listing every market that did, is the whole difference
             * between an honest absence and the em dash that used to be a borrowed number:
             * the readouts are this market's, so they are withheld; the table is every
             * market's, so it stays, however short it is (ADR-081).
             */
            <>
              <p className="detail-empty">
                {`No current ${marketLabel(market)} ADP for him. He is fully ranked on the tier board, and the markets that do price him are below.`}
              </p>
              <MarketComparisonTable
                name={name}
                fairRank={arbitrage.fair_rank}
                markets={everyMarket}
                consensus={consensus}
                cross={cross}
                selection={market}
              />
            </>
          ) : (
            <>
              {gap !== null && (
                <div className="market-verdict" data-kind={gap.kind}>
                  <strong>{gap.sentence}</strong>{" "}
                  {trend !== null && trend.direction !== "unknown" && <span>{trend.text}</span>}
                </div>
              )}
              <div className="readout-grid">
                <Readout
                  label={`${marketLabel(shownMarket)} ADP`}
                  value={formatAdp(selected.market_adp)}
                  hint={data.cohortExact === false ? "approximate cohort" : undefined}
                  strong
                />
                <Readout label="Market rank" value={formatRank(selected.market_rank)} />
                <Readout
                  label="Value gap"
                  value={formatSigned(selected.rank_gap)}
                  kind={gap?.kind}
                  hint={
                    gap?.kind === "bargain"
                      ? "picks later"
                      : gap?.kind === "premium"
                        ? "picks earlier"
                        : "even"
                  }
                  srSuffix={gap?.sentence}
                />
                {/* `Arbitrage score` is in the identity rail, which every variant renders. One
                    label, one place. */}
                {view?.trendIsScalar === true ? (
                  <Readout
                    label={`${marketLabel(shownMarket)} trend`}
                    value={view.trend === null ? EM_DASH : formatSigned(view.trend, 2)}
                    hint={view.trend === null ? "collecting" : trend?.text}
                    srSuffix={view.trend === null ? "trend collecting" : trend?.text}
                  />
                ) : (
                  /* No market published a cross-market trend, and one source's slope under the
                     word "Cross-market" would name a market the number did not come from. The
                     per-source slopes are in the chart's legend and in the comparison table
                     below, which is where a comparison belongs (ADR-081). */
                  <Readout
                    label="Market trend"
                    value={EM_DASH}
                    hint="per market, below"
                    srSuffix="each market's own trend is listed with its history below"
                  />
                )}
                <Readout
                  label="Aggregation window"
                  value={
                    windowLabel(
                      selected.aggregation_window_type,
                      selected.aggregation_window_days,
                    ) || EM_DASH
                  }
                  size="sm"
                />
              </div>

              {/* The retained observations the slope above was estimated from, as a shape. Up
                  is earlier — the axis is inverted, because a falling line for "the market
                  likes him more" reads backwards (roadmap 10.7). No vendor is called: the
                  points come from the artifact, which came from a retained snapshot. Under the
                  cross-market view every market's real series is drawn on one dated axis;
                  nothing is averaged into a line no capture produced. */}
              <MarketTrend
                series={chartSeries}
                label={market === CROSS_MARKET ? "market" : marketLabel(market)}
              />

              {/* Every market side by side. The expert consensus sits with them and is
                  labelled a ranking, because a reader comparing the model to the experts is
                  asking a different question from one comparing it to a price.

                  Only when there is something to compare: a one-row table directly beneath
                  that market's own readouts is the same numbers twice. */}
              {(Object.keys(everyMarket).length > 1 || consensus !== null) && (
                <MarketComparisonTable
                  name={name}
                  fairRank={arbitrage.fair_rank}
                  markets={everyMarket}
                  consensus={consensus}
                  cross={cross}
                  selection={market}
                />
              )}
              <div className="readout-grid">
                <Readout
                  label="Observed picks"
                  value={
                    selected.market_adp_low === null || selected.market_adp_high === null
                      ? EM_DASH
                      : `${formatAdp(selected.market_adp_low)} – ${formatAdp(selected.market_adp_high)}`
                  }
                  hint="earliest – latest"
                />
                <Readout
                  label="Regional value gap"
                  value={selected.regional_value_gap.toFixed(3)}
                />
                {/* The selected market's own cohort and its own capture time. The flat pair
                    here named MyFantasyLeague's cohort and MyFantasyLeague's snapshot under an
                    FFC heading, which is two sources' provenance in one grid. */}
                <Readout label="Cohort" value={selected.market_cohort_detail} size="sm" />
                <Readout
                  label="Snapshot"
                  value={formatEastern(selected.market_snapshot_at_utc)}
                  hint={marketSourceLabel(selected.source_id)}
                  size="sm"
                />
              </div>
            </>
          )}
        </DetailSection>
      );
    }
    return (
      <DetailSection
        key={kind}
        index={index}
        id={id}
        title="Current status"
        badge="Not in model"
        tabbed={sheet}
      >
        {status === null ? (
          <>
            <p className="status-headline" data-known="false">
              No status record was published for this player
            </p>
            <p className="status-annotation">
              That is the absence of a record, not a report of health.
            </p>
          </>
        ) : (
          <StatusStrip status={status} meaningful={meaningful} />
        )}
      </DetailSection>
    );
  });

  return (
    <dialog
      className="player-detail"
      ref={dialogRef}
      aria-labelledby={`${baseId}-title`}
      onClose={onClose}
      onClick={(event) => {
        // Click on the backdrop (the dialog element itself, outside its content) closes.
        if (event.target === dialogRef.current) onClose();
      }}
    >
      <div className="detail-frame chamfer">
        <div className="detail-card chamfer">
          {/*
            The identity rail (artboard 1c). Below 1100px the stylesheet turns it into a header
            band; below 768px it keeps identity and fair rank and the tabs carry the rest. It is
            always in the DOM, so the accessible title never moves.
          */}
          <div className="detail-rail">
            {/*
              The portrait leads the rail on the wide variant and sits left of the identity
              block on the two narrow ones — one DOM position serves all three, because the
              rail is a column at 1c and a row at 1a/1b and "first" reads correctly either
              way. It is the only element on the page that fetches from another origin, and
              it exists only while this dialog is open (ADR-087).
            */}
            <PlayerPortrait
              name={name}
              position={position}
              imageUrl={data.headshotUrl ?? null}
            />
            <div className="detail-identity-block">
              {position !== null && (
                <span className="detail-eyebrow">
                  {position}
                  {team === null ? "" : ` · ${team}`}
                </span>
              )}
              <div className="detail-identity">
                <h2 id={`${baseId}-title`}>{name}</h2>
                <div className="detail-subtitle">
                  {position !== null && <PositionTag position={position} />}
                  {inSeasonCard && ros != null ? (
                    <span className="detail-posrank">
                      {ros.position}
                      {formatRank(ros.ros_position_rank)}
                    </span>
                  ) : (
                    tier !== null && (
                      <span className="detail-posrank">
                        {tier.position}
                        {formatRank(tier.position_rank)}
                      </span>
                    )
                  )}
                  {team !== null && <span className="detail-posrank">{team}</span>}
                  {inSeasonCard && ros != null
                    ? ros.ros_tier_label !== null && <TierTag label={ros.ros_tier_label} />
                    : tier !== null && <TierTag label={tier.tier_label} />}
                  <StatusBadge status={status} />
                </div>
              </div>
            </div>

            {/*
              The one number the card is organised around, and in season that is not the draft
              one. A rest-of-season rank comes from a different model over a different horizon
              (ADR-071), so the label changes with it rather than the value quietly swapping
              underneath a heading that would then be wrong.
            */}
            {inSeasonCard && ros != null ? (
              <div className="rail-hero">
                <span className="rail-hero-label">ROS rank</span>
                <span className="rail-hero-value">{formatRank(ros.ros_fair_rank)}</span>
                <span className="rail-hero-note">median simulated remaining VORP</span>
              </div>
            ) : (
              tier !== null && (
                <div className="rail-hero">
                  <span className="rail-hero-label">Fair rank</span>
                  <span className="rail-hero-value">{formatRank(tier.fair_rank)}</span>
                  <span className="rail-hero-note">median simulated VORP</span>
                </div>
              )
            )}

            {/* The three things a reader looks at first, before any grid. Which three depends
                on the season: a draft price and an arbitrage score answer a question that
                closed in September, so in season they are what the wire is doing instead
                (ADR-085). */}
            <div className="rail-verdict">
              {inSeasonCard && ros != null ? (
                <>
                  <div>
                    <span className="rail-verdict-label">Since preseason</span>
                    <span
                      className="rail-verdict-value"
                      data-kind={
                        ros.fair_rank_change == null || ros.fair_rank_change === 0
                          ? undefined
                          : ros.fair_rank_change > 0
                            ? "bargain"
                            : "premium"
                      }
                    >
                      {rankChangeLabel(ros.fair_rank_change)}
                    </span>
                    <span className="rail-verdict-note">
                      a different model over a different horizon
                    </span>
                  </div>
                  {opportunity?.behavior_available === true && (
                    <div>
                      <span className="rail-verdict-label">
                        {`Net adds${
                          opportunity.behavior_lookback_hours == null
                            ? ""
                            : ` · ${String(opportunity.behavior_lookback_hours)}h`
                        }`}
                      </span>
                      <span
                        className="rail-verdict-value"
                        data-kind={
                          opportunity.net_add_count == null || opportunity.net_add_count === 0
                            ? undefined
                            : opportunity.net_add_count > 0
                              ? "bargain"
                              : "premium"
                        }
                      >
                        {opportunity.net_add_count == null
                          ? EM_DASH
                          : opportunity.net_add_count > 0
                            ? `+${formatInteger(opportunity.net_add_count)}`
                            : formatInteger(opportunity.net_add_count)}
                      </span>
                      <span className="rail-verdict-note">transactions, not a price</span>
                    </div>
                  )}
                </>
              ) : (
                <>
                  {selected !== null && gap !== null && (
                    <div>
                      {/* The number and the sentence must be the same market's. The rail
                          printed the flat V1 gap — MyFantasyLeague's — beneath a sentence
                          computed from the selected market, so with FFC selected the two
                          disagreed (ADR-081). */}
                      <span className="rail-verdict-label">
                        {`${marketLabel(selected.source_id)} verdict`}
                      </span>
                      <span className="rail-verdict-value" data-kind={gap.kind}>
                        {`${formatSigned(selected.rank_gap)} ${
                          gap.kind === "bargain"
                            ? "later"
                            : gap.kind === "premium"
                              ? "earlier"
                              : "even"
                        }`}
                      </span>
                      <span className="rail-verdict-note">{gap.sentence}</span>
                    </div>
                  )}
                  {arbitrage !== null && (
                    <div>
                      <span className="rail-verdict-label">Arbitrage score</span>
                      <span className="rail-verdict-value" data-kind="accent">
                        {formatScore(arbitrage.arbitrage_score)}
                      </span>
                    </div>
                  )}
                </>
              )}
              <div>
                <span className="rail-verdict-label">Status</span>
                <span className="rail-status" data-meaningful={meaningful}>
                  {badge === null
                    ? status === null
                      ? "No record published"
                      : "No designation reported"
                    : badge.full}
                </span>
              </div>
            </div>
          </div>

          <div className="detail-main">
            <div className="detail-head">
              <button
                type="button"
                className="detail-close"
                onClick={onClose}
                aria-label="Close player detail"
              >
                <span className="detail-close-glyph" aria-hidden="true">
                  ✕
                </span>
                <span aria-hidden="true">Esc</span>
              </button>
            </div>

            {/*
              Artboard 1b's tab bar, on the sheet variant only. On wider viewports every
              section is on screen at once, so a tab list would be three controls that
              hide two thirds of what is already visible.
            */}
            {sheet && (
              <div className="detail-tabs" role="tablist" aria-label="Player detail">
                {sections.map((kind, index) => (
                  <button
                    key={kind}
                    type="button"
                    role="tab"
                    id={`${baseId}-${kind}-tab`}
                    aria-selected={index === activeTab}
                    aria-controls={`${baseId}-${kind}-panel`}
                    tabIndex={index === activeTab ? 0 : -1}
                    onKeyDown={(event) => {
                      const step =
                        event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
                      if (step === 0) return;
                      event.preventDefault();
                      setTab((current) => (current + step + sections.length) % sections.length);
                    }}
                    onClick={() => {
                      setTab(index);
                    }}
                  >
                    {tabLabels[kind]}
                  </button>
                ))}
              </div>
            )}

            {/*
              `tabIndex` because this is the card's scroll container: a region that scrolls but
              cannot be focused is unreachable for anyone driving the page from the keyboard,
              which axe reports as `scrollable-region-focusable`. The dialog's own accessible
              name covers it, so it needs no second label.
            */}
            <div className="detail-body" tabIndex={0}>
              {sheet ? sectionNodes[activeTab] : sectionNodes}

              {flags.length > 0 && (
                <details className="detail-more">
                  <summary>Data-quality flags on this player</summary>
                  <FlagList flags={flags} />
                </details>
              )}
            </div>

            <div className="detail-foot">
              <span className="detail-foot-stamp">
                {inSeasonCard && ros != null
                  ? `Rest-of-season values through week ${String(ros.through_week)}`
                  : selected === null
                    ? "Intrinsic values from this build"
                    : `${marketLabel(selected.source_id)} snapshot ${formatEastern(selected.market_snapshot_at_utc)}`}
              </span>
              {onOpenData !== undefined && (
                <p className="detail-methodology">
                  <button
                    type="button"
                    className="button-link"
                    onClick={() => {
                      onClose();
                      onOpenData();
                    }}
                  >
                    Definitions and methodology
                  </button>
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </dialog>
  );
}

/**
 * The current-status strip.
 *
 * Fields, not prose. "None reported" is the absence of a designation and never the word
 * "healthy"; Data carries the standing explanation that none of this entered the projection.
 */
function StatusStrip({
  status,
  meaningful,
}: {
  readonly status: PlayerStatusRecord;
  readonly meaningful: boolean;
}): React.JSX.Element {
  return (
    <div className="status-strip">
      <p className="status-headline" data-meaningful={meaningful}>
        {meaningful
          ? `${status.injury_status ?? "Designation"} reported`
          : "No injury designation reported"}
      </p>
      <div className="readout-grid">
        <OptionalReadout label="Current team" value={status.current_team} />
        <OptionalReadout label="Injury" value={status.injury_status} />
        <OptionalReadout label="Body part" value={status.injury_body_part} />
        <OptionalReadout label="Reported" value={status.injury_start_date} />
        <OptionalReadout label="Practice" value={status.practice_participation} />
        <OptionalReadout label="Practice detail" value={status.practice_description} />
        <OptionalReadout label="Sleeper" value={status.sleeper_status} />
        <OptionalReadout
          label="Roster"
          value={isNoteworthyRosterStatus(status.roster_status) ? status.roster_status : null}
        />
        <OptionalReadout label="Depth chart" value={status.depth_chart_position} />
        <OptionalReadout
          label="Depth order"
          value={status.depth_chart_order === null ? null : `#${String(status.depth_chart_order)}`}
        />
        <Readout label="Observed" value={formatEastern(status.observed_at_utc)} />
      </div>
      {status.injury_notes !== null && <p className="status-note">{status.injury_notes}</p>}
      <p className="annotation status-annotation">Annotation only — not a model input.</p>
    </div>
  );
}

function FlagList({
  flags,
}: {
  readonly flags: readonly { flag: string; label: string; detail: string }[];
}): React.JSX.Element {
  return (
    <ul className="flag-list">
      {flags.map((entry) => (
        <li key={entry.flag}>
          <span className="flag-name">{entry.label}.</span>{" "}
          <span className="muted">{entry.detail}</span>
        </li>
      ))}
    </ul>
  );
}
