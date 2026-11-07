/**
 * A Skill Tree metric's cohort comparison (ADR-117).
 *
 * What a reader leans on, each tested on its own:
 *
 * * **nothing loads until asked** — opening the tree or a detail fetches no cohort; the
 *   detail's button does, once, and a second look draws from memory;
 * * **a response for another player or metric never renders** — a load that resolves after
 *   the reader moved on is dropped;
 * * **nothing is drawn across builds, windows, positions or metrics**, nor when the focal
 *   player's cohort row disagrees with his tree reading — each refusal says why;
 * * **pins** — up to three, the fourth refused; remove and clear; differences with sign, unit
 *   and the metric's own better direction; an unranked pin drawn apart from the ranking;
 * * **geometry** — equal values in one column, negative values, an all-equal cohort, never NaN;
 * * **keyboard and table** — every control by keyboard, every value in a table.
 *
 * Component tests use mocked sources over the in-season fixture (whose ranks are re-derived
 * per cohort, as a real build's are); one test runs the real store over the golden served
 * layout end to end.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SkillCompare from "../src/app/SkillCompare";
import SkillTree from "../src/app/SkillTree";
import type { PlayerSkillMetricRecord, Position, SkillTreeDefinitionRecord } from "../src/data/contracts";
import {
  MAX_PINS,
  checkCohort,
  compareUnit,
  difference,
  niceTicks,
  stackLevels,
  valueDomain,
  type CohortMember,
} from "../src/data/skillCompare";
import { buildSkillTreeView, type SkillReading } from "../src/data/skilltree";
import { parseManifest } from "../src/data/serving";
import { DataStore, type SkillCohortLoad, type SkillTreeLoad, type SkillTreeSource } from "../src/data/store";
import {
  seasonActualsRecords,
  skillTreeDefinitionRecords,
  skillTreeMetadata,
  skillTreeRecords,
} from "./fixtures/artifacts";
import { required } from "./required";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const COHORT_STATES = new Set(["ranked", "below_minimum", "small_cohort"]);

function definition(position: string, metric: string): SkillTreeDefinitionRecord {
  return required(
    skillTreeDefinitionRecords().find((row) => row.position === position && row.metric_id === metric),
    `${position}/${metric}`,
  );
}

const NAMES = new Map(seasonActualsRecords().map((record) => [record.player_id, record.display_name]));

function loadFor(playerId: string): SkillTreeLoad {
  const rows = skillTreeRecords().filter((row) => row.player_id === playerId);
  const position = rows[0]?.position ?? "WR";
  return {
    rows: rows as unknown as Record<string, unknown>[],
    definitions: skillTreeDefinitionRecords().filter((row) => row.position === position) as unknown as Record<
      string,
      unknown
    >[],
  };
}

/** The fixture's served cohort for one metric: every reading with a value, archive excluded. */
function cohortFor(position: string, metric: string): Record<string, unknown>[] {
  return skillTreeRecords()
    .filter((row) => row.position === position && row.metric_id === metric && COHORT_STATES.has(row.state))
    .map((row) => ({
      build_id: row.build_id,
      season: row.season,
      through_week: row.through_week,
      player_id: row.player_id,
      position: row.position,
      metric_id: row.metric_id,
      state: row.state,
      value: row.value,
      numerator: row.numerator,
      denominator: row.denominator,
      rank: row.rank,
      percentile: row.percentile,
      cohort_size: row.cohort_size,
      games: row.games,
    }));
}

/** A WR ranked on catch rate in a cohort that also has unranked receivers, and his rows. */
function rankedReceiver(): { readonly playerId: string; readonly name: string } {
  const rows = cohortFor("WR", "catch_rate");
  expect(rows.some((row) => row.state === "below_minimum")).toBe(true);
  const focal = required(
    rows.find((row) => row.state === "ranked" && NAMES.has(String(row.player_id))),
    "a ranked receiver",
  );
  const playerId = String(focal.player_id);
  return { playerId, name: required(NAMES.get(playerId), "his name") };
}

interface MockSource extends SkillTreeSource {
  readonly cohortCalls: string[];
}

function mockSource(
  options: {
    readonly hasCohorts?: boolean;
    readonly cohort?: (position: string, metric: string) => Promise<SkillCohortLoad | null>;
  } = {},
): MockSource {
  const cohortCalls: string[] = [];
  return {
    status: "published",
    meta: skillTreeMetadata(),
    cohortCalls,
    load: (playerId) => Promise.resolve(loadFor(playerId)),
    hasCohorts: () => options.hasCohorts ?? true,
    loadCohort: (position, metric) => {
      cohortCalls.push(`${position}.${metric}`);
      return (
        options.cohort?.(position, metric) ??
        Promise.resolve({ position, metricId: metric, rows: cohortFor(position, metric) })
      );
    },
    nameOf: (playerId) => NAMES.get(playerId) ?? null,
  };
}

async function openNode(label: RegExp): Promise<HTMLElement> {
  const group = await screen.findByRole("group", { name: /skill tree/ });
  await userEvent.setup().click(within(group).getByRole("button", { name: label }));
  return screen.getByRole("region", { name: /: details$/ });
}

async function openComparison(detail: HTMLElement): Promise<HTMLElement> {
  await userEvent.setup().click(within(detail).getByRole("button", { name: /^Compare with all \d+ ranked/ }));
  return within(detail).findByRole("region", { name: /compared across \d+ ranked/ }, { timeout: 5000 });
}

// --------------------------------------------------------------------------------- logic

describe("the comparison's logic", () => {
  it("names the unit a difference is read in", () => {
    expect(compareUnit(definition("RB", "yards_per_carry"))).toBe("yds/carry");
    expect(compareUnit(definition("QB", "pass_epa_per_dropback"))).toBe("EPA/dropback");
    expect(compareUnit(definition("RB", "rush_epa_per_carry"))).toBe("EPA/carry");
    expect(compareUnit(definition("WR", "adot"))).toBe("yds/target");
    expect(compareUnit(definition("RB", "rush_yards_over_expected_per_att"))).toBe("yds");
    expect(compareUnit(definition("QB", "interception_rate"))).toBe("pp");
    expect(compareUnit(definition("QB", "cpoe"))).toBe("pp");
    expect(compareUnit(definition("QB", "avg_time_to_throw"))).toBe("s");
    expect(compareUnit(definition("RB", "carries"))).toBe("carries");
    expect(compareUnit(definition("QB", "rushing_tds"))).toBe("rushing touchdowns");
    expect(compareUnit(definition("RB", "red_zone_carries"))).toBe("red-zone carries");
  });

  function member(value: number, overrides: Partial<CohortMember> = {}): CohortMember {
    return {
      playerId: `gsis:${String(value)}`,
      name: "Other",
      state: "ranked",
      value,
      numerator: null,
      denominator: null,
      rank: 1,
      percentile: 50,
      cohortSize: 10,
      games: 8,
      focal: false,
      ...overrides,
    };
  }

  it("states differences with sign, unit and the metric's own better direction", () => {
    const ypc = definition("RB", "yards_per_carry");
    expect(difference(member(4.74), member(4.32), ypc, "Pierce")).toEqual({
      text: "+0.42 yds/carry vs Pierce",
      side: "ahead",
      words: "ahead of Pierce; higher is better",
    });
    expect(difference(member(4.29), member(4.32), ypc, "Pierce")).toMatchObject({
      text: "-0.03 yds/carry vs Pierce",
      side: "behind",
    });
    // Lower is better: a smaller interception rate is ahead, phrased so.
    const ints = definition("QB", "interception_rate");
    expect(difference(member(0.021), member(0.03), ints, "Allen")).toEqual({
      text: "-0.90 pp vs Allen",
      side: "ahead",
      words: "ahead of Allen; lower is better",
    });
    expect(difference(member(0.035), member(0.03), ints, "Allen").side).toBe("behind");
    // A context metric has no better side.
    expect(difference(member(11.5), member(8.4), definition("WR", "adot"), "Nacua")).toEqual({
      text: "+3.10 yds/target vs Nacua",
      side: "undirected",
      words: "no better direction",
    });
    expect(difference(member(150), member(138), definition("RB", "carries"), "Pierce").text).toBe(
      "+12 carries vs Pierce",
    );
    expect(difference(member(0.107), member(-0.05), definition("QB", "pass_epa_per_dropback"), "Allen").text).toBe(
      "+0.157 EPA/dropback vs Allen",
    );
    // Equal at the published precision, whatever float residue says.
    expect(difference(member(0.1 + 0.2), member(0.3), ypc, "Pierce")).toMatchObject({ text: "Same as Pierce", side: "level" });
  });

  it("stacks equal values in one column, deterministically", () => {
    const values = [4.3, 4.3, 4.3, 4.9, 5.6];
    const members = values.map((value, index) => member(value, { playerId: `p${String(index)}` }));
    const x = (value: number): number => (value - 4) * 100;
    const levels = stackLevels(members, x, 8);
    expect([levels.get("p0"), levels.get("p1"), levels.get("p2")]).toEqual([0, 1, 2]);
    expect([levels.get("p3"), levels.get("p4")]).toEqual([0, 0]);
    // The same input, shuffled, stacks the same way: no randomness, no input-order effect.
    const again = stackLevels([...members].reverse(), x, 8);
    expect([...again.entries()].sort()).toEqual([...levels.entries()].sort());
  });

  it("gives every domain width: negative values, a single value, an all-equal cohort", () => {
    const epa = definition("RB", "rush_epa_per_carry");
    const [lo, hi] = valueDomain([-0.21, -0.04, 0.12], epa);
    expect(lo).toBe(-0.21);
    expect(hi).toBe(0.12);
    const ticks = niceTicks(lo, hi, 4);
    expect(ticks).toContain(0);
    expect(ticks.every((tick) => tick >= lo && tick <= hi && Number.isFinite(tick))).toBe(true);
    for (const values of [[0.05, 0.05, 0.05], [-0.1], []]) {
      const [min, max] = valueDomain(values, epa);
      expect(max - min).toBeGreaterThan(0);
      expect(Number.isFinite(min) && Number.isFinite(max)).toBe(true);
    }
    const [min, max] = valueDomain([7, 7, 7], definition("RB", "carries"));
    expect(min).toBeLessThan(7);
    expect(max).toBeGreaterThan(7);
  });

  it("refuses a cohort from another build, cutoff, position or metric, and a focal row that disagrees", () => {
    const { playerId } = rankedReceiver();
    const view = buildSkillTreeView(loadFor(playerId), skillTreeMetadata(), "WR");
    const focal = required(
      view.branches.flatMap((branch) => branch.nodes).find((node) => node.id === "catch_rate"),
      "catch rate",
    );
    const rows = cohortFor("WR", "catch_rate");
    const load = (changed: Record<string, unknown>[]): SkillCohortLoad => ({ position: "WR", metricId: "catch_rate", rows: changed });
    const nameOf = (id: string): string | null => NAMES.get(id) ?? null;
    expect(checkCohort(load(rows), focal, nameOf).status).toBe("ready");

    const other = (field: string, value: unknown): string => {
      const result = checkCohort(load(rows.map((row, index) => (index === 0 ? { ...row, [field]: value } : row))), focal, nameOf);
      return result.status === "refused" ? result.message : "drawn";
    };
    expect(other("build_id", "2026-11-05T00:00:00Z")).toMatch(/another build/);
    expect(other("through_week", 7)).toMatch(/another through week/);
    expect(other("position", "TE")).toMatch(/another position/);
    expect(other("metric_id", "targets")).toMatch(/another metric/);
    expect(checkCohort({ position: "WR", metricId: "targets", rows }, focal, nameOf).status).toBe("refused");

    const disagree = rows.map((row) => (row.player_id === playerId ? { ...row, value: Number(row.value) + 0.01 } : row));
    const refused = checkCohort(load(disagree), focal, nameOf);
    expect(refused.status).toBe("refused");
    expect(refused.status === "refused" ? refused.message : "").toMatch(/^His row in the cohort .* disagrees with his reading in the tree/);

    const shrunk = rows.filter((row) => row.player_id === playerId || row.state !== "ranked");
    expect(checkCohort(load(shrunk), focal, nameOf)).toMatchObject({ status: "refused" });
    const missing = rows.filter((row) => row.player_id !== playerId);
    expect(checkCohort(load(missing), focal, nameOf).status).toBe("refused");
  });
});

// ---------------------------------------------------------------------------- component

describe("the comparison in a node's detail", () => {
  it("loads nothing until its button is pressed, then the one cohort, and reuses it", async () => {
    const { playerId, name } = rankedReceiver();
    const source = mockSource();
    render(<SkillTree source={source} playerId={playerId} position="WR" name={name} />);
    const detail = await openNode(/^Catch rate:/);
    expect(source.cohortCalls).toEqual([]);
    const toggle = within(detail).getByRole("button", { name: /^Compare with all \d+ ranked WRs$/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const panel = await openComparison(detail);
    expect(source.cohortCalls).toEqual(["WR.catch_rate"]);
    expect(within(detail).getByRole("button", { name: "Hide comparison" }).getAttribute("aria-expanded")).toBe("true");
    const plot = within(panel).getByRole("img", { name: /^Dot plot of \d+ ranked WRs by catch rate/ });
    const ranked = cohortFor("WR", "catch_rate").filter((row) => row.state === "ranked");
    // One dot per ranked receiver but him; he is the diamond, with his name.
    expect(plot.querySelectorAll(".stc-dot")).toHaveLength(ranked.length - 1);
    expect(plot.querySelectorAll(".stc-focal-diamond")).toHaveLength(1);
    expect(within(plot).getByText(new RegExp(`◆ ${name}`))).toBeDefined();
    expect(plot.innerHTML).not.toContain("NaN");
    expect(within(panel).getByText(/^Ranked among wide receivers/)).toBeDefined();
    expect(within(panel).getByText(/higher is better/)).toBeDefined();

    // Hide and show again: drawn at once from memory, nothing asked of the store.
    await userEvent.setup().click(within(detail).getByRole("button", { name: "Hide comparison" }));
    expect(within(detail).queryByRole("region", { name: /compared across/ })).toBeNull();
    await userEvent.setup().click(within(detail).getByRole("button", { name: /^Compare with all/ }));
    expect(await within(detail).findByRole("region", { name: /compared across/ })).toBeDefined();
    expect(within(detail).queryByText(/^Loading every/)).toBeNull();
    expect(source.cohortCalls).toEqual(["WR.catch_rate"]);
  });

  it("drops a response that arrives after the reader switched player or metric", async () => {
    const receivers = cohortFor("WR", "targets").filter((row) => row.state === "ranked");
    const [first, second] = [String(receivers[0]?.player_id), String(receivers[1]?.player_id)];
    const pending: ((value: SkillCohortLoad) => void)[] = [];
    const source = mockSource({
      cohort: () =>
        new Promise((resolveLoad) => {
          pending.push(resolveLoad);
        }),
    });
    const { rerender } = render(<SkillTree source={source} playerId={first} position="WR" name="First" />);
    let detail = await openNode(/^Targets:/);
    await userEvent.setup().click(within(detail).getByRole("button", { name: /^Compare with all/ }));
    expect(await within(detail).findByText(/^Loading every WR/)).toBeDefined();

    // Another player: the comparison closes; the first player's late answer draws nothing.
    rerender(<SkillTree source={source} playerId={second} position="WR" name="Second" />);
    await screen.findByRole("group", { name: /skill tree/ });
    await act(async () => {
      pending[0]?.({ position: "WR", metricId: "targets", rows: cohortFor("WR", "targets") });
      await Promise.resolve();
    });
    expect(screen.queryByRole("region", { name: /compared across/ })).toBeNull();
    expect(screen.queryByText(/◆ First/)).toBeNull();

    // Another metric of the same player: likewise.
    detail = await openNode(/^Targets:/);
    await userEvent.setup().click(within(detail).getByRole("button", { name: /^Compare with all/ }));
    const other = await openNode(/^Receptions|^Receiving yards:/);
    await act(async () => {
      pending[1]?.({ position: "WR", metricId: "targets", rows: cohortFor("WR", "targets") });
      await Promise.resolve();
    });
    expect(within(other).queryByRole("region", { name: /compared across/ })).toBeNull();
    expect(within(other).getByRole("button", { name: /^Compare with all/ }).getAttribute("aria-expanded")).toBe("false");
  });

  it("pins up to three by keyboard, refuses a fourth, and removes and clears", async () => {
    const { playerId, name } = rankedReceiver();
    render(<SkillTree source={mockSource()} playerId={playerId} position="WR" name={name} />);
    const detail = await openNode(/^Targets:/);
    const user = userEvent.setup();
    const toggle = within(detail).getByRole("button", { name: /^Compare with all/ });
    toggle.focus();
    await user.keyboard("{Enter}");
    const panel = await within(detail).findByRole("region", { name: /compared across/ });
    const search = within(panel).getByRole("searchbox", { name: /Pin up to 3 WRs/ });
    const others = cohortFor("WR", "targets")
      .map((row) => String(row.player_id))
      .filter((id) => id !== playerId && NAMES.has(id));
    expect(others.length).toBeGreaterThanOrEqual(4);

    for (const id of others.slice(0, MAX_PINS)) {
      const other = required(NAMES.get(id), id);
      await user.click(search);
      await user.keyboard(other);
      const button = within(panel).getByRole("button", { name: `Pin ${other}` });
      button.focus();
      await user.keyboard("{Enter}");
      // Pinning clears the search and returns to it for the next one.
      expect(search).toHaveProperty("value", "");
      expect(document.activeElement).toBe(search);
    }
    const pins = within(panel).getByRole("list", { name: "Pinned players" });
    expect(within(pins).getAllByRole("listitem")).toHaveLength(3);
    expect(within(panel).getByText("3 players pinned: remove one to pin another.")).toBeDefined();
    // Each pin states value, sample, standing and its difference from him.
    for (const item of within(pins).getAllByRole("listitem")) {
      expect(item.textContent).toMatch(new RegExp(`(\\+|-)\\d[\\d,]* targets vs ${name}|Same as ${name}`));
      expect(item.textContent).toMatch(/pct · \d+(st|nd|rd|th) of \d+/);
    }

    // The fourth is refused: its pin button is disabled, and pressing it changes nothing.
    const fourth = required(NAMES.get(others[3] ?? ""), "a fourth");
    await user.click(search);
    await user.keyboard(fourth);
    const refused = within(panel).getByRole("button", { name: `Pin ${fourth}` });
    expect(refused).toHaveProperty("disabled", true);
    await user.click(refused);
    expect(within(pins).getAllByRole("listitem")).toHaveLength(3);

    // Remove one by keyboard, then clear the rest.
    const firstName = required(NAMES.get(others[0] ?? ""), "first pin");
    within(panel).getByRole("button", { name: `Remove ${firstName}` }).focus();
    await user.keyboard("{Enter}");
    expect(within(pins).getAllByRole("listitem")).toHaveLength(2);
    expect(within(pins).queryByText(firstName)).toBeNull();
    await user.click(within(panel).getByRole("button", { name: "Clear pins" }));
    expect(within(panel).queryByRole("list", { name: "Pinned players" })).toBeNull();
    // Pins never changed the ranking: the plot still draws every ranked receiver.
    const plot = within(panel).getByRole("img");
    const ranked = cohortFor("WR", "targets").filter((row) => row.state === "ranked");
    expect(plot.querySelectorAll(".stc-dot")).toHaveLength(ranked.length - 1);
  });

  it("draws a pinned unranked player apart from the ranking, labelled", async () => {
    const { playerId, name } = rankedReceiver();
    render(<SkillTree source={mockSource()} playerId={playerId} position="WR" name={name} />);
    const panel = await openComparison(await openNode(/^Catch rate:/));
    const unranked = required(
      cohortFor("WR", "catch_rate").find((row) => row.state === "below_minimum" && NAMES.has(String(row.player_id))),
      "an unranked receiver",
    );
    const other = required(NAMES.get(String(unranked.player_id)), "his name");
    await userEvent.setup().type(within(panel).getByRole("searchbox"), other);
    await userEvent.setup().click(within(panel).getByRole("button", { name: `Pin ${other}` }));
    const pin = within(within(panel).getByRole("list", { name: "Pinned players" })).getByRole("listitem");
    expect(within(pin).getByText("Unranked")).toBeDefined();
    expect(pin.textContent).toMatch(/Unranked · \d+ of \d+ targets/);
    const plot = within(panel).getByRole("img");
    expect(within(plot).getByText("Unranked (pinned, outside the ranking)")).toBeDefined();
    const mark = required(plot.querySelector('.stc-pin-mark[data-state="below_minimum"]'), "his mark");
    expect(mark.querySelector("rect")).not.toBeNull();
    expect(plot.querySelectorAll(".stc-dot")).toHaveLength(
      cohortFor("WR", "catch_rate").filter((row) => row.state === "ranked").length - 1,
    );
    expect(plot.getAttribute("aria-label")).toContain(`${other} `);
    expect(plot.getAttribute("aria-label")).toContain("(unranked)");
  });

  it("lists every row in a table, his row and the pins marked in words", async () => {
    const { playerId, name } = rankedReceiver();
    render(<SkillTree source={mockSource()} playerId={playerId} position="WR" name={name} />);
    const panel = await openComparison(await openNode(/^Catch rate:/));
    const rows = cohortFor("WR", "catch_rate");
    const toggle = within(panel).getByRole("button", { name: `Show all ${String(rows.length)} as a table` });
    toggle.focus();
    await userEvent.setup().keyboard("{Enter}");
    const region = within(panel).getByRole("region", { name: /as a table/ });
    expect(region.tabIndex).toBe(0);
    const table = within(region).getByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1);
    expect(bodyRows).toHaveLength(rows.length);
    const mine = required(bodyRows.find((row) => row.getAttribute("aria-current") === "true"), "his row");
    expect(mine.textContent).toContain(`(this card: ${name})`);
    expect(bodyRows.filter((row) => row.textContent.startsWith("Unranked"))).toHaveLength(
      rows.filter((row) => row.state !== "ranked").length,
    );
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Rank",
      "Player · sample",
      "Value (%)",
      "Pct",
    ]);
    // His sample rides under his name.
    expect(mine.textContent).toMatch(/\d+ of \d+ targets/);
  });

  it("refuses to draw a cohort from another build or one his row disagrees with", async () => {
    const { playerId, name } = rankedReceiver();
    const wrongBuild = mockSource({
      cohort: (position, metric) =>
        Promise.resolve({
          position,
          metricId: metric,
          rows: cohortFor(position, metric).map((row) => ({ ...row, build_id: "an-older-build" })),
        }),
    });
    render(<SkillTree source={wrongBuild} playerId={playerId} position="WR" name={name} />);
    let detail = await openNode(/^Catch rate:/);
    await userEvent.setup().click(within(detail).getByRole("button", { name: /^Compare with all/ }));
    expect(await within(detail).findByText(/No comparison drawn\./)).toBeDefined();
    expect(within(detail).getByRole("alert").textContent).toMatch(/another build .*Nothing is drawn/);
    expect(within(detail).queryByRole("img")).toBeNull();
    cleanup();

    const disagreeing = mockSource({
      cohort: (position, metric) =>
        Promise.resolve({
          position,
          metricId: metric,
          rows: cohortFor(position, metric).map((row) =>
            row.player_id === playerId ? { ...row, rank: Number(row.rank) + 1 } : row,
          ),
        }),
    });
    render(<SkillTree source={disagreeing} playerId={playerId} position="WR" name={name} />);
    detail = await openNode(/^Catch rate:/);
    await userEvent.setup().click(within(detail).getByRole("button", { name: /^Compare with all/ }));
    expect((await within(detail).findByRole("alert")).textContent).toMatch(/disagrees with his reading in the tree/);
    expect(within(detail).queryByRole("img")).toBeNull();
  });

  it("explains why the archive has no comparison, and never asks for one", async () => {
    const archived = required(
      skillTreeRecords().find((row) => row.metric_id === "combine_forty" && row.state === "ranked" && row.games > 0),
      "a ranked combine time",
    );
    const source = mockSource();
    render(<SkillTree source={source} playerId={archived.player_id} position={archived.position} name="Tested" />);
    await screen.findByRole("group", { name: /skill tree/ });
    const plaque = required(document.querySelector<HTMLElement>(".st-archive .st-node"), "the plaque");
    await userEvent.setup().click(plaque);
    const detail = screen.getByRole("region", { name: /: details$/ });
    expect(within(detail).getByText(/No comparison is drawn for the archive\./)).toBeDefined();
    expect(detail.textContent).toContain(`among the ${String(archived.cohort_size)} historical combine testers`);
    expect(detail.textContent).toMatch(/are not that cohort and are never put in its place/);
    expect(within(detail).queryByRole("button", { name: /^Compare/ })).toBeNull();
    expect(source.cohortCalls).toEqual([]);
  });

  it("says comparison is not available on a build that serves no cohorts, and the tree still works", async () => {
    const { playerId, name } = rankedReceiver();
    const old = mockSource({ hasCohorts: false });
    render(<SkillTree source={old} playerId={playerId} position="WR" name={name} />);
    const detail = await openNode(/^Catch rate:/);
    expect(
      within(detail).getByText("Comparison with the whole cohort is not available for this build: it publishes no cohort files."),
    ).toBeDefined();
    expect(within(detail).queryByRole("button", { name: /^Compare/ })).toBeNull();
    expect(within(detail).getByText("Limitations")).toBeDefined();
    cleanup();

    const absent = mockSource({ cohort: () => Promise.resolve(null) });
    render(<SkillTree source={absent} playerId={playerId} position="WR" name={name} />);
    const again = await openNode(/^Catch rate:/);
    await userEvent.setup().click(within(again).getByRole("button", { name: /^Compare with all/ }));
    expect(
      await within(again).findByText("Comparison is not available for this build: it serves no cohort for catch rate."),
    ).toBeDefined();
    cleanup();

    const failing = mockSource({ cohort: () => Promise.reject(new Error("HTTP 503")) });
    render(<SkillTree source={failing} playerId={playerId} position="WR" name={name} />);
    const third = await openNode(/^Catch rate:/);
    await userEvent.setup().click(within(third).getByRole("button", { name: /^Compare with all/ }));
    expect((await within(third).findByRole("alert")).textContent).toBe(
      "The comparison could not be loaded (HTTP 503). The tree is unaffected.",
    );
  });

  it("offers nothing for an unranked reading", async () => {
    const below = required(
      skillTreeRecords().find((row) => row.state === "below_minimum" && row.position === "WR"),
      "a below-minimum reading",
    );
    const label = definition("WR", below.metric_id).label;
    const source = mockSource();
    render(<SkillTree source={source} playerId={below.player_id} position="WR" name="Sparse" />);
    const group = await screen.findByRole("group", { name: /skill tree/ });
    const node = within(group).queryByRole("button", { name: new RegExp(`^${label}:`) });
    if (node === null) return; // a detail metric: no node of its own to open
    await userEvent.setup().click(node);
    const detail = screen.getByRole("region", { name: /: details$/ });
    expect(within(detail).queryByRole("button", { name: /^Compare/ })).toBeNull();
    expect(source.cohortCalls).toEqual([]);
  });
});

// ----------------------------------------------------------------------- crafted cohorts

describe("crafted cohorts", () => {
  /** A focal reading of `metric` for a WR, ranked as `focalRow` says, and a source serving `rows`. */
  function crafted(
    metric: string,
    values: readonly number[],
  ): { readonly focal: SkillReading; readonly source: MockSource } {
    const position: Position = metric === "rush_epa_per_carry" ? "RB" : "WR";
    const def = definition(position, metric);
    const base = skillTreeRecords().find((row) => row.position === position && row.metric_id === metric);
    const template = required(base, metric);
    const n = values.length;
    const adjusted = values.map((value) => (def.direction === "lower" ? -value : value));
    const rows = values.map((value, index) => {
      const mine = adjusted[index] ?? 0;
      const behind = adjusted.filter((other) => other < mine).length;
      const ahead = adjusted.filter((other) => other > mine).length;
      return {
        ...template,
        player_id: `gsis:craft-${String(index)}`,
        state: "ranked",
        value,
        rank: ahead + 1,
        percentile: Math.round((1000 * (behind + (n - behind - ahead - 1) / 2)) / (n - 1)) / 10,
        cohort_size: n,
      } satisfies PlayerSkillMetricRecord;
    });
    const focalRow = required(rows[0], "focal row");
    const view = buildSkillTreeView(
      {
        rows: [focalRow],
        definitions: skillTreeDefinitionRecords().filter((row) => row.position === position) as unknown as Record<
          string,
          unknown
        >[],
      },
      skillTreeMetadata(),
      position,
    );
    const focal = required(
      view.branches.flatMap((branch) => branch.nodes.flatMap((node) => [node, ...node.details])).find((node) => node.id === metric),
      "focal",
    );
    const source = mockSource({
      cohort: () => Promise.resolve({ position, metricId: metric, rows }),
    });
    return { focal, source };
  }

  it("draws equal values in one column, negative values and an all-equal cohort without NaN", async () => {
    for (const [metric, values] of [
      ["targets", [40, 40, 40, 40, 55, 61]],
      ["rush_epa_per_carry", [-0.21, -0.18, -0.04, 0, 0.12]],
      ["catch_rate", [0.65, 0.65, 0.65, 0.65, 0.65]],
    ] as const) {
      const { focal, source } = crafted(metric, values);
      render(<SkillCompare source={source} focal={focal} position={focal.definition.position} name="Focal" />);
      const plot = await screen.findByRole("img", { name: /^Dot plot/ });
      expect(plot.innerHTML, metric).not.toContain("NaN");
      const dots = [...plot.querySelectorAll(".stc-dot")];
      expect(dots).toHaveLength(values.length - 1);
      const diamond = required(plot.querySelector(".stc-focal-diamond"), "diamond");
      expect(diamond.getAttribute("d")).not.toContain("NaN");
      if (metric === "targets") {
        // Three other 40s share his column, each one level higher than the last.
        const cx = required(diamond.getAttribute("d")?.match(/^M ([\d.]+)/)?.[1], "his x");
        const column = dots.filter((dot) => dot.getAttribute("cx") === cx);
        expect(column.length).toBe(3);
        expect(new Set(column.map((dot) => dot.getAttribute("cy"))).size).toBe(3);
      }
      if (metric === "rush_epa_per_carry") {
        expect(plot.querySelector(".stc-zero")).not.toBeNull();
        expect(within(plot).getAllByText(/^[+-]?0\.\d+$|^0\.0+$/).length).toBeGreaterThan(0);
      }
      if (metric === "catch_rate") {
        // Every dot in one column, the axis around the one value.
        expect(new Set(dots.map((dot) => dot.getAttribute("cx"))).size).toBe(1);
      }
      cleanup();
    }
  });
});

// ------------------------------------------------------------- the golden served layout

describe("on the golden served layout (ADR-117)", () => {
  const GOLDEN_DIR = resolve(__dirname, "../../tests/fixtures/artifacts");
  const read = (path: string): string => readFileSync(resolve(GOLDEN_DIR, path), "utf-8");

  beforeEach(() => {
    vi.stubGlobal("caches", undefined);
  });

  it("fetches the index and the one slice on activation, and draws the whole ranked cohort", async () => {
    const paths: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const path = new URL(String(input), "http://localhost/").pathname;
        paths.push(path);
        try {
          return Promise.resolve(new Response(read(path.replace(/^.*\/data\//, "")), { status: 200 }));
        } catch {
          return Promise.resolve(new Response(null, { status: 404 }));
        }
      }),
    );
    const store = new DataStore(parseManifest(JSON.parse(read("manifest.json")) as unknown));
    await store.ensure(["players"]);
    const source = required(store.skillTreeSource(), "the golden tree");
    const indexHash = required(store.manifest.files["skill_cohort_index/RB"], "the RB index");
    const index = JSON.parse(read(`serve/skill_cohort_index/RB.${indexHash}.json`)) as { files: Record<string, string> };
    const sliceHash = required(index.files["RB.yards_per_carry"], "the slice's hash");
    const slice = JSON.parse(read(`serve/skill_cohort/RB.yards_per_carry.${sliceHash}.json`)) as {
      columns: { player_id: string[]; state: string[] };
    };
    const focalIndex = slice.columns.state.indexOf("ranked");
    const playerId = required(slice.columns.player_id[focalIndex], "a ranked back");
    const name = source.nameOf(playerId) ?? "Golden Back";

    render(<SkillTree source={source} playerId={playerId} position="RB" name={name} />);
    const detail = await openNode(/^Yards per carry:/);
    const before = paths.length;
    const panel = await openComparison(detail);
    const fetched = paths.slice(before).filter((path) => path.includes("/serve/"));
    expect(fetched.filter((path) => path.includes("/skill_cohort_index/RB."))).toHaveLength(1);
    expect(fetched.filter((path) => path.includes("/skill_cohort/RB.yards_per_carry."))).toHaveLength(1);
    expect(fetched).toHaveLength(2);
    const ranked = slice.columns.state.filter((state) => state === "ranked").length;
    expect(within(panel).getByRole("img").querySelectorAll(".stc-dot")).toHaveLength(ranked - 1);
    expect(within(panel).getByText(String(ranked))).toBeDefined();
    await waitFor(() => {
      expect(within(panel).queryByRole("alert")).toBeNull();
    });
  });
});
