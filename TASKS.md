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

Completed 2026-09-01. **`v1.0.0` is released**; see `SESSION_STATE.md` for the released state
and the exact run evidence.

### Release polish

- [x] Masthead brand is the owner's `web/src/assets/jt_logo.png`, imported through Vite so the
      URL carries the build's base; sized by height with `width: auto` (48/42/38px) so the
      ratio comes from the file. The image is the document's `<h1>` with `alt="Jeisey Tiers"`.
- [x] The Phase-9A wordmark, sub-label and command glyph are **removed**, in the shell and in
      the refusal screen. Tests assert zero `.wordmark`, `.wordmark-sub`, `.masthead-glyph`
      elements — hidden is not removed.
- [x] Favicon generated from that artwork by `scripts/make_favicon.py` — `favicon.ico`
      (16/32/48), `favicon.png`, `apple-touch-icon.png`. `--check` compares committed bytes and
      CI runs it, so an icon cannot drift from its generator.
- [x] Icons linked through Vite's base token, so they resolve under `/` and `/jeisey-tiers/`.
      CI's base-path build greps for a root-relative icon href and was confirmed to reject one.
- [x] Browser title reads `Jeisey Tiers — Fantasy Draft Intelligence`.
- [x] Both export labels centred. `.button` had no `display` of its own, so a blockified anchor
      put its label at the top of the 40px frame: measured **−14.5px** off centre before,
      −0.78px after, matching the `<button>` beside it.
- [x] Export controls keep a visible focus ring — asserted separately, so centring cannot be
      bought with a focus regression.

### ADR reconciliation

- [x] ADR-053 — **Accepted — V1 disposition; production integration deferred.** Both its own
      revisit conditions fired and both said add nothing.
- [x] ADR-056 — same status, with a header pointer to the Phase-8 disposition that supersedes
      §3.4. Its one genuinely open item is relabelled **deferred to post-V1** rather than
      resolved.
- [x] ADR-054 — status corrected: the "larger question" it said was awaiting review was
      retracted the same day and superseded by ADR-055.
- [x] No `Proposed` status remains in `docs/DECISIONS.md`, and no open ADR blocks V1.

### Release verification

- [x] Run final daily refresh — [33526105451](https://github.com/jeisey/jeisey-tiers/actions/runs/33526105451),
      **success**, on the merged `main` commit `5511370`. Dispatched with `skip_capture: true`
      because 2026-09-01 had already spent two MyFantasyLeague player-database requests and
      ADR-017 asks for at most one a day; that input skips only the two vendor calls, and the
      store checkout, its re-hash, the build, cohort selection, arbitrage, artifact validation,
      `verify:board` and the Pages deploy all ran in full on the release code.
- [x] Capture final metrics and build metadata — build
      `2026-intrinsic-cb-hurdle-v1-20260901T153049Z`, generated `2026-09-01T15:30:49Z`,
      quality gate **pass, 0 critical, 3 warnings**; 2,700 tier rows, 3,291 projections,
      1,945 arbitrage rows, 319 player-status rows (318 matched via Sleeper). Full record in
      `SESSION_STATE.md`.
- [x] Verify all nine supported presets — `npm run verify:presets` against the **deployed
      site**, run [33526715705](https://github.com/jeisey/jeisey-tiers/actions/runs/33526715705).
      All nine blocks pass both passes: 300 tier rows and 1,097 projections each, 8-11 tiers,
      212-220 priced arbitrage rows, Bijan Robinson at rank 1 in every block, controls
      reporting the requested state, no console error and no request leaving the origin.
- [x] Representative review of `PPR/redraft-12`, `HALF/redraft-10`, `STD/redraft-14` at 1440px
      and 390px — **42/42 measured checks pass** on the deployed board, with screenshots
      captured from the same navigation. On the live 300-row board both export labels measure
      `dx 0, dy −0.78` in a 40px frame, so the centring holds at production row counts.
- [x] Verify CSV exports — `npm run verify:csv` against the deployed site, **32/32 checks**.
      Both full exports byte-identical to the artifacts the build wrote; both filtered exports
      proved to hold exactly the visible rows in visible order under four simultaneous filters,
      with the filename's date taken from build metadata, a UTF-8 BOM, CRLF terminators and the
      published column order. RFC 4180 quoting is honestly reported **not exercised**: no value
      on this board contains a comma, quote or newline, and the escaping rule is pinned
      directly in `web/tests/csv.test.ts`.
- [x] Verify Pages URL and base-path behaviour — `npm run verify:live` via `live-smoke.yml`.
      The document, every script, stylesheet and icon href under `/jeisey-tiers/` answering 200,
      the four vendored fonts, the logo's decoded `naturalWidth` and aspect ratio, all five JSON
      artifacts and four CSVs, the three views, a player card, a shared query-state link across
      a reload, a 390px reflow, and **no request leaving the site's own origin**.
- [x] Tag/release V1 — `v1.0.0` at `5511370a52dc057471f9756f1da480e5756d914c`, the exact merged
      `main` commit the final refresh built and deployed. Cut by `release.yml` rather than by a
      local `git push`: the sandbox's git proxy answers 403 to any `refs/tags/*` push. The
      workflow refuses a commit that is not reachable from `main`, refuses to move an existing
      tag, and refuses empty notes. Release:
      <https://github.com/jeisey/jeisey-tiers/releases/tag/v1.0.0>; the annotated tag object
      resolves to `5511370a52dc057471f9756f1da480e5756d914c`.
- [x] Release visual QA — `docs/visual-qa/2026-09-01-release/`: the masthead at three
      viewports, both export controls at two, and the generated favicon at 16/32/48px over a
      near-black and a white tab bar, with the measurements beside them.
- [x] Mark `SESSION_STATE.md` with production model/data versions and known limitations.

**Exit gate:** met. The release polish shipped, no ADR is awaiting review, every local and
runner gate is green, the final refresh deployed through the ordinary production path, all nine
presets and all four CSV exports verify against the deployed site, and `v1.0.0` points at the
exact `main` commit that produced it.

## Phase 10 — Multi-market draft intelligence

**Implemented 2026-09-02; the exit gate is partially met.** One criterion failed on measured
evidence and is named below rather than rounded up, in the same shape Phase 4 used. Evidence:
`docs/source-probes/2026-09-02/phase10-report.md`; decisions ADR-060 through ADR-066;
commands, runs and measurements recorded in `SESSION_STATE.md`.

- [x] Re-probe FFC on a runner: current schema, `teams=` behaviour per player, window,
      volume, dispersion, cadence. — Four probe passes, all recorded. `teams=` is **still
      accepted and ignored**: per-player `adp`/`times_drafted` byte-identical across
      8/10/12/14 in all three formats, zero rows differing in any of the nine comparisons, so
      ADR-056 stands and no successor ADR was written. The window is **seven days**
      (`meta.start_date` 2026-08-26 → `end_date` 2026-09-02) against MyFantasyLeague's season
      aggregate. Volume 1,794 / 3,142 / 8,007 drafts; `stdev` a genuine standard deviation on
      221/221 rows.
- [x] Productionise FFC as an exact-scoring, league-size-unknown ADP source. — `FfcAdpAdapter`
      on `market_quote` 3.0, three cohorts, semantic checks that fail the build if a row ever
      claims a league size or calls its window cumulative. `high`/`low` ordered numerically
      rather than by their labels, with the observed orientation counted into the manifest.
- [x] Preserve MyFantasyLeague unchanged. — Its capture path was not edited. The adapter
      states what it always meant (`season_cumulative`, permanently null `adp_sd`, now
      enforced by its own check) and changes no value.
- [x] FFC identity linkage with a 90% continuation gate. — **222/222, 100.000%**, zero
      quarantined, zero top-300 unresolved, every row by exact normalized name and position.
      `phase10_linkage_v1`; alias file `config/market-aliases/fantasyfootballcalculator_adp.yaml`;
      report and quarantine under `docs/source-probes/2026-09-02/`.
- [x] Compact gold fixture and the required linkage tests. — 15 hand-checked synthetic cases
      plus 40 tests: determinism under permutation, no cross-position resolution, ties and
      thin margins quarantined, normalization proved not to collapse two distinct players,
      accepted aliases proved to resolve by id without rescoring, candidate recall measured,
      and a test that loosening the thresholds accepts rows the gold set marks ambiguous.
- [x] Generalise the market contracts without erasing semantics. — `market_quote` 3.0 adds
      signal type, observed cohort dimensions, aggregation window, a real standard deviation
      and rank-denominated consensus dispersion. Waiver behaviour gets its own contract
      rather than being forced into a price schema.
- [x] Sleeper: once-daily player map recorded, add/drop adapters implemented and retained. —
      Payload re-measured at 13.97 MiB / 12,226 records; `limit` and `lookback_hours` both
      measured as honoured; `search_rank` recorded as **not** ADP.
- [x] Source-relative arbitrage plus a separate FantasyPros consensus comparison. — One
      independent A0 comparison per ADP source, `ecr_gap` structurally separated from
      `rank_gap`, cross-market ADP-only diagnostics. The roadmap's own worked example
      reproduces exactly.
- [x] Fix the 300-row publication blind spot. — Three universes replace `head(300)`; tier
      depth versioned (`phase4_tier_depth_v1` retained, `phase10_tier_depth_v2` in force);
      surface reasons machine-readable; the coverage gate is critical; the original bug is a
      regression test, and a second test proves the gate is load-bearing by feeding it a
      pre-truncated board.
- [x] Market selector, FantasyPros columns and the expanded-board UX. — Selector derived from
      what the build published, window and observed dimensions printed beside it, per-source
      headers, ECR in its own column with its own gap, spread column, CSV columns naming
      source and signal.
- [x] Replace the Market Trend scalar with a themed mini chart. — Inverted y axis so up means
      earlier, sparse history stated in words below three points, direction in text as well as
      colour, points from a published artifact and never a vendor call. The scalar remains for
      sorting, CSV and the accessible summary.
- [x] Attribution in `Data` → `07 Sources and attribution`. — FFC and FantasyPros added,
      Sleeper's entry extended to name the trending feeds. The FantasyPros entry says the key
      never reaches the page and why no number is published.
- [!] **FantasyPros ADP and ECR publicly visible in Tier and Arbitrage.** — **Blocked on the
      API tier, not on this repository.** The provisioned key is on the free tier: every
      response carries `public_api_limited: true` and returns ten rows, no parameter widens
      it, and no endpoint the key can reach carries an ADP field at all. Forty players are
      reachable across the four core positions against a documented 407 receivers alone. The
      adapter, budget, cache, retention, identity bridges and fail-closed checks all ship and
      are tested; publication is withheld. ADR-064 records the exact, checkable condition
      under which it becomes a one-line change.
- [x] Live multi-source board. — **This was wrong when it was written.** It claimed nothing
      further was required in this repository; in fact the capture step, the `extra_quotes`
      argument, the published depth and the surface rule were all missing from the production
      path, so the first refreshes after the merge published a single-market 300-row board
      with three empty columns. Wired in ADR-067: FFC capture in `daily-refresh.yml`,
      `ffdraft.market.extra` into `build-arbitrage`, publication depth 500, and the
      full-board handoff that lets the surface rule reach beyond it.

**Exit gate: met.**

**Met.** FFC, MFL and FantasyPros have explicit dispositions with distinct semantics
preserved and fresh runner evidence behind each. FFC identity coverage is 100% against a 90%
gate with an empty quarantine. FantasyPros stays inside 50 requests/day and one per second,
never exposes its key, and handles truncation explicitly by refusing to publish. Sleeper's
cadence rule and both trending feeds are implemented and retained. ESPN remains disabled.
Cross-market summaries exclude ECR by construction. Contracts preserve source semantics.
Every new adapter has fixture and schema-drift tests. The frontend renders a Release 1 bundle,
a missing source and an absent trend series without breaking. The trend chart is
source-specific, sparse-history safe, accessible and theme-consistent.

**Not met — one criterion, on measured evidence.**

*FantasyPros is not publicly visible*, because the key's tier cannot serve a market. The
roadmap asked for ADP **and** ECR; there is no ADP available at any depth, and the ECR is
capped at ten rows per response. Publishing forty players as "FantasyPros ECR" would describe
a consensus the reader cannot get, and would make the surface gate — which requires 100% of
each enabled source's top 300 — unevaluable and therefore dishonest. The source is built,
retained and one config line from live.

Two consequences follow and are recorded rather than worked around: the required
`fantasypros_adp` comparison does not exist, and `market_top300_fantasypros_*` surface
reasons are declared in the vocabulary but never emitted.

**Scope boundaries held:** no learned arbitrage model, no blended ADP/ECR score, no
market-informed intrinsic values, no ESPN scrape, no synthesized Sleeper ADP, no roster
sync, no rest-of-season model, no weekly rankings. Phase 11 was not started.

**Validation at the checkpoint:** `ruff`, `ruff format` and `mypy` (118 files) clean; `pytest`
**1,196** passed with the 4 live-network tests deselected; the fixture build 0 critical and
`validate-artifacts` 0 critical 0 warning over it; `npm lint` 0 errors, `typecheck` clean,
**270** vitest, a clean production build, **70** Playwright across `chromium`/`mobile`/`a11y`
and **13** more on `smoke-chromium`. `npm run e2e:browsers` (Firefox, WebKit) is runner-only in
this sandbox as it has been since ADR-059; it ran on the PR and passed, so every gate in the
steady-state command set has now been exercised against Phase 10.

## Phase 11 — Rest-of-season intrinsic model

**Implemented 2026-09-04; exit gate met after the production-readiness pass.** The candidate
beats every declared baseline on every primary metric, in development and on the sealed season.
It **failed `ros_promotion_v1`**, that failure is preserved in full (ADR-073), and the readiness
pass established that the failing clause was mis-specified for a zero-inflated target rather
than describing a model defect (ADR-075). Under the successor rule `ros_promotion_v2` — frozen
and committed before it touched any evidence — `RC1` is **promoted and accepted for Phase 12**
(ADR-077). Evidence: `docs/experiments/phase11-ros/experiment.md`,
`docs/experiments/phase11-ros/final_holdout.md`,
`docs/experiments/phase11-ros-value/value_study.md`, `models/cards/intrinsic-ros-v1.md`;
decisions ADR-068 through ADR-074.

- [x] Define the point-in-time training grain and freeze the cutoff rule. — `ros_cutoff_v1`:
      a snapshot through week N reads weeks 1..N of season Y and any earlier season, and
      predicts weeks N+1..`horizon.last_week`. Week 0 refused (that is the preseason model's
      grain); the last modelled snapshot is `last_week − 1`. **455,157 rows** across 2017-2025,
      15 snapshots per pre-2021 season and 16 from 2021.
- [x] Define ROS targets and horizons, reconciled against the scoring engine. — Remaining
      games, remaining points per appearance and their product, plus `remaining_horizon_weeks`.
      `points_to_date + actual_remaining_points` reproduces the existing season total with a
      worst absolute error of **1.14e-13** over 340,419 rows per preset, as a *critical* build
      check.
- [x] Engineer in-season feature families with availability rules. — **43** declared in-season
      columns in six families on top of Phase 3's frozen 78-column preseason block, inherited
      unchanged. Every one declares an availability rule; `docs/ROS_FEATURE_DICTIONARY.md` is
      generated from the code and a test asserts it is not stale. Injury and practice-report
      status stay out (ADR-070).
- [x] Prove the cutoff constructively. — Rebuild each sampled snapshot from a panel with its
      own future deleted and assert every in-season feature is identical; then assert the label
      built from that same panel is exactly zero. **27 cutoffs × 40 columns, clean.** It found
      a real defect on the way: universe membership was a season property, so a week-3 row
      existed for a player who signed in week 9 (ADR-068).
- [x] Build the chronological evaluation protocol. — Season-blocked expanding folds from 2017,
      development validation 2020-2024, 2025 sealed behind its own token. The evaluation cell
      is one week's board, so the paired bootstrap never resamples the same player sixteen
      times (ADR-072). **948 development cells, 253,197 scored rows.**
- [x] Declare four baselines and freeze the promotion rule before the candidate existed. — R0
      preseason-prorated, R1 current-rate, R2 shrinkage blend, R3 availability prior; the
      comparator is picked by the frozen rule (lowest development macro pinball) and is **R2**.
      The gate was committed in `c7815f9`, the candidate in `af30b38`.
- [x] Build and evaluate the candidate. — `RC1`, the availability × conditional-performance
      hurdle, reusing Q1's predeclared configuration with no tuning of any kind. Against R2:
      MAE **−2.4632** [−2.5305, −2.3958], pinball **−0.8084** [−0.8328, −0.7857], Spearman
      **+0.1203** [+0.1184, +0.1229]. All three intervals exclude zero.
- [x] Report the edge-case cohorts 11.3 names. — Twelve required cohorts, all reported, eleven
      clean. Rookies 16.69 → 14.87 MAE, weeks 1-3 19.48 → 15.18, returning-from-absence
      Spearman 0.294 → 0.311, high-capital rookies 29.83 → 26.66.
- [x] Touch the sealed season once, after the freeze. — 2025, 53,307 rows: MAE **−2.2497**,
      pinball **−0.7136**, Spearman **+0.1163**, all resolved. Every development conclusion
      reproduces out of time, the failure included. The holdout is spent.
- [x] Produce ROS value above replacement with a documented replacement interpretation. —
      Both interpretations measured over identical draws across twelve scenarios;
      `ros_replacement_v1` selects **`rostered_depth`** because the two disagree materially
      (worst fair-rank Spearman 0.9981, largest mean |Δrank| in the top 150 2.15, smallest
      top-50 overlap 0.940, largest single move 41 places). ADR-071.
- [x] Measure ROS simulation convergence and tier-boundary stability. — Both frozen Release 1
      rules reused unchanged, and **both fail**, exactly as they did preseason: no draw count
      in the ladder meets every tolerance (10,000 used as the declared fallback), and boundary
      agreement is **0.167** against a 0.500 bar. Membership is highly reproducible (bootstrap
      ARI 0.857) and tiers order realized value across **100%** of adjacent pairs. ADR-074.
- [x] Add offline per-player attribution diagnostics. — Exact TreeSHAP per component, with the
      summation identity asserted by a test. For Saquon Barkley at 2024 week 8, availability is
      led by `weeks_since_last_game` and performance by `touches_per_game_to_date`,
      `points_per_week_to_date` and `carry_share_to_date` —
      `docs/experiments/phase11-ros/attribution/2024-w08-RB-PPR.json`.
- [x] **Record the `ros_promotion_v1` verdict without repairing it.** — **Not promoted under
      v1**, and that stands. Clause 4 fires on `games_played_band / no_games`: candidate P10-P90
      coverage **0.964** against a [0.60, 0.95] band, on 131,844 rows. The threshold was not
      moved, the rule was not edited, and both remain in the codebase and in every report.
      ADR-073.

### Production-readiness pass (2026-09-04)

- [x] Revisit clause 4 from first principles. — An absolute symmetric coverage band is
      **statistically inappropriate** for this target. A P10-P90 interval covers 0.80 only for
      a *continuous* target; where a predictive distribution has an atom of mass `p >= 0.10` at
      its own tenth percentile a perfectly calibrated interval covers exactly **0.90**, and
      where `p >= 0.90` it collapses to a point and covers `p`. A test asserts all three cases,
      including the decisive one: **a perfectly calibrated forecaster with an interval of width
      zero breaches v1's ceiling.** The measured climatological reference agrees — calibration
      attains **0.843-0.926** across all twenty-two development cohorts and **0.926** on the
      zero-game cohort. Not one is near 0.80. ADR-075.
- [x] Define and freeze `ros_promotion_v2` before applying it. — Committed in `5e532c7`
      containing the rule and **no result**. Clauses 1-3 and 4a-4b are v1's unchanged; **4c**
      adds cohort mean pinball loss (proper and atom-safe); **4d** fails an interval only when
      it is wider than *both* the baseline's and climatology's; **4e** states coverage against
      the cohort's attainable coverage instead of a fixed 0.80. The tolerance is v1's own upper
      allowance applied symmetrically, which **tightens** the under-coverage side from 0.20 to
      0.15. A test asserts a cohort passing v1 at 0.62 coverage **fails** v2.
- [x] Apply v2 to the frozen development evidence. — Re-scored the prediction frame the original
      run wrote (`ffdraft evaluate-ros --predictions`): same 253,197 rows, **no refit**, macro
      metrics reproducing to the digit. **PROMOTED.** The three tightest clauses in the whole
      gate are `high_capital_rookie` (**0.015** headroom), `changed_team_in_season` (0.032) and
      `extreme_uncertainty` (0.052) — all *under*-coverage, all comfortable passes under v1 and
      near-failures under v2, which is the side v2 made stricter.
- [x] Investigate `in_season_arrival` on development evidence. — **No special handling, and no
      model change.** On 4,296 development rows `RC1` wins the proper score by **20.7%** (2.477
      against 3.122), wins ordering (0.552 against 0.492), edges MAE, and is far better
      calibrated: the baseline under-covers by **0.237** against attainable, carrying a 12.0-wide
      interval where climatology is 28.3. A fallback would swap a calibrated forecast for an
      overconfident one — and would change production outputs, which there is no sealed season
      left to evaluate honestly. ADR-076.
- [x] Review `returning_from_absence` as a production limitation. — No injury feature is added;
      ADR-070's four conditions are unchanged and unmet. `RC1` is better than the baseline on
      every axis, and **both are close to unable to order the cohort** (Spearman 0.311 against
      0.797 on the full universe). ADR-076 specifies a six-part disclosure contract Phase 12
      must implement: a machine-readable flag on the published artifact, `weeks_since_last_game`
      beside it, an explicit "no injury or practice-report information" statement, no
      presentation as medical status, no colour-only encoding, and the measured ordering
      weakness in the published limitations.
- [x] Force an explicit production-readiness outcome. — **`RC1 ACCEPTED FOR PHASE 12`**
      (ADR-077), with the six inherited limitations enumerated and the constraint that any
      change to the model's outputs invalidates the spent sealed season.

**Exit gate: partially met.**

**Met.** The weekly point-in-time leakage audit passes constructively. The snapshot builder is
deterministic and its content hash is recorded. Four simple baselines were declared and the
comparator chosen by rule. The promotion criteria were frozen and committed before the
candidate existed. The sealed season was touched exactly once, after the freeze. No
current-only data entered training: injury, practice-report and depth-chart sources are all
excluded with recorded reasons. Rookie/veteran, games-played-band and early-season slices are
all reported. Uncertainty calibration is reported *by cohort* rather than hidden by the pooled
zero-game rows — which is precisely how the gate failure was found. ROS simulation convergence
is measured. Tier-boundary stability is measured and represented honestly. Per-player
attribution is available offline.

**The promotion criterion, resolved rather than left ambiguous.** `RC1` failed
`ros_promotion_v1` and that record is permanent. The readiness pass then showed the failing
clause was measuring the target's atom at zero rather than the model, froze a successor stated
on quantities that survive an atom, and applied it to the same frozen predictions: `RC1` is
promoted under `ros_promotion_v2` and accepted for Phase 12. The successor loosens no bound v1
stated, adds one v1 lacked, and tightens the under-coverage allowance — and `RC1` passes it with
0.015 of headroom on its tightest clause. ADR-075, ADR-077.

**Scope boundaries held:** no opponent-specific start/sit advice, no lineup optimization, no
betting or props, no news-sentiment modelling, no user rosters, no market data inside
`intrinsic-ros-v1`, no published artifact, no frontend change. Release 1 and Phase 10 are
byte-identical: the only shared-code change is one optional parameter on the simulation draw
loop whose default preserves every preseason number.

## Phase 12 — In-season product mode, Opportunity Board, operations, Release 2 launch

**Implemented 2026-09-04.** The accepted rest-of-season model reaches disk and is served; the
product has two modes and the season decides which; the in-season bundle publishes
all-or-nothing beside the draft one. Evidence: `docs/releases/v2.0.0.md`,
`docs/visual-qa/2026-09-04-phase12/`, `models/cards/intrinsic-ros-v1.md` (production-fit section);
decisions ADR-078.

### The question that had to be answered before any UI

- [x] **Define and ADR the smallest legitimate production-fit protocol.** Phase 11 accepted
      `intrinsic-ros-v1` and persisted nothing: `RosHurdleCandidate` deliberately exposes no
      fitted object, so every prediction it ever made came out of a fold. Read literally,
      ADR-077's "any change to RC1's outputs needs a fresh sealed season" forbids fitting the
      accepted architecture at all — which would mean the model accepted for Phase 12 can
      never be served in Phase 12. **ADR-078** names the distinction that sentence always
      implied: a *production refit* varies the labelled rows and nothing else; a *methodology
      change* is everything else and stays governed by ADR-077 unchanged. The rule against
      actual model changes is not weakened; it is given the boundary it implied.
- [x] **Freeze the architecture as a hash rather than a promise.** `ffdraft.ros.frozen`
      restates the accepted configuration as constants and digests them
      (`d79133847436f04f`); a test compares every modelling field against
      `RosHurdleCandidate` itself, so an edited constant fails the suite rather than shipping
      under an accepted model's name. The fitter calls the evaluated candidate's own
      `fit_components` and `compose_draws`, so "the same code path" is a property of the call
      graph rather than a claim in a comment.
- [x] **Fit on the maximum permitted window, and record the lineage.**
      `models/production/intrinsic-ros-v1`: seasons **2017-2025**, **455,157** rows, 12 fitted
      groups, feature set `f5ad9df207795351`, schema `f0384c75cac8218a`, dataset content hash
      `1590cde5…`. Not a pickle: gzipped LightGBM text with a SHA-256 per booster and
      `mtime=0`, so two fits of the same model are byte-identical and a committed artifact is
      checkable against a rebuild.
- [x] **Make the window unable to widen by accident.** Two independent barriers: the sealed
      season still needs its token (given here, with the reason recorded on the artifact), and
      a training season at or after the serving season is refused outright — the one error
      that cannot be detected from the output.
- [x] **Keep the spent holdout spent.** `final_holdout.md` is untouched and was not re-scored.
      The card's production-fit section states in its first line that it carries no
      performance claim: the fit was scored on nothing, and every measured number belongs to
      the Phase-11 evidence.

### 12.1 Deterministic season-state orchestration

- [x] Rule `season_state_v1`, a pure function of the published schedule and a timestamp; no
      date anywhere in the code. Four states, and the product mode is the first Week-1
      kickoff and nothing else. Against the real 2026 schedule the transition lands at
      **2026-09-10T00:20Z** — the published opener, derived rather than typed.
- [x] A week counts as played six hours after its **last scheduled kickoff**, from kickoff
      times rather than a schedule row's `result`: a result lands whenever nflverse publishes
      it, and a state machine reading one would change its mind about the past.
- [x] Week-1 transition fixtures, written against a **synthetic** schedule so they prove
      something about 2027 as well as 2026. Nine cases including the several days in week 1
      when the mode is In-Season and `completed_week` is still 0.
- [x] Draft mode stays reproducible and reachable all season: `?mode=draft` is a user-visible
      override, in the URL like every other control, and the daily draft build never stops.

### 12.2 Production ROS pipeline

- [x] **Source freshness is a second, independent question.** `ros_source_freshness_v1`
      compares the clubs the schedule says played a week against the clubs present in that
      week's weekly statistics. The clock says the games are over; this says whether the rows
      arrived, and a build takes the smaller answer.
- [x] The deepest buildable cutoff is the last week with **no gap behind it**; a requested
      week deeper than the sources support is refused rather than built.
- [x] Current features under the frozen cutoff, with the panel truncated **before** it is
      built — a dense week grid over an unplayed week is indistinguishable, to every
      cumulative feature, from a week the player missed.
- [x] The preseason block is anchored and built from sources with the target season's own
      statistics deleted, so no in-season outcome can reach a draft-time feature.
- [x] Frozen inference, never training. `build-ros` loads the committed artifact and refuses a
      feature contract it was not fitted against.
- [x] ROS VORP under `rostered_depth` at the documented **10,000-draw fallback**, published
      with its verdict rather than as a converged value.
- [x] Versioned artifacts: `ros_tiers`, `inseason_opportunity`, `ros_build_metadata`.

### 12.3 ROS Tier Board

- [x] Every field the roadmap names, all `ros_*`: `ros_fair_rank`, `ros_position_rank`,
      `ros_expected_vorp`, the P10-P90 interval, `ros_expected_points`, `ros_expected_games`,
      `ros_tier`, `ros_uncertainty`, `current_status`, and the cutoff/model/freshness stamps.
- [x] **`fair_rank` and `ros_fair_rank` are never the same quantity anywhere.** The record has
      no field called `fair_rank`, the table has no column called `Rank`, and the player card
      shows the preseason rank, the current ROS rank and the change as three separate
      readouts labelled "two models, two orderings".
- [x] ADR-074 respected: a tier is a band. The board says so in the legend, the caption and
      the artifact's own `tier_boundary_statement`, and no edge is drawn as a fact.

### 12.4 ADR-076's disclosure contract, implemented exactly

- [x] Machine-readable `long_absence`, set by exactly `has_played_this_season` **and**
      `consecutive_weeks_missed >= 3`. A validator asserts **both** directions.
- [x] `weeks_since_last_game` published beside it, so the claim is checkable.
- [x] "No injury or practice-report information" stated on the artifact
      (`uses_injury_information` is a schema `const: false`) and rendered from it, so the
      interface cannot drift from what the model did.
- [x] The phrasing is the observable fact: **"Has not appeared for N weeks"**. Never a status,
      a designation, or medical knowledge — asserted in an e2e test that fails on the words
      "out", "questionable", "doubtful" and "injured".
- [x] Never colour alone: a glyph, the week count as text, and a full sentence for assistive
      technology, before any colour.
- [x] The measured ordering weakness (Spearman **0.311** against **0.797**) is published beside
      the rows it applies to, and the disclosed flag count is checked against the published
      rows.
- [x] Current injury/status appears as annotation in its own column, separated by a rule, and
      reaches no model input.

### 12.5 The in-season Opportunity Board

- [x] Sleeper add/drop retention built (`capture-behavior`) — Phase 10 wrote the adapter and
      consumed nothing; this is the retention half. Both feeds under one snapshot key, because
      a drop count is only interpretable against the add count from the same moment; a
      half-missing capture is refused rather than retained.
- [x] Add count, drop count, requested lookback and snapshot time preserved with their exact
      semantics: the window is the one **requested** (Sleeper confirms none), and the
      timestamp is a retrieval time rather than a data-as-of claim.
- [x] **Never called ADP, never a rank gap.** `net_add_count` is the only difference the board
      takes, and only because both sides are the same unit over the same window from the same
      feed. Three orderings, no blended score.
- [x] Phase 10's mode-aware surface universe reused, extended with `SurfaceMembership` so an
      in-season reason can be stated explicitly. A trending player or a snap-share promotion
      surfaces a player from beyond the tier depth, carrying a fair rank, a declared reason and
      **no tier**.
- [x] **Behaviour never alters an intrinsic value**, and that is checkable rather than
      promised: every intrinsic column is copied from the ROS board, and
      `cross_artifact.intrinsic_firewall` compares all seven of them over the published bytes.

### 12.6 Product UX

- [x] Draft mode: Tier Board, Arbitrage Board. In-Season mode: ROS Tier Board, Opportunity
      Board. `Data` shared.
- [x] One visual system, not a second application: the same section rhythm, numbered heads,
      legend strip, table and player card.
- [x] One obvious season-mode indicator that says *why* it is what it is, with an override.
- [x] Scoring/team controls, search, URL state, exports, freshness and methodology all shared.
      `view=auto` is the default, so one link is correct in both modes and an explicit view
      still wins.
- [x] Exports name the board **and the cutoff week**, and every in-season column is `ros_`-named
      so a spreadsheet holding both files has no two columns called `fair_rank`.

### 12.7 Operations and failure handling

- [x] Full Sleeper player map at most once a day (unchanged); the two trending endpoints are
      two requests per refresh; both feeds record their requested window.
- [x] Post-week refresh: a second Tuesday slot on the **same** job graph, because a separate
      pipeline would be a second description of the same build.
- [x] A failed behaviour source degrades the Opportunity Board's columns and nothing else.
- [x] A critical ROS input publishes **nothing**: the bundle is staged to a sibling directory
      and moved into place only once every artifact *and* the metadata validate. Writing
      straight into the output would have satisfied this for the artifacts and missed it for
      the metadata.
- [x] Last-known-good preserved: the deploy job is still the last job and nothing clears the
      live site.
- [x] Draft and ROS artifacts validate independently, with separate build ids, because they are
      produced by different models at different cutoffs on different cadences.

### 12.8 Release 2 hardening

- [x] Full Python and frontend suites green: `pytest` **1,414 passed** (4 live-network
      deselected), `ruff`/`mypy` clean over 240/152 files, `vitest` **291 passed**, `eslint`
      0 errors, `tsc` clean, `vite build` clean.
- [x] Deterministic ROS rebuild and inference checks: saving the same model twice produces
      **identical bytes** (`mtime=0`), a re-loaded artifact serves the same numbers as the
      in-memory one, and an altered booster is refused on load by its SHA-256.
- [x] Week-1 transition fixtures: `season_state_v1` is tested across the kickoff boundary in
      both directions, with the completion buffer, an unknown kickoff time resolving towards
      "not yet played", and the postseason weeks excluded.
- [x] Stale and missing-source tests: no complete upstream week is **critical**; a gap behind
      week N caps `available_through_week`; a behaviour snapshot older than the freshness
      window degrades rather than publishes.
- [x] Market-firewall audit extended to the in-season path: the ROS feature audit rejects any
      market-named input, and `cross_artifact.intrinsic_firewall` compares the copied intrinsic
      fields across the two published files.
- [x] Artifact schema and semantic validation for all three new contracts, including monotonic
      ROS quantiles under their published names and `disclosures.uses_injury_information` as a
      schema `const: false`.
- [x] CSV and export verification: in-season exports name the board and the cutoff week, carry
      `ros_fair_rank`, `long_absence` and `weeks_since_last_game`, and contain **no** bare
      `fair_rank` column. Asserted end to end from a real download.
- [x] Desktop, tablet and mobile visual QA: **41 screens** at 1440/900/390px in
      `docs/visual-qa/2026-09-04-phase12/`, capture script exit 0 (no console error, no
      horizontal page overflow at any width). `REVIEW.md` records the four defects the pictures
      caught that the tests did not.
- [x] Accessibility QA: the a11y project passes, and a **pre-existing** flake in it was
      root-caused rather than retried — seven controls declared `transition: all`, which
      animated the shared focus ring in over 160ms. A `--t-control` token names the surface
      properties instead, so a keyboard user's position appears at once.
- [x] Failure-path QA: behaviour absent (columns blank, values intact, notice shown), ROS
      artifact absent (the site stays in Draft mode and says so), and a partially-written
      bundle refused. All three have tests; the first two also have screenshots.
- [ ] **Deployed Pages verification against a live in-season build.** *Blocked until the season
      starts.* The 2026 opener is `2026-09-10T00:20:00Z`, so `season-state` resolves to
      `preseason_draft` and no in-season bundle can be produced from real data before the
      release. The base-path scenario is verified on the fixture build (`10-pages-base-path`)
      and the whole in-season path on the 2024 rehearsal; the first post-Week-1 refresh
      (`"40 12 * * 2"`) is the observation that closes this. Recorded as a release blocker in
      `docs/releases/v2.0.0.md`.

See `docs/releases/v2.0.0.md` for the measured results and the definition-of-done verdict
clause by clause.
