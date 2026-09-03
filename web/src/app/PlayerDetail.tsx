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
import { useMediaQuery } from "../components/useMediaQuery";
import { MarketTrend } from "../charts/MarketTrend";
import type {
  ArbitrageRecord,
  MarketTrendSeriesRecord,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  TierRecord,
} from "../data/contracts";
import {
  CROSS_MARKET,
  comparisonFor,
  consensusOf,
  crossMarketOf,
  crossMarketSummaryText,
  marketLabel,
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
import { explainFlags, playerLevelFlags } from "../data/flags";
import { CONFIDENCE_SHORT, describeGap, describeTrend, marketSourceLabel } from "../data/market";
import { hasMeaningfulStatus, isNoteworthyRosterStatus, statusBadge } from "../data/model";

/** The stylesheet's sheet breakpoint. Keep in step with `base.css`. */
const SHEET_QUERY = "(max-width: 767px)";

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
  /** The ADP market the reader has selected. Decides which comparison leads the card. */
  readonly market?: string;
  /** Retained ADP history for that market, or null when there is not enough of it. */
  readonly trendSeries?: MarketTrendSeriesRecord | null;
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

  const { tier, arbitrage, status, projection } = data;
  const market = data.market ?? CROSS_MARKET;
  const selected = arbitrage === null ? null : comparisonFor(arbitrage, market);
  const consensus = arbitrage === null ? null : consensusOf(arbitrage);
  const cross = arbitrage === null ? null : crossMarketOf(arbitrage);
  const everyMarket = arbitrage === null ? {} : marketsOf(arbitrage);
  const name = tier?.display_name ?? arbitrage?.display_name ?? status?.display_name ?? "Player";
  const position = tier?.position ?? arbitrage?.position ?? status?.position ?? null;
  const team = tier?.team ?? arbitrage?.team ?? status?.current_team ?? null;
  const gap = arbitrage === null ? null : describeGap(arbitrage.rank_gap);
  const trend = arbitrage === null ? null : describeTrend(arbitrage.market_trend);
  const badge = statusBadge(status);
  const meaningful = hasMeaningfulStatus(status);
  // Build-level market flags — an approximate cohort, a thin cohort, a trend still collecting —
  // describe the board, not the player, and Data explains each one once.
  const flags = explainFlags([
    ...playerLevelFlags(tier?.quality_flags ?? []),
    ...playerLevelFlags(arbitrage?.quality_flags ?? []),
  ]);

  /** Sections actually rendered, in order. The index and the tab list both follow this. */
  const sections: readonly ("intrinsic" | "market" | "status")[] = [
    ...(tier !== null ? (["intrinsic"] as const) : []),
    "market",
    "status",
  ];
  // The tab label is the panel's own heading, word for word: a tab that says something else
  // is a second name for the same thing. It also keeps `Status` unambiguous — that word is the
  // rail's verdict label, and one string should mean one control.
  const tabLabels: Readonly<Record<string, string>> = {
    intrinsic: "Intrinsic value",
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
                <ConfidenceMeter
                  confidence={arbitrage.confidence}
                  label={`${CONFIDENCE_SHORT[arbitrage.confidence]} · ${formatInteger(arbitrage.market_sample_size)} drafts`}
                />
              </>
            )
          }
          tabbed={sheet}
        >
          {arbitrage === null ? (
            <p className="detail-empty">
              {data.marketAvailable
                ? "No current MyFantasyLeague ADP. He is fully ranked on the tier board; there is simply no market price to compare against."
                : "The market comparison is unavailable for this build."}
            </p>
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
                  label="MFL ADP"
                  value={formatAdp(arbitrage.market_adp)}
                  hint={data.cohortExact === false ? "approximate cohort" : undefined}
                  strong
                />
                <Readout label="Market rank" value={formatRank(arbitrage.market_rank)} />
                <Readout
                  label="Value gap"
                  value={formatSigned(arbitrage.rank_gap)}
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
              </div>

              {/* The same history the slope above was computed from, as a shape. Up is
                  earlier — the axis is inverted, because a falling line for "the market
                  likes him more" reads backwards (roadmap 10.7). No vendor is called: the
                  points come from the artifact, which came from a retained snapshot. */}
              <MarketTrend
                points={data.trendSeries?.points ?? []}
                label={marketLabel(selected?.source_id ?? arbitrage.market_source_id)}
                trend={arbitrage.market_trend}
              />

              {/* Every market side by side. The expert consensus sits with them and is
                  labelled a ranking, because a reader comparing the model to the experts is
                  asking a different question from one comparing it to a price. */}
              {(Object.keys(everyMarket).length > 1 || consensus !== null) && (
                <div className="market-compare">
                  <table className="compare-table">
                    <caption className="visually-hidden">
                      {`Every published market and expert reference for ${name}, each compared with the model's fair rank of ${formatRank(arbitrage.fair_rank)}.`}
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Source</th>
                        <th scope="col">Reading</th>
                        <th scope="col">vs fair rank</th>
                        <th scope="col">Window</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.values(everyMarket)
                        .sort((a, b) => a.source_id.localeCompare(b.source_id))
                        .map((entry) => {
                          const entryGap = describeGap(entry.rank_gap);
                          return (
                            <tr
                              key={entry.source_id}
                              data-selected={entry.source_id === market ? "true" : undefined}
                            >
                              <th scope="row">{marketLabel(entry.source_id)}</th>
                              <td>{`ADP ${formatAdp(entry.market_adp)}`}</td>
                              <td className="dir" data-kind={entryGap.kind}>
                                <span aria-hidden="true">{formatSigned(entry.rank_gap)}</span>
                                <span className="visually-hidden">{entryGap.sentence}</span>
                              </td>
                              <td className="muted">
                                {windowLabel(
                                  entry.aggregation_window_type,
                                  entry.aggregation_window_days,
                                )}
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
                          <td className="muted">expert consensus, not a price</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  <p className="section-note">{crossMarketSummaryText(cross)}</p>
                </div>
              )}
              <div className="readout-grid">
                <Readout
                  label="Observed picks"
                  value={
                    arbitrage.market_adp_low === null || arbitrage.market_adp_high === null
                      ? EM_DASH
                      : `${formatAdp(arbitrage.market_adp_low)} – ${formatAdp(arbitrage.market_adp_high)}`
                  }
                  hint="earliest – latest"
                />
                <Readout
                  label="Regional value gap"
                  value={arbitrage.regional_value_gap.toFixed(3)}
                />
                <Readout label="Cohort" value={arbitrage.market_cohort_detail} size="sm" />
                <Readout
                  label="Snapshot"
                  value={formatEastern(arbitrage.market_snapshot_at_utc)}
                  hint={marketSourceLabel(arbitrage.market_source_id)}
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
                  {tier !== null && (
                    <span className="detail-posrank">
                      {tier.position}
                      {formatRank(tier.position_rank)}
                    </span>
                  )}
                  {team !== null && <span className="detail-posrank">{team}</span>}
                  {tier !== null && <TierTag label={tier.tier_label} />}
                  <StatusBadge status={status} />
                </div>
              </div>
            </div>

            {tier !== null && (
              <div className="rail-hero">
                <span className="rail-hero-label">Fair rank</span>
                <span className="rail-hero-value">{formatRank(tier.fair_rank)}</span>
                <span className="rail-hero-note">median simulated VORP</span>
              </div>
            )}

            {/* The three things a drafter reads first, before any grid. */}
            <div className="rail-verdict">
              {arbitrage !== null && gap !== null && (
                <div>
                  <span className="rail-verdict-label">Market verdict</span>
                  <span className="rail-verdict-value" data-kind={gap.kind}>
                    {`${formatSigned(arbitrage.rank_gap)} ${
                      gap.kind === "bargain" ? "later" : gap.kind === "premium" ? "earlier" : "even"
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
                {arbitrage === null
                  ? "Intrinsic values from this build"
                  : `Snapshot ${formatEastern(arbitrage.market_snapshot_at_utc)}`}
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
