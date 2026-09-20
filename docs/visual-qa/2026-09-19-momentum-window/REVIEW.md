# Visual QA — the momentum window at its real length, 2026-09-19 (ADR-090)

All 73 screens were captured with `npm run e2e:screens` and inspected; **nine are committed
here.** The other 64 are the same content as `2026-09-19-momentum/`, captured hours earlier from
the same code minus this fix, and nothing in this change can move them: the only rendering
change is the momentum strip, and the only data change is `behavior_trend_series`, which Pick of
the Week is the sole reader of. The PNGs are not byte-deterministic — every screen differs at the
byte level between two runs — so a second full set cannot be deduplicated by comparison and would
add 15MB for no reviewable difference. The nine kept are every Pick of the Week screen, which is
where the strip lives. Re-capture the full set with `npm run e2e:screens <dir>` when a change can
reach further than this one.

The faces are a drawn silhouette, not faces: `capture-screens.mjs` stubs the portrait host so a
review never depends on a third party's image server (ADR-087).

This is a re-capture against a fixture whose window is now fifteen snapshots rather than seven —
production's own cadence — and a strip that no longer caps itself at twelve bars.

## What changed since the last review

| | before | now |
|---|---|---|
| snapshots in the fixture window | 7, one per calendar day | **15, across 8 dates**, five in one afternoon |
| bars drawn on a full window | 12 (the cap), silently | **15** |
| the two-point case | two points a day apart | two points **seven hours** apart |
| `observations` vs `observation_days` | identical on every record | **15 vs 8** |

## The four states, re-read at 3×

Page-scale screenshots were not enough here: the defect this ADR fixes is a *count*, and twelve
bars beside fifteen looks like fifteen bars at 100% zoom. Each strip was screenshotted on its own
at `deviceScaleFactor: 3` and its bar count read out of the DOM beside it.

| card | state | drawn | reading |
|---|---|---|---|
| Jalen Marsh (QB) | the feed has never carried him | 0 bars, 0 gaps | the absence sentence — no em dash, no zero |
| Bijan Robinson (RB) | a full rising window | **15 bars**, 0 gaps | `▲ +40.0/day over 7 days` |
| Amon-Ra Bright (WR) | one observation, gap beside it | 1 narrow bar, 1 gap | `· — one observation` |
| Kyle Pitts Sr. (TE) | a falling window | **15 bars**, 0 gaps | `▼ -100.0/day over 7 days` |

Heights on the rising window, oldest first:
`69 72 76 81 82 82 82 84 85 86 90 94 95 99 100`. The four near-equal values in the middle are
the five-run afternoon, correctly showing almost no movement across a few hours — the picture
production's cadence actually produces, which no previous capture could contain.

## What was checked and is right

- **The bar count is the artifact's.** Read from the DOM, not eyeballed: 15 where the record
  publishes 15, 1 where it publishes 1. `verify:board` asserts the same thing on the deployed
  bytes and reports zero failures.
- **No overflow anywhere.** 0px of horizontal page overflow at 1440, 1024, 768, 420 and 320.
  The narrowest strip is 261px and bars sit at 15.5–20px; the flex floor fits 65 bars before
  anything spills, which a seven-day window reaches at ~9.4 refreshes a day.
- **The short-series cap still does its job.** `max-width: 20px` is untouched, and Amon-Ra's
  single observation is still one narrow bar rather than a full-width block — the ADR-089
  defect has not come back with the other cap removed.
- **The span is on screen beside every direction**, and the 320px stack still separates the two
  behaviour panels with each keeping its heading.
- **No percentage anywhere.** ADR-088's rule binds the longer history exactly as it bound the
  day.

## One note that is not a defect

**A long window reads flatter than a short one at the same slope.** Bijan's series runs 437→715
adds, which is 69%→100% of peak: about 11px of rise across a 34px strip, spread over fifteen
bars instead of seven. Nothing is wrong — the scale is zero-based because a count's zero is
meaningful (ADR-086), and scaling to the series' own minimum would make every small move look
dramatic. Recorded here so the next reviewer does not read smoothness as a bug, and so that if
the decision is ever revisited it is revisited deliberately.

## Gates run at this code state

```
uv run ruff check .          clean
uv run ruff format --check . clean, 251 files
uv run mypy                  clean, 157 source files
uv run pytest                1,526 passed, 4 live-network deselected
uv run ffdraft build-fixture-artifacts   0 critical, 5 warning (the documented fixtures)
uv run ffdraft validate-artifacts        0 critical, 0 warning
npm run lint                 0 errors, 4 pre-existing warnings (ADR-048)
npm run typecheck            clean
npm run test -- --run        500 passed
npm run e2e                  140 passed (chromium, mobile, a11y)
npm run build                clean
npm run verify:board         0 failures
```

Controls, both directions, all firing: the fixture change alone against the unmodified
component reproduces production's `drew 12 bar(s) … publishes 15 observation(s)`; restoring
`slice(-12)` fails the new vitest case; reverting the fixture to one snapshot per day fails all
three new Python guards; and a dropped point in the checker's copy (`--dist` clean, `--data`
corrupted) fires the bar-count and gap checks together.
