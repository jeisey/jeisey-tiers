# Implementation Task Board

Status legend: `[ ]` not started, `[-]` in progress, `[x]` complete, `[!]` blocked.

Do not check a phase complete until every exit criterion below passes.

## Phase 0 — Source/legal/feasibility proof

- [ ] Verify current nflreadpy install/API and required datasets.
- [ ] Verify nflverse/ffopportunity licenses and attribution obligations.
- [ ] Probe required historical/current seasons and record schemas/counts/freshness.
- [ ] Verify 2026 MyFantasyLeague ADP endpoint, filters, unauthenticated access behavior, sample-size/dispersion fields, rate expectations, and historical year access.
- [ ] Verify Sleeper player/status endpoint behavior and attribution/rate guidance.
- [ ] Re-check FantasyCalc current terms; decide `allowed_optional`, `benchmark_only`, or `disabled` for this non-commercial deployment.
- [ ] Re-check FantasyPros-derived ECR terms; decide benchmark-only handling.
- [ ] Determine whether free historical market data is sufficient for an arbitrage ML target across >= 3 chronological holdout seasons.
- [ ] Document all source findings in `docs/DATA_SOURCES.md` and `config/source-registry.yaml` with retrieval date.
- [ ] Add tiny permitted source fixtures or recorded schema examples for adapter tests.
- [ ] Record any architecture-impacting source decision in `docs/DECISIONS.md`.

**Exit gate:** every production/benchmark source has a verified policy decision and a tested access/schema path. Arbitrage ML feasibility is explicitly yes/no. No critical source assumption remains unverified.

## Phase 1 — Repo scaffold, contracts, identity, adapters

- [ ] Initialize Python package, `pyproject.toml`, `uv.lock`, lint/test config.
- [ ] Initialize Vite/React/TypeScript app and lockfile.
- [ ] Implement typed source adapter interfaces.
- [ ] Implement canonical player identity/crosswalk layer.
- [ ] Implement schema/data-quality framework.
- [ ] Finalize JSON Schemas in `schemas/` and serializer skeletons.
- [ ] Add fixture-based adapter/identity/contract tests.
- [ ] Add minimal CI that runs Python + frontend checks.

**Exit gate:** clean clone installs; fixture-only pipeline resolves player identities and emits schema-valid example artifacts with no network access.

## Phase 2 — Historical feature dataset

- [ ] Define draft-time anchor date logic by season.
- [ ] Build player-season eligibility rules.
- [ ] Build historical raw/canonical feature assembly for QB/RB/WR/TE.
- [ ] Engineer lagged performance/opportunity/age/team/depth/draft/athletic features.
- [ ] Build actual fantasy scoring labels for STD/HALF/PPR.
- [ ] Build realized VORP labels independently of market data.
- [ ] Add feature-availability timestamps/rules.
- [ ] Add automated temporal leakage tests.
- [ ] Emit data-quality report by season/position.

**Exit gate:** reproducible historical modeling table with documented feature dictionary, target dictionary, leakage tests passing, and acceptable missingness/identity quality.

## Phase 3 — Intrinsic baselines + evaluation harness

- [ ] Implement naive baselines (prior-year/age-position or equivalent documented baselines).
- [ ] Implement chronological rolling-origin fold generator.
- [ ] Implement point/rank/probabilistic metrics and bootstrap CIs.
- [ ] Implement simple boosted-tree quantile baseline.
- [ ] Compare candidates year-by-year and position-by-position.
- [ ] Freeze final holdout rules before production candidate tuning.

**Exit gate:** evaluation harness can train/evaluate from scratch and generates machine-readable + human-readable metrics; at least one candidate improves on the declared naive baseline without leakage.

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
