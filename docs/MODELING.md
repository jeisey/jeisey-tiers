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

> **Phase-3 implementation.** `ffdraft.modeling.folds` makes a fold data rather than a loop
> variable: the fold table is persisted in every experiment report with its window policy,
> training span, validation season, record counts, feature-set hash and seed. Development
> validation seasons are **2020-2024**, common to both training-window policies so the
> comparison is paired at the row level; 2017-2019 are emitted as W1-only diagnostics and
> may not decide the window, because W2 cannot reproduce them with three training seasons.
>
> **Season 2025 is the sealed final holdout** (ADR-025). It is removed from the modelling
> frame at load time, so a development run does not have the rows at all; the fold generator
> additionally refuses to construct a fold that validates a sealed season. Opening it
> requires an explicit `FinalEvalAuthorization` carrying an exact token, which the CLI only
> accepts from `--final-eval --confirm-final-eval <token> --final-eval-reason <why>`.
> `tests/model/test_folds_and_holdout.py` proves the seal by construction: poisoning every
> 2025 label leaves a development run byte-identical.
>
> Fold isolation is structural. A model implements one method, `fit_predict(train, validate,
> context)`, so there is no fitted object that could outlive a fold and nowhere to keep a
> statistic computed over the whole dataset. Preprocessing, baseline priors, penalty
> selection and residual quantiles are all fitted inside the training window, the last three
> on an inner *chronological* split of it.

## 8. Baselines

At least:

### B0 — prior production baseline

For veterans, prior-season fantasy PPG/total with age/availability shrinkage; rookies assigned position/draft-capital prior.

### B1 — simple regularized model

ElasticNet/linear or simple gradient boosting on compact feature set.

### B2 — simple market-gap baseline for arbitrage

`market_adp - fair_rank`, with no learned parameters beyond optional percentile normalization.

Baseline code remains in repo after better models are promoted.

> **Phase-3 implementation.** `ffdraft.modeling.baselines`.
>
> **B0 — naive prior production.** For a veteran with usable prior production: prior-season
> points per game in the row's own scoring flavour (STD and PPR are carried explicitly;
> half-PPR is their mean), optionally shrunk towards the position's typical training-fold
> rate, times the training-fold mean games played by players in the same previous-season
> availability cohort and age cohort. For a player without usable prior production —
> rookies, and veterans whose previous season produced no qualifying stat line — the
> training-fold mean season total for his draft-capital bucket. Every statistic is estimated
> on training rows only; the shrinkage weight is chosen from a four-value predeclared grid
> on an inner chronological split of the training window.
>
> B0 is deliberately a **strong** naive baseline. The obvious alternative, last season's
> point total, is beaten by it on every development season tried, because games played last
> season is itself an availability signal and conditioning the multiplier on it uses that
> signal honestly. A baseline chosen to be easy to beat would make the promotion gate
> meaningless.
>
> **B1 — simple regularized model.** Closed-form ridge on the Phase-3 core feature set, with
> training-fold median imputation, an explicit missingness indicator per imputed column, and
> training-fold standardization. The penalty comes from a five-value predeclared grid chosen
> on the same inner chronological split. Its job is to say whether nonlinear boosting is
> buying anything over an ordinary regularized model.
>
> **Baseline uncertainty.** Neither baseline is given a fabricated fixed-width interval.
> Both emit the same five quantiles as the candidate, built from residuals collected on the
> inner chronological split — fit on the earlier training seasons, residuals from the latest
> one or two — stratified by predicted level where a stratum has at least 100 rows and
> pooled otherwise. No validation-season row influences its own predictive interval.

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

> **Phase-3 implementation.** `ffdraft.modeling.candidates` implements Candidate A as **Q1**:
> LightGBM quantile regression, one booster per position x scoring preset x quantile, over
> P10/P25/P50/P75/P90, predicting the season point total directly. The configuration is
> fixed and predeclared for the whole phase — 250 rounds, learning rate 0.05, 15 leaves, a
> 30-row leaf minimum, feature and row subsampling, L2 of 1.0 — with no search of any kind:
> no grid, no Optuna, no early stopping against a validation season, no feature-selection
> loop. Determinism is enforced rather than hoped for: one thread, LightGBM's
> `deterministic` and `force_row_wise` modes, and every seed derived from the experiment seed
> plus the group identity. Missing values reach LightGBM as NaN and are handled natively,
> which is why the nullable Phase-2 columns were never imputed upstream.

### 9.2 Candidate B — availability × performance

Two components:

1. availability distribution / expected games active;
2. conditional points-per-active-game or usage/performance distribution.

Monte Carlo combines them.

Potentially more interpretable and responsive to current status, but only promote if it improves out-of-time probabilistic/rank metrics enough to justify complexity.

> **Phase-4 implementation, and the promotion (ADR-033).** `ffdraft.modeling.candidates`
> implements Candidate B as **CB**, and it is the production model. Two LightGBM quantile
> components over the same `intrinsic_core_v1` features: **availability**, modelled as the
> rate `games / fantasy_horizon_weeks` so 16- and 17-week seasons are comparable inside one
> training window, and **conditional performance**, fantasy points per *active* game, fitted
> only on training rows with at least one game because the ratio is undefined for the others.
> The composition is `games x points-per-game` with zero games scoring exactly zero and
> nothing clipped from below - this project's scoring presets make a negative season total
> genuinely possible, and 92 occur in the historical dataset.
>
> The two components are **not** sampled independently. A Gaussian copula couples them
> through one correlation per position x scoring preset, estimated inside the fold on an
> inner chronological split from probability-integral transforms of both components. The
> fitted value is positive in all sixty development groups (median 0.323), so independence
> would have been a measurably wrong assumption rather than a harmless simplification. The
> parameter necessarily describes players who played, since points per game does not exist
> for the rest; that extrapolation is stated in the model card.
>
> Why the separation earns its complexity here: 44% of eligible player-seasons record zero
> games, so a direct-total model spends much of its capacity on an availability question
> dressed as a scoring question. Against the calibrated direct model, CB improves MAE,
> pinball, Spearman and top-K retrieval with every paired interval excluding zero.

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

> **Phase-3 implementation.** Crossing is *measured*, not assumed away. Every experiment
> reports the raw row-level crossing rate and the mean crossing magnitude in fantasy points
> before any repair, alongside empirical P10-P90 and P25-P75 coverage and the corresponding
> mean interval widths. Coverage is never reported without width: an interval wide enough to
> swallow every observation is uninformative, not calibrated. The only post-processing Phase
> 3 applies is a deterministic sort of each row's quantiles, which is the minimum needed for
> pinball loss and coverage to be well defined; the rate it repairs is reported separately.
> Conformal or residual calibration belongs to Phase 4 and must be fitted on allowed
> development folds, never on the sealed holdout.

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

> **Phase-4 implementation.** `ffdraft.simulation.sampler` builds a monotone piecewise-linear
> quantile function per player and refuses to be constructed from a crossing grid - repair
> happens upstream, so the sampler can assume monotonicity rather than silently sorting.
> Interior points interpolate linearly between the two bracketing levels; exterior points
> continue the slope of the nearest interior segment and clamp to domain bounds derived from
> the **training** range alone (5% of the range below the observed minimum, 15% above the
> maximum - asymmetric because records fall upward far more often than a season collapses
> below the worst ever seen). One formula covers interior and tail because the segment index
> is clipped rather than special-cased, so there is no discontinuity at P10 or P90.
>
> Each player's uniform stream is derived from the model version, the simulation version, the
> scoring preset, the build id and **his own id**, so a player's draws do not change when
> another player enters or leaves the pool. The league preset is deliberately *absent* from
> the seed material: the same simulated seasons are re-allocated under every roster shape, so
> a preset-to-preset difference in VORP is a scarcity difference rather than Monte Carlo
> noise. Player draws are independent; V1 models no teammate or game-script correlation, and
> section 23 states that limitation publicly.

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

> **Phase-4 implementation.** `ffdraft.simulation.vorp` is the draw loop around that one
> algorithm, and it adds nothing to it. Every draw hands a whole sampled season to
> `allocate_starters` and subtracts *that draw's* replacement baseline from *that draw's*
> points. **Replacement is resampled with everyone else**, which is the entire point:
> subtracting one fixed baseline from every quantile would make VORP a shifted copy of
> points and would understate uncertainty exactly where scarcity is uncertain. A draw where
> the top backs collapse is a draw where replacement is low and the survivors are worth more.
>
> A player whose position had no replacement baseline in any draw gets a null VORP, and the
> production build withholds him from the published board with a counted quality check rather
> than shipping an invented zero. With a production-sized pool that never fires.

### Superflex future extension

Would require joint QB/RB/WR/TE slot optimization. Do not fake superflex by reusing 1QB replacement ranks.

## 13. Fair ranking

Primary fair rank = descending expected or median simulated VORP. Pick one before final evaluation; preferred initial default is **median VORP** for robustness, while expected VORP remains visible.

Tie break is deterministic per `DATA_CONTRACTS.md`.

Do not bake upside preference into rank. Ceiling/floor are displayed separately.

> **Phase-4 implementation (ADR-034).** The choice was settled by measurement rather than
> preference, under a rule frozen before the evidence existed. Both statistics were scored
> against the realized VORP labels Phase 2 built, over the full eligible universe of every
> development season and every scoring x league preset. The rule allowed expected VORP to win
> only by materially improving top-K retrieval - the part of the board a draft sheet is
> mostly about, and the part ADR-029 recorded as Q1's weakness - without deteriorating global
> rank correlation or collapsing a position. The selected statistic, its evidence and the
> tie-break that applied are in `docs/experiments/phase4-simulation-ranking/`.

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

> **Phase-4 implementation.** `ffdraft.tiers.dynamic` implements it, and the study reaches it
> **only** when a frozen rule refuses PELT - either no penalty in the grid is admissible or
> the promoted one fails the stability gate. Both attempts are recorded in the report, so an
> escalation is visible rather than inferred.
>
> The two algorithms optimize different things, which is the point. PELT with an RBF cost
> finds where the *kernel mean* of the feature vector changes. This one minimizes within-tier
> squared quantile distance, and because the L2 distance between two quantile functions on a
> common level grid is the 2-Wasserstein distance between the distributions, that is
> minimizing within-tier Wasserstein dispersion directly - the phrase this section uses.
>
> Three implementation choices: the solution is **exact** (contiguous segmentation with an
> additive per-segment cost is a shortest path, solved by dynamic programming in O(n^2) with
> prefix sums, which removes "a local optimum" from the list of things a boundary could be);
> it uses **three quantiles rather than four features**, because the interquartile spread the
> PELT candidate also passes *is* P75 - P25 and would be counted twice under an L2 cost; and
> its cost is **normalized per feature**, so a penalty means roughly the same thing under
> both algorithms and the frozen grid stays interpretable across them.

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

> **Phase-4 measurement (ADR-035).** The thresholds were declared in `phase4_tier_stability_v1`
> before any tier existed, and the promoted segmentation **fails** one of the six. The
> failure is specific and worth reading carefully, because it is not "the algorithm is
> wrong":
>
> | Quantity | Bar | Measured |
> |---|---|---|
> | bootstrap adjusted Rand | >= 0.60 | 0.865 |
> | boundary agreement | >= 0.50 | **0.239** |
> | singleton rate | <= 0.20 | 0.040 |
> | tier-count CV | <= 0.25 | 0.045 |
> | monotonic tier pairs | >= 0.80 | 0.845 |
> | cross-preset ARI | >= 0.50 | 0.529 |
>
> **Membership is reproducible; boundaries are not located.** Over 1,200 replicates the
> segmentation used 283 of 299 possible cut sites at least once and only 4 survived in a
> majority. The median promoted boundary sits on a 0.55-point P50 cliff against a 80-130
> point P10-P90 width, and the median probability that the player below a boundary outscores
> the player above it is 0.497 - a coin flip.
>
> The cause is a conflict between two frozen rules rather than a property of either
> algorithm. `max_largest_tier_share = 0.25` forbids any tier holding more than a quarter of
> a 300-deep board, but the deep tail of that board genuinely is one large near-replacement
> group; the rule therefore forces cuts inside a flat region, which is exactly what a
> bootstrap cannot reproduce. The same grid offers penalties whose boundary agreement passes
> (3.0 at 0.517, 8.0 at 0.500) and both are inadmissible on largest tier share. Neither
> threshold was moved after the fact; the remedy is a new rule version with its own evidence.

> **Phase-4 implementation (ADR-035).** `ffdraft.tiers` implements the PELT candidate on the
> rank-ordered matrix of standardized P25, P50, P75 and interquartile spread of simulated
> VORP, with `min_size=1` so a genuinely isolated top player may stand alone. The penalty
> comes from a fixed six-value grid declared before any of it ran; there is no search outside
> the grid and no extra value added after seeing the diagnostics.
>
> **The bootstrap resamples simulated seasons, not players.** Tiers are a function of the
> Monte Carlo VORP distribution, so the honest question is how much of the board is a
> property of the model rather than of these particular draws. Each replicate resamples draw
> indices with replacement, recomputes every player's VORP summary, **re-ranks** the board and
> re-segments it - holding the fair ranks fixed would flatter every boundary, because the
> ranking comes from the same draws.
>
> Every boundary carries diagnostics computed identically for boundary and non-boundary
> adjacent pairs - the P50 cliff, a standardized effect size, and the probability the lower
> player outscores the higher one under a transparent normal proxy - which is what makes
> "this boundary separates more than a typical pair inside a tier" a ratio rather than an
> impression. Thresholds, results and the promoted penalty are in
> `docs/experiments/phase4-tier-segmentation/` and `models/cards/tier-method.md`.

## 15. Tier labels

Ordinal 0 -> `S`, 1 -> `A`, 2 -> `B`, etc.

If the board requires more segments than comfortable letter labels, maintain semantic tier ordinal in data and allow UI labels such as `Late 1`, `Late 2` after `F`. Do not merge statistically distinct tiers solely to keep a meme-style alphabet.

> **Phase-4 implementation.** `ffdraft.tiers.labels` maps ordinal 0-6 to `S` through `F` and
> everything deeper to `Late 1`, `Late 2` and so on. The ordinal is the data and the letter is
> presentation: nothing downstream computes with a letter, and a letter carries no claim
> beyond "the segmentation put a break above this group".

## 15.1 Phase-5 status: A0 only, and what it is

Sections 16 and 17 describe the **learned** arbitrage design. None of it is built, and ADR-010 says why on measured source evidence: MyFantasyLeague's historical export is a season-long aggregate recomputed at request time, so a historical "market cost" embeds drafts held after the season's outcomes were partly known. There is no honest realized-surplus label to fit against, and there will not be one until at least three draft seasons of this project's own point-in-time snapshots exist.

What ships is **A0**, frozen in `ffdraft.arbitrage` (ADR-040):

```text
rank_gap           = market_adp - fair_rank            # positive = bargain
regional_value_gap = ln(market_adp / fair_rank)        # same sign, region-normalized
arbitrage_score    = midpoint percentile of regional_value_gap, within one preset block
```

Fair rank is the promoted median simulated VORP (ADR-034). **Tier ordinals and tier edges are not inputs**: the tier stability gate failed (ADR-035) and fair rank did not, so the failed quantity does not propagate into the arbitrage score, and tier instability is deliberately *not* turned into an arbitrage confidence penalty.

`expected_surplus_vorp` and `p_positive_surplus` are null on every row and are not approximated. `confidence` is a data-quality rubric, not a probability (ADR-041). `market_trend` is a trailing seven-day slope over retained snapshots and is null until three observation days spanning three days exist (ADR-042).

## 15.2 Historical injury features: a 2027 refresh candidate, not a Phase-5 addition

Integrating Sleeper's current injury data (ADR-043) makes an adjacent idea tempting: nflverse publishes historical weekly injury reports, so the intrinsic model could learn from prior-season injury history. It probably should, eventually. It must not now.

Adding the family would require a new feature-set version, a full historical feature rebuild, a new rolling evaluation, a new candidate comparison — and a **new final holdout**. The 2025 holdout was evaluated once and is spent (ADR-036). There is no untouched season left to promote a new feature set against in 2026, and promoting one without a holdout would abandon the discipline that makes every other number in this project mean something.

A future refresh may investigate, only where each can be reconstructed leakage-safely against the draft anchor and the licensing and semantics still hold:

- prior-season injury-report weeks;
- repeated limited/DNP practice patterns;
- prior-season games missed by injury category;
- recurring body-part or injury-category signals.

`intrinsic_core_v1` is unchanged, no `intrinsic_core_v2` exists, and `intrinsic-cb-hurdle-v1` was not retrained. **The current Sleeper annotations are not a substitute for model features**: they describe today, the model has never seen them, and a reader looking at an injury badge beside a fair rank is looking at two independent things (ADR-044).

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

> **Phase-4 implementation.** The tier artifact publishes `uncertainty` = the interquartile
> range of simulated VORP (`p75_vorp - p25_vorp`), which is a width in fantasy points with a
> stated meaning rather than a manufactured 0-100 score. Data-quality context travels
> separately in `quality_flags`: `rookie`, `no_prior_season_stats`, `no_depth_context`,
> `no_current_roster_entry` and the current roster status codes. Nothing here is a learned
> confidence, and no single number pretends to combine them.

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

> **Phase-4 implementation.** `ffdraft model-card` generates `models/cards/intrinsic-<version>.{md,json}`
> and `models/cards/tier-method.{md,json}` from the committed experiment reports and the model
> artifact. They are generated rather than written, for the same reason
> `docs/FEATURE_DICTIONARY.md` is: a number in a card that no command produces is a number
> that can drift.

## 23. Important limitations to state publicly

- fantasy outcomes have substantial injury/role randomness;
- independent-player Monte Carlo omits teammate/team correlations in V1;
- current free injury history may be incomplete after nflverse source changes;
- rookie projections are lower-information;
- ADP sources may represent specific platforms/league cohorts rather than all fantasy players;
- model rank is decision support, not certainty.

> **Phase-4 additions, all measured rather than asserted.**
>
> - **There is no preseason injury feature, in any season.** No nflverse source publishes an
>   injury report at a draft anchor (ADR-011), so a player entering the season hurt looks
>   healthy to this model. This is a coverage gap in the sources, not an oversight.
> - **The 2021 horizon boundary was measured and left in place.** A horizon-normalized target
>   was built and rejected (ADR-032); season totals still sit on a ~6% different scale either
>   side of 2021.
> - **Pooled interval coverage overstates the interval width** because the promoted model
>   represents "never plays" as a genuine atom at zero. Coverage is reported split by whether
>   the player appeared in a game.
> - **The availability/performance dependence is estimated on active players only**, because
>   points per game is undefined for the rest, and extrapolated to everyone.
> - **Tier boundaries move between builds.** How much is measured by bootstrap and published;
>   deep boundaries are far less stable than the top of the board.
> - **Current roster status is metadata, never signal.** It can annotate a published row or
>   remove a retired player from the board, but it cannot move a prediction: it has no
>   development-era support and could not be validated.
