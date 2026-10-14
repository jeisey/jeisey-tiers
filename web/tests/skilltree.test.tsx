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
  buildSkillTreeView,
  formatSkillValue,
  nodeName,
  nodeOrder,
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
      "app/skillTreeGlyphs.tsx",
      "data/contracts.ts",
      "data/skilltree.ts",
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
    const viewModel = files.filter((file) => /from\s+["'][./]*(data\/)?skilltree["']/.test(file.text));
    expect(viewModel.map((file) => file.name)).toEqual(["app/SkillTree.tsx"]);
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
    expect(reading.segments).toBe(0);

    const uncovered = skillTreeRecords().find((row) => row.reason === "not_in_ngs_summary");
    const covered = required(uncovered, "an NGS reading not covered");
    const ngsView = buildSkillTreeView(loadFor(covered.player_id), skillTreeMetadata(), covered.position);
    const ngs = ngsView.branches.flatMap((branch) => branch.nodes).find((node) => node.id === covered.metric_id);
    if (ngs !== undefined) {
      expect(ngs.standingText).toBe("Not in Next Gen Stats");
      expect(ngs.empty).toBe(true);
    }
  });

  it("lights meter segments from the published percentile and marks context metrics", () => {
    const base = loadFor(playerAt("WR"));
    const tweak = (metric: string, percentile: number): number => {
      const rows = base.rows.map((row) =>
        row.metric_id === metric ? { ...row, state: "ranked", percentile, rank: 3, cohort_size: 40 } : row,
      );
      const view = buildSkillTreeView({ ...base, rows }, skillTreeMetadata(), "WR");
      const node = required(
        view.branches.flatMap((branch) => branch.nodes).find((candidate) => candidate.id === metric),
        metric,
      );
      return metric === "adot" ? (node.marker ?? -1) : node.segments;
    };
    expect(tweak("catch_rate", 0)).toBe(1);
    expect(tweak("catch_rate", 19.9)).toBe(1);
    expect(tweak("catch_rate", 20)).toBe(2);
    expect(tweak("catch_rate", 80)).toBe(5);
    expect(tweak("catch_rate", 100)).toBe(5);
    // aDOT has no better direction: a marker at the percentile, never a fill.
    expect(tweak("adot", 72)).toBe(72);
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
    const source: SkillTreeSource = { status: "published", meta, load: (id) => Promise.resolve(loadFor(id)) };
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
});
