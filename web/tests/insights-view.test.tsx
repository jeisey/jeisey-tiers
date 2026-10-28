/**
 * The Insights tab (ADR-116) as a reader meets it: from the tab, from a shared link, across a
 * kickoff with the page left open, through the copy and share actions, and in every state the
 * build can leave it in.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { fixtureFiles, inSeasonFixtureFiles } from "./fixtures/artifacts";
import { INSIGHT_IDS, KICKOFF_EARLY, LONG_NAME, type InsightsFixtureMode } from "./fixtures/insights";
import { required } from "./required";
import { stubSite } from "./site";

/** Thursday before the week-9 Sunday: every week-9 game is still to come. */
const BEFORE_KICKOFFS = new Date("2026-11-05T12:00:00Z");

function go(query = ""): void {
  window.history.replaceState(null, "", `/${query}`);
}

function params(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

function serve(mode: InsightsFixtureMode = "present"): void {
  stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true, { insights: mode }) });
}

async function open(query = "?view=insights", now?: Date): Promise<void> {
  go(query);
  render(now === undefined ? <App /> : <App now={now} />);
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Insights", level: 2 })).toBeDefined();
  });
}

/** The async Clipboard API, replaced for one test (jsdom has none). */
function clipboard(writeText: (text: string) => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

function story(id: string): HTMLElement {
  const node = document.getElementById(`story-${id}`);
  if (node === null) throw new Error(`no story ${id} on the page`);
  return node;
}

function headlines(group: string): string[] {
  const section = required(
    screen.getByRole("heading", { name: new RegExp(group) }).closest("section"),
    group,
  );
  return within(section)
    .getAllByRole("article")
    .map((article) => article.getAttribute("data-story") ?? "");
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: BEFORE_KICKOFFS });
  go();
  serve();
});

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
  vi.useRealTimers();
  vi.unstubAllGlobals();
  cleanup();
  go();
});

describe("the tab", () => {
  it("sits after My Leagues, and leads with the build's lead order", async () => {
    await open();
    const tabs = within(screen.getByRole("tablist", { name: "Board" })).getAllByRole("tab");
    expect(tabs.map((tab) => tab.id)).toEqual([
      "tab-ros",
      "tab-myleagues",
      "tab-insights",
      "tab-startsit",
      "tab-trade",
      "tab-opportunity",
      "tab-potw",
      "tab-data",
    ]);
    expect(screen.getByRole("tab", { name: "Insights" }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Lead stories" })).toBeDefined();
    });
    expect(screen.getByText(/Week 8 edition · through W8 · built/)).toBeDefined();
    expect(screen.getByText("Same in every league size: the Teams setting changes nothing here.")).toBeDefined();
    expect(headlines("Lead stories")).toEqual([
      INSIGHT_IDS.upsideLead,
      INSIGHT_IDS.openingObserved,
      INSIGHT_IDS.volumeLagging,
      INSIGHT_IDS.streakBreakout,
      INSIGHT_IDS.roleBackfield,
      INSIGHT_IDS.pacePerGame,
      INSIGHT_IDS.upsideDeep,
      INSIGHT_IDS.openingProspective,
      INSIGHT_IDS.volumeShrinking,
      INSIGHT_IDS.streakTouchdowns,
      INSIGHT_IDS.roleReceiving,
    ]);
    expect(headlines("More findings")).toEqual([
      INSIGHT_IDS.upsideLongName,
      INSIGHT_IDS.upsideDoubtful,
      INSIGHT_IDS.streakQuiet,
      INSIGHT_IDS.paceOverlooked,
    ]);
  });

  it("prints each card whole: kicker, reading, every fact's basis, the chart in words, caveat and sources", async () => {
    await open();
    const card = story(INSIGHT_IDS.upsideLead);
    expect(within(card).getByText("This week's upside · Week 9")).toBeDefined();
    expect(within(card).getByRole("heading", { level: 4 }).textContent).toBe("Puka Nightingale: a 22.4-point ceiling at 31% rostered");
    expect(within(card).getByText("Reading")).toBeDefined();
    expect(within(card).getAllByText("Model").length).toBe(2);
    expect(within(card).getByText("Observed")).toBeDefined();
    expect(within(card).getByText("ESPN")).toBeDefined();
    expect(within(card).getByText(/P90: one week in ten/)).toBeDefined();
    expect(within(card).getByText(/^What could undermine it$/)).toBeDefined();
    expect(within(card).getByText("nflverse (CC-BY 4.0) · weekly-startsit-v1 model · ESPN roster % (espn.com)")).toBeDefined();
    expect(within(card).getByText("Jeisey Tiers")).toBeDefined();
    // The chart is decoration for assistive technology; its sentence carries the numbers.
    expect(card.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(within(card).getByText(/ceiling \(1 week in 10\) 22\.4 points/)).toBeDefined();
    // A story with no counterpoint prints none.
    expect(within(story(INSIGHT_IDS.openingProspective)).queryByText(/What could undermine it/)).toBeNull();
    // A role battle is the same in every scoring, and says so.
    expect(within(story(INSIGHT_IDS.roleBackfield)).getByText("Same in every scoring")).toBeDefined();
  });

  it("opens the Evidence: every predicate with its value and threshold, and the exact values", async () => {
    await open();
    const fetched = (): string[] =>
      vi
        .mocked(fetch)
        .mock.calls.map((call) => call[0] as string)
        .filter((url) => url.includes("/serve/insight_evidence/"));
    // Opening the tab fetched no evidence.
    expect(fetched()).toEqual([]);
    const card = story(INSIGHT_IDS.roleReceiving);
    fireEvent.click(within(card).getByRole("button", { name: "Evidence" }));
    // The chart's exact values are in the feed and show at once; the predicates arrive.
    expect(within(card).getByRole("region", { name: /Exact values/ })).toBeDefined();
    const qualification = await within(card).findByRole("region", { name: "Qualification" });
    expect(within(qualification).getByText("Largest share change in the room, at least")).toBeDefined();
    expect(within(qualification).getByText("0.11")).toBeDefined();
    expect(within(qualification).getByText("0.06")).toBeDefined();
    const exact = within(card).getByRole("region", { name: /Exact values/ });
    // A null red-zone count is a dash, never a zero.
    const terry = required(within(exact).getByText("Terry Mack (WR)").closest("tr"), "row");
    expect(within(terry).getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(within(card).getByRole("button", { name: "Hide evidence" }).getAttribute("aria-expanded")).toBe("true");
    // The named values behind the story, exactly as published: an unknown count is a dash.
    expect(within(card).getByText("Pbp state")).toBeDefined();
    expect(within(required(within(card).getByText("Team red zone").parentElement, "row")).getByText("—")).toBeDefined();
    // A second story's Evidence reuses the slice: one fetch per preset.
    const other = story(INSIGHT_IDS.pacePerGame);
    fireEvent.click(within(other).getByRole("button", { name: "Evidence" }));
    await within(other).findByRole("region", { name: "Qualification" });
    expect(fetched()).toHaveLength(1);
    expect(fetched()[0]).toMatch(/\/serve\/insight_evidence\/PPR\./);
  });

  it("opens a player's card from his name", async () => {
    await open();
    fireEvent.click(within(story(INSIGHT_IDS.pacePerGame)).getByRole("button", { name: "Joe Burrow" }));
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /Joe Burrow/ })).toBeDefined();
    });
  });
});

describe("filters in the URL", () => {
  it("filters by family and reads the upside family under the ESPN ceiling", async () => {
    await open();
    await waitFor(() => {
      expect(screen.getByRole("radiogroup", { name: "Show" })).toBeDefined();
    });
    fireEvent.click(screen.getByRole("radio", { name: /^Role battles, 2 stories/ }));
    expect(params().get("ins")).toBe("roles");
    await waitFor(() => {
      expect(screen.getAllByRole("article").map((node) => node.getAttribute("data-family"))).toEqual(["role_battle", "role_battle"]);
    });
    // The ceiling applies to upside stories only, so it is offered only where they can show.
    expect(screen.queryByRole("radiogroup", { name: /ESPN rostered below/ })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /^This week, 5 stories/ }));
    const ceiling = await screen.findByRole("radiogroup", { name: /ESPN rostered below/ });
    expect(screen.getByText("ESPN leagues, not yours; an unknown share is not 0%.")).toBeDefined();
    fireEvent.click(within(ceiling).getByRole("radio", { name: /fewer than 10%/ }));
    expect(params().get("ceil")).toBe("10");
    await waitFor(() => {
      expect(screen.getAllByRole("article").map((node) => node.getAttribute("data-story"))).toEqual([
        INSIGHT_IDS.openingObserved,
        INSIGHT_IDS.upsideDeep,
        INSIGHT_IDS.upsideLongName,
      ]);
    });
    expect(within(ceiling).getByRole("radio", { name: /fewer than 10%/ }).getAttribute("aria-checked")).toBe("true");
  });

  it("finds a player's stories through the search, and says what is filtering", async () => {
    await open("?view=insights&search=valdes");
    await waitFor(() => {
      expect(screen.getAllByRole("article").map((node) => node.getAttribute("data-story"))).toEqual([INSIGHT_IDS.upsideLongName]);
    });
    expect(screen.getByText("stories matching “valdes”")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(params().get("search")).toBeNull();
  });

  it("says when nothing matches, and offers every story back", async () => {
    await open("?view=insights&search=nobody");
    const notice = await screen.findByText("No story matches these settings.");
    fireEvent.click(within(required(notice.parentElement, "notice")).getByRole("button", { name: "Show every story" }));
    expect(window.location.search).toBe("?view=insights");
  });
});

describe("links and editions", () => {
  it("focuses a linked story, and names an older edition before showing the current version", async () => {
    await open(`?view=insights&story=${INSIGHT_IDS.upsideLead}&ed=2026w07`);
    await waitFor(() => {
      expect(screen.getByText("This link is from the Week 7 edition; the current edition is Week 8.")).toBeDefined();
    });
    expect(screen.getByText(/Older editions are not kept/)).toBeDefined();
    const card = story(INSIGHT_IDS.upsideLead);
    expect(within(card).getByText("Updated for Week 8")).toBeDefined();
    // The evidence slice is fetched only when a reader asks for it, a linked story included.
    expect(within(card).getByRole("button", { name: "Evidence" }).getAttribute("aria-expanded")).toBe("false");
    await waitFor(() => {
      expect(document.activeElement).toBe(within(card).getByRole("heading", { level: 4 }));
    });
  });

  it("says a story from an older edition is no longer in the current one, never showing another", async () => {
    await open("?view=insights&story=upside-00-0099999&ed=2026w07");
    await waitFor(() => {
      expect(screen.getByText(/This story is no longer in the current edition\./)).toBeDefined();
    });
    expect(screen.queryByText(/Updated for Week 8/)).toBeNull();
  });

  it("says an unknown story in the current edition is not available", async () => {
    await open("?view=insights&story=upside-00-0099999&ed=2026w08");
    await waitFor(() => {
      expect(screen.getByText("This story is not available.")).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(window.location.search).toBe("?view=insights");
  });

  it("shows a linked story the current filter would hide, above the feed", async () => {
    await open(`?view=insights&story=${INSIGHT_IDS.pacePerGame}&ed=2026w08&ins=roles`);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Linked story" })).toBeDefined();
    });
    expect(screen.getByText("Shown although the current settings would hide it.")).toBeDefined();
    expect(within(story(INSIGHT_IDS.pacePerGame)).getByText("Linked story")).toBeDefined();
  });
});

describe("withdrawal at the reader's clock", () => {
  it("withdraws a start idea in place at kickoff, with the page left open", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date(Date.parse(KICKOFF_EARLY) - 90_000) });
    await open();
    await waitFor(() => {
      expect(story(INSIGHT_IDS.upsideLead)).toBeDefined();
    });
    expect(story(INSIGHT_IDS.upsideLead).getAttribute("data-withdrawn")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    await waitFor(() => {
      expect(story(INSIGHT_IDS.upsideLead).getAttribute("data-withdrawn")).toBe("true");
    });
    expect(within(story(INSIGHT_IDS.upsideLead)).getByText(/Kickoff passed — no longer a start idea\./)).toBeDefined();
    // The story as published stays one tap away, not a recommendation.
    expect(within(story(INSIGHT_IDS.upsideLead)).getByText("The story as published")).toBeDefined();
    // The Sunday-night game has not started; a completed-weeks story is never withdrawn.
    expect(story(INSIGHT_IDS.upsideDeep).getAttribute("data-withdrawn")).toBeNull();
    expect(story(INSIGHT_IDS.pacePerGame).getAttribute("data-withdrawn")).toBeNull();
  });

  it("withdraws a player the availability policy refuses, and keeps a Questionable one with its label", async () => {
    await open();
    await waitFor(() => {
      expect(story(INSIGHT_IDS.upsideDoubtful).getAttribute("data-withdrawn")).toBe("true");
    });
    expect(within(story(INSIGHT_IDS.upsideDoubtful)).getByText(/Doubtful this week — left out of the verdict/)).toBeDefined();
    const long = story(INSIGHT_IDS.upsideLongName);
    expect(long.getAttribute("data-withdrawn")).toBeNull();
    expect(within(long).getByText("Q")).toBeDefined();
    expect(within(long).getByRole("button", { name: LONG_NAME })).toBeDefined();
  });
});

describe("copy", () => {
  it("copies the story's link and its summary, and says so", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>(() => Promise.resolve());
    clipboard(writeText);
    await open();
    const card = story(INSIGHT_IDS.upsideLead);
    fireEvent.click(within(card).getByRole("button", { name: "Copy link" }));
    await waitFor(() => {
      expect(within(card).getByRole("status").textContent).toBe("Link copied.");
    });
    expect(writeText).toHaveBeenLastCalledWith(
      `${window.location.origin}/?view=insights&scoring=ppr&story=${INSIGHT_IDS.upsideLead}&ed=2026w08`,
    );
    fireEvent.click(within(card).getByRole("button", { name: "Copy summary" }));
    await waitFor(() => {
      expect(within(card).getByRole("status").textContent).toBe("Summary copied.");
    });
    const summary = String(writeText.mock.calls.at(-1)?.at(0));
    expect(summary.startsWith("Puka Nightingale: a 22.4-point ceiling at 31% rostered\n")).toBe(true);
    expect(summary).toContain("Caveat: P90: one week in ten");
  });

  it("says when the copy failed, and puts the text where it can be copied by hand", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>(() => Promise.reject(new Error("denied")));
    clipboard(writeText);
    await open();
    const card = story(INSIGHT_IDS.pacePerGame);
    fireEvent.click(within(card).getByRole("button", { name: "Copy link" }));
    await waitFor(() => {
      expect(within(card).getByRole("status").textContent).toBe("Could not copy the link. Select it below and copy it.");
    });
    const box = within(card).getByRole("textbox", { name: "Story link" });
    expect((box as HTMLTextAreaElement).value).toContain(`story=${INSIGHT_IDS.pacePerGame}&ed=2026w08`);
  });
});

describe("the share view", () => {
  it("opens from a card into the URL, previews the card, switches layout and closes", async () => {
    await open();
    fireEvent.click(within(story(INSIGHT_IDS.roleBackfield)).getByRole("button", { name: "Share" }));
    expect(params().get("share")).toBe("land");
    expect(params().get("story")).toBe(INSIGHT_IDS.roleBackfield);
    expect(params().get("ed")).toBe("2026w08");
    const dialog = await screen.findByRole("dialog", { name: "Share this story" });
    const image = await within(dialog).findByRole("img", { name: /Share card \(landscape\): BUF backfield/ });
    expect(image.getAttribute("width")).toBe("1200");
    expect(image.getAttribute("height")).toBe("675");
    expect(image.getAttribute("src")?.startsWith("data:image/svg+xml")).toBe(true);
    const preview = required(image.parentElement, "preview");
    expect(preview.getAttribute("data-fits")).toBe("true");
    expect(preview.getAttribute("data-overflow")).toBe("0");
    fireEvent.click(within(dialog).getByRole("radio", { name: /Portrait/ }));
    expect(params().get("share")).toBe("port");
    const portrait = await within(dialog).findByRole("img", { name: /Share card \(portrait\)/ });
    expect(portrait.getAttribute("width")).toBe("1080");
    expect(portrait.getAttribute("height")).toBe("1350");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(params().get("share")).toBeNull();
    });
    expect(params().get("story")).toBe(INSIGHT_IDS.roleBackfield);
  });

  it("closes when the reader leaves the tab", async () => {
    await open(`?view=insights&story=${INSIGHT_IDS.pacePerGame}&ed=2026w08&share=land`);
    await screen.findByRole("dialog", { name: "Share this story" });
    fireEvent.click(screen.getByRole("tab", { name: "Trade" }));
    expect(params().get("share")).toBeNull();
  });
});

describe("states", () => {
  it("an older deploy with no Insights says so", async () => {
    serve("absent");
    await open();
    await waitFor(() => {
      expect(screen.getByText("Insights are not available.")).toBeDefined();
    });
    expect(screen.getByText(/This build published no Insights/)).toBeDefined();
    expect(screen.queryByRole("article")).toBeNull();
  });

  it("a withheld edition gives the build's reason", async () => {
    serve("withheld");
    await open();
    await waitFor(() => {
      expect(screen.getByText("No Insights this week.")).toBeDefined();
    });
    expect(screen.getByText(/withheld its Insights: season actuals are withheld for this build/)).toBeDefined();
  });

  it("a published edition with no story says no story qualified, family by family", async () => {
    serve("empty");
    await open();
    await waitFor(() => {
      expect(screen.getByText("No story qualified in the Week 8 edition.")).toBeDefined();
    });
    expect(screen.getByText(/no player under 50% rostered had a confirmed role/)).toBeDefined();
    expect(screen.queryByRole("radiogroup", { name: "Show" })).toBeNull();
  });

  it("a family the build could not make is named with its reason, and the rest publish", async () => {
    serve("degraded");
    await open();
    await waitFor(() => {
      expect(screen.getByText(/Not built this week:/)).toBeDefined();
    });
    expect(screen.getByText("This week's upside — ESPN roster readings unavailable: weekly upside not built")).toBeDefined();
    expect(screen.getAllByRole("article").length).toBe(11);
    expect(screen.queryByRole("radiogroup", { name: /ESPN rostered below/ })).toBeNull();
  });

  it("flags a stale edition", async () => {
    await open();
    await waitFor(() => {
      expect(screen.getByText(/days ago — stale/)).toBeDefined();
    });
  });
});
