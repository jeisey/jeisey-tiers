/**
 * Shared number and time formatting.
 *
 * One module so a rank is an integer everywhere and a VORP carries one decimal everywhere.
 * `docs/UX_SPEC.md` section 7 wants a draft sheet whose columns line up; columns line up
 * when every producer of a number agrees on its precision, and they only agree when there
 * is one producer.
 */

/** Rendered in place of a value the artifact does not carry. Never `0`, never `N/A`. */
export const EM_DASH = "—";

function fixed(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return value.toFixed(digits);
}

/** Fair rank, market rank, tier ordinal: whole numbers. */
export function formatRank(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return String(Math.round(value));
}

/** ADP: one decimal, because MyFantasyLeague publishes an average pick. */
export function formatAdp(value: number | null | undefined): string {
  return fixed(value, 1);
}

/** VORP, fantasy points, uncertainty: one decimal. */
export function formatValue(value: number | null | undefined): string {
  return fixed(value, 1);
}

/** Arbitrage score: the contract is a 0-100 percentile with two decimals of precision. */
export function formatScore(value: number | null | undefined): string {
  return fixed(value, 1);
}

/** Rank gap and trend: signed, because the sign is the whole message (ADR-040). */
export function formatSigned(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  const magnitude = Math.abs(value).toFixed(digits);
  if (Number(magnitude) === 0) return magnitude;
  // U+2212 MINUS SIGN rather than a hyphen: it aligns with the digits and screen readers
  // announce it as "minus", which is the point of showing a sign at all (UX spec section 12).
  return `${value > 0 ? "+" : "\u2212"}${magnitude}`;
}

/** A compact interval, e.g. `11.2 – 19.8`. Both bounds or nothing. */
export function formatRange(
  low: number | null | undefined,
  high: number | null | undefined,
  digits = 1,
): string {
  if (low === null || low === undefined || high === null || high === undefined) return EM_DASH;
  if (!Number.isFinite(low) || !Number.isFinite(high)) return EM_DASH;
  return `${low.toFixed(digits)} – ${high.toFixed(digits)}`;
}

export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return Math.round(value).toLocaleString("en-US");
}

const ET_STAMP = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const ET_DATE = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "short",
  day: "numeric",
  year: "numeric",
});

/**
 * `Aug 20 · 10:38 AM ET`, always Eastern.
 *
 * Eastern rather than the viewer's zone because a fantasy draft calendar is published in
 * Eastern and a reader comparing this against a kickoff time should not have to convert.
 * The exact UTC instant stays available in player and source detail.
 */
export function formatEastern(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return EM_DASH;
  const parts = ET_STAMP.formatToParts(new Date(parsed));
  const get = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${get("month")} ${get("day")} · ${get("hour")}:${get("minute")} ${get("dayPeriod")} ET`;
}

export function formatEasternDate(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return EM_DASH;
  return ET_DATE.format(new Date(parsed));
}

/** `YYYY-MM-DD` in Eastern, for export filenames. Derived from build metadata, never `new Date()`. */
export function easternIsoDate(iso: string | null | undefined): string {
  if (!iso) return "unknown-date";
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "unknown-date";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(parsed));
  const get = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** `3 hours ago` / `2 days ago`, for the freshness line beside the absolute stamp. */
export function formatAge(hours: number): string {
  if (!Number.isFinite(hours)) return EM_DASH;
  if (hours < 1) return "less than an hour ago";
  if (hours < 24) {
    const whole = Math.round(hours);
    return `${String(whole)} hour${whole === 1 ? "" : "s"} ago`;
  }
  const days = Math.round(hours / 24);
  return `${String(days)} day${days === 1 ? "" : "s"} ago`;
}
