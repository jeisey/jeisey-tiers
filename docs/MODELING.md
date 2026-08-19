# Modeling Specification

## 1. Modeling philosophy

The project must resist two common failure modes:

1. building an elaborate model before establishing a strong baseline and leakage-safe evaluation;
2. letting market consensus leak into the "independent" model, then rediscovering the market and calling it arbitrage.

The intrinsic and arbitrage systems are separate statistical problems with separate targets and feature allowlists.

## 2. Terminology

- **Intrinsic projection:** football-data-only estimate of a player's fantasy outcome distribution.
- **DraftValue:** league-adjusted intrinsic value, represented primarily through VORP distributions.
- **Fair rank / fair pick:** ordering implied by intrinsic DraftValue for a league preset.
- **Market cost:** observed ADP/rank from verified draft-market data.
- **Realized surplus:** actual season value delivered relative to what is normally delivered at the player's market cost.
- **Tier:** contiguous group of fair-ranked players whose modeled value distributions do not exhibit a stable meaningful break.

## 3. Dataset grain and target horizon

Primary training grain: player-season at a reproducible preseason draft-time anchor.

Positions: QB/RB/WR/TE.

Scoring labels: STD/HALF/PPR generated from one tested scoring engine.

Recommended fantasy horizon:

- 2021+ seasons: NFL Weeks 1–17;
- pre-2021 17-week NFL schedules: Weeks 1–16;
- exclude final NFL regular-season week to reduce meaningless rest/start decisions and align common fantasy championship schedules.

This rule must be applied consistently to labels and documented in model cards.

## 4. Eligibility

### Veterans

Include players who were on an NFL roster/depth universe at the anchor and meet position criteria. Do not require prior-year touches; that would remove breakouts.

### Rookies

Include drafted/UDFA players present in the current roster/player universe. Missing historical NFL stats are expected; rookie features rely more heavily on draft capital, age, combine/athletic data, college-independent public features if permitted, and depth/team context.

### Low-information players

The model may predict them but should emit a quality/confidence flag. Do not silently exclude all unknown players if they are draft-relevant.

> **Phase-2 implementation.** The eligibility rules above are realised as ADR-022's preseason universe: a row exists only when the previous season's roster, the target season's draft class, or a pre-anchor depth snapshot says the player was in the league. Prior-year touches are deliberately not required, so breakouts survive. `load_rosters(Y)` and week-1 weekly rosters are refused — see `docs/DATA_CONTRACTS.md` section 3.1 for why. Low-information rows are not silently dropped: they carry `rookie_flag`, `has_prior_season_stats`, `depth_context_state` and per-family missingness indicators, and the quality report slices coverage by season and position so their share is visible.

## 5. Feature allowlist

Candidate families, all calculated using information available by the anchor:

### Usage/opportunity

- carries/game, targets/game, receptions/game
- target share / rush share if derivable leakage-safely
- red-zone opportunities
- prior snap share
- expected fantasy points/opportunity from ffopportunity
- actual minus expected points
- rolling 1/2/3-year recency-weighted opportunity

### Efficiency

- yards/carry
- yards/target or reception
- catch rate
- TD rate with shrinkage/reversion features
- passing efficiency for QBs
- advanced/NGS/PFR measures only if historically available at the relevant anchor and license permits

### Durability/availability

- previous games played/missed
- career games
- age
- position × age interaction
- prior injury/status summaries only when historical source coverage permits point-in-time reconstruction

### Career/athletic

- experience
- rookie flag
- draft round/pick
- combine measures
- size/athletic composites if transparent and reproducible

### Context

- current team at anchor
- team change flag
- prior team offensive volume/efficiency summaries
- depth-chart rank at anchor — **Phase-0 caveat (2026-08-17):** only available as a true anchor observation for 2025 onward, where depth charts are timestamped daily snapshots. For 2024 and earlier the earliest observation is week 1, which postdates a late-August draft and final roster cuts, so it may not be used as an anchor feature without the documented leakage caveat in ADR-015.
- teammate opportunity vacated using only prior-season/current roster information
- QB/team context features for RB/WR/TE if constructed without market rank

### Missingness indicators

Tree models can often handle missing values, but missingness can itself be informative. Add explicit indicators only where evaluation supports them.

### 5.1 Phase-2 first cut

The built feature set is published in `docs/FEATURE_DICTIONARY.md`, generated from `ffdraft.features.dictionary` with a test asserting the two agree. 102 columns, of which 85 are model inputs, in these families:

| Family | What it carries |
|---|---|
| `production` | Previous-season fantasy points and per-game production. STD and PPR totals are carried explicitly; half-PPR is exactly their mean. |
| `opportunity` | Carries, targets, receptions, pass attempts per game; target and rush share against the player's own teams in the weeks he played; ffopportunity expected points per game. |
| `efficiency` | Yards per carry/target, catch rate, touchdown rates, passing efficiency, actual-minus-expected points. Every one is null below a declared minimum denominator, with a paired `*_denominator_met` indicator. |
| `durability` | Games played, the player's team's games inside the horizon, and the difference. |
| `career` | Experience, rookie flag, age at anchor, position-standardised age, a fixed five-season prior window and recency-weighted 3-season summaries. |
| `draft` | Draft year, round, overall pick, drafted flag, seasons since draft. |
| `athletic` | Height, weight, the six combine drills, and a transparent speed score — never imputed for a player who did not test. |
| `depth` | ADR-018's three states, the observed pre-anchor depth rank (2025+ only) and the lagged prior-season role rank. |
| `team_context` | Previous-season team offensive volume, the team observed at the anchor where one exists, and a team-change flag that is null wherever it cannot be known. |

Two families named in section 5 are **deliberately deferred**, with reasons rather than silence:

- **Vacated-opportunity / teammate features.** Deriving them needs to know who is on the team at the anchor. Before 2025 that is unobservable, so the feature would exist for one labelled season out of twelve and would be perfectly confounded with the era boundary. Revisit once Phase 3 has baselines and more snapshot-era seasons exist.
- **NGS and PFR advanced metrics, and FTN charting.** Not needed for a first cut, and FTN carries a share-alike obligation the project has no reason to take on yet. Revisit only with evidence that the compact set is leaving signal on the table.

Preseason injury state is absent because no nflverse source publishes one at a draft anchor in any season (ADR-011), not because it was overlooked.

## 6. Forbidden intrinsic features

Automated test must reject feature names/lineage matching:

- adp
- ecr
- expert rank
- fantasypros rank/projection
- fantasycalc rank/value
- consensus rank
- market pick/rank
- arbitrage score

Do not evade this rule by renaming a market proxy.

> **Phase-2 implementation.** `ffdraft.quality.forbidden` audits both the declared model-input names *and* the columns actually present in the built table, plus each feature's declared source lineage against the registry — so a market-derived column with an innocent name fails too, and a `benchmark_only` source (FantasyPros ECR, ADR-014) can never become an input. The audit runs inside every build and again in `ffdraft validate-historical`, and the leakage suite proves it fires on `market_adp`, `prev1_ecr`, `consensus_rank`, `fantasypros_tier` and `arbitrage_score`.

## 7. Evaluation split

Never random-split player-seasons.

Recommended rolling origin:

```text
Train <= 2017 -> validate 2018
Train <= 2018 -> validate 2019
...
Train <= 2024 -> validate 2025
```

Actual first fold depends on feature availability. Use enough earlier seasons to train responsibly.

Reserve final holdout season(s) from iterative tuning. A reasonable workflow:

- development rolling folds through 2023/2024;
- 2024 as validation depending current date/data quality;
- 2025 as final untouched holdout for 2026 launch if full labels are available and feature source history is reproducible.

Record fold definitions before tuning.

## 8. Baselines

At least:

### B0 — prior production baseline

For veterans, prior-season fantasy PPG/total with age/availability shrinkage; rookies assigned position/draft-capital prior.

### B1 — simple regularized model

ElasticNet/linear or simple gradient boosting on compact feature set.

### B2 — simple market-gap baseline for arbitrage

`market_adp - fair_rank`, with no learned parameters beyond optional percentile normalization.

Baseline code remains in repo after better models are promoted.

## 9. Intrinsic candidate model family

Initial preferred candidate: position-specific LightGBM quantile regression.

Why:

- handles nonlinear tabular relationships and missingness well;
- fast enough for public GitHub Actions;
- supports quantile objectives;
- interpretable enough via feature importance/SHAP offline if desired;
- compact artifacts.

Do not assume it wins. Compare to baselines.

### 9.1 Candidate A — direct total-points quantiles

For each position × scoring preset, predict P10/P25/P50/P75/P90 (or minimal P10/P50/P90 first) of fantasy-season points.

Advantages:

- simple
- injury/role uncertainty implicitly present in historical target
- easy to validate

Disadvantages:

- blends availability and performance
- quantile crossing possible
- injuries may dominate noise

### 9.2 Candidate B — availability × performance

Two components:

1. availability distribution / expected games active;
2. conditional points-per-active-game or usage/performance distribution.

Monte Carlo combines them.

Potentially more interpretable and responsive to current status, but only promote if it improves out-of-time probabilistic/rank metrics enough to justify complexity.

### 9.3 Optional ensemble

A simple average/stack of candidates is allowed only if learned/tuned entirely inside training folds and materially improves holdouts. Avoid model zoo behavior.

## 10. Quantile calibration

Raw quantile models must be checked for:

- crossing
- empirical coverage
- position/year calibration

Minimum fixes:

- sort/postprocess quantiles if tiny crossing occurs, but track crossing rate;
- use conformal or empirical residual calibration if interval coverage is materially off;
- calibration parameters must be learned on allowed validation/calibration folds, not final holdout.

Public model card reports target vs empirical interval coverage.

## 11. Monte Carlo

Goal: translate per-player predictive uncertainty into league-relative value uncertainty.

Initial simulations: 10,000 draws per supported scoring/preset unless performance tests justify a lower deterministic count. 5,000 may be sufficient; choose based on convergence tests.

### Sampling

If the production model emits quantiles rather than a parametric distribution:

- construct a monotone piecewise quantile function;
- sample uniform `u` and interpolate between supported quantiles;
- handle tails conservatively using documented bounded extrapolation or fitted simple tail assumptions;
- truncate impossible negative fantasy totals where appropriate by position/scoring.

Do not pretend players are independent if future work adds correlations, but V1 may use independent player draws for tractability. Document this limitation.

### Determinism

Seed is derived from model version + league preset + build ID or fixed production seed. Re-running the same inputs must reproduce outputs within exact/tight tolerance.

## 12. Replacement allocation

For every simulation and league preset:

1. sort QBs by sampled fantasy points and fill all mandatory QB starting slots;
2. fill mandatory RB/WR/TE starting slots;
3. allocate FLEX slots globally to the highest remaining eligible RB/WR/TE players;
4. for each position, define replacement baseline as the highest-scoring eligible player not consumed by the starter/FLEX allocation;
5. player VORP = sampled fantasy points - sampled positional replacement baseline.

A player not projected above replacement can have negative VORP.

This produces position-aware scarcity without market ADP.

> **Phase-2 implementation.** The algorithm lives in `ffdraft.simulation.allocation`, independent of where the points came from: Phase 2 feeds it a player's **actual** season total to build realized-VORP labels, and Phase 4 will feed it one Monte Carlo draw per player. There is one implementation, so the realized label and the simulated value cannot disagree about what a league starts. Ties break on `player_id` ascending, making an allocation a pure function of its inputs, and a position whose pool is entirely consumed by starting slots gets a null replacement rather than an invented zero.

### Superflex future extension

Would require joint QB/RB/WR/TE slot optimization. Do not fake superflex by reusing 1QB replacement ranks.

## 13. Fair ranking

Primary fair rank = descending expected or median simulated VORP. Pick one before final evaluation; preferred initial default is **median VORP** for robustness, while expected VORP remains visible.

Tie break is deterministic per `DATA_CONTRACTS.md`.

Do not bake upside preference into rank. Ceiling/floor are displayed separately.

## 14. Natural tier segmentation

### 14.1 Requirement

Tiers are contiguous in fair-rank order. Number of tiers is not preselected.

### 14.2 Initial candidate: change-point segmentation

For each position or overall board (depending view), create a rank-ordered feature matrix from simulated VORP summaries, e.g. standardized:

```text
p25_vorp
p50_vorp
p75_vorp
uncertainty = p75 - p25
```

Run a contiguous change-point algorithm such as `ruptures.Pelt(model="rbf")`.

Penalty is a hyperparameter trained/tuned on development seasons according to stability + utility criteria, not visual preference.

### 14.3 Alternative candidate

Dynamic programming segmentation minimizing within-tier distribution distance (e.g. Wasserstein/quantile dispersion) plus a per-tier complexity penalty.

Implement only if the simpler PELT candidate proves unstable/unintuitive under measured tests.

### 14.4 Boundary diagnostics

For each adjacent boundary compute diagnostics such as:

- P50 VORP cliff
- standardized effect size
- distribution overlap / probability lower player exceeds upper player
- bootstrap boundary frequency

These can power an explainable tooltip later.

### 14.5 Stability test

Bootstrap/re-simulate model outputs and rerun segmentation. Track:

- boundary frequency by rank interval;
- adjusted Rand index or equivalent membership similarity;
- singleton rate;
- average tier count.

Tier algorithm promotion requires a declared stability threshold chosen during development and documented in the tier method card. Avoid inventing an arbitrary threshold in code without evaluation.

## 15. Tier labels

Ordinal 0 -> `S`, 1 -> `A`, 2 -> `B`, etc.

If the board requires more segments than comfortable letter labels, maintain semantic tier ordinal in data and allow UI labels such as `Late 1`, `Late 2` after `F`. Do not merge statistically distinct tiers solely to keep a meme-style alphabet.

## 16. Arbitrage target construction

### 16.1 Market cost curve

For each historical season/scoring/league cohort, estimate the typical **realized actual VORP** delivered by a player selected at market pick `p`.

Use a robust smooth/monotonic curve fitted only on training seasons/fold-allowed data. Candidate methods:

- isotonic regression after appropriate transformation;
- monotonic spline;
- rolling/LOESS with monotonic enforcement.

The relationship must generally decline with later draft cost; enforce/diagnose this rather than allowing noisy upward market-value curves.

### 16.2 Realized surplus label

For player i:

`surplus_i = actual_vorp_i - market_expected_actual_vorp(adp_i)`

This means a late-round 40-VORP season can be excellent if that draft slot normally produces little value, while an early first-round 40-VORP season may be a disappointment.

### 16.3 Fold isolation

When evaluating season Y:

- market expected-value curve is fitted without Y outcomes;
- intrinsic fair rank/DraftValue for Y is generated by an intrinsic model trained without Y outcomes;
- any arbitrage feature normalization is learned without Y.

## 17. Arbitrage features

Allowed:

- intrinsic fair rank
- intrinsic expected/median VORP and quantiles
- intrinsic uncertainty
- position
- age/rookie/context features already allowed intrinsically
- market ADP/rank
- ADP spread/sample size
- fair-rank minus market gap
- daily/weekly ADP movement computed from retained historical snapshots
- cross-source market divergence if optional source is legally allowed

Avoid raw expert rank unless benchmark/feature use is explicitly legally approved and a separate experiment proves value. The preferred production arbitrage system should work without FantasyPros.

## 18. Arbitrage candidate models

### A0 — deterministic baseline

Primary score ingredients:

- positive `market_adp - fair_rank` gap
- normalized by draft region (a 12-pick gap at pick 15 differs from pick 150)
- discount low-sample/high-dispersion ADP
- optional trend signal

Output percentile 0–100.

This is launchable if historical ML data is insufficient.

### A1 — continuous surplus regressor

LightGBM or similarly simple tabular model predicting realized surplus VORP.

### A2 — positive-surplus classifier

Predict `P(surplus > 0)` and calibrate probability.

Could be paired with A1 but only if extra output adds user value and validation supports it.

## 19. Arbitrage promotion gate

An ML model is promoted only if it improves on deterministic A0 in multiple chronological holdouts.

Predeclare a primary metric combination, for example:

- higher Spearman/IC on realized surplus in >= 2/3 latest holdouts; and
- higher top-decile realized-surplus uplift; and
- no severe calibration failure if probability is exposed.

Do not define a fake universal numeric threshold before seeing scale. Define the rule structure first, then freeze actual thresholds before final holdout.

If the learned model loses, ship A0 and keep collecting data.

## 20. Fair pick vs ADP presentation

`fair_rank` is the intrinsic rank. It is not necessarily a literal recommended draft slot if the user can wait and exploit market availability.

Therefore the UI should distinguish:

- **Fair Rank:** where the player belongs by intrinsic value.
- **Market ADP:** where drafts typically take him.
- **Value Gap:** difference.
- **Take-by / availability guidance:** optional future derived metric; do not invent it without a validated availability model based on actual pick distributions.

## 21. Model confidence

Do not expose fake precision from an arbitrary 0.83 "confidence" score.

Confidence can be derived from transparent data/model diagnostics, e.g.:

- predictive interval width percentile
- training-domain distance / rookie/low-sample flag
- source completeness
- ensemble disagreement if an ensemble exists

Public confidence label may be `high/medium/low` with methodology, or a normalized score if calibrated. It must have a defined meaning.

## 22. Model cards

Every promoted intrinsic/arbitrage model needs a Markdown + JSON card with:

- purpose
- version
- training window
- data sources
- features and forbidden features
- target
- fold definitions
- hyperparameters
- primary/secondary metrics
- year/position slices
- calibration
- known limitations
- fairness not relevant in human-demographic sense, but data coverage/rookie/position biases must be discussed
- artifact hash
- code SHA
- promotion decision

## 23. Important limitations to state publicly

- fantasy outcomes have substantial injury/role randomness;
- independent-player Monte Carlo omits teammate/team correlations in V1;
- current free injury history may be incomplete after nflverse source changes;
- rookie projections are lower-information;
- ADP sources may represent specific platforms/league cohorts rather than all fantasy players;
- model rank is decision support, not certainty.
