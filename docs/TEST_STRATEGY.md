# Test Strategy

## 1. Testing principle

The most dangerous bugs in this project are not syntax errors. They are:

- silent identity mismatches;
- temporal leakage;
- market leakage into the intrinsic model;
- source schema drift;
- stochastic non-reproducibility;
- incorrect replacement/FLEX math;
- model artifact/schema incompatibility;
- charts displaying a value differently from the table;
- bad data overwriting a good public deployment.

The test strategy is designed around those failure modes.

## 2. Test layers

### 2.1 Unit tests

Fast, network-free tests for:

- fantasy scoring formulas
- age/anchor-date calculations
- source normalization functions
- canonical ID parsing/crosswalk logic
- quantile monotonicity handling
- interpolation/sampling
- roster/FLEX allocation
- VORP calculation
- tier label mapping
- arbitrage gap sign convention
- CSV serialization
- URL state parsing/serialization

### 2.2 Contract tests

For every adapter fixture:

- normalized schema
- required fields/types
- source metadata
- duplicate expectations
- identity fields

For public artifacts:

- JSON Schema validation
- cross-field semantic validation

### 2.3 Integration tests

Network-free fixture mini pipeline:

```text
source fixture
 -> normalize
 -> canonical identity
 -> current feature subset
 -> deterministic mock/model inference
 -> VORP
 -> tiers
 -> market join
 -> arbitrage
 -> artifact JSON/CSV
 -> schema validation
```

This is the key PR CI smoke path.

### 2.4 Live source smoke tests

Run manually and/or scheduled, not ordinary PR CI.

Checks:

- endpoint reachable
- HTTP success/content type
- minimum records
- required key fields still exist
- source timestamp plausible
- sampled IDs resolve

These detect upstream changes without making local development dependent on the internet.

### 2.5 Leakage tests

Required automated tests:

#### Temporal cutoff

For every model feature with source timestamp lineage:

`feature_available_at <= anchor_at`

For season aggregates without row timestamps, assert the aggregation season/week set is strictly prior to the target horizon.

#### Forbidden intrinsic features

Feature-list test rejects market/expert tokens and source lineage.

#### Arbitrage OOF test

For each historical arbitrage row:

- intrinsic model training max season < target/evaluation season or fold excludes target season according to fold design;
- market-cost curve fit excludes target fold outcomes.

#### Final holdout protection

Experiment configuration must prevent final holdout from being used in tuning commands unless an explicit `--final-eval` mode is set.

### 2.6 Model tests

Not unit tests for "accuracy > magic number". Use controlled assertions:

- training completes on fixture/small data;
- deterministic seed produces same predictions;
- prediction length/IDs preserved;
- quantiles finite/monotonic;
- probability range valid;
- production artifact feature schema matches inference schema;
- calibration function monotonic;
- model promotion comparator behaves correctly on synthetic metrics.

Full model metrics are evaluated in experiment/retrain jobs and stored as reports.

### 2.7 Simulation tests

Hand-work small league examples.

Example: 2-team league, 1 RB starter, no flex, player sampled points [100, 80, 60]. Replacement after starters is 60; VORP [40,20,0].

Add tests for:

- multiple RB/WR FLEX competition;
- ties;
- negative scores/edge values if possible;
- missing eligible positions;
- deterministic output across seeds/configs;
- simulation convergence tolerance for 1k vs 5k vs 10k draws in development benchmark.

### 2.8 Tier tests

Synthetic distributions:

- clear two-cluster structure -> one boundary near known gap;
- smooth no-cliff structure -> algorithm should not create pathological many tiers;
- isolated elite player -> singleton top tier allowed;
- fair-rank order shuffled internally -> tier function sorts/validates correctly;
- tier members contiguous;
- bootstrap result deterministic for fixed seed.

### 2.9 Arbitrage tests

- positive `market_adp - fair_rank` means bargain;
- negative gap means market is more aggressive than model;
- missing ADP does not crash Tier output;
- market sample quality affects confidence/baseline only as documented;
- ML fields null/omitted in baseline mode;
- baseline preserved as comparator after ML promotion.

### 2.10 Frontend unit/component tests

- artifact schema/version loader
- scoring/teams/position control state
- URL serialization
- table sort/filter/search
- filtered CSV generation
- baseline-mode conditional columns
- stale/degraded banner
- tooltip/detail accessible text

### 2.11 E2E tests

Playwright fixture build tests:

1. open default Tiers view;
2. change scoring and team size;
3. filter RB;
4. search a player;
5. verify chart/table agree on tier/rank;
6. export filtered CSV and validate row count/header;
7. switch Arbitrage;
8. sort by ADP/value gap;
9. open methodology;
10. reload copied URL and verify state;
11. test mobile viewport;
12. test Pages base path.

## 3. Data-quality tests

Critical checks should have direct tests demonstrating they block deploy:

- empty core nflverse data
- > allowed unresolved identity threshold
- public top-150 unresolved player
- duplicate player ID/rank
- stale source
- schema drift
- NaN/inf in public metrics
- nonmonotonic quantiles
- arbitrage market snapshot from wrong scoring/season
- production model feature schema mismatch

## 4. Golden fixtures

Keep fixtures intentionally tiny, e.g. 12–30 players, but cover all positions and edge cases.

Golden outputs are appropriate for:

- scoring
- identity resolution
- VORP allocation
- artifact field order/CSV headers

Avoid huge snapshot tests that obscure meaningful changes.

## 5. CI stages

Suggested order for fast feedback:

```text
Python lint/format
Python unit + leakage + contracts
Fixture mini-pipeline + artifact validation
Frontend lint/type/unit
Frontend build
Playwright smoke
```

Parallelize Python/frontend checks when convenient.

## 6. Production pipeline validation

Daily workflow additionally runs:

- live source smoke/data quality
- current identity coverage
- current model inference checks
- simulation/tier semantic checks
- market freshness
- JSON Schema validation
- web build against actual artifacts

Only after these pass can Pages deploy.

## 7. Retrain validation

Retrain job must output:

- fold table
- metrics by fold/position/scoring
- aggregate comparison to incumbent/baselines
- calibration table
- feature list + forbidden-feature audit
- data coverage report
- model artifact hash
- promotion decision/reason

A test should simulate a candidate losing a promotion metric and prove incumbent remains selected.

## 8. Code coverage

Do not chase a vanity percentage. Prioritize high coverage on:

- scoring
- identity
- contracts
- leakage guard
- simulation/VORP
- tiering
- arbitrage target/baseline
- artifact serializers

Coverage reporting is useful, but missing a critical invariant is worse than 95% line coverage.

## 9. Manual review requirements

Before V1 release, a human/agent visual review should inspect:

- 5–10 known players across ranks/positions for plausible inputs/outputs;
- rookie cases;
- injured/current-status cases;
- tier cliffs;
- top arbitrage candidates and source ADP values;
- CSV export;
- source attribution.

This is a sanity layer, not a reason to manually override model outputs.
