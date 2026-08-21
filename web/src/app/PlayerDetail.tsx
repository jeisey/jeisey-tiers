/**
 * One player-detail surface, reachable from every board.
 *
 * The Tier table, the Tier Board, the Arbitrage table and the Draft Rail all open this same
 * dialog. There is deliberately no second tooltip system: a hover-only affordance would put
 * the intrinsic, market and status detail out of reach on a phone and behind a mouse for
 * keyboard users, and the UX spec requires no core function depend on hover.
 *
 * The status section carries a standing disclosure. `player_status.json` describes *today*;
 * the projection beside it never saw it (ADR-043). Nothing in this file says the model
 * accounts for an injury, adjusts for one, prices one in, or lost confidence because of one,
 * because none of that happened.
 */

import { useEffect, useRef } from "react";

import { PositionTag, TierTag } from "../components/primitives";
import type {
  ArbitrageRecord,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  TierRecord,
} from "../data/contracts";
import { EM_DASH, formatAdp, formatEastern, formatInteger, formatRank, formatScore, formatSigned, formatValue } from "../data/format";
import { explainFlags } from "../data/flags";
import { CONFIDENCE_MEANING, CONFIDENCE_LABELS, describeGap, describeTrend, marketSourceLabel, TREND_UNAVAILABLE_EXPLANATION } from "../data/market";
import { hasMeaningfulStatus, isNoteworthyRosterStatus } from "../data/model";

export interface PlayerDetailData {
  readonly playerId: string;
  readonly tier: TierRecord | null;
  readonly arbitrage: ArbitrageRecord | null;
  readonly status: PlayerStatusRecord | null;
  readonly projection: PlayerProjectionRecord | null;
  /** True when the arbitrage artifact loaded but holds no row for this player. */
  readonly marketAvailable: boolean;
}

export const ANNOTATION_DISCLOSURE =
  "Current status annotation — not included in the projection or the model.";

function Fact({
  label,
  children,
}: {
  readonly label: string;
  readonly children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Fields Sleeper publishes as keys with null values in the preseason are simply left out. */
function OptionalFact({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string | number | null | undefined;
}): React.JSX.Element | null {
  if (value === null || value === undefined || value === "") return null;
  return <Fact label={label}>{value}</Fact>;
}

export function PlayerDetail({
  data,
  onClose,
}: {
  readonly data: PlayerDetailData | null;
  readonly onClose: () => void;
}): React.JSX.Element | null {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;
    if (data !== null && !dialog.open) {
      // `showModal` gives focus trapping, Escape-to-close and inert background for free, which
      // is a great deal more correct than any hand-rolled overlay.
      dialog.showModal();
    }
    if (data === null && dialog.open) dialog.close();
  }, [data]);

  if (data === null) return null;

  const { tier, arbitrage, status, projection } = data;
  const name = tier?.display_name ?? arbitrage?.display_name ?? status?.display_name ?? "Player";
  const position = tier?.position ?? arbitrage?.position ?? status?.position ?? null;
  const team = tier?.team ?? arbitrage?.team ?? status?.current_team ?? null;
  const gap = arbitrage === null ? null : describeGap(arbitrage.rank_gap);
  const trend = arbitrage === null ? null : describeTrend(arbitrage.market_trend);
  const intrinsicFlags = explainFlags(tier?.quality_flags ?? []);
  const marketFlags = explainFlags(arbitrage?.quality_flags ?? []);

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
      <div className="detail-head">
        <div>
          <h2 id="player-detail-title">{name}</h2>
          <div className="detail-subtitle">
            {position !== null && <PositionTag position={position} />}
            {tier !== null && (
              <span>
                {tier.position}
                {formatRank(tier.position_rank)}
              </span>
            )}
            {team !== null && <span>{team}</span>}
            {tier !== null && <TierTag label={tier.tier_label} />}
          </div>
        </div>
        <button type="button" className="detail-close" onClick={onClose} aria-label="Close player detail">
          Close
        </button>
      </div>

      <div className="detail-body">
        {tier !== null && (
          <section className="detail-group">
            <h3>Intrinsic value</h3>
            <dl className="facts">
              <Fact label="Fair rank">{formatRank(tier.fair_rank)}</Fact>
              <Fact label="Position rank">
                {tier.position}
                {formatRank(tier.position_rank)}
              </Fact>
              <Fact label="Tier group">{tier.tier_label}</Fact>
              <Fact label="Expected VORP">{formatValue(tier.expected_vorp)}</Fact>
              <Fact label="Median VORP (P50)">{formatValue(tier.p50_vorp)}</Fact>
              <Fact label="P25 – P75 VORP">
                {`${formatValue(tier.p25_vorp)} – ${formatValue(tier.p75_vorp)}`}
              </Fact>
              <Fact label="P10 – P90 VORP">
                {`${formatValue(tier.p10_vorp)} – ${formatValue(tier.p90_vorp)}`}
              </Fact>
              <Fact label="Expected fantasy points">{formatValue(tier.expected_points)}</Fact>
              <Fact label="Uncertainty">{formatValue(tier.uncertainty)}</Fact>
              {projection !== null && (
                <OptionalFact
                  label="Expected games"
                  value={
                    projection.expected_games === null || projection.expected_games === undefined
                      ? null
                      : formatValue(projection.expected_games)
                  }
                />
              )}
              {projection !== null && (
                <Fact label="P25 – P75 points">
                  {`${formatValue(projection.p25_points)} – ${formatValue(projection.p75_points)}`}
                </Fact>
              )}
            </dl>
            <p className="annotation-note">
              Fair rank is median simulated VORP. Tier groups are useful; exact tier edges are
              statistically soft, so treat a player either side of an edge as comparable.
            </p>
            {intrinsicFlags.length > 0 && <FlagList flags={intrinsicFlags} />}
          </section>
        )}

        <section className="detail-group">
          <h3>Draft market</h3>
          {arbitrage === null ? (
            <p className="muted">
              {data.marketAvailable
                ? "No current MyFantasyLeague ADP. He is fully ranked on the tier board; there is simply no market price to compare against."
                : "The market comparison is unavailable for this build."}
            </p>
          ) : (
            <>
              <dl className="facts">
                <Fact label={marketSourceLabel(arbitrage.market_source_id)}>
                  {formatAdp(arbitrage.market_adp)}
                </Fact>
                <Fact label="Market rank">{formatRank(arbitrage.market_rank)}</Fact>
                <Fact label="Rank gap">
                  <span className="dir" data-kind={gap?.kind}>
                    {formatSigned(arbitrage.rank_gap)}
                  </span>
                </Fact>
                <Fact label="Regional value gap">{arbitrage.regional_value_gap.toFixed(3)}</Fact>
                <Fact label="Arbitrage score">{formatScore(arbitrage.arbitrage_score)}</Fact>
                <Fact label="Drafts priced">{formatInteger(arbitrage.market_sample_size)}</Fact>
                <Fact label="Observed pick range">
                  {arbitrage.market_adp_low === null || arbitrage.market_adp_high === null
                    ? EM_DASH
                    : `${formatAdp(arbitrage.market_adp_low)} – ${formatAdp(arbitrage.market_adp_high)}`}
                </Fact>
                <Fact label="Market trend">
                  {arbitrage.market_trend === null ? EM_DASH : formatSigned(arbitrage.market_trend, 2)}
                </Fact>
                <Fact label="Market-data confidence">{CONFIDENCE_LABELS[arbitrage.confidence]}</Fact>
                <Fact label="Cohort">{arbitrage.market_cohort_detail}</Fact>
                <Fact label="Snapshot taken">{formatEastern(arbitrage.market_snapshot_at_utc)}</Fact>
              </dl>
              <p className="annotation-note">
                {gap?.sentence}{" "}
                {trend?.direction === "unknown" ? TREND_UNAVAILABLE_EXPLANATION : trend?.text}{" "}
                {CONFIDENCE_MEANING}
              </p>
              {marketFlags.length > 0 && <FlagList flags={marketFlags} />}
            </>
          )}
        </section>

        <section className="detail-group">
          <h3>Current status</h3>
          {status === null ? (
            <p className="muted">
              No current status record was published for this player, so there is no roster,
              depth-chart or injury annotation to show.
            </p>
          ) : (
            <>
              <dl className="facts">
                <OptionalFact label="Current team" value={status.current_team} />
                <OptionalFact
                  label="Roster status"
                  value={isNoteworthyRosterStatus(status.roster_status) ? status.roster_status : null}
                />
                <OptionalFact label="Sleeper status" value={status.sleeper_status} />
                <OptionalFact label="Injury status" value={status.injury_status} />
                <OptionalFact label="Body part" value={status.injury_body_part} />
                <OptionalFact label="Injury reported" value={status.injury_start_date} />
                <OptionalFact label="Practice" value={status.practice_participation} />
                <OptionalFact label="Practice detail" value={status.practice_description} />
                <OptionalFact label="Depth chart" value={status.depth_chart_position} />
                <OptionalFact
                  label="Depth order"
                  value={status.depth_chart_order === null ? null : `#${String(status.depth_chart_order)}`}
                />
                <Fact label="Observed">{formatEastern(status.observed_at_utc)}</Fact>
              </dl>
              {status.injury_notes !== null && <p className="muted">{status.injury_notes}</p>}
              {!hasMeaningfulStatus(status) && (
                <p className="muted">
                  No injury designation is currently reported for this player. That is the absence
                  of a report, not a clearance.
                </p>
              )}
              <p className="annotation-note">
                <strong>{ANNOTATION_DISCLOSURE}</strong> The board above was produced without any
                of these fields. Source: {status.source_ids.join(", ")}.
              </p>
            </>
          )}
        </section>
      </div>
    </dialog>
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
