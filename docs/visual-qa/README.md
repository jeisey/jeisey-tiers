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
