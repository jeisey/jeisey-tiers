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

Turn Release 1's **Intrinsic vs MFL** draft comparison into a useful multi-source decision surface with three distinct kinds of external evidence:

1. **Fantasy Football Calculator (FFC)** — required new scoring-specific ADP market;
2. **MyFantasyLeague (MFL)** — existing cumulative ADP market, retained unchanged;
3. **FantasyPros** — approved production reference for both **ADP** and **ECR**, with the two signals kept semantically separate.

Phase 10 should also prepare the documented **Sleeper** player/trending feeds that Phase 12 will use in season, fix the current hard 300-row publication blind spot, and improve the player-detail market-trend presentation.

This phase should be deployable independently of Phases 11-12.

Phase 10 is the dedicated post-V1 market-methodology change that ADR-053 and ADR-056 explicitly deferred. Do **not** reopen the broad question of whether FFC is generally usable: the repository already measured that the API is reachable from GitHub Actions, the publisher permits API use with attribution/restraint, genuine `standard` / `ppr` / `half-ppr` cohorts exist, volume is materially larger than MFL, and per-player standard deviation is available. Re-probe only facts that can change operationally, especially current `teams` behavior, schema, volume, freshness/window, and identity coverage.

There is **no blocking pre-phase human action**. The owner has already provisioned `FANTASYPROS_API_KEY` as a GitHub Actions/environment secret and has reviewed/approved the FantasyPros terms for this free non-commercial project. Human review may be needed after the build for the quarantined tail of FFC identity matches, but it must not stop the coding agent from completing the rest of Phase 10 once the minimum linkage gate below is met.

---

## 10.1 Freeze the source dispositions before implementation

Use the following source disposition unless new primary-source evidence contradicts it. Do not spend Phase 10 rediscovering the same sources from scratch.

### 10.1.1 Fantasy Football Calculator — **required production ADP source**

FFC is the first new draft-price source to implement. The objective is to productionize the already-verified source safely.

Required Phase 10 actions:

1. Re-run and extend the existing GitHub-runner FFC probe (`scripts/probe_ffc.py` / `.github/workflows/source-probe-ffc.yml`) against the current 2026 API.
2. Verify the current live schemas for `standard`, `ppr`, and `half-ppr`.
3. Verify current source window/freshness, total draft volume, per-player sample/dispersion fields, and once-daily usage guidance.
4. Re-test `teams=` across at least 8/10/12/14-team requests **per player**, not merely at envelope level.
5. If `teams=` is still accepted but ignored, this is **not a blocker**. Record FFC as an exact scoring-format market with league size unavailable. Never label it “12-team FFC ADP” when the API does not substantiate that claim.
6. If `teams=` now materially differentiates cohorts, capture the new evidence and write a successor ADR rather than silently overturning ADR-056.
7. Preserve FFC's actual aggregation semantics. The previous probe measured a rolling/recent window, while MFL is a season-cumulative aggregate. Store and display those as different source semantics rather than pretending they are interchangeable.
8. Add required FFC attribution in the existing frontend `Data` view under **“07 Sources and attribution.”**
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

### 10.1.3 FantasyPros — **approved production ADP + ECR reference**

FantasyPros is no longer `benchmark_only` for Release 2. The owner has an approved API key stored in GitHub as:

```text
FANTASYPROS_API_KEY
```

The Phase 10 agent must review and probe the current official v2 documentation, especially the Rankings endpoints, before finalizing the adapter:

```text
https://api.fantasypros.com/public/v2/docs
https://api.fantasypros.com/public/v2/docs#tag/Rankings
```

The intended production use is meaningful, not merely a hidden benchmark:

- ingest **FantasyPros ADP** as its own external draft-price signal;
- ingest **FantasyPros ECR** as expert consensus;
- show both publicly in Tier and Arbitrage tables/cards/player detail;
- compute explicit intrinsic-FV comparisons against both;
- keep ADP and ECR as separate semantics everywhere;
- attribute FantasyPros in the frontend `Data` view under **“07 Sources and attribution.”**

#### API budget and caching — conservative project rule

Treat these as hard application constraints even if the vendor account technically permits more:

```text
FANTASYPROS_DAILY_REQUEST_CAP = 50
FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS = 1
```

The current terms state one request per second and up to 100 requests/day; this project deliberately halves the daily allowance to 50 for operational headroom.

Implementation requirements:

1. **Only the GitHub Actions/backend capture path may call FantasyPros.** The browser must never receive the API key or call the vendor directly.
2. The key must be read from `secrets.FANTASYPROS_API_KEY`; never print, serialize, cache, or expose the secret value.
3. One capture step owns all FantasyPros requests. Downstream model/artifact/frontend jobs read the captured normalized snapshot rather than polling again.
4. Cache/reuse same-day request results by season + endpoint + scoring/position/request shape so reruns do not consume quota unnecessarily.
5. Record request count in the workflow summary and refuse to exceed the internal 50/day cap.
6. Rate-limit sequential vendor requests to at most one per second.
7. Responses are truncated. The source probe must determine the official query/pagination/position strategy required to retrieve the complete relevant player set. Do **not** mistake a truncated response for a complete top-300 market.
8. Prefer the smallest deterministic call plan that gives complete coverage. If position × scoring requests are required, that is acceptable while comfortably below the 50/day cap.
9. Persist the normalized snapshot to the same private source-history architecture used by the other market sources. Do not commit raw authenticated responses to the public repository.
10. If the daily API call fails or quota is unavailable, use last-known-good FantasyPros data with an explicit staleness flag; a noncritical FantasyPros failure must not take down the intrinsic board.

#### FantasyPros public semantics

At minimum preserve separately:

```text
fantasypros_adp
fantasypros_ecr
fantasypros_adp_gap       # FP ADP - intrinsic fair_rank
fantasypros_ecr_gap       # FP ECR - intrinsic fair_rank
fantasypros_scoring
fantasypros_snapshot_at
fantasypros_source_as_of
fantasypros_quality_flags[]
```

`fantasypros_adp_gap` may participate in the draft-market comparison layer. `fantasypros_ecr_gap` is a **consensus comparison**, not an ADP/arbitrage price and must never be silently mixed into an ADP median.

### 10.1.4 Sleeper — **documented API production utility + required in-season behavior source**

Use only Sleeper's documented free read-only API surface. No API token is required. Keep requests comfortably below Sleeper's documented general guidance of **1000 API calls/minute**.

Phase 10 should explicitly support these documented endpoints/roles:

#### Player map

```text
GET https://api.sleeper.app/v1/players/nfl
```

- intended to be called **once per day at most**;
- documentation describes an average payload around **5 MB**;
- cache the player map locally/private build storage and reuse it throughout the day's jobs;
- use it to keep Sleeper player IDs/current metadata aligned with canonical identity;
- do not call it on every page build or every trend request.

The current repo recorded a larger payload in an earlier Phase-0 probe; Phase 10 should measure the current payload and update the source registry rather than treating payload size as a hard schema contract. The **once/day maximum** is the important operational rule.

#### Trending adds and drops

```text
GET https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=<hours>&limit=<n>
GET https://api.sleeper.app/v1/players/nfl/trending/drop?lookback_hours=<hours>&limit=<n>
```

These are the required initial in-season behavior feeds for Release 2.

Phase 10 should:

- implement/verify adapters for both `add` and `drop`;
- retain `player_id`, `count`, lookback window, request timestamp, and any source metadata;
- start append-only snapshots now so Phase 12 inherits real history rather than beginning from zero after kickoff;
- capture them at least on the normal daily refresh; Phase 12 may increase cadence if useful while remaining far below the rate limit;
- add Sleeper attribution wherever trending data is displayed, including the frontend Sources and attribution section;
- keep add/drop counts out of intrinsic features.

Do **not** invent a global Sleeper ADP by crawling individual drafts, and do not use `search_rank` as pseudo-ADP. Phase 10 does not need Sleeper ADP to succeed.

### 10.1.5 ESPN — **disabled**

Do not build Phase 10 on undocumented ESPN fantasy endpoints. There is no verified sanctioned public production route that meets this project's reliability/policy standard.

### 10.1.6 Other sources

Do not spend the Phase 10 session hunting for logo count after FFC/FantasyPros are working. A new source may be considered only if it clearly improves user utility and passes the same policy/schema/freshness/identity gates without delaying the required deliverables.

**Yahoo is intentionally out of Release 2 scope and should not appear in Phase 10 code, source registry planning, UI placeholders, or the Release 2 roadmap.**

### Exit criterion

- FFC, MFL, and FantasyPros have explicit production dispositions with their distinct semantics preserved.
- FantasyPros uses the existing secret safely, stays within the internal 50/day and 1/sec limits, and has a reproducible cached capture path.
- FantasyPros ADP and ECR are both publicly useful while remaining semantically distinct.
- Sleeper's once-daily player-map rule and add/drop trending endpoints are implemented/recorded for Phase 12 use.
- ESPN remains disabled.
- Yahoo is absent from Release 2 scope.
- `docs/DATA_SOURCES.md`, `config/source-registry.yaml`, source fixtures, attribution UI, and ADRs reflect measured Phase 10 facts rather than assumptions.

---

## 10.2 Build FFC identity linkage with a 90% continuation gate

FFC's internal player IDs do not bridge directly to the canonical identifiers already used by the project. Solve this once as a lightweight, testable record-linkage workflow rather than maintaining a large hand-typed map.

### Primary linkage design

Use **RapidFuzz normalized Levenshtein similarity** as the default candidate generator. Do not add a heavyweight dataframe/entity-resolution framework for a few hundred football players.

Desired workflow:

```text
FFC row
  -> normalize source fields
  -> block candidate pool by exact fantasy position
  -> score canonical name candidates with normalized Levenshtein similarity
  -> apply deterministic confidence + ambiguity rules
  -> generate exact FFC id -> canonical player_id aliases for accepted rows
  -> quarantine unresolved/ambiguous rows
  -> continue Phase 10 if coverage gate passes
```

Once a row is accepted into the alias file, normal production capture uses the exact stable FFC ID mapping; it does not fuzzy-match that player again every day.

### Name normalization

Implement one deterministic normalization function with unit tests. At minimum:

- Unicode normalize consistently;
- lowercase/casefold;
- normalize apostrophes, periods, hyphens and repeated whitespace;
- remove punctuation that is non-identifying after normalization;
- normalize common generational suffixes (`Jr`, `Sr`, `II`, `III`, `IV`) consistently;
- preserve original and normalized values in linkage diagnostics.

Do not start with a large nickname dictionary. Add only evidence-backed aliases if reviewed false negatives demonstrate a recurring problem.

### Candidate blocking and scoring

1. Exclude team units/DST and non-QB/RB/WR/TE records before linkage.
2. **Block on position exactly.** A QB may never match an RB/WR/TE simply because the name is similar.
3. Do **not** hard-block on team. Team can be stale around trades/free agency and should be a diagnostic/tie-break signal.
4. Score same-position canonical candidates using normalized Levenshtein similarity.
5. Retain at least the top two candidates and:

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
resolution_method
review_status
```

6. Calibrate the exact score/margin required for an automatic high-confidence proposal against a small hand-checked gold set. Do not choose a permissive threshold merely to hit coverage.
7. Exact normalized-name + position matches may be accepted automatically when collision-free.
8. Fuzzy rows may be accepted automatically only when they clear the frozen high-confidence score/margin rules and no competing identity evidence conflicts.
9. Any collision, tie, cross-source disagreement, malformed position, or low-margin candidate is quarantined rather than guessed.

### Build-continuation threshold

Freeze a simple minimum gate:

```text
FFC_IDENTITY_MIN_COVERAGE = 0.90
```

Coverage is the share of relevant live FFC QB/RB/WR/TE market rows that resolve to a canonical player through an exact/high-confidence accepted alias.

- If linkage coverage is **>= 90%**, the coding agent continues the Phase 10 build without waiting for the human to review the quarantined tail.
- The unresolved <=10% is written to a deterministic quarantine/review artifact for post-build human cleanup.
- If coverage is **< 90%**, linkage is not good enough; improve candidate generation before proceeding to production integration.
- Regardless of overall coverage, unresolved players in the **top 300 by FFC ADP** must be explicitly listed and prioritized because a 90% aggregate rate is not permission to silently miss important drafted players.

This gate exists to keep the coding session moving, not to weaken identity observability. Every accepted row records how it was resolved, and every unresolved row has a reason.

### Optional enrichment: `mayscopeland/ffb_ids`

If RapidFuzz name linkage does not produce an excellent match rate or leaves too many low-margin rows, the coding agent may evaluate the fresh public repository:

```text
https://github.com/mayscopeland/ffb_ids
player_ids.csv
```

As of this planning update, the CSV maps player identities/names across multiple fantasy systems including Sleeper, Yahoo, ESPN, NFFC, CBS, FFToday, NFL.com, FantasyPros, and Footballguys, with a focus on fantasy-relevant 2023-2026 players. **FFC is not one of its direct ID columns.**

Potential use:

```text
FFC name
  -> compare against several known source-name variants from ffb_ids
  -> use a matching source ID already present in our canonical crosswalk when available
  -> strengthen or disambiguate the FFC candidate
```

This is an **optional one-time linkage aid**, not a runtime dependency and not a required Phase 10 source.

Important: the repository currently exposes the CSV publicly but does not present an obvious license file at the repo root. Before copying/vendoring/persisting the dataset into this project, verify reuse permission/licensing. If permission is unclear, do not vendor the CSV; keep the primary RapidFuzz path and quarantine the unresolved tail.

### Required linkage tests

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
- ambiguous/tied candidates quarantine;
- unknown IDs quarantine;
- normalization does not collapse two known distinct players into one alias;
- accepted aliases resolve exactly on subsequent runs without fuzzy scoring;
- candidate top-1/top-k recall is measured against the gold/reviewed set;
- the overall live coverage gate is measured and reported;
- top-300 FFC unresolved players are surfaced separately from the aggregate coverage number.

### Exit criterion

The live FFC population produces a reproducible linkage report, accepted aliases cover at least 90% of relevant FFC market rows, unresolved rows are quarantined with reasons, top-300 unresolved rows are highlighted, and subsequent production ingestion uses exact stored FFC ID aliases rather than re-running fuzzy linkage for already-known players.

---

## 10.3 Generalize draft-market/reference contracts without erasing semantics

Refactor the market pipeline so FFC, MFL, and FantasyPros normalize through shared versioned contracts while preserving what each number means.

For ADP/ECR quote records, preserve at minimum:

```text
source_id
market_signal_type        # adp | ecr
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

- ECR must never masquerade as ADP.
- A source ADP must retain its source identity.
- Cross-market ADP calculations may use FFC ADP, MFL ADP, and FantasyPros ADP; **FantasyPros ECR is excluded from ADP aggregates.**
- Exact vs unavailable/approximate scoring and league-size dimensions remain explicit.
- For FFC, if `teams=` remains ignored, `league_size` is unknown/not claimable rather than copied from the selected intrinsic preset.
- FFC standard deviation is a real dispersion field; MFL min/max are extreme order statistics and must not be relabeled as standard deviation.
- Aggregation-window semantics remain explicit enough to distinguish FFC recent/rolling from MFL cumulative and whatever FantasyPros documents for its ADP/ECR response.
- Player identity failures remain retained in private/history evidence and excluded from public comparisons until resolved.
- Historical snapshots continue append-only retention using source-specific trees.

### Sleeper behavior contract

Do **not** overload an ADP/ECR quote record with waiver behavior. Define a small separate versioned behavior snapshot for Phase 12, such as:

```text
source_id: sleeper
behavior_type: add | drop
snapshot_at_utc
lookback_hours
limit
player_id
count
quality_flags[]
```

Phase 10 should begin retaining these records so in-season history already exists when Phase 12 starts.

### Exit criterion

FFC, MFL, and FantasyPros can travel adapter → canonical identity → retained snapshot → public comparison artifacts through shared tested interfaces without frontend source-specific data plumbing, while Sleeper add/drop behavior remains a separate truthful signal rather than being forced into a draft-price schema.

---

## 10.4 Add source-relative arbitrage and FantasyPros consensus comparisons

For each eligible **ADP** source, compute the existing transparent rank-gap baseline independently:

```text
rank_gap = market_adp - fair_rank
regional_value_gap = ln(market_adp / fair_rank)
```

Required ADP comparisons:

```text
FFC ADP vs intrinsic fair rank
MFL ADP vs intrinsic fair rank
FantasyPros ADP vs intrinsic fair rank
```

Required expert-consensus comparison:

```text
FantasyPros ECR vs intrinsic fair rank
```

The same player should legitimately be able to read, for example:

```text
Intrinsic Fair Rank: 42
FFC Recent Half-PPR ADP: 61       -> +19 model-vs-market gap
MFL Cumulative ADP: 53            -> +11 model-vs-market gap
FantasyPros ADP: 57               -> +15 model-vs-market gap
FantasyPros ECR: 49               -> +7 model-vs-expert-consensus gap
```

Do **not** average ECR into an ADP price.

Add a cross-market **ADP-only** diagnostic layer containing, where available:

```text
market_adp_min
market_adp_max
market_adp_median
market_disagreement_range
cheapest_market_source
most_expensive_market_source
sources_available
```

Because the sources may describe different populations/windows, `market_adp_median` is a convenience summary only. It must not become the default canonical price unless a separate versioned methodology is frozen first.

Cross-market disagreement is itself useful information and should remain reproducible from component quotes.

### Exit criterion

A player can have independent FFC/MFL/FantasyPros ADP gaps plus a separate FantasyPros ECR gap; every public comparison is reconstructable from its component fields; and no consensus rank is mislabeled as observed draft price.

---

## 10.5 Fix the 300-row publication blind spot with a mode-aware surface universe

This is a **Phase 10 release issue**, not a cosmetic nice-to-have.

Current production computes fair rank over the eligible player pool and then applies:

```text
published = board.head(config.board_depth)
```

with a frozen `board_depth = 300`. That means a player can be legitimately present in the intrinsic/model universe but disappear from the public Tier Board, status artifact, and downstream market comparison simply because his fair rank falls below 300.

A current example such as **MarShawn Lloyd** being drafted in roughly the RB20-30 market range while absent from the public 300-player surface is exactly the kind of red flag this design must detect automatically rather than by human screenshot review.

### Architectural rule: separate three concepts

Do not solve this by letting market data change intrinsic fair rank. Separate:

1. **Intrinsic/model universe** — all eligible QB/RB/WR/TE players the football-only model can value. Market-blind and unchanged.
2. **Tier segmentation universe** — the contiguous fair-ranked prefix to which tier segmentation is applied. Versioned and large enough for useful public coverage.
3. **Public surface/relevance universe** — players searchable/displayable in tables/cards/arbitrage because either the intrinsic model or current external evidence says they matter.

Market signals may affect **whether a player is surfaced**, never his intrinsic projection, VORP, fair rank, or tier computation.

### Phase 10 required analysis

Before changing the depth, measure:

- every player's intrinsic fair rank;
- FantasyPros top-300 ADP and top-300 ECR membership;
- FFC top-300 ADP membership;
- MFL top-300 ADP membership where the source has that depth;
- current active-roster/depth context;
- how many market-relevant players currently fall below fair rank 300, 400, 500, 600, etc.;
- artifact size, frontend render cost, and tier stability/performance at candidate expanded depths.

Do not blindly pick `500` because it is round. Pick the smallest simple versioned depth with enough headroom based on the measured market-coverage distribution and frontend/model QA. A likely outcome is `>=500`, but evidence decides the final V2 tier depth.

### Required public-surface invariant

Create a versioned `surface_universe` / relevance-selection rule with machine-readable reasons, for example:

```text
surface_reasons[] =
  intrinsic_top_tier_depth
  market_top300_ffc_adp
  market_top300_fantasypros_adp
  market_top300_fantasypros_ecr
  market_top300_mfl_adp
  current_roster_relevant
  sleeper_trending_add
  sleeper_trending_drop
  current_depth_promotion
```

Not every reason is active in draft mode, but the contract should be reusable by Phase 12.

For Phase 10 draft mode:

- all players inside the chosen V2 tier depth are public;
- any canonical player inside the top 300 of an enabled production ADP/ECR source must be available in public search/detail/arbitrage even if his intrinsic fair rank is worse than the tier depth;
- such an exception may carry `outside_tier_board=true` rather than receiving a fabricated tier;
- arbitrage must operate from the broader intrinsic-value universe, not only the first 300 tier rows;
- status metadata should be available for surfaced players, not only historical `head(300)` members.

### Market-relevance coverage gate

Generate a daily report comparing each source's top 300 against the public surface.

Required gate for **resolved canonical market rows**:

```text
market_top300_surface_coverage = 100%
```

A top-300 player may not silently disappear because his intrinsic fair rank is too low. If a resolved top-300 market player is absent, the build should fail or explicitly quarantine the row with a blocking reason.

Identity-unresolved source rows are measured separately and must not be hidden inside the surface-coverage denominator.

### Tier-depth change rule

If Phase 10 expands tier segmentation beyond the frozen V1 300 rows:

- create a new V2 methodology/config version; do not rewrite V1 evidence;
- rerun tier stability diagnostics at the new depth;
- rerun performance and mobile/desktop visual QA;
- keep tier membership contiguous in fair-rank order;
- never construct a tier from a market-filtered/noncontiguous set.

### In-season compatibility

The same surface mechanism must work when a previously irrelevant player becomes important midseason.

Example:

> RB1 and RB2 on a team are injured; RB3 was previously far outside the draft board but is now the starting back.

Phase 12 must be able to surface that player from current football context and/or Sleeper add velocity without waiting for him to have been preseason top 300. That is why the solution is a broad intrinsic/current-player universe plus mode-aware **surface relevance**, not simply “FantasyPros top 300 only.”

### Exit criterion

- No resolved top-300 FFC/MFL/FantasyPros ADP or FantasyPros ECR player is silently absent from public search/detail/arbitrage.
- The tier depth is measured, versioned, and large enough for current draft utility without breaking tier semantics.
- Market inclusion changes visibility only; intrinsic FV remains market-blind.
- The surface-selection contract is reusable by Phase 12 for Sleeper trends/current role changes.
- A regression test uses a synthetic market-relevant low-intrinsic-rank player to prove the old `head(300)` blind spot cannot recur.

---

## 10.6 Update the draft UI so the new data is actually useful

Phase 10 is not complete if new sources exist only in backend artifacts.

### Market selector

The Arbitrage Board should expose selectable **ADP** markets:

```text
Market: FFC Recent | MFL Cumulative | FantasyPros ADP | Cross-market
```

Do not add ECR as though it were another ADP market. FantasyPros ECR is a separate consensus comparison visible alongside the selected market.

Recommended behavior:

- default to a clearly labeled production source rather than silently averaging;
- strongly consider **FFC Recent** as the default for draft-week use because it is scoring-specific and responds to the recent market, while preserving MFL and FantasyPros ADP as equally accessible alternatives;
- remember market selection in URL/query state where practical;
- show source freshness/window beside the selected market;
- show whether scoring and league size are actually observed;
- add market-disagreement sort/filter in the cross-market view;
- keep the underlying intrinsic value unchanged when the market selector changes.

### FantasyPros is required in both Tiers and Arbitrage

At minimum, both the **Tier** and **Arbitrage** tables/cards must expose:

```text
FantasyPros ECR
FantasyPros ADP
FV vs FantasyPros ECR gap
FV vs FantasyPros ADP gap
```

This may use responsive/optional columns on narrow screens, but the information must be reachable without downloading a CSV.

Player detail should show the complete comparison clearly, for example:

```text
Intrinsic Fair Rank
FFC Recent ADP + dispersion
MFL Cumulative ADP + observed range
FantasyPros ADP
FantasyPros ECR
FV vs each source
Cross-market ADP spread
```

CSV exports should include the FantasyPros fields and explicit source/signal names.

### Attribution

Update `web/src/app/DataView.tsx` section:

```text
07 Sources and attribution
```

with the required FantasyPros attribution and any FFC/Sleeper attribution required by their source terms. Keep this as the canonical public source-attribution surface rather than scattering duplicate legal copy throughout the UI.

### Expanded-board UX

If the V2 tier depth grows beyond 300, preserve the current progressive-disclosure pattern:

- initial view remains fast/readable;
- `Show full board (...)` reflects the new full tier depth;
- search operates across the full public surface, including market-relevant exceptions;
- table row-count labels are truthful;
- mobile performance is remeasured rather than assumed.

---

## 10.7 Replace the player-card Market Trend number with a themed mini trend chart

The current `market_trend` scalar is useful and should remain: it is the existing trailing 7-day negated OLS slope of ADP versus elapsed days, where positive means moving earlier/more expensive.

But the player detail currently exposes that history only as a number such as:

```text
MARKET TREND
-3.11
Moving later (less expensive)
```

Phase 10 should turn that section into a compact visual trend component using the retained source snapshots that already exist.

### Data requirement

Add a small public history series per player/source or a keyed companion artifact, containing only the points needed to draw the chart, for example:

```text
market_source_id
player_id
points[]:
  observed_at
  market_adp
```

Rules:

- generate the series from the retained private snapshot history; **the browser must not call vendors for chart history**;
- default chart window should align with the existing 7-day trend methodology unless evidence supports a modest longer display window;
- retain the scalar `market_trend` for sorting, CSV, accessibility text, and concise summary;
- history is source-specific: switching FFC/MFL/FantasyPros changes the chart to that source's retained ADP series;
- do not draw ECR and ADP on one unlabeled line.

### Visual behavior

Use a minimal sparkline/mini bar-line treatment that fits the existing dark HUD design rather than importing a generic chart package/style.

Requirements:

- compact enough to replace the existing Market Trend value tile on the player card;
- explicit latest ADP and directional summary remain readable;
- lower ADP means **earlier/more expensive**, so orient/invert the chart or label it so an upward visual move intuitively means “moving earlier” rather than accidentally reversing the semantics;
- hover/focus tooltip on desktop with date + ADP; touch-accessible equivalent on mobile if practical;
- use existing semantic/theme tokens rather than introducing a detached color system;
- handle 0/1/2 points gracefully with a truthful “not enough history” state;
- include an accessible text summary for screen readers;
- no axes/grid clutter unless needed to understand the movement.

The Arbitrage table may keep the compact numeric trend column; the mini chart is primarily a **player-detail QoL improvement**.

### Exit criterion

A player with sufficient retained market history shows a source-specific themed mini trend chart plus the existing slope/direction summary, and visual/automated tests prove the chart changes with source selection, handles sparse history, and does not require live vendor calls.

---

## Phase 10 quality gates

- Existing V1 intrinsic artifacts remain reproducible under the frozen V1 methodology.
- Existing MFL semantics remain unchanged.
- FFC current API/schema/terms/cadence behavior has fresh runner evidence.
- FFC `teams=` behavior is re-measured and labeled truthfully; ignored team size is not a release blocker.
- FFC `standard`, `half-ppr`, and `ppr` scoring cohorts are fixture-tested.
- FFC identity coverage is >=90%; unresolved rows are quarantined; top-300 unresolved rows are separately visible.
- Optional `ffb_ids` enrichment is used only if helpful and only after reuse/licensing is acceptable.
- FantasyPros capture uses `FANTASYPROS_API_KEY` only in backend Actions, stays <=50 requests/day and <=1 request/sec, caches responses, and handles truncation explicitly.
- FantasyPros ADP + ECR are visible in Tier and Arbitrage tables/cards/player detail and CSV with distinct labels.
- FantasyPros attribution is present in frontend `Data` → `07 Sources and attribution`.
- Sleeper player map is fetched no more than once/day and cached; add/drop trending adapters are captured/retained with attribution.
- Market ADP cross-source summaries exclude ECR.
- Market quote and Sleeper behavior contracts preserve source semantics.
- Resolved top-300 market/ECR surface coverage is 100% across enabled sources.
- No market source or surface-inclusion rule enters intrinsic features or changes intrinsic fair rank.
- If tier depth changes, V2 tier stability/performance/visual QA is rerun and V1 remains reproducible.
- Every new adapter has fixture tests and schema-drift/failure tests.
- Frontend works when one optional/noncritical external source is stale or temporarily unavailable.
- Market Trend mini chart is source-specific, sparse-history safe, accessible, and theme-consistent.
- Last-known-good deployment behavior remains intact.
- Desktop and mobile visual QA completed for all production market modes and the expanded surface.

### Phase 10 scope boundaries

Do not build:

- a learned arbitrage model without a valid historical point-in-time target;
- an opaque blended ADP/ECR score;
- market-informed intrinsic projections/ranks;
- a scraped/undocumented ESPN source;
- a global Sleeper ADP synthesized from individual drafts;
- roster synchronization/user accounts;
- the Phase 11 in-season projection model;
- weekly start/sit rankings.

### Phase 10 handoff artifact

Before starting Phase 11, update `SESSION_STATE.md` with:

- accepted source dispositions and exact semantics;
- FFC probe results, including scoring cohorts, team-size behavior, aggregation window, volume, dispersion, cadence;
- FFC linkage coverage, threshold, quarantine count, top-300 unresolved count, optional enrichment decision, and alias-file path;
- FantasyPros exact endpoints/request shapes, truncation behavior, daily request budget, cache strategy, captured fields, coverage, and attribution evidence;
- Sleeper player-map payload/cadence measurement and add/drop capture semantics;
- market/reference contract versions;
- selected V2 tier depth and the evidence that chose it;
- market top-300 surface-coverage results and any exceptions;
- UI source-selection behavior and FantasyPros fields;
- market-trend series/chart contract and visual QA evidence;
- source freshness/failure behavior;
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

## 12.3 Build the in-season Opportunity Board around documented Sleeper behavior

MFL/FFC/FantasyPros draft ADP should not remain the primary comparison after drafts are complete.

Create a separate `inseason_opportunity` artifact rather than overloading the draft arbitrage record.

The **required first production behavior signal** is Sleeper's documented trending add/drop feed already captured beginning in Phase 10:

```text
Sleeper adds: player_id + count over declared lookback window
Sleeper drops: player_id + count over declared lookback window
```

The Opportunity Board should use those signals truthfully, for example:

```text
ros_fair_rank
sleeper_add_count_24h
sleeper_drop_count_24h
net_add_interest or separately labeled add/drop measures
current roster/depth/status context
```

Do not pretend add counts are ADP or convert them into draft rank without a documented reason.

Other candidate signals, only where source policy and semantics are verified, may include:

- roster percentage;
- waiver/transaction trends;
- FantasyPros ROS ECR/rank if the approved Rankings API exposes the required ROS view and Phase 12 verifies its semantics;
- permitted platform trade-value or ROS market indicators;
- cross-source disagreement.

Examples of legitimate comparisons include:

```text
ros_fair_rank vs fantasypros_ros_ecr
ros_fair_rank alongside sleeper_add_velocity
ros_fair_rank alongside roster_rate_rank
```

Do not subtract ranks from semantically unrelated count/velocity signals merely because both are numeric.

A simple first production Opportunity Board may prioritize:

1. ROS intrinsic rank/value;
2. Sleeper add/drop behavior;
3. current role/status/depth context;
4. roster availability/percentage where verified;
5. permitted ROS consensus disagreement;
6. uncertainty.

The release does **not** require a learned in-season arbitrage model.

### Surface-universe requirement

Reuse the Phase 10 mode-aware surface-universe architecture. A player who was outside the preseason tier depth must still become discoverable when current evidence makes him relevant.

For example, if a team's RB1 and RB2 are injured and RB3 becomes the starter, current roster/depth context and/or a surge in Sleeper adds should surface him even if his preseason fair rank was 600+ or absent from the visible draft board.

### Exit criterion

The Opportunity Board identifies actionable in-season discrepancies using documented Sleeper add/drop behavior without calling that behavior “ADP,” and market/current-role relevance can surface previously obscure players without altering intrinsic ROS calculations.

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
refresh Sleeper add/drop + other live opportunity signals
validate artifacts
build frontend
atomic deploy
```

Sleeper operational rules remain explicit:

- refresh the full `/players/nfl` player map **no more than once per day** and reuse the cached map;
- trending add/drop endpoints may be refreshed with the in-season opportunity cadence while remaining comfortably under 1000 API calls/minute;
- persist lookback window and snapshot timestamp with every behavior record;
- add/drop capture failure may degrade the Opportunity Board to last-known-good/stale behavior data but must not corrupt the intrinsic ROS board.

Retraining remains a separately gated process triggered only when a completed season provides a new training window or a deliberate model-development phase occurs.

### Exit criterion

A failed market/behavior source cannot take down the intrinsic ROS board; a failed critical intrinsic input cannot deploy a partially updated ROS board; last-known-good remains intact.

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

1. Draft views expose independent FFC, MFL, and FantasyPros ADP comparisons plus FantasyPros ECR without conflating the signal types.
2. The draft public surface no longer silently drops resolved top-300 market/consensus players because of the old 300-row intrinsic publication cut.
3. `intrinsic-ros-v1` has passed a frozen chronological evaluation protocol against declared baselines.
4. In-season mode uses current-season football evidence through an explicit point-in-time cutoff.
5. The ROS Tier Board is live and clearly distinct from preseason fair value.
6. Sleeper documented add/drop behavior powers the first production Opportunity Board and can surface previously obscure players.
7. Draft and in-season modes fail closed and preserve last-known-good deployment.
8. All source provenance, methodology versions, model versions, cutoffs, and build timestamps are visible/recoverable.
9. V1 remains reproducible and Release 2 changes do not silently redefine its published numbers.
10. Release visual QA and operations evidence are committed.
11. `SESSION_STATE.md`, `TASKS.md`, model cards, ADRs, data-source docs, and release notes reflect the final implementation rather than this planning document.

---

# 3. Recommended coding-agent session split

The three phases are intentionally sized so each can be a dedicated coding-agent session with a clean checkpoint/PR.

## Session A — Phase 10

**Primary objective:** multi-market production plumbing + market-relevant surface + UI.

Recommended agent prompt scope:

> Implement Phase 10 from `docs/RELEASE2_ROADMAP.md`. Begin by re-reading `PRD.md`, `MASTER_SPEC.md`, `TASKS.md`, `SESSION_STATE.md`, `docs/DATA_SOURCES.md`, `docs/DATA_CONTRACTS.md`, ADR-053/056 and all identity/market-related ADRs. Treat FFC, FantasyPros and the 300-row publication blind spot as required work, not optional source research. Use `FANTASYPROS_API_KEY` only from GitHub Actions and obey the roadmap's conservative cache/rate budget. Preserve all V1 intrinsic semantics. Complete the Phase 10 exit gate, update canonical repo documentation with measured results, run the full relevant test/QA suite, and stop at a PR-ready checkpoint. Do not begin Phase 11.

## Session B — Phase 11

**Primary objective:** historical weekly ROS dataset + validated `intrinsic-ros-v1` + ROS VORP.

Recommended agent prompt scope:

> Implement Phase 11 from `docs/RELEASE2_ROADMAP.md`. Treat Release 1 and Phase 10 as read-only baselines unless a necessary shared abstraction is proven. Freeze the ROS cutoff, labels, baselines, evaluation protocol, promotion rules, and sealed holdout before candidate tuning. Build the smallest model that passes the declared gates. Add offline per-player attribution diagnostics. Update canonical documentation with measured evidence and stop at a PR-ready checkpoint. Do not build the Phase 12 UI.

## Session C — Phase 12

**Primary objective:** seasonal mode transition + ROS/Opportunity UI + operations hardening + `v2.0.0` readiness.

Recommended agent prompt scope:

> Implement Phase 12 from `docs/RELEASE2_ROADMAP.md`. Consume the frozen Phase 11 ROS artifacts rather than changing the model to fit UI preferences. Reuse Phase 10's broad mode-aware surface universe and retained Sleeper add/drop history. Build deterministic season-state switching, ROS Tier Board, Sleeper-powered Opportunity Board, refresh/deploy orchestration, failure handling, exports, and full visual/operational QA. Update all canonical docs from measured final behavior. Stop only when the Release 2 definition of done is either fully met or every unmet clause is explicitly documented as a release blocker.

---

# 4. Two-day execution priority

Given the short implementation window, prioritize correctness and a clean seasonal architecture over source count.

Recommended order:

### Day 1

1. Complete Phase 10 FFC + FantasyPros adapters/capture and source contracts.
2. Fix the 300-row publication/surface-universe blind spot and prove top-300 market coverage.
3. Wire FantasyPros fields and market-source selector into the current UI; add the player-card market-trend mini chart.
4. Begin retaining Sleeper add/drop snapshots for Phase 12.
5. Freeze Phase 11 dataset/cutoff/evaluation design before extensive model work.
6. Start historical weekly ROS dataset build and baselines.

### Day 2

1. Finish Phase 11 candidate evaluation and freeze/promote the ROS model.
2. Implement ROS simulation/artifacts.
3. Complete Phase 12 mode/UI wiring using existing visual patterns and Sleeper behavior history.
4. Exercise failure paths, visual QA, and production build.

If time becomes constrained before September 9, preserve this priority:

```text
validated ROS Tier Board
    > correct broad player surface / no market-relevant omissions
    > Sleeper-powered in-season Opportunity Board
    > FFC + FantasyPros draft comparison
    > additional cosmetic expansion
```

A trustworthy ROS board and complete relevant player universe are more valuable than adding weakly verified source count.

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