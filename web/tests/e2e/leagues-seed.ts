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

