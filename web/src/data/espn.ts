/**
 * ESPN's public roster and start percentages, read back for the Opportunity Board and the card
 * (`espn_ownership_v1`, ADR-112).
 *
 * **What these numbers are.** The share of ESPN leagues that roster a player, and ESPN's own
 * start share, read once a day from ESPN's public player data. They describe ESPN's population,
 * not the reader's league, and popularity is crowd interest — not a projection. Nothing here
 * reaches a value, a rank, a tier or a replacement level, and nothing here combines an ESPN
 * percentage with a Sleeper count or a model value: every reading is printed beside the others,
 * never folded into them.
 *
 * **What this module computes: nothing new.** Every number is a published field. The 1- and
 * 7-day changes are the artifact's own `change_pp` (current minus a stated baseline, in
 * percentage points), each with the baseline's time and the actual span. A start-share change, a
 * started-among-rostered ratio and a roster-minus-start gap are deliberately absent: ESPN states
 * neither the start share's denominator nor which week's lineups it counts.
 *
 * **Absences are kinds.** "This build published no ESPN readings", "ESPN published nothing for
 * him", "his ESPN id is ambiguous", "his value failed validation" and "the newest capture is too
 * old to be current" are different facts. None of them is 0%, none passes an active ESPN filter,
 * and every one sorts after every current reading.
 *
 * **Display never contradicts a filter.** A board cell truncates — it never rounds up — so a
 * player at 9.99% reads `9.9%` and is correctly inside "below 10%", and one at 50.00% reads `50%`
 * and is correctly outside "below 50%". The exact value is in the cell's sentence.
 */

import type {
  EspnOwnershipMetadata,
  EspnOwnershipRecord,
  EspnReadingState,
  EspnRosterChange,
} from "./contracts";
import { EM_DASH, formatEastern } from "./format";

// ---------------------------------------------------------------------------- availability

/** Whether this build's ESPN readings can be used at all, and why not. */
export type EspnAvailability =
  /** An older bundle: no ESPN metadata block and no artifact. Nothing to say about ESPN. */
  | { readonly kind: "unpublished" }
  /** Published under a record version this page cannot read. */
  | { readonly kind: "incompatible" }
  /** The build ran the step and published nothing — no capture in the window, or it failed. */
  | { readonly kind: "unavailable"; readonly reason: string }
  /** Published, but the newest capture is past the freshness bound: no reading is current. */
  | { readonly kind: "stale"; readonly meta: EspnOwnershipMetadata }
  | { readonly kind: "published"; readonly meta: EspnOwnershipMetadata };

export function espnAvailability(
  meta: EspnOwnershipMetadata | null | undefined,
  published: boolean,
  compatible = true,
): EspnAvailability {
  if (published && !compatible) return { kind: "incompatible" };
  if (meta === null || meta === undefined) {
    return published ? { kind: "unavailable", reason: "the build recorded no ESPN metadata" } : { kind: "unpublished" };
  }
  if (meta.status !== "published" || !published) {
    return { kind: "unavailable", reason: meta.reason ?? "no ESPN capture was available to this build" };
  }
  return meta.stale === true ? { kind: "stale", meta } : { kind: "published", meta };
}

/** Can the ESPN roster ceiling be applied on this build? */
export function espnFilterUsable(availability: EspnAvailability): boolean {
  return availability.kind === "published";
}

/** Why the ESPN filter is off, in one sentence, or null when it can be applied. */
export function espnFilterUnavailableReason(availability: EspnAvailability): string | null {
  switch (availability.kind) {
    case "published":
      return null;
    case "unpublished":
      return "This build carries no ESPN roster percentages, so the ESPN filter is not applied.";
    case "incompatible":
      return "This build's ESPN readings use a contract this page cannot read; reload for the current page. The ESPN filter is not applied.";
    case "unavailable":
      return `No ESPN roster percentages were published with this build (${availability.reason}), so the ESPN filter is not applied.`;
    case "stale":
      return (
        `ESPN's newest retained reading is ${formatAge(availability.meta.latest_age_hours)} old, past the ` +
        "freshness bound, so no reading is current and the ESPN filter is not applied."
      );
  }
}

function formatAge(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "too";
  return hours >= 48 ? `${String(Math.floor(hours / 24))} days` : `${String(Math.round(hours))} hours`;
}

// --------------------------------------------------------------------------------- signals

export type EspnSignal =
  /** The build carries no usable ESPN readings (see `EspnAvailability`). */
  | { readonly kind: "unavailable" }
  /** Readings are published, and none for this player — not on the board when it was built. */
  | { readonly kind: "no_record" }
  /** A record that holds no reading, with the reason. Never 0%. */
  | {
      readonly kind: "absent";
      readonly state: Exclude<EspnReadingState, "observed" | "stale">;
      readonly record: EspnOwnershipRecord;
    }
  /** Values from a capture past the freshness bound: printed, muted, and never current. */
  | { readonly kind: "stale"; readonly record: EspnOwnershipRecord; readonly rostered: number }
  | { readonly kind: "observed"; readonly record: EspnOwnershipRecord; readonly rostered: number };

export function espnSignal(
  availability: EspnAvailability,
  record: EspnOwnershipRecord | null,
): EspnSignal {
  if (availability.kind !== "published" && availability.kind !== "stale") return { kind: "unavailable" };
  if (record === null) return { kind: "no_record" };
  const rostered = record.percent_rostered;
  if (record.reading_state === "observed" && rostered !== null) return { kind: "observed", record, rostered };
  if (record.reading_state === "stale" && rostered !== null) return { kind: "stale", record, rostered };
  const state = record.reading_state === "observed" || record.reading_state === "stale" ? "invalid" : record.reading_state;
  return { kind: "absent", state, record };
}

/** A current roster reading: the only thing an ESPN filter or the rising evidence may read. */
export function isCurrent(signal: EspnSignal): signal is Extract<EspnSignal, { kind: "observed" }> {
  return signal.kind === "observed";
}

// ---------------------------------------------------------------------------- the ceiling

/** The reader's ESPN roster ceiling, in percent. `all` applies none. */
export const ESPN_CEILINGS = ["all", 10, 25, 50, 75] as const;
export type EspnCeiling = (typeof ESPN_CEILINGS)[number];

export const ESPN_CEILING_LABELS: Readonly<Record<string, string>> = {
  all: "All",
  10: "<10%",
  25: "<25%",
  50: "<50%",
  75: "<75%",
};

/** `lt50` in a URL; `all` is the default and is never written. */
export function serializeCeiling(ceiling: EspnCeiling): string {
  return ceiling === "all" ? "" : `lt${String(ceiling)}`;
}

export function parseCeiling(raw: string | null): { readonly value: EspnCeiling; readonly valid: boolean } {
  if (raw === null) return { value: "all", valid: true };
  const match = /^lt(10|25|50|75)$/.exec(raw);
  if (match === null) return { value: "all", valid: false };
  return { value: Number(match[1]) as EspnCeiling, valid: true };
}

/**
 * Strictly below the ceiling: `percent_rostered < ceiling`, so exactly 10% fails "below 10%".
 * Only a current reading can pass; a stale, absent or invalid one never does.
 */
export function passesCeiling(signal: EspnSignal, ceiling: EspnCeiling): boolean {
  if (ceiling === "all") return true;
  return signal.kind === "observed" && signal.rostered < ceiling;
}

/** `rostered below 50% on ESPN` — the phrase both the chip and the discovery label use. */
export function ceilingPhrase(ceiling: Exclude<EspnCeiling, "all">): string {
  return `rostered below ${String(ceiling)}% on ESPN`;
}

// ------------------------------------------------------------------------------ the readings

/**
 * A board-cell percentage, truncated (never rounded up) so it cannot contradict a ceiling:
 * one decimal below 10%, whole numbers from 10%. `0%` is a reading, not an absence.
 */
export function formatEspnPercent(value: number | null): string {
  if (value === null) return EM_DASH;
  if (value === 0) return "0%";
  if (value < 10) return `${(Math.floor(value * 10) / 10).toFixed(1)}%`;
  return `${String(Math.floor(value))}%`;
}

/** The published value exactly, for sentences and tables: `9.99%`. */
export function exactPercent(value: number): string {
  return `${String(Number(value.toFixed(2)))}%`;
}

/** `+13.0 pp`, `−0.4 pp`, `±0.0 pp` — percentage points, never relative growth. */
export function formatPp(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "±0.0 pp";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)} pp`;
}

function spanDays(hours: number): string {
  const days = hours / 24;
  return Math.abs(days - Math.round(days)) < 0.25
    ? `${String(Math.round(days))} day${Math.round(days) === 1 ? "" : "s"}`
    : `${days.toFixed(1)} days`;
}

export const CHANGE_STATE_TEXT: Readonly<Record<string, string>> = {
  no_current_reading: "no current reading",
  insufficient_history: "not enough history",
  no_baseline_reading: "new since baseline",
  incomparable: "not comparable",
};

/** `+13.0 pp`, or the short reason there is no change. */
export function changeCell(change: EspnRosterChange): string {
  return change.state === "measured" && change.change_pp !== null
    ? formatPp(change.change_pp)
    : (CHANGE_STATE_TEXT[change.state] ?? EM_DASH);
}

/**
 * The change as a sentence: `Rostered on ESPN: 18% → 31% in 7 days (+13 percentage points).`
 * Null when no change is published — the caller says why.
 */
export function changeSentence(current: number, change: EspnRosterChange): string | null {
  if (change.state !== "measured" || change.change_pp === null || change.baseline_percent_rostered === null) {
    return null;
  }
  const span = change.span_hours === null ? "" : ` in ${spanDays(change.span_hours)}`;
  const points = Math.round(change.change_pp * 10) / 10;
  const signed = points === 0 ? "no change" : `${points > 0 ? "+" : "−"}${String(Math.abs(points))} percentage points`;
  return (
    `Rostered on ESPN: ${exactPercent(change.baseline_percent_rostered)} → ${exactPercent(current)}` +
    `${span} (${signed}).`
  );
}

export const ABSENT_TEXT: Readonly<Record<string, { readonly short: string; readonly sentence: string }>> = {
  not_published: {
    short: "not listed",
    sentence: "ESPN publishes no roster percentage for him, which is unknown, not 0%.",
  },
  invalid: {
    short: "invalid",
    sentence: "ESPN's newest value for him failed validation, so no reading is shown.",
  },
  no_espn_id: {
    short: "no ESPN id",
    sentence: "No verified ESPN id is on record for him, so no ESPN reading can be matched.",
  },
  ambiguous_espn_id: {
    short: "id conflict",
    sentence: "His ESPN id is claimed by more than one player, so no reading is matched (fails closed).",
  },
};

export interface EspnCell {
  /** `31%`, `stale`, `not listed`, or an em dash. */
  readonly rostered: string;
  /** `13%` or a short absence. */
  readonly started: string;
  /** `+13.0 pp` or a short reason. */
  readonly change7: string;
  readonly change1: string;
  /** Whether the values are current (false for stale: printed muted). */
  readonly current: boolean;
  /** The whole reading as a sentence for a screen reader and a tooltip. */
  readonly sentence: string;
}

export function espnCell(signal: EspnSignal): EspnCell {
  switch (signal.kind) {
    case "unavailable":
      return {
        rostered: EM_DASH,
        started: EM_DASH,
        change7: "",
        change1: "",
        current: false,
        sentence: "This build published no ESPN roster percentages.",
      };
    case "no_record":
      return {
        rostered: EM_DASH,
        started: EM_DASH,
        change7: "",
        change1: "",
        current: false,
        sentence: "No ESPN reading is published for him on this build.",
      };
    case "absent": {
      const text = ABSENT_TEXT[signal.state] ?? { short: EM_DASH, sentence: "No ESPN reading." };
      return { rostered: text.short, started: EM_DASH, change7: "", change1: "", current: false, sentence: text.sentence };
    }
    case "stale":
    case "observed": {
      const { record, rostered } = signal;
      const started = startedText(record);
      const change7 = changeSentence(rostered, record.rostered_change_7d);
      const stale =
        signal.kind === "stale"
          ? ` Stale: read ${formatEastern(record.observed_at_utc)}, past the freshness bound, so it is not current and passes no ESPN filter.`
          : "";
      return {
        rostered: formatEspnPercent(rostered),
        started: started.short,
        change7: changeCell(record.rostered_change_7d),
        change1: changeCell(record.rostered_change_1d),
        current: signal.kind === "observed",
        sentence:
          `Rostered in ${exactPercent(rostered)} of ESPN leagues; ${started.sentence}` +
          (change7 === null
            ? ` 7-day change: ${CHANGE_STATE_TEXT[record.rostered_change_7d.state] ?? "none"}.`
            : ` ${change7}`) +
          stale,
      };
    }
  }
}

/** The start share's cell and sentence, with its context; never a zero in place of absent. */
export function startedText(record: EspnOwnershipRecord): { readonly short: string; readonly sentence: string } {
  if (record.start_state === "observed" && record.percent_started !== null) {
    const period =
      record.espn_current_period === null ? "" : ` (read during ESPN period ${String(record.espn_current_period)})`;
    return {
      short: formatEspnPercent(record.percent_started),
      sentence: `started in ${exactPercent(record.percent_started)}${period}.`,
    };
  }
  if (record.start_state === "invalid") return { short: "invalid", sentence: "ESPN's start share failed validation." };
  return { short: "not listed", sentence: "ESPN publishes no start share for him (unknown, not 0%)." };
}

// ------------------------------------------------------------------------------- orderings

function tier(signal: EspnSignal): number {
  return signal.kind === "observed" ? 0 : signal.kind === "stale" ? 1 : 2;
}

/**
 * ESPN rostered %, highest first. Current readings first, then stale ones, then every row with
 * no reading — an unknown is never placed between two real percentages. `0` on a tie, for the
 * caller's own deterministic tie-break.
 */
export function compareRostered(a: EspnSignal, b: EspnSignal): number {
  const byTier = tier(a) - tier(b);
  if (byTier !== 0) return byTier;
  const ra = "rostered" in a ? a.rostered : null;
  const rb = "rostered" in b ? b.rostered : null;
  if (ra !== null && rb !== null && ra !== rb) return rb - ra;
  return 0;
}

function measured7(signal: EspnSignal): number | null {
  if (signal.kind !== "observed") return null;
  const change = signal.record.rostered_change_7d;
  return change.state === "measured" ? change.change_pp : null;
}

/** The 7-day roster change in points, largest gain first; current measured changes only first. */
export function compareRosterChange(a: EspnSignal, b: EspnSignal): number {
  const ca = measured7(a);
  const cb = measured7(b);
  if (ca === null && cb === null) return 0;
  if (ca === null) return 1;
  if (cb === null) return -1;
  return cb - ca;
}

/** Supporting evidence, labelled apart: a current reading whose 7-day change is positive. */
export function risingOnEspn(signal: EspnSignal): boolean | null {
  const change = measured7(signal);
  return change === null ? null : change > 0;
}
