/**
 * "Why this week", in plain English (ADR-099).
 *
 * A manager knows a good receiver projects well. What he wants to know is why **this** week is
 * better or worse than the receiver's usual one — at the median, and at the ceiling where a
 * boom lives. Every record carries that account (`explanation`, `typical_week_shapley_v1`): for
 * P10, P50 and P90, his typical week's number and the exact split of the difference into the
 * game inputs the model read. This module turns those numbers, and the published game-day
 * context, into sentences.
 *
 * Two kinds of chip, never confused:
 *
 * - **model** chips carry points. One exists only for an input group the served model reads,
 *   at the level it is shown for, with the exact published term — "Opponent allows the 5th-most
 *   points to WRs (+1.2)". The words come from published fields (the opponent block, the
 *   team's typical and this-week lines, the game), never from an inference.
 * - **context** chips carry facts and no points: the forecast, the roof, who is listed out.
 *   weekly-startsit-v1 reads neither weather nor injuries, so attaching a point value to them
 *   would invent an effect the model never computed.
 *
 * Direction is always spelled (a sign and an arrow, and the words above/below), never colour
 * alone.
 */

import type {
  ListedPlayer,
  WeeklyAccount,
  WeeklyExplainedLevel,
  WeeklyExplanationGroup,
  WeeklyGameContextRecord,
  WeeklyProjectionRecord,
} from "./contracts";

/** Below this a term rounds to ±0.0 and is not worth a chip. */
export const MATERIAL_POINTS = 0.05;

export interface ModelChip {
  readonly kind: "model";
  readonly group: WeeklyExplanationGroup;
  /** What the input was this week, in words. */
  readonly label: string;
  /** Points this input moved the reading by, against his typical week. */
  readonly value: number;
}

export interface ContextChip {
  readonly kind: "context";
  readonly id: string;
  readonly label: string;
  /** Longer wording for a tooltip and screen readers. */
  readonly detail: string;
  readonly tone: "neutral" | "concern" | "absent";
  /** A licence the shown values carry (Open-Meteo's CC BY 4.0), printed with the chip. */
  readonly attribution?: string;
}

/** Open-Meteo's data licence asks for this wherever its values are shown. */
export const OPEN_METEO_ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)";

export interface LevelReading {
  readonly level: WeeklyExplainedLevel;
  readonly typical: number;
  readonly thisWeek: number;
  readonly delta: number;
  /** Material model chips, largest first. */
  readonly chips: readonly ModelChip[];
  /** The monotone repair and rounding, when it moved the number visibly. */
  readonly residual: number;
}

export interface WhyThisWeek {
  readonly floor: LevelReading;
  readonly median: LevelReading;
  readonly ceiling: LevelReading;
  readonly context: readonly ContextChip[];
}

const POSITION_PLURAL: Readonly<Record<string, string>> = {
  QB: "QBs",
  RB: "RBs",
  WR: "WRs",
  TE: "TEs",
};

export function ordinal(value: number): string {
  const tens = value % 100;
  if (tens >= 11 && tens <= 13) return `${String(value)}th`;
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[value % 10] ?? "th";
  return `${String(value)}${suffix}`;
}

function one(value: number): string {
  return value.toFixed(1);
}

/** "+1.2" / "−0.4" / "±0.0", with a true minus sign. */
export function signedPoints(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "±0.0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)}`;
}

/** ▲ above, ▼ below, ● level: the shape carries direction where colour cannot. */
export function arrow(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "●";
  return rounded > 0 ? "▲" : "▼";
}

function linesLabel(record: WeeklyProjectionRecord, own: WeeklyGameContextRecord | null): string {
  const now = own?.this_week.team_points ?? record.game?.team_points ?? null;
  const usual = own?.typical.team_points ?? null;
  if (now === null) return "Sportsbook outlook";
  if (usual === null) return `Team implied for ${one(now)} pts`;
  return `Team implied for ${one(now)} pts (usually ${one(usual)})`;
}

function opponentLabel(record: WeeklyProjectionRecord): string {
  const opponent = record.opponent;
  const plural = POSITION_PLURAL[record.position] ?? `${record.position}s`;
  if (opponent?.rank == null) return `Opponent ${opponent?.defense ?? ""}`.trim();
  const defenses = opponent.defenses ?? 32;
  return opponent.rank <= defenses / 2
    ? `${opponent.defense} allows the ${ordinal(opponent.rank)}-most points to ${plural}`
    : `${opponent.defense} allows the ${ordinal(defenses + 1 - opponent.rank)}-fewest points to ${plural}`;
}

function homeLabel(record: WeeklyProjectionRecord): string {
  if (record.game === null) return "Home or away";
  if (record.game.neutral_site) return "Neutral site";
  return record.game.home_away === "home" ? "Home game" : "Road game";
}

function restLabel(own: WeeklyGameContextRecord | null): string {
  const rest = own?.this_week.rest_advantage ?? null;
  if (rest === null || rest === 0) return "Equal rest";
  const days = Math.abs(rest);
  return rest > 0
    ? `${String(days)} more day${days === 1 ? "" : "s"} of rest than the opponent`
    : `${String(days)} fewer day${days === 1 ? "" : "s"} of rest than the opponent`;
}

function roofLabel(own: WeeklyGameContextRecord | null): string {
  if (own === null) return "Roof";
  const indoors = own.this_week.indoors;
  if (own.roof.assumed_from_last_home_game) {
    return indoors === 1
      ? "Roof read as closed (as at its last home game; not yet announced)"
      : "Roof read as open (as at its last home game; not yet announced)";
  }
  if (indoors === 1) return own.venue?.roof_type === "dome" ? "Indoors (dome)" : "Indoors (roof closed)";
  return "Outdoors";
}

function modelChips(
  account: WeeklyAccount,
  record: WeeklyProjectionRecord,
  own: WeeklyGameContextRecord | null,
): ModelChip[] {
  const labels: Record<WeeklyExplanationGroup, string> = {
    lines: linesLabel(record, own),
    home: homeLabel(record),
    rest: restLabel(own),
    roof: roofLabel(own),
    opponent: opponentLabel(record),
  };
  return (Object.keys(account.terms) as WeeklyExplanationGroup[])
    .map((group) => ({ kind: "model" as const, group, label: labels[group], value: account.terms[group] }))
    .filter((chip) => Math.abs(chip.value) >= MATERIAL_POINTS)
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value) || a.group.localeCompare(b.group));
}

function level(
  key: WeeklyExplainedLevel,
  record: WeeklyProjectionRecord,
  own: WeeklyGameContextRecord | null,
): LevelReading | null {
  const account = record.explanation?.[key];
  const thisWeek = record.quantiles?.[key];
  if (account === undefined || thisWeek === undefined) return null;
  return {
    level: key,
    typical: account.typical,
    thisWeek,
    delta: thisWeek - account.typical,
    chips: modelChips(account, record, own),
    residual: account.rearrangement,
  };
}

const LISTED_ORDER: Readonly<Record<string, number>> = { QB: 0, OL: 1, SKILL: 2, CB: 3, S: 4, DL: 5 };

function listedWords(entry: ListedPlayer): string {
  const name = entry.name ?? entry.player_id;
  const status = entry.designation === "Questionable" ? "questionable" : entry.designation === "Doubtful" ? "doubtful" : "out";
  if (entry.group === "SKILL") {
    const share =
      (entry.target_share ?? 0) >= (entry.carry_share ?? 0)
        ? `${String(Math.round((entry.target_share ?? 0) * 100))}% of targets`
        : `${String(Math.round((entry.carry_share ?? 0) * 100))}% of carries`;
    return `${name} (${entry.position ?? "skill"}, ${share}) ${status}`;
  }
  return `${entry.role} ${name} ${status}`;
}

function lineupChips(
  record: WeeklyProjectionRecord,
  own: WeeklyGameContextRecord | null,
  opponent: WeeklyGameContextRecord | null,
): ContextChip[] {
  const chips: ContextChip[] = [];
  const mine = (own?.lineup.listed ?? [])
    .filter((entry) => ["OL", "QB", "SKILL"].includes(entry.group))
    .filter((entry) => entry.player_id !== record.player_id)
    .sort((a, b) => (LISTED_ORDER[a.group] ?? 9) - (LISTED_ORDER[b.group] ?? 9));
  const theirs = (opponent?.lineup.listed ?? [])
    .filter((entry) => ["CB", "S", "DL"].includes(entry.group))
    .sort((a, b) => (LISTED_ORDER[a.group] ?? 9) - (LISTED_ORDER[b.group] ?? 9));
  for (const entry of mine) {
    chips.push({
      kind: "context",
      id: `own:${entry.player_id}`,
      label: `${own?.team ?? "Team"} offence: ${listedWords(entry)}`,
      detail: `${listedWords(entry)} on the week ${String(record.target_week)} report${entry.primary_injury === null ? "" : ` (${entry.primary_injury})`}. Context only: weekly-startsit-v1 does not read the injury report.`,
      tone: entry.designation === "Questionable" ? "concern" : "absent",
    });
  }
  for (const entry of theirs) {
    chips.push({
      kind: "context",
      id: `opp:${entry.player_id}`,
      label: `${opponent?.team ?? "Their"} defence: ${listedWords(entry)}`,
      detail: `${listedWords(entry)} for ${opponent?.team ?? "the opponent"} on the week ${String(record.target_week)} report. Context only: weekly-startsit-v1 does not read the injury report.`,
      tone: entry.designation === "Questionable" ? "concern" : "absent",
    });
  }
  if (own !== null && own.lineup.report_available && !own.lineup.report_final) {
    chips.push({
      kind: "context",
      id: "own:report-pending",
      label: `${own.team} report: no game statuses yet`,
      detail: `${own.team}'s week ${String(record.target_week)} injury report carries no Out, Doubtful or Questionable designation yet, so absences are unknown — not none.`,
      tone: "neutral",
    });
  }
  return chips;
}

function clock(iso: string | null): string {
  if (iso === null) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function providerName(provider: string | null): string {
  return provider === "nws" ? "NWS" : provider === "open_meteo" ? "Open-Meteo" : "forecast";
}

/** The forecast as one chip: numbers only when the published status allows them. */
export function weatherChip(own: WeeklyGameContextRecord | null): ContextChip | null {
  if (own === null) return null;
  const weather = own.weather;
  const where = own.venue?.name ?? "the stadium";
  const reading = (): string => {
    const parts: string[] = [];
    if (weather.wind_mph !== null) parts.push(`${String(Math.round(weather.wind_mph))} mph wind`);
    if (weather.gust_mph !== null && weather.gust_mph >= (weather.wind_mph ?? 0) + 5) {
      parts.push(`gusts ${String(Math.round(weather.gust_mph))}`);
    }
    if (weather.temp_f !== null) parts.push(`${String(Math.round(weather.temp_f))}°F`);
    if (weather.precip_probability !== null && weather.precip_probability >= 30) {
      parts.push(`${String(Math.round(weather.precip_probability))}% chance of precipitation`);
    }
    return parts.join(", ");
  };
  const source = `${providerName(weather.provider)}${weather.retrieved_at_utc === null ? "" : `, retrieved ${clock(weather.retrieved_at_utc)} ET`}`;
  const attribution = weather.provider === "open_meteo" ? { attribution: OPEN_METEO_ATTRIBUTION } : {};
  switch (weather.status) {
    case "ok": {
      const text = reading();
      const windy = (weather.wind_mph ?? 0) >= 15 || (weather.precip_probability ?? 0) >= 50 || (weather.temp_f ?? 60) <= 32;
      return {
        kind: "context",
        id: "weather",
        label: `Forecast: ${text}`,
        detail: `Kickoff-hour forecast at ${where}: ${text}${weather.short_forecast === null ? "" : ` (${weather.short_forecast})`} — ${source}. Context only: weekly-startsit-v1 does not read weather.`,
        tone: windy ? "concern" : "neutral",
        ...attribution,
      };
    }
    case "roof_unknown": {
      const outside = reading();
      const unverified = own.venue?.roof_type === "unverified";
      return {
        kind: "context",
        id: "weather",
        label: unverified
          ? `Roof cover unverified${outside === "" ? "" : `; outside: ${outside}`}`
          : `Retractable roof — announced on game day${outside === "" ? "" : `; outside: ${outside}`}`,
        detail: unverified
          ? `Whether ${where}'s roof covers the field is not established by this site's venue evidence, so the forecast is shown as outside conditions only${outside === "" ? "" : `: ${outside}`} — ${source}.`
          : `${where} has a retractable roof, and whether it is closed is announced on game day, so the forecast may not reach the field${outside === "" ? "" : `. Outside at kickoff: ${outside}`} — ${source}.`,
        tone: "neutral",
        ...attribution,
      };
    }
    case "indoors":
      return {
        kind: "context",
        id: "weather",
        label: "Dome — no weather",
        detail: `${where} is a fixed dome; no weather reaches the field.`,
        tone: "neutral",
      };
    case "stale":
      return {
        kind: "context",
        id: "weather",
        label: "Forecast too old to show",
        detail: `The newest retained forecast for ${where} is older than this build allows, so it is not shown.`,
        tone: "neutral",
      };
    default:
      return {
        kind: "context",
        id: "weather",
        label: "No usable forecast yet",
        detail: `No forecast for ${where} covers this kickoff (${weather.status.replace(/_/g, " ")}).`,
        tone: "neutral",
      };
  }
}

/**
 * The whole reading for one record: P10, P50 and P90 against his typical week, and the
 * context. Null when the record has no distribution (bye, line pending) or no explanation
 * (an older build).
 */
export function whyThisWeek(
  record: WeeklyProjectionRecord,
  own: WeeklyGameContextRecord | null,
  opponent: WeeklyGameContextRecord | null,
): WhyThisWeek | null {
  const floor = level("q10", record, own);
  const median = level("q50", record, own);
  const ceiling = level("q90", record, own);
  if (floor === null || median === null || ceiling === null) return null;
  const context: ContextChip[] = [];
  const weather = weatherChip(own);
  if (weather !== null) context.push(weather);
  context.push(...lineupChips(record, own, opponent));
  return { floor, median, ceiling, context };
}

/** "3.1 above a typical week (21.0)" — the headline a reader keeps. */
export function deltaSentence(reading: LevelReading): string {
  const rounded = Math.round(reading.delta * 10) / 10;
  if (rounded === 0) return `level with a typical week (${one(reading.typical)})`;
  return `${Math.abs(rounded).toFixed(1)} ${rounded > 0 ? "above" : "below"} a typical week (${one(reading.typical)})`;
}

/** The single largest model reason at the median, for a one-cell summary on the week board. */
export function topReason(reading: LevelReading | null): ModelChip | null {
  return reading?.chips[0] ?? null;
}
