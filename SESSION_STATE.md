# Session State

This file is durable cross-session state for coding agents. Keep it concise and factual.

## Current phase

Phase 4 — **implemented, exit gate partially met** (2026-08-19). Every task is built and measured; two frozen gates were measured as failing and are published rather than repaired. Phase 5 (market snapshots and arbitrage) has not been started.

## Current target gate

Phase 5 exit gate: point-in-time market snapshots retained append-only, a fair-rank-vs-ADP arbitrage baseline that stays a permanent challenger, and — only if the historical market coverage and out-of-time promotion gate pass — a learned arbitrage model whose target is realized value relative to market cost.

Two Phase-4 criteria remain open and are **not** Phase-5 work to quietly absorb: the Monte Carlo convergence rule needs a revision that measures its tier clause on the promoted configuration (ADR-034), and tier boundary stability needs either a re-specified admissibility rule or a boundary-confidence presentation (ADR-035). Both are new decisions with their own gates.

## Last validated commit

The Phase-4 branch `claude/ffdraft-phase-4-w96nvs`, branched from the merged Phase-3 state on `main` (`4e2fb4b`).

**The freeze checkpoint is `2f0e725`.** Every Phase-4 model, calibration, ranking, simulation and tier decision is fixed in that commit, and the sealed 2025 holdout was evaluated only afterwards. A future session auditing whether a decision could have seen the holdout should check whether it predates that SHA.

Validation run locally; every network-free command below also runs in CI (`.github/workflows/ci.yml`):

```
uv sync --frozen
uv run ruff check .                 # clean
uv run ruff format --check .        # clean, 134 files
uv run mypy                         # clean, 89 source files, strict
uv run pytest                       # 830 passed, 4 live deselected, 544s
uv run ffdraft config-check
uv run ffdraft build-fixture-artifacts --out web/public/data
uv run python -m ffdraft.cli validate-artifacts web/public/data   # gate: pass

# Phase-2, network-bound (nflverse only)
uv run ffdraft build-historical --last-season 2025 --git-sha c2b48cc
#   -> 11,604 feature rows, 34,812 fantasy labels, 104,436 VORP labels
#   -> quality gate: pass (0 critical, 2 warning), 187 checks
uv run ffdraft validate-historical data/historical   # gate: pass (0 critical, 0 warning)

# Phase-3, offline
uv run ffdraft evaluate-intrinsic --git-sha 5550ba8
#   -> 31,503 modelling rows, 2014-2024; 3,309 sealed 2025 rows withheld at load
#   -> feature set intrinsic_core_v1 (7203befaa5be25a2), 78 inputs, 7 excluded
#   -> 612.5s; window W1_all_history; promoted Q1
#   -> quality gate: pass (0 critical, 0 warning)
#   -> re-run at Phase 4 and diffed against the committed report: IDENTICAL on every
#      number, every decision and every check. Only the timestamped experiment_id differs.

# Phase-4 development studies, offline (data/phase4/ intermediates are gitignored)
uv run ffdraft evaluate-distribution --git-sha 4cd90af    # ~40 min; promoted CB
uv run ffdraft evaluate-simulation   --git-sha 3ba6cb0    # 3325s; 10000 draws, median_vorp
#   -> quality gate: FAIL (1 critical) — no draw count met every convergence tolerance
uv run ffdraft evaluate-tiers        --git-sha 3ba6cb0    # 6903s; dp_quantile @ penalty 1.0
#   -> quality gate: FAIL (1 critical, 1 warning) — stability gate, and PELT escalation

# Phase-4 sealed holdout — RUN ONCE, at the freeze checkpoint, and now spent
uv run ffdraft evaluate-intrinsic --final-eval \
  --confirm-final-eval RELEASE-FINAL-HOLDOUT-2025 --final-eval-reason "<why>" \
  --window W1_all_history --out docs/experiments/phase4-final-holdout --git-sha 2f0e725
#   -> PASS. CB vs B0 on 3,309 rows: MAE -3.738 [-4.364, -3.102],
#      pinball -2.134 [-2.377, -1.874], Spearman +0.1015, zero quantile crossings
#   -> quality gate: pass (0 critical, 1 warning: "final holdout consumed")

# Phase-4 production, network-bound (nflverse + Sleeper for current status)
uv run ffdraft train-production --allow-unsealed \
  --confirm-final-eval RELEASE-FINAL-HOLDOUT-2025 --final-eval-reason "<why>" --git-sha 2f0e725
#   -> intrinsic-cb-hurdle-v1 on 34,812 rows, seasons 2014-2025; 12 groups, 78 features
#   -> 121 files, ~15 MB gzipped, one SHA-256 per booster
uv run ffdraft build-current --git-sha 2f0e725
#   -> 2026 board; 3,510 projections, 2,700 tier records; cutoff = build time (pre-anchor)
#   -> quality gate: pass (0 critical, 1 warning: tiers published under a failed gate)
uv run python -m ffdraft.cli validate-artifacts web/public/data   # gate: pass
uv run ffdraft model-card --git-sha 2f0e725

npm ci
npm run lint                        # clean
npm run typecheck                   # clean
npm run test -- --run               # 31 passed
npm run build                       # clean; also verified with VITE_BASE_PATH=/jeisey-tiers/
```

The Phase-1 golden artifacts were **not** regenerated: Phases 2 and 3 changed no public serialization contract, and a rebuild produces byte-identical files.

## Production status

**A production model exists.** `intrinsic-cb-hurdle-v1`, trained on 2014-2025, promoted through a sealed single-use holdout, serving a 2026 board for every launch preset. There is still no arbitrage board and no deployed site.

- `models/production/intrinsic-cb-hurdle-v1/` — **committed**, not gitignored (`PRD.md` section 15). 120 gzipped LightGBM boosters plus `metadata.json` carrying the spec, seed, training seasons, library versions, dataset manifest, `feature_set_hash` `7203befaa5be25a2`, `feature_schema_hash` `c495ba3177dcb989` and a SHA-256 per booster. No pickles anywhere: loading reads JSON and LightGBM's documented text format, and a tampered booster fails closed.
- `models/cards/` — the model card and the tier-method report, generated from the committed experiment reports and the artifact, never hand-written.
- `web/public/data/` — the 2026 build. Gitignored and reproducible.

The fixture stub `fixture-stub-0` is gone from the production path.

What was there before and still is:

- `src/ffdraft/` — config, contracts, sources, identity, quality, artifacts, pipeline, CLI (Phase 1) plus `anchors.py`, `scoring/`, `features/`, `labels/`, `simulation/`, `leakage.py` (Phase 2) plus `modeling/` (Phase 3).
- `data/historical/` — the modelling dataset. Gitignored and reproducible; see "Phase-2 dataset" below.
- `docs/FEATURE_DICTIONARY.md` — every model feature with formula, sources and availability rule, generated from code and pinned by a test.
- `docs/experiments/phase3-intrinsic-baselines/` — the committed Phase-3 experiment reports, machine-readable and human-readable. Row-level predictions are gitignored.
- `.github/workflows/ci.yml` — Python and frontend gates, fixture-only, no vendor network.
- `web/` — Vite/React/TypeScript skeleton with a typed artifact loader.
- `tests/` — 830 network-free Python tests (4 live-network deselected), including the Phase-3/4 suites in `tests/model/`; `web/tests/` adds 31.
- `docs/experiments/` — four committed experiment report pairs: the Phase-3 baselines and the three Phase-4 studies, plus the single final-holdout report. Row-level predictions are gitignored.

## Phase-2 dataset — the validated build

Target seasons **2014-2025**, positions QB/RB/WR/TE. Source windows: statistics 2009-2025 (the deepest declared lookback is five seasons), rosters 2013-2024 (always the *previous* season), depth charts 2025 only (the one target season with timestamped snapshots).

| Season | Rows | Rookies | Observed depth | Role proxy | No depth | Zero-point share (PPR) |
|---:|---:|---:|---:|---:|---:|---:|
| 2014 | 672 | 75 | 0 | 538 | 134 | 34.7% |
| 2015 | 667 | 78 | 0 | 537 | 130 | 33.1% |
| 2016 | 684 | 77 | 0 | 543 | 141 | 36.0% |
| 2017 | 1056 | 83 | 0 | 562 | 494 | 53.4% |
| 2018 | 1078 | 83 | 0 | 566 | 512 | 54.1% |
| 2019 | 1092 | 80 | 0 | 583 | 509 | 54.6% |
| 2020 | 1065 | 77 | 0 | 586 | 479 | 50.2% |
| 2021 | 1056 | 75 | 0 | 626 | 430 | 46.9% |
| 2022 | 1008 | 79 | 0 | 671 | 337 | 47.2% |
| 2023 | 1073 | 80 | 0 | 625 | 448 | 53.2% |
| 2024 | 1050 | 77 | 0 | 617 | 433 | 51.7% |
| 2025 | 1103 | 106 | 549 | 197 | 357 | 51.7% |

Quality metrics over the whole dataset: canonical key coverage 1.0, duplicate `(season, player_id)` keys 0, `age_at_anchor` coverage 0.967, snap-count `pfr_id` bridge coverage 0.977, ffopportunity coverage 0.954, label coverage 1.0 for every scoring and league preset. Excluded candidates: 25,476 non-core positions, 15 with no anchor-safe position, 12 with no canonical id, 1 ambiguous identity.

Anchors (all rule `draft_anchor_v1_tuesday_eod_pre_week1`, lead time 1.85 days in every season): 2014-09-03T03:59:59Z through 2025-09-03T03:59:59Z.

## Phase-3 results — the frozen evaluation

Development folds 2020-2024 (plus W1-only diagnostics 2017-2019), 468 evaluation cells, seed 20260819, 1000 bootstrap replicates. Season **2025 is sealed and was not evaluated**.

Macro aggregates over season x position x scoring, window `W1_all_history`:

| Model | MAE | RMSE | Spearman | Kendall | Top-K | Pinball | P10-P90 cov | P10-P90 width | Raw crossing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 25.60 | 44.06 | 0.659 | 0.524 | 0.535 | 9.98 | 0.793 | 83.1 | 0.000 |
| B1 | 26.98 | 42.21 | 0.711 | 0.550 | 0.593 | 9.74 | 0.798 | 80.4 | 0.000 |
| **Q1** | **22.07** | **41.03** | **0.726** | **0.570** | 0.544 | **8.13** | 0.771 | 62.7 | 0.387 |

Paired deltas against B0 under W1: MAE **-3.53** (95% CI -3.87 to -3.18), mean pinball **-1.85** (-1.98 to -1.72), Spearman **+0.066** (+0.058 to +0.075). Q1 passes the frozen gate under **both** windows; B1 fails under both, losing to B0 on MAE at every position.

Per position under W1 (B0 -> Q1): QB 39.50 -> 34.50 MAE, RB 27.38 -> 23.10, TE 14.80 -> 13.00, WR 20.73 -> 17.68; Spearman 0.642 -> 0.670, 0.641 -> 0.742, 0.665 -> 0.742, 0.689 -> 0.748. No position triggers the collapse rule. Per scoring preset the ordering is identical (PPR is the hardest: Q1 MAE 24.40 against STD's 19.78, which is scale, not skill).

Training window (ADR-028): W1 beats W2 on the common folds with Q1 by MAE **-0.286** (-0.474 to -0.107) and pinball **-0.083** (-0.134 to -0.037), Spearman indistinguishable. Per fold the MAE advantage is -0.911 (2020), -0.023 (2021), -0.024 (2022), -0.158 (2023), -0.315 (2024) - concentrated in the fold where W2 has only three training seasons, which is the honest reading of *why* W1 wins.

Selected for Phase 4 (ADR-029): **Q1**, window **W1**, feature set `intrinsic_core_v1` (`7203befaa5be25a2`), 78 inputs.

## Phase-4 results — the frozen production system

Development folds 2020-2024, seed 20260819, 1000 bootstrap replicates. Every decision below was made by a rule written into `ffdraft.modeling.rules` **before** the run that decided it, and the whole set was committed at `2f0e725` before 2025 was opened.

| Decision | Rule | Outcome |
|---|---|---|
| calibration | `phase4_calibration_v1` | monotone (PAV) projection only; the fitted conformal layer was measured and refused |
| target scale | `phase4_horizon_v1` | season total; horizon normalization refused on both declared routes |
| architecture | `phase4_candidate_v1` | **CB**, availability x performance hurdle |
| draw count | `phase4_convergence_v1` | 10,000 — **by the fallback clause; no count passed** |
| fair rank | `phase4_ranking_v1` | median simulated VORP; expected VORP refused |
| tier penalty | `phase4_tier_v1` | 1.0, the only admissible penalty in the grid |
| tier stability | `phase4_tier_stability_v1` | **FAIL** on boundary agreement, after escalating from PELT to dp_quantile |
| final holdout | `phase4_final_holdout_v1` | **PASS** |

**Development macro aggregates (CB vs the A0 direct-quantile candidate):** MAE 21.91 vs 22.11, pinball 8.080 vs 8.142, Spearman 0.750, top-K 0.577, P10-P90 coverage 0.827, raw crossing rate **0.000** (against Q1's 0.387). Paired deltas: pinball -0.0614 [-0.1002, -0.0236], MAE -0.205 [-0.332, -0.073], Spearman +0.0298, top-K +0.0326.

**Final holdout, 2025, run once (ADR-036):** CB MAE 20.19 vs B0 23.93; pinball 7.197 vs 9.331; Spearman 0.780 vs 0.679; P10-P90 coverage 0.845 against nominal 0.80; width 56.9 vs 80.7. Paired: MAE **-3.738** [-4.364, -3.102], pinball **-2.134** [-2.377, -1.874], Spearman **+0.1015**. CB improves MAE and pinball on **all eleven** predeclared slices; rookies go 34.29 -> 29.83 MAE with coverage 0.675 -> 0.747.

**The two failures, in the units that matter.**

- *Convergence.* Ranking tolerances pass comfortably (fair-rank Spearman 0.99993 between seeds, top-50 overlap 0.96+); value tolerances miss by 10-20% (mean |Δ expected VORP| 0.29-0.31 against 0.25); the tier clause misses badly (ARI 0.50-0.75 against 0.90). More draws would close the value gap; they would not close the tier gap, because a boundary is a discrete cut on a nearly continuous curve.
- *Tier stability.* Boundary agreement 0.239 against 0.500. Everything else passes: ARI 0.865, singleton rate 0.040, tier-count CV 0.045, monotonic pairs 0.845, cross-preset ARI 0.529. Across 1,200 replicates the segmentation used 283 of 299 cut sites and only 4 survived in a majority (ranks 267, 99, 16, 68). The median promoted boundary sits on a 0.55-point P50 cliff against an 80-130 point interval, and P(player below outscores player above) is 0.497.

**The 2026 board looks right.** PPR/redraft-12 top eight: Bijan Robinson, Amon-Ra St. Brown, Ja'Marr Chase, Jahmyr Gibbs, De'Von Achane, Puka Nacua, Jaxon Smith-Njigba, CeeDee Lamb. Top 12 is 6 RB and 6 WR; the first QB is 15th (Josh Allen) and the first TE 19th (Trey McBride), which is the correct shape for a 1-QB league where those positions' VORP is compressed. Tier sizes 8/14/25/33/29/42/45/69/35. 34 rookies make the 300-deep board, the best at rank 72. Zero quantile-monotonicity violations, zero non-finite values.

## Confirmed decisions

- Static GitHub Pages runtime.
- Python modeling/data + React/TypeScript/Vite frontend.
- Intrinsic model cannot use market/expert rank features.
- Arbitrage may use market data; historical intrinsic inputs must be OOF.
- Phase-gated implementation.
- **Arbitrage V1 ships in deterministic baseline mode** — historical ADP is dense but not point-in-time (ADR-010).
- **Current player status comes from nflverse rosters/depth charts plus Sleeper**, never `load_injuries` (ADR-011).
- **Market cohorts are approximate and must be labelled**; cohort mix is re-measured at the start of Phase 5 (ADR-012, amended 2026-08-18).
- **FantasyCalc disabled** (ADR-013). **FantasyPros-derived ECR is `benchmark_only`** — internal comparison allowed, redistribution and DraftValue use forbidden (ADR-014, amended 2026-08-18).
- **Depth charts have two upstream schemas**; pre-2025 seasons have no draft-time depth observation (ADR-015).
- **Repository stays private through Phase 6**; visibility is a required Phase-7 decision (ADR-016).
- **MFL developer client provisioned**; the adapter reads env-variable names and never touches credentials on the unauthenticated ADP path (ADR-017).
- **Historical anchor depth**: point-in-time for 2025+, prior-season role proxy before that, explicit missingness for rookies (ADR-018).
- **Canonical identity**: namespaced ids, two independent market bridges, fail closed on any ambiguity (ADR-019).
- **Public artifacts use the bundled Shape A** with a shared envelope (ADR-020).
- **Draft anchor is 23:59:59 America/New_York on the Tuesday before the earliest Week-1 kickoff**, versioned `draft_anchor_v1_tuesday_eod_pre_week1` (ADR-021). It may not be re-tuned after seeing model performance.
- **The preseason universe is built only from pre-anchor evidence** — previous-season roster, target-season draft class, pre-anchor depth snapshot. Week-1 rosters are refused (ADR-022).
- **The historical dataset is Parquet at three normalized grains, outside version control**, reproducible with a manifest of content hashes (ADR-023).
- **Phase-3 modelling dependencies are LightGBM and NumPy only**; ridge, every metric and the bootstrap are written in-house, SciPy is a test-only cross-check (ADR-024).
- **Season 2025 is the sealed final holdout**, with primary and diagnostic slices predeclared before any comparison (ADR-025).
- **The Phase-3 core feature set is `intrinsic_core_v1`**, 78 of the 85 Phase-2 model inputs; snapshot-era-only columns, era indicators, the horizon index and the calendar index are excluded with recorded evidence (ADR-026).
- **The promotion and window-selection rules were frozen in code before the decisive comparison** (ADR-027).
- **The training window is W1, the full 2014+ expanding history** (ADR-028).
- **Q1, the direct-total LightGBM quantile model, advances to Phase 4** (ADR-029).
- **The Phase-4 decision rules were frozen in code before their results existed** (ADR-030).
- **Quantile monotonicity is an isotonic projection, not a sort**; the fitted calibration layer was measured and not adopted (ADR-031).
- **Horizon normalization was measured and rejected** on both declared routes; no calendar-year feature was added (ADR-032).
- **Candidate B, the availability x performance hurdle, is the production intrinsic model** (ADR-033).
- **Median simulated VORP is the fair rank**; the draw count is the convergence rule's predeclared fallback, and that rule's tier clause is stricter than the tier gate it protects (ADR-034).
- **Tiers come from the dynamic-programming alternative at penalty 1.0, and the stability gate fails** on boundary agreement; they ship with the failure attached (ADR-035).
- **The sealed 2025 holdout was evaluated once, at `2f0e725`, and passed** (ADR-036). It is spent.
- **`intrinsic-cb-hurdle-v1` is the production artifact**, trained through 2025, committed, digest-verified; a 2026 build uses `min(as_of, anchor)` and never loads target-season statistics (ADR-037).
- Source verification runs on a GitHub runner, not in an egress-restricted sandbox (ADR-009).

## Verified source facts a later phase should not re-derive

Full Phase-0 detail in `docs/DATA_SOURCES.md` section 13; Phase-2 additions in section 14. The load-bearing ones:

- Market ADP: `https://api.myfantasyleague.com/{season}/export?TYPE=adp&JSON=1`, no auth, **no standard-deviation field**, `DAYS` ignored, response `timestamp` is generation time not data-as-of.
- Market → canonical identity works by id alone: 100% of priced QB/RB/WR/TE, two independent bridges, zero disagreements.
- Sleeper `gsis_id` coverage is only 31.9%, so join **nflverse → Sleeper on `sleeper_id`**, never the reverse.
- `nflreadpy.get_current_season()` returns the *prior* season in August; take the draft-target season from config.
- **Snap counts start at 2013** — `load_snap_counts(2012)` returns an empty file. That is why 2014 is the first target season.
- **nflverse roster coverage steps up at 2016** (2,190 rows in 2015 → 3,061 in 2016), which is why 2014-2016 carry ~670 eligible rows against ~1,050 afterwards.
- **The 2016 roster leaves `years_exp` null on 510 rows.** Treating that as zero experience would misclassify 247 established players as 2017 rookies.
- **A seasonal roster's grain is `(season, gsis_id, team)`** — a traded player appears once per club.
- **`load_players` keys ~24% of its rows by an ESB id, not GSIS**, and misses ~70 skill players a season; birth dates fall back to season rosters.
- **ffopportunity can emit one row per position per player-week**; the largest attribution wins rather than summing.
- **nflverse `fantasy_points` includes six points per return touchdown**, which this project's presets do not define. That is the entire difference between the two, proven by reconciliation rather than assumed.

## Phase-1 facts a later phase should not re-derive

- **Adapters split into a pure `normalize` and an I/O `fetch`.** Every fixture test drives `normalize`; only opt-in live tests touch `fetch`.
- **Each adapter declares `required_source_columns` and `recorded_schema_fixture`**, checked against a recorded schema. Add both to any new adapter.
- **Column order in CSV comes from the JSON Schema**, not from Python.
- **Artifacts are byte-reproducible** for identical inputs.
- **`QualityCheck` records rather than exceptions.** A build collects every finding, then the gate decides once.
- **Ambiguity severity is contextual** — producing an ambiguous outcome is the resolver working; publishing one is critical.
- **`FIXTURE_IDENTITY_COVERAGE_MINIMUM` (0.80) is a local relaxation for the adversarial 16-player fixture**; production stays at 0.95.

## Phase-2 facts a later phase should not re-derive

- **The anchor is the spine.** Every feature row carries `anchor_at_utc` and `feature_cutoff_rule_version`, and every leakage argument is written against them. Do not compute a new anchor anywhere else.
- **Leakage rules 1 and 6 are proved by construction, not inspection.** `audit_target_season_independence` rebuilds each season with its own statistics deleted and compares content hashes. It roughly triples build time and is on by default; `--skip-independence-check` exists for iteration only.
- **The feature dictionary is code.** `HISTORICAL_FEATURE_CONTRACT` is generated from it, `docs/FEATURE_DICTIONARY.md` is rendered from it, and tests pin both. Add a column by adding a `FeatureSpec`, never by editing a contract or the Markdown.
- **`prev1_fantasy_points_std` and `_ppr` are the only scoring-flavoured features**, and half-PPR is exactly their mean. Do not add a third.
- **Lagged aggregates use the fantasy horizon**, the same one the label uses, so a prior-production baseline compares like with like.
- **Efficiency ratios are null below a declared minimum denominator** (20 carries, 20 targets, 100 pass attempts) with a paired `*_denominator_met` indicator. Do not impute them.
- **`ffdraft.simulation.allocation` is shared with Phase 4.** Feed it sampled points rather than writing a second replacement algorithm.
- **`HistoricalThresholds.fixture()` exists because production coverage thresholds are meaningless on a thirty-row fixture.** The structural thresholds do not relax, and a test asserts the fixture profile is strictly looser only on the statistical ones.
- **Two feature families were deliberately deferred with reasons**: vacated-opportunity (needs pre-anchor roster knowledge, so it would exist for one labelled season and be era-confounded) and NGS/PFR/FTN advanced metrics (unproven value, and FTN carries a share-alike obligation). Both are documented in `docs/MODELING.md` section 5.1.

## Phase-3 facts a later phase should not re-derive

- **A model implements one method.** `fit_predict(train, validate, context)` is the whole interface, so there is no fitted object that could outlive a fold and nowhere to keep a statistic computed over the whole dataset. Fold isolation is structural, not a convention to remember.
- **The seal is at load time.** `load_modeling_dataset` drops sealed seasons before anything sees the frame, and the fold generator refuses to build a fold that validates one. `tests/model/test_folds_and_holdout.py` proves it by construction: poisoning every 2025 label leaves a development run byte-identical. Do not add a second, softer path to the holdout.
- **Residual quantiles come from an inner chronological split** of the training window - fit on the earlier seasons, residuals from the latest one or two, stratified by predicted level where a stratum has 100+ rows. That is how B0 and B1 get honest intervals; never give a baseline a fixed-width band.
- **B0 is a strong baseline on purpose.** Prior-season points per game times the training-fold mean games for the same availability *and* age cohort beats a raw prior-season total on every development season tried, and beats ridge on MAE at every position. If a future candidate "beats the baseline", check which baseline.
- **Macro before row-weighted.** Aggregates are means over season x position x scoring cells. WR and RB cells carry two to three times the rows of QB and TE ones, so a pooled mean lets them decide positional questions on their own. Row-weighted numbers are emitted as diagnostics.
- **Metrics are the project's own code** (ADR-024), pinned by hand-worked examples and cross-checked against SciPy. Spearman is Pearson on average ranks; Kendall is the tie-corrected tau-b. Do not swap in a library mid-project without re-pinning the report numbers.
- **The paired bootstrap resamples within cells and carries both models through the same resample.** Two models differing by a constant produce a degenerate interval, which is the property that makes the interval mean anything; independent resampling would not.
- **Q1's raw quantiles cross on 38.7% of rows** with a mean magnitude of 0.53 points against a 62.7-point P10-P90 width. Phase 3 sorts them and reports the raw rate separately. Phase 4 should fix the cause, not keep sorting.
- **Top-K retrieval does not follow rank correlation.** Q1 has the better Spearman but B1 retrieves more of the actual top-K (0.593 against 0.544). A median-quantile point prediction is robust, and robustness compresses the top of the board. Measure top-K on simulated VORP in Phase 4 rather than assuming the point ordering carries over.
- **`prev1_games_missed` was clamped to zero when either component was missing.** Phase 3 fixed it to null, matching what the dictionary always declared, and added the regression test. 4,946 of 11,604 rows are affected; a dataset built before this fix disagrees.

## Phase-4 facts a later phase should not re-derive

- **`ffdraft.modeling.rules` is the freeze, and `ffdraft.modeling.frozen` is its output.** Every Phase-4 threshold lives in the first as a frozen dataclass with a pure evaluator; every decision those rules made lives in the second as a constant. If you want to know what the production system is, read `frozen.py` — it is one screen and every value cites the ADR that produced it. Do not add a decision to `frozen.py` that no rule made.
- **A rule that fails is a result.** Two did. The convergence rule fell through to its own fallback clause and the tier stability gate failed outright, and both are published rather than repaired. If a future session is tempted to move `min_boundary_agreement` or `max_largest_tier_share`, that is a new rule version with its own evidence and its own ADR — not an edit.
- **Crossing is fixed by projection, not by sorting.** PAV projects the raw quantile vector onto the monotone cone, which is an L2 projection onto a closed convex set that contains the true quantile vector, so it provably cannot move the estimate further from the truth. Sorting has no such guarantee. Raw crossing went 0.387 -> 0.000 and CB's own components do not cross at all.
- **The hurdle's two components are coupled, not independent.** A Gaussian copula carries one fold-fitted rank correlation between availability and per-game performance, estimated from probability-integral transforms on an inner chronological split. Assuming independence would have understated the spread of the season total.
- **VORP is simulated, never differenced against a fixed replacement.** Every draw allocates starters and derives *that draw's* replacement level. Subtracting one deterministic baseline from every quantile would have made VORP a shifted copy of points and destroyed the league-scarcity information the whole simulation exists to produce.
- **Point draws deliberately do not depend on the league preset.** The same simulated seasons are re-allocated under every roster shape, so a preset-to-preset difference is a scarcity difference rather than Monte Carlo noise. Per-player BLAKE2b streams make a board independent of player order and pool membership too.
- **`ffdraft.simulation.allocation` is still the only allocator.** Phase 4 fed it sampled points instead of realized ones; it did not write a second one, and neither should Phase 5+.
- **Tier membership is reproducible; tier boundaries are not.** ARI 0.865 beside boundary agreement 0.239 is not a contradiction, it is the finding. Simulated VORP declines almost smoothly, so "where a tier ends" is mostly not an identified quantity — only about four cut sites on a 300-deep board are. Any UI that draws a hard line overstates the measurement.
- **The board's deep tail genuinely is one group.** At penalty 3.0 the segmentation wants tiers of 82 and 110 players. The frozen 25%-of-board cap forbids that, which is what forces the unstable cuts. A future tier rule should let the undifferentiated tail be one wide tier rather than slicing it.
- **The holdout is spent and the seal is one-way in code.** `--final-eval` needs a fixed token *and* a written reason; `train-production --allow-unsealed` needs the same token and refuses unless the holdout has already been consumed. There is no softer path, and none should be added.
- **A current build never loads target-season statistics.** `include_target_statistics=False` is correct in general — a preseason board may not consume the season it predicts — and not a workaround for 2026 being unplayed. The 404 from nflverse for an unplayed season is a symptom of the same fact.
- **A pre-anchor build uses its own timestamp, not the anchor.** `min(as_of, anchor)`. Stamping a future anchor onto a build that ran before it would claim knowledge the build does not have.
- **Current roster status is metadata, never a feature.** It can drop a retired player from the board and it annotates rows with flags, but it has no development-era support and cannot enter a prediction.
- **The Phase-3 harness reproduces exactly.** `evaluate-intrinsic` was re-run at Phase 4 and diffed against the committed report: identical on every number, decision and check, with only the timestamped `experiment_id` differing. Determinism here is real, not aspirational.
- **Model cards are generated, like the feature dictionary.** `ffdraft model-card` reads the committed experiment reports and the artifact. A number in a card that no command produces is a number that can drift.

## Open questions requiring evidence

- **How to make tier boundaries meet a stability bar, or how to stop pretending they are lines.** The measurement says a 300-deep board supports about four reproducible cut sites. Two candidate remedies, both new decisions needing their own rule version and evidence: let the undifferentiated tail be one wide tier by re-specifying `max_largest_tier_share`, or keep the segmentation and present membership with a boundary-confidence band instead of a hard edge. **Do not simply lower the threshold** (ADR-035).
- **How to re-specify the Monte Carlo convergence rule.** Its tier clause is stricter than the tier stability gate it was meant to protect and is decided partly by penalties the tier rule may never select. A revision should measure the tier clause on the promoted configuration only, and set its bar consistently with the gate (ADR-034).
- **Whether correlated player draws are worth building.** V1 samples every player independently, so it cannot express that a quarterback's collapse takes his receivers with him. That is the largest structural simplification in the simulation and it was never measured.
- **Repository visibility** — deferred to Phase 7 by ADR-016.
- **Market cohort mix closer to peak draft season** — re-measure at the start of Phase 5 (ADR-012 amendment).
- **Whether `load_ftn_charting` earns its CC-BY-SA obligation** — still open, and still not needed.

## Known risks (non-blocking)

- **Tiers are published having failed their stability gate.** `build_metadata.json` carries a `current.tier_stability` warning and the cards say so, but nothing stops a consumer from rendering a hard line anyway. The Phase-6 frontend is where this becomes a user-visible risk rather than a documented one.
- **Residual Monte Carlo error is real and unmeasured beyond the ladder.** At 10,000 draws two seeds differ by about 0.3 fantasy points on a player's expected VORP and under 1.5 rank positions in the top 150. Tier boundaries move more than that, which is part of why boundary agreement is low. A build is deterministic for a fixed seed; it is not seed-invariant.
- **CB's pooled P25-P75 coverage is 0.614 against a nominal 0.50**, driven by zero-game rows: among players with at least one game it is 0.456, among zero-game rows 0.836, and 18.4% of rows have `q25 == q75 == 0`. The hurdle is right that many players score nothing; the inner interval is consequently wide where it should be degenerate. Recorded as an ADR-033 limitation rather than patched.
- **The model card and tier report are only as current as the last `ffdraft model-card` run.** They are generated from committed experiment reports, so a retrain without regenerating them leaves published numbers describing a model that no longer exists.
- **The 2014-2016 era boundary is real and is reported as a warning, not hidden.** It comes from upstream roster coverage, not from this code. Any metric averaged across all twelve seasons mixes two different universes. ADR-028 chose to train across it anyway, on measured evidence, and records that W1's advantage is largest where W2 has least data.
- **The fantasy horizon changed at 2021** (weeks 1-16 to weeks 1-17), so season totals are on a ~6% different scale either side of it. It affects every candidate identically within a fold and is not corrected for; validation season 2021 is the one fold trained entirely on 16-week seasons. `prev1_team_games`, which is that horizon expressed as a lagged count, is excluded from the feature set for the same reason (ADR-026).
- **B0 and B1 predictive intervals under-cover slightly** because their residual quantiles are estimated on one or two inner-split seasons, which understates season-to-season variance. Q1's P10-P90 coverage is 0.771 against a nominal 0.80. Calibration is Phase-4 work and must be fitted on development folds only.
- **`team_at_anchor` is null for almost every pre-2025 veteran.** Free agency and trades are unobservable before the snapshot era, so `team_change_flag` is null there too, with `team_change_known` saying so. Overall `team_at_anchor` coverage is 12%; that is honest, not a defect.
- **Pre-2025 rookies have no depth or role signal at all** (`depth_unavailable`), by ADR-018. Their preseason signal is draft capital, biography and team context. Coverage is reported per season and position rather than patched over.
- **One upstream GSIS id names two different players** (`00-0035718`, 2019). Failed closed and excluded; re-check if nflverse corrects it.
- **Source-schema drift is detected, not prevented.** Phase 2 adds a semantic layer over the structural one, but a column that changes meaning *inside* its declared domain would still pass. Re-run `scripts/source_probe.py` and `scripts/capture_source_schemas.py` if more than a few weeks pass.
- **`mypy --strict` covers `src/ffdraft` only.** Tests are covered by execution.
- **The historical build takes a few minutes** of nflverse downloads plus the independence proof. There is no incremental mode; if that becomes painful, cache the normalized frames rather than weakening the proof.

## Repository notes

- **`BUNDLE_MANIFEST.txt` is a snapshot of the original specification bundle, not a live checksum.** The frozen set (`AGENTS.md`, `PRD.md`, `MASTER_SPEC.md`, `PROMPT_START_HERE.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/TEST_STRATEGY.md`, `docs/UX_SPEC.md`, `docs/BASELINE_FFTIERS_ANALYSIS.md`, `repo-tree.txt`) is untouched. The living records — `README.md`, `TASKS.md`, `SESSION_STATE.md`, `docs/DECISIONS.md`, `docs/DATA_SOURCES.md`, `docs/DATA_CONTRACTS.md`, `docs/MODELING.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/SECURITY_LICENSE.md`, `docs/FEATURE_DICTIONARY.md`, `config/*` — are updated as the contract requires.
- **`ruff` 0.16 formats Python code blocks inside Markdown.** Markdown is excluded from ruff in `pyproject.toml`; do not remove that exclusion.
- **Regenerating the golden artifacts is a deliberate act**, not a fix for a red test: `uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000`. Read the diff first.
- **`docs/FEATURE_DICTIONARY.md` is generated.** Regenerate from `uv run ffdraft feature-dictionary` after changing `ffdraft.features.dictionary`; a test fails if it is stale.
- **`data/historical/` is gitignored.** Rebuild it rather than looking for it in a clone.
- **The Phase-3 experiment reports are committed; the row-level predictions are not.** `docs/experiments/phase3-intrinsic-baselines/{experiment.json,experiment.md}` are the evidence behind ADR-028 and ADR-029, in the same spirit as `docs/source-probes/`. `predictions.parquet` is written only with `--write-predictions` and is gitignored.

## Known blockers

None blocking Phase 5. Two Phase-4 exit criteria are **open, not blocking**: the Monte Carlo convergence rule fell through to its fallback (ADR-034) and the tier stability gate failed on boundary agreement (ADR-035). Both are published limitations of a model that otherwise passed every gate including the sealed holdout, and neither prevents market snapshots or an arbitrage baseline from being built. Neither should be closed by editing a threshold.

## Next action

Begin Phase 5 (`docs/IMPLEMENTATION_PLAN.md`). The concrete first step, and the one Phase 4 deliberately did **not** take:

**Take the first point-in-time MFL ADP snapshot and stand up the append-only retention strategy** — `https://api.myfantasyleague.com/{season}/export?TYPE=adp&JSON=1`, no auth, recording source id, retrieval timestamp and the response `timestamp` separately (it is generation time, not data-as-of), plus sample size where available. `PRD.md` section 15 recommends a dedicated `data` branch or another append-only store, and that decision needs an ADR before the first snapshot is written, because a retention scheme chosen after a month of snapshots exist is a migration rather than a decision.

Then, in order: re-measure the market cohort mix now that it is closer to peak draft season (the ADR-012 amendment requires this at the start of Phase 5); build the deterministic fair-rank-vs-ADP arbitrage baseline and keep it as a permanent challenger; and only then consider a learned arbitrage model, whose target must be realized value *relative to market cost* and which may not be called ML until the historical market coverage and out-of-time promotion gate pass.

**What Phase 5 must not do.** Market or expert data may never reach the intrinsic model — not as a feature, not as a training target, not as a calibration input. Arbitrage may consume intrinsic outputs; the reverse is a design bug (`AGENTS.md` section 1). Historical arbitrage training may only use out-of-fold intrinsic predictions for the same season, and `data/phase4/oof_predictions.parquet` is regenerable with `ffdraft evaluate-distribution` for exactly that purpose.

Rebuild the dataset first — `uv run ffdraft build-historical --last-season 2025` — because `data/historical/` is not in the repository. The production model artifact **is** committed, so inference needs no retrain.
