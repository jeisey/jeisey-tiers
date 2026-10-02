/**
 * The Start/Sit duel (ADR-096): who to start, how sure, and where the answer flips.
 *
 * The fixture week is built so every case the tab must get right is present: a steady back and
 * a boom-bust receiver with a flip point between them, CIN teammates with a measured
 * same-game correlation, a player ruled Out, and teams on bye.
 */

import { describe, expect, it } from "vitest";

import { InSeasonBundle } from "../src/data/ros";
import {
  flipSentence,
  injuryReading,
  readDuel,
  selectWeekBoard,
  toggleDuel,
} from "../src/data/duel";
import { DEFAULT_STATE, MAX_DUEL, parseState, serializeState } from "../src/data/state";
import {
  opportunityRecords,
  rosBuildMetadata,
  inSeasonPlayerStatusRecords,
  playerStatusRecords,
  rosTierRecords,
  weeklyProjectionRecords,
} from "./fixtures/artifacts";
import { required } from "./required";

const COOK = "gsis:00-0000011"; // steady RB, the higher median
const PUKA = "gsis:00-0000012"; // boom-bust WR, the wider range
const BURROW = "gsis:00-0000009"; // CIN QB
const SWIFT = "gsis:00-0000003"; // CIN WR
const KIRK = "gsis:00-0000017"; // Out on the week-9 report
const MARSH = "gsis:00-0000018"; // PHI, on bye
const BRIGHT = "gsis:00-0000002"; // Questionable

/**
 * The draft-time status records: everyone active except the fixture's Questionable, IR and
 * inactive players. `inSeason` swaps in the in-season shapes (ADR-101).
 */
function bundle(status: "draft" | "inSeason" = "draft"): InSeasonBundle {
  return new InSeasonBundle({
    metadata: rosBuildMetadata(),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(),
    opportunityDegradation: null,
    weekly: weeklyProjectionRecords(),
    status: status === "draft" ? playerStatusRecords() : inSeasonPlayerStatusRecords(),
  });
}

function duel(ids: readonly string[], margin = 0) {
  return readDuel(bundle(), { ...DEFAULT_STATE, duel: ids, margin });
}

describe("the verdict", () => {
  it("starts the steadier player when the reader is comfortably ahead", () => {
    const reading = duel([COOK, PUKA], 20);
    const verdict = required(reading.verdict, "reading.verdict");
    expect(verdict.pick.record.player_id).toBe(COOK);
    expect(verdict.edge).toBeGreaterThan(0.5);
    expect(verdict.postureChangedPick).toBe(false);
    expect(reading.sigma).toBeCloseTo((31.49 + 31.36) / 2, 9);
  });

  it("starts the higher mean, not the higher median, in an even matchup", () => {
    // Cook has the higher median and outscores Puka more often than not, but Puka's right
    // skew gives him the higher mean — and with a margin uncertainty of ~31 points the chance
    // to win the week is close to linear in points, so the mean is what it rewards. This is
    // the case a median ranking gets wrong, and the page has to say both halves.
    const verdict = required(duel([COOK, PUKA], 0).verdict, "the verdict at margin 0");
    expect(verdict.pick.record.player_id).toBe(PUKA);
    expect(verdict.medianLeader.record.player_id).toBe(COOK);
    expect(verdict.edge).toBeLessThan(0.5);
    expect(verdict.postureChangedPick).toBe(true);
    expect(required(verdict.pick.winProbability, "verdict.pick.winProbability")).toBeGreaterThan(required(verdict.runnerUp.winProbability, "verdict.runnerUp.winProbability"));
  });

  it("names the flip margin, and who is the better start past it", () => {
    const flip = required(required(duel([COOK, PUKA], 0).verdict, "the verdict at margin 0").flip, "the flip point at margin 0");
    expect(flip.margin).toBeGreaterThan(0);
    expect(flip.margin).toBeLessThan(20);
    expect(flip.side).toBe("ahead");
    expect(flip.beyond.record.player_id).toBe(COOK);
    expect(flipSentence(flip)).toMatch(
      /^If you are projected to win by more than [\d.]+ without this slot, start Jahmyr Cook — his floor protects the lead\.$/,
    );
    // From the other side of the flip the sentence points back at the ceiling.
    const fromAhead = required(required(duel([COOK, PUKA], 20).verdict, "the verdict at margin 20").flip, "the flip point at margin 20");
    expect(fromAhead.margin).toBeCloseTo(flip.margin, 6);
    expect(fromAhead.side).toBe("behind");
    expect(fromAhead.beyond.record.player_id).toBe(PUKA);
    expect(flipSentence(fromAhead)).toMatch(/you are projected to win by less than [\d.]+ .* start Puka Nightingale — you need his ceiling\.$/);
  });

  it("gives the same pick from either order in the URL", () => {
    for (const margin of [-20, 0, 20]) {
      const forward = required(duel([COOK, PUKA], margin).verdict, "duel([COOK, PUKA], margin).verdict");
      const backward = required(duel([PUKA, COOK], margin).verdict, "duel([PUKA, COOK], margin).verdict");
      expect(backward.pick.record.player_id).toBe(forward.pick.record.player_id);
      expect(backward.edge).toBe(forward.edge);
    }
  });
});

describe("who can be in the verdict", () => {
  it("lists a ruled-out player and a player on bye, and keeps both out of the verdict", () => {
    const reading = duel([COOK, KIRK, MARSH]);
    const byId = new Map(reading.contenders.map((contender) => [contender.record.player_id, contender]));
    expect(required(byId.get(KIRK), "byId.get(KIRK)").out).toBe(true);
    expect(required(byId.get(MARSH), "byId.get(MARSH)").bye).toBe(true);
    expect(reading.eligible.map((contender) => contender.record.player_id)).toEqual([COOK]);
    expect(reading.verdict).toBeNull();
  });

  it("keeps a player whose game has no posted line off the verdict, and calls it that", () => {
    const LANE = "gsis:00-0000010"; // WAS: no line posted for the week-9 game
    const reading = duel([COOK, LANE, PUKA]);
    const lane = required(
      reading.contenders.find((contender) => contender.record.player_id === LANE),
      "Jaylin Lane's contender",
    );
    expect(lane.pending).toBe(true);
    expect(lane.bye).toBe(false);
    expect(lane.eligible).toBe(false);
    expect(lane.record.game?.opponent).toBe("ARI");
    expect(reading.eligible.map((contender) => contender.record.player_id)).toEqual([COOK, PUKA]);
    expect(reading.verdict).not.toBeNull();
  });

  it("reports an id this build has no projection for", () => {
    const reading = duel([COOK, "gsis:00-9999999"]);
    expect(reading.missing).toEqual(["gsis:00-9999999"]);
    expect(reading.verdict).toBeNull();
  });
});

describe("the same game", () => {
  it("uses the measured teammate correlation, and says it was measured", () => {
    const verdict = required(duel([BURROW, SWIFT]).verdict, "duel([BURROW, SWIFT]).verdict");
    expect(verdict.correlation).toEqual({ rho: 0.3191, key: "teammates:QB-WR", measured: true });
  });

  it("treats players in different games as independent", () => {
    const verdict = required(duel([COOK, PUKA]).verdict, "duel([COOK, PUKA]).verdict");
    expect(verdict.correlation).toEqual({ rho: 0, key: null, measured: false });
  });
});

describe("three or four players", () => {
  it("gives each a chance to top the set, and the chances sum to one", () => {
    const reading = duel([COOK, PUKA, SWIFT, BRIGHT]);
    const tops = reading.eligible.map((contender) => required(contender.topOfSet, "contender.topOfSet"));
    expect(tops).toHaveLength(4);
    expect(tops.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 9);
    const matrix = required(reading.matrix, "reading.matrix");
    matrix.forEach((row, i) => {
      row.forEach((value, j) => {
        if (i === j) expect(value).toBeNull();
        else expect((value ?? 0) + (matrix[j]?.[i] ?? 0)).toBe(1);
      });
    });
  });

  it("refuses a fifth player and toggles one off", () => {
    let ids: readonly string[] = [];
    for (const id of [COOK, PUKA, SWIFT, BRIGHT, BURROW]) ids = toggleDuel(ids, id);
    expect(ids).toHaveLength(MAX_DUEL);
    expect(ids).not.toContain(BURROW);
    expect(toggleDuel(ids, PUKA)).toEqual([COOK, SWIFT, BRIGHT]);
  });
});

describe("the week board", () => {
  it("orders by ceiling when asked, leaves byes after the players, and sinks the sidelined", () => {
    const rows = selectWeekBoard(bundle(), DEFAULT_STATE, "ceiling");
    const sidelined = (row: (typeof rows)[number]): boolean =>
      row.availability.week === "out" || row.availability.week === "unavailable";
    const playing = rows.filter((row) => !sidelined(row));
    const ceilings = playing.map((row) => row.record.quantiles?.q90 ?? -Infinity);
    expect(ceilings).toEqual([...ceilings].sort((a, b) => b - a));
    expect(playing.at(-1)?.record.game_state).toBe("bye");
    // ADR-101: a player who cannot play this week is listed, labelled, and below every choice.
    const firstSidelined = rows.findIndex(sidelined);
    expect(firstSidelined).toBeGreaterThan(0);
    expect(rows.slice(firstSidelined).every(sidelined)).toBe(true);
    const kirk = required(rows.find((row) => row.record.player_id === KIRK), "Kirk on the board");
    expect(kirk.availability.short).toBe("OUT");
    expect(kirk.positionRank).toBeNull();
  });

  it("reads a startable probability against this league's threshold", () => {
    const cook = required(selectWeekBoard(bundle(), DEFAULT_STATE, "startable").find((row) => row.record.player_id === COOK), "selectWeekBoard(bundle(), DEFAULT_STATE, 'startable').fin...");
    expect(cook.threshold).toBe(9.88);
    expect(cook.startable).toBeGreaterThan(0.5);
    expect(cook.startable).toBeLessThan(1);
  });
});

describe("availability (ADR-101)", () => {
  const SEASON_OVER = "gsis:00-0000014";
  const OUT_SLEEPER_ONLY = "gsis:00-0000004";
  const DOUBTFUL_SLEEPER_ONLY = "gsis:00-0000015";

  function inSeasonDuel(ids: readonly string[]) {
    return readDuel(bundle("inSeason"), { ...DEFAULT_STATE, duel: ids, margin: 0 });
  }

  it("never lets a player whose season is over win, whatever his projection", () => {
    const reading = inSeasonDuel([SEASON_OVER, PUKA]);
    const over = required(reading.contenders.find((c) => c.record.player_id === SEASON_OVER), "contender");
    expect(over.eligible).toBe(false);
    expect(over.exclusion).toMatch(/Out for the season/);
    expect(reading.verdict).toBeNull();
    expect(reading.eligible.map((c) => c.record.player_id)).toEqual([PUKA]);
  });

  it("excludes a player ruled out by Sleeper before the official report lists him", () => {
    const reading = inSeasonDuel([OUT_SLEEPER_ONLY, COOK, PUKA]);
    expect(reading.eligible.map((c) => c.record.player_id).sort()).toEqual([COOK, PUKA].sort());
    expect(reading.verdict?.pick.record.player_id).not.toBe(OUT_SLEEPER_ONLY);
  });

  it("keeps a Doubtful player off the default verdict but leaves his numbers visible", () => {
    const reading = inSeasonDuel([DOUBTFUL_SLEEPER_ONLY, COOK]);
    const doubtful = required(reading.contenders.find((c) => c.record.player_id === DOUBTFUL_SLEEPER_ONLY), "contender");
    expect(doubtful.eligible).toBe(false);
    expect(doubtful.quantiles).not.toBeNull();
    expect(doubtful.exclusion).toMatch(/Doubtful/);
  });

  it("keeps a Questionable player comparable", () => {
    const reading = inSeasonDuel([BRIGHT, COOK]);
    expect(reading.verdict).not.toBeNull();
    expect(reading.eligible).toHaveLength(2);
  });

  it("leaves every published quantile untouched", () => {
    const reading = inSeasonDuel([SEASON_OVER, OUT_SLEEPER_ONLY, BRIGHT, COOK]);
    expect(reading.contenders).toHaveLength(4);
    for (const contender of reading.contenders) {
      const original = weeklyProjectionRecords().find(
        (r) => r.player_id === contender.record.player_id && r.scoring_preset === contender.record.scoring_preset,
      );
      expect(contender.record.quantiles).toEqual(original?.quantiles);
    }
  });
});

describe("the injury line", () => {
  it("pairs the designation with how often it has meant a missed game", () => {
    const record = required(weeklyProjectionRecords().find((row) => row.player_id === BRIGHT), "weeklyProjectionRecords().find((row) => row.player_id ===...");
    const reading = required(injuryReading(record, rosBuildMetadata().weekly), "injuryReading(record, rosBuildMetadata().weekly)");
    expect(reading.short).toBe("Q");
    expect(reading.sentence).toContain("have played 75% of the time (3,350 reports)");
    expect(reading.sentence).toContain("The projection assumes he plays.");
  });
});

describe("the URL", () => {
  it("round-trips the duel and the margin", () => {
    const parsed = parseState("?view=startsit&duel=00-0000011.00-0000012&margin=-12");
    expect(parsed.normalized).toBe(true);
    expect(parsed.state.duel).toEqual([COOK, PUKA]);
    expect(parsed.state.margin).toBe(-12);
    expect(serializeState(parsed.state)).toBe("?view=startsit&duel=00-0000011.00-0000012&margin=-12");
  });

  it("drops a malformed id, a duplicate, and a fifth player, and rewrites the URL", () => {
    const parsed = parseState(
      "?duel=00-0000011.nonsense.00-0000011.00-0000012.00-0000003.00-0000002.00-0000009",
    );
    expect(parsed.normalized).toBe(false);
    expect(parsed.state.duel).toEqual([COOK, PUKA, SWIFT, BRIGHT]);
  });

  it("refuses a margin outside the bound or not an integer", () => {
    for (const raw of ["41", "-41", "3.5", "ten", ""]) {
      const parsed = parseState(`?margin=${raw}`);
      expect(parsed.state.margin).toBe(0);
      expect(parsed.normalized).toBe(false);
    }
    expect(parseState("?margin=40").state.margin).toBe(40);
  });
});
