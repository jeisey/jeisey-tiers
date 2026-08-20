# Fantasy Draft Intelligence — Coding-Agent Handoff Bundle

This bundle is the source-of-truth specification for building a public, daily-refreshed fantasy-football draft intelligence website that materially improves on the product pattern popularized by `borisachen/fftiers`.

The product has two analytically separate outputs:

1. **Intrinsic Tier Board** — model player value without using ADP/ECR as inputs, quantify uncertainty, convert outcomes to league-aware value above replacement, and discover natural contiguous tiers.
2. **Draft Arbitrage Board** — compare intrinsic value to observed draft-market cost and rank mispricings using historically validated surplus modeling.

The intended production architecture is static and GitHub-native: Python data/model pipelines + GitHub Actions + React/TypeScript/Vite + D3 + TanStack Table + GitHub Pages. No runtime backend is required for V1.

## What is in this bundle

| File | Purpose |
|---|---|
| `PRD.md` | Canonical product requirements and launch criteria |
| `AGENTS.md` | Canonical coding-agent operating instructions |
| `CLAUDE.md` | Thin Claude Code bridge to `AGENTS.md` |
| `PROMPT_START_HERE.md` | Copy/paste bootstrap prompt for a frontier coding agent |
| `TASKS.md` | Phase-gated implementation checklist |
| `SESSION_STATE.md` | Cross-session state template |
| `docs/ARCHITECTURE.md` | System architecture, repo shape, execution paths |
| `docs/DATA_SOURCES.md` | Source registry, legal/availability gates, fallbacks |
| `docs/DATA_CONTRACTS.md` | Canonical entities, IDs, schemas, validation rules |
| `docs/MODELING.md` | Tier and arbitrage modeling methodology and evaluation |
| `docs/UX_SPEC.md` | Detailed visual/product behavior |
| `docs/IMPLEMENTATION_PLAN.md` | Methodical build phases with exit gates |
| `docs/TEST_STRATEGY.md` | Unit/integration/data/model/UI/E2E test requirements |
| `docs/OPERATIONS.md` | Actions cadence, failure handling, observability, reproducibility |
| `docs/SECURITY_LICENSE.md` | Secrets, permissions, dependency, licensing, attribution rules |
| `docs/DECISIONS.md` | Architecture decision record index |
| `docs/AGENT_MODEL_NOTES.md` | Current frontier-agent capabilities and harness guidance |
| `config/league-defaults.yaml` | Supported league/scoring presets |
| `config/source-registry.yaml` | Machine-readable source policy registry |
| `schemas/*.schema.json` | Public artifact contract schemas |
| `repo-tree.txt` | Target repository structure |
| `MASTER_SPEC.md` | Concatenated human/agent-readable master specification |

## How to use this with a coding agent

1. Put this bundle at the root of a new repository.
2. Give the agent `PROMPT_START_HERE.md` as the initial task.
3. The agent must read `AGENTS.md`, `PRD.md`, `TASKS.md`, and the relevant docs before touching code.
4. The agent must implement phases in order and satisfy each exit gate before progressing.
5. The agent must update `TASKS.md` and `SESSION_STATE.md` after every meaningful phase or handoff.
6. Source/API uncertainty must be resolved in Phase 0. The agent may not invent endpoints, licenses, historical coverage, or model results.

## Repository status

Phase 0 (source, legal, and feasibility proof) completed 2026-08-17. Phase 1 (scaffold, contracts, identity, adapters) completed 2026-08-18. Phase 2 (historical feature dataset) and Phase 3 (intrinsic baselines and evaluation harness) completed 2026-08-19. **Phase 4 (production DraftValue, simulation and tiers) implemented 2026-08-19, with two frozen gates measured as failing** — the Monte Carlo draw count is a predeclared fallback rather than a converged count (ADR-034), and tier boundaries are not stable enough to meet the declared threshold (ADR-035). **Phase 5 (market snapshots and arbitrage) completed 2026-08-20.** Every shortfall is published as a limitation rather than repaired by moving a threshold; see `TASKS.md` for the exit-gate detail.

There is a model and an arbitrage board now. Phase 1 built the skeleton that makes bad joins and schema drift hard; Phase 2 built the time-correct data asset — 11,604 leakage-audited player-seasons across 2014-2025 with independently computed STD/HALF/PPR labels and market-independent realized VORP; Phase 3 built the rolling-origin evaluation harness and the baselines worth beating; Phase 4 turned that into a production intrinsic model, a deterministic Monte Carlo simulation of league-relative value, and natural contiguous tiers. The model passed its single sealed-holdout evaluation on 2025; the tiers are honest about being groups rather than hard lines.

Phase 5 added the market half without letting it near the model. Point-in-time ADP snapshots are retained append-only on a dedicated `market-data` branch, because MyFantasyLeague's historical export is a season aggregate recomputed at request time and a price we do not capture today can never be reconstructed. The arbitrage board is a transparent fair-rank-versus-ADP baseline and says so; no learned model is claimed and no surplus or probability is invented. Current injury and roster status ships as a separate artifact that annotates a row and can never move one. The cohort study found dynasty rookie drafts inside the ADP aggregate — rookies priced three to five times earlier than in real redraft leagues, while veterans did not move — so a redraft board is now priced only by keeper-free cohorts. There is still no deployed site.

| Path | Purpose |
|---|---|
| `src/ffdraft/` | Config, typed contracts, source adapters, canonical identity, quality gate, artifact serializers, CLI |
| `web/` + root `package.json` | Vite/React/TypeScript skeleton with a typed, version-checked artifact loader |
| `schemas/` | Public artifact contracts, plus the shared `artifact_envelope` wrapper |
| `config/` | League presets, source policy registry, human-reviewed identity aliases |
| `src/ffdraft/anchors.py` + `features/` + `scoring/` + `labels/` + `simulation/` + `leakage.py` | The Phase-2 historical dataset: anchor rule, feature dictionary, eligibility, lagged aggregates, scoring engine, VORP labels, leakage audits |
| `docs/FEATURE_DICTIONARY.md` | Every model feature with its formula, sources and availability rule — generated from code, kept current by a test |
| `src/ffdraft/modeling/` | The evaluation harness, the frozen Phase-4 decision rules, calibration, the candidates, production model training/serving, and the generated cards |
| `src/ffdraft/simulation/` | The one starter/FLEX allocation, the deterministic quantile sampler, and the simulated-VORP draw loop |
| `src/ffdraft/tiers/` | Contiguous natural tier segmentation, its documented alternative, and the stability bootstrap |
| `src/ffdraft/market/` | MFL cohorts and the frozen sufficiency rule, point-in-time capture, snapshot manifests, cohort measurement, market trend, the current price layer |
| `src/ffdraft/retention/` | The append-only content-addressed capture store, shared by market and status so neither imports the other |
| `src/ffdraft/arbitrage/` | The frozen A0 baseline, the data-quality confidence rubric, the board build, the generated method card |
| `src/ffdraft/status/` | The Sleeper capture and the annotation-only `player_status` artifact |
| `models/` | Versioned production model artifacts (text boosters plus JSON metadata, no pickle) and the generated model card and tier-method report |
| `docs/experiments/` | The committed evidence behind every promotion decision |
| `tests/` | Network-free Python tests across unit / contract / integration / data-quality / leakage / model |
| `tests/fixtures/pipeline/` | Synthetic source fixtures covering every documented edge case |
| `tests/fixtures/historical/` | Synthetic nflverse-shaped history spanning both depth eras |
| `tests/fixtures/artifacts/` | Committed golden artifacts, also read by the frontend tests |
| `.github/workflows/ci.yml` | Python and frontend gates; fixtures only, no vendor network |
| `.github/workflows/market-capture.yml` | The live point-in-time capture, triggered by bumping `.github/market-capture.request` |
| `docs/market-cohorts/` | The committed cohort measurement, reproducible offline from a retained snapshot |
| `scripts/source_probe.py` | The Phase-0 evidence generator |
| `scripts/capture_source_schemas.py` | Records upstream schemas for the Phase-2 loaders |

Verified source decisions live in `docs/DATA_SOURCES.md` sections 13 and 14, and in `config/source-registry.yaml`; the reasoning is in ADR-009 through ADR-023 in `docs/DECISIONS.md`. Headline outcomes: the free source stack covers every required role; **arbitrage launches in deterministic baseline mode** because historical ADP is plentiful but not point-in-time; **market identity resolves by id alone** through two independent bridges that fail closed when they disagree; and the historical dataset's **draft anchor is 23:59:59 America/New_York on the Tuesday before Week 1**, with a preseason universe built only from evidence that predates it.

```bash
# Python
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                                            # network-free
uv run pytest -m live                                    # opt-in live source smoke tests

# The Phase-1 fixture pipeline: fixtures -> adapters -> identity -> contracts -> artifacts
uv run ffdraft build-fixture-artifacts --out web/public/data
uv run python -m ffdraft.cli validate-artifacts web/public/data

# The Phase-2 historical dataset. `build-historical` is the only command that needs the
# network; the other two read what it wrote.
uv run ffdraft build-historical --last-season 2025 --git-sha "$(git rev-parse --short HEAD)"
uv run ffdraft validate-historical data/historical
uv run ffdraft feature-dictionary

# The Phase-3 evaluation harness. Offline; reads what build-historical wrote. Season 2025
# is the sealed final holdout and an ordinary run cannot reach it.
uv run ffdraft evaluate-intrinsic --git-sha "$(git rev-parse --short HEAD)"

# The Phase-4 development studies, in order. Each writes a committed experiment report and
# each decision is made by a rule frozen before its evidence existed. See
# docs/OPERATIONS.md "Phase-4 commands" for the whole sequence, including the single sealed
# final-holdout evaluation and the production build that follows it.
uv run ffdraft evaluate-distribution --git-sha "$(git rev-parse --short HEAD)"
uv run ffdraft evaluate-simulation   --git-sha "$(git rev-parse --short HEAD)"
uv run ffdraft evaluate-tiers        --git-sha "$(git rev-parse --short HEAD)"

# The Phase-5 market path. Exactly two commands touch a vendor, and they run on a GitHub
# runner (ADR-009) via .github/workflows/market-capture.yml. Everything else reads the
# retained bytes, which is what makes the analysis reproducible and diffable.
git clone --branch market-data <this repo> ../market-data
uv run ffdraft validate-market-history ../market-data --season 2026
uv run ffdraft measure-market-cohorts --store ../market-data
uv run ffdraft build-current   --store ../market-data     # tiers, projections, player_status
uv run ffdraft build-arbitrage --store ../market-data     # the A0 board
uv run ffdraft arbitrage-card

# Frontend
npm ci
npm run lint && npm run typecheck
npm run test -- --run
npm run build
```

Artifacts written to `web/public/data/` and the historical dataset in `data/historical/` are generated and gitignored; both are reproducible from code plus source releases, and the historical build writes a manifest of content hashes so a rebuild that disagrees is detectable. The `market-data` branch is *not* in this working tree — it shares no history with `main`, is never merged, and holds the retained captures the market path reads. `ffdraft config-check` prints the loaded configuration and which MFL client secrets are present — never their values.

Data attribution: player/roster/depth-chart/stat data from **nflverse** (`nflreadpy`), expected fantasy points from **ffopportunity** (CC-BY-SA-4.0), market ADP from **MyFantasyLeague.com**, current player status from the **Sleeper** API (non-commercial use only).

## Product defaults

- Audience: redraft fantasy-football players preparing draft-day sheets.
- Core positions: QB, RB, WR, TE. K and D/ST are a non-blocking extension after the core launch.
- Scoring: Standard, Half-PPR, PPR.
- Default league: 12 teams, 1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX, 5 bench.
- Core model independence rule: **ADP, ECR, expert ranks, market prices, and FantasyCalc values are forbidden inputs to the intrinsic projection/tier model.**
- Cadence: daily public refresh; weekly/manual model retraining during active draft season.
- Hosting: GitHub Pages.
- Cost target: $0 recurring infrastructure cost using public/free data and standard GitHub-hosted runners in a public repository.

## Definition of “better than fftiers”

The product is not considered successful merely because it looks newer. It must improve along four measurable dimensions:

1. **Method:** intrinsic projections and uncertainty, rather than clustering average expert rank alone.
2. **Validation:** rolling out-of-time model evaluation with baselines, calibration, leakage tests, and published metrics.
3. **Actionability:** explicit market-vs-model arbitrage and expected-surplus ranking.
4. **Product utility:** interactive tier/arbitrage visualizations, sortable/filterable tables, exports, freshness/quality indicators, and reproducible daily updates.

See `PRD.md` for binding acceptance criteria.
