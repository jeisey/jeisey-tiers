# Design source map — Claude Design → jeisey-tiers frontend

This file is the implementation map for **Phase 9A**. It records what the owner's Claude Design
source actually contains, how each part of it was mapped onto the React product, and every place
the implementation deliberately departs from the source.

It exists because Phase 8 could not read the design. `docs/PHASE8_UI_FEEDBACK.md` item 1 records
that the Claude Design MCP was unreachable and that the Phase-8 HUD was therefore *inferred from
the owner's written brief*. Phase 9A had the files. This document is the difference between the
two, written down so a later session does not have to guess again.

## 1. The source

Two files, supplied directly to the Phase-9A session by the project owner, downloaded by hand
from the Claude Design project. No MCP, no `/design-login`, no network fetch of
`claude.ai/design/...` was involved or is required.

| file | what it is | how it was used |
|---|---|---|
| `Player Card HUD.dc.html` | the design document: 5 artboards across 2 turns | primary visual and interaction source of truth |
| `support.js` | `dc-runtime`, the Claude Design canvas runtime | read in full; **not** a design input |

Neither file is committed. They are a design handoff, not repository content; this document and
`docs/visual-qa/2026-08-31-design/REVIEW.md` are the durable record of what they said.

### 1.1 What `support.js` turned out to be

A generated bundle (`// GENERATED from dc-runtime/src/*.ts`) implementing the canvas editor's
template language: an HTML template compiler (`<sc-if>`, `<sc-for>`, `{{ expr }}`), a `DCLogic`
component base class with `setState`, a helmet that injects `<head>` tags, a `style-hover="…"`
attribute compiled into a generated `!important` pseudo-class stylesheet, and a React 18 UMD
boot from a CDN.

It carries **no product design tokens**. It is exactly the category the brief calls
"design-only JavaScript mechanisms", and nothing in it is reproduced. Two things in it *are*
load-bearing as design information, and both were honoured:

- `style-hover="…"` is how the design expresses a **hover state**. Every one of them was read
  and translated into a real CSS `:hover` rule.
- `<sc-for>` / `<sc-if>` mark which parts of an artboard are **data-driven** rather than static
  mock-up — i.e. which parts must survive real production data. The tier rows, table rows,
  segmented options and nav options are all `<sc-for>`; the three player-card tabs and the three
  views are `<sc-if>`.

## 2. The artboards

`Player Card HUD.dc.html` holds two turns and five options.

| id | title | what it is |
|---|---|---|
| **2a** | Command board — live | the whole application: header, controls, nav, Tier Board, Tier table. Arbitrage is an explicit placeholder. |
| **2b** | Tier stack | an alternative Tier Board: tier blocks with a two-column grid of compact player cells |
| **1a** | Tactical dossier | player card, 780px, one surface, three stacked numbered sections |
| **1b** | Segmented scope | player card, 660px, three tabs, no scroll, distribution rails |
| **1c** | Recon sweep | a 300px hover peek **and** a 1180px two-pane click state |

The design's own captions are design instructions and were read as such:

- 2b: *"Trades the shared axis for density — good for scanning membership on a phone, worse for
  comparing spreads across tiers."* → **2b is the phone variant of the Tier Board**, in the
  design's own words.
- 1c: the two states are labelled `HOVER STATE` and `CLICK STATE`. Our product opens a modal on
  click, so **1c's click state is the desktop player card**.
- 1c peek: *"Peek answers one question — is he underpriced — in under a second."*
- 2a arbitrage panel: *"ARBITRAGE VIEW — NOT PART OF THIS PASS."* → the Draft Rail has **no**
  design source and is an extension (section 6).

## 3. The visual system

Everything below is read out of the source's inline styles.

### 3.1 Colour roles

| role | source value | notes |
|---|---|---|
| canvas | `#050B14`, `#04090f` | plus a radial `#0b1a2b → #050B14` on card artboards |
| panel | `#081422`, `#091523`, `#0c1c2d` | board and card grounds |
| recessed tile | `#0B1A2A` | the metric-tile ground; the single most repeated surface |
| line | `rgba(46,204,255,.08 … .30)` | there is no grey border anywhere — every rule is cyan at low alpha |
| accent | `#2ECCFF` | chips, section indices, underlines |
| accent bright | `#66F1FF` | the value colour: fair rank, medians, active states |
| primary button | fill `#2563A9`, border `#2ECCFF`, ink `#EAF8FF`, hover `#2f76c6` | |
| text | `#E6F3FF` → `#C7E6FF` → `#9FD8FF` → `#8FB2D2` → `#6E93B8` → `#5F86AD` → `#4E7397` | seven steps |
| good / bargain | `#22D19A` | rank gap, tier chip, ACTIVE status |
| warn / caution | `#FFB347` | uncertainty, injury chips, approximate-cohort notes |
| QB / RB / WR / TE | `#B58CFF` / `#22D19A` / `#2ECCFF` / `#FFB347` | `POSC` in the design's own logic |

### 3.2 Geometry

- **Radius is zero.** Not one `border-radius` appears in the design.
- Corners are cut instead, with `clip-path: polygon(...)` — an 8px notch on a glyph box, 12px on
  a tier block, 14–22px on a card. Three different chamfer patterns are used: top-right +
  bottom-left (1a, 2b), top-left + bottom-right (1b), and a two-corner variant on 1c.
- A card frame is a **1px gradient border**: an outer element with `padding:1px` and a
  `linear-gradient` background, clipped identically to the inner surface.
- **The hairline grid is a gap, not a border.** Metric tiles are
  `display:grid; gap:1px; background:rgba(46,204,255,.12)` with opaque tiles — the container's
  background shows through the gap. This is the signature construction and it appears seven
  times.
- Glow is `box-shadow: 0 0 6–10px <colour>` on 5–8px square marks, and `0 0 12–16px` on hover.
- Optional 4px `repeating-linear-gradient` scanlines, **default off** (`scanlines: false`).

### 3.3 Type

- `Exo 2` 400/500/600/700 for all UI text; `JetBrains Mono` 400/500/700 for **every number**.
- Micro-label: `600 9.5px/1 Exo 2`, uppercase, `letter-spacing: .14em`.
- Section header: `600 12px`, `letter-spacing: .18em`, preceded by a two-digit mono index
  (`01`, `02`, `03`) in `#2ECCFF` and followed by a `flex:1` hairline that fades to transparent.
- Numeric readouts: mono at 12 / 13 / 15 / 17 / 19 / 20 / 24 / 28 / 30 / 56px, weight 500.
- Buttons and nav: `600 10.5–12px`, `letter-spacing: .14–.16em`, uppercase.
- Body prose: `400 11.5–12.5px/1.5–1.6`, `text-wrap: pretty`.

### 3.4 Components

| design element | where it appears |
|---|---|
| metric tile (label over mono value, hairline grid) | 1a ×20, 1b ×13, 1c ×15 |
| section header (index · label · fading rule · right badge) | 1a, 1b, 1c |
| annotation bar (2px vertical gradient rule + prose) | 1a ×4, 1b ×3, 1c ×2 |
| position chip (solid accent, dark ink) | everywhere |
| outline chip (1px `rgba(accent,.35)`, `#9FD8FF`) | team, position rank |
| tier chip (green tint) | everywhere |
| injury chip (amber border + tint) | 2a board rows and table rows |
| distribution rail (track, P25–P75 band, glowing median tick) | 1a, 1b, 1c |
| confidence meter (three 4×11px bars, filled to level) | 1b |
| segmented control (1px frame, 1px gaps, inset ring on active) | 2a |
| nav tab (`inset 0 -2px 0` underline on active) | 2a |
| button pair (ghost + primary) | 1a, 1b, 1c, 2a |

### 3.5 Interaction

- `style-hover` on rows: `background: rgba(46,204,255,.06–.08)`.
- `style-hover` on ghost buttons: `border-color:#66F1FF; color:#66F1FF` and, on icon buttons,
  `box-shadow: 0 0 12px rgba(46,204,255,.25)`.
- `style-hover` on primary buttons: `background:#2f76c6; box-shadow: 0 0 16px rgba(46,204,255,.4)`.
- Every transition in the file is `all 160ms`. There is no animation, no keyframe and no
  entrance effect anywhere.
- Active segmented option: `rgba(46,204,255,.18)` + `#66F1FF` + `inset 0 0 0 1px rgba(102,241,255,.5)`.
- Active nav tab: `#66F1FF` + `inset 0 -2px 0 #2ECCFF`.
- Active card tab: `rgba(46,204,255,.16)` + `#66F1FF` + `inset 0 -2px 0 #2ECCFF`.

## 4. Responsive mapping

The source is a set of fixed-width artboards (1440 / 1180 / 780 / 660 / 640 / 300), not a
responsive specification. The mapping below is a decision, made from the artboards and their
captions, and it is the answer to the brief's "reason explicitly about which should become
desktop / large tablet / narrow tablet / mobile".

| viewport | Tier Board | Player card |
|---|---|---|
| desktop ≥1100px | **2a** — tier gutter, shared axis, one row per player | **1c click state** — 268px identity rail + detail pane |
| large tablet 768–1099px | **2a** at reduced column widths | **1a** — stacked dossier, no rail |
| narrow tablet / mobile <768px | **2b** — tier stack, one column of compact cells | **1b** — tabbed sheet, full-height |

Reasoning, briefly:

- 2b's own caption says it is the phone treatment and says why. It is used at one column rather
  than two, because two columns of player names inside 390px would truncate almost every name.
- 1c is the design's answer to "what opens when a row is clicked", which is literally what our
  modal is. Its left rail also front-loads the three things a drafter reads first — fair rank,
  market verdict, status — which is exactly the owner's Phase-8 ask.
- 1a is 780px wide and stacks; it fits a tablet without a rail squeezing the readouts.
- 1b is the only variant designed to **not scroll**: three tabs, `min-height: 392px`. On a phone
  a tab bar beats a 1,400px scroll, and the tab targets are 40px tall.

The 1c **hover peek** is deliberately *not* implemented. `docs/UX_SPEC.md` and AGENTS.md §11
require that no core function depend on hover, and a hover-only card is unreachable by keyboard
and on touch. Its content is not lost: fair rank, ADP, gap, the VORP band and the status line are
the first things in the implemented card's identity rail.

## 5. Keep / adapt / replace against the Phase-8 UI

| surface | verdict | why |
|---|---|---|
| shell layout (wordmark, freshness, status chip, controls, tabs) | **KEEP structure, ADAPT skin** | the design's header is the same five elements in the same order, including a "3 BUILD NOTES" chip that matches `mastheadStatus` exactly |
| segmented controls | **ADAPT** | same construction, different frame/active treatment |
| nav tabs | **ADAPT** | design adds a row-count readout on the right, which we now render from real counts |
| Tier Board structure | **KEEP** | collapse, shared scale, band-not-line, exact ordering all survive |
| Tier Board presentation | **REPLACE** | tier gutter, top axis with ticks, track gridlines, glowing square median, mono readouts |
| Tier Board on mobile | **REPLACE** | 2b tier stack instead of a compressed desktop board |
| Tier table | **ADAPT** | semantic `<table>` kept; header tint, hairline rows, mono numerics, mini P25–P75 track and amber uncertainty bar added from the design's DATA view |
| Draft Rail | **ADAPT** | no design source; Phase-8 semantics kept, HUD vocabulary applied |
| Arbitrage table | **ADAPT** | same as Tier table |
| Player detail | **REPLACE** | three real variants replacing one responsive card |
| status / injury chips | **ADAPT** | design's amber outline chip and green dot-and-word |
| Data view | **ADAPT** | inherits the system, stays quiet, keeps every definition |
| methodology copy placement | **KEEP** | ADR-058 holds; the design agrees with it — its annotations are short and sit only on the card |

## 6. Deliberate deviations

Each of these is a place the implementation does not match the source, and why.

1. **Colour, for contrast.** Four of the design's seven text tones fail WCAG AA at the sizes the
   design uses them. Measured against the design's own surfaces including composited hover
   states: `#4E7397` = 2.80:1, `#5F86AD` = 3.64:1, `#6E93B8` = 4.32:1. The ramp is collapsed to
   two dim steps, both AA: `--ink-faint #7E9BB9` (4.82:1 worst) covers the design's `#4E7397`
   and `#5F86AD` roles, and `--ink-muted #8FB2D2` (6.27:1, the design's own value, unchanged)
   covers `#6E93B8` and `#8FB2D2`. The roles stay distinguishable because the design already
   separates them by typeface and tracking rather than by an 11-unit luminance step. Every other
   colour in the design — including all four position hues, the accent, the bright cyan, the
   green and the amber — passes AA on the dark surfaces unchanged.
2. **Hover and selected surfaces are opaque tokens, not alpha overlays.** Phase 8's finding
   stands: axe reads the composited pixel. `--surface-hover` and `--surface-selected` are the
   pre-composited results of the design's own `rgba(46,204,255,.07)` and `.12`, so contrast is
   deterministic rather than dependent on what is underneath.
3. **Dark only.** The source is a dark HUD and has no light variant. Inventing one would
   reintroduce exactly the "inferred rather than read" problem this phase exists to close, and
   the position hues only clear AA at their design values against a dark ground.
4. **Fonts are self-hosted.** The design links Google Fonts. `docs/ARCHITECTURE.md` §3.2 forbids
   a runtime call to a third party and `web/tests/e2e/board.spec.ts` fails any request that
   leaves localhost. Both families are SIL OFL 1.1 and are vendored as Latin/Latin-Ext variable
   subsets with their licences.
5. **No scanlines, no grid overlay.** Both are off by default in the source
   (`scanlines: false`), both are pure ornament, and the 32px background grid on the card
   artboards is canvas presentation rather than product surface.
6. **Chamfers are used sparingly.** The source cuts corners on cards, tier blocks and glyph
   boxes. Applied to 300 board rows the `clip-path` cost is real and the motif stops reading as
   an accent, so it is kept for the card frame, the tier-stack blocks, the masthead glyph and
   the primary buttons only.
7. **"PIN TO BOARD" and "COMPARE" are not implemented.** They are design affordances for
   features V1 does not have. Inventing them would be product scope, not a reskin.
8. **The 1c hover peek is not implemented** — see section 4.
9. **The design's placeholder ID (`ID · ARSB-DET-11`) is not rendered.** Our canonical key is a
   namespaced identifier that means nothing to a drafter and takes header space a name needs.
10. **Section numbering follows the data.** The design hard-codes `01 INTRINSIC VALUE`,
    `02 DRAFT MARKET`, `03 CURRENT STATUS`. A player with no market price has no section 02, so
    the indices are assigned over the sections actually rendered rather than fixed.
11. **`REGIONAL VALUE GAP` keeps its artifact name.** The design shortens it to `REGIONAL GAP` in
    1c; the full label is what `docs/DATA_CONTRACTS.md` and the CSV call it.
12. **The masthead brand is the owner's logo, not the source's wordmark** (Phase 9B,
    2026-09-01). Artboard 2a's header sets the product name as type beside a notched command
    glyph, and Phase 9A reproduced that literally: a glyph, `jeisey-tiers`, and a mono
    `/ Tiers & arbitrage` sub-label. The owner then supplied `web/src/assets/jt_logo.png`, which
    is the product's actual brand mark, so the artwork replaces all three. The header's *shape*
    is unchanged — brand left, freshness and status chip right, the source's gradient wash still
    running from the left — and only the brand element inside it moved. Nothing repeats the name
    beside the picture: a visible duplicate wordmark would be a second brand, and a hidden one
    would make a screen reader say "Jeisey Tiers" twice. The image is the document's `<h1>` and
    its `alt` is the product name, which is the heading the page never had while the brand was a
    `<span>`. The glyph's chamfer motif survives on the card frame, the tier-stack blocks and the
    primary buttons, so deviation 6 above is unaffected.

## 7. What did not change

No model, artifact, feature, projection, simulation, VORP, fair rank, position rank, tier
membership, tier algorithm, tier penalty, cohort selection, ADP, market confidence, rank gap,
arbitrage score, market trend, source adapter, identity resolution or refresh methodology was
touched. `npm run verify:board` compares the rendered board against the artifact bytes and is the
check that fails if one had.
