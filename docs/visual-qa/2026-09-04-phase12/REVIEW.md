# Phase-12 visual QA — 2026-09-04

Forty-three images from `npm run e2e:screens`, captured from the **fixture** builds so two runs of
the same code produce the same pictures (`docs/visual-qa/README.md`). Screens `01`–`28` are the
existing set, recaptured so this directory is a complete picture of the product on this date
rather than a patch on an older one. Screens `29`–`40` are new and are the Phase-12 subject:
**In-Season mode**, and the two windows in which it does not exist yet.

The default fixture build publishes no in-season bundle, because before the season's first
kickoff that is the correct product. The new screens therefore come from four scenario builds —
`/scenario/in-season/`, `/scenario/in-season-no-behavior/`, `/scenario/awaiting-first-week/` and
`/scenario/season-complete/` — which the static server mounts alongside the existing degraded
scenarios.

| file | what it is |
|---|---|
| `29-desktop-ros-tiers` | the ROS tier board at 1440px, full page |
| `30-desktop-ros-long-absence` | the same board scrolled to the ADR-076 cohort |
| `31-desktop-opportunity` | the opportunity board at 1440px, full page |
| `32-tablet-ros-tiers` | the ROS board filtered to RB at 900px |
| `33-mobile-ros-tiers` | the ROS board at 390px |
| `34-mobile-opportunity` | the opportunity board at 390px |
| `35-opportunity-behaviour-absent` | the behaviour feed down: counts blank, values intact |
| `36-inseason-player-detail` | the player card's rest-of-season section |
| `37-inseason-data-methodology` | the Data panel, including `05b Rest-of-season build` |
| `38-inseason-draft-mode` | the draft board, still reachable in season |
| `39-awaiting-first-ros-board` | the season has started and no board exists yet (ADR-079) |
| `40-season-complete` | the far end: no remaining horizon, and no board of zeros |

## What the review confirms

**No rest-of-season number is labelled with a preseason name.** Every column heading on `29` and
`31` carries `ROS` — `ROS Rank`, `ROS PosRk`, `ROS Tier`, `ROS Exp VORP`, `ROS P25–P75` — and the
board's own note says so in words: *"Every value below is what is left of 2026, estimated from
weeks 1–8 only. These are not the preseason numbers: a different model, a different horizon, and
a different replacement baseline."* `e2e/inseason.spec.ts` asserts the bare names `Rank`, `Tier`
and `Exp VORP` appear on no heading of this board.

**The two orderings sit side by side and are never reconciled.** `36` shows the player card's
`02 Rest of season` section carrying *Preseason fair rank 1* (`draft model`) beside *Current ROS
fair rank 1* (`rest-of-season model`) and *Change in intrinsic view* labelled `two models, two
orderings`. Nothing on the card averages, differences or supersedes one with the other.

**ADR-074 is load-bearing on the screen, not only in the artifact.** `29` and `30` carry
*"Rest-of-season tiers are bands, not lines"* in the disclosure block, again under the chart
legend with the reason (*"Membership reproduces across resamples; the exact cut positions do
not"*), and the draw count is printed as `10000 (declared fallback)` rather than as a plain
number.

**ADR-076's six clauses are all rendered.** `30` shows, in this order: the flag exists as a badge
carrying a glyph *and* `3w` *and* a full sentence for assistive technology; the model statement
*"This estimate uses no injury or practice-report information of any kind. The model infers
absence from appearances alone"*; the cohort's measured weakness *"Ranking quality inside this
group is weak: Spearman 0.311 against 0.797 on the full universe"*; the definition in observable
terms *"has played at least once this season and has not appeared for 3 or more consecutive weeks
ending at the cutoff"*; the population *"54 players on the published board carry this flag; 6 are
in the current view"*. No wording anywhere implies a medical fact, and the badge's colour is the
third channel, never the only one.

**Current status is visibly separate from every model input.** The `Current status` column on `29`
takes a left rule of its own, and both the table caption and the section note say it *"is
annotation and reached no model input"*. `35` is the same separation under failure.

**Behaviour is counts over a named window, never a price.** `31`'s headings are `Adds (24h)`,
`Drops (24h)`, `Net adds`; the facts strip names the source, the requested window and the
retrieval time, and the paragraph below states that the source publishes no observation time of
its own. Nothing on the board is called ADP, a rank gap, an edge or a score, and the one row from
beyond the tier depth is marked `surfaced` and carries no tier.

**A behaviour outage empties columns rather than zeroing them.** `35` shows `—` in all three count
columns with `ROS Exp VORP` untouched, above the notice *"Every rest-of-season value on this board
is unchanged: the behaviour feed decides which players are visible and never what they are worth."*
A zero would have claimed nobody added the player.

**The mode is obvious, and the draft product is not replaced.** The masthead carries the mode as a
chip (`In-Season mode` on `29`–`37`, `Draft mode` on `01` and `38`); the band below it, which
exists only when there is a second board to switch to, carries the cutoff and the three-state
switch. `38` is the draft board in November: the same Tier Board and Arbitrage Board, reached by
`?mode=draft` and kept in the URL.

## Defects found and fixed in this pass

Four, all found by looking at the images rather than by a failing test:

1. **The opportunity table's headings collided** — `ROS RANKPLAYER`,
   `WEEKS SINCE LAST GAMECURRENT STATUS`. `table.sheet thead th` carries no padding of its own; it
   lives on the sort button, or on `.plain` for a header that has none. These had neither.
2. **A wide table's caption ran off the right edge.** A caption takes its table's width, so on the
   ROS board — wider than 1440px — the end of the sentence sat where nobody scrolls to read prose.
   It is now pinned to the scroll container's left edge and wrapped inside the visible width.
3. **The footer named the draft model on an in-season page.** `intrinsic-cb-hurdle-v1` under a
   board served by `intrinsic-ros-v1`, which attributes a rest-of-season number to a model that
   never produced it. In-season it now reads `intrinsic-ros-v1 · phase12_ros_v1`.
4. **The behaviour-outage notice spliced a machine phrase into prose** — *"no retained behaviour
   capture Every rest-of-season value…"*. The build's reason is now quoted and closed.

One more was found earlier, by measurement rather than by eye, and is recorded here because it is
a layout fact: a **season-mode band on every page pushed the arbitrage board below the fold on a
phone** (the rail heading landed at 857px in an 839px viewport). The indicator moved to the
masthead beside the build stamp, where it costs no vertical band, and the band itself now renders
only when there is something to switch to. `e2e/mobile.spec.ts` measures this.

**The two lifecycle windows say something true rather than something convenient.** `39` and `40`
are the states in which the season has started and the draft board is the only board that exists
— opening week, and after the last scored week. Both are ordinary and both last days or weeks,
and the wrong version of either would not look broken: a draft board labelled "Draft mode" in
November is a perfectly tidy screen. The indicator instead reads `SEASON UNDER WAY` and `SEASON
COMPLETE`, a banner states the reason **in the build's own sentence** rather than in one the
frontend composed, and both say the draft board below is unaffected and current. No mode switch
is offered in either, because there is nothing to switch to.

## Known and accepted

**The ROS board scrolls horizontally inside its own container at 1440px.** Sixteen columns of
rest-of-season quantities do not fit a laptop, and `.table-scroll` is the contract for that
(`AGENTS.md` section 11 requires the container, not the page, to scroll). The page itself does not
scroll sideways at any captured width, which the capture script asserts.

**The fixture's add/drop counts are zero for every board player.** That is the fixture, not the
product: only the surfaced row carries counts, because it exists to prove that a player from
beyond the tier depth can be surfaced by behaviour alone. `35` is the same fixture with the feed
removed, which is the comparison that matters.
