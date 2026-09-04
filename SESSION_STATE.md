# Session State

This file is durable cross-session state for coding agents. Keep it concise and factual.

## Current phase

**Phase 12 — implemented 2026-09-04. In-Season mode exists, end to end.** The accepted model
reaches disk as a versioned production artifact, a deterministic season-state rule decides which
product the site shows, a rest-of-season build publishes two new artifacts behind their own
freshness gate, and the frontend has an In-Season mode beside the Draft mode it does not replace.
Release 2's definition of done is met with **one release blocker recorded**: nothing in this phase
has run against a live 2026 in-season week, because the season has not started.

### The productionization question, answered first

Phase 11 validated `RC1` chronologically and persisted **no** `models/production/intrinsic-ros-v1`.
Serving 2026 needs a fit, and ADR-077's literal wording — no change to the accepted model — would
have forbidden the very fit that serves it. **ADR-078 (`ros_production_fit_v1`)** names the
boundary instead of blurring it:

| a refit is | a methodology change is |
|---|---|
| the same architecture, parameters, calibration, composition and seed rule | any edit to any of those |
| a wider *training window* of already-permitted seasons | a wider *feature set*, a new target, a new fallback |
| checkable: the configuration hash is unchanged | the configuration hash moves |
| carries **no** performance claim — it was scored on nothing | needs a fresh sealed season |

Three refit reasons are permitted and recorded on the artifact: `initial_production_fit`,
`new_completed_season`, `reproduction`. ADR-077's rule against real model changes is untouched.

### What Phase 12 built

| | |
|---|---|
| Production artifact | `models/production/intrinsic-ros-v1/` — 121 files, 12 group boosters, committed |
| Configuration hash | `d79133847436f04f` (digest of architecture; excludes window, timestamp, SHA) |
| Training window | **2017-2025**, 455,157 rows, refit reason `initial_production_fit` |
| Sealed-season use | 2025 included under an explicit authorization token: the holdout was already spent |
| Serving season | 2026 — a fit at or after the served season is refused at the door |
| Feature contract | `f5ad9df207795351` / `f0384c75cac8218a`, both asserted at load and at inference |
| Season-state rule | `season_state_v1` — derived from the NFL schedule, never a date literal |
| Freshness rule | `ros_source_freshness_v1` — a `through_week=N` build needs weeks 1..N complete |
| Methodology | `phase12_ros_v1`; draws 10,000, the ADR-074 declared fallback |
| New artifacts | `ros_tiers`, `inseason_opportunity`, `ros_build_metadata` (3 new schemas) |
| Behaviour source | Sleeper add/drop, `behavior/` prefix on the append-only snapshot store |
| Opportunity method | `phase12_opportunity_v1` — counts over a named window, never a price |

### Two rules, two gates, deliberately not one

**Played** and **available** are different facts and are decided separately. `season_state_v1`
answers *which product* (has the season's first regular-season kickoff happened, plus a 6-hour
completion buffer); `ros_source_freshness_v1` answers *which week may be built* (does upstream
carry every scheduled team for weeks 1..N, with no gap behind N). A season that has started with
no complete upstream week yields a **critical** `ros.no_complete_week`, not a week-0 board.

### The firewall is checked, not asserted

The Opportunity Board copies seven intrinsic fields from the ROS board verbatim, and
`cross_artifact.intrinsic_firewall` compares them **over the published bytes** of both artifacts.
Behaviour decides *visibility* only: a Sleeper signal can surface a player from beyond the tier
depth, and can never move a rest-of-season number. `tests/unit/test_opportunity_board.py` asserts
both directions.

### Publication is all-or-nothing

`run_ros_build` stages the whole bundle into a sibling directory and `os.replace`s it only after
every artifact validates. An earlier version wrote metadata after a failed artifact — a partially
refreshed board, which is the failure mode the roadmap names. A pool too small to have a
replacement now **withholds** rather than publishing NaN (the draw loop records "no baseline" as
NaN, and `is_not_null()` does not catch it; the filter is `is_not_null() & is_finite()`).

### The rehearsal, and why it is 2024 and not 2025

Today is 2026-09-04. The first 2026 regular-season kickoff is **2026-09-10T00:20:00Z**, so
`season-state` resolves to `preseason_draft` / `draft` and the live in-season path **cannot** be
exercised on 2026 data. It was rehearsed instead: a second, **non-production** fit on 2017-2023
serving 2024, then a real `build-ros --season 2024 --through-week 8`:

```
season state  : regular_season (in_season)     ros_tiers   : 4,500 records
build id      : 2024w08-intrinsic-ros-v1-...   long absence: 241 players flagged
quality gate  : pass (0 critical, 3 warning)   validate-artifacts: 0 critical, 0 warning
```

The three warnings are the declared ones: tier stability, the 10,000-draw fallback, and the absent
behaviour feed. **2024 was chosen over 2025 deliberately** — the sealed season is spent, and
scoring anything on it again would be a second bite. No accuracy metric was computed on the
rehearsal at all; it proves the pipeline runs, not that the model is good.

### The dataset content hash moved, and the row count did not

The Phase-12 dataset rebuild produced content hash **`1590cde5…`** where Phase 11 recorded
**`c976f5f8…`** — with **identical** row count (455,157) and **identical** feature-set and schema
hashes. That is an upstream data revision inside nflverse, not a code change: the columns, the
contract and the cutoff rule all reproduce. The production artifact records the hash it was
actually trained on via its dataset manifest, which is the point of recording it.

### What Release 2 does not have

**One blocker, recorded rather than worked around: no live in-season week has ever been built.**
Everything in-season is proven on fixtures and on the 2024 rehearsal. The first real exercise is
the Tuesday after Week 1 (`"40 12 * * 2"`), and until it runs the in-season path is
*validated but not observed*. `docs/releases/v2.0.0.md` carries this clause by clause.

### Commands and gates run (Phase 12)

```bash
uv run ruff check . && uv run ruff format --check .   # clean, 240 files
uv run mypy                                            # 152 source files, clean
uv run pytest                                          # 1,414 passed, 4 live-network deselected
uv run ffdraft build-fixture-artifacts                 # 0 critical, 5 warning (documented fixtures)
uv run ffdraft validate-artifacts <fixture build>      # 0 critical, 0 warning
npm run lint && npm run typecheck                      # 0 errors (3 pre-existing compiler warnings)
npm run test -- --run                                  # 291 passed
npm run build                                          # clean
npm run e2e                                            # 88 passed (chromium, mobile, a11y)
npx playwright test --project=smoke-chromium           # 13 passed
npm run e2e:screens -- docs/visual-qa/2026-09-04-phase12   # 41 screens, exit 0
```

Phase-12 specific:

```bash
uv run ffdraft season-state                             # preseason_draft / draft, next change 2026-09-10
uv run ffdraft train-ros-production                     # the committed artifact, 2017-2025
uv run ffdraft build-ros --season 2024 --through-week 8 # the rehearsal, gate pass
uv run ffdraft capture-behavior                         # Sleeper add/drop into behavior/
uv run ffdraft ros-model-card --model models/production/intrinsic-ros-v1
```

Playwright needs `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium` in this sandbox
(the pinned headless-shell build is absent; `/opt/pw-browsers/chromium` is the working binary
here, unlike the versioned path Phase 11 recorded). `npm run e2e:browsers` (Firefox and WebKit)
remains runner-only, as since ADR-059.

### Four UI defects the screenshots caught that the tests did not

Recorded because each was invisible to a passing suite and visible in a picture:
colliding table headings on the opportunity board; a wide table's caption running off the right
edge; the footer naming the **draft** model under a rest-of-season board; and a machine phrase
spliced mid-sentence in the behaviour-outage notice. All four are fixed and all four now have a
screenshot. A fifth was found by measurement: a season-mode band on every page pushed the
arbitrage board below the fold on a phone, so the indicator moved into the masthead and the band
now renders only when there is something to switch to.

### One pre-existing flake, root-caused

`a11y.spec.ts` "a visible focus indicator exists on every custom control" failed about half the
time when the mobile project ran first — **on the pre-existing base as well**, verified in a
worktree at the merge commit. Cause: `.status-chip` and six sibling controls declared
`transition: all`, which includes `outline-width`, so the shared focus ring **animated in over
160ms** and the assertion sampled it mid-transition at 0px. A keyboard user's own position was
being animated. Fixed with a `--t-control` token naming the surface properties; five consecutive
combined runs green.

### What Phase 13 inherits, and what it must not assume

- **`intrinsic-ros-v1` is frozen, and now has an artifact to be frozen *as*.** A refit for a newly
  completed season is routine and needs only `RosRefitReason.NEW_COMPLETED_SEASON` plus an
  unchanged configuration hash. Anything that moves that hash is a methodology change and needs a
  fresh sealed season (ADR-077, ADR-078).
- **The in-season path has never seen a live week.** Treat the first post-Week-1 refresh as an
  observation, not a formality.
- **The behaviour feed is optional by construction and must stay that way.** Its failure is a
  warning that empties three columns; a critical ROS input failure withholds the whole bundle.
- **Do not add a learned opportunity score.** The board is deliberately three orderings over
  unlike units and no blend. Blending an add count with a VORP would manufacture a rank gap out
  of quantities that do not share a scale.
- **The two ranks are two models.** `fair_rank` and `ros_fair_rank` may sit side by side and may
  never be averaged, differenced into a single "true" rank, or presented as versions of one
  number.

---

## Phase 11 — implemented 2026-09-04, merged 2026-09-04 as jeisey/jeisey-tiers#32

**Exit gate met after the production-readiness pass.** The
rest-of-season model `intrinsic-ros-v1` is built, validated in development and on the sealed
season, and **accepted for Phase 12**. It failed `ros_promotion_v1`; that failure is preserved
in full, and the readiness pass established the failing clause was mis-specified for a
zero-inflated target rather than describing a defect. Under the successor `ros_promotion_v2` —
frozen and committed before it touched any evidence — `RC1` is **promoted** (ADR-075, ADR-077).
Phase 11 remains entirely offline: no artifact, no schema, no frontend change, nothing
published. Phase 12 has **not** been started.

### What Phase 11 built

| | |
|---|---|
| Grain | `season × through_week × player_id × scoring_preset` |
| Cutoff rule | `ros_cutoff_v1` — week N reads weeks 1..N of season Y and any earlier season |
| Label | `ros_label_v1` — remaining games, remaining points per appearance, remaining points |
| Dataset | **455,157 rows**, 2017-2025, content hash `c976f5f8…`, `data/ros/` (gitignored) |
| Feature set | `ros_core_v1` (`f5ad9df207795351`) — **121** inputs: 78 inherited preseason + 43 in-season |
| Schema hash | `ros_features_v1` = `f0384c75cac8218a` |
| Candidate | `rc1_ros_hurdle_v1` — availability × conditional performance, Monte Carlo composed |
| Comparator | `R2` (shrinkage blend), picked by the frozen rule, not by preference |
| Sealed season | 2025, **CONSUMED** once on 2026-09-04 |
| Promotion | **not promoted** under `ros_promotion_v1` (preserved); **promoted** under `ros_promotion_v2` |
| Production status | **`RC1 ACCEPTED FOR PHASE 12`** (ADR-077) |
| Replacement | `rostered_depth` (`ros_replacement_v1`) |
| Model card | `models/cards/intrinsic-ros-v1.{md,json}` |

### The result, and the clause that refused it

`RC1` against `R2`, paired within cell:

| | development (948 cells, 253,197 rows) | sealed 2025 (192 cells, 53,307 rows) |
|---|---|---|
| MAE | **−2.4632** [−2.5305, −2.3958] | **−2.2497** [−2.3774, −2.1285] |
| mean pinball | **−0.8084** [−0.8328, −0.7857] | **−0.7136** [−0.7513, −0.6755] |
| Spearman | **+0.1203** [+0.1184, +0.1229] | **+0.1163** [+0.1120, +0.1216] |
| top-K recall | −0.0034 [−0.0044, +0.0079] — unresolved | −0.0078 [−0.0141, +0.0156] — unresolved |

Clauses 1, 2 and 3 pass in both. **Clause 4 fails on `games_played_band / no_games`**:
candidate P10-P90 coverage 0.964 in development, 0.957 on 2025, against a [0.60, 0.95] band.

**That clause was mis-specified, and the readiness pass proved it rather than asserting it.** A
P10-P90 interval covers 0.80 only for a *continuous* target. Where a predictive distribution has
an atom of mass `p >= 0.10` at its own tenth percentile, a **perfectly calibrated** interval
covers exactly **0.90**; where `p >= 0.90` both quantiles are zero, the interval collapses to a
point, and coverage is `p`. So a perfectly calibrated forecaster with an interval of **width
zero** breaches v1's ceiling — a clause written to catch "an interval so wide it says nothing"
refuses the narrowest possible correct interval. A test asserts all three cases.

The measurement agrees. The **climatological reference** (`ffdraft.ros.reference`) — the
coverage a calibrated, player-blind forecaster attains, computed from outcomes alone — is
**0.843-0.926** across all twenty-two development cohorts and **0.926** on the zero-game cohort,
where P(Y=0) = 0.885. Not one cohort is near 0.80. v1's band was centred on a value the target
makes unreachable everywhere.

**The threshold was never moved** (ADR-073 stands). `ros_promotion_v2` was frozen in `5e532c7`
containing the rule and no result, then applied to the prediction frame the original run wrote —
same 253,197 rows, no refit, macro metrics reproducing to the digit. It keeps every v1 threshold
that remained meaningful, adds a clause v1 lacked (4c, cohort pinball loss), states width against
climatology (4d), states coverage against the attainable reference (4e), and **tightens** the
under-coverage allowance from 0.20 to 0.15. **PROMOTED** (ADR-075).

**The margins are the evidence that v2 was not reverse-engineered.** The three tightest clauses
in the whole gate are all *under*-coverage, all comfortable passes under v1 and near-failures
under v2: `high_capital_rookie` 0.763 against an attainable 0.898 (**0.015** headroom),
`changed_team_in_season` 0.782 against 0.900 (0.032), `extreme_uncertainty` 0.781 against 0.880
(0.052). The cohort v1 refused `RC1` for is now only the tenth-tightest of twenty-two.

One extra cohort fails on 2025 only: `in_season_arrival`, MAE 1.08 → 1.69 on 315 rows, where
the baseline confidently predicts ~0 with a 1.7-point interval and is mostly right. The
candidate is better *ordered* on the same rows (Spearman −0.060 → +0.160).

**That cohort was investigated on development evidence only, and needs no model change**
(ADR-076). On 4,296 development rows `RC1` wins the proper score by 20.7%, wins ordering, edges
MAE, and is far better calibrated: the baseline under-covers by **0.237** against attainable,
carrying a 12.0-wide interval where climatology is 28.3 — it is overconfident, not precise. A
sparse-history fallback would swap a calibrated forecast for that one, and would change
production outputs with no sealed season left to evaluate them honestly. **No change was made,
so the spent 2025 result still describes the model being accepted.**

### The leakage audit found a real defect

Universe membership was a *season* property: anyone who appeared anywhere in season Y got a row
at every cutoff of Y, so a week-3 snapshot contained a row for a player who signed in week 9.
The row was all zeros; its **existence** was the leak. The constructive audit caught it —
rebuild week 3 from a panel truncated at week 3 and the row count fell from 120 to 96.

Nothing shipped wrong: a downstream `position` filter had been dropping those rows because
position for an unobserved arrival is null. That was luck. The rule now lives in
`build_in_season_features` where the audit can see it (ADR-068).

### The value study

- **Replacement.** Both interpretations run over identical draws, twelve scenarios. They
  disagree materially — worst fair-rank Spearman 0.9981, largest mean |Δrank| in the top 150
  2.15, smallest top-50 overlap 0.940, largest single move 41 places — so `rostered_depth` is
  used. `bench` in `config/league-defaults.yaml`, carried for user context in V1, is now
  load-bearing for the in-season board (ADR-071).
- **Convergence: fails, as preseason did.** No count in [1000, 2500, 5000, 10000] meets every
  tolerance; at 10,000 the seed-to-seed tier ARI is 0.451 at week 4 against a 0.900 bound. The
  *value* quantities are inside tolerance; what does not converge is the tier partition.
- **Tier stability: fails on boundary agreement, 0.167 against 0.500.** Everything else passes
  and by a distance — bootstrap ARI 0.857, no singletons, tier-count CV 0.074, cross-preset ARI
  0.524, and realized remaining VORP falls across **100%** of adjacent tier pairs. Membership is
  reproducible; the boundary's *location* is not. Penalty 3.0, 6.8 mean tiers (ADR-074).

### What Phase 12 inherits, and what it must not assume

- **`intrinsic-ros-v1` is an accepted production model** under `ros_promotion_v2` (ADR-077).
  What that licenses: building the in-season product on it. What it does not: publishing a
  number without the ADR-076 disclosures, drawing a tier boundary as a line, presenting
  `ros_fair_rank` as comparable with the preseason `fair_rank`, or changing the model's outputs.
- **Six inherited limitations, all measured, none repaired.** Overconfident on high-capital
  rookies (coverage 0.763 against an attainable 0.898 — the tightest clause in the gate, 0.015
  from failing); close to unable to order the long-absence cohort (Spearman 0.311 against 0.797);
  conservative intervals on the zero-game cohort (14.5 against a climatological 4.5); the spent
  sealed season; tiers as bands not lines; no injury feature.
- **`returning_from_absence` carries a disclosure contract** (ADR-076): a machine-readable flag
  on the published artifact, `weeks_since_last_game` beside it, an explicit statement that no
  injury or practice-report information is used, no presentation as medical status, no
  colour-only encoding, and the measured ordering weakness in the published limitations. Phase 12
  implements it; Phase 11 built no UI.
- **`ros_promotion_v2` was never applied to 2025.** The saved sealed prediction frame is on
  disk; re-scoring it would have been one command. It was deliberately not done — running a
  newly written rule against the sealed season is using it to evaluate the rule, which is a
  second bite at a one-shot resource. `final_holdout.md` carries the v1 verdict alone and is
  unchanged by this pass.
- **The sealed season is spent, and the readiness pass changed no model output.** 2025 was
  opened once, before the pass began; no fallback, no retrain, no tuning, no feature was added,
  so the published out-of-time result still describes the model being accepted. **Any future
  change to `RC1`'s outputs invalidates that and needs a fresh sealed season** — which is why
  ADR-076 declines a sparse-history fallback rather than designing one.
- **Tier boundaries may not be drawn as lines.** Same finding as Release 1, same response: a
  band, and text that says so.
- **Nothing is published and nothing runs on a schedule.** `build-ros-dataset` performs network
  I/O and is not in `daily-refresh.yml`. The weekly availability rule — a week-N snapshot may
  only be built once the upstream release covering week N exists — is documented in
  `docs/OPERATIONS.md` and is Phase 12's to enforce.
- **There is still no injury feature, and the cohort that needs one is measurably the worst.**
  `returning_from_absence` Spearman 0.294 → 0.311 in development: both near-random. ADR-070
  records the exact four things a source would have to produce.
- **Release 1 and Phase 10 are byte-identical.** The only shared-code change is one optional
  parameter on `simulate_vorp` whose default is Release 1's rule, plus two additive members on
  the `Availability` enum. The preseason feature-schema hash is unchanged.

### Commands and gates run (Phase 11)

```bash
uv sync --frozen
uv run ruff check . && uv run ruff format --check .   # clean, 222 files
uv run mypy                                            # 140 source files, clean
uv run pytest                                          # 1,329 passed, 4 live-network deselected
uv run ffdraft build-fixture-artifacts                 # 0 critical, 5 warning (documented fixtures)
uv run ffdraft validate-artifacts <fixture build>      # 0 critical, 0 warning
npm ci && npm run lint && npm run typecheck            # 0 errors (2 pre-existing warnings)
npm run test -- --run                                  # 272 passed
npm run build                                          # clean
npm run e2e                                            # 70 passed (chromium, mobile, a11y)
```

Phase-11 specific, all run on this branch:

```bash
uv run ffdraft build-historical --last-season 2025      # 11,605 feature rows, gate pass
uv run ffdraft build-ros-dataset --last-season 2025     # 455,157 snapshot rows, gate pass
uv run ffdraft evaluate-ros                             # 5 folds, 948 cells, ~26 min
uv run ffdraft evaluate-ros-value                       # ~28 min
uv run ffdraft evaluate-ros --final-eval \
  --confirm-final-eval RELEASE-ROS-FINAL-HOLDOUT-2025 \
  --final-eval-reason "..."                             # the one sealed run, ~12 min
uv run ffdraft ros-attribution --season 2024 --through-week 8 --position RB
uv run ffdraft ros-model-card
uv run ffdraft feature-dictionary --ros

# The production-readiness pass. Re-scores the prediction frame the development run wrote:
# the same 253,197 rows, no model refitted, macro metrics reproducing to the digit.
uv run ffdraft evaluate-ros --predictions data/ros/ros_predictions_experiment.parquet
```

`npm run e2e:browsers` (Firefox and WebKit) remains runner-only in this sandbox, as it has been
since ADR-059. Phase 11 changed **no** frontend file, so the browser matrix has nothing new to
cover; the chromium/mobile/a11y suite was run anyway to prove the shared-code change to
`simulate_vorp` did not move a published number, and it did not. Playwright needs
`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` here — the
unversioned `/opt/pw-browsers/chromium` directory is not the binary.

---

## Phase 10 — implemented 2026-09-02, merged 2026-09-03 as jeisey/jeisey-tiers#27

Exit gate partially met. One criterion failed on measured evidence (FantasyPros publication)
and is recorded rather than rounded up.

### Post-merge corrections (2026-09-03)

Two defects, found by looking at the deployed site rather than at the test suite.

**1. `verify:board` failed the refresh** ([33709328259](https://github.com/jeisey/jeisey-tiers/actions/runs/33709328259)), on all 30 arbitrage rows, against a site that was correct. `verify-real-build.mjs` indexed cells by position; Phase 10 inserted three columns and `Score`/`Trend` moved. Fixed by reading columns from the header row, and by running `verify:board` in `ci.yml` so a frontend column change is caught on the pull request rather than in production (jeisey/jeisey-tiers#28).

**2. Phase 10 was never wired into production** (ADR-067). The refresh then ran green and published a board that was Release 1 with three extra column headings: no FFC, still 300 rows, `FP ECR` and `Spread` empty on every row. Every gate passed because each measured a part in isolation.

| symptom | cause |
|---|---|
| no FFC anywhere | `daily-refresh.yml` never called `capture-market-source` |
| one market, empty Spread | `pipeline/market.py` passed no `extra_quotes` |
| 300 rows | production published `TIER_BOARD_DEPTH`; `TIER_DEPTH_V2` and `build_surface_universe` were imported by no pipeline |
| `FP ECR` all null | the column shipped for a source that publishes nothing (ADR-064) |

Now: `ffdraft.market.extra` joins retained snapshots to the arbitrage build; `build-current --full-board` hands the untruncated universe to `build-arbitrage --full-board` so the surface rule can rescue beyond the depth; publication depth is `TIER_DEPTH_RULE.depth` (500) while Phase 4's frozen `TIER_BOARD_DEPTH` (300) is untouched; the coverage gate's severity depends on whether the caller certified a complete board; and the arbitrage table renders a market-dependent column only when some row has a value.

**3. The first refresh after the wiring failed the cross-artifact gate** ([33789677907](https://github.com/jeisey/jeisey-tiers/actions/runs/33789677907)). `cross_artifact.arbitrage_player_not_in_tiers` requires arbitrage players to be a subset of tier players — which is precisely what a surfaced row is not. Ten `redraft-10` players were rescued from beyond depth 500, published on the arbitrage board as designed, and rejected by an invariant that predated the rescue. The rule now exempts a row that declares itself an exception in both `outside_tier_board` and `surface_reasons`; an undeclared absence is still critical, and the inverse lie (flagged beyond the depth while tiers publishes him) is now caught too.

**4. The third refresh failed `verify:board`, and the audit found why there were three** ([33793938632](https://github.com/jeisey/jeisey-tiers/actions/runs/33793938632)). All thirty arbitrage rows mismatched against a page that was correct: the board defaults to FFC and the verifier compared the flat V1 `market_adp`, which is MFL's. The same assumption sat in the draft rail, the player card and a positional Trend-column check.

**No fixture had ever carried a second market** — not the Python golden artifact, not the TypeScript fixtures — so every local gate ran against a single-market bundle and every consumer that only misbehaves on the real shape was invisible. Both fixture generators now build two disagreeing markets, partial coverage, asymmetric dispersion and a priced surfaced player, so the gates exercise production's shape by default. The selector governs the whole page; an unpriced row keeps its place with an em dash.

**What the next production build will show, and what to check.** The tier board becomes 500 rows per block, so tier boundaries in the top 300 may move — the segmentation now sees 500 players. Confirm FFC appears in the market selector and that `build_metadata.json` lists it as `priced`. If FFC's capture failed, the board degrades to one market with a warning naming it, which is the intended behaviour and not a silent absence.

### Accepted source dispositions

| Source | Disposition | Semantics that must not be flattened |
|---|---|---|
| `fantasyfootballcalculator_adp` | **production_allowed** | ADP; **rolling 7-day** window; scoring exact (STD/HALF/PPR); **league size null and not claimable**; genuine per-player `stdev`; `high`/`low` are order statistics, not an SD |
| `myfantasyleague_adp` | production_allowed, **unchanged** | ADP; **season-cumulative**; `adp_sd` permanently null; cohort exactness is a per-preset verdict |
| `fantasypros_ecr` | **verify_before_use — retained, NOT published** | ECR only; dispersion measured in ranks; no ADP exists at this tier |
| `sleeper` | production_allowed | Player map once/day; add/drop are **behaviour**, never a price; `search_rank` is not ADP |
| ESPN | **disabled**, unchanged | — |

### FFC probe results (2026-09-02)

- Schema: `player_id, name, position, team, adp, adp_formatted, times_drafted, high, low, stdev, bye`; envelope `status, meta, players`; `meta.{type,teams,rounds,total_drafts,start_date,end_date}`. All fields 100% populated.
- **`teams=` accepted and ignored** — byte-identical per player across 8/10/12/14 in all three formats, **zero rows differing in nine comparisons**. ADR-056 reproduced, not overturned.
- Cohorts: standard 221 rows / 186 core / 1,794 drafts / deepest ADP 172.6; half-ppr 233 / 3,142 / 188.6; ppr 264 / 8,007 / 201.1.
- **Window: 7 days** (2026-08-26 → 2026-09-02). MFL is cumulative.
- `stdev` 221/221 populated, range 0.60–31.90.
- **FFC's whole population is under 300 rows**, so "FFC top 300" is the whole source.
- CSV path returns HTML; the JSON path with an explicit `year` is the reproducible one.

### FFC linkage

```text
rule phase10_linkage_v1   source rows 270 (48 non-core excluded)
relevant 222   accepted 222 (100.000%)   quarantined 0   top-300 unresolved 0
gate >= 90% -> PASS      accepted_by_method {resolved_exact_name_position: 222}
```

- Alias file: `config/market-aliases/fantasyfootballcalculator_adp.yaml` (222 entries).
- Report/quarantine: `docs/source-probes/2026-09-02/fantasyfootballcalculator_adp-linkage/`.
- **Every row matched exactly**; the fuzzy path was not needed once. It stays for the rookie spellings and mid-season signings that will arrive.
- `ffb_ids` enrichment: **not used and not vendored.** Coverage was 100% without it, and the roadmap makes it conditional on needing help. The licensing question it raises was therefore never reached.
- Generated aliases never outrank `config/identity-aliases.yaml`, which loads last.

### FantasyPros — the failed criterion

**The provisioned key is on the free tier.** Every response: `public_api_limited: true`,
`tier: "free"`, exactly ten rows. `limit`, `offset`, `start`, `page`, `max_results` and
`ranks` all returned the same ten rows and the same first player. Per-position calls reach
**40 distinct players** across QB/RB/WR/TE, against a documented `count` of 407 receivers and
225 tight ends.

**There is no ADP at all**: `/json/nfl/{season}/adp` → `403 Missing Authentication Token`;
`type=adp` returns the ECR row shape with no ADP field.

Endpoint that works: `GET /public/v2/json/nfl/{season}/consensus-rankings?position={QB|RB|WR|TE|FLX|ALL}&scoring={STD|HALF|PPR}&type=draft&week=0`.
`position=ALL` 400s without `type=draft&week=0`.

Captured fields: `rank_ecr, rank_ave, rank_min, rank_max, rank_std, pos_rank, tier,
player_ecr_delta, total_experts (93–109), last_updated ("9/02" — no year, no time, never
promoted to `source_as_of_utc`)`. Scoring axis genuinely reorders.

**Identity: joins by id, no linkage needed** — `sportsdata_id` 40/40 via Sportradar,
`player_yahoo_id` 36/40 via Yahoo.

**Budget:** 50/day (half the vendor's 100), 1 req/sec, both enforced in `RequestBudget`;
deterministic 12-request plan (4 positions × 3 scoring). Key read from `FANTASYPROS_API_KEY`
in Actions only, sent as `x-api-key`, never a query string, never printed or cached.

**Revisit condition (exact, and tested on every capture):** a key whose responses omit
`public_api_limited` (or set it false) and whose `count` equals the rows delivered. Then flip
`MarketSourceSpec.publishable` — one line.

### Sleeper measurements

Player map 14,651,318 bytes (13.97 MiB) / 12,226 records / 4,041 core; `player_id` 1.000,
`sportradar_id` 0.948, `yahoo_id` 0.559, `espn_id` 0.547, `gsis_id` 0.312, `search_rank` 0.974.
Once-per-day rule unchanged. Trending returns a **bare list** of `{player_id, count}` with no
timestamp, so the snapshot records the request: `limit` honoured exactly (5/25/100),
`lookback_hours` honoured (6h vs 24h share 24 of 25 ids; 6h vs 72h, 22).

### Tier depth and surface coverage

`phase10_tier_depth_v2` = **500**, superseding `phase4_tier_depth_v1` = 300, which is retained
so a Release 1 board stays reproducible.

**It is a reasoned choice, not a measured optimum.** `scripts/phase10_depth_analysis.py` was
written to measure it from the joined board and found the question **unanswerable from
published artifacts**: an arbitrage row exists only for a player already on the tier board,
so against a board published at depth 300 every "priced players beyond 300" count is zero
*by construction*. Run [33655647823](https://github.com/jeisey/jeisey-tiers/actions/runs/33655647823)
returned nine blocks of zeros; reading that as "300 is fine" would have been the
wrong-denominator mistake ADR-054 recorded elsewhere. The script now detects the circularity
and refuses to conclude from it.

Bounds that *are* measured: 300 is definitively too shallow (the roadmap's own motivating
case is one priced player beyond it); FFC's whole population is 221–264 rows with a deepest
ADP of 201.1; the deepest launch preset drafts 182 players. 500 is the smallest simple value
with headroom over the one measured bound.

**The safety net is the thing that was missing before.** The surface coverage gate is
*critical*: if 500 is ever too shallow a resolved top-market player fails the build rather
than disappearing quietly. Answering the question properly needs the full intrinsic board
joined against a market snapshot — a production build with the retained store attached — and
the first live multi-source refresh is where to re-check it.

Surface coverage required: **100%** of resolved top-market rows, enforced as a **critical**
check. Unresolved source rows are counted separately and never enter the denominator.

### UI

Market selector on Arbitrage: derived from what the build published, defaulting to **FFC
Recent** for draft week, with `Cross-market` offered only when two markets actually priced
someone. Window and observed-dimension text beside it. Per-source column headers; ECR in its
own column with `ecr_gap`; a `Spread` column that is null — not zero — when one market spoke.
Player card gains the full comparison table and the mini trend chart. Selection is in the URL
as `?market=`, validated for shape rather than membership so a link from a build with one
more source still opens. CSV gains twelve columns naming source and signal.

### Market-trend chart

`market_trend_series.json`, contract 1.0, generated from the retained snapshots. **Inverted y
axis** — up is earlier, up is more expensive — with the direction in text as well as colour.
Below three points it says so in words. The browser calls no vendor; a bundle test asserts the
fetch list contains no vendor host. The scalar `market_trend` remains for sorting, CSV and the
accessible summary.

### Commands and gates run

```bash
uv run ruff check . && uv run ruff format --check .   # clean
uv run mypy                                            # 118 files, clean
uv run pytest                                          # 1,196 passed, 4 live-network deselected
uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000
uv run ffdraft validate-artifacts <fixture build>      # 0 critical, 0 warning
npm ci && npm run lint && npm run typecheck            # 0 errors (2 pre-existing warnings)
npm run test -- --run                                  # 270 passed
npm run build                                          # clean
npm run e2e                                            # 70 passed (chromium, mobile, a11y)
npx playwright test --project=smoke-chromium           # 13 passed
```

The fixture build itself reports **0 critical, 5 warning** — every warning is a fixture that
exists to exercise a fail-closed identity path, and each is asserted by name in the pipeline
tests. The Playwright runs used the sandbox's pre-installed Chromium
(`PLAYWRIGHT_CHROMIUM_EXECUTABLE`), which is what `playwright.config.ts` already looks for.
**`npm run e2e:browsers` — the Firefox and WebKit smoke gate — cannot run here**, because
those two browsers are not present in the sandbox and are not downloadable through its egress
policy (ADR-059). It ran on a runner instead: `ci.yml` triggers on `pull_request`, so the
`browsers` job first ran when jeisey/jeisey-tiers#27 opened, and it **passed** — Firefox and
WebKit against the Phase-10 market selector, per-source headers and hand-drawn trend SVG.

New CLI: `ffdraft capture-market-source <source>`, `ffdraft link-market-source`.
New workflows: `source-probe-phase10.yml` (dispatch/request, inert),
`phase10-linkage.yml` (dispatch/request, commits the alias file).

### What Phase 11 inherited from Phase 10, and what it confirmed

- The multi-source **code path** is complete and fixture-tested; the **published** board still
  needs one production refresh that captures FFC into the private store. Nothing further is
  required in this repository for that.
- Every gate has now run somewhere: `chromium`, `mobile`, `a11y` and `smoke-chromium` in this
  sandbox, and the Firefox/WebKit cross-browser smoke on a runner, green on the PR. ADR-059
  still holds — that gate is runner-only here and must not be assumed reproducible locally.
- Sleeper add/drop retention is implemented but **has not yet run in production**, so the
  in-season history Phase 12 expects starts accumulating from the first refresh that includes
  it — not from today.
- The V1 intrinsic model, its methodology, its feature set and its fair ranks are untouched.
  Nothing in Phase 10 reads market data into an intrinsic feature, and the forbidden-feature
  guard still covers it. Phase 11 confirmed it from the other side: the same guard runs over
  the rest-of-season input list, and the two models share no target.

---

## Previous phases


**Phase 9B — complete. V1.0.0 released (2026-09-01).**

| | |
|---|---|
| Release date | 2026-09-01 |
| Tag | `v1.0.0` — <https://github.com/jeisey/jeisey-tiers/releases/tag/v1.0.0> |
| Release commit | `5511370a52dc057471f9756f1da480e5756d914c` |
| Live URL | <https://jeisey.github.io/jeisey-tiers/> |
| Final CI | [33525398786](https://github.com/jeisey/jeisey-tiers/actions/runs/33525398786) — green on the release SHA |
| Final daily refresh | [33526105451](https://github.com/jeisey/jeisey-tiers/actions/runs/33526105451) — success, deployed |
| Live smoke | [33526715705](https://github.com/jeisey/jeisey-tiers/actions/runs/33526715705) — nine presets, four CSVs, all live checks green |
| Build id | `2026-intrinsic-cb-hurdle-v1-20260901T153049Z` |
| Generated at | `2026-09-01T15:30:49Z` |
| Intrinsic model | `intrinsic-cb-hurdle-v1` |
| Methodology | `phase4_intrinsic_v1` |
| Arbitrage | `baseline (a0_rank_gap_v1)` |
| Feature set | `intrinsic_core_v1`, hash `7203befaa5be25a2` |
| Private store commit | `b0afbb8888a3871fd0d7ce5f8ecb96b627505656` |

Phase 9A — complete (2026-08-31). The frontend implements the owner's actual Claude Design source rather than a language inferred from his written brief.

Phase 8 — complete (2026-08-31). The site is live at **<https://jeisey.github.io/jeisey-tiers/>**, public, and refreshing itself daily at 07:17 America/New_York from sources it captures into a private store. The frontend was rebuilt around the owner's review, and every hardening track in the Phase-8 brief was run — apart from one item that could not be done and was recorded as blocked, which is what Phase 9A closed.

Phase 7 completed on 2026-08-22; the note below is its record and stays because it explains why the store lives where it does.

**The phase did not start where its task list said it did.** The append-only capture store lived on a `market-data` branch of this repository, and ADR-038's own consequences said that was safe *because the repository is private*. GitHub visibility is a property of a repository, not of a branch — there is no private branch inside a public repository — so going public would have published thousands of retained MyFantasyLeague payloads and normalized Sleeper rows, which are a private research cache under non-commercial terms. Excluding the branch from the Pages artifact would have done nothing, because `git clone` hands any visitor every branch. The store had to move first (ADR-049), and that reordered everything after it.

Three things are worth carrying forward as ideas rather than as file paths:

1. **Last-known-good is a job graph, not a checklist** (ADR-050). `capture → build → deploy`, the deploy job contains only the Pages actions, and nothing anywhere clears the live site before a new one validates. "A gate failed" and "the previous site is still serving" are therefore the same event rather than two facts that have to agree — and it has now held three times in production, twice for defects nobody designed a test for.
2. **The forced-failure proof breaks a real invariant.** It corrupts quantile monotonicity in a generated artifact and lets the ordinary validator reject it, so what stops the deploy is `artifact.non_monotonic_quantiles` — a production critical check — not an `exit 1` added for the test.
3. **Splitting the data out made permissions narrower, not wider.** The capture job used to need `contents: write` here; it now needs `contents: read` plus a token scoped to one other repository.

## Current target gate

**Phase 12 is implemented; Release 2's remaining gate is an observation, not a task.** The
in-season product exists and every offline gate passes. What is left is the first live in-season
refresh — the Tuesday after Week 1, `"40 12 * * 2"` — which cannot be run before the season
starts (first 2026 kickoff `2026-09-10T00:20:00Z`). `docs/releases/v2.0.0.md` records the
definition of done clause by clause with that one clause open.

The question Phase 12 opened with is closed. Phase 11 handed over a promoted rest-of-season model
(ADR-077) with no production artifact; ADR-078 defined the smallest legitimate fit that serves
2026 without reinterpreting the spent holdout, and that artifact is committed.

**Release 1 has no open gate. V1 is released.** Phase 9B's checklist in `TASKS.md` is complete and its exit gate is met. Phases 0-8 were not renumbered; 9A was inserted before the release because the one blocked Phase-8 item became doable and doing it before tagging V1 was cheaper than tagging twice.

The next work is the post-V1 backlog at the end of this file. None of it is a launch blocker and none of it should be started as though it were a phase gate.

`docs/PHASE8_UI_FEEDBACK.md` is the human-to-implementation trace for the redesign: the owner's 2026-08-31 feedback and a status row per item, with item 1 now resolved. `docs/DESIGN_SOURCE_MAP.md` is the design source itself — what the five artboards contain, how each maps onto the product, and every deliberate deviation. Read both before touching the frontend again.

The visibility question ADR-016 deferred is closed: the repository is **public**, serving a public Pages project site from standard GitHub-hosted Actions, free and non-commercial — which is a licence condition rather than a preference, because `player_status.json` carries Sleeper fields to every visitor.

## Last validated commit

**`5511370a52dc057471f9756f1da480e5756d914c` on `main` — the released commit, tagged `v1.0.0`.** Everything below was run on it, locally and on runners: `ruff` clean, `ruff format` clean over 173 files, `mypy` clean over 111 files, `pytest` **1,058** passed (4 live-network deselected), `config-check` clean, the favicon generator's `--check` current, `npm lint`/`typecheck` clean, **234** vitest, **70** Playwright across `chromium`/`mobile`/`a11y`, both base-path builds, and `verify:board` with zero disagreements against the fixture build, the project-base-path build and the matured-market build. `npm run e2e:browsers` is runner-only here, as always, and was green in CI.

The command list below is the Phase-8 record with the Phase-9B verifiers added, and is still the right list.

```
uv sync --frozen
uv run ruff check .                 # clean
uv run ruff format --check .        # clean, 172 files
uv run mypy                         # clean, strict, 111 source files
uv run pytest                       # 1055 passed, 4 live-network deselected
uv run ffdraft config-check
uv run ffdraft audit-convergence    # phase8_simulation_convergence_v1 (ADR-057)

# The retained store, a separate PRIVATE repository (ADR-049)
git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data
uv run ffdraft validate-market-history ../market-data --season 2026

npm ci
npm run lint            # clean (2 known React-Compiler/TanStack warnings, ADR-048)
npm run typecheck       # clean, strict
npm run test -- --run   # 234 frontend tests
npm run build                                    # root base path
VITE_BASE_PATH=/jeisey-tiers/ npm run build      # project Pages base path
npm run e2e             # 70 Playwright tests: chromium + mobile + a11y
npm run e2e:browsers    # smoke across Chromium, Firefox and WebKit — RUNNER ONLY

# The Phase-9B release verifiers. Each takes a local build or a deployed --url.
npm run verify:board     # rendered board vs artifact bytes, cell by cell, one block deep
npm run verify:presets   # all nine scoring x league-size blocks, artifact and browser
npm run verify:presets -- --review "PPR/redraft-12,HALF/redraft-10,STD/redraft-14"
npm run verify:csv       # all four CSV exports, downloaded and parsed
npm run verify:live -- --url https://jeisey.github.io/jeisey-tiers --out live-artifacts
```

**Three environment notes that cost time and should not cost it again.**

1. This sandbox ships Chromium build 1194 at `/opt/pw-browsers` while the pinned Playwright wants a newer one, so `npm run e2e` fails every test with "Executable doesn't exist" until `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` is exported. `playwright.config.ts` reads that variable **per project**, and never hands it to Firefox or WebKit.
2. **`npm run e2e | tail` reports `tail`'s exit code, not Playwright's** — without `set -o pipefail` a completely red suite looks green.
3. **Firefox and WebKit cannot be installed here at all.** The egress policy blocks `cdn.playwright.dev` and `playwright.download.prss.microsoft.com`, so `npm run e2e:browsers` is a runner-only gate, the same shape as the source probes (ADR-009, ADR-059). `ci.yml`'s `browsers` job is where it runs.

`build-current`, `build-arbitrage` and `verify:board` on real data are **runner-only** here: the sandbox answers 403 to CONNECT for nflverse, MyFantasyLeague and Sleeper (ADR-009), which is the whole reason source work happens in Actions. The live site is unreachable from here too, so a deployed-site smoke is a runner or owner action.

## Production status

**A production model and a production arbitrage board exist.** `intrinsic-cb-hurdle-v1`, trained on 2014-2025, promoted through a sealed single-use holdout, serving a 2026 board for every launch preset; and the deterministic A0 arbitrage baseline built on top of it from retained market history, deployed and refreshing daily since 2026-08-22.

- `models/production/intrinsic-cb-hurdle-v1/` — **committed**, not gitignored (`PRD.md` section 15). 120 gzipped LightGBM boosters plus `metadata.json` carrying the spec, seed, training seasons, library versions, dataset manifest, `feature_set_hash` `7203befaa5be25a2`, `feature_schema_hash` `c495ba3177dcb989` and a SHA-256 per booster. No pickles anywhere: loading reads JSON and LightGBM's documented text format, and a tampered booster fails closed.
- `models/cards/` — the model card and the tier-method report, generated from the committed experiment reports and the artifact, never hand-written.
- `models/cards/arbitrage-method-a0.{json,md}` — the arbitrage method card, generated from the artifacts, the cohort report and the frozen constants.
- `web/public/data/` — the 2026 build: `tiers`, `projections`, `arbitrage`, `player_status`, `build_metadata`. Gitignored and reproducible. Everything else under `web/public/` — the three icons — **is** committed.
- **`jeisey/jeisey-tiers-market-data`** — the append-only point-in-time capture store, a private repository since Phase 7 (ADR-038 as amended by ADR-049). Not in this working tree; clone it separately.

The fixture stub `fixture-stub-0` is gone from the production path, and so is the Phase-1 stub arbitrage score: the fixture pipeline now drives the real A0 code.

What was there before and still is:

- `src/ffdraft/` — config, contracts, sources, identity, quality, artifacts, pipeline, CLI (Phase 1) plus `anchors.py`, `scoring/`, `features/`, `labels/`, `simulation/`, `leakage.py` (Phase 2) plus `modeling/` (Phase 3) plus `market/`, `arbitrage/`, `status/`, `retention/` and `pipeline/market.py` (Phase 5).
- `data/historical/` — the modelling dataset. Gitignored and reproducible; see "Phase-2 dataset" below.
- `docs/FEATURE_DICTIONARY.md` — every model feature with formula, sources and availability rule, generated from code and pinned by a test.
- `docs/experiments/phase3-intrinsic-baselines/` — the committed Phase-3 experiment reports, machine-readable and human-readable. Row-level predictions are gitignored.
- `.github/workflows/` — `ci.yml` (fixture-only gates, no vendor network, no store credential), `daily-refresh.yml` (the production path), `retrain.yml` (an evidence gate that mostly declines), `market-capture.yml` (out-of-band capture), `source-probe.yml` (Phase-0) and, since Phase 9B, `live-smoke.yml` (dispatch-only, gates nothing, deploys nothing). `.github/actions/market-data-store/` is the one way any of them reaches the private store.
- `docs/visual-qa/` — committed screenshots and the written review. One directory per review; `2026-08-31-design/` is Phase 9A's and does not replace Phase 8's, and `2026-09-01-release/` is Phase 9B's release-polish review (masthead, export controls, favicon) rather than a design review.
- `docs/releases/` — the notes each GitHub Release is published from. `release.yml` reads the file and refuses an empty one, so a release cannot ship with a placeholder.
- `scripts/workflow_summary.py` and `scripts/retrain_gate.py` — the two Phase-7 gate/report scripts, both runnable locally. `scripts/make_favicon.py` (Phase 9B) generates the committed icons from the owner's logo; CI runs it with `--check`.
- `web/tests/e2e/verify-*.mjs` — the release verifiers, each usable against a local build or a deployed `--url`: `verify-board` (rendered board vs artifact bytes, one block deep), `verify-presets` (all nine blocks, plus a measured `--review` of representative ones), `verify-csv` (all four exports), `verify-live` (the deployment itself).
- `web/` — the draft sheet: `src/data/` (contracts, loader, indexes, market derivations, flags, formats, CSV, URL state), `src/app/` (shell, controls, two tables, player detail, data view), `src/charts/` (Tier Board, Draft Rail), `src/components/`, `src/styles/base.css`, since Phase 9A `src/assets/fonts/` (two OFL families, vendored — `docs/SECURITY_LICENSE.md` section 8), and since Phase 9B `src/assets/jt_logo.png` (the owner's own artwork) plus the generated `public/favicon.{ico,png}` and `public/apple-touch-icon.png`.
- `tests/` — 1,058 network-free Python tests (4 live-network deselected); `web/tests/` adds 234 vitest plus 70 Playwright, and 13 more in the runner-only three-engine smoke.
- `docs/experiments/` — four committed experiment report pairs: the Phase-3 baselines and the three Phase-4 studies, plus the single final-holdout report. Row-level predictions are gitignored.

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

## Phase-3 results — the frozen evaluation

Development folds 2020-2024 (plus W1-only diagnostics 2017-2019), 468 evaluation cells, seed 20260819, 1000 bootstrap replicates. Season **2025 is sealed and was not evaluated**.

Macro aggregates over season x position x scoring, window `W1_all_history`:

| Model | MAE | RMSE | Spearman | Kendall | Top-K | Pinball | P10-P90 cov | P10-P90 width | Raw crossing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 25.60 | 44.06 | 0.659 | 0.524 | 0.535 | 9.98 | 0.793 | 83.1 | 0.000 |
| B1 | 26.98 | 42.21 | 0.711 | 0.550 | 0.593 | 9.74 | 0.798 | 80.4 | 0.000 |
| **Q1** | **22.07** | **41.03** | **0.726** | **0.570** | 0.544 | **8.13** | 0.771 | 62.7 | 0.387 |

Paired deltas against B0 under W1: MAE **-3.53** (95% CI -3.87 to -3.18), mean pinball **-1.85** (-1.98 to -1.72), Spearman **+0.066** (+0.058 to +0.075). Q1 passes the frozen gate under **both** windows; B1 fails under both, losing to B0 on MAE at every position.

Per position under W1 (B0 -> Q1): QB 39.50 -> 34.50 MAE, RB 27.38 -> 23.10, TE 14.80 -> 13.00, WR 20.73 -> 17.68; Spearman 0.642 -> 0.670, 0.641 -> 0.742, 0.665 -> 0.742, 0.689 -> 0.748. No position triggers the collapse rule. Per scoring preset the ordering is identical (PPR is the hardest: Q1 MAE 24.40 against STD's 19.78, which is scale, not skill).

Training window (ADR-028): W1 beats W2 on the common folds with Q1 by MAE **-0.286** (-0.474 to -0.107) and pinball **-0.083** (-0.134 to -0.037), Spearman indistinguishable. Per fold the MAE advantage is -0.911 (2020), -0.023 (2021), -0.024 (2022), -0.158 (2023), -0.315 (2024) - concentrated in the fold where W2 has only three training seasons, which is the honest reading of *why* W1 wins.

Selected for Phase 4 (ADR-029): **Q1**, window **W1**, feature set `intrinsic_core_v1` (`7203befaa5be25a2`), 78 inputs.

## Phase-4 results — the frozen production system

Development folds 2020-2024, seed 20260819, 1000 bootstrap replicates. Every decision below was made by a rule written into `ffdraft.modeling.rules` **before** the run that decided it, and the whole set was committed at `2f0e725` before 2025 was opened.

| Decision | Rule | Outcome |
|---|---|---|
| calibration | `phase4_calibration_v1` | monotone (PAV) projection only; the fitted conformal layer was measured and refused |
| target scale | `phase4_horizon_v1` | season total; horizon normalization refused on both declared routes |
| architecture | `phase4_candidate_v1` | **CB**, availability x performance hurdle |
| draw count | `phase4_convergence_v1` | 10,000 — **by the fallback clause; no count passed** |
| fair rank | `phase4_ranking_v1` | median simulated VORP; expected VORP refused |
| tier penalty | `phase4_tier_v1` | 1.0, the only admissible penalty in the grid |
| tier stability | `phase4_tier_stability_v1` | **FAIL** on boundary agreement, after escalating from PELT to dp_quantile |
| final holdout | `phase4_final_holdout_v1` | **PASS** |

**Development macro aggregates (CB vs the A0 direct-quantile candidate):** MAE 21.91 vs 22.11, pinball 8.080 vs 8.142, Spearman 0.750, top-K 0.577, P10-P90 coverage 0.827, raw crossing rate **0.000** (against Q1's 0.387). Paired deltas: pinball -0.0614 [-0.1002, -0.0236], MAE -0.205 [-0.332, -0.073], Spearman +0.0298, top-K +0.0326.

**Final holdout, 2025, run once (ADR-036):** CB MAE 20.19 vs B0 23.93; pinball 7.197 vs 9.331; Spearman 0.780 vs 0.679; P10-P90 coverage 0.845 against nominal 0.80; width 56.9 vs 80.7. Paired: MAE **-3.738** [-4.364, -3.102], pinball **-2.134** [-2.377, -1.874], Spearman **+0.1015**. CB improves MAE and pinball on **all eleven** predeclared slices; rookies go 34.29 -> 29.83 MAE with coverage 0.675 -> 0.747.

**The two failures, in the units that matter.**

- *Convergence.* Ranking tolerances pass comfortably (fair-rank Spearman 0.99993 between seeds, top-50 overlap 0.96+); value tolerances miss by 10-20% (mean |Δ expected VORP| 0.29-0.31 against 0.25); the tier clause misses badly (ARI 0.50-0.75 against 0.90). More draws would close the value gap; they would not close the tier gap, because a boundary is a discrete cut on a nearly continuous curve.
- *Tier stability.* Boundary agreement 0.239 against 0.500. Everything else passes: ARI 0.865, singleton rate 0.040, tier-count CV 0.045, monotonic pairs 0.845, cross-preset ARI 0.529. Across 1,200 replicates the segmentation used 283 of 299 cut sites and only 4 survived in a majority (ranks 267, 99, 16, 68). The median promoted boundary sits on a 0.55-point P50 cliff against an 80-130 point interval, and P(player below outscores player above) is 0.497.

**The 2026 board looks right.** PPR/redraft-12 top eight: Bijan Robinson, Amon-Ra St. Brown, Ja'Marr Chase, Jahmyr Gibbs, De'Von Achane, Puka Nacua, Jaxon Smith-Njigba, CeeDee Lamb. Top 12 is 6 RB and 6 WR; the first QB is 15th (Josh Allen) and the first TE 19th (Trey McBride), which is the correct shape for a 1-QB league where those positions' VORP is compressed. Tier sizes 8/14/25/33/29/42/45/69/35. 34 rookies make the 300-deep board, the best at rank 72. Zero quantile-monotonicity violations, zero non-finite values.

## Phase-5 results — market history, cohorts and the arbitrage baseline

Every rule was frozen at `455f08b` before it had been run against live data.

**The store.** Two real 2026 snapshots on the `market-data` branch:

| snapshot | commit | contents |
|---|---|---|
| `2026-08-20T14-11-48Z` | `36303e6` | 13 cohorts, 3,293 normalized rows, 2,606-row player directory |
| `2026-08-20T14-38-44Z` | `57ee0c1` | 16 cohorts, 4,110 normalized rows |
| `status/sleeper/2026/2026-08-20T14-12-17Z` | `36303e6` | 12,240 normalized status rows |

`validate-market-history` re-hashes all 35 files clean. Roughly 590 KB per study capture; a production capture (three cohorts) is far smaller.

**The cohort measurement** (`docs/market-cohorts/2026-08-20/`, reproducible offline from the retained snapshot). Aggregate volume has barely moved since Phase 0: 426 drafts against 410. Exact scoring × league-size intersections are still thin or empty, so ADR-012 stands. Two things the measurement found that Phase 0 could not:

- **`IS_MOCK=0` is inert** — 426 drafts, byte-identical to unfiltered. No mocks in the aggregate.
- **`IS_KEEPER=N` returns 125 drafts, and the other 301 are dynasty rookie drafts.** 2026 rookies price three to five times earlier in the aggregate than in the keeper-free cohort while established veterans do not move at all. Ty Simpson 35.6 → 162.3; Emmett Johnson 50.4 → 193.1; Bijan Robinson 2.5 → 2.6. In a dynasty rookie draft only rookies are selectable, so a rookie's `averagePick` there is a pick number in a rookie-only draft.

That produced ADR-045 and `phase5_cohort_v2`: a redraft board may only be priced by a keeper-free cohort. **No bound moved.** Every keeper-free cohort then fails `min_total_drafts` (125 and 115 against 300), so the rule falls through to its documented last resort and flags the result.

**Identity coverage depends on the population counted**: ~87% over the whole priced payload, **98.2–98.5%** over the QB/RB/WR/TE rows the board is made of. MFL also prices kickers, team defences and IDP. The rule counts the core positions its clauses are written about (ADR-039 clarification).

**Per-player sample is the statistic that matters.** Medians over the priced top-150: unfiltered 141, `IS_PPR=1` 129, `IS_KEEPER=N` **105**, `FCOUNT=12` 62, `FCOUNT=14` 7. That `no-keeper` scores 105 on the direct measure while failing a cohort-level bar of 300 is the open question ADR-045 records and deliberately does not answer.

**The 2026 arbitrage board.** 2,124 rows across nine preset blocks, `a0_rank_gap_v1`, built from snapshot `2026-08-20T14-38-44Z`. Confidence: 2,124 `low`, all for the same recorded reason. Trend: null on every row — the store holds two snapshots against a requirement of three observation days spanning three days. 42 top-150 board players carry no price and are excluded rather than filled in.

PPR/redraft-12, the biggest signals, and why they are believable:

| | player | fair rank | ADP | gap | score |
|---|---|---:|---:|---:|---:|
| bargain | Amon-Ra St. Brown | 2 | 10.5 | +8.5 | 99.8 |
| bargain | De'Von Achane | 4 | 18.5 | +14.5 | 99.0 |
| premium | Joe Burrow | 234 | 28.1 | −205.9 | 0.2 |
| premium | Jayden Daniels | 267 | 34.5 | −232.5 | 0.6 |
| premium | Christian McCaffrey | 43 | 12.9 | −30.1 | 1.9 |

The quarterbacks are the known 1-QB-league VORP compression from Phase 4, not a defect: the model ranks them where their league-relative value sits and the market takes them where positional scarcity feels. McCaffrey is `Questionable/Undisclosed` in the status artifact — which is exactly the join Phase 6 exists to render.

**Player status.** 315 rows for the published board, 309 matched through `sleeper_id`, one failed the `gsis_id` cross-check closed. 61 players carry an `injury_status`, 13 carry `injury_notes`. `injury_start_date`, `practice_participation` and `practice_description` are published by Sleeper as keys with null values across the whole preseason payload; they are normalized anyway because Sleeper declares them and they populate in season.

## Phase-6 results — the draft sheet

Built against the real 2026 build, in ADR-008's order: tables first, because a table is the truth surface a chart is checked against.

**What shipped.** One page, three tabs, state in the URL.

| Surface | What it does |
|---|---|
| Tier board | Tier groups as soft bands over a **median simulated VORP** axis, P25-P75 interval per player, position-coloured marks with position rank, one tab stop with arrow-key movement. Defaults to the top 100; a shareable control shows the whole board. |
| Tier table | TanStack v8, default `fair_rank` ASC, sticky header, 11 columns, ~38px rows. The canonical accessible equivalent of the board. |
| Draft rail | Paired anchors per player — filled diamond for fair rank, open circle for MFL ADP — with a signed sentence per row (`+14.5 picks later`). Bargains / Premiums / All, top 30. |
| Arbitrage table | Default `arbitrage_score` DESC. **No** surplus columns: V1 has no learned model and will not grow a header for one. |
| Player detail | One `<dialog>` reachable from all four surfaces: intrinsic, market and current-status sections, with the annotation-only disclosure standing in the status section. |
| Data | Definitions, the build read from metadata, a source freshness table, market provenance, ten current limitations and source attribution. No metric is hardcoded; the model cards are linked. |
| Export | `Download full CSV` links the artifact the build wrote; `Export filtered CSV` writes exactly the visible rows in visible order, named `ffdraft-<board>-<scoring>-<teams>-<build date>.csv`. |

**Verified against the real artifacts** (`npm run verify:board`, 0 disagreements): 40 tier rows, 25 chart-mark labels, 30 arbitrage rows and 56 injury badges match `tiers.json`, `arbitrage.json` and `player_status.json` exactly. The 2026 PPR/redraft-12 board renders 300 tier rows, 238 priced arbitrage rows and the expected quarterback premiums (Joe Burrow −207.9, Jayden Daniels −230.5, Christian McCaffrey −31.1 picks).

**Two contract corrections the frontend surfaced.**

- `build_metadata.market.assignments[]` now carries `failed_clauses` — the frozen rule's own words, e.g. `total_drafts 125 < 300`. Without it the UI would have to hardcode today's measurement to explain a low-confidence board (ADR-047). The market block was already `additionalProperties: true`, so no version moved; the schema now declares the field.
- `expected_games` is **optional** in `player_projection.schema.json` and the production current build omits it while the fixture pipeline emits it. `web/src/data/contracts.ts` claimed it was always present; it is now optional there too.

**Visual QA found nine real defects**, all fixed and written up in `docs/visual-qa/2026-08-21/REVIEW.md`. The two worth remembering: the Tier Board was scaled to P10-P90 while drawing P25-P75, which parked every median in the middle third of the plot; and the arbitrage page scrolled sideways by ~700px on a phone because `.table-scroll` was not a containing block, so the absolutely positioned screen-reader-only spans inside its cells escaped the scroller and dragged the document's scroll width out to the table's width — an accessibility affordance silently breaking the mobile layout.

**Dependencies added:** TanStack Table v8, `d3-scale`, `d3-array`, `@playwright/test`, `@testing-library/user-event` (ADR-048). No router, no UI kit, no charting framework, no CSS framework.

## Phase-7 results — deployment, and the storage change it forced

**The topology, which is the durable part.**

```text
jeisey/jeisey-tiers                PUBLIC     code, schemas, the production model, the frontend
  main                                        -> GitHub Pages at /jeisey-tiers/

jeisey/jeisey-tiers-market-data    PRIVATE    the append-only capture store
  market-data                                 immutable MFL + Sleeper captures
```

**The migration.** Byte-faithful and verified before anything irreversible happened: 40/40 files compare equal, both trees hash to `1e60a55283e69c763a9dbc0bbb5fe4eb2e10cd476716fa2fbd5653c4822434f2`, and `validate-market-history` passes on the migrated checkout. Zero objects from the old branch were reachable from `main` — it shared no history with it — which is why deleting the branch while still private left nothing recoverable in a public repository.

**The credential.** `MARKET_DATA_REPO_TOKEN`, a fine-grained token scoped to the data repository alone. It reaches `actions/checkout` through `token:` and never a shell; read-only jobs use `persist-credentials: false`; `ci.yml` never references it. The address is in `config/source-registry.yaml` and nowhere else.

**What ran on GitHub-hosted runners, and what it proved.**

| run | outcome |
|---|---|
| `market-capture` [32590470088](https://github.com/jeisey/jeisey-tiers/actions/runs/32590470088) | first capture into the private repository |
| `ci` [32590972677](https://github.com/jeisey/jeisey-tiers/actions/runs/32590972677) | three jobs green on a clean checkout |
| `daily-refresh` [32591545618](https://github.com/jeisey/jeisey-tiers/actions/runs/32591545618) | **found a real Phase-5 defect** — see below |
| `daily-refresh` [32594084631](https://github.com/jeisey/jeisey-tiers/actions/runs/32594084631) | capture + build green end to end; deploy blocked at the visibility gate |
| `daily-refresh` [32594602638](https://github.com/jeisey/jeisey-tiers/actions/runs/32594602638) | forced-failure proof: real gate rejected it, deploy skipped |
| `retrain` [32594603959](https://github.com/jeisey/jeisey-tiers/actions/runs/32594603959) | declined in 23 seconds, candidate job skipped |

**The 2026 production build, from the runner's own summary** (build `2026-intrinsic-cb-hurdle-v1-20260822T193501Z`, snapshot `2026-08-22T19-34-24Z`): 2,700 tier rows, 3,510 projections, 2,021 arbitrage rows, 315 player-status rows with 309 matched through Sleeper. Nine preset blocks — `redraft-14` joined the supported set. Quality gate **pass**, 0 critical, 3 warnings (the tier-stability warning, Sleeper `gsis_id` conflicts failing closed, unpriced top-150 players excluded). Cohort `no-mock-no-keeper` for every preset: **143 drafts**, up from Phase 5's 125, still `low` confidence on `total_drafts 143 < 300`, median per-player sample 93. Trend still null — ADR-042 wants three observation days spanning three days. `verify:board` at the project base path: 40 tier rows, 25 chart marks, 30 arbitrage rows, 63 injury badges, **0 disagreements**.

**Running the production path for the first time found a defect nothing else could have.** `PRODUCTION_COHORT_IDS` was frozen under `phase5_cohort_v1` as `("unfiltered", "ppr", "std")`; ADR-045 later made keeper-free a *qualifying* condition; so a daily capture retained nothing the frozen rule could legally select and `select_cohorts` refused to price a board. Every board Phase 5 built came from a `study` capture, which retains all sixteen candidates — so the production path had never actually been run. The rule was right; the capture was wrong. Fixed by retaining what the rule needs (ADR-045 amendment, 2026-08-22), with two tests that price every launch preset from `PRODUCTION_COHORT_IDS` alone.

**The workflows.**

| workflow | trigger | may do |
|---|---|---|
| `ci.yml` | PR, push to `main`, dispatch | fixtures only — no vendor, no store, no `pages:` scope |
| `daily-refresh.yml` | 07:17 America/New_York, dispatch | capture → build → deploy |
| `retrain.yml` | Sunday 06:43 America/New_York, dispatch | an evidence gate, and at most a candidate report |
| `market-capture.yml` | dispatch, or a request-file bump | an out-of-band capture |

Exactly one job in the repository holds a `pages:` scope: `daily-refresh`'s `deploy`, which also holds `id-token: write` and the `github-pages` environment. Everything else is `contents: read`, including both capture jobs — they write to another repository through a token scoped to it, so they need no write scope here at all.

**The public-release audit.** 517 paths and 56 commits scanned. No `.env`, no key material, no raw payload, no `data/historical/`, no `web/public/data/`, no identifying filesystem path. One credential-*shaped* match: the old workflow's `https://x-access-token:${GH_TOKEN}@github.com/...`, a shell variable reference expanded at runtime, and that construction is now gone. Full record in `docs/PHASE7_DEPLOYMENT.md`.

**The retrain gate, and why it says no.** `intrinsic-cb-hurdle-v1` trained through 2025; 2025 is the spent holdout; 2026 unplayed. `scripts/retrain_gate.py` asks whether a season after the last training season has a **complete fantasy horizon** upstream. 404 is "no", a short weekly file is "no", and it exits 0 either way. Every weekly run this preseason stops there in about two minutes, which is the gate being exercised rather than asserted.

## Phase-8 results — the redesign, and what the audit found

**Two tracks, and the second is the one that produced findings.**

### The frontend

| surface | before | after |
|---|---|---|
| Tier board | one SVG chart row per player; ~1,800px for the top 100 | HUD rows with the same P25-P75 bar on a shared scale, tiers collapsible; **1,405px** default, **~230px** with every tier closed, 7,670px fully expanded |
| Draft rail | a 1-to-300 pick axis, paired diamond/circle anchors | the signed gap on a symmetric scale sized to the rows shown, with numeric anchors beside it |
| Player card | three sections each ending in a paragraph of methodology | a HUD card of labelled readouts, a status strip of fields, one `<details>`, one link to Data — and a sheet at 390px |
| SVG elements on the two chart views | ~700 | **0** |
| Frontend production dependencies | React, ReactDOM, TanStack Table, d3-scale, d3-array | React, ReactDOM, TanStack Table |

**Nothing a number means changed.** No projection, feature, fair rank, VORP, tier membership, ADP, arbitrage score, confidence calculation, trend calculation, cohort selection or status meaning moved. `npm run verify:board` compares the rendered board against the artifact bytes on every production build and is the check that would fail if one had.

### The audit

- **Production, seven runs:** `docs/PHASE8_OPERATIONS_AUDIT.md`. Zero critical, three warnings, flat and identical for the whole window. Tier rows exactly constant; projection and arbitrage row counts drifting down for two unrelated and explainable reasons.
- **Model artifact:** 120 boosters re-hashed against `metadata.json`, **0 mismatches**; feature set and `feature_set_hash` identical to the code's own; the repository's forbidden-feature rule passes; no serialized object anywhere. Model card and tier-method card regenerated and deep-diffed against the committed ones: **0 differences** outside `generated_at_utc`, `git_sha` and one block whose input is gitignored.
- **Convergence:** ADR-057. Ranking is converged at 10,000 draws and value is not; the residual is 19-29% over tolerance on expected and median VORP across three of four scenarios. The production draw count did not move and cannot move on this rule.
- **Security and dependencies:** `docs/PHASE8_SECURITY_REVIEW.md`. `pip-audit` and `npm audit` both clean. Every credential property is now a test.
- **Accessibility:** axe at WCAG 2.2 AA over eight surfaces plus the open dialog, clean, plus eight keyboard and semantic checks a scanner cannot make. **Four real defects found and fixed**, all introduced by the redesign.
- **Browsers:** Chromium, Firefox and WebKit green on a runner, at the phase's final code state ([33426138022](https://github.com/jeisey/jeisey-tiers/actions/runs/33426138022) on `aa3d6c3`; first measured in [33407642729](https://github.com/jeisey/jeisey-tiers/actions/runs/33407642729)).
- **Full gate, three ways:** locally, on a fresh clone of the pushed branch with no vendor egress, and on runners. Every step exit 0 in all three — `ruff`, `ruff format`, `mypy` (111 files), `pytest` (1,055 passed, 4 deselected), `config-check`, `audit-convergence`, the fixture pipeline, `validate-artifacts`, `npm lint`/`typecheck`/`test` (226) `/build`, and Playwright (61 across `chromium`, `mobile`, `a11y`). CI additionally confirmed the committed golden artifacts are current.
- **Failure drills:** nineteen, offline, in `tests/integration/test_failure_drills.py`.
- **Source freshness and schema drift:** re-probed on a runner fourteen days after the Phase-0 baseline ([33412957744](https://github.com/jeisey/jeisey-tiers/actions/runs/33412957744)), evidence at `docs/source-probes/2026-08-31/`, refreshed fixtures committed at `3ed5b37`. Same status counts as the baseline (78 ok, 1 `http_error`, 1 `loader_error`). Twelve schemas moved: **no column added, no column removed, one dtype change** (`nflverse_ff_playerids.pff_id`, unused here). Read column by column in `docs/PHASE8_OPERATIONS_AUDIT.md` section 3.4.

### The two findings that mattered

1. **The verification layer had frozen the launch condition.** Every market-sensitive test — vitest, Playwright, mobile — was written against a uniformly `low` board with a null trend and an insufficient cohort. Production reached the opposite state a week before this phase started and nothing in the repository rendered it. Fixed with a second fixture condition; both are exercised and neither is "the normal one".
2. **Three pieces of UI copy asserted a condition the build computes.** All three now read from `build_metadata`.
3. **The accessibility scan added this phase could pass against a page that failed to load.** A clean-clone reproduction reused a stale static server holding a build with no `data/`; forty-seven board and mobile tests failed on it and **all eight axe scans passed**, because axe finds nothing wrong with the refusal screen. Each surface is now paired with a selector only that surface renders. Verified against the failure that produced it: with `data/` removed the unguarded scan passes and the guarded one fails.

## Phase-9A results — the design source, implemented

**The one Phase-8 item that was blocked is closed.** The owner downloaded `Player Card HUD.dc.html` and `support.js` from his Claude Design project by hand and supplied them to the session. No MCP was needed and none was used; `/design-login` was never run. Neither file is committed — they are a design handoff, and `docs/DESIGN_SOURCE_MAP.md` plus `docs/visual-qa/2026-08-31-design/REVIEW.md` are the durable record of what they said.

**What the source turned out to be.** Five artboards: a whole-application "command board" (2a), an alternative tier stack (2b), and three player cards (1a tactical dossier, 1b segmented scope, 1c recon sweep). Its Arbitrage view is an explicit placeholder reading "NOT PART OF THIS PASS", so the Draft Rail has no design source and keeps its Phase-8 encoding in the new vocabulary.

**How much the Phase-8 inference got right, and what it missed.** The *language* was mostly right — HUD panels, micro-label over readout, density, status treatment. What a written brief could not supply, and what changed most: the type (Exo 2 + JetBrains Mono against a system stack), the hairline construction (a 1px grid `gap` over a tinted container, not borders), zero border-radius with *cut* corners, and a third card variant.

| surface | verdict |
|---|---|
| shell, controls, nav | KEEP structure, ADAPT skin — the source's header is the same five elements in the same order, including a build-notes chip that already matched `mastheadStatus` |
| Tier Board structure | KEEP — collapse, shared scale, band-not-line, exact ordering all survive |
| Tier Board presentation | REPLACE — tier gutter as the collapse control, axis built as a lane, per-row gridlines at the axis's own step, glowing square median |
| Tier Board on mobile | REPLACE — artboard 2b, the tier stack, which the source's own caption prescribes for a phone |
| both tables | ADAPT — semantic `<table>` kept; the source's two micro-glyphs added as cell backgrounds |
| Draft Rail | ADAPT — no artboard; Phase-8 semantics kept, vocabulary applied |
| player detail | REPLACE — three real variants by viewport, one DOM |
| Data, methodology placement | KEEP — ADR-058 holds, and the source agrees with it |

**Six defects the review found, none of which a test was failing on.** Two alignment bugs where the tier band and the axis were not on the rows' own track — one an off-by-one in grid columns, one `grid-area: span`, where `span` is a reserved grid keyword so the declaration was dropped silently. A card that overflowed its own frame because an implicit `auto` grid row is sized by its content. A tinted readout at 4.36:1 because the tint composited against the grid's wash rather than the tile. A scroll container that could not be focused. A 102px horizontal overflow at 320px from the rail's scale strip. All fixed; the alignment invariant is now measured by a test at three viewports.

**Performance: DOM at parity, one interaction up 1.46×.** Measured as an interleaved A/B against the Phase-8 build on one machine, because this sandbox's run-to-run noise reaches 9× and a first attempt at motif attribution produced impossible results. Default view 6,969 → 7,003 nodes, 0 SVG either way; board 20% taller. Six of eight interactions at parity or better; `expand all tiers` 511 → 744ms and the arbitrage view's first render 486 → 627ms. An earlier draft of the table glyphs cost 1,200 extra nodes and was rewritten to cost none.

## Phase-9B results — the release, and the checks it turned out to need

**Three owner-requested changes, one record correction, and a verification gap the checklist exposed.**

### What shipped

| change | what it is |
|---|---|
| masthead | the owner's `web/src/assets/jt_logo.png`, imported through Vite so the URL carries the build's base. Sized by `height` with `width: auto` — 48px desktop, 42 tablet, 38 phone — so the ratio comes from the file. The image is the document's `<h1>`, `alt="Jeisey Tiers"`. |
| removed | the Phase-9A wordmark, mono sub-label and command glyph, in the shell **and** in the refusal screen, which carried its own copy of the header. |
| favicon | `favicon.ico` (16/32/48), `favicon.png`, `apple-touch-icon.png`, generated by `scripts/make_favicon.py` from the logo's football and a palette sampled from the logo itself. Linked through Vite's base token. |
| title | `Jeisey Tiers — Fantasy Draft Intelligence`. |
| export labels | `.button` gains `inline-flex` with both axes centred. |
| ADRs | 053, 054 and 056 closed; no `Proposed` status remains in `docs/DECISIONS.md`. |

### The CSV defect, in the units that matter

`.button` dresses a `<button>` and the `Download full CSV` `<a>`, and without a `display` of its own the two laid their label out differently. A native button centres its content; a blockified anchor puts its single line box at the **top** of the 40px frame. Measured in Chromium at 1440px before the change, the anchor's label centre sat **14.5px above** its frame centre and the button's 0.78px. Both now measure 0.78px, which is the trailing letter-space every tracked control in the app carries and is deliberately not compensated for.

### The release build

Run [33526105451](https://github.com/jeisey/jeisey-tiers/actions/runs/33526105451), dispatched from `main` at `5511370`, **success** end to end: capture → build → deploy → report.

**It ran with `skip_capture: true`, and that was a source-policy decision rather than a shortcut.** 2026-09-01 had already spent two MyFantasyLeague player-database requests — a dispatched refresh and the scheduled one — and ADR-017 asks for at most one a day. The input skips only the two vendor calls; the store checkout, its re-hash, `build-current`, cohort selection, `build-arbitrage`, `validate-artifacts`, the base-path frontend build, `verify:board` against the real artifacts, the Pages-artifact boundary assertion and the deploy all ran in full on the release code. The store commit is therefore unchanged (`store_appended: false`) and the board is priced by the snapshot retained at 11:25:40Z the same morning.

| | |
|---|---|
| Build id | `2026-intrinsic-cb-hurdle-v1-20260901T153049Z` |
| Generated | `2026-09-01T15:30:49Z` |
| Season | 2026 |
| Model / methodology | `intrinsic-cb-hurdle-v1` / `phase4_intrinsic_v1` |
| Arbitrage | `baseline (a0_rank_gap_v1)` |
| Presets | `redraft-10`, `redraft-12`, `redraft-14` × STD/HALF/PPR |
| Market snapshot | `2026-09-01T11-25-40Z`, source `myfantasyleague_adp` |
| Cohort rule | `phase5_cohort_v2` — `ppr-no-keeper` for PPR, `no-keeper` for STD and HALF |
| Cohort sufficiency | **all nine presets `sufficient: yes`, no failed clause**, every match `approximate` |
| Trend | available |
| Store commit | `b0afbb8888a3871fd0d7ce5f8ecb96b627505656` (unchanged) |

**Artifact counts:** 2,700 tier rows, 3,291 projections, 1,945 arbitrage rows, 319 player-status rows with 318 matched through Sleeper.

**Market confidence:** 45 `low` against 1,900 `medium`, median per-player sample **522 drafts**. Retained cohort volume: `no-keeper` 792 drafts, `no-mock-no-keeper` 789, `ppr-no-keeper` 594, `unfiltered` 1,503.

**Quality gate: PASS — 0 critical, 3 warnings**, and all three are the standing published limitations rather than anything new: tiers published having failed their stability gate (ADR-035), Sleeper `gsis_id` conflicts failing closed, and unpriced top-150 board players excluded rather than filled in.

### The verification gap, which is the more useful half

The checklist asked for things the repository could not check. `verify:board` compared the rendered page with the artifact bytes cell by cell — for **one** block out of nine. CSV coverage was a Playwright test asserting a download fires, which is a clicked button rather than a verified file. And nothing at all looked at the site *after* `actions/deploy-pages` ran, which is exactly the class of failure the favicon introduces: the icons are the one asset referenced from `index.html` rather than from the module graph, so a root-relative href works in development and 404s only once deployed.

Three verifiers close it, each usable against a local build or a deployed `--url`:

- **`verify:presets`** — all nine blocks, in the artifacts (rows present, fair ranks unique *and* a complete 1..N run, tiers zero-based and contiguous in fair-rank order, every arbitrage row naming a player its block ranks) and in the browser (board and both tables populate, the rank-1 name on screen is the artifact's rank-1 name *for that block*, the controls report the requested state, no console error, no request leaving the origin). `--review` adds a measured pass over representative blocks at 1440 and 390, printing the rendered top ten beside the artifact's, the masthead's boxes and both CSV labels' centring, with screenshots taken from the same navigation.
- **`verify:csv`** — all four exports downloaded and parsed. Full exports byte-identical to the artifact; filtered exports proved to hold exactly the visible rows in visible order under four simultaneous filters, from both directions.
- **`verify:live`** + `live-smoke.yml` — a *deployment* check rather than a build check: every script, stylesheet and icon href under the deployed base path answering 200, the vendored fonts, the logo's decoded `naturalWidth`, all five JSON artifacts and four CSVs, the three views, a player card, a shared link across a reload, a phone reflow, and no request leaving the origin. It downloads what the site serves, so the three checks above then compare the page against the bytes that page was actually served.

### What the deployed site was checked against, before the tag existed

`live-smoke` [33526715705](https://github.com/jeisey/jeisey-tiers/actions/runs/33526715705), against `https://jeisey.github.io/jeisey-tiers` — **all green**. Every artifact it compared with was downloaded from the site itself, so the comparison is against the bytes that page was served rather than a local rebuild.

All nine blocks, from `verify:presets`:

| block | tiers | rows | projections | arbitrage | rendered | rank 1 |
|---|---:|---:|---:|---:|---:|---|
| STD/10 | 10 | 300 | 1097 | 212 | 212 | Bijan Robinson |
| STD/12 | 11 | 300 | 1097 | 213 | 213 | Bijan Robinson |
| STD/14 | 10 | 300 | 1097 | 214 | 214 | Bijan Robinson |
| HALF/10 | 8 | 300 | 1097 | 215 | 215 | Bijan Robinson |
| HALF/12 | 9 | 300 | 1097 | 216 | 216 | Bijan Robinson |
| HALF/14 | 9 | 300 | 1097 | 217 | 217 | Bijan Robinson |
| PPR/10 | 11 | 300 | 1097 | 219 | 219 | Bijan Robinson |
| PPR/12 | 10 | 300 | 1097 | 219 | 219 | Bijan Robinson |
| PPR/14 | 10 | 300 | 1097 | 220 | 220 | Bijan Robinson |

Plus **42/42** representative-review checks over PPR/12, HALF/10 and STD/14 at 1440px and 390px; **32/32** CSV checks across both boards; and `verify:board` cell-by-cell against the served bytes. On the live 300-row board both export labels measure `dx 0, dy −0.78` in a 40px frame, so the centring holds at production row counts rather than only on an 18-player fixture.

**Nothing a number means changed.** No model, artifact, projection, feature, fair rank, VORP, tier membership, cohort selection, ADP, market confidence, trend or arbitrage value moved. No source was added, `config/source-registry.yaml` is untouched, MFL remains the sole V1 price source and FantasyPros stays `benchmark_only`.

## Phase-9B facts a later phase should not re-derive

- **A `<button>` centres its content and a blockified `<a>` does not.** `height` on an inline anchor does nothing, and once it becomes a flex item the height applies but the single line box still sits at the top. Any class dressing both elements needs its own `display` and alignment, or the two will disagree by half the control's height. This is a layout bug that no assertion on the label *string* can see.
- **The icons are the only assets referenced from `index.html` rather than from the module graph.** Vite rewrites the module graph's URLs for `base`; it does not rewrite a hand-written `href`. Use the base token, and check it in the built output — a root-relative icon href is invisible locally and 404s only on Pages.
- **The logo's file has transparent margins**: 434x145 with ink at 422x103. A height set here paints a mark about 71% of it, so "48px" is a ~34px wordmark. Size by `height` with `width: auto` and let the ratio come from the file; a `width`/`height` pair written by hand is a second source of truth that a re-export can falsify.
- **`scripts/make_favicon.py` uses `p > 0.5` in `(u/A)^2 + (|v|/B)^(1/p) = 1`.** Below 0.5 the shape is *blunter* than an ellipse, not pointier — the first draft got this backwards and drew an egg. At `p = 0.5` it is exactly an ellipse.
- **A favicon must be legible on a white tab bar and a near-black one.** The logo's own football is dark navy with chrome edges, which disappears on a dark tab, so the generated icon's sweep bottoms out at a mid blue instead. Check both grounds before believing an icon works.
- **A screenshot is not evidence a sandbox can use.** This environment cannot reach the deployed site and cannot download a workflow artifact (403 on `actions/artifacts/.../zip`), so a runner's screenshots are for the owner. What a session can check is a **job log**, which is why the representative review prints measurements. `get_job_logs` reads a daily refresh's whole summary — build id, counts, cohorts, confidence distribution, warnings — so release metadata never needs to be guessed.
- **A verifier's own bugs look exactly like product findings.** Four were found by running them: projections carry no `league_preset_id` (a points forecast varies by scoring, not league size), the tier record's name field is `display_name`, the search parameter is `search` rather than `q`, and `matchesSearch` matches name, team **or** an exact position. Each one reported a correct build as broken. Run a new checker against a build you already believe in before trusting the first thing it says.
- **The name cell is not the name.** It contains the injury badge and that badge's screen-reader sentence, so `td.textContent` yields `Chris JohnsonQ · HamstringCurrent status: …`. Read `.player-name`. Phase 7 made this same correction to `verify-real-build.mjs`; it had to be made again.
- **A tag cannot be pushed from this sandbox.** The git proxy answers **403 to any
  `refs/tags/*` push** while accepting branch pushes — confirmed on both an annotated and a
  lightweight tag — and `api.github.com` is unreachable, and the GitHub MCP server has no ref-
  or release-creation tool. `.github/workflows/release.yml` is the way through: dispatch-only,
  `contents: write` on its one job and nothing else, and it takes the commit as an **input**
  because a release tag must point at the code that produced the deployed build, which is not
  `HEAD` — the workflow itself lands on `main` after the commit it tags. That input is safe
  only because of the guard beside it: the SHA must be reachable from `main`. Do not re-derive
  this; dispatch the workflow.
- **A post-deploy check must not be scheduled.** `live-smoke.yml` gates nothing and deploys nothing; giving it a schedule would make an observation look like a gate, and `tests/unit/test_workflows.py` fails if one is added. The gate that protects production is still `daily-refresh`'s job graph, where "a gate failed" and "the previous site is still serving" are the same event.
- **The release refresh used `skip_capture: true`, and that was a source-policy decision rather than a shortcut.** MFL asks for at most one player-database request per day (ADR-017) and 2026-09-01 had already spent two. `skip_capture` skips only the two vendor calls: the store is still checked out and re-hashed, and the build, cohort selection, arbitrage, validation, `verify:board` and deploy all run in full on the new code SHA. That is the input's documented purpose — "re-run a deploy after a code fix".

## Phase-8 facts a later phase should not re-derive

- **A tier band, a player's interval bar and the axis are one CSS grid, not three similar ones.** `--board-cols`, `--board-gap` and `--board-pad` on `.tier-board` drive all three, and every breakpoint redefines only those. This is load-bearing: "adjacent tier bands overlap" is a claim about the measurement, and it is only true of the picture if the tracks are the same pixels. The first draft had them 45px apart.
- **Zero-based tier ordinals.** `schemas/tier_record.schema.json` says `minimum: 0` and the first tier really is 0. A URL parser that required a positive integer silently dropped it from every shared link. Take a bound from the contract, never from what looks reasonable.
- **`tiers=none` and an absent `tiers` are different states.** Empty means every tier closed; absent means the board chooses. A resolved default written into the URL on first paint would freeze one build's tier structure into a shared link.
- **A closed tier renders no rows, not hidden ones.** The container stays so `aria-controls` resolves; the `<li>`s do not.
- **axe reads the composited pixel, not the declaration.** A hue that passes in the token table fails on screen once an `opacity` multiplies it. There is no `opacity` on any text in the stylesheet for that reason.
- **The stylesheet contains no transition and no animation at all.** The one that existed was a 120ms slide on the skip link. That makes the reduced-motion assertion a true invariant rather than a check on one media query — keep it that way.
- **`--ink-faint` is a text colour and must clear 4.5:1.** It was 3.15:1 for two phases and only became a problem when the HUD gave it every micro-label.
- **`minmax(30rem, 1fr)` is a grid track wider than a 320px viewport.** Use `minmax(min(30rem, 100%), 1fr)`. WCAG Reflow names 320px and the Data view failed it by 168px.
- **`test.use({ reducedMotion })` did not typecheck against the pinned Playwright; `page.emulateMedia` does**, and reads better in one place anyway.
- **Two fixture market conditions, and neither is normal.** `MARKET_CONDITIONS` in `web/tests/fixtures/artifacts.ts`. A market-sensitive test that runs against only one of them is the defect this phase existed to find.
- **The performance board is synthetic and production-shaped.** `web/tests/e2e/measure-performance.mjs` builds 2,700 tier rows with the real board's tier sizes. The values are nonsense; the dimensions are not, and an 18-player fixture measures nothing.
- **The convergence audit was committed before it was run.** `87db5e5`, then the result. A rule written after its result is not a rule.
- **A green scan is not a scanned page.** axe reports zero violations on an empty document and on the schema-refusal screen. Every surface in `a11y.spec.ts` asserts a selector only that surface renders *before* scanning. The same applies to any check whose pass condition is an absence.
- **`reuseExistingServer` is on locally, so a stray `static-server.mjs` on port 4173 silently serves the wrong tree.** That is what made a clean-clone reproduction fail en masse. Check the port before blaming the clone.
- **`source-probe.yml` with `commit_results: true` rewrites `tests/fixtures/source_schemas/` and commits with `[skip ci]`.** The refresh is strict against a *removed* column — `test_required_columns_exist_in_the_phase0_recorded_schema` then fails — and blind to a silent widening. Read the diff; it is the contract.
- **The registry's spine is whatever its caller passes.** Market: `supplement_roster(roster, players)` per ADR-055. Status: the roster alone, because there "not on a roster" is the answer. The module docstring said "the roster" for both until Phase 8.

## Phase-9A facts a later phase should not re-derive

- **`grid-area: span` is silently invalid.** `span` is a reserved grid keyword, so the declaration is dropped, the base rule's `grid-column` applies instead, and the layout is quietly wrong — two implicit columns appeared and a band shrank to two thirds of its track. Nothing warns. Name a grid area anything else.
- **An implicit `auto` grid row is sized by its content, so `max-height` on the container does nothing.** This is why the player card rendered 1,002px inside a 768px dialog with no scrolling. `grid-template-rows: minmax(0, 1fr)` is what binds a single-child grid to a capped container.
- **The board's axis, the tier band and every player bar are one geometry, and the only safe way to keep them so is to build them the same way.** The axis is a lane — an empty gutter cell plus a body carrying the row grid — rather than a grid that restates `gutter + columns`. Restating it silently dropped the row gap and made the ticks 22px wider than the bars. `board.spec.ts › draws the tier band on exactly the track the player bars use` measures all three at 1440/900/390.
- **A translucent tint on a tile composites against whatever is behind the *grid*, not against the tile.** A `data-kind` background replaces the tile's own, so it landed on the readout grid's cyan wash and the micro-label came out at 4.36:1. Interaction and tint surfaces are pre-composited opaque tokens for exactly this reason; Phase 8's "axe reads the pixel" applies to backgrounds too.
- **The focus indicator is a real `outline`, not a `box-shadow`.** An outline follows the element's shape, survives an ancestor's `overflow`, and is what a check for a visible ring can read — a shadow leaves `outline-width` at zero. Rows inside a scroller use `outline-offset: -2px` so the ring is not clipped by the next row.
- **This sandbox cannot measure frontend performance across sessions.** Three runs of identical code varied by 9.0× on cold load and 6.5× on the arbitrage view. Any comparison has to be an interleaved A/B on one machine — build the other arm in a `git worktree`, symlink `node_modules`, alternate the runs. `measure-performance.mjs --css <file>` exists to attribute cost to one motif, and its first use found the noise rather than an answer.
- **Two spans per micro-glyph is 1,200 nodes on a 300-row board.** A gradient on the `<td>`'s own `background-image` renders identically for none. The cost of that: every rule painting a cell must set `background-color`, because the `background` shorthand resets `background-image` and row hover would erase the glyph.
- **The sheet breakpoint is a real branch, not a media query.** Artboard 1b's tab bar is a different accessibility tree — `role="tablist"`, one visible panel — so `useMediaQuery` reads the same 767px query the stylesheet uses. Move one and move the other. `useSyncExternalStore`, not `useState` + effect: reading during render is what stops the first paint being the wrong variant.
- **`web/dist-*/` was gitignored *and* tracked**, so 34 generated fixture-build files were carried in every commit that ran a build. Untracked in Phase 9A. Nothing referenced them; `playwright.config.ts` builds them in `globalSetup`.
- **The matured market condition is now a served build**, `/scenario/matured/`, not only a test fixture. `verify:board` against it checks 16 rows carrying a real `market_trend` — a path the launch fixture, with zero trends, could never exercise. This is the Phase-8 finding ("no test rendered the new state") applied to the *verification* layer.
- **The vitest player-detail tests time out under concurrent load, and it is not the code.** They render the whole app and open the dialog; on a quiet machine each takes about 0.6s, and with a `pytest` or Playwright run alongside they cross vitest's 5,000ms default and five of them fail together. Every failure reads "Test timed out", never an assertion. Re-run the suite on its own before believing it.
- **The design source is not always right about this product.** It captions its board axis "Vertical position inside a tier carries no meaning"; this board is in fair-rank order and prints the rank, so reproducing that caption would have been a truthfulness defect. Read design copy as a claim to check, not a string to copy.

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
- **Phase-3 modelling dependencies are LightGBM and NumPy only**; ridge, every metric and the bootstrap are written in-house, SciPy is a test-only cross-check (ADR-024).
- **Season 2025 is the sealed final holdout**, with primary and diagnostic slices predeclared before any comparison (ADR-025).
- **The Phase-3 core feature set is `intrinsic_core_v1`**, 78 of the 85 Phase-2 model inputs; snapshot-era-only columns, era indicators, the horizon index and the calendar index are excluded with recorded evidence (ADR-026).
- **The promotion and window-selection rules were frozen in code before the decisive comparison** (ADR-027).
- **The training window is W1, the full 2014+ expanding history** (ADR-028).
- **Q1, the direct-total LightGBM quantile model, advances to Phase 4** (ADR-029).
- **The Phase-4 decision rules were frozen in code before their results existed** (ADR-030).
- **Quantile monotonicity is an isotonic projection, not a sort**; the fitted calibration layer was measured and not adopted (ADR-031).
- **Horizon normalization was measured and rejected** on both declared routes; no calendar-year feature was added (ADR-032).
- **Candidate B, the availability x performance hurdle, is the production intrinsic model** (ADR-033).
- **Median simulated VORP is the fair rank**; the draw count is the convergence rule's predeclared fallback, and that rule's tier clause is stricter than the tier gate it protects (ADR-034).
- **Tiers come from the dynamic-programming alternative at penalty 1.0, and the stability gate fails** on boundary agreement; they ship with the failure attached (ADR-035).
- **The sealed 2025 holdout was evaluated once, at `2f0e725`, and passed** (ADR-036). It is spent.
- **`intrinsic-cb-hurdle-v1` is the production artifact**, trained through 2025, committed, digest-verified; a 2026 build uses `min(as_of, anchor)` and never loads target-season statistics (ADR-037).
- **Point-in-time captures live on the dedicated long-lived `market-data` branch**, immutable and timestamp-keyed, fail-closed on a differing rewrite (ADR-038).
- **The cohort sufficiency rule and its selection policy were frozen before their measurement** (ADR-039), and the measured population is core positions only.
- **A0 is the arbitrage baseline**: `rank_gap = market_adp - fair_rank`, `regional_value_gap = ln(market_adp / fair_rank)`, score = within-preset midpoint percentile, no reliability multiplier (ADR-040).
- **`confidence` is market-data quality, not a probability**, and dispersion is described rather than scored (ADR-041).
- **Trend is a trailing 7-day negated OLS slope over our own snapshots**, null until three observation days spanning three days exist (ADR-042).
- **Current player status is a separate artifact, keyed once per player, and is annotation only** (ADR-043).
- **Richer historical injury features are a 2027 refresh candidate**; the 2025 holdout is spent, so there is nothing to promote them against (ADR-044).
- **A redraft board may only be priced by a keeper-free cohort** (`phase5_cohort_v2`, ADR-045). No bound moved; the resulting insufficiency is published.
- **The frontend draws a tier as a band, never as a line** (ADR-046).
- **A shared market condition is explained once at view level, from `build_metadata`** (ADR-047).
- **The frontend's dependency set is TanStack Table v8, d3-scale/d3-array and Playwright** — no router, no UI kit, no charting framework (ADR-048).
- **V1 deploys as a public repository on a public GitHub Pages project site**, standard GitHub-hosted Actions, no external paid host; the repository stays private through Phase 6 (ADR-016 as amended 2026-08-21).
- **FantasyPros terms review is complete**; the source is `benchmark_only` and is *not* a production input, so it is absent from the site's source list (ADR-014 as amended).
- Source verification runs on a GitHub runner, not in an egress-restricted sandbox (ADR-009).
- **`min_total_drafts` was measuring the evidence, not the filter** — the keeper-free cohort crossed its own bar unaided, so no bound moved (ADR-052, resolved 2026-08-31).
- **FFC is not a production V1 price source and MFL remains the only one**; ADR-056's runner-measured findings are accepted and its integration is deferred to a dedicated post-V1 market-methodology change. No multi-source ADP, no averaging (ADR-056 Phase-8 disposition).
- **Simulation convergence is audited separately from tier-boundary stability**, on the promoted configuration only, with every Phase-4 bound inherited unchanged and no power to select a draw count (ADR-057).
- **Methodology is stated once in Data**; a repeated surface carries only what stops a number being misread (ADR-058).
- **The behavioural end-to-end suite is single-engine; a smoke suite is three-engine**, and the three-engine gate is runner-only (ADR-059).

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

## Phase-3 facts a later phase should not re-derive

- **A model implements one method.** `fit_predict(train, validate, context)` is the whole interface, so there is no fitted object that could outlive a fold and nowhere to keep a statistic computed over the whole dataset. Fold isolation is structural, not a convention to remember.
- **The seal is at load time.** `load_modeling_dataset` drops sealed seasons before anything sees the frame, and the fold generator refuses to build a fold that validates one. `tests/model/test_folds_and_holdout.py` proves it by construction: poisoning every 2025 label leaves a development run byte-identical. Do not add a second, softer path to the holdout.
- **Residual quantiles come from an inner chronological split** of the training window - fit on the earlier seasons, residuals from the latest one or two, stratified by predicted level where a stratum has 100+ rows. That is how B0 and B1 get honest intervals; never give a baseline a fixed-width band.
- **B0 is a strong baseline on purpose.** Prior-season points per game times the training-fold mean games for the same availability *and* age cohort beats a raw prior-season total on every development season tried, and beats ridge on MAE at every position. If a future candidate "beats the baseline", check which baseline.
- **Macro before row-weighted.** Aggregates are means over season x position x scoring cells. WR and RB cells carry two to three times the rows of QB and TE ones, so a pooled mean lets them decide positional questions on their own. Row-weighted numbers are emitted as diagnostics.
- **Metrics are the project's own code** (ADR-024), pinned by hand-worked examples and cross-checked against SciPy. Spearman is Pearson on average ranks; Kendall is the tie-corrected tau-b. Do not swap in a library mid-project without re-pinning the report numbers.
- **The paired bootstrap resamples within cells and carries both models through the same resample.** Two models differing by a constant produce a degenerate interval, which is the property that makes the interval mean anything; independent resampling would not.
- **Q1's raw quantiles cross on 38.7% of rows** with a mean magnitude of 0.53 points against a 62.7-point P10-P90 width. Phase 3 sorts them and reports the raw rate separately. Phase 4 should fix the cause, not keep sorting.
- **Top-K retrieval does not follow rank correlation.** Q1 has the better Spearman but B1 retrieves more of the actual top-K (0.593 against 0.544). A median-quantile point prediction is robust, and robustness compresses the top of the board. Measure top-K on simulated VORP in Phase 4 rather than assuming the point ordering carries over.
- **`prev1_games_missed` was clamped to zero when either component was missing.** Phase 3 fixed it to null, matching what the dictionary always declared, and added the regression test. 4,946 of 11,604 rows are affected; a dataset built before this fix disagrees.

## Phase-4 facts a later phase should not re-derive

- **`ffdraft.modeling.rules` is the freeze, and `ffdraft.modeling.frozen` is its output.** Every Phase-4 threshold lives in the first as a frozen dataclass with a pure evaluator; every decision those rules made lives in the second as a constant. If you want to know what the production system is, read `frozen.py` — it is one screen and every value cites the ADR that produced it. Do not add a decision to `frozen.py` that no rule made.
- **A rule that fails is a result.** Two did. The convergence rule fell through to its own fallback clause and the tier stability gate failed outright, and both are published rather than repaired. If a future session is tempted to move `min_boundary_agreement` or `max_largest_tier_share`, that is a new rule version with its own evidence and its own ADR — not an edit.
- **Crossing is fixed by projection, not by sorting.** PAV projects the raw quantile vector onto the monotone cone, which is an L2 projection onto a closed convex set that contains the true quantile vector, so it provably cannot move the estimate further from the truth. Sorting has no such guarantee. Raw crossing went 0.387 -> 0.000 and CB's own components do not cross at all.
- **The hurdle's two components are coupled, not independent.** A Gaussian copula carries one fold-fitted rank correlation between availability and per-game performance, estimated from probability-integral transforms on an inner chronological split. Assuming independence would have understated the spread of the season total.
- **VORP is simulated, never differenced against a fixed replacement.** Every draw allocates starters and derives *that draw's* replacement level. Subtracting one deterministic baseline from every quantile would have made VORP a shifted copy of points and destroyed the league-scarcity information the whole simulation exists to produce.
- **Point draws deliberately do not depend on the league preset.** The same simulated seasons are re-allocated under every roster shape, so a preset-to-preset difference is a scarcity difference rather than Monte Carlo noise. Per-player BLAKE2b streams make a board independent of player order and pool membership too.
- **`ffdraft.simulation.allocation` is still the only allocator.** Phase 4 fed it sampled points instead of realized ones; it did not write a second one, and neither should Phase 5+.
- **Tier membership is reproducible; tier boundaries are not.** ARI 0.865 beside boundary agreement 0.239 is not a contradiction, it is the finding. Simulated VORP declines almost smoothly, so "where a tier ends" is mostly not an identified quantity — only about four cut sites on a 300-deep board are. Any UI that draws a hard line overstates the measurement.
- **The board's deep tail genuinely is one group.** At penalty 3.0 the segmentation wants tiers of 82 and 110 players. The frozen 25%-of-board cap forbids that, which is what forces the unstable cuts. A future tier rule should let the undifferentiated tail be one wide tier rather than slicing it.
- **The holdout is spent and the seal is one-way in code.** `--final-eval` needs a fixed token *and* a written reason; `train-production --allow-unsealed` needs the same token and refuses unless the holdout has already been consumed. There is no softer path, and none should be added.
- **A current build never loads target-season statistics.** `include_target_statistics=False` is correct in general — a preseason board may not consume the season it predicts — and not a workaround for 2026 being unplayed. The 404 from nflverse for an unplayed season is a symptom of the same fact.
- **A pre-anchor build uses its own timestamp, not the anchor.** `min(as_of, anchor)`. Stamping a future anchor onto a build that ran before it would claim knowledge the build does not have.
- **Current roster status is metadata, never a feature.** It can drop a retired player from the board and it annotates rows with flags, but it has no development-era support and cannot enter a prediction.
- **The Phase-3 harness reproduces exactly.** `evaluate-intrinsic` was re-run at Phase 4 and diffed against the committed report: identical on every number, decision and check, with only the timestamped `experiment_id` differing. Determinism here is real, not aspirational.
- **Model cards are generated, like the feature dictionary.** `ffdraft model-card` reads the committed experiment reports and the artifact. A number in a card that no command produces is a number that can drift.

## Phase-5 facts a later phase should not re-derive

- **The firewall is a test, not a habit.** `tests/contract/test_architecture_boundary.py` walks the import graph — function-local imports included — from every intrinsic module and fails on any path to market data. It found a real edge on its first run. If a new module needs the append-only store, import `ffdraft.retention`, not `ffdraft.market`.
- **A quote belongs to a cohort, not a preset.** `market_quote` 2.0 records `cohort_id`; exactness is a per-preset verdict the selection rule reaches later. Do not reintroduce a preset column on a quote row.
- **The analysis is offline by construction.** Only `snapshot-market` and `capture-status` touch a vendor. Cohort measurement, arbitrage and the cards all read retained bytes, which is why a session behind an egress policy can still build and validate the whole product, and why every report can be regenerated and diffed.
- **`build_metadata.json` is merged, never rewritten.** An arbitrage build that overwrote it would erase the Phase-4 tier-stability warning. A test asserts the warning survives.
- **`source_as_of_utc` is null for MFL everywhere, forever.** Its response `timestamp` is generation time. It is retained as `response_timestamp` vendor metadata and a semantic check fails the build if the field is ever populated.
- **Two snapshots on the same day are two observations but one observation day.** That is what stops a "7-day trend" from silently becoming a 6-hour one.
- **The status build goes through the frame contract, not schema inference.** A 12,000-row Sleeper capture is mostly nulls; Polars infers from the first rows, so the first injury note several thousand rows in used to kill the build.
- **An empty *cohort* is a finding; an empty *capture* is an outage.** The adapter's `source.too_few_records` is downgraded per cohort and re-raised at capture level, because a study that refused to record a collapsed cohort could not prove the collapse.
- **`no-keeper` and `no-mock-no-keeper` are the same cohort on this data**, because `IS_MOCK=0` does nothing. The fallback tie-break picks the latter; it is an arbitrary but deterministic choice between identical populations.

## Phase-6 facts a later phase should not re-derive

- **The browser filters, joins and formats. It computes nothing.** No component derives a VORP, a fair rank, a tier or an arbitrage score. `npm run verify:board` proves it against the artifact bytes on the live build; if a future change makes a chart "smarter", that command is what fails.
- **`web/tests/fixtures/artifacts.ts` is the test board, and it is not the real one.** Ten players carrying the cases that are easy to get wrong: an injury designation, a status record with no designation, no status record at all, a tier player with no market price, a generational suffix, and two quarterback premiums. Every arbitrage row reads `low` with a null trend, mirroring the launch condition. The real generated artifacts change on every rebuild; a test bound to them proves nothing.
- **An overflow container only clips absolutely positioned descendants when it is itself positioned.** `.table-scroll` carries `position: relative` for that reason and only that reason. Remove it and the screen-reader-only spans inside table cells escape a horizontally scrolled table and give the whole page an invisible horizontal scrollbar on mobile.
- **The tier axis spans the interval the chart draws.** P25-P75, not P10-P90. Scaling to the outer interval spends a third of the width on tails the chart does not render and parks every median in the middle third. P10-P90 lives in player detail and in every mark's accessible label.
- **Almost nothing shares a lane row on the real board, and that is the finding.** A top back's interquartile interval is wider than the entire gap between the first and twentieth median. Packing two players side by side would only be possible by drawing intervals too short to be true.
- **Charts are one tab stop, not three hundred.** `useRovingMarks` implements the composite-widget pattern; the table beside each chart remains the definitive accessible equivalent.
- **The end-to-end run builds five sites**: root, `/jeisey-tiers/`, and three that withhold or corrupt an artifact. Each scenario is its own build at its own base path, so no test can see another's outage, and none of them can silently read the healthy build's `data/`.
- **Every spec fails a request that leaves localhost.** That is what makes `docs/ARCHITECTURE.md` section 3.2 a check rather than a convention.
- **`docs/visual-qa/` captures the *fixture* build, deliberately.** Two runs of the same code produce the same images, so a review is reproducible; the real board is reviewed live during a build because it changes every time.
- **jsdom has no `HTMLDialogElement.showModal` and no `ResizeObserver`.** Both are polyfilled in `web/tests/setup.ts` rather than worked around in components; production code should use the platform API.
- **TanStack Table is pinned to v8**, not the v9 rewrite (ADR-048). The two React-Compiler warnings it produces are left visible rather than silenced.

## Phase-7 facts a later phase should not re-derive

- **Visibility is a repository property, not a branch property.** This is the fact the whole phase turned on. There is no private branch inside a public repository, and no amount of Pages-artifact hygiene changes that, because `git clone` hands over every branch. If a future phase wants to publish something new, ask what a clone would carry before asking what the build copies.
- **The store's address lives in `config/source-registry.yaml` and nowhere else.** `.github/actions/market-data-store` reads it; `tests/unit/test_workflows.py` fails if a workflow grows the literal. Moving the store again is one edit to one file.
- **Last-known-good is `needs:`, not `if:`.** `deploy` needs `build` needs `capture`, and the deploy job contains only the Pages actions. Do not merge them "for speed" — the separation *is* the guarantee, and a real unplanned failure ([32591545618](https://github.com/jeisey/jeisey-tiers/actions/runs/32591545618)) demonstrated it before the rehearsed one did.
- **Concurrency queues rather than cancels, on purpose.** A cancellation between `git commit` and `git push` in the capture job would drop a validated snapshot. Queueing also gives the ordering: a superseding run deploys *after* the one it supersedes.
- **The forced-failure proof breaks a real invariant.** It corrupts quantile monotonicity and lets `validate-artifacts` reject it, so `artifact.non_monotonic_quantiles` is what stops the deploy. If a future change makes this an `exit 1`, the proof stops proving anything.
- **A production capture must retain a cohort the frozen rule can pick.** This was not true for two phases and no test noticed, because every selection test handed `select_cohorts` all sixteen candidates. When a rule gains a qualifying condition, check the *capture set* against it, not only the rule.
- **Both market identity "bridges" terminate at the same registry, so the registry's universe decides what can ever resolve.** `build_registry` builds the canonical player set from the current season's roster, and both `registry.lookup` calls in `_resolve_one_quote` end there, so a player the registry lacks cannot resolve through *either* bridge and cannot be aliased either (`alias_target_unknown`). Two bridges guard against a wrong answer, not against an absent player. And the registry's inputs are themselves incomplete: `load_rosters(season)` omitted 101 active skill players in 2026, which is why the spine is now roster + `load_players()` (ADR-055).
- **Classify an unpriced board player before remedying it.** It is one of: present in the vendor payload but unresolved (an identity defect — ours), priced only in a cohort the block may not use (a cohort-rule question), or absent from the vendor entirely (a source-depth question). ADR-054's table works all three, and getting the classification wrong sent a whole investigation at the board when the bug was in the registry.
- **A vendor's documented parameter is not a working parameter.** FFC's help article lists `teams`; the API accepts it, echoes it back in `meta`, and returns byte-identical data for all four league sizes (probe [32998697322](https://github.com/jeisey/jeisey-tiers/actions/runs/32998697322)). MFL's `CUTOFF` and `DAYS` behave the same way. Measure a filter before building a cohort on it — `config/source-registry.yaml` only lists honoured filters for exactly this reason.
- **`robots.txt` and a published API licence answer different questions.** FFC disallows `/api/` to crawlers *and* documents that same API as free for personal and commercial use with attribution. Both are true: the first addresses indexers, the second addresses clients. Read the publisher's own terms before concluding a source is off-limits — and before concluding it is open.
- **Egress denial is not a reason to guess.** This sandbox 403s most vendor hosts, which is why ADR-053 could only say "unverified" for months. `.github/workflows/source-probe-ffc.yml` runs the check on a runner and prints to the job log. Anything a probe can answer should not appear in an ADR as an assumption.
- **A source's silence is not evidence of absence.** `load_rosters(2026)` not listing Stefon Diggs was read as "Diggs is a free agent"; `load_players()` was one call away and said WAS/ACT/2026. Before concluding a fact about the world from one file, ask which other file answers the same question.
- **A verification check must assert the contract, not the day's data.** `verify-real-build.mjs` asserted that every arbitrage Trend cell renders an em dash. That was true in Phase 6 only because the store was too young for ADR-042, and the first build with a real trend failed it — a green product failing a test that had frozen the launch condition. The check now compares the rendered cell with the artifact's own `market_trend`, like every other assertion in that file. When a value is null *because the system is young*, do not pin the null. The same audit found a second instance in the same file: the tier-row name assertion stripped the injury badge out of the cell text with a pattern that assumed `IR · Knee`, so a designation reported without a body part would have failed a correct board; it now reads the name from `.player-name` instead of un-rendering the cell.
- **The nflverse cache key contains the UTC date and has no `restore-keys`.** A prefix fallback would make a cache hit serve staler rosters than a miss, which inverts the "correct, only slower" rule. Do not add restore-keys to that one.
- **A workflow artifact on a public repository is world-readable.** The build record therefore stages the store's *manifests* only, and asserts no `.gz` reached it. Adding anything from `market-data/` to an artifact needs that same thought.
- **`persist-credentials: false` on read-only store checkouts is load-bearing**, not tidiness: it is what keeps a credential out of the workspace while the frontend builds and the Pages artifact is packaged. Confirmed in the post-job cleanup logs.
- **`npm run e2e | tail` reports `tail`'s exit code.** Without `set -o pipefail` a completely red Playwright suite reads as green. This cost real time; do not pipe a gate's output without pipefail.
- **This sandbox's Chromium build does not match the pinned Playwright release.** Export `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` before `npm run e2e` here. On a runner, `npx playwright install` fetches the matching build and none of this applies.
- **`api.github.com` is unreachable from this environment and the git proxy rejects ref deletions.** Repository visibility and branch deletion are owner actions; do not plan a phase around automating them.

## Open questions requiring evidence

- **How to make tier boundaries meet a stability bar, or how to stop pretending they are lines.** The measurement says a 300-deep board supports about four reproducible cut sites. Two candidate remedies, both new decisions needing their own rule version and evidence: let the undifferentiated tail be one wide tier by re-specifying `max_largest_tier_share`, or keep the segmentation and present membership with a boundary-confidence band instead of a hard edge. **Do not simply lower the threshold** (ADR-035).
- ~~**How to re-specify the Monte Carlo convergence rule.**~~ **Done** (ADR-057). `phase8_simulation_convergence_v1` evaluates the promoted configuration only, inherits every bound unchanged, reports tier agreement instead of deciding on it, and cannot select a draw count. **What remains open is narrower and has a number:** at 10,000 draws the ranking criteria pass (fair-rank Spearman 0.9994, top-50 overlap 0.98, mean top-150 rank change 1.35, replacement 0.249 against a 0.5 bar) and the value criteria do not (mean |Δ expected VORP| 0.314 against 0.25; mean |Δ P50| 0.416 against 0.35; p99 |Δ expected| 1.93 against 1.50). Closing that last ~25% is a simulation-refresh question, and lowering the draw count is not an answer to it.
- **Whether correlated player draws are worth building.** V1 samples every player independently, so it cannot express that a quarterback's collapse takes his receivers with him. That is the largest structural simplification in the simulation and it was never measured.
- ~~**Whether `min_total_drafts` is the right instrument for a filtered cohort.**~~ **Closed 2026-08-31** (ADR-052 resolution). The keeper-free cohort went 125 → 735 drafts in eleven days with the filter, the clause and the bound all untouched; every preset now reports `sufficient: yes` with no failed clause and a median per-player sample of 487. The structural reading — that `IS_KEEPER=N` caps the achievable count — is refuted. **No bound moved, and none should.**
- ~~**Whether the fallback should prefer specificity when candidates are close.**~~ **Moot for V1.** With qualifying cohorts available the rule now selects `ppr-no-keeper` for the PPR presets and `no-keeper` for the others, on its own. The tie-break question only arises when nothing is sufficient; it is not a launch blocker and any future change still needs a comparison rule predeclared before player-level results are read.
- **Whether a learned arbitrage model is ever worth it.** Not before three draft seasons of our own snapshots (ADR-010), which is 2029 at the earliest. Until then, snapshot retention is still the highest-value arbitrage work in the repository.
- **Repository visibility** — deferred to Phase 7 by ADR-016.
- **Market cohort mix closer to peak draft season** — re-measure at the start of Phase 5 (ADR-012 amendment).
- **Whether `load_ftn_charting` earns its CC-BY-SA obligation** — still open, and still not needed.

## Known risks (non-blocking)

- ~~**Two owner actions gate the live site**~~ — **done.** Both happened in the required order: the `market-data` branch was deleted from `jeisey/jeisey-tiers` and only then was the repository made public. The record of why the order mattered is `docs/PHASE7_DEPLOYMENT.md` section 7, and it stays because a future session moving anything else into this repository needs the same reasoning: a clone hands over every branch, so ask what a clone would carry before asking what the build copies.
- **`MARKET_DATA_REPO_TOKEN` expires.** When it does the daily refresh fails at its first job with a message naming the secret, the deploy job is never reached, and the deployed site stays live and stale. Loud and non-destructive, but it needs a calendar reminder; rotation steps are `docs/OPERATIONS.md` section 5.3.
- **Scheduled-workflow inactivity got slightly worse.** The daily capture now commits to the *private data* repository, so a run of `daily-refresh.yml` creates no activity in the application repository at all. GitHub disables scheduled workflows in public repositories after long inactivity; re-enabling steps are in `docs/OPERATIONS.md` section 12.
- **Two MyFantasyLeague player-database requests were made on 2026-09-01**, both by ordinary refreshes (one dispatched, one scheduled). The release refresh took none: it ran with `skip_capture: true`, which is exactly what that input exists for. Watch this on any day that mixes a dispatch with the schedule.
- **Three MyFantasyLeague player-database requests were made on 2026-08-22** — the out-of-band capture, the first production refresh, and the refresh that validated the cohort fix. MFL asks for at most one per day. This was a migration day and the third was needed to prove the fix; a routine day takes exactly one, and `skip_capture` exists so a re-deploy does not take a second.

- ~~**Every arbitrage row reads `low` confidence**~~ — **no longer true, and the way it stopped being true is the point.** The 2026-08-31 board is 1,889 `medium` against 45 `low`, with the frozen rule untouched (ADR-052 resolution). What this exposed is recorded above: no test rendered the new state. `confidence` is now discriminating, and both conditions are exercised.
- **`wide_market_range` is still non-discriminating, and is no longer rendered.** The min-to-max span widens with sample size, so it fires on most of the board at any realistic draft count and always will. Phase 8's instruction was to stop giving it repetitive visual treatment rather than to retune its threshold: the flag stays on the artifact and in the CSV, the actual `market_adp_low`/`market_adp_high` range is shown directly, and Data explains what the range is once (ADR-041, ADR-058).
- **The 2026 board is priced by 792 keeper-free redraft drafts** as of the release build, up from 125 at Phase-5 launch, with a median of 520 drafts behind each top-150 player. It got there on its own, with no bound moved (ADR-052 resolution).
- **STD and HALF are still served by an all-scoring cohort.** MyFantasyLeague exposes a PPR flag and no half-PPR filter, so a standard-scoring reader is looking at a board priced mostly by PPR drafters. Stated on the Data view. This is the one thing Fantasy Football Calculator could genuinely fix, and is the aim of the deferred post-V1 market-methodology change (ADR-056 Phase-8 disposition).
- **Sleeper publishes `practice_participation`, `practice_description` and `injury_start_date` as keys with null values in the preseason.** They are normalized and will populate in season; a Phase-6 UI must not assume they are present.
- **Tiers are published having failed their stability gate.** `build_metadata.json` carries a `current.tier_stability` warning and the cards say so, but nothing stops a consumer from rendering a hard line anyway. The Phase-6 frontend is where this becomes a user-visible risk rather than a documented one.
- **Residual Monte Carlo error is real and unmeasured beyond the ladder.** At 10,000 draws two seeds differ by about 0.3 fantasy points on a player's expected VORP and under 1.5 rank positions in the top 150. Tier boundaries move more than that, which is part of why boundary agreement is low. A build is deterministic for a fixed seed; it is not seed-invariant.
- **CB's pooled P25-P75 coverage is 0.614 against a nominal 0.50**, driven by zero-game rows: among players with at least one game it is 0.456, among zero-game rows 0.836, and 18.4% of rows have `q25 == q75 == 0`. The hurdle is right that many players score nothing; the inner interval is consequently wide where it should be degenerate. Recorded as an ADR-033 limitation rather than patched.
- **The model card and tier report are only as current as the last `ffdraft model-card` run.** They are generated from committed experiment reports, so a retrain without regenerating them leaves published numbers describing a model that no longer exists.
- **The 2014-2016 era boundary is real and is reported as a warning, not hidden.** It comes from upstream roster coverage, not from this code. Any metric averaged across all twelve seasons mixes two different universes. ADR-028 chose to train across it anyway, on measured evidence, and records that W1's advantage is largest where W2 has least data.
- **The fantasy horizon changed at 2021** (weeks 1-16 to weeks 1-17), so season totals are on a ~6% different scale either side of it. It affects every candidate identically within a fold and is not corrected for; validation season 2021 is the one fold trained entirely on 16-week seasons. `prev1_team_games`, which is that horizon expressed as a lagged count, is excluded from the feature set for the same reason (ADR-026).
- **B0 and B1 predictive intervals under-cover slightly** because their residual quantiles are estimated on one or two inner-split seasons, which understates season-to-season variance. Q1's P10-P90 coverage is 0.771 against a nominal 0.80. Calibration is Phase-4 work and must be fitted on development folds only.
- **`team_at_anchor` is null for almost every pre-2025 veteran.** Free agency and trades are unobservable before the snapshot era, so `team_change_flag` is null there too, with `team_change_known` saying so. Overall `team_at_anchor` coverage is 12%; that is honest, not a defect.
- **Pre-2025 rookies have no depth or role signal at all** (`depth_unavailable`), by ADR-018. Their preseason signal is draft capital, biography and team context. Coverage is reported per season and position rather than patched over.
- **One upstream GSIS id names two different players** (`00-0035718`, 2019). Failed closed and excluded; re-check if nflverse corrects it.
- **Source-schema drift is detected, not prevented.** Phase 2 adds a semantic layer over the structural one, but a column that changes meaning *inside* its declared domain would still pass. Re-run `scripts/source_probe.py` and `scripts/capture_source_schemas.py` if more than a few weeks pass.
- **`mypy --strict` covers `src/ffdraft` only.** Tests are covered by execution.
- **The historical build takes a few minutes** of nflverse downloads plus the independence proof. There is no incremental mode; if that becomes painful, cache the normalized frames rather than weakening the proof.

- **The Tier Board is tall by construction.** One hundred players at ~17px plus lane padding is roughly 1,800px, because intervals this wide force one player per row. It reads as a board and scrolls like one; a future tier rule that produced fewer, wider tiers would not change that, since the constraint is interval width rather than tier count.
- **The React Compiler skips optimising the two table components**, because `useReactTable` returns functions it cannot memoise. A warning, not an error, and not measurable on a 300-row board (ADR-048).
- **`expected_games` is absent from the production projection artifact** even though the schema allows it and the fixture pipeline emits it. The UI hides the field rather than showing an em dash. If a future build starts emitting it, it appears with no code change.
- **The visual-QA screenshots are of the fixture board.** They prove layout, not data. A regression that only appears at production row counts would not show up there; `npm run verify:board` and a live look are what cover that.

## Repository notes

- **`BUNDLE_MANIFEST.txt` is a snapshot of the original specification bundle, not a live checksum.** The specification set — `AGENTS.md`, `PRD.md`, `MASTER_SPEC.md`, `PROMPT_START_HERE.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/UX_SPEC.md`, `docs/BASELINE_FFTIERS_ANALYSIS.md`, `repo-tree.txt` — is untouched. **`docs/TEST_STRATEGY.md` is the exception and always was:** it has been *appended to* since Phase 4 (sections 8.1 and 8.2 record the Phase-5 and Phase-8 invariants), because a test strategy that cannot record what a later phase decided to test is a document nobody reads. Its original sections are unmodified; a phase adds a section rather than editing one. The living records — `README.md`, `TASKS.md`, `SESSION_STATE.md`, `docs/DECISIONS.md`, `docs/DATA_SOURCES.md`, `docs/DATA_CONTRACTS.md`, `docs/MODELING.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/SECURITY_LICENSE.md`, `docs/FEATURE_DICTIONARY.md`, `config/*` — are updated as the contract requires.
- **`ruff` 0.16 formats Python code blocks inside Markdown.** Markdown is excluded from ruff in `pyproject.toml`; do not remove that exclusion.
- **Regenerating the golden artifacts is a deliberate act**, not a fix for a red test: `uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000`. Read the diff first.
- **`docs/FEATURE_DICTIONARY.md` is generated.** Regenerate from `uv run ffdraft feature-dictionary` after changing `ffdraft.features.dictionary`; a test fails if it is stale.
- **`data/historical/` is gitignored.** Rebuild it rather than looking for it in a clone.
- **The retained store is a separate private repository** (ADR-049). `git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data`, then pass `--store ../market-data` to the Phase-5 commands. It is not in this working tree, is never merged, and is not in this repository at all — which is what makes a public application repository safe. A contributor without access to it can still run every fixture-based gate, the whole frontend and the entire test suite; the only thing they cannot do is rebuild the production board.
- **`docs/market-cohorts/` is committed evidence**, like `docs/source-probes/` and `docs/experiments/`. Regenerate with `ffdraft measure-market-cohorts` and read the diff.
- **`models/cards/arbitrage-method-a0.*` is generated.** Regenerate with `ffdraft arbitrage-card` after any rebuild; a number in a card that no command produces is a number that can drift.
- **`web/public/favicon.{ico,png}` and `apple-touch-icon.png` are generated**, not drawn. `uv run python scripts/make_favicon.py` writes them from `web/src/assets/jt_logo.png`; `--check` compares the committed bytes and `ci.yml` runs it. Change the geometry constants at the top of that script, never the PNG. `--sample` reprints the palette evidence the colours were taken from.
- **`docs/PHASE8_UI_FEEDBACK.md` was deliberately not reopened by Phase 9B.** None of the three release-polish changes traces to an owner item in it — the logo, the favicon and the CSV centring are new requests, recorded in `TASKS.md` and here. Reopening it for ceremony would have made a trace document describe work it never traced.
- **The Phase-3 experiment reports are committed; the row-level predictions are not.** `docs/experiments/phase3-intrinsic-baselines/{experiment.json,experiment.md}` are the evidence behind ADR-028 and ADR-029, in the same spirit as `docs/source-probes/`. `predictions.parquet` is written only with `--write-predictions` and is gitignored.

## Known blockers

**None.**

The Phase-8 blocker — the Claude Design MCP being unreachable, so the design language was inferred from the owner's written brief rather than read out of the project — is **closed**. It was never a code problem: the owner downloaded `Player Card HUD.dc.html` and `support.js` and handed them to the Phase-9A session directly. `/design-login` was never run and no MCP was involved. If a later phase needs the project again, that is the route that works; do not plan around `DesignSync` from a non-interactive session, and do not expect an unauthenticated fetch of `https://claude.ai/design/p/…` to return anything but 403.

Nothing else is blocking. The four analytical findings are unchanged and none is a blocker: the Monte Carlo residual (ADR-034 as narrowed by ADR-057), tier boundary stability (ADR-035), the non-discriminating `wide_market_range` flag (ADR-041) and the all-scoring cohort serving STD and HALF (ADR-012). All four are published as limitations on the site's Data view rather than repaired by moving a threshold, and all four are in the post-V1 backlog below with what would have to be true before touching them.

**Two things this environment cannot do, and a later session should not plan around.** It has no egress to vendor hosts or to the deployed site (ADR-009), and it cannot download a workflow artifact — `actions/artifacts/<id>/zip` answers 403. So a real board can only be built on a runner, a deployed site can only be smoked on a runner, and a runner's screenshots are evidence for a human rather than for the session. What *is* readable is a job log: `get_job_logs` returns a daily refresh's whole rendered summary, which is where release metadata should be read from rather than guessed.

## Post-V1 research backlog

**None of these is a defect, a blocker, or a phase gate.** They are the honest open ends of a
released V1, kept here so a future session inherits questions rather than a search. Each names
what would have to be true before it is worth doing.

1. **Multi-source market pricing, and exact half-PPR.** ADR-053 and ADR-056 are accepted with
   integration deferred. Fantasy Football Calculator serves genuine `standard`, `ppr` and
   `half-ppr` cohorts with 7-30x MFL's volume and a published per-player `stdev`; its `teams`
   parameter is accepted and **ignored**, so it offers three scoring cohorts and not twelve,
   and team-size exactness must never be claimed from it. The pay-off is a real half-PPR price,
   which `IS_PPR` as a boolean can never be. Two preconditions, both non-negotiable: a durable
   reviewed identity crosswalk with the same fail-closed discipline as the existing bridges,
   because FFC's player id bridges to nothing this project holds; and a frozen source-selection
   rule committed **before** its evidence exists. Do not average two aggregates over different
   populations and windows.
2. **Tier-boundary methodology.** The measurement says a 300-deep board supports about four
   reproducible cut sites (ADR-035). Two candidate remedies, each needing its own rule version
   and evidence: re-specify `max_largest_tier_share` so the undifferentiated tail is one wide
   tier, or keep the segmentation and present membership with a boundary-confidence band
   instead of a hard edge. **Do not simply lower the threshold.**
3. **Residual Monte Carlo value convergence.** At 10,000 draws the ranking criteria pass and
   the value criteria miss by 19-29% (ADR-057). Closing that is a simulation-refresh question;
   lowering the draw count is not an answer to it.
4. **Correlated player draws.** V1 samples every player independently, so it cannot express
   that a quarterback's collapse takes his receivers with him. The largest structural
   simplification in the simulation, and never measured.
5. **Historical injury features.** A 2027 intrinsic-refresh candidate (ADR-044). The 2025
   holdout is spent, so there is nothing to promote them against until a new season completes.
6. **Learned arbitrage.** Not before three draft seasons of this project's own point-in-time
   snapshots (ADR-010), which is 2029 at the earliest. Until then, snapshot retention is still
   the highest-value arbitrage work in the repository — a price not captured today can never
   be reconstructed.
7. **`TOP_BOARD_PRICED_MINIMUM` is an alias of `IDENTITY_COVERAGE_MINIMUM`** rather than a
   derived bar (ADR-056 §1). Give it its own constant and a stated derivation at a moment when
   nobody is reading a number it would move.
8. **FTN advanced metrics.** Still open, still not needed, and still carrying a share-alike
   obligation that would bind what this site publishes.

## Next action

**None that is a gate. V1.0.0 is released and the site is live and refreshing itself daily.**

The ordinary operating loop from here is `docs/OPERATIONS.md`: the daily refresh runs at 07:17 America/New_York, a failed gate leaves the previous site serving, and `live-smoke.yml` is the dispatch-only way to check the deployed site afterwards. Two standing operational chores, neither urgent: `MARKET_DATA_REPO_TOKEN` expires and needs a calendar reminder (section 5.3), and GitHub disables scheduled workflows in public repositories after long inactivity, which the daily capture no longer prevents because it commits to the *private data* repository (section 12).

**The post-V1 backlog is below, under "Post-V1 research backlog". None of it is a defect and none of it should be picked up as though it were a phase gate.** The two most valuable things a future session can do are unglamorous: keep the snapshot retention running, because a point-in-time price not captured today can never be reconstructed (ADR-010, ADR-038), and re-run `scripts/source_probe.py` before trusting any adapter after a few weeks have passed, because source-schema drift is detected rather than prevented.
