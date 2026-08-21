/**
 * Export.
 *
 * The filtered export has to be exactly what is on screen — same rows, same order — and it has
 * to survive a name with a comma or a quote in it. It also has to *not* invent the two ML
 * columns V1 has no model for (ADR-010).
 */

import { describe, expect, it } from "vitest";

import {
  ARBITRAGE_EXPORT_COLUMNS,
  TIER_EXPORT_COLUMNS,
  arbitrageRowsToCsv,
  escapeCsvValue,
  exportFilename,
  tierRowsToCsv,
  toCsv,
} from "../src/data/csv";
import { ArtifactIndex, selectArbitrageRows, selectTierRows } from "../src/data/model";
import { DEFAULT_STATE } from "../src/data/state";
import {
  arbitrageRecords,
  buildMetadata,
  playerStatusRecords,
  projectionRecords,
  tierRecords,
} from "./fixtures/artifacts";

const index = new ArtifactIndex({
  metadata: buildMetadata(),
  tiers: tierRecords(),
  arbitrage: arbitrageRecords(),
  playerStatus: playerStatusRecords(),
  projections: projectionRecords(),
});

describe("escapeCsvValue", () => {
  it("leaves an ordinary value alone", () => {
    expect(escapeCsvValue("Bijan Robinson")).toBe("Bijan Robinson");
    expect(escapeCsvValue(135.4)).toBe("135.4");
  });

  it("quotes a value containing a comma", () => {
    expect(escapeCsvValue("Robinson, Bijan")).toBe('"Robinson, Bijan"');
  });

  it("doubles an embedded quote", () => {
    expect(escapeCsvValue('He said "questionable"')).toBe('"He said ""questionable"""');
  });

  it("quotes a value containing a newline or carriage return", () => {
    expect(escapeCsvValue("line one\nline two")).toBe('"line one\nline two"');
    expect(escapeCsvValue("line one\r\nline two")).toBe('"line one\r\nline two"');
  });

  it("writes an empty cell for null and undefined, never the word null", () => {
    expect(escapeCsvValue(null)).toBe("");
    expect(escapeCsvValue(undefined)).toBe("");
  });
});

describe("toCsv", () => {
  it("writes CRLF line endings and a trailing newline", () => {
    expect(toCsv(["a", "b"], [[1, 2]])).toBe("a,b\r\n1,2\r\n");
  });
});

describe("tier export", () => {
  const rows = selectTierRows(index, DEFAULT_STATE);

  it("uses the documented stable column order", () => {
    const header = tierRowsToCsv(rows).split("\r\n")[0];
    expect(header).toBe(TIER_EXPORT_COLUMNS.join(","));
  });

  it("exports exactly the rows it was handed, in that order", () => {
    const csv = tierRowsToCsv(rows);
    const lines = csv.trim().split("\r\n").slice(1);
    expect(lines).toHaveLength(rows.length);
    lines.forEach((line, position) => {
      expect(line.split(",")[1]).toBe(rows[position]?.record.display_name);
    });
  });

  it("writes artifact values, not rendered strings", () => {
    const first = rows[0];
    const cells = tierRowsToCsv(rows).split("\r\n")[1]?.split(",") ?? [];
    expect(cells[0]).toBe(String(first?.record.fair_rank));
    expect(cells[7]).toBe(String(first?.record.expected_vorp));
    expect(cells[9]).toBe(String(first?.record.p50_vorp));
  });

  it("respects the current filters", () => {
    const filtered = selectTierRows(index, { ...DEFAULT_STATE, position: "te" });
    const lines = tierRowsToCsv(filtered).trim().split("\r\n").slice(1);
    expect(lines).toHaveLength(3);
    expect(lines.every((line) => line.includes(",TE,"))).toBe(true);
  });

  it("carries the injury annotation but leaves it blank where none was reported", () => {
    const csv = tierRowsToCsv(rows);
    expect(csv).toContain("Questionable,Hamstring");
    const deebo = csv.split("\r\n").find((line) => line.startsWith("") && line.includes("Deebo Gray"));
    expect(deebo?.endsWith(",,")).toBe(true);
  });
});

describe("arbitrage export", () => {
  const rows = selectArbitrageRows(index, DEFAULT_STATE);

  it("uses the documented stable column order", () => {
    const header = arbitrageRowsToCsv(rows).split("\r\n")[0];
    expect(header).toBe(ARBITRAGE_EXPORT_COLUMNS.join(","));
  });

  it("does not fabricate the two columns V1 has no model for", () => {
    const header = arbitrageRowsToCsv(rows).split("\r\n")[0] ?? "";
    expect(header).not.toContain("expected_surplus_vorp");
    expect(header).not.toContain("p_positive_surplus");
  });

  it("writes a null trend as an empty cell, not a zero", () => {
    const cells = arbitrageRowsToCsv(rows).split("\r\n")[1]?.split(",") ?? [];
    const trendIndex = ARBITRAGE_EXPORT_COLUMNS.indexOf("market_trend");
    expect(cells[trendIndex]).toBe("");
  });

  it("carries market provenance on every row", () => {
    const csv = arbitrageRowsToCsv(rows);
    expect(csv).toContain("myfantasyleague_adp");
    // No comma in the value, so it is written unquoted — quoting is by content, not by column.
    expect(csv).toContain("IS_KEEPER=N&IS_MOCK=0 (approximate cohort)");
  });

  it("preserves the visible order", () => {
    const lines = arbitrageRowsToCsv(rows).trim().split("\r\n").slice(1);
    lines.forEach((line, position) => {
      expect(line.split(",")[0]).toBe(String(rows[position]?.arbitrageRank));
    });
  });
});

describe("exportFilename", () => {
  it("names the board, the preset and the build date", () => {
    expect(exportFilename("tiers", "ppr", 12, "2026-08-21")).toBe("ffdraft-tiers-ppr-12-2026-08-21.csv");
    expect(exportFilename("arbitrage", "half", 14, "2026-08-21")).toBe(
      "ffdraft-arbitrage-half-14-2026-08-21.csv",
    );
  });
});
