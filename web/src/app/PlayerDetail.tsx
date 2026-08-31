/**
 * One player-detail surface, reachable from every board.
 *
 * The Tier table, the Tier Board, the Arbitrage table and the Draft Rail all open this same
 * dialog. There is deliberately no second tooltip system: a hover-only affordance would put
 * the intrinsic, market and status detail out of reach on a phone and behind a mouse for
 * keyboard users, and the UX spec requires no core function depend on hover.
 *
 * **What changed in Phase 8.** The card used to end each of its three sections with a
 * paragraph of methodology — what `confidence` is a statement about, why the cohort is
 * approximate, and the standing disclosure that current status is annotation only. All three
 * are true and none of them is about *this* player, so on a three-hundred-player board they
 * were three hundred copies of the same three paragraphs. They now live once in Data, and
 * this card leads with what a drafter needs while the pick clock is running: rank, tier,
 * value, uncertainty, price, gap, score, trend, and any current designation.
 *
 * Truthfulness is unchanged, only repetition. Two things that are easy to get wrong and are
 * therefore still explicit *here*:
 *
 * - a status row reading "none reported" is the absence of a report, not a clearance — the
 *   word "healthy" appears nowhere in this product (ADR-043);
 * - `Market data` is a statement about how much draft evidence stands behind the price, not
 *   a probability and not model confidence (ADR-041). The card labels it "Market data" for
 *   that reason and Data carries the rubric.
 *
 * The responsive treatment is one DOM with two presentations (`web/src/styles/base.css`): a
 * centred HUD card where there is width for it, and a full-height sheet on a phone. Native
 * `<dialog>` + `showModal()` keeps focus trapping, Escape and an inert background in both.
 */

import { useEffect, useRef } from "react";

import { PositionTag, StatusBadge, TierTag } from "../components/primitives";
import type {
  ArbitrageRecord,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  TierRecord,
} from "../data/contracts";
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
import { explainFlags, playerLevelFlags } from "../data/flags";
import { CONFIDENCE_SHORT, describeGap, describeTrend, marketSourceLabel } from "../data/market";
import { hasMeaningfulStatus, isNoteworthyRosterStatus } from "../data/model";

export interface PlayerDetailData {
  readonly playerId: string;
  readonly tier: TierRecord | null;
  readonly arbitrage: ArbitrageRecord | null;
  readonly status: PlayerStatusRecord | null;
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
}

/**
 * A labelled numeric readout — the unit of the HUD.
 *
 * `strong` promotes the two values a drafter reads first. `hint` is at most three words; it
 * is not a place for methodology.
 */
function Readout({
  label,
  value,
  hint,
  kind,
  strong = false,
  srSuffix,
}: {
  readonly label: string;
  readonly value: React.ReactNode;
  readonly hint?: string | undefined;
  readonly kind?: "bargain" | "premium" | "even" | undefined;
  readonly strong?: boolean;
  /** Extra words for assistive technology only, when the visible value is a glyph or sign. */
  readonly srSuffix?: string | undefined;
}): React.JSX.Element {
  return (
    <div className="readout" data-strong={strong} data-kind={kind}>
      <span className="readout-label">{label}</span>
      <span className="readout-value">
        {value}
        {srSuffix !== undefined && <span className="visually-hidden">{` ${srSuffix}`}</span>}
      </span>
      {hint !== undefined && <span className="readout-hint">{hint}</span>}
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

  useEffect(() => {
    if (data !== null) return;
    const target = returnFocusTo.current;
    returnFocusTo.current = null;
    if (target?.isConnected === true) target.focus();
  }, [data]);

  if (data === null) return null;

  const { tier, arbitrage, status, projection } = data;
  const name = tier?.display_name ?? arbitrage?.display_name ?? status?.display_name ?? "Player";
  const position = tier?.position ?? arbitrage?.position ?? status?.position ?? null;
  const team = tier?.team ?? arbitrage?.team ?? status?.current_team ?? null;
  const gap = arbitrage === null ? null : describeGap(arbitrage.rank_gap);
  const trend = arbitrage === null ? null : describeTrend(arbitrage.market_trend);
  // Build-level market flags — an approximate cohort, a thin cohort, a trend still
  // collecting — describe the board, not the player, and Data explains each one once.
  const intrinsicFlags = explainFlags(playerLevelFlags(tier?.quality_flags ?? []));
  const marketFlags = explainFlags(playerLevelFlags(arbitrage?.quality_flags ?? []));

  return (
    <dialog
      className="player-detail"
      ref={dialogRef}
      aria-labelledby="player-detail-title"
      onClose={onClose}
      onClick={(event) => {
        // Click on the backdrop (the dialog element itself, outside its content) closes.
        if (event.target === dialogRef.current) onClose();
      }}
    >
      <div className="detail-card">
        <header className="detail-head">
          <div className="detail-identity">
            <h2 id="player-detail-title">{name}</h2>
            <div className="detail-subtitle">
              {position !== null && <PositionTag position={position} />}
              {tier !== null && (
                <span className="detail-posrank">
                  {tier.position}
                  {formatRank(tier.position_rank)}
                </span>
              )}
              {team !== null && <span>{team}</span>}
              {tier !== null && <TierTag label={tier.tier_label} />}
              <StatusBadge status={status} />
            </div>
          </div>
          <button
            type="button"
            className="detail-close"
            onClick={onClose}
            aria-label="Close player detail"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </header>

        <div className="detail-body">
          {tier !== null && (
            <div className="readout-grid readout-grid-primary">
              <Readout label="Fair rank" value={formatRank(tier.fair_rank)} strong />
              <Readout
                label="Position rank"
                value={`${tier.position}${formatRank(tier.position_rank)}`}
              />
              <Readout label="Tier" value={tier.tier_label} hint="group, not a cut" />
              <Readout label="Median VORP" value={formatValue(tier.p50_vorp)} strong />
              <Readout
                label="P25 – P75"
                value={`${formatValue(tier.p25_vorp)} – ${formatValue(tier.p75_vorp)}`}
              />
              <Readout label="Uncertainty" value={formatValue(tier.uncertainty)} hint="points" />
            </div>
          )}

          {arbitrage !== null && (
            <div className="readout-grid readout-grid-market">
              <Readout
                label="MFL ADP"
                value={formatAdp(arbitrage.market_adp)}
                hint={data.cohortExact === false ? "approximate cohort" : undefined}
                strong
              />
              <Readout
                label="Value gap"
                value={formatSigned(arbitrage.rank_gap)}
                kind={gap?.kind}
                hint={gap?.kind === "bargain" ? "picks later" : gap?.kind === "premium" ? "picks earlier" : "even"}
                srSuffix={gap?.sentence}
              />
              <Readout label="Arbitrage score" value={formatScore(arbitrage.arbitrage_score)} strong />
              <Readout
                label="Market trend"
                value={
                  arbitrage.market_trend === null
                    ? EM_DASH
                    : formatSigned(arbitrage.market_trend, 2)
                }
                hint={trend?.direction === "unknown" ? "collecting" : trend?.text}
                srSuffix={trend?.direction === "unknown" ? "trend collecting" : trend?.text}
              />
              <Readout
                label="Market data"
                value={CONFIDENCE_SHORT[arbitrage.confidence]}
                hint={`${formatInteger(arbitrage.market_sample_size)} drafts`}
                srSuffix="market-data quality, not a probability"
              />
              <Readout
                label="Observed picks"
                value={
                  arbitrage.market_adp_low === null || arbitrage.market_adp_high === null
                    ? EM_DASH
                    : `${formatAdp(arbitrage.market_adp_low)} – ${formatAdp(arbitrage.market_adp_high)}`
                }
                hint="earliest – latest"
              />
            </div>
          )}

          {arbitrage === null && (
            <p className="detail-empty muted">
              {data.marketAvailable
                ? "No current MyFantasyLeague ADP. He is fully ranked on the tier board; there is simply no market price to compare against."
                : "The market comparison is unavailable for this build."}
            </p>
          )}

          {/* A player with *no* status record is not the same as a player with a record and
              no designation, and neither is the same as good news. Both say so, briefly. */}
          {status !== null ? (
            <StatusStrip status={status} />
          ) : (
            <div className="status-strip" data-meaningful="false">
              <span className="status-strip-label">Current status</span>
              <p className="status-note">No status record was published for this player.</p>
            </div>
          )}

          <details className="detail-more">
            <summary>Full simulation and market evidence</summary>
            <div className="readout-grid readout-grid-more">
              {tier !== null && (
                <>
                  <Readout label="Expected VORP" value={formatValue(tier.expected_vorp)} />
                  <Readout
                    label="P10 – P90 VORP"
                    value={`${formatValue(tier.p10_vorp)} – ${formatValue(tier.p90_vorp)}`}
                  />
                  <Readout label="Expected points" value={formatValue(tier.expected_points)} />
                </>
              )}
              {projection !== null && (
                <>
                  <Readout
                    label="P25 – P75 points"
                    value={`${formatValue(projection.p25_points)} – ${formatValue(projection.p75_points)}`}
                  />
                  {projection.expected_games !== null && projection.expected_games !== undefined && (
                    <Readout label="Expected games" value={formatValue(projection.expected_games)} />
                  )}
                </>
              )}
              {arbitrage !== null && (
                <>
                  <Readout label="Market rank" value={formatRank(arbitrage.market_rank)} />
                  <Readout
                    label="Regional value gap"
                    value={arbitrage.regional_value_gap.toFixed(3)}
                  />
                  <Readout label="Cohort" value={arbitrage.market_cohort_detail} />
                  <Readout
                    label={marketSourceLabel(arbitrage.market_source_id)}
                    value={formatEastern(arbitrage.market_snapshot_at_utc)}
                    hint="snapshot taken"
                  />
                </>
              )}
              {status !== null && (
                <Readout label="Status observed" value={formatEastern(status.observed_at_utc)} />
              )}
            </div>
            {(intrinsicFlags.length > 0 || marketFlags.length > 0) && (
              <FlagList flags={[...intrinsicFlags, ...marketFlags]} />
            )}
          </details>

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
    </dialog>
  );
}

/**
 * The current-status strip.
 *
 * Fields, not prose. "None reported" is the absence of a designation and never the word
 * "healthy"; Data carries the standing explanation that none of this entered the projection.
 */
function StatusStrip({ status }: { readonly status: PlayerStatusRecord }): React.JSX.Element {
  const meaningful = hasMeaningfulStatus(status);
  return (
    <div className="status-strip" data-meaningful={meaningful}>
      <span className="status-strip-label">Current status</span>
      <div className="readout-grid readout-grid-status">
        {!meaningful && <Readout label="Designation" value="None reported" />}
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
      </div>
      {status.injury_notes !== null && <p className="status-note">{status.injury_notes}</p>}
      <p className="status-annotation">Annotation only — not a model input.</p>
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
          <span className="flag-name">{entry.label}.</span> <span className="muted">{entry.detail}</span>
        </li>
      ))}
    </ul>
  );
}
