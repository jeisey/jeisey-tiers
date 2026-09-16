# Visual QA — the player card's micro-charts (2026-09-15, ADR-086)

Captured from the fixture builds with `npm run e2e:screens -- docs/visual-qa/2026-09-15-card-meters`,
at 1440 / 900 / 390 CSS pixels. 60 screens; the seven new ones are `51-` to `57-`.

## Why this review exists

ADR-085 put the in-season card together and the numbers in it were right. The owner then asked
a harder question about the same card:

> `ROS Uncertainty` just shows a number, e.g. `82.8`. A viewer has no idea what that means. Is
> that really uncertain? A little uncertain? Are we confident?

That is not a defect a gate can find. `82.1` is the artifact's own `ros_uncertainty`,
`verify:board` compares it against the bytes and agrees, axe has nothing to say about it, and
it answers nothing. The same was true of every other tile in the two in-season sections: a
correct wall of digits with no scale on any of them.

**Nothing here is a new quantity.** Every picture below is made of numbers the build already
published; what is new is that each of them is now *placed* — against the board, against the
player's own position, or against the model's own forecast of the same quantity.

## What the screens show

| screen | what to look at |
|---|---|
| `51-card-rest-of-season-meters` | the rank-move rail: two anchors of different shapes on the board's own 1–18 axis, the artifact's `fair_rank_change` between them, and "two orderings of one board, not one rank that moved" under it. Below the distribution rail, `ROS uncertainty` reads as **an ordinal among its own position** rather than as a bare 47.3 |
| `52-card-breakout-no-preseason-rank` | the branch that must not draw a move: a player the preseason board never held. Two em dashes and a sentence, no track at all |
| `53-card-pace-and-usage` | the pace rail and the production strip for that same breakout: 28.4 scored per appearance against 14.0 projected, the two on one axis because they are one unit, and the four appearances behind the first number printed |
| `54-card-meters-tablet` | 900px: the dossier variant, no identity rail, the same three meters at full card width |
| `55-`, `56-` | 390px: every meter stacks — label and readout on one line, track beneath. The three rank readouts become one line each rather than three tiles of 150px |
| `57-card-usage-no-behaviour` | the feed down: the moves strip drawn empty and labelled, every count an em dash reading `not published`, and the usage readings that do not depend on that feed untouched |

## Checked by eye, on each screen

- **The rank rail is two orderings and never one rank.** Two anchor shapes, two model names,
  the artifact's own change; the diamond sits above the centre line and the square below it,
  so a player both models agree about reads as two marks in one place. On `51-` compare the
  anchor positions against the printed `4` and `1`.
- **A small move is drawn small.** The axis is the published board's depth (18 rows in the
  fixture, 500 in production), not the two ranks — so 4→1 is a short span at the left of `51-`
  and would be a long one for 244→59. Scaling to the player would have drawn both identically.
- **The pace bars share an axis because they share a unit.** Points per appearance either side
  of the cutoff. That is the exact condition the Opportunity Board fails, which is why that
  board draws two tracks and this draws one; the axis strip says the unit out loud on `53-`.
- **The projection is hatched and the observation is solid.** An estimate and a count of what
  happened do not look like the same kind of fact.
- **Every cohort reading carries its population.** `2nd widest of 7 WRs`, never `2nd widest`.
  Two rows in one strip can carry different denominators — the rest-of-season board and the
  opportunity board are different artifacts — which is why the heading names the position and
  each row names its own count.
- **No mark leaves its own track.** The top-ranked player on a min–max axis sits at 100%; the
  glyph is clamped so it stays inside the rail rather than straddling its edge. Check the
  `Points per game` row on `53-`, where the subject is first.
- **A cohort too small to be one says nothing at all**, and the note under the strip says which
  case it is in — the fixture's positions are 3 to 7 rows deep, so it reads "too few rows here
  for a middle-half band" rather than drawing quartiles over four numbers.
- **The tiles are still the record.** Every value a meter places also has a tile of its own, so
  a build whose cohort is too small loses the *reading* and never the *number*.
- **No horizontal scroll at 390px or 320px**, in either in-season tab.

## Gates run alongside

```
npm run lint            # 0 errors, 4 warnings (pre-existing TanStack, ADR-048's category)
npm run typecheck       # clean
npm run test -- --run   # 403 passed
npm run e2e             # 124 passed across chromium / mobile / a11y
npm run verify:board    # five builds, zero disagreements
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

No Python file changed. No model, artifact, schema, feature, rank, tier, count or CSV column
changed; `verify:board` against all five builds is the check that fails if one had.
