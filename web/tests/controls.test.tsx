/**
 * Controls and keyboard behaviour.
 *
 * The segmented controls are radio groups, so a screen reader hears "2 of 3" rather than three
 * independent pressed buttons, and arrow keys move within the group while Tab leaves it. The
 * charts follow the same composite-widget pattern for the same reason (`docs/UX_SPEC.md` 12).
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import {
  arbitrageEnvelope,
  buildMetadata,
  playerStatusEnvelope,
  projectionEnvelope,
  tierEnvelope,
} from "./fixtures/artifacts";

function serve(): void {
  const payloads: Record<string, unknown> = {
    "build_metadata.json": buildMetadata(),
    "tiers.json": tierEnvelope(),
    "arbitrage.json": arbitrageEnvelope(),
    "player_status.json": playerStatusEnvelope(),
    "projections.json": projectionEnvelope(),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const payload = payloads[input.split("/").pop() ?? ""];
      return Promise.resolve({
        ok: payload !== undefined,
        status: payload === undefined ? 404 : 200,
        json: () => Promise.resolve(payload ?? null),
      } as Response);
    }),
  );
}

async function boardReady(): Promise<void> {
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Tier board" })).toBeDefined();
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  serve();
});

describe("segmented controls", () => {
  it("exposes each control as a labelled radio group", async () => {
    render(<App />);
    await boardReady();
    for (const name of ["Scoring", "Teams", "Position"]) {
      const group = screen.getByRole("radiogroup", { name });
      expect(within(group).getAllByRole("radio").length).toBeGreaterThan(1);
    }
  });

  it("keeps one tab stop per group and moves the selection with arrow keys", async () => {
    render(<App />);
    await boardReady();
    const group = screen.getByRole("radiogroup", { name: "Position" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.filter((radio) => radio.getAttribute("tabindex") === "0")).toHaveLength(1);
    const first = radios[0];
    expect(first).toBeDefined();
    if (first === undefined) return;
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    await waitFor(() => {
      expect(window.location.search).toBe("?position=qb");
    });
  });

  it("only offers presets the build published", async () => {
    render(<App />);
    await boardReady();
    const teams = screen.getByRole("radiogroup", { name: "Teams" });
    for (const radio of within(teams).getAllByRole("radio")) {
      expect(radio.hasAttribute("disabled")).toBe(false);
    }
  });
});

describe("view tabs", () => {
  it("is a tablist whose panel is labelled by the active tab", async () => {
    render(<App />);
    await boardReady();
    const tabs = screen.getByRole("tablist", { name: "Board" });
    expect(within(tabs).getAllByRole("tab")).toHaveLength(3);
    const panel = screen.getByRole("tabpanel");
    expect(panel.getAttribute("aria-labelledby")).toBe("tab-tiers");
  });

  it("moves between tabs with arrow keys", async () => {
    render(<App />);
    await boardReady();
    const tab = screen.getByRole("tab", { name: /Tiers/ });
    tab.focus();
    fireEvent.keyDown(tab, { key: "ArrowRight" });
    await waitFor(() => {
      expect(window.location.search).toBe("?view=arbitrage");
    });
  });
});

describe("player search", () => {
  it("clears from the keyboard with Escape and from the clear button", async () => {
    const user = userEvent.setup();
    render(<App />);
    await boardReady();
    const input = screen.getByLabelText("Player search");
    await user.type(input, "burrow");
    await waitFor(() => {
      expect(window.location.search).toBe("?search=burrow");
    });
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(window.location.search).toBe("");
    });
    await user.type(input, "ertz");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Clear player search" })).toBeDefined();
    });
    await user.click(screen.getByRole("button", { name: "Clear player search" }));
    await waitFor(() => {
      expect(window.location.search).toBe("");
    });
  });

  it("adopts a search supplied by the URL", async () => {
    window.history.replaceState(null, "", "/?search=pitts");
    render(<App />);
    await boardReady();
    expect(screen.getByLabelText<HTMLInputElement>("Player search").value).toBe("pitts");
  });
});

describe("chart keyboard access", () => {
  it("gives the tier board one tab stop and moves between marks with arrows", async () => {
    render(<App />);
    await boardReady();
    const marks = screen.getAllByRole("button", { name: /median simulated VORP/ });
    expect(marks.filter((mark) => mark.getAttribute("tabindex") === "0")).toHaveLength(1);
    const first = marks.find((mark) => mark.getAttribute("tabindex") === "0");
    expect(first?.getAttribute("aria-label")).toMatch(/^Bijan Robinson,/);
  });

  it("opens the detail dialog from a focused chart mark", async () => {
    render(<App />);
    await boardReady();
    const mark = screen.getByRole("button", { name: /^Joe Burrow,.*median simulated VORP/ });
    fireEvent.keyDown(mark, { key: "Enter" });
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Joe Burrow" })).toBeDefined();
    });
  });

  it("provides a skip link to the board", async () => {
    render(<App />);
    await boardReady();
    const skip = screen.getByRole("link", { name: /Skip to the board/ });
    expect(skip.getAttribute("href")).toBe("#board");
  });
});

describe("export controls", () => {
  it("links the full CSV to the generated artifact rather than regenerating it", async () => {
    render(<App />);
    await boardReady();
    const link = screen.getByRole("link", { name: "Download full CSV" });
    expect(link.getAttribute("href")).toMatch(/data\/tiers\.csv$/);
    expect(link.hasAttribute("download")).toBe(true);
  });

  it("names the filtered export with the row count it will write", async () => {
    render(<App />);
    await boardReady();
    expect(screen.getByRole("button", { name: "Export filtered CSV (10)" })).toBeDefined();
    fireEvent.click(screen.getByRole("radio", { name: "TE" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Export filtered CSV (3)" })).toBeDefined();
    });
  });

  it("writes a file named from the build date and the current preset", async () => {
    render(<App />);
    await boardReady();
    const created: { href: string; download: string }[] = [];
    // The export builds an anchor and clicks it; intercepting the click on the prototype is how
    // the filename becomes observable without the environment actually saving a file.
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function click(
      this: HTMLAnchorElement,
    ): void {
      created.push({ href: this.href, download: this.download });
    });
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });

    fireEvent.click(screen.getByRole("button", { name: /Export filtered CSV/ }));
    expect(created[0]?.download).toBe("ffdraft-tiers-ppr-12-2026-08-21.csv");
  });
});
