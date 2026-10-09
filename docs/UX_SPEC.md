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

- short product name/logo wordmark only. The logo is a real link home: `<a href>` resolved
  from Vite's base (`/` or `/jeisey-tiers/`), no query, so it opens the season-aware default
  view with no tab, Start/Sit or Trade selection and no card. Ordinary link behaviour (new tab,
  copy link) is preserved; its accessible name is "Jeisey Tiers home"; it keeps the global
  focus ring and is the masthead's first tab stop after the skip link.
- last successful refresh, e.g. `Updated Aug 12 · 7:23 AM ET`, in Eastern from
  `build_metadata.generated_at_utc`, with the build's age as visually hidden text for
  assistive technology.

Nothing else sits beside the logo (revised 2026-10-06). The header carries no build-status
button and no season-mode label or dot: degraded artifacts, a stale build (older than the
48-hour refresh window), the quality gate and build notes are reported in the **Data** tab,
which is always one tab away; the season mode is the switch among the controls and the tabs
it changes. On phones the stamp shares the logo's line (the mark is 34px tall below 360px so
320px fits), vertically centred on it.

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

**Since ADR-101 the mark is the availability policy's reading** (`data/availability.ts`), the
same everywhere in season — ROS board and table, Opportunity, Pick of the Week, Start/Sit deck
and week board, Trade chips, pickers, packages and the excluded list, and the card:

| Reading | Chip | Row | What the decision surfaces do |
|---|---|---|---|
| Out for the season (reviewed override + reserve list, or retired) | `OUT · season` / `RET` | held back from the default ROS ranking; elsewhere muted | never a verdict, a pick, or a trade target; as the reader's side of a trade, no search |
| Reserve list or released | `IR`, `PUP`, `RES`, `CUT`… | muted | out of verdicts and picks; a Trade target only with "Include players expected back" (`ret=1`) |
| Out this week | `OUT` | muted; sorts below choices on the week board | out of this week's verdict and picks; rest of season kept, with a warning |
| Doubtful | `D` | normal | out of the default verdict; the card says its numbers assume he plays |
| Questionable | `Q` | normal | comparable; the verdict says "If active" |
| Uncertain (missing, stale, refused, contradictory) | `?` | normal | comparable and inspectable; never featured as clean; never called healthy |
| Available | none | normal | normal |

Muting is a hatched background and a left rule — never opacity, which fails contrast — and
always comes with the chip's text; the chip's accessible text is the headline and the evidence
with its time. The ROS board says how many players are held back, that ranks are the model's
and are not renumbered (a held-back player leaves a gap), and offers "Show players out for the
season" (`unavail=1`); a search that names a held-back player shows him.

### 6A.5 The player card in season

The card belongs to the board the row was clicked on, not to the calendar. From an in-season
board, the `Draft market` section is **replaced** by `In-season usage`: production to date,
workload shares, and roster moves over the declared window, in two blocks that are separated
for the same reason the board's tracks are. The identity rail leads with the rest-of-season
rank and carries the change since preseason and the net adds in place of a market verdict and
an arbitrage score.

The draft board stays reachable all season and keeps its own card, unchanged.

**Amended 2026-09-30 (ADR-096).** A **This week** block sits under the identity rail: the
week's median, floor–ceiling, the startable probability in the reader's league, the game with
its implied team total, and any injury designation with its measured appearance rate, plus a
*Compare in Start/Sit* action that adds the player to the duel (*Open Start/Sit* once he is in
it; only when there is a distribution to compare). A bye or a game with no posted
line says which it is instead of showing numbers.

**Amended 2026-10-01 (ADR-099).** The **This week** block adds the full *Why this week*
reading of section 6A.11.1 item 6b — median, ceiling and floor against a typical week, the
points table and the context chips — fetched with the card (the context is one small file
named in the card's requirement set).

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

### 6A.10 The Opportunity Board as the triage surface (ADR-092)

**The question the board now answers without opening a card: which waiver candidates deserve a
deeper look, and why?** The card is where the evidence lives; the board is where a reader finds
the handful of players worth opening. It shows four readings side by side and combines none of
them: rest-of-season value (the model), role (observed), add momentum (market behaviour) and the
next game (sportsbook context).

#### 6A.10.1 The three readings

| reading | chart | table cell | source |
|---|---|---|---|
| Role | fourth readout, text: `SNAP 81% ▲ +34 pts` | `SNAP 81% ▲ +34 pts` over `wk 8 vs 7 gms` | `player_usage.role_changes[ROLE_METRICS_BY_POSITION[pos][0]]` |
| Add momentum | — | `▲ +55.0/day` over `over 7 days` | `behavior_trend_series.add_trend`, `span_days` |
| Next game | — | `W9 vs ATL` over `27.5 implied` | `team_matchups` for the team the card reads |

- **Role** leads with the position's first mapped metric — pass attempts for a QB, snap share
  otherwise — using the card's own glyph and wording, so the two cannot disagree. A change that
  rounds to nothing is `▬ no change`. Absences: `—` over `not published`, `no record`,
  `no games`, `no latest value`; one appearance is a level over `wk 8 only`.
- **Add momentum** always carries its span. A slope at or past 100/day prints in whole
  transactions (`+72,054/day`, on the card too). Absences: `not in feed` (never `0`), `one obs.`
  over `no direction yet`, `—` when no series was published. A slope whose window **ended
  before the latest snapshot** prints muted with the day it ended — `over 10 hours · to Sep 16`
  — and is not a current reading.
- **Next game** is `W{n} vs|@ OPP` over the implied team points, `no line yet`, or
  `bye W9 · no line yet`. It is not sortable and nothing rates the opponent.

#### 6A.10.2 Filters and orderings

"Show only" holds three toggle chips in the segmented control's frame — **Role rising**,
**Momentum rising**, **Surfaced** — each one predicate over one reading, composing by AND with
each other and with position and search, written to the URL as `only=role.momentum.surfaced`.
The status line beside them prints, per active filter, how many rows pass and how many had no
reading to decide on ("not counted either way"). A chip whose artifact is missing is struck
through and disabled; a link naming it shows a notice and the board unfiltered by it. There is
no chip that counts agreeing signals. Below 768px the chips and the orderings fold behind one
**Options** row that names the ordering, the applied filters and the chart depth; the census
line stays outside the fold (ADR-093, §11).

"Order by" offers ROS value, Adds, Net adds, **Momentum** (current slopes, then ended ones, then
none) and **Role** (rising, flat, falling, no reading; the size of a change is compared only when
one position is on screen, and a note under the chips says which rule is in force).

#### 6A.10.3 Width

The table never scrolls sideways on a laptop, **with room to spare**: at every width a cell or
a two-word heading may wrap when its column is short, below 1280px Team and Drops step aside
(the chart draws every drop count), and below 768px ROS rank and ROS value go too (the chart
prints both) and the player's name is pinned while the readings scroll. "Fits" means at least
64px between the table's minimum width and its container at 1024, 1280 and 1440px — a table
that fits by one pixel on one font rasteriser does not fit on another (ADR-092 correction). The
filtered export keeps its fixed column list whatever a screen hides.

### 6A.11 Start/Sit (ADR-096)

**The question: of these two to four players, who gives me the best chance to win this week?**
Not "who is projected for more": that is a different question whenever two players' ranges
differ and the matchup is not even, and it is the only one other sites answer. The tab sits
second, after the rest-of-season board it is read against: `ROS tiers · Start/Sit ·
Trade · Opportunity · Pick of the Week · Data` (Trade added by ADR-100). State is `duel=00-0036389.00-0039164` (reader's order,
up to four, malformed or duplicate ids dropped and the URL rewritten) and `margin=-12` (an
integer within ±40), so a call can be pasted into a league chat and reopened exactly.

#### 6A.11.1 Layout, top to bottom

1. **The deck** — one chamfered card per slot, lettered A–D in the slot colour: name (opens the
   player card), position, team and game, median in large type, floor / P25–P75 / ceiling, and
   three Halo-style **shield meters** (20 segments, the value printed beside them): *Startable
   week* against this league's threshold, *Win the week* at the reader's margin, and, for three
   or four players, *Top scorer of the set*. The leading card's meter is lit; the rest are
   muted. Empty slots invite an add; a flag line replaces the numbers' meaning for a bye, a
   game with no posted line ("left out of the verdict until then"), a player ruled Out, or a
   game already kicked off.
2. **The verdict** — a kicker word from the head-to-head (*Coin flip*, *Lean*, *Clear*,
   *Strong*; never *certain*), `Start {name}`, and one line: "He outscores {other} N% of the
   time", plus the sealed-season calibration bin it falls in ("favourites given 60–65% won 62.5%
   of 26,327 such calls"). When the pick is the better chance to win but *not* the likelier to
   outscore (a right-skewed range has the higher mean), the line says both halves: "{other}
   outscores him 52% of the time, but his range wins more matchups: 67.0% vs 66.7% chance to
   win the week". A note names the higher-median player when the margin changed the pick.
   **Flip point**: the margin at which the answer changes, in the reader's words ("If you are
   projected to win by more than 6.5 without this slot, start Jahmyr Cook — his floor protects
   the lead"), or "No flip point" with the range checked.
3. **Your matchup without this slot** — a segmented control (Down 20, Down 10, Even, Up 10, Up
   20) and a slider for any integer from −40 to +40, with the measured margin uncertainty and
   the sentence that kickers and defences are not counted in it.
4. **The week, as a distribution** — outcome ridges for every contender on one shared points
   axis, P10–P90 and P25–P75 bands, the median marked, and this league's startable threshold
   drawn at each position.
5. **Head to head** — for three or four players, the matrix of P(row outscores column). Each
   cell prints its percentage; the win / even / loss tint (at 55% and 45%) only reinforces the
   number, and the two cells of a pair always sum to 100%.
6. **Why** — the pick's median as an additive account: the position baseline, seven labelled
   families (Recent production, Role and volume, Availability, His offence, Game environment,
   Opponent, Track record), calibration and rounding, summing to the median shown.
7. **The week board** — every published projection for the reader's filters, ordered by
   Startable (the default with all positions on screen, because it means the same thing at
   every position), Median, Ceiling or Floor; each row has an add/remove toggle, the game and
   implied team total, the opponent's rank against the position, the median and a range bar
   with the league threshold marked. Byes and pending lines sort last and say which they are.
8. **How these numbers are made** — a disclosure with the model, both verdicts, the calibration
   table and the statement of what the model reads and what reads it.

6b. **Why this week** (ADR-099) — after the account of the median, one disclosure per
   contender (the pick open), each answering "why is this week different from his typical
   week":
   * three headlines — **Median**, **Ceiling**, **Floor** — each this week's number with its
     difference from the typical week in words ("3.1 above a typical week (12.0)"), an arrow
     and a sign;
   * a points table, one row per game input that moved any of the three by at least 0.05
     (lines, venue, rest, roof, opponent), with its median, ceiling and floor terms. Each
     row's label is built from published fields: "Team implied for 27.3 pts (usually 23.4)",
     "MIA allows the 5th-most points to WRs", "3 fewer days of rest than the opponent",
     "Indoors (dome)";
   * **context chips without points**: the kickoff forecast ("Forecast: 18 mph wind, gusts 29,
     37°F, 70% chance of precipitation"), a retractable roof ("announced on game day; outside:
     …"), an unverified roof, a dome, a stale or missing forecast, and every lagged starter or
     notable teammate on either report ("BUF offence: OL2 Ross Fixture out", "CIN defence: CB1
     … out"). A team whose report carries no game status yet says so ("no game statuses yet"),
     because unknown is not healthy. Open-Meteo values print their CC BY 4.0 credit beside the
     chips;
   * the sentence that every number is a model attribution against a typical week, not a
     measured cause.

   The deck card carries the compact form (median and ceiling against typical, the largest
   reason with its two values, the first context chip and a count of the rest). The week board
   gains a **vs typical** column: the median's difference with an arrow and the largest
   reason's short name, its full sentence in the accessible label.

#### 6A.11.2 What the tab will not do

- It never prints a player value, a rank or a tier: those are the boards'.
- It never projects a game without a posted line or a player on bye, and never folds an Out
  player into a verdict. It lists them and says why.
- It never discounts a projection for an injury designation. The designation is printed with
  how often it has meant a missed game (Questionable players have played 64% of the time),
  and the projection says it assumes he plays.
- It never uses colour alone: every meter prints its value, every matrix cell its percentage,
  and the slot letter travels with the slot colour.
- It never puts a point value on something the served model does not read. Until a weekly
  model that reads weather or the injury report is promoted (ADR-099), the forecast and the
  report are context chips, and an explanation's numbers are only the published terms of
  inputs the model does read, at the exact level shown.
- It never invents an explanation: a record without a published `explanation` (a bye, a
  pending line, an older build) shows none.

#### 6A.11.3 Width

Four deck cards across from 1100px, two from 360px, one below. The verdict, posture control,
ridges and matrix are one column at every width; nothing scrolls sideways at 320px with four
players in the comparison (`web/tests/e2e/startsit.spec.ts` checks 1440, 1024, 820, 390 and
320px, and the a11y reflow check includes the four-player page). Below 768px the week board
pins the player's name and drops rank and opponent. The view is lazy-loaded. Below 768px the
*Why this week* reading keeps the median and the ceiling and drops the floor's headline and
column (the floor stays on the deck card's range); context chips wrap. The same five widths
are checked on fixtures and on a real build.

### 6A.12 Trade (ADR-100)

**The question: if I offer these players, which packages of the size I want are worth about the
same over the rest of the season — and, among those, which give me the most value, the highest
ceiling or the safest floor?** The tab sits third: `ROS tiers · Start/Sit · Trade · Opportunity ·
Pick of the Week · Data`. Results are called **model-based targets**: combinations of assets to
explore, possibly owned by different managers. One sentence beside the results says the tool
cannot know rosters or whether anyone would accept; nothing prints an acceptance chance, a
fairness verdict, a lineup gain or championship odds.

#### 6A.12.1 Layout, top to bottom

1. **You give** — removable chips (position tag, name opening the player card, roster badge,
   expected value) and a combobox search over the block's published rows (eight suggestions,
   best ROS rank first, players already given excluded, disabled at three). A link naming an id
   the board does not hold shows *Not on this board* and counts for nothing; a long-absence or
   reserve player can be offered, with the ADR-076 sentence.
2. **Controls** — *Prefer* (ROS value · Highest ceiling · Highest floor; ROS value default),
   *Players to receive* (1 · 2 · 3; 1 default, independent of how many are given), *Value
   range* (±10 · ±20 · ±35 · ±50%; ±20 default) and *Positions* (one select per received
   player: Any, QB, RB, WR, TE; all Any by default, so cross-position packages are the
   default).
3. **The shape line** — `Give 1 · Receive 2`, the roster spots it needs or frees, and the
   composition in words. Never "parity".
4. **Helper text** — the horizon from the published records ("Weeks 9–17 (9 weeks), including
   weeks 15–17, where most fantasy playoffs fall; NFL week 18 is not counted. There is no
   playoff-only projection.") and that floor and ceiling are percentiles of *total*
   remaining-season value, not weekly consistency or one game's upside.
5. **Your side** — a readout grid: value, floor, ceiling, projected points, and the value range
   in points. The active preset's cell carries the accent underline.
6. **Up to five packages** — each a chamfered panel: rank, members (position tag, name opening
   the player card, team, badge, expected value), a readout grid (Value, Floor, Ceiling,
   Proj. pts, each with its signed difference from your side; Top asset vs yours; Roster
   spots), and one numerical sentence of why it qualifies ("Value 75.1 is +12.2 (+19.4%)
   against your 63.0, inside ±20%. Smallest piece carries 23% (at least 15% required). #1 of
   13 by ROS value."). Two- and three-player floors and ceilings print with `~`. Actions:
   **Keep** and **Swap**.
7. **More targets · Reset**, and a count: packages that qualify, how many of the best 200 are
   explored, how many dealt. When the dealt order is used up the tab says so and how to
   broaden.
8. **Kept** (up to three) — the same panel, with *Remove*; a kept package that stops
   qualifying after a control or build change stays, marked *No longer qualifies* with every
   reason.
9. **Not targets** — a disclosure listing positive-value players kept out (long absence with
   "has not appeared for N weeks"; roster code), and the count at or below replacement.
10. **How targets are found** — a short disclosure; the full method is in Data.

#### 6A.12.2 States

- **Nothing given**: one line inviting one to three players.
- **At or below replacement** (`V_out ≤ 0`): "Nothing to trade for" with the value, and no
  search.
- **Unpriced outgoing player**: a warning naming him.
- **No package qualifies**: the band in points and the share rule, then explicit buttons —
  *Widen to ±N%*, *Any positions*, *Receive k* — and nothing widened automatically.
- **A link made on another board or other settings**: re-dealt from the start, with a one-line
  notice.
- **No rest-of-season block for the chosen presets**, or no in-season bundle: a notice; every
  other board is unaffected.

#### 6A.12.3 URL, keyboard, width

State is `give`, `goal`, `get`, `range`, `comp`, `keep`, `shown`, `dealt`, `stamp` and, since
ADR-101, `ret=1` (the labelled "Include players expected back" opt-in, part of the stamp only
when on) (ADR-100 §8), defaults omitted; every action pushes a history entry, so Back undoes a swap.
The combobox is keyboard-complete (type, arrows, Enter, Escape); results changes are announced
in a polite live region. Below 768px the packages' readout grid is three columns with each
difference under its number (never cut off), and Keep/Swap span the panel at 40px. Checked at
1440, 820, 390 and 320px (`web/tests/e2e/trade.spec.ts`, `capture-trade.mjs`).

**The tab row** has six in-season tabs. It scrolls sideways rather than shrinking text or
targets (every tab stays 44px tall): the active tab is scrolled into view whenever it changes, a
focused tab is scrolled into view, an arrow key moves focus with the selection, and a solid
`‹` / `›` marker at either edge says there is more row. Below 560px *Opportunity* prints as
*Opp*, its accessible name still "Opportunity". Reduced motion makes the scroll instant.

### 6A.13 Free agents and signings the roster file has not caught up with (ADR-102)

* **"FA" means verified.** The team cell, the card header and the Not projected list print
  **FA** only when the build's employment reading says *unsigned* (no current-roster club, a
  fresh Sleeper record with no club and status Active). A null team with no such evidence
  prints "—", never "FA". FA carries a visually hidden "— unsigned free agent".
* **A free agent is discoverable, not playable.** He is a row on the Opportunity Board (when
  the model has a value for him and managers are adding him) or in **Not projected** (when it
  has none), searchable by name and by "FA", and his card opens. The availability chip reads
  **FA** with the headline "Unsigned free agent — speculative stash": never a Start/Sit
  verdict, Pick of the Week or trade target, muted with text.
* **A signing only Sleeper reports** prints the new club, reads "Signing reported — not yet on
  the official roster" (uncertain), gets no weekly projection and is never featured.
* **Not projected** (Opportunity view, section 03, only when the block has such rows): a plain
  table — player (button to the card) with his chip, position, team, adds, drops, "why listed"
  — most added first. Position and search apply; the ROS value, role and momentum controls do
  not (there is nothing of his to read) and the note says what the section is. The card for
  such a player states "No rest-of-season projection" and leaves rank, tier and value blank.

### 6A.14 Drive breadth, a rail in the role block (ADR-103, ADR-104)

* Sits after the role rails and before the points rail, and **is a rail**: the same grid, the
  same classes, one bar slot per week on the shared week axis, the same absence marks.
* **Label and question, per position:** QB "Designed-run drives — Are runs called for him?";
  RB "Drives with a touch — Every series, or a rotation?"; WR "Drives targeted — A target on
  every drive?"; TE "Drives targeted — Between the 20s, every drive?".
* **Bars:** each game's drive share (drives with one of his opportunities over the team's
  eligible drives) on the shares' absolute 0–100% axis; the latest bar is tinted by direction
  as on every rail.
* **Notch** (RB, WR, TE only — `compares_with_random`): a 2px ink line across each bar at the
  share the same count would reach placed at random. Short of it: bunched into fewer drives;
  above it: spread across more. QB draws no notch.
* **Reading:** the latest drive share, the `role_change_v1` change in points with its glyph,
  and "from X% · week N vs M earlier games" — word for word the share rails' form. One more
  line, RB/WR/TE only: "wks a–b: −23 pts vs random" (whole points, real minus, "level" at
  zero) once the window clears the display minimums, else "vs random: too few targets (5)".
* **Words never used:** better/worse as a verdict, trust, safety, script, coach, predict. The
  role block's note explains the notch and says it is descriptive, not a forecast. No badge,
  tile, filter, sort or column anywhere else; Pick of the Week does not show it.
* Missing play-by-play draws no row; a played game without play-by-play draws "·".

### 6A.15 Season to date beside rest of season (ADR-105)

Every number below is `season_actuals_v1`, read from the `season_actuals/<scoring>` slice; the
page never ranks loaded rows itself. Three states: ranked, **no appearances** (0 points, "—"
rank and rate) and **unavailable** ("—" with the reason; never a model or preseason number).

* **RoS chart — comparison lane** (RoS board only; the draft board is unchanged). Two columns
  after the median value: a lane on its own **logarithmic positional-rank scale**, 1 at the left,
  ending at the next round number past the deepest rank on the whole published block (stable
  under search, filter and collapse; ticks 1, 2, 5, 10, 20, 50 … in the header, gridlines in the
  rows); then the two ranks in words. **Square** = RoS positional rank (upper track),
  **triangle** = season positional rank by points (lower track), hairline between them. Equal
  ranks stack vertically; marks are inset half a mark so rank 1 and the scale's end draw whole.
  In this variant the value lane's median is a **vertical tick**, so the square means a rank
  only. Legend: tick = median remaining VORP, ■ RoS positional rank, ▲ season positional rank
  by points (weeks 1–N); axis note says log scale and that each player is ranked in his own
  position (QB4 and RB4 are separate standings). Phone (2b stack): a third line per row — lane
  across, `■ ROS QB15` / `▲ SZN QB4` in a 4.6rem column (fits `WR104`). The mark's accessible
  label carries both ranks in words.
* **Tables — four columns, same everywhere:**
  * `Szn rank` (position-prefixed, e.g. `QB4`) comes immediately after the RoS positional rank.
  * **`RoS vs Szn`** follows: Szn rank minus RoS rank, in places. `+7` means the model ranks
    him 7 places higher than his production; Shough reads `−10`, with a real minus sign. It is
    `0` when the two agree, and a dash when either rank is missing. The cell's hidden words and
    title say "RoS rank is 10 places below season rank", so the sign is never the only carrier
    and nothing relies on colour.
  * Then `Total pts` and `Avg pts/g` (one decimal, real minus sign).
  * **Sorting, RoS and Opportunity tables:**
    * positional ranks (RoS and season) sort grouped by position, then rank, best first;
    * `RoS vs Szn` sorts as one number across positions, largest first, so the widest gaps
      either way are one or two clicks from the top;
    * points and rate sort high first;
    * missing values sort last;
    * default order is unchanged.
  * The Opportunity "Not projected" list adds `ROS PosRk` ("No RoS projection"), `Szn rank`,
    `Total pts` and `Avg pts/g`. It has no gap column, because it has no RoS rank.
  * **Start/Sit week board:**
    * `Pos rk` becomes **Week rank** (this week's medians, unchanged).
    * `RoS rank`, `Szn rank`, `RoS vs Szn`, `Total pts` and `Avg pts/g` follow `Startable`.
    * On phones, a second sub-line under the name prints `RoS QB15 · Szn QB4`.
    * The board's scroll region is keyboard-focusable.
  * Captions and notes say the season columns are actual results through week N in the
    preset, not projections, and define `RoS vs Szn`.
* **Start/Sit week board sorting:**
  * Every heading except the compare toggle is a sort button, with `aria-sort` and ▲/▼.
  * First click: numbers largest first; ranks, names, kickoff and "Opp. allows" from the top.
  * P10 – P90 sorts by the range's width.
  * Blanks sort last both ways, and ties keep the "Order by" order.
  * On this-week columns, a player who cannot play this week sorts with the blanks.
  * The whole board is sorted before the 40-row page.
  * A status line says "Sorted by X, descending/ascending" and offers "Back to {order}
    order". Any "Order by" choice also clears the column sort.
  * With no column sorted, the Startable or Median heading carries the mark when it is the
    order, and clicking it reverses that order.
  * Headings may wrap to two lines. From 1100 to 1439px, the range bar's floor is 7rem and
    "Opp. allows" prints `7th` (the "of 32" stays for screen readers), so the board fits at
    1280px with ≥32px to spare.
* **Card:** two tags in the identity row, after the position tag and in the same style as it.
  * **`■ ROS QB15`** (or "Not projected", titled "No RoS projection") and **`▲ SZN QB5`** (or
    "No appearances" / "Unavailable") replace the bare RoS rank tag. A screen reader hears "RoS rank" and
    "Season rank". The season tag's title gives the population ("of 53 QBs who have appeared").
  * The two tags move to a new line as a unit, and split only when the pair is wider than
    the whole row.
  * Under the row, one small line reads `Half PPR · through week 4 · RoS is 10 places below
    his season-to-date rank.` (Shough on the live week-4 build).
  * The wide in-season rail uses a square portrait and tighter gaps, so it fits the dialog
    without a scroll.
  * On a short screen the headshot yields first, but never below 9rem, which still shows the
    whole face. Past that the rail scrolls; nothing else in the rail shrinks.
  * The phone sheet's cap is `96dvh`, so its header is never under the browser's toolbars.
* **Card, continued:** The hero becomes **ROS overall rank**. "Production so far": the
  PaceRail's scored side is the actuals' rate; a context box says what each rank measures and
  why they can differ, that the gap is not a fall over time or by itself a model error, and
  prints his rate, the model's remaining points per expected appearance and expected remaining
  appearances, and names the season rank's population; when a snaps-only week makes the games
  counts differ it says so. Readouts:
  Season rank, Games played, Total points, Points per game, then the existing ones.

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

Opportunity table, default visible (ADR-092):

- ROS Rank, Player, ROS PosRk (the position tag with its rank, `RB12`), Team
- ROS Exp VORP, Role, Adds (window), Drops (window), Net adds, Add momentum, Next game

The generic `Snap share` column (a constant for every quarterback) became **Role**, the
position's leading measure; `Weeks since last game` went because the long-absence mark on the
name and the role window carry its one useful reading. Both fields stay in the filtered export.

**Every column name is a rest-of-season name.** `ROS Rank` is never `Rank`: a reader who saw a
bare "Rank" would reasonably read it as the draft one, and the two are not comparable.

**A bar's denominator is stated in the caption.** Adds and drops share one denominator with
each other, because eight adds and eight drops are the same size; the value bar has its own.
The signal columns carry no bar: a role change is in attempts or share points depending on the
position, and a bar would claim one scale. A null renders as an em dash with **no bar** —
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

### How it works (2026-10-09)

The first section of the tab, and only of this tab: a carousel of nine boards that explains
every model in plain English for a reader with no statistics background — mission map, draft
model, simulation/value/tiers, bargain finder (A0), rest of season, Start/Sit v1, Start/Sit v2
(shadow), the tools built on top, and the rules every model follows. Design source: the owner's
"Model Field Briefing" canvas, translated into this stylesheet's tokens (`.hiw-*` in
`base.css`) and its vendored fonts.

- Previous/next buttons wrap; one button per board; arrow keys while focus is inside the
  carousel (never a global handler); the board name is announced politely.
- Phones (below 768px): a second Previous/Next pair under the board, each named for the board
  it opens, brings the new board's top back into view (instant, not smooth). The top row stays
  on one line; below 380px a "02 / 09" counter replaces the per-board bars.
- Status is a word plus a shape (square, diamond, triangle), never colour alone.
- No metric is typed in. Boards describe and link to the generated model cards; the one number
  printed — the start/sit holdout pair accuracy against the best simple rule — is read from
  `ros_build_metadata.weekly.evaluation` and falls back to words when absent.
- Figures are labelled illustrations, `aria-hidden`, each with a sentence saying what it shows.
- Loaded as its own chunk with the Data page, so no other view's first visit pays for it.
- Screens: `docs/visual-qa/2026-10-09-how-it-works/`.

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

- sticky compact controls or horizontally scrollable segmented control where accessible —
  implemented as **reachable, not resident** (ADR-093): the sticky block is one **Settings** row
  that prints every folded value (`PPR · 12 teams · All positions`, then any search term, then
  an overridden season mode) above the tabs, at most 96px and 12% of the viewport; tapping it
  opens the season-mode switch and the four controls between the row and the tabs, Escape folds
  it and returns focus, `/` opens it and focuses search, and on a short screen the open panel
  scrolls inside itself so the tabs stay on screen. Open/closed is chrome, not in the URL.
- the Opportunity Board's orderings, depth switch and "Show only" chips fold behind one
  **Options** row (`By Adds · Role rising · Top 40 of 176`); the filter census line under
  them never folds (ADR-092)
- above 767px nothing folds and nothing is sticky: the rows are not rendered and every pixel
  matches the pre-fold layout
- Tier Board may use vertical card alignment inside lanes with axis simplified
- Draft Rail can stack player rows
- the Opportunity Board stacks each row into identity, then its two tracks, each keeping its
  own zero, its own readout and a micro-label naming it, then its role reading and net adds
- the Opportunity table pins the player's name and leads with Role; rank, team, value and drops
  step aside because the chart above prints them (ADR-092)
- the Start/Sit deck is two cards across (one below 360px), and the verdict, posture control,
  ridges and matrix stack in one column; the week board pins the name (ADR-096, §6A.11.3)
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
- the phone's folded controls: first screen, scrolled, each panel open, a shared link's
  filters named while folded, 320px, and a short landscape screen with the panel open (ADR-093)
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

- the Opportunity Board's signal layer (ADR-092): the table's Role / Add momentum / Next game
  columns in every state the fixture holds (QB attempts, a flat lead, no snap value, one
  appearance, an ended window, one observation, never in the feed, a bye before the next game,
  an unposted line); Role rising + Momentum rising; the role order mixed and one-position; the
  momentum order; a filter the build cannot apply; the feed down; 1024px; 420px board and table;
  320px controls. And the same board on a live build, because the fixture cannot show what six-
  and seven-digit Sleeper counts do to a column

Use screenshot review to catch clipping, label overlap, unreadable scales, and Pages base-path failures. Pixel-perfect snapshots should not become brittle blockers for dynamic data unless fixtures are fixed.
