# Search dialog, Start/Sit empty cards, compact phone card header — 2026-10-15 (ADR-111)

`before/` is `main` at `18e743e`. `after/` is this branch. Both are captures of the in-season
fixture build (`npm run e2e:build`, `web/dist-in-season`), taken with `capture.mjs`. The player
card is Puka Nightingale's, opened from ROS tiers.

| file | what |
|---|---|
| `card-<size>.png` | the card as it opens. On a phone the header is compact. |
| `card-<size>-expanded*.png` | after *Expand details*, and on the Skill tree tab |
| `startsit-<size>.png`, `startsit-pair-390.png` | the deck, empty and with a pair |
| `startsit-picker-<size>.png` | the add-player dialog after typing `a` |
| `search-<size>.png`, `search-modal-<size>.png` | the trigger, and the dialog after typing `an` |
| `search-applied-<size>.png` | after ArrowDown + Enter: the applied search above the board |

Sizes: `320` = 320×640, `390` = 390×844, `short` = 390×560, `tablet` = 820×1180, `desktop` =
1440×900.

`measurements.json` holds both runs' numbers. Heights are in px.

| viewport | header (rail) before → after | tab panel before → after |
|---|---:|---:|
| 390×844 | 288 → 81 | 401 → 617 |
| 390×560 | 288 → 81 | 134 → 345 |
| 320×640 | 352 → 81 | 147 → 422 |
| 820×1180 | 209 → 209 | 514 → 514 |
| 1440×900 | 766 → 766 | 667 → 667 |

When the header is expanded on a phone, the rail is capped at half the screen and scrolls past
that: 328 px at 390×844, 280 at 390×560 and 320 at 320×640.

In every capture the page and the card have 0 px of horizontal overflow, and there is no console
error. The search dialog sits 12 px from the top on a phone; on a tablet and a desktop it is
centred.
