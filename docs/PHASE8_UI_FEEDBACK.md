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

One row per owner item. `implemented` / `partially implemented` / `deferred`, with what was
done, why, and where.

| # | Owner item | Status | Implementation | Where |
|---|---|---|---|---|
| 1 | Claude Design MCP as design source | _pending_ | | |
| 2 | Re-skin shell / card / board / rail / controls / tables | _pending_ | | |
| 3 | Player detail: lead with draft-relevant facts | _pending_ | | |
| 4 | Player-card responsive variants, modal semantics kept | _pending_ | | |
| 5 | Tier Board denser without falsifying uncertainty | _pending_ | | |
| 6 | Tier groups stay soft; no hard cliff | _pending_ | | |
| 7 | Draft Rail reconsidered against real data | _pending_ | | |
| 8 | Remove per-modal status disclosure paragraph | _pending_ | | |
| 9 | Remove repeated cohort paragraphs | _pending_ | | |
| 10 | Removed disclosures still present once in Data | _pending_ | | |
| 11 | Confidence state data-driven (low → medium → high) | _pending_ | | |
| 12 | Trend state data-driven (null and non-null) | _pending_ | | |
| 13 | No launch-only assumption survives in copy or tests | _pending_ | | |
| 14 | `wide_market_range` de-emphasised, range shown, explained once | _pending_ | | |
| 15 | Tier stability threshold untouched | _pending_ | | |

---

## Also waiting for Phase 8, from elsewhere

These are recorded in full in their own places and are listed here only so a Phase-8 session
sees the whole queue in one view. **None of them is a UI question**, and none should be
answered by looking at the site.

| item | where it lives | why it is not Phase-7 work |
|---|---|---|
| Multi-source fantasy market-price study | `docs/DATA_SOURCES.md` §16, **ADR-053** | the sweep is done and the candidates are named; a new production price source is still a source-policy decision needing a runner-side probe and its own ADR |
| Monte Carlo convergence rule re-specification | ADR-034 | the tier clause is stricter than the gate it protects; needs a new rule version |
| Tier boundary stability | ADR-035 | the measurement supports ~4 reproducible cuts on a 300-deep board; do not lower the threshold |
| `wide_market_range` is non-discriminating | ADR-041, known risks | true and useless at 125 drafts; render the range instead of the flag |
| `min_total_drafts` for filtered cohorts | ADR-045, **ADR-052** | measured as self-resolving — 125 → 227 drafts in four days against a bar of 300 — so re-specifying it now could never be told apart from the season arriving |
| Correlated player draws | open questions | never measured; the largest structural simplification in the simulation |
| Historical injury features | ADR-044 | a 2027 refresh candidate; the 2025 holdout is spent, so there is nothing to promote against |
| Learned arbitrage | ADR-010 | needs three draft seasons of our own snapshots, so 2029 at the earliest |
