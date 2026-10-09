# Visual QA

Committed evidence, in the same spirit as `docs/source-probes/` and `docs/market-cohorts/`:
a dated set of screenshots of the actual rendered product, captured from a real static build
and reviewed by eye rather than diffed by pixel.

## Regenerating

```bash
npm run e2e:build                       # builds the sites and writes the fixture artifacts
node web/tests/e2e/static-server.mjs &  # serves them, including the /jeisey-tiers/ mount
npm run e2e:screens -- docs/visual-qa/<YYYY-MM-DD>
```

The capture runs against the **fixture** build, so two runs of the same code produce the same
images and a review is reproducible. The real generated board is reviewed separately during a
build; it changes on every run, so committing images of it would produce a diff that means
nothing.

The script fails if a page logs a console error or scrolls horizontally. Everything else is a
human judgement: clipped text, colliding labels, marks outside the plot, unreadable whiskers,
sticky-header problems, over-wide controls, hard tier boundaries, status badges covering names,
invisible focus, missing assets under the Pages base path.

## What is captured

| File | Screen |
|---|---|
| `01-desktop-tiers-ppr-12-all` | Tier board, PPR, 12 teams, all positions, 1440px |
| `02-tablet-tiers-rb` | Tier board filtered to RB, 900px |
| `03-desktop-arbitrage-draft-rail` | Draft rail and arbitrage table, 1440px |
| `04-desktop-data-methodology` | Data and methodology reference |
| `05-mobile-tiers` | Tier board at 390px |
| `06-mobile-arbitrage` | Draft rail at 390px |
| `07-degraded-market` | Arbitrage artifact absent; tier board unaffected |
| `08-player-injury-detail` | Player detail with an injury annotation and its disclosure |
| `09-schema-refusal` | Unsupported artifact contract, expected versus received |
| `10-pages-base-path` | The same product served from `/jeisey-tiers/` |
| `11-keyboard-focus` | Focus ring on a chart mark |

Later reviews add to this set rather than replacing it, and each keeps its own directory: a
review is evidence of what the product looked like on a date, so overwriting one loses the
comparison. Phase 8 added `12`-`15` (collapsed and expanded tiers, the tablet rail, premiums)
and Phase 9A added `16`-`28` — the third breakpoint, both tables on a phone, the tabbed sheet's
three panels, the awkward player records the fixture exists to carry, and the matured market
condition, which the default fixture cannot show.

Phase 12 added `29`-`40`: the In-Season screens, and the two lifecycle windows in which the
season has started and no rest-of-season board exists (ADR-079). They come from the two in-season scenario mounts
rather than the default build, because the default build publishes no in-season bundle: before the
season's first kickoff the draft board is the whole product, and a fixture that pretended otherwise
would be evidence of a state the pipeline never produces.

The in-season presentation pass added `41`-`50` (ADR-085): the rest-of-season tier board, which
did not exist before it; the disclosure open; the Opportunity Board's two tracks, at three
widths and with the behaviour feed down; and the player card in season beside the draft card it
replaced. That review exists because every one of its four defects passed every automated gate
and was obvious in a picture — which is the standing argument for this directory.

The card-meters pass added `51`-`57` (ADR-086): the same player card with three micro-charts on
it. It is the sequel to the review above and a narrower claim — the numbers were already right
and already there, and a reader still could not tell whether `ROS uncertainty 82.1` was a wide
interval or a narrow one. Each screen shows a *state* rather than a viewport: a rank move drawn,
a rank move refused because the player has no preseason rank, a pace gap in the direction that
matters, and the behaviour feed down.

The current directories:

| Directory | Review |
|---|---|
| `2026-08-21/` | Phase 6 — the draft sheet, first capture |
| `2026-08-31/` | Phase 8 — the inferred HUD redesign |
| `2026-08-31-design/` | Phase 9A — the owner's Claude Design source, implemented |
| `2026-09-01-release/` | Phase 9B — the logo masthead, export controls and favicon |
| `2026-09-04-phase12/` | Phase 12 — In-Season mode: the ROS board, the opportunity board, the two disclosure contracts |
| `2026-09-07-market-history/` | The player card's retained market history (ADR-081) |
| `2026-09-15-inseason-ui/` | The in-season presentation pass — both boards drawn, the status column removed, the card's draft market replaced (ADR-085) |
| `2026-09-15-card-meters/` | The player card's micro-charts — a rank move against the board, a pace comparison in the model's own unit, a value placed among its position (ADR-086) |
| `2026-09-22-in-season-signals/` | The signal layer — observed role week by week, the next game as context, and Pick of the Week's evidence row; fixture states plus six real week-2 cards (ADR-091) |

## "Why this week" (2026-10-01, ADR-099)

`web/tests/e2e/capture-whyweek.mjs` captures the Start/Sit tab with a pair compared, the week
board's "vs typical" column and the player card's "This week" block, at 1440, 1024, 820, 390 and
320px. For each screen it records the document's horizontal overflow, and any explanation
element whose box leaves its section, in `measurements.json`. It exits non-zero on either. The
images keep the widths a reviewer needs; every width is measured.

- `2026-10-01/whyweek-fixture/` — the in-season fixture (`/scenario/in-season/`).
- `2026-10-01/whyweek-real/` — a **real-data** build, committed once because the owner asked for
  it. The previous session's phone defects showed up only on real data. The build combined:
  - the local `build-current` and `build-ros` for 2026 week 4 (nflverse, the committed models);
  - forecasts seeded from the runner probe's real NWS and Open-Meteo readings of that day,
    because the private store is unreachable from the sandbox;
  - no arbitrage, since there was no market store.

  `verify-real-build.mjs --allow-missing-arbitrage` passed on the same build with 0 failures.

```bash
node web/tests/e2e/capture-whyweek.mjs docs/visual-qa/<date>/whyweek-fixture --prefix /scenario/in-season/
E2E_BASE_URL=http://localhost:4180 node web/tests/e2e/capture-whyweek.mjs \
  docs/visual-qa/<date>/whyweek-real --prefix / --data web/dist-real/data
```

## 2026-10-02 — the Trade tab and six-tab navigation (ADR-100)

`2026-10-02-trade/fixture/` — the in-season fixture at 1440, 820, 390 and 320px:

- the empty tab;
- give one (Bijan Robinson), receive two;
- the same with Highest ceiling, one package kept and one swapped;
- the tab row on the ROS, Opportunity, Pick of the Week and Data tabs.

`measurements.json` records document overflow, any Trade element outside the section, any
ellipsised number, and whether the active tab sits fully inside the row: all clean, 28 screens.
A first pass caught ellipsised readout cells at 320px; they were fixed before commit. No
real-data build was made for this pass: the tab adds no artifact, and `verify-real-build.mjs`
checks its packages against whatever build it is pointed at.

```bash
node web/tests/e2e/capture-trade.mjs docs/visual-qa/<date>/fixture --prefix /scenario/in-season/
```

## 2026-10-09 — season to date beside rest of season (ADR-105)

`2026-10-09-season-actuals/`. `real-*` screens are a live `build-ros` of 2026-10-09 (nflverse
through week 4, Half PPR, 12 teams, QB filter) assembled with the live draft artifacts:

- `real-ros-qb-half-{1440,390,320}` — the RoS chart's comparison lane: square = RoS positional
  rank, triangle = season rank by points, words beside it; the value lane's median is a tick.
  Tyler Shough reads `ROS QB15 · SZN QB5`; Bryce Young `ROS QB13 · SZN QB3`.
- `real-card-shough-{1440,390,320}` and `-1440-production` — the rank pair in the identity block
  ("Half PPR · through week 4 · RoS is 10 places below his season-to-date rank."), the context
  box, Production so far (QB5, 4 games, 85.3, 21.3) and the PaceRail (21.3 scored, 15.8 ahead).
- `real-ros-table-half-1440`, `real-opportunity-1440`, `real-startsit-390` — the three columns.

`fixture-*` screens are the in-season fixture build: ties (RB1/RB1), a wide gap (WR2/WR7), the
week board and the unprojected list with genuine actuals beside "No RoS projection".
`web/tests/e2e/actuals.spec.ts` measures the lane at 1440, 390 and 320 px (marks inside the lane,
triangle below square, words inside the row, no page overflow) and scans the board and card.
