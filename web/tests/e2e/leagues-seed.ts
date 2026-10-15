/**
 * Saved leagues for an end-to-end run (ADR-106): the stored document, written before the
 * page's own scripts run, so a spec starts from a known workspace without clicking one into
 * being. The document is the real contract's shape (`web/src/data/leagueContract.ts`).
 */

import type { Page } from "@playwright/test";

export const IN_SEASON = "/scenario/in-season/";
export const KEY = `jeisey-tiers:my-leagues@${IN_SEASON}`;

export interface SeedLeague {
  readonly id: string;
  readonly name: string;
  readonly scoring?: "std" | "half" | "ppr";
  readonly teams?: 10 | 12 | 14;
  readonly roster: Partial<Record<"QB" | "RB" | "WR" | "TE" | "FLEX" | "BN" | "IR", (string | null)[]>>;
  readonly rising?: boolean;
}

const COUNTS = { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, BN: 5, IR: 2 } as const;

export function leagueDocument(leagues: readonly SeedLeague[]): string {
  return JSON.stringify({
    format: "jeisey-tiers.my-leagues",
    version: 1,
    revision: 1,
    activeId: leagues[0]?.id ?? null,
    leagues: leagues.map((league) => ({
      id: league.id,
      name: league.name,
      season: 2026,
      scoring: league.scoring ?? "ppr",
      teams: league.teams ?? 12,
      slots: COUNTS,
      roster: Object.fromEntries(
        Object.entries(COUNTS).map(([group, count]) => [
          group,
          Array.from({ length: count }, (_, index) => league.roster[group as keyof typeof COUNTS]?.[index] ?? null),
        ]),
      ),
      prefs: { risingStars: league.rising ?? false, mode: "q50" },
      rev: 1,
      updatedAt: "2026-08-21T00:00:00Z",
    })),
  });
}

/** Seed saved leagues before the page's scripts run, once per page (not on every reload). */
export async function seed(page: Page, leagues: readonly SeedLeague[]): Promise<void> {
  await page.addInitScript(
    ([key, value]) => {
      if (window.sessionStorage.getItem("seeded") === null) {
        window.localStorage.setItem(key, value);
        window.sessionStorage.setItem("seeded", "1");
      }
    },
    [KEY, leagueDocument(leagues)] as const,
  );
}

export const g = (short: string): string => `gsis:00-00000${short}`;

/** A roster on which every Auto Start/Sit rule and Improve have something to say. */
export const OFFICE: SeedLeague = {
  id: "lg-office01",
  name: "Office",
  roster: {
    QB: [g("09")],
    RB: [g("01"), g("16")],
    WR: [g("12"), g("06")],
    TE: [g("07")],
    FLEX: [g("17")],
    BN: [g("10"), g("02")],
  },
};

export const MATCHUP_KEY = `jeisey-tiers:win-my-matchup@${IN_SEASON}`;

/** Seed Win My Matchup's saved inputs (ADR-110), once per page, beside the leagues. */
export async function seedMatchups(page: Page, document: unknown): Promise<void> {
  await page.addInitScript(
    ([key, value]) => {
      if (window.sessionStorage.getItem("seeded-wmm") === null) {
        window.localStorage.setItem(key, value);
        window.sessionStorage.setItem("seeded-wmm", "1");
      }
    },
    [MATCHUP_KEY, JSON.stringify(document)] as const,
  );
}

/**
 * A week-9 league whose starters exercise Win My Matchup's slot conditions: a bye (Deebo Gray),
 * three players the policy sidelines (Omarion Vance, Kyle Pitts Sr., Rashee Kirk), and three
 * playable starters. Jahmyr Cook, a rising back with high net adds, is on nobody's roster.
 */
export const MATCH: SeedLeague = {
  id: "lg-match01",
  name: "Match",
  roster: {
    QB: [g("09")],
    RB: [g("01"), g("16")],
    WR: [g("12"), g("06")],
    TE: [g("04")],
    FLEX: [g("17")],
    BN: [g("07"), g("10")],
  },
};

/** A complete week-9 opponent for `MATCH`, with every absence confirmed as 0. */
export function matchOpponent(week = 9, complete = true): unknown {
  return {
    format: "jeisey-tiers.win-my-matchup",
    version: 1,
    revision: 1,
    prefs: {},
    entries: [
      {
        leagueId: MATCH.id,
        season: 2026,
        week,
        opponent: {
          name: "Rival",
          starters: { QB: [g("18")], RB: [g("13"), g("14")], WR: [g("02"), g("15")], TE: [null], FLEX: [g("03")] },
          others: [],
        },
        confirmedEmpty: { mine: [], theirs: complete ? ["TE:0"] : [] },
        countZero: complete ? [g("16"), g("04"), g("17"), g("13"), g("14"), g("15"), g("03")] : [],
        finals: {},
        marks: {},
        rev: 1,
        updatedAt: "2026-08-21T00:00:00Z",
      },
    ],
  };
}
