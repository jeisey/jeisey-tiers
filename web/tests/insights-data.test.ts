/**
 * Insights (ADR-116): the parser, the feed's selection, withdrawal, links and summaries, the URL
 * parameters and the share card — everything the tab decides without rendering.
 */

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { approximateMeasure, wrapText, type Measure } from "../src/app/insights/marks";
import { SHARE_SIZES, buildShareCard } from "../src/app/insights/shareCard";
import { readAvailability } from "../src/data/availability";
import type { InsightStoryRecord } from "../src/data/contracts";
import {
  KICKOFF_PASSED,
  ceilingRank,
  editionLabel,
  evidenceRows,
  exportFilename,
  humanizeKey,
  insightsState,
  kicker,
  evidenceByStory,
  parseInsightEvidence,
  parseInsightStories,
  parseInsightStory,
  parseInsightsMetadata,
  playerContext,
  scoringLabel,
  selectFeed,
  sourceLabels,
  storyLink,
  storyStanding,
  storySummary,
  windowText,
  type InsightStory,
} from "../src/data/insights";
import { DEFAULT_STATE, parseState, serializeState } from "../src/data/state";
import {
  INSIGHT_IDS,
  KICKOFF_EARLY,
  KICKOFF_SUNDAY_NIGHT,
  LONG_NAME,
  insightStories,
  insightsMetadata,
} from "./fixtures/insights";
import { required } from "./required";

const GOLDEN = resolve(__dirname, "../../tests/fixtures/artifacts/insights.json");

function ppr(): InsightStory[] {
  return insightStories("PPR").map((record) => required(parseInsightStory(record), record.story_id));
}

function byId(id: string): InsightStory {
  return required(
    ppr().find((story) => story.story_id === id),
    id,
  );
}

const EVIDENCE_FIELDS = ["evidence", "qualification", "also_qualifies"];

function served(record: InsightStoryRecord): Record<string, unknown> {
  // What the feed slice carries (`serving.py`): no record version and no evidence.
  return Object.fromEntries(
    Object.entries(record).filter(([key]) => key !== "schema_version" && !EVIDENCE_FIELDS.includes(key)),
  );
}

function servedEvidence(record: InsightStoryRecord): Record<string, unknown> {
  // What the evidence slice carries, fetched when a reader expands a story.
  return {
    scoring_preset: record.scoring_preset,
    story_id: record.story_id,
    player_id: record.player_id,
    evidence: record.evidence,
    qualification: record.qualification,
    also_qualifies: record.also_qualifies,
  };
}

describe("parseInsightStory", () => {
  it("accepts every fixture story, as a feed row, as a whole record, and its evidence row", () => {
    for (const preset of ["STD", "HALF", "PPR"] as const) {
      for (const record of insightStories(preset)) {
        expect(parseInsightStory(record), record.story_id).not.toBeNull();
        expect(parseInsightStory(served(record)), record.story_id).not.toBeNull();
        expect(parseInsightEvidence(servedEvidence(record)), record.story_id).not.toBeNull();
        // The feed's own copies equal the evidence they come from.
        expect(record.espn_rostered).toBe(typeof record.evidence.espn_rostered === "number" ? record.evidence.espn_rostered : null);
      }
    }
    const byStory = evidenceByStory(insightStories("PPR").map(servedEvidence));
    expect(byStory.get(INSIGHT_IDS.roleBackfield)?.qualification.length).toBeGreaterThan(0);
  });

  // The Python builder's committed golden: every record the validator passes must parse here.
  describe.skipIf(!existsSync(GOLDEN))("the Python golden insights.json", () => {
    it("parses every record, its feed row and its evidence row", () => {
      const envelope = JSON.parse(readFileSync(GOLDEN, "utf-8")) as { records: InsightStoryRecord[] };
      expect(envelope.records.length).toBeGreaterThan(0);
      const { stories, rejected } = parseInsightStories(envelope.records);
      expect(rejected).toBe(0);
      expect(stories).toHaveLength(envelope.records.length);
      for (const record of envelope.records) {
        expect(parseInsightStory(record), record.story_id).not.toBeNull();
        expect(parseInsightStory(served(record)), record.story_id).not.toBeNull();
        expect(parseInsightEvidence(servedEvidence(record)), record.story_id).not.toBeNull();
      }
    });
  });

  it.each([
    ["a record of another major version", { schema_version: "2.0" }],
    ["an unknown family", { family: "hot_take" }],
    ["an unknown variant", { variant: "due" }],
    ["an unknown horizon", { horizon: "next_year" }],
    ["a lead rank past 12", { lead_rank: 13 }],
    ["a malformed story id", { story_id: "Upside_00" }],
    ["a malformed edition", { edition: "2026-08" }],
    ["a non-GSIS player", { player_id: "sleeper:123" }],
    ["one fact", { facts: [{ label: "Only", value: "1", basis: "observed" }] }],
    ["a fact with an unknown basis", { facts: [{ label: "A", value: "1", basis: "vibes" }, { label: "B", value: "2", basis: "model" }] }],
    ["a missing caveat", { caveat: "" }],
    ["an unparseable kickoff", { kickoff_utc: "Sunday" }],
    ["an unknown chart", { chart: { type: "pie" } }],
    ["an interval with a null P90", { chart: { type: "interval", q10: 1, q50: 2, q90: null, typical_q10: null, typical_q50: null, typical_q90: null } }],
    ["a predicate that did not pass", { qualification: [{ rule: "x", label: "x", value: 1, threshold: 2, passed: false }] }],
    ["an unknown source", { sources: ["twitter"] }],
    ["an unknown source time", { source_times: { vibes_at: "2026-01-01T00:00:00Z" } }],
    ["evidence that is not an object", { evidence: [] }],
    ["an ESPN share over 100", { espn_rostered: 120 }],
    ["ceiling ranks without a 10% rank", { ceiling_ranks: { "50": 1, "25": 1 } }],
    ["a ceiling rank of 0", { ceiling_ranks: { "50": 0, "25": null, "10": null } }],
    ["an injury report with an unknown designation", { injury: { week: 9, designation: "Probable", practice_status: null, primary_injury: null } }],
  ])("rejects %s", (_name, patch) => {
    const record = { ...served(required(insightStories("PPR")[0], "first")), ...patch };
    expect(parseInsightStory(record)).toBeNull();
  });

  it.each([
    ["no evidence object", { evidence: null }],
    ["no predicate", { qualification: [] }],
    ["a malformed sibling id", { also_qualifies: ["Pace 9"] }],
    ["an unknown preset", { scoring_preset: "TEP" }],
  ])("rejects an evidence row with %s", (_name, patch) => {
    const row = { ...servedEvidence(required(insightStories("PPR")[0], "first")), ...patch };
    expect(parseInsightEvidence(row)).toBeNull();
  });

  it("rejects a week strip whose played week has a non-numeric value, and a room with one row", () => {
    const strip = served(byIdRecord(INSIGHT_IDS.volumeLagging));
    const chart = strip.chart as { weeks: Record<string, unknown>[] };
    const bad = { ...strip, chart: { ...chart, weeks: [{ ...chart.weeks[0], points: "12" }, ...chart.weeks.slice(1)] } };
    expect(parseInsightStory(bad)).toBeNull();
    const room = served(byIdRecord(INSIGHT_IDS.roleBackfield));
    const roomChart = room.chart as { rows: unknown[] };
    expect(parseInsightStory({ ...room, chart: { ...roomChart, rows: roomChart.rows.slice(0, 1) } })).toBeNull();
  });

  it("skips and counts what it rejects, and a second row with the same id", () => {
    const records = insightStories("PPR");
    const first = required(records[0], "first");
    const { stories, rejected } = parseInsightStories([...records, { ...first, family: "x" }, first, null, "story"]);
    expect(stories).toHaveLength(records.length);
    expect(rejected).toBe(4);
  });
});

function byIdRecord(id: string): InsightStoryRecord {
  return required(
    insightStories("PPR").find((record) => record.story_id === id),
    id,
  );
}

describe("the build's account (ros_build_metadata.insights)", () => {
  it("reads a published, a withheld and an empty account, and refuses a malformed one", () => {
    expect(parseInsightsMetadata(insightsMetadata())?.status).toBe("published");
    expect(parseInsightsMetadata(insightsMetadata("withheld"))?.withheld_reason).toMatch(/season actuals/);
    expect(parseInsightsMetadata(insightsMetadata("empty"))?.families.weekly_upside?.status).toBe("empty");
    expect(parseInsightsMetadata(null)).toBeNull();
    expect(parseInsightsMetadata({ ...insightsMetadata(), edition: "week 8" })).toBeNull();
    expect(parseInsightsMetadata({ ...insightsMetadata(), families: { x: { status: "maybe" } } })).toBeNull();
  });

  it("names the four states the tab keeps apart", () => {
    expect(insightsState({ published: false, compatible: false, meta: null }).kind).toBe("absent");
    expect(insightsState({ published: true, compatible: true, meta: null }).kind).toBe("absent");
    const withheld = insightsState({ published: false, compatible: false, meta: insightsMetadata("withheld") });
    expect(withheld.kind).toBe("withheld");
    expect(withheld.kind === "withheld" && withheld.reason).toMatch(/withheld its Insights: season actuals/);
    expect(insightsState({ published: true, compatible: false, meta: insightsMetadata() }).kind).toBe("incompatible");
    expect(insightsState({ published: true, compatible: true, meta: insightsMetadata() }).kind).toBe("published");
  });
});

describe("the feed", () => {
  const options = { ins: "all", ceil: 50, search: "", position: "all" } as const;

  it("leads in lead order, then every other story by the build's family order", () => {
    const feed = selectFeed(ppr(), { ...options, familyOrder: insightsMetadata().selection.family_order });
    expect(feed.lead.map((story) => story.lead_rank)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(feed.lead[0]?.story_id).toBe(INSIGHT_IDS.upsideLead);
    expect(feed.more.map((story) => story.story_id)).toEqual([
      // Upside under 50%: rank 1 before rank 2, positions interleaved (WR, RB, TE, QB).
      INSIGHT_IDS.upsideLongName,
      INSIGHT_IDS.upsideDoubtful,
      INSIGHT_IDS.streakQuiet,
      INSIGHT_IDS.paceOverlooked,
    ]);
  });

  it("filters by family, and `week` is the upside family plus every story about the target week", () => {
    const week = selectFeed(ppr(), { ...options, ins: "week" });
    const ids = [...week.lead, ...week.more].map((story) => story.story_id).sort();
    expect(ids).toEqual(
      [INSIGHT_IDS.upsideLead, INSIGHT_IDS.upsideDeep, INSIGHT_IDS.upsideDoubtful, INSIGHT_IDS.upsideLongName, INSIGHT_IDS.openingObserved].sort(),
    );
    const roles = selectFeed(ppr(), { ...options, ins: "roles" });
    expect([...roles.lead, ...roles.more].every((story) => story.family === "role_battle")).toBe(true);
    expect(week.counts).toEqual({ all: 15, week: 5, disappoint: 2, opening: 2, roles: 2, streaks: 3, pace: 2 });
  });

  it("reads the ESPN ceiling for upside only: a story shows under a ceiling where it has a rank, ordered by it", () => {
    const under25 = selectFeed(ppr(), { ...options, ceil: 25 });
    const upside = [...under25.lead, ...under25.more].filter((story) => story.family === "weekly_upside");
    // Puka (31.2%) has no rank under 25%; Vance leads; then rank 1s before rank 2s.
    expect(upside.map((story) => story.story_id)).toEqual([INSIGHT_IDS.upsideDeep, INSIGHT_IDS.upsideDoubtful, INSIGHT_IDS.upsideLongName]);
    expect(under25.hiddenByCeiling).toBe(1);
    // Other families are untouched by the ceiling.
    expect([...under25.lead, ...under25.more].filter((story) => story.family !== "weekly_upside")).toHaveLength(11);
    const under10 = selectFeed(ppr(), { ...options, ins: "week", ceil: 10 });
    expect([...under10.lead, ...under10.more].map((story) => story.story_id)).toEqual([
      INSIGHT_IDS.openingObserved,
      INSIGHT_IDS.upsideDeep,
      INSIGHT_IDS.upsideLongName,
    ]);
    expect(ceilingRank(byId(INSIGHT_IDS.upsideDoubtful), 25)).toBe(1);
    expect(ceilingRank(byId(INSIGHT_IDS.upsideDoubtful), 10)).toBeNull();
  });

  it("applies the player search and the position setting, and leaves a linked story out of the lists", () => {
    const searched = selectFeed(ppr(), { ...options, search: "valdes" });
    expect([...searched.lead, ...searched.more].map((story) => story.display_name)).toEqual([LONG_NAME]);
    const qbs = selectFeed(ppr(), { ...options, position: "qb" });
    expect([...qbs.lead, ...qbs.more].map((story) => story.display_name)).toEqual(["Joe Burrow", "Jalen Marsh"]);
    const linked = selectFeed(ppr(), { ...options, exclude: INSIGHT_IDS.upsideLead });
    expect(linked.lead.some((story) => story.story_id === INSIGHT_IDS.upsideLead)).toBe(false);
  });
});

describe("withdrawal", () => {
  const before = Date.parse(KICKOFF_EARLY) - 60_000;
  const after = Date.parse(KICKOFF_EARLY);

  it("withdraws a this-week story at kickoff, and only a this-week story", () => {
    const puka = byId(INSIGHT_IDS.upsideLead);
    expect(storyStanding(puka, before, null).withdrawn).toBe(false);
    expect(storyStanding(puka, after, null)).toMatchObject({ withdrawn: true, reason: KICKOFF_PASSED });
    // The Sunday-night game has not kicked off yet.
    expect(storyStanding(byId(INSIGHT_IDS.upsideDeep), after, null).withdrawn).toBe(false);
    expect(storyStanding(byId(INSIGHT_IDS.upsideDeep), Date.parse(KICKOFF_SUNDAY_NIGHT), null).withdrawn).toBe(true);
    // A completed-weeks story never is.
    expect(storyStanding(byId(INSIGHT_IDS.pacePerGame), Date.parse("2027-01-01T00:00:00Z"), null).withdrawn).toBe(false);
  });

  it("withdraws a player the availability policy would not feature, with the policy's reason", () => {
    const zay = byId(INSIGHT_IDS.upsideDoubtful);
    const doubtful = readAvailability({
      status: {
        player_id: zay.player_id,
        roster_status: "ACT",
        sleeper_status: "Active",
        injury_status: "Doubtful",
        observed_at_utc: "2026-08-21T14:00:00Z",
        quality_flags: [],
        season: 2026,
      },
      referenceTime: "2026-08-21T14:38:00Z",
      season: 2026,
    });
    const standing = storyStanding(zay, before, doubtful);
    expect(standing.withdrawn).toBe(true);
    expect(standing.reason).toMatch(/^Doubtful this week/);
    // Questionable stays a start idea, labelled by the policy.
    const questionable = readAvailability({
      status: null,
      report: { week: 9, designation: "Questionable", practice_status: null, primary_injury: "Hamstring" },
      referenceTime: "2026-08-21T14:38:00Z",
      season: 2026,
    });
    expect(storyStanding(byId(INSIGHT_IDS.upsideLongName), before, questionable).withdrawn).toBe(false);
  });
});

describe("words around a story", () => {
  it("prints the kicker, context, window, scoring and sources from the story", () => {
    const puka = byId(INSIGHT_IDS.upsideLead);
    expect(kicker(puka)).toBe("This week's upside · Week 9");
    expect(playerContext(puka)).toEqual(["WR", "LAR", "kickoff Sun, Nov 8, 1:00 PM ET"]);
    expect(windowText(puka)).toBe("W6–W8, baseline W1–W5");
    expect(scoringLabel(puka)).toBe("PPR scoring");
    expect(scoringLabel(byId(INSIGHT_IDS.roleBackfield))).toBe("Same in every scoring");
    expect(sourceLabels(puka)).toEqual(["nflverse (CC-BY 4.0)", "weekly-startsit-v1 model", "ESPN roster % (espn.com)"]);
    expect(windowText(byId(INSIGHT_IDS.pacePerGame))).toBe("Through Week 8");
    expect(editionLabel("2026w08")).toBe("Week 8");
  });

  it("links the story, its preset and its edition under the site's base path, and nothing else", () => {
    const puka = byId(INSIGHT_IDS.upsideLead);
    expect(storyLink("https://example.github.io", "/jeisey-tiers/", puka)).toBe(
      "https://example.github.io/jeisey-tiers/?view=insights&scoring=ppr&story=upside-00-0000012&ed=2026w08",
    );
    expect(storyLink("http://localhost:4173", "/", { ...puka, scoring_preset: "HALF" })).toBe(
      "http://localhost:4173/?view=insights&scoring=half&story=upside-00-0000012&ed=2026w08",
    );
    // A link parses back to the same story and edition, and opens the tab.
    const parsed = parseState("?view=insights&scoring=ppr&story=upside-00-0000012&ed=2026w08");
    expect(parsed.normalized).toBe(true);
    expect(parsed.state).toMatchObject({ view: "insights", story: "upside-00-0000012", ed: "2026w08" });
  });

  it("summarises in the story's own words, with the caveat, the edition and the link", () => {
    const zay = byId(INSIGHT_IDS.upsideDoubtful);
    const text = storySummary(zay, "https://x.test/?story=1", { withdrawn: true, reason: "Doubtful this week.", availability: null });
    expect(text.split("\n")[0]).toBe(zay.headline);
    expect(text).toContain("Withdrawn: Doubtful this week.");
    expect(text).toContain(`Reading: ${zay.dek}`);
    expect(text).toContain("• Rostered on ESPN: 22% (ESPN)");
    expect(text).toContain(`Caveat: ${zay.caveat}`);
    expect(text).toContain("Week 8 edition (2026w08)");
    expect(text.trim().endsWith("Jeisey Tiers — https://x.test/?story=1")).toBe(true);
    expect(exportFilename(zay, "port")).toBe("jeisey-tiers-upside-00-0000015-2026w08-portrait.png");
  });

  it("prints exact values exactly: no rounding, a dash for null, nested values flattened", () => {
    const rows = evidenceRows({ espn_rostered: 31.2, injury: null, ceiling_ranks: { "50": 1, "25": null }, weeks: [5, 7] });
    expect(rows).toEqual([
      ["ESPN rostered %", "31.2"],
      ["Official report", "—"],
      // Integer-like keys iterate in ascending order in JavaScript, whatever the JSON order.
      ["Rank under ESPN ceiling · 25", "—"],
      ["Rank under ESPN ceiling · 50", "1"],
      ["Weeks", "5, 7"],
    ]);
    expect(humanizeKey("matchup_q90_term")).toBe("Matchup P90 term");
  });
});

describe("URL state (ADR-116)", () => {
  it("round-trips the Insights parameters in a fixed order, defaults omitted", () => {
    const state = { ...DEFAULT_STATE, view: "insights", story: "role-buf-backfield", ed: "2026w08", ins: "roles", ceil: 10, share: "land" } as const;
    const href = serializeState(state);
    expect(href).toBe("?view=insights&story=role-buf-backfield&ed=2026w08&ins=roles&ceil=10&share=land");
    expect(parseState(href)).toEqual({ state, normalized: true });
    expect(serializeState({ ...DEFAULT_STATE, view: "insights" })).toBe("?view=insights");
  });

  it.each([
    ["an unknown filter", "?view=insights&ins=hot", "?view=insights"],
    ["an unknown ceiling", "?view=insights&ceil=33", "?view=insights"],
    ["a malformed story id", "?view=insights&story=DROP%20TABLE", "?view=insights"],
    ["an edition without a story", "?view=insights&ed=2026w08", "?view=insights"],
    ["a malformed edition", "?view=insights&story=pace-00-0000009&ed=w8", "?view=insights&story=pace-00-0000009"],
    ["a share view without a story", "?view=insights&share=land", "?view=insights"],
    ["an unknown share layout", "?view=insights&story=pace-00-0000009&share=square", "?view=insights&story=pace-00-0000009"],
  ])("normalizes %s", (_name, raw, canonical) => {
    const parsed = parseState(raw);
    expect(parsed.normalized).toBe(false);
    expect(serializeState(parsed.state)).toBe(canonical);
  });
});

describe("the share card", () => {
  const measure: Measure = approximateMeasure;
  const input = (story: InsightStory, layout: "land" | "port", withdrawn: string | null = null) => ({
    story,
    layout,
    measure,
    context: playerContext(story),
    withdrawn,
    edition: "Week 8 edition · through W8 · built Aug 21 · 10:38 AM ET",
    window: windowText(story),
    scoring: scoringLabel(story),
    sources: sourceLabels(story),
  });

  it.each(["land", "port"] as const)("is an SVG of exactly the %s size, with every part a capture needs", (layout) => {
    for (const story of ppr()) {
      const card = buildShareCard(input(story, layout));
      const svg = card.toSvg("", null);
      const { width, height } = SHARE_SIZES[layout];
      expect(svg.startsWith(`<svg xmlns="http://www.w3.org/2000/svg" width="${String(width)}" height="${String(height)}" viewBox="0 0 ${String(width)} ${String(height)}">`)).toBe(true);
      expect(card.fits, story.story_id).toBe(true);
      const text = card.texts.map((line) => line.text).join(" ");
      expect(text).toContain("CAVEAT");
      expect(text).toContain("JEISEY TIERS");
      expect(text).toContain("Week 8 edition");
      expect(text).toContain("Sources: nflverse (CC-BY 4.0)");
      expect(text).toContain(story.display_name.split(" ")[0]);
      expect(text).toContain(scoringLabel(story));
      // No line is wider than its box, and every line is inside the card.
      for (const line of card.texts) {
        expect(line.width, line.text).toBeLessThanOrEqual(line.maxWidth + 0.5);
        expect(line.y, line.text).toBeLessThanOrEqual(height);
        expect(line.x, line.text).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("wraps a very long name rather than clipping it, and carries a withdrawal", () => {
    const long = byId(INSIGHT_IDS.upsideLongName);
    const renamed = { ...long, display_name: `${LONG_NAME} ${LONG_NAME}`, headline: `${LONG_NAME}-${LONG_NAME}: a 16.8-point ceiling at 4.1% rostered` };
    for (const layout of ["land", "port"] as const) {
      const card = buildShareCard(input(renamed, layout, KICKOFF_PASSED));
      expect(card.fits).toBe(true);
      expect(card.texts.some((line) => line.text.includes("Withdrawn — Kickoff passed"))).toBe(true);
      for (const line of card.texts) expect(line.width, line.text).toBeLessThanOrEqual(line.maxWidth + 0.5);
    }
    // The wrap itself: a hyphenated word longer than the line breaks after its hyphen.
    const style = { size: 40, weight: 700, face: "sans" } as const;
    const lines = wrapText("Valdes-Scantling-Valdes-Scantling", style, 400, measure);
    expect(lines.length).toBeGreaterThan(1);
    for (const line of lines) expect(measure(line, style)).toBeLessThanOrEqual(400);
    expect(lines.join("")).toBe("Valdes-Scantling-Valdes-Scantling");
  });

  it("embeds the faces and the logo it is given, and escapes the story's text", () => {
    const story = { ...byId(INSIGHT_IDS.pacePerGame), headline: "Burrow <b>& friends</b>: QB4 in points a game" };
    const svg = buildShareCard(input(story, "land")).toSvg("@font-face{font-family:'Exo 2'}", "data:image/png;base64,AAAA");
    expect(svg).toContain("<style>@font-face{font-family:'Exo 2'}</style>");
    expect(svg).toContain('href="data:image/png;base64,AAAA"');
    expect(svg).toContain("Burrow &lt;b&gt;&amp; friends&lt;/b&gt;");
    expect(svg).not.toContain("<b>");
  });
});
