/**
 * The availability policy (ADR-101): one place that decides whether a player can be acted on.
 *
 * Every number on this site is the model's, and no model here reads an injury report: the
 * weekly start/sit model projects points **given that he plays**, and the rest-of-season model
 * learned availability from appearances, not from news. So a newly announced season-ending
 * injury changes no projection, and must not — retraining on a feed nobody validated would be
 * worse. What it must change is what the page *recommends*: a player who will not play cannot
 * win a Start/Sit verdict, be Pick of the Week, or be suggested as a trade target. That is a
 * decision about eligibility and presentation, made here, from published evidence, and it
 * never touches a projection, a VORP, a rank, a tier or a calibration figure.
 *
 * ## Evidence, kept distinct
 *
 * - **Roster code** (nflverse `roster_status`, or a board row's `current_status`): where he is
 *   on a roster. `RES`/`PUP`/`NFI`/`SUS`/`EXE` are reserve-type lists; `INA` is "inactive for
 *   his latest game"; `CUT` released; `RET` retired.
 * - **Injury status** (Sleeper `injury_status`/`status`): `Questionable`/`Doubtful`/`Out` are
 *   game designations; `IR`, `PUP`, `NFI`, `Sus` and their spelled-out forms are reserve lists.
 * - **The official report** (`weekly_projections[].injury`): the league's designation for the
 *   target week, as nflverse publishes it.
 * - **A reviewed override** (`player_status.availability_override`): a person recorded reliable
 *   reporting that his season is over. Neither feed can say that — `RES` and `IR` are the same
 *   for two weeks and for the rest of the year — so it is never inferred from a code.
 *
 * ## Precedence
 *
 * 1. Retired, or a reviewed season-ending override **corroborated** by a reserve-list reading,
 *    is out for the season. An override with both feeds showing him active is a conflict: the
 *    entry is not honoured, and the page says the sources disagree (recovery when he returns).
 * 2. A reserve-list reading from either feed is "unavailable now, return uncertain", unless
 *    the other feed affirmatively clears him, which is a conflict.
 * 3. Released (`CUT`): unavailable now, not on an NFL roster.
 *
 * ADR-102 adds the employment reading (`player_status.employment_status`, from the season
 * roster, then a fresh Sleeper record): a verified **unsigned** player is unavailable now —
 * "FA", a speculative stash, never a current-week choice — right after retirement and ahead
 * of every injury reading; a **signing** only Sleeper reports is uncertain, ahead of a stale
 * `CUT`, until the official roster lists him.
 * 4. The worst game designation across the official report and Sleeper. Two sources that
 *    disagree are both shown, and the more severe one governs the decision.
 * 5. `INA` with no designation: uncertain for this game.
 * 6. No designation, with a current Sleeper record and an active roster code: available.
 *    Anything less — no status record, the feed down, an identity refusal, a record older than
 *    48 hours at build time, another season's record — is **uncertain**, never "healthy".
 *
 * ## This week versus the rest of the season
 *
 * `week` answers "can he fill a lineup slot in the target week"; `horizon` answers "is his
 * remaining season still worth acting on". An OUT designation removes him from this week's
 * verdict and leaves his rest of season alone (with a warning); a reserve list mutes both and
 * says the return is uncertain; only a corroborated override or retirement ends the season.
 */

import type { AvailabilityOverrideRecord, PlayerStatusRecord, WeeklyProjectionRecord } from "./contracts";

/** A status record older than this, at the time the decision was built, is not current. */
export const STATUS_STALE_HOURS = 48;

export type WeekAvailability =
  /** Nothing reported against him, from current evidence. */
  | "available"
  | "questionable"
  | "doubtful"
  /** Designated out for the target week's game. */
  | "out"
  /** On a reserve list, released, retired or out for the season: not this week either. */
  | "unavailable"
  /** Missing, stale or contradictory evidence. Never read as healthy. */
  | "uncertain";

export type HorizonAvailability =
  | "available"
  /** A game designation or a short absence: a warning, not a removal. */
  | "caution"
  /** Reserve list or released: unavailable now, return uncertain. */
  | "unavailable_now"
  /** Retired, or a corroborated reviewed override. */
  | "season_over"
  | "uncertain";

export type AvailabilityKind =
  | "season_over"
  | "retired"
  | "reserve"
  | "released"
  /** ADR-102: verified free agent — no NFL club, so not playable until he signs. */
  | "unsigned"
  /** ADR-102: a signing Sleeper reports that the official roster file does not list yet. */
  | "signing"
  | "out"
  | "doubtful"
  | "questionable"
  | "inactive"
  | "conflict"
  | "stale"
  | "unknown"
  | "available";

/** The fields of a status record the policy reads: the `player_availability` slice. */
export type StatusEvidence = Pick<
  PlayerStatusRecord,
  "player_id" | "roster_status" | "sleeper_status" | "injury_status" | "observed_at_utc" | "quality_flags"
> &
  Partial<
    Pick<
      PlayerStatusRecord,
      | "season"
      | "injury_body_part"
      | "availability_override"
      | "current_team"
      | "employment_status"
      | "employment_source"
    >
  >;

export interface AvailabilityEvidence {
  readonly status: StatusEvidence | null;
  /** The board row's `current_status` (nflverse, at the board's build), as a fallback. */
  readonly rosterCode?: string | null;
  /** The official report for the target week, from the weekly record. */
  readonly report?: WeeklyProjectionRecord["injury"] | null;
  /** When the decision was built (ISO). Freshness and override expiry are measured here. */
  readonly referenceTime: string;
  /** The season the decision is about. A status record for another season is not evidence. */
  readonly season: number;
}

export interface Availability {
  readonly week: WeekAvailability;
  readonly horizon: HorizonAvailability;
  readonly kind: AvailabilityKind;
  /** Chip text, readable without colour; null when there is nothing to say. */
  readonly short: string | null;
  /** One line: what this means for a decision. */
  readonly headline: string;
  /** The evidence, its sources and its time. */
  readonly detail: string;
  readonly severity: "none" | "info" | "caution" | "warn";
  readonly stale: boolean;
  readonly conflict: boolean;
  /** The honoured override, when one decided the reading. */
  readonly override: AvailabilityOverrideRecord | null;
  readonly observedAt: string | null;
}

// ----------------------------------------------------------------------- normalisation

type RosterKind = "active" | "practice_squad" | "reserve" | "inactive" | "released" | "retired" | "other";

const ROSTER_RESERVE = new Set(["RES", "PUP", "NFI", "SUS", "EXE", "E14"]);
const ROSTER_NAMES: Readonly<Record<string, string>> = {
  RES: "reserve list",
  PUP: "physically-unable-to-perform list",
  NFI: "non-football-injury list",
  SUS: "suspended list",
  EXE: "exempt list",
  E14: "exempt list",
  INA: "inactive",
  CUT: "released",
  RET: "retired",
};

export function rosterKind(code: string | null | undefined): RosterKind | null {
  if (code === null || code === undefined || code.trim() === "") return null;
  const value = code.trim().toUpperCase();
  if (value === "ACT" || value === "A01") return "active";
  if (value === "DEV") return "practice_squad";
  if (ROSTER_RESERVE.has(value)) return "reserve";
  if (value === "INA") return "inactive";
  if (value === "CUT") return "released";
  if (value === "RET") return "retired";
  return "other";
}

type InjuryKind = "questionable" | "doubtful" | "out" | "reserve" | "note";

/** Verified aliases only: what Sleeper and the official report actually publish. */
const INJURY_ALIASES: Readonly<Record<string, { kind: InjuryKind; short: string; name: string }>> = {
  questionable: { kind: "questionable", short: "Q", name: "Questionable" },
  q: { kind: "questionable", short: "Q", name: "Questionable" },
  doubtful: { kind: "doubtful", short: "D", name: "Doubtful" },
  d: { kind: "doubtful", short: "D", name: "Doubtful" },
  out: { kind: "out", short: "OUT", name: "Out" },
  o: { kind: "out", short: "OUT", name: "Out" },
  ir: { kind: "reserve", short: "IR", name: "injured reserve" },
  "injured reserve": { kind: "reserve", short: "IR", name: "injured reserve" },
  pup: { kind: "reserve", short: "PUP", name: "physically-unable-to-perform list" },
  "physically unable to perform": { kind: "reserve", short: "PUP", name: "physically-unable-to-perform list" },
  nfi: { kind: "reserve", short: "NFI", name: "non-football-injury list" },
  "non football injury": { kind: "reserve", short: "NFI", name: "non-football-injury list" },
  sus: { kind: "reserve", short: "SUS", name: "suspended list" },
  suspended: { kind: "reserve", short: "SUS", name: "suspended list" },
  cov: { kind: "reserve", short: "COV", name: "reserve/COVID-19 list" },
};

export function injuryKind(
  value: string | null | undefined,
): { readonly kind: InjuryKind; readonly short: string; readonly name: string } | null {
  if (value === null || value === undefined || value.trim() === "") return null;
  const entry = INJURY_ALIASES[value.trim().toLowerCase()];
  return entry ?? { kind: "note", short: value.trim().toUpperCase().slice(0, 4), name: value.trim() };
}

const DESIGNATION_ORDER: Readonly<Record<"questionable" | "doubtful" | "out", number>> = {
  questionable: 1,
  doubtful: 2,
  out: 3,
};

// ----------------------------------------------------------------------------- policy

interface DesignationReading {
  readonly kind: "questionable" | "doubtful" | "out";
  readonly source: string;
  readonly name: string;
}

const SLEEPER_MISSING_FLAGS = ["sleeper_unavailable", "sleeper_record_missing", "sleeper_identity_conflict"];

function hoursBetween(earlier: string, later: string): number {
  return (Date.parse(later) - Date.parse(earlier)) / 3_600_000;
}

function shortDate(iso: string): string {
  return iso.slice(0, 10);
}

function result(
  partial: Omit<Availability, "stale" | "conflict" | "override" | "observedAt"> &
    Partial<Pick<Availability, "stale" | "conflict" | "override" | "observedAt">>,
): Availability {
  return { stale: false, conflict: false, override: null, observedAt: null, ...partial };
}

/** The reading for one player, from whatever evidence the open view has. Pure. */
export function readAvailability(evidence: AvailabilityEvidence): Availability {
  const sameSeason =
    evidence.status !== null &&
    (evidence.status.season === undefined || evidence.status.season === evidence.season);
  const status = sameSeason ? evidence.status : null;
  const observedAt = status?.observed_at_utc ?? null;
  const stale =
    observedAt !== null && hoursBetween(observedAt, evidence.referenceTime) > STATUS_STALE_HOURS;
  const asOf = observedAt === null ? "" : ` Status observed ${shortDate(observedAt)}.`;

  const rosterCode = status?.roster_status ?? evidence.rosterCode ?? null;
  const roster = rosterKind(rosterCode);
  const sleeperMissing =
    status === null || SLEEPER_MISSING_FLAGS.some((flag) => status.quality_flags.includes(flag));
  const sleeperInjury = sleeperMissing ? null : injuryKind(status.injury_status);
  const sleeperStatus = sleeperMissing ? null : injuryKind(status.sleeper_status);
  const sleeperActive =
    !sleeperMissing &&
    (status.sleeper_status ?? "").trim().toLowerCase() === "active" &&
    sleeperInjury === null;

  const employment = status?.employment_status ?? null;

  // --- 1. the season is over
  if (roster === "retired" || employment === "retired") {
    return result({
      week: "unavailable",
      horizon: "season_over",
      kind: "retired",
      short: "RET",
      headline: "Retired",
      detail: `The current roster records him as retired.${asOf}`,
      severity: "warn",
      observedAt,
    });
  }

  // --- 1b. a verified free agent (ADR-102)
  if (employment === "unsigned") {
    return result({
      week: "unavailable",
      horizon: "unavailable_now",
      kind: "unsigned",
      short: "FA",
      headline: "Unsigned free agent — speculative stash",
      detail:
        `Not on an NFL roster: the current roster does not list him and Sleeper shows no club.${asOf} ` +
        "He cannot play until he signs. Any rest-of-season value shown is the model's own, from " +
        "before any signing, and assumes nothing about where he goes.",
      severity: "warn",
      stale,
      observedAt,
    });
  }

  const sleeperReserve =
    sleeperInjury?.kind === "reserve" ? sleeperInjury : sleeperStatus?.kind === "reserve" ? sleeperStatus : null;
  const rosterReserve = roster === "reserve";
  const anyReserve = rosterReserve || sleeperReserve !== null;
  const rosterActive = roster === "active";

  const override = status?.availability_override ?? null;
  const overrideInForce =
    override !== null &&
    override !== undefined &&
    Date.parse(`${override.expires_at}T00:00:00Z`) > Date.parse(evidence.referenceTime);
  if (overrideInForce) {
    if (anyReserve) {
      return result({
        week: "unavailable",
        horizon: "season_over",
        kind: "season_over",
        short: "OUT · season",
        headline: "Out for the season",
        detail:
          `${override.summary} Reviewed ${override.reviewed_at}; the feeds still list him on ` +
          `${sleeperReserve?.name ?? ROSTER_NAMES[(rosterCode ?? "").toUpperCase()] ?? "a reserve list"}.` +
          `${asOf} The projections are unchanged: the model does not read injury news.`,
        severity: "warn",
        override,
        stale,
        observedAt,
      });
    }
    if (rosterActive && sleeperActive) {
      return result({
        week: "uncertain",
        horizon: "uncertain",
        kind: "conflict",
        short: "?",
        headline: "Sources disagree",
        detail:
          `A reviewed report (${override.reviewed_at}) said his season was over, but both feeds now ` +
          `list him active. The report is not applied until it is reviewed again.${asOf}`,
        severity: "caution",
        conflict: true,
        stale,
        observedAt,
      });
    }
  }

  // --- 2. a reserve list
  if (anyReserve) {
    const cleared = (rosterReserve && sleeperActive) || (sleeperReserve !== null && rosterActive);
    const source =
      sleeperReserve !== null
        ? `Sleeper lists him on ${sleeperReserve.name}`
        : `the roster lists him on the ${ROSTER_NAMES[(rosterCode ?? "").toUpperCase()] ?? "reserve list"}`;
    if (cleared) {
      return result({
        week: "uncertain",
        horizon: "uncertain",
        kind: "conflict",
        short: "?",
        headline: "Sources disagree",
        detail:
          `${sleeperReserve !== null ? "Sleeper lists him on " + sleeperReserve.name + " but the roster code is active" : "The roster code is " + (rosterCode ?? "") + " but Sleeper lists him active with no injury"}. ` +
          `Treated as uncertain, not as available.${asOf}`,
        severity: "caution",
        conflict: true,
        stale,
        observedAt,
      });
    }
    return result({
      week: "unavailable",
      horizon: "unavailable_now",
      kind: "reserve",
      short: sleeperReserve?.short ?? (rosterCode ?? "RES").toUpperCase(),
      headline: "Unavailable now — return date unknown",
      detail:
        `${source.charAt(0).toUpperCase()}${source.slice(1)}${status?.injury_body_part ? ` (${status.injury_body_part})` : ""}. ` +
        `A reserve list says he cannot play now; it does not say when he returns, or that his season is over.${asOf}`,
      severity: "warn",
      stale,
      observedAt,
    });
  }

  // --- 2b. a signing the official roster has not caught up with (ADR-102)
  if (employment === "signed" && status?.employment_source === "sleeper") {
    return result({
      week: "uncertain",
      horizon: "uncertain",
      kind: "signing",
      short: "NEW",
      headline: "Signing reported — not yet on the official roster",
      detail:
        `Sleeper lists him with ${status.current_team ?? "a club"}; the official roster file does not ` +
        `list him there yet.${asOf} Treated as uncertain until it does: no weekly projection is ` +
        "made for him and he is not featured.",
      severity: "caution",
      stale,
      observedAt,
    });
  }

  // --- 3. released
  if (roster === "released") {
    return result({
      week: "unavailable",
      horizon: "unavailable_now",
      kind: "released",
      short: "CUT",
      headline: "Released — not on an NFL roster",
      detail: `The current roster records him as released.${asOf}`,
      severity: "warn",
      stale,
      observedAt,
    });
  }

  // --- 4. a game designation
  const readings: DesignationReading[] = [];
  const official = injuryKind(evidence.report?.designation ?? null);
  if (official !== null && official.kind !== "reserve" && official.kind !== "note") {
    readings.push({ kind: official.kind, source: `the official week ${String(evidence.report?.week ?? "")} report`, name: official.name });
  }
  if (sleeperInjury !== null && sleeperInjury.kind !== "reserve" && sleeperInjury.kind !== "note") {
    readings.push({ kind: sleeperInjury.kind, source: "Sleeper", name: sleeperInjury.name });
  }
  if (readings.length > 0) {
    const worst = readings.reduce((a, b) => (DESIGNATION_ORDER[b.kind] > DESIGNATION_ORDER[a.kind] ? b : a));
    const disagree = new Set(readings.map((reading) => reading.kind)).size > 1;
    const body = status?.injury_body_part ? ` (${status.injury_body_part})` : "";
    const sources = disagree
      ? `${readings.map((reading) => `${reading.name} on ${reading.source}`).join("; ")} — the more severe one governs`
      : `${worst.name} on ${readings.map((reading) => reading.source).join(" and ")}`;
    const headline =
      worst.kind === "out"
        ? "Out this week"
        : worst.kind === "doubtful"
          ? "Doubtful this week"
          : "Questionable this week";
    return result({
      week: worst.kind,
      horizon: "caution",
      kind: worst.kind,
      short: worst.kind === "out" ? "OUT" : worst.kind === "doubtful" ? "D" : "Q",
      headline,
      detail:
        `${sources}${body}. ` +
        (worst.kind === "out"
          ? "A game designation is for one game; his rest of season is not zeroed."
          : "Projections assume he plays.") +
        asOf,
      severity: worst.kind === "questionable" ? "caution" : "warn",
      conflict: disagree,
      stale,
      observedAt,
    });
  }

  // --- 5. inactive for his latest game
  if (roster === "inactive") {
    return result({
      week: "uncertain",
      horizon: "caution",
      kind: "inactive",
      short: "INA",
      headline: "Inactive for his latest game",
      detail: `The roster lists him inactive for his latest game, and no designation for the next one has been reported.${asOf}`,
      severity: "caution",
      stale,
      observedAt,
    });
  }

  // --- 6. nothing reported: available only on current, complete evidence
  if (status === null) {
    return result({
      week: "uncertain",
      horizon: "uncertain",
      kind: "unknown",
      short: "?",
      headline: "Status unknown",
      detail:
        evidence.status !== null
          ? "The status record is for another season, so his current status is unknown."
          : "No status record was published for him, so his current status is unknown — not confirmed healthy.",
      severity: "info",
    });
  }
  if (sleeperMissing) {
    return result({
      week: "uncertain",
      horizon: "uncertain",
      kind: "unknown",
      short: "?",
      headline: "Status unknown",
      detail: `No injury feed record is attached to him in this build, so no designation is known — not confirmed healthy.${asOf}`,
      severity: "info",
      stale,
      observedAt,
    });
  }
  if (stale) {
    return result({
      week: "uncertain",
      horizon: "uncertain",
      kind: "stale",
      short: "?",
      headline: "Status may be out of date",
      detail: `The newest status reading is more than ${String(STATUS_STALE_HOURS)} hours older than this build.${asOf}`,
      severity: "info",
      stale: true,
      observedAt,
    });
  }
  return result({
    week: "available",
    horizon: "available",
    kind: "available",
    short: null,
    headline: "No designation reported",
    detail: `No injury designation or reserve list is reported for him.${asOf}`,
    severity: "none",
    observedAt,
  });
}

// --------------------------------------------------------------------------- decisions

/** Can he receive a Start/Sit verdict? Questionable and uncertain stay comparable, labelled. */
export function startEligible(availability: Availability): boolean {
  return (
    availability.week === "available" ||
    availability.week === "questionable" ||
    availability.week === "uncertain"
  );
}

/** Why he is left out of the verdict, or null. */
export function startExclusion(availability: Availability): string | null {
  switch (availability.week) {
    case "out":
      return "Out this week — left out of the verdict.";
    case "doubtful":
      return "Doubtful this week — left out of the verdict. The numbers below assume he plays.";
    case "unavailable":
      return `${availability.headline} — left out of the verdict.`;
    default:
      return null;
  }
}

/** Does he belong in the default, actionable rest-of-season ranking? */
export function rosActionable(availability: Availability): boolean {
  return availability.horizon !== "season_over";
}

export type TradeTargetBlock = "season_over" | "unavailable_now";

/** Why he cannot be suggested as an incoming target, or null. */
export function tradeTargetBlock(
  availability: Availability,
  includeReturning: boolean,
): TradeTargetBlock | null {
  if (availability.horizon === "season_over") return "season_over";
  if (availability.horizon === "unavailable_now" && !(includeReturning && availability.kind === "reserve")) {
    return "unavailable_now";
  }
  return null;
}

export type OutgoingReading = "ok" | "warn" | "blocked";

/**
 * How an outgoing player's published value may be used as a trade budget.
 *
 * A season that is over cannot finance anything with a projection that predates the news; a
 * reserve list, a release or an uncertain reading still lets the search run, with the
 * warning printed beside the budget rather than hidden.
 */
export function tradeOutgoing(availability: Availability): OutgoingReading {
  if (availability.horizon === "season_over") return "blocked";
  if (
    availability.horizon === "unavailable_now" ||
    availability.horizon === "uncertain" ||
    availability.week === "out" ||
    availability.week === "doubtful"
  ) {
    return "warn";
  }
  return "ok";
}

/** Can he be featured as Pick of the Week? Only if he can play this week and after it. */
export function featureable(availability: Availability): boolean {
  return (
    (availability.week === "available" ||
      availability.week === "questionable" ||
      (availability.week === "uncertain" &&
        availability.kind !== "inactive" &&
        availability.kind !== "conflict" &&
        availability.kind !== "signing")) &&
    (availability.horizon === "available" ||
      availability.horizon === "caution" ||
      availability.horizon === "uncertain")
  );
}

/** Whether the row should be visibly muted (with text) as not actionable now. */
export function isMuted(availability: Availability): boolean {
  return availability.week === "unavailable" || availability.week === "out";
}
