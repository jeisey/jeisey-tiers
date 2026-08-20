# Arbitrage method card — A0, fair rank versus ADP

**Version** `a0_rank_gap_v1` · **mode** `baseline` · **generated** 2026-08-20T14:47:07.909298Z · **code** `239db00`

## Why there is no model here

MyFantasyLeague's historical ADP export is a season-long aggregate recomputed at request time, and its day-window filter is ignored. A historical "market cost" therefore includes drafts held after the season's outcomes were partly known — which would contaminate exactly the signal a learned arbitrage model exists to exploit. So V1 computes a transparent baseline and calls it one (ADR-010).

`expected_surplus_vorp` and `p_positive_surplus` are null on all 2124 rows. They are not approximated, and no output is labelled `ml`.

**Revisit condition.** at least 3 draft seasons of our own point-in-time snapshots, then an out-of-time promotion gate against A0.

## The formula

```text
rank_gap           = market_adp - fair_rank
regional_value_gap = ln(market_adp / fair_rank)
arbitrage_score    = midpoint percentile of regional_value_gap, within preset
```

Positive `rank_gap` means the model would take the player **earlier** than the market does — a bargain. Zero is agreement. Negative means the market is paying up.

The log ratio exists because the same absolute gap means different things in different regions of a draft: eight picks between fair rank 3 and ADP 11 is a round of value; eight picks between 180 and 188 is noise.

Fair rank comes from `median_vorp` in `tiers.json`, produced by `intrinsic-cb-hurdle-v1`. Tier ordinals and tier edges are **not** inputs.

## Market source

- source `myfantasyleague_adp`, snapshot `2026-08-20T14-38-44Z` retrieved 2026-08-20T14:38:44Z
- retained on the dedicated long-lived `market-data` git branch, append-only at `market/<source>/<season>/<YYYY-MM-DDTHH-MM-SSZ>/`
- `source_as_of_utc` is null: MyFantasyLeague publishes no data-as-of time; its response timestamp is generation time and is retained as vendor metadata only
- `market_adp_sd` is null: MyFantasyLeague publishes no standard deviation; dispersion is min/max pick

## Cohort selection

Rule `phase5_cohort_v2` (ADR-039, ADR-045), measured against retained snapshot `2026-08-20T14-38-44Z`. Every bound was frozen before any measurement existed; v2 adds one qualifying condition and moves no bound.

| scoring | teams | cohort | exact | sufficient |
|---|---:|---|---|---|
| HALF | 10 | `no-mock-no-keeper` | no | no |
| HALF | 12 | `no-mock-no-keeper` | no | no |
| HALF | 14 | `no-mock-no-keeper` | no | no |
| PPR | 10 | `no-mock-no-keeper` | no | no |
| PPR | 12 | `no-mock-no-keeper` | no | no |
| PPR | 14 | `no-mock-no-keeper` | no | no |
| STD | 10 | `no-mock-no-keeper` | no | no |
| STD | 12 | `no-mock-no-keeper` | no | no |
| STD | 14 | `no-mock-no-keeper` | no | no |

MFL exposes IS_PPR as a boolean and publishes no half-PPR filter, so a HALF assignment is never exact (ADR-039).

A cohort may price this board only if its filters exclude keeper and dynasty drafts. The 2026 measurement found rookies priced three to five times earlier in the aggregate than in IS_KEEPER=N while veterans did not move: dynasty rookie drafts, where a rookie's average pick is a pick number in a rookie-only draft (ADR-045).

**Why every row reads `cohort_insufficient`.** Filtering to redraft leagues shrinks the cohort-level draft count, so no qualifying cohort clears min_total_drafts. The rule falls through to its documented last resort - widest qualifying candidate, flagged - which puts cohort_insufficient and therefore low confidence on every row. Published rather than repaired (ADR-045).

## Confidence

`confidence` is a statement about **market-data quality**, not a probability. Rubric `phase5_confidence_v1`:

- **unknown** — no market sample size
- **low** — cohort failed the sufficiency rule, OR fewer than 30 drafts priced the player, OR identity resolved through the secondary bridge only, OR the snapshot is stale
- **medium** — everything else
- **high** — exact cohort for the preset AND at least 200 drafts priced the player AND a fresh snapshot AND primary-bridge identity

Dispersion is excluded from the tiers because minPick/maxPick are extreme order statistics that widen with sample size, so they are not comparable across players.

Observed on this board: {'low': 2124}.

## Trend

`market_trend` is the negated OLS slope of market_adp on days elapsed, picks/day over a 7-day window, requiring at least 3 observation days spanning 3 days. positive = moving earlier (more expensive).

Source: our own retained point-in-time snapshots only, never MFL history. Currently **null on every row** — the retained store does not yet hold enough history, which is the correct output rather than a gap to fill (2 snapshot(s) in window).

## Coverage and flags

- records: 2124 across 9 preset block(s)
- quality flags: {'cohort_approximate': 2124, 'cohort_insufficient': 2124, 'insufficient_trend_history': 2124, 'low_market_sample': 525, 'secondary_identity_bridge_only': 54, 'wide_market_range': 1914}
- top-150 board players with no price: 42

## Limitations

- No learned model. expected_surplus_vorp and p_positive_surplus are null on every row and are not approximated (ADR-010).
- Cohorts are approximate wherever the source cannot express a preset; HALF always is.
- adp_low/adp_high are extreme order statistics that widen with sample size, so they describe dispersion but do not move confidence (ADR-041).
- wide_market_range fires on most rows at this sample size, which makes it a poor discriminator: with roughly 125 drafts the min-to-max span genuinely does exceed five rounds for most players. The flag is true and unhelpful; a reader should use market_adp_low/market_adp_high directly, which every row carries.
- market_trend is null until at least three observation days spanning three days exist in the retained store (ADR-042).
- Every row carries cohort_insufficient and therefore low confidence: no keeper-free cohort clears the frozen cohort-level draft-count bar. That bar may be the wrong instrument for a filtered cohort - the same cohort carries a median of 105 drafts per top-150 player - but re-specifying it is a separate decision with its own evidence (ADR-045).
- The intrinsic fair rank this compares against carries its own published limitations: the Monte Carlo convergence rule fell through to its fallback (ADR-034) and the tier stability gate failed (ADR-035). A0 uses fair rank, not tier boundaries, so the second does not propagate into this score.

## Degraded behaviour

- **market_unavailable** — no arbitrage artifact; the Tier board is unaffected
- **stale_snapshot** — every row flagged market_snapshot_stale and capped at low confidence
- **player_unpriced** — no arbitrage row; the player keeps his tier row

## Licensing and attribution

- MyFantasyLeague developer rules: free use, registered client User-Agent transmitted, player database requested at most once per day, 429 backed off
- attribution: MyFantasyLeague ADP export; Sleeper (non-commercial) for status
- decisions: ADR-017, ADR-013, ADR-016
