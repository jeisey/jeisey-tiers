# Phase-9A visual review — the Claude Design implementation

Twenty-eight screens from real static builds of the fixture board, plus an **interleaved A/B**
performance measurement against the Phase-8 build on the same machine.

This directory does not replace `docs/visual-qa/2026-08-31/`, which is the Phase-8 evidence and
stays as it was. The two are meant to be read side by side: Phase 8's HUD was inferred from the
owner's written brief because the design project could not be reached, and this one is the same
product built from the project's own files.

`docs/DESIGN_SOURCE_MAP.md` is the companion document — what the source contains, how it maps
onto the product, and every deliberate deviation. Read that first; this file is what the
implementation actually looks like.

Regenerate with:

```bash
npm run e2e:build
node web/tests/e2e/static-server.mjs &
node web/tests/e2e/capture-screens.mjs docs/visual-qa/2026-08-31-design
```

Two runs of the same code produce the same images: the fixture board is fixed and the
performance board is seeded.

---

## 1. The design sources

| file | what it is |
|---|---|
| `Player Card HUD.dc.html` | the design document — five artboards across two turns |
| `support.js` | `dc-runtime`, the Claude Design canvas runtime |

Supplied directly to the session by the owner, downloaded by hand from the Claude Design
project. No MCP, no `/design-login`, no fetch of `claude.ai/design/…`. Neither file is
committed: they are a design handoff, and this directory plus `docs/DESIGN_SOURCE_MAP.md` is the
durable record of what they said.

`support.js` turned out to be the canvas editor's template runtime — an HTML template compiler,
a `DCLogic` base class, a `style-hover` attribute compiled into a generated stylesheet, and a
React UMD boot. It carries no product tokens and none of it is reproduced. Two things in it were
still design information and were honoured: every `style-hover` is a hover state and became a
real `:hover` rule, and every `<sc-for>` marks a part of an artboard that is data-driven rather
than mock-up, which is the part that has to survive production data.

## 2. The screens

### Desktop

| screen | what it shows |
|---|---|
| `01-desktop-tiers-ppr-12-all` | artboard 2a: tier gutter, shared axis, glowing medians |
| `12-tiers-all-collapsed` | every tier closed — the whole board's shape in one screen |
| `13-tiers-all-expanded` | every tier open |
| `03-desktop-arbitrage-draft-rail` | the rail in the new vocabulary; no artboard exists for it |
| `15-arbitrage-premiums` | the same encoding on the other side of zero |
| `08-player-injury-detail` | **artboard 1c** — the two-pane card, with a designation |
| `20-player-detail-no-status-record` | no status record at all, which is not "healthy" |
| `21-player-detail-large-bargain` | the largest positive gap on the board, plus an IR badge |
| `22-player-detail-large-premium` | a structural quarterback premium |
| `08d-unpriced-player-detail` | a player the market has not priced |
| `04-desktop-data-methodology` | where the methodology lives, once |
| `11-keyboard-focus` | the focus ring, which is now a real `outline` |

### Tablet

| screen | what it shows |
|---|---|
| `02-tablet-tiers-rb` | the shared grid at 900px |
| `16-narrow-tablet-tiers` | …and at 768px, the last width before the stack |
| `08c-tablet-player-detail` | **artboard 1a** — the rail becomes a header band |
| `17-narrow-tablet-player-detail` | the same variant at 768px |
| `14-tablet-arbitrage-rail` | the rail at 900px, score column dropped |

### Mobile

| screen | what it shows |
|---|---|
| `05-mobile-tiers` | **artboard 2b** — the tier stack, not a compressed desktop board |
| `23-mobile-tier-table` | the canonical table, still a semantic table |
| `06-mobile-arbitrage` | the rail at 390px, anchors dropped |
| `24-mobile-arbitrage-table` | the arbitrage table at 390px |
| `08b-mobile-player-detail-sheet` | **artboard 1b** — the tabbed sheet, intrinsic tab |
| `18-mobile-player-detail-market-tab` | the market tab |
| `19-mobile-player-detail-status-tab` | the status tab |
| `25-mobile-data` | Data at 390px |

### Conditions the launch fixture cannot show

| screen | what it shows |
|---|---|
| `26-matured-market-arbitrage` | medium confidence, a measured trend, a sufficient cohort |
| `27-matured-market-player-detail` | the same condition on the card |
| `07-degraded-market` | the arbitrage artifact withheld |
| `28-degraded-status` | the status artifact withheld; every model value intact |
| `09-schema-refusal` | a contract the build does not understand |
| `10-pages-base-path` | the project-Pages base path |

`26` and `27` are new in Phase 9A and exist because of a Phase-8 finding: every market-sensitive
*test* had been written against a uniformly `low` board with a null trend, a state production had
already left. The component tests were fixed then; there was still no build a human could *look*
at. `web/tests/e2e/build-fixtures.ts` now serves the matured condition as its own site.

## 3. What the review found, and what was fixed

Six defects, all found by measuring or by reading a screen rather than by a failing test.

1. **The tier band was not on the rows' track.** "Adjacent tier bands overlap" is a claim about
   the measurement (ADR-035) and is only true of the picture if the band and the bars are the
   same pixels. Two separate causes: the strip's grid columns were numbered one off, and — after
   that was fixed — `grid-area: span` on the mobile layout, where `span` is a reserved grid
   keyword, so the declaration was dropped silently and the base rule's `grid-column: 5` applied
   instead. Nothing warned. Both are fixed and
   `board.spec.ts › draws the tier band on exactly the track the player bars use` now measures
   it at three viewports.
2. **The axis ticks were not on that track either** — 22px wider, because the rows' column gap is
   inside the lane body and the axis re-derived the geometry instead of reusing it. The axis is
   now built as a lane: an empty gutter cell and a body carrying the row grid. Same test.
3. **The card overflowed its own frame** — 1,002px inside a 768px dialog, so nothing scrolled and
   the status section was simply cut off. An implicit `auto` grid row is sized by its content;
   `minmax(0, 1fr)` is what binds it to the capped container.
4. **A tinted readout failed WCAG AA at 4.36:1.** The kind tint replaces the tile's background,
   so a translucent green composited against the *grid's* cyan wash rather than against the tile.
   Phase 8's rule again: axe reads the pixel. The two tinted tiles are now opaque tokens at the
   colour the tint was meant to produce — 5.26:1 and 5.30:1.
5. **The card's scroll container was not focusable** (`scrollable-region-focusable`), so it was
   unreachable from the keyboard.
6. **The rail's scale strip pushed the document sideways at 320px** by 102px, because the
   three-part label sits in the bar's own column and that column is under 100px on a phone. The
   strip is replaced there by the same statement as a full-width sentence.

Two things were changed because reproducing the source would have been *wrong*, not because they
did not fit:

- The source captions its board axis "Vertical position inside a tier carries no meaning". That
  is false of this board — rows are in fair-rank order and each prints its rank — so the note
  says what is actually drawn.
- The source's cards end sections with paragraphs of methodology. ADR-058 and the owner's
  Phase-8 review put those in Data once. The short markers stay; the paragraphs do not.

## 4. Accessibility

| check | result |
|---|---|
| axe, WCAG 2.2 A + AA, eight surfaces plus the open card | **clean** |
| contrast of every text token against every surface it lands on | **AA**, worst case 4.82:1 |
| keyboard reach, roving focus on both charts, tab order | pass |
| focus indicator on every custom control | pass — now a real `outline`, not a shadow |
| focus restoration to the trigger | pass |
| dialog semantics: `showModal`, focus trap, Escape, backdrop | pass on Chromium |
| reflow at 320px, no horizontal scrollbar | pass on all views |
| reduced motion | pass — the stylesheet still has no animation at all |

The colour work is the substantive part. Four of the source's seven text tones fail AA at the
sizes it uses them: `#4E7397` is 2.80:1, `#5F86AD` is 3.64:1 and `#6E93B8` is 4.32:1 against the
surfaces they actually sit on. The ramp is collapsed to two dim steps, both AA, and the roles
stay separable because the source already separates them by typeface and tracking rather than by
an eleven-unit luminance step. Everything else in the source — all four position hues, the
accent, the bright cyan, the green and the amber — passes unchanged on the dark surfaces.

## 5. Cross-browser

| engine | result |
|---|---|
| Chromium | 13/13 smoke, plus 62 behavioural, mobile and a11y tests |
| Firefox | **not runnable here** |
| WebKit | **not runnable here** |

Unchanged from Phase 8 and for the same recorded reason: this sandbox's egress blocks
`cdn.playwright.dev`, and `npx playwright install firefox` fails at download. The three-engine
gate is the `browsers` job in `ci.yml` (ADR-059). The smoke suite gained a Phase-9A test —
`the player card takes its three design variants from the viewport` — which is deliberately in
the three-engine suite rather than the single-engine one, because layout and `<dialog>` are
exactly what varies between engines.

## 6. Performance

`performance.json` holds the full record. The method matters more than usual here:

**This sandbox's run-to-run noise is larger than the effect being measured.** Three runs of
*identical* code varied by 9.0× on cold load and 6.5× on the arbitrage view, and by 1.1–1.6× on
everything else. A first attempt to attribute cost to individual motifs produced results that
were internally impossible — disabling a background image made sorting ten times *slower* — which
is how the noise was found. So the comparison is an **interleaved A/B**: three pairs of
(Phase-8 build at `00ac5bd`, Phase-9A build) run back to back on one machine, each figure a
median of three runs, each run itself the harness's median of five.

| | Phase 8 | Phase 9A | |
|---|---:|---:|---|
| DOM nodes, default view | 6,969 | 7,003 | +34 |
| DOM nodes, full 300 board | 9,993 | 10,039 | +46 |
| SVG elements | 0 | 0 | unchanged |
| board height, default | 1,405px | 1,690px | **+20%** |
| board height, full 300 | 7,670px | 8,827px | +15% |

| interaction | Phase 8 | Phase 9A | ratio |
|---|---:|---:|---:|
| cold load to first board row | 965 ms | 598 ms | 0.62× |
| sort the 300-row tier table | 640 ms | 546 ms | 0.85× |
| expand all tiers | 511 ms | 744 ms | **1.46×** |
| switch to the full 300-player board | 2,248 ms | 773 ms | 0.34× |
| filter to one position | 237 ms | 237 ms | 1.00× |
| search, after the declared debounce | 362 ms | 360 ms | 0.99× |
| open the player card | 256 ms | 247 ms | 0.96× |
| render the arbitrage view | 486 ms | 627 ms | 1.29× |

Reading this honestly: six of eight interactions are at parity or better, and the two that are
not — expanding every tier, and the arbitrage view's first render — are one-off actions that stay
under a second. The metrics showing an *improvement* are the two with a 6–9× noise band, so those
are not claims. The regression is not attributed to a specific motif, because attribution needs a
quieter machine than this one; what can be said is that it is not DOM growth, since the node
counts are at parity.

**One real cost was found and removed.** The first implementation of the table's two micro-glyphs
nested two spans per glyph, which is **1,200 extra nodes** on a 300-row board — measured, and
exactly what AGENTS.md and the Phase-9A brief forbid. They are now the cell's own
`background-image`, which renders identically and adds nothing to the DOM. That is the difference
between the +1,234 nodes an earlier draft measured and the +34 above.

The board being 20% taller is a real cost with a real cause: the source's row treatment and the
per-tier strip. It is still well below the Phase-6 board's ~1,800px, and the collapse mechanism
Phase 8 added is untouched — every tier closed is still roughly one screen.

## 7. What did not change

No model, artifact, feature, projection, simulation, VORP, fair rank, position rank, tier
membership, tier algorithm, tier penalty, cohort selection, ADP, market confidence, rank gap,
arbitrage score, market trend, source adapter, identity resolution or refresh methodology.

`npm run verify:board` compares the rendered board against the artifact bytes on every production
build and is the check that fails if one had. It runs inside the daily refresh, against real
data, on a runner — this sandbox has no vendor egress and cannot produce a real build (ADR-009),
so that check is pending the first refresh on the merged branch, exactly as it was for Phase 8.
