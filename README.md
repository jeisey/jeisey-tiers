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

Phase 0 (source, legal, and feasibility proof) completed 2026-08-17. **Phase 1 (scaffold, contracts, identity, adapters) completed 2026-08-18.** There is still no model, no production pipeline and no deployed site — Phase 1 builds the skeleton that makes bad joins and schema drift hard, and proves it end to end without touching a vendor API.

| Path | Purpose |
|---|---|
| `src/ffdraft/` | Config, typed contracts, source adapters, canonical identity, quality gate, artifact serializers, CLI |
| `web/` + root `package.json` | Vite/React/TypeScript skeleton with a typed, version-checked artifact loader |
| `schemas/` | Public artifact contracts, plus the shared `artifact_envelope` wrapper |
| `config/` | League presets, source policy registry, human-reviewed identity aliases |
| `tests/` | 254 network-free Python tests across unit / contract / integration / data-quality / leakage |
| `tests/fixtures/pipeline/` | Synthetic source fixtures covering every documented edge case |
| `tests/fixtures/artifacts/` | Committed golden artifacts, also read by the frontend tests |
| `.github/workflows/ci.yml` | Python and frontend gates; fixtures only, no vendor network |
| `scripts/source_probe.py` | The Phase-0 evidence generator |

Verified source decisions live in `docs/DATA_SOURCES.md` section 13 and `config/source-registry.yaml`; the reasoning is in ADR-009 through ADR-020 in `docs/DECISIONS.md`. Three headline outcomes: the free source stack covers every required role, **arbitrage launches in deterministic baseline mode** because historical ADP is plentiful but not point-in-time, and **market identity resolves by id alone** through two independent bridges that fail closed when they disagree.

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

# Frontend
npm ci
npm run lint && npm run typecheck
npm run test -- --run
npm run build
```

Artifacts written to `web/public/data/` are generated and gitignored. `ffdraft config-check` prints the loaded configuration and which MFL client secrets are present — never their values.

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
