/**
 * The player card's market history, end to end: published artifact -> served bytes -> chart.
 *
 * This is the integration the defect slipped through. Every layer had a passing test —
 * `market/trend.py` computed a correct slope, `ArtifactIndex` looked up a correct key,
 * `MarketTrend` drew a correct line — and the product still showed a current FFC ADP beside
 * "0 snapshots so far", because nothing in the repository ever ran a *second* market's
 * retained history all the way to a rendered card (ADR-081).
 *
 * So the assertions here read `market_trend_series.json` **from the same server the page
 * fetched it from**, and compare it with what the card drew. A chart that agreed with a
 * recomputation rather than with the published bytes would pass a component test and fail a
 * reader.
 */

import { expect, test, type Page } from "@playwright/test";

const MATURED = "/scenario/matured/";
const NO_FFC_HISTORY = "/scenario/no-ffc-history/";

const FFC = "fantasyfootballcalculator_adp";
const MFL = "myfantasyleague_adp";

/** Priced by both markets in every block. */
const DUAL_PRICED = "Bijan Robinson";
/** Priced by MyFantasyLeague alone — the graceful-degradation case. */
const MFL_ONLY = "Joe Burrow";

interface SeriesRecord {
  readonly market_source_id: string;
  readonly league_preset_id: string;
  readonly scoring_preset: string;
  readonly player_id: string;
  readonly market_trend: number | null;
  readonly points: readonly { readonly observed_at: string; readonly market_adp: number }[];
}

/** Fail the test on any request that leaves the static server. No vendor call may exist. */
function forbidExternalRequests(page: Page): void {
  const escaped: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("http://localhost") && !url.startsWith("data:") && !url.startsWith("blob:")) {
      escaped.push(url);
    }
  });
  page.on("close", () => {
    expect(escaped, "the chart's history must come from the artifact, never from a vendor").toEqual(
      [],
    );
  });
}

test.beforeEach(({ page }) => {
  forbidExternalRequests(page);
});

/** The artifacts the site itself serves, read back over the same origin. */
async function artifacts(
  page: Page,
  site: string,
): Promise<{ series: SeriesRecord[]; arbitrage: Record<string, unknown>[] }> {
  const [series, arbitrage] = await Promise.all([
    page
      .request.get(`${site}data/market_trend_series.json`)
      .then(async (response) => (await response.json()) as { records: SeriesRecord[] }),
    page
      .request.get(`${site}data/arbitrage.json`)
      .then(async (response) => (await response.json()) as { records: Record<string, unknown>[] }),
  ]);
  return { series: series.records, arbitrage: arbitrage.records };
}

async function openCard(page: Page, site: string, player: string, market: string): Promise<void> {
  await page.goto(`${site}?market=${market}&scoring=ppr&teams=12`);
  await expect(page.getByRole("heading", { name: "Tier board" })).toBeVisible();
  await page.getByRole("button", { name: player, exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
}

function seriesFor(
  records: readonly SeriesRecord[],
  playerId: string,
  sourceId: string,
): SeriesRecord | undefined {
  return records.find(
    (record) =>
      record.player_id === playerId &&
      record.market_source_id === sourceId &&
      record.league_preset_id === "redraft-12" &&
      record.scoring_preset === "PPR",
  );
}

function playerId(
  arbitrage: readonly Record<string, unknown>[],
  displayName: string,
): string {
  const row = arbitrage.find(
    (record) =>
      record.display_name === displayName &&
      record.league_preset_id === "redraft-12" &&
      record.scoring_preset === "PPR",
  );
  expect(row, `no ${displayName} row in the published board`).toBeTruthy();
  return String(row?.player_id);
}

test.describe("the market-history chart follows the selected market", () => {
  test("draws the published FFC history when FFC is selected", async ({ page }) => {
    const { series, arbitrage } = await artifacts(page, MATURED);
    const id = playerId(arbitrage, DUAL_PRICED);
    const ffc = seriesFor(series, id, FFC);
    const mfl = seriesFor(series, id, MFL);
    expect(ffc, "the build must publish an FFC history").toBeTruthy();
    expect(mfl).toBeTruthy();

    await openCard(page, MATURED, DUAL_PRICED, FFC);
    const chart = page.getByTestId("market-trend");
    await expect(chart).toBeVisible();
    await expect(chart.locator("g[data-source]")).toHaveCount(1);
    await expect(chart.locator(`g[data-source="${FFC}"]`)).toBeVisible();

    // The reading the card prints is the artifact's newest FFC point, not MyFantasyLeague's.
    const latest = ffc?.points.at(-1)?.market_adp ?? 0;
    await expect(chart.locator(".trend-reading")).toHaveText(`FFC Recent ${latest.toFixed(1)}`);
    expect(latest).not.toBeCloseTo(mfl?.points.at(-1)?.market_adp ?? 0, 1);
  });

  test("draws the published MyFantasyLeague history when MFL is selected", async ({ page }) => {
    const { series, arbitrage } = await artifacts(page, MATURED);
    const id = playerId(arbitrage, DUAL_PRICED);
    const mfl = seriesFor(series, id, MFL);

    await openCard(page, MATURED, DUAL_PRICED, MFL);
    const chart = page.getByTestId("market-trend");
    await expect(chart.locator("g[data-source]")).toHaveCount(1);
    await expect(chart.locator(`g[data-source="${MFL}"]`)).toBeVisible();
    await expect(chart.locator(".trend-reading")).toHaveText(
      `MFL Cumulative ${(mfl?.points.at(-1)?.market_adp ?? 0).toFixed(1)}`,
    );
  });

  test("plots one mark per retained calendar day, at the artifact's own prices", async ({
    page,
  }) => {
    const { series, arbitrage } = await artifacts(page, MATURED);
    const id = playerId(arbitrage, DUAL_PRICED);
    const record = seriesFor(series, id, FFC);
    // FFC's cadence has two captures on one calendar day; the chart shows the latest of each.
    const days = new Map<string, number>();
    for (const point of record?.points ?? []) days.set(point.observed_at.slice(0, 10), point.market_adp);

    await openCard(page, MATURED, DUAL_PRICED, FFC);
    const marks = page.getByTestId("market-trend").locator("circle[role='button']");
    await expect(marks).toHaveCount(days.size);
    const labels = await marks.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("aria-label") ?? ""),
    );
    for (const [day, adp] of days) {
      const readable = new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      });
      expect(
        labels.some((label) => label.includes(readable) && label.includes(`ADP ${adp.toFixed(1)}`)),
        `no mark for ${readable} at ${String(adp)}`,
      ).toBe(true);
    }
  });

  test("charts a short-span history while its scalar stays collecting", async ({ page }) => {
    const { series, arbitrage } = await artifacts(page, MATURED);
    const id = playerId(arbitrage, DUAL_PRICED);
    const ffc = seriesFor(series, id, FFC);
    // The published fact this test is about: real points, no slope.
    expect(ffc?.market_trend).toBeNull();
    expect((ffc?.points ?? []).length).toBeGreaterThan(2);

    await openCard(page, MATURED, DUAL_PRICED, FFC);
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("market-trend")).toBeVisible();
    await expect(dialog.getByTestId("market-trend-empty")).toHaveCount(0);
    await expect(
      dialog.locator(".readout", { hasText: "FFC Recent trend" }).first(),
    ).toContainText("collecting");
  });

  test("never shows another market's slope under the selected market's name", async ({ page }) => {
    const { series, arbitrage } = await artifacts(page, MATURED);
    const id = playerId(arbitrage, DUAL_PRICED);
    const mfl = seriesFor(series, id, MFL);
    // MyFantasyLeague has a slope, so a fallback would have something to show.
    expect(mfl?.market_trend).not.toBeNull();

    await openCard(page, MATURED, DUAL_PRICED, FFC);
    const readout = page
      .getByRole("dialog")
      .locator(".readout", { hasText: "FFC Recent trend" })
      .first();
    await expect(readout.locator(".readout-value")).toContainText("—");
    await expect(readout).not.toContainText((mfl?.market_trend ?? 0).toFixed(2));
  });
});

test.describe("the cross-market view", () => {
  test("overlays both published histories and requests no `cross` source", async ({ page }) => {
    const { series, arbitrage } = await artifacts(page, MATURED);
    expect(series.some((record) => record.market_source_id === "cross")).toBe(false);
    const id = playerId(arbitrage, DUAL_PRICED);
    expect(seriesFor(series, id, FFC)).toBeTruthy();
    expect(seriesFor(series, id, MFL)).toBeTruthy();

    await openCard(page, MATURED, DUAL_PRICED, "cross");
    const chart = page.getByTestId("market-trend");
    await expect(chart.locator("g[data-source]")).toHaveCount(2);
    await expect(chart.locator(`g[data-source="${FFC}"]`)).toBeVisible();
    await expect(chart.locator(`g[data-source="${MFL}"]`)).toBeVisible();
    await expect(chart.locator('g[data-source="cross"]')).toHaveCount(0);
    // Named, and told apart by stroke pattern rather than by colour alone.
    await expect(chart.locator(".trend-legend li")).toHaveCount(2);
    await expect(chart).toContainText("FFC Recent");
    await expect(chart).toContainText("MFL Cumulative");
  });

  test("publishes no single cross-market slope, listing each market's own instead", async ({
    page,
  }) => {
    const { series, arbitrage } = await artifacts(page, MATURED);
    const id = playerId(arbitrage, DUAL_PRICED);
    const mfl = seriesFor(series, id, MFL);

    await openCard(page, MATURED, DUAL_PRICED, "cross");
    const dialog = page.getByRole("dialog");
    const readout = dialog.locator(".readout", { hasText: "Market trend" }).first();
    await expect(readout.locator(".readout-value")).toContainText("—");
    await expect(readout).toContainText("per market, below");

    const legend = dialog.locator(".trend-legend");
    await expect(legend).toContainText("trend collecting");
    await expect(legend).toContainText(`${(mfl?.market_trend ?? 0).toFixed(2)}/day`);
  });

  test("shows the one market that has history when the other priced nobody", async ({ page }) => {
    await openCard(page, MATURED, MFL_ONLY, "cross");
    const chart = page.getByTestId("market-trend");
    await expect(chart.locator("g[data-source]")).toHaveCount(1);
    await expect(chart.locator(`g[data-source="${MFL}"]`)).toBeVisible();
  });
});

test.describe("degrading honestly", () => {
  test("says which market it has no history for, and keeps that market's price", async ({
    page,
  }) => {
    const { series } = await artifacts(page, NO_FFC_HISTORY);
    expect(series.some((record) => record.market_source_id === FFC)).toBe(false);

    await openCard(page, NO_FFC_HISTORY, DUAL_PRICED, FFC);
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("market-trend-empty")).toContainText("FFC Recent");
    // A missing chart is not a missing price.
    await expect(dialog.locator(".readout", { hasText: "FFC Recent ADP" }).first()).toBeVisible();
  });

  test("names the market that did not price him, and still lists the one that did", async ({
    page,
  }) => {
    await openCard(page, MATURED, MFL_ONLY, FFC);
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/No current FFC Recent ADP for him/)).toBeVisible();
    await expect(dialog.locator("table.compare-table")).toContainText("MFL Cumulative");
  });
});
