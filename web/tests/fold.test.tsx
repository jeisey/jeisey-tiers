/**
 * The phone's folded controls (ADR-093).
 *
 * What jsdom can check: what each summary row says, that it is a disclosure naming the panels
 * it controls, that folding changes neither the URL nor the controls' state, and that the
 * rows print exactly the state a folded control is hiding. What it cannot check — which
 * widths fold, how tall the sticky block is, Escape at phone width — has no layout to measure
 * here and is asserted in `web/tests/e2e/mobile.spec.ts` and `board.spec.ts` instead.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { settingsSummary } from "../src/app/Controls";
import {
  OPPORTUNITY_BOARD_PREVIEW_DEPTH,
  opportunityOptionsSummary,
} from "../src/app/OpportunityView";
import { PanelToggle } from "../src/components/primitives";
import type { FilterReport } from "../src/data/candidates";
import { DEFAULT_STATE, type AppState } from "../src/data/state";
import { FIXTURE_GENERATED_AT, fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { required } from "./required";

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

function serve(inSeason: boolean): void {
  const payloads: Record<string, unknown> = {
    ...fixtureFiles(),
    ...(inSeason ? inSeasonFixtureFiles() : {}),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const payload = payloads[input.split("/").pop() ?? ""];
      if (payload === undefined) {
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) } as Response);
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) } as Response);
    }),
  );
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

function state(overrides: Partial<AppState> = {}): AppState {
  return { ...DEFAULT_STATE, ...overrides };
}

function report(filter: FilterReport["filter"], available = true): FilterReport {
  return { filter, available, passing: 3, withoutReading: 1 };
}

/** The accessible name, the way a screen reader is handed it: whitespace collapsed. */
function spoken(element: HTMLElement): string {
  const clone = element.cloneNode(true) as HTMLElement;
  for (const hidden of clone.querySelectorAll('[aria-hidden="true"]')) hidden.remove();
  return (clone.textContent ?? "").replace(/\s+/g, " ").trim();
}

beforeEach(() => {
  go();
});

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
  go();
});

describe("the settings row's summary", () => {
  it("prints every folded control's value, defaults included", () => {
    expect(settingsSummary(state(), false)).toEqual(["PPR", "12 teams", "All positions"]);
    expect(settingsSummary(state({ scoring: "half", teams: 14, position: "rb" }), false)).toEqual([
      "Half",
      "14 teams",
      "RB",
    ]);
    expect(settingsSummary(state({ scoring: "std" }), false)[0]).toBe("STD");
  });

  it("names a search only when there is one, because a hidden search is a forgotten filter", () => {
    expect(settingsSummary(state({ search: "cook" }), false)).toEqual([
      "PPR",
      "12 teams",
      "All positions",
      "“cook”",
    ]);
  });

  it("names the season mode only when a reader overrode it, and last", () => {
    // `auto` is what the masthead chip already names; repeating it costs the row its width.
    expect(settingsSummary(state({ mode: "auto" }), true)).not.toContain("Draft mode");
    expect(settingsSummary(state({ mode: "draft", search: "x" }), true)).toEqual([
      "PPR",
      "12 teams",
      "All positions",
      "“x”",
      "Draft mode",
    ]);
    expect(settingsSummary(state({ mode: "in_season" }), true).at(-1)).toBe("In-season mode");
    // Before kickoff there is no switch, so there is no override to report.
    expect(settingsSummary(state({ mode: "draft" }), false)).not.toContain("Draft mode");
  });
});

describe("the opportunity options row's summary", () => {
  it("prints the ordering, the applied filters and the chart's depth", () => {
    expect(opportunityOptionsSummary(state(), { filters: [] }, 19)).toEqual([
      "By ROS value",
      "No filters",
      "All 19",
    ]);
    expect(
      opportunityOptionsSummary(
        state({ opportunity: "momentum" }),
        { filters: [report("role"), report("momentum")] },
        176,
      ),
    ).toEqual(["By Momentum", "Role rising + Momentum rising", `Top ${String(OPPORTUNITY_BOARD_PREVIEW_DEPTH)} of 176`]);
    expect(opportunityOptionsSummary(state({ board: "full" }), { filters: [] }, 176)[2]).toBe(
      "All 176",
    );
  });

  it("does not claim a filter the build could not apply", () => {
    // The notice under the options names it; the summary says what the board actually did.
    expect(
      opportunityOptionsSummary(state(), { filters: [report("role", false)] }, 19)[1],
    ).toBe("No filters");
    expect(
      opportunityOptionsSummary(
        state(),
        { filters: [report("role", false), report("surfaced")] },
        19,
      )[1],
    ).toBe("Surfaced");
  });
});

describe("PanelToggle", () => {
  it("is a disclosure button that names its panels and reads its summary as a list", () => {
    const onToggle = vi.fn();
    render(
      <PanelToggle
        label="Settings"
        items={["PPR", "12 teams", "All positions"]}
        open={false}
        controls="one two"
        onToggle={onToggle}
      />,
    );
    const button = screen.getByRole("button");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.getAttribute("aria-controls")).toBe("one two");
    // The dots are for the eye and the commas for the ear.
    expect(spoken(button)).toBe("Settings PPR, 12 teams, All positions");
    expect(button.querySelectorAll(".panel-toggle-sep[aria-hidden='true']")).toHaveLength(2);
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledOnce();
  });
});

describe("the shell's settings panel", () => {
  it("folds the controls without unmounting them or touching the URL", async () => {
    serve(false);
    go("?scoring=half&position=rb");
    render(<App now={FIXTURE_NOW} />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Tier board" })).toBeDefined();
    });

    const toggle = screen.getByRole("button", { name: /^Settings/ });
    expect(spoken(toggle)).toBe("Settings Half, 12 teams, RB");
    expect(toggle.getAttribute("aria-controls")).toBe("board-settings");
    const panel = required(document.getElementById("board-settings"), "the settings panel");
    expect(panel.dataset.open).toBe("false");
    // Folded is hidden by the stylesheet at phone width, not removed: the radios keep their
    // state and the desktop, which ignores `data-open`, renders every one of them.
    expect(within(panel).getByRole("radio", { name: "RB" }).getAttribute("aria-checked")).toBe("true");

    const before = window.location.search;
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(panel.dataset.open).toBe("true");
    fireEvent.click(toggle);
    expect(panel.dataset.open).toBe("false");
    // Chrome, not board: a shared link must not open somebody else's panel.
    expect(window.location.search).toBe(before);

    // A change made through the panel is in the summary at once.
    fireEvent.click(within(panel).getByRole("radio", { name: "WR" }));
    await waitFor(() => {
      expect(spoken(screen.getByRole("button", { name: /^Settings/ }))).toBe(
        "Settings Half, 12 teams, WR",
      );
    });
  });

  it("holds the season-mode switch in the same panel once there is a switch", async () => {
    serve(true);
    go("?view=ros");
    render(<App now={FIXTURE_NOW} />);
    await waitFor(() => {
      expect(screen.getByRole("radiogroup", { name: "Season mode" })).toBeDefined();
    });
    const panel = required(document.getElementById("board-settings"), "the settings panel");
    expect(within(panel).getByRole("radiogroup", { name: "Season mode" })).toBeDefined();
    expect(within(panel).getByRole("radiogroup", { name: "Scoring" })).toBeDefined();
  });
});

describe("the opportunity board's options", () => {
  it("fold the orderings and the chips together and leave the census outside", async () => {
    serve(true);
    go("?view=opportunity&only=role&opportunity=adds");
    render(<App now={FIXTURE_NOW} />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /^Opportunity — through week/ })).toBeDefined();
    });

    const toggle = screen.getByRole("button", { name: /^Options/ });
    expect(spoken(toggle)).toMatch(/^Options By Adds, Role rising, All \d+$/);
    const ids = (toggle.getAttribute("aria-controls") ?? "").split(" ");
    expect(ids).toEqual(["opp-order-options", "opp-filter-options"]);
    const panels = ids.map((id) => required(document.getElementById(id), `panel ${id}`));
    expect(within(required(panels[0], "order")).getByRole("radiogroup", { name: "Order by" })).toBeDefined();
    expect(within(required(panels[1], "filters")).getByRole("button", { name: "Role rising" })).toBeDefined();

    // The status line is the filters' census (ADR-092) and is never inside a fold.
    const status = required(document.querySelector(".opp-filter-status"), "the census line");
    for (const panel of panels) expect(panel.contains(status)).toBe(false);

    expect(panels.map((panel) => panel.dataset.open)).toEqual(["false", "false"]);
    fireEvent.click(toggle);
    expect(panels.map((panel) => panel.dataset.open)).toEqual(["true", "true"]);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });
});
