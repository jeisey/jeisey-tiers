/**
 * Unsigned and newly signed NFL players in the in-season views (ADR-102).
 *
 * On 2026-10-06 Tyreek Hill (released, unsigned) was Sleeper's fifth-most-added player and
 * Joe Mixon (signed by Seattle the day before, not yet on the roster file) its tenth; neither
 * could be found in season. The fixture carries both shapes on fictional players: Darnell
 * Ashby, verified unsigned with 2,400 adds and no model output, and Corey Halvorsen, signed on
 * Sleeper evidence only. What is tested is what a reader sees and what the decision tabs do.
 */

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/App";
import { AvailabilityContext, TeamCell } from "../src/components/primitives";
import {
  featureable,
  readAvailability,
  rosActionable,
  startEligible,
  startExclusion,
  tradeOutgoing,
  tradeTargetBlock,
  type StatusEvidence,
} from "../src/data/availability";
import { InSeasonBundle, displayTeam, isUnprojected, selectRosRows } from "../src/data/ros";
import { DEFAULT_STATE } from "../src/data/state";
import {
  FIXTURE_GENERATED_AT,
  FIXTURE_SIGNING_ID,
  FIXTURE_UNSIGNED_ID,
  fixtureFiles,
  inSeasonFixtureFiles,
  inSeasonPlayerStatusRecords,
  opportunityRecords,
  rosBuildMetadata,
  rosTierRecords,
  unprojectedRecords,
  weeklyProjectionRecords,
} from "./fixtures/artifacts";
import { required } from "./required";
import { stubSite } from "./site";

const BUILT = "2026-10-06T12:00:00Z";

function evidence(patch: Partial<StatusEvidence>): StatusEvidence {
  return {
    player_id: "gsis:00-0000099",
    season: 2026,
    roster_status: null,
    sleeper_status: "Active",
    injury_status: null,
    injury_body_part: null,
    observed_at_utc: "2026-10-06T11:00:00Z",
    quality_flags: ["no_current_roster_entry"],
    availability_override: null,
    ...patch,
  };
}

function read(patch: Partial<StatusEvidence>) {
  return readAvailability({ status: evidence(patch), referenceTime: BUILT, season: 2026 });
}

describe("the availability policy reads employment (ADR-102)", () => {
  it("makes a verified free agent a speculative stash, never a current-week choice", () => {
    const reading = read({ employment_status: "unsigned", employment_source: "sleeper", current_team: null });
    expect(reading.kind).toBe("unsigned");
    expect(reading.short).toBe("FA");
    expect(reading.headline).toBe("Unsigned free agent — speculative stash");
    expect(reading.week).toBe("unavailable");
    expect(reading.horizon).toBe("unavailable_now");
    expect(startEligible(reading)).toBe(false);
    expect(startExclusion(reading)).toMatch(/left out of the verdict/);
    expect(featureable(reading)).toBe(false);
    // Never a suggested trade target, even with the "expected back" opt-in, which is for
    // reserve lists; as an outgoing budget he is searched with a warning.
    expect(tradeTargetBlock(reading, false)).toBe("unavailable_now");
    expect(tradeTargetBlock(reading, true)).toBe("unavailable_now");
    expect(tradeOutgoing(reading)).toBe("warn");
    // Still listed: a stash is a rest-of-season question, not a season that is over.
    expect(rosActionable(reading)).toBe(true);
  });

  it("wins over a stale injury tag Sleeper keeps on a free agent", () => {
    const reading = read({ employment_status: "unsigned", employment_source: "sleeper", injury_status: "IR" });
    expect(reading.kind).toBe("unsigned");
  });

  it("calls a signing only Sleeper reports uncertain, and does not feature it", () => {
    const reading = read({ employment_status: "signed", employment_source: "sleeper", current_team: "SEA" });
    expect(reading.kind).toBe("signing");
    expect(reading.week).toBe("uncertain");
    expect(reading.detail).toMatch(/SEA/);
    expect(featureable(reading)).toBe(false);
  });

  it("supersedes a stale CUT once Sleeper reports the new club", () => {
    const reading = read({
      roster_status: "CUT",
      employment_status: "signed",
      employment_source: "sleeper",
      current_team: "SEA",
    });
    expect(reading.kind).toBe("signing");
  });

  it("never prints FA without verified evidence", () => {
    expect(displayTeam(null, "unknown")).toBeNull();
    expect(displayTeam(null, null)).toBeNull();
    expect(displayTeam("MIA", "unsigned")).toBe("FA");
    expect(displayTeam("SEA", "signed")).toBe("SEA");
    const unknown = read({ employment_status: "unknown" });
    expect(unknown.kind).not.toBe("unsigned");
    expect(unknown.short).not.toBe("FA");
  });
});

function bundle(): InSeasonBundle {
  return new InSeasonBundle({
    metadata: rosBuildMetadata(),
    rosTiers: rosTierRecords(),
    opportunity: [...opportunityRecords(), ...unprojectedRecords()],
    opportunityDegradation: null,
    weekly: weeklyProjectionRecords(),
    status: inSeasonPlayerStatusRecords(),
  });
}

describe("the in-season bundle keeps unprojected rows apart", () => {
  it("never puts a row without a value into a value ordering", () => {
    const own = bundle();
    const board = own.opportunityFor("redraft-12", "PPR");
    expect(board.every((row) => !isUnprojected(row))).toBe(true);
    expect(board.some((row) => row.player_id === FIXTURE_UNSIGNED_ID)).toBe(false);
    const listed = own.unprojectedFor("redraft-12", "PPR");
    // Most added first.
    expect(listed.map((row) => row.player_id)).toEqual([FIXTURE_UNSIGNED_ID, FIXTURE_SIGNING_ID]);
    expect(listed.every((row) => row.ros_fair_rank === null && row.ros_tier === null)).toBe(true);
    expect(own.unprojectedRecordFor("redraft-12", "PPR", FIXTURE_UNSIGNED_ID)?.add_count).toBe(2400);
  });

  it("labels the unsigned player FA and the signing with his new club", () => {
    const own = bundle();
    expect(own.teamLabel(FIXTURE_UNSIGNED_ID, null)).toBe("FA");
    expect(own.teamLabel(FIXTURE_SIGNING_ID, "SEA")).toBe("SEA");
    expect(own.availabilityFor(FIXTURE_UNSIGNED_ID).kind).toBe("unsigned");
    expect(own.availabilityFor(FIXTURE_SIGNING_ID).kind).toBe("signing");
  });

  it("applies the policy to a projected unsigned player without moving a number", () => {
    // A rest-of-season row whose status says he is now unsigned: his value is the model's,
    // unchanged; the page lists him as a stash and the decision tabs leave him out.
    const target = required(rosTierRecords().find((row) => row.league_preset_id === "redraft-12"));
    const status = inSeasonPlayerStatusRecords().map((record) =>
      record.player_id === target.player_id
        ? { ...record, roster_status: null, current_team: null, employment_status: "unsigned" as const, employment_source: "sleeper" as const }
        : record,
    );
    const own = new InSeasonBundle({
      metadata: rosBuildMetadata(),
      rosTiers: rosTierRecords(),
      opportunity: opportunityRecords(),
      opportunityDegradation: null,
      status,
    });
    const row = required(selectRosRows(own, DEFAULT_STATE).find((entry) => entry.record.player_id === target.player_id));
    expect(row.availability?.kind).toBe("unsigned");
    expect(row.record).toEqual(
      rosTierRecords().find(
        (record) =>
          record.player_id === target.player_id &&
          record.league_preset_id === row.record.league_preset_id &&
          record.scoring_preset === row.record.scoring_preset,
      ),
    );
    render(
      <AvailabilityContext.Provider value={(id) => own.availabilityFor(id)}>
        <TeamCell team={target.team} playerId={target.player_id} />
      </AvailabilityContext.Provider>,
    );
    expect(screen.getByText("FA")).toBeDefined();
    cleanup();
  });
});

const FIXTURE_NOW = new Date(Date.parse(FIXTURE_GENERATED_AT) + 3 * 60 * 60 * 1000);

describe("add activity reaches the FA card (end to end, rendered)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: FIXTURE_NOW });
    stubSite({ ...fixtureFiles(), ...inSeasonFixtureFiles(true) });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("lists him under Not projected, searchable, and opens a card that says what he is", async () => {
    window.history.replaceState(null, "", "/?view=opportunity&scoring=ppr&teams=12&search=Ashby");
    render(<App />);
    const section = await waitFor(() =>
      required(
        screen.getByRole("heading", { name: "Not projected" }).closest("section"),
        "the Not projected section",
      ),
    );
    const table = within(section).getByRole("table");
    const row = required(
      within(table)
        .getAllByRole("row")
        .find((candidate) => candidate.textContent?.includes("Darnell Ashby")),
      "Ashby's row",
    );
    expect(row.textContent).toContain("FA");
    expect(row.textContent).toContain("2,400");
    expect(row.textContent).toContain("Unsigned free agent · no projection");
    // The search applied: the signing does not match "Ashby".
    expect(table.textContent).not.toContain("Corey Halvorsen");

    await userEvent.setup().click(within(row).getByRole("button", { name: "Darnell Ashby" }));
    const dialog = await waitFor(() => screen.getByRole("dialog"));
    expect(within(dialog).getByRole("heading", { name: "Darnell Ashby" })).toBeDefined();
    const text = dialog.textContent ?? "";
    expect(text).toContain("FA");
    expect(text).toContain("Unsigned free agent — speculative stash");
    expect(text).toContain("No rest-of-season projection.");
    expect(text).toContain("2,400");
    // No invented value: no tier, no rank, no next game for a club he does not have.
    expect(within(dialog).queryByText(/^Tier\b/)).toBeNull();
  });

  it("finds every verified free agent with a search for FA", async () => {
    window.history.replaceState(null, "", "/?view=opportunity&scoring=ppr&teams=12&search=FA");
    render(<App />);
    const section = await waitFor(() =>
      required(
        screen.getByRole("heading", { name: "Not projected" }).closest("section"),
        "the Not projected section",
      ),
    );
    expect(section.textContent).toContain("Darnell Ashby");
    expect(section.textContent).not.toContain("Corey Halvorsen");
  });
});
