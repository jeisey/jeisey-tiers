# Session State

This file is durable cross-session state for coding agents. Keep it concise and factual.

## Current phase

Phase 3 — **complete** (2026-08-19). Phase 4 (production DraftValue, simulation and tiers) is next and has not been started.

## Current target gate

Phase 4 exit gate: a versioned, reproducible, leakage-safe production intrinsic model that beats the required baseline, meets calibration and stability gates, and emits valid Tier artifacts for every launch preset.

## Last validated commit

The Phase-3 branch `claude/fdi-phase-3-baselines-82pptx`, branched from the merged Phase-2 state on `main` (`0cbb343`).

Validation run locally; every network-free command below also runs in CI (`.github/workflows/ci.yml`):

```
uv sync --frozen
uv run ruff check .                 # clean
uv run ruff format --check .        # clean, 105 files
uv run mypy                         # clean, 71 source files, strict
uv run pytest                       # 638 passed, 4 live deselected
uv run ffdraft config-check
uv run ffdraft build-fixture-artifacts --out web/public/data
uv run python -m ffdraft.cli validate-artifacts web/public/data   # gate: pass

# Phase-2, network-bound (nflverse only)
uv run ffdraft build-historical --last-season 2025 --git-sha c2b48cc
#   -> 11,604 feature rows, 34,812 fantasy labels, 104,436 VORP labels
#   -> quality gate: pass (0 critical, 2 warning), 187 checks
uv run ffdraft validate-historical data/historical   # gate: pass (0 critical, 0 warning)

# Phase-3, offline
uv run ffdraft evaluate-intrinsic --git-sha c2b48cc --write-predictions
#   -> 31,503 modelling rows, 2014-2024; 3,309 sealed 2025 rows withheld at load
#   -> feature set intrinsic_core_v1 (7203befaa5be25a2), 78 inputs, 7 excluded
#   -> 296.6s; window W1_all_history; promoted Q1
#   -> quality gate: pass (0 critical, 0 warning)

npm ci
npm run lint                        # clean
npm run typecheck                   # clean
npm run test -- --run               # 31 passed
npm run build                       # clean
```

The Phase-1 golden artifacts were **not** regenerated: Phases 2 and 3 changed no public serialization contract, and a rebuild produces byte-identical files.

## Production status

No production pipeline, model, artifact or site exists. What exists is the Phase-0 evidence base, the Phase-1 skeleton, and the Phase-2 historical dataset:

- `src/ffdraft/` — config, contracts, sources, identity, quality, artifacts, pipeline, CLI (Phase 1) plus `anchors.py`, `scoring/`, `features/`, `labels/`, `simulation/`, `leakage.py` (Phase 2) plus `modeling/` (Phase 3).
- `data/historical/` — the modelling dataset. Gitignored and reproducible; see "Phase-2 dataset" below.
- `docs/FEATURE_DICTIONARY.md` — every model feature with formula, sources and availability rule, generated from code and pinned by a test.
- `docs/experiments/phase3-intrinsic-baselines/` — the committed Phase-3 experiment reports, machine-readable and human-readable. Row-level predictions are gitignored.
- `.github/workflows/ci.yml` — Python and frontend gates, fixture-only, no vendor network.
- `web/` — Vite/React/TypeScript skeleton with a typed artifact loader.
- `tests/` — 638 network-free Python tests, including the Phase-3 suite in `tests/model/`; `web/tests/` adds 31.

**The fixture pipeline's valuation is still not a model** (`intrinsic_model_version="fixture-stub-0"`). Phase 3 evaluated candidates but promoted none to production: no model artifact is trained, saved or served. Phase 4 replaces the stub.

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

## Open questions requiring evidence

- **Whether Candidate B (availability x performance) beats Q1.** Unimplemented and unjudged. Phase 4 compares it against the same frozen protocol, or documents why it is not worth building.
- **The production ranking statistic** — expected versus median simulated VORP. `docs/MODELING.md` section 13 prefers median for robustness; Phase 3's top-K finding is evidence that robustness costs something at the top of the board. Decide with a measurement, not a preference.
- **How to fix quantile crossing properly.** Sorting is a Phase-3 expedient. Monotonic or joint quantile estimation, or calibrated post-processing fitted on development folds, is Phase-4 work.
- **Repository visibility** — deferred to Phase 7 by ADR-016.
- **Market cohort mix closer to peak draft season** — re-measure at the start of Phase 5 (ADR-012 amendment).
- **Whether `load_ftn_charting` earns its CC-BY-SA obligation** — still open, and still not needed.

## Known risks (non-blocking)

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

None. Phase 4 can start immediately.

## Next action

Begin Phase 4 (`docs/IMPLEMENTATION_PLAN.md`). Everything it needs is frozen: the dataset, the fold protocol, window **W1**, feature set **`intrinsic_core_v1`** (`7203befaa5be25a2`), candidate family **Q1**, and an untouched 2025 holdout.

The first concrete step is **quantile calibration and the crossing fix**, before any simulation code:

1. address Q1's 38.7% raw crossing rate at its source - monotonic or joint quantile estimation, or a calibrated post-processing step fitted on development folds - and re-measure coverage and width together, not separately;
2. only then compare Candidate B (availability x performance) against Q1 on the same folds, or record why it is not worth building;
3. then the deterministic Monte Carlo sampler, the shared `ffdraft.simulation.allocation` replacement algorithm, VORP distributions and tiers.

Two things Phase 4 must not do casually. **The final holdout is a single-use instrument**: run it once, after the candidate, the calibration and the ranking statistic are all frozen, with `--final-eval --confirm-final-eval RELEASE-FINAL-HOLDOUT-2025 --final-eval-reason "<why>" --window W1_all_history`, and report the full-universe result as primary with the predeclared slices beside it. **The window decision is not to be re-run against 2025** to check.

Rebuild the dataset first - `uv run ffdraft build-historical --last-season 2025` - because `data/historical/` is not in the repository.
