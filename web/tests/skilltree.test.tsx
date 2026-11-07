/**
 * The Skill Tree on the player card (ADR-107).
 *
 * What a reader leans on, each tested on its own:
 *
 * * **every word comes from the artifact** — labels, definitions, samples, ranks — and the view
 *   model only formats and orders them;
 * * **states are never merged**: a reading below its minimum prints its value and no rank, no
 *   opportunity prints no value, a source that does not cover him says so in words, and a
 *   player with no games has no tree to draw;
 * * **the meter repeats the words**: five segments from the published percentile, a marker
 *   (never a fill) for a context metric;
 * * **opening a card fetches nothing** — the tree loads on the section's button (desktop) or
 *   its tab (phone), and stays open for the next player in the same dialog;
 * * **every node works by keyboard**: arrows move, Enter opens, Close returns focus.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import SkillTree, { columnsFor } from "../src/app/SkillTree";
import type { SkillTreeDefinitionRecord } from "../src/data/contracts";
import {
  BAND_WORDS,
  METER_TICKS,
  buildSkillTreeView,
  formatSkillValue,
  meterTicks,
  nodeName,
  nodeOrder,
  percentileBand,
  type SkillReading,
} from "../src/data/skilltree";
import type { SkillTreeLoad, SkillTreeSource } from "../src/data/store";
import {
  FIXTURE_GENERATED_AT,
  FIXTURE_SKILL_TREE_ZERO_ID,
  fixtureFiles,
  inSeasonFixtureFiles,
  rosTierRecords,
  skillTreeDefinitionRecords,
  skillTreeMetadata,
  skillTreeRecords,
} from "./fixtures/artifacts";
import { required } from "./required";
import { setMediaQuery } from "./setup";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function definition(position: string, metric: string): SkillTreeDefinitionRecord {
  return required(
    skillTreeDefinitionRecords().find((row) => row.position === position && row.metric_id === metric),
    `${position}/${metric}`,
  );
}

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

/** ADR-117's comparison members for a source that serves no cohorts (an older build). */
const NO_COHORTS = {
  hasCohorts: () => false,
  loadCohort: () => Promise.resolve(null),
  nameOf: () => null,
} as const;

function sourceFor(load: (playerId: string) => SkillTreeLoad): SkillTreeSource & { readonly calls: string[] } {
  const calls: string[] = [];
  return {
    status: "published",
    meta: skillTreeMetadata(),
    calls,
    load: (playerId) => {
      calls.push(playerId);
      return Promise.resolve(load(playerId));
    },
    ...NO_COHORTS,
  };
}

/** A fixture player at `position` with games, and his id. */
function playerAt(position: string): string {
  const row = skillTreeRecords().find(
    (record) => record.position === position && record.metric_id === "appearances" && record.games > 0,
  );
  return required(row, `a ${position} with games`).player_id;
}

// ------------------------------------------------------------------------ firewall

describe("the firewall (ADR-107)", () => {
  const SRC = resolve(__dirname, "../src");
  function sources(directory: string): string[] {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) return sources(path);
      return /\.(ts|tsx)$/.test(entry.name) ? [path] : [];
    });
  }
  const files = sources(SRC).map((path) => ({
    name: relative(SRC, path).split("\\").join("/"),
    text: readFileSync(path, "utf-8"),
  }));

  it("keeps every model, board and decision module away from the tree", () => {
    // The card's wiring and the tree itself; nothing else may so much as name it.
    const allowed = new Set([
      "app/App.tsx",
      "app/PlayerDetail.tsx",
      "app/SkillTree.tsx",
      "app/SkillCompare.tsx",
      "app/skillTreeGlyphs.tsx",
      "data/contracts.ts",
      "data/skilltree.ts",
      "data/skillCompare.ts",
      "data/store.ts",
    ]);
    const naming = files
      .filter((file) => !allowed.has(file.name) && /skill.?tree/i.test(file.text))
      .map((file) => file.name);
    expect(naming).toEqual([]);
    expect(files.length).toBeGreaterThan(40);
  });

  it("loads the tree's code only through the card's lazy import", () => {
    const statics = files.filter((file) => /import[^;]*from\s+["'](\.\.?\/)*(app\/)?SkillTree["']/.test(file.text));
    expect(statics.map((file) => file.name)).toEqual([]);
    const detail = files.find((file) => file.name === "app/PlayerDetail.tsx");
    expect(detail?.text).toContain('lazy(() => import("./SkillTree"))');
    // The view model rides the tree's chunk; the comparison's own chunk and its logic read it.
    const viewModel = files.filter((file) => /from\s+["'][./]*(data\/)?skilltree["']/.test(file.text));
    expect(viewModel.map((file) => file.name).sort()).toEqual([
      "app/SkillCompare.tsx",
      "app/SkillTree.tsx",
      "data/skillCompare.ts",
    ]);
  });

  it("loads the comparison's code only through the tree's own lazy import (ADR-117)", () => {
    const statics = files.filter((file) => /import[^;]*from\s+["'](\.\.?\/)*(app\/)?SkillCompare["']/.test(file.text));
    expect(statics.map((file) => file.name)).toEqual([]);
    const tree = files.find((file) => file.name === "app/SkillTree.tsx");
    expect(tree?.text).toContain('lazy(() => import("./SkillCompare"))');
    const logic = files.filter((file) => /from\s+["'][./]*(data\/)?skillCompare["']/.test(file.text));
    expect(logic.map((file) => file.name)).toEqual(["app/SkillCompare.tsx"]);
  });
});

// ------------------------------------------------------------------------ view model

describe("the view model", () => {
  it("draws every position's tree in the definitions' order, with details under nodes", () => {
    const counts: Record<string, number> = {};
    for (const position of ["QB", "RB", "WR", "TE"] as const) {
      const view = buildSkillTreeView(loadFor(playerAt(position)), skillTreeMetadata(), position);
      expect(view.branches).toHaveLength(4);
      counts[position] = nodeOrder(view).length;
      // A detail never appears as a node of its own.
      const details = view.branches.flatMap((branch) => branch.nodes.flatMap((node) => node.details));
      for (const detail of details) expect(nodeOrder(view)).not.toContain(detail.id);
    }
    expect(counts).toEqual({ QB: 13, RB: 13, WR: 14, TE: 13 });
    const wr = buildSkillTreeView(loadFor(playerAt("WR")), skillTreeMetadata(), "WR");
    const te = buildSkillTreeView(loadFor(playerAt("TE")), skillTreeMetadata(), "TE");
    expect(wr.branches.map((branch) => branch.label)).not.toEqual(te.branches.map((branch) => branch.label));
  });

  it("formats values without changing them", () => {
    expect(formatSkillValue(0.6512, definition("WR", "catch_rate"))).toBe("65.1%");
    expect(formatSkillValue(1.85, definition("QB", "cpoe"))).toBe("+1.9");
    expect(formatSkillValue(-0.0228, definition("QB", "pass_epa_per_dropback"))).toBe("-0.02");
    expect(formatSkillValue(1572, definition("QB", "passing_yards"))).toBe("1,572");
    expect(formatSkillValue(0.52, definition("RB", "rush_yards_over_expected_per_att"))).toBe("+0.52");
    expect(formatSkillValue(11.68, definition("WR", "adot"))).toBe("11.7");
    expect(formatSkillValue(null, definition("WR", "adot"))).toBe("—");
  });

  it("keeps the states apart, in words", () => {
    const zero = buildSkillTreeView(loadFor(FIXTURE_SKILL_TREE_ZERO_ID), skillTreeMetadata(), "TE");
    const nodes = new Map(zero.branches.flatMap((branch) => branch.nodes.map((node) => [node.id, node])));
    const catchRate = required(nodes.get("catch_rate"), "catch rate");
    expect(catchRate.state).toBe("no_opportunity");
    expect(catchRate.valueText).toBe("—");
    expect(catchRate.empty).toBe(true);
    expect(catchRate.standingText).toBe("No targets yet");
    // His targets are a real zero-opportunity count, still a ranked volume.
    expect(required(nodes.get("targets"), "targets").state).toBe("ranked");

    const below = skillTreeRecords().find((row) => row.state === "below_minimum");
    const owner = required(below, "a below-minimum reading");
    const view = buildSkillTreeView(loadFor(owner.player_id), skillTreeMetadata(), owner.position);
    const reading = required(
      [...view.branches.flatMap((branch) => branch.nodes.flatMap((node) => [node, ...node.details]))].find(
        (node) => node.id === owner.metric_id,
      ),
      "the reading",
    );
    expect(reading.valueText).not.toBe("—");
    expect(reading.standingText).toMatch(/^Unranked · \d+ of \d+ /);
    expect(reading.ticks).toBe(0);
    expect(reading.meter).toBe("none");
    expect(reading.band).toBeNull();

    const uncovered = skillTreeRecords().find((row) => row.reason === "not_in_ngs_summary");
    const covered = required(uncovered, "an NGS reading not covered");
    const ngsView = buildSkillTreeView(loadFor(covered.player_id), skillTreeMetadata(), covered.position);
    const ngs = ngsView.branches.flatMap((branch) => branch.nodes).find((node) => node.id === covered.metric_id);
    if (ngs !== undefined) {
      expect(ngs.standingText).toBe("Not in Next Gen Stats");
      expect(ngs.empty).toBe(true);
    }
  });

  it("lights ten ticks by one shared rule: none at 0, then ceil(p / 10)", () => {
    expect(METER_TICKS).toBe(10);
    const cases: readonly (readonly [number, number])[] = [
      [0, 0],
      [0.1, 1],
      [5, 1],
      [10, 1],
      [10.1, 2],
      [19.9, 2],
      [20, 2],
      [20.1, 3],
      [50, 5],
      [55.6, 6],
      [89.9, 9],
      [90, 9],
      [90.1, 10],
      [99.9, 10],
      [100, 10],
    ];
    for (const [percentile, ticks] of cases) expect(meterTicks(percentile), `p=${String(percentile)}`).toBe(ticks);
    // Read at the published precision: float residue never lights another tick.
    expect(meterTicks(20.000000001)).toBe(2);
    expect(meterTicks(30.000000000004)).toBe(3);
    // Nothing outside 0-100 or non-finite lights anything it should not.
    expect(meterTicks(-1)).toBe(0);
    expect(meterTicks(Number.NaN)).toBe(0);
    expect(meterTicks(140)).toBe(10);
  });

  it("bands a percentile at explicit inclusive lower bounds 20, 40, 60, 80", () => {
    const cases: readonly (readonly [number, number])[] = [
      [0, 1],
      [19.9, 1],
      [20, 2],
      [39.9, 2],
      [40, 3],
      [59.9, 3],
      [60, 4],
      [79.9, 4],
      [80, 5],
      [100, 5],
    ];
    for (const [percentile, band] of cases) expect(percentileBand(percentile), `p=${String(percentile)}`).toBe(band);
    expect(Object.values(BAND_WORDS)).toEqual(["below 20", "20 to under 40", "40 to under 60", "60 to under 80", "80 to 100"]);
  });

  /** One WR reading set to `fields`, read back as its node (or detail) in the view. */
  function readingWith(metric: string, fields: Record<string, unknown>, position = "WR"): SkillReading {
    const base = loadFor(playerAt(position));
    const rows = base.rows.map((row) => (row.metric_id === metric ? { ...row, ...fields } : row));
    const view = buildSkillTreeView({ ...base, rows }, skillTreeMetadata(), position as "WR");
    const all = [
      ...view.branches.flatMap((branch) => branch.nodes.flatMap((node) => [node, ...node.details])),
      ...(view.archive === null ? [] : [view.archive]),
      ...(view.presence === null ? [] : [view.presence]),
    ];
    return required(all.find((candidate) => candidate.id === metric), metric);
  }

  it("tints a ranked higher/lower reading by band and prints its exact percentile", () => {
    const ranked = (percentile: number): SkillReading =>
      readingWith("catch_rate", { state: "ranked", percentile, rank: 5, cohort_size: 10 });
    const middle = ranked(55.6);
    expect([middle.meter, middle.ticks, middle.band]).toEqual(["ticks", 6, 3]);
    expect(middle.standingText).toBe("55.6 pct · 5th of 10");
    expect(middle.meterText).toBe("6 of 10 ticks, band 40 to under 60");
    const top = ranked(80);
    expect([top.ticks, top.band, top.standingText]).toEqual([8, 5, "80th pct · 5th of 10"]);
    const bottom = ranked(1.5);
    expect([bottom.ticks, bottom.band, bottom.standingText]).toEqual([1, 1, "1.5 pct · 5th of 10"]);

    // A lower-is-better metric's percentile is already direction-adjusted: 90 is near the best,
    // nine ticks and the top band, never inverted a second time.
    const interceptions = readingWith(
      "interception_rate",
      { state: "ranked", percentile: 90, rank: 1, cohort_size: 10 },
      "QB",
    );
    expect(interceptions.definition.direction).toBe("lower");
    expect([interceptions.ticks, interceptions.band]).toEqual([9, 5]);
  });

  it("marks a context metric on a neutral track, never banded", () => {
    const adot = readingWith("adot", { state: "ranked", percentile: 72, rank: 3, cohort_size: 10 });
    expect([adot.meter, adot.marker, adot.band, adot.ticks]).toEqual(["marker", 72, null, 0]);
    expect(adot.standingText).toBe("above 72% · 3rd of 10");
    expect(adot.meterText).toBe("a position marker, not a grade");
  });

  it("keeps presence and the archive in their own meaning", () => {
    const presence = readingWith("appearances", { state: "ranked", percentile: 50, rank: 4, cohort_size: 9 });
    expect([presence.meter, presence.band, presence.ticks]).toEqual(["none", null, 0]);
    expect(presence.standingText).toBe("4th of 9 WRs by games");
    const archive = readingWith("combine_forty", {
      state: "ranked",
      value: 4.41,
      percentile: 73.2,
      rank: 190,
      cohort_size: 710,
      source_season: 2021,
      reason: null,
    });
    // Ticks by the same rule, but untinted: historical testers are not a current grade.
    expect([archive.meter, archive.ticks, archive.band]).toEqual(["ticks", 8, null]);
    expect(archive.meterText).toBe("8 of 10 ticks among historical testers");
  });

  it("draws no rank for any unranked or missing state", () => {
    const states: readonly Record<string, unknown>[] = [
      { state: "below_minimum", rank: null, percentile: null, cohort_size: null, denominator: 4 },
      { state: "small_cohort", rank: null, percentile: null, cohort_size: 4 },
      { state: "no_opportunity", value: null, rank: null, percentile: null, cohort_size: null },
      { state: "not_covered", value: null, rank: null, percentile: null, cohort_size: null, reason: "not_in_ngs_summary" },
      { state: "unavailable", value: null, rank: null, percentile: null, cohort_size: null, reason: "no_snap_rows" },
    ];
    for (const fields of states) {
      const reading = readingWith("catch_rate", fields);
      expect([reading.meter, reading.ticks, reading.band, reading.meterText], String(fields.state)).toEqual([
        "none",
        0,
        null,
        "",
      ]);
    }
    expect(readingWith("catch_rate", states[1] ?? {}).standingText).toBe("Unranked · 4 qualified WRs");
  });

  it("tells a ranked zero from a missing reading in words, in the meter and in the name", () => {
    const zero = readingWith("catch_rate", { state: "ranked", percentile: 0, rank: 66, cohort_size: 66 });
    expect(zero.empty).toBe(false);
    expect(zero.valueText).not.toBe("—");
    expect([zero.meter, zero.ticks, zero.band]).toEqual(["ticks", 0, 1]);
    expect(zero.standingText).toBe("0 pct · 66th of 66");
    expect(nodeName(zero)).toContain("0 pct · 66th of 66. Meter: 0 of 10 ticks, band below 20.");

    const base = loadFor(playerAt("WR"));
    const view = buildSkillTreeView(
      { ...base, rows: base.rows.filter((row) => row.metric_id !== "catch_rate") },
      skillTreeMetadata(),
      "WR",
    );
    const missing = required(
      view.branches.flatMap((branch) => branch.nodes).find((node) => node.id === "catch_rate"),
      "catch_rate",
    );
    expect([missing.state, missing.empty, missing.meter, missing.valueText]).toEqual(["missing", true, "none", "—"]);
    expect(nodeName(missing)).toBe("Catch rate. No reading in this build.");
    expect(nodeName(missing)).not.toContain("Meter");
  });

  it("names every node by label, value and standing", () => {
    const view = buildSkillTreeView(loadFor(playerAt("QB")), skillTreeMetadata(), "QB");
    const node = required(view.branches[0]?.nodes[0], "first node");
    expect(nodeName(node)).toContain("Pass attempts");
    expect(nodeName(node)).toContain(node.standingText);
  });

  it("chooses columns from the pane's width, never a scaled drawing", () => {
    expect(columnsFor(720)).toBe(4);
    expect(columnsFor(500)).toBe(2);
    expect(columnsFor(320)).toBe(1);
  });
});

// ------------------------------------------------------------------------- component

describe("the Skill Tree component", () => {
  it("opens a node's detail inline and returns focus when it closes", async () => {
    const playerId = playerAt("RB");
    const source = sourceFor(loadFor);
    render(<SkillTree source={source} playerId={playerId} position="RB" name="Test Back" />);
    const group = await screen.findByRole("group", { name: /skill tree/ });
    const buttons = within(group).getAllByRole("button");
    expect(buttons).toHaveLength(13);
    const first = required(buttons[0], "first node");
    expect(first.getAttribute("aria-expanded")).toBe("false");
    await userEvent.setup().click(first);
    expect(first.getAttribute("aria-expanded")).toBe("true");
    const region = screen.getByRole("region", { name: /Carries: details/ });
    expect(within(region).getByText(/Official rush attempts/)).toBeDefined();
    expect(within(region).getByText("Limitations")).toBeDefined();
    // Detail metrics carry their own readings.
    expect(within(region).getByRole("list", { name: /More on Carries/ })).toBeDefined();
    await userEvent.setup().click(within(region).getByRole("button", { name: /Close/ }));
    expect(screen.queryByRole("region", { name: /Carries: details/ })).toBeNull();
    expect(document.activeElement).toBe(first);
  });

  it("draws a ranked zero as a solid empty meter in its band, and a missing reading as dashed", async () => {
    const playerId = playerAt("WR");
    const source = sourceFor((id) => {
      const load = loadFor(id);
      return {
        ...load,
        rows: load.rows
          .filter((row) => row.metric_id !== "yards_per_reception")
          .map((row) =>
            row.metric_id === "catch_rate" ? { ...row, state: "ranked", percentile: 0, rank: 66, cohort_size: 66 } : row,
          ),
      };
    });
    render(<SkillTree source={source} playerId={playerId} position="WR" name="Test Receiver" />);
    const group = await screen.findByRole("group", { name: /skill tree/ });
    const zero = within(group).getByRole("button", { name: /^Catch rate: .*0 pct · 66th of 66\. Meter: 0 of 10 ticks/ });
    expect(zero.dataset.empty).toBeUndefined();
    expect(zero.dataset.band).toBe("1");
    expect(zero.dataset.meter).toBe("ticks");
    const zeroMeter = required(zero.querySelector<HTMLElement>(".st-meter"), "meter");
    expect(zeroMeter.dataset.variant).toBe("fill");
    expect(zeroMeter.dataset.ticks).toBe("0");
    expect(zeroMeter.querySelectorAll(".st-seg")).toHaveLength(10);
    expect(zeroMeter.querySelectorAll(".st-seg[data-on]")).toHaveLength(0);

    const missing = within(group).getByRole("button", { name: /^Yards per reception\. No reading in this build\.$/ });
    expect(missing.dataset.empty).toBe("true");
    expect(missing.dataset.band).toBeUndefined();
    expect(required(missing.querySelector<HTMLElement>(".st-meter"), "meter").dataset.variant).toBe("empty");
    expect(within(missing).getByText("—")).toBeDefined();

    // Every ranked higher/lower node lights ceil(p / 10) of ten ticks in its band.
    for (const node of within(group).getAllByRole("button")) {
      if (node.dataset.meter !== "ticks" || node === zero) continue;
      const meter = required(node.querySelector<HTMLElement>(".st-meter"), "meter");
      expect(meter.querySelectorAll(".st-seg")).toHaveLength(10);
      expect(meter.querySelectorAll(".st-seg[data-on]")).toHaveLength(Number(meter.dataset.ticks));
      expect(node.dataset.band).toMatch(/^[1-5]$/);
    }
  });

  it("states the tick rule and the bands in the legend", async () => {
    const source = sourceFor(loadFor);
    render(<SkillTree source={source} playerId={playerAt("QB")} position="QB" name="Test Passer" />);
    await screen.findByRole("group", { name: /skill tree/ });
    const legend = required(document.querySelector<HTMLElement>(".st-legend"), "legend");
    expect(legend.textContent).toContain("ten ticks, one per 10 points, rounded up");
    expect(legend.textContent).toContain("0 lights none, 0.1–10 lights one, 90.1–100 all ten");
    expect(legend.textContent).not.toContain("20 points");
    expect([...legend.querySelectorAll(".st-band-key-item")].map((item) => item.textContent)).toEqual([
      "<20",
      "20–39.9",
      "40–59.9",
      "60–79.9",
      "80–100",
    ]);
    expect(legend.querySelectorAll(".st-legend-meter span")).toHaveLength(10);
  });

  it("moves between nodes with the arrow keys (a single tab stop)", async () => {
    const source = sourceFor(loadFor);
    render(<SkillTree source={source} playerId={playerAt("WR")} position="WR" name="Test Receiver" />);
    const group = await screen.findByRole("group", { name: /skill tree/ });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.filter((button) => button.tabIndex === 0)).toHaveLength(1);
    const first = required(buttons[0], "first");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(document.activeElement).toBe(buttons[1]);
    fireEvent.keyDown(required(buttons[1], "second"), { key: "ArrowRight" });
    // The second branch's second node.
    const secondBranch = within(group).getAllByRole("list")[1];
    expect(document.activeElement).toBe(within(required(secondBranch, "branch")).getAllByRole("button")[1]);
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "End" });
    expect(document.activeElement).toBe(buttons.at(-1));
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Home" });
    expect(document.activeElement).toBe(first);
  });

  it("says when a player has no games, rather than drawing zeros", async () => {
    const noGames = required(
      skillTreeRecords().find((row) => row.state === "no_appearances"),
      "a no-appearance record",
    );
    const source = sourceFor(loadFor);
    render(<SkillTree source={source} playerId={noGames.player_id} position={noGames.position} name="Bench Player" />);
    expect(await screen.findByText(/has not played a regular-season game/)).toBeDefined();
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("says when the build has no record for him, and when loading failed", async () => {
    const empty = sourceFor(() => ({ rows: [], definitions: loadFor(playerAt("WR")).definitions }));
    render(<SkillTree source={empty} playerId="gsis:00-0000020" position="WR" name="Free Agent" />);
    expect(await screen.findByText(/No skill tree is published for Free Agent/)).toBeDefined();
    cleanup();
    const broken: SkillTreeSource = {
      status: "published",
      meta: null,
      load: () => Promise.reject(new Error("HTTP 404")),
      ...NO_COHORTS,
    };
    render(<SkillTree source={broken} playerId="gsis:00-0000001" position="WR" name="X" />);
    expect(await screen.findByText(/could not be loaded \(HTTP 404\)/)).toBeDefined();
  });

  it("lists withheld sources with the build's own sentence", async () => {
    const meta = skillTreeMetadata({
      sources: {
        ...skillTreeMetadata().sources,
        next_gen_stats: { status: "unavailable", reason: "next_gen_stats_not_at_cutoff" },
      },
    });
    const source: SkillTreeSource = {
      status: "published",
      meta,
      load: (id) => Promise.resolve(loadFor(id)),
      ...NO_COHORTS,
    };
    render(<SkillTree source={source} playerId={playerAt("TE")} position="TE" name="Test End" />);
    expect(await screen.findByText(/does not yet end at the board's cutoff week/)).toBeDefined();
  });
});

// ------------------------------------------------------------------- on the card

describe("on the in-season card", () => {
  const SHEET = "(max-width: 767px)";

  function serve(skillTree: "present" | "absent" = "present"): void {
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true, { skillTree }) });
  }

  async function openCard(name: string): Promise<HTMLElement> {
    window.history.replaceState(null, "", "/?view=ros&scoring=ppr&teams=12");
    render(<App now={FIXTURE_NOW} />);
    // The in-season board decodes several artifacts; a loaded CI worker can take seconds.
    await waitFor(
      () => {
        expect(screen.getByRole("heading", { name: /Rest of season/ })).toBeDefined();
      },
      { timeout: 10_000 },
    );
    fireEvent.click(required(screen.getAllByRole("button", { name })[0], name));
    await waitFor(
      () => {
        expect(screen.getByRole("heading", { name })).toBeDefined();
      },
      { timeout: 10_000 },
    );
    return screen.getByRole("dialog");
  }

  function boardPlayer(): string {
    const row = rosTierRecords().find(
      (record) =>
        record.league_preset_id === "redraft-12" &&
        record.scoring_preset === "PPR" &&
        skillTreeRecords().some((reading) => reading.player_id === record.player_id && reading.games > 0),
    );
    return required(row, "a board player with a tree").display_name;
  }

  function skillRequests(): string[] {
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    return calls.map((call) => String(call[0])).filter((url) => url.includes("/skill_tree"));
  }

  it("fetches nothing when the card opens, and loads on the button", async () => {
    serve();
    const dialog = await openCard(boardPlayer());
    const section = within(dialog).getByRole("heading", { name: "Skill tree" });
    expect(section).toBeDefined();
    const button = within(dialog).getByRole("button", { name: "Show skill tree" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(skillRequests()).toEqual([]);
    fireEvent.click(button);
    expect(await within(dialog).findByRole("group", { name: /skill tree/ }, { timeout: 10_000 })).toBeDefined();
    expect(skillRequests().length).toBe(2);
    expect(within(dialog).getByRole("button", { name: "Hide skill tree" }).getAttribute("aria-expanded")).toBe(
      "true",
    );
  });

  it("is absent from a build that published no tree", async () => {
    serve("absent");
    const dialog = await openCard(boardPlayer());
    expect(within(dialog).queryByRole("heading", { name: "Skill tree" })).toBeNull();
    expect(within(dialog).getByRole("heading", { name: "In-season usage" })).toBeDefined();
  });

  it("is a tab on a phone, loading only when chosen", async () => {
    setMediaQuery(SHEET, true);
    serve();
    const dialog = await openCard(boardPlayer());
    const tab = within(dialog).getByRole("tab", { name: "Skill tree" });
    expect(skillRequests()).toEqual([]);
    fireEvent.click(tab);
    expect(await within(dialog).findByRole("group", { name: /skill tree/ }, { timeout: 10_000 })).toBeDefined();
    expect(within(dialog).queryByRole("button", { name: "Show skill tree" })).toBeNull();
  });

  /*
   * ADR-111: the phone's compact header. jsdom applies no stylesheet, so this pins the state the
   * stylesheet keys on (`data-header`) and the control's semantics; the pixels are Playwright's
   * (`mobile.spec.ts`).
   */
  it("starts compact on a phone, and keeps the reader's choice across every tab until it closes", async () => {
    setMediaQuery(SHEET, true);
    serve();
    const name = boardPlayer();
    const dialog = await openCard(name);
    const card = required(dialog.querySelector<HTMLElement>(".detail-card"), ".detail-card");
    const toggle = within(dialog).getByRole("button", { name: "Expand details" });
    expect(card.dataset.header).toBe("compact");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.getAttribute("aria-controls")).toBe(required(dialog.querySelector(".detail-rail"), "rail").id);
    // The title is still the whole name, in the dialog's accessible name.
    expect(within(dialog).getByRole("heading", { level: 2, name })).toBeDefined();

    fireEvent.click(toggle);
    expect(card.dataset.header).toBe("expanded");
    const tabs = within(dialog).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toContain("Skill tree");
    for (const tab of tabs) {
      fireEvent.click(tab);
      expect(tab.getAttribute("aria-selected")).toBe("true");
      expect(card.dataset.header).toBe("expanded");
      expect(within(dialog).getByRole("button", { name: "Collapse details" })).toBeDefined();
      expect(within(dialog).getByRole("button", { name: "Close player detail" })).toBeDefined();
      if (tab.textContent === "Skill tree") {
        expect(await within(dialog).findByRole("group", { name: /skill tree/ }, { timeout: 10_000 })).toBeDefined();
        expect(card.dataset.header).toBe("expanded");
      }
    }
    fireEvent.click(within(dialog).getByRole("button", { name: "Collapse details" }));
    fireEvent.click(tabs[0] ?? toggle);
    expect(card.dataset.header).toBe("compact");

    // Closing resets it: the next card opens compact.
    fireEvent.click(within(dialog).getByRole("button", { name: "Expand details" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Close player detail" }));
    await waitFor(() => {
      expect(screen.queryByRole("heading", { level: 2, name })).toBeNull();
    });
    fireEvent.click(required(screen.getAllByRole("button", { name })[0], name));
    const reopened = await screen.findByRole("button", { name: "Expand details" });
    expect(reopened.getAttribute("aria-expanded")).toBe("false");
  });

  it("renders no header toggle above the sheet breakpoint", async () => {
    serve();
    const dialog = await openCard(boardPlayer());
    expect(within(dialog).queryByRole("button", { name: /details$/ })).toBeNull();
    expect(required(dialog.querySelector<HTMLElement>(".detail-card"), ".detail-card").dataset.header).toBeUndefined();
  });
});
