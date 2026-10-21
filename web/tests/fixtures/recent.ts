/**
 * Recent form fixtures (ADR-113): `recent_form.json` and its metadata, derived the way
 * `recent_form_v1` and `breakout_v1` derive them.
 *
 * Board players' weeks are their usage records' weeks (status, points per preset, role shares),
 * so the card's week strip and the board's recent columns describe one season. Off-board players
 * with season actuals get the weeks their actuals imply. Twelve off-board tight ends
 * (`FIXTURE_TE_PEERS`) out-scored the board's third tight end early and faded late, which is the
 * population a genuine rise needs: he is TE15 for the season and TE3 over the last three weeks.
 *
 * Ranks are computed here over every player, and the categories by a test-side restatement of
 * the rule — so the badge a test finds is one the rule actually gives, not one assigned to a
 * name. Role shares are per-game means (the usage fixture publishes shares, not team totals),
 * where the production rule pools; the difference is a fixture simplification, stated.
 */

import type {
  BreakoutRoleReading,
  BreakoutVerdict,
  Position,
  RecentFormMetadata,
  RecentFormRecord,
  RecentWindow,
  RecentWindowKey,
  RoleMeasureMetric,
  ScoringPreset,
} from "../../src/data/contracts";
import {
  FIXTURE_BUILD_ID,
  FIXTURE_TE_PEERS,
  FIXTURE_THROUGH_WEEK,
  PEER_PRESET_FACTOR,
  seasonActualsRecords,
  usageRecords,
} from "./artifacts";

export { FIXTURE_TE_PEERS };

const PRESETS: readonly ScoringPreset[] = ["HALF", "PPR", "STD"];
const WINDOWS: readonly RecentWindowKey[] = ["1", "2", "3", "4", "6"];
/** The six-week span, read when called: this module and `artifacts.ts` import each other. */
function span(): number[] {
  return Array.from({ length: 6 }, (_, index) => FIXTURE_THROUGH_WEEK - 5 + index);
}

/** The third tight end on the board: the fixture's genuine Takeover in Last 3. */
export const FIXTURE_TAKEOVER_ID = "gsis:00-0000007";

function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export const BREAKOUT_RULE_FIXTURE: RecentFormMetadata["breakout_rule"] = {
  version: "breakout_v1",
  bands: { QB: 12, RB: 24, WR: 24, TE: 12 },
  min_gain_places: 3,
  min_gain_percent: 30,
  min_prior_games: 2,
  max_missed_after_latest: 0,
  takeover_games: 3,
  sneaking_games: 2,
  measures: {
    QB: [
      { metric: "snap_share", averaging: "mean", substantial: 0.8, emerging: null, increase: null },
      { metric: "pass_attempts", averaging: "mean", substantial: 25, emerging: null, increase: null },
    ],
    RB: [
      { metric: "snap_share", averaging: "mean", substantial: 0.55, emerging: 0.4, increase: 0.15 },
      { metric: "carry_share", averaging: "pooled", substantial: 0.45, emerging: 0.3, increase: 0.15 },
    ],
    WR: [
      { metric: "target_share", averaging: "pooled", substantial: 0.22, emerging: 0.16, increase: 0.06 },
      { metric: "snap_share", averaging: "mean", substantial: 0.8, emerging: 0.65, increase: 0.15 },
    ],
    TE: [
      { metric: "target_share", averaging: "pooled", substantial: 0.18, emerging: 0.13, increase: 0.05 },
      { metric: "snap_share", averaging: "mean", substantial: 0.7, emerging: 0.55, increase: 0.15 },
    ],
  },
};

interface Game {
  readonly week: number;
  readonly points: Readonly<Record<ScoringPreset, number>>;
  readonly role: Readonly<Partial<Record<RoleMeasureMetric, number | null>>>;
}

interface Player {
  readonly id: string;
  readonly name: string;
  readonly position: Position;
  /** Every week 1..cutoff: a game, `B` (bye) or `D` (did not play). */
  readonly weeks: ReadonlyMap<number, Game | "B" | "D">;
}

function players(): Player[] {
  const usage = new Map(usageRecords().map((record) => [record.player_id, record]));
  const season = seasonActualsRecords();
  const seen = new Map<string, Player>();
  for (const record of season) {
    if (seen.has(record.player_id)) continue;
    const weeks = new Map<number, Game | "B" | "D">();
    const peer = FIXTURE_TE_PEERS.find((candidate) => candidate.id === record.player_id);
    const held = usage.get(record.player_id);
    const byPreset = (preset: ScoringPreset): number =>
      season.find((row) => row.player_id === record.player_id && row.scoring_preset === preset)?.points ?? 0;
    for (let week = 1; week <= FIXTURE_THROUGH_WEEK; week += 1) {
      if (peer !== undefined) {
        const base = week <= 5 ? peer.early : peer.late;
        const scaled = (preset: ScoringPreset): number => round(base * PEER_PRESET_FACTOR[preset], 2);
        weeks.set(week, {
          week,
          points: { STD: scaled("STD"), HALF: scaled("HALF"), PPR: scaled("PPR") },
          role: { snap_share: 0.5, target_share: 0.1 },
        });
        continue;
      }
      if (held !== undefined) {
        const entry = held.weeks.find((candidate) => candidate.week === week);
        if (entry?.status !== "played" || entry.fantasy_points === null) {
          weeks.set(week, entry?.status === "bye" ? "B" : "D");
          continue;
        }
        weeks.set(week, {
          week,
          points: {
            STD: entry.fantasy_points.STD ?? 0,
            HALF: entry.fantasy_points.HALF ?? 0,
            PPR: entry.fantasy_points.PPR ?? 0,
          },
          role: {
            snap_share: entry.snap_share,
            target_share: entry.target_share,
            carry_share: entry.carry_share,
            pass_attempts: entry.pass_attempts,
          },
        });
        continue;
      }
      // No weekly record: his games are the last `games_played` weeks, points spread evenly,
      // and no role facts at all — the state a missing usage reading has to survive.
      const games = record.games_played;
      const first = FIXTURE_THROUGH_WEEK - games + 1;
      if (games === 0 || week < first) {
        weeks.set(week, "D");
        continue;
      }
      const even = (preset: ScoringPreset): number => {
        const total = byPreset(preset);
        const share = round(total / games, 2);
        return week === FIXTURE_THROUGH_WEEK ? round(total - share * (games - 1), 2) : share;
      };
      weeks.set(week, { week, points: { STD: even("STD"), HALF: even("HALF"), PPR: even("PPR") }, role: {} });
    }
    seen.set(record.player_id, { id: record.player_id, name: record.display_name, position: record.position, weeks });
  }
  return [...seen.values()];
}

function competition(values: ReadonlyMap<string, number>): Map<string, number> {
  const ordered = [...values.values()].map((value) => Math.round(value * 100)).sort((a, b) => b - a);
  return new Map([...values].map(([id, value]) => [id, ordered.indexOf(Math.round(value * 100)) + 1]));
}

function units(value: number, metric: RoleMeasureMetric): number {
  const digits = metric.endsWith("_share") ? 3 : 1;
  return Math.round(round(value, digits) * 10 ** digits);
}

function measure(games: readonly Game[], metric: RoleMeasureMetric): number | null {
  if (games.length === 0) return null;
  const values = games.map((game) => game.role[metric]);
  if (values.some((value) => value === null || value === undefined)) return null;
  return values.reduce<number>((sum, value) => sum + (value ?? 0), 0) / values.length;
}

function roleCheck(
  position: Position,
  games: readonly Game[],
  prior: readonly Game[],
): { verdict: "pass" | "fail" | "unknown"; readings: BreakoutRoleReading[] } {
  const readings = (BREAKOUT_RULE_FIXTURE.measures[position] ?? []).map((spec): BreakoutRoleReading => {
    const digits = spec.metric.endsWith("_share") ? 3 : 1;
    const level = measure(games, spec.metric);
    const defined = prior.filter((game) => measure([game], spec.metric) !== null);
    const baseline = defined.length >= BREAKOUT_RULE_FIXTURE.min_prior_games ? measure(defined, spec.metric) : null;
    const levelR = level === null ? null : round(level, digits);
    const baselineR = baseline === null ? null : round(baseline, digits);
    let passed: BreakoutRoleReading["passed"] = null;
    if (levelR !== null) {
      if (units(levelR, spec.metric) >= units(spec.substantial, spec.metric)) passed = "substantial";
      else if (
        spec.emerging !== null &&
        spec.increase !== null &&
        baselineR !== null &&
        units(levelR, spec.metric) >= units(spec.emerging, spec.metric) &&
        units(levelR, spec.metric) - units(baselineR, spec.metric) >= units(spec.increase, spec.metric)
      ) {
        passed = "increase";
      }
    }
    return {
      metric: spec.metric,
      games: games.length,
      level: levelR,
      baseline: baselineR,
      baseline_games: defined.length,
      passed,
    };
  });
  if (readings.some((reading) => reading.passed !== null)) return { verdict: "pass", readings };
  if (readings.length === 0 || readings.some((reading) => reading.level === null)) return { verdict: "unknown", readings };
  return { verdict: "fail", readings };
}

function verdict(
  player: Player,
  seasonRank: number | null,
  windowRank: number | null,
  games: readonly Game[],
  weekRanks: ReadonlyMap<number, number>,
  prior: readonly Game[],
  missed: number,
): BreakoutVerdict {
  const rule = BREAKOUT_RULE_FIXTURE;
  const band = rule.bands[player.position] ?? 12;
  const make = (
    category: BreakoutVerdict["category"],
    reason: BreakoutVerdict["reason"],
    extra: Partial<BreakoutVerdict> = {},
  ): BreakoutVerdict => ({ category, reason, games: [], streak: null, role: null, ...extra });
  if (games.length === 0 || windowRank === null) return make("insufficient", "no_games");
  if (windowRank > band) return make("none", "outside_band");
  if (prior.length < rule.min_prior_games || seasonRank === null) return make("insufficient", "no_baseline");
  const gain = seasonRank - windowRank;
  if (gain <= 0) return make("none", "not_improved");
  if (gain < rule.min_gain_places || gain * 100 < rule.min_gain_percent * seasonRank) return make("none", "gain_too_small");
  if (missed > rule.max_missed_after_latest) return make("none", "stale");
  const newest = [...games].sort((a, b) => b.week - a.week);
  let streak = 0;
  for (const game of newest) {
    const rank = weekRanks.get(game.week);
    if (rank === undefined || rank > band) break;
    streak += 1;
    if (streak === rule.takeover_games) break;
  }
  const latest = newest[0];
  if (streak === 0 || latest === undefined) {
    return make("none", "latest_not_strong", { games: latest === undefined ? [] : [latest.week], streak: 0 });
  }
  let last: BreakoutRoleReading[] | null = null;
  for (const [size, category] of [
    [rule.takeover_games, "takeover"],
    [rule.sneaking_games, "sneaking"],
  ] as const) {
    if (streak < size) continue;
    const used = newest.slice(0, size);
    const weeks = used.map((game) => game.week).sort((a, b) => a - b);
    const check = roleCheck(player.position, used, prior);
    if (check.verdict === "pass") {
      return make(category, category === "takeover" ? "takeover_role" : "sneaking_role", {
        games: weeks,
        streak,
        role: check.readings,
      });
    }
    if (check.verdict === "unknown") {
      return make("insufficient", "role_unavailable", { games: weeks, streak, role: check.readings });
    }
    last = check.readings;
  }
  return make("eyebrow", streak === 1 ? "one_strong" : "role_not_confirmed", {
    games: [latest.week],
    streak,
    role: last,
  });
}

export function recentFormRecords(): RecentFormRecord[] {
  const SPAN = span();
  const all = players();
  const seasonRank = new Map(
    seasonActualsRecords().map((record) => [`${record.scoring_preset}|${record.player_id}`, record.season_position_rank]),
  );
  const records: RecentFormRecord[] = [];
  for (const preset of PRESETS) {
    const weekRanks = new Map<number, Map<string, number>>();
    for (const week of SPAN) {
      const ranks = new Map<string, number>();
      for (const position of ["QB", "RB", "WR", "TE"] as const) {
        const members = new Map<string, number>();
        for (const player of all) {
          const game = player.weeks.get(week);
          if (player.position === position && typeof game === "object") members.set(player.id, game.points[preset]);
        }
        for (const [id, rank] of competition(members)) ranks.set(id, rank);
      }
      weekRanks.set(week, ranks);
    }
    const windowRanks = new Map<RecentWindowKey, Map<string, number>>();
    for (const key of WINDOWS) {
      const weeks = SPAN.slice(-Number(key));
      const ranks = new Map<string, number>();
      for (const position of ["QB", "RB", "WR", "TE"] as const) {
        const members = new Map<string, number>();
        for (const player of all) {
          if (player.position !== position) continue;
          const games = weeks.map((week) => player.weeks.get(week)).filter((game): game is Game => typeof game === "object");
          if (games.length > 0) members.set(player.id, round(games.reduce((sum, game) => sum + game.points[preset], 0), 2));
        }
        for (const [id, rank] of competition(members)) ranks.set(id, rank);
      }
      windowRanks.set(key, ranks);
    }
    for (const player of all) {
      const season = seasonRank.get(`${preset}|${player.id}`) ?? null;
      const status = SPAN.map((week) => {
        const game = player.weeks.get(week);
        return typeof game === "object" ? "P" : (game ?? "D");
      }).join("");
      const own = new Map<number, number>();
      for (const week of SPAN) {
        const rank = weekRanks.get(week)?.get(player.id);
        if (rank !== undefined) own.set(week, rank);
      }
      const windows = Object.fromEntries(
        WINDOWS.map((key): [RecentWindowKey, RecentWindow] => {
          const weeks = SPAN.slice(-Number(key));
          const first = weeks[0] ?? 1;
          const games = weeks.map((week) => player.weeks.get(week)).filter((game): game is Game => typeof game === "object");
          const prior = [...player.weeks.values()].filter((game): game is Game => typeof game === "object" && game.week < first);
          const points = round(games.reduce((sum, game) => sum + game.points[preset], 0), 2);
          const rank = games.length > 0 ? (windowRanks.get(key)?.get(player.id) ?? null) : null;
          const latest = games.at(-1)?.week ?? null;
          const missed =
            latest === null ? 0 : SPAN.filter((week, index) => week > latest && status[index] === "D").length;
          return [
            key,
            {
              games: games.length,
              points,
              points_per_game: games.length === 0 ? null : round(points / games.length, 2),
              rank,
              prior_games: prior.length,
              breakout: verdict(player, season, rank, games, own, prior, missed),
            },
          ];
        }),
      ) as Record<RecentWindowKey, RecentWindow>;
      records.push({
        schema_version: "1.0",
        build_id: FIXTURE_BUILD_ID,
        season: 2026,
        through_week: FIXTURE_THROUGH_WEEK,
        scoring_preset: preset,
        player_id: player.id,
        display_name: player.name,
        position: player.position,
        season_rank: season,
        span_status: status,
        span_points: SPAN.map((week) => {
          const game = player.weeks.get(week);
          return typeof game === "object" ? game.points[preset] : null;
        }),
        span_ranks: SPAN.map((week) => own.get(week) ?? null),
        windows,
      });
    }
  }
  return records.sort(
    (a, b) =>
      a.scoring_preset.localeCompare(b.scoring_preset) ||
      a.position.localeCompare(b.position) ||
      a.player_id.localeCompare(b.player_id),
  );
}

export function recentFormMetadata(overrides: Partial<RecentFormMetadata> = {}): RecentFormMetadata {
  const records = recentFormRecords();
  const population: Record<string, Record<string, number>> = {};
  const categories: Record<string, Record<string, Record<string, number>>> = {};
  for (const key of WINDOWS) {
    const counts: Record<string, number> = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const record of records) {
      if (record.scoring_preset === "HALF" && record.windows[key].games > 0) counts[record.position] = (counts[record.position] ?? 0) + 1;
    }
    population[key] = counts;
  }
  for (const record of records) {
    const byPreset = (categories[record.scoring_preset] ??= {});
    for (const key of WINDOWS) {
      const byWindow = (byPreset[key] ??= {});
      const category = record.windows[key].breakout.category;
      byWindow[category] = (byWindow[category] ?? 0) + 1;
    }
  }
  return {
    rule: {
      version: "recent_form_v1",
      windows: [1, 2, 3, 4, 6],
      default_window: 3,
      points_decimals: 2,
      rank_method: "competition",
      scoring_engine_version: "scoring_v1",
    },
    breakout_rule: BREAKOUT_RULE_FIXTURE,
    status: "published",
    withheld_reason: null,
    season: 2026,
    through_week: FIXTURE_THROUGH_WEEK,
    span_weeks: span(),
    windows: Object.fromEntries(
      WINDOWS.map((key) => {
        const weeks = span().slice(-Number(key));
        return [key, { requested: Number(key), first_week: weeks[0] ?? null, last_week: weeks.at(-1) ?? null, weeks: weeks.length }];
      }),
    ),
    scoring_presets: ["HALF", "PPR", "STD"],
    definitions: {
      window:
        "The last N completed regular-season weeks ending at the cutoff, the same calendar weeks for every player.",
      recent_rank:
        "Rank by total points in the window among every player at the position who appeared in it.",
      recent_vs_season: "Season rank minus recent rank, in places. Positive means the recent rank is better.",
      breakout: "A descriptive, heuristic category from fixed thresholds. Not a prediction.",
      takeover:
        "Three consecutive appearances inside the window, each a top-band weekly finish, with a substantial or clearly increased role over those games.",
      sneaking:
        "His two most recent appearances inside the window are top-band weekly finishes with a confirmed role; the three-game condition is not met.",
      eyebrow:
        "A one-game watch: his latest appearance is a top-band weekly finish, and earlier games do not establish a sustained pattern.",
      insufficient: "The sample, the pre-window baseline or the role facts the rule needs do not exist.",
    },
    records: records.length,
    population,
    categories,
    ...overrides,
  };
}
