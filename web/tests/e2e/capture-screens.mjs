/**
 * Visual QA capture.
 *
 * `docs/UX_SPEC.md` section 14 names the screens a Phase-6 review has to look at. This script
 * takes them from a real static build so the review sees what a visitor sees, and writes them
 * to `docs/visual-qa/<date>/` where they are committed as evidence alongside the source probes
 * and the market-cohort reports.
 *
 * It captures the *fixture* build by default, so a review is reproducible and two runs of the
 * same code produce the same images; pass `--real` to point it at a build made from the live
 * artifacts instead.
 *
 *   node web/tests/e2e/build-fixtures.ts       # or: npm run e2e:build
 *   node web/tests/e2e/static-server.mjs &
 *   node web/tests/e2e/capture-screens.mjs docs/visual-qa/2026-08-21
 */

import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

import { stubPortraits } from "./portrait-stub.mjs";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";

/** Viewport, path and any interaction each required screen needs. */
const SCREENS = [
  {
    name: "01-desktop-tiers-ppr-12-all",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: true,
  },
  {
    name: "02-tablet-tiers-rb",
    path: "/?position=rb",
    viewport: { width: 900, height: 1100 },
    fullPage: true,
  },
  {
    name: "03-desktop-arbitrage-draft-rail",
    path: "/?view=arbitrage",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    name: "04-desktop-data-methodology",
    path: "/?view=data",
    viewport: { width: 1440, height: 1000 },
    fullPage: true,
  },
  {
    name: "05-mobile-tiers",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    name: "06-mobile-arbitrage",
    path: "/?view=arbitrage",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    name: "07-degraded-market",
    path: "/scenario/no-market/?view=arbitrage",
    viewport: { width: 1440, height: 800 },
    fullPage: false,
    // The whole point of this screen is an artifact that is not there.
    expectMissingArtifact: true,
  },
  {
    name: "08-player-injury-detail",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The other half of the Phase-8 responsive decision: at this width the same dialog is a
    // sheet. Captured next to 08 so a reviewer compares the two treatments directly.
    name: "08b-mobile-player-detail-sheet",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "08c-tablet-player-detail",
    path: "/",
    viewport: { width: 900, height: 1100 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Kyle Pitts Sr.", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The portrait at each of the three card variants, plus the monogram the card falls back
    // to. ADR-087: the picture is a drawn silhouette, not a real player - the fixture's ESPN
    // ids are synthetic and resolve to nothing at the real host, so what these show is the
    // *treatment* (the wash, the scanlines, the corner ticks, the bottom fade, the crop) and
    // not a face.
    name: "58-card-portrait-desktop",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Bijan Robinson", exact: true }).click();
      await page.getByRole("dialog").waitFor();
      await page.locator("img.portrait-image").waitFor();
    },
  },
  {
    name: "59-card-portrait-tablet-band",
    path: "/",
    viewport: { width: 900, height: 1100 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Bijan Robinson", exact: true }).click();
      await page.getByRole("dialog").waitFor();
      await page.locator("img.portrait-image").waitFor();
    },
  },
  {
    name: "60-card-portrait-mobile-sheet",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Bijan Robinson", exact: true }).click();
      await page.getByRole("dialog").waitFor();
      await page.locator("img.portrait-image").waitFor();
    },
  },
  {
    // The fallback, at the widest variant where it is most visible. Deebo Gray is the
    // fixture's unbridged player; the frame, the wash and the ticks are identical and the
    // face is a monogram, so nothing about the card's geometry depends on the picture.
    name: "61-card-portrait-monogram",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Deebo Gray", exact: true }).click();
      await page.getByRole("dialog").waitFor();
      await page.locator(".portrait-monogram").waitFor();
    },
  },
  {
    // A player with no price at all: the card has to say so rather than show an empty market
    // block, and the Phase-8 layout has to survive a missing readout grid.
    name: "08d-unpriced-player-detail",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Zach Ertz", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "12-tiers-all-collapsed",
    path: "/?tiers=none",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "13-tiers-all-expanded",
    path: "/?tiers=0.1.2",
    viewport: { width: 1440, height: 1000 },
    fullPage: true,
  },
  {
    name: "14-tablet-arbitrage-rail",
    path: "/?view=arbitrage&rail=all",
    viewport: { width: 900, height: 1100 },
    fullPage: false,
  },
  {
    name: "15-arbitrage-premiums",
    path: "/?view=arbitrage&rail=premiums",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "09-schema-refusal",
    path: "/scenario/bad-schema/",
    viewport: { width: 1440, height: 700 },
    fullPage: false,
  },
  {
    name: "10-pages-base-path",
    path: "/jeisey-tiers/?view=arbitrage&position=qb",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "11-keyboard-focus",
    path: "/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: /median simulated VORP/ }).first().focus();
    },
  },

  /*
   * Phase 9A additions.
   *
   * The design source has three player-card variants and two board treatments, so a review
   * that only looks at a desktop and a phone cannot tell a designed variant from a compressed
   * one. These screens cover the third breakpoint, both tables on a phone, the awkward player
   * records the fixture exists to carry, and the market condition the launch fixture cannot
   * show.
   */
  {
    // Narrow tablet: the last width before the board becomes the stack and the card becomes
    // the sheet. If anything is going to be a squeezed desktop, it is this one.
    name: "16-narrow-tablet-tiers",
    path: "/",
    viewport: { width: 768, height: 1100 },
    fullPage: true,
  },
  {
    name: "17-narrow-tablet-player-detail",
    path: "/",
    viewport: { width: 768, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "18-mobile-player-detail-market-tab",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "Draft market" }).click();
    },
  },
  {
    name: "19-mobile-player-detail-status-tab",
    path: "/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "Current status" }).click();
    },
  },
  {
    // No status record published at all, which is not the same as no designation.
    name: "20-player-detail-no-status-record",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Deebo Gray", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The largest positive rank gap on the fixture board, and an IR designation with it.
    name: "21-player-detail-large-bargain",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Jaylin Lane", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // A structural quarterback premium: the number that broke the Phase-6 rail's axis.
    name: "22-player-detail-large-premium",
    path: "/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Joe Burrow", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "23-mobile-tier-table",
    path: "/",
    viewport: { width: 390, height: 900 },
    fullPage: false,
    async act(page) {
      await page.getByRole("heading", { name: "Tier table" }).scrollIntoViewIfNeeded();
    },
  },
  {
    name: "24-mobile-arbitrage-table",
    path: "/?view=arbitrage",
    viewport: { width: 390, height: 900 },
    fullPage: false,
    async act(page) {
      await page.getByRole("heading", { name: "Arbitrage table" }).scrollIntoViewIfNeeded();
    },
  },
  {
    name: "25-mobile-data",
    path: "/?view=data",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    // The matured market: medium confidence, a measured trend, a sufficient cohort. The launch
    // fixture is uniformly low with a null trend, and a review that only sees that one is the
    // defect Phase 8 found in the test suite.
    name: "26-matured-market-arbitrage",
    path: "/scenario/matured/?view=arbitrage",
    viewport: { width: 1440, height: 1100 },
    fullPage: false,
  },
  {
    name: "27-matured-market-player-detail",
    path: "/scenario/matured/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The other degraded mode: model values intact, every status annotation gone.
    name: "28-degraded-status",
    path: "/scenario/no-status/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
    expectMissingArtifact: true,
  },

  /*
   * Phase 12 — In-Season mode.
   *
   * The default fixture build publishes no in-season bundle, because before kickoff that is
   * the correct product. These screens come from the two in-season scenario builds instead,
   * and they are the ones a review has to look at hardest: every heading here names a
   * rest-of-season quantity, and the two disclosure contracts — ADR-074's tier bands and
   * ADR-076's long absence — are only real if they are legible on the screen.
   */
  {
    name: "29-desktop-ros-tiers",
    path: "/scenario/in-season/",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    // The ADR-076 cohort: the flag, the week count, and the sentences that bound what it means.
    name: "30-desktop-ros-long-absence",
    path: "/scenario/in-season/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator(".absence-badge").first().scrollIntoViewIfNeeded();
    },
  },
  {
    name: "31-desktop-opportunity",
    path: "/scenario/in-season/?view=opportunity",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    name: "32-tablet-ros-tiers",
    path: "/scenario/in-season/?position=rb",
    viewport: { width: 900, height: 1100 },
    fullPage: true,
  },
  {
    name: "33-mobile-ros-tiers",
    path: "/scenario/in-season/",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    name: "34-mobile-opportunity",
    path: "/scenario/in-season/?view=opportunity",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    // The behaviour feed is down. Counts go blank rather than to zero, and every intrinsic
    // value is still there — the failure a reader must be able to tell from "nobody added him".
    name: "35-opportunity-behaviour-absent",
    path: "/scenario/in-season-no-behavior/?view=opportunity",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
  },
  {
    // Two models, two orderings, side by side and not reconciled into one number.
    name: "36-inseason-player-detail",
    path: "/scenario/in-season/",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    name: "37-inseason-data-methodology",
    path: "/scenario/in-season/?view=data",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    // The draft board stays reachable all season, and says so in the mode indicator.
    name: "38-inseason-draft-mode",
    path: "/scenario/in-season/?mode=draft",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
  },

  /*
   * The two lifecycle windows (ADR-079): the season has started and the draft board is the
   * only board that exists. Worth a picture precisely because the wrong version of these
   * looks fine — a draft board labelled "Draft mode" in November is not visibly broken.
   */
  {
    name: "39-awaiting-first-ros-board",
    path: "/scenario/awaiting-first-week/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "40-season-complete",
    path: "/scenario/season-complete/",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },

  /*
   * The in-season presentation pass (ADR-085).
   *
   * Four owner-reported defects, and every one of them was invisible to a passing suite and
   * obvious in a picture — which is why each gets one. The rest-of-season board had no chart
   * at all; the opportunity board had no chart and a table with no glyphs; both carried a
   * `Current status` column that read `ACT` on every row and pushed the model's own columns
   * off the right edge; and the player card led with a draft ADP in November.
   */
  {
    // The board that did not exist: artboard 2a's own language over remaining VORP.
    name: "41-ros-tier-board",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    // The disclosure open. The summary is the contractual sentence and is always on screen;
    // this is what the rest of ADR-076 looks like once a reader asks for it.
    name: "42-ros-disclosure-open",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
    async act(page) {
      await page.locator("details.disclosure summary").click();
    },
  },
  {
    // Two tracks, two zeros, one rule between them, and no position that spans both.
    name: "43-opportunity-board-two-tracks",
    path: "/scenario/in-season/?view=opportunity&opportunity=adds",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    // The behaviour feed down, drawn as an absence rather than as a row of zero-length bars.
    name: "44-opportunity-board-no-behaviour",
    path: "/scenario/in-season-no-behavior/?view=opportunity",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
  },
  {
    name: "45-opportunity-board-tablet",
    path: "/scenario/in-season/?view=opportunity",
    viewport: { width: 900, height: 1100 },
    fullPage: false,
  },
  {
    name: "46-opportunity-board-mobile",
    path: "/scenario/in-season/?view=opportunity",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    name: "47-ros-board-mobile-stack",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    // The card in season: the draft market is replaced by what the player has actually done.
    name: "48-inseason-card-usage",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      await page.getByRole("dialog").waitFor();
      await page.locator(".detail-body").evaluate((node) => {
        node.scrollTop = node.scrollHeight;
      });
    },
  },
  {
    name: "49-inseason-card-usage-mobile",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "In-season usage" }).click();
    },
  },
  {
    // And the draft card, unchanged, on the draft board that stays reachable all season.
    name: "50-draft-card-in-november",
    path: "/scenario/in-season/?mode=draft&view=tiers",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      await page.getByRole("dialog").waitFor();
    },
  },

  /*
   * The card's micro-charts (ADR-086).
   *
   * The owner's report was that the two in-season sections were "very static looking" and
   * that `ROS uncertainty 82.1` told a reader nothing. Every screen below is a number that was
   * already correct, in a picture that says what it means — so a picture is exactly the right
   * evidence, and each one shows a different *state* rather than a different viewport.
   */
  {
    // Rest of season: the rank-move rail, the interval width against its own position.
    name: "51-card-rest-of-season-meters",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The breakout: no preseason rank at all, and a rate the model is declining to buy. The
    // rail is a sentence rather than a move, which is the branch a picture is worth having.
    name: "52-card-breakout-no-preseason-rank",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).first().click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The pace rail and the production cohort strip, scrolled to.
    name: "53-card-pace-and-usage",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).first().click();
      await page.getByRole("dialog").waitFor();
      await page.locator(".detail-body").evaluate((node) => {
        node.scrollTop = node.scrollHeight;
      });
    },
  },
  {
    // The tablet dossier: no identity rail, the same three meters at full card width.
    name: "54-card-meters-tablet",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 900, height: 1100 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      await page.getByRole("dialog").waitFor();
    },
  },
  {
    // The sheet: every meter stacks, label and readout on one line, track beneath.
    name: "55-card-meters-mobile-ros",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "Rest of season" }).click();
    },
  },
  {
    name: "56-card-meters-mobile-usage",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Amon-Ra Bright", exact: true }).first().click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "In-season usage" }).click();
    },
  },
  {
    // The feed down: the moves strip is empty and labelled, and the usage cohort rows that
    // depend on it are absent rather than drawn at zero.
    name: "57-card-usage-no-behaviour",
    path: "/scenario/in-season-no-behavior/?view=ros",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.locator("table.sheet .player-name").first().click();
      await page.getByRole("dialog").waitFor();
      await page.locator(".detail-body").evaluate((node) => {
        node.scrollTop = node.scrollHeight;
      });
    },
  },
  /*
    Pick of the Week (ADR-088). Seven screens, and five of them exist because the view has
    states a happy-path capture would never reach: a set deep enough that a position has run
    out of candidates, a behaviour feed that published nothing, and the three viewports where
    a portrait beside a tile grid is the widest thing this product draws.
  */
  {
    name: "58-desktop-potw",
    path: "/scenario/in-season/?view=potw",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    name: "59-desktop-potw-set-2",
    path: "/scenario/in-season/?view=potw&set=2",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    // One position. The chip row writes the shared filter, so this is the same state the
    // boards beside it would be in.
    name: "60-desktop-potw-one-position",
    path: "/scenario/in-season/?view=potw&position=rb",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    name: "61-tablet-potw",
    path: "/scenario/in-season/?view=potw",
    viewport: { width: 900, height: 1300 },
    fullPage: true,
  },
  {
    name: "62-mobile-potw",
    path: "/scenario/in-season/?view=potw",
    viewport: { width: 390, height: 844 },
    fullPage: false,
  },
  {
    // The card at the reflow width the spec names. A portrait column beside a tile grid is
    // the layout most likely to push a number off the edge rather than wrap it.
    name: "63-potw-320",
    path: "/scenario/in-season/?view=potw",
    viewport: { width: 320, height: 900 },
    fullPage: false,
  },
  {
    // No behaviour feed: no picks, and a notice saying which case that is. "Nobody qualified"
    // and "the feed said nothing" are different facts and this is the second one.
    name: "64-potw-behaviour-absent",
    path: "/scenario/in-season-no-behavior/?view=potw",
    viewport: { width: 1440, height: 900 },
    fullPage: false,
  },
  {
    /*
      Add momentum (ADR-089), in every state one screen can hold.

      The default set carries four of them at once and that is not luck — the fixture is built
      to: a full seven-point rising window (RB), a falling one (TE), a single observation with
      a gap beside it (WR), and a player the feed has never carried (QB). The sixth state, a
      two-point window, is the surfaced player deeper in the sets.
    */
    name: "65-potw-momentum-states",
    path: "/scenario/in-season/?view=potw",
    viewport: { width: 1440, height: 1100 },
    fullPage: true,
  },
  {
    // The two behaviour panels stack rather than shrink, and each keeps its own heading. A
    // 140px-wide twelve-bar strip is a picture of nothing.
    name: "66-potw-momentum-320",
    path: "/scenario/in-season/?view=potw",
    viewport: { width: 320, height: 900 },
    fullPage: true,
  },
  // --------------------------------------------------------------- the signal layer (ADR-091)
  signalCard("67-card-qb-attempts-bye-next-week", "Jalen Marsh"),
  signalCard("68-card-rb-role-rising", "Jahmyr Cook"),
  signalCard("69-card-wr-role-declining", "Deebo Gray"),
  signalCard("70-card-te-no-snap-row-unposted-line", "Trey McBride"),
  signalCard("71-card-absent-player", "James Cook III"),
  signalCard("72-card-no-usage-record", "Jaylin Lane"),
  signalCard("73-card-signals-not-published", "Jahmyr Cook", "/scenario/in-season-no-signals/"),
  signalCard("74-card-next-game-and-momentum", "Jahmyr Cook", "/scenario/in-season/", ".matchup"),
  {
    // Thin history: the surfaced player has one appearance, which is a reading and not a
    // change. Opened from the Opportunity Board, the one board that publishes him.
    name: "75-card-one-appearance",
    path: "/scenario/in-season/?view=opportunity",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: /\(surfaced\)/ }).first().click();
      await scrollTo(page, ".usage-rails");
    },
  },
  {
    name: "76-card-role-mobile-tab",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 390, height: 844 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Jahmyr Cook", exact: true }).first().click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "In-season usage" }).click();
      await scrollTo(page, ".usage-rails");
    },
  },
  {
    name: "77-card-role-320",
    path: "/scenario/in-season/?view=ros",
    viewport: { width: 320, height: 800 },
    fullPage: false,
    async act(page) {
      await page.getByRole("button", { name: "Jahmyr Cook", exact: true }).first().click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("tab", { name: "In-season usage" }).click();
      await scrollTo(page, ".matchup");
    },
  },
  {
    name: "78-potw-evidence-desktop",
    path: "/scenario/in-season/?view=potw",
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    name: "79-potw-evidence-mobile",
    path: "/scenario/in-season/?view=potw&position=rb",
    viewport: { width: 390, height: 844 },
    fullPage: true,
  },
  {
    name: "80-potw-signals-not-published",
    path: "/scenario/in-season-no-signals/?view=potw&position=wr",
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    expectMissingArtifact: true,
  },
];

/** Scroll the open card so `selector` is at the top of its scrolling body. */
async function scrollTo(page, selector) {
  await page.getByRole("dialog").waitFor();
  await page.locator(".detail-body").evaluate((body, target) => {
    const node = body.querySelector(target);
    if (node !== null) body.scrollTop = node.offsetTop - 60;
  }, selector);
}

/** An in-season card for `player`, scrolled to its role block (or to `anchor`). */
function signalCard(name, player, scenario = "/scenario/in-season/", anchor = ".detail-subhead") {
  return {
    name,
    path: `${scenario}?view=ros&scoring=ppr&teams=12`,
    viewport: { width: 1440, height: 1000 },
    fullPage: false,
    expectMissingArtifact: scenario.includes("no-signals"),
    async act(page) {
      await page.getByRole("button", { name: player, exact: true }).first().click();
      await scrollTo(page, anchor === ".detail-subhead" ? ".usage-rails, .signal-absent" : anchor);
    },
  };
}

/** Artifacts a build is allowed not to publish; see the console filter below. */
const OPTIONAL_ARTIFACTS =
  /market_trend_series\.json|ros_build_metadata\.json|behavior_trend_series\.json|player_usage\.json|team_matchups\.json/;

const outDir = resolve(process.argv[2] ?? "docs/visual-qa/local");
mkdirSync(outDir, { recursive: true });

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch(executablePath ? { executablePath } : {});
const problems = [];

for (const screen of SCREENS) {
  const page = await browser.newPage({ viewport: screen.viewport });
  // A silhouette, not a refusal: these images are a design review, and the card's fallback
  // is not what is being reviewed. See `portrait-stub.mjs` for why neither is a real face.
  await stubPortraits(page);
  page.on("pageerror", (error) => problems.push(`${screen.name}: ${String(error)}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    // A scenario that withholds an artifact necessarily logs the browser's own 404 line.
    if (screen.expectMissingArtifact && /404/.test(message.text())) return;
    // So does an artifact the contract declares optional. The market trend series exists only
    // once the snapshot window holds enough of them, and the in-season bundle only after the
    // season's first kickoff — before which the draft build is the whole product. The loader
    // treats both absences as normal; the browser still prints a 404, and a 404 for an
    // artifact that is allowed to be missing is not evidence of anything.
    // The console line names no URL, so the resource comes from the message's own location.
    if (/404/.test(message.text()) && OPTIONAL_ARTIFACTS.test(message.location().url)) return;
    problems.push(`${screen.name}: ${message.text()}`);
  });
  await page.goto(`${BASE}${screen.path}`, { waitUntil: "networkidle" });
  if (screen.act) await screen.act(page);
  await page.waitForTimeout(250);

  // A page that scrolls sideways is a defect, not a screenshot note.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 1) problems.push(`${screen.name}: horizontal overflow of ${String(overflow)}px`);

  await page.screenshot({ path: resolve(outDir, `${screen.name}.png`), fullPage: screen.fullPage });
  await page.close();
  process.stdout.write(`captured ${screen.name}\n`);
}

await browser.close();

if (problems.length > 0) {
  process.stderr.write(`\n${problems.join("\n")}\n`);
  process.exitCode = 1;
}
