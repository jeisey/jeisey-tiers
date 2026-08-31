# Phase-8 visual review — 2026-08-31

Eighteen screens from a real static build of the fixture board, plus a performance measurement
on a synthetic board at **production dimensions**. The fixture proves layout and the production
board proves cost; neither substitutes for the other, and the Phase-6 review said so before the
Phase-8 redesign made it matter.

Regenerate with:

```bash
npm run e2e:build
node web/tests/e2e/static-server.mjs &
node web/tests/e2e/capture-screens.mjs docs/visual-qa/2026-08-31
node web/tests/e2e/measure-performance.mjs --out docs/visual-qa/2026-08-31/performance.json
```

Two runs of the same code produce the same images: the fixture board is fixed and the
performance board is seeded.

---

## What changed, and what it was measured against

| screen | what it shows |
|---|---|
| `01-desktop-tiers-ppr-12-all` | the redesigned board, default depth |
| `12-tiers-all-collapsed` | every tier closed — the whole board's shape in one screen |
| `13-tiers-all-expanded` | every tier open |
| `02-tablet-tiers-rb` | the shared grid at 900px |
| `05-mobile-tiers` | …and at 390px |
| `03-desktop-arbitrage-draft-rail` | the rail's new signed-gap encoding |
| `15-arbitrage-premiums` | the same encoding on the other side of zero |
| `14-tablet-arbitrage-rail` | the rail at 900px, score column dropped |
| `06-mobile-arbitrage` | the rail at 390px, anchors dropped |
| `08-player-injury-detail` | the desktop HUD card |
| `08b-mobile-player-detail-sheet` | the same DOM as a sheet |
| `08c-tablet-player-detail` | the card at 900px |
| `08d-unpriced-player-detail` | a player with no market row at all |
| `04-desktop-data-methodology` | where the methodology went |
| `07-degraded-market` | the arbitrage artifact withheld |
| `09-schema-refusal` | a contract the site does not understand |
| `10-pages-base-path` | served from `/jeisey-tiers/` |
| `11-keyboard-focus` | the focus ring on a board row |

---

## 1. The Tier Board

**The owner's complaint was height; the answer was not a shorter interval.**

| | Phase 6 | Phase 8 |
|---|---:|---:|
| default view, production board | ~1,800px | **1,405px** |
| every tier collapsed | not possible | **~230px** |
| all 300 players, every tier open | ~5,400px | 7,670px |
| SVG elements on the page | ~700 | **0** |

The default view is 22% shorter, but the number that matters is the second row. Collapsing puts
the *whole* board — nine tiers, their sizes, their rank ranges and their value spans — in about
a screen, and the reader opens the tier they are drafting from. The full expansion is taller
than Phase 6's because each row is 24px rather than 17px: that is a WCAG 2.2 target-size
minimum, and it is a trade made deliberately rather than a regression.

**The interval was not narrowed.** Each row still draws P25–P75 on the board's shared scale.
What changed is that the bar no longer shares horizontal space with a name label, so it needs a
fifth of the width rather than all of it.

**Three tracks, one grid.** The scale, each tier header's band and each player's bar are all in
column four of a single grid definition, driven by three CSS custom properties. That is
load-bearing: "these two tier bands overlap" is a *measured* claim about the value curve, and it
is only a true statement about the picture if the tracks occupy the same pixels. The first
version of this redesign had them ~45px apart, which made an honest claim into an approximate
one. `12-tiers-all-collapsed` is the screen where the overlap is unmistakable — tier 1 runs
89.3→187.8 while tier 2 runs 29.4→176.6, and they share most of their range.

That is ADR-035's finding, drawn. Nothing rules a line between two tiers, nothing labels a
cliff, and the collapsed header shows a tier as a *span* rather than as an edge.

## 2. The Draft Rail

The 1-to-300 pick axis is gone. Judged on the real board it could not work: the axis had to
reach a −206-pick quarterback premium, which left a genuine 8.5-pick bargain at three percent of
the width. The sentence beside each row was doing all the work.

The bar is now the signed gap on a symmetric scale sized to the rows shown (85th percentile of
their absolute gaps, floored at 10 picks and ceilinged at 120). `03` and `15` show it from both
sides: bargains extend right, premiums left, the axis line is where fair rank sits, and a row
past the scale keeps its exact number and gains an overflow chevron.

Direction survives without colour three ways: the side, the glyph, and the word (`later` /
`earlier` / `even`) under the signed number. The row's accessible name still carries the full
sentence.

**Responsive decisions, made per surface rather than by shrinking.** Desktop keeps the two
numeric anchors and the arbitrage score; the tablet drops the score, which the table below
carries; the phone drops the anchors too, because three columns of tabular numbers in 390px is
a column of collisions. `mobile.spec.ts` asserts the columns do not overlap and that the bar
keeps a usable width.

## 3. The player card

`08` and `08b` are the same DOM. Desktop gets a centred HUD card; at 390px it becomes a sheet
anchored to the bottom edge, because a centred card at that width puts the readouts a drafter
needs behind a scroll and shrinks every touch target.

Both lead with what is needed while a pick clock runs — fair rank, position rank, tier, median
VORP, P25–P75, uncertainty, then MFL ADP, value gap, arbitrage score, trend, market data,
observed picks — followed by a status strip of *fields* rather than prose, and one `<details>`
for the full simulation and market evidence.

The three repeated paragraphs are gone. What is left where a number could be misread: the word
`Medium` (not a colour), `approximate cohort` under the ADP when the build says the cohort is
approximate, `None reported` where there is no designation, and the five-word marker
`Annotation only — not a model input.` The definitions are one link away (ADR-058).

`08d` is the case that would have broken a layout built only against priced players: no market
grid at all, and the card says why rather than showing empty readouts.

Native `<dialog>` + `showModal()` throughout, so focus trapping, Escape and an inert background
are the platform's rather than hand-rolled — verified on all three engines.

## 4. Performance, on a production-scale board

2,700 tier rows, 1,800 arbitrage rows, 3,438 projections, 316 status rows; median of five,
Chromium, 1440×1000.

| interaction | median | range |
|---|---:|---|
| cold load to first board row | 287 ms | 260-336 |
| sort the 300-row tier table | 194 ms | 182-199 |
| expand all tiers | 199 ms | 181-210 |
| switch to the full 300-player board | 260 ms | 230-338 |
| filter to one position | 164 ms | 98-223 |
| search (includes the declared 220 ms debounce) | 305 ms | 305-313 |
| open the player card | 106 ms | 89-136 |
| render the arbitrage view | 313 ms | 231-421 |

Bundle: **326 kB JS (99 kB gzipped)**, **27 kB CSS (5.8 kB gzipped)**. DOM 6,969 nodes in the
default view, 9,993 with all 300 board rows open.

**No launch-blocking performance problem.** Every interaction is under a third of a second at a
scale the product will not exceed, and the one that looks slowest is 220 ms of deliberate
debounce.

**What the redesign changed.** SVG element count on the two chart views went from roughly seven
hundred to **zero** — the encodings are CSS geometry now — and the default board renders 47 rows
instead of 100. Bundle size is flat: removing `d3-scale`/`d3-array` paid for the extra component
code almost exactly.

**The two React-Compiler warnings on the table components stand** (ADR-048). `useReactTable`
returns functions the compiler cannot memoise, so it skips those components. Sorting three
hundred rows costs 194 ms including the click round-trip; there is no measurement here that
would justify replacing the library or silencing the warning, and AGENTS.md asks for measured
benefit rather than a clean log.

## 5. Accessibility

`a11y.spec.ts`, sixteen checks: axe-core at WCAG 2.0/2.1/2.2 A and AA over eight surfaces plus
the open dialog, then the properties a scanner cannot judge.

**Four real defects, all introduced by this redesign, all found on the first scan.**

1. `--ink-faint` was **3.15:1** on white. Tolerable while it tinted a few em dashes; the HUD had
   just given it every micro-label on the board, the rail and the card. Now `#5f6a78` —
   5.50:1 on the page, 5.12:1 on a sunken panel, 4.53:1 on a selected row.
2. `--pos-rb` and `--pos-te` carried text at **4.52:1** and **4.14:1** against a selected row,
   made worse by an `opacity: 0.85` on the tier-header chips. The opacity is gone (axe reads
   the composited pixel, not the declaration) and both hues are darker.
3. The tier toggle had **no focus ring** — a new control that missed the stylesheet's shared
   rule.
4. The Data view overflowed **168px at 320px wide**, the width WCAG Reflow names, because a
   grid track had a `minmax()` minimum larger than its container.

All fixed; the scan is clean. Beyond it: landmarks and heading order asserted, the board is one
tab stop with arrow-key movement inside it, every tier toggle carries `aria-expanded` and
`aria-controls` and is operable from the keyboard, direction and status survive without colour,
every interactive target clears 24px, every custom control has a visible focus indicator, and
all three views reflow at 320px without a horizontal scrollbar.

**Zero automated violations is a floor, not a result**, and the spec says so in code rather than
in a comment.

## 6. Cross-browser

`smoke.spec.ts` on Chromium, Firefox and WebKit: load, reflow, tier collapse through the URL,
filters, search, the arbitrage view, the Data view, dialog focus-trap and Escape and focus
restoration, keyboard activation from a board row, CSV download, the `/jeisey-tiers/` base path,
and reduced motion. Green on all three in
[33407642729](https://github.com/jeisey/jeisey-tiers/actions/runs/33407642729).

The stylesheet now contains **no transition and no animation at all** — the one that existed, a
120 ms slide on the skip link, was decorative and is gone — so the reduced-motion assertion is a
true invariant rather than a check on one media query.

## 7. Defects found and fixed during this review

| # | defect | severity |
|---|---|---|
| 1 | tier band and player bars on different grid columns, making the overlap claim approximate | high — it is the honesty claim |
| 2 | the scale was on neither of those columns | high — same |
| 3 | rail anchors wrapped to two lines, floating each label away from its row | medium |
| 4 | `--ink-faint` at 3.15:1 across every micro-label | high (WCAG AA) |
| 5 | RB/TE chip text under 4.5:1 on a selected row | medium (WCAG AA) |
| 6 | tier toggle without a focus ring | high (WCAG A) |
| 7 | Data view overflowing 168px at 320px | medium (WCAG AA) |
| 8 | `tiers=` URL parser rejecting the zero-based first tier | medium |
| 9 | closed tiers rendering hidden rows rather than none | low (cost, not correctness) |

## 8. Non-blocking observations

- **`::backdrop` does not appear in these screenshots.** Verified as a capture artefact, not a
  product defect: `getComputedStyle(dialog, "::backdrop").backgroundColor` reads
  `rgba(10, 14, 20, 0.55)` in the same session. The headless build does not composite the top
  layer into a screenshot.
- **The masthead reads "Build is stale" in every screen.** Correct: the fixture board is stamped
  2026-08-21 and the review clock is real. It is the freshness rule working.
- **Full expansion is 7,670px.** Deliberate, reachable only by choosing it, and the table below
  remains the complete 300-row surface either way.
