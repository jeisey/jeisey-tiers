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

**Implemented 2026-08-19; the exit gate is partially met.** Every task below was built and
measured, and two frozen gates were measured as failing. This section's contract is that a
phase is not checked complete until every exit criterion passes, so it is not: the shortfall
is stated in the exit gate below and carried into the artifacts, not rounded up here.

Evidence: `docs/experiments/phase4-intrinsic-distribution/`,
`docs/experiments/phase4-simulation-ranking/`, `docs/experiments/phase4-tier-segmentation/`,
`docs/experiments/phase4-final-holdout/`; the production model card and tier-method report in
`models/cards/`; commands and results recorded in `SESSION_STATE.md`; decisions ADR-030
through ADR-037.

- [x] Evaluate direct total-points quantile model vs availability × performance candidate. — Both on the frozen Phase-3 protocol: **A0/A1**, direct season-total quantiles with Q1's parameters unchanged, and **CB**, a hurdle of LightGBM quantile regressions on `games / horizon_weeks` and on points per *active* game, composed by Monte Carlo. The two components are **not** assumed independent: a Gaussian copula carries one rank correlation per fold, estimated from probability-integral transforms on an inner chronological split and clipped at 0.95.
- [x] Promote simplest candidate that passes primary metrics/calibration gates. — `phase4_candidate_v1`, frozen before the run, promoted **CB**: pinball −0.0614 (95% CI −0.1002 to −0.0236), MAE −0.205 (−0.332 to −0.073), Spearman +0.0298, top-K +0.0326, no positional tolerance exceeded, and the absolute P10-P90 coverage gap *shrank* from 0.062 to 0.027. The simpler candidate would have stood otherwise (ADR-033).
- [x] Implement quantile calibration if needed. — **A1** projects the raw quantile vector onto the monotone cone by PAV: an L2 projection onto a closed convex set that contains the true quantile vector, so it provably cannot move the estimate away from it. **AH** adds per-level split-conformal shifts. `phase4_calibration_v1` kept A1 — the fitted layer bought +0.036 of P10-P90 coverage but lost 0.019 of P25-P75 against a 0.010 allowance (ADR-031). Crossing goes 0.387 → **0.000**, by projection rather than by sorting. A single horizon-sensitivity variant was measured and rejected (ADR-032); no calendar-year feature was added.
- [x] Implement deterministic Monte Carlo sampler. — `mc_quantile_sampler_v1`. Each player gets an independent uniform stream seeded from BLAKE2b over (build, season, scoring, player), so a board is reproducible regardless of player order, pool membership or league preset. Quantile functions are interpolated under fold-local domain bounds and refuse a crossing or non-finite grid outright. Two seeds agree to Spearman 0.99993 on fair rank.
- [x] Implement league starter/FLEX allocation and simulated replacement baselines. — `ffdraft.simulation.allocation`, the Phase-2 module, reused rather than rewritten; the replacement baseline is recomputed **inside every draw**. Replacement moves with league size exactly as it should (2024 PPR QB 235.4 / 221.9 / 207.7 and RB 145.8 / 130.6 / 117.2 across redraft-10/12/14).
- [x] Compute VORP distributions and fair ranks for every supported preset. — VORP is a distribution, not a point: each draw allocates starters, derives that draw's replacement level and differences against it, so the spread of VORP carries both the player's own uncertainty and the league's. `phase4_ranking_v1` kept **median** simulated VORP — expected VORP gained only +0.0014 of top-K against the 0.010 required while losing 0.0058 Spearman and 0.0071 Kendall (ADR-034). Expected-vs-median was measured, not assumed: mean |Δ rank| 20.25 with 0.96 top-50 overlap.
- [x] Implement contiguous natural tier segmentation. — PELT with an RBF cost over standardized P25/P50/P75 and spread in fair-rank order, plus the documented alternative: exact dynamic programming minimizing within-tier squared quantile distance, which is within-tier 2-Wasserstein dispersion. Contiguity and ordinality are structural, and tier count is discovered.
- [x] Tune tier penalty/parameters only on allowed development folds. — Fixed six-value grid `(1, 2, 3, 5, 8, 12)`, declared before any tier existed, evaluated on development folds only. The rule selected penalty **1.0**; the better-looking penalty 3.0 in the same grid was **not** substituted for it (ADR-035).
- [x] Implement tier bootstrap/sensitivity stability tests. — 1,200 replicates resampling the *simulated season*, each re-ranking as well as re-segmenting. **The gate fails**: boundary agreement 0.239 against a 0.500 bar. Membership is reproducible (ARI 0.865), tier-count CV 0.045, realized VORP falls across 84.5% of adjacent tier pairs, cross-preset ARI 0.529 — only the boundaries are unlocated. PELT failed three clauses, so the documented alternative was reached; it fixed two and not the third. Diagnosed, not hand-tuned: 283 of 299 cut sites used, 4 reproduced by a majority, median boundary cliff 0.55 points against an 80-130 point interval (ADR-035).
- [x] Generate intrinsic model card and tier-method report. — `models/cards/intrinsic-cb-hurdle-v1.{json,md}` and the tier-method report, generated from the artifacts rather than written by hand. Both carry the two failed gates as named limitations.
- [x] Emit schema-valid current tier JSON/CSV. — 2026 boards for every launch preset, `validate-artifacts` clean. `current_build_as_of_v1` sets the cutoff to `min(as_of, anchor)`, so a build running before the 2026 anchor uses its own timestamp rather than pretending the anchor has passed; target-season statistics are never loaded.

**Exit gate:** partially met, and the shortfall is named rather than rounded up.

**Met.** The production intrinsic model is **versioned, reproducible and leakage-safe**: `intrinsic-cb-hurdle-v1`, trained on 2014-2025 under W1, saved as 120 gzipped LightGBM boosters with a SHA-256 each and a `metadata.json` recording the spec, seed, library versions, dataset manifest, feature-set hash `7203befaa5be25a2` and feature-schema hash `c495ba3177dcb989`; `ProductionModel.load` verifies every digest and `assert_compatible` refuses a mismatched contract. It **beats the required baseline on the sealed holdout**, run exactly once after freeze checkpoint `2f0e725`: MAE -3.738 (95% CI -4.364 to -3.102), pinball -2.134 (-2.377 to -1.874), Spearman +0.1015, no positional collapse, zero production quantile crossings, and an improvement on every one of the eleven predeclared ADR-025 slices (ADR-036). Intervals are **calibrated within the documented tolerance** - full-universe P10-P90 coverage 0.845 against a nominal 0.80, positional 0.803-0.879 inside the declared 0.60-0.95 band. Simulation is **deterministic**: two seeds agree to Spearman 0.99993 on fair rank, and per-player streams make a board independent of player order and pool membership. **VORP and replacement pass hand-worked examples** in `tests/unit/`, and replacement moves correctly with league size. Tiers are **contiguous** by construction. Artifacts are **valid for all launch presets**: 3,510 projections and 2,700 tier records across 3 scoring x 3 league presets, `validate-artifacts` clean.

**Not met — two frozen gates failed, and neither threshold was moved afterwards.**

1. **The Monte Carlo draw count did not pass its convergence test.** No count in the frozen ladder `(1000, 2500, 5000, 10000)` met every tolerance; 10,000 stands by the rule's own predeclared fallback clause. The ranking tolerances all pass comfortably - it is the value and tier clauses that miss, by 10-20% on value and by a wide margin on tier ARI. ADR-034 also records a design error found by running the rule: its tier clause (ARI >= 0.90 between seeds) is strictly stricter than the tier stability gate (>= 0.60 under bootstrap) it was meant to protect, and is decided partly by penalties the tier rule may never select. That is recorded, not corrected.

2. **Tiers are "contiguous" but not "stable enough by declared metric".** Boundary agreement is 0.239 against a declared 0.500. PELT failed three of the six clauses, so the documented dynamic-programming alternative was reached - ADR-030's declared response - and it fixed two of the three and improved five of the six quantities, but not that one. The failure is diagnosed rather than asserted: across 1,200 replicates the segmentation used 283 of 299 possible cut sites and only 4 survived in a majority; the median promoted boundary sits on a 0.55-point P50 cliff against an 80-130 point P10-P90 width, and the player just below a boundary outscores the one just above it 49.7% of the time. Membership *is* reproducible (ARI 0.865, tier-count CV 0.045, cross-preset ARI 0.529) and realized VORP falls across 84.5% of adjacent tier pairs, so the groups carry signal and only their edges are soft. The binding cause is a conflict between two frozen rules: `max_largest_tier_share = 0.25` forbids a tier larger than 75 on a 300-deep board, but the deep tail genuinely is one large near-replacement group, so the rule forces cuts inside a flat region - and the same grid offers penalties whose boundary agreement passes (3.0 at 0.517, 8.0 at 0.500) and which are inadmissible on tier share (ADR-035).

Tiers ship anyway, with the failure attached: `build_metadata.json` carries a `current.tier_stability` warning naming the algorithm, penalty and verdict, and the model card and tier-method report both state it. Publishing them silently would have been the dishonest option; withholding them would have left the artifact contract untested. **The Phase-6 frontend must present tier membership as a group rather than drawing a hard line.**

## Phase 5 — Market snapshots + arbitrage

- [x] Implement verified current market adapter(s). — `MflAdpAdapter` 2.0 on `market_quote` 2.0; unauthenticated ADP path, registered User-Agent only, 429 backoff, one player-directory request per capture, `adp_sd` permanently null.
- [x] Implement append-only daily market snapshot strategy. — `ffdraft.retention` + the `market-data` branch (ADR-038). New timestamp appends; identical re-capture is idempotent; a differing rewrite fails closed; every file hashed and re-verified by `validate-market-history`.
- [x] Normalize ADP, sample size, spread, scoring/league filters, and IDs. — a quote records its cohort, not a preset; identity through the existing fail-closed two-bridge resolver.
- [x] Implement transparent deterministic fair-rank-vs-ADP baseline. — A0, frozen in `ffdraft.arbitrage` before the board existed (ADR-040).
- [x] ~~If Phase 0 says ML feasible: construct historical realized-surplus target.~~ — **not feasible** (ADR-010). Historical MFL ADP is a season aggregate recomputed at request time; there is no honest draft-time price to build a surplus label against.
- [x] ~~If ML feasible: generate historical rolling OOF intrinsic predictions.~~ — not applicable.
- [x] ~~If ML feasible: train/evaluate arbitrage candidates against simple gap baseline.~~ — not applicable.
- [x] Promote ML only if declared out-of-time gates pass; otherwise retain baseline labeling. — `arbitrage_mode = baseline` on every row and in the envelope; `expected_surplus_vorp` and `p_positive_surplus` null throughout, enforced by the schema and by a build-time check.
- [x] Compute daily trend features from retained snapshots. — `phase5_trend_v1` (ADR-042). **Null on every launch row**, correctly: the store holds two snapshots and the rule requires three observation days spanning three days.
- [x] Generate arbitrage model/method card. — `models/cards/arbitrage-method-a0.{json,md}`, generated from the artifacts, the cohort report and the frozen constants.
- [x] Emit schema-valid arbitrage JSON/CSV. — 2,124 records across nine preset blocks; `arbitrage_record` 1.1; `validate-artifacts` clean.

Added in the course of the phase, and not in the original list:

- [x] Re-measure the MFL cohort mix (ADR-012 amendment). — `ffdraft measure-market-cohorts`, offline and reproducible from a retained snapshot; report in `docs/market-cohorts/2026-08-20/`.
- [x] Current player-status artifact. — `player_status` 1.0, one row per canonical player, annotation only (ADR-043).
- [x] Import-graph enforcement of the intrinsic/market firewall.

**Exit gate: met.** The arbitrage artifact is reliable and transparent, no learned model is claimed, and baseline mode is explicit. Two findings are published rather than repaired, in the ADR-034/ADR-035 tradition:

- **the cohort rule's volume clause blocks every keeper-free cohort.** Filtering to redraft leagues necessarily shrinks the cohort-level draft count, so the selection falls through to its documented last resort and every row carries `cohort_insufficient` and therefore `low` confidence. Re-specifying that clause is a separate decision with its own evidence (ADR-045).
- **`wide_market_range` fires on 90% of rows** at this sample size. The flag is true and useless; Phase 6 should render `market_adp_low`/`market_adp_high` directly.

## Phase 6 — Frontend product

- [x] Implement compact global configuration controls + URL query state.
- [x] Implement Tier Board D3 visualization.
- [x] Implement Draft Rail D3 visualization.
- [x] Implement Tier table with search/filter/sort/export.
- [x] Implement Arbitrage table with search/filter/sort/export.
- [x] Implement methodology/freshness/source panel.
- [x] Implement player details/tooltip behavior.
- [x] Implement loading/error/degraded-source states from static metadata.
- [x] Implement responsive tablet/mobile layouts.
- [x] Implement keyboard/accessibility and reduced-motion requirements.
- [x] Add component/unit/E2E tests.

**Exit gate: met (2026-08-21).** Verified against the real 2026 build — 2,700 tier rows,
2,122 arbitrage rows, 315 status rows.

- 194 vitest tests and 39 Playwright tests, both green; frontend lint, typecheck and build clean.
- `npm run verify:board` cross-checks the rendered board against the artifact bytes on the live
  build: 40 tier rows, 25 chart marks, 30 arbitrage rows and 56 injury badges agree exactly.
- Built and end-to-end tested under both `/` and the project Pages base path `/jeisey-tiers/`.
- Eleven visual-QA screens captured, reviewed and committed to `docs/visual-qa/2026-08-21/`,
  with nine defects found and fixed (`REVIEW.md`).
- A tier is drawn as a band, not a line (ADR-046). Status is annotation only and a null injury
  designation never renders as "Healthy" (ADR-043). The shared low-confidence condition is
  explained once from build metadata rather than hardcoded (ADR-047).

**Not done, deliberately:** no Pages deployment, no repository visibility change, no schedule,
no model or methodology change. Those are Phase 7.

## Phase 7 — Production GitHub Actions + Pages

A prerequisite appeared that the original list did not anticipate. The retained capture store
lived on a `market-data` branch of this repository, and GitHub visibility is a property of a
repository, not of a branch — so going public would have published every retained vendor
payload. The store had to move to a separate private repository **before** anything else
(ADR-049), and that reordered the whole phase.

### 7A — retained-data migration (prerequisite)

- [x] Verify `jeisey/jeisey-tiers-market-data` exists and is private.
- [x] Verify the migration is byte-faithful: 40/40 files identical, tree hash `1e60a552…` on both sides.
- [x] `validate-market-history` passes on the migrated checkout (2 snapshots/35 files, 2 status captures/4 files).
- [x] Record the address in **one** place (`config/source-registry.yaml`) and read it from there (`.github/actions/market-data-store`).
- [x] Wire `MARKET_DATA_REPO_TOKEN` through `actions/checkout`, never through a shell.
- [x] Refactor `market-capture.yml` and every Phase-7 workflow onto the private store.
- [x] Amend ADR-038 with ADR-049 rather than rewriting it; update ARCHITECTURE, OPERATIONS, SECURITY_LICENSE, the store README and the source registry.
- [x] Prove a real capture persists to the private repository from Actions (run 32590470088).
- [ ] **Delete the old `market-data` branch from `jeisey/jeisey-tiers`** — owner-only; the git proxy rejects a push that deletes a ref and the GitHub tooling here has no ref-deletion method. Must happen **before** the visibility flip; steps in `docs/PHASE7_DEPLOYMENT.md` section 7.

### 7B — public-release audit (prerequisite)

- [x] Scan the tracked tree and all 56 commits reachable from `main` for secrets, `.env` files, key material, raw retained payloads and identifying paths.
- [x] Confirm `web/public/data/` and `data/historical/` are gitignored and were never committed.
- [x] Confirm no retained payload object is reachable from `main`.
- [x] Leave the software licence to the owner rather than choosing one on their behalf.

### 7C-7I — the phase as originally specified

- [x] Complete `ci.yml`.
- [x] Complete `daily-refresh.yml` with off-the-hour America/New_York schedule + manual dispatch (`cron: "17 7 * * *"`, `timezone: America/New_York`; capture → build green on runs 32594084631 and 32594602638).
- [x] Complete `retrain.yml` with candidate/promotion gates (run 32594603959 declined in 23s; candidate job skipped).
- [x] Configure official GitHub Pages build/deploy actions (`upload-pages-artifact@v3` in build; `configure-pages@v5` with `enablement: true` and `deploy-pages@v4` in the deploy job).
- [x] Apply least-privilege workflow permissions.
- [x] Add safe cache strategy.
- [x] Add last-known-good deployment behavior.
- [x] Add workflow summaries with source counts/freshness/model versions.
- [x] Prove failed critical validation cannot deploy (run 32594602638: `artifact.non_monotonic_quantiles` rejected the build, `upload-pages-artifact` skipped, deploy job skipped).
- [x] **Make `jeisey/jeisey-tiers` public** — owner action, completed 2026-08-22 after the `market-data` branch was deleted.
- [x] Deploy GitHub Pages — live at <https://jeisey.github.io/jeisey-tiers/> (run 32597324898); first *scheduled* deploy 2026-08-23 (run 32636603290). Needed one owner setting the workflow could not make for itself: Settings → Pages → Source → **GitHub Actions**.
- [x] Verify the **deployed** site with real 2026 data, not fixtures.
- [x] Create the Phase-8 human UI feedback backlog (`docs/PHASE8_UI_FEEDBACK.md`).
- [x] Record the multi-source ADP study as a Phase-8 research item (`docs/DATA_SOURCES.md` §16).

**Exit gate:** a clean GitHub-hosted run can build and deploy the site; daily refresh can update it; a forced data-quality failure leaves existing production intact.

**Status: met.** A clean GitHub-hosted run captures, builds, validates, packages and deploys the site; the daily schedule has updated it unattended; and a forced data-quality failure leaves the previous deployment serving. Evidence is in `docs/PHASE7_DEPLOYMENT.md`.

The last-known-good property has now held **three times in production**, and only once was it the rehearsed test — the other two were a real cohort-selection defect and a stale test assertion. That is the better evidence.

One defect was found and fixed, and only because the production path was run for the first
time: `PRODUCTION_COHORT_IDS` predated ADR-045's keeper-free requirement, so a routine daily
capture retained nothing the frozen rule could select. The rule was right and failed closed;
the capture set was wrong. Fixed by retaining what the rule needs, recorded as an ADR-045
amendment, and pinned by two new tests. **No threshold moved.**

### Post-deployment operations (7b, 7c)

Three defects surfaced by running the thing daily rather than by review, all fixed without
moving a threshold:

- **7b — three checks pinned the day's data instead of the contract.** `verify:board`
  asserted every arbitrage Trend cell renders an em dash (true only while the store was too
  young for ADR-042) and stripped injury badges with a pattern that assumed a body part is
  always reported; three frontend tests keyed on the masthead chip's freshness label, which
  expires 48h after the fixture's build time. All now assert against the artifact or an
  injected clock.
- **7b — `enablement: true` on `configure-pages` was a false promise.** Creating a Pages site
  is an admin API call and `GITHUB_TOKEN` never holds admin. Removed; the owner action is
  documented instead.
- **7c — the reviewed-alias escape hatch was never wired into production** (ADR-054).
  `config/identity-aliases.yaml`, `load_alias_map` and the resolver's alias path all existed
  and were tested, and the fixture pipeline used them, but `ffdraft.market.capture` — the
  module every real snapshot runs — never loaded the file. Wired through `build_snapshot`,
  with a negative-control test proving the wiring rather than the parameter.

- **7d — the registry's player universe was incomplete** (ADR-055). `load_rosters(2026)`
  omits 101 skill-position players who are on NFL rosters, including Stefon Diggs (WAS),
  Keenan Allen (IND) and Deebo Samuel Sr. (SF). Both market bridges terminate at
  `registry.lookup`, so those players were unreachable and their real ADPs could not join the
  board — which is what failed `arbitrage.top_board_priced` on 2026-08-26. The spine is now
  the roster plus nflverse's own player master, filtered to the season. Re-resolving the real
  capture: 258 → 263 resolved on the primary bridge alone.

  ADR-054's first diagnosis — that those players were free agents — was **wrong**, drawn from
  a single search against the roster file, and is retracted in place. It had recommended
  removing unrostered players from the published board, which would have deleted three
  genuine starters to cover our own defect.

- [ ] **ADR-056, `Proposed` — now measured, not speculative.** What `top_board_priced` measures
      (our board's coverage *by* the market, not the reverse) and its threshold inherited from
      the identity bar. Section 3 was rewritten from two runner probes of the live Fantasy
      Football Calculator endpoints:

      - **terms permit it** — the publisher documents the ADP REST API as free for personal and
        commercial use with attribution, and asks that it not be called more than daily;
      - **`teams` is accepted and ignored** — byte-identical per-player data across 8/10/12/14,
        so FFC supplies three scoring cohorts, not twelve, and every quote is league-size
        approximate;
      - **half-PPR is the prize** — the one cohort MFL structurally cannot express, with 7-30×
        the sample and a published `stdev` that MFL flags as unavailable;
      - **identity is the work** — `player_id` is FFC-internal and bridges to nothing, so a
        human-reviewed crosswalk of ~270 entries is required before a single price is used.

      §3.5 is a ten-step implementation path for a dedicated session.

Otherwise Phase 7 deliberately changed no methodology. No Phase-4 or Phase-5 threshold moved, no tier
or Monte Carlo rule was touched, MFL remains the sole production price source, and the Tier
Board's known vertical density was left alone rather than "fixed" during a deployment — it is
seeded in the Phase-8 backlog instead.

## Phase 8 — Hardening and quality

**Complete — 2026-08-31.** Two tracks: the owner's frontend redesign, and an adversarial audit
of everything five green production days do not prove.

### Track A — the redesign

- [x] Record the owner's 2026-08-31 feedback in `docs/PHASE8_UI_FEEDBACK.md`, with a status row per item.
- [ ] **Import the design through the Claude Design MCP.** *Blocked, owner action.* `/design-login` cannot run in a non-interactive session and the design app 403s an unauthenticated fetch; the implemented design language was derived from the owner's written brief instead. See `SESSION_STATE.md` "Known blockers".
- [x] A coherent HUD design system across shell, board, rail, tables, controls and card.
- [x] Tier Board: dense HUD rows, a compact interval glyph on the shared scale, collapsible tiers. 1,800px → 1,405px default, ~230px collapsed.
- [x] Tier groups stay soft — a band per tier on the shared scale, overlapping where the values do; no rule, arrow or cliff (ADR-035, ADR-046).
- [x] Draft Rail: the signed gap on a symmetric scale, reconsidered against the real 2026 board.
- [x] Player Detail: readouts first, methodology gone, deliberate desktop card / mobile sheet variants.
- [x] Copy audit — methodology once in Data, markers on the board (ADR-058).
- [x] Every removed disclosure still present, once, in Data; pinned by test.
- [x] Confidence and trend states data-driven; `low` → `medium` → `high` and a null trend all render from the same components.
- [x] No launch-only assumption left in copy, and a second fixture market condition so tests can no longer pin one.

### Track B — the audit

- [x] Production-run audit over seven daily-refresh runs — `docs/PHASE8_OPERATIONS_AUDIT.md`.
- [x] Verification-layer audit for today's-data assumptions; two high-severity findings fixed.
- [x] Full model/backtest/model-card review: 120 boosters re-hashed (0 mismatches), feature-set hash matched, forbidden-feature audit green, cards regenerated and deep-diffed (0 differences).
- [x] Monte Carlo convergence rule re-specified and evaluated — frozen first, run second (ADR-057).
- [x] `min_total_drafts` / ADR-052 resolved from current evidence, with no bound moved.
- [x] ADR-056 FFC evidence reconciled; **not** added to production V1.
- [x] Data-source failure/fallback drills — nineteen, offline (`tests/integration/test_failure_drills.py`).
- [x] Source freshness / schema-drift probe re-run on a GitHub runner — same status counts as the Phase-0 baseline; twelve schemas refreshed with **no column added, no column removed, one unused dtype change**.
- [x] Private-store security audit — `docs/PHASE8_SECURITY_REVIEW.md`; every credential property is now a test.
- [x] Dependency/security review — `pip-audit` and `npm audit` both clean; two unused dependencies removed.
- [x] Frontend performance review on a production-scale board; no launch-blocking problem.
- [x] Accessibility review — axe at WCAG 2.2 AA plus a manual keyboard pass; four real defects found and fixed, plus a fifth in the scan itself (it passed against a page that failed to load).
- [x] Browser compatibility — Chromium, Firefox and WebKit green on a runner.
- [x] Visual QA after the redesign — eighteen screens, `docs/visual-qa/2026-08-31/`.
- [x] Reproducibility run from a clean clone.
- [x] Documentation / source attribution review.
- [x] Resolve critical/high defects.

**Exit gate:** no known launch-blocking defect, leakage issue, source-rights ambiguity, or
broken primary flow. **Met**, with the design-import item above outstanding as an owner action
rather than a defect.

## Phase 9A — Claude Design frontend reskin

Inserted between Phase 8 and the launch release, and **not** a renumbering: phases 0-8 are
unchanged and the release checklist below is unchanged, only deferred. The reason for the split
is recorded in `docs/PHASE8_UI_FEEDBACK.md` item 1 — Phase 8 could not reach the owner's Claude
Design project and inferred a HUD language from the written brief instead. The owner supplied the
project's files directly, so the one Phase-8 item that was blocked became doable, and doing it
before tagging V1 is cheaper than tagging twice.

- [x] Read `Player Card HUD.dc.html` and `support.js` in full; extract the design language.
- [x] Record what the source contains and how it maps onto the product —
      `docs/DESIGN_SOURCE_MAP.md`.
- [x] Rebuild the token layer from the source; vendor its two OFL fonts.
- [x] Shell, controls and navigation.
- [x] Tier Board — artboard 2a on a desktop, artboard 2b on a phone.
- [x] Player detail — artboards 1c / 1a / 1b by viewport, dialog semantics unchanged.
- [x] Both tables, keeping semantic `<table>`, sorting, sticky headers and CSV.
- [x] Draft Rail and Arbitrage — no artboard exists for these; the language was extended.
- [x] Data and status presentation; methodology still stated once (ADR-058).
- [x] Tests: 234 vitest, 62 Playwright, including the tier-band/axis alignment invariant.
- [x] Visual QA: 28 screens plus an interleaved A/B performance record —
      `docs/visual-qa/2026-08-31-design/`.
- [x] Full frontend and Python gates.

**Exit gate:** met. No model, artifact or market value changed; `verify:board` reports zero
disagreements against the fixture build and against the matured-market build.

## Phase 9B — Launch release

**Not started, and deliberately untouched by Phase 9A.**

- [ ] Run final daily refresh.
- [ ] Capture final metrics and build metadata.
- [ ] Verify all supported presets visually and via artifact validation.
- [ ] Verify CSV exports.
- [ ] Verify Pages URL and base-path behavior.
- [ ] Tag/release V1.
- [ ] Mark `SESSION_STATE.md` with production model/data versions and known limitations.

**Exit gate:** all acceptance criteria in `PRD.md` Section 21 pass.
