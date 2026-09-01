# Release 2 Roadmap — Multi-Market Draft Intelligence + In-Season Mode

**Status:** Planned  
**Release target:** `v2.0.0`  
**Planning baseline:** `v1.0.0` / commit `e9c73d1`  
**Planning date:** 2026-09-01  
**Operational deadline:** first 2026 NFL game is Wednesday, September 9, 2026 at 8:20 PM ET  
**Primary implementation window:** dedicated coding-agent sessions over September 1-3, 2026

---

## 1. Release 2 objective

Release 1 proved the core product:

1. an **intrinsic, market-blind fantasy valuation system**;
2. a **league-aware tier board** built from simulated VORP;
3. an **arbitrage board** comparing intrinsic fair rank with one verified market price source;
4. a deterministic, static GitHub Pages product with daily refreshes and fail-closed data quality.

Release 2 should extend that product without rewriting or weakening the Release 1 contract.

The product should answer two additional questions:

> **Draft season:** “How does the intrinsic model compare with the market I actually draft on, and where do markets disagree with each other?”

> **In season:** “Given everything known through today, who has the most rest-of-season value, and where is current fantasy-market behavior mispricing that value?”

Release 2 is therefore split into three phases:

- **Phase 10 — Multi-market draft intelligence**
- **Phase 11 — Rest-of-season intrinsic model**
- **Phase 12 — In-season product mode, opportunity board, operations, and Release 2 launch**

The ordering is intentional. Phase 10 is an additive extension of the existing market layer and should ship with minimal model risk. Phase 11 is the new analytical core. Phase 12 exposes the new model safely and completes the seasonal product transition.

---

## 2. Release 2 guardrails

These rules should be treated as architectural constraints, not preferences.

### 2.1 Keep Release 1 reproducible

Do not mutate the meaning of existing V1 artifacts in place.

- `intrinsic-cb-hurdle-v1` remains the frozen preseason intrinsic model.
- Existing draft `fair_rank`, tiers, and V1 MFL arbitrage remain reproducible from the V1 methodology.
- New schemas and methodology versions must be additive/versioned.
- Existing public URLs should continue to work unless a migration is explicitly tested.

### 2.2 Preserve the intrinsic/market firewall

No ADP, ECR, platform ranking, waiver trend, roster percentage, expert rank, or other market signal may enter an intrinsic model.

Market data may only be joined **after** intrinsic values have been produced.

### 2.3 Do not average unlike market signals into an opaque “consensus”

ADP, ECR, roster percentage, add/drop velocity, and trade value describe different behaviors.

If a cross-source consensus is introduced, every component, transformation, weighting rule, timestamp, and version must remain recoverable. The UI must still expose the component sources.

### 2.4 In-season mode is a separate model problem

The preseason model is intentionally anchored before Week 1. Do not make it “in-season” by simply allowing current-week data into a model trained and validated on preseason information.

Create a separately trained and validated rest-of-season model with point-in-time weekly snapshots.

### 2.5 Source access must remain permitted and operationally boring

Do not add an unofficial scrape merely to increase logo count.

Every new source requires:

- permitted use for this public free product;
- stable acquisition path suitable for GitHub Actions;
- recorded schema and source semantics;
- freshness checks;
- identity coverage measurement;
- fail-closed behavior;
- no secret exposed to the frontend.

A source that does not meet those requirements stays disabled.

---

# Phase 10 — Multi-Market Draft Intelligence

## Goal

Turn the Arbitrage Board from **Intrinsic vs MFL** into a market-aware decision surface with **Fantasy Football Calculator (FFC) as the required second production draft-price source**, while preserving MFL as a first-class source and keeping expert consensus distinct from observed draft behavior.

This phase should be deployable independently of Phases 11-12.

Phase 10 is the dedicated post-V1 market-methodology change that ADR-053 and ADR-056 explicitly deferred. Do **not** reopen the question of whether FFC is generally usable: the repository already measured that the API is reachable from GitHub Actions, the publisher permits API use with attribution/restraint, genuine `standard` / `ppr` / `half-ppr` cohorts exist, volume is materially larger than MFL, and per-player standard deviation is available. Re-probe only the facts that can change operationally, especially the current `teams` behavior, schema, volume, freshness/window, and identity coverage.

## Pre-Phase Human Step

These actions have external lead time and should be done before or in parallel with the Phase 10 coding session. **Neither may block FFC + MFL shipping.**

1. **Yahoo:** submit/request official Yahoo Fantasy API access if not already approved. Record the application date/status. Phase 10 may prepare an optional adapter only after official access and redistribution semantics are verified; Release 2 must not wait for approval.
2. **Sleeper:** ask Sleeper for explicit written permission to use the undocumented projections/ADP endpoint/fields for this free public site. The documented Sleeper API remains permitted for its existing roles, but undocumented ADP must not enter production without explicit authorization.

No FFC API key or pre-registration is required. The one human task FFC does require happens *during* the phase: review the generated FFC identity-alias proposal before those aliases are accepted as production identity truth.

---

## 10.1 Freeze the source dispositions before implementation

Use the following source order and disposition unless new primary-source evidence contradicts it.

### 10.1.1 Fantasy Football Calculator — **required production target**

FFC is the first new source to implement. The objective is not another exploratory sweep; it is to productionize the already-verified source safely.

Required Phase 10 actions:

1. Re-run and extend the existing GitHub-runner FFC probe (`scripts/probe_ffc.py` / `.github/workflows/source-probe-ffc.yml`) against the current 2026 API.
2. Verify the current live schemas for `standard`, `ppr`, and `half-ppr`.
3. Verify current source window/freshness, total draft volume, per-player sample/dispersion fields, and once-daily usage guidance.
4. Re-test `teams=` across at least 8/10/12/14-team requests **per player**, not merely at envelope level.
5. If `teams=` is still accepted but ignored, this is **not a blocker**. Record FFC as an exact scoring-format market with league-size unavailable. Never label it “12-team FFC ADP” when the API does not substantiate that claim.
6. If `teams=` now materially differentiates cohorts, capture the new evidence and write a successor ADR rather than silently overturning ADR-056.
7. Preserve FFC's actual aggregation semantics. The previous probe measured a rolling/recent window, while MFL is a season-cumulative aggregate. Store and display those as different source semantics rather than pretending they are interchangeable.
8. Add the required FFC attribution in the appropriate public Data/Methodology surface.
9. Respect the publisher's requested API cadence. A normal production refresh should fetch no more frequently than the documented cadence unless new publisher guidance explicitly permits it.

**Required production semantics if the prior behavior still holds:**

```text
source_id: fantasyfootballcalculator_adp
market_signal_type: adp
scoring_preset: STD | HALF | PPR       # exact
league_size: null                      # not observed / not claimable
cohort_exact_scoring: true
cohort_exact_league_size: false
aggregation_window: rolling/recent     # exact field/version from current probe
market_adp_sd: populated when supplied
```

FFC should be presented to users as the **recent scoring-specific market**, not as a generic replacement for MFL.

### 10.1.2 MyFantasyLeague — **retain production unchanged**

MFL remains the Release 1 market baseline and must not be redefined to make multi-source output easier.

- Preserve the existing adapter, cohort-selection rules, fields, trend retention, and V1 semantics.
- Preserve its season-cumulative aggregation semantics.
- Do not force MFL and FFC into the same apparent cohort precision.
- Existing MFL output given identical inputs must remain semantically unchanged.

The useful contrast is intentional:

```text
FFC = recent / rolling, scoring-specific draft market
MFL = broader season-cumulative draft market with its existing cohort rules
```

### 10.1.3 Yahoo — **optional production candidate; non-blocking**

Yahoo is worth adding because its official Fantasy API exposes draft-analysis fields such as average pick/round and percent drafted. However, current API access requires application/OAuth and therefore has human lead time.

Only enable Yahoo if all of the following are verified:

- official API access is approved and stable from GitHub Actions;
- authentication can be stored entirely in GitHub secrets/backend workflow execution;
- the exact draft-analysis semantics are recorded;
- redistribution/public-display terms permit this use;
- source freshness and identity coverage meet the same quality bar as MFL/FFC.

If approval is not available during Phase 10, record Yahoo as `verify_before_use` / deferred and ship without it.

### 10.1.4 Sleeper — **documented API production; draft ADP disabled pending permission**

Keep the currently documented Sleeper API in production for the roles already verified in Release 1, including player/status/injury context and any permitted trending/add-drop use.

Do **not** infer a global Sleeper ADP from individual public drafts as a Phase 10 shortcut, and do not use `search_rank` as pseudo-ADP.

The undocumented projections endpoint appears to expose scoring-specific ADP fields, but it is not a documented API surface. Treat those fields as:

```text
policy: disabled_pending_written_permission
```

If Sleeper grants explicit permission, perform a fresh schema/semantics probe and write an ADR before enabling it. Otherwise Phase 10 ships without Sleeper ADP.

### 10.1.5 FantasyPros — **benchmark only**

Preserve the existing `benchmark_only` decision.

- A developer/free API or permitted mirror may be useful for internal validation.
- ECR is expert consensus, not ADP, and must never masquerade as draft price.
- Do not publish or redistribute FantasyPros fields unless current terms explicitly permit the exact public use.
- FantasyPros remains outside intrinsic features and outside critical production dependencies.

### 10.1.6 ESPN — **disabled**

Do not build Phase 10 on undocumented ESPN fantasy endpoints. There is no verified sanctioned public production route that meets this project's reliability/policy standard.

### 10.1.7 Other sources

Do not spend the Phase 10 session hunting for logo count after FFC is working. A new source may be considered only if it clearly improves user utility and passes the same policy/schema/freshness/identity gates without delaying the required FFC + MFL deliverable.

### Exit criterion

- FFC and MFL have explicit `production` dispositions with independently preserved semantics.
- Yahoo has a truthful `production` or deferred/`verify_before_use` disposition based on actual approval status.
- Sleeper's documented roles remain separated from any undocumented ADP role.
- FantasyPros remains `benchmark_only` and ESPN remains `disabled` unless new primary-source evidence justifies a new ADR.
- `docs/DATA_SOURCES.md`, `config/source-registry.yaml`, source fixtures, and ADRs reflect measured Phase 10 facts rather than assumptions.

---

## 10.2 Build FFC identity linkage as a reviewed record-linkage workflow

FFC's internal player IDs do not bridge directly to the canonical identifiers already used by the project. Solve this once as a lightweight, testable record-linkage workflow rather than maintaining an ad-hoc hand-typed map.

### Design decision

Use **RapidFuzz normalized Levenshtein similarity** for candidate generation. Do not add a heavyweight pandas/entity-resolution framework for ~300 football players. The desired workflow is:

```text
FFC row
  -> normalize source fields
  -> block candidate pool by exact fantasy position
  -> score canonical name candidates with normalized Levenshtein similarity
  -> retain top candidates + metadata diagnostics
  -> write deterministic review report/proposed alias rows
  -> HUMAN REVIEW
  -> approved FFC id -> canonical player_id alias
  -> production exact-id lookup
```

RapidFuzz is preferred because it provides deterministic, efficient Levenshtein/normalized-similarity primitives and score cutoffs without introducing a broad dataframe linkage dependency.

### Name normalization

Implement one deterministic normalization function, covered by unit tests. At minimum:

- Unicode normalize consistently;
- lowercase/casefold;
- normalize apostrophes, periods, hyphens and repeated whitespace;
- remove punctuation that is non-identifying after normalization;
- normalize common generational suffixes (`Jr`, `Sr`, `II`, `III`, `IV`) consistently rather than allowing punctuation differences to create false misses;
- preserve both original and normalized values in the review output.

Do **not** build a large nickname dictionary as the first solution. If reviewed false negatives demonstrate recurring nickname aliases, add only evidence-backed aliases through the existing human-reviewed identity mechanism.

### Candidate blocking and scoring

1. Exclude team units/DST and non-QB/RB/WR/TE records before linkage.
2. **Block on position exactly.** A QB may never fuzzy-match to an RB/WR/TE merely because a name is similar.
3. Do **not** hard-block on team. Team can be stale around trades/free agency and should be a diagnostic/tie-break signal, not a condition that erases the true candidate.
4. For each FFC player, score all canonical players in the same-position candidate pool using normalized Levenshtein similarity.
5. Persist at least the top two candidates and:

```text
ffc_player_id
ffc_display_name
ffc_position
ffc_team
normalized_ffc_name
candidate_1_player_id
candidate_1_name
candidate_1_score
candidate_1_team
candidate_2_player_id
candidate_2_name
candidate_2_score
score_margin
team_agrees
review_status
```

6. The implementation may use initial review bands such as `>= 0.92` top-score and `>= 0.08` margin to classify a row as `high_confidence_candidate`, but **thresholds are review prioritization only**. Calibrate/freeze them against the reviewed FFC population before documenting them as methodology.
7. Exact normalized-name + position matches should be marked clearly and sorted first for review, but they still do not bypass the identity contract when FFC has no authoritative bridge.

### Fail-closed rule — non-negotiable

**Fuzzy matching never directly resolves a production player.** It proposes a match for review.

This preserves ADR-019's identity philosophy: names are evidence/diagnostics, not an authoritative bridge. Production FFC capture resolves only through an approved mapping keyed by stable FFC player ID. If an FFC ID is unknown or its alias is not approved, retain the source row and reason in evidence/history, exclude it from public arbitrage, and surface it in the review queue.

### Human review workflow

The coding agent should generate a deterministic initial review artifact for the full live FFC QB/RB/WR/TE population and a proposed alias patch. The human reviewer should be able to approve the obvious batch quickly and focus attention on low-score/small-margin/collision rows.

After initial seeding, daily capture should produce only the small delta of new/changed FFC IDs requiring review (for example rookies, late signings, or vendor identity changes).

### Required tests

Build a compact gold fixture containing difficult cases, including:

- punctuation/apostrophe/hyphen variants;
- `Jr.` / `III` suffix differences;
- exact same-position name matches;
- similar names within the same position;
- team changes/stale team labels;
- rookies/new players;
- duplicate or near-duplicate canonical names;
- malformed/missing position;
- intentionally ambiguous rows;
- a player for whom the correct candidate is second under naive name-only matching.

Tests must prove:

- deterministic output/order;
- no cross-position candidate can resolve;
- ambiguous/tied candidates fail closed;
- unknown IDs fail closed;
- normalization does not collapse two known distinct players into an accepted alias;
- approved aliases resolve exactly on later runs without fuzzy scoring;
- the candidate generator has measured top-1 and top-k recall against the reviewed live/gold set;
- no fuzzy score, however high, bypasses the approved-alias gate.

### Exit criterion

The live FFC population produces a reproducible review report; the approved alias file covers the declared production threshold; unresolved records are counted and fail closed; and subsequent FFC ingestion resolves through exact approved IDs rather than re-fuzzy-matching the whole market every run.

---

## 10.3 Generalize the market quote contract without erasing source semantics

Refactor the market pipeline so source-specific adapters normalize into one versioned quote contract while preserving the facts needed to understand why MFL and FFC differ.

At minimum preserve:

```text
source_id
market_signal_type        # adp | rank | ecr | other declared type
snapshot_at_utc
source_as_of_utc
season
cohort_id
scoring_preset|null
league_size|null
aggregation_window_type
aggregation_window_days|null
player_id
market_adp|null
market_rank|null
sample_size|null
market_adp_sd|null
market_low|null
market_high|null
quality_flags[]
```

Rules:

- An ECR row must never masquerade as ADP.
- A platform/source ADP must retain source identity.
- Exact vs unavailable/approximate scoring and league-size cohort dimensions remain explicit.
- For FFC, if `teams=` remains ignored, `league_size` is unknown/not claimable rather than silently copied from the selected intrinsic preset.
- FFC standard deviation is a real dispersion field; MFL min/max are extreme order statistics and must not be relabeled as standard deviation.
- Aggregation window semantics must remain explicit enough that a user can distinguish FFC recent/rolling from MFL cumulative.
- Player identity failures remain retained in private/history evidence and excluded from public arbitrage output.
- Historical snapshots continue append-only retention using a versioned contract, with separate source trees.

### Exit criterion

MFL and FFC can travel adapter → canonical quote → identity → snapshot retention → arbitrage artifact through the same tested interface without source-specific branching in the frontend, while the resulting records still make their different cohort/window/dispersion semantics recoverable.

---

## 10.4 Add source-relative arbitrage and cross-market disagreement

For each eligible production ADP source, compute the existing transparent baseline independently:

```text
rank_gap = market_adp - fair_rank
regional_value_gap = ln(market_adp / fair_rank)
```

Do **not** average FFC and MFL before calculating these values.

The same player should legitimately be able to read, for example:

```text
Intrinsic Fair Rank: 42
FFC Recent Half-PPR ADP: 61
MFL Cumulative ADP: 53
FFC rank gap: +19
MFL rank gap: +11
```

Add a cross-market diagnostic layer containing, where available:

```text
market_adp_min
market_adp_max
market_adp_median
market_disagreement_range
cheapest_market_source
most_expensive_market_source
sources_available
```

Because FFC and MFL describe different aggregation windows/populations, `market_adp_median` is a convenience summary only. It must not become the default canonical price unless a separate versioned methodology is frozen first.

Cross-market disagreement is itself useful information and should remain interpretable from the component quotes.

### Exit criterion

The same player has independent MFL and FFC arbitrage values, source semantics are visible, and every cross-market value can be reproduced exactly from the component quotes.

---

## 10.5 Update the draft UI around source choice, not source blending

Add a market selector to the Arbitrage Board. With the required two sources the baseline UI should be:

```text
Market: FFC Recent | MFL Cumulative | Cross-market
```

Add Yahoo only if its official adapter actually passes the production gate. Do not render disabled/benchmark-only sources as selectable public markets.

Recommended behavior:

- default to a clearly labeled production source rather than silently averaging;
- strongly consider **FFC Recent** as the default for draft-week use because it is scoring-specific and responds to the recent market, while preserving MFL as an equally accessible broader/cumulative view;
- remember market selection in URL/query state where practical;
- show source freshness/window beside the selected market;
- show whether the market is scoring-specific and whether league size is actually observed;
- expose benchmark ECR only on internal/diagnostic surfaces unless public redistribution is permitted;
- add a market-disagreement sort/filter in the cross-market view;
- keep the intrinsic Tier Board unchanged.

Player detail should make the distinction explicit:

```text
Intrinsic Fair Rank
FFC Recent ADP
FFC ADP Std Dev
MFL Cumulative ADP
MFL observed min/max
Yahoo ADP (only if enabled)
Cross-market spread
```

Never display `12-team FFC ADP` unless the Phase 10 re-probe proves the team-size parameter genuinely changes the cohort.

---

## Phase 10 quality gates

- Existing V1 intrinsic artifacts are byte-identical given identical inputs/model/build identity.
- Existing MFL outputs remain semantically unchanged.
- FFC current API/schema/terms/cadence behavior has fresh runner evidence.
- FFC `teams=` behavior is re-measured and labeled truthfully; ignored team size is not treated as a release blocker.
- FFC `standard`, `half-ppr`, and `ppr` scoring cohorts are fixture-tested.
- FFC attribution is present where required.
- FFC player-ID linkage uses the reviewed alias gate; fuzzy scores never auto-resolve production identity.
- Record-linkage candidate generation has deterministic tests plus measured top-1/top-k recall on reviewed data.
- Identity coverage and unresolved counts are reported per source.
- FFC and MFL retain independent aggregation-window and dispersion semantics.
- No new market feature appears in the intrinsic feature audit.
- Every new adapter has fixture tests and schema-drift failure tests.
- Frontend works if optional Yahoo/Sleeper secondary integrations are unavailable.
- Last-known-good deployment behavior remains intact.
- Desktop and mobile visual QA completed for all production market modes.

### Phase 10 scope boundaries

Do not build:

- a learned arbitrage model without a valid historical point-in-time target;
- an opaque blended ADP;
- automatic fuzzy identity resolution from player names;
- a scraped/undocumented ESPN source;
- undocumented Sleeper ADP without written authorization;
- roster synchronization;
- an in-season projection model;
- weekly start/sit rankings.

### Phase 10 handoff artifact

Before starting Phase 11, update `SESSION_STATE.md` with:

- accepted sources and their exact semantics;
- FFC probe results, including scoring cohorts, team-size behavior, aggregation window, volume, dispersion, and cadence;
- FFC alias/linkage coverage, unresolved count, review method, candidate recall, and alias-file path;
- Yahoo application/approval status;
- Sleeper ADP permission status;
- rejected/deferred sources and why;
- market contract version;
- source coverage/freshness results;
- UI default/source-selection behavior;
- commands/tests/run IDs proving the exit gate.

---

# Phase 11 — Rest-of-Season Intrinsic Model

## Goal

Build a separately validated model that answers:

> “From the end of the current NFL week, what is this player's distribution of fantasy value over the remaining fantasy season?”

Working model name:

```text
intrinsic-ros-v1
```

The final name may change, but it must remain distinct from the preseason model.

---

## 11.1 Define the point-in-time training grain first

The dataset should be one row per:

```text
season × through_week × player × scoring_preset
```

Example:

```text
2023 | through_week=4 | Player X
features: information available after Week 4
label: fantasy output from Weeks 5 through the configured fantasy horizon
```

The cutoff rule must be explicit and testable. Recommended convention:

> Snapshot immediately after all games/stat corrections for Week N are considered available, predicting Week N+1 onward.

If injury/status sources cannot be reconstructed historically at the same cutoff, they cannot be used as production model inputs merely because current data exists.

### Exit criterion

A historical builder can produce leakage-safe weekly snapshots and paired rest-of-season labels for multiple seasons, with every feature declaring its availability rule.

---

## 11.2 Define ROS targets and horizons

At minimum model:

1. **remaining availability** — games played over the remaining fantasy horizon;
2. **conditional performance** — fantasy points per active remaining game;
3. **remaining season total** — composition of availability × performance.

Preserve the successful V1 hurdle concept if validation supports it; do not assume it must win simply because it won preseason.

The fantasy horizon should remain aligned to the project's existing scoring-horizon definition unless a new rule is explicitly justified.

For each snapshot, persist:

```text
through_week
remaining_horizon_weeks
actual_remaining_games
actual_remaining_points
```

### Exit criterion

Labels reconcile against the existing scoring engine and cannot contain statistics from `through_week` or earlier in the remaining-season target.

---

## 11.3 Engineer in-season feature families

Candidate football-only features should include evidence available through the snapshot cutoff, such as:

- preseason/static biography and draft capital;
- prior-season production and opportunity;
- current-season games played to date;
- current-season fantasy points per game;
- rolling usage/opportunity metrics;
- snaps / route / target / carry / red-zone opportunity where supported by existing sources;
- rolling efficiency metrics;
- team offensive context through the cutoff;
- observed current team/depth information only where historical point-in-time parity is defensible;
- trend/change features using only prior weeks.

Critical design rule:

> “Useful today” is not enough. A feature must be reproducible at equivalent historical cutoffs or be annotation-only.

Current injury/status data should remain annotation-only unless Phase 11 proves a historical, point-in-time injury feature source with adequate coverage.

### Explicit edge-case diagnostics

The Phase 11 report must separately examine:

- rookies vs veterans;
- players returning from long absences;
- players with 0/1/2 current-season games;
- players changing teams or roles;
- QB/RB/WR/TE;
- early-season Weeks 1-3 vs later-season snapshots;
- players with extreme uncertainty;
- high-draft-capital players with poor recent production;
- low-history rookies with strong draft capital.

This is intended to expose the asymmetry observed in Release 1 rather than hide it in pooled metrics.

---

## 11.4 Build chronological evaluation protocol

Never randomly split weekly snapshots across years.

Use chronological, season-blocked validation so snapshots from a validation season never leak into its training set.

Recommended structure:

- development seasons: historical seasons before the final sealed season;
- evaluation by `through_week`, position, scoring preset, rookie/veteran cohort;
- one final sealed season evaluated only after architecture and promotion rules freeze.

Baselines should include at least:

- preseason Release 1 expectation prorated over remaining games;
- current-season points-per-game × simple remaining-games estimate;
- a conservative blend of prior expectation + current production;
- simple position/availability priors for sparse-history players.

Metrics should preserve the Release 1 philosophy:

- MAE / rank correlation;
- top-K retrieval;
- quantile pinball loss;
- P10-P90 / P25-P75 coverage;
- calibration by week and position;
- paired confidence intervals for material model comparisons.

### Promotion rule

Promote a more complex ROS model only if it beats the declared simple baseline on probabilistic quality and does not materially collapse rank quality or a key cohort.

No “it looks better on the website” promotion.

---

## 11.5 Produce ROS value above replacement

Once player remaining-season distributions are validated, reuse the existing simulation/allocation philosophy with an explicitly versioned ROS methodology.

Compute a remaining-season VORP distribution for each supported league preset.

Do not reuse the preseason `fair_rank` field without semantic distinction. Recommended public naming:

```text
ros_fair_rank
ros_expected_vorp
ros_vorp_p25
ros_vorp_p50
ros_vorp_p75
ros_tier
```

The replacement calculation must reflect the same league roster structure, but Phase 11 must decide whether the correct baseline is:

- the best unstarted player in a fresh league allocation; or
- a different explicitly documented ROS replacement interpretation.

Do not silently assume preseason draft opportunity cost and in-season roster replacement are identical concepts.

This decision deserves an ADR and a measured sensitivity test.

---

## 11.6 Add model explainability diagnostics

Release 1 currently cannot answer “exactly why Player A ranked above Player B” from published artifacts.

Phase 11 should add offline per-player feature attribution for diagnostics, ideally separated by model component:

```text
availability_top_positive_contributors[]
availability_top_negative_contributors[]
performance_top_positive_contributors[]
performance_top_negative_contributors[]
```

SHAP or the model library's equivalent may be used offline if deterministic and tested.

This does **not** need to become a giant public explanation UI in Phase 11. The goal is engineering observability and faster detection of pathological rankings.

### Exit criterion

For a representative player, an engineer can trace why the availability and performance components moved without guessing from raw feature values.

---

## Phase 11 quality gates

- Weekly point-in-time leakage audit passes.
- Historical snapshot builder is deterministic.
- Simple ROS baselines are declared before candidate tuning.
- Promotion criteria are frozen before final evaluation.
- Final sealed season is touched once after freeze.
- No current-only data enters training unless historical parity is proven.
- Rookie/veteran and early-season slices are explicitly reported.
- Uncertainty calibration is reported rather than hidden by pooled zero-game rows.
- ROS simulation convergence is measured.
- Tier-boundary stability is measured; unstable boundaries must be represented honestly.
- Per-player attribution diagnostics are available offline.

### Phase 11 scope boundaries

Do not build:

- opponent-specific weekly start/sit recommendations;
- lineup optimization;
- betting/props;
- news-sentiment modeling;
- user-specific rosters;
- market data inside `intrinsic-ros-v1`.

### Phase 11 handoff artifact

Before starting Phase 12, update `SESSION_STATE.md` with:

- ROS cutoff/label rule;
- final feature set and hashes;
- baselines/candidates considered;
- final promotion decision;
- sealed evaluation result;
- model card path;
- simulation/replacement decision;
- known model limitations;
- commands/tests/run IDs proving the exit gate.

---

# Phase 12 — In-Season Product Mode + Opportunity Board + Release 2 Launch

## Goal

Turn the website from a product whose usefulness falls after Week 1 into a season-long decision tool while keeping the interface simple.

Release 2 should have two explicit product modes:

```text
DRAFT
IN-SEASON
```

Mode selection should be deterministic from season state with a manual/user-visible override only if useful.

---

## 12.1 Add season-state orchestration

Create a versioned season-state rule using the NFL schedule rather than hard-coded calendar guesses.

Recommended states:

```text
preseason_draft
regular_season
fantasy_postseason
season_complete
```

The first regular-season kickoff transitions the default product from Draft to In-Season.

The current preseason daily pipeline remains available and reproducible, but it should no longer be presented as current ROS intelligence after the season begins.

### Exit criterion

Given a timestamp and schedule fixture, tests deterministically select the expected product mode around the Week 1 boundary.

---

## 12.2 Build the ROS Tier Board

Reuse the strongest interaction patterns from the existing Tier Board rather than designing an unrelated second site.

The ROS board should expose:

- `ros_fair_rank`;
- position rank;
- ROS tier;
- expected remaining points;
- remaining-games expectation;
- ROS VORP median/interval;
- uncertainty;
- current status annotation;
- “as of Week N” and build freshness.

The interface must clearly say **Rest of Season**. Do not label ROS values simply `Fair Rank` where they can be confused with the preseason fair rank.

Recommended detail panel:

```text
Preseason Fair Rank
Current ROS Fair Rank
Change in intrinsic value
Remaining games distribution
ROS points distribution
Current status
Model-data quality flags
```

The preseason-vs-current intrinsic delta is useful because it shows what football evidence, rather than market opinion, changed the model's view.

---

## 12.3 Replace draft arbitrage with an in-season Opportunity Board

MFL draft ADP should not remain the primary comparison after drafts are complete.

Create a separate `inseason_opportunity` artifact rather than overloading the draft arbitrage record.

Candidate market signals, only where source policy and semantics are verified:

- Sleeper add/drop velocity;
- roster percentage;
- waiver/transaction trends;
- permitted ROS expert benchmark ranks;
- permitted platform trade-value or ROS market indicators;
- cross-market disagreement.

These signals must remain labeled by what they actually mean.

Examples:

```text
ros_fair_rank vs ros_ecr
ros_fair_rank vs roster_rate_rank
ros_fair_rank vs add_velocity_rank
```

Do not subtract ranks from semantically unrelated signals unless the transformation has a defensible interpretation.

A simple first production Opportunity Board may prioritize:

1. ROS intrinsic rank;
2. availability on rosters / roster percentage;
3. add/drop velocity;
4. market/benchmark disagreement;
5. uncertainty/status context.

The release does **not** require a learned in-season arbitrage model.

### Exit criterion

The Opportunity Board identifies actionable in-season discrepancies using at least one verified live market/behavior signal without calling that signal “ADP.”

---

## 12.4 Product navigation and lifecycle UX

Recommended top-level structure:

### Draft mode

- Tier Board
- Arbitrage Board

### In-season mode

- ROS Tier Board
- Opportunity Board

Keep methodology/data pages shared where practical.

Requirements:

- one obvious season-mode indicator;
- no duplicate configuration controls unless semantics differ;
- scoring and league-size presets remain available;
- URLs are stable/shareable;
- CSV exports identify mode/methodology/version;
- build timestamps/source freshness remain visible;
- status annotations continue to be visually distinct from model inputs.

---

## 12.5 Refresh cadence and workflow orchestration

Draft mode can retain the existing daily refresh cadence.

In season, the workflow should support at least:

- a regular daily refresh; and
- an explicit post-week refresh once weekly stat sources are complete.

Do not retrain the ROS model every day.

Recommended split:

```text
capture/refresh sources
build current weekly ROS features
run frozen ROS inference
simulate ROS VORP/tiers
refresh live market/opportunity signals
validate artifacts
build frontend
atomic deploy
```

Retraining remains a separately gated process triggered only when a completed season provides a new training window or a deliberate model-development phase occurs.

### Exit criterion

A failed market source cannot take down the intrinsic ROS board; a failed critical intrinsic input cannot deploy a partially updated ROS board; last-known-good remains intact.

---

## 12.6 Release 2 hardening

Before tagging `v2.0.0`:

- run full Python + frontend CI;
- run artifact schema/semantic validation for draft and in-season artifacts;
- rerun intrinsic market-firewall audits;
- test source failure and stale-source paths;
- test Week 1 state transition with fixtures;
- test optional-source absence;
- test deterministic ROS rebuild;
- verify Pages build/deploy atomically;
- perform desktop/tablet/mobile visual QA;
- perform accessibility pass for new controls;
- verify CSV exports;
- verify no secrets/raw prohibited source payloads entered Git history;
- regenerate relevant model/methodology cards;
- write `docs/releases/v2.0.0.md` only after the release state is proven.

### Phase 12 exit gate / Release 2 definition of done

Release 2 is complete only when all are true:

1. Draft Arbitrage supports multiple independently identifiable production market sources, or Phase 10 has documented why only one additional source passed policy/feasibility.
2. `intrinsic-ros-v1` has passed a frozen chronological evaluation protocol against declared baselines.
3. In-season mode uses current-season football evidence through an explicit point-in-time cutoff.
4. The ROS Tier Board is live and clearly distinct from preseason fair value.
5. At least one verified in-season market/behavior signal powers an Opportunity Board.
6. Draft and in-season modes fail closed and preserve last-known-good deployment.
7. All source provenance, methodology versions, model versions, cutoffs, and build timestamps are visible/recoverable.
8. V1 remains reproducible and the Release 2 changes do not silently redefine its published numbers.
9. Release visual QA and operations evidence are committed.
10. `SESSION_STATE.md`, `TASKS.md`, model cards, ADRs, data-source docs, and release notes reflect the final implementation rather than this planning document.

---

# 3. Recommended coding-agent session split

The three phases are intentionally sized so each can be a dedicated coding-agent session with a clean checkpoint/PR.

## Session A — Phase 10

**Primary objective:** multi-market production plumbing + UI.

Recommended agent prompt scope:

> Implement Phase 10 from `docs/RELEASE2_ROADMAP.md`. Begin by re-reading `PRD.md`, `MASTER_SPEC.md`, `TASKS.md`, `SESSION_STATE.md`, `docs/DATA_SOURCES.md`, `docs/DATA_CONTRACTS.md`, and all market-related ADRs. Verify every candidate source before coding. Preserve all V1 intrinsic semantics. Complete the Phase 10 exit gate, update the canonical repo documentation with measured results, run the full relevant test/QA suite, and stop at a PR-ready checkpoint. Do not begin Phase 11.

## Session B — Phase 11

**Primary objective:** historical weekly ROS dataset + validated `intrinsic-ros-v1` + ROS VORP.

Recommended agent prompt scope:

> Implement Phase 11 from `docs/RELEASE2_ROADMAP.md`. Treat Release 1 and Phase 10 as read-only baselines unless a necessary shared abstraction is proven. Freeze the ROS cutoff, labels, baselines, evaluation protocol, promotion rules, and sealed holdout before candidate tuning. Build the smallest model that passes the declared gates. Add offline per-player attribution diagnostics. Update canonical documentation with measured evidence and stop at a PR-ready checkpoint. Do not build the Phase 12 UI.

## Session C — Phase 12

**Primary objective:** seasonal mode transition + ROS/Opportunity UI + operations hardening + `v2.0.0` readiness.

Recommended agent prompt scope:

> Implement Phase 12 from `docs/RELEASE2_ROADMAP.md`. Consume the frozen Phase 11 ROS artifacts rather than changing the model to fit UI preferences. Build deterministic season-state switching, ROS Tier Board, verified in-season Opportunity Board, refresh/deploy orchestration, failure handling, exports, and full visual/operational QA. Update all canonical docs from measured final behavior. Stop only when the Release 2 definition of done is either fully met or every unmet clause is explicitly documented as a release blocker.

---

# 4. Two-day execution priority

Given the short implementation window, prioritize correctness and a clean seasonal architecture over source count.

Recommended order:

### Day 1

1. Complete Phase 10 source gate quickly.
2. Ship the generalized market contract and second production source if one cleanly passes.
3. Freeze Phase 11 dataset/cutoff/evaluation design before extensive model work.
4. Start historical weekly ROS dataset build and baselines.

### Day 2

1. Finish Phase 11 candidate evaluation and freeze/promote the ROS model.
2. Implement ROS simulation/artifacts.
3. Complete Phase 12 mode/UI wiring using existing visual patterns.
4. Exercise failure paths, visual QA, and production build.

If time becomes constrained before September 9, preserve this priority:

```text
validated ROS Tier Board
    > in-season Opportunity Board
    > second clean ADP source
    > additional market-source count
    > cosmetic expansion
```

A trustworthy ROS board with one good in-season behavioral signal is more valuable than four weakly verified market integrations.

---

# 5. Deferred post-Release-2 candidates

Do not pull these into Release 2 unless the three core phases finish with substantial margin:

- learned draft arbitrage once genuine historical point-in-time market prices exist;
- learned in-season opportunity/surplus model;
- player-to-player correlation in simulation;
- custom league scoring/roster configuration;
- roster import / “my team” mode;
- trade analyzer;
- waiver-budget optimization;
- weekly opponent-aware start/sit model;
- dynasty;
- D/ST and kicker modeling;
- current injury as a model feature unless equivalent historical point-in-time data is established;
- richer public player-level SHAP/explanation UI.

---

# 6. Planning document authority

This file is a **Release 2 implementation brief**, not the long-term source of truth after coding begins.

During each phase, measured decisions should continue to land in the same canonical locations used by Release 1:

- `TASKS.md` — checklist and exit-gate status;
- `SESSION_STATE.md` — current factual checkpoint and handoff state;
- `docs/DECISIONS.md` — architecture/model/source ADRs;
- `docs/DATA_SOURCES.md` — verified source behavior/policy;
- `docs/DATA_CONTRACTS.md` — artifact and internal contract semantics;
- `models/cards/` — promoted model/methodology evidence;
- `docs/experiments/` — evaluation evidence;
- `docs/visual-qa/` — UI review evidence;
- `docs/releases/` — final released state.

Once Release 2 ships, `docs/RELEASE2_ROADMAP.md` should remain as the original plan, while the files above describe what was actually built.