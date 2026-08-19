# Phase 4, stage B — the production predictive distribution

Study `phase4_distribution_v1`, rules `phase4_rules_v1`, seed `20260819`, code `4cd90af`, generated 2026-08-19T18:32:09Z.

## Conclusion

**`CB` is the production predictive distribution.**

- family: availability x performance hurdle
- calibration: `monotone_projection_v1`
- target scale: `season_total`
- macro MAE 21.9068
- macro mean pinball 8.0804
- macro Spearman 0.7502
- macro top-K recall 0.5771
- P10-P90 coverage 0.8271 at mean width 64.8
- P25-P75 coverage 0.6143
- quantile crossing: 0.0000 raw, 0.0000 after post-processing

The three decisions, each taken by a rule frozen in ADR-030 before its evidence existed and applied in the declared order:

**Calibration** (`phase4_calibration_v1`) selected `A0` — not decisive; the incumbent stands.

> A0 stands: P25-P75 coverage gap widened by +0.0189, beyond the 0.010 tolerance

**Horizon sensitivity** (`phase4_horizon_v1`) selected `A0` — not decisive; the incumbent stands.

> A0 retained: mae +0.1420 [+0.0458, +0.2366]; mean_pinball -0.0188 [-0.0427, +0.0063]; 2021 MAE +0.79%, worst other fold +1.41%

**Candidate A vs B** (`phase4_candidate_v1`) selected `CB` — decisive.

> probabilistic quality: mean_pinball -0.0614 [-0.1002, -0.0236]
> secondary improvement: MAE mae -0.2052 [-0.3322, -0.0733]; Spearman +0.0298; top-K recall +0.0326

## Aggregate performance

Macro means over validation season x position x scoring cells, development folds 2020-2024, window `W1_all_history`.

| Model | Cells | Rows | MAE | Spearman | Top-K | Pinball | P10-P90 cov | P25-P75 cov | P10-P90 width | Raw crossing |
|---|---|---|---|---|---|---|---|---|---|---|
| A0 | 60 | 15756 | 22.1120 | 0.7203 | 0.5444 | 8.1418 | 0.7379 | 0.4771 | 62.4587 | 0.3873 |
| A1 | 60 | 15756 | 22.1199 | 0.7197 | 0.5444 | 8.1326 | 0.8260 | 0.5418 | 70.9838 | 0.3873 |
| AH | 60 | 15756 | 22.2540 | 0.7185 | 0.5597 | 8.1230 | 0.7442 | 0.4814 | 64.6096 | 0.3814 |
| B0 | 60 | 15756 | 25.6016 | 0.6592 | 0.5354 | 9.9775 | 0.7927 | 0.5284 | 83.1079 | 0.0000 |
| CB | 60 | 15756 | 21.9068 | 0.7502 | 0.5771 | 8.0804 | 0.8271 | 0.6143 | 64.8295 | 0.0000 |
| Q1 | 60 | 15756 | 22.0699 | 0.7256 | 0.5444 | 8.1318 | 0.7712 | 0.5132 | 62.6765 | 0.3873 |

Post-processing crossing rate by model:

| Model | Post crossing |
|---|---|
| A0 | 0.0000 |
| A1 | 0.0000 |
| AH | 0.0000 |
| B0 | 0.0000 |
| CB | 0.0000 |
| Q1 | 0.0000 |

## Paired deltas

- `AH_vs_A0` **mae** +0.1420 (95% CI +0.0458 to +0.2366, excludes zero)
- `AH_vs_A0` **mean_pinball** -0.0188 (95% CI -0.0427 to +0.0063, includes zero)
- `AH_vs_A0` **spearman** -0.0019 (95% CI -0.0048 to +0.0010, includes zero)
- `AH_vs_A0` **top_k_recall** +0.0153 (95% CI -0.0049 to +0.0153, includes zero)
- `CB_vs_A0` **mae** -0.2052 (95% CI -0.3322 to -0.0733, excludes zero)
- `CB_vs_A0` **mean_pinball** -0.0614 (95% CI -0.1002 to -0.0236, excludes zero)
- `CB_vs_A0` **spearman** +0.0298 (95% CI +0.0262 to +0.0345, excludes zero)
- `CB_vs_A0` **top_k_recall** +0.0326 (95% CI +0.0007 to +0.0354, excludes zero)
- `CB_vs_B0` **mae** -3.6948 (95% CI -4.0171 to -3.3843, excludes zero)
- `CB_vs_B0` **mean_pinball** -1.8971 (95% CI -2.0277 to -1.7764, excludes zero)
- `CB_vs_B0` **spearman** +0.0909 (95% CI +0.0829 to +0.0993, excludes zero)
- `CB_vs_B0` **top_k_recall** +0.0417 (95% CI +0.0174 to +0.0660, excludes zero)
- `Q1_vs_B0` **mae** -3.5318 (95% CI -3.8669 to -3.1801, excludes zero)
- `Q1_vs_B0` **mean_pinball** -1.8457 (95% CI -1.9760 to -1.7176, excludes zero)
- `Q1_vs_B0` **spearman** +0.0664 (95% CI +0.0575 to +0.0746, excludes zero)
- `Q1_vs_B0` **top_k_recall** +0.0090 (95% CI +0.0007 to +0.0500, excludes zero)

Paired block bootstrap, 1000 replicates, seed 20260819, resampling player-seasons within validation season x position x scoring blocks and carrying both variants' predictions for the same rows through the same resample.

## By position

| Position | Model | Rows | MAE | Spearman | Top-K | Pinball | P10-P90 cov | P25-P75 cov |
|---|---|---|---|---|---|---|---|---|
| QB | A0 | 2058 | 34.5927 | 0.6650 | 0.5000 | 13.0931 | 0.7083 | 0.4426 |
| QB | A1 | 2058 | 34.6047 | 0.6637 | 0.5000 | 13.0397 | 0.8063 | 0.5184 |
| QB | AH | 2058 | 34.9889 | 0.6631 | 0.5333 | 13.0842 | 0.7200 | 0.4478 |
| QB | B0 | 2058 | 39.4950 | 0.6422 | 0.5333 | 16.4625 | 0.7554 | 0.4685 |
| QB | CB | 2058 | 34.3088 | 0.7027 | 0.5500 | 13.0744 | 0.7856 | 0.5819 |
| QB | Q1 | 2058 | 34.4976 | 0.6697 | 0.5000 | 13.0751 | 0.7344 | 0.4643 |
| RB | A0 | 3849 | 23.1286 | 0.7366 | 0.5889 | 8.4070 | 0.7339 | 0.4696 |
| RB | A1 | 3849 | 23.1433 | 0.7351 | 0.5889 | 8.4239 | 0.8257 | 0.5271 |
| RB | AH | 3849 | 23.0912 | 0.7368 | 0.6056 | 8.3692 | 0.7247 | 0.4682 |
| RB | B0 | 3849 | 27.3826 | 0.6405 | 0.5528 | 9.8404 | 0.7856 | 0.4686 |
| RB | CB | 3849 | 22.8195 | 0.7545 | 0.6333 | 8.3222 | 0.8378 | 0.6050 |
| RB | Q1 | 3849 | 23.1034 | 0.7424 | 0.5889 | 8.3991 | 0.7624 | 0.5048 |
| TE | A0 | 3366 | 13.0222 | 0.7374 | 0.5056 | 4.6516 | 0.7243 | 0.4737 |
| TE | A1 | 3366 | 13.0277 | 0.7374 | 0.5056 | 4.6516 | 0.8280 | 0.5525 |
| TE | AH | 3366 | 13.1505 | 0.7359 | 0.5111 | 4.6335 | 0.7378 | 0.4807 |
| TE | B0 | 3366 | 14.7954 | 0.6652 | 0.5111 | 5.7615 | 0.7975 | 0.5797 |
| TE | CB | 3366 | 12.7888 | 0.7716 | 0.5278 | 4.5491 | 0.8276 | 0.5994 |
| TE | Q1 | 3366 | 12.9996 | 0.7419 | 0.5056 | 4.6443 | 0.7689 | 0.5029 |
| WR | A0 | 6483 | 17.7044 | 0.7424 | 0.5833 | 6.4155 | 0.7852 | 0.5226 |
| WR | A1 | 6483 | 17.7039 | 0.7426 | 0.5833 | 6.4150 | 0.8440 | 0.5691 |
| WR | AH | 6483 | 17.7855 | 0.7380 | 0.5889 | 6.4051 | 0.7945 | 0.5290 |
| WR | B0 | 6483 | 20.7337 | 0.6891 | 0.5444 | 7.8455 | 0.8322 | 0.5967 |
| WR | CB | 6483 | 17.7101 | 0.7719 | 0.5972 | 6.3761 | 0.8575 | 0.6709 |
| WR | Q1 | 6483 | 17.6790 | 0.7484 | 0.5833 | 6.4087 | 0.8190 | 0.5807 |

## By validation season

| Season | Model | Rows | MAE | Spearman | Pinball | P10-P90 cov |
|---|---|---|---|---|---|---|
| 2020 | A0 | 3195 | 21.0313 | 0.7325 | 7.8198 | 0.7220 |
| 2020 | A1 | 3195 | 21.0547 | 0.7309 | 7.8133 | 0.8484 |
| 2020 | AH | 3195 | 21.0313 | 0.7325 | 7.8198 | 0.7220 |
| 2020 | B0 | 3195 | 24.7421 | 0.6717 | 9.6788 | 0.8220 |
| 2020 | CB | 3195 | 20.9119 | 0.7584 | 7.8528 | 0.8368 |
| 2020 | Q1 | 3195 | 20.9917 | 0.7391 | 7.8069 | 0.7722 |
| 2021 | A0 | 3168 | 22.9954 | 0.6858 | 8.4223 | 0.7255 |
| 2021 | A1 | 3168 | 22.9984 | 0.6854 | 8.4185 | 0.8099 |
| 2021 | AH | 3168 | 23.1780 | 0.6858 | 8.4227 | 0.7355 |
| 2021 | B0 | 3168 | 26.6052 | 0.6231 | 10.4708 | 0.8207 |
| 2021 | CB | 3168 | 22.9100 | 0.7237 | 8.4800 | 0.8176 |
| 2021 | Q1 | 3168 | 22.9676 | 0.6894 | 8.4121 | 0.7480 |
| 2022 | A0 | 3024 | 22.4994 | 0.7114 | 8.2068 | 0.7421 |
| 2022 | A1 | 3024 | 22.4978 | 0.7112 | 8.1774 | 0.8161 |
| 2022 | AH | 3024 | 22.8167 | 0.7046 | 8.1986 | 0.7346 |
| 2022 | B0 | 3024 | 24.7274 | 0.6692 | 9.6206 | 0.7834 |
| 2022 | CB | 3024 | 22.0424 | 0.7380 | 8.0046 | 0.8095 |
| 2022 | Q1 | 3024 | 22.4620 | 0.7150 | 8.1982 | 0.7644 |
| 2023 | A0 | 3219 | 22.1175 | 0.7278 | 8.2284 | 0.7520 |
| 2023 | A1 | 3219 | 22.1233 | 0.7273 | 8.2237 | 0.8301 |
| 2023 | AH | 3219 | 22.2989 | 0.7253 | 8.2279 | 0.7704 |
| 2023 | B0 | 3219 | 25.8657 | 0.6608 | 10.0033 | 0.7865 |
| 2023 | CB | 3219 | 21.9230 | 0.7548 | 8.1242 | 0.8390 |
| 2023 | Q1 | 3219 | 22.0704 | 0.7347 | 8.2203 | 0.7838 |
| 2024 | A0 | 3150 | 21.9164 | 0.7441 | 8.0317 | 0.7480 |
| 2024 | A1 | 3150 | 21.9254 | 0.7437 | 8.0299 | 0.8254 |
| 2024 | AH | 3150 | 21.9452 | 0.7440 | 7.9461 | 0.7586 |
| 2024 | B0 | 3150 | 26.0678 | 0.6712 | 10.1139 | 0.7507 |
| 2024 | CB | 3150 | 21.7468 | 0.7758 | 7.9405 | 0.8328 |
| 2024 | Q1 | 3150 | 21.8578 | 0.7499 | 8.0214 | 0.7876 |

## By scoring preset

| Scoring | Model | Rows | MAE | Spearman | Pinball |
|---|---|---|---|---|---|
| HALF | A0 | 5252 | 22.0674 | 0.7200 | 8.1177 |
| HALF | A1 | 5252 | 22.0751 | 0.7198 | 8.1096 |
| HALF | AH | 5252 | 22.1210 | 0.7196 | 8.0833 |
| HALF | B0 | 5252 | 25.5786 | 0.6609 | 9.9634 |
| HALF | CB | 5252 | 21.8505 | 0.7510 | 8.0656 |
| HALF | Q1 | 5252 | 22.0293 | 0.7244 | 8.1080 |
| PPR | A0 | 5252 | 24.4484 | 0.7235 | 8.9807 |
| PPR | A1 | 5252 | 24.4563 | 0.7229 | 8.9745 |
| PPR | AH | 5252 | 24.7087 | 0.7201 | 8.9736 |
| PPR | B0 | 5252 | 28.3187 | 0.6618 | 10.9806 |
| PPR | CB | 5252 | 24.2036 | 0.7502 | 8.8893 |
| PPR | Q1 | 5252 | 24.4030 | 0.7286 | 8.9699 |
| STD | A0 | 5252 | 19.8201 | 0.7175 | 7.3270 |
| STD | A1 | 5252 | 19.8284 | 0.7164 | 7.3136 |
| STD | AH | 5252 | 19.9324 | 0.7157 | 7.3121 |
| STD | B0 | 5252 | 22.9076 | 0.6550 | 8.9885 |
| STD | CB | 5252 | 19.6664 | 0.7493 | 7.2863 |
| STD | Q1 | 5252 | 19.7774 | 0.7239 | 7.3175 |

## Checks

- [ok] `phase3.final_holdout_withheld` — sealed seasons were removed before any model saw the frame
- [ok] `phase4.calibration_rule` — phase4_calibration_v1 selected A0
- [ok] `phase4.horizon_rule` — phase4_horizon_v1 selected A0
- [ok] `phase4.candidate_rule` — phase4_candidate_v1 selected CB
- [warning] `phase4.selected_distribution_calibration_diagnostic` — the promoted distribution is outside a calibration band the phase4_calibration_v1 rule applies when choosing between calibration variants; reported as a limitation, not applied as a gate
- [ok] `phase4.production_quantiles_monotonic` — the selected distribution never produces crossing quantiles

Season 2025 is sealed and was not touched: the modelling frame drops it at load time, and every fold above validates a development season.
