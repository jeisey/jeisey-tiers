# Card portraits — coverage audit and image probe, 2026-11-06 (ADR-117)

Two measurements, kept apart on purpose:

* `coverage-audit.json` — whether a portrait **row exists** (a published provider address) for
  every player a card can be opened for, before and after `portrait_population_v1`, with the
  reason for every player still without one.
* `image-probe.json` — whether those addresses **serve an image** (HTTP 200 with an image content
  type). It does not check that the face is the right person, and the pipeline never makes these
  requests: this was a one-off audit.

**Kirk Cousins** (`gsis:00-0029604`, ESPN `14880`, unique in the identity registry) was on the
ROS board, the Opportunity board, the week-9 projections and the season actuals of the
2026-11-06 build, but had no portrait row: the portrait population was the draft tier board
alone. Serving lost nothing (0 omissions in 5,175 card-shard checks); the record never existed.
His address serves `image/png`.

**Coverage over the 729 card-surface players of the Nov 6 build:**

| | rows | out-of-scope publication | no ESPN id | serving omissions |
|---|---|---|---|---|
| before (tier board only) | 575 | 115 | 39 | 0 / 5,175 |
| after, roster crosswalk | 690 | 0 | 39 | — |
| after, + nflverse player-master gap fill | **720** | 0 | 9 | 0 / 6,480 |

No invalid, conflicting or shared ESPN id was found. The 9 still unresolved are deep tight ends
with no ESPN id on any nflverse bridge.

**Image probe** (HEAD, at most 4 requests/s, User-Agent `jeisey-tiers-audit/1.0`, plus 8 ranged
GETs that all returned a PNG signature):

| group | requests | image served | 404 |
|---|---|---|---|
| newly covered via the roster | 115 | 114 | 1 (Jack Strand, `5344782`) |
| newly covered via the player master | 30 | 29 | 1 (Kevin Foelsch, `5212228`) |
| already published (every 15th row) | 39 | 39 | 0 |
| negative controls (ids `1`, `999999999`) | 2 | 0 | 2 |

A missing athlete is a plain 404, so the card's error handler draws the monogram.
