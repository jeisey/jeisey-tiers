# Rest-of-season experiment — `development`

Generated 2026-09-04T13:39:03Z · experiment `phase11_ros_v1` · seed `20260903`.

## What was measured

- grain: `season x through_week x player_id x scoring_preset`
- rows scored: **253,197**
- seasons: [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]
- folds: ['ros:2017-2019->2020', 'ros:2017-2020->2021', 'ros:2017-2021->2022', 'ros:2017-2022->2023', 'ros:2017-2023->2024']
- evaluation cell: `season x through_week x position x scoring_preset`

## Macro results

Macro means across evaluation cells, so one week's quarterback board weighs the same as one week's receiver board.

| model | MAE | pinball | Spearman | top-K recall | P10-P90 coverage | P25-P75 coverage | P10-P90 width | cells |
|---|---|---|---|---|---|---|---|---|
| R0 | 14.05 | 5.313 | 0.578 | 0.472 | 0.785 | 0.495 | 43.9 | 948 |
| R1 | 11.05 | 4.500 | 0.779 | 0.546 | 0.805 | 0.652 | 32.2 | 948 |
| R2 | 12.32 | 4.444 | 0.677 | 0.561 | 0.790 | 0.484 | 36.0 | 948 |
| R3 | 15.83 | 5.520 | 0.751 | 0.245 | 0.693 | 0.388 | 46.5 | 948 |
| RC1 | 9.86 | 3.635 | 0.797 | 0.557 | 0.869 | 0.715 | 32.6 | 948 |

**Primary baseline: `R2`** — chosen by the frozen rule (lowest development macro pinball loss), not by preference.

## Paired deltas

`RC1` minus `R2`, paired within cell, 1000 bootstrap replicates. Negative is better for a loss.

| metric | baseline | candidate | delta | 95% CI | interval excludes 0 |
|---|---|---|---|---|---|
| mae | 12.319 | 9.856 | -2.4632 | [-2.5305, -2.3958] | yes |
| mean_pinball | 4.444 | 3.635 | -0.8084 | [-0.8328, -0.7857] | yes |
| spearman | 0.677 | 0.797 | 0.1203 | [+0.1184, +0.1229] | yes |
| top_k_recall | 0.561 | 0.557 | -0.0034 | [-0.0044, +0.0079] | no |

## Predeclared cohorts

| cohort | rows | decisive | baseline MAE | candidate MAE | baseline ρ | candidate ρ | baseline pinball | candidate pinball | P(Y=0) | attainable coverage | baseline coverage | candidate coverage | climatological width | baseline width | candidate width |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `full_universe` / all | 253,197 | yes | 11.26 | 8.96 | 0.677 | 0.797 | 4.046 | 3.305 | 0.568 | 0.893 | 0.795 | 0.878 | 65.6 | 32.7 | 30.5 |
| `position` / QB | 32,628 | yes | 19.14 | 15.64 | 0.643 | 0.718 | 6.977 | 5.811 | 0.525 | 0.865 | 0.772 | 0.832 | 118.3 | 56.9 | 50.4 |
| `position` / RB | 62,625 | yes | 12.67 | 9.94 | 0.676 | 0.817 | 4.546 | 3.636 | 0.525 | 0.896 | 0.790 | 0.883 | 72.1 | 36.5 | 34.3 |
| `position` / TE | 54,078 | yes | 7.28 | 5.74 | 0.688 | 0.828 | 2.632 | 2.088 | 0.589 | 0.898 | 0.798 | 0.870 | 39.0 | 21.9 | 15.7 |
| `position` / WR | 103,866 | yes | 10.02 | 7.95 | 0.699 | 0.826 | 3.561 | 2.953 | 0.596 | 0.897 | 0.803 | 0.893 | 58.9 | 28.4 | 29.5 |
| `scoring_preset` / HALF | 84,399 | yes | 11.26 | 8.94 | 0.678 | 0.797 | 4.043 | 3.297 | 0.568 | 0.893 | 0.797 | 0.878 | 65.6 | 32.7 | 30.4 |
| `scoring_preset` / PPR | 84,399 | yes | 12.72 | 10.11 | 0.681 | 0.799 | 4.557 | 3.732 | 0.568 | 0.893 | 0.796 | 0.879 | 75.0 | 36.8 | 34.8 |
| `scoring_preset` / STD | 84,399 | yes | 9.81 | 7.84 | 0.671 | 0.795 | 3.539 | 2.887 | 0.569 | 0.892 | 0.791 | 0.877 | 56.2 | 28.6 | 26.2 |
| `season_phase` / weeks_1_3 | 47,655 | yes | 19.48 | 15.18 | 0.696 | 0.801 | 7.124 | 5.626 | 0.501 | 0.892 | 0.624 | 0.847 | 115.7 | 41.9 | 50.4 |
| `season_phase` / weeks_4_9 | 95,985 | yes | 13.38 | 10.78 | 0.699 | 0.816 | 4.665 | 3.950 | 0.533 | 0.892 | 0.785 | 0.866 | 79.5 | 37.2 | 37.1 |
| `season_phase` / weeks_10_plus | 109,557 | yes | 5.84 | 4.66 | 0.649 | 0.778 | 2.166 | 1.731 | 0.628 | 0.894 | 0.878 | 0.901 | 31.5 | 24.7 | 16.0 |
| `rookie` / rookie | 18,393 | yes | 16.69 | 14.87 | 0.610 | 0.716 | 6.508 | 5.288 | 0.279 | 0.872 | 0.733 | 0.823 | 81.7 | 42.6 | 43.9 |
| `veteran` / veteran | 234,804 | yes | 10.84 | 8.50 | 0.672 | 0.796 | 3.854 | 3.150 | 0.591 | 0.893 | 0.800 | 0.882 | 63.9 | 31.9 | 29.4 |
| `games_played_band` / no_games | 131,844 | yes | 5.82 | 2.05 | 0.182 | 0.214 | 1.754 | 0.994 | 0.885 | 0.926 | 0.825 | 0.964 | 4.5 | 17.1 | 14.5 |
| `games_played_band` / one_or_two_games | 34,782 | yes | 19.01 | 17.41 | 0.319 | 0.436 | 7.360 | 6.190 | 0.334 | 0.856 | 0.693 | 0.803 | 85.3 | 40.2 | 51.1 |
| `games_played_band` / three_plus_games | 86,571 | yes | 16.44 | 16.09 | 0.671 | 0.695 | 6.206 | 5.666 | 0.179 | 0.855 | 0.790 | 0.776 | 77.1 | 53.3 | 46.4 |
| `returning_from_absence` / returning | 18,951 | yes | 8.39 | 6.44 | 0.294 | 0.311 | 2.820 | 2.352 | 0.635 | 0.864 | 0.814 | 0.912 | 16.0 | 27.1 | 20.9 |
| `changed_team_in_season` / changed_team | 1,668 | yes | 11.66 | 10.36 | 0.512 | 0.597 | 4.283 | 3.587 | 0.342 | 0.900 | 0.813 | 0.782 | 45.1 | 37.6 | 29.0 |
| `in_season_arrival` / arrival | 4,296 | yes | 6.82 | 6.73 | 0.492 | 0.552 | 3.122 | 2.477 | 0.475 | 0.896 | 0.659 | 0.867 | 28.3 | 12.0 | 25.3 |
| `high_capital_underperforming` / high_capital_underperforming | 15,288 | yes | 17.44 | 16.17 | 0.363 | 0.497 | 6.531 | 5.651 | 0.180 | 0.843 | 0.780 | 0.783 | 63.4 | 54.5 | 47.5 |
| `high_capital_rookie` / high_capital_rookie | 4,965 | yes | 29.83 | 26.66 | 0.590 | 0.618 | 11.809 | 9.332 | 0.099 | 0.898 | 0.694 | 0.763 | 136.0 | 70.7 | 73.6 |
| `extreme_uncertainty` / widest_decile | 70,651 | yes | 23.11 | 19.39 | 0.594 | 0.698 | 8.318 | 6.868 | 0.207 | 0.880 | 0.815 | 0.781 | 97.1 | 73.5 | 56.8 |

## By snapshot week

| through week | R0 | R1 | R2 | R3 | RC1 |
|---|---|---|---|---|---|
| 1 | 24.25 | 25.41 | 22.81 | 27.10 | 17.95 |
| 2 | 22.92 | 20.67 | 21.20 | 25.80 | 16.34 |
| 3 | 21.57 | 17.98 | 19.48 | 23.77 | 15.20 |
| 4 | 20.29 | 16.05 | 17.99 | 23.45 | 14.37 |
| 5 | 18.94 | 14.51 | 16.62 | 23.39 | 13.48 |
| 6 | 17.74 | 12.92 | 15.33 | 23.55 | 12.51 |
| 7 | 16.39 | 11.48 | 13.92 | 22.39 | 11.30 |
| 8 | 14.87 | 10.19 | 12.47 | 14.09 | 10.24 |
| 9 | 13.51 | 9.25 | 11.29 | 13.29 | 9.28 |
| 10 | 12.15 | 8.34 | 10.17 | 12.76 | 8.31 |
| 11 | 10.70 | 7.34 | 8.96 | 11.95 | 7.29 |
| 12 | 9.20 | 6.31 | 7.68 | 8.35 | 6.23 |
| 13 | 7.53 | 5.25 | 6.34 | 7.37 | 5.06 |
| 14 | 5.87 | 4.18 | 4.98 | 6.55 | 3.96 |
| 15 | 4.06 | 3.05 | 3.58 | 3.77 | 2.79 |
| 16 | 2.51 | 1.99 | 2.29 | 3.07 | 1.75 |

MAE, macro-averaged across the cells of that week.

## Promotion gate

### `ros_promotion_v1`

The original rule, frozen before the candidate existed and reported unchanged. Its verdict is the historical record (ADR-073) and is preserved whatever the successor says.

**NOT PROMOTED** — `RC1` against `R2`.

Satisfied:
- clause 1: macro mean_pinball -0.8084 [-0.8328, -0.7857]
- clause 2: macro mae -2.4632 within the 1% tolerance (+0.1232)
- clause 3: macro spearman +0.1203

Failed:
- clause 4: cohort deterioration: games_played_band/no_games P10-P90 coverage 0.964 outside [0.60, 0.95]

### `ros_promotion_v2`

The successor rule (ADR-075), frozen and committed before it was applied to any evidence. Clauses 1-3 and 4a-4b are v1's, unchanged; 4c adds a proper local score; 4d states width against climatology; 4e states coverage against the coverage a calibrated forecaster can actually attain on the cohort.

**PROMOTED** — `RC1` against `R2`.

Satisfied:
- clause 1: macro mean_pinball -0.8084 [-0.8328, -0.7857]
- clause 2: macro mae -2.4632 within the 1% tolerance (+0.1232)
- clause 3: macro spearman +0.1203
- clause 4: no cohort deterioration across 22 decisive cohort(s) of 22 reported, on all five sub-clauses


## Checks

- `ros_experiment.seal_respected` **pass** — the run touched only the seasons its label permits (label=development; seasons=[2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024])
- `ros_experiment.scored_rows` **pass** — rows scored by every model on identical keys (253197 row(s) across 5 fold(s))
- `ros_experiment.macro_metrics` **pass** — R0 macro metrics (mae=14.051 pinball=5.313 spearman=0.578 coverage_p10_p90=0.785)
- `ros_experiment.macro_metrics` **pass** — R1 macro metrics (mae=11.046 pinball=4.500 spearman=0.779 coverage_p10_p90=0.805)
- `ros_experiment.macro_metrics` **pass** — R2 macro metrics (mae=12.319 pinball=4.444 spearman=0.677 coverage_p10_p90=0.790)
- `ros_experiment.macro_metrics` **pass** — R3 macro metrics (mae=15.826 pinball=5.520 spearman=0.751 coverage_p10_p90=0.693)
- `ros_experiment.macro_metrics` **pass** — RC1 macro metrics (mae=9.856 pinball=3.635 spearman=0.797 coverage_p10_p90=0.869)
