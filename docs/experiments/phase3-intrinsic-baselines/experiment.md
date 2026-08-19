# Phase 3 — intrinsic baselines and evaluation harness

Experiment `phase3_intrinsic_v1`, seed `20260819`, code `c2b48cc`, generated 2026-08-19T13:34:46Z.

## Conclusion

**Q1 advances to Phase 4 under training window `W1_all_history`.**

- macro MAE 22.070 points
- macro mean pinball loss 8.132
- macro Spearman 0.7256
- selection rule: the candidate with the lowest macro mean pinball loss among those passing the frozen gate on the selected window; ties broken on macro MAE
- promotion criteria `phase3_promotion_v1`, frozen before the comparison

**Training window:** W1_all_history — decisive.

> W1 improves both primary metrics on the common folds with paired 95% intervals excluding zero (MAE -0.2864 [-0.4735, -0.1067], pinball -0.0826 [-0.1340, -0.0373])

**Final holdout:** season 2025 — **UNTOUCHED / NOT EVALUATED**.

## What the numbers say

### Aggregate performance (development folds, macro over season x position x scoring)

| Window | Model | Cells | Rows | MAE | RMSE | Spearman | Kendall | Top-K | Pinball | P10-P90 cov | P10-P90 width | Crossing |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| W1_all_history | B0 | 60 | 15756 | 25.6016 | 44.0636 | 0.6592 | 0.5243 | 0.5354 | 9.9775 | 0.7927 | 83.1079 | 0.0000 |
| W1_all_history | B1 | 60 | 15756 | 26.9786 | 42.2099 | 0.7105 | 0.5503 | 0.5931 | 9.7418 | 0.7983 | 80.3692 | 0.0000 |
| W1_all_history | Q1 | 60 | 15756 | 22.0699 | 41.0277 | 0.7256 | 0.5703 | 0.5444 | 8.1318 | 0.7712 | 62.6765 | 0.3873 |
| W2_modern_era | B0 | 60 | 15756 | 25.4267 | 44.1152 | 0.6588 | 0.5239 | 0.5347 | 10.0056 | 0.7518 | 77.4559 | 0.0000 |
| W2_modern_era | B1 | 60 | 15756 | 27.5869 | 43.5878 | 0.7078 | 0.5478 | 0.5715 | 10.0713 | 0.7934 | 83.2274 | 0.0000 |
| W2_modern_era | Q1 | 60 | 15756 | 22.3563 | 41.2130 | 0.7249 | 0.5714 | 0.5611 | 8.2144 | 0.7652 | 62.1570 | 0.4014 |

Row-weighted equivalents are in the JSON report under `aggregates`; they are diagnostics, not the decision metric, because WR and RB cells carry two to three times the rows of QB and TE ones.

### Paired deltas against the primary baseline

- `B1_vs_B0@W1_all_history` **mae** +1.3769 (95% CI +0.9933 to +1.7293, excludes zero)
- `B1_vs_B0@W1_all_history` **mean_pinball** -0.2357 (95% CI -0.3951 to -0.1007, excludes zero)
- `B1_vs_B0@W1_all_history` **spearman** +0.0512 (95% CI +0.0421 to +0.0594, excludes zero)
- `B1_vs_B0@W2_modern_era` **mae** +2.1602 (95% CI +1.7797 to +2.5218, excludes zero)
- `B1_vs_B0@W2_modern_era` **mean_pinball** +0.0657 (95% CI -0.0987 to +0.2099, includes zero)
- `B1_vs_B0@W2_modern_era` **spearman** +0.0490 (95% CI +0.0401 to +0.0573, excludes zero)
- `Q1_vs_B0@W1_all_history` **mae** -3.5318 (95% CI -3.8669 to -3.1801, excludes zero)
- `Q1_vs_B0@W1_all_history` **mean_pinball** -1.8457 (95% CI -1.9760 to -1.7176, excludes zero)
- `Q1_vs_B0@W1_all_history` **spearman** +0.0664 (95% CI +0.0575 to +0.0746, excludes zero)
- `Q1_vs_B0@W2_modern_era` **mae** -3.0704 (95% CI -3.3725 to -2.7684, excludes zero)
- `Q1_vs_B0@W2_modern_era` **mean_pinball** -1.7912 (95% CI -1.9231 to -1.6524, excludes zero)
- `Q1_vs_B0@W2_modern_era` **spearman** +0.0661 (95% CI +0.0568 to +0.0744, excludes zero)
- `W1_vs_W2@Q1` **mae** -0.2864 (95% CI -0.4735 to -0.1067, excludes zero)
- `W1_vs_W2@Q1` **mean_pinball** -0.0826 (95% CI -0.1340 to -0.0373, excludes zero)
- `W1_vs_W2@Q1` **spearman** +0.0007 (95% CI -0.0036 to +0.0054, includes zero)

Paired block bootstrap, 1000 replicates, seed 20260819, resampling player-seasons within validation-season x position x scoring blocks and carrying both models' predictions for the same rows through the same resample.

### By position

| Window | Position | Model | Rows | MAE | Spearman | Pinball | P10-P90 cov | P10-P90 width |
|---|---|---|---|---|---|---|---|---|
| W1_all_history | QB | B0 | 2058 | 39.4950 | 0.6422 | 16.4625 | 0.7554 | 119.3966 |
| W1_all_history | QB | B1 | 2058 | 42.5482 | 0.6720 | 16.6860 | 0.7815 | 132.5888 |
| W1_all_history | QB | Q1 | 2058 | 34.4976 | 0.6697 | 13.0751 | 0.7344 | 93.7893 |
| W1_all_history | RB | B0 | 3849 | 27.3826 | 0.6405 | 9.8404 | 0.7856 | 78.4320 |
| W1_all_history | RB | B1 | 3849 | 28.2262 | 0.7253 | 9.6217 | 0.7887 | 80.3302 |
| W1_all_history | RB | Q1 | 3849 | 23.1034 | 0.7424 | 8.3991 | 0.7624 | 65.7561 |
| W1_all_history | TE | B0 | 3366 | 14.7954 | 0.6652 | 5.7615 | 0.7975 | 56.0583 |
| W1_all_history | TE | B1 | 3366 | 14.9467 | 0.7143 | 5.1005 | 0.8228 | 42.5926 |
| W1_all_history | TE | Q1 | 3366 | 12.9996 | 0.7419 | 4.6443 | 0.7689 | 36.0489 |
| W1_all_history | WR | B0 | 6483 | 20.7337 | 0.6891 | 7.8455 | 0.8322 | 78.5448 |
| W1_all_history | WR | B1 | 6483 | 22.1933 | 0.7302 | 7.5590 | 0.8001 | 65.9654 |
| W1_all_history | WR | Q1 | 6483 | 17.6790 | 0.7484 | 6.4087 | 0.8190 | 55.1117 |
| W2_modern_era | QB | B0 | 2058 | 39.2217 | 0.6410 | 16.5226 | 0.7063 | 110.7461 |
| W2_modern_era | QB | B1 | 2058 | 44.3734 | 0.6772 | 17.2980 | 0.7877 | 142.0461 |
| W2_modern_era | QB | Q1 | 2058 | 35.1175 | 0.6825 | 13.1105 | 0.7564 | 102.0089 |
| W2_modern_era | RB | B0 | 3849 | 27.0325 | 0.6487 | 10.0692 | 0.7700 | 78.6636 |
| W2_modern_era | RB | B1 | 3849 | 28.5191 | 0.7189 | 9.9925 | 0.7802 | 81.1970 |
| W2_modern_era | RB | Q1 | 3849 | 23.1959 | 0.7364 | 8.4987 | 0.7436 | 61.7151 |
| W2_modern_era | TE | B0 | 3366 | 14.7399 | 0.6659 | 5.8817 | 0.7776 | 54.5198 |
| W2_modern_era | TE | B1 | 3366 | 15.2963 | 0.7111 | 5.3718 | 0.8081 | 44.4218 |
| W2_modern_era | TE | Q1 | 3366 | 13.0336 | 0.7390 | 4.7033 | 0.7686 | 35.4289 |
| W2_modern_era | WR | B0 | 6483 | 20.7126 | 0.6797 | 7.5491 | 0.7535 | 65.8941 |
| W2_modern_era | WR | B1 | 6483 | 22.1588 | 0.7241 | 7.6230 | 0.7977 | 65.2447 |
| W2_modern_era | WR | Q1 | 6483 | 18.0782 | 0.7417 | 6.5451 | 0.7922 | 49.4749 |

### By validation season

| Window | Season | Model | Rows | MAE | Spearman | Pinball | P10-P90 cov |
|---|---|---|---|---|---|---|---|
| W1_all_history | 2020 | B0 | 3195 | 24.7421 | 0.6717 | 9.6788 | 0.8220 |
| W1_all_history | 2020 | B1 | 3195 | 25.3194 | 0.7201 | 9.4546 | 0.8164 |
| W1_all_history | 2020 | Q1 | 3195 | 20.9917 | 0.7391 | 7.8069 | 0.7722 |
| W1_all_history | 2021 | B0 | 3168 | 26.6052 | 0.6231 | 10.4708 | 0.8207 |
| W1_all_history | 2021 | B1 | 3168 | 27.8880 | 0.6817 | 10.0034 | 0.7722 |
| W1_all_history | 2021 | Q1 | 3168 | 22.9676 | 0.6894 | 8.4121 | 0.7480 |
| W1_all_history | 2022 | B0 | 3024 | 24.7274 | 0.6692 | 9.6206 | 0.7834 |
| W1_all_history | 2022 | B1 | 3024 | 27.0028 | 0.7045 | 9.5357 | 0.8060 |
| W1_all_history | 2022 | Q1 | 3024 | 22.4620 | 0.7150 | 8.1982 | 0.7644 |
| W1_all_history | 2023 | B0 | 3219 | 25.8657 | 0.6608 | 10.0033 | 0.7865 |
| W1_all_history | 2023 | B1 | 3219 | 27.1431 | 0.7262 | 9.7930 | 0.8131 |
| W1_all_history | 2023 | Q1 | 3219 | 22.0704 | 0.7347 | 8.2203 | 0.7838 |
| W1_all_history | 2024 | B0 | 3150 | 26.0678 | 0.6712 | 10.1139 | 0.7507 |
| W1_all_history | 2024 | B1 | 3150 | 27.5397 | 0.7198 | 9.9223 | 0.7837 |
| W1_all_history | 2024 | Q1 | 3150 | 21.8578 | 0.7499 | 8.0214 | 0.7876 |
| W2_modern_era | 2020 | B0 | 3195 | 24.9643 | 0.6559 | 10.3348 | 0.7599 |
| W2_modern_era | 2020 | B1 | 3195 | 26.5219 | 0.7137 | 10.4009 | 0.7933 |
| W2_modern_era | 2020 | Q1 | 3195 | 21.9031 | 0.7256 | 8.0855 | 0.7746 |
| W2_modern_era | 2021 | B0 | 3168 | 26.3266 | 0.6281 | 10.3327 | 0.7514 |
| W2_modern_era | 2021 | B1 | 3168 | 28.6855 | 0.6829 | 10.2606 | 0.7781 |
| W2_modern_era | 2021 | Q1 | 3168 | 22.9907 | 0.6992 | 8.4244 | 0.7418 |
| W2_modern_era | 2022 | B0 | 3024 | 24.4369 | 0.6719 | 9.4259 | 0.7694 |
| W2_modern_era | 2022 | B1 | 3024 | 27.5090 | 0.7018 | 9.7555 | 0.8110 |
| W2_modern_era | 2022 | Q1 | 3024 | 22.4864 | 0.7227 | 8.1382 | 0.7555 |
| W2_modern_era | 2023 | B0 | 3219 | 25.7299 | 0.6615 | 9.9975 | 0.7240 |
| W2_modern_era | 2023 | B1 | 3219 | 27.6779 | 0.7214 | 10.0218 | 0.7994 |
| W2_modern_era | 2023 | Q1 | 3219 | 22.2285 | 0.7308 | 8.2517 | 0.7856 |
| W2_modern_era | 2024 | B0 | 3150 | 25.6757 | 0.6766 | 9.9373 | 0.7545 |
| W2_modern_era | 2024 | B1 | 3150 | 27.5402 | 0.7192 | 9.9178 | 0.7854 |
| W2_modern_era | 2024 | Q1 | 3150 | 22.1728 | 0.7460 | 8.1723 | 0.7684 |

### By scoring preset

| Window | Scoring | Model | Rows | MAE | Spearman | Pinball |
|---|---|---|---|---|---|---|
| W1_all_history | HALF | B0 | 5252 | 25.5786 | 0.6609 | 9.9634 |
| W1_all_history | HALF | B1 | 5252 | 26.9507 | 0.7117 | 9.7352 |
| W1_all_history | HALF | Q1 | 5252 | 22.0293 | 0.7244 | 8.1080 |
| W1_all_history | PPR | B0 | 5252 | 28.3187 | 0.6618 | 10.9806 |
| W1_all_history | PPR | B1 | 5252 | 29.7622 | 0.7123 | 10.6780 |
| W1_all_history | PPR | Q1 | 5252 | 24.4030 | 0.7286 | 8.9699 |
| W1_all_history | STD | B0 | 5252 | 22.9076 | 0.6550 | 8.9885 |
| W1_all_history | STD | B1 | 5252 | 24.2229 | 0.7074 | 8.8122 |
| W1_all_history | STD | Q1 | 5252 | 19.7774 | 0.7239 | 7.3175 |
| W2_modern_era | HALF | B0 | 5252 | 25.4057 | 0.6602 | 10.0119 |
| W2_modern_era | HALF | B1 | 5252 | 27.5893 | 0.7079 | 10.0719 |
| W2_modern_era | HALF | Q1 | 5252 | 22.3476 | 0.7245 | 8.2133 |
| W2_modern_era | PPR | B0 | 5252 | 28.1357 | 0.6609 | 10.9772 |
| W2_modern_era | PPR | B1 | 5252 | 30.3784 | 0.7102 | 11.0231 |
| W2_modern_era | PPR | Q1 | 5252 | 24.6919 | 0.7263 | 9.0559 |
| W2_modern_era | STD | B0 | 5252 | 22.7387 | 0.6554 | 9.0277 |
| W2_modern_era | STD | B1 | 5252 | 24.7930 | 0.7053 | 9.1190 |
| W2_modern_era | STD | Q1 | 5252 | 20.0295 | 0.7239 | 7.3741 |

## The promotion gate

Criteria `phase3_promotion_v1`, frozen in `src/ffdraft/modeling/gate.py` and committed before the decisive comparison ran:

1. macro MAE improves and its paired 95% CI excludes zero
2. macro mean pinball loss improves and its paired 95% CI excludes zero
3. macro Spearman falls by no more than max_rank_regression
4. no position exceeds the MAE, Spearman or coverage tolerances

**B1 @ W1_all_history: FAIL**

- probabilistic quality: mean_pinball -0.2357 [-0.3951, -0.1007]
- ranking: spearman +0.0512 within tolerance
- **failed:** point accuracy: mae did not improve (delta +1.3769)
- **failed:** positional collapse: QB: MAE +7.7% worse than baseline; RB: MAE +3.1% worse than baseline; WR: MAE +7.0% worse than baseline

**Q1 @ W1_all_history: PASS**

- point accuracy: mae -3.5318 [-3.8669, -3.1801]
- probabilistic quality: mean_pinball -1.8457 [-1.9760, -1.7176]
- ranking: spearman +0.0664 within tolerance
- no positional collapse across 4 position(s)

**B1 @ W2_modern_era: FAIL**

- ranking: spearman +0.0490 within tolerance
- **failed:** point accuracy: mae did not improve (delta +2.1602)
- **failed:** probabilistic quality: mean_pinball did not improve (delta +0.0657)
- **failed:** positional collapse: QB: MAE +13.1% worse than baseline; RB: MAE +5.5% worse than baseline; TE: MAE +3.8% worse than baseline; WR: MAE +7.0% worse than baseline

**Q1 @ W2_modern_era: PASS**

- point accuracy: mae -3.0704 [-3.3725, -2.7684]
- probabilistic quality: mean_pinball -1.7912 [-1.9231, -1.6524]
- ranking: spearman +0.0661 within tolerance
- no positional collapse across 4 position(s)

## Folds

| Fold | Window | Train | Validate |
|---|---|---|---|
| W1_all_history:2014-2019->2020 | W1_all_history | [2014, 2015, 2016, 2017, 2018, 2019] | 2020 |
| W1_all_history:2014-2020->2021 | W1_all_history | [2014, 2015, 2016, 2017, 2018, 2019, 2020] | 2021 |
| W1_all_history:2014-2021->2022 | W1_all_history | [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021] | 2022 |
| W1_all_history:2014-2022->2023 | W1_all_history | [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022] | 2023 |
| W1_all_history:2014-2023->2024 | W1_all_history | [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023] | 2024 |
| W2_modern_era:2017-2019->2020 | W2_modern_era | [2017, 2018, 2019] | 2020 |
| W2_modern_era:2017-2020->2021 | W2_modern_era | [2017, 2018, 2019, 2020] | 2021 |
| W2_modern_era:2017-2021->2022 | W2_modern_era | [2017, 2018, 2019, 2020, 2021] | 2022 |
| W2_modern_era:2017-2022->2023 | W2_modern_era | [2017, 2018, 2019, 2020, 2021, 2022] | 2023 |
| W2_modern_era:2017-2023->2024 | W2_modern_era | [2017, 2018, 2019, 2020, 2021, 2022, 2023] | 2024 |

W1-only diagnostic folds (2017-2019) are in the JSON report. They are reported, never decisive: W2 cannot reproduce those validation seasons with three training seasons, so letting them influence the window choice would compare the windows on folds only one of them can run.

## Feature set

`intrinsic_core_v1` (`7203befaa5be25a2`), 78 inputs selected from the Phase-2 model-input set, 7 excluded:

| Feature | Reason | Evidence |
|---|---|---|
| depth_rank_at_anchor | snapshot_era_only | non-null on 0.0% of rows in every season 2014-2024 and 49.8% of 2025 (ADR-015: only the 2025+ depth charts are timestamped snapshots) |
| depth_rank_observed | era_indicator | constant false in every development season; true on 49.8% of 2025 |
| team_change_flag | snapshot_era_only | non-null on 0.0% of rows 2014-2024 and 36.9% of 2025; a pre-anchor team observation does not exist before the snapshot era |
| team_change_known | era_indicator | constant false in every development season; true on 36.9% of 2025 |
| team_at_anchor_known | era_distribution_shift | true on 7.1-11.7% of rows per development season against 50.6% of 2025; the shift is the data era, not a change in football |
| prev1_team_games | horizon_era_index | mean 15.0 in every target season through 2021 and 16.0 from 2022, i.e. the previous season's fantasy horizon (weeks 1-16 or 1-17) minus the bye, constant within a season apart from the cancelled 2022 game |
| draft_year | time_index | a calendar index whose training-fold range never covers the validation season's rookies; seasons_since_draft = season - draft_year carries the same information relative to the target season and is era-stable |

## Final holdout

Season 2025 is sealed (season >= 2025). Status after this run: **UNTOUCHED / NOT EVALUATED**. Unsealing requires `--final-eval --confirm-final-eval RELEASE-FINAL-HOLDOUT-2025`.

Predeclared slices for the eventual final evaluation, fixed before any candidate comparison and without inspecting 2025 outcomes:

| Slice | Kind | Definition |
|---|---|---|
| full_universe | primary | Every eligible 2025 player-season, all positions and scoring presets |
| era_stable_universe | diagnostic | 2025 rows whose eligibility is supported by the prior-season roster or the target-season draft class, i.e. discoverable under the pre-snapshot mechanism |
| rookie | diagnostic | Rows flagged as rookies by prior-existence evidence |
| veteran | diagnostic | Rows not flagged as rookies |
| depth_context_state | diagnostic | Grouped by ADR-018 depth context: observed, prior-season role, none |
| position | diagnostic | Grouped by QB/RB/WR/TE |
| scoring_preset | diagnostic | Grouped by STD/HALF/PPR |
| information_rich | diagnostic | Rows with a substantial prior-season workload: prior stats exist and the player appeared in at least eight games of the previous season |
| low_information | diagnostic | The complement of information_rich |

## Checks

- [ok] `phase3.final_holdout_withheld` — sealed seasons were removed before any model saw the frame
- [ok] `phase3.feature_era_stability` — all 78 core features have development-era coverage and variation
- [ok] `phase3.exclusion_evidence_holds` — depth_rank_at_anchor excluded as snapshot_era_only
- [ok] `phase3.exclusion_evidence_holds` — depth_rank_observed excluded as era_indicator
- [ok] `phase3.exclusion_evidence_holds` — team_change_flag excluded as snapshot_era_only
- [ok] `phase3.exclusion_evidence_holds` — team_change_known excluded as era_indicator
- [ok] `phase3.final_holdout_untouched` — no sealed season entered training, tuning or evaluation
- [ok] `phase3.promotion_gate` — at least one candidate passed the frozen promotion gate
