# Rest-of-season model card — `rc1_ros_hurdle_v1`

Card `ros_model_card_v1`, generated 2026-09-04T03:06:43Z from code `af30b38`. Every number below is read from a committed report or from the code's own frozen declarations; none is written by hand.

## Purpose and intended use

Estimate the distribution of a player's fantasy points over the remainder of the current season from football evidence alone, and translate it into league-relative value. Decision support for in-season roster decisions, not a certainty.

## Grain, cutoff and label

- grain: `season x through_week x player_id x scoring_preset`
- cutoff `ros_cutoff_v1`: A snapshot through week N of season Y may read completed regular-season weeks 1..N of season Y and any season strictly before Y. It predicts weeks N+1..horizon.last_week of season Y. Snapshots run from week 1 to horizon.last_week - 1 inclusive.
- label `ros_label_v1`: `actual_remaining_points`, composed from `actual_remaining_games`, `actual_remaining_ppg`

## Features

Set `ros_core_v1` (`f5ad9df207795351`): 121 inputs — 78 inherited from Phase 3's frozen preseason core and 43 in-season columns. Full list in `docs/ROS_FEATURE_DICTIONARY.md`.

Excluded by decision, not by omission:

- **market_signals** — audited by ffdraft.quality.audit_intrinsic_feature_names
- **injury_and_practice_reports** — excluded; see ADR-070
- **depth_and_roster_snapshots** — excluded; no historical point-in-time parity

## Architecture

availability x conditional performance hurdle, Monte Carlo composed; 250 boosting rounds per quantile per component; tuning: none; Q1's predeclared configuration is reused unchanged.

## Development result

Primary baseline `R2`, chosen by the frozen rule.

| model | MAE | pinball | Spearman | P10-P90 coverage |
|---|---|---|---|---|
| R0 | 14.05 | 5.313 | 0.578 | 0.785 |
| R1 | 11.05 | 4.500 | 0.779 | 0.805 |
| R2 | 12.32 | 4.444 | 0.677 | 0.790 |
| R3 | 15.83 | 5.520 | 0.751 | 0.693 |
| RC1 | 9.86 | 3.635 | 0.797 | 0.869 |

Paired deltas, candidate minus primary baseline:

| metric | delta | 95% CI | interval excludes 0 |
|---|---|---|---|
| mae | -2.4632 | [-2.5305, -2.3958] | yes |
| mean_pinball | -0.8084 | [-0.8328, -0.7857] | yes |
| spearman | 0.1203 | [+0.1184, +0.1229] | yes |
| top_k_recall | -0.0034 | [-0.0044, +0.0079] | no |

## Promotion decision

Rule `ros_promotion_v1` — **NOT PROMOTED**.

- satisfied: clause 1: macro mean_pinball -0.8084 [-0.8328, -0.7857]
- satisfied: clause 2: macro mae -2.4632 within the 1% tolerance (+0.1232)
- satisfied: clause 3: macro spearman +0.1203
- **failed**: clause 4: cohort deterioration: games_played_band/no_games P10-P90 coverage 0.964 outside [0.60, 0.95]

## Sealed season

2025 — status `CONSUMED`.

2025 was opened once before, in Phase 4, as the preseason model's final holdout. Nothing from it informed the rest-of-season design: the cutoff rule, the feature set, the baselines, the promotion rule and the replacement decision were all frozen and committed before it was opened here. Season totals do correlate with rest-of-season totals, so this is strong but not fully naive out-of-time evidence (ADR-069).

| model | MAE | pinball | Spearman | P10-P90 coverage |
|---|---|---|---|---|
| R0 | 13.06 | 4.886 | 0.602 | 0.794 |
| R1 | 10.80 | 4.388 | 0.759 | 0.805 |
| R2 | 11.59 | 4.140 | 0.679 | 0.809 |
| R3 | 15.93 | 5.653 | 0.739 | 0.557 |
| RC1 | 9.34 | 3.427 | 0.795 | 0.870 |

| metric | delta | 95% CI | interval excludes 0 |
|---|---|---|---|
| mae | -2.2497 | [-2.3774, -2.1285] | yes |
| mean_pinball | -0.7136 | [-0.7513, -0.6755] | yes |
| spearman | 0.1163 | [+0.1120, +0.1216] | yes |
| top_k_recall | -0.0078 | [-0.0141, +0.0156] | no |

- **failed on the sealed season**: clause 4: cohort deterioration: games_played_band/no_games P10-P90 coverage 0.957 outside [0.60, 0.95]; in_season_arrival/arrival MAE 1.08->1.69

## Value, replacement and tiers

- **replacement**: `rostered_depth` (rule `ros_replacement_v1`)
- **convergence**: `10000` (rule `phase4_convergence_v1`)
- **tier_penalty**: `3.0` (rule `phase4_tier_v1`)
- **tier_stability**: `fail` (rule `phase4_tier_stability_v1`)

## Known limitations

- There is no injury or practice-report feature. The model learns absence from the box score, so it sees a player who has stopped playing but not one who is about to (ADR-070).
- The sealed season is 2025, which Phase 4 had already opened as the preseason model's final holdout. Nothing from it informed this model's design, but season totals correlate with rest-of-season totals, so its out-of-time result is strong rather than fully naive evidence (ADR-069).
- Roughly half of all modelled rows have zero remaining games. Pooled interval coverage therefore overstates interval width, and coverage is reported split by appearances.
- The availability/performance dependence is estimated on players with at least one remaining game, because points per game is undefined for the rest, and extrapolated to everyone.
- The preseason feature block is null for in-season arrivals, who are 8.7% of players in the 2017-2025 build and are reported as their own cohort.
- Player outcomes are simulated independently; teammate and team-level correlations are not modelled, exactly as in Release 1.
- Nothing here is published. Phase 11 is an offline subsystem; exposing it safely is Phase 12's job.
