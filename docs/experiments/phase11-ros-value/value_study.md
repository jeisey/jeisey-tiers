# Rest-of-season value study

Generated 2026-09-04T02:58:35Z · fold `ros:2017-2023->2024` · seed `20260903` · reference draws `10000`.

## 1. Which replacement?

Both interpretations are run over identical simulated seasons. Rule `ros_replacement_v1` decides.

- **`fresh_allocation`** — the best player nobody starts, after allocating the whole board into the league's starting slots (Release 1's preseason rule, unchanged)
- **`rostered_depth`** — the best player nobody rosters, after the starting slots and teams x bench bench places are filled, the bench by surplus over the starting-slot baseline

| scenario | fair-rank Spearman | mean |Δrank| top 150 | max |Δrank| | top-50 overlap | players |
|---|---|---|---|---|---|
| STD w01 | 0.9989 | 2.07 | 33 | 0.980 | 299 |
| STD w04 | 0.9987 | 1.66 | 35 | 0.980 | 297 |
| STD w08 | 0.9985 | 2.10 | 41 | 0.960 | 299 |
| STD w12 | 0.9981 | 1.79 | 40 | 0.980 | 300 |
| HALF w01 | 0.9991 | 1.71 | 29 | 1.000 | 298 |
| HALF w04 | 0.9990 | 1.71 | 23 | 0.980 | 299 |
| HALF w08 | 0.9988 | 2.15 | 31 | 0.980 | 297 |
| HALF w12 | 0.9991 | 1.71 | 28 | 0.940 | 298 |
| PPR w01 | 0.9993 | 1.76 | 21 | 1.000 | 300 |
| PPR w04 | 0.9993 | 1.88 | 17 | 0.980 | 298 |
| PPR w08 | 0.9994 | 1.91 | 24 | 1.000 | 298 |
| PPR w12 | 0.9988 | 1.62 | 31 | 0.980 | 299 |

**Decision: `rostered_depth`** (rule `ros_replacement_v1`, decisive=True)

- the two interpretations disagree materially, so the in-season meaning is used
- across 12 scenario(s): worst fair-rank Spearman 0.9981, largest mean |rank change| in the top 150 2.15, smallest top-50 overlap 0.940

## 2. How many draws?

Frozen tolerance `phase4_convergence_v1`, ladder [1000, 2500, 5000, 10000]. Two comparisons must both pass at a candidate count: against the reference count at one seed, and between two seeds at that count.

| scenario | comparison | draws | mean |Δ E[VORP]| | mean |Δ P50 VORP| | mean |Δrank| top 150 | fair-rank Spearman | tier ARI |
|---|---|---|---|---|---|---|---|
| redraft-12|PPR|w04 | vs 10000 draws | 1000 | 0.461 | 0.556 | 2.69 | 0.9989 | 0.849 |
| redraft-12|PPR|w04 | seed to seed | 1000 | 0.760 | 0.927 | 3.63 | 0.9979 | 0.606 |
| redraft-12|PPR|w04 | vs 10000 draws | 2500 | 0.265 | 0.343 | 1.62 | 0.9996 | 0.893 |
| redraft-12|PPR|w04 | seed to seed | 2500 | 0.436 | 0.534 | 2.77 | 0.9991 | 0.475 |
| redraft-12|PPR|w04 | vs 10000 draws | 5000 | 0.152 | 0.196 | 0.87 | 0.9998 | 0.937 |
| redraft-12|PPR|w04 | seed to seed | 5000 | 0.309 | 0.360 | 1.95 | 0.9994 | 0.447 |
| redraft-12|PPR|w04 | vs 10000 draws | 10000 | 0.000 | 0.000 | 0.00 | 1.0000 | 1.000 |
| redraft-12|PPR|w04 | seed to seed | 10000 | 0.244 | 0.278 | 1.63 | 0.9997 | 0.451 |
| redraft-12|PPR|w12 | vs 10000 draws | 1000 | 0.221 | 0.281 | 2.71 | 0.9980 | 0.686 |
| redraft-12|PPR|w12 | seed to seed | 1000 | 0.322 | 0.406 | 3.93 | 0.9962 | 0.716 |
| redraft-12|PPR|w12 | vs 10000 draws | 2500 | 0.113 | 0.149 | 1.69 | 0.9993 | 0.618 |
| redraft-12|PPR|w12 | seed to seed | 2500 | 0.185 | 0.237 | 2.53 | 0.9984 | 0.640 |
| redraft-12|PPR|w12 | vs 10000 draws | 5000 | 0.067 | 0.091 | 1.15 | 0.9997 | 0.813 |
| redraft-12|PPR|w12 | seed to seed | 5000 | 0.133 | 0.163 | 2.19 | 0.9992 | 0.878 |
| redraft-12|PPR|w12 | vs 10000 draws | 10000 | 0.000 | 0.000 | 0.00 | 1.0000 | 1.000 |
| redraft-12|PPR|w12 | seed to seed | 10000 | 0.097 | 0.122 | 1.44 | 0.9996 | 0.811 |

**Decision: `10000`** (rule `phase4_convergence_v1`, decisive=False)

- no draw count satisfied every tolerance; the largest declared count (10000) is used and the breaches are recorded
- **failed:** redraft-12|PPR|w04/seed to seed: mean |Δ rank| top 150 1.6267 exceeds 1.5000
- **failed:** redraft-12|PPR|w04/seed to seed: tier ARI 0.4505 below 0.9000
- **failed:** redraft-12|PPR|w12/seed to seed: tier ARI 0.8107 below 0.9000

## 3. Are the tiers real?

Penalty selection `phase4_tier_v1` over the frozen grid [1.0, 2.0, 3.0, 5.0, 8.0, 12.0]; stability gate `phase4_tier_stability_v1`.

| algorithm | penalty | mean tiers | singleton rate | largest tier share | scenarios |
|---|---|---|---|---|---|
| dp_quantile | 1.0 | 9.7 | 0.059 | 0.222 | 12 |
| pelt_rbf | 1.0 | 16.5 | 0.219 | 0.167 | 12 |
| dp_quantile | 2.0 | 6.8 | 0.021 | 0.256 | 12 |
| pelt_rbf | 2.0 | 7.6 | 0.000 | 0.221 | 12 |
| dp_quantile | 3.0 | 5.9 | 0.000 | 0.304 | 12 |
| pelt_rbf | 3.0 | 6.8 | 0.000 | 0.246 | 12 |
| dp_quantile | 5.0 | 5.0 | 0.000 | 0.353 | 12 |
| pelt_rbf | 5.0 | 5.2 | 0.000 | 0.306 | 12 |
| dp_quantile | 8.0 | 4.2 | 0.000 | 0.383 | 12 |
| pelt_rbf | 8.0 | 4.3 | 0.000 | 0.366 | 12 |
| dp_quantile | 12.0 | 3.9 | 0.000 | 0.405 | 12 |
| pelt_rbf | 12.0 | 3.8 | 0.000 | 0.383 | 12 |

**Penalty: `3.0`** (rule `phase4_tier_v1`, decisive=True)

- penalty 3.0 is admissible with bootstrap ARI 0.857, mean tier count 6.75, singleton rate 0.000 and boundary effect size 0.013

**Stability: `fail`** (rule `phase4_tier_stability_v1`, decisive=False)

- bootstrap ARI 0.8570
- singleton rate 0.0000
- tier-count CV 0.0736
- monotonic tier pairs 1.0000
- cross-preset ARI 0.5238
- **failed:** boundary agreement 0.1667 below 0.5000

## Checks

- `ros_value.replacement_rule` **pass** — the rest-of-season replacement interpretation, chosen by a frozen rule (rostered_depth: the two interpretations disagree materially, so the in-season meaning is used; across 12 scenario(s): worst fair-rank Spearman 0.9981, largest mean |rank change| in the top 150 2.15, smallest top-50 overlap 0.940)
- `ros_value.convergence_not_reached` **fail** — no draw count in the frozen ladder met every convergence tolerance (redraft-12|PPR|w04/seed to seed: mean |Δ rank| top 150 1.6267 exceeds 1.5000; redraft-12|PPR|w04/seed to seed: tier ARI 0.4505 below 0.9000; redraft-12|PPR|w12/seed to seed: tier ARI 0.8107 below 0.9000)
- `ros_value.tier_penalty` **pass** — tier penalty selected by the frozen rule (3.0; decisive=True)
- `ros_value.tier_stability_failed` **fail** — the rest-of-season segmentation did not clear the frozen stability gate; boundaries must be presented as provisional wherever they are shown (boundary agreement 0.1667 below 0.5000)
