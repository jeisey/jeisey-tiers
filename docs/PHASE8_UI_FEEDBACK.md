# Phase-8 human UI feedback backlog

This file exists so that looking at the real site has somewhere to go.

Phase 6 built the draft sheet and verified it against the real 2026 board; Phase 7 deployed
it. Neither phase asked a human to *use* it. That is the next thing, and it is deliberately
sequenced this way: opinions about a Tier Board formed from screenshots of a ten-player
fixture are worth much less than opinions formed while actually reading a 300-deep board on
a phone the night before a draft.

**How to use this document.** Open the live site, use it as you would for a real draft, and
add observations under the headings below. Rough notes are fine and are more useful than
polished ones — "I kept scrolling past the tier I wanted" is a better bug report than a
proposed redesign. Phase 8 reads this file and turns it into work.

**What this document is not.** It is not a decision record. A visual preference is a
preference, and it stays here. An **ADR** is written only when a change would move a binding
product, data or methodology contract — for example changing what a tier *means*, changing
what a number is computed from, or changing a published artifact's schema. Rearranging how
a tier is drawn does not need one; ADR-046 already says a tier is drawn as a band and never
as a line, and that constraint is a finding about the measurement, not a style choice.

---

## The deployment under review

| | |
|---|---|
| Production URL | **<https://jeisey.github.io/jeisey-tiers/> — live since 2026-08-22** |
| Deployed commit at review | `645409b` |
| Refreshing | daily at 07:17 America/New_York; first scheduled deploy [32636603290](https://github.com/jeisey/jeisey-tiers/actions/runs/32636603290) on 2026-08-23 |
| Model | `intrinsic-cb-hurdle-v1` (trained 2014-2025) |
| Arbitrage | `a0_rank_gap_v1`, deterministic baseline |
| Review date | **2026-08-31** |
| Reviewer | project owner |

The build id, code SHA and source timestamps for whatever is live right now are always on
the site's own **Data** tab, read from `build_metadata.json`. That is the authoritative
answer to "what am I looking at"; the table above is a convenience.

---

## Seeded items

These are known before anyone opens the site. They are **non-blocking** — none of them is a
correctness, accessibility or security defect, and Phase 7 deliberately did not "fix" any of
them while deploying.

### 1. The Tier Board is vertically tall, by construction

About 1,800px for the default top-100. The cause is not tier count and not padding: it is
**interval width**. A top back's P25-P75 interval is wider than the entire gap between the
first and twentieth median, so almost no two players can share a lane row without drawing
intervals too short to be true. One player per row at ~17px plus lane padding is 1,800px.

Things that would genuinely change it, and their costs:

- draw a narrower interval (e.g. P40-P60) — cheaper vertically, but it would understate
  uncertainty, which is the one thing this board exists to show honestly;
- drop the interval from the board and keep it in player detail — dense, but then the board
  is a ranked list with colour and the chart earns nothing over the table;
- collapse or virtualise the tail — plausible, and the least dishonest of the three;
- a different visual encoding entirely — open.

This is the item most likely to produce real Phase-8 work, and it is exactly the item that
needs a human who has scrolled it, not a designer who has been told about it.

### 2. Tier lane / display preferences

The owner wants to look at how tiers are presented as bands and whether the default of the
top 100 is the right first screen. Bear ADR-046 in mind: whitespace and a surface change
separate lanes, and no rule, arrow or "value cliff" may be drawn, because boundary agreement
is 0.239 and drawing a hard line would overstate the measurement (ADR-035).

### 3. Draft Rail presentation

Paired anchors per player — filled diamond for fair rank, open circle for MFL ADP — with a
signed sentence per row. Top 30, filtered to Bargains / Premiums / All. Worth judging live:
whether 30 is the right depth, whether the paired-anchor encoding reads instantly, and
whether the sentence or the geometry is doing the work.

### 4. Player card / detail presentation

One `<dialog>` reachable from all four surfaces, with intrinsic, market and current-status
sections. Worth judging: what is missing when you are actually on the clock, and whether the
annotation-only status disclosure is clear without being noisy.

### 5. Things a live look may surface that fixtures cannot

The visual-QA screenshots are of the **fixture** board — ten players carrying the awkward
cases — because a reproducible review needs reproducible pixels. A regression that only
appears at production row counts would not show up there. Specifically worth checking live:
long-name wrapping at 390px, the arbitrage table on a phone, the tier table's sticky header
over 300 rows, and how the quarterback premiums read to someone who has not read ADR-034.

---

## Observations

Add below. One heading per surface; anything that does not fit goes in **Other**. The
seeded items above were written before anyone opened the site; the section that follows is
what the owner actually said after using it.

---

## Owner feedback — 2026-08-31

Recorded verbatim in substance by the Phase-8 session, from the owner's own notes. This is
**feedback**, not a decision record: nothing below is binding until it is implemented, and
anything here that would move a product, data or methodology contract gets its own ADR.

The status column in [Implementation trace](#implementation-trace-2026-08-31) is filled in
as the work lands.

### Global design direction

The frontend should be substantially re-skinned using the supplied Claude Design project.
The design is the **visual and interaction source of truth**. The repository remains the
source of truth for model semantics, artifact values, fair ranks, tiers, arbitrage
calculations, source provenance, accessibility and degraded-mode behaviour.

No number may change because a prettier layout would look better.

### Redundant explanatory copy

The UI repeats methodology caveats too aggressively. Durable methodology explanations belong
in the **Data** tab once, not on every player and every board.

Specifically, remove this from every Player Detail modal:

> Current status annotation — not included in the projection or the model. The board above
> was produced without any of these fields. Source: nflreadpy, sleeper.

and remove repeated per-view/per-player paragraphs like:

> Approximate cohort. MyFantasyLeague ADP cannot filter drafts to this exact scoring and
> league size...

> Approximate cohort. MyFantasyLeague cannot filter drafts to this exact scoring and league
> size, so the price comes from the closest population it can express.

The board may keep a concise, non-intrusive indicator — `MFL ADP · approximate cohort` —
where truthfulness needs it. Player detail may show `Market confidence: Medium` and the
relevant direct data without a paragraph re-teaching the confidence rubric every time.

**Truthfulness must not be reduced — only repetition.** Every disclosure removed from a
repeated surface must still exist, once, in Data / Methodology.

### Player detail

The dialog carries too much repeated descriptive information. The redesigned card should
lead with what a drafter needs immediately:

player · position/team · fair rank · position rank · tier · projection/value · uncertainty ·
MFL ADP · rank/value gap · arbitrage score · recent market trend · relevant current
injury/practice/status · concise market evidence or sample where useful.

Long methodology explanations belong in Data.

### Visual redesign

The Claude Design source should drive the redesign of the application shell, the player
card, the Tier Board, the Draft Rail, the controls, the tables, status/injury presentation,
information hierarchy and responsive behaviour.

The design project contains multiple views and variants. **Do not mechanically reproduce a
single desktop screenshot across every component and device** — reason about which treatment
suits each surface and viewport.

### Player-card responsive decision

Choose the best variant by device and context:

- **desktop / large tablet** — the richer HUD/detail-card treatment, where the width exists;
- **narrow tablet / mobile** — a compact variant or a sheet/full-screen presentation, if that
  better preserves readable hierarchy, touch targets, no horizontal scrolling and immediate
  access to the highest-value draft information.

Modal semantics are not negotiable: focus trapping, Escape dismissal, focus restored to the
trigger, an accessible title, keyboard usability and backdrop behaviour. Native `<dialog>`
semantics may be kept while its visual treatment changes. Do not sacrifice accessibility to
mimic static design markup.

### Tier Board

The board is about 1,800px tall for the top 100 because wide uncertainty intervals prevent
dense row packing. The visual encoding may now be redesigned. **Do not fake narrow
uncertainty intervals to reduce height.** Legitimate approaches include denser tier
cards/rows with a compact uncertainty glyph, expandable tier groups, progressive disclosure
beyond the draft-relevant portion, a compact interval mini-bar rather than a full chart row
per player, virtualisation, or another design-derived encoding.

Required invariants: fair rank exact; tier membership exact; P25/P75 (or the uncertainty
information) still available; tier boundaries still statistically soft; no hard cliff drawn
between adjacent tiers; no implied separation stronger than the model measured; the complete
300-player table still reachable.

The redesign should make the product materially easier to scan during a live draft.

### Tier boundary finding

Do **not** lower ADR-035's stability threshold to make the tier methodology "pass". The
empirical result is meaningful: membership is relatively reproducible, precise boundaries are
not. For V1 that is an accepted limitation, not a defect needing a new statistical algorithm
during final hardening. If the new visual treatment makes individual boundary positions less
prominent, that is a feature. Do not alter tier generation in Phase 8 unless an actual
correctness defect is found.

### Draft Rail

Reassess the rail against the design language. The paired-anchor semantics stay: fair rank,
MFL ADP, signed difference, bargain/premium direction. Evaluate whether the line is
necessary, whether the signed text is redundant, whether a more compact HUD row reads faster,
whether top-30 is still the right depth, and whether Bargains / Premiums / All should remain.
Use real 2026 data. Do not turn rank-gap arbitrage into an implied probability or a projected
surplus — A0 stays deterministic.

### Remove redundant methodology copy

Systematic copy audit across Arbitrage, Player Detail, status blocks, notices, legends and
Data. The principle: **context on the board; methodology in Data.** A board should explain
enough to stop a user misreading a number; it should not re-teach the methodology.

Keep `Market confidence · Medium`; move the full rubric to Data. Keep `MFL ADP · approximate`;
move the full filter/cohort explanation to Data. Keep an injury/status badge; move the
standing "status is annotation only" explanation to Data.

### Audit stale launch-state UI copy

The system has matured since Phase 6. Search frontend code and docs for language true only at
launch: *every row has low confidence*, *market data is early*, *trend is still collecting*,
*trend is always null*, *cohort has 125 drafts*, *player status fields are always null*, *no
site has deployed*, *no current market trend exists*.

Do not replace one hardcoded contemporary value with another. Prefer data-driven conditional
UI: the product must move low → medium → high with no code change, and a future null trend
must still render correctly from the same component.

### `wide_market_range`

Technically true and weakly discriminating. Do not retune the threshold to make it fire less.
De-emphasise or remove it from repetitive visual treatment, keep exposing the actual ADP
low/high range where useful, explain the meaning once in Data, and retain artifact provenance
if downstream compatibility requires it.

---

## Implementation trace (2026-08-31)

One row per owner item, with what was done and where. Visual choices are not ADRs; three
changes here did move a binding rule and have one each.

| # | Owner item | Status | What was done, and where |
|---|---|---|---|
| 1 | Claude Design MCP as the design source | **resolved in Phase 9A (2026-08-31)** | Blocked for the whole of Phase 8 and recorded as such: `DesignSync` refuses without `/design-login`, which cannot run non-interactively, and an unauthenticated fetch of the project URL returns 403, so the Phase-8 design language was **derived from the owner's written brief** rather than read out of the project. The owner then downloaded `Player Card HUD.dc.html` and `support.js` by hand and supplied them directly to a session — no MCP needed, and none used. Phase 9A implements them. **`docs/DESIGN_SOURCE_MAP.md`** is what the source actually contains and how each part maps onto the product; **`docs/visual-qa/2026-08-31-design/REVIEW.md`** is the implementation and its evidence. The "in more detail" note below is kept as the record of what was inferred, so the two can be diffed. |
| 2 | Re-skin shell, card, board, rail, controls, tables | **implemented** | A HUD vocabulary shared by all three surfaces: a hairline panel on a recessed ground, a small-caps micro-label over a tabular readout, geometry that carries a value. `web/src/styles/base.css`, `charts/TierBoard.tsx`, `charts/DraftRail.tsx`, `app/PlayerDetail.tsx`, `app/ArbitrageView.tsx`. |
| 3 | Player detail leads with what a drafter needs | **implemented** | Two readout grids on a recessed panel: fair rank, position rank, tier, median VORP, P25–P75, uncertainty; then MFL ADP, value gap, arbitrage score, market trend, market data, observed picks. Everything else moved into one `<details>`. `app/PlayerDetail.tsx`. |
| 4 | Player-card responsive variants; modal semantics kept | **implemented** | One DOM, two presentations chosen by width: a centred card ≥768px, a bottom-anchored full-width sheet below it. Native `<dialog>` + `showModal()` in both, plus explicit focus restoration to the trigger — verified on Chromium, Firefox and WebKit. `base.css`, `PlayerDetail.tsx`, `web/tests/e2e/mobile.spec.ts`, `smoke.spec.ts`. |
| 5 | Tier Board denser, without falsifying uncertainty | **implemented** | Same P25–P75 interval on the same shared scale; the bar is narrower only because it no longer shares horizontal space with a name label. Tiers collapse past the draft-relevant top, and the open set is in the URL. **1,800px → 1,405px** default and **~230px** with every tier closed, measured on a production-scale board. `charts/TierBoard.tsx`, `app/TiersView.tsx`, `data/state.ts`. |
| 6 | Tier groups stay soft; no hard cliff | **implemented** | No rule, arrow or cliff anywhere. A collapsed tier draws its own P25–P75 span as a band on the *same grid column* as the player bars, so adjacent bands visibly overlap — the measurement drawn rather than footnoted. `12-tiers-all-collapsed.png`. |
| 7 | Draft Rail reconsidered against real data | **implemented** | The 1-to-300 pick axis is gone: it had to reach a −206-pick quarterback premium, leaving a real 8.5-pick bargain at 3% of the width. The bar is now the signed gap on a symmetric scale sized to the rows shown, clipped with the exact number kept. Top-30 and Bargains/Premiums/All both retained. `charts/DraftRail.tsx`. |
| 8 | Remove the per-modal status paragraph | **implemented** | Replaced by `Annotation only — not a model input.` The full disclosure is in Data. `PlayerDetail.tsx`, `DataView.tsx`, pinned by `app.test.tsx`. |
| 9 | Remove repeated cohort paragraphs | **implemented** | The card shows `approximate cohort` under the ADP when the build says so; the Arbitrage panel shows `MyFantasyLeague ADP · approximate cohort` once. Build-level flags are suppressed per row by `BUILD_LEVEL_MARKET_FLAGS`. `data/flags.ts`, `ArbitrageView.tsx`. |
| 10 | Removed disclosures still present once in Data | **implemented** | Data gained definitions for market-data confidence, observed pick range, approximate cohort and current status, plus the trend rule. `app.test.tsx` fails if the card drops a marker *or* if Data drops a definition. **ADR-058.** |
| 11 | Confidence state data-driven | **implemented** | `marketHeadline` reports whatever the rows carry — one label or a distribution — and the tone follows the evidence. No branch assumes a condition. `data/market.ts`. |
| 12 | Trend state data-driven | **implemented** | The panel says `measured` or `collecting` from `build_metadata`; a null row still renders an em dash and never a zero. Both paths exercised by both fixture conditions. |
| 13 | No launch-only assumption survives | **implemented** | Three pieces of asserted copy replaced by derived copy, and a second fixture market condition added so the *tests* can no longer pin one either. `web/tests/fixtures/artifacts.ts`. |
| 14 | `wide_market_range` de-emphasised, range shown, explained once | **implemented** | Not rendered anywhere; the actual `market_adp_low`/`market_adp_high` range is shown on the card and in the table; Data defines what the range is. Threshold untouched, flag still on the artifact and in the CSV. |
| 15 | Tier stability threshold untouched | **implemented** | `min_boundary_agreement` is 0.50, unchanged. The redesign makes boundary positions *less* prominent, which is the feature the owner asked for. |

### On item 1, in more detail

The brief was explicit that the literal Claude Design request is how to *acquire* the project,
not a instruction to reproduce one HTML file. That reading was followed — what is missing is the
acquisition itself. Concretely, this is what could **not** be checked against the source:
exact type scale and weights, the project's own spacing ramp, its panel and border treatment,
its status-chip vocabulary, and whichever player-card variants it offers.

What was implemented instead came from the brief's own vocabulary, and every choice is written
down where it can be diffed later: the design tokens and component classes are in one
stylesheet with comments explaining each decision, and `docs/visual-qa/2026-08-31/REVIEW.md`
shows eighteen screens.

**What the diff turned out to be.** Phase 9A read the source and the five unknowns above resolve
as follows. Exact type: Exo 2 for text, JetBrains Mono for every number — Phase 8 used the system
stack, so this is the largest single visual difference. Spacing and panels: a 1px grid `gap` over
a tinted container as the hairline, which Phase 8 drew as borders. Borders: no grey rule anywhere
and no border-radius anywhere — corners are *cut*, which Phase 8 did not do. Status vocabulary:
an amber outline chip and a green dot-and-word headline, close to what the brief produced.
Variants: five artboards, including three distinct player cards, where Phase 8 had inferred two.

The brief was a good guide and the inference was mostly right about *language*; what it could not
supply was the type, the hairline construction and the third card variant. That is the honest
measure of the gap, and it is why the row above is worth having been marked blocked rather than
quietly implemented.

### Decisions this produced

- **ADR-057** — simulation convergence audited separately from tier-boundary stability.
- **ADR-058** — methodology once in Data; a board carries only what stops a number being misread.
- **ADR-059** — single-engine behavioural suite, three-engine smoke; dependency set amended.

Everything else was a presentation change and correctly has no ADR. **Phase 9A produced no ADR
either**, for the same reason: implementing the design source moved presentation, not a binding
product, data or methodology contract. Two of its choices are worth knowing about anyway and are
recorded in `docs/DESIGN_SOURCE_MAP.md` section 6 rather than as decisions — the product is now
dark-only, because the source is a dark HUD with no light variant; and two OFL web fonts are
vendored, because the source's typography is part of its identity and a runtime call to a font
CDN is forbidden by `docs/ARCHITECTURE.md` section 3.2.

---

## Also waiting for Phase 8, from elsewhere — all now answered

Recorded in full in their own places. None was a UI question and none was answered by looking
at the site.

| item | where it lives | Phase-8 outcome |
|---|---|---|
| Multi-source fantasy market-price study | `docs/DATA_SOURCES.md` §16, **ADR-053**, **ADR-056** | **Deferred, deliberately.** FFC's findings are accepted as measured fact; integration is a post-V1 market-methodology change, not a hardening change. MFL remains the sole V1 price source. No multi-source ADP, no averaging. |
| Monte Carlo convergence rule re-specification | ADR-034, **ADR-057** | **Done.** Frozen first, run second. Ranking is converged at 10,000 draws and value is not, by 19-29%. Production draw count unchanged and unchangeable by this rule. |
| Tier boundary stability | ADR-035 | **Threshold untouched**, as instructed. The redesign makes individual boundary positions less prominent and draws the tier spans overlapping, which is the honest picture. |
| `wide_market_range` is non-discriminating | ADR-041 | **De-emphasised, not retuned.** Not rendered; the actual range is; Data explains it once; the flag stays on the artifact. |
| `min_total_drafts` for filtered cohorts | ADR-045, **ADR-052** | **Resolved by the event ADR-052 predicted.** 125 → 735 drafts in eleven days with the rule untouched; every preset now sufficient. What it exposed — no test rendered the new state — is the more valuable finding. |
| Correlated player draws | open questions | **Deferred to a 2027 simulation refresh.** The 2025 holdout is spent, so a structural change to the joint distribution has nothing to be promoted against. Recorded as a concrete research item. |
| Historical injury features | ADR-044 | **Still deferred to the 2027 refresh.** No `intrinsic_core_v2` in Phase 8. |
| Learned arbitrage | ADR-010 | **Still deferred.** Needs three complete seasons of retained point-in-time market history; a growing 2026 snapshot history is not a substitute. 2029 at the earliest. |
| FTN charting | open questions | **Still deferred.** Nothing in current evidence shows the feature family earns its share-alike obligation. |
