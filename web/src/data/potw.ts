/**
 * Pick of the Week: the one waiver target the model likes most at each position.
 *
 * **The question this answers, and the one it refuses to.** A reader in week 6 does not want
 * the best player at each position — the Opportunity Board and the rest-of-season board
 * already order those, and the answer is always the same four names nobody can acquire. They
 * want the best player *they can actually add*. So the whole engine is one sentence:
 *
 *     Behaviour decides who is eligible. The intrinsic model decides who wins.
 *
 * That is not a new rule. It is the Opportunity Board's own rule — "behaviour may decide
 * whether a player is surfaced; it may never change a single intrinsic number" — applied one
 * level up, to a selection instead of to a row. Nothing here computes a player value, blends
 * two units, or produces a score. A candidate either clears a set of published thresholds or
 * does not; the ones that do are ordered by a single published quantity.
 *
 * **Why there is no "opportunity score" here, and must not be.** `AGENTS.md` section 10 and
 * ADR-085 both forbid it in the same words: an add count is a number of transactions and a
 * remaining VORP is a number of points, they share no unit, and any weighting of the two is a
 * coefficient nobody measured wearing the authority of a ranking. A gate is not a blend — a
 * threshold on a count, and separately an ordering on points, never meet in an arithmetic
 * expression. `buildPotwBoard` contains no line where a count and a value are on the same side of
 * an operator, and `tests/potw.test.ts` asserts it behaviourally: hold the adds fixed and the
 * winner follows the VORP; hold the VORP fixed and the adds decide only membership.
 *
 * ## Rostered percentage, and why this uses something else (ADR-088)
 *
 * The obvious availability signal is the share of leagues rostering a player, and this
 * project cannot publish one. Four routes were checked and all four are closed:
 *
 * | route | why not |
 * |---|---|
 * | Sleeper | the documented API publishes no ownership field anywhere — `/players/nfl` has none in its recorded schema, and the trending endpoints return a bare `{player_id, count}` list |
 * | FantasyPros | publishes `player_owned_avg`/`_espn`/`_yahoo`, and is `benchmark_only` (ADR-014): redistribution is forbidden, so it may not reach a public artifact even with a key — and the provisioned key is free-tier, 40 distinct players (ADR-080) |
 * | ESPN | publishes `percentOwned`, and is `disabled` in `config/source-registry.yaml`; enabling it is a source decision needing a probe, a terms review and its own ADR, not a frontend change |
 * | sampling public leagues | a scrape, at a volume `AGENTS.md` section 5's cadence rule forbids |
 *
 * So the owner's named fallback is what this implements — add volume and direction — and the
 * reason it works is worth stating, because it is stronger than a substitute usually is:
 *
 * **An add count is itself availability evidence, in the only direction that matters.** A
 * roster that added a player did not have him. A player rostered in 99% of leagues can
 * therefore *not* post a large add count, because at most 1% of leagues are in a position to
 * add him at all. The example the owner gave is excluded by construction rather than by a
 * threshold someone tuned: a widely-rostered back cannot appear high in a feed of
 * acquisitions. What an add count cannot do is tell you the *level* — "38% rostered" is not
 * recoverable from it — so no surface in this feature prints a percentage, claims one, or
 * implies one. It prints the count, its window, and the population it is being compared with.
 *
 * ## The gates
 *
 * Five, all over published fields, all booleans:
 *
 * 1. **Acquisition evidence exists.** `behavior_available`, and `add_count` is a number. A
 *    row the feed never mentioned has *no evidence*, which is not the same as evidence of
 *    nothing — `docs/UX_SPEC.md` section 7.1A already draws that distinction for a bar and it
 *    binds a gate harder, because this feature makes a positive claim about a player.
 * 2. **The volume clears the position's own bar** (`addFloorFor`). Population-relative rather
 *    than a constant, so it survives a feed whose scale changes between seasons.
 * 3. **The direction is positive.** `net_add_count > 0`. The one subtraction the opportunity
 *    schema sanctions, for the reason it gives: both sides are the same unit, over the same
 *    window, from the same feed, at the same moment. It is the closest thing to the "momentum"
 *    half of the brief that a single snapshot can honestly support, and it is labelled as a
 *    direction over one window rather than as a trend across days.
 * 4. **He is playable.** Not `long_absence` — the model's ordering inside that cohort is
 *    measurably near-random (Spearman 0.311 against 0.797, ADR-076), so presenting one as a
 *    confident number-one pick would be an overclaim the published limitations contradict.
 * 5. **His roster status does not say otherwise.** A severe code (`RES`, `INA`, `PUP`, `NFI`,
 *    `SUS`, `CUT`, `RET`) is annotation the reader can see, and featuring such a player as
 *    this week's pick would be the one place annotation has to bite.
 * 6. **He is worth more than replacement.** `ros_expected_vorp > 0`. This gate is not a
 *    threshold somebody chose: the in-season replacement rule is `rostered_depth` (ADR-071),
 *    which defines replacement as *the best unrostered player*, so a remaining VORP at or
 *    below zero is the model saying in its own units that he is no better than whatever else
 *    is already sitting on the wire. "Add him" and "he is not worth more than the waiver
 *    wire" cannot both be true, and when nothing clears it the view says nobody did.
 *
 * Nothing about a *tier* is a gate. A surfaced player carries no tier by contract, and a
 * surfaced player is exactly who a waiver feature exists to find.
 */

import { quantileAt } from "./cohort";
import type {
  OpportunityRecord,
  PlayerUsageRecord,
  Position,
  RosTierRecord,
  ScoringPreset,
} from "./contracts";
import { projectedRemainingRate, type InSeasonBundle } from "./ros";
import { ROLE_METRICS_BY_POSITION, ROLE_METRIC_SPECS, formatMetric } from "./signals";
import { SCORING_TO_PRESET, leaguePresetId, type AppState } from "./state";

/** Bump when the meaning of a pick changes. Printed on the view beside the picks. */
export const POTW_RULE_VERSION = "potw_selection_v1";

/** The four positions the product publishes a board for, in the order the view lays them out. */
export const POTW_POSITIONS: readonly Position[] = ["QB", "RB", "WR", "TE"];

/**
 * How many sets a reader may cycle through.
 *
 * Five, because the owner asked for five, and because the fifth-best acquirable tight end in
 * a given week is already deep enough that the claim "this is a pick" is doing real work to
 * stay true. A set is a *depth*, not a tier: set 3 is the third-ranked eligible player at each
 * position, which is why two positions in one set have nothing to do with each other.
 */
export const POTW_MAX_SETS = 5;

/**
 * The smallest population that can set its own bar.
 *
 * Below this there is no distribution to take a median of, so the bar falls back to "the feed
 * saw him at all" and the card says which case it is in — the same discipline `cohortStat`
 * uses when it withholds a reading rather than printing `1st of 2`.
 */
export const POTW_FLOOR_MINIMUM = 3;

/**
 * Where the bar sits inside the position's own non-zero add counts.
 *
 * The median, and the reason is the claim it has to support. "He is being added more than
 * half the players at his position that the feed is moving on this week" is a statement a
 * reader can check against the numbers printed beside it. A percentile further out would
 * describe a smaller and smaller group until a quiet week at quarterback produced no pick at
 * all; one further in stops being a bar. It is deliberately **not** a constant: the feed is a
 * top-100 list whose absolute counts depend on how many leagues Sleeper has this season, and
 * a hard-coded 500 would mean something different next August.
 */
export const POTW_FLOOR_QUANTILE = 0.5;

/** Roster codes that say the player cannot take the field. Mirrors `ROSTER_STATUS_SEVERE`. */
const UNPLAYABLE_STATUS = new Set(["RES", "INA", "PUP", "NFI", "SUS", "CUT", "RET"]);

/** Why a position produced no pick at this depth. Each renders as its own sentence. */
export type PotwAbsence =
  /** The behaviour feed was down or stale, so no row has acquisition evidence. */
  | "no_behavior"
  /** The feed is up and nobody at this position cleared the bar. */
  | "none_eligible"
  /** Somebody cleared it, but fewer players than this set is deep. */
  | "set_deeper_than_pool";

/** The bar a position's candidates had to clear, and the population that set it. */
export interface PotwFloor {
  /** The add count a candidate had to reach. */
  readonly value: number;
  /** How many rows at this position carried a non-zero add count. The printed denominator. */
  readonly count: number;
  /**
   * False when the population was under `POTW_FLOOR_MINIMUM` and the bar fell back to "the
   * feed saw him". An ordinary state, and one the card states rather than hides.
   */
  readonly fromPopulation: boolean;
}

/**
 * One pick: a published opportunity row, its published rest-of-season row, and the reasons.
 *
 * Both records are carried whole and unmodified. Every number any surface prints comes off
 * one of them, which is what keeps `AGENTS.md` section 11 true of this feature — the view
 * renders artifact fields, and the only thing computed here is which artifact rows to render.
 */
export interface PotwPick {
  readonly position: Position;
  /** 1-based depth among the eligible candidates at this position. Set 1 holds the 1s. */
  readonly depth: number;
  readonly opportunity: OpportunityRecord;
  /** The rest-of-season row for the same player, or null for a row published only as surfaced. */
  readonly ros: RosTierRecord | null;
  /** How many candidates cleared the bar at this position. The denominator for `depth`. */
  readonly poolSize: number;
  readonly floor: PotwFloor;
  /**
   * The gates that fired, in the order the card states them. Facts about published fields,
   * never adjectives: "undrafted on the preseason board", not "sneaky-good".
   */
  readonly reasons: readonly string[];
  /** Remaining points divided by remaining games, or null. Described, never called an expectation. */
  readonly projectedRate: number | null;
  /**
   * His observed role week by week (ADR-091), or null when the build published none for him.
   * Evidence the card states, never an input to which card it is: selection is still the six
   * gates and the one ordering above, and `potw.test.ts` holds that with and without it.
   */
  readonly usage: PlayerUsageRecord | null;
}

/** One cycle of the picker: at most one pick per position, plus why a position is missing. */
export interface PotwSet {
  /** 1-based. Set 1 is the best eligible player at each position. */
  readonly index: number;
  readonly picks: readonly PotwPick[];
  readonly absent: ReadonlyMap<Position, PotwAbsence>;
}

export interface PotwBoard {
  readonly sets: readonly PotwSet[];
  /** Eligible candidates per position, whatever the set depth. */
  readonly poolSizes: ReadonlyMap<Position, number>;
  readonly floors: ReadonlyMap<Position, PotwFloor>;
  /** False when the build published no usable behaviour snapshot. Every set is then empty. */
  readonly behaviorAvailable: boolean;
  /** The window the counts were requested over, straight off the build metadata. */
  readonly lookbackHours: number | null;
  /** Rows considered, before any gate. The population the bars were taken from. */
  readonly consideredRows: number;
}

/**
 * The add count a candidate at `position` has to reach.
 *
 * The population is the position's own published rows on this board, never the reader's
 * filtered view — the same rule `buildRosCohortContext` follows and for the same reason: a bar
 * that moved when a control did would be a reading about the control.
 */
export function addFloorFor(rows: readonly OpportunityRecord[], position: Position): PotwFloor {
  const counts: number[] = [];
  for (const row of rows) {
    if (row.position !== position) continue;
    const count = row.add_count;
    if (typeof count === "number" && Number.isFinite(count) && count > 0) counts.push(count);
  }
  if (counts.length < POTW_FLOOR_MINIMUM) {
    return { value: 1, count: counts.length, fromPopulation: false };
  }
  const sorted = [...counts].sort((a, b) => a - b);
  return {
    // `Math.ceil` so the bar is a whole transaction: a floor of 512.5 adds cannot be cleared
    // by an integer count of 512, and printing a fractional transaction would be nonsense.
    value: Math.max(1, Math.ceil(quantileAt(sorted, POTW_FLOOR_QUANTILE))),
    count: sorted.length,
    fromPopulation: true,
  };
}

/** Gate 5. A code the product treats as severe disqualifies a pick; anything else does not. */
function playableStatus(status: string | null | undefined): boolean {
  if (status === null || status === undefined) return true;
  return !UNPLAYABLE_STATUS.has(status.trim().toUpperCase());
}

/**
 * Does this row clear every gate?
 *
 * Exported so a test can drive one row at a time, and so the view can explain a near-miss
 * without re-deriving the rule.
 */
export function isPotwCandidate(record: OpportunityRecord, floor: PotwFloor): boolean {
  if (!record.behavior_available) return false;
  const adds = record.add_count;
  const net = record.net_add_count;
  if (typeof adds !== "number" || !Number.isFinite(adds)) return false;
  if (adds < floor.value) return false;
  if (typeof net !== "number" || !Number.isFinite(net) || net <= 0) return false;
  if (record.long_absence) return false;
  if (!playableStatus(record.current_status)) return false;
  // Gate 6. `>` and not `>=`: the replacement baseline *is* the best unrostered player, so a
  // VORP of exactly zero is the model declining to prefer him to the wire he would come off.
  return Number.isFinite(record.ros_expected_vorp) && record.ros_expected_vorp > 0;
}

/**
 * The sentences a card states under "why he pops".
 *
 * Every one is a published field read back in words. There is no sentence here that an
 * adjective could smuggle a claim into, and there is none that describes a rostered share,
 * a matchup or a multi-week trend — the three things this product does not have.
 */
/**
 * His leading role reading as a sentence, when it grew (ADR-091).
 *
 * Only a *growing* role is stated under "why he is the pick", because that heading makes a
 * claim; the evidence row beneath it states every role reading whichever way it moved, so a
 * shrinking share is shown and never hidden. The sentence is two published numbers and the
 * window they were measured over — no adjective, and no threshold on how much growth counts.
 */
function roleReason(usage: PlayerUsageRecord | null, position: Position): string | null {
  if (usage === null) return null;
  const metric = ROLE_METRICS_BY_POSITION[position][0];
  if (metric === undefined) return null;
  const change = usage.role_changes[metric];
  if (change?.earlier == null || change.change === null) return null;
  if (!(change.change > 0)) return null;
  const spec = ROLE_METRIC_SPECS[metric];
  const games = change.earlier_games;
  return (
    `${spec.label} up from ${formatMetric(spec, change.earlier)} to ` +
    `${formatMetric(spec, change.latest)} in week ${String(change.latest_week)}, against his ` +
    `${String(games)} earlier game${games === 1 ? "" : "s"}`
  );
}

function reasonsFor(
  record: OpportunityRecord,
  ros: RosTierRecord | null,
  floor: PotwFloor,
  usage: PlayerUsageRecord | null,
): readonly string[] {
  const reasons: string[] = [];
  const adds = record.add_count ?? 0;
  const window =
    record.behavior_lookback_hours === null || record.behavior_lookback_hours === undefined
      ? "the requested window"
      : `${String(record.behavior_lookback_hours)}h`;

  reasons.push(
    floor.fromPopulation
      ? `${adds.toLocaleString("en-US")} adds in ${window} — over the ${floor.value.toLocaleString("en-US")}-add median of the ${String(floor.count)} ${record.position}s the feed moved on`
      : `${adds.toLocaleString("en-US")} adds in ${window}; too few ${record.position} add counts on this board to set a median`,
  );
  reasons.push(
    `Net ${(record.net_add_count ?? 0).toLocaleString("en-US")} roster moves over the same window`,
  );

  // Preseason context, not a gate. It is the closest published answer to "was he drafted?",
  // and it is stated as what it is — this project's own preseason ordering — rather than as a
  // roster share it is not.
  if (ros !== null) {
    const preseason = ros.preseason_fair_rank ?? null;
    const change = ros.fair_rank_change ?? null;
    if (preseason === null) {
      reasons.push("The preseason board never ranked him");
    } else if (change !== null && change > 0) {
      reasons.push(
        `Up ${String(change)} places on this model's board since preseason rank ${String(preseason)}`,
      );
    }
  }

  const role = roleReason(usage, record.position);
  if (role !== null) reasons.push(role);

  const snap = record.snap_share_last3;
  if (typeof snap === "number" && Number.isFinite(snap) && record.position !== "QB") {
    reasons.push(`${String(Math.round(snap * 100))}% of snaps over the last three weeks`);
  }
  if (record.outside_tier_board) {
    reasons.push("Surfaced from beyond the published tier depth by current evidence");
  }
  return reasons;
}

/**
 * The whole board: every set, every floor, every absence, for one league and scoring preset.
 *
 * Deterministic for a given build. It changes when the build does — which is daily, because
 * the add counts are a 24-hour window and the rest-of-season values are rebuilt each refresh —
 * and that is the intended behaviour rather than a caveat.
 */
export function buildPotwBoard(
  bundle: InSeasonBundle,
  leaguePreset: string,
  scoring: ScoringPreset,
): PotwBoard {
  const rows = bundle.opportunityFor(leaguePreset, scoring);
  const rosRows = bundle.rosFor(leaguePreset, scoring);
  const rosByPlayer = new Map(rosRows.map((row) => [row.player_id, row]));

  const behaviorAvailable = rows.some((row) => row.behavior_available);
  const lookbackHours =
    bundle.metadata.behavior?.lookback_hours ??
    rows.find((row) => typeof row.behavior_lookback_hours === "number")?.behavior_lookback_hours ??
    null;

  const floors = new Map<Position, PotwFloor>();
  const pools = new Map<Position, PotwPick[]>();

  for (const position of POTW_POSITIONS) {
    const floor = addFloorFor(rows, position);
    floors.set(position, floor);

    const eligible = rows.filter(
      (record) => record.position === position && isPotwCandidate(record, floor),
    );
    // One published quantity decides the order, and it is the model's own rest-of-season
    // value. The add count decided membership and has no say from here on — which is the
    // property that makes this a gate rather than a weighting.
    eligible.sort(
      (a, b) =>
        b.ros_expected_vorp - a.ros_expected_vorp ||
        a.ros_fair_rank - b.ros_fair_rank ||
        a.player_id.localeCompare(b.player_id),
    );

    pools.set(
      position,
      eligible.slice(0, POTW_MAX_SETS).map((record, index) => {
        const ros = rosByPlayer.get(record.player_id) ?? null;
        // Read after the order is fixed, for the pick that is already chosen.
        const usage = bundle.usageFor(record.player_id);
        return {
          position,
          depth: index + 1,
          opportunity: record,
          ros,
          poolSize: eligible.length,
          floor,
          reasons: reasonsFor(record, ros, floor, usage),
          usage,
          projectedRate:
            typeof record.ros_expected_points === "number" &&
            typeof record.ros_expected_games === "number"
              ? projectedRemainingRate({
                  ros_expected_points: record.ros_expected_points,
                  ros_expected_games: record.ros_expected_games,
                })
              : null,
        };
      }),
    );
  }

  const deepest = Math.max(0, ...[...pools.values()].map((pool) => pool.length));
  const setCount = Math.min(POTW_MAX_SETS, deepest);

  const sets: PotwSet[] = [];
  for (let index = 1; index <= setCount; index += 1) {
    const picks: PotwPick[] = [];
    const absent = new Map<Position, PotwAbsence>();
    for (const position of POTW_POSITIONS) {
      const pick = pools.get(position)?.[index - 1];
      if (pick !== undefined) {
        picks.push(pick);
      } else if (!behaviorAvailable) {
        absent.set(position, "no_behavior");
      } else {
        absent.set(
          position,
          (pools.get(position)?.length ?? 0) === 0 ? "none_eligible" : "set_deeper_than_pool",
        );
      }
    }
    sets.push({ index, picks, absent });
  }

  return {
    sets,
    poolSizes: new Map(
      POTW_POSITIONS.map((position) => [
        position,
        pools.get(position)?.[0]?.poolSize ?? 0,
      ]),
    ),
    floors,
    behaviorAvailable,
    lookbackHours,
    consideredRows: rows.length,
  };
}

/** The board for the preset the reader has selected. */
export function selectPotwBoard(bundle: InSeasonBundle, state: AppState): PotwBoard {
  return buildPotwBoard(bundle, leaguePresetId(state.teams), SCORING_TO_PRESET[state.scoring]);
}

/**
 * The set to render, clamped into what this build actually produced.
 *
 * A link naming set 4 against a build with two sets opens set 2 rather than an empty panel —
 * the same "normalize, never crash" rule `parseState` applies to every other parameter, made
 * here because the bound depends on the build and a parser may not depend on one.
 */
export function clampSet(requested: number, board: PotwBoard): number {
  if (board.sets.length === 0) return 1;
  return Math.min(Math.max(1, Math.trunc(requested)), board.sets.length);
}

/** The picks a reader's position filter leaves on screen. `all` shows every position. */
export function visiblePicks(set: PotwSet, filter: AppState["position"]): readonly PotwPick[] {
  if (filter === "all") return set.picks;
  const wanted = filter.toUpperCase();
  return set.picks.filter((pick) => pick.position === wanted);
}

/** The one sentence a missing position is stated as. Never a blank card. */
export function absenceSentence(position: Position, absence: PotwAbsence, board: PotwBoard): string {
  const floor = board.floors.get(position);
  const window =
    board.lookbackHours === null ? "the requested window" : `${String(board.lookbackHours)}h`;
  switch (absence) {
    case "no_behavior":
      return `No add or drop counts were published for this build, so no ${position} can be shown as a waiver target. Every rest-of-season value on the other boards is unaffected.`;
    case "none_eligible":
      return floor?.fromPopulation === true
        ? `No ${position} cleared the ${floor.value.toLocaleString("en-US")}-add bar over ${window} with roster moves running positive.`
        : `The feed published too few ${position} add counts on this board to name a waiver target.`;
    case "set_deeper_than_pool":
      return `Only ${String(board.poolSizes.get(position) ?? 0)} ${position}${(board.poolSizes.get(position) ?? 0) === 1 ? "" : "s"} cleared the bar this week, so this set has none.`;
  }
}
