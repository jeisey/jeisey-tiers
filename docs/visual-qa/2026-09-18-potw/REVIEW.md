# Visual QA — Pick of the Week, 2026-09-18 (ADR-088)

64 screens from the fixture build. Screens `01`–`57` are the existing set, re-captured
unchanged; `58`–`64` are new and are what this pass is for.

## Read this before reading the pictures

**The face is not a face**, for the same reason ADR-087's review says so: the fixture's ESPN
ids are synthetic and this sandbox has no egress to `a.espncdn.com`. Every portrait below is a
drawn silhouette served by `web/tests/e2e/portrait-stub.mjs`. What these screens prove is the
**treatment and the geometry**; what a given player's picture is belongs to the build's own
cross-artifact checks.

**The numbers are the fixture's, and the fixture is adversarial rather than realistic.** Four
of the players featured here would not be waiver targets in a real week — `Bijan Robinson` at
900 adds is a synthetic row. What is real is the *shape*: a per-position add bar taken from a
population of 3 to 7 rows, a pool that runs out at different depths for different positions,
and a board where one pick has no preseason rank at all.

## The seven new screens

| screen | viewport | what to look at |
|---|---|---|
| `58-desktop-potw` | 1440 | the four cards. Each seal reads `#1` plus **the position it is a #1 at** and the denominator — four bare `#1`s would read as a ranking of the four against each other |
| `59-desktop-potw-set-2` | 1440 | three cards and one absence line. `Only 1 QB cleared the bar this week, so this set has none` is the state a set deeper than a pool produces, and it is a sentence rather than an empty frame |
| `60-desktop-potw-one-position` | 1440 | the position filter. The chip row writes the **shared** `position` parameter, so the boards beside this one are in the same state |
| `61-tablet-potw` | 900 | one card per row. The portrait keeps its column; the tile rows stay 3-across and 4-across |
| `62-mobile-potw` | 390 | the chip row keeps its label and drops its buttons — the control strip above already carries them, and a second copy costs the fold (ADR-085's finding, reapplied) |
| `63-potw-320` | 320 | WCAG Reflow. No horizontal scroll, the heading wraps rather than pushing the document, and the tiles are one per row so no value is clipped |
| `64-potw-behaviour-absent` | 1440 | the feed published nothing. No cards, a notice naming the build's own reason, and a sentence saying the boards beside this one are unaffected |

## Three defects this review found and fixed

All three were invisible to a passing suite and obvious in a capture — the sixth, seventh and
eighth instances of the species ADR-081 named.

1. **3px of horizontal scroll at 320px, from a heading.** `.section-head h2` carried
   `flex: none`, which held for as long as every section title was short enough to fit.
   "Pick of the Week — through week 8" is not, and an unshrinkable flex item overflows in
   silence. `flex: 0 1 auto` lets it wrap; shrinking engages only on a line that genuinely
   overflows, so every heading that fits today is laid out exactly as it was. **Found by the
   reflow check, not by looking** — which is the check doing its job.

2. **A third of each card was empty, and stretching the portrait to fill it made it a
   sliver.** The first draft gave the portrait a column beside the whole card body. A body
   three times taller than a portrait's ratio leaves dead space; removing the ratio and
   filling the column crops a head-and-shoulders cut-out to a vertical strip, because
   `object-fit: cover` crops what it cannot fit. The portrait now spans the readouts and the
   rationale and stops there, which gives the frame about 3:4 — the layout the mockup had.

3. **A hole in the three-tile row.** `.readout-grid`'s shared
   `> .readout:last-child:nth-child(4n + 3)` spans two columns, which is right in a
   four-column grid and wrong in a three-column one: the third tile wanted two columns, could
   not have them, wrapped, and left an empty cell. Switched off for these tiles.

## What to check against the mockup, and where it deliberately differs

The owner supplied two mockups. The layout is theirs. **Three of their readouts are not in
this build, and their absence is the finding rather than an omission** (ADR-088 §2):

| mockup tile | why it is not here | what is in its place |
|---|---|---|
| `38% ROSTERED` | no source this project may publish from reports an ownership share — Sleeper documents none, FantasyPros' columns are `benchmark_only`, ESPN is `disabled` | `Adds (24h)` — the count, its window, and the bar it cleared |
| `▲ +26% LAST 3 GAMES` | a delta of that same unavailable share, over a window no retained artifact covers | `Net roster moves` — adds minus drops over one window, the one subtraction the opportunity schema sanctions |
| `MATCHUP vs IND (18th vs QB)` | there is no opponent or schedule-strength artifact, and inventing one would be a number with no source | `ROS expected VORP` with its position-cohort reading — which is *why* he is the pick |
| `ADD MOMENTUM` sparkline | no behaviour-history artifact exists; the retained store has the snapshots but nothing publishes a series | the diverging adds/drops strip the Opportunity Board and the player card already draw, on the board's own `movesBound` |

This is `docs/DESIGN_SOURCE_MAP.md`'s own rule applied to a supplied mockup: **read design copy
as a claim to check, not a string to copy.** The same review found the same thing in Phase 9A,
where the design source captioned an axis with a statement that was false of this board.

## What the screens do not prove

- **That the picks are right.** They are the fixture's. Whether the *rule* is right is
  `web/tests/potw.test.ts`, and whether a deployed page matches its artifact is the new
  Pick-of-the-Week block in `verify-real-build.mjs`, negative-controlled four ways.
- **That a real week produces four picks.** The fixture's add counts decay with rank by
  construction; a quiet real week may produce two, or none, and `64` is what none looks like.
