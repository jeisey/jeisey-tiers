# Visual QA — the in-season presentation pass (2026-09-15, ADR-085)

Captured from the fixture builds with `npm run e2e:screens -- docs/visual-qa/2026-09-15-inseason-ui`,
at 1440 / 900 / 768 / 390 CSS pixels. 54 screens; the ten new ones are `41-` to `50-`.

## Why this review exists

The first live in-season week published on 2026-09-15. The owner reviewed the deployed site and
found four defects, and **every automated gate had passed on every one of them**: `verify:board`
compared the rest-of-season table against its own bytes and agreed, Playwright was green, axe
found nothing, the artifacts validated, the ROS values were correct to the digit.

They were defects of *presentation*, and a suite that checks whether numbers are right cannot
see whether a board is there. That is the same finding Phase 12 recorded about its own four
screenshot-only defects, one phase later and one level up: it is not enough to picture the
things a test can check.

## What the screens show

| screen | what to look at |
|---|---|
| `41-ros-tier-board` | the board that did not exist. Artboard 2a over remaining VORP: tier gutter, tick header on the interval column, glowing square median, bands that overlap because the values do |
| `42-ros-disclosure-open` | the ADR-076 sentences, one click behind a summary that carries the contractual one |
| `43-opportunity-board-two-tracks` | two tracks, two zeros, two tick strips, a border between them, and no mark that spans both |
| `44-opportunity-board-no-behaviour` | the feed down: dashed empty track, `— / —`, and every rest-of-season value untouched |
| `45-`, `46-`, `47-` | the same two boards at 900 and 390 — the stack, the micro-labels, no horizontal scroll |
| `48-`, `49-` | the card in season: `Draft market` replaced by what the player has actually done |
| `50-draft-card-in-november` | and the draft card, unchanged, on the draft board that stays reachable all season |

## Checked by eye, on each screen

- **Nothing spans the two Opportunity tracks.** The ticks sit on the track column alone, not on
  track-plus-readout — the first draft got that wrong and every bar was shifted by the width of
  its own readout. Compare a bar's end against its printed number on `43-`.
- **A count of zero is not an alert.** `0 / 0` renders muted; only a non-zero count takes the
  green or the red.
- **`ACT` renders nothing.** The status mark appears on `RES` rows and nowhere else, and the
  model's own columns now fit inside the viewport on `41-`.
- **The disclosure summary is legible without opening it** (`41-`), and opening it adds nothing
  the closed state contradicts (`42-`).
- **No name is clipped without an ellipsis**, at any of the four widths.
- **The mobile stack keeps every number.** `47-` is artboard 2b; `46-` gives each row its two
  tracks with a micro-label naming each, because stacked there are no column headers left.

## Gates run alongside

```
npm run lint            # 0 errors, 4 warnings (3 pre-existing TanStack + 1 on the new table)
npm run typecheck       # clean
npm run test -- --run   # 348 passed
npm run e2e             # 117 passed across chromium + mobile + a11y
npm run verify:board    # 5 builds, 0 disagreements
uv run pytest           # clean; no Python file changed
```

`verify:board` covers root, matured, in-season and both ADR-079 lifecycle windows. Its
rest-of-season status check is now a contract — the badge exists exactly when the artifact's
code is noteworthy, and its text is that code — with a negative control in both directions.
