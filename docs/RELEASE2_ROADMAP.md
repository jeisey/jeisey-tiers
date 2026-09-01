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

Turn the Arbitrage Board from **Intrinsic vs MFL** into a market-aware decision surface while preserving MFL as a first-class source and keeping expert consensus distinct from observed draft behavior.

This phase should be deployable independently of Phases 11-12.

## 10.1 Source feasibility and policy gate

Before implementation, create a short evidence record for each candidate source.

Prioritize:

1. **Sleeper** — highest-priority additional production source if a permitted, stable draft-price signal can be derived or retrieved.
2. **MFL** — retain as the existing verified production source.
3. **FantasyPros ECR** — retain as `benchmark_only` unless the current terms explicitly permit public production use for this project.
4. **Yahoo** — production only if an official acquisition path can operate within the static/GitHub Actions architecture and redistribution terms permit it.
5. **ESPN** — production only if a permitted, stable source is verified. Do not rely on undocumented endpoints by default.
6. Any additional source — must pass the same gate; source count alone is not a Release 2 success metric.

Update `docs/DATA_SOURCES.md`, `config/source-registry.yaml`, schema fixtures, and ADRs for every accepted or rejected source.

### Exit criterion

Every investigated source has an explicit `production`, `benchmark_only`, or `disabled` disposition supported by evidence. No source enters production on assumption.

---

## 10.2 Generalize the market contract

Refactor the market pipeline so source-specific adapters normalize into one versioned quote contract without losing source-specific semantics.

At minimum preserve:

```text
source_id
market_signal_type        # adp | rank | ecr | other declared type
snapshot_at_utc
source_as_of_utc
season
cohort_id
player_id
market_adp|null
market_rank|null
sample_size|null
market_low|null
market_high|null
quality_flags[]
```

Rules:

- An ECR row must never masquerade as ADP.
- A platform ADP must retain the platform identity.
- Exact vs approximate scoring/league-size cohorts remain explicit.
- Player identity failures remain retained in the private/history evidence path and excluded from public arbitrage output.
- Historical snapshots continue append-only retention using a versioned contract.

### Exit criterion

At least two production market sources can travel adapter → canonical quote → identity → snapshot retention → arbitrage artifact through the same tested interface, without source-specific branching in the frontend.

---

## 10.3 Add market-relative arbitrage outputs

For each eligible production market source, compute the V1 transparent baseline independently:

```text
rank_gap = market_adp - fair_rank
regional_value_gap = ln(market_adp / fair_rank)
```

Do **not** average source ADPs before calculating these values.

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

Any “consensus market ADP” is optional and must have a documented, versioned method. Median is preferred over mean if a simple summary is needed, but component prices remain primary.

### Exit criterion

The same player can have independent MFL/Sleeper/etc. arbitrage values, and a cross-market disagreement value can be reproduced exactly from the component quotes.

---

## 10.4 Update the draft UI

Add a market selector to the Arbitrage Board:

```text
Market: MFL | Sleeper | ... | Cross-market
```

Recommended behavior:

- default to the best-supported production source rather than silently averaging;
- remember the selection in the URL/query state where practical;
- show source freshness beside the selected market;
- expose ECR/benchmark values separately from platform ADP;
- add a “market disagreement” sort/filter in the cross-market view;
- keep the existing fair-rank and tier views unchanged.

Player detail should make the distinction obvious:

```text
Intrinsic Fair Rank
MFL ADP
Sleeper ADP
Benchmark ECR (if permitted)
Market spread
```

### Phase 10 quality gates

- Existing V1 intrinsic artifacts are byte-identical given identical inputs/model/build identity.
- Existing MFL outputs remain semantically unchanged.
- No new market feature appears in the intrinsic feature audit.
- Every new adapter has fixture tests and schema-drift failure tests.
- Identity coverage and unresolved counts are reported per source.
- Frontend works when one, several, or all optional secondary sources are unavailable.
- Last-known-good deployment behavior remains intact.
- Desktop and mobile visual QA completed.

### Phase 10 scope boundaries

Do not build:

- a learned arbitrage model without a valid historical point-in-time target;
- an opaque blended ADP;
- roster synchronization;
- an in-season projection model;
- weekly start/sit rankings.

### Phase 10 handoff artifact

Before starting Phase 11, update `SESSION_STATE.md` with:

- accepted sources and their exact semantics;
- rejected/deferred sources and why;
- market contract version;
- source coverage/freshness results;
- UI behavior;
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
