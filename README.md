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

**[V1.0.0 is released](https://github.com/jeisey/jeisey-tiers/releases/tag/v1.0.0)**
(2026-09-01). The site is live at **<https://jeisey.github.io/jeisey-tiers/>** and refreshes
itself daily at 07:17 America/New_York.

What it is, in one paragraph: an **intrinsic** fantasy-value model that never sees a market
price, a Monte Carlo simulation that turns its distribution into league-relative value above
replacement, contiguous tiers discovered from that value rather than declared, and — kept
strictly downstream — a deterministic arbitrage board comparing the resulting fair rank with
MyFantasyLeague ADP captured point-in-time into a private append-only store. Injury and roster
status from Sleeper annotates a row and can never move one. Nine scoring × league-size presets,
a static React frontend on GitHub Pages, CSV export, and no runtime backend.

The production model is `intrinsic-cb-hurdle-v1`, trained on 2014-2025 and promoted through a
sealed single-use holdout. Arbitrage is `a0_rank_gap_v1`, a transparent fair-rank-versus-ADP
baseline — **not** a learned model, and the repository says so everywhere rather than implying
otherwise. MyFantasyLeague is the only V1 market price source (ADR-053, ADR-056).

**Release 2 is in progress.** Phase 10 (multi-market draft intelligence) shipped 2026-09-03.
Phase 11 (the rest-of-season model, `intrinsic-ros-v1`) is an **offline** subsystem: it builds
point-in-time weekly snapshots, trains and validates a separate rest-of-season model against
four declared baselines and a frozen promotion rule, and produces rest-of-season value above
replacement with its own documented replacement interpretation. The model is **promoted and
accepted for Phase 12** (ADR-077) — after a readiness pass established that the clause it
originally failed was measuring the target's atom at zero rather than the model, and replaced it
with a rule stated on quantities that survive an atom (ADR-075). The original failure is
preserved, not repealed. Nothing from it is published yet — exposing it safely is Phase 12's
job — and the preseason model, its artifacts and the live site are untouched by it.

Two measured shortfalls ship as published limitations rather than as repaired thresholds: the
Monte Carlo draw count is a predeclared fallback rather than a converged count (ADR-034,
ADR-057), and tier boundaries do not meet their declared stability bar (ADR-035), which is why
the board draws a tier as a band and never as a line. The full list is on the site's Data view
and in `SESSION_STATE.md`.

### How it got here

Phase 0 (source, legal, and feasibility proof) completed 2026-08-17. Phase 1 (scaffold, contracts, identity, adapters) completed 2026-08-18. Phase 2 (historical feature dataset) and Phase 3 (intrinsic baselines and evaluation harness) completed 2026-08-19. **Phase 4 (production DraftValue, simulation and tiers) implemented 2026-08-19, with two frozen gates measured as failing** — the Monte Carlo draw count is a predeclared fallback rather than a converged count (ADR-034), and tier boundaries are not stable enough to meet the declared threshold (ADR-035). **Phase 5 (market snapshots and arbitrage) completed 2026-08-20. Phase 6 (the frontend draft sheet) completed 2026-08-21. Phase 7 (production Actions and GitHub Pages) implemented and validated 2026-08-22, with the site itself waiting on the owner to make this repository public. Phase 8 (hardening, audit and the frontend redesign) and Phase 9A (implementing the owner's Claude Design source) completed 2026-08-31. Phase 9B, the launch release, completed 2026-09-01 and tagged `v1.0.0`. Release 2 opened with Phase 10 (multi-market draft intelligence) on 2026-09-03, one criterion short on measured evidence (FantasyPros' free API tier serves ten rows and no ADP at all, ADR-064), Phase 11 (the rest-of-season model) on 2026-09-04, offline, and closed with Phase 12 (In-Season mode: the ROS Tier Board, the Sleeper-powered Opportunity Board, season-state orchestration and the `v2.0.0` release) on 2026-09-04 — with one clause of its definition of done open until the season's first week is actually built (`docs/releases/v2.0.0.md`).** Every shortfall is published as a limitation rather than repaired by moving a threshold; see `TASKS.md` for the exit-gate detail.

There is a model and an arbitrage board now. Phase 1 built the skeleton that makes bad joins and schema drift hard; Phase 2 built the time-correct data asset — 11,604 leakage-audited player-seasons across 2014-2025 with independently computed STD/HALF/PPR labels and market-independent realized VORP; Phase 3 built the rolling-origin evaluation harness and the baselines worth beating; Phase 4 turned that into a production intrinsic model, a deterministic Monte Carlo simulation of league-relative value, and natural contiguous tiers. The model passed its single sealed-holdout evaluation on 2025; the tiers are honest about being groups rather than hard lines.

Phase 5 added the market half without letting it near the model. Point-in-time ADP snapshots are retained append-only in a dedicated Git-backed store, because MyFantasyLeague's historical export is a season aggregate recomputed at request time and a price we do not capture today can never be reconstructed. The arbitrage board is a transparent fair-rank-versus-ADP baseline and says so; no learned model is claimed and no surplus or probability is invented. Current injury and roster status ships as a separate artifact that annotates a row and can never move one. The cohort study found dynasty rookie drafts inside the ADP aggregate — rookies priced three to five times earlier than in real redraft leagues, while veterans did not move — so a redraft board is now priced only by keeper-free cohorts.

Phase 6 put a product in front of all of it: a Tier board and a Draft rail drawn with D3 geometry and React DOM, two sortable tables, filtered and full CSV export, a methodology and freshness surface read entirely from build metadata, degraded-artifact states, layouts down to 390px, and keyboard and reduced-motion behaviour. The interface is built around the same three findings the modelling phases published rather than around them — a tier is drawn as a band because its boundaries were measured as unstable, an injury badge says outright that the projection never saw it, and the market-confidence label is explained as data quality with its reason pulled from the build rather than written into the source. It is validated against the real 2026 artifacts, and it builds and passes its end-to-end suite under the GitHub Pages project base path.

Phase 7 deployed it, and had to move the data before it could. The retained capture store lived on a branch of this repository, and GitHub visibility is a property of a repository rather than of a branch — there is no private branch inside a public one — so making this repository public would have published thousands of retained vendor payloads that are a private research cache under non-commercial terms. The store moved to a separate private repository first, byte-faithfully and verified as such, and only then did anything else happen. What deploys the site is a three-job graph — capture, build, deploy — in which the deploy job contains nothing but the Pages actions, so a failed gate anywhere upstream simply leaves the previous site serving. A stale correct site beats a fresh incorrect one, and that is the job graph rather than a rule anyone has to remember.

The one thing Phase 7 could not do for itself is flip this repository's visibility, which is an owner-only action. Everything downstream of it is wired: the deploy job enables Pages itself on its first successful run, and the expected address is `https://jeisey.github.io/jeisey-tiers/`.

Phase 8 hardened the whole system and rebuilt the frontend around the owner's review of the live site: a copy audit that put every methodology explanation in Data exactly once, a Tier board that collapses so a 300-deep board fits on a screen without faking narrower uncertainty, a rail whose geometry encodes the signed gap rather than an absolute pick axis, and an audit pass across production runs, the model artifact, simulation convergence, security, accessibility and three browsers. Its most useful finding was in the tests rather than the product: every market-sensitive test had been written against a uniformly low-confidence board with no trend history, a state production had already left, so the suite was pinning a launch condition rather than checking a contract.

Phase 9A finished the one Phase-8 item that could not be done. The redesign was supposed to implement the owner's Claude Design project; that project could not be reached from the session, so the HUD language was inferred from his written brief and the gap was recorded rather than papered over. He then supplied the design files directly, and the frontend now implements what they actually say — the tier board, both tables, the controls and three distinct player-card variants chosen by viewport, in the source's own typography and hairline construction. Four of the source's text tones fail WCAG AA at the sizes it uses them, so those are corrected and the deviation is written down; its per-card methodology paragraphs are the ones Phase 8 had already moved to Data, so they stayed there. No projection, tier, price or score changed, and `verify:board` compares the rendered board against the artifact bytes on every production build to keep it that way.

Phase 9B released it. The visible changes are small — the owner's logo replaces the typeset
wordmark, a favicon drawn from that same artwork, and both CSV buttons centre their label — but
the phase found that the repository could not check most of what a release checklist asks for.
`verify:board` compared the rendered page against the artifact bytes for one preset block out
of nine; CSV coverage was a test asserting a download fires rather than a file being right; and
nothing at all looked at the site *after* it deployed. Three verifiers now close that:
`verify:presets` resolves all nine blocks in the artifact and in the browser, `verify:csv`
downloads and parses all four exports and proves the filtered ones hold the visible subset
rather than the artifact, and `verify:live` checks a deployment rather than a build — every
asset under the deployed base path, the logo's decoded width, a shared link across a reload, and
that no request leaves the site's origin. The last runs from `live-smoke.yml`, which is
deliberately outside the production job graph: dispatch-only, gating nothing, because a schedule
would make an observation look like a gate. Three stale ADRs whose V1 disposition had already
been settled were closed at the same time; none is still awaiting review.

| Path | Purpose |
|---|---|
| `src/ffdraft/` | Config, typed contracts, source adapters, canonical identity, quality gate, artifact serializers, CLI |
| `web/` + root `package.json` | The React/TypeScript draft sheet: typed artifact loader, Tier board and Draft rail (D3 geometry, React DOM), tables, exports and the methodology surface |
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
| `.github/workflows/daily-refresh.yml` | The production path: capture → build → deploy, where a failed gate leaves the previous site serving |
| `.github/workflows/live-smoke.yml` | Dispatch-only smoke of the deployed site; gates nothing, deploys nothing |
| `web/tests/e2e/verify-*.mjs` | The release verifiers: rendered board vs artifact bytes, nine presets, four CSV exports, the live deployment |
| `scripts/make_favicon.py` | The favicon, generated from `web/src/assets/jt_logo.png`; CI runs it with `--check` |
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
git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data
uv run ffdraft validate-market-history ../market-data --season 2026
uv run ffdraft measure-market-cohorts --store ../market-data
uv run ffdraft build-current   --store ../market-data     # tiers, projections, player_status
uv run ffdraft build-arbitrage --store ../market-data     # the A0 board
uv run ffdraft arbitrage-card

# Frontend
npm ci
npm run lint && npm run typecheck
npm run test -- --run                            # 226 component and unit tests
npm run build                                    # root path
VITE_BASE_PATH=/jeisey-tiers/ npm run build      # GitHub Pages project path
npm run e2e                                      # 62 Playwright tests: behaviour, mobile, accessibility
npm run e2e:browsers                             # 36 smoke tests on Chromium, Firefox and WebKit
npm run verify:board                             # rendered board vs artifact bytes
```

Artifacts written to `web/public/data/` and the historical dataset in `data/historical/` are generated and gitignored; both are reproducible from code plus source releases, and the historical build writes a manifest of content hashes so a rebuild that disagrees is detectable. The retained capture store is a *separate private repository*, not a branch here — it holds the point-in-time captures the market path reads, and keeping it out of this repository is what makes a public application repository safe. Everything except rebuilding the production board runs without it. `ffdraft config-check` prints the loaded configuration and which MFL client secrets are present — never their values.

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
