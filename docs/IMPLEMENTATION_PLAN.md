# Methodical Implementation Plan

This plan is deliberately phase-gated so a frontier coding agent can work autonomously without turning the repo into a half-finished mix of data science, frontend prototypes, and brittle API calls.

## Phase 0 — Source, legal, and feasibility proof

### Objective

Turn every important external assumption into evidence before designing production code around it.

### Deliverables

- executable source probe script/notebook kept reproducible;
- source decision table updated with date;
- tiny legal fixtures/schema samples;
- arbitrage historical-data feasibility decision;
- injury-source decision;
- ADR for any material departure from target stack.

### Tasks

1. Create minimal Python environment if repo is empty.
2. Install/probe nflreadpy.
3. Fetch sample historical/current datasets and record schema/counts.
4. Verify point-in-time depth availability for training seasons.
5. Verify expected-points data coverage.
6. Verify MFL current ADP and historical seasons programmatically.
7. Verify Sleeper player/status data.
8. Re-read FantasyCalc current terms/access mechanism.
9. Re-read FantasyPros/ECR benchmark terms.
10. Decide historical ADP sufficiency.
11. Update source registry.

### Exit criteria

- No production-critical endpoint is hypothetical.
- No source-rights assumption is undocumented.
- At least one current ADP source is viable or the project is explicitly blocked before arbitrage work.
- Clear yes/no on historical arbitrage ML feasibility.

### Do not do yet

- train final model;
- build polished frontend;
- write live-source calls directly into UI.

---

## Phase 1 — Scaffold, contracts, identity, adapters

### Objective

Build a boring but reliable skeleton that makes bad joins and schema drift difficult.

### Deliverables

- Python package/lockfile;
- React/Vite/TS skeleton/lockfile;
- source adapters;
- identity service;
- data-quality primitives;
- JSON Schema validators;
- fixture mini-pipeline;
- CI skeleton.

### Implementation order

1. Config loading/validation.
2. Internal contract types.
3. Source adapter protocol.
4. nflverse adapter.
5. Sleeper adapter.
6. market adapter.
7. canonical player crosswalk/resolver.
8. artifact serializer skeleton.
9. fixture pipeline.
10. CI.

### Exit criteria

From a clean clone without network:

- dependencies install;
- fixtures flow through normalize → identity → artifact serialization;
- generated fixture artifacts validate against JSON Schemas;
- ambiguous identity fixture fails closed;
- CI passes.

---

## Phase 2 — Historical modeling table

### Objective

Build the time-correct data asset on which every model result depends.

### Deliverables

- anchor-date generator;
- historical feature builder;
- scoring engine;
- actual label builder;
- replacement/VORP label builder;
- feature dictionary;
- leakage tests;
- data-quality report.

### Method

Start with compact, highly trustworthy feature families before adding advanced sources.

Recommended first cut:

- prior 1–3 year player stats
- age/experience
- draft capital/combine
- team change
- prior snap/opportunity
- ffopportunity expected points
- anchor depth rank

Add advanced NGS/PFR only after coverage analysis proves value.

### Exit criteria

- all training rows have a documented anchor;
- feature lineage proves no target-season future data;
- duplicate player-season keys = 0;
- identity threshold met;
- model matrix can be regenerated deterministically;
- feature/label distributions inspected and reasonable.

---

## Phase 3 — Baselines and evaluation harness

### Objective

Know what "good" means before pursuing sophistication.

### Deliverables

- rolling fold framework;
- baselines B0/B1;
- quantile model experiment;
- metrics and bootstrap CI package;
- machine-readable experiment results;
- final holdout freeze.

### Required experiment report

For each position/scoring:

- training years
- validation year
- record counts
- MAE/RMSE
- Spearman/Kendall
- quantile pinball/coverage
- top-K metric

### Exit criteria

At least one model candidate beats declared naive baseline on primary aggregate metric(s) and has no hidden positional collapse. If none does, debug data/features rather than moving to the UI.

---

## Phase 4 — Production intrinsic model, VORP, tiers

### Objective

Produce the first genuine headline product.

### Steps

1. Compare direct-total quantiles to availability × performance if implemented.
2. Choose simplest validated production candidate.
3. Calibrate distributions.
4. Train final production models through allowed seasons.
5. Save versioned model artifacts.
6. Implement quantile sampler.
7. Convergence-test Monte Carlo draw count.
8. Implement roster slot/FLEX replacement algorithm.
9. Generate VORP distributions per league preset.
10. Implement PELT tier candidate.
11. Tune tier penalty on development folds.
12. Bootstrap tier stability.
13. Create model/tier card.
14. Generate current artifacts.

### Exit criteria

- model gates pass;
- intervals calibrated within documented tolerance;
- simulation deterministic;
- VORP/replacement tests pass on small hand-worked examples;
- natural tiers are contiguous and stable enough by declared metric;
- artifacts valid for all launch presets.

---

## Phase 5 — Market history and arbitrage

### Objective

Add market pricing without contaminating intrinsic value.

### Steps common to both modes

1. Normalize live ADP.
2. Persist daily market snapshot.
3. Join market to intrinsic via canonical IDs.
4. Build deterministic A0 gap score.
5. Add market trend from retained snapshots when enough data exists.

### If historical ML feasible

6. Build historical market table.
7. Generate rolling OOF intrinsic predictions.
8. Fit training-fold market-cost → expected actual VORP curve.
9. Create realized surplus target.
10. Train A1/A2 candidates.
11. Evaluate year-by-year against A0.
12. Calibrate probability if exposed.
13. Promote only if gate passes.

### If historical ML not feasible

- explicitly set `arbitrage_mode=baseline`;
- document how many future snapshot seasons are needed before revisiting;
- do not block product launch.

### Exit criteria

- one reliable current ADP source;
- daily snapshot retention proven;
- arbitrage public contract valid;
- mode labeling truthful;
- learned model, if present, beats A0 according to frozen gate.

---

## Phase 6 — Frontend

### Objective

Turn model artifacts into a superior draft sheet.

### Build order

1. typed artifact loaders + schema version checks;
2. URL state/global controls;
3. basic Tier table;
4. Tier Board visualization;
5. basic Arbitrage table;
6. Draft Rail visualization;
7. export full/filtered CSV;
8. methodology/freshness panel;
9. details/tooltips;
10. responsive/accessibility states;
11. E2E tests/screens.

Starting with tables before bespoke charts provides a reliable truth surface for visual QA.

### Exit criteria

- chart values agree with table/fixtures;
- filters and URL state agree;
- exports match filtered rows;
- keyboard/mobile smoke tests pass;
- no runtime vendor API dependency.

---

## Phase 7 — GitHub Actions and Pages

### Objective

Make the repository self-refreshing and safely deployable.

### CI

PR checks against fixtures; no live network required.

### Daily

Use timezone-aware off-the-hour schedule such as 07:17 America/New_York; exact time may shift after source probe. GitHub warns top-of-hour scheduled workflows can experience more delay.

Suggested job graph:

```text
fetch-current
   ├─> validate-current
   ├─> persist-market-snapshot (only after market validation)
   └─> inference
          └─> public-artifacts
                  └─> frontend-build
                          └─> pages-deploy
```

A failed ancestor prevents deploy.

### Retrain

Keep separate from daily inference. Weekly/manual during draft season; candidate model should not replace incumbent on a failed gate.

### Exit criteria

- Pages deployment works from clean runner;
- permissions minimal;
- workflow caching safe;
- source failures visible in summary;
- forced validation failure proves deploy is skipped.

---

## Phase 8 — Hardening

### Objective

Challenge assumptions before release.

Run:

- source outage simulations;
- stale source simulations;
- identifier collision tests;
- final holdout review;
- model feature audit for forbidden columns;
- front-end performance and accessibility checks;
- Pages path/custom base check;
- dependency license/security review;
- full clean-clone reproduction.

Exit only when critical/high defects are closed or explicitly accepted in a release note with rationale.

---

## Phase 9 — Release

### Objective

Publish a reproducible V1 rather than merely enabling Pages.

Checklist:

- final current data refresh;
- final source freshness check;
- model cards linked;
- all preset artifacts validated;
- Pages site manually/automatically smoke tested;
- release tag;
- known limitations documented;
- production build SHA recorded.

## Agent work-unit recommendation

For long autonomous sessions, use these coherent work units rather than one monolithic "build everything" diff:

1. Source probe + decisions
2. Contracts + identity
3. Historical feature set
4. Eval baselines
5. Intrinsic model
6. VORP/tiering
7. Market snapshots
8. Arbitrage
9. Frontend data/table state
10. Tier chart
11. Arbitrage chart
12. Actions/Pages
13. Hardening

Each unit should leave the repository green.
