/**
 * Shell rendering.
 *
 * Three behaviours matter in Phase 1: freshness comes from the artifact, an incompatible
 * version produces a visible refusal rather than a blank page, and the baseline-mode label
 * is shown rather than implied (ADR-010 truthfulness).
 */

import { render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";

const GOLDEN = resolve(__dirname, "../../tests/fixtures/artifacts/build_metadata.json");

function metadata(overrides: Record<string, unknown> = {}): unknown {
  return { ...(JSON.parse(readFileSync(GOLDEN, "utf-8")) as object), ...overrides };
}

function mockFetch(payload: unknown, ok = true): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok,
        status: ok ? 200 : 500,
        json: () => Promise.resolve(payload),
      } as Response),
    ),
  );
}

describe("App", () => {
  it("renders build facts read from the artifact", async () => {
    mockFetch(metadata());
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("fixture-20260818T120000Z")).toBeDefined();
    });
    expect(screen.getByText("fixture-stub-0")).toBeDefined();
    expect(screen.getByText("redraft-10, redraft-12")).toBeDefined();
  });

  it("labels baseline arbitrage rather than implying a model", async () => {
    mockFetch(metadata());
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/deterministic baseline/)).toBeDefined();
    });
  });

  it("refuses an incompatible schema version visibly", async () => {
    mockFetch(metadata({ schema_version: "2.0" }));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
    });
    expect(screen.getByText("Incompatible data")).toBeDefined();
  });

  it("explains how to generate artifacts when none are present", async () => {
    mockFetch({}, false);
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("No build data")).toBeDefined();
    });
    expect(screen.getByText(/build-fixture-artifacts/)).toBeDefined();
  });
});
