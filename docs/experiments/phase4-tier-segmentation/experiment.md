# Phase 4, stage C — tier segmentation

Study `phase4_tiers_v1`, seed `20260819`, code `3ba6cb0`, generated 2026-08-19T21:41:20Z. 10000 draws, ranked by `median_vorp`, board depth 300.

## Conclusion

**Algorithm `dp_quantile`** (`dp_quantile_wasserstein_v1`) at **penalty `1.0`**.

The PELT candidate was tried first and refused by a frozen rule, so the documented dynamic-programming alternative was evaluated - ADR-030's declared response, not a wider penalty search.

| Algorithm | Penalty | Admissible | Stability | Why not |
|---|---|---|---|---|
| pelt_rbf | 1.0 | True | fail | boundary agreement 0.3336 below 0.5000; monotonic tier pairs 0.6560 below 0.8000; cross-preset ARI 0.4316 below 0.5000 |
| dp_quantile | 1.0 | True | fail | boundary agreement 0.2394 below 0.5000 |

**Penalty selection** (`phase4_tier_v1`) — passed.

> penalty 1.0 is admissible with bootstrap ARI 0.865, mean tier count 8.80, singleton rate 0.033 and boundary effect size 0.014

**Stability gate** (`phase4_tier_stability_v1`) — failed.

> bootstrap ARI 0.8649
> singleton rate 0.0396
> tier-count CV 0.0454
> monotonic tier pairs 0.8448
> cross-preset ARI 0.5288
> **failed:** boundary agreement 0.2394 below 0.5000

## Penalty grid

Shape diagnostics averaged over every development season and scoring preset; stability from the declared bootstrap subset.

| Penalty | Mean tiers | Singleton rate | Largest tier | Boundary effect | Within-tier effect | Bootstrap ARI | Boundary agreement |
|---|---|---|---|---|---|---|---|
| 1.0000 | 8.8000 | 0.0329 | 0.2409 | 0.0144 | 0.0047 | 0.8649 | 0.2394 |
| 2.0000 | 6.7333 | 0.0000 | 0.2902 | 0.0153 | 0.0047 | 0.9143 | 0.3889 |
| 3.0000 | 5.6667 | 0.0000 | 0.3409 | 0.0148 | 0.0047 | 0.9305 | 0.5167 |
| 5.0000 | 4.9333 | 0.0000 | 0.3736 | 0.0136 | 0.0047 | 0.9514 | 0.4583 |
| 8.0000 | 4.0667 | 0.0000 | 0.3978 | 0.0188 | 0.0047 | 0.9593 | 0.5000 |
| 12.0000 | 3.6000 | 0.0000 | 0.4502 | 0.0210 | 0.0047 | 0.9440 | 0.3611 |

## Stability of the promoted segmentation

| Bootstrap ARI | Boundary agreement | Singleton rate | Tier-count CV | Monotonic tier pairs | Cross-preset ARI |
|---|---|---|---|---|---|
| 0.8649 | 0.2394 | 0.0396 | 0.0454 | 0.8448 | 0.5288 |

## Tier monotonicity against realized VORP

| Season | Scoring | Tiers | Adjacent pairs | Monotonic | Share |
|---|---|---|---|---|---|
| 2020 | STD | 9 | 8 | 7 | 0.8750 |
| 2020 | HALF | 8 | 7 | 5 | 0.7143 |
| 2020 | PPR | 9 | 8 | 6 | 0.7500 |
| 2021 | STD | 11 | 10 | 6 | 0.6000 |
| 2021 | HALF | 9 | 8 | 7 | 0.8750 |
| 2021 | PPR | 7 | 6 | 5 | 0.8333 |
| 2022 | STD | 10 | 9 | 8 | 0.8889 |
| 2022 | HALF | 8 | 7 | 7 | 1.0000 |
| 2022 | PPR | 8 | 7 | 7 | 1.0000 |
| 2023 | STD | 10 | 9 | 7 | 0.7778 |
| 2023 | HALF | 9 | 8 | 6 | 0.7500 |
| 2023 | PPR | 8 | 7 | 6 | 0.8571 |
| 2024 | STD | 9 | 8 | 6 | 0.7500 |
| 2024 | HALF | 8 | 7 | 7 | 1.0000 |
| 2024 | PPR | 9 | 8 | 8 | 1.0000 |

## Cross-preset membership similarity

| Left | Right | Shared | ARI |
|---|---|---|---|
| 2024/HALF/redraft-10 | 2024/HALF/redraft-12 | 290 | 0.7420 |
| 2024/HALF/redraft-10 | 2024/HALF/redraft-14 | 285 | 0.6905 |
| 2024/HALF/redraft-10 | 2024/PPR/redraft-10 | 285 | 0.6000 |
| 2024/HALF/redraft-10 | 2024/PPR/redraft-12 | 282 | 0.4782 |
| 2024/HALF/redraft-10 | 2024/PPR/redraft-14 | 276 | 0.4408 |
| 2024/HALF/redraft-10 | 2024/STD/redraft-10 | 280 | 0.4989 |
| 2024/HALF/redraft-10 | 2024/STD/redraft-12 | 291 | 0.6403 |
| 2024/HALF/redraft-10 | 2024/STD/redraft-14 | 288 | 0.5166 |
| 2024/HALF/redraft-12 | 2024/HALF/redraft-14 | 295 | 0.8400 |
| 2024/HALF/redraft-12 | 2024/PPR/redraft-10 | 293 | 0.6512 |
| 2024/HALF/redraft-12 | 2024/PPR/redraft-12 | 290 | 0.5325 |
| 2024/HALF/redraft-12 | 2024/PPR/redraft-14 | 285 | 0.5454 |
| 2024/HALF/redraft-12 | 2024/STD/redraft-10 | 271 | 0.4134 |
| 2024/HALF/redraft-12 | 2024/STD/redraft-12 | 285 | 0.5936 |
| 2024/HALF/redraft-12 | 2024/STD/redraft-14 | 290 | 0.4619 |
| 2024/HALF/redraft-14 | 2024/PPR/redraft-10 | 294 | 0.6225 |
| 2024/HALF/redraft-14 | 2024/PPR/redraft-12 | 294 | 0.5152 |
| 2024/HALF/redraft-14 | 2024/PPR/redraft-14 | 289 | 0.5480 |
| 2024/HALF/redraft-14 | 2024/STD/redraft-10 | 267 | 0.3906 |
| 2024/HALF/redraft-14 | 2024/STD/redraft-12 | 282 | 0.5405 |
| 2024/HALF/redraft-14 | 2024/STD/redraft-14 | 289 | 0.4710 |
| 2024/PPR/redraft-10 | 2024/PPR/redraft-12 | 295 | 0.5124 |
| 2024/PPR/redraft-10 | 2024/PPR/redraft-14 | 289 | 0.5351 |
| 2024/PPR/redraft-10 | 2024/STD/redraft-10 | 269 | 0.3679 |
| 2024/PPR/redraft-10 | 2024/STD/redraft-12 | 284 | 0.5690 |
| 2024/PPR/redraft-10 | 2024/STD/redraft-14 | 289 | 0.4347 |
| 2024/PPR/redraft-12 | 2024/PPR/redraft-14 | 294 | 0.8893 |
| 2024/PPR/redraft-12 | 2024/STD/redraft-10 | 264 | 0.3164 |
| 2024/PPR/redraft-12 | 2024/STD/redraft-12 | 279 | 0.4123 |
| 2024/PPR/redraft-12 | 2024/STD/redraft-14 | 284 | 0.4004 |
| 2024/PPR/redraft-14 | 2024/STD/redraft-10 | 258 | 0.3009 |
| 2024/PPR/redraft-14 | 2024/STD/redraft-12 | 274 | 0.3935 |
| 2024/PPR/redraft-14 | 2024/STD/redraft-14 | 280 | 0.3628 |
| 2024/STD/redraft-10 | 2024/STD/redraft-12 | 282 | 0.6979 |
| 2024/STD/redraft-10 | 2024/STD/redraft-14 | 273 | 0.4949 |
| 2024/STD/redraft-12 | 2024/STD/redraft-14 | 291 | 0.6155 |

## Example board

The top 40 of one development board, so the shape of a tier is visible rather than described.

| Rank | Pos | Pos rank | Tier | E[VORP] | P50 VORP | Spread |
|---|---|---|---|---|---|---|
| 1 | WR | 1 | S | 132.5459 | 134.6399 | 118.3648 |
| 2 | WR | 2 | S | 130.5164 | 129.2253 | 129.0506 |
| 3 | WR | 3 | S | 106.0397 | 119.6440 | 94.0724 |
| 4 | WR | 4 | S | 107.3240 | 113.1471 | 111.4925 |
| 5 | WR | 5 | S | 101.5412 | 103.7488 | 93.7558 |
| 6 | RB | 1 | S | 100.5372 | 102.4101 | 100.0672 |
| 7 | WR | 6 | S | 85.6757 | 99.8506 | 99.8664 |
| 8 | WR | 7 | S | 102.0337 | 99.2211 | 126.2487 |
| 9 | WR | 8 | A | 81.0719 | 95.0830 | 83.7451 |
| 10 | WR | 9 | A | 77.9217 | 93.2091 | 114.1887 |
| 11 | WR | 10 | A | 66.8074 | 90.7556 | 84.4332 |
| 12 | WR | 11 | A | 78.8032 | 89.5060 | 89.0486 |
| 13 | WR | 12 | A | 84.0298 | 89.4441 | 81.3548 |
| 14 | RB | 2 | A | 84.6699 | 84.7898 | 94.3452 |
| 15 | WR | 13 | A | 78.2828 | 84.5884 | 89.7562 |
| 16 | WR | 14 | A | 75.5988 | 84.2989 | 78.5877 |
| 17 | WR | 15 | A | 70.2670 | 83.0251 | 98.8705 |
| 18 | WR | 16 | A | 78.8641 | 82.8326 | 84.3336 |
| 19 | QB | 1 | A | 47.8710 | 81.3150 | 125.2713 |
| 20 | QB | 2 | A | 64.7253 | 80.1754 | 82.4224 |
| 21 | TE | 1 | A | 62.7871 | 79.6539 | 119.5666 |
| 22 | RB | 3 | A | 64.9513 | 79.5996 | 84.7283 |
| 23 | WR | 17 | A | 63.0700 | 77.3215 | 88.1366 |
| 24 | WR | 18 | A | 60.9333 | 77.0005 | 126.5416 |
| 25 | QB | 3 | A | 58.0580 | 75.9541 | 91.3548 |
| 26 | WR | 19 | A | 55.4188 | 75.1248 | 100.8162 |
| 27 | RB | 4 | A | 71.0848 | 73.3853 | 89.2668 |
| 28 | RB | 5 | A | 68.8021 | 72.3461 | 74.6407 |
| 29 | RB | 6 | A | 71.6944 | 68.7039 | 161.5297 |
| 30 | WR | 20 | A | 57.2846 | 68.6534 | 95.9037 |
| 31 | WR | 21 | A | 56.2831 | 67.6544 | 61.6291 |
| 32 | WR | 22 | A | 54.6073 | 64.9568 | 53.7770 |
| 33 | TE | 2 | A | 61.9091 | 64.6094 | 69.7638 |
| 34 | RB | 7 | A | 65.2147 | 64.1644 | 121.9006 |
| 35 | TE | 3 | B | 53.2205 | 64.1164 | 92.8957 |
| 36 | RB | 8 | B | 54.2193 | 62.7959 | 84.3966 |
| 37 | TE | 4 | B | 52.7883 | 60.9611 | 98.6839 |
| 38 | WR | 23 | B | 47.7293 | 60.9082 | 62.1778 |
| 39 | WR | 24 | B | 48.9865 | 60.6336 | 59.2217 |
| 40 | WR | 25 | B | 51.5380 | 59.8080 | 70.9136 |

## Checks

- [warning] `phase4.tier_algorithm_escalated` — the pelt_rbf candidate failed a frozen rule, so the documented dynamic-programming alternative was evaluated - ADR-030's declared response, not a wider penalty search
- [ok] `phase4.tier_penalty` — phase4_tier_v1 selected penalty 1.0
- [critical] `phase4.tier_stability` — the promoted segmentation failed the frozen stability gate; the documented response is the dynamic-programming alternative in docs/MODELING.md section 14.3, not a wider penalty search

Tier letters are ordinal labels. `S` above `A` means the segmentation put a break between them, nothing more; no letter carries a claim about how much better one group is than the next.
