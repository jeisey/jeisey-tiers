/**
 * The application, rendered.
 *
 * These are the behavioural guarantees the exit gate names: state lives in the URL, the tables
 * agree with the charts, a degraded optional artifact does not invalidate the tier board, and
 * an unsupported contract refuses rather than guesses.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { ANNOTATION_DISCLOSURE } from "../src/app/PlayerDetail";
import {
  arbitrageEnvelope,
  arbitrageRecords,
  buildMetadata,
  playerStatusEnvelope,
  projectionEnvelope,
  tierEnvelope,
  tierRecords,
} from "./fixtures/artifacts";

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
    render(<App />);
    await boardReady();
    const chip = screen.getByRole("button", { name: /build note/i });
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

  it("explains the shared low-confidence condition once, with numbers from metadata", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Every row on this board reads low market-data confidence/i)).toBeDefined();
    });
    expect(screen.getByText(/125 drafts against the 300/)).toBeDefined();
    expect(screen.getByText(/Market-data quality/)).toBeDefined();
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

describe("player detail", () => {
  it("opens from a tier table row and discloses that status is annotation only", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Amon-Ra Bright" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Amon-Ra Bright" })).toBeDefined();
    });
    expect(screen.getByText("Questionable")).toBeDefined();
    expect(screen.getByText("Hamstring")).toBeDefined();
    expect(screen.getByText(ANNOTATION_DISCLOSURE)).toBeDefined();
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
    expect(screen.getByText(/absence of a report, not a clearance/)).toBeDefined();
    expect(document.body.textContent).not.toMatch(/\bhealthy\b/i);
  });

  it("handles a player with no status record at all", async () => {
    render(<App />);
    await boardReady();
    fireEvent.click(screen.getByRole("button", { name: "Deebo Gray" }));
    await waitFor(() => {
      expect(screen.getByText(/No current status record was published/)).toBeDefined();
    });
    // His model values are still there.
    expect(screen.getByText("Fair rank")).toBeDefined();
  });
});

describe("degraded states", () => {
  it("keeps the tier board fully usable when arbitrage is missing", async () => {
    serve({ "arbitrage.json": MISSING });
    render(<App />);
    await boardReady();
    const table = screen.getByRole("table", { name: /Intrinsic tier board/ });
    expect(within(table).getAllByRole("row")).toHaveLength(11);
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
      /Market trend needs history/,
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
