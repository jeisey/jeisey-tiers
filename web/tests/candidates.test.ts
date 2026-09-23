/**
 * The Opportunity Board's candidate layer (ADR-092): one row joined to the signal artifacts,
 * with every absence named, and the filters and orderings over it.
 *
 * Every assertion is made against the fixture *artifacts* — the records the site would load —
 * rather than against hand-built shapes, and the important ones are written so the defect they
 * guard against would fail them:
 *
 * | defect | the test that fails on it |
 * |---|---|
 * | a role direction reversed | "states the direction the published change has, for every row" |
 * | a missing slope read as zero | "never turns a missing slope into a zero" |
 * | another player's (or team's) next game | "reads each row's next game for its own team" |
 * | role magnitudes compared across positions | "cannot compare a QB's attempts with a back's share" |
 * | a filter or sort that moves Pick of the Week | "leaves Pick of the Week exactly where it was" |
 */

import { describe, expect, it } from "vitest";

import {
  compareMomentum,
  compareRole,
  momentumCell,
  nextGameCell,
  opportunityCandidate,
  primaryRoleMetric,
  roleCell,
  roleOrderingFor,
  selectOpportunityCandidates,
  signalTeam,
  type OpportunityCandidate,
} from "../src/data/candidates";
import { OPPORTUNITY_EXPORT_COLUMNS, opportunityRowsToCsv } from "../src/data/csv";
import { buildPotwBoard, selectPotwBoard } from "../src/data/potw";
import { InSeasonBundle, formatMomentumRate, momentumDirection } from "../src/data/ros";
import { ROLE_METRICS_BY_POSITION, roleReading } from "../src/data/signals";
import {
  DEFAULT_STATE,
  OPPORTUNITY_FILTERS,
  OPPORTUNITY_SORTS,
  type AppState,
  type OpportunityFilter,
} from "../src/data/state";
import {
  behaviorSeriesRecords,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  teamMatchupRecords,
  usageRecords,
} from "./fixtures/artifacts";
import { required } from "./required";

const QB_RISING = "Jalen Marsh";
const RB_RISING = "Jahmyr Cook";
const WR_FLAT_SNAP = "Rashee Kirk";
const WR_DECLINING = "Deebo Gray";
const TE_NO_SNAP = "Trey McBride";
const SURFACED = "Bijan Robinson (surfaced)";
const LONG_ABSENCE = "Ja'Marr Swift";
const NO_MATCHUP_TEAM = "Zach Ertz";
const MOMENTUM_ENDED = "Zay Meadows";

function bundle(
  options: {
    readonly signals?: boolean;
    readonly series?: boolean;
    readonly behaviorAvailable?: boolean;
  } = {},
): InSeasonBundle {
  const signals = options.signals ?? true;
  const series = options.series ?? true;
  return new InSeasonBundle({
    metadata: rosBuildMetadata({}, options.behaviorAvailable ?? true),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(options.behaviorAvailable ?? true),
    opportunityDegradation: null,
    behaviorSeries: series ? behaviorSeriesRecords() : null,
    usage: signals ? usageRecords() : null,
    matchups: signals ? teamMatchupRecords() : null,
  });
}

function state(patch: Partial<AppState> = {}): AppState {
  return { ...DEFAULT_STATE, view: "opportunity", ...patch };
}

function select(patch: Partial<AppState> = {}, source = bundle()) {
  return selectOpportunityCandidates(source, state(patch));
}

function candidate(name: string, source = bundle()): OpportunityCandidate {
  return required(
    select({}, source).candidates.find((row) => row.row.record.display_name === name),
    `a candidate named ${name}`,
  );
}

function names(candidates: readonly OpportunityCandidate[]): readonly string[] {
  return candidates.map((row) => row.row.record.display_name);
}

// --------------------------------------------------------------------------------- role

describe("the board's role reading", () => {
  it("leads with the position's first mapped metric and invents no second map", () => {
    for (const position of ["QB", "RB", "WR", "TE"] as const) {
      expect(primaryRoleMetric(position)).toBe(ROLE_METRICS_BY_POSITION[position][0]);
    }
    expect(primaryRoleMetric("QB")).toBe("pass_attempts");
    expect(primaryRoleMetric("RB")).toBe("snap_share");
  });

  it("reads a quarterback's rising pass attempts in attempts, not as a share", () => {
    const { role } = candidate(QB_RISING);
    expect(role.kind).toBe("measured");
    if (role.kind !== "measured") return;
    expect(role.reading.spec.metric).toBe("pass_attempts");
    expect(role.direction).toBe("up");
    const cell = roleCell(role, "QB");
    expect(cell.metric).toBe("Pass att");
    expect(cell.value).toBe("48");
    expect(cell.change).toBe("▲ +20");
    expect(cell.change).not.toMatch(/pts|%/);
    expect(cell.detail).toBe("wk 8 vs 7 gms");
  });

  it("reads a back's rising snap share with the card's glyph and wording", () => {
    const { role } = candidate(RB_RISING);
    expect(role.kind).toBe("measured");
    const cell = roleCell(role, "RB");
    expect(cell.metric).toBe("Snap");
    expect(cell.value).toBe("81%");
    expect(cell.change).toBe("▲ +34 pts");
    expect(cell.direction).toBe("up");
  });

  it("prints a flat snap share as flat even where the card's other rails move", () => {
    const { role } = candidate(WR_FLAT_SNAP);
    expect(role.kind).toBe("measured");
    if (role.kind !== "measured") return;
    expect(role.direction).toBe("flat");
    expect(roleCell(role, "WR").change).toBe("▬ no change");
    // The card draws target and air-yards rails for the same record, and they rose. The board
    // leads with one metric by design; the disagreement is the reason to open the card.
    expect(roleReading(role.usage, "target_share").direction).toBe("up");
    expect(roleReading(role.usage, "air_yards_share").direction).toBe("up");
  });

  it("shows a declining role as declining, never hidden", () => {
    const { role } = candidate(WR_DECLINING);
    expect(role.kind).toBe("measured");
    const cell = roleCell(role, "WR");
    expect(cell.direction).toBe("down");
    expect(cell.change).toBe("▼ −29 pts");
  });

  it("withholds a change when the latest game has no snap value, and never reaches back", () => {
    const { role } = candidate(TE_NO_SNAP);
    expect(role.kind).toBe("no_latest_value");
    const cell = roleCell(role, "TE");
    expect(cell.value).toBe("—");
    expect(cell.change).toBeNull();
    expect(cell.direction).toBeNull();
    expect(cell.detail).toBe("no latest value");
  });

  it("states one appearance as a level with no direction", () => {
    const { role } = candidate(SURFACED);
    expect(role.kind).toBe("one_game");
    const cell = roleCell(role, "RB");
    expect(cell.value).toBe("45%");
    expect(cell.change).toBeNull();
    expect(cell.detail).toBe("wk 8 only");
  });

  it("tells a missing artifact from a missing record", () => {
    expect(candidate(RB_RISING, bundle({ signals: false })).role.kind).toBe("unpublished");
    expect(roleCell({ kind: "unpublished" }, "RB").detail).toBe("not published");
    const noRecord = required(
      select().candidates.find((row) => row.role.kind === "no_record"),
      "the fixture's player with no usage record",
    );
    expect(roleCell(noRecord.role, noRecord.row.record.position).sentence).toMatch(
      /No week-by-week role is published for him/,
    );
  });

  it("states the direction the published change has, for every row", () => {
    // The mutation this guards: a glyph flipped, or a direction read from a subtraction done
    // in the browser. For every measured row the direction must be the sign of the artifact's
    // own change at the precision it is printed.
    let measured = 0;
    for (const row of select().candidates) {
      if (row.role.kind !== "measured") continue;
      measured += 1;
      const change = required(row.role.reading.change?.change, "a published change");
      const printed =
        row.role.reading.spec.unit === "share"
          ? Math.round(Math.abs(change) * 100)
          : Math.round(Math.abs(change));
      const expected = printed === 0 ? "flat" : change > 0 ? "up" : "down";
      expect(row.role.direction, row.row.record.display_name).toBe(expected);
      expect(roleCell(row.role, row.row.record.position).change?.[0]).toBe(
        { up: "▲", down: "▼", flat: "▬" }[expected],
      );
    }
    expect(measured).toBeGreaterThan(10);
  });
});

// ----------------------------------------------------------------------------- momentum

describe("the board's momentum reading", () => {
  it("reads a rising slope from the published series, with its span", () => {
    const row = candidate(RB_RISING);
    expect(row.momentum.kind).toBe("measured");
    const cell = momentumCell(row.momentum);
    expect(cell.direction).toBe("rising");
    expect(cell.value).toMatch(/^▲ \+\d+\.\d\/day$/);
    expect(cell.span).toMatch(/^over \d+ (day|hour)s?$/);
  });

  it("reads a falling slope as falling", () => {
    const falling = required(
      select().candidates.find(
        (row) => row.momentum.kind === "measured" && row.momentum.direction === "falling",
      ),
      "a falling series in the fixture",
    );
    // At or past a hundred a day the slope prints in whole transactions (`-100/day`).
    expect(momentumCell(falling.momentum).value).toMatch(/^▼ -(\d{1,3}(,\d{3})*|\d+\.\d)\/day$/);
  });

  it("prints the artifact's own slope, not one computed here", () => {
    for (const row of select().candidates) {
      if (row.momentum.kind !== "measured") continue;
      const published = required(row.momentum.momentum.record.add_trend, "a published slope");
      expect(row.momentum.momentum.trend).toBe(published);
      expect(row.momentum.direction).toBe(momentumDirection(published));
    }
  });

  it("names one observation, a player the feed never carried, and a missing series apart", () => {
    const one = required(
      select().candidates.find((row) => row.momentum.kind === "one_observation"),
      "a one-observation series",
    );
    expect(momentumCell(one.momentum).value).toBe("one obs.");
    expect(candidate(QB_RISING).momentum.kind).toBe("not_in_feed");
    expect(momentumCell({ kind: "not_in_feed" }).value).toBe("not in feed");
    expect(candidate(RB_RISING, bundle({ series: false })).momentum.kind).toBe("unpublished");
    expect(momentumCell({ kind: "unpublished" }).value).toBe("—");
  });

  it("prints a slope whose window ended early, and never lets it pass as current", () => {
    const row = candidate(MOMENTUM_ENDED);
    expect(row.momentum.kind).toBe("ended");
    if (row.momentum.kind !== "ended") return;
    // The published slope is still printed, with its span and the day the window ended.
    expect(row.momentum.momentum.trend).toBe(row.momentum.momentum.record.add_trend);
    expect(row.momentum.direction).toBe("rising");
    const cell = momentumCell(row.momentum);
    expect(cell.value).toMatch(/^▲ \+/);
    expect(cell.span).toMatch(/^over \d+ (day|hour)s? · to [A-Z][a-z]{2} \d{1,2}$/);
    expect(cell.sentence).toMatch(/not a current reading/);
    // It is not "Momentum rising", and it sorts after every current slope.
    expect(names(select({ only: ["momentum"] }).candidates)).not.toContain(MOMENTUM_ENDED);
    const ordered = select({ opportunity: "momentum" }).candidates;
    const at = names(ordered).indexOf(MOMENTUM_ENDED);
    const lastCurrent = ordered.map((c) => c.momentum.kind).lastIndexOf("measured");
    expect(at).toBeGreaterThan(lastCurrent);
  });

  it("cannot call a reading current without a snapshot time to compare it with", () => {
    const source = new InSeasonBundle({
      metadata: rosBuildMetadata({ behavior: null }),
      rosTiers: rosTierRecords(),
      opportunity: opportunityRecords(),
      opportunityDegradation: null,
      behaviorSeries: behaviorSeriesRecords(),
      usage: usageRecords(),
      matchups: teamMatchupRecords(),
    });
    // With no recorded snapshot the newest published point stands in for it, so the ordinary
    // rows are still current and the early-ending one is still not.
    expect(candidate(RB_RISING, source).momentum.kind).toBe("measured");
    expect(candidate(MOMENTUM_ENDED, source).momentum.kind).toBe("ended");
  });

  it("never turns a missing slope into a zero", () => {
    // A zero would print as a flat reading and would sort *above* every falling player. Both
    // are asserted, because either is the defect.
    const absent = candidate(QB_RISING);
    const cell = momentumCell(absent.momentum);
    expect(cell.value).not.toMatch(/0\.0|\/day/);
    expect(cell.direction).toBeNull();
    const ordered = select({ opportunity: "momentum" }).candidates;
    const lastMeasured = ordered.map((row) => row.momentum.kind).lastIndexOf("measured");
    const firstUnmeasured = ordered.findIndex((row) => row.momentum.kind !== "measured");
    expect(firstUnmeasured).toBeGreaterThan(lastMeasured);
    const falling = ordered.findIndex(
      (row) => row.momentum.kind === "measured" && row.momentum.direction === "falling",
    );
    expect(falling).toBeGreaterThanOrEqual(0);
    expect(firstUnmeasured).toBeGreaterThan(falling);
  });

  it("prints a large slope in whole transactions and a small one to a tenth", () => {
    expect(formatMomentumRate(72053.7)).toBe("+72,054/day");
    expect(formatMomentumRate(-2238.34)).toBe("-2,238/day");
    expect(formatMomentumRate(99.94)).toBe("+99.9/day");
    expect(formatMomentumRate(0.04)).toBe("0.0/day");
    expect(momentumDirection(0.04)).toBe("flat");
    expect(momentumDirection(-0.06)).toBe("falling");
    expect(formatMomentumRate(null)).toBe("—");
  });

  it("orders momentum by the published slope, highest first", () => {
    const slopes = select({ opportunity: "momentum" })
      .candidates.filter((row) => row.momentum.kind === "measured")
      .map((row) => (row.momentum.kind === "measured" ? (row.momentum.momentum.trend ?? 0) : 0));
    expect(slopes).toEqual([...slopes].sort((a, b) => b - a));
  });
});

// ---------------------------------------------------------------------------- next game

describe("the board's next-game reading", () => {
  it("prints the opponent and the implied team points when a line is posted", () => {
    const cell = nextGameCell(candidate(RB_RISING).nextGame);
    expect(cell.head).toBe("W9 vs ATL");
    expect(cell.detail).toBe("27.5 implied");
    expect(cell.sentence).toMatch(/context, read by no model/);
  });

  it("says a line is not posted rather than drawing a pick'em", () => {
    const cell = nextGameCell(candidate(TE_NO_SNAP).nextGame);
    expect(cell.head).toBe("W9 vs WAS");
    expect(cell.detail).toBe("no line yet");
    expect(cell.linesPosted).toBe(false);
  });

  it("puts a bye before the next game in front of it", () => {
    const cell = nextGameCell(candidate(QB_RISING).nextGame);
    expect(cell.head).toBe("W10 vs SF");
    expect(cell.detail).toBe("bye W9 · no line yet");
    expect(cell.sentence).toMatch(/On bye in week 9 first/);
  });

  it("says a team with no published game has none, and a missing artifact is missing", () => {
    expect(candidate(NO_MATCHUP_TEAM).nextGame.kind).toBe("no_record");
    expect(nextGameCell(candidate(NO_MATCHUP_TEAM).nextGame).sentence).toMatch(/WAS/);
    expect(candidate(RB_RISING, bundle({ signals: false })).nextGame.kind).toBe("unpublished");
  });

  it("never rates an opponent", () => {
    for (const row of select().candidates) {
      const cell = nextGameCell(row.nextGame);
      expect(`${cell.head} ${cell.detail} ${cell.sentence}`).not.toMatch(
        /easy|hard|tough|good matchup|bad matchup|favorable|favourable|soft|vs (QB|RB|WR|TE)\b|\d+(st|nd|rd|th) vs/i,
      );
    }
  });

  it("reads each row's next game for its own team", () => {
    // The mutation this guards: a join on the wrong key, or one row's matchup reused for the
    // next. Every published reading must be the record `team_matchups.json` holds for the
    // team the card itself would read.
    const matchups = new Map(teamMatchupRecords().map((record) => [record.team, record]));
    const usage = new Map(usageRecords().map((record) => [record.player_id, record]));
    let checked = 0;
    for (const row of select().candidates) {
      if (row.nextGame.kind !== "published") continue;
      const team = signalTeam(usage.get(row.row.record.player_id) ?? null, row.row.record.team);
      expect(row.nextGame.reading.record.team, row.row.record.display_name).toBe(team);
      expect(row.nextGame.reading.record, row.row.record.display_name).toStrictEqual(
        matchups.get(team ?? ""),
      );
      checked += 1;
    }
    expect(checked).toBeGreaterThan(10);
  });
});

// ------------------------------------------------------------------------------ filters

describe("the filters", () => {
  it("keeps exactly the rows whose leading role has a published rise", () => {
    const selection = select({ only: ["role"] });
    expect(names(selection.candidates)).toEqual(
      expect.arrayContaining([QB_RISING, RB_RISING, "Puka Nightingale"]),
    );
    for (const row of selection.candidates) {
      expect(row.role.kind === "measured" && row.role.direction === "up").toBe(true);
    }
    // A missing reading is not a "no": it is excluded and counted separately.
    const report = required(selection.filters[0], "the role report");
    expect(report.withoutReading).toBeGreaterThan(0);
    expect(report.passing).toBe(selection.candidates.length);
    expect(names(selection.candidates)).not.toContain(TE_NO_SNAP);
    expect(names(selection.candidates)).not.toContain(WR_FLAT_SNAP);
  });

  it("keeps rising momentum only, and a missing series never passes", () => {
    const selection = select({ only: ["momentum"] });
    expect(selection.candidates.length).toBeGreaterThan(0);
    for (const row of selection.candidates) {
      expect(row.momentum.kind === "measured" && row.momentum.direction === "rising").toBe(true);
    }
    expect(names(selection.candidates)).not.toContain(QB_RISING);
  });

  it("keeps the surfaced rows", () => {
    expect(names(select({ only: ["surfaced"] }).candidates)).toEqual([SURFACED]);
  });

  it("composes by AND with each other and with position and search", () => {
    const both = select({ only: ["role", "momentum"] }).candidates;
    for (const row of both) {
      expect(row.role.kind === "measured" && row.role.direction === "up").toBe(true);
      expect(row.momentum.kind === "measured" && row.momentum.direction === "rising").toBe(true);
    }
    expect(names(select({ only: ["role"], position: "rb" }).candidates)).toEqual([RB_RISING]);
    expect(names(select({ only: ["role"], search: "marsh" }).candidates)).toEqual([QB_RISING]);
  });

  it("does not apply a filter whose artifact is missing, and says so", () => {
    const noSignals = bundle({ signals: false });
    const selection = select({ only: ["role"] }, noSignals);
    expect(selection.unavailable).toEqual(["role"]);
    // Not an empty board: "no player's role rose" would be a claim built from a missing file.
    expect(selection.candidates.length).toBe(selection.matched);
    const noSeries = select({ only: ["momentum", "surfaced"] }, bundle({ series: false }));
    expect(noSeries.unavailable).toEqual(["momentum"]);
    expect(names(noSeries.candidates)).toEqual([SURFACED]);
  });

  it("has a predicate per filter and no filter that counts signals", () => {
    expect([...OPPORTUNITY_FILTERS].sort()).toEqual(["momentum", "role", "surfaced"]);
    expect([...OPPORTUNITY_SORTS].sort()).toEqual(["adds", "momentum", "net", "role", "value"]);
  });
});

// ------------------------------------------------------------------------------- orders

describe("the role ordering", () => {
  it("is categorical across positions: rising, flat, falling, then no reading", () => {
    const selection = select({ opportunity: "role" });
    expect(selection.roleOrdering.magnitudes).toBe(false);
    const rank = { up: 0, flat: 1, down: 2, none: 3 } as const;
    const categories = selection.candidates.map((row) =>
      row.role.kind === "measured" ? rank[row.role.direction] : rank.none,
    );
    expect(categories).toEqual([...categories].sort((a, b) => a - b));
    // Inside "rising", by ROS rank — so the QB's +20 attempts does not jump the backs.
    const rising = selection.candidates.filter(
      (row) => row.role.kind === "measured" && row.role.direction === "up",
    );
    const ranks = rising.map((row) => row.row.record.ros_fair_rank);
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    expect(names(rising).indexOf(QB_RISING)).toBe(rising.length - 1);
  });

  it("compares the size of a change once one position is on screen", () => {
    const selection = select({ opportunity: "role", position: "wr" });
    expect(selection.roleOrdering).toEqual({ magnitudes: true, position: "WR" });
    const measured = selection.candidates.filter((row) => row.role.kind === "measured");
    const changes = measured.map((row) =>
      row.role.kind === "measured" ? (row.role.reading.change?.change ?? 0) : 0,
    );
    expect(changes).toEqual([...changes].sort((a, b) => b - a));
  });

  it("cannot compare a QB's attempts with a back's share, whatever it is told", () => {
    const qb = candidate(QB_RISING);
    const rb = candidate(RB_RISING);
    // A permissive ordering handed in from outside still cannot compare across positions: the
    // RB is ranked ahead of the QB on ROS rank, not behind him on "+20 > +0.34".
    const permissive = { magnitudes: true, position: "QB" } as const;
    expect(compareRole(rb, qb, permissive)).toBeLessThan(0);
    expect(compareRole(qb, rb, permissive)).toBeGreaterThan(0);
    // And the ordering the selection derives for mixed rows never permits it.
    expect(roleOrderingFor([qb, rb]).magnitudes).toBe(false);
  });

  it("orders momentum ties and absences deterministically", () => {
    const a = candidate(QB_RISING);
    const b = candidate(RB_RISING);
    expect(compareMomentum(b, a)).toBeLessThan(0);
    expect(compareMomentum(a, a)).toBe(0);
  });
});

// ----------------------------------------------------------------- invariance and export

describe("what the candidate layer must not change", () => {
  it("copies every published row unmodified", () => {
    const records = opportunityRecords().map((record) => Object.freeze({ ...record }));
    const source = new InSeasonBundle({
      metadata: rosBuildMetadata(),
      rosTiers: rosTierRecords(),
      opportunity: records,
      opportunityDegradation: null,
      behaviorSeries: behaviorSeriesRecords(),
      usage: usageRecords(),
      matchups: teamMatchupRecords(),
    });
    for (const sort of OPPORTUNITY_SORTS) {
      const selection = selectOpportunityCandidates(
        source,
        state({ opportunity: sort, only: ["role"] }),
      );
      for (const row of selection.candidates) {
        expect(records).toContain(row.row.record);
      }
    }
    const fresh = opportunityRecords();
    records.forEach((record, index) => {
      expect(record).toEqual(fresh[index]);
    });
  });

  it("leaves Pick of the Week exactly where it was", () => {
    // The board's filters and orderings live in the same URL as the picks. None of them may
    // reach the selection: every set for every preset, under every filter combination.
    const source = bundle();
    const baseline = buildPotwBoard(source, "redraft-12", "PPR");
    const combos: (readonly OpportunityFilter[])[] = [
      [],
      ["role"],
      ["momentum"],
      ["surfaced"],
      ["role", "momentum", "surfaced"],
    ];
    const ids = (board: ReturnType<typeof buildPotwBoard>) =>
      board.sets.map((set) => set.picks.map((pick) => pick.opportunity.player_id));
    for (const only of combos) {
      for (const opportunity of OPPORTUNITY_SORTS) {
        for (const position of ["all", "rb"] as const) {
          const picked = selectPotwBoard(source, state({ only, opportunity, position }));
          expect(ids(picked)).toEqual(ids(baseline));
        }
      }
    }
    // And building every candidate first changes nothing either.
    select({ only: ["role", "momentum"], opportunity: "role" });
    expect(ids(buildPotwBoard(source, "redraft-12", "PPR"))).toEqual(ids(baseline));
  });
});

describe("the filtered export", () => {
  it("keeps every existing column in place and appends the signal summary", () => {
    const header = OPPORTUNITY_EXPORT_COLUMNS.join(",");
    expect(header.startsWith("season,through_week,ros_fair_rank,player,")).toBe(true);
    expect(OPPORTUNITY_EXPORT_COLUMNS.indexOf("quality_flags")).toBe(28);
    expect(OPPORTUNITY_EXPORT_COLUMNS.slice(29)).toEqual([
      "role_reading",
      "role_metric",
      "role_latest_week",
      "role_latest",
      "role_earlier",
      "role_earlier_games",
      "role_change",
      "momentum_reading",
      "add_trend_per_day",
      "add_trend_span_days",
      "add_trend_observations",
      "add_trend_snapshots_in_window",
      "add_trend_last_observed_at_utc",
      "next_game_reading",
      "next_game_week",
      "next_game_opponent",
      "next_game_home_away",
      "next_game_bye_week_before",
    ]);
  });

  it("carries no sportsbook number", () => {
    for (const column of OPPORTUNITY_EXPORT_COLUMNS) {
      expect(column).not.toMatch(/implied|spread|total|line|odds|margin/);
    }
  });

  it("writes the published values, in the order it was handed, with absences named", () => {
    const rows = select({ opportunity: "role" }).candidates;
    const csv = opportunityRowsToCsv(rows).trim().split("\r\n");
    const header = required(csv[0], "a header").split(",");
    const at = (name: string) => header.indexOf(name);
    expect(csv).toHaveLength(rows.length + 1);
    rows.forEach((row, index) => {
      const cells = required(csv[index + 1], "a row").split(",");
      expect(cells[at("ros_fair_rank")]).toBe(String(row.row.record.ros_fair_rank));
    });
    const byName = (name: string) =>
      required(csv.find((line) => line.includes(`,${name},`)), `a row for ${name}`).split(",");
    const marsh = byName(QB_RISING);
    expect(marsh[at("role_reading")]).toBe("measured");
    expect(marsh[at("role_metric")]).toBe("pass_attempts");
    expect(marsh[at("role_change")]).toBe("20.29");
    expect(marsh[at("momentum_reading")]).toBe("not_in_feed");
    expect(marsh[at("add_trend_per_day")]).toBe("");
    expect(marsh[at("next_game_week")]).toBe("10");
    expect(marsh[at("next_game_bye_week_before")]).toBe("9");
    expect(byName(TE_NO_SNAP)[at("role_reading")]).toBe("no_latest_value");
    expect(byName(SURFACED)[at("role_reading")]).toBe("no_earlier_game");
    expect(byName(MOMENTUM_ENDED)[at("momentum_reading")]).toBe("ended_before_latest_snapshot");
    expect(byName(MOMENTUM_ENDED)[at("add_trend_last_observed_at_utc")]).toMatch(/^2026-/);

    const bare = opportunityRowsToCsv(select({}, bundle({ signals: false, series: false })).candidates);
    const first = required(bare.split("\r\n")[1], "a row").split(",");
    expect(first[at("role_reading")]).toBe("artifact_not_published");
    expect(first[at("momentum_reading")]).toBe("artifact_not_published");
    expect(first[at("next_game_reading")]).toBe("artifact_not_published");
  });

  it("leaves a long absence and its status exactly as published", () => {
    const row = candidate(LONG_ABSENCE);
    expect(row.row.record.long_absence).toBe(true);
    expect(opportunityCandidate(bundle(), row.row).row.record).toBe(row.row.record);
  });
});
