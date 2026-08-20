# Tier-method report

Model `intrinsic-cb-hurdle-v1`, generated 2026-08-19T23:30:46Z from code `2f0e725`. Generated from the committed stage-C experiment reports.

## What a tier is, and what it is not

A tier is a contiguous run of fair-ranked players whose simulated value distributions do not show a stable break between them. The letters are ordinal labels and nothing more: `S` above `A` means the segmentation put a boundary between them, not that `S` is a fixed amount better, and no letter carries a claim that survives being compared across positions, presets or builds.

## The ranking statistic

- **Fair rank** (`phase4_ranking_v1`) selected `median_vorp` (incumbent retained).
  - median_vorp stands: top-K recall gain +0.0014 below the 0.010 required; macro Spearman falls 0.0058, beyond 0.005; macro Kendall falls 0.0071, beyond 0.005

Fair rank is 1-based and unique. Ties break in the order `docs/DATA_CONTRACTS.md` section 7 declares: the ranking statistic, then P50 points, then lower uncertainty, then a stable `player_id`.

## Simulation

- **Draw count** (`phase4_convergence_v1`) selected `10000` (incumbent retained).
  - no draw count satisfied every tolerance; the largest declared count (10000) is used and the breaches are recorded
  - **failed:** 2022/PPR/redraft-12/vs_second_seed: mean |Δ expected VORP| 0.2937 exceeds 0.2500
  - **failed:** 2022/PPR/redraft-12/vs_second_seed: p99 |Δ expected VORP| 1.9288 exceeds 1.5000
  - **failed:** 2022/PPR/redraft-12/vs_second_seed: mean |Δ P50 VORP| 0.4160 exceeds 0.3500
  - **failed:** 2022/PPR/redraft-12/vs_second_seed: tier ARI 0.7472 below 0.9000
  - **failed:** 2022/PPR/redraft-12/vs_second_seed: tier count differs by 5, beyond 1
  - **failed:** 2024/PPR/redraft-12/vs_second_seed: mean |Δ expected VORP| 0.3141 exceeds 0.2500
  - **failed:** 2024/PPR/redraft-12/vs_second_seed: mean |Δ P50 VORP| 0.4062 exceeds 0.3500
  - **failed:** 2024/PPR/redraft-12/vs_second_seed: tier ARI 0.4992 below 0.9000
  - **failed:** 2024/PPR/redraft-12/vs_second_seed: tier count differs by -5, beyond 1
  - **failed:** 2024/STD/redraft-10/vs_second_seed: tier ARI 0.5132 below 0.9000
  - **failed:** 2023/HALF/redraft-14/vs_second_seed: mean |Δ expected VORP| 0.2735 exceeds 0.2500
  - **failed:** 2023/HALF/redraft-14/vs_second_seed: p99 |Δ expected VORP| 1.6329 exceeds 1.5000
  - **failed:** 2023/HALF/redraft-14/vs_second_seed: mean |Δ P50 VORP| 0.3520 exceeds 0.3500
  - **failed:** 2023/HALF/redraft-14/vs_second_seed: tier ARI 0.5458 below 0.9000
  - **failed:** 2023/HALF/redraft-14/vs_second_seed: tier count differs by -3, beyond 1

Each draw samples every player's season total from his own monotone quantile function and hands the whole draw to the one canonical starter/FLEX allocation in `ffdraft.simulation.allocation` - the same code that built the Phase-2 realized VORP labels. Mandatory positional slots fill first, FLEX competes globally among the remaining eligible RB/WR/TE, and the replacement baseline is the best player nobody started. **Replacement is resampled with everyone else**, so a draw where the top backs collapse is a draw where replacement is low and the survivors are worth more; subtracting one fixed baseline from every quantile would have made VORP a shifted copy of points.

Point draws depend on the model version, the simulation version, the scoring preset, the build id and each player's own id - deliberately **not** on the league preset, so the same simulated seasons are re-allocated under every roster shape and a preset-to-preset difference is a scarcity difference rather than Monte Carlo noise.

## Segmentation

- promoted algorithm: `dp_quantile` (`dp_quantile_wasserstein_v1`)
- board depth: 300
- penalty grid: [1.0, 2.0, 3.0, 5.0, 8.0, 12.0]
- the primary candidate is `ruptures.Pelt(model='rbf')` over standardized P25, P50, P75 and interquartile spread of simulated VORP in fair-rank order, with minimum segment size 1 so a genuinely isolated top player may stand alone
- the documented alternative is exact dynamic programming minimizing within-tier quantile (Wasserstein) dispersion plus a per-tier penalty; it is reached only when a frozen rule refuses the primary

- **Penalty** (`phase4_tier_v1`) selected `1.0` (decisive).
  - penalty 1.0 is admissible with bootstrap ARI 0.865, mean tier count 8.80, singleton rate 0.033 and boundary effect size 0.014

| Penalty | Mean tiers | Singleton rate | Largest tier | Boundary effect | Within-tier effect | Bootstrap ARI |
|---|---|---|---|---|---|---|
| 1.0000 | 8.8000 | 0.0329 | 0.2409 | 0.0144 | 0.0047 | 0.8649 |
| 2.0000 | 6.7333 | 0.0000 | 0.2902 | 0.0153 | 0.0047 | 0.9143 |
| 3.0000 | 5.6667 | 0.0000 | 0.3409 | 0.0148 | 0.0047 | 0.9305 |
| 5.0000 | 4.9333 | 0.0000 | 0.3736 | 0.0136 | 0.0047 | 0.9514 |
| 8.0000 | 4.0667 | 0.0000 | 0.3978 | 0.0188 | 0.0047 | 0.9593 |
| 12.0000 | 3.6000 | 0.0000 | 0.4502 | 0.0210 | 0.0047 | 0.9440 |

### Why the alternative was reached

| Algorithm | Penalty | Admissible | Stability | Why not |
|---|---|---|---|---|
| pelt_rbf | 1.0 | True | fail | boundary agreement 0.3336 below 0.5000; monotonic tier pairs 0.6560 below 0.8000; cross-preset ARI 0.4316 below 0.5000 |
| dp_quantile | 1.0 | True | fail | boundary agreement 0.2394 below 0.5000 |

## Stability

- **Stability gate** (`phase4_tier_stability_v1`) selected `fail` (incumbent retained).
  - bootstrap ARI 0.8649
  - singleton rate 0.0396
  - tier-count CV 0.0454
  - monotonic tier pairs 0.8448
  - cross-preset ARI 0.5288
  - **failed:** boundary agreement 0.2394 below 0.5000

| Bootstrap ARI | Boundary agreement | Singleton rate | Tier-count CV | Monotonic tier pairs | Cross-preset ARI |
|---|---|---|---|---|---|
| 0.8649 | 0.2394 | 0.0396 | 0.0454 | 0.8448 | 0.5288 |

### Do tiers order realized value?

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

### Across presets

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

## Boundary diagnostics

Every boundary carries the P50 VORP cliff across it, a standardized effect size computed identically for boundary and non-boundary adjacent pairs, and the probability that the lower-ranked player outscores the higher-ranked one under a transparent normal proxy. Computing the effect size the same way on both sides of the question is what makes 'this boundary separates more than a typical pair inside a tier' a ratio rather than an impression.

## Known limitations

- Tier boundaries move between builds. The bootstrap measures how much, and the boundary-frequency diagnostic says where on the board the segmentation is confident; deep boundaries are far less stable than the top of the board.
- A tier is a statement about *this* league preset and scoring rule. Membership similarity across presets is measured and reported rather than assumed.
- The segmentation sees only the simulated VORP summary. It has no notion of bye weeks, schedule, positional runs in a real draft room, or a manager's existing roster.
- Nothing here is manually adjusted. If a tier looks wrong, the answer is in the model or the algorithm, not in an edit.

