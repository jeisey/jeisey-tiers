/**
 * Client-side CSV export.
 *
 * Two exports exist and they mean different things. `Download full CSV` links straight to the
 * versioned artifact the build produced — the same bytes the Python serializer wrote, in the
 * column order the JSON Schema declares (`docs/DATA_CONTRACTS.md` section 13.2). `Export
 * filtered CSV` is generated here from exactly the rows currently on screen, in exactly the
 * order they are displayed, so a user can hand someone else the board they are looking at.
 *
 * Nothing in this file invents a column. Fields the artifact publishes as null export as
 * empty cells; fields V1 has no model for (`expected_surplus_vorp`, `p_positive_surplus`) are
 * not in the column lists at all, because a header with 2,124 empty cells under it implies a
 * quantity that was measured and lost rather than one that was never claimed (ADR-010).
 */

import type { ArbitrageRecord } from "./contracts";
import { crossMarketOf, marketsOf } from "./multimarket";
import type { ArbitrageRow, TierRow } from "./model";
import type { OpportunityRow, RosRow } from "./ros";
import type { ScoringValue, TeamCount } from "./state";

/** RFC 4180: quote whenever the value contains a comma, a quote, or a line break. */
export function escapeCsvValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (text === "") return "";
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function toCsv(header: readonly string[], rows: readonly (readonly (string | number | null)[])[]): string {
  const lines = [header.map(escapeCsvValue).join(",")];
  for (const row of rows) lines.push(row.map(escapeCsvValue).join(","));
  // A trailing newline, so the file ends the way every other text tool expects it to.
  return `${lines.join("\r\n")}\r\n`;
}

/**
 * The filtered Tier export's stable column order.
 *
 * It matches the table's own reading order and is documented here rather than derived from
 * the visible columns, so hiding a column on screen cannot silently change a downstream file.
 */
export const TIER_EXPORT_COLUMNS = [
  "fair_rank",
  "player",
  "position",
  "team",
  "position_rank",
  "tier",
  "tier_ordinal",
  "expected_vorp",
  "p25_vorp",
  "p50_vorp",
  "p75_vorp",
  "p10_vorp",
  "p90_vorp",
  "expected_points",
  "uncertainty",
  "injury_status",
  "injury_body_part",
  "quality_flags",
] as const;

export function tierRowsToCsv(rows: readonly TierRow[]): string {
  return toCsv(
    TIER_EXPORT_COLUMNS,
    rows.map((row) => {
      const record = row.record;
      return [
        record.fair_rank,
        record.display_name,
        record.position,
        record.team,
        record.position_rank,
        record.tier_label,
        record.tier_ordinal,
        record.expected_vorp,
        record.p25_vorp,
        record.p50_vorp,
        record.p75_vorp,
        record.p10_vorp,
        record.p90_vorp,
        record.expected_points,
        record.uncertainty,
        row.status?.injury_status ?? null,
        row.status?.injury_body_part ?? null,
        record.quality_flags.join("|"),
      ];
    }),
  );
}

export const ARBITRAGE_EXPORT_COLUMNS = [
  "arbitrage_rank",
  "player",
  "position",
  "team",
  "fair_rank",
  "market_adp",
  "market_rank",
  "rank_gap",
  "regional_value_gap",
  "arbitrage_score",
  "market_trend",
  "market_sample_size",
  "market_adp_low",
  "market_adp_high",
  "market_source_id",
  "market_cohort_id",
  "market_cohort_detail",
  "market_snapshot_at_utc",
  "confidence",
  "quality_flags",
  // Phase 10. Every column names its source and its signal, because a spreadsheet has no
  // selector to explain which market a bare "adp" column came from (roadmap 10.6).
  "ffc_adp",
  "ffc_rank_gap",
  "ffc_adp_sd",
  "mfl_adp",
  "mfl_rank_gap",
  "market_adp_median",
  "market_disagreement_range",
  "sources_available",
  "surface_reasons",
  "outside_tier_board",
] as const;

export function arbitrageRowsToCsv(rows: readonly ArbitrageRow[]): string {
  return toCsv(
    ARBITRAGE_EXPORT_COLUMNS,
    rows.map((row) => {
      const record = row.record;
      return [
        row.arbitrageRank,
        record.display_name,
        record.position,
        record.team,
        record.fair_rank,
        record.market_adp,
        record.market_rank,
        record.rank_gap,
        record.regional_value_gap,
        record.arbitrage_score,
        record.market_trend,
        record.market_sample_size,
        record.market_adp_low,
        record.market_adp_high,
        record.market_source_id,
        record.market_cohort_id,
        record.market_cohort_detail,
        record.market_snapshot_at_utc,
        record.confidence,
        record.quality_flags.join("|"),
        ...multiMarketCells(record),
      ];
    }),
  );
}

/**
 * The Phase-10 columns for one row.
 *
 * Kept in one function beside the header list so the two cannot drift: a CSV whose header
 * and cells disagree is worse than one that omits the columns entirely.
 */
function multiMarketCells(record: ArbitrageRecord): (string | number | null)[] {
  const markets = marketsOf(record);
  const ffc = markets.fantasyfootballcalculator_adp ?? null;
  const mfl = markets.myfantasyleague_adp ?? null;
  const cross = crossMarketOf(record);
  return [
    ffc?.market_adp ?? null,
    ffc?.rank_gap ?? null,
    ffc?.market_adp_sd ?? null,
    mfl?.market_adp ?? null,
    mfl?.rank_gap ?? null,
    cross?.market_adp_median ?? null,
    cross?.market_disagreement_range ?? null,
    (cross?.sources_available ?? []).join("|"),
    (record.surface_reasons ?? []).join("|"),
    record.outside_tier_board === undefined ? null : String(record.outside_tier_board),
  ];
}

/**
 * The filtered rest-of-season export.
 *
 * Every column name carries `ros_` or an unambiguous "rem"/"since" word for the same reason
 * the table headers do: a spreadsheet holding both exports must not have two columns called
 * `fair_rank` that mean different things. The disclosure fields travel with the numbers —
 * a downstream reader who has the rank should also have the sentence that qualifies it.
 */
export const ROS_EXPORT_COLUMNS = [
  "season",
  "through_week",
  "ros_fair_rank",
  "player",
  "position",
  "team",
  "ros_position_rank",
  "ros_tier",
  "ros_tier_ordinal",
  "ros_expected_vorp",
  "ros_vorp_p25",
  "ros_vorp_p50",
  "ros_vorp_p75",
  "ros_vorp_p10",
  "ros_vorp_p90",
  "ros_expected_points",
  "ros_expected_games",
  "ros_uncertainty",
  "preseason_fair_rank",
  "fair_rank_change",
  "games_played_to_date",
  "points_to_date",
  "weeks_since_last_game",
  "consecutive_weeks_missed",
  "long_absence",
  "in_preseason_universe",
  "current_status",
  "quality_flags",
] as const;

export function rosRowsToCsv(rows: readonly RosRow[]): string {
  return toCsv(
    ROS_EXPORT_COLUMNS,
    rows.map(({ record }) => [
      record.season,
      record.through_week,
      record.ros_fair_rank,
      record.display_name,
      record.position,
      record.team,
      record.ros_position_rank,
      record.ros_tier_label,
      record.ros_tier,
      record.ros_expected_vorp,
      record.ros_vorp_p25,
      record.ros_vorp_p50,
      record.ros_vorp_p75,
      record.ros_vorp_p10,
      record.ros_vorp_p90,
      record.ros_expected_points,
      record.ros_expected_games,
      record.ros_uncertainty,
      record.preseason_fair_rank ?? null,
      record.fair_rank_change ?? null,
      record.games_played_to_date,
      record.points_to_date,
      record.weeks_since_last_game,
      record.consecutive_weeks_missed,
      record.long_absence ? "true" : "false",
      record.in_preseason_universe ? "true" : "false",
      record.current_status,
      record.quality_flags.join("|"),
    ]),
  );
}

/**
 * The filtered Opportunity export.
 *
 * `add_count` and `drop_count` are counts of transactions over the window named in
 * `behavior_lookback_hours`, and the window travels in the file because a count without its
 * window is uninterpretable. There is no combined score column, because there is no combined
 * score: adding a rank to a count would invent one.
 */
export const OPPORTUNITY_EXPORT_COLUMNS = [
  "season",
  "through_week",
  "ros_fair_rank",
  "player",
  "position",
  "team",
  "ros_position_rank",
  "ros_tier",
  "ros_expected_vorp",
  "ros_expected_points",
  "ros_uncertainty",
  "behavior_source_id",
  "behavior_available",
  "behavior_snapshot_at_utc",
  "behavior_lookback_hours",
  "add_count",
  "drop_count",
  "net_add_count",
  "add_rank",
  "drop_rank",
  "snap_share_last3",
  "target_share_last3",
  "games_played_to_date",
  "weeks_since_last_game",
  "long_absence",
  "current_status",
  "outside_tier_board",
  "surface_reasons",
  "quality_flags",
] as const;

export function opportunityRowsToCsv(rows: readonly OpportunityRow[]): string {
  return toCsv(
    OPPORTUNITY_EXPORT_COLUMNS,
    rows.map(({ record }) => [
      record.season,
      record.through_week,
      record.ros_fair_rank,
      record.display_name,
      record.position,
      record.team,
      record.ros_position_rank,
      record.ros_tier,
      record.ros_expected_vorp,
      record.ros_expected_points ?? null,
      record.ros_uncertainty,
      record.behavior_source_id ?? null,
      record.behavior_available ? "true" : "false",
      record.behavior_snapshot_at_utc ?? null,
      record.behavior_lookback_hours ?? null,
      record.add_count ?? null,
      record.drop_count ?? null,
      record.net_add_count ?? null,
      record.add_rank ?? null,
      record.drop_rank ?? null,
      record.snap_share_last3 ?? null,
      record.target_share_last3 ?? null,
      record.games_played_to_date ?? null,
      record.weeks_since_last_game,
      record.long_absence ? "true" : "false",
      record.current_status,
      record.outside_tier_board ? "true" : "false",
      record.surface_reasons.join("|"),
      record.quality_flags.join("|"),
    ]),
  );
}

/** Which board an export names in its filename, and which artifact CSV it links to. */
export type ExportBoard = "tiers" | "arbitrage" | "ros_tiers" | "inseason_opportunity";

/**
 * `ffdraft-tiers-ppr-12-2026-08-21.csv`. The date comes from build metadata, never the clock.
 *
 * In-season exports also carry their cutoff week, because two rest-of-season files from the
 * same day at different cutoffs are different data, and a filename that could not tell them
 * apart would be the one thing a downstream reader cannot recover.
 */
export function exportFilename(
  board: ExportBoard,
  scoring: ScoringValue,
  teams: TeamCount,
  buildDate: string,
  throughWeek?: number,
): string {
  const week = throughWeek === undefined ? "" : `-w${String(throughWeek).padStart(2, "0")}`;
  return `ffdraft-${board}-${scoring}-${String(teams)}${week}-${buildDate}.csv`;
}

/**
 * Hand the browser a file.
 *
 * An object URL rather than a data URI so a 300-row export is not pushed through the address
 * bar, and revoked on the next frame so the blob does not outlive the click.
 */
export function downloadCsv(filename: string, contents: string): void {
  // A BOM so Excel opens UTF-8 exports without mangling accented names. Escaped rather than
  // literal so the character is visible to a reader of this file.
  const blob = new Blob([`\uFEFF${contents}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
