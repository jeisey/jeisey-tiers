# Visual QA — add momentum, 2026-09-19 (ADR-089)

73 screens from the fixture build, captured with `npm run e2e:screens`. The faces are a drawn
silhouette, not faces: `capture-screens.mjs` stubs the portrait host so a review never depends
on a third party's image server (ADR-087). Two screens are new.

## What is new

| screen | what it is for |
|---|---|
| `65-potw-momentum-states` | the whole Pick of the Week tab at 1440px, which carries four of the strip's six states at once |
| `66-potw-momentum-320` | the same tab at 320px, where the two behaviour panels stack |

## The four states on one screen, and why that is not luck

`web/tests/fixtures/artifacts.ts` is built so the default set lands one of each on a card:

| card | state | what it renders |
|---|---|---|
| Jalen Marsh (QB) | the feed has never carried him | a sentence — *No retained history: the feed has not carried him inside the window.* No bars, no em dash, no zero |
| Bijan Robinson (RB) | a full seven-point rising window | seven bars, the newest one bright, `▲ +40.0/day over 6 days` |
| Amon-Ra Bright (WR) | one observation, with a gap beside it | one narrow bar, the gap hairline, `— one observation` |
| Kyle Pitts Sr. (TE) | a falling window | seven bars in the premium tint, `▼ -100.0/day over 6 days` |

The fifth and sixth states — a two-point window and a window genuinely only two snapshots deep
— live in the sets deeper in and in the frontend fixture's `young` variant respectively.

## One defect the capture caught that no test failed on

**A single observation rendered as a full-width bar**, which is the picture of *maximum*
momentum and the exact opposite of what the card was saying beside it in words. `flex: 1 1 0`
gives one bar the whole strip; every assertion about the reading's text passed, because the
text was right.

Fixed with `max-width: 20px` on `.momentum-bar`. A short series now looks short: one bar is one
bar, and seven still share the width evenly because the cap only binds below about four. This
is the ninth instance of the species `SESSION_STATE.md` records (ADR-081, 082, 084, 085, 086,
088 ×3) — a correct number in an incorrect picture — and the second time in this repository
that a capture has been the only thing that could see it.

## What was checked and is right

- **The span is on screen beside every direction.** `+40.0/day over 6 days`, never the rate
  alone. That is the whole price of `behavior_trend_v1` stating a direction from two
  observations, and it is the thing to look at first in any future capture.
- **Direction is not colour alone.** The glyph (`▲`/`▼`), the sign on the number and the
  screen-reader sentence each carry it; the tint is the fourth channel.
- **The two behaviour panels never share an axis.** Today's counts on the board's symmetric
  strip, the window behind them on its own bars, a hairline between. At 320px they stack and
  each keeps its heading — the divider is the meaning, so it survives the reflow.
- **No percentage anywhere.** ADR-088's rule binds the history as it binds the day, and the
  caption still says a count is a count of transactions and not a share of leagues.
- **No horizontal overflow at any captured width.** `capture-screens.mjs` fails the run on more
  than 1px, and it did not.

## Gates run at this code state

```
uv run ruff check .          clean
uv run ruff format --check . clean, 250 files
uv run mypy                  clean, 157 source files
uv run pytest                1,516 passed, 4 live-network deselected
uv run ffdraft build-fixture-artifacts   0 critical, 5 warning (the documented fixtures)
uv run ffdraft validate-artifacts        0 critical, 0 warning
npm run lint                 0 errors, 4 pre-existing warnings (ADR-048)
npm run typecheck            clean
npm run test -- --run        497 passed
npm run e2e                  140 passed (chromium, mobile, a11y)
npm run build                clean
npm run verify:board         0 failures across all six builds
```

Five negative controls against the new pre-deploy checks, all firing: a moved slope, a dropped
point, a nulled direction, an invented gap and a deleted series. They corrupt the **checker's**
copy (`--dist <clean> --data <corrupted>`), because the gate compares the page with the bytes
that page was served and corrupting the dist corrupts both sides — see ADR-089.
