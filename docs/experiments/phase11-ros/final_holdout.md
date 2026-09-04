# Rest-of-season experiment — `final_holdout`

Generated 2026-09-04T03:04:39Z · experiment `phase11_ros_v1` · seed `20260903`.

## What was measured

- grain: `season x through_week x player_id x scoring_preset`
- rows scored: **53,307**
- seasons: [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
- folds: ['ros:2017-2024->2025']
- evaluation cell: `season x through_week x position x scoring_preset`

## Macro results

Macro means across evaluation cells, so one week's quarterback board weighs the same as one week's receiver board.

| model | MAE | pinball | Spearman | top-K recall | P10-P90 coverage | P25-P75 coverage | P10-P90 width | cells |
|---|---|---|---|---|---|---|---|---|
| R0 | 13.06 | 4.886 | 0.602 | 0.418 | 0.794 | 0.513 | 40.5 | 192 |
| R1 | 10.80 | 4.388 | 0.759 | 0.536 | 0.805 | 0.656 | 30.9 | 192 |
| R2 | 11.59 | 4.140 | 0.679 | 0.538 | 0.809 | 0.497 | 34.2 | 192 |
| R3 | 15.93 | 5.653 | 0.739 | 0.250 | 0.557 | 0.360 | 46.8 | 192 |
| RC1 | 9.34 | 3.427 | 0.795 | 0.530 | 0.870 | 0.732 | 29.7 | 192 |

**Primary baseline: `R2`** — chosen by the frozen rule (lowest development macro pinball loss), not by preference.

## Paired deltas

`RC1` minus `R2`, paired within cell, 1000 bootstrap replicates. Negative is better for a loss.

| metric | baseline | candidate | delta | 95% CI | interval excludes 0 |
|---|---|---|---|---|---|
| mae | 11.586 | 9.337 | -2.2497 | [-2.3774, -2.1285] | yes |
| mean_pinball | 4.140 | 3.427 | -0.7136 | [-0.7513, -0.6755] | yes |
| spearman | 0.679 | 0.795 | 0.1163 | [+0.1120, +0.1216] | yes |
| top_k_recall | 0.538 | 0.530 | -0.0078 | [-0.0141, +0.0156] | no |

## Predeclared cohorts

| cohort | rows | decisive | baseline MAE | candidate MAE | baseline ρ | candidate ρ | baseline P10-P90 coverage | candidate P10-P90 coverage | baseline width | candidate width |
|---|---|---|---|---|---|---|---|---|---|---|
| `full_universe` / all | 53,307 | yes | 10.55 | 8.52 | 0.679 | 0.795 | 0.803 | 0.880 | 30.8 | 28.2 |
| `position` / QB | 6,927 | yes | 18.19 | 14.08 | 0.644 | 0.725 | 0.838 | 0.840 | 57.0 | 42.6 |
| `position` / RB | 12,738 | yes | 11.91 | 10.14 | 0.655 | 0.807 | 0.815 | 0.860 | 32.6 | 32.5 |
| `position` / TE | 11,421 | yes | 6.92 | 5.82 | 0.738 | 0.819 | 0.793 | 0.873 | 19.8 | 15.9 |
| `position` / WR | 22,221 | yes | 9.24 | 7.24 | 0.677 | 0.829 | 0.792 | 0.907 | 27.2 | 27.5 |
| `scoring_preset` / HALF | 17,769 | yes | 10.50 | 8.53 | 0.680 | 0.794 | 0.802 | 0.880 | 30.7 | 27.9 |
| `scoring_preset` / PPR | 17,769 | yes | 11.88 | 9.55 | 0.682 | 0.797 | 0.802 | 0.883 | 34.4 | 32.3 |
| `scoring_preset` / STD | 17,769 | yes | 9.26 | 7.48 | 0.674 | 0.794 | 0.806 | 0.877 | 27.1 | 24.3 |
| `season_phase` / weeks_1_3 | 9,954 | yes | 18.14 | 14.63 | 0.710 | 0.800 | 0.645 | 0.852 | 40.1 | 46.2 |
| `season_phase` / weeks_4_9 | 19,947 | yes | 12.60 | 10.27 | 0.700 | 0.810 | 0.789 | 0.868 | 34.7 | 34.5 |
| `season_phase` / weeks_10_plus | 23,406 | yes | 5.57 | 4.42 | 0.647 | 0.780 | 0.883 | 0.903 | 23.4 | 15.1 |
| `rookie` / rookie | 5,136 | yes | 14.82 | 13.14 | 0.648 | 0.750 | 0.736 | 0.837 | 36.8 | 39.1 |
| `veteran` / veteran | 48,171 | yes | 10.09 | 8.03 | 0.680 | 0.798 | 0.810 | 0.884 | 30.1 | 27.0 |
| `games_played_band` / no_games | 28,383 | yes | 4.84 | 1.83 | 0.195 | 0.210 | 0.842 | 0.957 | 14.6 | 11.3 |
| `games_played_band` / one_or_two_games | 6,990 | yes | 18.44 | 17.50 | 0.407 | 0.424 | 0.697 | 0.798 | 39.0 | 50.3 |
| `games_played_band` / three_plus_games | 17,934 | yes | 16.50 | 15.60 | 0.669 | 0.722 | 0.784 | 0.789 | 53.1 | 46.2 |
| `returning_from_absence` / returning | 3,867 | yes | 8.22 | 6.51 | 0.281 | 0.269 | 0.818 | 0.900 | 26.2 | 20.9 |
| `changed_team_in_season` / changed_team | 363 | yes | 9.47 | 7.97 | 0.480 | 0.706 | 0.829 | 0.876 | 39.4 | 26.1 |
| `in_season_arrival` / arrival | 315 | yes | 1.08 | 1.69 | -0.060 | 0.160 | 0.756 | 0.946 | 1.7 | 13.9 |
| `high_capital_underperforming` / high_capital_underperforming | 3,074 | yes | 18.00 | 15.69 | 0.383 | 0.599 | 0.764 | 0.795 | 54.0 | 45.5 |
| `high_capital_rookie` / high_capital_rookie | 1,008 | yes | 34.04 | 28.76 | 0.115 | 0.164 | 0.641 | 0.720 | 68.0 | 72.4 |
| `extreme_uncertainty` / widest_decile | 14,059 | yes | 24.01 | 20.53 | 0.587 | 0.676 | 0.808 | 0.785 | 75.7 | 59.2 |

## By snapshot week

| through week | R0 | R1 | R2 | R3 | RC1 |
|---|---|---|---|---|---|
| 1 | 22.85 | 25.43 | 22.65 | 26.81 | 17.89 |
| 2 | 21.65 | 19.47 | 19.80 | 25.57 | 15.42 |
| 3 | 20.41 | 16.81 | 17.85 | 23.83 | 14.26 |
| 4 | 19.01 | 15.08 | 16.33 | 23.61 | 13.28 |
| 5 | 17.79 | 14.12 | 15.46 | 23.72 | 12.82 |
| 6 | 16.43 | 12.55 | 14.03 | 23.29 | 11.48 |
| 7 | 14.98 | 11.46 | 12.89 | 23.94 | 10.85 |
| 8 | 13.90 | 10.85 | 12.30 | 14.58 | 10.15 |
| 9 | 12.60 | 9.66 | 11.10 | 13.63 | 8.89 |
| 10 | 11.32 | 8.70 | 9.96 | 13.19 | 8.27 |
| 11 | 9.85 | 7.35 | 8.53 | 12.60 | 6.90 |
| 12 | 8.66 | 6.36 | 7.38 | 8.54 | 6.02 |
| 13 | 7.21 | 5.43 | 6.29 | 7.59 | 4.93 |
| 14 | 5.90 | 4.41 | 5.09 | 7.03 | 3.96 |
| 15 | 4.14 | 3.15 | 3.62 | 4.00 | 2.69 |
| 16 | 2.30 | 1.88 | 2.11 | 2.96 | 1.57 |

MAE, macro-averaged across the cells of that week.

## Promotion gate

Rule `ros_promotion_v1`, frozen before the comparison ran.

**NOT PROMOTED** — `RC1` against `R2`.

Satisfied:
- clause 1: macro mean_pinball -0.7136 [-0.7513, -0.6755]
- clause 2: macro mae -2.2497 within the 1% tolerance (+0.1159)
- clause 3: macro spearman +0.1163

Failed:
- clause 4: cohort deterioration: games_played_band/no_games P10-P90 coverage 0.957 outside [0.60, 0.95]; in_season_arrival/arrival MAE 1.08->1.69


## Checks

- `ros_experiment.seal_respected` **pass** — the run touched only the seasons its label permits (label=final_holdout; seasons=[2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025])
- `ros_experiment.scored_rows` **pass** — rows scored by every model on identical keys (53307 row(s) across 1 fold(s))
- `ros_experiment.macro_metrics` **pass** — R0 macro metrics (mae=13.063 pinball=4.886 spearman=0.602 coverage_p10_p90=0.794)
- `ros_experiment.macro_metrics` **pass** — R1 macro metrics (mae=10.795 pinball=4.388 spearman=0.759 coverage_p10_p90=0.805)
- `ros_experiment.macro_metrics` **pass** — R2 macro metrics (mae=11.586 pinball=4.140 spearman=0.679 coverage_p10_p90=0.809)
- `ros_experiment.macro_metrics` **pass** — R3 macro metrics (mae=15.930 pinball=5.653 spearman=0.739 coverage_p10_p90=0.557)
- `ros_experiment.macro_metrics` **pass** — RC1 macro metrics (mae=9.337 pinball=3.427 spearman=0.795 coverage_p10_p90=0.870)
