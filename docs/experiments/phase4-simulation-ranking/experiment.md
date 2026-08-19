# Phase 4, stage C — Monte Carlo draw count and the fair-ranking statistic

Study `phase4_simulation_v1`, seed `20260819`, code `4cd90af`, generated 2026-08-19T19:37:57Z.

## Conclusion

**10000 draws** and **`median_vorp`** as the fair-ranking statistic.

**Draw count** (`phase4_convergence_v1`) selected `10000` — not decisive; the default stands.

> no draw count satisfied every tolerance; the largest declared count (10000) is used and the breaches are recorded
> **failed:** 2022/PPR/redraft-12/vs_second_seed: mean |Δ expected VORP| 0.2937 exceeds 0.2500
> **failed:** 2022/PPR/redraft-12/vs_second_seed: p99 |Δ expected VORP| 1.9288 exceeds 1.5000
> **failed:** 2022/PPR/redraft-12/vs_second_seed: mean |Δ P50 VORP| 0.4160 exceeds 0.3500
> **failed:** 2022/PPR/redraft-12/vs_second_seed: tier ARI 0.7472 below 0.9000
> **failed:** 2022/PPR/redraft-12/vs_second_seed: tier count differs by 5, beyond 1
> **failed:** 2024/PPR/redraft-12/vs_second_seed: mean |Δ expected VORP| 0.3141 exceeds 0.2500
> **failed:** 2024/PPR/redraft-12/vs_second_seed: mean |Δ P50 VORP| 0.4062 exceeds 0.3500
> **failed:** 2024/PPR/redraft-12/vs_second_seed: tier ARI 0.4992 below 0.9000
> **failed:** 2024/PPR/redraft-12/vs_second_seed: tier count differs by -5, beyond 1
> **failed:** 2024/STD/redraft-10/vs_second_seed: tier ARI 0.5132 below 0.9000
> **failed:** 2023/HALF/redraft-14/vs_second_seed: mean |Δ expected VORP| 0.2735 exceeds 0.2500
> **failed:** 2023/HALF/redraft-14/vs_second_seed: p99 |Δ expected VORP| 1.6329 exceeds 1.5000
> **failed:** 2023/HALF/redraft-14/vs_second_seed: mean |Δ P50 VORP| 0.3520 exceeds 0.3500
> **failed:** 2023/HALF/redraft-14/vs_second_seed: tier ARI 0.5458 below 0.9000
> **failed:** 2023/HALF/redraft-14/vs_second_seed: tier count differs by -3, beyond 1

**Ranking statistic** (`phase4_ranking_v1`) selected `median_vorp` — not decisive; the default stands.

> median_vorp stands: top-K recall gain +0.0014 below the 0.010 required; macro Spearman falls 0.0058, beyond 0.005; macro Kendall falls 0.0071, beyond 0.005

## Convergence

Every ladder step is compared twice: against 10000 draws at the same seed, and against a second seed at the same count. Fair-rank and tier comparisons are taken as the worst case over both candidate ranking statistics and all six penalties in the frozen grid, because the draw count is chosen before either of those decisions is made.

| Draws | Scenario | Comparison | mean |dE[VORP]| | p99 |dE[VORP]| | mean |dP50| | mean |douter| | max |drepl| | rank rho | top-50 | tier ARI |
|---|---|---|---|---|---|---|---|---|---|---|
| 1000 | 2022/PPR/redraft-12 | vs_reference | 0.6853 | 3.9214 | 0.8785 | 0.9607 | 0.5083 | 0.9978 | 0.9600 | 0.5549 |
| 1000 | 2022/PPR/redraft-12 | vs_second_seed | 0.9669 | 5.3634 | 1.3563 | 1.3968 | 0.6310 | 0.9945 | 0.9600 | 0.5445 |
| 1000 | 2023/HALF/redraft-14 | vs_reference | 0.6385 | 3.3222 | 0.8192 | 0.8295 | 0.4295 | 0.9982 | 0.9600 | 0.6102 |
| 1000 | 2023/HALF/redraft-14 | vs_second_seed | 0.9397 | 5.2535 | 1.1579 | 1.2583 | 1.0940 | 0.9961 | 0.9600 | 0.5360 |
| 1000 | 2024/PPR/redraft-12 | vs_reference | 0.5523 | 3.7853 | 0.8105 | 0.8337 | 0.1750 | 0.9983 | 1.0000 | 0.6175 |
| 1000 | 2024/PPR/redraft-12 | vs_second_seed | 0.9256 | 5.3506 | 1.3426 | 1.2571 | 1.0663 | 0.9969 | 0.9600 | 0.5837 |
| 1000 | 2024/STD/redraft-10 | vs_reference | 0.4741 | 2.4896 | 0.6003 | 0.6801 | 0.2620 | 0.9985 | 0.9800 | 0.5447 |
| 1000 | 2024/STD/redraft-10 | vs_second_seed | 0.7513 | 4.1548 | 0.9240 | 1.0926 | 0.5981 | 0.9965 | 0.9800 | 0.4947 |
| 2500 | 2022/PPR/redraft-12 | vs_reference | 0.3504 | 2.1289 | 0.5307 | 0.5099 | 0.0497 | 0.9992 | 0.9800 | 0.5312 |
| 2500 | 2022/PPR/redraft-12 | vs_second_seed | 0.6499 | 3.7113 | 0.9411 | 0.8779 | 0.5297 | 0.9975 | 0.9800 | 0.5056 |
| 2500 | 2023/HALF/redraft-14 | vs_reference | 0.3471 | 1.9934 | 0.4452 | 0.4808 | 0.1737 | 0.9992 | 0.9800 | 0.6858 |
| 2500 | 2023/HALF/redraft-14 | vs_second_seed | 0.5499 | 3.2964 | 0.6950 | 0.7875 | 0.2709 | 0.9980 | 0.9800 | 0.5690 |
| 2500 | 2024/PPR/redraft-12 | vs_reference | 0.3508 | 2.2379 | 0.4746 | 0.5180 | 0.3768 | 0.9993 | 1.0000 | 0.6392 |
| 2500 | 2024/PPR/redraft-12 | vs_second_seed | 0.5051 | 3.2803 | 0.7480 | 0.7856 | 0.1224 | 0.9985 | 0.9800 | 0.6868 |
| 2500 | 2024/STD/redraft-10 | vs_reference | 0.2747 | 1.4694 | 0.3746 | 0.3876 | 0.1618 | 0.9991 | 0.9800 | 0.5463 |
| 2500 | 2024/STD/redraft-10 | vs_second_seed | 0.3766 | 2.2407 | 0.5538 | 0.6097 | 0.1935 | 0.9982 | 0.9600 | 0.6282 |
| 5000 | 2022/PPR/redraft-12 | vs_reference | 0.2204 | 1.2049 | 0.3053 | 0.3074 | 0.1626 | 0.9997 | 1.0000 | 0.5827 |
| 5000 | 2022/PPR/redraft-12 | vs_second_seed | 0.4199 | 2.3585 | 0.5945 | 0.6034 | 0.2171 | 0.9990 | 1.0000 | 0.5523 |
| 5000 | 2023/HALF/redraft-14 | vs_reference | 0.1804 | 1.1420 | 0.2486 | 0.2780 | 0.1436 | 0.9997 | 1.0000 | 0.7522 |
| 5000 | 2023/HALF/redraft-14 | vs_second_seed | 0.3673 | 2.2028 | 0.4800 | 0.5383 | 0.2080 | 0.9991 | 0.9800 | 0.6378 |
| 5000 | 2024/PPR/redraft-12 | vs_reference | 0.1928 | 1.0735 | 0.2553 | 0.2937 | 0.1083 | 0.9998 | 1.0000 | 0.6233 |
| 5000 | 2024/PPR/redraft-12 | vs_second_seed | 0.3864 | 2.1248 | 0.5142 | 0.5560 | 0.1090 | 0.9993 | 0.9800 | 0.7050 |
| 5000 | 2024/STD/redraft-10 | vs_reference | 0.1641 | 0.8677 | 0.2470 | 0.2225 | 0.0980 | 0.9997 | 1.0000 | 0.6244 |
| 5000 | 2024/STD/redraft-10 | vs_second_seed | 0.2726 | 1.6861 | 0.3967 | 0.4124 | 0.1818 | 0.9990 | 0.9800 | 0.6384 |
| 10000 | 2022/PPR/redraft-12 | vs_reference | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| 10000 | 2022/PPR/redraft-12 | vs_second_seed | 0.2937 | 1.9288 | 0.4160 | 0.4394 | 0.0848 | 0.9994 | 1.0000 | 0.7472 |
| 10000 | 2023/HALF/redraft-14 | vs_reference | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| 10000 | 2023/HALF/redraft-14 | vs_second_seed | 0.2735 | 1.6329 | 0.3520 | 0.3794 | 0.1753 | 0.9995 | 0.9800 | 0.5458 |
| 10000 | 2024/PPR/redraft-12 | vs_reference | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| 10000 | 2024/PPR/redraft-12 | vs_second_seed | 0.3141 | 1.4524 | 0.4062 | 0.4507 | 0.1928 | 0.9995 | 1.0000 | 0.4992 |
| 10000 | 2024/STD/redraft-10 | vs_reference | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| 10000 | 2024/STD/redraft-10 | vs_second_seed | 0.2288 | 1.3815 | 0.2931 | 0.3131 | 0.2491 | 0.9995 | 0.9800 | 0.5132 |

## Expected versus median simulated VORP

Scored against the realized VORP labels Phase 2 built, over the full eligible universe of each development season, for every scoring x league preset.

| Statistic | Spearman | Kendall | Top-K recall | Early-round recall | Seed rank stability |
|---|---|---|---|---|---|
| median_vorp | 0.8057 | 0.6528 | 0.6204 | 0.3611 | 0.9998 |
| expected_vorp | 0.7999 | 0.6457 | 0.6218 | 0.3593 | 0.9999 |

Top-K retrieval by position:

| Position | median VORP | expected VORP |
|---|---|---|
| QB | 0.5389 | 0.5333 |
| RB | 0.6352 | 0.6222 |
| TE | 0.5204 | 0.5222 |
| WR | 0.5991 | 0.6000 |

## Checks

- [critical] `phase4.monte_carlo_convergence` — no draw count in the declared ladder satisfied every tolerance
- [ok] `phase4.ranking_statistic` — phase4_ranking_v1 selected median_vorp
- [ok] `phase4.simulation_deterministic` — repeating a scenario with the same inputs reproduced it exactly
