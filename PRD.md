# Product Requirements Document — Fantasy Draft Intelligence

**Status:** Build-ready specification  
**Version:** 1.0  
**Primary use case:** 2026+ redraft fantasy-football draft preparation  
**Deployment target:** Public GitHub Pages site with daily GitHub Actions refreshes

## 1. Executive summary

Build a public, zero-backend fantasy-football draft intelligence product with two complementary analytical systems:

- **Tier Board:** estimate each player's intrinsic fantasy value and uncertainty from football data only, translate that into league-aware value above replacement, then discover natural contiguous tiers and render them as a clean interactive S-tier-style draft board.
- **Arbitrage Board:** independently observe what the fantasy market is paying for players, then identify and rank discrepancies between intrinsic value and market cost. When sufficient historical market data exists, predict realized draft surplus out-of-time; otherwise launch a transparent deterministic market-gap baseline until the ML gate is passed.

The product must be useful as a draft-day sheet: fast, readable, sortable, filterable, exportable, explainable, and fresh. The website must remain static at runtime. Data acquisition, feature engineering, model training/inference, validation, artifact generation, and deployment occur in GitHub Actions.

## 2. Problem statement

Traditional expert-consensus tier products often group players by rank or consensus dispersion. They are useful summaries of expert opinion but do not independently estimate player outcomes, positional replacement value, or market mispricing.

This product should answer two different questions without conflating them:

1. **Intrinsic question:** "Given the football evidence available today, what is this player worth in my league?"
2. **Market question:** "Given that intrinsic value, is the current draft market overpaying or underpaying for him?"

The separation is non-negotiable. Market information entering the intrinsic model would weaken the causal/analytical distinction and make arbitrage circular.

## 3. Goals

### 3.1 Product goals

- Produce daily-updated pre-draft rankings and natural tiers for QB/RB/WR/TE.
- Produce daily-updated arbitrage rankings using at least one verified market ADP source.
- Support Standard, Half-PPR, and PPR scoring at launch.
- Support at least 10-, 12-, and 14-team 1QB redraft presets; 8-team support is desirable.
- Let users explore the visualizations, search/filter/sort tables, and export data.
- Make every public number traceable to a build timestamp, model version, league configuration, and source status.
- Keep recurring infrastructure cost at $0 for the default public deployment.
- Make the repository reproducible and highly legible to future coding agents and human contributors.

### 3.2 Analytical goals

- Produce calibrated probabilistic player outcome estimates, not only point estimates.
- Compute positional scarcity from modeled outcomes and league roster structure, not ADP.
- Discover tiers from the modeled value distributions without preselecting a fixed number of tiers.
- Validate models with rolling, time-aware holdouts.
- Prevent all temporal and market leakage through automated tests.
- Demonstrate that the final model beats declared naive baselines and that the arbitrage model beats a simple rank-gap baseline before claiming ML superiority.

### 3.3 UX goals

- Utility-first, minimalist interface; no decorative dashboard clutter.
- Immediate readability at laptop/tablet draft-table distance.
- Charts must expose useful structure that a normal ranked list hides.
- Tables must be first-class, not an afterthought.
- Mobile must be usable, but desktop/tablet draft use is the primary layout target.

## 4. Non-goals for V1

- Live draft-room synchronization or automated picks.
- User accounts, authentication, cloud database, or personalized persistent server state.
- Dynasty rankings.
- DFS optimization.
- Weekly start/sit rankings.
- Betting/prop recommendations.
- Natural-language news sentiment models.
- Paid-data dependency.
- Scraping sites whose terms or robots/usage policy do not permit the intended use.
- Marketing copy, articles, community features, ads, or social features.

Kicker and D/ST rankings are desirable compatibility additions but must not delay the core QB/RB/WR/TE launch.

## 5. Personas and jobs to be done

### Primary persona: prepared redraft manager

Needs a trustworthy draft sheet that goes beyond consensus, quickly shows tier cliffs, highlights value pockets, and can be exported or kept open during a draft.

Key jobs:

- "Show me who belongs in the same decision set at my current pick."
- "Show me where a tier cliff is coming."
- "Show me which players the market is meaningfully undervaluing."
- "Show me the uncertainty so I know whether the model has conviction."
- "Let me filter to a position and scoring format instantly."
- "Let me download the current table before my draft."

### Secondary persona: analytically curious fantasy player

Needs methodology, model performance, source freshness, and transparent explanation without requiring a notebook.

## 6. Functional requirements

### FR-001 — League configuration

The UI must expose at minimum:

- scoring: `STD`, `HALF`, `PPR`
- league size: `10`, `12`, `14` teams; `8` if supported by final artifact size/performance
- position filter: `ALL`, `QB`, `RB`, `WR`, `TE`

The default configuration is defined in `config/league-defaults.yaml`.

V1 does not allow arbitrary scoring rules. The architecture must not prevent a future custom-scoring calculator.

### FR-002 — Daily data refresh

A scheduled workflow must:

1. fetch/refresh permitted current sources;
2. validate schemas and source freshness;
3. resolve player identity;
4. build current features;
5. run production model inference;
6. perform deterministic Monte Carlo simulation;
7. compute VORP and tiers for supported presets;
8. fetch/normalize market data;
9. compute arbitrage outputs;
10. validate public artifacts;
11. build the frontend;
12. deploy only if all critical gates pass.

If a critical source fails, the last-known-good production site stays live. Never deploy corrupt, empty, or partially joined data just to satisfy cadence.

### FR-003 — Intrinsic Tier Board

The board must display natural contiguous tiers using visual labels beginning with `S`, then `A`, `B`, `C`, etc.

Each player mark/card must expose:

- player name
- team
- position and positional rank
- overall fair rank
- tier
- median or mean DraftValue/VORP
- floor and ceiling indicators (at least P25/P75; P10/P90 in detail view)
- uncertainty/volatility indicator
- model confidence/data-quality flag if applicable

The visualization must communicate distance within a tier, not merely place equal-sized cards in rows.

### FR-004 — Arbitrage Board

The board must compare intrinsic fair cost to market draft cost and visually encode the size and direction of the pricing gap.

At minimum expose:

- player
- position
- fair/model rank or fair pick
- market ADP
- market ADP spread if source provides it
- raw rank gap
- expected surplus VORP if the ML model passes promotion gates
- arbitrage score percentile 0–100
- probability of positive surplus when available
- confidence
- trend/change versus previous daily snapshot when enough snapshots exist

Positive value must be visually distinguishable from overvalued players without relying on color alone.

### FR-005 — Data tables

Both Tier and Arbitrage views must have associated sortable/filterable tables.

Required behaviors:

- stable multi-column sort
- text search
- position filter
- league/scoring preset filter
- numeric range filtering for key value columns where practical
- sticky table header
- column tooltips or concise glossary
- deterministic default sort
- no pagination requirement for <= 400 rows; virtualization optional

### FR-006 — Export

Users must be able to:

- download the full current tier dataset as CSV;
- download the full current arbitrage dataset as CSV;
- export the currently filtered table view as CSV client-side;
- see model/build date in exported files or accompanying metadata.

### FR-007 — Methodology and provenance

The site must expose a compact methodology/source panel with:

- last successful refresh timestamp
- production model version(s)
- public build SHA if available
- source status/freshness summary
- concise explanation of Tier Board vs Arbitrage Board
- explicit statement that ADP/ECR are not intrinsic-model features
- links/attributions required by data licenses

### FR-008 — URL state

Scoring format, league size, primary tab, position filter, and optional player search should be serializable into URL query parameters so a view can be bookmarked/shared without a backend.

### FR-009 — Accessibility

- Keyboard-accessible interactive controls.
- WCAG AA contrast target for text and important marks.
- Do not encode tier or arbitrage direction by hue alone; use labels, position, line direction, icons, or pattern/weight as secondary channels.
- Tooltips must have an accessible equivalent.
- Respect `prefers-reduced-motion`.

### FR-010 — Performance

Target on a normal broadband desktop:

- initial compressed JS/CSS/data payload kept intentionally modest; avoid shipping raw historical data to the browser;
- chart interactions remain responsive with at least 300 player records;
- no runtime API calls are required for the core experience;
- Lighthouse performance/accessibility regressions should be monitored in CI if stable enough.

## 7. Data requirements

### 7.1 Required data categories

**Football performance/history**

- weekly/season player statistics
- play-by-play-derived opportunity where useful
- rosters/team status
- historical/current depth charts
- draft capital
- combine/athletic measures where available
- age/experience
- Next Gen / advanced statistics where legally and temporally available
- expected fantasy opportunity (`ffopportunity`) where available

**Current-state context**

- current roster/team
- current depth-chart position
- current injury/status data from an allowed source

**Market data**

- current ADP with sample size and dispersion where possible
- daily snapshots retained during draft season
- historical ADP/draft-cost coverage sufficient for arbitrage ML training, or transparent fallback to a deterministic gap model

### 7.2 Source priority

Primary free stack target:

1. nflverse/nflreadpy
2. ffopportunity through nflreadpy/ffverse
3. verified MyFantasyLeague ADP endpoint(s)
4. Sleeper public API for current player/status sanity and optional trending
5. FantasyCalc only if its current terms fit the deployment's non-commercial status and the access method is permitted

FantasyPros-derived ECR may be used for internal benchmarking only if current terms permit the exact usage. It must not become a hidden production dependency.

See `docs/DATA_SOURCES.md`.

### 7.3 Identity requirement

Never join datasets solely on player name in a production transformation.

Preferred canonical ID is `gsis_id` where available. Maintain crosswalks for Sleeper/MFL/ESPN/etc. Name-based fuzzy matching may exist only in an explicit staging resolver that emits unresolved/ambiguous records for review; it must never silently choose among ambiguous players.

## 8. Intrinsic model requirements

Binding rules:

- market/expert data are prohibited features;
- all training examples must represent a reproducible draft-time information cutoff;
- validation is rolling/time-aware, never random player-season splitting across future/past;
- output must be probabilistic or quantile-based;
- direct total-points baseline and more sophisticated availability × performance candidate must both be evaluated before choosing production complexity;
- model choice is metric-driven, not architecture-driven;
- deterministic seeds and versioned feature schemas are required;
- model artifact promotion requires published validation metrics and leakage checks.

Core outputs per player/scoring preset:

- expected fantasy points
- P10/P25/P50/P75/P90 fantasy points or equivalent simulated quantiles
- expected/median VORP
- VORP quantiles
- fair overall rank
- positional rank
- uncertainty
- optional games-played distribution

## 9. Replacement value and DraftValue requirements

Replacement value must derive from modeled outcomes and the league's roster structure, not ADP.

For each simulation and league preset:

1. allocate required starting QB/RB/WR/TE slots across all teams;
2. allocate FLEX slots to the best eligible remaining RB/WR/TE outcomes;
3. define positional replacement baseline from the best player remaining after starter/FLEX allocation (with a documented deterministic tie rule);
4. compute each player's VORP against the position-appropriate replacement baseline for that simulation.

Overall intrinsic ranking defaults to expected/median VORP. Any future risk-adjusted ranking must be explicit and user-selectable rather than silently embedding subjective upside preference.

## 10. Tiering requirements

Tiers must be contiguous in fair-rank order and derived from the simulated VORP distributions.

The production algorithm may use multidimensional change-point segmentation (recommended initial candidate: PELT/RBF on normalized distribution summaries) or another statistically defensible contiguous segmentation method.

The number of tiers must not be manually fixed per position.

Promotion requirements:

- bootstrap stability test;
- sensitivity test to reasonable penalty/hyperparameter perturbations;
- monotonic tier ordering on holdout actual VORP;
- no pathological singleton proliferation; legitimate statistically isolated S-tier singletons are allowed;
- documented minimum/maximum display handling for deep ranks.

See `docs/MODELING.md`.

## 11. Arbitrage model requirements

### 11.1 Strict separation

The arbitrage pipeline may consume intrinsic model outputs and market data. The intrinsic pipeline may not consume arbitrage/market data.

### 11.2 Historical target

Preferred realized target:

`realized_surplus_vorp = actual_player_vorp - expected_actual_vorp_for_players_drafted_near_that_market_cost`

The expected market-cost curve must be estimated only from information/training seasons allowed by the rolling evaluation fold.

### 11.3 Historical intrinsic features

When training the arbitrage model, historical intrinsic predictions must be **out-of-fold / rolling-origin predictions**. Never feed a historical player a DraftValue prediction produced by a model trained on that player's target season.

### 11.4 ML feasibility gate

Before calling the arbitrage system "ML":

- verify sufficient historical ADP coverage and stable identifiers;
- define at least three chronological holdout seasons when available;
- compare against simple `ADP - fair_rank` and fair-value-only baselines;
- require improvement on declared metrics.

If the historical market dataset fails this gate, V1 launches a transparent deterministic arbitrage score using fair rank vs market ADP, ADP dispersion, and market trend. It must be labeled baseline/heuristic, not ML.

### 11.5 Output

- fair rank / fair pick
- market ADP
- ADP spread/sample size where possible
- fair-vs-market gap
- expected surplus VORP (only after ML promotion)
- `p_positive_surplus` (only after calibrated model promotion)
- arbitrage percentile score
- market trend
- confidence/data sufficiency flag

## 12. Evaluation framework

### 12.1 Intrinsic ranking/projection metrics

At minimum:

- MAE/RMSE on fantasy points for point-estimate baselines
- pinball loss for modeled quantiles
- interval coverage for P10–P90 / P25–P75
- Spearman rank correlation of predicted DraftValue vs realized VORP
- Kendall tau as a secondary rank metric
- NDCG or top-K utility metric for the most draft-relevant ranks
- positional calibration/error slices
- rookie vs veteran slices
- bootstrap confidence intervals around material comparisons

### 12.2 Tier metrics

- tier bootstrap stability (e.g. adjusted Rand index or boundary agreement)
- holdout actual-VORP monotonicity by tier
- within-tier vs between-tier separation
- rate of unstable boundaries under perturbation

### 12.3 Arbitrage metrics

- Spearman/information coefficient between predicted and realized surplus
- MAE/RMSE if predicting continuous surplus
- Brier/log loss and calibration if predicting positive-surplus probability
- top-decile realized surplus uplift versus all drafted players
- top-decile uplift versus simple `ADP - fair_rank` baseline
- year-by-year results, not only pooled metrics

### 12.4 Comparison to consensus

Where legally permitted, use historical FantasyPros ECR as a **benchmark only**. Any public claim that this product "beats consensus" requires a reproducible out-of-time table and confidence interval. If it does not beat consensus, say so; the product can still be better on transparency, uncertainty, interactivity, and arbitrage usefulness.

## 13. Technical stack

### Data/model

- Python 3.12+
- `uv` for dependency and lockfile management
- Polars + PyArrow
- nflreadpy
- scikit-learn
- LightGBM as initial boosted-tree candidate
- `ruptures` as initial tier change-point candidate
- Pydantic or dataclasses for typed internal contracts where useful
- Pandera or explicit Polars schema/data-quality checks
- pytest
- ruff
- mypy or pyright if compatible with chosen stack

Do not add heavyweight orchestration frameworks.

### Frontend

- React
- TypeScript strict mode
- Vite
- D3 for bespoke visualizations
- TanStack Table for interactive tables
- lightweight CSS approach; no heavy design system required
- Vitest + Testing Library
- Playwright for critical E2E paths

### CI/CD/hosting

- GitHub Actions
- GitHub Pages using official Pages actions
- standard GitHub-hosted Linux runners
- no runtime server/database

## 14. Public artifact contracts

The build must emit versioned, schema-validated static artifacts, including at minimum:

- `public/data/tiers.json`
- `public/data/tiers.csv`
- `public/data/arbitrage.json`
- `public/data/arbitrage.csv`
- `public/data/build_metadata.json`

Optional per-preset files are allowed if total payload and complexity improve. The browser must not receive raw proprietary/benchmark-only datasets.

See `schemas/` and `docs/DATA_CONTRACTS.md`.

## 15. Repository/reproducibility requirements

- One public Git repository.
- All handwritten source, config, schemas, docs, lockfiles, model cards, and production model artifacts needed for deterministic inference are versioned.
- Raw nflverse historical datasets should be re-fetched/cached rather than duplicated into Git unless needed for a legal, small snapshot fixture.
- Daily market snapshots should be retained in a dedicated strategy (recommended `data` branch or another append-only Git-managed store) because point-in-time market history is analytically valuable.
- Tests must use small committed fixtures and should not require live network access by default.
- Every production build records Git SHA, model version, source timestamps, and config version.

## 16. GitHub Actions requirements

At least three workflows:

### `ci.yml`

On pull request / relevant push:

- Python lint/type/tests
- frontend lint/type/tests
- fixture-based mini pipeline
- JSON Schema validation
- frontend production build
- optional Playwright smoke test

### `daily-refresh.yml`

Scheduled daily at an off-the-hour minute using `America/New_York` timezone, plus manual dispatch.

- source refresh
- validation
- inference
- tier/arbitrage generation
- artifact validation
- site build
- Pages deploy
- optional safe market-snapshot persistence

Deploy only after every production gate passes.

### `retrain.yml`

Weekly during draft season plus manual dispatch:

- reconstruct historical training feature sets
- train baselines and candidates
- rolling validation
- leakage checks
- generate model card/metrics
- promote only when declared gates pass; otherwise retain incumbent

Automatic promotion is permitted only when all gates are machine-verifiable and deterministic. Otherwise produce a candidate artifact for review.

## 17. UX architecture

Single-page utility app with three main surfaces:

1. **Tiers** — S-tier-style distribution-aware board + table
2. **Arbitrage** — Draft Rail visualization + table
3. **Methodology/Data** — concise metrics, definitions, freshness, sources

Global controls stay visually compact. Avoid dashboards full of cards. A draft user should be able to understand the first screen in seconds.

See `docs/UX_SPEC.md`.

## 18. Failure and freshness behavior

- Critical data-contract failure: stop pipeline; do not deploy.
- Optional source failure: continue only if the output explicitly records degradation and core outputs remain valid.
- Intrinsic source stale beyond configured threshold: stop production deploy.
- Market source stale: Tier Board may update, but Arbitrage must show stale/degraded state or remain last-known-good; never present old market data as current.
- Site header must display last successful production refresh.
- Workflow summary must list source status and record counts.

## 19. Security and licensing

- No secrets committed.
- Prefer unauthenticated public endpoints for V1.
- GitHub token permissions must be least privilege; Pages deployment gets only required permissions.
- Never execute downloaded source content as code.
- Attribute datasets according to current licenses.
- FantasyCalc/non-commercial or other restricted sources require a legal/terms re-check before monetization.
- FantasyPros-derived data must not be redistributed unless explicit current terms permit it.

See `docs/SECURITY_LICENSE.md`.

## 20. Phase gates

The coding agent must build in the following order:

0. Source/legal/feasibility proof
1. Repository scaffold + contracts + identity + source adapters
2. Historical feature dataset + leakage-safe snapshots
3. Intrinsic baselines + evaluation harness
4. Production probabilistic DraftValue + VORP + natural tiers
5. Market snapshots + arbitrage baseline + ML feasibility/promotion
6. Frontend Tier Board, Draft Rail, tables, export
7. GitHub Actions + Pages production deployment
8. Hardening, performance, accessibility, model cards
9. Launch validation and release

Exact exit criteria are in `docs/IMPLEMENTATION_PLAN.md` and `TASKS.md`.

## 21. Launch acceptance criteria

The V1 launch is complete only when all of the following are true:

### Data

- All required free sources have documented terms/usage decision and verified adapter tests.
- >= 95% of model-eligible current QB/RB/WR/TE records have resolved canonical identity.
- No ambiguous name-only production joins.
- Critical source freshness gates pass.

### Intrinsic model

- Rolling holdout evaluation exists for every modeled position.
- Production model beats declared naive baseline on the preselected primary rank/probabilistic metrics overall and does not catastrophically regress a position without documented reason.
- Quantile intervals meet declared calibration tolerance or are post-calibrated.
- Leakage tests pass.
- Model card is generated and shipped.

### Tiers

- Tier boundaries are algorithmic and not manually authored.
- Bootstrap/sensitivity stability is measured.
- Holdout tier value is directionally monotonic.
- UI renders tiers legibly for at least top 150 overall players.

### Arbitrage

- At least one verified current market source works in production.
- Daily market snapshots are retained.
- If labeled ML, historical coverage and out-of-time promotion gates pass and the ML model beats the simple gap baseline on the declared primary metric(s).
- Otherwise the site clearly labels arbitrage as a deterministic baseline and does not claim learned surplus prediction.

### Product

- Tier and Arbitrage visualizations are interactive.
- Tables sort/filter/search correctly.
- Full and filtered CSV exports work.
- URL state works.
- Desktop/tablet primary flows and mobile smoke tests pass.
- Accessibility smoke tests pass.

### Operations

- PR CI is green from a clean clone.
- Manual daily refresh succeeds from a clean runner.
- Scheduled workflow is enabled.
- Production deploy uses GitHub Pages.
- A deliberately failed data-quality test proves bad output cannot overwrite the last-known-good site.
- Public metadata exposes build SHA, model version, config, and refresh timestamp.

## 22. Decision principles for coding agents

When a detail is not explicitly specified:

1. Preserve the intrinsic-vs-market separation.
2. Prefer reproducibility and leakage prevention over extra model complexity.
3. Prefer verified public sources over clever scraping.
4. Prefer a simple baseline with measured evidence over an unvalidated sophisticated model.
5. Prefer static artifacts over a backend.
6. Prefer clear, typed contracts over implicit dataframe conventions.
7. Prefer utility and legibility over visual decoration.
8. Document material architectural deviations as an ADR before implementing them.
