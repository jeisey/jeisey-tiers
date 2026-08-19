# Session State

This file is durable cross-session state for coding agents. Keep it concise and factual.

## Current phase

Phase 2 — **complete** (2026-08-19). Phase 3 (intrinsic baselines and the evaluation harness) is next and has not been started.

## Current target gate

Phase 3 exit gate: an evaluation harness that can train and evaluate from scratch and emit machine-readable plus human-readable metrics, with at least one candidate beating the declared naive baseline without leakage and without a hidden positional collapse.

## Last validated commit

The Phase-2 branch `claude/fantasy-draft-phase-2-35a14u`, branched from the merged Phase-1 state on `main` (`7b050e7`).

Validation run locally; every network-free command below also runs in CI (`.github/workflows/ci.yml`):

```
uv sync --frozen
uv run ruff check .                 # clean
uv run ruff format --check .        # clean, 83 files
uv run mypy                         # clean, 57 source files, strict
uv run pytest                       # 510 passed, 4 live deselected
uv run ffdraft config-check
uv run ffdraft build-fixture-artifacts --out web/public/data
uv run python -m ffdraft.cli validate-artifacts web/public/data   # gate: pass

# Phase-2, network-bound (nflverse only)
uv run ffdraft build-historical --last-season 2025 --git-sha 7b050e7
#   -> 11,604 feature rows, 34,812 fantasy labels, 104,436 VORP labels
#   -> quality gate: pass (0 critical, 2 warning), 187 checks
uv run ffdraft validate-historical data/historical   # gate: pass (0 critical, 0 warning)

npm ci
npm run lint                        # clean
npm run typecheck                   # clean
npm run test -- --run               # 31 passed
npm run build                       # clean; also verified with VITE_BASE_PATH=/jeisey-tiers/
```

The Phase-1 golden artifacts were **not** regenerated: Phase 2 changed no public serialization contract, and a rebuild produces byte-identical files.

## Production status

No production pipeline, model, artifact or site exists. What exists is the Phase-0 evidence base, the Phase-1 skeleton, and the Phase-2 historical dataset:

- `src/ffdraft/` — config, contracts, sources, identity, quality, artifacts, pipeline, CLI (Phase 1) plus `anchors.py`, `scoring/`, `features/`, `labels/`, `simulation/`, `leakage.py` (Phase 2).
- `data/historical/` — the modelling dataset. Gitignored and reproducible; see "Phase-2 dataset" below.
- `docs/FEATURE_DICTIONARY.md` — every model feature with formula, sources and availability rule, generated from code and pinned by a test.
- `.github/workflows/ci.yml` — Python and frontend gates, fixture-only, no vendor network.
- `web/` — Vite/React/TypeScript skeleton with a typed artifact loader.
- `tests/` — 510 network-free Python tests; `web/tests/` adds 31.

**The fixture pipeline's valuation is still not a model** (`intrinsic_model_version="fixture-stub-0"`). Phase 2 did not change that; Phases 3-5 replace it.

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

## Open questions requiring evidence

- **Phase-3 training window.** nflverse roster coverage steps up at 2016, so 2014-2016 are systematically thinner universes (~670 rows against ~1,050). Whether to train on all twelve seasons, weight them, or start at 2017 is a Phase-3 decision that needs a measured comparison, not a guess.
- **Whether the 2025 snapshot era should be the final holdout.** It is the only season with observed anchor depth, which makes it both the most realistic proxy for production *and* the least comparable to the training seasons. Decide with the fold design, before tuning.
- **Repository visibility** — deferred to Phase 7 by ADR-016.
- **Market cohort mix closer to peak draft season** — re-measure at the start of Phase 5 (ADR-012 amendment).
- **Whether `load_ftn_charting` earns its CC-BY-SA obligation** — still open, and still not needed.

## Known risks (non-blocking)

- **The 2014-2016 era boundary is real and is reported as a warning, not hidden.** It comes from upstream roster coverage, not from this code. Any metric averaged across all twelve seasons mixes two different universes.
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

## Known blockers

None. Phase 3 can start immediately.

## Next action

Begin Phase 3 (`docs/IMPLEMENTATION_PLAN.md`). The first concrete step is the **chronological rolling-origin fold generator plus baseline B0**, in that order and before any candidate model:

1. build the fold generator over the 2014-2025 target seasons, with the final-holdout freeze rule enforced in configuration rather than by convention (`docs/TEST_STRATEGY.md` 2.5 requires a test proving the holdout cannot be used without an explicit flag);
2. implement B0 — prior-season fantasy PPG with age/availability shrinkage for veterans, a position/draft-capital prior for rookies — which the dataset already supports directly through `prev1_fantasy_ppg_ppr`, `age_at_anchor`, `prev1_games_missed`, `draft_round` and `rookie_flag`;
3. only then add metrics, bootstrap CIs and a candidate.

Two Phase-2 findings shape the fold design and should be settled before tuning: the 2016 roster-coverage step means 2014-2016 are thinner universes, and 2025 is the only season with observed anchor depth. Decide explicitly whether folds start at 2017, and whether 2025 is the holdout, rather than letting the defaults decide.

Rebuild the dataset first — `uv run ffdraft build-historical --last-season 2025` — because `data/historical/` is not in the repository.
