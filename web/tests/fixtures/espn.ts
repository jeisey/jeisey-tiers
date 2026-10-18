/**
 * ESPN roster/start fixtures for the frontend (ADR-112), carrying every *state* a real window
 * produces rather than one normal case.
 *
 * Captures sit at the production cadence — roughly daily, with one missed day — and the
 * reading per player is chosen in one table, so a test can name the case it needs:
 *
 * | player | case |
 * |---|---|
 * | Jahmyr Cook | the riser: 18% → 31% over the 7-day baseline, started share rising |
 * | James Cook III | **first seen today**: one point, both changes withheld, at 9.99% (inside "<10%") |
 * | Jaylin Lane | **roster-only**: 25.0% exactly (outside "<25%"), no start share ever |
 * | Omarion Vance | a valid **0%** |
 * | Zay Meadows | a **gap** (three missed reads), at exactly 10.0% (outside "<10%") |
 * | Puka Nightingale | **falling** |
 * | Deebo Gray | ESPN **publishes nothing** for his ESPN id |
 * | Derrick Hampton | an **invalid** newest value |
 * | Rashee Kirk | **two points** only: 1-day change measured, 7-day withheld |
 * | Bijan Robinson (surfaced) | **no ESPN id** |
 * | the signing (00-0000021) | an **ambiguous** ESPN id |
 * | Kyle Pitts Sr. / Trey McBride | 75.0% and 74.99%: the "<75%" boundary |
 * | Zach Ertz | exactly 50.0%: outside "<50%" |
 * | Jalen Marsh | a rising-role QB at 44.3%: passes "Role rising + below 50%" |
 */

import type {
  EspnOwnershipMetadata,
  EspnOwnershipPoint,
  EspnOwnershipRecord,
  EspnOwnershipSeriesRecord,
  EspnRosterChange,
  Position,
} from "../../src/data/contracts";
import { FIXTURE_BUILD_ID, FIXTURE_GENERATED_AT, FIXTURE_THROUGH_WEEK, opportunityEnvelope } from "./artifacts";

/** Read times, hours before the fixture's generation time. No 122 h read: a missed day. */
export const ESPN_CAPTURE_HOURS = [230, 196, 170, 146, 98, 74, 50, 24.5, 1] as const;
/** Reads at or after this age report the next ESPN period: a week rollover inside the window. */
export const ESPN_ROLLOVER_HOURS = 98;

interface Spec {
  readonly final?: number;
  readonly rate?: number;
  readonly state?: "not_published" | "invalid" | "no_espn_id" | "ambiguous_espn_id";
  readonly startless?: boolean;
  /** Indexes into `ESPN_CAPTURE_HOURS` that carried him; absent means all of them. */
  readonly carried?: readonly number[];
}

export const ESPN_FIXTURE: Readonly<Record<string, Spec>> = {
  "gsis:00-0000001": { final: 99.4 },
  "gsis:00-0000001-surfaced": { state: "no_espn_id" },
  "gsis:00-0000002": { final: 97.2 },
  "gsis:00-0000003": { final: 88.0 },
  "gsis:00-0000004": { final: 75.0 },
  "gsis:00-0000005": { final: 74.99 },
  "gsis:00-0000006": { state: "not_published" },
  "gsis:00-0000007": { final: 50.0 },
  "gsis:00-0000008": { final: 99.9 },
  "gsis:00-0000009": { final: 96.1 },
  "gsis:00-0000010": { final: 25.0, startless: true },
  // 13 points over exactly the 169 hours between the 7-day baseline and the latest read.
  "gsis:00-0000011": { final: 31.0, rate: (13 * 24) / 169 },
  "gsis:00-0000012": { final: 62.0, rate: -0.8 },
  "gsis:00-0000013": { final: 9.99, carried: [8] },
  "gsis:00-0000014": { state: "invalid" },
  "gsis:00-0000015": { final: 10.0, carried: [0, 1, 2, 6, 7, 8] },
  "gsis:00-0000016": { final: 0.0, rate: 0 },
  "gsis:00-0000017": { final: 24.6, carried: [7, 8] },
  "gsis:00-0000018": { final: 44.3, rate: 0.9 },
  "gsis:00-0000020": { final: 1.2 },
  "gsis:00-0000021": { state: "ambiguous_espn_id" },
};

const round2 = (value: number): number => Math.round(value * 100) / 100;

function at(hours: number): string {
  return new Date(Date.parse(FIXTURE_GENERATED_AT) - hours * 3_600_000).toISOString().replace(".000Z", "Z");
}

function periodAt(hours: number): number {
  return hours < ESPN_ROLLOVER_HOURS ? FIXTURE_THROUGH_WEEK + 1 : FIXTURE_THROUGH_WEEK;
}

/** Board players, one per id, in id order: every in-season block publishes the same set. */
export function espnPlayers(): readonly { readonly playerId: string; readonly position: Position }[] {
  const seen = new Map<string, Position>();
  for (const record of opportunityEnvelope(true).records) seen.set(record.player_id, record.position);
  return [...seen.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([playerId, position]) => ({ playerId, position }));
}

function espnIdOf(playerId: string): string {
  const digits = playerId.replace(/\D/g, "").slice(-4);
  return String(4_100_000 + Number(digits));
}

function points(spec: Spec): EspnOwnershipPoint[] {
  const final = spec.final ?? 0;
  const rate = spec.rate ?? 0.3;
  const carried = spec.carried ?? ESPN_CAPTURE_HOURS.map((_, index) => index);
  const latestHours = ESPN_CAPTURE_HOURS[ESPN_CAPTURE_HOURS.length - 1] ?? 1;
  return ESPN_CAPTURE_HOURS.flatMap((hours, index) => {
    if (!carried.includes(index)) return [];
    const days = (hours - latestHours) / 24;
    const rostered = round2(Math.min(100, Math.max(0, final - rate * days)));
    return [
      {
        observed_at_utc: at(hours),
        espn_updated_at_utc: at(hours + 0.75),
        espn_current_period: periodAt(hours),
        percent_rostered: rostered,
        percent_started: spec.startless === true ? null : round2(rostered * 0.45),
      },
    ];
  });
}

const EMPTY_CHANGE: EspnRosterChange = {
  state: "no_current_reading",
  change_pp: null,
  baseline_percent_rostered: null,
  baseline_observed_at_utc: null,
  span_hours: null,
};

function change(series: readonly EspnOwnershipPoint[], baselineHours: number): EspnRosterChange {
  const latest = series[series.length - 1];
  if (latest?.percent_rostered == null) return EMPTY_CHANGE;
  const baselineAt = at(baselineHours);
  const span = round2(baselineHours - (ESPN_CAPTURE_HOURS[ESPN_CAPTURE_HOURS.length - 1] ?? 1));
  const baseline = series.find((point) => point.observed_at_utc === baselineAt);
  if (baseline?.percent_rostered == null) {
    return { ...EMPTY_CHANGE, state: "no_baseline_reading", baseline_observed_at_utc: baselineAt, span_hours: span };
  }
  return {
    state: "measured",
    change_pp: round2(latest.percent_rostered - baseline.percent_rostered),
    baseline_percent_rostered: baseline.percent_rostered,
    baseline_observed_at_utc: baselineAt,
    span_hours: span,
  };
}

export type EspnFixtureMode = "present" | "stale" | "unavailable" | "absent";

export function espnOwnershipRecords(mode: EspnFixtureMode = "present"): EspnOwnershipRecord[] {
  const stale = mode === "stale";
  return espnPlayers().map(({ playerId, position }) => {
    const spec = ESPN_FIXTURE[playerId] ?? { state: "not_published" as const };
    const base = {
      schema_version: "1.0",
      build_id: FIXTURE_BUILD_ID,
      season: 2026,
      through_week: FIXTURE_THROUGH_WEEK,
      source_id: "espn_fantasy_ownership",
      player_id: playerId,
      position,
    };
    if (spec.state === "no_espn_id" || spec.state === "ambiguous_espn_id" || spec.state === "not_published") {
      return {
        ...base,
        espn_id: spec.state === "no_espn_id" ? null : espnIdOf(playerId),
        reading_state: spec.state,
        observed_at_utc: null,
        espn_updated_at_utc: null,
        espn_current_period: null,
        percent_rostered: null,
        start_state: "no_reading",
        percent_started: null,
        rostered_change_1d: EMPTY_CHANGE,
        rostered_change_7d: EMPTY_CHANGE,
      };
    }
    if (spec.state === "invalid") {
      return {
        ...base,
        espn_id: espnIdOf(playerId),
        reading_state: "invalid",
        observed_at_utc: at(1),
        espn_updated_at_utc: at(1.75),
        espn_current_period: periodAt(1),
        percent_rostered: null,
        start_state: "not_published",
        percent_started: null,
        rostered_change_1d: EMPTY_CHANGE,
        rostered_change_7d: EMPTY_CHANGE,
      };
    }
    const series = points(spec);
    const latest = series[series.length - 1];
    return {
      ...base,
      espn_id: espnIdOf(playerId),
      reading_state: stale ? "stale" : "observed",
      observed_at_utc: latest?.observed_at_utc ?? null,
      espn_updated_at_utc: latest?.espn_updated_at_utc ?? null,
      espn_current_period: latest?.espn_current_period ?? null,
      percent_rostered: latest?.percent_rostered ?? null,
      start_state: latest?.percent_started == null ? "not_published" : "observed",
      percent_started: latest?.percent_started ?? null,
      rostered_change_1d: change(series, 24.5),
      rostered_change_7d: change(series, 170),
    };
  });
}

export function espnOwnershipSeriesRecords(): EspnOwnershipSeriesRecord[] {
  return espnPlayers().flatMap(({ playerId, position }) => {
    const spec = ESPN_FIXTURE[playerId];
    if (spec === undefined || spec.state === "no_espn_id" || spec.state === "ambiguous_espn_id" || spec.state === "not_published") {
      return [];
    }
    const series = spec.state === "invalid" ? points({ final: 12 }).slice(0, -1) : points(spec);
    if (series.length === 0) return [];
    const first = Date.parse(series[0]?.observed_at_utc ?? "");
    const last = Date.parse(series[series.length - 1]?.observed_at_utc ?? "");
    return [
      {
        schema_version: "1.0",
        build_id: FIXTURE_BUILD_ID,
        season: 2026,
        through_week: FIXTURE_THROUGH_WEEK,
        source_id: "espn_fantasy_ownership",
        player_id: playerId,
        position,
        espn_id: espnIdOf(playerId),
        window_days: 28,
        captures_in_window: ESPN_CAPTURE_HOURS.length,
        observations: series.length,
        span_hours: round2((last - first) / 3_600_000),
        points: series,
      },
    ];
  });
}

export function espnOwnershipMetadata(mode: EspnFixtureMode = "present"): EspnOwnershipMetadata | null {
  if (mode === "absent") return null;
  if (mode === "unavailable") {
    return {
      rule_version: "espn_ownership_v1",
      status: "unavailable",
      reason: "no retained ESPN capture falls inside the 28-day window",
      source_id: "espn_fantasy_ownership",
    };
  }
  const records = espnOwnershipRecords(mode);
  const count = (state: string): number => records.filter((record) => record.reading_state === state).length;
  return {
    rule_version: "espn_ownership_v1",
    status: "published",
    reason: null,
    source_id: "espn_fantasy_ownership",
    latest_snapshot_key: at(1).replace(/:/g, "-"),
    latest_observed_at_utc: at(1),
    latest_age_hours: mode === "stale" ? 52 : 1,
    stale: mode === "stale",
    espn_current_period: periodAt(1),
    captures_in_window: ESPN_CAPTURE_HOURS.length,
    capture_times_utc: ESPN_CAPTURE_HOURS.map((hours) => at(hours)),
    skipped_captures: 0,
    baseline_1d_observed_at_utc: at(24.5),
    baseline_7d_observed_at_utc: at(170),
    players: records.length,
    series_players: espnOwnershipSeriesRecords().length,
    reading_states: {
      observed: count("observed"),
      stale: count("stale"),
      not_published: count("not_published"),
      invalid: count("invalid"),
      no_espn_id: count("no_espn_id"),
      ambiguous_espn_id: count("ambiguous_espn_id"),
    },
    attribution:
      "Rostered % and started %: ESPN Fantasy Football (fantasy.espn.com), read once a day from ESPN's public player data.",
    population_statement:
      "ESPN's percentages describe ESPN leagues, not yours: whether a player is free in your league is a separate question. Popularity is crowd interest, not a projection.",
    start_context_statement: `Started % is ESPN's figure, read while ESPN reported scoring period ${String(periodAt(1))} as current. ESPN does not say which week's lineups it counts or how it is calculated, so no start change or started-among-rostered ratio is shown.`,
  };
}

function envelope<T>(artifact: string, recordSchema: string, records: readonly T[]) {
  return {
    schema_version: "1.0",
    artifact,
    record_schema: recordSchema,
    build_id: FIXTURE_BUILD_ID,
    generated_at_utc: FIXTURE_GENERATED_AT,
    record_count: records.length,
    records,
  };
}

/** The served files for one ESPN mode, merged into an in-season fixture site. */
export function espnFixtureFiles(mode: EspnFixtureMode): Record<string, unknown> {
  if (mode === "absent" || mode === "unavailable") return {};
  return {
    "espn_ownership.json": envelope("espn_ownership", "espn_ownership_record", espnOwnershipRecords(mode)),
    "espn_ownership_series.json": envelope("espn_ownership_series", "espn_ownership_series", espnOwnershipSeriesRecords()),
  };
}
