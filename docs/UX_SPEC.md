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

**Amended 2026-09-22 (ADR-091).** The in-season section now reads top to bottom in the order a
waiver decision is made: roster moves headline → **Role, week by week** → **Production so far**
→ the cohort strip → **Next game** → roster moves strip → momentum. Section 6A.9 specifies the
two new blocks. The card also renders for a player the draft board never held: identity falls
back to the in-season records, and a player surfaced from beyond the rest-of-season depth gets
the in-season section from his Opportunity Board row, with the projection-dependent pace and
tiles withheld and a sentence saying why — never the draft market card.

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

### 6A.7 The portrait (ADR-087)

The card leads with the player's public ESPN headshot, layered so it reads as part of the HUD
rather than as a picture pasted onto it. Four layers, and each one is doing a job:

| layer | why it is there |
|---|---|
| position-tinted wash | the provider serves a cut-out on a transparent ground; without a ground behind it the player floats and reads as a sticker |
| monogram, always behind | a slow network, an unbridged player and a provider 404 then all look the same and none of them moves the layout |
| scanline veil + two corner ticks | the source's own frame vocabulary, at one DOM node |
| bottom fade to the panel's own ground | the layer that does the blending: it dissolves the cut-out's lower edge into the rail instead of ending it on a line |

**It is a hero at 1c and an identity anchor at 1a/1b.** Full rail width above the name on the
wide variant; a small square beside the name in the header band and in the sheet, because a
rail-width picture in a header band would be a picture with a card beside it, and because the
sheet's whole argument is that fair rank, the verdict and the status line are on screen with
no tap.

**It carries no information and must never be given any.** The name, position, team, tier and
status are all text within a few pixels of the frame. `alt=""`; the monogram and the veil are
`aria-hidden`. It is not a status indicator, not a tier cue, and never a row on a board — a
portrait on three hundred rows would be three hundred third-party requests for decoration.

**It is the only element on the site that fetches from another origin**, it does so only when
a card is opened, and the Data view says so in the reader's own words. See
`docs/ARCHITECTURE.md` section 3.2 and ADR-087 for what that costs and what bounds it.

### 6A.8 Pick of the Week (ADR-088)

**The two in-season boards publish every row and let the reader order them. This tab makes a
claim about four players**, which is a stronger thing to put on a page, so the design is mostly
about making the claim checkable.

One card per position — QB, RB, WR, TE — for the most valuable player at that position the
add/drop feed shows rosters still acquiring. A reader cycles up to five **sets**, where set *k*
holds the *k*-th ranked eligible player at each position. A set is a depth, not a tier: the
players in one have nothing to do with each other beyond sharing that depth, and the copy never
implies otherwise.

**The rule is on the page, not behind it.** Every card prints the add count that qualified the
player, the bar he cleared, and how many players at his position set that bar. A reader who
disagrees with a pick can see exactly which threshold produced it and go to the Opportunity
Board, which has every row and every count behind the decision.

**Behaviour gates; the model orders.** The same sentence the Opportunity Board is built on,
applied to a selection instead of a row. There is no combined score anywhere in this feature
and there must not be: an add count is transactions and a remaining VORP is points, and the
page says so in as many words under the cards.

**The seal names the position it is a seal for.** `#1` beside `WR waiver pick`, with the
denominator — `of 3 eligible` — under it. Four bare `#1`s on one screen would read as a ranking
of the four against each other, which they are not, and a rank without its population looks
exact (section 7.1A, ADR-086).

#### 6A.8.1 There is no rostered percentage, and that is stated

A share of leagues is the obvious way to say whether a waiver target is available, and no
source this project may publish from reports one: Sleeper documents no ownership field,
FantasyPros' ownership columns are `benchmark_only` and may not be redistributed, and ESPN is
disabled in the source registry (ADR-088 §1).

The substitute is the add count itself, and it is honest in one direction only: a roster that
added a player did not have him, so a player rostered almost everywhere cannot post a large
count. It recovers no percentage. **No surface in this feature prints a percentage of leagues,
implies one, or leaves room to infer one**, the tab says so in the reader's own words, and
`Data` says it again in full. Three things a waiver card conventionally shows are therefore
absent by design and replaced rather than faked:

| conventional | why it is absent | what is there instead |
|---|---|---|
| a rostered share | no publishable source reports one | the add count, its window, and the bar it cleared |
| a multi-week ownership trend | a delta of that same unavailable share | **the add count's own history** — see 6A.8.4 |
| a matchup rating | there is no opponent or schedule-strength artifact | the rest-of-season value with its position-cohort reading, which is *why* he is the pick |

The middle row changed in ADR-089 and the distinction it now draws is the point: what remains
unavailable is a trend in *ownership*, because the level it would be a delta of does not exist.
What is available, and now drawn, is a trend in the **counts themselves** — a quantity this
project has been retaining daily since the season opened.

#### 6A.8.4 Add momentum (ADR-089)

The mockup's fourth readout is a small rising bar chart labelled `ADD MOMENTUM`, and until the
retained window was published it was the one element of that design with no source. It is drawn
now, beside today's counts rather than instead of them.

**Two panels, and the split is the product rule.** The left strip is *this window*: how many
rosters moved on him in the last 24 hours, on the board's own symmetric axis, drops left and
adds right. The right strip is *the window behind it*: which way that count has been going over
the days the store actually holds. They are never combined into one score — an instantaneous
count and a rate share no unit — which is the Opportunity Board's own two-track rule applied one
level in. At 320px they stack and each keeps its heading; the divider is the meaning, so it
survives the reflow rather than the layout.

**Bars, not a line.** A line implies a value between two samples and a daily transaction count
has none.

**One bar per retained snapshot, and the strip is never truncated** (ADR-090). A snapshot is a
`daily-refresh` run rather than a day: the schedule fires once most mornings and twice on
Tuesdays, and a morning spent re-running the workflow contributes five, so a seven-day window
routinely holds fifteen and the count of bars is never the count of days. Nothing else in the
panel truncates — the slope, the span, the gap count and the bar scale are all measured over
the whole window, and `behavior_trend_v1` belongs to the artifact rather than to the component,
so a shortened strip cannot restate any of them for the stretch it actually drew. A cap
therefore does not shorten the reading; it makes the picture describe a different window from
the numbers printed beside it, including the vertical scale. Bars shrink to fit instead.

**A direction is never drawn without its span.** `behavior_trend_v1` states one from as few as
two observations, on purpose: an add count moves in hours and the market rule's three-day bar
would admit a waiver signal after the edge has gone. What makes that honest rather than reckless
is that `+320/day` always appears beside `over 2 days`, in the same reading. A span under a day
says hours. One observation prints an em dash and the words `one observation`, because a line
needs two points and a direction of zero would be an invented one.

**A gap is drawn as a gap.** The feed is a top-100 list, so a snapshot the player sat outside
it carries no count at all — unknown, not zero. Those render as a hairline mark rather than a
short bar, and the caption says how many there were. A floor-height bar would read as "nobody
added him", which is a different fact.

**Three absences, three sentences**, on the same principle as 6A.8.2: the build published no
history at all, the feed has not carried this player inside the window, or he has one
observation and therefore no direction yet. A reader can act on the difference.

**Never colour alone.** Direction is in the caption's words, in the arrow glyph and in the
accessible summary; the tint is the fourth channel. The bars are `aria-hidden` and the reading
is a sentence, because announcing every bar would be a dozen-odd announcements of one number.

**Still no share of leagues.** 6A.8.1 binds the history exactly as it binds the day: a count of
transactions has no denominator in leagues however many days of it are drawn. No percentage
appears in a momentum panel, and both a component test and the pre-deploy gate assert it.

#### 6A.8.2 A position with no pick says which case it is in

Three states, and a reader can act on the difference, so they are three sentences and never a
blank card: the behaviour feed published nothing; nobody at that position cleared the bar; or
the pool is shallower than this set is deep. Where the feed is down there are no cards at all,
the build's own reason is quoted, and the notice says the boards beside it are unaffected —
the same construction the Opportunity Board uses for the same outage.

#### 6A.8.3 The portrait, and why it is allowed here

ADR-087's rule — never a portrait on a board row — stands, and this is not a board: at most
four cards, on a tab a reader opened, where the picture is the format rather than decoration
added to a table. Only the visible set's portraits exist in the DOM, so cycling replaces four
requests rather than accumulating twenty, and the frame, the fallback monogram and the
`no-referrer` policy are the player card's own component unchanged.

The portrait spans the readouts and the rationale and stops there. Spanning the whole card body
leaves a third of it empty at a portrait's natural ratio, and filling that space crops a
head-and-shoulders cut-out into a vertical sliver.

### 6A.9 Role and the next game (ADR-091)

**The question the card now answers first: did his role change before his box score did?**
The signal layer publishes what a manager weighs on a Tuesday — the role, the production, the
next game — as observed context beside the model, never inside it. The six concepts stay
separate on the page and in the data: rest-of-season value (model), observed role, opportunity
quality, efficiency, the next game (context), and roster moves (market behaviour). There is no
combined waiver score and there must not be.

#### 6A.9.1 Role rails

Small multiples on one shared week axis, one rail per role metric, with the player's fantasy
points in the reader's preset as the last rail — "has the scoring followed?". Position decides
which metrics lead, in one place (`ROLE_METRICS_BY_POSITION`, `web/src/data/signals.ts`):

| position | rails |
|---|---|
| QB | pass attempts, rush attempts |
| RB | snap share, carry share, target share |
| WR | snap share, target share, air-yards share |
| TE | snap share, target share |

A quarterback's snap share is ~100% and his target share ~0%, so ranking those constants — what
the card did before — is noise. The artifact still carries all six metrics for every player.

- **Scale.** A share keeps its absolute 0–100% scale for every player; a count (attempts,
  points) is scaled to the player's own peak and the caption says which is which.
- **Reading.** Beside each rail: the published latest value, a glyph and signed change
  (`▲ +12 pts`, `▼ −4 pts`, `▬ no change`), the earlier value and the window —
  `from 31% · week 3 vs 2 earlier games`. The glyph follows the printed rounding, so a `▼` never
  sits beside "no change". With no earlier game the window reads `week 1 only` and no change is
  printed.
- **Absence.** A bye (`B`), a week he did not play (`×`) and a played week with no value for
  that measure (`·`, e.g. no snap-count row bridged to him) are three marks, never a
  floor-height bar. Never colour alone: every rail has a screen-reader sentence.
- **Nothing is recomputed.** Every bar, value and change is the artifact's own; the frontend
  selects and formats. `verify:board` compares them against the bytes.

#### 6A.9.2 Production tiles and the cohort strip

A quarterback's tiles and cohort rows are points per game, **EPA per dropback** (null below 20
dropbacks, and the tile says so) and **points from TDs**. Everyone else keeps the two
three-week shares and gains points from TDs (null below 10 points; it can exceed 100% when
turnovers subtracted points). The cohort noun is the position's own (`POSITION_NOUN`: "QBs",
"RBs") — never "players".

#### 6A.9.3 Next game

Opponent, venue (`vs`/`@`, neutral site flagged), kickoff in Eastern time, rest days for both
teams and the roof. When a line is posted: the implied points for each side as a split bar of
the posted total, the spread from this team's side (`Favoured by 3.5`, `Underdog by 6`,
`Pick'em`) and the total, with the build's `sportsbook_context_statement` printed beneath and
the time the lines were retrieved. The subhead says **context · not a model input**. Before a
line is posted the panel says so — an unposted line is never drawn as an even split. A bye
before the next game, or a bye still ahead, is one sentence. There is no matchup *rating*
(ADR-088 stands): the next game is sourced, a judgement about it is not.

#### 6A.9.4 Pick of the Week evidence row

The pick card's secondary tile row (two three-week shares for every position) is replaced by
three labelled blocks: **Role · observed** (the position's leading metrics with their change
and window), **Production** (points per game against the model's remaining points ÷ remaining
games), and **Next game · context** (the compact panel: opponent, implied points, spread and
total, with "Sportsbook context, read by no model."). "Why he is the pick" gains one sentence
only when his leading role grew — the heading makes a claim, and a shrinking role is shown in
the evidence row, not argued for. The selection rule (`potw_selection_v1`) is unchanged.

#### 6A.9.5 Degraded states

Every block stays on the page and says which of the two facts it is — the build did not publish
the artifact, or it did and holds nothing for this player — because a reader acts on the
difference. Selection is unchanged in every row.

| state | card | Pick of the Week |
|---|---|---|
| build published no `player_usage.json` | "This build published no week-by-week role series; every value on this card is unaffected." | Role: "This build published no role series." |
| artifact published, no record for him | "No week-by-week role is published for him on this build." | Role: "No week-by-week role is published for him." |
| build published no `team_matchups.json` | "This build published no schedule context." | Next game: "This build published no schedule context." |
| no record for his team | "No next game is published for his team on this build." | Next game: "No next game is published for DET." |
| line not yet posted | "no line posted yet" hints; no split bar | "No line posted yet — sportsbooks post about two weeks ahead." |

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

### In-season signal layer absent (ADR-091)

The boards, the card and Pick of the Week render in full without `player_usage.json` or
`team_matchups.json`; the role and next-game blocks say which artifact is missing (section
6A.9.5). The build's own warning (`ros.player_usage_failed`, `ros.team_matchups_failed`) is the
reason, and no value elsewhere on the page changes.

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
- Pick of the Week, desktop, tablet and phone; a set deep enough that a position has run out of
  candidates; one position filtered; 320px reflow; and the behaviour feed down (ADR-088)
- the add-momentum strip in each of its states (ADR-089, ADR-090): a full window of *as many
  snapshots as the week actually held* — fifteen, not seven — a two-point window hours rather
  than days apart, a single observation, a window with a gap in it, a falling count, and a card
  whose player the feed has never carried; plus the 320px stack, where the two behaviour panels
  separate. Count the bars against the artifact's `observations`: a strip that silently drops
  its oldest points is the ADR-090 defect, and it is invisible in every text assertion

Use screenshot review to catch clipping, label overlap, unreadable scales, and Pages base-path failures. Pixel-perfect snapshots should not become brittle blockers for dynamic data unless fixtures are fixed.
