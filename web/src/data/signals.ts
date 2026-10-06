/**
 * The in-season signal layer, read for a card: which facts each position leads with, and how
 * each is stated (ADR-091).
 *
 * **Presentation, not computation.** Every number a surface prints from here is a published
 * field of `player_usage.json` or `team_matchups.json`, read back verbatim — the change
 * beside a share is the artifact's own `role_changes[...].change`, never a subtraction done
 * in the browser, and the implied points beside a matchup are the artifact's own. The only
 * arithmetic is formatting and the cohort ranks `cohort.ts` already licenses (ADR-086).
 *
 * **Position decides what leads, and this is the one place that says so.** The EDA found
 * that every card showed the same two shares for every position, which gave a quarterback two
 * constants — 100% of snaps, 0% of targets — and then ranked them (`SIGNAL_EXPANSION_EDA.md`
 * Part 2b). The map below is the fix: a quarterback's role is whether he is throwing and
 * running; a back's is whether he is on the field and carrying; a receiver's is whether he is
 * on the field, targeted and targeted deep; a tight end's is the field and the targets.
 *
 * **Four kinds of fact, never blended.** Observed role, observed production, matchup context
 * and market behaviour each keep their own block and their own heading, for the reason every
 * surface in this product gives: they share no unit, and one number made of them would be the
 * most confident-looking figure on the page (AGENTS.md section 10, ADR-086, ADR-088).
 */

import { cohortStat, finiteValues, type CohortStat } from "./cohort";
import type {
  DriveBreadth,
  DriveBreadthMetric,
  PlayerUsageRecord,
  UsageCohortRecord,
  Position,
  RoleChange,
  RoleMetric,
  ScoringPreset,
  TeamMatchupRecord,
  UsageWeek,
  UsageWeekStatus,
} from "./contracts";
import { EM_DASH, formatValue } from "./format";

/** Bump when which facts a position leads with, or how one is stated, changes. */
export const SIGNAL_PRESENTATION_VERSION = "signal_presentation_v1";

/** What formatting and direction need from a rail's metric: its unit. */
export interface RailUnit {
  /** A share is 0–1 on an absolute axis; a count is scaled to the player's own peak. */
  readonly unit: "share" | "count";
}

export interface RoleMetricSpec extends RailUnit {
  readonly metric: RoleMetric;
  readonly label: string;
  /** The label a board cell has room for (ADR-092). The card prints `label`. */
  readonly short: string;
  /** The question the reading answers, in the reader's words. */
  readonly question: string;
  readonly weekValue: (week: UsageWeek) => number | null;
}

export const ROLE_METRIC_SPECS: Readonly<Record<RoleMetric, RoleMetricSpec>> = {
  snap_share: {
    metric: "snap_share",
    label: "Snap share",
    short: "Snap",
    unit: "share",
    question: "Is he on the field more?",
    weekValue: (week) => week.snap_share,
  },
  target_share: {
    metric: "target_share",
    label: "Target share",
    short: "Tgt share",
    unit: "share",
    question: "Is he getting more of his team's targets?",
    weekValue: (week) => week.target_share,
  },
  carry_share: {
    metric: "carry_share",
    label: "Carry share",
    short: "Carry share",
    unit: "share",
    question: "Is he taking over the backfield?",
    weekValue: (week) => week.carry_share,
  },
  air_yards_share: {
    metric: "air_yards_share",
    label: "Air-yards share",
    short: "Air yds",
    unit: "share",
    question: "Is he getting the downfield looks, caught or not?",
    weekValue: (week) => week.air_yards_share,
  },
  pass_attempts: {
    metric: "pass_attempts",
    label: "Pass attempts",
    short: "Pass att",
    unit: "count",
    question: "Is he the one throwing?",
    weekValue: (week) => week.pass_attempts,
  },
  carries: {
    metric: "carries",
    label: "Rush attempts",
    short: "Rush att",
    unit: "count",
    question: "Is he running?",
    weekValue: (week) => week.carries,
  },
};

/**
 * What each position's role block leads with, in order. The first two are what Pick of the
 * Week states; the card draws them all.
 *
 * Snap share leads for backs, receivers and tight ends because it is the reading that moves
 * *first* — a role is handed to a player before the ball is — and the one a reader checks
 * when asking whether a big week was a role or a one-off.
 */
export const ROLE_METRICS_BY_POSITION: Readonly<Record<Position, readonly RoleMetric[]>> = {
  QB: ["pass_attempts", "carries"],
  RB: ["snap_share", "carry_share", "target_share"],
  WR: ["snap_share", "target_share", "air_yards_share"],
  TE: ["snap_share", "target_share"],
  K: [],
  DST: [],
};

export type ChangeDirection = "up" | "down" | "flat";

export interface RoleBar {
  readonly week: number;
  readonly status: UsageWeekStatus;
  /** The published value, or null — a bye, a missed week, or a metric the week lacks. */
  readonly value: number | null;
  readonly latest: boolean;
}

export interface RoleReading {
  readonly spec: RoleMetricSpec;
  /** The artifact's own `role_change_v1` entry, or null when the latest game has no value. */
  readonly change: RoleChange | null;
  readonly bars: readonly RoleBar[];
  /** The top of the bar axis: 1 for a share, the player's own peak for a count. */
  readonly axisMax: number;
  /** From the sign of the published change; null when no change is published. */
  readonly direction: ChangeDirection | null;
}

/**
 * The direction as the reader will see it: from the change *at the precision it is printed*,
 * so a glyph can never point down beside text that says "no change". A snap share that moved
 * by 0.3 points is printed as "no change" and marked flat.
 */
function directionOf(
  spec: RailUnit,
  change: number | null | undefined,
): ChangeDirection | null {
  if (change === null || change === undefined || !Number.isFinite(change)) return null;
  if (printedMagnitude(spec, change) === 0) return "flat";
  return change > 0 ? "up" : "down";
}

function printedMagnitude(spec: RailUnit, change: number): number {
  return spec.unit === "share" ? Math.round(Math.abs(change) * 100) : Math.round(Math.abs(change));
}

/** One metric's week-by-week bars and its published change. */
export function roleReading(record: PlayerUsageRecord, metric: RoleMetric): RoleReading {
  const spec = ROLE_METRIC_SPECS[metric];
  const change = record.role_changes[metric];
  const bars = record.weeks.map((week) => ({
    week: week.week,
    status: week.status,
    value: spec.weekValue(week),
    latest: change !== null && week.week === change.latest_week,
  }));
  const peak = Math.max(0, ...finiteValues(bars.map((bar) => bar.value)));
  return {
    spec,
    change,
    bars,
    axisMax: spec.unit === "share" ? 1 : Math.max(1, peak),
    direction: directionOf(spec, change?.change),
  };
}

export function roleReadingsFor(
  record: PlayerUsageRecord,
  position: Position = record.position,
): readonly RoleReading[] {
  return ROLE_METRICS_BY_POSITION[position].map((metric) => roleReading(record, metric));
}

/** Fantasy points per week in the reader's preset: the production rail under the role rails. */
export function productionBars(
  record: PlayerUsageRecord,
  scoring: ScoringPreset,
): { readonly bars: readonly RoleBar[]; readonly axisMax: number } {
  const lastPlayed = [...record.weeks].reverse().find((week) => week.status === "played")?.week;
  const bars = record.weeks.map((week) => ({
    week: week.week,
    status: week.status,
    value: week.fantasy_points?.[scoring] ?? null,
    latest: week.week === lastPlayed,
  }));
  const peak = Math.max(0, ...finiteValues(bars.map((bar) => bar.value)));
  return { bars, axisMax: Math.max(1, peak) };
}

/** `72%`. A share's own value, never rescaled. */
export function formatShare(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return `${String(Math.round(value * 100))}%`;
}

/** The value of one metric in its own unit: `72%` for a share, `31` for a count. */
export function formatMetric(spec: RailUnit, value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return spec.unit === "share" ? formatShare(value) : String(Math.round(value));
}

/**
 * The published change in the metric's own unit: `+18 pts` for a share (percentage points,
 * because a change of shares is a difference and not a ratio), `+2` for a count.
 *
 * U+2212 for a minus, as `formatSigned` does. A change that rounds to nothing says `no change`
 * rather than `+0 pts`, which would read as a direction.
 */
export function formatChange(spec: RailUnit, change: number | null | undefined): string {
  if (change === null || change === undefined || !Number.isFinite(change)) return EM_DASH;
  const magnitude = printedMagnitude(spec, change);
  if (magnitude === 0) return "no change";
  const sign = change > 0 ? "+" : "−";
  return spec.unit === "share" ? `${sign}${String(magnitude)} pts` : `${sign}${String(magnitude)}`;
}

export const DIRECTION_GLYPH: Readonly<Record<ChangeDirection, string>> = {
  up: "▲",
  down: "▼",
  flat: "▬",
};

/**
 * The window a change was measured over, in words: `week 8 vs 7 earlier games`.
 *
 * Never absent when a change is printed, for the reason `span_days` travels with every
 * momentum reading (ADR-089): a change against one earlier game and a change against seven
 * are different claims, and the reader gets to see which one they have.
 */
export function changeWindow(change: RoleChange): string {
  const games = change.earlier_games;
  if (games === 0 || change.earlier === null) return `week ${String(change.latest_week)} only`;
  return `week ${String(change.latest_week)} vs ${String(games)} earlier game${games === 1 ? "" : "s"}`;
}

/** The sentence a screen reader gets for one role reading. */
export function roleSentence(reading: RoleReading): string {
  const { spec, change } = reading;
  if (change === null) return `${spec.label}: no value in his latest game.`;
  const latest = formatMetric(spec, change.latest);
  if (change.earlier === null || change.change === null) {
    return `${spec.label}: ${latest} in week ${String(change.latest_week)}; no earlier game to compare.`;
  }
  return (
    `${spec.label}: ${latest} in week ${String(change.latest_week)}, ` +
    `${formatChange(spec, change.change)} against ${formatMetric(spec, change.earlier)} ` +
    `over his ${String(change.earlier_games)} earlier game${change.earlier_games === 1 ? "" : "s"}.`
  );
}

// ------------------------------------------------------------------------ sustainability

/**
 * Where a player's touchdown share and pass EPA sit among the same position's published usage
 * records. `cohort.ts`'s rank-among-published-rows, over a second artifact, with the
 * denominator carried — the same licence ADR-086 gave the card's other readings.
 */
export interface UsageCohort {
  readonly touchdownShare: CohortStat | null;
  readonly passEpa: CohortStat | null;
}

export function buildUsageCohort(
  records: readonly UsageCohortRecord[],
  record: UsageCohortRecord,
  scoring: ScoringPreset,
): UsageCohort {
  const peers = records.filter((row) => row.position === record.position);
  return {
    touchdownShare: cohortStat(
      finiteValues(peers.map((row) => row.touchdown_points_share[scoring])),
      record.touchdown_points_share[scoring],
      "desc",
      { low: 0, high: 1 },
    ),
    passEpa: cohortStat(
      finiteValues(peers.map((row) => row.pass_epa_per_dropback)),
      record.pass_epa_per_dropback,
      "desc",
    ),
  };
}

/** `0.14` EPA per dropback, signed: the sign is most of what the number says. */
export function formatEpa(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  const magnitude = Math.abs(value).toFixed(2);
  if (Number(magnitude) === 0) return magnitude;
  return `${value > 0 ? "+" : "−"}${magnitude}`;
}

// ------------------------------------------------------------------------------- matchup

export interface MatchupReading {
  readonly record: TeamMatchupRecord;
  /** `vs CHI` at home, `@ CHI` away. */
  readonly opponentLabel: string;
  /** `Favoured by 3.5`, `Underdog by 3.5`, `Pick'em`, or null when no line is posted. */
  readonly spreadLabel: string | null;
  /** The first bye after the cutoff and before this game — "on bye next week". */
  readonly byeBeforeGame: number | null;
  readonly nextBye: number | null;
  readonly linesPosted: boolean;
}

export function matchupReading(record: TeamMatchupRecord): MatchupReading {
  const margin = record.team_expected_margin;
  const spreadLabel =
    margin === null
      ? null
      : margin === 0
        ? "Pick'em"
        : margin > 0
          ? `Favoured by ${formatValue(margin)}`
          : `Underdog by ${formatValue(Math.abs(margin))}`;
  const byes = [...record.upcoming_bye_weeks].sort((a, b) => a - b);
  return {
    record,
    opponentLabel: `${record.home_away === "home" ? "vs" : "@"} ${record.opponent}`,
    spreadLabel,
    byeBeforeGame: byes.find((week) => week < record.week) ?? null,
    nextBye: byes[0] ?? null,
    linesPosted: record.total_line !== null || record.team_expected_margin !== null,
  };
}

/**
 * The implied-points split as two fractions of the posted total, for a two-segment bar.
 * Null unless both implied scores are published. Arithmetic over two published numbers and
 * their published sum; it states nothing the three numbers printed beside it do not.
 */
export function impliedSplit(
  record: TeamMatchupRecord,
): { readonly team: number; readonly opponent: number } | null {
  const mine = record.implied_team_points;
  const theirs = record.implied_opponent_points;
  if (mine === null || theirs === null) return null;
  const total = mine + theirs;
  if (!(total > 0)) return null;
  return { team: mine / total, opponent: theirs / total };
}

// --------------------------------------------------------- drive breadth (ADR-103, ADR-104)

/**
 * The card's words for each position's drive rail, in the rails' own form: a noun and the
 * reader's question. `one` is a single opportunity and `drives` the denominator — which of the
 * team's drives count — for the sentence; `noun` is his opportunities, for the "too few" line.
 */
export const BREADTH_LABELS: Readonly<
  Record<
    DriveBreadthMetric,
    {
      readonly label: string;
      readonly question: string;
      readonly noun: string;
      readonly one: string;
      readonly drives: string;
    }
  >
> = {
  designed_runs: {
    label: "Designed-run drives",
    question: "Are runs called for him?",
    noun: "designed runs",
    one: "a designed run",
    drives: "team drives",
  },
  backfield: {
    label: "Drives with a touch",
    question: "Every series, or a rotation?",
    noun: "carries and targets",
    one: "a carry or target",
    drives: "drives on which a back got the ball",
  },
  targets: {
    label: "Drives targeted",
    question: "A target on every drive?",
    noun: "targets",
    one: "a target",
    drives: "drives with a target",
  },
  open_field_targets: {
    label: "Drives targeted",
    question: "Between the 20s, every drive?",
    noun: "targets outside the red zone",
    one: "a target outside the red zone",
    drives: "drives with one",
  },
};

const SHARE: RailUnit = { unit: "share" };

const WITHHELD_TEXT: Readonly<Record<NonNullable<DriveBreadth["withheld_reason"]>, string>> = {
  too_few_appearances: "fewer than 3 games",
  too_few_eligible_drives: "fewer than 20 drives",
  too_few_opportunities: "too few",
};

/** "+4 pts" / "−9 pts" / "level": ADR-103's gap in the card's change unit (percentage points). */
export function formatBreadth(value: number): string {
  const rounded = Math.round(value);
  if (rounded === 0) return "level";
  return `${rounded > 0 ? "+" : "−"}${String(Math.abs(rounded))} pts`;
}

export interface BreadthReading {
  readonly metric: DriveBreadthMetric;
  readonly label: string;
  readonly question: string;
  /** One bar per week on the rails' axis; the value is that game's drive share. */
  readonly bars: readonly RoleBar[];
  /** Week → the share the same count would reach at random: the notch on each bar. */
  readonly expected: ReadonlyMap<number, number | null>;
  /** The artifact's own `role_change_v1` on the drive share, or null. */
  readonly change: RoleChange | null;
  readonly direction: ChangeDirection | null;
  readonly valueText: string;
  readonly changeText: string | null;
  /** The rails' window line: "from 62% · week 4 vs 3 earlier games". */
  readonly window: string;
  /**
   * ADR-103's four-game comparison with random, or why there is none; null where the build
   * does not compare the position with random at all (QB, ADR-104).
   */
  readonly vsRandom: string | null;
  /** The four-game gap when it clears the display minimums, else null. */
  readonly gap: number | null;
  /** The whole reading in words, for assistive technology. */
  readonly sentence: string;
}

function weeksLabel(block: DriveBreadth): string {
  if (block.first_week === null || block.last_week === null) return "no games";
  return block.first_week === block.last_week
    ? `wk ${String(block.first_week)}`
    : `wks ${String(block.first_week)}–${String(block.last_week)}`;
}

/**
 * The drive rail from the published block. Nothing is recomputed: every bar, notch, change and
 * gap is the artifact's own number, placed on the record's week axis; weeks the block does not
 * carry keep the rails' absence marks (a played game without play-by-play reads "no value").
 */
export function breadthReading(record: PlayerUsageRecord, block: DriveBreadth): BreadthReading {
  const words = BREADTH_LABELS[block.metric];
  const byWeek = new Map(block.weeks.map((week) => [week.week, week]));
  const change = block.change;
  const bars = record.weeks.map((week) => ({
    week: week.week,
    status: week.status,
    value: week.status === "played" ? (byWeek.get(week.week)?.drive_share ?? null) : null,
    latest: change !== null && week.week === change.latest_week,
  }));
  const compared = block.compares_with_random;
  const expected = new Map(
    compared ? block.weeks.map((week) => [week.week, week.expected_share] as const) : [],
  );
  const direction = directionOf(SHARE, change?.change);
  const window =
    change === null
      ? "no drive count for his latest game"
      : change.earlier === null
        ? changeWindow(change)
        : `from ${formatShare(change.earlier)} · ${changeWindow(change)}`;
  const span = weeksLabel(block);
  const gap = compared && block.displayable && block.breadth_gap_pp !== null ? block.breadth_gap_pp : null;
  const why =
    block.withheld_reason === null
      ? "no reading"
      : block.withheld_reason === "too_few_opportunities"
        ? `too few ${words.noun} (${String(block.opportunities)})`
        : WITHHELD_TEXT[block.withheld_reason];
  const vsRandom = !compared
    ? null
    : gap === null
      ? `vs random: ${why}`
      : `${span}: ${formatBreadth(gap)} vs random`;

  const latestWeek = change === null ? null : byWeek.get(change.latest_week);
  const opening =
    change === null || latestWeek === undefined || latestWeek === null
      ? `${words.label}: no drive count for his latest game.`
      : `${words.label}: in week ${String(change.latest_week)} he had ${words.one} on ` +
        `${String(latestWeek.reached_drives)} of ${String(latestWeek.eligible_drives)} ${words.drives} ` +
        `(${formatShare(change.latest)})` +
        (change.earlier === null || change.change === null
          ? "; no earlier game to compare."
          : `, ${formatChange(SHARE, change.change)} against ${formatShare(change.earlier)} over his ` +
            `${String(change.earlier_games)} earlier game${change.earlier_games === 1 ? "" : "s"}.`);
  const closing = !compared
    ? ""
    : gap === null
      ? ` Over ${span} there are too few ${words.noun} to compare with random (${why}).`
      : ` Over ${span} his ${String(block.opportunities)} ${words.noun} reached ` +
        `${String(block.reached_drives)} of ${String(block.eligible_drives)} drives; placed at random ` +
        `they would reach about ${block.expected_drives.toFixed(1)}, so he is ` +
        (Math.round(gap) === 0
          ? "level with random"
          : `${String(Math.abs(Math.round(gap)))} points ${gap > 0 ? "more spread out" : "more bunched"} than random`) +
        ".";
  return {
    metric: block.metric,
    label: words.label,
    question: words.question,
    bars,
    expected,
    change,
    direction,
    valueText: change === null ? EM_DASH : formatShare(change.latest),
    changeText:
      change?.change !== null && change?.change !== undefined && direction !== null
        ? formatChange(SHARE, change.change)
        : null,
    window,
    vsRandom,
    gap,
    sentence: `${opening}${closing} Descriptive only: not a forecast.`,
  };
}
