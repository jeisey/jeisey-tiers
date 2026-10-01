# weekly-startsit-v2 — development evaluation

Outcome: **selected**; v2 families: **lineup**.

Rules frozen before this run (`src/ffdraft/weekly/frozen_v2.py`): weekly_family_selection_v1, weekly_promotion_v2. Folds: 2020, 2021, 2022, 2023, 2024.

## Pooled, development folds

| model | pinball | pinball (rows) | MAE (median) | pair accuracy | pair Brier | P10–P90 |
|---|---|---|---|---|---|---|
| b0_season_rate | 1.3248 | 1.2360 | 3.884 | 0.6255 | 0.2351 | 0.810 |
| b1_recent_form | 1.4095 | 1.3239 | 4.136 | 0.6040 | 0.2537 | 0.809 |
| b2_rate_x_vegas | 1.3086 | 1.2083 | 3.823 | 0.6362 | 0.2324 | 0.810 |
| v1 | 1.1086 | 1.0217 | 3.477 | 0.6592 | 0.2109 | 0.808 |
| v1+defense | 1.1086 | 1.0217 | 3.477 | 0.6588 | 0.2109 | 0.806 |
| v1+lineup | 1.1049 | 1.0176 | 3.468 | 0.6606 | 0.2102 | 0.808 |
| v1+weather | 1.1087 | 1.0217 | 3.477 | 0.6595 | 0.2108 | 0.808 |
| v1+weather+lineup+defense | 1.1054 | 1.0181 | 3.468 | 0.6609 | 0.2101 | 0.807 |

## Each family's incremental value over v1 (weekly_family_selection_v1)

| family | Δ pinball (v1 − v1+f) | 95% interval (week-clustered) | fold wins | Δ accuracy | Δ Brier | selected |
|---|---|---|---|---|---|---|
| Opposing defence's health | 0.00003 | [-0.00035, 0.00047] | 2/5 | -0.00035 | 0.00007 | no |
| His offence's health | 0.00371 | [0.00303, 0.00524] | 5/5 | 0.00144 | -0.00070 | yes |
| Weather at kickoff | -0.00002 | [-0.00072, 0.00078] | 3/5 | 0.00032 | -0.00007 | no |

## Macro pinball by season (each fold trained on the seasons before it)

| season | b0_season_rate | b1_recent_form | b2_rate_x_vegas | v1 | v1+defense | v1+lineup | v1+weather | v1+weather+lineup+defense |
|---|---|---|---|---|---|---|---|---|
| 2020 | 1.3805 | 1.4806 | 1.3821 | 1.1764 | 1.1769 | 1.1717 | 1.1757 | 1.1714 |
| 2021 | 1.3434 | 1.4396 | 1.3431 | 1.1210 | 1.1210 | 1.1175 | 1.1196 | 1.1173 |
| 2022 | 1.3093 | 1.3933 | 1.2676 | 1.0875 | 1.0878 | 1.0845 | 1.0900 | 1.0872 |
| 2023 | 1.2947 | 1.3744 | 1.2698 | 1.0794 | 1.0791 | 1.0777 | 1.0798 | 1.0781 |
| 2024 | 1.2992 | 1.3644 | 1.2838 | 1.0831 | 1.0826 | 1.0776 | 1.0825 | 1.0775 |

## Macro pinball by position (pooled folds)

| position | b0_season_rate | b1_recent_form | b2_rate_x_vegas | v1 | v1+defense | v1+lineup | v1+weather | v1+weather+lineup+defense |
|---|---|---|---|---|---|---|---|---|
| QB | 1.8695 | 1.9457 | 1.9076 | 1.6353 | 1.6356 | 1.6344 | 1.6354 | 1.6348 |
| RB | 1.2950 | 1.3757 | 1.2703 | 1.0786 | 1.0784 | 1.0699 | 1.0789 | 1.0714 |
| TE | 0.8935 | 0.9783 | 0.8551 | 0.6992 | 0.6989 | 0.6974 | 0.6989 | 0.6970 |
| WR | 1.2411 | 1.3384 | 1.2014 | 1.0214 | 1.0215 | 1.0180 | 1.0215 | 1.0187 |

## Where each family has something to say (diagnostic; decides nothing)

| family | rows | share | v1 pinball | v1+family pinball |
|---|---|---|---|---|
| defense | 17034 | 0.193 | 1.0572 | 1.0565 |
| lineup | 30741 | 0.348 | 1.0286 | 1.0217 |
| weather | 10848 | 0.123 | 0.9877 | 0.9877 |

## 2025 (previously examined; decides nothing)

| model | pinball | pair accuracy | pair Brier | P10–P90 |
|---|---|---|---|---|
| b0_season_rate | 1.3396 | 0.6321 | 0.2310 | 0.811 |
| b1_recent_form | 1.4293 | 0.6123 | 0.2479 | 0.808 |
| b2_rate_x_vegas | 1.3161 | 0.6454 | 0.2279 | 0.812 |
| v1 | 1.0970 | 0.6656 | 0.2072 | 0.803 |
| v1+lineup | 1.0941 | 0.6672 | 0.2064 | 0.800 |

Consistent with development: **True**.

## weekly_promotion_v1 development clauses, asked of v2

- `coverage_50_in_band`: pass
- `coverage_80_in_band`: pass
- `pairwise_accuracy_above_best_baseline`: pass
- `pairwise_brier_below_best_baseline`: pass
- `pinball_below_best_baseline`: pass
- `pinball_wins_by_fold`: pass
