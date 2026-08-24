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
| Deployed commit | `d34756a` |
| Refreshing | daily at 07:17 America/New_York; first scheduled deploy [32636603290](https://github.com/jeisey/jeisey-tiers/actions/runs/32636603290) on 2026-08-23 |
| Model | `intrinsic-cb-hurdle-v1` (trained 2014-2025) |
| Arbitrage | `a0_rank_gap_v1`, deterministic baseline |
| Review date | _to be filled in_ |
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

Add below. One heading per surface; anything that does not fit goes in **Other**.

### Tier Board

_(nothing recorded yet)_

### Draft Rail

_(nothing recorded yet)_

### Tables

_(nothing recorded yet)_

### Player Details

_(nothing recorded yet)_

### Mobile

_(nothing recorded yet)_

### Data / Methodology

_(nothing recorded yet)_

### Other

_(nothing recorded yet)_

---

## Also waiting for Phase 8, from elsewhere

These are recorded in full in their own places and are listed here only so a Phase-8 session
sees the whole queue in one view. **None of them is a UI question**, and none should be
answered by looking at the site.

| item | where it lives | why it is not Phase-7 work |
|---|---|---|
| Multi-source fantasy market-price study | `docs/DATA_SOURCES.md` §16 | a new production price source is a source-policy decision needing its own ADR and evidence |
| Monte Carlo convergence rule re-specification | ADR-034 | the tier clause is stricter than the gate it protects; needs a new rule version |
| Tier boundary stability | ADR-035 | the measurement supports ~4 reproducible cuts on a 300-deep board; do not lower the threshold |
| `wide_market_range` is non-discriminating | ADR-041, known risks | true and useless at 125 drafts; render the range instead of the flag |
| `min_total_drafts` for filtered cohorts | ADR-045 | re-specifying it must not happen in the same breath as reading the result it would change |
| Correlated player draws | open questions | never measured; the largest structural simplification in the simulation |
| Historical injury features | ADR-044 | a 2027 refresh candidate; the 2025 holdout is spent, so there is nothing to promote against |
| Learned arbitrage | ADR-010 | needs three draft seasons of our own snapshots, so 2029 at the earliest |
