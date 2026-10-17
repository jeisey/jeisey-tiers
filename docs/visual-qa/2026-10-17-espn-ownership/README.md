# ESPN roster and start percentages — 2026-10-17 (ADR-112)

`after/` is this branch. These are captures of the fixture builds (`npm run e2e:build`), taken
with `capture.mjs`:

* `web/dist-in-season`: ESPN published;
* `web/dist-in-season-no-espn`: an older bundle with no ESPN artifacts;
* `web/dist-in-season-espn-stale`: the latest capture is past the 36 h bound.

Portraits are the neutral silhouette from `portrait-stub.mjs`. The fixture's ESPN ids are
synthetic.

`before/` is `main` at `912a299`: the Opportunity Board and the riser's card on the same
fixture, with no ESPN column, ceiling or block.

| file | what |
|---|---|
| `opportunity-<size>.png` | the board as it opens |
| `opportunity-discovery-<size>.png` | `only=role&espn=lt50`: the discovery label, each condition's count, the supporting evidence, the two rows |
| `opportunity-table-<size>.png` | `opportunity=espn7`: the ESPN rost column, highest 7-day gain first |
| `opportunity-no-espn-link-<size>.png` | an older build opened with `espn=lt25`: the ceiling is disabled, the reason is printed, and the board is whole |
| `opportunity-stale-<size>.png` | a stale build sorted by rostered %: values printed muted and labelled stale, the ceiling disabled |
| `card-<size>.png` | Jahmyr Cook's card with the ESPN trend open. On a phone this is the In-season usage tab; elsewhere it is *Show ESPN trend*. |
| `card-readings-<size>.png` | the same card with *Exact readings* expanded |
| `card-first-day-<size>.png` | a player whose first retained read is today: one point, both changes withheld and named |

Sizes:

* `320` = 320×640
* `390` = 390×844
* `short` = 390×560
* `768` = 768×1024
* `1024` = 1024×800
* `1440` = 1440×900

The 320, 390, short and 768 captures are touch.

`after/measurements.json` records the following for each capture:

* `pageX`: the page's horizontal overflow, in px;
* `clipped`: any button or radio outside the viewport that is not inside a horizontally
  scrolling strip;
* `chartOverflow`: for the card, the chart's own horizontal overflow;
* `errors-<size>`: console errors and failed requests.

**Result:**

* All 36 measured captures have 0 px page overflow, no clipped control and 0 px chart overflow.
* There is no console error or failed request at any size.

The Opportunity table scrolls horizontally inside its own frame on a phone, as it did before.

To make room for the ESPN rost column at 1024 and 1280 px, two existing columns now hide:

* season totals, below 1440 px;
* ROS-vs-season, below 1280 px, on Opportunity only.

The table's slack is 103 / 121 / 146 px at 1024 / 1280 / 1440 (`e2e/inseason.spec.ts`).
