# Implementation Task Board

Status legend: `[ ]` not started, `[-]` in progress, `[x]` complete, `[!]` blocked.

Do not check a phase complete until every exit criterion below passes.

## Phase 0 — Source/legal/feasibility proof

Completed 2026-08-17. Evidence: `docs/source-probes/2026-08-17/report.json`; verified record: `docs/DATA_SOURCES.md` section 13; decisions: ADR-009 through ADR-015.

- [x] Verify current nflreadpy install/API and required datasets. — `nflreadpy==0.1.5`; 30 loader calls probed, all returned data.
- [x] Verify nflverse/ffopportunity licenses and attribution obligations. — MIT client / CC-BY-4.0 data (FTN subsets CC-BY-SA-4.0); ffopportunity data CC-BY-SA-4.0, code GPL-3. Quoted evidence captured.
- [x] Probe required historical/current seasons and record schemas/counts/freshness. — 2012→2026 coverage recorded per loader; found the 2025 depth-chart schema break and the missing preseason depth history (ADR-015).
- [x] Verify 2026 MyFantasyLeague ADP endpoint, filters, unauthenticated access behavior, sample-size/dispersion fields, rate expectations, and historical year access. — all twelve registry questions answered; no `adp_sd` field, `DAYS` ignored, 2019–2025 all retrievable.
- [x] Verify Sleeper player/status endpoint behavior and attribution/rate guidance. — 12,220 records / 14.6 MB; status+injury fields present; non-commercial terms and 1000 calls/minute guidance quoted.
- [x] Re-check FantasyCalc current terms; decide policy. — **`disabled`** (ADR-013).
- [x] Re-check FantasyPros-derived ECR terms; decide benchmark-only handling. — **`disabled` pending human terms review** (ADR-014).
- [x] Determine whether free historical market data is sufficient for an arbitrage ML target across >= 3 chronological holdout seasons. — **No.** Dense but not point-in-time; baseline mode (ADR-010).
- [x] Document all source findings in `docs/DATA_SOURCES.md` and `config/source-registry.yaml` with retrieval date.
- [x] Add tiny permitted source fixtures or recorded schema examples for adapter tests. — 12 schema fixtures in `tests/fixtures/source_schemas/`; benchmark-only rows suppressed.
- [x] Record any architecture-impacting source decision in `docs/DECISIONS.md`. — ADR-009 … ADR-015.

**Exit gate:** met. Every production/benchmark source has a verified policy decision and a tested access/schema path; arbitrage ML feasibility is explicitly **no**; the market→canonical identity path is measured (100% of priced QB/RB/WR/TE) rather than assumed.

Two follow-ups are recorded in `SESSION_STATE.md` and neither blocks Phase 1: registering an MFL developer client (needs an MFL account) and deciding whether the repository becomes public before Phase 7.

## Phase 1 — Repo scaffold, contracts, identity, adapters

Completed 2026-08-18. Evidence: `.github/workflows/ci.yml`; commands and results recorded in `SESSION_STATE.md`; decisions ADR-016 through ADR-020 plus amendments to ADR-012 and ADR-014.

- [x] Initialize Python package, `pyproject.toml`, `uv.lock`, lint/test config. — `src/ffdraft/` (hatchling, editable), `ffdraft` console script, ruff + mypy `--strict` + pytest. Added `jsonschema`, `pydantic`, `rfc3339-validator`; modeling deps deliberately deferred to Phase 3/4.
- [x] Initialize Vite/React/TypeScript app and lockfile. — root `package.json` + `package-lock.json`, Vite 7 rooted at `web/`, TypeScript strict (plus `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`), ESLint 9 flat config with type-checked rules, Vitest + Testing Library. D3/TanStack Table arrive with the Phase-6 UI.
- [x] Implement typed source adapter interfaces. — `SourceAdapter` protocol with a pure `normalize` and an I/O `fetch`; nflverse rosters / ff_playerids / depth charts (both ADR-015 eras), Sleeper player map + state, MFL ADP + player directory. Each adapter declares the upstream columns it reads and is tested against the Phase-0 recorded schemas.
- [x] Implement canonical player identity/crosswalk layer. — namespaced `player_id`, id trimming and format validation, poisoned crosswalk indexes, two-bridge market resolution failing closed on disagreement, nflverse → Sleeper joins with a fatal `gsis_id` cross-check, team units barred from player identity, name matching as diagnostics only, human-reviewed alias file (ADR-019).
- [x] Implement schema/data-quality framework. — Polars `FrameContract`s, structured `QualityCheck` records, the collecting `QualityGate`, reusable semantic checks, launch thresholds, and the forbidden-feature guard over both names and source lineage.
- [x] Finalize JSON Schemas in `schemas/` and serializer skeletons. — added `artifact_envelope.schema.json` (ADR-020); deterministic JSON/CSV serializers driven by the schemas themselves; `validate-artifacts` enforces schema **and** semantics.
- [x] Add fixture-based adapter/identity/contract tests. — 254 network-free Python tests plus 31 frontend tests; synthetic fixtures cover every `docs/DATA_CONTRACTS.md` section 14 case and each fail-closed path.
- [x] Add minimal CI that runs Python + frontend checks. — `.github/workflows/ci.yml`, two jobs, `contents: read`, no live vendor access.

**Exit gate:** met. From a clean clone with no vendor network, `uv sync --frozen` and `npm ci` install deterministically; fixtures flow source → adapter → identity → contracts → serialization; generated artifacts pass JSON Schema and semantic validation; deliberately conflicting identity fixtures fail closed for their intended reasons and are excluded from public output; both toolchains lint, type-check, test and build.

Phase-1 scope boundaries held: no historical feature engineering, no model training, no VORP simulation, no arbitrage logic, no bespoke charts, no Pages deployment. The fixture pipeline's valuation is an explicitly labelled `fixture-stub-0` serialization exerciser, not a model.

## Phase 2 — Historical feature dataset

Completed 2026-08-19. Evidence: `data/historical/quality_report.md` from the validated build; commands and results recorded in `SESSION_STATE.md`; decisions ADR-021 through ADR-023.

- [x] Define draft-time anchor date logic by season. — `ffdraft.anchors`, rule `draft_anchor_v1_tuesday_eod_pre_week1` (ADR-021): 23:59:59 America/New_York on the Tuesday before the earliest Week-1 kickoff, persisted as UTC. Explicit time zone, DST-correct, weekday derived rather than assumed, strictly-before-kickoff enforced by the type. Tested across eight real openers including the two Wednesday ones.
- [x] Build player-season eligibility rules. — ADR-022's preseason universe: previous-season roster, target-season draft class, and pre-anchor depth snapshots (2025+ only). `load_rosters(Y)` and week-1 weekly rosters are refused because neither carries evidence it was settled by the anchor. Every row records `eligibility_basis` and `universe_era`; every exclusion is counted with a reason.
- [x] Build historical raw/canonical feature assembly for QB/RB/WR/TE. — 11,604 rows across 2014-2025, zero duplicate `(season, player_id)` keys, 102 columns built from the feature dictionary.
- [x] Engineer lagged performance/opportunity/age/team/depth/draft/athletic features. — 85 model inputs across nine families; ADR-018's three depth states realised, with the prior-season role rank as the pre-2025 proxy and no fabricated depth rank anywhere.
- [x] Build actual fantasy scoring labels for STD/HALF/PPR. — `ffdraft.scoring` computes all three from weekly stat components over the documented horizon (1-17 from 2021, 1-16 before). 34,812 label rows. nflverse's own totals are a reconciliation check, never the label.
- [x] Build realized VORP labels independently of market data. — 104,436 rows across three launch presets, using the same `ffdraft.simulation.allocation` Phase 4 will drive with Monte Carlo draws. No market input anywhere.
- [x] Add feature-availability timestamps/rules. — every column declares an availability class; rows carry `anchor_at_utc`, `feature_cutoff_rule_version`, `max_lagged_source_season` and `depth_observed_at_utc`, which is what the audits check.
- [x] Add automated temporal leakage tests. — all ten required rules, each with a paired test proving the guard fails when the rule is broken. Rules 1 and 6 are proved by construction: every season rebuilt with its own statistics deleted produces a byte-identical table.
- [x] Emit data-quality report by season/position. — deterministic JSON and Markdown covering eligibility, rookie/veteran counts, depth-state distribution, per-family missingness, label coverage, exclusions, thresholds and every check.

**Exit gate:** met. The dataset rebuilds reproducibly from `ffdraft build-historical`, its 187 checks pass with zero critical failures, the feature dictionary is published and test-pinned against the code, and both eras of the ADR-018 boundary are visible rather than averaged away.

Two warnings are deliberate and expected: one upstream GSIS id names two different players in 2019 (failed closed, excluded), and 2014-2016 carry ~36% fewer eligible rows than the median season because nflverse roster coverage steps up at 2016. Phase 3 must choose its training window with that boundary in view.

Phase-2 scope boundaries held: no model trained or evaluated, no rolling-origin harness, no holdout chosen, no simulation, no tiering, no arbitrage, no UI.

## Phase 3 — Intrinsic baselines + evaluation harness

Completed 2026-08-19. Evidence: `docs/experiments/phase3-intrinsic-baselines/{experiment.json,experiment.md}`; commands and results recorded in `SESSION_STATE.md`; decisions ADR-024 through ADR-029.

- [x] Implement naive baselines (prior-year/age-position or equivalent documented baselines). — **B0**: prior-season points per game in the row's own scoring flavour, optionally shrunk towards the position's typical training-fold rate, times the training-fold mean games played by the same previous-season availability and age cohort; a draft-capital prior for players without usable prior production. It beats a raw prior-season total on every development season tried, so the gate is a real gate. **B1**: closed-form ridge on the core feature set with fold-local imputation, missingness indicators and standardization. Both emit the same five quantiles as the candidate, from residuals collected on an inner chronological split.
- [x] Implement chronological rolling-origin fold generator. — `ffdraft.modeling.folds`; expanding windows, two policies (W1 from 2014, W2 from 2017), common development validation seasons 2020-2024, W1-only diagnostics 2017-2019, and a persisted fold table. A fold that trains on or after its validation season cannot be constructed.
- [x] Implement point/rank/probabilistic metrics and bootstrap CIs. — MAE, RMSE, Spearman, Kendall tau-b, top-K retrieval, per-quantile and mean pinball, P10-P90 and P25-P75 coverage with the matching widths, and raw crossing rate *and* magnitude. All written in NumPy (ADR-024), pinned by hand-worked examples and cross-checked against SciPy. Paired block bootstrap, 1000 replicates, resampling within validation-season x position x scoring blocks with both models carried through the same resample.
- [x] Implement simple boosted-tree quantile baseline. — **Q1**, LightGBM quantile regression per position x scoring x quantile, fixed predeclared parameters, deterministic seeds, no search of any kind.
- [x] Compare candidates year-by-year and position-by-position. — 468 evaluation cells across window x model x season x position x scoring, aggregated macro-first with row-weighted diagnostics beside them.
- [x] Freeze final holdout rules before production candidate tuning. — ADR-025: 2025 is sealed structurally, with predeclared primary and diagnostic slices. ADR-027 froze the promotion and window rules in code, committed before the decisive run.

**Exit gate:** met. `ffdraft evaluate-intrinsic` rebuilds folds, trains every model from scratch and writes both reports in ~5 minutes with no network. **Q1 passes the frozen gate on both windows**: against B0 under W1, MAE −3.53 (95% CI −3.87 to −3.18), mean pinball −1.85 (−1.98 to −1.72), Spearman +0.066 (+0.058 to +0.075), with every position improving and none triggering the collapse rule. **W1 is the selected training window** (ADR-028); **Q1 advances to Phase 4** (ADR-029). B1 fails the gate on both windows — it loses to B0 on MAE at every position — which is a result, not a defect.

Two limitations are recorded rather than smoothed over: Q1's raw quantiles cross on 38.7% of rows (mean magnitude 0.53 points against a 62.7-point P10-P90 width), and Q1's top-K retrieval (0.544) is below B1's (0.593) despite better rank correlation. Both are Phase-4 work.

**The 2025 final holdout was not evaluated.** No development command can reach it, and the sealed path was exercised only against synthetic data in the test suite.

## Phase 4 — Production DraftValue + simulation + tiers

- [ ] Evaluate direct total-points quantile model vs availability × performance candidate.
- [ ] Promote simplest candidate that passes primary metrics/calibration gates.
- [ ] Implement quantile calibration if needed.
- [ ] Implement deterministic Monte Carlo sampler.
- [ ] Implement league starter/FLEX allocation and simulated replacement baselines.
- [ ] Compute VORP distributions and fair ranks for every supported preset.
- [ ] Implement contiguous natural tier segmentation.
- [ ] Tune tier penalty/parameters only on allowed development folds.
- [ ] Implement tier bootstrap/sensitivity stability tests.
- [ ] Generate intrinsic model card and tier-method report.
- [ ] Emit schema-valid current tier JSON/CSV.

**Exit gate:** production intrinsic model is versioned, reproducible, leakage-safe, beats required baseline, meets calibration/stability gates, and emits valid Tier artifacts for all launch presets.

## Phase 5 — Market snapshots + arbitrage

- [ ] Implement verified current market adapter(s).
- [ ] Implement append-only daily market snapshot strategy.
- [ ] Normalize ADP, sample size, spread, scoring/league filters, and IDs.
- [ ] Implement transparent deterministic fair-rank-vs-ADP baseline.
- [ ] If Phase 0 says ML feasible: construct historical realized-surplus target.
- [ ] If ML feasible: generate historical rolling OOF intrinsic predictions.
- [ ] If ML feasible: train/evaluate arbitrage candidates against simple gap baseline.
- [ ] Promote ML only if declared out-of-time gates pass; otherwise retain baseline labeling.
- [ ] Compute daily trend features from retained snapshots.
- [ ] Generate arbitrage model/method card.
- [ ] Emit schema-valid arbitrage JSON/CSV.

**Exit gate:** current arbitrage artifact is reliable and transparent. If ML label is used, it has demonstrably beaten the baseline out-of-time; otherwise baseline mode is explicit.

## Phase 6 — Frontend product

- [ ] Implement compact global configuration controls + URL query state.
- [ ] Implement Tier Board D3 visualization.
- [ ] Implement Draft Rail D3 visualization.
- [ ] Implement Tier table with search/filter/sort/export.
- [ ] Implement Arbitrage table with search/filter/sort/export.
- [ ] Implement methodology/freshness/source panel.
- [ ] Implement player details/tooltip behavior.
- [ ] Implement loading/error/degraded-source states from static metadata.
- [ ] Implement responsive tablet/mobile layouts.
- [ ] Implement keyboard/accessibility and reduced-motion requirements.
- [ ] Add component/unit/E2E tests.

**Exit gate:** all primary draft-sheet flows work against real generated artifacts, exports are correct, and accessibility/responsive smoke tests pass.

## Phase 7 — Production GitHub Actions + Pages

- [ ] Complete `ci.yml`.
- [ ] Complete `daily-refresh.yml` with off-the-hour America/New_York schedule + manual dispatch.
- [ ] Complete `retrain.yml` with candidate/promotion gates.
- [ ] Configure official GitHub Pages build/deploy actions.
- [ ] Apply least-privilege workflow permissions.
- [ ] Add safe cache strategy.
- [ ] Add last-known-good deployment behavior.
- [ ] Add workflow summaries with source counts/freshness/model versions.
- [ ] Prove failed critical validation cannot deploy.

**Exit gate:** a clean GitHub-hosted run can build and deploy the site; daily refresh can update it; a forced data-quality failure leaves existing production intact.

## Phase 8 — Hardening and quality

- [ ] Full model backtest/model-card review.
- [ ] Data-source failure/fallback drills.
- [ ] Dependency/security review.
- [ ] Frontend performance review.
- [ ] Accessibility review.
- [ ] Browser compatibility smoke test.
- [ ] Documentation/source attribution review.
- [ ] Reproducibility run from clean clone.
- [ ] Resolve critical/high defects.

**Exit gate:** no known launch-blocking defect, leakage issue, source-rights ambiguity, or broken primary flow.

## Phase 9 — Launch release

- [ ] Run final daily refresh.
- [ ] Capture final metrics and build metadata.
- [ ] Verify all supported presets visually and via artifact validation.
- [ ] Verify CSV exports.
- [ ] Verify Pages URL and base-path behavior.
- [ ] Tag/release V1.
- [ ] Mark `SESSION_STATE.md` with production model/data versions and known limitations.

**Exit gate:** all acceptance criteria in `PRD.md` Section 21 pass.
