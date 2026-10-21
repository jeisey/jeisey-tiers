# Visual QA — recent form and breakout categories (ADR-113), 2026-10-21

`capture.mjs` captures the Opportunity Board on the fixture site (`npm run e2e:build` first) at
320×640, 390×844, 390×560 (`short`), 820×1180, 1024×800 and 1440×900:

| key | what |
|---|---|
| `controls` | the board's options (unfolded on a phone): Recent weeks, Breakout, the census line |
| `table` | the table in the default Last 3 lens |
| `dialog` | Zach Ertz's Takeover evidence (the fixture's genuine Takeover: TE15 season → TE3 in W6–W8) |
| `long-name` | a 40-character name beside the badge (the name is replaced in the DOM for the shot) |
| `combined` | `last=2&form=any&espn=lt75&position=wr` — every filter at once |
| `no-results` | `form=sneaking&position=te` — "No players match" |
| `season-lens` | `last=season`: no Recent column, no badges, RoS vs Szn as before |
| `insufficient` | the *too little data* explanation, Last 6 |
| `no-recent` | an older build with no recent form and `form=takeover` in the link |

`before/` is the same `controls` and `table` captures against `main` at `09d54f0`.

`measurements.json` records, per capture, page overflow, controls clipped off-screen, the
dialog's overflow and the Opportunity table's minimum-width slack. Both runs: **0 page
overflow, 0 clipped controls, 0 console errors**.

Table slack (px; the inseason spec requires ≥ 64 at 1024, 1280 and 1440):

| width | main | this change |
|---|---|---|
| 1024 | 103 | 99 |
| 1280 | not captured | 117 (measured with the inseason spec's method) |
| 1440 | 146 | 82 |

At 820 the table scrolled sideways on main too (−77 → −81); on phones it scrolls under the
pinned name column, which carries the badge. The `long-name` capture narrows desktop slack to
12/2 px with a 40-character name — the name column grows for long names on main as well.
