# Session State

This file is durable cross-session state for coding agents. Keep it concise and factual.

## Current phase

Phase 1 — **complete** (2026-08-18). Phase 2 (historical feature dataset) is next and has not been started.

## Current target gate

Phase 2 exit gate: a reproducible historical modelling table with a documented feature dictionary and target dictionary, passing leakage tests, zero duplicate `(season, player_id)` keys, and acceptable missingness/identity quality by season and position.

## Last validated commit

The Phase-1 branch `claude/fantasy-draft-phase-1-dn51yp`, branched from the merged Phase-0 state on `main` (`c494d4c`).

Validation run locally; the same commands run in CI (`.github/workflows/ci.yml`):

```
uv sync --frozen
uv run ruff check .                 # clean
uv run ruff format --check .        # clean
uv run mypy                         # clean, 37 source files, strict
uv run pytest                       # 254 passed, 4 live deselected
uv run ffdraft config-check
uv run ffdraft build-fixture-artifacts --out web/public/data
uv run python -m ffdraft.cli validate-artifacts web/public/data   # gate: pass

npm ci
npm run lint                        # clean
npm run typecheck                   # clean
npm run test -- --run               # 31 passed
npm run build                       # clean; also verified with VITE_BASE_PATH=/jeisey-tiers/
```

## Production status

No production pipeline, model, artifact or site exists. What exists is the Phase-0 evidence base plus the Phase-1 skeleton:

- `src/ffdraft/` — config, contracts, sources, identity, quality, artifacts, pipeline, CLI.
- `.github/workflows/ci.yml` — Python and frontend gates, fixture-only, no vendor network.
- `web/` + root `package.json`/`vite.config.ts`/`tsconfig*.json` — Vite/React/TypeScript skeleton with a typed artifact loader.
- `tests/` — 254 network-free Python tests across `unit/`, `contract/`, `integration/`, `data_quality/`, `leakage/`; `web/tests/` adds 31.
- `tests/fixtures/pipeline/` — synthetic source fixtures; `tests/fixtures/artifacts/` — committed golden output.

**The fixture pipeline's valuation is not a model.** It reads projections from a fixture file, takes replacement value as the last startable player at a position, cuts tiers on a fixed VORP gap, and scores arbitrage by percentile rank. Every artifact it writes records `intrinsic_model_version="fixture-stub-0"`. It exists to exercise the serialization contract; Phases 4 and 5 replace those sections.

## Confirmed decisions

- Static GitHub Pages runtime.
- Python modeling/data + React/TypeScript/Vite frontend.
- Intrinsic model cannot use market/expert rank features.
- Arbitrage may use market data; historical intrinsic inputs must be OOF.
- Phase-gated implementation.
- **Arbitrage V1 ships in deterministic baseline mode** — historical ADP is dense but not point-in-time (ADR-010).
- **Current player status comes from nflverse rosters/depth charts plus Sleeper**, never `load_injuries` (ADR-011).
- **Market cohorts are approximate and must be labelled**; cohort mix is re-measured at the start of Phase 5 (ADR-012, amended 2026-08-18).
- **FantasyCalc disabled** (ADR-013). **FantasyPros-derived ECR is `benchmark_only`** after the owner's terms review — internal comparison allowed, redistribution and DraftValue use still forbidden (ADR-014, amended 2026-08-18).
- **Depth charts have two upstream schemas**; pre-2025 seasons have no draft-time depth observation (ADR-015).
- **Repository stays private through Phase 6**; visibility is a required Phase-7 decision (ADR-016).
- **MFL developer client provisioned**; the adapter reads env-variable names, transmits only the User-Agent, and never touches credentials on the unauthenticated ADP path (ADR-017).
- **Historical anchor depth**: point-in-time snapshots for 2025+, prior-season role proxy before that, explicit missingness for rookies. Week-1 depth is never a preseason proxy (ADR-018).
- **Canonical identity**: namespaced ids, two independent market bridges, fail closed on any ambiguity (ADR-019).
- **Public artifacts use the bundled Shape A** with a shared envelope (ADR-020).
- Source verification runs on a GitHub runner, not in an egress-restricted sandbox (ADR-009).

## Verified source facts a later phase should not re-derive

Full detail in `docs/DATA_SOURCES.md` section 13. The load-bearing ones:

- Market ADP: `https://api.myfantasyleague.com/{season}/export?TYPE=adp&JSON=1`, no auth. Fields `id, rank, averagePick, minPick, maxPick, draftsSelectedIn, draftSelPct`. **No standard deviation** — `adp_sd` stays null, dispersion comes from min/max pick. Response `timestamp` is generation time, not data-as-of. Both absences are enforced by tests.
- MFL honours `IS_PPR`, `FCOUNT`, `IS_MOCK`, `IS_KEEPER`; **ignores `DAYS`**; `CUTOFF` had no effect at 5.
- Market → canonical identity works by id alone: 100% of priced QB/RB/WR/TE (287/287), 95.4% of all priced rows; the 17 unresolved are MFL team-defence units. Two independent bridges agreed on all 331 rows where both resolved, with zero disagreements. The nflverse-native `espn_id` bridge is primary; `mfl_id` only exists in the dynastyprocess mirror, which publishes no licence.
- Sleeper `gsis_id` coverage is only 31.9%, so join **nflverse → Sleeper on `sleeper_id`**, never the reverse. Sleeper ids can carry whitespace (`" 00-0035057"`); trim and fail closed on malformed ids.
- `nflreadpy.get_current_season()` returned 2025 on 2026-08-17 while `get_current_season(roster=True)` returned 2026. Take the draft-target season from config, cross-checked against `load_rosters` and Sleeper `/v1/state/nfl`.
- 2026 current-state inputs are healthy: 2,930 roster rows (2,852 ACT), 915 skill rows with 100% `gsis_id` and 100% `depth_chart_position`; depth-chart snapshots refresh daily at ~07:25–08:25 UTC.
- Season-level `load_player_stats` carries every component the scoring engine needs, so STD/HALF/PPR are computed in-house rather than trusting upstream `fantasy_points`.

## Phase-1 facts a later phase should not re-derive

- **Adapters split into a pure `normalize` and an I/O `fetch`.** Every fixture test drives `normalize`; only opt-in live tests touch `fetch`. Keep that split — it is what makes the exit gate network-free.
- **Each adapter declares `required_source_columns` and `recorded_schema_fixture`.** A contract test asserts those columns exist in the Phase-0 recorded schema, which keeps adapters tied to measured evidence. Add both fields to any new adapter.
- **Column order in CSV comes from the JSON Schema**, not from Python. Reordering a schema's properties reorders the export.
- **Artifacts are byte-reproducible** for identical inputs. Anything nondeterministic (a wall clock, a set iteration) will show up as a failing golden test.
- **`QualityCheck` records rather than exceptions.** A build collects every finding, then the gate decides once. Do not convert checks into raises.
- **Ambiguity severity is contextual.** Producing an ambiguous outcome is the resolver working correctly, so the resolution stage records a warning; publishing one is critical, and a separate check enforces that. Do not collapse the two.
- **`FIXTURE_IDENTITY_COVERAGE_MINIMUM` (0.80) is a local relaxation for a deliberately adversarial 16-player fixture.** The production threshold in `ffdraft.quality.thresholds` stays at 0.95; a test asserts both.

## Open questions requiring evidence

- **Repository visibility** — deferred to Phase 7 by ADR-016. Nothing in Phases 1–6 may depend on the repository being public.
- **Market cohort mix closer to peak draft season** — re-measure at the start of Phase 5 (ADR-012 amendment). Cohort counts were taken on 2026-08-17 with only 410 aggregated drafts.
- **Anchor-date rule for Phase 2.** ADR-018 fixes the *depth* strategy; the anchor date itself still needs choosing and encoding (`docs/DATA_CONTRACTS.md` section 3 recommends the Tuesday before the opening game week). It must be applied historically without future knowledge, with a `feature_cutoff_rule_version` recorded per row.
- **Whether `load_ftn_charting` earns its CC-BY-SA obligation.** Not needed yet; decide only if a Phase-2 feature actually wants it.

## Known risks (non-blocking)

- **The fixture pool is 16 players, so every league preset produces identical replacement values.** That is arithmetically correct for a pool that small and is asserted as expected behaviour, but it means the preset dimension is exercised structurally rather than numerically until Phase 4 supplies a real pool.
- **Source-schema drift is detected, not prevented.** `check_source_schema` fires when an upstream column the adapter reads disappears; a column that changes *meaning* while keeping its name would pass. Re-run `scripts/source_probe.py` if more than a few weeks pass.
- **`mypy --strict` covers `src/ffdraft` only.** Tests are type-checked by neither mypy nor ruff's type rules; they are covered by execution.
- **The golden artifacts must be regenerated deliberately** when a contract changes: `uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000`. CI fails if they are stale.

## Repository notes

- **`BUNDLE_MANIFEST.txt` is a snapshot of the original specification bundle, not a live checksum.** Phase 1 verified that the frozen specification files still match it: `AGENTS.md`, `PRD.md`, `MASTER_SPEC.md`, `PROMPT_START_HERE.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/TEST_STRATEGY.md`, `docs/UX_SPEC.md`, `docs/BASELINE_FFTIERS_ANALYSIS.md` and `repo-tree.txt` are all byte-identical to the bundle. `CLAUDE.md` and `docs/MODELING.md` diverged before this session (the owner's clarification commit and Phase 0 respectively). The living records — `README.md`, `TASKS.md`, `SESSION_STATE.md`, `docs/DECISIONS.md`, `docs/DATA_SOURCES.md`, `docs/DATA_CONTRACTS.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/SECURITY_LICENSE.md`, `config/*` — are updated as the contract requires, so they are expected to differ. Use the manifest only to confirm the frozen set is untouched.
- **`ruff` 0.16 formats Python code blocks inside Markdown**, which silently rewrote `MASTER_SPEC.md` and `docs/ARCHITECTURE.md` the first time it ran. Markdown is excluded from ruff in `pyproject.toml`; do not remove that exclusion.
- **Regenerating the golden artifacts is a deliberate act**, not a fix for a red test: `uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000`. Read the diff first — it is the contract changing.

## Known blockers

None. Phase 2 can start immediately.

## Next action

Begin Phase 2 (`docs/IMPLEMENTATION_PLAN.md`): the draft-time anchor generator first, because every feature and every leakage test keys off it, then player-season eligibility, then the lagged feature families in the order that document recommends. Encode ADR-018's three depth states (`depth_observed_at_anchor`, `prior_season_role_proxy`, `depth_unavailable`) in the feature dictionary from the start, and write the pre-2025 leakage test before the features it guards.

Re-run `uv run python scripts/source_probe.py` (or dispatch `source-probe.yml`) if more than a few weeks have passed, since source contracts drift.
