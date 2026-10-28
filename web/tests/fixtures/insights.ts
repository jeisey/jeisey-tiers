/**
 * Insights fixtures (ADR-116): `insights.json` and `ros_build_metadata.insights` for the
 * in-season browser fixture — season 2026, edition `2026w08` (through week 8, target week 9).
 *
 * At least one story of every family and variant, on the browser fixture's own players wherever
 * a card must open, with the states the page has to keep apart:
 *
 * - **upside** — a WR at 31.2% rostered (top 3 under 50% only), an RB at 8.7% (under every
 *   ceiling, Sunday night, off the board), a WR the availability policy refuses (Doubtful in Sleeper, which
 *   the build's pre-screen does not read), and a long-named TE at 4.1% with a Questionable
 *   official report. Two kick off at 18:00 UTC on 8 November, one at 01:20 UTC on the 9th, so a
 *   test clock can pass one kickoff and not the other;
 * - **volume** — a heavily rostered receiver whose targets rose while his points fell, and a back
 *   whose touches genuinely fell (with a bye and a missed game in his strip);
 * - **opening** — one game without an absent tight end (a one-game sample) and a back before
 *   any game without the starter (no history: `share_without` null, `games_without` 0);
 * - **role** — a backfield with red-zone counts and a receiving room whose red-zone counts and
 *   one snap share are null;
 * - **streak** — a breakout, a touchdown-led run with no role growth, and quiet role growth;
 * - **pace** — a per-game standing the total hides, and an overlooked low-rostered quarterback.
 *
 * Wording follows the builder's templates (live W7 output, 2026-10-27), and every number a
 * headline, dek or fact prints is a value of the story's evidence or chart. Points scale per
 * preset (Half PPR × 0.9, Standard × 0.8); role battles are the same in every preset.
 */

import type {
  InsightFact,
  InsightStoryRecord,
  InsightStripWeek,
  InsightsMetadata,
  ScoringPreset,
} from "../../src/data/contracts";
import { FIXTURE_BUILD_ID, FIXTURE_GENERATED_AT } from "./artifacts";

export const INSIGHTS_EDITION = "2026w08";
export const INSIGHTS_PREVIOUS_EDITION = "2026w07";
const SEASON = 2026;
const THROUGH = 8;
const TARGET = 9;
const WINDOW = { label: "W6–W8", first_week: 6, last_week: 8, weeks: 3, baseline_first_week: 1, baseline_last_week: 5 } as const;

/** Kickoffs of the fixture's week-9 games (`teamMatchupRecords`). */
export const KICKOFF_EARLY = "2026-11-08T18:00:00Z";
export const KICKOFF_LATE_AFTERNOON = "2026-11-08T21:25:00Z";
export const KICKOFF_SUNDAY_NIGHT = "2026-11-09T01:20:00Z";

/** Players stories are about, by role in the tests. */
export const INSIGHT_IDS = {
  upsideLead: "upside-00-0000012",
  upsideDeep: "upside-00-0000106",
  upsideDoubtful: "upside-00-0000015",
  upsideLongName: "upside-00-0000095",
  volumeLagging: "volume-00-0000002",
  volumeShrinking: "volume-00-0000011",
  openingObserved: "opening-00-0000004",
  openingProspective: "opening-00-0000014",
  roleBackfield: "role-buf-backfield",
  roleReceiving: "role-was-receiving",
  streakBreakout: "streak-00-0000005",
  streakTouchdowns: "streak-00-0000006",
  streakQuiet: "streak-00-0000003",
  pacePerGame: "pace-00-0000009",
  paceOverlooked: "pace-00-0000018",
} as const;

/** The long name the share card must wrap rather than clip. */
export const LONG_NAME = "Marquez Valdes-Scantling Jr.";
export const LONG_NAME_ID = "gsis:00-0000095";

const FACTOR: Readonly<Record<ScoringPreset, number>> = { PPR: 1, HALF: 0.9, STD: 0.8 };

function one(value: number): number {
  return Math.round(value * 10) / 10;
}
function two(value: number): number {
  return Math.round(value * 100) / 100;
}
function pct(value: number): string {
  return `${String(Math.round(value * 100))}%`;
}
function espn(value: number): string {
  // The builder prints a share under 10% with one decimal, otherwise a whole number.
  return value < 10 ? `${value.toFixed(1)}%` : `${String(Math.round(value))}%`;
}
function signed(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}`;
}

type Base = Omit<
  InsightStoryRecord,
  "schema_version" | "build_id" | "season" | "through_week" | "edition" | "scoring_preset" | "espn_rostered" | "ceiling_ranks" | "injury" | "opponent" | "home_away"
>;

function story(preset: ScoringPreset, base: Base): InsightStoryRecord {
  // The three fields the feed slice carries for itself equal their evidence values, as the
  // builder writes them: the ESPN reading, the upside ranks, a this-week story's report.
  const evidence = base.evidence;
  const espnRostered = typeof evidence.espn_rostered === "number" ? evidence.espn_rostered : null;
  const ceilingRanks = base.family === "weekly_upside" ? (evidence.ceiling_ranks as InsightStoryRecord["ceiling_ranks"]) : null;
  const thisWeek = base.horizon === "this_week";
  const injury = thisWeek ? ((evidence.injury ?? null) as InsightStoryRecord["injury"]) : null;
  const opponent = thisWeek && typeof evidence.opponent === "string" ? evidence.opponent : null;
  const homeAway = thisWeek && (evidence.home_away === "home" || evidence.home_away === "away") ? evidence.home_away : null;
  // Field order is the contract's (`INSIGHT_STORY_FIELDS`).
  return {
    schema_version: "1.0",
    build_id: FIXTURE_BUILD_ID,
    season: SEASON,
    through_week: THROUGH,
    target_week: base.target_week,
    edition: INSIGHTS_EDITION,
    scoring_preset: preset,
    scoring_dependent: base.scoring_dependent,
    story_id: base.story_id,
    family: base.family,
    variant: base.variant,
    horizon: base.horizon,
    nature: base.nature,
    lead_rank: base.lead_rank,
    family_rank: base.family_rank,
    player_id: base.player_id,
    display_name: base.display_name,
    position: base.position,
    team: base.team,
    headline: base.headline,
    dek: base.dek,
    facts: base.facts,
    counterpoint: base.counterpoint,
    caveat: base.caveat,
    window: base.window,
    kickoff_utc: base.kickoff_utc,
    espn_rostered: espnRostered,
    ceiling_ranks: ceilingRanks,
    injury,
    opponent,
    home_away: homeAway,
    chart: base.chart,
    evidence: base.evidence,
    qualification: base.qualification,
    also_qualifies: base.also_qualifies,
    sources: base.sources,
    source_times: base.source_times,
  };
}

function fact(label: string, value: string, basis: InsightFact["basis"]): InsightFact {
  return { label, value, basis };
}

// --------------------------------------------------------------------------- upside

interface UpsideSpec {
  readonly id: string;
  readonly name: string;
  readonly position: "QB" | "RB" | "WR" | "TE";
  readonly team: string;
  readonly opponent: string;
  readonly homeAway: "home" | "away";
  readonly kickoff: string;
  readonly q: readonly [number, number, number];
  readonly typical: readonly [number, number, number];
  readonly rostered: number;
  readonly ranks: { readonly "50": number | null; readonly "25": number | null; readonly "10": number | null };
  readonly eligible: number;
  readonly role: readonly [string, number];
  readonly injury: InsightStoryRecord["evidence"]["injury"];
  readonly lead: number | null;
  readonly familyRank: number;
}

const UPSIDE: readonly UpsideSpec[] = [
  {
    id: "00-0000012",
    name: "Puka Nightingale",
    position: "WR",
    team: "LAR",
    opponent: "BAL",
    homeAway: "away",
    kickoff: KICKOFF_EARLY,
    q: [5.2, 11.9, 22.4],
    typical: [4.6, 10.8, 20.1],
    rostered: 31.2,
    ranks: { "50": 1, "25": null, "10": null },
    eligible: 14,
    role: ["Target share", 0.24],
    injury: null,
    lead: 1,
    familyRank: 1,
  },
  {
    // Not on the board (no status record: the policy reads him as unknown, which still stands).
    // The board's own Sunday-night back is on a reserve list.
    id: "00-0000106",
    name: "Darius Holt",
    position: "RB",
    team: "LAC",
    opponent: "KC",
    homeAway: "away",
    kickoff: KICKOFF_SUNDAY_NIGHT,
    q: [4.0, 10.2, 21.0],
    typical: [3.1, 8.5, 18.2],
    rostered: 8.7,
    ranks: { "50": 1, "25": 1, "10": 1 },
    eligible: 11,
    role: ["Carry share", 0.46],
    injury: null,
    lead: 7,
    familyRank: 2,
  },
  {
    id: "00-0000015",
    name: "Zay Meadows",
    position: "WR",
    team: "BAL",
    opponent: "LAR",
    homeAway: "home",
    kickoff: KICKOFF_EARLY,
    q: [3.8, 9.9, 19.6],
    typical: [3.5, 9.1, 18.4],
    rostered: 22.0,
    ranks: { "50": 2, "25": 1, "10": null },
    eligible: 14,
    role: ["Target share", 0.21],
    // The official report has not listed him; Sleeper has him Doubtful (the policy reads both).
    injury: null,
    lead: null,
    familyRank: 3,
  },
  {
    id: "00-0000095",
    name: LONG_NAME,
    position: "TE",
    team: "CIN",
    opponent: "BUF",
    homeAway: "away",
    kickoff: KICKOFF_LATE_AFTERNOON,
    q: [2.9, 7.7, 16.8],
    typical: [2.5, 6.9, 15.2],
    rostered: 4.1,
    ranks: { "50": 1, "25": 1, "10": 1 },
    eligible: 9,
    role: ["Target share", 0.17],
    injury: {
      week: TARGET,
      designation: "Questionable",
      practice_status: "Limited Participation in Practice",
      primary_injury: "Hamstring",
    },
    lead: null,
    familyRank: 4,
  },
];

function upside(preset: ScoringPreset, spec: UpsideSpec): InsightStoryRecord {
  const f = FACTOR[preset];
  const [q10, q50, q90] = spec.q.map((value) => two(value * f)) as [number, number, number];
  const [t10, t50, t90] = spec.typical.map((value) => two(value * f)) as [number, number, number];
  const delta = two(q90 - t90);
  const ceiling = spec.ranks["10"] !== null ? 10 : spec.ranks["25"] !== null ? 25 : 50;
  const rank = spec.ranks[String(ceiling) as "50" | "25" | "10"] ?? 1;
  return story(preset, {
    target_week: TARGET,
    scoring_dependent: true,
    story_id: `upside-${spec.id}`,
    family: "weekly_upside",
    variant: "ceiling",
    horizon: "this_week",
    nature: "thesis",
    lead_rank: spec.lead,
    family_rank: spec.familyRank,
    player_id: `gsis:${spec.id}`,
    display_name: spec.name,
    position: spec.position,
    team: spec.team,
    headline: `${spec.name}: a ${one(q90).toFixed(1)}-point ceiling at ${espn(spec.rostered)} rostered`,
    dek: `No. ${String(rank)} by week-9 ceiling of ${String(spec.eligible)} ${spec.position}s with a confirmed role and under ${String(ceiling)}% rostered on ESPN. The matchup lifts his ceiling ${one(delta).toFixed(1)} points against his typical week.`,
    facts: [
      fact("Ceiling / median / floor (P90 / P50 / P10)", `${one(q90).toFixed(1)} / ${one(q50).toFixed(1)} / ${one(q10).toFixed(1)}`, "model"),
      fact(`${spec.role[0]}, last 3 games`, pct(spec.role[1]), "observed"),
      fact("Rostered on ESPN", espn(spec.rostered), "market"),
      fact("Matchup vs typical week (P90)", signed(delta), "model"),
    ],
    counterpoint: `His median week is ${one(q50).toFixed(1)} points: this is a ceiling bet, not a safe start.`,
    caveat:
      "P90: one week in ten at or above it, per the weekly model — not a 90% chance. ESPN share describes ESPN leagues, not yours.",
    window: WINDOW,
    kickoff_utc: spec.kickoff,
    chart: { type: "interval", q10, q50, q90, typical_q10: t10, typical_q50: t50, typical_q90: t90 },
    evidence: {
      name: spec.name,
      position: spec.position,
      team: spec.team,
      opponent: spec.opponent,
      home_away: spec.homeAway,
      kickoff_utc: spec.kickoff,
      target_week: TARGET,
      q10,
      q50,
      q90,
      typical_q10: t10,
      typical_q50: t50,
      typical_q90: t90,
      matchup_delta_q90: delta,
      terms_q90: { lines: two(delta * 0.4), home: spec.homeAway === "home" ? 0.15 : -0.15, rest: 0, roof: 0, opponent: two(delta * 0.6) },
      espn_rostered: spec.rostered,
      espn_state: "observed",
      ceiling,
      ceiling_rank: rank,
      eligible: spec.eligible,
      ceiling_ranks: spec.ranks,
      role_metric: spec.role[0].toLowerCase().replace(" ", "_"),
      role_level: spec.role[1],
      role_games: 3,
      injury: spec.injury,
      model_version: "weekly-startsit-v1",
    },
    qualification: [
      { rule: "game_upcoming", label: "Target-week kickoff after the build", value: spec.kickoff, threshold: "after build", passed: true },
      { rule: "espn_below", label: "ESPN rostered %, below", value: spec.rostered, threshold: ceiling, passed: true },
      { rule: "role_confirmed", label: "Games with a confirmed role, at least", value: 3, threshold: 2, passed: true },
      { rule: "ceiling_rank", label: `Week-9 ceiling rank among ${spec.position}s under ${String(ceiling)}%, at most`, value: rank, threshold: 3, passed: true },
    ],
    also_qualifies: [],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_injuries", "weekly_startsit_v1", "espn_fantasy_ownership"],
    source_times: {
      espn_observed_at_utc: "2026-08-21T11:30:07Z",
      lines_retrieved_at_utc: "2026-08-21T13:05:00Z",
      injury_report_final: false,
    },
  });
}

// ------------------------------------------------------------------------- week strips

type Week = readonly [week: number, status: "P" | "B" | "D", points?: number, td?: number, opportunity?: number | null, share?: number | null, rank?: number | null];

function strip(preset: ScoringPreset, weeks: readonly Week[]): InsightStripWeek[] {
  const f = FACTOR[preset];
  return weeks.map(([week, status, points, td, opportunity, share, rank]) => ({
    week,
    status,
    in_window: week >= WINDOW.first_week,
    points: status === "P" && points !== undefined ? one(points * f) : null,
    td_points: status === "P" && td !== undefined ? td : null,
    opportunity: status === "P" ? (opportunity ?? null) : null,
    share: status === "P" ? (share ?? null) : null,
    rank: status === "P" ? (rank ?? null) : null,
  }));
}

function sum(weeks: readonly InsightStripWeek[], key: "points" | "opportunity" | "td_points", window: boolean): { total: number; games: number } {
  const played = weeks.filter((week) => week.status === "P" && week.in_window === window);
  return { total: played.reduce((total, week) => total + (week[key] ?? 0), 0), games: played.length };
}

function volumeLagging(preset: ScoringPreset): InsightStoryRecord {
  const weeks = strip(preset, [
    [1, "P", 18.4, 6, 8, 0.24, 14],
    [2, "P", 9.1, 0, 6, 0.19, 41],
    [3, "P", 21.7, 12, 9, 0.27, 8],
    [4, "B"],
    [5, "P", 12.2, 0, 7, 0.22, 30],
    [6, "P", 8.1, 0, 11, 0.31, 47],
    [7, "P", 6.4, 0, 10, 0.3, 58],
    [8, "P", 9.9, 0, 12, 0.33, 39],
  ]);
  const opp = sum(weeks, "opportunity", true);
  const oppBase = sum(weeks, "opportunity", false);
  const pts = sum(weeks, "points", true);
  const ptsBase = sum(weeks, "points", false);
  const perGame = one(opp.total / opp.games);
  const basePerGame = one(oppBase.total / oppBase.games);
  const ppg = one(pts.total / pts.games);
  const basePpg = one(ptsBase.total / ptsBase.games);
  return story(preset, {
    target_week: null,
    scoring_dependent: true,
    story_id: INSIGHT_IDS.volumeLagging,
    family: "volume_vs_results",
    variant: "lagging",
    horizon: "role_watch",
    nature: "thesis",
    lead_rank: 3,
    family_rank: 1,
    player_id: "gsis:00-0000002",
    display_name: "Amon-Ra Bright",
    position: "WR",
    team: "DET",
    headline: `Amon-Ra Bright: ${perGame.toFixed(1)} targets a game (WR6), ${ppg.toFixed(1)} points a game (WR38)`,
    dek: `Over W6–W8 his workload ranks WR6 of 152 WRs, but his scoring ranks WR38. The role has held; the results have trailed it, which is a reason for patience rather than a cut.`,
    facts: [
      fact("Targets a game, before → W6–W8", `${basePerGame.toFixed(1)} → ${perGame.toFixed(1)}`, "observed"),
      fact("Points a game, before → W6–W8", `${basePpg.toFixed(1)} → ${ppg.toFixed(1)}`, "observed"),
      fact("Target share, W6–W8", "31%", "observed"),
      fact("Rostered on ESPN", "99%", "market"),
    ],
    counterpoint: "His 5.1 yards per target trail the WR median of 7.2 in these weeks, so the gap is not only touchdowns.",
    caveat: "Three weeks of usage and scoring, described rather than forecast: a workload gap is not a promise of points.",
    window: WINDOW,
    kickoff_utc: null,
    chart: { type: "week_strip", weeks, opportunity_label: "Targets", share_label: "Target share", band: null },
    evidence: {
      name: "Amon-Ra Bright",
      window_label: "W6–W8",
      opportunity_label: "targets",
      window_games: opp.games,
      baseline_games: oppBase.games,
      window_opportunities: opp.total,
      window_opportunities_per_game: perGame,
      baseline_opportunities_per_game: basePerGame,
      workload_rank: 6,
      production_rank: 38,
      cohort_size: 152,
      gap_places: 32,
      required_gap_places: 12,
      window_points_per_game: ppg,
      baseline_points_per_game: basePpg,
      window_share: 0.313,
      yards_per_target: 5.1,
      median_yards_per_target: 7.2,
      espn_rostered: 99.1,
    },
    qualification: [
      { rule: "window_games", label: "Games in W6–W8", value: opp.games, threshold: 2, passed: true },
      { rule: "workload_rank", label: "Targets-a-game rank among 152 WRs, at most", value: 6, threshold: 24, passed: true },
      { rule: "gap_places", label: "Production rank minus workload rank, in places", value: 32, threshold: 12, passed: true },
      { rule: "workload_held", label: "Window targets a game as % of baseline, at least", value: 152, threshold: 90, passed: true },
    ],
    also_qualifies: [INSIGHT_IDS.streakBreakout.replace("00-0000005", "00-0000002")],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_schedule", "espn_fantasy_ownership"],
    source_times: { espn_observed_at_utc: "2026-08-21T11:30:07Z" },
  });
}

function volumeShrinking(preset: ScoringPreset): InsightStoryRecord {
  const weeks = strip(preset, [
    [1, "P", 19.6, 6, 21, 0.58, 9],
    [2, "P", 14.2, 0, 18, 0.55, 17],
    [3, "P", 22.8, 12, 20, 0.61, 5],
    [4, "B"],
    [5, "D"],
    [6, "P", 9.1, 0, 12, 0.41, 33],
    [7, "P", 6.3, 0, 10, 0.37, 44],
    [8, "P", 7.7, 6, 11, 0.39, 38],
  ]);
  const opp = sum(weeks, "opportunity", true);
  const oppBase = sum(weeks, "opportunity", false);
  const pts = sum(weeks, "points", true);
  const ptsBase = sum(weeks, "points", false);
  const perGame = one(opp.total / opp.games);
  const basePerGame = one(oppBase.total / oppBase.games);
  return story(preset, {
    target_week: null,
    scoring_dependent: true,
    story_id: INSIGHT_IDS.volumeShrinking,
    family: "volume_vs_results",
    variant: "shrinking",
    horizon: "role_watch",
    nature: "thesis",
    lead_rank: 9,
    family_rank: 1,
    player_id: "gsis:00-0000011",
    display_name: "Jahmyr Cook",
    position: "RB",
    team: "DET",
    headline: "Jahmyr Cook's carry share fell from 58% to 39% over W6–W8",
    dek: `A shrinking share is a smaller role, not a cold streak: carries and targets a game are down from ${basePerGame.toFixed(1)} to ${perGame.toFixed(1)}.`,
    facts: [
      fact("Carry share, before → W6–W8", "58% → 39%", "observed"),
      fact("Carries + targets a game, before → W6–W8", `${basePerGame.toFixed(1)} → ${perGame.toFixed(1)}`, "observed"),
      fact("Points a game, before → W6–W8", `${one(ptsBase.total / ptsBase.games).toFixed(1)} → ${one(pts.total / pts.games).toFixed(1)}`, "observed"),
      fact("Snap share, before → W6–W8", "71% → 52%", "observed"),
    ],
    counterpoint: "He missed week 5, and the window's first game was his return: a short read on a settled role.",
    caveat: "Shares pool his games against his team's; three weeks against his earlier games is a small sample.",
    window: WINDOW,
    kickoff_utc: null,
    chart: { type: "week_strip", weeks, opportunity_label: "Carries + targets", share_label: "Carry share", band: null },
    evidence: {
      name: "Jahmyr Cook",
      window_label: "W6–W8",
      window_games: opp.games,
      baseline_games: oppBase.games,
      window_opportunities_per_game: perGame,
      baseline_opportunities_per_game: basePerGame,
      share_metric: "carry_share",
      window_share: 0.39,
      baseline_share: 0.58,
      share_drop: 0.19,
      role_step: 0.15,
      snap_share: 0.52,
      snap_share_baseline: 0.71,
    },
    qualification: [
      { rule: "window_games", label: "Games in W6–W8", value: opp.games, threshold: 2, passed: true },
      { rule: "baseline_games", label: "Games before the window", value: oppBase.games, threshold: 2, passed: true },
      { rule: "share_drop", label: "Carry share fall, at least", value: 0.19, threshold: 0.15, passed: true },
    ],
    also_qualifies: [],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_schedule"],
    source_times: {},
  });
}

function streak(
  preset: ScoringPreset,
  spec: {
    readonly id: string;
    readonly playerId: string;
    readonly name: string;
    readonly position: "RB" | "WR" | "TE";
    readonly team: string;
    readonly variant: "breakout" | "production_without_role" | "quiet_role_growth";
    readonly lead: number | null;
    readonly band: number;
    readonly shareLabel: string;
    readonly weeks: readonly Week[];
    readonly headline: (ppg: number) => string;
    readonly dek: string;
    readonly facts: (ppg: number, tdShare: number) => InsightFact[];
    readonly counterpoint: string | null;
    readonly horizon: "role_watch" | "season_view";
  },
): InsightStoryRecord {
  const weeks = strip(preset, spec.weeks);
  const pts = sum(weeks, "points", true);
  const td = sum(weeks, "td_points", true);
  const ppg = one(pts.total / pts.games);
  const tdShare = pts.total > 0 ? Math.round((td.total / pts.total) * 100) : 0;
  return story(preset, {
    target_week: null,
    scoring_dependent: true,
    story_id: spec.id,
    family: "streak_watch",
    variant: spec.variant,
    horizon: spec.horizon,
    nature: spec.variant === "breakout" ? "fact" : "thesis",
    lead_rank: spec.lead,
    family_rank: 1,
    player_id: spec.playerId,
    display_name: spec.name,
    position: spec.position,
    team: spec.team,
    headline: spec.headline(ppg),
    dek: spec.dek,
    facts: spec.facts(ppg, tdShare),
    counterpoint: spec.counterpoint,
    caveat: "A descriptive reading from fixed thresholds over three weeks; not a prediction.",
    window: WINDOW,
    kickoff_utc: null,
    chart: { type: "week_strip", weeks, opportunity_label: spec.position === "RB" ? "Carries + targets" : "Targets", share_label: spec.shareLabel, band: spec.band },
    evidence: {
      name: spec.name,
      window_label: "W6–W8",
      band: spec.band,
      window_games: pts.games,
      window_points: one(pts.total),
      window_points_per_game: ppg,
      window_td_points: td.total,
      td_share: tdShare,
      td_led_percent: 50,
    },
    qualification: [
      { rule: "window_games", label: "Games in W6–W8", value: pts.games, threshold: 2, passed: true },
      { rule: "category", label: "breakout_v1 over W6–W8", value: spec.variant === "breakout" ? "takeover" : "eyebrow", threshold: "takeover, sneaking or eyebrow", passed: true },
    ],
    also_qualifies: [],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_schedule"],
    source_times: {},
  });
}

// ------------------------------------------------------------------------- openings

function openingObserved(preset: ScoringPreset): InsightStoryRecord {
  return story(preset, {
    target_week: TARGET,
    scoring_dependent: true,
    story_id: INSIGHT_IDS.openingObserved,
    family: "opportunity_opening",
    variant: "observed",
    horizon: "this_week",
    nature: "thesis",
    lead_rank: 2,
    family_rank: 1,
    player_id: "gsis:00-0000001",
    display_name: "Bijan Robinson",
    position: "RB",
    team: "ATL",
    headline: "Without Kyle Pitts Sr., Bijan Robinson's share of ATL targets rose to 19%",
    dek: "Kyle Pitts Sr. missed W8 and is out for week 9. In ATL's 1 game without him, Bijan Robinson took 19% of the targets, against 12% alongside him.",
    facts: [
      fact("Kyle Pitts Sr.'s share of ATL targets", "21% over 7 games", "observed"),
      fact("Bijan Robinson without him", "19% (1 game)", "observed"),
      fact("Bijan Robinson with him", "12% (7 games)", "observed"),
      fact("Rostered on ESPN", "100%", "market"),
    ],
    counterpoint: "1 game without him: opponents and game script move shares as much as an absence does.",
    caveat: "This shows what happened in games he missed, or who is next by share; vacated work is not assigned to anyone.",
    window: WINDOW,
    kickoff_utc: KICKOFF_EARLY,
    chart: {
      type: "with_without",
      metric: "target_share",
      absent: { player_id: "gsis:00-0000004", name: "Kyle Pitts Sr.", position: "TE", share: 0.21, games: 7, per_game: 6.4, reason: "missed W8; out for week 9" },
      rows: [
        { player_id: "gsis:00-0000001", name: "Bijan Robinson", position: "RB", share_with: 0.12, games_with: 7, share_without: 0.19, games_without: 1, latest_share: 0.19 },
        { player_id: "gsis:00-0000101", name: "Drake Lowell", position: "WR", share_with: 0.24, games_with: 7, share_without: 0.27, games_without: 1, latest_share: 0.27 },
        { player_id: "gsis:00-0000102", name: "Ray-Ray Pickens", position: "WR", share_with: 0.16, games_with: 6, share_without: 0.13, games_without: 1, latest_share: 0.13 },
      ],
    },
    evidence: {
      name: "Bijan Robinson",
      metric: "target_share",
      absent_name: "Kyle Pitts Sr.",
      absent_share: 0.21,
      absent_games: 7,
      absent_designation: "Out",
      share_with: 0.12,
      games_with: 7,
      share_without: 0.19,
      games_without: 1,
      opponent: "DET",
      home_away: "away",
      injury: null,
      espn_rostered: 99.8,
    },
    qualification: [
      { rule: "absent_share", label: "Absent player's share of ATL targets, at least", value: 0.21, threshold: 0.18, passed: true },
      { rule: "absent_games", label: "Absent player's games, at least", value: 7, threshold: 2, passed: true },
      { rule: "share_rise", label: "Target share rise without him, at least", value: 0.07, threshold: 0.06, passed: true },
    ],
    also_qualifies: ["upside-00-0000001"],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_injuries", "espn_fantasy_ownership"],
    source_times: { espn_observed_at_utc: "2026-08-21T11:30:07Z", injury_report_final: false },
  });
}

function openingProspective(preset: ScoringPreset): InsightStoryRecord {
  return story(preset, {
    target_week: null,
    scoring_dependent: true,
    story_id: INSIGHT_IDS.openingProspective,
    family: "opportunity_opening",
    variant: "prospective",
    horizon: "role_watch",
    nature: "thesis",
    lead_rank: 8,
    family_rank: 1,
    player_id: "gsis:00-0000096",
    display_name: "Keaton Mills",
    position: "RB",
    team: "BAL",
    headline: "Derrick Hampton (61% of BAL carries) is out for the season",
    dek: "BAL has not played a game without him. Keaton Mills took 18% of the carries beside him and 22% in week 8; who absorbs the rest is not known.",
    facts: [
      fact("Derrick Hampton's share of BAL carries", "61% over 7 games", "observed"),
      fact("Keaton Mills with him", "18% (7 games)", "observed"),
      fact("Keaton Mills, week 8", "22%", "observed"),
    ],
    counterpoint: null,
    caveat: "This shows what happened in games he missed, or who is next by share; vacated work is not assigned to anyone.",
    window: WINDOW,
    kickoff_utc: null,
    chart: {
      type: "with_without",
      metric: "carry_share",
      absent: { player_id: "gsis:00-0000014", name: "Derrick Hampton", position: "RB", share: 0.61, games: 7, per_game: 15.4, reason: "on a reserve list for the season" },
      rows: [
        { player_id: "gsis:00-0000096", name: "Keaton Mills", position: "RB", share_with: 0.18, games_with: 7, share_without: null, games_without: 0, latest_share: 0.22 },
        { player_id: "gsis:00-0000103", name: "Rasheen Doe", position: "RB", share_with: 0.09, games_with: 6, share_without: null, games_without: 0, latest_share: 0.08 },
      ],
    },
    evidence: { name: "Keaton Mills", metric: "carry_share", absent_name: "Derrick Hampton", absent_share: 0.61, absent_games: 7, share_with: 0.18, games_without: 0, latest_share: 0.22 },
    qualification: [
      { rule: "absent_share", label: "Absent player's share of BAL carries, at least", value: 0.61, threshold: 0.45, passed: true },
      { rule: "absent_games", label: "Absent player's games, at least", value: 7, threshold: 2, passed: true },
    ],
    also_qualifies: [],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_injuries"],
    source_times: {},
  });
}

// ---------------------------------------------------------------------------- rooms

function roleBackfield(preset: ScoringPreset): InsightStoryRecord {
  return story(preset, {
    target_week: null,
    scoring_dependent: false,
    story_id: INSIGHT_IDS.roleBackfield,
    family: "role_battle",
    variant: "backfield",
    horizon: "role_watch",
    nature: "fact",
    lead_rank: 5,
    family_rank: 1,
    player_id: "gsis:00-0000013",
    display_name: "James Cook III",
    position: "RB",
    team: "BUF",
    headline: "BUF backfield: James Cook III's share of carries fell from 55% to 48%",
    dek: "Over W6–W8, James Cook III took 34 of BUF's 71 carries; Ty Johnson took 20. A change in who gets the ball shows in the share before it shows in a season total.",
    facts: [
      fact("James Cook III, W6–W8", "34 of 71 carries", "observed"),
      fact("James Cook III's share, before → W6–W8", "55% → 48%", "observed"),
      fact("Ty Johnson, W6–W8", "20 of 71 carries", "observed"),
      fact("Red-zone carries, W6–W8", "9 of 21", "observed"),
    ],
    counterpoint: "Josh Allen's 14 carries are part of the denominator: the backs share what he leaves.",
    caveat: "Shares are of BUF's carries in its games. Snap shares overlap — players share the field — so they do not add to 100%.",
    window: WINDOW,
    kickoff_utc: null,
    chart: {
      type: "room",
      room: "backfield",
      metric: "carries",
      team_count: 71,
      team_games: 3,
      team_red_zone: 21,
      team_inside_five: 9,
      rows: [
        { player_id: "gsis:00-0000013", name: "James Cook III", position: "RB", window_games: 3, baseline_games: 5, snap_share: 0.58, snap_share_baseline: 0.66, count: 34, share: 0.479, share_baseline: 0.55, red_zone: 9, inside_five: 3 },
        { player_id: "gsis:00-0000104", name: "Ty Johnson", position: "RB", window_games: 3, baseline_games: 5, snap_share: 0.31, snap_share_baseline: 0.22, count: 20, share: 0.282, share_baseline: 0.18, red_zone: 5, inside_five: 2 },
        { player_id: "gsis:00-0000008", name: "Josh Allen", position: "QB", window_games: 3, baseline_games: 5, snap_share: 1, snap_share_baseline: 1, count: 14, share: 0.197, share_baseline: 0.21, red_zone: 4, inside_five: 3 },
      ],
    },
    evidence: { team: "BUF", room: "backfield", window_label: "W6–W8", team_carries: 71, team_games: 3, team_red_zone: 21, team_inside_five: 9, share: 0.479, share_baseline: 0.55, role_step: 0.15 },
    qualification: [
      { rule: "room_rows", label: "Players with a share of BUF carries", value: 3, threshold: 2, passed: true },
      { rule: "share_change", label: "Largest share change in the room, at least", value: 0.102, threshold: 0.06, passed: true },
    ],
    also_qualifies: [],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_pbp", "nflverse_schedule"],
    source_times: {},
  });
}

function roleReceiving(preset: ScoringPreset): InsightStoryRecord {
  return story(preset, {
    target_week: null,
    scoring_dependent: false,
    story_id: INSIGHT_IDS.roleReceiving,
    family: "role_battle",
    variant: "receiving",
    horizon: "role_watch",
    nature: "fact",
    lead_rank: 11,
    family_rank: 2,
    player_id: "gsis:00-0000010",
    display_name: "Jaylin Lane",
    position: "WR",
    team: "WAS",
    headline: "WAS receiving room: Jaylin Lane's share of targets rose from 14% to 25%",
    dek: "Over W6–W8, Jaylin Lane took 24 of WAS's 96 targets; Zach Ertz took 19. A change in who gets the ball shows in the share before it shows in a season total.",
    facts: [
      fact("Jaylin Lane, W6–W8", "24 of 96 targets", "observed"),
      fact("Jaylin Lane's share, before → W6–W8", "14% → 25%", "observed"),
      fact("Zach Ertz, W6–W8", "19 of 96 targets", "observed"),
      fact("Jaylin Lane's snap share, W6–W8", "74%", "observed"),
    ],
    counterpoint: "Terry Mack played 2 of WAS's 3 games in W6–W8, so part of the shift is his absence.",
    caveat: "Shares are of WAS's targets in its games. Snap shares overlap — players share the field — so they do not add to 100%.",
    window: WINDOW,
    kickoff_utc: null,
    chart: {
      type: "room",
      room: "receiving",
      metric: "targets",
      team_count: 96,
      team_games: 3,
      // Play-by-play was not available for these weeks: red-zone counts are unknown, not zero.
      team_red_zone: null,
      team_inside_five: null,
      rows: [
        { player_id: "gsis:00-0000010", name: "Jaylin Lane", position: "WR", window_games: 3, baseline_games: 5, snap_share: 0.74, snap_share_baseline: 0.52, count: 24, share: 0.25, share_baseline: 0.14, red_zone: null, inside_five: null },
        { player_id: "gsis:00-0000007", name: "Zach Ertz", position: "TE", window_games: 3, baseline_games: 5, snap_share: 0.81, snap_share_baseline: 0.85, count: 19, share: 0.198, share_baseline: 0.22, red_zone: null, inside_five: null },
        { player_id: "gsis:00-0000105", name: "Terry Mack", position: "WR", window_games: 2, baseline_games: 5, snap_share: null, snap_share_baseline: 0.61, count: 11, share: 0.115, share_baseline: 0.17, red_zone: null, inside_five: null },
      ],
    },
    evidence: { team: "WAS", room: "receiving", window_label: "W6–W8", team_targets: 96, team_games: 3, team_red_zone: null, share: 0.25, share_baseline: 0.14, pbp_state: "unavailable" },
    qualification: [
      { rule: "room_rows", label: "Players with a share of WAS targets", value: 3, threshold: 2, passed: true },
      { rule: "share_change", label: "Largest share change in the room, at least", value: 0.11, threshold: 0.06, passed: true },
    ],
    also_qualifies: [],
    sources: ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_schedule"],
    source_times: {},
  });
}

// ----------------------------------------------------------------------------- pace

function pace(
  preset: ScoringPreset,
  spec: {
    readonly id: string;
    readonly playerId: string;
    readonly name: string;
    readonly team: string;
    readonly variant: "per_game_hidden" | "overlooked";
    readonly lead: number | null;
    readonly games: number;
    readonly teamGames: number;
    readonly points: number;
    readonly ppgRank: number;
    readonly totalRank: number;
    readonly rostered: number | null;
  },
): InsightStoryRecord {
  // A quarterback's points do not depend on reception scoring: the same in every preset.
  const ppg = two(spec.points / spec.games);
  const pace17 = one(ppg * 17);
  const hidden = spec.variant === "per_game_hidden";
  return story(preset, {
    target_week: null,
    scoring_dependent: true,
    story_id: spec.id,
    family: "pace_perspective",
    variant: spec.variant,
    horizon: "season_view",
    nature: "fact",
    lead_rank: spec.lead,
    family_rank: 1,
    player_id: spec.playerId,
    display_name: spec.name,
    position: "QB",
    team: spec.team,
    headline: hidden
      ? `${spec.name}: QB${String(spec.ppgRank)} in points a game, QB${String(spec.totalRank)} in total`
      : `${spec.name} is QB${String(spec.ppgRank)} in points a game and ${espn(spec.rostered ?? 0)} rostered`,
    dek: hidden
      ? `He has played ${String(spec.games)} of ${spec.team}'s ${String(spec.teamGames)} games. Among 34 QBs with 3+ games he averages ${one(ppg).toFixed(1)}; the total rank reflects the games he missed.`
      : `${one(ppg).toFixed(1)} points a game over ${String(spec.games)} games ranks QB${String(spec.ppgRank)} of 34 QBs with 3+ games, yet most ESPN leagues leave him unrostered.`,
    facts: [
      fact("Points a game", `${one(ppg).toFixed(1)} (QB${String(spec.ppgRank)})`, "observed"),
      fact("Games played", `${String(spec.games)} of ${String(spec.teamGames)}`, "observed"),
      fact("17-game pace (PPG × 17)", pace17.toFixed(1), "observed"),
      hidden
        ? fact("Season points", `${spec.points.toFixed(1)} (QB${String(spec.totalRank)})`, "observed")
        : fact("Rostered on ESPN", espn(spec.rostered ?? 0), "market"),
    ],
    counterpoint: hidden ? `He missed ${String(spec.teamGames - spec.games)} of ${spec.team}'s games: availability is part of a season's value.` : "A quarterback's weekly start is one slot: a per-game rank is a bye-week or matchup option first.",
    caveat: "Pace is arithmetic (points a game × 17), not a projection; it assumes games he may not play.",
    window: null,
    kickoff_utc: null,
    chart: {
      type: "stat_line",
      games: spec.games,
      team_games: spec.teamGames,
      points: spec.points,
      points_per_game: ppg,
      pace_17: pace17,
      ppg_rank: spec.ppgRank,
      total_rank: spec.totalRank,
      cohort_size: 34,
      cohort_min_games: 3,
    },
    evidence: {
      name: spec.name,
      games: spec.games,
      team_games: spec.teamGames,
      points: spec.points,
      points_per_game: ppg,
      pace: pace17,
      ppg_rank: spec.ppgRank,
      total_rank: spec.totalRank,
      cohort_size: 34,
      cohort_min_games: 3,
      espn_rostered: spec.rostered,
    },
    qualification: hidden
      ? [
          { rule: "games", label: "Games played, at least", value: spec.games, threshold: 3, passed: true },
          { rule: "ppg_rank", label: "Points-a-game rank among 34 QBs", value: spec.ppgRank, threshold: 12, passed: true },
          { rule: "hidden_gap", label: "Total rank minus points-a-game rank, in places", value: spec.totalRank - spec.ppgRank, threshold: 8, passed: true },
        ]
      : [
          { rule: "games", label: "Games played, at least", value: spec.games, threshold: 3, passed: true },
          { rule: "ppg_rank", label: "Points-a-game rank among 34 QBs", value: spec.ppgRank, threshold: 12, passed: true },
          { rule: "espn_below", label: "ESPN rostered %, below", value: spec.rostered, threshold: 50, passed: true },
        ],
    also_qualifies: [],
    sources: hidden ? ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_schedule"] : ["nflverse_player_stats", "nflverse_snap_counts", "nflverse_schedule", "espn_fantasy_ownership"],
    source_times: hidden ? {} : { espn_observed_at_utc: "2026-08-21T11:30:07Z" },
  });
}

// ---------------------------------------------------------------------------- stories

/** Every story of one preset, in the artifact's sort order (family, variant, rank, id). */
export function insightStories(preset: ScoringPreset): InsightStoryRecord[] {
  const stories: InsightStoryRecord[] = [
    ...UPSIDE.map((spec) => upside(preset, spec)),
    volumeLagging(preset),
    volumeShrinking(preset),
    openingObserved(preset),
    openingProspective(preset),
    roleBackfield(preset),
    roleReceiving(preset),
    streak(preset, {
      id: INSIGHT_IDS.streakBreakout,
      playerId: "gsis:00-0000005",
      name: "Trey McBride",
      position: "TE",
      team: "ARI",
      variant: "breakout",
      lead: 4,
      band: 12,
      shareLabel: "Target share",
      horizon: "role_watch",
      weeks: [
        [1, "P", 9.2, 0, 6, 0.18, 14],
        [2, "P", 7.1, 0, 5, 0.16, 19],
        [3, "P", 11.4, 6, 7, 0.2, 9],
        [4, "P", 8.3, 0, 6, 0.19, 15],
        [5, "B"],
        [6, "P", 17.8, 6, 10, 0.27, 3],
        [7, "P", 15.6, 0, 11, 0.29, 5],
        [8, "P", 19.2, 6, 12, 0.3, 2],
      ],
      headline: () => "Trey McBride: 3 straight top-12 TE weeks",
      dek: "Takeover (breakout_v1): TE3 over W6–W8 after TE11 for the season, with his target share at 29% in those games.",
      facts: (ppg, tdShare) => [
        fact("Points rank, W6–W8 → season", "TE3 → TE11", "observed"),
        fact("Points a game, W6–W8", ppg.toFixed(1), "observed"),
        fact("Target share, before → W6–W8", "18% → 29%", "observed"),
        fact("Points from touchdowns, W6–W8", `${String(tdShare)}%`, "observed"),
      ],
      counterpoint: null,
    }),
    streak(preset, {
      id: INSIGHT_IDS.streakTouchdowns,
      playerId: "gsis:00-0000006",
      name: "Deebo Gray",
      position: "WR",
      team: "SF",
      variant: "production_without_role",
      lead: 10,
      band: 24,
      shareLabel: "Target share",
      horizon: "role_watch",
      weeks: [
        [1, "P", 7.2, 0, 5, 0.15, 52],
        [2, "P", 5.9, 0, 4, 0.14, 60],
        [3, "D"],
        [4, "P", 8.8, 6, 5, 0.16, 44],
        [5, "P", 6.1, 0, 5, 0.15, 58],
        [6, "P", 19.4, 12, 5, 0.15, 9],
        [7, "P", 16.7, 12, 4, 0.14, 12],
        [8, "P", 21.3, 12, 6, 0.16, 6],
      ],
      headline: () => "Deebo Gray: 3 top-24 WR weeks in a row, but his target share is 15%",
      dek: "Production jumped; usage did not reach breakout_v1's role bar. Repeating it rests on touchdowns rather than a bigger role.",
      facts: (ppg, tdShare) => [
        fact("Points rank, W6–W8 → season", "WR7 → WR31", "observed"),
        fact("Points a game, W6–W8", ppg.toFixed(1), "observed"),
        fact("Target share, before → W6–W8", "15% → 15%", "observed"),
        fact("Points from touchdowns, W6–W8", `${String(tdShare)}%`, "observed"),
      ],
      counterpoint: "His role may still be growing: three games is a short read on usage.",
    }),
    streak(preset, {
      id: INSIGHT_IDS.streakQuiet,
      playerId: "gsis:00-0000003",
      name: "Ja'Marr Swift",
      position: "WR",
      team: "CIN",
      variant: "quiet_role_growth",
      lead: null,
      band: 24,
      shareLabel: "Target share",
      horizon: "role_watch",
      weeks: [
        [1, "P", 10.1, 0, 6, 0.18, 33],
        [2, "P", 8.4, 0, 5, null, 40],
        [3, "P", 12.0, 6, 6, 0.19, 28],
        [4, "P", 9.3, 0, 6, 0.18, 37],
        [5, "P", 11.2, 0, 8, 0.22, 30],
        [6, "P", 12.8, 0, 9, 0.26, 24],
        [7, "B"],
        [8, "P", 13.9, 0, 10, 0.28, 21],
      ],
      headline: () => "Ja'Marr Swift's target share rose from 19% to 27% before the points did",
      dek: "Over W6–W8 his role passed breakout_v1's growth bar while his scoring ranks WR26. The points have not followed the role yet.",
      facts: (ppg, tdShare) => [
        fact("Points rank, W6–W8 → season", "WR26 → WR33", "observed"),
        fact("Points a game, W6–W8", ppg.toFixed(1), "observed"),
        fact("Target share, before → W6–W8", "19% → 27%", "observed"),
        fact("Points from touchdowns, W6–W8", `${String(tdShare)}%`, "observed"),
      ],
      counterpoint: "2 games in the window: a small sample.",
    }),
    pace(preset, {
      id: INSIGHT_IDS.pacePerGame,
      playerId: "gsis:00-0000009",
      name: "Joe Burrow",
      team: "CIN",
      variant: "per_game_hidden",
      lead: 6,
      games: 5,
      teamGames: 7,
      points: 104,
      ppgRank: 4,
      totalRank: 15,
      rostered: null,
    }),
    pace(preset, {
      id: INSIGHT_IDS.paceOverlooked,
      playerId: "gsis:00-0000018",
      name: "Jalen Marsh",
      team: "PHI",
      variant: "overlooked",
      lead: null,
      games: 8,
      teamGames: 8,
      points: 141.6,
      ppgRank: 11,
      totalRank: 9,
      rostered: 36.2,
    }),
  ];
  return stories;
}

export function insightRecords(options: { readonly families?: "all" | "no_upside" } = {}): InsightStoryRecord[] {
  const out: InsightStoryRecord[] = [];
  for (const preset of ["HALF", "PPR", "STD"] as const) {
    for (const record of insightStories(preset)) {
      if (options.families === "no_upside" && record.family === "weekly_upside") continue;
      out.push(record);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------- metadata

const FAMILY_ORDER = [
  "weekly_upside",
  "opportunity_opening",
  "volume_vs_results",
  "streak_watch",
  "role_battle",
  "pace_perspective",
] as const;

function counts(family: string, records: readonly InsightStoryRecord[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const preset of ["HALF", "PPR", "STD"] as const) {
    out[preset] = records.filter((record) => record.family === family && record.scoring_preset === preset).length;
  }
  return out;
}

export type InsightsFixtureMode = "present" | "absent" | "withheld" | "empty" | "degraded";

export function insightsMetadata(mode: Exclude<InsightsFixtureMode, "absent"> = "present"): InsightsMetadata {
  const records = mode === "present" ? insightRecords() : mode === "degraded" ? insightRecords({ families: "no_upside" }) : [];
  const families: Record<string, InsightsMetadata["families"][string]> = {};
  const EMPTY_REASONS: Readonly<Record<string, string>> = {
    weekly_upside: "no player under 50% rostered had a confirmed role and a top-3 ceiling",
    opportunity_opening: "no player with a large enough share is absent",
    volume_vs_results: "no workload held while its scoring trailed by the required places",
    streak_watch: "no player met breakout_v1's streak or growth rules",
    role_battle: "no room's shares moved by the required step",
    pace_perspective: "no per-game rank was hidden by missed games",
  };
  for (const family of FAMILY_ORDER) {
    if (mode === "degraded" && family === "weekly_upside") {
      families[family] = {
        status: "unavailable",
        reason: "ESPN roster readings unavailable: weekly upside not built",
        qualified: {},
        published: {},
        suppressed: {},
      };
      continue;
    }
    const published = counts(family, records);
    families[family] = {
      status: mode === "empty" || mode === "withheld" ? "empty" : "published",
      reason: mode === "empty" || mode === "withheld" ? (EMPTY_REASONS[family] ?? null) : null,
      qualified: published,
      published,
      suppressed: mode === "present" && family === "volume_vs_results" ? { duplicate_player: 1 } : {},
    };
  }
  const leads = (preset: ScoringPreset): number =>
    records.filter((record) => record.scoring_preset === preset && record.lead_rank !== null).length;
  return {
    status: mode === "withheld" ? "withheld" : "published",
    withheld_reason: mode === "withheld" ? "season actuals are withheld for this build, and every story reads them" : null,
    rule_version: "insights_v1",
    selection_rule_version: "insights_select_v1",
    edition: INSIGHTS_EDITION,
    season: SEASON,
    through_week: THROUGH,
    target_week: TARGET,
    generated_at_utc: FIXTURE_GENERATED_AT,
    window: { first_week: 6, last_week: 8, weeks: 3, baseline_first_week: 1, baseline_last_week: 5 },
    rule: { version: "insights_v1", window_weeks: 3, upside_ceilings: [50, 25, 10], upside_per_position: 3 },
    selection: {
      lead_max: 12,
      family_order: [...FAMILY_ORDER],
      family_caps: { weekly_upside: 3, opportunity_opening: 2, volume_vs_results: 3, streak_watch: 2, role_battle: 2, pace_perspective: 1 },
      team_cap: 2,
      one_story_per_player: true,
    },
    families,
    sources: {
      nflverse_player_stats: { state: "available", detail: null },
      nflverse_pbp: { state: mode === "degraded" ? "partial" : "available", detail: mode === "degraded" ? "W6 play-by-play missing" : null },
      weekly_projections: { state: "available", detail: null },
      espn_fantasy_ownership:
        mode === "degraded"
          ? { state: "unavailable", detail: "no ESPN capture newer than 48 hours" }
          : { state: "available", detail: "18 of 19 published players observed" },
    },
    counts: {
      HALF: { stories: records.filter((record) => record.scoring_preset === "HALF").length, lead: leads("HALF") },
      PPR: { stories: records.filter((record) => record.scoring_preset === "PPR").length, lead: leads("PPR") },
      STD: { stories: records.filter((record) => record.scoring_preset === "STD").length, lead: leads("STD") },
    },
    definitions: {
      window:
        "The last three completed regular-season weeks ending at the cutoff, the same calendar weeks for every player (recent form's Last 3). The baseline is every earlier week.",
      appearance:
        "A week with a stats row or an offensive snap. A bye (B) and a game his team played without him (D) are not games and are never zeros.",
      ceiling:
        "P90 of the weekly start/sit model's distribution of his points given that he plays: one week in ten at or above it. Not a 90% chance of a big game, and not a ranking of boom probabilities.",
      espn_rostered:
        "ESPN's public share of ESPN leagues rostering him. It describes ESPN leagues, not yours; an unknown reading is not 0%.",
      pace: "Points per game × 17: arithmetic extrapolation, not a projection.",
      snap_share:
        "His share of his team's offensive snaps. Teammates share the field, so snap shares overlap and never add to 100%.",
    },
    limitations: [
      "Stories describe completed weeks and the published weekly distribution; none is a forecast of a result, and none says a player is due.",
      "League size changes nothing here: no story reads a replacement level or a VORP.",
    ],
    unsupported: [
      {
        claim: "Route participation, targets per route run, first-read share, route-tree fit",
        reason: "No current-season route or participation source is available (the participation feed refuses 2026; ADR-107).",
      },
    ],
  };
}

/** The fixture's `insights.json` envelope for a mode, or null when the build published none. */
export function insightRecordsFor(mode: InsightsFixtureMode): InsightStoryRecord[] | null {
  switch (mode) {
    case "present":
      return insightRecords();
    case "degraded":
      return insightRecords({ families: "no_upside" });
    case "empty":
      return [];
    case "absent":
    case "withheld":
      return null;
  }
}
