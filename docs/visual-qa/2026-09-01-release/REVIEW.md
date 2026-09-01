# Phase-9B release visual QA — 2026-09-01

Eight images, captured from the **fixture** build so two runs of the same code produce the same
pictures (the standing convention in `docs/visual-qa/README.md`). What they show — the masthead,
the export controls and the favicon — does not depend on the data, so a fixture board is the
right surface for them. The *board* was reviewed against the real deployed artifacts instead,
in measurements, by `npm run verify:presets -- --review`; the numbers are in the `live-smoke`
job log and the reasoning for measuring rather than eyeballing is in `SESSION_STATE.md`.

This is a **release-polish** review, not a design review. Phase 9A's
`docs/visual-qa/2026-08-31-design/` is the design record and is not superseded by it.

| file | what it is |
|---|---|
| `ppr-redraft-12-desktop-masthead.png` | the masthead at 1440px — logo left, freshness and status right |
| `ppr-redraft-12-tablet-masthead.png` | the same at 900px |
| `ppr-redraft-12-mobile-masthead.png` | the same at 390px, where the meta row wraps to its own line |
| `ppr-redraft-12-desktop.png` | the whole board at 1440px |
| `ppr-redraft-12-mobile.png` | the whole board at 390px |
| `csv-controls-desktop.png` | both export controls at 1440px |
| `csv-controls-mobile.png` | both export controls at 390px |
| `favicon-16-32-48-on-dark-and-light.png` | the generated icon at 16, 32 and 48px, magnified 6x, on a near-black tab bar (top) and a white one (bottom) |

## What the review confirms

**The masthead is the owner's logo and nothing else.** The Phase-9A wordmark, mono sub-label and
notched glyph are gone — not hidden: `verify:presets --review` asserts zero `.wordmark`,
`.wordmark-sub` and `.masthead-glyph` elements at every viewport, and `board.spec.ts` asserts the
header's text contains neither `jeisey-tiers` nor `Tiers & arbitrage`.

**The mark is sized from the file, not from a guess.** Measured rendered boxes, against the
artwork's own 434:145:

| viewport | logo box | ratio | overflow |
|---|---|---:|---:|
| 1440 x 900 | 143.7 x 48 | 2.99 | 0px |
| 900 x 1000 | 125.7 x 42 | 2.99 | 0px |
| 390 x 844 | 113.7 x 38 | 2.99 | 0px |

The artwork carries transparent margins — its ink is 422x103 inside 434x145 — so a 48px box
paints a ~34px mark. Freshness and status keep their boxes on screen at all three widths.

**Both export controls are one treatment.** Measured label offset from the centre of each
control's own frame, at both viewports:

| control | frame | dx | dy |
|---|---|---:|---:|
| `Download full CSV` | 40px | 0.00 | -0.78 |
| `Export filtered CSV (n)` | 40px | 0.00 | -0.78 |

Before the fix the anchor measured **-14.5px** on `dy` while the button measured -0.78px: a
blockified `<a>` puts its single line box at the top of the frame, and a native `<button>` does
not. The residual -0.78px is the trailing letter-space every tracked control in the app carries
and is deliberately shared rather than corrected here alone.

**The favicon reads as a football from 32px up.** At 16px the laces are gone and it is a small
tilted blue lozenge — the honest ceiling for a 16px tab icon, and the silhouette and hue still
read as this product. Checked on both grounds because the logo's own football is dark navy,
which would have vanished on a dark tab bar; the generated sweep bottoms out at a mid blue for
that reason.

## Regenerating

```bash
uv run ffdraft build-fixture-artifacts --out web/public/data --git-sha 0000000
npm run build
npm run verify:presets -- --review "PPR/redraft-12" --screens docs/visual-qa/2026-09-01-release
```

The favicon sheet is a magnified composite of `scripts/make_favicon.py`'s own output at 16, 32
and 48px over the two grounds.
