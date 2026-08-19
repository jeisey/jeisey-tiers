# Intrinsic model card — `intrinsic-cb-hurdle-v1`

Card `intrinsic_model_card_v1`, generated 2026-08-19T23:30:46Z from code `2f0e725`. Every number below is read from a committed experiment report or from the model artifact itself; none is written by hand.

## Purpose and intended use

Estimate the distribution of a player's fantasy-point total for one season from football evidence alone, and translate it into league-relative value. It is decision support for a redraft fantasy draft: a way to see where value and uncertainty sit, not a prediction anyone should treat as certain.

**Prohibited uses.** This model must never consume ADP, expert consensus rank, FantasyPros or FantasyCalc values, or any other market price (ADR-002); doing so would make the arbitrage comparison circular. It is not a betting model, not a weekly start/sit model, and not a dynasty model. Its outputs are not a claim about any individual player's health or future.

## Version and provenance

| Field | Value |
|---|---|
| model version | intrinsic-cb-hurdle-v1 |
| architecture | availability_x_performance |
| calibration | monotone_projection_v1 |
| target scale | season_total |
| quantile levels | 0.1, 0.25, 0.5, 0.75, 0.9 |
| seed | 20260819 |
| training seasons | 2014-2025 |
| fitted groups | 12 |
| feature set | intrinsic_core_v1 (7203befaa5be25a2) |
| feature schema | historical_features_v1 (c495ba3177dcb989) |
| features | 78 |
| LightGBM | 4.7.0 |
| code SHA | 2f0e725 |
| artifact generated | 2026-08-19T22:56:36Z |

## Data

Training grain is one row per season, player and scoring preset, over the eligible preseason universe ADR-022 defines: previous-season roster, target-season draft class, or a pre-anchor depth-chart snapshot. Every row's information cutoff is the draft-time anchor `draft_anchor_v1_tuesday_eod_pre_week1` (ADR-021). Labels are the season fantasy-point total over the documented horizon - weeks 1-16 before 2021, 1-17 from 2021 - computed by one scoring engine from weekly rows.

Sources are nflverse and ffopportunity only. No market or expert data touches any part of this model, and an automated audit over both feature names and declared source lineage runs inside every build.

## Architecture

Two LightGBM quantile components over the same features, composed by deterministic Monte Carlo:

1. **availability** — quantiles of `games / fantasy_horizon_weeks`, modelled as a rate so 16- and 17-week seasons are comparable inside one training window, then multiplied by the target season's horizon and rounded;
2. **conditional performance** — quantiles of fantasy points per *active* game, fitted only on rows with at least one game;
3. **composition** — `games x points-per-game`, with zero games scoring exactly zero and nothing clipped from below, because this project's scoring presets make a negative season total genuinely possible;
4. **dependence** — a Gaussian copula with one correlation per position x scoring preset, estimated inside the fold from probability-integral transforms of both components on an inner chronological split.

Because the published quantiles are empirical quantiles of one Monte Carlo sample, they cannot cross. The isotonic monotonicity projection is still applied as a safety net and is a no-op in practice.

**Uncertainty methodology.** The model emits five quantiles rather than a point estimate. They become a monotone piecewise-linear quantile function, sampled with per-player deterministic uniform streams; tails continue the slope of the nearest interior segment and clamp to bounds derived from the training range alone. Player draws are independent - V1 models no teammate or game-script correlation.

## Development results

Development folds 2020-2024, window `W1_all_history`, macro means over validation season x position x scoring cells. `B0` is the project's permanent naive baseline; `Q1` is the Phase-3 promoted direct-total model.

| Model | MAE | Spearman | Top-K | Pinball | P10-P90 cov | P25-P75 cov | P10-P90 width | Raw crossing |
|---|---|---|---|---|---|---|---|---|
| A0 | 22.1120 | 0.7203 | 0.5444 | 8.1418 | 0.7379 | 0.4771 | 62.4587 | 0.3873 |
| A1 | 22.1199 | 0.7197 | 0.5444 | 8.1326 | 0.8260 | 0.5418 | 70.9838 | 0.3873 |
| AH | 22.2540 | 0.7185 | 0.5597 | 8.1230 | 0.7442 | 0.4814 | 64.6096 | 0.3814 |
| B0 | 25.6016 | 0.6592 | 0.5354 | 9.9775 | 0.7927 | 0.5284 | 83.1079 | 0.0000 |
| CB | 21.9068 | 0.7502 | 0.5771 | 8.0804 | 0.8271 | 0.6143 | 64.8295 | 0.0000 |
| Q1 | 22.0699 | 0.7256 | 0.5444 | 8.1318 | 0.7712 | 0.5132 | 62.6765 | 0.3873 |

### The decisions, and the rules that made them

- **Calibration** (`phase4_calibration_v1`) selected `A0` (incumbent retained).
  - A0 stands: P25-P75 coverage gap widened by +0.0189, beyond the 0.010 tolerance
- **Horizon sensitivity** (`phase4_horizon_v1`) selected `A0` (incumbent retained).
  - A0 retained: mae +0.1420 [+0.0458, +0.2366]; mean_pinball -0.0188 [-0.0427, +0.0063]; 2021 MAE +0.79%, worst other fold +1.41%
- **Candidate A vs B** (`phase4_candidate_v1`) selected `CB` (decisive).
  - probabilistic quality: mean_pinball -0.0614 [-0.1002, -0.0236]
  - secondary improvement: MAE mae -0.2052 [-0.3322, -0.0733]; Spearman +0.0298; top-K recall +0.0326
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
- **Ranking statistic** (`phase4_ranking_v1`) selected `median_vorp` (incumbent retained).
  - median_vorp stands: top-K recall gain +0.0014 below the 0.010 required; macro Spearman falls 0.0058, beyond 0.005; macro Kendall falls 0.0071, beyond 0.005
- **Tier penalty** (`phase4_tier_v1`) selected `1.0` (decisive).
  - penalty 1.0 is admissible with bootstrap ARI 0.865, mean tier count 8.80, singleton rate 0.033 and boundary effect size 0.014
- **Tier stability** (`phase4_tier_stability_v1`) selected `fail` (incumbent retained).
  - bootstrap ARI 0.8649
  - singleton rate 0.0396
  - tier-count CV 0.0454
  - monotonic tier pairs 0.8448
  - cross-preset ARI 0.5288
  - **failed:** boundary agreement 0.2394 below 0.5000

### Quantile crossing, before and after

| Model | Raw crossing rate |
|---|---|
| A0 | 0.3873 |
| A1 | 0.3873 |
| AH | 0.3814 |
| B0 | 0.0000 |
| CB | 0.0000 |
| Q1 | 0.3873 |

Post-processing crossing rate is zero for every model, by construction of the monotonicity repair; the raw rate is reported so the repair cannot hide what it repaired.

### By position

| Position | Model | MAE | Spearman | Top-K | Pinball | P10-P90 cov |
|---|---|---|---|---|---|---|
| QB | A0 | 34.5927 | 0.6650 | 0.5000 | 13.0931 | 0.7083 |
| QB | A1 | 34.6047 | 0.6637 | 0.5000 | 13.0397 | 0.8063 |
| QB | AH | 34.9889 | 0.6631 | 0.5333 | 13.0842 | 0.7200 |
| QB | B0 | 39.4950 | 0.6422 | 0.5333 | 16.4625 | 0.7554 |
| QB | CB | 34.3088 | 0.7027 | 0.5500 | 13.0744 | 0.7856 |
| QB | Q1 | 34.4976 | 0.6697 | 0.5000 | 13.0751 | 0.7344 |
| RB | A0 | 23.1286 | 0.7366 | 0.5889 | 8.4070 | 0.7339 |
| RB | A1 | 23.1433 | 0.7351 | 0.5889 | 8.4239 | 0.8257 |
| RB | AH | 23.0912 | 0.7368 | 0.6056 | 8.3692 | 0.7247 |
| RB | B0 | 27.3826 | 0.6405 | 0.5528 | 9.8404 | 0.7856 |
| RB | CB | 22.8195 | 0.7545 | 0.6333 | 8.3222 | 0.8378 |
| RB | Q1 | 23.1034 | 0.7424 | 0.5889 | 8.3991 | 0.7624 |
| TE | A0 | 13.0222 | 0.7374 | 0.5056 | 4.6516 | 0.7243 |
| TE | A1 | 13.0277 | 0.7374 | 0.5056 | 4.6516 | 0.8280 |
| TE | AH | 13.1505 | 0.7359 | 0.5111 | 4.6335 | 0.7378 |
| TE | B0 | 14.7954 | 0.6652 | 0.5111 | 5.7615 | 0.7975 |
| TE | CB | 12.7888 | 0.7716 | 0.5278 | 4.5491 | 0.8276 |
| TE | Q1 | 12.9996 | 0.7419 | 0.5056 | 4.6443 | 0.7689 |
| WR | A0 | 17.7044 | 0.7424 | 0.5833 | 6.4155 | 0.7852 |
| WR | A1 | 17.7039 | 0.7426 | 0.5833 | 6.4150 | 0.8440 |
| WR | AH | 17.7855 | 0.7380 | 0.5889 | 6.4051 | 0.7945 |
| WR | B0 | 20.7337 | 0.6891 | 0.5444 | 7.8455 | 0.8322 |
| WR | CB | 17.7101 | 0.7719 | 0.5972 | 6.3761 | 0.8575 |
| WR | Q1 | 17.6790 | 0.7484 | 0.5833 | 6.4087 | 0.8190 |

### Calibration

Pooled coverage understates how tight the intervals are, because the model represents the probability of never playing as a genuine atom at zero: when a player's P25 and P75 are both exactly zero and he scores exactly zero, the interval covers him by definition. Both halves are therefore reported.

| Population | Rows | P10-P90 coverage | P25-P75 coverage |
|---|---|---|---|
| all rows | 15756.0 | 0.8373 | 0.6284 |
| played at least one game | 8613.0 | 0.7479 | 0.4562 |
| never played | 7143.0 | 0.9450 | 0.8361 |

Share of evaluation rows whose P25 and P75 are both exactly zero: 18.4%.

## Final holdout

Season 2025 was sealed from the start of Phase 3 (ADR-025) and evaluated **exactly once**, after every model-design decision was frozen. It is no longer a holdout; it joined the production training window only after that evaluation.

- authorization reason: Phase 4 stage E: the single evaluation of the sealed 2025 holdout for the frozen production intrinsic model (CB, ADR-033), run after freeze checkpoint 2f0e725 fixed every architecture, calibration, ranking, simulation and tier decision.
- verdict: **PASS**
  - point accuracy: mae -3.7384 [-4.3641, -3.1018]
  - probabilistic quality: mean_pinball -2.1337 [-2.3774, -1.8744]
  - ranking: spearman +0.1015 within tolerance
  - no positional collapse across 4 position(s)
  - distribution validity: no production quantile crossings

### Full 2025 universe (the primary result)

| Model | Cells | Rows | MAE | Spearman | Top-K | Pinball | P10-P90 cov |
|---|---|---|---|---|---|---|---|
| B0 | 12 | 3309 | 23.9332 | 0.6786 | 0.4722 | 9.3310 | 0.8077 |
| CB | 12 | 3309 | 20.1948 | 0.7801 | 0.5208 | 7.1974 | 0.8450 |

### Predeclared diagnostic slices

ADR-025 fixed these before any candidate was compared. They explain the primary result; not one of them can replace it, and none is part of the acceptance gate.

| Slice | Label | Model | Rows | MAE | Spearman | Pinball | P10-P90 cov |
|---|---|---|---|---|---|---|---|
| full_universe | all | B0 | 432 | 37.2220 | 0.6751 | 15.2185 | 0.7778 |
| full_universe | all | B0 | 789 | 26.0305 | 0.6427 | 9.1282 | 0.8175 |
| full_universe | all | B0 | 708 | 14.6247 | 0.6850 | 6.0043 | 0.7797 |
| full_universe | all | B0 | 1380 | 17.8557 | 0.6764 | 6.9731 | 0.8558 |
| full_universe | all | CB | 432 | 29.9206 | 0.7526 | 10.5456 | 0.8032 |
| full_universe | all | CB | 789 | 23.7443 | 0.7439 | 8.5026 | 0.8264 |
| full_universe | all | CB | 708 | 12.3452 | 0.8185 | 4.5476 | 0.8715 |
| full_universe | all | CB | 1380 | 14.7693 | 0.8033 | 5.1936 | 0.8790 |
| era_stable_universe | prior_roster_or_draft_class | B0 | 429 | 37.4698 | 0.6838 | 15.2909 | 0.7762 |
| era_stable_universe | prior_roster_or_draft_class | B0 | 771 | 26.5575 | 0.6510 | 9.3084 | 0.8171 |
| era_stable_universe | prior_roster_or_draft_class | B0 | 699 | 14.7989 | 0.6846 | 6.0617 | 0.7768 |
| era_stable_universe | prior_roster_or_draft_class | B0 | 1344 | 18.0955 | 0.6915 | 7.0390 | 0.8564 |
| era_stable_universe | prior_roster_or_draft_class | CB | 429 | 30.1041 | 0.7579 | 10.6118 | 0.8019 |
| era_stable_universe | prior_roster_or_draft_class | CB | 771 | 24.1226 | 0.7497 | 8.6259 | 0.8288 |
| era_stable_universe | prior_roster_or_draft_class | CB | 699 | 12.4595 | 0.8252 | 4.5908 | 0.8698 |
| era_stable_universe | prior_roster_or_draft_class | CB | 1344 | 14.9171 | 0.8122 | 5.2409 | 0.8847 |
| rookie | rookie | B0 | 45 | 35.7627 | 0.4367 | 13.9159 | 0.8000 |
| rookie | rookie | B0 | 93 | 39.8518 | 0.5863 | 14.8779 | 0.6882 |
| rookie | rookie | B0 | 57 | 38.7952 | 0.1769 | 16.8901 | 0.4561 |
| rookie | rookie | B0 | 123 | 22.7447 | 0.6345 | 9.1771 | 0.7561 |
| rookie | rookie | CB | 45 | 31.1163 | 0.5577 | 10.9153 | 0.8222 |
| rookie | rookie | CB | 93 | 39.8996 | 0.4484 | 14.2936 | 0.6667 |
| rookie | rookie | CB | 57 | 28.4296 | 0.7967 | 10.7846 | 0.7193 |
| rookie | rookie | CB | 123 | 19.8760 | 0.7182 | 7.1193 | 0.7805 |
| veteran | veteran | B0 | 387 | 37.3917 | 0.6980 | 15.3700 | 0.7752 |
| veteran | veteran | B0 | 696 | 24.1837 | 0.6396 | 8.3599 | 0.8348 |
| veteran | veteran | B0 | 651 | 12.5084 | 0.7335 | 5.0511 | 0.8080 |
| veteran | veteran | B0 | 1257 | 17.3773 | 0.6761 | 6.7574 | 0.8656 |
| veteran | veteran | CB | 387 | 29.7816 | 0.7772 | 10.5026 | 0.8010 |
| veteran | veteran | CB | 696 | 21.5856 | 0.7474 | 7.7288 | 0.8477 |
| veteran | veteran | CB | 651 | 10.9369 | 0.8224 | 4.0015 | 0.8848 |
| veteran | veteran | CB | 1257 | 14.2696 | 0.7972 | 5.0052 | 0.8886 |
| depth_context_state | depth_observed_at_anchor | B0 | 255 | 56.6996 | 0.7003 | 22.3656 | 0.6471 |
| depth_context_state | depth_observed_at_anchor | B0 | 390 | 41.9564 | 0.6948 | 15.3989 | 0.7487 |
| depth_context_state | depth_observed_at_anchor | B0 | 369 | 24.5366 | 0.6501 | 9.6329 | 0.6612 |
| depth_context_state | depth_observed_at_anchor | B0 | 633 | 29.8946 | 0.7537 | 11.1529 | 0.7567 |
| depth_context_state | depth_observed_at_anchor | CB | 255 | 48.1853 | 0.7504 | 16.6655 | 0.7137 |
| depth_context_state | depth_observed_at_anchor | CB | 390 | 42.9672 | 0.6839 | 15.1172 | 0.7333 |
| depth_context_state | depth_observed_at_anchor | CB | 369 | 22.1595 | 0.7663 | 8.0734 | 0.7940 |
| depth_context_state | depth_observed_at_anchor | CB | 633 | 29.3607 | 0.7646 | 10.0317 | 0.7883 |
| depth_context_state | depth_unavailable | B0 | 144 | 7.7707 | 0.2170 | 4.2975 | 0.9792 |
| depth_context_state | depth_unavailable | B0 | 213 | 9.0781 | 0.0056 | 2.3068 | 0.9577 |
| depth_context_state | depth_unavailable | B0 | 222 | 2.9502 | 0.0624 | 1.8028 | 0.9099 |
| depth_context_state | depth_unavailable | B0 | 492 | 6.6295 | -0.0938 | 3.0838 | 0.9878 |
| depth_context_state | depth_unavailable | CB | 144 | 0.9221 | 0.0303 | 0.7564 | 0.9583 |
| depth_context_state | depth_unavailable | CB | 213 | 1.3675 | 0.1267 | 0.8175 | 0.9437 |
| depth_context_state | depth_unavailable | CB | 222 | 0.4135 | -0.0512 | 0.2840 | 0.9865 |
| depth_context_state | depth_unavailable | CB | 492 | 0.2704 | -0.0250 | 0.2468 | 0.9695 |
| depth_context_state | prior_season_role_proxy | B0 | 33 | 15.2287 | 0.6066 | 7.6463 | 0.9091 |
| depth_context_state | prior_season_role_proxy | B0 | 186 | 12.0510 | 0.2289 | 3.7916 | 0.8011 |
| depth_context_state | prior_season_role_proxy | B0 | 117 | 5.5155 | 0.2629 | 2.5319 | 0.9060 |
| depth_context_state | prior_season_role_proxy | B0 | 255 | 9.6309 | 0.3352 | 4.1014 | 0.8471 |
| depth_context_state | prior_season_role_proxy | CB | 33 | 15.3229 | 0.4716 | 5.9721 | 0.8182 |
| depth_context_state | prior_season_role_proxy | CB | 186 | 9.0631 | 0.3189 | 3.4340 | 0.8871 |
| depth_context_state | prior_season_role_proxy | CB | 117 | 4.0320 | 0.3026 | 1.5175 | 0.8974 |
| depth_context_state | prior_season_role_proxy | CB | 255 | 6.5225 | 0.2127 | 2.7283 | 0.9294 |
| position | QB | B0 | 432 | 37.2220 | 0.6751 | 15.2185 | 0.7778 |
| position | QB | CB | 432 | 29.9206 | 0.7526 | 10.5456 | 0.8032 |
| position | RB | B0 | 789 | 26.0305 | 0.6427 | 9.1282 | 0.8175 |
| position | RB | CB | 789 | 23.7443 | 0.7439 | 8.5026 | 0.8264 |
| position | TE | B0 | 708 | 14.6247 | 0.6850 | 6.0043 | 0.7797 |
| position | TE | CB | 708 | 12.3452 | 0.8185 | 4.5476 | 0.8715 |
| position | WR | B0 | 1380 | 17.8557 | 0.6764 | 6.9731 | 0.8558 |
| position | WR | CB | 1380 | 14.7693 | 0.8033 | 5.1936 | 0.8790 |
| scoring_preset | HALF | B0 | 144 | 37.2220 | 0.6801 | 15.2185 | 0.7778 |
| scoring_preset | HALF | B0 | 263 | 26.0217 | 0.6529 | 9.1068 | 0.8137 |
| scoring_preset | HALF | B0 | 236 | 14.5932 | 0.7032 | 5.9914 | 0.7500 |
| scoring_preset | HALF | B0 | 460 | 17.8175 | 0.6854 | 6.9650 | 0.8565 |
| scoring_preset | HALF | CB | 144 | 30.2075 | 0.7440 | 10.5848 | 0.8194 |
| scoring_preset | HALF | CB | 263 | 23.8234 | 0.7445 | 8.4396 | 0.8289 |
| scoring_preset | HALF | CB | 236 | 12.2862 | 0.8196 | 4.5374 | 0.8644 |
| scoring_preset | HALF | CB | 460 | 14.6899 | 0.8037 | 5.1595 | 0.8826 |
| scoring_preset | PPR | B0 | 144 | 37.2378 | 0.6804 | 15.2245 | 0.7778 |
| scoring_preset | PPR | B0 | 263 | 28.5966 | 0.6486 | 10.0182 | 0.8175 |
| scoring_preset | PPR | B0 | 236 | 17.8366 | 0.7058 | 7.2883 | 0.7627 |
| scoring_preset | PPR | B0 | 460 | 21.4223 | 0.6915 | 8.3544 | 0.8630 |
| scoring_preset | PPR | CB | 144 | 29.7905 | 0.7652 | 10.5669 | 0.7917 |
| scoring_preset | PPR | CB | 263 | 25.8607 | 0.7394 | 9.3331 | 0.8137 |
| scoring_preset | PPR | CB | 236 | 15.1700 | 0.8140 | 5.5731 | 0.8771 |
| scoring_preset | PPR | CB | 460 | 17.9059 | 0.8026 | 6.3150 | 0.8717 |
| scoring_preset | STD | B0 | 144 | 37.2063 | 0.6803 | 15.2126 | 0.7778 |
| scoring_preset | STD | B0 | 263 | 23.4733 | 0.6476 | 8.2596 | 0.8213 |
| scoring_preset | STD | B0 | 236 | 11.4443 | 0.6817 | 4.7331 | 0.8263 |
| scoring_preset | STD | B0 | 460 | 14.3274 | 0.6858 | 5.5998 | 0.8478 |
| scoring_preset | STD | CB | 144 | 29.7638 | 0.7494 | 10.4851 | 0.7986 |
| scoring_preset | STD | CB | 263 | 21.5486 | 0.7495 | 7.7352 | 0.8365 |
| scoring_preset | STD | CB | 236 | 9.5795 | 0.8248 | 3.5323 | 0.8729 |
| scoring_preset | STD | CB | 460 | 11.7119 | 0.8046 | 4.1063 | 0.8826 |
| information_rich | information_rich | B0 | 111 | 82.5125 | 0.4762 | 32.2688 | 0.5135 |
| information_rich | information_rich | B0 | 306 | 39.1872 | 0.7443 | 13.5199 | 0.8072 |
| information_rich | information_rich | B0 | 237 | 24.4697 | 0.7627 | 8.8916 | 0.7046 |
| information_rich | information_rich | B0 | 459 | 33.4005 | 0.7693 | 12.1137 | 0.7669 |
| information_rich | information_rich | CB | 111 | 72.6138 | 0.5564 | 24.7087 | 0.6396 |
| information_rich | information_rich | CB | 306 | 40.4015 | 0.7546 | 14.0609 | 0.7484 |
| information_rich | information_rich | CB | 237 | 23.6072 | 0.7913 | 8.4197 | 0.8017 |
| information_rich | information_rich | CB | 459 | 32.8110 | 0.7707 | 11.2453 | 0.7952 |
| low_information | low_information | B0 | 321 | 21.5609 | 0.4206 | 9.3227 | 0.8692 |
| low_information | low_information | B0 | 483 | 17.6952 | 0.3386 | 6.3459 | 0.8240 |
| low_information | low_information | B0 | 471 | 9.6709 | 0.3082 | 4.5514 | 0.8174 |
| low_information | low_information | B0 | 921 | 10.1086 | 0.2942 | 4.4111 | 0.9001 |
| low_information | low_information | CB | 321 | 15.1575 | 0.5654 | 5.6481 | 0.8598 |
| low_information | low_information | CB | 483 | 13.1912 | 0.5658 | 4.9812 | 0.8758 |
| low_information | low_information | CB | 471 | 6.6784 | 0.5704 | 2.5992 | 0.9066 |
| low_information | low_information | CB | 921 | 5.7777 | 0.6280 | 2.1777 | 0.9207 |

For context, the same model scored MAE 21.907 and pinball 8.080 on the development folds, against B0's 25.602 and 9.977.

## Known limitations

- **Fantasy outcomes are mostly noise.** Injury, role change and coaching turn a correct process into a wrong answer routinely. A P10-P90 interval sixty points wide is the honest statement of that, not a modelling failure.
- **Independent player draws.** V1 samples every player independently, so it cannot express that a quarterback's collapse takes his receivers with him.
- **The draw count is a predeclared fallback, not a converged one.** No count in the frozen ladder met every tolerance, so 10000 draws stands by the rule's own fallback clause (ADR-034). Residual Monte Carlo error is roughly 0.3 fantasy points on a player's expected VORP and under one and a half rank positions in the top 150; tier boundaries move more than that.
- **Tier boundaries are not sharply located, and the stability gate says so.** Membership is reproducible under resampling (bootstrap ARI 0.865), but only 23.9% of promoted boundaries survive in a majority of replicates against a 50% bar, so the gate fails (ADR-035). Read a tier as a group of comparable players, never as a hard line: the median boundary sits on a sub-point median gap, and the player just below one outscores the player just above it almost half the time.
- **The 2014-2016 era is thinner.** nflverse roster coverage steps up at 2016, so those target seasons carry about 36% fewer eligible rows. ADR-028 chose to train across the boundary on measured evidence; any metric averaged over all seasons mixes two universes.
- **The fantasy horizon changed at 2021**, from weeks 1-16 to 1-17, so season totals sit on a ~6% different scale either side. ADR-032 measured a horizon-normalized target and rejected it; the boundary remains a limitation rather than a correction.
- **Rookies are low-information rows.** Before 2025 no season has a draft-time depth observation at all, so a rookie's entire preseason signal is draft capital, biography and team context. Their errors are larger and are reported separately rather than averaged away.
- **There is no preseason injury feature, in any season.** No nflverse source publishes an injury report at a draft anchor (ADR-011). A player who enters the season hurt looks healthy to this model.
- **Pre-2025 team and depth context is mostly unobservable.** Free agency and trades leave no timestamped preseason trace before the snapshot era, so `team_at_anchor` and `depth_rank_at_anchor` are excluded from the feature set entirely (ADR-026).
- **Current status is metadata, not signal.** Today's roster status and team annotate a published row and can remove a retired player from the board, but they never enter a prediction: they have no development-era support and could not be validated.
- **The copula parameter describes active players.** Points per game is undefined for a player who never appears, so the availability/performance dependence is estimated on players who played and extrapolated to those who did not.

## Fairness and coverage

Human demographic fairness is not applicable: the model consumes on-field production, age, draft capital, athletic testing and team context, and no protected attribute. The coverage biases that do matter are data ones and are reported above: rookies and low-information players carry larger error, the pre-2016 seasons are thinner, and combine measurements exist only for players who tested - they are never imputed for those who did not.

