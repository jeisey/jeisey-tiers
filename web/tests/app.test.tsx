/**
 * The application, rendered.
 *
 * These are the behavioural guarantees the exit gate names: state lives in the URL, the tables
 * agree with the charts, a degraded optional artifact does not invalidate the tier board, and
 * an unsupported contract refuses rather than guesses.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { setMediaQuery } from "./setup";
import {
  FIXTURE_GENERATED_AT,
  arbitrageEnvelope,
  arbitrageRecords,
  buildMetadata,
  playerStatusEnvelope,
  projectionEnvelope,
  tierEnvelope,
  tierRecords,
} from "./fixtures/artifacts";

/**
 * The clock these tests render against: three hours after the fixture board was built.
 *
 * Without it the suite silently expires. `STALE_WARNING_HOURS` is 48, so a test asserting
 * the "build notes" chip only passed while the wall clock was within two days of
 * `FIXTURE_GENERATED_AT` — it went green in CI and started failing two days later with no
 * code change, which is a test measuring the calendar rather than the component. The fixture
 * stays a fixed board, deterministic by design; the *clock* is what the test now pins.
 */
const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

type Payloads = Record<string, unknown>;

/** Sentinel for "this build did not publish that artifact". */
const MISSING = Symbol("missing");

function serve(overrides: Payloads = {}): void {
  const payloads: Payloads = {
    "build_metadata.json": buildMetadata(),
    "tiers.json": tierEnvelope(),
    "arbitrage.json": arbitrageEnvelope(),
    "player_status.json": playerStatusEnvelope(),
    "projections.json": projectionEnvelope(),
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const name = input.split("/").pop() ?? "";
      const payload = payloads[name];
      if (payload === undefined || payload === MISSING) {
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) } as Response);
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) } as Response);
    }),
  );
}

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

async function boardReady(): Promise<void> {
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Tier board" })).toBeDefined();
  });
}

beforeEach(() => {
  go();
  serve();
});

afterEach(() => {
  go();
});

describe("shell", () => {
  it("renders the build timestamp from metadata, in Eastern", async () => {
    render(<App />);
    await boardReady();
    expect(screen.getByText("Aug 21 · 10:38 AM ET")).toBeDefined();
  });

  it("shows a compact status chip rather than a full-width alarm", async () => {
    render(<App now={FIXTURE_NOW} />);
    await boardReady();
    const chip = screen.getByRole("button", { name: /build note/i });
    expect(chip.className).toContain("status-chip");
  });

  it("escalates the same chip to a stale warning once the build ages out", async () => {
    // The other half of the contract, and the branch that had quietly been swallowing the
    // test above: past STALE_WARNING_HOURS the chip says so. Still a chip, never an alarm.
    const stale = new Date(Date.parse(FIXTURE_GENERATED_AT) + 49 * 60 * 60 * 1000);
    render(<App now={stale} />);
    await boardReady();
    const chip = screen.getByRole("button", { name: /build is stale/i });
    expect(chip.className).toContain("status-chip");
  });

  it("labels the arbitrage method as deterministic, never as ML", async () => {
    go("?view=arbitrage");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Draft rail" })).toBeDefined();
    });
    expect(screen.getByText(/Deterministic market-gap baseline/)).toBeDefined();
    expect(document.body.textContent).not.toMatch(/AI arbitrage|ML signal|machine.learning model/i);
  });
});

describe("URL state", () => {
  it("hydrates from a hand-typed URL", async () => {
    go("?view=arbitrage&scoring=std&teams=14&position=qb");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Arbitrage table" })).toBeDefined();
    });
    expect(screen.getByRole("radio", { name: "Standard" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "14-team league" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "QB" }).getAttribute("aria-checked")).toBe("true");
  });

  it("writes a control change into the URL", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("radio", { name: "RB" }));
    await waitFor(() => {
      expect(window.location.search).toBe("?position=rb");
    });
  });

  it("normalizes an unsupported value and replaces the URL rather than crashing", async () => {
    go("?scoring=superflex&teams=11&position=k");
    render(<App />);
    await boardReady();
    await waitFor(() => {
      expect(window.location.search).toBe("");
    });
    expect(screen.getByRole("radio", { name: "PPR" }).getAttribute("aria-checked")).toBe("true");
  });

  it("supports browser back after a control change", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("radio", { name: "WR" }));
    await waitFor(() => {
      expect(window.location.search).toBe("?position=wr");
    });
    window.history.back();
    await waitFor(() => {
      expect(window.location.search).toBe("");
    });
    await waitFor(() => {
      expect(screen.getByRole("radio", { name: "All positions" }).getAttribute("aria-checked")).toBe("true");
    });
  });
});

describe("tier table", () => {
  it("defaults to fair-rank ascending and shows the published order", async () => {
    render(<App />);
    await boardReady();
    const table = screen.getByRole("table", { name: /Intrinsic tier board/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]?.textContent).toContain("Bijan Robinson");
    expect(within(table).getByRole("columnheader", { name: /Rank/ }).getAttribute("aria-sort")).toBe(
      "ascending",
    );
  });

  it("re-orders on a header click without changing fair rank itself", async () => {
    render(<App />);
    await boardReady();
    const table = screen.getByRole("table", { name: /Intrinsic tier board/ });
    fireEvent.click(within(table).getByRole("button", { name: /Exp FP/ }));
    const rows = within(table).getAllByRole("row").slice(1);
    // The Rank column still shows the artifact's fair rank; only the row order moved.
    const ranks = rows.map((row) => Number(row.querySelectorAll("td")[0]?.textContent));
    expect(new Set(ranks).size).toBe(ranks.length);
    expect(Math.min(...ranks)).toBe(1);
  });

  it("filters by search", async () => {
    const user = userEvent.setup();
    render(<App />);
    await boardReady();
    await user.type(screen.getByLabelText("Player search"), "burrow");
    await waitFor(() => {
      const table = screen.getByRole("table", { name: /Intrinsic tier board/ });
      expect(within(table).getAllByRole("row")).toHaveLength(2);
    });
  });

  it("agrees with the artifact on every displayed value", async () => {
    render(<App />);
    await boardReady();
    const record = tierRecords().find(
      (row) => row.league_preset_id === "redraft-12" && row.scoring_preset === "PPR" && row.fair_rank === 1,
    );
    const table = screen.getByRole("table", { name: /Intrinsic tier board/ });
    const cells = within(table).getAllByRole("row")[1]?.querySelectorAll("td") ?? [];
    expect(cells[0]?.textContent).toBe(String(record?.fair_rank));
    expect(cells[6]?.textContent).toBe(record?.expected_vorp.toFixed(1));
    expect(cells[7]?.textContent).toBe(record?.p50_vorp.toFixed(1));
  });
});

describe("chart and table agreement", () => {
  it("plots the artifact's median VORP and says so in the mark's label", async () => {
    render(<App />);
    await boardReady();
    const record = tierRecords().find(
      (row) => row.league_preset_id === "redraft-12" && row.scoring_preset === "PPR" && row.fair_rank === 1,
    );
    const mark = screen.getByRole("button", { name: /^Bijan Robinson,/ });
    const label = mark.getAttribute("aria-label") ?? "";
    expect(record).toBeDefined();
    expect(label).toContain(`median simulated VORP ${(record?.p50_vorp ?? 0).toFixed(1)}`);
    expect(label).toContain(
      `P25 to P75 ${(record?.p25_vorp ?? 0).toFixed(1)} to ${(record?.p75_vorp ?? 0).toFixed(1)}`,
    );
  });

  it("labels the axis with the statistic it plots", async () => {
    render(<App />);
    await boardReady();
    expect(screen.getByText("Median simulated VORP")).toBeDefined();
  });

  it("presents tiers as soft groups and never as a cliff", async () => {
    render(<App />);
    await boardReady();
    expect(screen.getByText(/exact tier edges are statistically soft/i)).toBeDefined();
    expect(document.body.textContent).not.toMatch(/value cliff/i);
  });

  it("draws the draft rail from the same numbers the arbitrage table shows", async () => {
    go("?view=arbitrage");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Draft rail" })).toBeDefined();
    });
    const record = arbitrageRecords()
      .filter((row) => row.league_preset_id === "redraft-12" && row.scoring_preset === "PPR")
      .sort((a, b) => b.arbitrage_score - a.arbitrage_score)[0];
    const mark = screen.getAllByRole("button", { name: new RegExp(`^${record?.display_name ?? ""},`) })[0];
    const label = mark?.getAttribute("aria-label") ?? "";
    expect(label).toContain(`fair rank ${String(record?.fair_rank)}`);
    expect(label).toContain(`ADP ${(record?.market_adp ?? 0).toFixed(1)}`);
  });
});

describe("arbitrage view", () => {
  beforeEach(() => {
    go("?view=arbitrage");
  });

  it("states the launch market condition once, with numbers from metadata", async () => {
    render(<App />);
    await waitFor(() => {
      expect(
        screen.getByText(/Every priced row on this board carries low market-data confidence/i),
      ).toBeDefined();
    });
    // The headline states what the label is about; the facts beside it carry the evidence,
    // and both are in the document rather than behind a fetch.
    expect(screen.getByText(/not a probability that a player is a bargain/)).toBeDefined();
    expect(screen.getByText(/125 drafts against the 300/)).toBeDefined();
    expect(screen.getByText(/below the frozen bar/)).toBeDefined();
  });

  it("renders a null trend as an em dash with a spoken explanation, never as zero", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Arbitrage table" })).toBeDefined();
    });
    const table = screen.getByRole("table", { name: /market-gap board/i });
    const row = within(table).getAllByRole("row")[1];
    const trendCell = row?.querySelectorAll("td")[9];
    expect(trendCell?.textContent).toContain("—");
    expect(trendCell?.textContent).toContain("Trend collecting");
    expect(trendCell?.textContent).not.toMatch(/\b0\b|flat|no movement/i);
  });

  it("omits the two columns V1 has no model for", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Arbitrage table" })).toBeDefined();
    });
    const table = screen.getByRole("table", { name: /market-gap board/i });
    const headers = within(table).getAllByRole("columnheader").map((cell) => cell.textContent ?? "");
    expect(headers.join(" ")).not.toMatch(/surplus/i);
  });

  it("states the bargain direction in words, not only in colour", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Arbitrage table" })).toBeDefined();
    });
    expect(screen.getAllByText(/picks later than his fair rank/).length).toBeGreaterThan(0);
  });

  it("names MyFantasyLeague and never calls it a consensus", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Draft rail" })).toBeDefined();
    });
    expect(screen.getAllByText(/MyFantasyLeague ADP/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/consensus adp/i);
  });

  it("explains a searched player who has no market price instead of showing zero results", async () => {
    go("?view=arbitrage&search=ertz");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("On the tier board, but not priced")).toBeDefined();
    });
    expect(screen.getByText(/Zach Ertz/)).toBeDefined();
    expect(document.body.textContent).not.toMatch(/0 results/i);
  });
});

/**
 * The market condition the launch fixture could not describe.
 *
 * Every market assertion in this file used to be written against one board: `low` on every
 * row, a null trend everywhere, a cohort below the frozen bar. That was the real August 2026
 * condition, and it made the suite blind — production reached a mostly-`medium` board with a
 * measured trend and a *sufficient* cohort within a fortnight, and nothing in the repository
 * rendered that state. It is the same defect class as the Phase-7 trend verifier that had
 * frozen the null launch condition into an assertion.
 *
 * These tests do not replace the launch ones. Both conditions are real, the product has to
 * move between them without a code change, and pinning either as "normal" is the mistake.
 */
describe("a matured market", () => {
  beforeEach(() => {
    serve({
      "build_metadata.json": buildMetadata({}, "matured"),
      "arbitrage.json": arbitrageEnvelope("matured"),
    });
    go("?view=arbitrage");
  });

  it("reports the label distribution instead of asserting one label", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Draft rail" })).toBeDefined();
    });
    const body = document.body.textContent ?? "";
    expect(body).toMatch(/Market-data confidence across these \d+ priced rows/);
    expect(body).toMatch(/\d+ medium/);
    expect(body).toMatch(/\d+ low/);
    // The launch sentence must not survive into a board that is no longer uniform.
    expect(body).not.toMatch(/Every priced row on this board carries/);
  });

  it("says the cohort clears the rule, and prints no failed clause", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/clears the frozen rule/)).toBeDefined();
    });
    expect(document.body.textContent).not.toMatch(/below the frozen bar/);
    expect(document.body.textContent).not.toMatch(/against the 300 the rule requires/);
  });

  it("renders a measured trend as a signed number and a direction word", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Arbitrage table" })).toBeDefined();
    });
    const table = screen.getByRole("table", { name: /market-gap board/i });
    const cells = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.querySelectorAll("td")[9]?.textContent ?? "");
    const measured = cells.filter((text) => /[+\u2212]\d/.test(text));
    expect(measured.length).toBeGreaterThan(0);
    expect(measured.join(" ")).toMatch(/Moving (earlier|later)/);
    // ...and the row the fixture deliberately leaves without an estimate is still an em dash.
    expect(cells.some((text) => text.includes("—") && text.includes("Trend collecting"))).toBe(true);
  });

  it("still shows the trend rule in Data, worded for a window that has history", async () => {
    go("?view=data");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Current limitations" })).toBeDefined();
    });
    expect(screen.getByText(/The window currently has enough history/)).toBeDefined();
    expect(screen.getByText(/clears the frozen sufficiency rule/)).toBeDefined();
  });

  it("drops the approximate-cohort marker on a preset the build calls exact", async () => {
    // The matured fixture marks STD at ten teams exact and every other block approximate,
    // so a card that hardcoded either word fails one of these two assertions.
    go("?scoring=std&teams=10");
    render(<App />);
    await boardReady();
    await userEvent.setup().click(screen.getByRole("button", { name: "Bijan Robinson" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Bijan Robinson" })).toBeDefined();
    });
    expect(screen.queryByText("approximate cohort")).toBeNull();
  });

  it("keeps the approximate marker where the build says approximate", async () => {
    go("?scoring=ppr&teams=12");
    render(<App />);
    await boardReady();
    await userEvent.setup().click(screen.getByRole("button", { name: "Bijan Robinson" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Bijan Robinson" })).toBeDefined();
    });
    expect(screen.getAllByText("approximate cohort").length).toBeGreaterThan(0);
  });
});

describe("player detail", () => {
  it("opens from a tier table row and marks status as annotation only, briefly", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Amon-Ra Bright" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Amon-Ra Bright" })).toBeDefined();
    });
    expect(screen.getByText("Questionable")).toBeDefined();
    expect(screen.getByText("Hamstring")).toBeDefined();
    // Phase 8 replaced the standing paragraph with a five-word marker; the paragraph itself
    // now lives once in Data, and `data view` below pins it there.
    expect(screen.getByText("Annotation only — not a model input.")).toBeDefined();
    expect(document.body.textContent).not.toMatch(
      /The board above was produced without any of these fields/,
    );
  });

  it("never claims the model accounted for an injury", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Amon-Ra Bright" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Amon-Ra Bright" })).toBeDefined();
    });
    expect(document.body.textContent).not.toMatch(
      /injury.adjusted|priced in|accounts for this injury|because of (this|his) injury/i,
    );
  });

  it("says a player has no current ADP rather than hiding him", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Zach Ertz" }));
    await waitFor(() => {
      expect(screen.getByText(/No current MyFantasyLeague ADP/)).toBeDefined();
    });
  });

  it("says nothing about health when no designation is reported", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Bijan Robinson" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Bijan Robinson" })).toBeDefined();
    });
    // The absence of a designation is stated as an absence. Phase 9A took the design source's
    // own status headline — "NO INJURY DESIGNATION REPORTED" — in place of Phase 8's
    // "None reported" field, which says the same thing in the same number of words and reads
    // as a sentence rather than as a value. The sentence explaining that an absence is not a
    // clearance is a property of the product, not of this player, so it stays in Data — where
    // `data view > keeps every disclosure the card stopped repeating` pins it.
    expect(screen.getByText("No injury designation reported")).toBeDefined();
    expect(document.body.textContent).not.toMatch(/\bhealthy\b/i);
    expect(document.body.textContent).not.toMatch(/\bcleared\b/i);
  });

  it("handles a player with no status record at all", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Deebo Gray" }));
    await waitFor(() => {
      expect(screen.getByText(/No status record was published for this player/)).toBeDefined();
    });
    // His model values are still there.
    expect(screen.getByText("Fair rank")).toBeDefined();
  });

  it("does not repeat the methodology it moved to Data", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Amon-Ra Bright" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Amon-Ra Bright" })).toBeDefined();
    });
    const body = document.body.textContent ?? "";
    // The three paragraphs the Phase-8 review named, none of which is about this player.
    expect(body).not.toMatch(/cannot filter drafts to this exact scoring and league size/);
    expect(body).not.toMatch(/It is not a probability that the player is a bargain/);
    expect(body).not.toMatch(/The board above was produced without any of these fields/);
    // ...but the compact markers that stop a number being misread are still on the card.
    expect(screen.getByText("Market data")).toBeDefined();
    expect(screen.getAllByText("approximate cohort").length).toBeGreaterThan(0);
  });

  /**
   * WCAG 2.2 "Focus Order": closing a dialog must not drop the keyboard user at the top of
   * the document. `userEvent` rather than `fireEvent` because a real pointer press focuses
   * the button it lands on and `fireEvent.click` does not, so the cheaper helper would be
   * testing a situation that cannot happen.
   */
  it("restores focus to the row that opened it", async () => {
    const user = userEvent.setup();
    render(<App />);
    await boardReady();
    const trigger = screen.getByRole("button", { name: "Amon-Ra Bright" });
    await user.click(trigger);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Amon-Ra Bright" })).toBeDefined();
    });
    await user.click(screen.getByRole("button", { name: "Close player detail" }));
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });
});

describe("degraded states", () => {
  it("keeps the tier board fully usable when arbitrage is missing", async () => {
    serve({ "arbitrage.json": MISSING });
    render(<App />);
    await boardReady();
    const table = screen.getByRole("table", { name: /Intrinsic tier board/ });
    expect(within(table).getAllByRole("row")).toHaveLength(19);
    fireEvent.click(screen.getByRole("tab", { name: /Arbitrage/ }));
    await waitFor(() => {
      expect(screen.getByText(/Market comparison unavailable/)).toBeDefined();
    });
    expect(screen.getByText(/tier board is unaffected/)).toBeDefined();
  });

  it("keeps every model value when player status is missing", async () => {
    serve({ "player_status.json": MISSING });
    render(<App />);
    await boardReady();
    expect(screen.queryByText("Q · Hamstring")).toBeNull();
    const table = screen.getByRole("table", { name: /Intrinsic tier board/ });
    const cells = within(table).getAllByRole("row")[1]?.querySelectorAll("td") ?? [];
    expect(cells[7]?.textContent).toBe("135.4");
  });

  it("reports the degraded annotation source in the data view", async () => {
    serve({ "player_status.json": MISSING });
    go("?view=data");
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("Degraded artifacts.")).toBeDefined();
    });
    expect(screen.getByText(/injury and roster annotations are absent/i)).toBeDefined();
  });

  it("refuses an unsupported tier contract and names both versions", async () => {
    serve({ "tiers.json": tierEnvelope("2.0") });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
    });
    expect(screen.getByText("Incompatible data contract")).toBeDefined();
    expect(screen.getByText("2.0")).toBeDefined();
    expect(screen.getByText("1.0")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("data view", () => {
  beforeEach(() => {
    go("?view=data");
  });

  it("reads the model and methodology versions from metadata", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Current build" })).toBeDefined();
    });
    expect(screen.getByText("intrinsic-cb-hurdle-v1")).toBeDefined();
    expect(screen.getByText("phase4_intrinsic_v1")).toBeDefined();
    expect(screen.getByText("baseline · a0_rank_gap_v1")).toBeDefined();
  });

  it("lists source freshness from the build's own report", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Freshness and source status" })).toBeDefined();
    });
    const table = screen.getByRole("table", { name: /Every row is reported by the build/ });
    expect(within(table).getByText("MyFantasyLeague ADP export")).toBeDefined();
    expect(within(table).getByText("Sleeper")).toBeDefined();
    expect(within(table).getByText("nflverse (via nflreadpy)")).toBeDefined();
  });

  it("states the current limitations rather than hiding them", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Current limitations" })).toBeDefined();
    });
    for (const phrase of [
      /Exact tier edges are soft/,
      /measured convergence limitation/,
      /only market source in V1/,
      /Injury and roster status is annotation only/,
      /Market trend is measured only over our own snapshots/,
      /Rookie projections are lower-information/,
      /simulated independently/,
    ]) {
      expect(screen.getByText(phrase)).toBeDefined();
    }
  });

  it("attributes the sources production actually used, and not FantasyPros", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Sources and attribution" })).toBeDefined();
    });
    expect(screen.getByText("nflverse")).toBeDefined();
    expect(screen.getByText("MyFantasyLeague")).toBeDefined();
    expect(screen.getByText(/free for non-commercial use/)).toBeDefined();
    expect(document.body.textContent).not.toMatch(/fantasypros|fantasycalc/i);
  });
});

/**
 * Phase 9A — the design source's three player-card variants, and the shell it sits in.
 *
 * `docs/DESIGN_SOURCE_MAP.md` section 4 is the mapping: 1c on a desktop, 1a on a tablet, 1b —
 * a tabbed sheet — on a phone. Two of the three are pure layout and belong to the visual-QA
 * pass; the sheet is not, because a tab list is a different accessibility tree, so it is a
 * real branch and it is tested here.
 */
describe("player card variants", () => {
  const SHEET = "(max-width: 767px)";

  async function openCard(name: string): Promise<HTMLElement> {
    render(<App now={FIXTURE_NOW} />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name })).toBeDefined();
    });
    return screen.getByRole("dialog");
  }

  it("renders every section at once above the sheet breakpoint, with no tab list", async () => {
    const dialog = await openCard("Amon-Ra Bright");
    expect(within(dialog).queryByRole("tablist")).toBeNull();
    for (const heading of ["Intrinsic value", "Draft market", "Current status"]) {
      expect(within(dialog).getByRole("heading", { name: heading })).toBeDefined();
    }
  });

  it("becomes a tabbed sheet below it, showing one section at a time", async () => {
    setMediaQuery(SHEET, true);
    const dialog = await openCard("Amon-Ra Bright");

    const tabs = within(dialog).getByRole("tablist");
    expect(within(tabs).getAllByRole("tab")).toHaveLength(3);
    // One panel, and it is the first tab's.
    expect(within(dialog).getAllByRole("tabpanel")).toHaveLength(1);
    expect(within(dialog).getByRole("heading", { name: "Intrinsic value" })).toBeDefined();
    expect(within(dialog).queryByRole("heading", { name: "Draft market" })).toBeNull();

    fireEvent.click(within(tabs).getByRole("tab", { name: "Draft market" }));
    expect(within(dialog).getByRole("heading", { name: "Draft market" })).toBeDefined();
    expect(within(dialog).queryByRole("heading", { name: "Intrinsic value" })).toBeNull();
    expect(within(tabs).getByRole("tab", { name: "Draft market" }).getAttribute("aria-selected")).toBe("true");
  });

  it("moves between tabs with the arrow keys, and wraps", async () => {
    setMediaQuery(SHEET, true);
    const dialog = await openCard("Amon-Ra Bright");
    const tabs = within(dialog).getByRole("tablist");
    const first = within(tabs).getByRole("tab", { name: "Intrinsic value" });

    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(within(dialog).getByRole("heading", { name: "Draft market" })).toBeDefined();

    fireEvent.keyDown(within(tabs).getByRole("tab", { name: "Draft market" }), { key: "ArrowLeft" });
    expect(within(dialog).getByRole("heading", { name: "Intrinsic value" })).toBeDefined();

    fireEvent.keyDown(first, { key: "ArrowLeft" });
    expect(within(dialog).getByRole("heading", { name: "Current status" })).toBeDefined();
  });

  /**
   * A player the market has not priced still gets a market tab, and it says so. Dropping the
   * tab would make the tab set vary by player and would hide the very fact a drafter needs —
   * that he is fully ranked and simply has no price to compare against.
   */
  it("keeps the market tab for an unpriced player, and says there is no price", async () => {
    setMediaQuery(SHEET, true);
    const dialog = await openCard("Zach Ertz");
    const tabs = within(dialog).getByRole("tablist");
    expect(within(tabs).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Intrinsic value",
      "Draft market",
      "Current status",
    ]);
    fireEvent.click(within(tabs).getByRole("tab", { name: "Draft market" }));
    expect(within(dialog).getByText(/No current MyFantasyLeague ADP/)).toBeDefined();
  });

  /**
   * The rail is the same DOM in all three variants and always carries the accessible title,
   * which is what lets the layout move it without any variant duplicating the heading.
   */
  it("keeps one accessible title, in both variants", async () => {
    const wide = await openCard("Amon-Ra Bright");
    expect(within(wide).getAllByRole("heading", { name: "Amon-Ra Bright" })).toHaveLength(1);
    expect(wide.getAttribute("aria-labelledby")).not.toBeNull();
  });

  it("leads with fair rank, the market verdict and the status line, in every variant", async () => {
    for (const sheet of [false, true]) {
      setMediaQuery(SHEET, sheet);
      const dialog = await openCard("Amon-Ra Bright");
      for (const label of ["Fair rank", "Market verdict", "Arbitrage score", "Status"]) {
        expect(within(dialog).getByText(label, { exact: true })).toBeDefined();
      }
      cleanup();
    }
  });
});

describe("the shell", () => {
  it("prints the shown and published row counts beside the navigation", async () => {
    render(<App now={FIXTURE_NOW} />);
    await boardReady();

    /*
     * Both numbers are counts of artifact rows for the preset on screen. They are checked
     * against the table beside them rather than against a fixture length: `tierRecords()`
     * spans every published preset, and a readout that agreed with *that* would be counting
     * rows this board does not show.
     */
    const rowsInTable = (): number =>
      within(screen.getByRole("table", { name: /Intrinsic tier board/ })).getAllByRole("row")
        .length - 1;

    const total = rowsInTable();
    expect(total).toBeGreaterThan(0);
    expect(screen.getByText(`${String(total)} of ${String(total)} rows`)).toBeDefined();

    fireEvent.click(screen.getByRole("radio", { name: "QB" }));
    await waitFor(() => {
      const shown = rowsInTable();
      expect(shown).toBeLessThan(total);
      expect(screen.getByText(`${String(shown)} of ${String(total)} rows`)).toBeDefined();
    });
  });

  /**
   * The slash shortcut the design source advertises with a key hint inside the field. It must
   * never eat a character someone is typing, which is the whole risk of a bare-key shortcut.
   */
  it("focuses the search box on / but never while text is being typed", async () => {
    render(<App now={FIXTURE_NOW} />);
    await boardReady();
    const search = screen.getByLabelText("Player search");

    fireEvent.keyDown(document.body, { key: "/" });
    expect(document.activeElement).toBe(search);

    // Already in the field: the keystroke is a character, not a command.
    const before = document.activeElement;
    fireEvent.keyDown(search, { key: "/" });
    expect(document.activeElement).toBe(before);

    // A modifier is somebody else's shortcut.
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(document.body, { key: "/", ctrlKey: true });
    expect(document.activeElement).not.toBe(search);
  });
});
