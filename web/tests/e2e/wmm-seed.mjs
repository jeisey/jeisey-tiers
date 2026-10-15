/**
 * A Win My Matchup scenario drawn from a build's own files (ADR-110), shared by
 * `verify-budget.mjs` and `measure-wmm.mjs` so the byte budgets and the interaction targets are
 * measured on the same kind of matchup.
 *
 * It picks players a simulation can use — a week-`target` PPR distribution, an upcoming game,
 * no injury designation and no reserve or injury status — splits them between the reader's
 * roster and the opponent's starters by position (and only signed players: ADR-102's unsigned,
 * retired and unknown readings are not playable), and writes the two localStorage documents
 * exactly as the page would: the saved league (`jeisey-tiers.my-leagues` v1) and its matchup
 * (`jeisey-tiers.win-my-matchup` v1). Nothing is invented: every id is in the build.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

export const DEFAULT_COUNTS = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 5, IR: 2 };
/** ADR-106's maxima: 15 starters a side and a ten-man bench. */
export const MAX_COUNTS = { QB: 2, RB: 4, WR: 4, TE: 2, FLEX: 3, BN: 10, IR: 0 };

const STARTERS = ["QB", "RB", "WR", "TE", "FLEX"];

function playable(dist) {
  const data = join(dist, "data");
  const metadata = JSON.parse(readFileSync(join(data, "ros_build_metadata.json"), "utf-8"));
  const target = metadata.weekly?.target_week;
  const weekly = JSON.parse(readFileSync(join(data, "weekly_projections.json"), "utf-8")).records;
  const status = new Map(
    JSON.parse(readFileSync(join(data, "player_status.json"), "utf-8")).records.map((row) => [row.player_id, row]),
  );
  const ok = (record) => {
    const row = status.get(record.player_id);
    return (
      record.scoring_preset === "PPR" &&
      record.target_week === target &&
      record.game_state === "upcoming" &&
      record.quantiles !== null &&
      record.injury === null &&
      (row === undefined ||
        (row.injury_status === null &&
          (row.roster_status === null || row.roster_status === "ACT") &&
          (row.employment_status ?? "signed") === "signed"))
    );
  };
  const seen = new Set();
  const byPosition = { QB: [], RB: [], WR: [], TE: [] };
  for (const record of weekly.filter(ok).sort((a, b) => b.quantiles.q50 - a.quantiles.q50)) {
    if (seen.has(record.player_id) || byPosition[record.position] === undefined) continue;
    seen.add(record.player_id);
    byPosition[record.position].push(record.player_id);
  }
  return { byPosition, season: metadata.season, week: target, behaviorAt: metadata.behavior?.snapshot_at_utc ?? null };
}

/**
 * The two documents. `counts` sets both lineups' slots; the reader's bench is filled with the
 * next playable players so lineup changes have something to evaluate.
 */
export function wmmScenario(dist, { counts = DEFAULT_COUNTS, base, leagueId = "lg-wmmbudget", name = "Matchup" } = {}) {
  const { byPosition, season, week, behaviorAt } = playable(dist);
  const queues = Object.fromEntries(Object.entries(byPosition).map(([position, ids]) => [position, [...ids]]));
  const take = (position) => {
    const id = queues[position]?.shift();
    if (id === undefined) throw new Error(`the build has too few playable ${position}s for this scenario`);
    return id;
  };
  const flex = ["RB", "WR", "TE"];
  const lineup = () =>
    Object.fromEntries(
      STARTERS.map((group) => [
        group,
        Array.from({ length: counts[group] }, (_, index) => take(group === "FLEX" ? flex[index % flex.length] : group)),
      ]),
    );
  // Alternate picks so neither side gets every top player.
  const mine = lineup();
  const theirs = lineup();
  const benchOrder = ["RB", "WR", "TE", "QB"];
  const bench = Array.from({ length: counts.BN }, (_, index) => take(benchOrder[index % benchOrder.length]));
  const roster = { ...mine, BN: bench, IR: Array.from({ length: counts.IR }, () => null) };
  const league = {
    id: leagueId,
    name,
    season,
    scoring: "ppr",
    teams: 12,
    slots: counts,
    roster,
    prefs: { risingStars: false, mode: "q50" },
    rev: 1,
    updatedAt: "2026-10-15T00:00:00Z",
  };
  const matchup = {
    format: "jeisey-tiers.win-my-matchup",
    version: 1,
    revision: 1,
    prefs: {},
    entries: [
      {
        leagueId,
        season,
        week,
        opponent: { name: "Rival", starters: theirs, others: [] },
        confirmedEmpty: { mine: [], theirs: [] },
        countZero: [],
        finals: {},
        marks: {},
        rev: 1,
        updatedAt: "2026-10-15T00:00:00Z",
      },
    ],
  };
  return {
    league,
    matchup,
    spare: Object.fromEntries(Object.entries(queues).map(([position, ids]) => [position, ids.slice(0, 6)])),
    week,
    behaviorAt,
    keys: { leagues: `jeisey-tiers:my-leagues@${base}`, matchups: `jeisey-tiers:win-my-matchup@${base}` },
  };
}

/** The leagues document holding `leagues`, the first one active. */
export function leaguesDocument(leagues) {
  return JSON.stringify({ format: "jeisey-tiers.my-leagues", version: 1, revision: 1, activeId: leagues[0]?.id ?? null, leagues });
}
