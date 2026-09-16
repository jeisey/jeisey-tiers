# UX / Visual Product Specification

## 1. Design direction

The site is a **draft utility**, not a sports-media homepage.

Visual character:

- clean
- compact
- high information density
- restrained typography
- neutral surfaces
- strong hierarchy
- minimal ornament
- charts first, tables equally important

Avoid:

- hero art
- gradients for decoration
- glassmorphism
- animated backgrounds
- oversized metric cards
- marketing claims above the data
- fantasy-football clichés (helmets, flames, trophies) unless they serve navigation

## 2. Page anatomy

Desktop order:

```text
[Product name]    Updated <timestamp>    [Methodology]

[Scoring: PPR] [Teams: 12] [Position: ALL]     [Search player]

[Tiers] [Arbitrage] [Data]
---------------------------------------------------------
Primary visualization
---------------------------------------------------------
Compact context / legend / controls
---------------------------------------------------------
Sortable table + export
---------------------------------------------------------
Source/model footer
```

Do not bury the chart under a large header.

## 3. Global state

Persist to URL query parameters:

- tab
- scoring
- teams
- position
- search (optional)

Example semantic state, not binding URL syntax:

`?view=tiers&scoring=ppr&teams=12&position=rb`

State must survive reload/back-forward.

## 4. Header

Contains:

- short product name/logo wordmark only
- last successful refresh, e.g. `Updated Aug 12 · 7:23 AM ET`
- degraded/stale marker if metadata says so
- Methodology/Data link

Avoid navigation beyond what the app needs.

## 5. Tier Board

### 5.1 Core visual metaphor

Horizontal stacked lanes resembling a highly refined S-tier list.

Each lane:

- fixed left rail with tier label (`S`, `A`, ...)
- player marks placed horizontally according to intrinsic DraftValue/VORP, not equal spaced
- subtle horizontal scale/grid if helpful
- vertical order within a lane may use collision avoidance or compact rows; do not imply extra meaning unless encoded

Potential sketch:

```text
S | Bijan ━━━━━●━━━━   Chase ━━━●━━
A | Gibbs ━━━●━━  Lamb ━━━●━━  Jefferson ━━●━━
B | ...
```

The uncertainty interval should appear as a muted line/whisker behind or around a focal point.

### 5.2 Player mark

At default zoom:

- abbreviated position rank (e.g. RB3)
- player last name or full name depending width
- team abbreviation

On hover/focus/click details:

- fair overall rank
- expected/median VORP
- P25/P75 and P10/P90
- expected fantasy points
- uncertainty label
- tier-boundary context if adjacent to a cliff

Player headshots are not required and should not create an image-rights dependency.

### 5.3 All-position vs position view

All-position board uses league-adjusted VORP and exposes position badges.

Position-only view may use the same league-adjusted VORP or position-relative display scale; the UI must not silently change the metric. Label the axis.

### 5.4 Tier cliff cues

At the right/left boundary between segments, optional subtle annotation:

- `value cliff`
- boundary stability/strength in tooltip

Do not clutter every boundary with a text label.

## 6. Draft Rail arbitrage chart

### 6.1 Core visual metaphor

A paired-anchor/slope rail for each player:

```text
Fair/model pick                          Market ADP
34 ●──────────────────────────────● 67   Player Name
```

Coordinate system should make **positive bargain direction intuitively obvious**. Because earlier picks are numerically smaller, consider reversing the x-axis or adding explicit labels so users do not need to reason about number direction.

Recommended visual semantics:

- model/fair anchor = distinct geometric shape
- market anchor = another shape
- connector length = value gap
- arrow/direction or text label communicates bargain/overpay
- sorting defaults to arbitrage score, not raw fair rank

### 6.2 Default population

Show top value opportunities, not all 300 players simultaneously. Default perhaps top 25–40 by positive arbitrage score, with controls to show overvalued/all.

Full table contains everything.

### 6.3 Details

Hover/focus/click:

- fair rank
- ADP
- ADP spread/sample size
- raw gap
- expected surplus VORP if ML mode
- P(positive surplus) if calibrated
- market trend since prior day/week
- the selected market's retained ADP history, drawn by day; under the cross-market view, every
  market's real history on one dated axis, each named and each with its own trend or its own
  reason for not having one. Nothing is averaged into a synthetic cross-market line, and a
  history that is too short for the frozen trend rule is still drawn — showing an observation
  and estimating a slope are different claims (ADR-081)
- intrinsic P10/P50/P90
- arbitrage mode (`Model` or `Market-gap baseline`)

## 6A. In-season boards

The site has two products and one visual system. The rest-of-season board and the Opportunity
Board are the in-season half, and neither has an artboard of its own — the same position the
Draft Rail is in (`docs/DESIGN_SOURCE_MAP.md` section 6).

### 6A.1 Rest-of-season Tier Board

**It is the Tier Board, over a different quantity.** Same component, same stylesheet, same
2a/2b responsive pair, same collapse behaviour and the same URL state. What changes is the
quantity and every word around it:

| | draft board | rest-of-season board |
|---|---|---|
| rank | `fair_rank` | `ros_fair_rank` |
| axis | `Median simulated VORP` | `Median simulated remaining VORP` |
| interval | `p25_vorp` – `p75_vorp` | `ros_vorp_p25` – `ros_vorp_p75` |
| mark label | "median simulated VORP" | "median simulated **remaining** VORP" |

The component is handed neutral marks and a set of strings and never learns which board it is
drawing. That is deliberate: a chart that could tell would be one type coercion away from
comparing two quantities that must never be compared (ADR-071).

Tier bands are drawn exactly as the draft board draws them — a span, never an edge — because
the rest-of-season boundary failed its own stability gate too (ADR-074).

### 6A.2 Disclosure, without spending the fold

The in-season board carries obligations the draft board does not (ADR-076). They are stated,
not displayed at length:

- the sentence that the model uses **no injury or practice-report information** is always
  visible, with no interaction;
- the measured ordering weakness, the tier-boundary statement and the flag's definition open
  from it;
- all of them are rendered from the artifact, never from constants in a component, so a build
  that changed what the model reads changes these sentences with it;
- `Data` states every one of them again in full, which is where methodology lives (ADR-058).

A disclosure a reader must scroll past to reach the board is not more honest than one they can
open; it is the same words costing the first screen.

### 6A.3 Opportunity Board

**Two tracks, two scales, one rule between them, and nothing that spans both.** The board
shows a rest-of-season value in points beside a count of roster transactions over a declared
window. Those have no common unit, so the geometry must make a combined reading impossible:

- each track has its own zero line, its own tick strip and its own heading;
- the divider is a border, not a gap;
- the transaction track is **diverging and symmetric** — drops left of centre, adds right —
  and its bound comes from the population rather than from its worst outlier, with a chevron
  where a count runs past the axis and the real number printed beside it;
- ordering is the reader's, from three choices, and there is no blended score at any point.

Direction is never colour alone: the side of the zero line, the two printed counts and the
row's accessible label all carry it.

Where the behaviour feed is down the track is drawn **empty and labelled**, never as
zero-length bars — "nobody added him" and "the feed said nothing" are different facts and a
reader has to be able to tell them apart.

### 6A.4 Current status on an in-season board

A mark beside the player's name, exactly as the draft board has always carried it, and only
when the artifact's code says something. `ACT` is the ordinary case and renders nothing
(ADR-043). It is never a column: a column of `ACT` is the same non-report five hundred times
and it pushes the model's own columns off the right edge.

### 6A.5 The player card in season

The card belongs to the board the row was clicked on, not to the calendar. From an in-season
board, the `Draft market` section is **replaced** by `In-season usage`: production to date,
workload shares, and roster moves over the declared window, in two blocks that are separated
for the same reason the board's tracks are. The identity rail leads with the rest-of-season
rank and carries the change since preseason and the net adds in place of a market verdict and
an arbitrage score.

The draft board stays reachable all season and keeps its own card, unchanged.

### 6A.6 A number with no scale is not a reading (ADR-086)

`ROS uncertainty 82.1` is correct, published, validated — and answers nothing. Both in-season
sections therefore carry **micro-charts beside the readouts**, and the rule for all of them is
that they place a published value rather than create one:

- **the rank move** is two anchors on the *board's own depth*, with two shapes, two model names
  and the artifact's own `fair_rank_change` between them. Never one rank that moved (ADR-071),
  and never scaled to the player: a three-place shuffle at the top of a five-hundred-deep board
  is drawn as the small thing it is. Where there is no preseason rank there is a sentence and
  no track, because the absence of an earlier ordering is not a move of zero;
- **the pace rail** is points per appearance scored against points per appearance the model
  projects, on **one** axis — permitted here precisely because it is one unit, which is the
  condition the Opportunity Board fails. The card says what it divided (remaining points by
  remaining games) and how many appearances stand behind the observed rate, and never calls the
  ratio an expectation;
- **the cohort strip** places a value among the same position's published rows: the cohort's
  middle half as a band, its median as a tick, this player as a mark, and a reading that always
  names its population — `2nd widest of 7 WRs`, never `2nd widest`. The population is the
  published board, never the reader's current filter.

Three further rules hold across all of them:

1. **The tiles are the record; the meters are the reading.** Every value a meter places keeps a
   readout tile of its own, so a board whose position cohort is too small loses the reading and
   never the number.
2. **A cohort too small to be one says nothing**, and says which case it is in.
3. **No blended score, at any point.** A rank move, a pace gap and an add count have no shared
   unit; averaging them would be the most confident-looking number on the page and the least
   supported. The readings sit side by side and the reading is the reader's.

## 7. Tables

### 7.1 Tier table columns

Default visible:

- Fair Rank
- Player
- Pos
- Team
- Tier
- Expected VORP
- P25–P75 VORP or Floor/Ceiling compact columns
- Expected FP
- Uncertainty

Optional column picker may expose P10/P90 and model metadata if easy, but do not overbuild.

### 7.1A In-season table columns

Both in-season tables are the Tier table's construction — sortable headers, position chips,
tier tags, and the design's micro-glyphs drawn as the cell's own `background-image`. A board
that is a bare grid of numbers beside a board that is not reads as a different product on the
same page.

Rest-of-season table, default visible:

- ROS Rank, Player, Pos, ROS PosRk, Team, ROS Tier
- ROS Exp VORP, ROS P25–P75, Rem FP, Rem G, Uncertainty
- Δ vs preseason, Weeks since last game

Opportunity table, default visible:

- ROS Rank, Player, Pos, ROS PosRk, Team
- ROS Exp VORP, Adds (window), Drops (window), Net adds, Snap share
- Weeks since last game

**Every column name is a rest-of-season name.** `ROS Rank` is never `Rank`: a reader who saw a
bare "Rank" would reasonably read it as the draft one, and the two are not comparable.

**A bar's denominator is stated in the caption.** Adds and drops share one denominator with
each other, because eight adds and eight drops are the same size; the value bar has its own;
the snap-share bar is the percentage itself. A null renders as an em dash with **no bar** —
the feed saying nothing and the feed saying zero are different facts.

The same rule binds a *rank*, and harder (ADR-086). A rank without its population looks exact,
so every cohort reading on the player card prints one, and two readings in one strip may carry
different counts where they come from different artifacts.

### 7.2 Arbitrage table columns

Default:

- Arbitrage Rank
- Player
- Pos
- Team
- Fair Rank
- Market ADP
- Value Gap
- Arbitrage Score
- Expected Surplus (ML only)
- P+ Surplus (ML only)
- Market Trend
- Confidence

Columns that are unavailable in baseline mode should be omitted or rendered `—` with an explanation, not fabricated.

**Every market-derived cell follows the market selector, including Market Trend.** ADP, Value
Gap, Dispersion and Trend on one row must be one market's account of the player. A cell whose
selected market has no value for it renders `—` and says why to a screen reader; it never
borrows another market's number, because a borrowed number is indistinguishable from a real
one on the page (ADR-081).

### 7.3 Table behavior

- compact rows (~36–44 px target)
- sticky header
- obvious sort indicators
- zebra striping optional and subtle
- keyboard focus visible
- no horizontal-scroll surprise on desktop; mobile may scroll or switch to essential columns

## 8. Export

Place export action near table controls, not hidden in a menu hierarchy.

Options:

- `Download full CSV`
- `Export filtered CSV`

Filename pattern:

`ffdraft-tiers-ppr-12-2026-08-12.csv`

and analogous arbitrage file.

## 9. Methodology/Data tab

This is not a long blog post.

Show concise sections:

### What the two models do

- Tier = intrinsic football value, no ADP/ECR input
- Arbitrage = intrinsic value versus draft market

### Freshness

Table of source → as-of → status.

### Model

- version
- trained through season
- top-level holdout metrics
- arbitrage mode baseline/ML

### Definitions

- VORP
- Fair Rank
- ADP
- Arbitrage Score
- prediction intervals

### Sources/attribution

Required source/license attribution links.

Detailed model cards can link to repository files.

## 10. Empty/degraded/error states

### Player absent from market

Tier output remains valid. Arbitrage row may be omitted or marked `No market ADP`.

### Market stale

Arbitrage tab banner: concise, e.g. `Market data is 2 days old; rankings shown from last verified snapshot.`

### Optional source down

No dramatic error if critical output remains valid. Methodology/source status notes degraded source.

### Unsupported URL config

Normalize to nearest valid/default config and update URL; do not crash.

### Artifact schema mismatch

Render a clear technical error with expected vs received schema version; fail safe.

## 11. Responsive design

### Desktop >= 1024

Full chart + table.

### Tablet ~768–1023

Primary target too. Controls may wrap into two compact rows. Chart remains full-featured.

### Mobile < 768

- sticky compact controls or horizontally scrollable segmented control where accessible
- Tier Board may use vertical card alignment inside lanes with axis simplified
- Draft Rail can stack player rows
- the Opportunity Board stacks each row into identity, then its two tracks, each keeping its
  own zero, its own readout and a micro-label naming it
- table uses essential columns and horizontal scroll or a compact row detail expander

Do not create a completely separate mobile product.

## 12. Accessibility

- semantic buttons, inputs, tables
- SVG chart marks focusable or mirrored in an accessible list/table
- chart has text summary and nearby data table; table is the definitive accessible equivalent
- `aria-live` only for important state updates, not every filter interaction
- tooltips accessible by keyboard/focus
- reduced motion disables animated transitions
- tier label text always visible
- positive/negative arbitrage also uses arrow/direction/sign text

## 13. Animation

Allowed only for continuity when changing filters, e.g. 100–200 ms position transitions.

No entrance choreography. Respect reduced motion.

## 14. Visual QA acceptance

Capture Playwright screenshots for at least:

- Tier Board desktop PPR 12-team ALL
- Tier Board tablet RB
- Arbitrage Board desktop
- methodology/data view
- mobile Tier Board
- stale/degraded market state
- rest-of-season Tier Board, desktop and phone
- Opportunity Board, desktop, tablet and phone
- Opportunity Board with the behaviour feed down
- the in-season player card, desktop and phone
- the card's micro-charts: a rank move drawn, a rank move refused because there is no preseason
  rank, a pace gap in both directions, and the behaviour feed down (ADR-086)

Use screenshot review to catch clipping, label overlap, unreadable scales, and Pages base-path failures. Pixel-perfect snapshots should not become brittle blockers for dynamic data unless fixtures are fixed.
