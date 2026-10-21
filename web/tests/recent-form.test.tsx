/**
 * The Opportunity Board's recent-weeks lens and breakout categories (ADR-113).
 *
 * The page reads build-time ranks and categories and never makes its own: these tests hold it
 * to that (a filter, a search or a page cannot move a rank), to the states it must keep apart
 * (a badge, none, insufficient evidence, an unavailable build), and to the composition rules
 * every other Opportunity filter follows. The rendered tests open the real App on the fixture
 * site, where the rule — not a name — gives the third tight end his Takeover.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { selectOpportunityCandidates, type OpportunityCandidate } from "../src/data/candidates";
import { chooseSearchPlayer } from "../src/data/boardSearch";
import { opportunityRowsToCsv } from "../src/data/csv";
import {
  RECENT_CSV_COLUMNS,
  badgeOf,
  breakoutCensus,
  breakoutExplanation,
  formatSpan,
  passesBreakout,
  recentAvailability,
  recentStanding,
  recentVsSeasonPlaces,
  windowSpan,
} from "../src/data/recent";
import { InSeasonBundle } from "../src/data/ros";
import { DEFAULT_STATE, parseState, serializeState, type AppState } from "../src/data/state";
import {
  FIXTURE_GENERATED_AT,
  behaviorSeriesRecords,
  fixtureFiles,
  inSeasonFixtureFiles,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  seasonActualsRecords,
  teamMatchupRecords,
  usageRecords,
} from "./fixtures/artifacts";
import { FIXTURE_TAKEOVER_ID, recentFormMetadata, recentFormRecords } from "./fixtures/recent";
import { required } from "./required";
import { stubSite } from "./site";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function bundle(recent: "present" | "absent" | "withheld" = "present"): InSeasonBundle {
  const meta =
    recent === "absent"
      ? null
      : recent === "withheld"
        ? recentFormMetadata({ status: "withheld", withheld_reason: "season actuals withheld", records: 0 })
        : recentFormMetadata();
  return new InSeasonBundle({
    metadata: rosBuildMetadata({ recent_form: meta }),
    rosTiers: rosTierRecords(),
    opportunity: opportunityRecords(true),
    opportunityDegradation: null,
    behaviorSeries: behaviorSeriesRecords(),
    usage: usageRecords(),
    matchups: teamMatchupRecords(),
    actuals: seasonActualsRecords(),
    recent: recent === "present" ? recentFormRecords() : null,
    recentPublished: recent !== "absent",
  });
}

function select(patch: Partial<AppState> = {}, source = bundle()) {
  return selectOpportunityCandidates(source, { ...DEFAULT_STATE, view: "opportunity", ...patch });
}

function names(rows: readonly OpportunityCandidate[]): string[] {
  return rows.map((row) => row.row.record.display_name);
}

function row(name: string, patch: Partial<AppState> = {}, source = bundle()): OpportunityCandidate {
  return required(
    select(patch, source).candidates.find((candidate) => candidate.row.record.display_name === name),
    name,
  );
}

describe("the standings", () => {
  it("reads the build's window rank, its real weeks and the gap to the season rank", () => {
    const ertz = row("Zach Ertz");
    const recent = required(ertz.recent, "his recent standing");
    expect(recent.kind).toBe("ranked");
    if (recent.kind !== "ranked") return;
    expect(recent.rank).toBe(3);
    expect(formatSpan(recent.span)).toBe("W6–W8");
    expect(recentVsSeasonPlaces(ertz.season, recent)).toBe(12);
    expect(badgeOf(recent)).toBe("takeover");
  });

  it("never re-ranks: position, search and filters leave every window rank where the build put it", () => {
    const all = row("Zach Ertz").recent;
    const onlyTe = row("Zach Ertz", { position: "te" }).recent;
    const searched = row("Zach Ertz", { search: "ertz" }).recent;
    for (const standing of [onlyTe, searched]) {
      expect(standing?.kind === "ranked" && standing.rank).toBe(all?.kind === "ranked" && all.rank);
    }
  });

  it("changes no value, rank, tier or order when only the window changes", () => {
    const keys = (rows: readonly OpportunityCandidate[]) =>
      rows.map((candidate) => [
        candidate.row.record.player_id,
        candidate.row.record.ros_fair_rank,
        candidate.row.record.ros_tier,
        candidate.row.record.ros_vorp_p50,
        candidate.role.kind,
        candidate.season?.kind === "ranked" ? candidate.season.rank : null,
      ]);
    const season = keys(select({ last: "season" }).candidates);
    for (const last of ["1", "2", "3", "4", "6"] as const) {
      expect(keys(select({ last }).candidates)).toEqual(season);
    }
  });

  it("shows a shorter window's real weeks, and a window with no game as no rank", () => {
    const meta = recentFormMetadata({
      windows: { ...recentFormMetadata().windows, "3": { requested: 3, first_week: 1, last_week: 2, weeks: 2 } },
    });
    expect(formatSpan(windowSpan(meta, "3"))).toBe("W1–W2 (2 of 3 wks)");
    const swift = row("Ja'Marr Swift");
    expect(swift.recent?.kind).toBe("no_games");
    expect(recentVsSeasonPlaces(swift.season, swift.recent)).toBeNull();
  });

  it("keeps a badge, none, insufficient and unavailable apart", () => {
    const census = breakoutCensus(select().candidates.map((candidate) => candidate.recent));
    expect(census.takeover).toBe(1);
    expect(census.insufficient).toBeGreaterThan(0);
    expect(census.none).toBeGreaterThan(0);
    // A board player with no recent record at all is unavailable, never "none".
    const withoutErtz = new InSeasonBundle({
      metadata: rosBuildMetadata({ recent_form: recentFormMetadata() }),
      rosTiers: rosTierRecords(),
      opportunity: opportunityRecords(true),
      opportunityDegradation: null,
      actuals: seasonActualsRecords(),
      recent: recentFormRecords().filter((record) => record.player_id !== FIXTURE_TAKEOVER_ID),
    });
    const missing = row("Zach Ertz", {}, withoutErtz);
    expect(missing.recent?.kind).toBe("unavailable");
    expect(passesBreakout(missing.recent, "any")).toBe(false);
    const absent = bundle("absent");
    expect(absent.recentAvailability.kind).toBe("unavailable");
    expect(row("Zach Ertz", {}, absent).recent?.kind).toBe("unavailable");
  });

  it("states a withheld or incompatible build as unavailable with its reason", () => {
    expect(recentAvailability(null, false, true).kind).toBe("unavailable");
    const withheld = recentAvailability(recentFormMetadata({ status: "withheld", withheld_reason: "x", records: 0 }), true, true);
    expect(withheld.kind === "unavailable" && withheld.reason).toMatch(/withheld/);
    const incompatible = recentAvailability(recentFormMetadata(), true, false);
    expect(incompatible.kind === "unavailable" && incompatible.reason).toMatch(/contract version/);
  });

  it("lets Last 1 reach at most Eyebrow and Last 2 at most Sneaking", () => {
    for (const record of recentFormRecords()) {
      expect(["takeover", "sneaking"]).not.toContain(record.windows["1"].breakout.category);
      expect(record.windows["2"].breakout.category).not.toBe("takeover");
    }
    expect(badgeOf(row("Zach Ertz", { last: "1" }).recent)).toBe("eyebrow");
    expect(badgeOf(row("Rashee Kirk", { last: "2" }).recent)).toBe("sneaking");
  });

  it("never badges a worse recent rank", () => {
    for (const record of recentFormRecords()) {
      for (const window of Object.values(record.windows)) {
        if (["takeover", "sneaking", "eyebrow"].includes(window.breakout.category)) {
          expect(window.rank).not.toBeNull();
          expect(record.season_rank).not.toBeNull();
          expect((record.season_rank ?? 0) - (window.rank ?? 0)).toBeGreaterThanOrEqual(3);
        }
      }
    }
  });
});

describe("the breakout filter", () => {
  it("counts only actual matching badges, and composes with position, search and the other filters", () => {
    expect(names(select({ form: "takeover" }).candidates)).toEqual(["Zach Ertz"]);
    expect(names(select({ form: "any" }).candidates)).toContain("Zach Ertz");
    expect(select({ form: "sneaking" }).candidates).toHaveLength(0);
    expect(select({ form: "takeover", position: "wr" }).candidates).toHaveLength(0);
    expect(select({ form: "takeover", search: "pitts" }).candidates).toHaveLength(0);
    expect(names(select({ form: "sneaking", last: "2" }).candidates)).toEqual(["Rashee Kirk"]);
    const report = required(select({ form: "takeover" }).breakout, "the report");
    expect(report).toMatchObject({ usable: true, passing: 1 });
    for (const candidate of select({ form: "any", last: "1" }).candidates) {
      expect(passesBreakout(candidate.recent, "any")).toBe(true);
    }
  });

  it("is not applied, and says why, in the Season lens or on a build without recent form", () => {
    const season = select({ form: "takeover", last: "season" });
    expect(season.breakout?.usable).toBe(false);
    expect(season.breakout?.reason).toMatch(/choose Last 1–6/);
    expect(season.candidates.length).toBe(select().candidates.length);
    const old = select({ form: "takeover" }, bundle("absent"));
    expect(old.breakout?.usable).toBe(false);
    expect(old.candidates.length).toBe(select({}, bundle("absent")).candidates.length);
  });

  it("is cleared by the player picker when it would hide the chosen player", () => {
    const state: AppState = { ...DEFAULT_STATE, view: "opportunity", form: "takeover" };
    const choice = chooseSearchPlayer(
      { id: "gsis:00-0000004", name: "Kyle Pitts Sr.", position: "TE" },
      state,
      "opportunity",
      bundle(),
    );
    expect(choice.patch.form).toBe("all");
    expect(choice.note).toMatch(/Breakout filter/);
    const kept = chooseSearchPlayer({ id: FIXTURE_TAKEOVER_ID, name: "Zach Ertz", position: "TE" }, state, "opportunity", bundle());
    expect(kept.patch.form).toBeUndefined();
  });
});

describe("URL state", () => {
  it("round-trips the lens and the filter, omits defaults, and normalizes anything else", () => {
    expect(serializeState({ ...DEFAULT_STATE, view: "opportunity" })).toBe("?view=opportunity");
    const href = serializeState({ ...DEFAULT_STATE, view: "opportunity", last: "6", form: "any" });
    expect(href).toBe("?view=opportunity&last=6&form=any");
    expect(parseState(href)).toEqual({ state: { ...DEFAULT_STATE, view: "opportunity", last: "6", form: "any" }, normalized: true });
    expect(parseState("?last=season").state.last).toBe("season");
    for (const bad of ["?last=5", "?last=", "?form=great", "?last=3.0"]) {
      const parsed = parseState(bad);
      expect(parsed.normalized).toBe(false);
      expect(parsed.state.last).toBe("3");
      expect(parsed.state.form).toBe("all");
    }
  });
});

describe("the explanation and the export", () => {
  it("explains a badge with the artifact's numbers: ranks, games, role and sample", () => {
    const ertz = row("Zach Ertz");
    const recent = required(ertz.recent, "recent");
    if (recent.kind === "unavailable") throw new Error("expected a standing");
    const text = breakoutExplanation(recent, ertz.season, recentFormMetadata());
    expect(text.headline).toBe("TE15 season → TE3 in W6–W8 (+12 places)");
    const lines = text.lines.join("\n");
    expect(lines).toMatch(/Games used: W6 TE3 \(9\.3\), W7 TE3 \(9\.7\), W8 TE3 \(9\.5\)/);
    expect(lines).toMatch(/snap share 70\.6% over 3 games/);
    expect(lines).toMatch(/passes: at least 70\.0%/);
    expect(lines).toMatch(/Sample: 3 games in W6–W8/);
    expect(text.footnote).toMatch(/not a prediction/);
  });

  it("explains insufficient evidence as missing, not as a no", () => {
    const mcbride = row("Trey McBride");
    const recent = required(mcbride.recent, "recent");
    if (recent.kind === "unavailable") throw new Error("expected a standing");
    expect(recent.verdict.category).toBe("insufficient");
    expect(breakoutExplanation(recent, mcbride.season, recentFormMetadata()).lines[0]).toMatch(
      /Too few games before the window/,
    );
  });

  it("writes the selected window for the rows on screen, in their order", () => {
    const rows = select({ last: "3" }).candidates;
    const csv = opportunityRowsToCsv(rows, "3", recentFormMetadata());
    const lines = csv.trim().split(/\r?\n/);
    const header = required(lines[0], "header").split(",");
    expect(header.slice(-RECENT_CSV_COLUMNS.length)).toEqual([...RECENT_CSV_COLUMNS]);
    expect(lines).toHaveLength(rows.length + 1);
    const ertzLine = required(lines.find((line) => line.includes("Zach Ertz")), "Ertz");
    expect(ertzLine.endsWith("3,6,8,3,3,28.54,3,9.51,12,takeover,takeover_role,breakout_v1,6|7|8,snap_share:substantial")).toBe(true);
    const season = opportunityRowsToCsv(select({ last: "season" }).candidates, "season", recentFormMetadata());
    expect(required(season.split(/\r?\n/)[1], "row").split(",").slice(-RECENT_CSV_COLUMNS.length)[0]).toBe("season");
  });

  it("keeps the record's numbers verbatim", () => {
    const record = required(
      recentFormRecords().find((candidate) => candidate.player_id === FIXTURE_TAKEOVER_ID && candidate.scoring_preset === "PPR"),
      "Ertz",
    );
    const standing = recentStanding(record, "3", { kind: "published", meta: recentFormMetadata() });
    expect(standing.kind === "ranked" && standing.points).toBe(record.windows["3"].points);
  });
});

// ------------------------------------------------------------------------------ rendered

async function openBoard(query: string, recent: "present" | "absent" = "present"): Promise<void> {
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true, { recent }) });
  window.history.replaceState(null, "", `/?view=opportunity&scoring=ppr&teams=12${query}`);
  render(<App now={FIXTURE_NOW} />);
  await waitFor(
    () => {
      expect(screen.getByRole("heading", { name: /Opportunity — through week/ })).toBeDefined();
    },
    { timeout: 10_000 },
  );
}

function table(): HTMLElement {
  return required(document.querySelector<HTMLElement>("table.opp-sheet"), "the table");
}

describe("on the page", () => {
  it("defaults to Last 3 with the weeks in the headings and a badge that opens its evidence", async () => {
    await openBoard("");
    const group = screen.getByRole("radiogroup", { name: "Recent weeks" });
    expect(within(group).getAllByRole("radio").map((radio) => radio.textContent)).toEqual(["Season", "1", "2", "3", "4", "6"]);
    expect(within(group).getByRole("radio", { name: /Last 3 completed weeks, W6–W8/ }).getAttribute("aria-checked")).toBe("true");
    expect(within(table()).getAllByText("W6–8").length).toBe(2);
    expect(screen.getByText(/Breakouts in W6–8: 1 Takeover/)).toBeDefined();
    const badge = within(table()).getByRole("button", { name: /^Takeover in W6–W8/ });
    fireEvent.click(badge);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("TE15 season → TE3 in W6–W8 (+12 places)")).toBeDefined();
    expect(within(dialog).getByText(/Games used: W6 TE3/)).toBeDefined();
  });

  it("drops the recent columns and badges in the Season lens, and keeps RoS vs Szn", async () => {
    await openBoard("&last=season");
    expect(within(table()).queryByRole("button", { name: /^Takeover/ })).toBeNull();
    expect(table().querySelector('[data-col="recent_rank"]')).toBeNull();
    expect(table().querySelector('[data-col="ros_vs_season"]')).not.toBeNull();
    expect(screen.queryByText(/Breakouts in/)).toBeNull();
  });

  it("sorts the recent rank best-first with no-game rows last in both directions", async () => {
    await openBoard("");
    const button = within(table()).getByRole("button", { name: /^Recent/ });
    const order = (): string[] =>
      [...table().querySelectorAll('tbody td[data-col="recent_rank"] .signal-value')].map((cell) => cell.textContent ?? "");
    fireEvent.click(button);
    const ascending = order();
    fireEvent.click(button);
    const descending = order();
    for (const list of [ascending, descending]) {
      const firstDash = list.indexOf("—");
      if (firstDash >= 0) expect(list.slice(firstDash).every((text) => text === "—")).toBe(true);
    }
    expect(ascending[0]).toMatch(/^QB\d/);
  });

  it("renders the existing board on an older build and disables the controls with a reason", async () => {
    await openBoard("&form=takeover", "absent");
    expect(screen.getByText("The breakout filter in this link cannot be applied here.")).toBeDefined();
    const lens = screen.getByRole("radiogroup", { name: "Recent weeks" });
    for (const radio of within(lens).getAllByRole("radio").slice(1)) {
      expect((radio as HTMLButtonElement).disabled).toBe(true);
    }
    expect(screen.queryByText("No players match.")).toBeNull();
    expect(table().querySelector('[data-col="recent_rank"]')).toBeNull();
    expect(screen.getByText(/Recent weeks: This build published no recent-form windows/)).toBeDefined();
  });

  it("filters to a badge from a direct link and counts it in the status line", async () => {
    await openBoard("&form=takeover");
    const rows = [...table().querySelectorAll("tbody tr .player-name")].map((cell) => cell.textContent);
    expect(rows).toEqual(["Zach Ertz"]);
    expect(screen.getByText(/Takeover: 1/)).toBeDefined();
  });
});
