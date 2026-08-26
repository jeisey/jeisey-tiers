# Architecture Decision Records

This file records binding architecture/product decisions. Coding agents should append ADRs for material deviations rather than silently changing the system.

## ADR-001 — Static runtime architecture

**Status:** Accepted

**Decision:** V1 uses precomputed static JSON/CSV rendered by React/Vite and hosted on GitHub Pages. No runtime backend/database.

**Why:** zero recurring infra cost, simple deployment, reproducible builds, sufficient for daily rather than real-time cadence.

**Revisit if:** live draft synchronization, arbitrary custom scoring requiring server computation, user accounts, or source licensing makes browser artifact delivery impractical.

---

## ADR-002 — Intrinsic value is market-independent

**Status:** Accepted

**Decision:** ADP, ECR, expert ranks, FantasyCalc market values, and other crowd price signals are forbidden intrinsic-model inputs.

**Why:** preserves independent value estimate and makes arbitrage meaningful rather than circular.

**Revisit if:** never for the intrinsic model. A separate hybrid/consensus product could be added under a different name later.

---

## ADR-003 — Arbitrage may launch in baseline mode

**Status:** Accepted

**Decision:** If Phase-0 historical free ADP coverage is insufficient for leakage-safe ML training/holdouts, ship deterministic market-gap arbitrage and accumulate daily history. Do not fabricate or overclaim an ML model.

**Why:** a transparent baseline is more useful and scientifically honest than a learned model trained on weak/non-point-in-time data.

---

## ADR-004 — Time-aware evaluation only

**Status:** Accepted

**Decision:** player-season models use rolling chronological folds. Random train/test split across seasons is prohibited.

**Why:** production is future-season forecasting and many features/source schemas drift over time.

---

## ADR-005 — Canonical ID joins; no name-only production joins

**Status:** Accepted

**Decision:** GSIS/crosswalk IDs drive joins. Name matching can only propose resolver candidates and must fail closed when ambiguous.

**Why:** player names/suffixes/team changes cause silent corruption.

---

## ADR-006 — Public market history must be retained

**Status:** Accepted

**Decision:** daily market snapshots are persisted in a durable versioned mechanism separate from transient Actions artifacts.

**Why:** point-in-time ADP is core future training data and may not be reconstructable.

---

## ADR-007 — Baseline-first model promotion

**Status:** Accepted

**Decision:** retain explicit naive/simple baselines and promote complexity only after rolling holdout improvement.

**Why:** prevents sophisticated but unvalidated modeling and keeps claims measurable.

---

## ADR-008 — Tables are canonical UX truth surface

**Status:** Accepted

**Decision:** build typed data tables before/alongside bespoke charts; charts must agree with table/artifact values.

**Why:** supports draft-day utility, accessibility, export, and visual QA.

---

## ADR-009 — Phase-0 source verification runs on a GitHub-hosted runner

**Status:** Accepted (2026-08-17)

**Decision:** the reproducible source probe (`scripts/source_probe.py`) is executed on a GitHub-hosted runner via `.github/workflows/source-probe.yml`, and the runner commits its report to the working branch. A probe status of `blocked_egress` means the *execution environment* refused the connection and is never evidence about the source.

**Why:** the development sandbox used for Phase 0 sits behind an egress policy that answers `403` to `CONNECT` for `api.myfantasyleague.com`, `api.sleeper.app`, `fantasycalc.com`, `docs.sleeper.com` and others, while permitting PyPI and the nflverse release hosts. Verification is impossible there by construction. A GitHub runner has open egress *and* is the environment the production workflows will run in, so evidence gathered there describes the environment that actually matters.

**Consequences:** any future source verification must be run through this workflow (or another unrestricted environment) rather than trusted from a local run; a local run is still useful as a fast syntax/logic check.

**Revisit if:** the project acquires a development environment with unrestricted egress, or GitHub Actions stops being the production execution environment.

---

## ADR-010 — Arbitrage V1 ships in deterministic baseline mode

**Status:** Accepted (2026-08-17). Confirms ADR-003 with evidence.

**Decision:** `arbitrage_ml_historical_feasible = false`. V1 computes the transparent fair-rank-vs-ADP baseline and labels it a baseline. No learned surplus model, no `expected_surplus_vorp`, no `p_positive_surplus` in public artifacts.

**Why:** MFL's ADP export carries seven usable historical seasons (362–445 priced players each), so volume is not the problem. The problem is timing: the export returns a season-long aggregate recomputed at request time, and the day-window filter is ignored — `DAYS=30` against 2019 returned exactly the unfiltered result (445 rows, `totalDrafts=15850`). A historical "market cost" therefore includes drafts held after the season's outcomes were partly known, which would contaminate the very feature a learned arbitrage model exists to exploit. Draft-type filters (`IS_MOCK`, `IS_KEEPER`) do work historically but say nothing about when a price was set.

**Revisit when:** at least three draft seasons of our own append-only point-in-time snapshots exist (ADR-006), at which point an honest out-of-time promotion gate becomes possible. Until then, snapshot retention is the highest-value arbitrage work in the repository.

---

## ADR-011 — Current player status comes from nflverse rosters plus Sleeper, not nflverse injuries

**Status:** Accepted (2026-08-17)

**Decision:** current-state status for inference is assembled from `load_rosters(target_season).status` / `depth_chart_position`, the timestamped depth-chart snapshots (2025+), and the Sleeper player map's `status` / `injury_status` / `injury_body_part` / `practice_participation` fields. `load_injuries` is used for historical feature work only, never as a current-state feed.

**Why:** `load_injuries` returns weekly in-season injury reports (weeks 1–22) and the installed loader rejects seasons after 2025. There is consequently **no** nflverse injury report available at a preseason draft anchor in any season, which is a different and larger gap than the "feed died after 2024" assumption in the original spec. Sleeper publishes preseason status/injury fields and is verified reachable; nflverse rosters carry `status` for every current player.

**Consequences:** Sleeper becomes an `important` (not merely optional) current-state dependency, and its non-commercial terms therefore bind the deployment (see ADR-013's non-commercial note and `docs/SECURITY_LICENSE.md` section 10). Joins go nflverse → Sleeper on `sleeper_id`, because Sleeper's own `gsis_id` coverage is only 31.9%.

---

## ADR-012 — Market cohorts are approximate and must be labelled as such

**Status:** Accepted (2026-08-17)

**Decision:** market snapshots are sourced from the widest reliable MFL cohort rather than one request per scoring × league-size preset. Each serialized market/arbitrage row records the filters actually used in `source_format_detail` and carries an explicit `cohort_approximate` entry in `quality_flags` whenever the row's preset is not an exact match for the requested cohort. The UI must not imply preset-specific ADP that the source cannot support.

**Why:** MFL cohort filters work individually (`IS_PPR=1` → 370 rows, `FCOUNT=12` → 356, `FCOUNT=14` → 242) but their intersections collapse: `IS_PPR=0&FCOUNT=10` returned **2** priced players on 2026-08-17. Nine exact preset cohorts cannot be populated from this source, and silently serving a two-player cohort would be worse than serving a labelled approximation. Fabricating nine distinct cohorts from one aggregate without labelling would be a truthfulness failure.

**Consequences:** Phase 5 owns the implementation; `schemas/market_snapshot.schema.json` needs no structural change because `quality_flags` and `source_format_detail` already exist. Arbitrage confidence/data-sufficiency flags must reflect cohort approximation, and cohort mix should be re-measured closer to peak draft season, when thin cohorts may fill in.

**Amendment (2026-08-18, project owner).** The ADR stands unchanged and Phase 1 must not attempt to solve thin scoring x league-size cohorts. Cohort coverage is instead a required first step of Phase 5: re-run the cohort measurement before implementing the market adapter, because the 2026-08-17 counts were taken with only 410 aggregated drafts and peak-draft-season samples may materially improve them. Until that measurement produces stronger evidence, the intended behaviour is unchanged - use the widest reliable cohort, record the filters actually sent, flag approximate cohorts explicitly, and never present an approximate cohort as exact preset-specific ADP.

---

## ADR-013 — FantasyCalc is disabled for V1

**Status:** Accepted (2026-08-17)

**Decision:** no FantasyCalc access of any kind in V1 — not as a production source, not as a secondary signal. The probe reads only the published terms page, never data.

**Why:** `docs/DATA_SOURCES.md` section 7 permits use only if a *documented, permitted* retrieval mechanism is confirmed. No published CSV/download or documented public API was found, and the terms page serves 113,878 bytes of client-rendered HTML with no terms text in the markup, so the policy cannot be verified programmatically. Reachability of an undocumented endpoint is explicitly not sanction. A permissive `robots.txt` is not a licence.

**Revisit if:** FantasyCalc publishes a documented reuse mechanism, or a human records a reading of the current terms plus written permission where required. The arbitrage path does not depend on this source.

---

## ADR-014 — FantasyPros-derived ECR is benchmark-only (originally: disabled pending a human terms review)

**Status:** Accepted (2026-08-17), **amended 2026-08-18 — the terms review is complete and the source is `benchmark_only`.** The original decision below is retained as the record of why the gate existed; the amendment at the end of this entry is the live policy.

**Decision:** `load_ff_rankings` is not used, even for internal benchmarking, until a human reads the current FantasyPros terms and records a decision. Consensus comparison for V1 uses the verified public MFL ADP and the declared naive baselines. No ECR-derived value, and no metric computed from ECR, appears in any public artifact.

**Why:** `docs/DATA_SOURCES.md` section 8 says to disable the benchmark when terms are unclear. They are: the dynastyprocess mirror that distributes the data publishes no licence or terms statement, and the FantasyPros terms page serves 215,237 bytes of client-rendered HTML with no terms text in the markup. Convenient access through nflverse tooling does not transfer rights.

**Consequences:** the PRD's "beats consensus" comparison (section 12.4) is scoped to market ADP for V1, which is legitimate because ADP is itself a crowd-expectation baseline. Any future claim about beating expert consensus requires this ADR to be revisited first. Note the probe already suppresses rows from this source so nothing benchmark-only can leak into the report or fixtures.

### Amendment (2026-08-18) - human terms review completed; benchmark-only use approved

**Status:** Amended. The "disabled pending human terms review" state above is superseded; the rest of the reasoning is retained as the record of why the gate existed.

**Decision:** the project owner has manually reviewed the current FantasyPros terms and approves use for this non-commercial project. `fantasypros_ecr_via_dynastyprocess` moves from `disabled` to **`benchmark_only`**. `load_ff_rankings(type="draft")` may be used as an internal comparison benchmark where useful.

**Invariants that do not change.** The amendment widens exactly one thing - internal benchmark use - and nothing else:

- FantasyPros/ECR remains a **forbidden intrinsic-model feature** (ADR-002).
- It must not influence DraftValue inputs: not the projection, not the Monte Carlo simulation, not replacement/VORP, not tier segmentation.
- It is **not** a critical production dependency. A build must succeed with the source absent, and no public page may require it to render.
- **No redistribution.** Raw FantasyPros ranking data must not appear in any public artifact unless the documented terms clearly permit that exact redistribution. Derived aggregate metrics may be published only if that publication is itself permitted; when in doubt, keep the benchmark internal.
- The project's non-commercial constraint remains binding and documented (`docs/SECURITY_LICENSE.md` section 10).

**Consequences:** `forbidden_roles` in the registry keeps `intrinsic_feature`, `critical_production_dependency` and `public_artifact_field`, drops `internal_benchmark_until_reviewed`, and gains `draftvalue_input` and `public_redistribution` so the prohibition is machine-checkable. The probe's benchmark-row suppression stays in place - approval to compare is not approval to republish. The PRD section 12.4 consensus comparison may now include ECR internally; any *published* claim about beating expert consensus still needs the redistribution question answered first.

**Revisit if:** FantasyPros terms change, the deployment stops being non-commercial, or a published metric would require redistributing the underlying ranking data.

---

## ADR-015 — Depth charts have two schemas; historical anchor depth is not directly available

**Status:** Accepted (2026-08-17)

**Decision:** the depth-chart adapter normalises two upstream formats behind one internal contract: the pre-2025 weekly format (`season/club_code/week/depth_team/depth_position`) and the 2025-onward timestamped snapshot format (`dt/team/pos_abb/pos_rank/pos_slot`). Point-in-time anchor depth is taken as the latest snapshot with `dt <= anchor` for 2025+. For 2024 and earlier, anchor depth may **not** be taken from the week-1 depth chart without an explicit, documented leakage caveat; the default is to derive anchor depth context from prior-season usage and roster status instead.

**Why:** the upstream source changed at 2025. Row counts show it plainly: 2024 → 37,312 weekly rows, 2025 → 554,215 snapshot rows across 221 timestamps, 2026 → 442,872 across 150 timestamps beginning 2026-03-22. Pre-2025 data starts at week 1 with no preseason observation, and week 1 is published after final roster cuts and after a typical late-August draft, so treating it as draft-time information leaks.

**Consequences:** Phase 2 must record the anchor-depth derivation per season era in the feature dictionary, and a leakage test must assert that no pre-2025 training row consumes a depth observation dated after its anchor. Current-season inference is unaffected and in fact better served, because daily snapshots give an exact anchor.

---

## ADR-016 — Repository stays private through Phase 6; visibility is a Phase-7 decision

**Status:** Accepted (2026-08-18, project owner)

**Decision:** `jeisey/jeisey-tiers` remains **private**. No phase between 1 and 6 may change repository visibility or take a dependency on the repository being public. The public-vs-private question is deferred to Phase 7, when GitHub Pages and the production workflows are actually implemented, and must be answered before that phase can exit.

**Why:** the open question recorded after Phase 0 was whether `docs/OPERATIONS.md` section 3 (free standard runners and Pages for public repositories) still holds. It does not need to hold yet: Phases 1–6 need only CI on the current plan's minute budget and a local `npm run build`. Deciding now would either force premature disclosure or bake a hosting assumption into code that has not been written. Deferring costs nothing as long as nothing in Phases 1–6 assumes publicity.

**Consequences:** Phase-1 CI is written to run on a private repository (no `pull_request_target`, no Pages permissions, no assumption of unlimited minutes). Phase 7 must choose between making the repository public and accepting the Actions-minutes/Pages terms for a private repository, and must record that choice as an ADR amendment before its exit gate. The Phase-0 observation in `docs/OPERATIONS.md` section 3 stays, now pointing here.

**Revisit at:** Phase 7 (mandatory), or earlier if a Phase 1–6 deliverable turns out to require a public repository.

### Amendment (2026-08-21) — the Phase-7 intent is settled; the Phase-6 constraint is unchanged

**Status:** Amended. The deferral above still binds through Phase 6; what changes is that the question it deferred now has an answer waiting for it.

**Decision (project owner).** The V1 deployment target is a **public `jeisey/jeisey-tiers` repository serving a public GitHub Pages project site**, built and deployed by standard GitHub-hosted Actions. There is no external paid web host. A custom domain is optional future work and is not required for V1.

**What does not change.** The repository stays **private for the whole of Phase 6**. Phase 6 did not make it public, did not configure Pages, and did not add deploy permissions. The first action of Phase 7 is to make the repository public; nothing before that may assume publicity.

**What Phase 6 did instead.** It removed the discovery risk from that first action by proving the project Pages base path now: the frontend builds and is tested under both `/` and `/jeisey-tiers/`, and an end-to-end test asserts that assets, artifacts, CSV links, query state and reload all resolve under the base path with no absolute `/data/...` assumption surviving (`docs/ARCHITECTURE.md` section 11).

**Consequences for Phase 7.** Two obligations follow from the visibility change rather than from the deploy itself. The `market-data` branch holds retained vendor payloads that are a private research cache today; making the repository public turns that into publication, so the exclusion recorded in ADR-038 and `docs/SECURITY_LICENSE.md` section 10 becomes part of the visibility decision rather than an implementation detail. And Sleeper's non-commercial terms bind what the site publishes (`player_status.json` carries its fields), so the free, ad-free, non-commercial character of the deployment is a licence condition, not a preference.

**Revisit if:** the deployment stops being free and non-commercial, or the retained-capture exclusion cannot be honoured on a public repository.

---

## ADR-017 — MFL client identity comes from environment secrets; the public ADP export stays unauthenticated

**Status:** Accepted (2026-08-18, project owner). Closes the Phase-0 open action in ADR-010/`docs/DATA_SOURCES.md` 13.5.

**Decision:** the project owner has provisioned an MFL developer client and stored its configuration as GitHub repository secrets exposed to workflows as the environment variables `MFL_API_CLIENT_NAME`, `MFL_API_USERNAME`, `MFL_API_PASSWORD` and `MFL_API_USER_AGENT`. The MFL adapter configuration reads those **names** from the environment. Two rules bind the implementation:

1. **The public ADP export is not authenticated.** The Phase-0 evidence that `TYPE=adp&JSON=1` needs no credentials remains valid, so the ADP path sends the registered `User-Agent` and nothing else. It must never attach `USERNAME`, `PASSWORD`, `APIKEY` or an `Authorization` header, and it must never require a credential to be present in order to run.
2. **Secret values are never printed, logged, committed, serialized, or embedded in a cache key or URL query.** Configuration objects expose only whether a value is present and which environment variable it came from; their `repr` is redacted. Only `MFL_API_USER_AGENT` is transmitted, and only as a request header.

Username/password exist for MFL's authenticated league endpoints, which V1 does not call. They are configured, not used.

**Why:** MFL's published rules ask clients to send the User-Agent chosen during client registration, and that was the one documented obligation Phase 0 could not satisfy. It is now satisfiable. Coupling the *public* ADP adapter to login credentials would be a self-inflicted failure mode: a missing secret would break a path that provably does not need one, and it would put credentials on a code path that has no use for them. `docs/SECURITY_LICENSE.md` section 2 already requires adapters to read secrets from the environment and to fail clearly rather than leak.

**Consequences:** `config/source-registry.yaml` records the environment-variable names (never values) under `myfantasyleague_adp.client_settings`. When `MFL_API_USER_AGENT` is absent — local development, forked PR CI, any offline run — the adapter falls back to the descriptive contact User-Agent used by the Phase-0 probe and records a `unregistered_user_agent` warning rather than failing. Normal Phase-1 tests and the fixture pipeline remain network-free and must not read these variables at all. A unit test asserts that no credential parameter or header appears on the ADP request and that redaction holds.

**Revisit if:** MFL begins requiring authentication for the ADP export, or V1 gains a genuine need for an authenticated league endpoint.

---

## ADR-018 — Historical anchor depth: point-in-time for 2025+, prior-season role proxy before that

**Status:** Accepted (2026-08-18, project owner). Resolves the ADR-015 open question. **Phase-2 contract; not implemented in Phase 1.**

**Decision:** anchor depth context is derived by season era, and the three cases are distinguishable in the feature dictionary rather than silently merged.

**2025 and later** — use the latest timestamped depth-chart observation satisfying `depth_snapshot_time <= draft_anchor_time`. This is a genuine point-in-time observation.

**2024 and earlier** — **do not** use week-1 depth charts as a preseason observation, with or without a caveat. For veterans, derive a prior-season role/usage proxy from information genuinely available before the target-season anchor: prior-season snap share, opportunity share, starts and games started, target/carry share, and comparable lagged role indicators. For rookies and players with no usable prior-season history, depth-derived prior-role features stay **missing/not-applicable** with explicit missingness and rookie indicators; their preseason role signal comes from legitimately available features instead — draft capital, roster and team context, athletic measures.

The Phase-2 feature dictionary must distinguish three states explicitly:

- `depth_observed_at_anchor` — an actual point-in-time depth observation (2025+);
- `prior_season_role_proxy` — a lagged usage-derived role estimate (pre-2025 veterans);
- `depth_unavailable` — no depth context at all (pre-2025 rookies and players without prior-season history).

**Why:** ADR-015 established that pre-2025 depth charts begin at week 1, which is published after final roster cuts and after a typical late-August draft. A week-1 proxy therefore leaks post-anchor information into the exact feature a preseason model is supposed to earn. A documented caveat does not remove the leak — it only labels it — and the model would still be trained on information it will never have in production. Prior-season usage is weaker but honest, and it is available at any anchor. Encoding "no signal" as missingness rather than imputing a plausible depth rank keeps the estimator's missing-value path truthful and makes the rookie case visible in slices.

**Consequences:** Phase 2 must ship a leakage test proving that **no** pre-2025 training row consumes a week-1 or otherwise post-anchor depth observation, alongside the general `feature_available_at <= anchor_at` test. Feature coverage will be materially lower for pre-2025 rookies; that is expected and must be reported in the data-quality report by season and position rather than patched over. Model cards must state which era supplied each row's depth context, because a metric slice that mixes point-in-time depth with a usage proxy is not comparing like with like.

**Revisit if:** a licensed or archived preseason depth source for pre-2025 seasons is found and verified, in which case the proxy can be replaced by a true observation for those rows.

---

## ADR-019 — Canonical player identity: namespaced IDs, two independent bridges, fail closed

**Status:** Accepted (2026-08-18). Implements ADR-005 with the Phase-0 measurements.

**Decision:** the canonical internal key is `player_id`, a namespaced string. `gsis:<gsis_id>` whenever a GSIS id exists; otherwise a deterministic namespaced external id (`espn:<id>`, `mfl:<id>`, `sleeper:<id>`) chosen by a fixed namespace precedence. Names never form a key. Team-defence units live in their own `dst:<team>` namespace and are structurally barred from QB/RB/WR/TE identity.

Resolution rules:

- **Market (MFL) → canonical** resolves through two independent bridges: the nflverse-native `espn_id` bridge (primary, because `load_rosters` is nflverse's own data) and the `mfl_id` → `load_ff_playerids()` bridge (secondary, because it exists only in the dynastyprocess mirror, which publishes no licence). Agreement accepts; primary-only accepts; secondary-only accepts with a `secondary_bridge_only` flag; **disagreement fails closed as `ambiguous`**.
- **nflverse → Sleeper** joins on `sleeper_id` carried by nflverse rosters, never on Sleeper's own `gsis_id` (31.9% coverage). Sleeper's `gsis_id`, when present and well formed, is used only as a cross-check; a mismatch fails the record closed.
- **All external ids are trimmed and format-validated** before use. A malformed id resolves nothing through that bridge; it never falls through to a looser strategy.
- **Name matching never resolves a production record.** The resolver may emit name candidates as diagnostics, and a curated, human-reviewed alias file may map a specific external id to a specific canonical id (`resolved_reviewed_alias`). Neither is automatic.
- A crosswalk index key that maps to more than one canonical player is poisoned: every lookup through it fails closed rather than picking a winner.

**Why:** Phase 0 measured 287/287 priced QB/RB/WR/TE resolving by id alone, with 331 rows resolving on both bridges and **zero** disagreements. That makes a strict, id-only policy achievable rather than aspirational, and it makes disagreement rare enough that failing closed on it costs almost nothing while catching precisely the silent-corruption class ADR-005 exists to prevent. The whitespace-bearing Sleeper ids observed in Phase 0 (`" 00-0035057"`) show that hygiene has to be enforced in code, not assumed.

**Consequences:** unresolved and ambiguous records are excluded from model and public layers and are reported as diagnostics with a machine-readable reason. Non-player entities (MFL `position="Def"`/`TMWR` rows) are classified as such rather than counted as identity failures. Identity regression fixtures are required for every collision bug (AGENTS.md section 6), and Phase 1 ships deliberate ambiguous fixtures proving the fail-closed path.

---

## ADR-020 — Public artifacts use the bundled shape (Shape A) for V1

**Status:** Accepted (2026-08-18)

**Decision:** the build emits `tiers.json`, `tiers.csv`, `arbitrage.json`, `arbitrage.csv` and `build_metadata.json`, each JSON file being an envelope `{schema_version, build_id, generated_at_utc, record_count, records: [...]}` whose records carry their own `league_preset_id` and `scoring_preset`. This is `docs/ARCHITECTURE.md` Shape A. Per-preset partitioning (Shape B) is deferred until a measured payload justifies it.

**Why:** ARCHITECTURE section 8 says to choose after measuring browser payload, and there is nothing to measure yet. One file per product keeps the frontend loader, the CSV export path and the schema validator simple, and a preset switch becomes a client-side filter rather than a fetch. The envelope carries the schema version outside the records so a frontend can reject an unsupported major version before parsing any record, as `docs/DATA_CONTRACTS.md` section 13 requires.

**Consequences:** the record schemas in `schemas/` are unchanged — they describe one record, and the envelope wraps them. If payload becomes a problem, Shape B can be introduced without changing record contracts, because the envelope is the only thing that would change. CSV export paths stay stable across that migration.

---

## ADR-021 — Draft-time anchor: Tuesday end of day before Week 1, in America/New_York

**Status:** Accepted (2026-08-19, project owner). Closes the Phase-1 open question "anchor-date rule for Phase 2".

**Decision:** for a target season, the draft-time anchor is **23:59:59 America/New_York on the Tuesday immediately preceding the earliest Week-1 regular-season kickoff**, persisted as UTC. The rule is versioned `draft_anchor_v1_tuesday_eod_pre_week1` and that string travels on every historical feature row in `feature_cutoff_rule_version`.

Implementation requirements, all enforced in `ffdraft.anchors` and tested:

- the time zone is explicit and named; machine-local time is never consulted, so a build's leakage boundary cannot depend on where it ran;
- daylight saving is handled by `zoneinfo`, not by a fixed offset — the local instant is constant and only its UTC rendering moves;
- the Tuesday is derived by date arithmetic, then combined with the local time, because subtracting a `timedelta` from an aware datetime does wall-clock arithmetic and can land on a local time that does not exist;
- the anchor must be **strictly earlier** than the first kickoff. `SeasonAnchor` refuses to be constructed otherwise, and an opener that itself falls on a Tuesday steps the anchor back a full week rather than trimming the time;
- the Week-1 kickoff comes from `load_schedules`, and nothing else about the schedule is read.

**Why the schedule is not leakage.** A season's Week-1 date is published in May, months before the anchor. It is preseason-known context, not an outcome of the season it opens. Reading it is the same kind of act as reading a player's birth date.

**Why Tuesday end of day.** `docs/DATA_CONTRACTS.md` section 3 recommended "the Tuesday immediately before the opening game week" as the point matching common final-draft timing. Measured across 2014-2025 the rule yields a lead time of 1.85 days in every season, so the anchor sits consistently after final roster cuts and before the first snap. Two of the fourteen openers this project touches (2012, 2026) fall on a Wednesday rather than a Thursday, which a "kickoff minus two days" shortcut would silently get wrong; deriving the weekday explicitly is what makes those seasons safe.

**Consequences:** every timestamped feature observation must satisfy `observed_at <= anchor_at_utc`, and the leakage suite asserts it. Changing the rule requires a new version string and a new ADR — in particular, the rule may **not** be tuned after seeing model performance in Phase 3 or later.

---

## ADR-022 — The preseason universe is built only from pre-anchor evidence

**Status:** Accepted (2026-08-19). Extends ADR-018 from features to the row list itself.

**Decision:** a `(season, player_id)` row exists only if at least one of three pieces of evidence, each of which demonstrably predates the anchor, says the player was in the league:

1. `prior_season_roster` — the player appeared on an NFL roster in season Y-1, which ended in January of year Y;
2. `draft_class` — the player was selected in the season-Y NFL draft, held in late April;
3. `depth_snapshot_pre_anchor` — the player appeared on a timestamped depth-chart snapshot with `observed_at <= anchor`, which nflverse publishes only from 2025 onward (ADR-015).

Each row records which of the three applied, in `eligibility_basis`, and each season records whether the snapshot basis was even available, in `universe_era`.

**Explicitly not used:** `load_rosters(Y)`, `load_rosters_weekly(Y)` week 1, target-season statistics, and anything else describing season Y after it began.

**Why the week-1 roster is refused.** It is the tempting near-miss: final cuts happen roughly ten days before a September opener, so a week-1 roster is *probably* settled by the anchor. But nflverse publishes it as a week-indexed record with no observation timestamp, so there is no evidence it was settled by the anchor rather than after it — and week-1 rosters carry practice-squad elevations and in-week signings that certainly were not. ADR-018 already refuses the identical argument for week-1 depth charts. Roster membership and depth rank are different questions, but both need a defensible availability rule, and week-1 rosters have none. Using one would let *eventual participation* select the training rows, which is the survivorship bias this ADR exists to prevent.

**Why the universe is not uniform across eras.** Admitting the snapshot basis widens the 2025 universe by players no lagged source can see — undrafted rookies, who have neither a prior roster season nor a draft pick. Refusing it would discard a genuine, timestamped, anchor-safe observation to buy cosmetic uniformity. The honest trade is to take the observation and make the boundary visible: `universe_era` is on every row, and the quality report breaks eligibility down by season, position and basis so anyone choosing an evaluation window can see exactly what changed and filter to the era-stable subset.

**Consequences:** pre-2025 universes exclude undrafted rookies entirely. That is a coverage limitation, not a leak, and it errs conservatively — the rows that are missing are ones a preseason model would have had the least information about anyway. A separate, larger era boundary is visible in the data and reported: nflverse roster coverage jumps from ~2,150 rows a season to ~3,060 at 2016, so target seasons 2014-2016 carry ~670 eligible rows against ~1,050 from 2017 onward. Phase 3 must choose its training window with that in view rather than assuming twelve comparable seasons.

**Revisit if:** a licensed or archived preseason roster source for pre-2025 seasons is found and verified, or nflverse begins publishing timestamped roster snapshots for historical seasons.

---

## ADR-023 — The historical modelling dataset is Parquet, outside version control

**Status:** Accepted (2026-08-19)

**Decision:** `ffdraft build-historical` writes three typed Parquet tables plus a quality report, a build manifest and a rendered feature dictionary into `data/historical/`, which is gitignored. The tables are:

- `features.parquet` — one scoring-independent row per `(season, player_id)`;
- `labels_fantasy.parquet` — one row per `(season, player_id, scoring_preset)`;
- `labels_vorp.parquet` — one row per `(season, player_id, scoring_preset, league_preset_id)`.

**Why three grains rather than one table.** Football features do not depend on scoring, and realized replacement value depends on roster construction as well as scoring. Materialising one wide table would repeat every football feature nine times (three scoring presets x three league presets) to carry two label columns that actually vary. The normalized grains keep the feature table honest about what a feature *is*, and a join is cheap.

**Why it stays out of git.** `AGENTS.md` section 15 keeps generated data out of source commits, and the dataset is reproducible from code plus source releases: the manifest records the code SHA, the config versions, the feature-schema hash, the season windows and a content hash per table, so a rebuild that disagrees is detectable rather than merely suspected. Committing 11,604 rows of derived data would trade review clarity for nothing. What *is* committed is `docs/FEATURE_DICTIONARY.md` (generated from the code, with a test asserting it is current) and the `SESSION_STATE.md` record of the validated build.

**Consequences:** Phase 3 must rebuild the dataset before training, which takes a few minutes of nflverse downloads. `ffdraft validate-historical` re-runs the table-level leakage and semantic audits over a dataset on disk without rebuilding it, and fails if the tables no longer match the hashes in their manifest.

---

## ADR-024 — Phase-3 modelling dependencies: LightGBM and NumPy, nothing else

**Status:** Accepted (2026-08-19)

**Decision:** Phase 3 adds exactly two runtime dependencies, `lightgbm` and `numpy`. The regularized baseline, every metric, and the paired bootstrap are written against NumPy inside `ffdraft.modeling` rather than importing scikit-learn and SciPy. SciPy is declared as a *development* dependency only, so the test suite can cross-check the project's Spearman and Kendall tau-b against an independent implementation.

**Why not scikit-learn.** What Phase 3 needs from it is a closed-form ridge — fifteen lines of linear algebra — and LightGBM's native training API does not need it either. Adding a large framework for that would violate `AGENTS.md` section 13, and its preprocessing objects would make "the preprocessor was fitted only on the training fold" a property of how the code is called rather than of what exists.

**Why not SciPy in production.** Two correlation coefficients and a percentile. Writing them here means the tie-handling conventions are the project's own documented choices — Spearman as Pearson on average ranks, Kendall in its tie-corrected `tau-b` form — pinned by hand-worked examples in `tests/model/test_metrics.py` rather than inherited from a library's defaults. SciPy arrives anyway as a LightGBM dependency, so declaring it for tests costs nothing and buys an independent check.

**Consequences:** the metric implementations are the project's responsibility and are tested twice, by hand-worked example and by cross-check. `ruptures` for tier segmentation still waits for Phase 4.

---

## ADR-025 — Season 2025 is the sealed final holdout for the 2026 launch model

**Status:** Accepted (2026-08-19)

**Decision:** Target season 2025 is the final holdout. It is excluded from every development fold, every fitted statistic and every model-selection decision. `ffdraft.modeling.holdout` seals it structurally: the modelling frame drops sealed seasons at load time, the fold generator refuses to produce a fold that validates one, and reaching it requires constructing a `FinalEvalAuthorization` with the exact token `RELEASE-FINAL-HOLDOUT-2025`, which the CLI accepts only from `--final-eval --confirm-final-eval <token> --final-eval-reason <why>`. Phase 3 does not run that path against real data.

**Why 2025.** It is the most recent fully labelled season; it is the only season carrying true timestamped preseason depth observations (ADR-015, ADR-018), so its information environment is the closest available analogue of 2026 inference; and for the same reason it is a deliberate domain-shift test, because part of its eligible universe is established by a mechanism no earlier season has.

**Predeclared diagnostic slices.** Fixed here, before any candidate comparison, and defined without inspecting 2025 outcomes. The primary result is **full-universe 2025 performance** and nothing may replace it. Reported beside it: an *era-stable subset* (rows whose eligibility is supported by the previous season's roster or the target season's draft class, i.e. discoverable under the pre-snapshot mechanism), rookie versus veteran, depth-context state, position, scoring preset, and an information-rich/low-information split defined purely from feature availability (`has_prior_season_stats` and at least eight games played in the previous season). Every predicate reads feature-side metadata only, and each has an executable form in `slice_masks`, so a slice cannot be defined in prose and quietly implemented differently.

**Why the era-stable subset exists.** Phase 4 has to be able to answer whether a weaker 2025 result means the model failed or the universe widened. Answering that after seeing the number would not be an answer.

**Consequences:** Phase-3 evaluation is restricted to 2020-2024 (with 2017-2019 available as W1-only diagnostics). A feature whose usable signal exists only in 2025 therefore has no development evidence and cannot enter the Phase-3 core set (ADR-026). Once the holdout is consumed it is not a holdout any more, so no model-design decision may be taken against it afterwards.

**Revisit if:** never for the 2026 launch model. A future season becomes the next holdout, and 2025 joins the training window.

---

## ADR-026 — The Phase-3 core feature set excludes snapshot-era and era-index columns

**Status:** Accepted (2026-08-19)

**Decision:** `ffdraft.modeling.features` publishes a versioned, hashed model-input view, `intrinsic_core_v1`, containing 78 of the 85 Phase-2 model inputs. Seven are excluded with a recorded reason, measured on the built 2014-2025 dataset:

| Column | Reason | Measurement |
|---|---|---|
| `depth_rank_at_anchor` | snapshot-era only | non-null on 0.0% of rows in every season 2014-2024, 49.8% of 2025 |
| `team_change_flag` | snapshot-era only | non-null on 0.0% of rows 2014-2024, 36.9% of 2025 |
| `depth_rank_observed` | era indicator | constant false in every development season |
| `team_change_known` | era indicator | constant false in every development season |
| `team_at_anchor_known` | era distribution shift | true on 7.1-11.7% of rows per development season against 50.6% of 2025 |
| `prev1_team_games` | horizon era index | mean exactly 15.0 through target season 2021 and 16.0 from 2022 — the previous season's fantasy horizon minus the bye, constant within a season apart from the cancelled 2022 game |
| `draft_year` | time index | a calendar index whose training range never covers the validation season's rookies; `seasons_since_draft` carries the same information relative to the target season |

**Why.** Not every leakage-safe feature is a defensible model input. The first five have no development-era support at all: their only signal lives in the sealed season, so no Phase-3 fold could validate them, and admitting one after seeing 2025 would change the production feature set *after* the final holdout — the exact move that invalidates a holdout. The last two are indices of *when* a row is, not of what the player did.

**What is kept.** The era-stable role signal is the lagged `prior_season_role_rank` with its `prior_season_role_known` indicator, which is present in every development season; no harmonized depth feature is constructed, because collapsing an observed depth rank and a prior-season role rank into one number would give one column two different meanings. `prev1_games_missed` is kept: it is the player-level durability content that `prev1_team_games` was only the denominator for.

**Enforcement.** `audit_era_stability` re-measures every claim it can on each experiment run, over every unsealed season rather than only the validation ones — a missingness indicator that matters mostly in 2014-2016 still carries information the training window uses. An included feature with no development coverage or no development variation is a critical failure; a *snapshot-era-only* or *era-indicator* exclusion whose evidence has gone stale is a warning naming the column. The third reason, **era distribution shift**, is deliberately not re-checked: it is a comparison against the sealed season, which a development run cannot see by design, so it stands as a recorded one-time measurement. The selection's hash and its full included/excluded lists appear in every experiment report; the hash covers the included columns and the exclusion reason codes, not the prose, so rewording an explanation does not masquerade as a different feature set.

**Consequences:** Phase 4 inherits a feature set that means the same thing in development and on the final holdout. Genuinely snapshot-era-only inputs are deferred production candidates and need a future season to validate against, not a rerun.

---

## ADR-027 — Phase-3 promotion criteria and window-selection rule, frozen before the comparison

**Status:** Accepted (2026-08-19)

**Decision:** The rules live in `ffdraft.modeling.gate` as `phase3_promotion_v1` and were committed before the decisive experiment ran. The primary baseline is **B0**. A candidate is promoted only if all four hold:

1. macro MAE improves, with the paired 95% bootstrap interval for the delta entirely below zero;
2. macro mean pinball loss improves, with its paired interval entirely below zero;
3. macro Spearman falls by no more than 0.010;
4. no positional collapse: for every position, MAE no more than 3% worse than the baseline's, Spearman no more than 0.030 worse, and empirical P10-P90 coverage inside [0.60, 0.95].

Aggregates are macro means over season x position x scoring cells, so a large position cannot outvote a small one; row-weighted numbers are emitted as diagnostics. Among candidates that pass on the selected window, the one with the lowest macro mean pinball loss is promoted, ties broken on macro MAE.

**Why these and not others.** The product is a distribution, so improving the point estimate alone is not enough; ranking is what a draft board consumes, so it may not materially regress even when the errors improve; and a pooled win that guts QB or TE is not a win. Requiring every one of the sixty cells to improve would select for luck instead, so the positional rule bounds *deterioration* with a materiality threshold rather than demanding improvement everywhere.

**Window rule.** W1 (2014+) and W2 (2017+) are compared on identical 2020-2024 folds with the same candidate family and feature set, paired at the row level. A window wins only by taking both primary metrics with intervals that exclude zero. Otherwise the evidence is inconclusive and **W2** is selected by predeclared conservative tie-break, because its eligibility universe does not straddle the 2016 nflverse roster-coverage step. No weighted hybrid is constructed to avoid choosing.

**Consequences:** if nothing passes, Phase 3 is not complete and the gate is not weakened afterwards; the response is to investigate data, features or baselines within Phase-3 scope. `tests/model/test_bootstrap_and_gate.py` drives the comparator with synthetic metrics, including a candidate that passes and a hidden positional collapse that fails.

---

## ADR-028 — Training window: W1, the full 2014+ history

**Status:** Accepted (2026-08-19)

**Decision:** The intrinsic model trains on an expanding window starting at **2014** (`W1_all_history`). The alternative, starting at 2017 to avoid the nflverse roster-coverage step (`W2_modern_era`), is retained in code as a policy but is not the production window.

**Evidence.** Both policies were run over the identical development folds 2020-2024, with the same feature set, the same models and the same seed, so the comparison is paired at the row level. On the Q1 candidate, W1 relative to W2:

| Metric | Delta (W1 − W2) | Paired 95% CI |
|---|---|---|
| macro MAE | **−0.286** | −0.474 to −0.107 |
| macro mean pinball | **−0.083** | −0.134 to −0.037 |
| macro Spearman | +0.0007 | −0.0036 to +0.0054 |

Both primary metrics favour W1 with intervals excluding zero, which is what ADR-027 declared a decisive win. Ranking is indistinguishable between the two.

**The honest caveat.** The advantage is small — 1.3% of MAE — and it is not evenly spread. By fold, W1's MAE advantage is −0.911 (2020), −0.023 (2021), −0.024 (2022), −0.158 (2023), −0.315 (2024). The largest gain is in 2020, which is exactly the fold where W2 has only three training seasons. So a fair reading is "more training data helps, most when there is least of it" rather than "2014-2016 are as informative per row as 2017+". W1 never *lost* a fold on MAE and lost only 2022 on pinball by 0.06, so the direction is consistent even if the mechanism is partly sample size.

**Why accept it anyway.** The rule was frozen before the numbers existed (ADR-027) and W1 met it. Re-reading the same evidence to reach the more conservative answer after seeing it would be exactly the move the freeze exists to prevent. The thin-era concern that motivated W2 — that 2014-2016 carry ~36% fewer eligible rows because of upstream roster coverage — is real but did not produce the systematic calibration or ranking degradation it was expected to: W1's P10-P90 coverage is 0.771 against W2's 0.765 and its Spearman is identical.

**No hybrid.** No era weighting, no observation weights, no menu of window variants. The clean question was asked and answered.

**Consequences:** Phase 4 trains through 2024 from 2014 and, after the final holdout is consumed, through 2025. If a future season's evidence reverses this, that is a new ADR with new folds — not a re-reading of these numbers. The comparison must not be re-run against 2025 to "check".

---

## ADR-029 — Q1, the direct-total LightGBM quantile model, advances to Phase 4

**Status:** Accepted (2026-08-19)

**Decision:** The Phase-4 production candidate family is **Candidate A / Q1**: position-specific, scoring-specific LightGBM quantile regression over P10/P25/P50/P75/P90 of the season fantasy-point total. B0 and B1 remain in the repository as permanent comparators.

**Evidence** (development folds 2020-2024, window W1, macro over season x position x scoring):

| Model | MAE | RMSE | Spearman | Kendall | Mean pinball | P10-P90 coverage | P10-P90 width |
|---|---|---|---|---|---|---|---|
| B0 | 25.60 | 44.06 | 0.659 | 0.524 | 9.98 | 0.793 | 83.1 |
| B1 | 26.98 | 42.21 | 0.711 | 0.550 | 9.74 | 0.798 | 80.4 |
| **Q1** | **22.07** | **41.03** | **0.726** | **0.570** | **8.13** | 0.771 | 62.7 |

Q1 against B0, paired bootstrap over 1000 replicates: MAE −3.53 (−3.87 to −3.18), mean pinball −1.85 (−1.98 to −1.72), Spearman +0.066 (+0.058 to +0.075). Every position improves on all three; no position triggers the collapse rule. The gate passes on both windows, so the window decision (ADR-028) and the candidate decision are independent.

**What the baselines proved.** B0 is not a strawman: it beats the ridge baseline B1 on MAE at every position, and B1 fails the frozen gate on both windows for that reason. Nonlinear boosting is therefore buying something a linear model on the same features does not — but so is a well-constructed naive rule, and the repository keeps both.

**Two limitations recorded now, for Phase 4 to fix, not to discover.**

1. **Quantile crossing is frequent but small.** 38.7% of Q1 rows have at least one crossing in the raw output, with a mean total crossing magnitude of 0.53 fantasy points against a mean P10-P90 width of 62.7. Phase 3 repairs it with a deterministic sort and reports the raw rate separately. Phase 4 should address it properly — joint or monotonic quantile estimation, or calibrated post-processing — rather than continue to sort.
2. **Top-K retrieval does not follow rank correlation.** Q1's macro Spearman (0.726) beats B1's (0.711), but B1 retrieves more of the actual top-K by position (0.593 against Q1's 0.544; B0 is 0.535). A median-quantile point prediction is deliberately robust, and robustness compresses the top of the board — which is the part of the board a draft sheet is mostly about. Phase 4 must decide the production ranking statistic (expected versus median simulated VORP) with this in view, and should measure top-K on the simulated VORP rather than assuming the point prediction's ordering carries over.

**Consequences:** Phase 4 inherits Q1, window W1, feature set `intrinsic_core_v1` (`7203befaa5be25a2`), the frozen fold protocol and an untouched 2025 holdout. Candidate B (availability x performance) remains unimplemented and unjudged; comparing it is Phase-4 work, against the same protocol.

---

## ADR-030 — The Phase-4 decision rules are frozen before their results exist

**Status:** Accepted (2026-08-19)

**Decision:** Every consequential Phase-4 choice is written as a versioned rule in `src/ffdraft/modeling/rules.py` (`phase4_rules_v1`) and committed **before** the study that produces its evidence runs. Eight rules are frozen here:

| Rule | Version | What it decides |
|---|---|---|
| calibration acceptance | `phase4_calibration_v1` | whether a fitted calibration layer replaces plain monotone projection |
| horizon sensitivity | `phase4_horizon_v1` | whether the horizon-normalized target replaces the plain season total |
| candidate comparison | `phase4_candidate_v1` | whether Candidate B replaces the calibrated Candidate A |
| Monte Carlo convergence | `phase4_convergence_v1` | the production draw count |
| ranking statistic | `phase4_ranking_v1` | expected versus median simulated VORP as the fair rank |
| tier penalty selection | `phase4_tier_v1` | which penalty from the frozen grid is promoted |
| tier stability | `phase4_tier_stability_v1` | whether the promoted segmentation is trustworthy enough to publish |
| final-holdout acceptance | `phase4_final_holdout_v1` | whether the frozen production model is released after 2025 |

**Why one module.** ADR-027 froze Phase 3's single gate and the repository history is the evidence that it happened before the comparison. Phase 4 has eight such decisions rather than one, spread across modelling, simulation and tiering. Scattering them next to the code that uses them would make "was this threshold written before or after the number?" a question about eight commits instead of one. They live together, they are versioned together, and `all_rules()` serializes the whole set into every Phase-4 report and into the freeze checkpoint.

**Two conventions run through all eight.**

*Simplicity is the default and complexity must earn itself.* Mixed or indistinguishable evidence always resolves to the simpler incumbent — plain monotone projection over a fitted calibrator, Candidate A over Candidate B, median VORP over expected VORP, the plain season total over a rescaled one. This is `AGENTS.md` section 8's baseline-first principle expressed as a comparator rather than as an intention.

*Deterioration is bounded; improvement is not demanded everywhere.* With sixty-odd evaluation cells, requiring every one to improve selects for luck. Each rule therefore bounds how much worse a position or a fold may get, exactly as `phase3_promotion_v1` does, and uses paired bootstrap intervals where a comparison is close.

**Three choices worth stating explicitly.**

- **Coverage is never judged without width.** A fitted calibrator that reaches nominal coverage by inflating the P10–P90 interval more than 15% is refused. An interval wide enough to swallow every observation is uninformative, not calibrated, and the acceptance rule says so numerically rather than in a comment.
- **Convergence is measured at the 99th percentile, not the maximum.** One extreme-variance player would otherwise choose the draw count for the whole board. The maximum is still reported; it just does not decide. The rule also requires two comparisons at each candidate count — against the largest count in the ladder, and between two seeds — because the first measures bias against the best available reference and only the second measures Monte Carlo error directly.
- **The final-holdout gate has no place to put a diagnostic slice.** `evaluate_final_holdout` takes full-universe evidence and nothing else; the ADR-025 slices are reported beside the primary result and cannot enter the decision. A test asserts the signature, so a later "just add the era-stable slice to the gate" is a visible change to a frozen rule rather than a quiet one.

**Consequences:** every Phase-4 study reports the rule version it was judged under, and the rules are pure functions driven by synthetic evidence in `tests/model/test_phase4_rules.py` — including cases that make each rule say no. Changing a threshold after seeing a result is a new decision with a new version and its own ADR; it is never an edit in place. If a rule refuses the outcome Phase 4 wanted, the phase is blocked and the block is recorded.

---

## ADR-031 — Quantile monotonicity is an isotonic projection; the fitted calibration layer is not adopted

**Status:** Accepted (2026-08-19). Closes the Phase-3 open question "how to fix quantile crossing properly" for the direct-total family. Evidence: `docs/experiments/phase4-intrinsic-distribution/`.

**Decision:** the production monotonicity repair is the **L2 projection onto the monotone cone**, computed by pool-adjacent-violators (`monotone_projection_v1`). Plain sorting is not used. The fitted per-level residual calibration (`residual_shift_then_monotone_v1`) was implemented, measured and **not** adopted under `phase4_calibration_v1`.

**Why projection rather than sorting.** Sorting a row's five values is the increasing rearrangement of the estimated quantile curve on that grid. Rearrangement has a real theoretical basis — Chernozhukov, Fernández-Val and Galichon (2010) show it weakly reduces estimation error in *L^p* for the quantile *function* — but the guarantee is stated for the function on [0, 1] and recovering it from a finite grid needs the grid to carry equal weight. This project's levels are 0.10, 0.25, 0.50, 0.75, 0.90, which are not evenly spaced, so a plain sort is not the rearrangement of any weighting of them and no contraction property follows. Isotonic projection needs no such argument: the true quantile vector lies in the monotone cone, the cone is closed and convex, and projection onto a closed convex set cannot increase the distance to any point of it. `tests/model/test_calibration.py` asserts that contraction on random inputs.

**The honest cost.** On the development folds the projection is very slightly *worse* than the sort on every headline number: MAE 22.112 against 22.070, mean pinball 8.142 against 8.132, P10–P90 coverage 0.738 against 0.771. The differences are around 0.1–0.5% and well inside the fold-to-fold spread. The choice is made on the guarantee rather than on a difference that small, and both are reported side by side (`A0` and `Q1`) rather than one being quietly dropped.

**Why the fitted calibration lost.** `A1` did exactly what it was designed to do — P10–P90 coverage moved from 0.738 to 0.826, closing the gap to nominal by 0.036 — and it cost almost nothing in pinball (−0.11%). But it moved the *inner* interval the wrong way: P25–P75 coverage went from 0.477 to 0.542, widening that gap by 0.0189 against the 0.010 tolerance, and the mean P10–P90 width inflated 13.6% (62.5 → 71.0, inside the 15% bound but visibly). The correction is concentrated at the top: the mean fitted shift is −0.21, −0.16, −0.05, +0.14, **+8.41** across the five levels, so the layer is essentially a ceiling-raiser. Buying outer coverage by pushing P90 up eight points while pushing P25–P75 past nominal is not calibration in the sense a draft sheet needs, and the frozen rule said so before the numbers existed.

**Consequences:** the production distribution carries no fitted calibration parameters, which is one fewer thing to version and one fewer thing to drift. The repair is a pure function of a row. If a future season's evidence shows the outer intervals genuinely under-covering *and* an adjustment that does not widen the inner ones, that is a new decision with a new version.

---

## ADR-032 — Horizon normalization is measured and rejected

**Status:** Accepted (2026-08-19). Closes the Phase-3 known risk "the fantasy horizon changed at 2021". Evidence: `docs/experiments/phase4-intrinsic-distribution/`.

**Decision:** the intrinsic model keeps the plain season fantasy-point total as its target. The horizon-normalized variant `AH` — the same architecture trained against `points / fantasy_horizon_weeks` and multiplied back by the validation season's horizon — was built, measured on the identical development folds, and **not** adopted under `phase4_horizon_v1`. No further horizon variant will be built.

**Evidence.** Against the incumbent, paired over 1000 bootstrap replicates:

| Metric | AH − A0 | Paired 95% CI |
|---|---:|---|
| macro MAE | **+0.1420** | +0.0458 to +0.2366 |
| macro mean pinball | −0.0188 | −0.0427 to +0.0063 |
| macro Spearman | −0.0019 | −0.0048 to +0.0010 |

Route (a) required both primary metrics to improve decisively; MAE moved *against* the variant with an interval excluding zero. Route (b) required the 2021 fold — the one development fold trained entirely on 16-week seasons and validated on a 17-week one — to improve by at least 2% relative. It got **worse** by 0.79% (22.995 → 23.178). Neither route opened.

**What that says about the risk.** The 2021 boundary is real and remains recorded, but rescaling the target does not fix it. The plausible reason is that the horizon change moves the target by about 6% while the season-to-season variance a preseason model faces is an order of magnitude larger, so removing a 6% scale factor from the label removes almost no error and costs a little precision by dividing every training row by a constant it did not need. The models see the boundary as noise either way; normalizing simply relabels it.

**Consequences:** the Phase-2 label contract is untouched, `prev1_team_games` stays excluded (ADR-026), and the horizon boundary remains a documented limitation rather than a corrected one. Revisiting needs a different mechanism, not another rescaling.

---

## ADR-033 — Candidate B, the availability × performance hurdle, is the production intrinsic model

**Status:** Accepted (2026-08-19). Closes the Phase-3 open question "whether Candidate B beats Q1". Supersedes ADR-029's *candidate* selection; ADR-029's window, feature set and fold protocol stand unchanged. Evidence: `docs/experiments/phase4-intrinsic-distribution/`.

**Decision:** the production intrinsic model is **Candidate B** (`cb_hurdle_availability_performance_v1`): two LightGBM quantile components over the same `intrinsic_core_v1` features, composed by deterministic Monte Carlo.

- **availability** — quantiles of `games / fantasy_horizon_weeks`, a rate rather than a count so 16- and 17-week seasons are comparable inside one training window; multiplied back by the target season's horizon and rounded at prediction time;
- **conditional performance** — quantiles of fantasy points per *active* game, fitted only on training rows with at least one game, because points per game is undefined for the rest;
- **composition** — `games x points-per-game`, with zero games scoring exactly zero and nothing clipped from below, because interceptions and lost fumbles make a negative season total genuinely possible;
- **dependence** — a Gaussian copula with one correlation per position × scoring preset, estimated inside the fold on an inner chronological split from probability-integral transforms of both components.

**Evidence** (development folds 2020–2024, window W1, macro over season × position × scoring; paired block bootstrap, 1000 replicates):

| Model | MAE | Spearman | Top-K | Pinball | P10–P90 cov | P25–P75 cov | Raw crossing |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | 25.602 | 0.659 | 0.535 | 9.978 | 0.793 | 0.528 | 0.000 |
| Q1 (Phase 3) | 22.070 | 0.726 | 0.544 | 8.132 | 0.771 | 0.513 | 0.387 |
| A0 (projected) | 22.112 | 0.720 | 0.544 | 8.142 | 0.738 | 0.477 | 0.387 |
| **CB** | **21.907** | **0.750** | **0.577** | **8.080** | 0.827 | 0.614 | **0.000** |

Against A0: MAE −0.2052 (−0.3322 to −0.0733), mean pinball −0.0614 (−0.1002 to −0.0236), Spearman +0.0298 (+0.0262 to +0.0345), top-K recall +0.0326 (+0.0007 to +0.0354) — every interval excludes zero, which is more than `phase4_candidate_v1` required. Against B0: MAE −3.695, pinball −1.897, Spearman +0.091, top-K +0.042. No position regresses on MAE or Spearman and every position's P10–P90 coverage improves.

**Why the separation actually helps here.** 44% of eligible player-seasons record zero games. A direct-total model spends much of its capacity on an availability question dressed as a scoring question; the hurdle asks the two questions separately and lets the composition put them back together. The clearest evidence is the top of the board: ADR-029 recorded that Q1's robust median ordering retrieved less of the actual top-K than a linear model did, and CB recovers most of that gap (0.577 against Q1's 0.544 and B1's 0.593) while keeping the better rank correlation.

**The dependence is not decorative.** The fitted copula correlation is positive in all sixty groups — minimum 0.205, median 0.323, maximum 0.494, by position RB 0.373, QB 0.345, TE 0.333, WR 0.289. Players who stay on the field also score more per game, so sampling the two components independently would have produced too narrow a spread at both ends. The parameter is estimated on players who actually played, because points per game is undefined for the others; that restriction is a limitation, not an approximation of convenience, and it is stated in the model card.

**Quantile crossing is resolved rather than repaired.** CB's quantiles are empirical quantiles of one Monte Carlo sample, so they cannot cross — the raw crossing rate is 0.000 against Q1's 0.387. The monotone projection remains applied as a safety net and is a no-op in practice.

**One limitation, measured rather than smoothed.** CB's P25–P75 coverage is 0.614 against a nominal 0.50, which the diagnostic check reports. It is not over-dispersion: restricted to players who appeared in at least one game, coverage is 0.456 (P25–P75) and 0.748 (P10–P90) — slightly *under* nominal. The gap comes from the atom the model deliberately represents. 18.4% of evaluation rows have P25 and P75 both exactly zero, and a player who scores exactly zero is inside that interval by definition. A discrete distribution covers its own mass point; that is arithmetic, not miscalibration, and the honest fix is to report both numbers rather than to widen or narrow anything.

**Consequences:** the production model has two components, a per-group correlation and a Monte Carlo composition step, so it is meaningfully more machinery than Q1. It earned that under a rule frozen before the comparison. Q1, A0, A1, AH, B0 and B1 all remain in the repository as comparators.

---

## ADR-034 — Median simulated VORP is the fair rank; the draw count is the predeclared fallback

**Status:** Accepted (2026-08-19). Closes the Phase-3 open question "expected versus median simulated VORP". Evidence: `docs/experiments/phase4-simulation-ranking/`.

**Decision A — the fair-ranking statistic is median simulated VORP.** `phase4_ranking_v1` allowed expected VORP to replace it only by improving macro top-K retrieval by at least 0.010 without losing more than 0.005 of macro Spearman or Kendall. Measured against the realized VORP labels over the full eligible universe of every development season and all nine scoring x league presets:

| Statistic | Spearman | Kendall | Top-K recall | Early-round recall | Seed rank stability |
|---|---:|---:|---:|---:|---:|
| **median VORP** | **0.8057** | **0.6528** | 0.6204 | **0.3611** | 0.9998 |
| expected VORP | 0.7999 | 0.6457 | **0.6218** | 0.3593 | 0.9999 |

Expected VORP gained 0.0014 of top-K — a seventh of the margin the rule required — while giving up 0.0058 of Spearman and 0.0071 of Kendall, both past the 0.005 tolerance. This is not an inconclusive tie resolved by a default; it is a refusal on evidence.

**What it says about the Phase-3 worry.** ADR-029 recorded that Q1's median point prediction retrieved less of the actual top-K than a linear model did, and asked Phase 4 to re-measure top-K on simulated VORP rather than assume the point ordering carried over. It did not carry over: top-K retrieval on simulated VORP is **0.620**, well above the 0.577 the promoted model's point prediction reaches and above every Phase-3 number. Simulating league-relative value recovers what a robust point estimate compresses, which is exactly what the simulation was for.

**Decision B — the production draw count is 10,000, selected by `phase4_convergence_v1`'s predeclared fallback rather than by satisfying it.** No count in the frozen ladder (1,000 / 2,500 / 5,000 / 10,000) met every tolerance. The rule's own text covers this case — "the largest declared count is used and the breaches are recorded" — so 10,000 is the frozen outcome, with the breaches published rather than smoothed.

**What converged and what did not**, comparing two independent seeds at 10,000 draws across the four declared scenarios:

| Quantity | Tolerance | Observed | Verdict |
|---|---|---|---|
| fair-rank Spearman | >= 0.9990 | 0.9994 - 0.9995 | pass |
| top-50 overlap | >= 0.96 | 0.98 - 1.00 | pass |
| mean rank change, top 150 | <= 1.5 | 0.86 - 1.35 | pass |
| max replacement shift | <= 0.50 | 0.09 - 0.25 | pass |
| mean abs outer-quantile VORP shift | <= 0.60 | 0.31 - 0.45 | pass |
| mean abs expected-VORP shift | <= 0.25 | 0.23 - 0.31 | 2 of 4 fail |
| mean abs P50-VORP shift | <= 0.35 | 0.29 - 0.42 | 3 of 4 fail |
| tier adjusted Rand | >= 0.90 | 0.50 - 0.75 | all fail |
| tier count difference | <= 1 | 1 - 5 | 3 of 4 fail |

**The ordering is converged; the segmentation is not.** Every ranking tolerance passes comfortably, which matters because fair rank is the board's spine. The value tolerances are missed by 10-20% — a further 4x in draws would close them, which the frozen ladder does not offer. The tier clause fails by a wide margin at every count and does not look like something more draws would fix: a tier boundary is a discrete cut on a nearly continuous value curve, and moving it a few ranks costs a lot of adjusted Rand index when nine tiers span three hundred players.

**A flaw in the frozen rule, recorded rather than corrected.** `phase4_convergence_v1` requires tier ARI >= 0.90 between seeds, taken as the worst case over both candidate ranking statistics and all six penalties in the grid. `phase4_tier_stability_v1` — the rule that actually governs whether tiers may be published — asks for >= 0.60 under bootstrap on the *same* quantity. The convergence clause is therefore strictly harder than the promotion clause it was meant to protect, and it is decided partly by penalties the tier rule may never select. That is a design error in ADR-030, discovered by running it. It is not fixed here: changing a threshold after seeing it fail is the move the freeze exists to prevent. It is recorded, the measurement is published, and the tier-stability gate remains the decisive test of whether tiers ship.

**Consequences:** Phase-4 exit criterion 7 ("draw count passed an explicit convergence test") is **not satisfied**. The convergence test ran, was explicit and was decided by a predeclared rule, but the draw count comes from that rule's fallback rather than from meeting its tolerances. Residual Monte Carlo error at 10,000 draws — about 0.3 fantasy points on a player's expected VORP, under one and a half rank positions in the top 150 — is published as a limitation in the model card and the tier-method report. A future revision of the convergence rule should measure the tier clause on the promoted configuration and set its bar consistently with the stability gate; that is a new decision with a new version, not an edit to this one.

## ADR-035 — Tiers are published from the dynamic-programming alternative and the stability gate fails

**Date:** 2026-08-19 (Phase 4, stage C)

**Status:** accepted

**Context:** `phase4_tier_v1` and `phase4_tier_stability_v1` were frozen in ADR-030 before any tier existed. The first selects a penalty from a fixed six-value grid — admissibility first (6-24 tiers, singleton rate <= 0.20, no tier holding more than 25% of the 300-player board, boundaries separating more than a typical within-tier adjacent pair), then the highest bootstrap adjusted Rand index among the admissible. The second decides whether the promoted segmentation may be put in front of a drafter. `docs/MODELING.md` section 14 names PELT as the primary candidate and exact quantile-dispersion dynamic programming as the alternative, to be reached only when the primary proves unstable under measured tests.

The study ran on development folds only, at the draw count and ranking statistic ADR-034 had already fixed (10,000 draws, `median_vorp`), with 200 bootstrap replicates per scenario over six scenarios — 1,200 replicates in total, each re-ranking as well as re-segmenting, because the fair ranks come from the same draws.

**Decision:** the promoted segmentation is **`dp_quantile`** (`dp_quantile_wasserstein_v1`) at **penalty 1.0**, and **the frozen stability gate fails on boundary agreement**. Tiers are published anyway, with the failure recorded in the model card, the tier-method report and the build metadata, because tier *membership* passes every other clause and is useful; tier *boundaries* are not sharply located and the artifacts must not imply that they are.

**Evidence:** PELT was tried first and refused, so the escalation is a measured failure rather than a preference:

| Criterion | Threshold | `pelt_rbf` @ 1.0 | `dp_quantile` @ 1.0 |
|---|---|---|---|
| bootstrap adjusted Rand | >= 0.60 | 0.7726 | **0.8649** |
| boundary agreement | >= 0.50 | 0.3336 **fail** | 0.2394 **fail** |
| singleton rate | <= 0.20 | 0.1381 | **0.0396** |
| tier-count CV | <= 0.25 | 0.1061 | **0.0454** |
| monotonic tier pairs | >= 0.80 | 0.6560 **fail** | **0.8448** |
| cross-preset ARI | >= 0.50 | 0.4316 **fail** | **0.5288** |

The alternative fixes two of PELT's three failures and improves five of the six quantities. It does not fix the third, and no further algorithm is declared.

**Why boundary agreement fails, measured rather than guessed.** Across 1,200 replicates the segmentation used **283 of the 299 possible cut sites at least once, and only 4 were reproduced by a majority**. The four are real: ranks 267 (0.995), 99 (0.680), 16 (0.587) and 68 (0.585). Everything else is spread thinly. The boundary diagnostics say the same thing in units a drafter would recognise — the median promoted boundary sits on a **0.55-point** P50 cliff against a P10-P90 width of 80-130 points, and the median probability that the player just below a boundary outscores the player just above it is **0.4972**. A coin flip.

So simulated VORP declines almost smoothly down a 300-deep board, and "where a tier ends" is mostly not an identified quantity. The frozen admissibility rule then demands more cuts than the data supports: `max_largest_tier_share = 0.25` forbids any tier larger than 75 players, but the deep tail of a 300-player board genuinely *is* one large near-replacement group — at penalty 3.0 the segmentation wants tiers of 82 and 110 — so the rule forces the tail to be sliced, and slices inside a flat region are exactly what a bootstrap cannot reproduce. The grid shows the trap directly: penalty 3.0 reaches boundary agreement 0.5167 and penalty 8.0 reaches 0.5000, and **both are inadmissible on largest tier share** (0.3409 and 0.3978). The two frozen rules cannot both be satisfied on this distribution.

**Bootstrap ARI 0.865 beside boundary agreement 0.239 is not a contradiction**, it is the finding: which group a player belongs to is reproducible, where the group ends is not. Realized-VORP monotonicity agrees — mean realized VORP falls across 0.845 of adjacent tier pairs, so the groups carry real signal even though their edges are soft.

**What was not done.** No threshold was changed after seeing it fail. No penalty outside the frozen grid was tried, and the admissible-but-better-looking penalty 3.0 was not substituted for the one the rule selected. No boundary was moved by hand. The escalation to the alternative is the response ADR-030 declared in advance for exactly this case, and it was taken only after PELT's measured failure.

**Consequences:** the Phase-4 exit criterion for tier stability is **not satisfied**, and is reported as not satisfied. Tier artifacts ship with `tier_stability_gate: "fail"` in their build metadata and a limitation in the model card, so no consumer can read a boundary as sharper than it is. `docs/MODELING.md` section 14 gains the measurement. The remedy is a Phase-6+ decision, not an edit here: either publish fewer, wider tiers by relaxing `max_largest_tier_share` for the undifferentiated tail (a new rule version with its own evidence), or present tier membership with an explicit boundary-confidence band instead of a hard line. Both are new decisions and both need their own gate.

## ADR-036 — The sealed 2025 holdout was evaluated once, and the production model passed

**Date:** 2026-08-19 (Phase 4, stage E)

**Status:** accepted

**Context:** ADR-025 sealed season 2025 structurally: `load_modeling_dataset` drops it before anything sees the frame, the fold generator refuses to build a fold that validates it, and the only path through requires an explicit `FinalEvalAuthorization` carrying a fixed token and a written reason. ADR-030 froze `phase4_final_holdout_v1` — the acceptance rule — before any Phase-4 model existed. The predeclared primary slice is the full universe against baseline **B0**; the ADR-025 diagnostic slices are reported beside it and are explicitly *not* part of the gate.

Freeze checkpoint `2f0e725` fixed the architecture, calibration, target scale, training window, ranking statistic, draw count, tier algorithm and tier penalty. That commit exists so that the holdout demonstrably could not have informed any of them.

**Decision:** the holdout was consumed **once**, at `2f0e725`, with `--window W1_all_history` and the required token. It **passed**. No parameter, threshold, feature or rule was changed afterwards, and the holdout is now spent: it can never again serve as an untouched test of this project.

**Result — full universe, 3,309 rows, 12 cells, macro over position × scoring:**

| Model | MAE | RMSE | Spearman | Kendall | Pinball | P10-P90 cov | P10-P90 width | Top-K |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 23.93 | 42.06 | 0.679 | 0.546 | 9.331 | 0.808 | 80.7 | 0.472 |
| **CB** | **20.19** | **38.75** | **0.780** | **0.648** | **7.197** | 0.845 | 56.9 | 0.521 |

Paired deltas, 1,000 block-bootstrap replicates: **MAE −3.738 (95% CI −4.364 to −3.102)**, **mean pinball −2.134 (−2.377 to −1.874)**, **Spearman +0.1015 (+0.082 to +0.122)**. Top-K recall +0.049 (−0.017 to +0.083) is not significant and is not required by the rule. Every clause passed: both intervals exclude zero, Spearman improved rather than regressed, no position exceeded a tolerance, positional P10-P90 coverage ran 0.803-0.879 inside the 0.60-0.95 band, and **no production quantile crossed** — 0.0000 against a bar of exactly zero.

**Diagnostics (not part of the gate).** CB improves MAE and pinball on **every** predeclared slice:

| Slice | n | B0 MAE | CB MAE | B0 Spearman | CB Spearman |
|---|---:|---:|---:|---:|---:|
| QB | 432 | 37.22 | 29.92 | 0.675 | 0.753 |
| RB | 789 | 26.03 | 23.74 | 0.643 | 0.744 |
| TE | 708 | 14.62 | 12.35 | 0.685 | 0.819 |
| WR | 1380 | 17.86 | 14.77 | 0.676 | 0.803 |
| rookie | 318 | 34.29 | 29.83 | 0.459 | 0.630 |
| veteran | 2991 | 22.87 | 19.14 | 0.687 | 0.786 |
| information-rich | 1113 | 44.89 | 42.36 | 0.688 | 0.718 |
| low-information | 2196 | 14.76 | 10.20 | 0.340 | 0.582 |
| depth observed at anchor | 1647 | 38.27 | 35.67 | 0.700 | 0.741 |
| prior-season role proxy | 591 | 10.61 | 8.74 | 0.358 | 0.326 |
| depth unavailable | 1071 | 6.61 | 0.74 | 0.048 | 0.020 |

Rookie coverage rises from 0.675 to 0.747, which matters more than the MAE: the baseline's rookie intervals were the least honest thing it produced. The two slices where Spearman falls (`prior_season_role_proxy`, `depth_unavailable`) are the two where MAE is smallest and nearly every player scores near zero, so their rank correlation is close to noise in both models; reporting them unflattered is the point of a predeclared slice.

**A caveat that should not be smoothed over.** CB's holdout MAE (20.19) is *better* than its development MAE (21.91), and its coverage is closer to nominal (0.845 against 0.827). A holdout beating development is a signal to check for leakage, so it was checked: the 2025 fold trains on 2014-2024, the longest training window any fold gets, while the development folds train on 6-10 seasons; and 2025 carries the only draft-time depth observations in the dataset (ADR-018), so its feature rows are the richest in the project. Both explanations are structural and were known before the holdout ran. The seal itself is proved by construction — `tests/model/test_folds_and_holdout.py` poisons every 2025 label and shows a development run stays byte-identical.

**Consequences:** CB is licensed for production, and `--allow-unsealed` may now extend the training window through 2025. Nothing else follows: a passing holdout does not license re-running a development comparison against 2025, and it does not repair the two gates that failed (ADR-034's convergence fallback, ADR-035's tier boundary stability). Those remain published limitations of a model that is otherwise validated.

## ADR-037 — The production model artifact and the 2026 current build

**Date:** 2026-08-19 (Phase 4, post-holdout)

**Status:** accepted

**Context:** ADR-036 licensed CB for production. What remained was to say precisely what "the production model" *is* as a file, and how a build that runs before the 2026 season anchor is allowed to talk about 2026.

**Decision — the model artifact.** `intrinsic-cb-hurdle-v1`, trained on **2014-2025** under window W1, saved as `intrinsic_model_artifact_v1`. Every group (position × scoring preset × quantile, plus the hurdle's two components) is a gzipped LightGBM booster with `mtime=0` so the bytes are reproducible, and each carries its own SHA-256. `ProductionModel.load` verifies every digest before use and refuses a mismatch. The artifact records **two** hashes, because they answer different questions: `feature_set_hash` `7203befaa5be25a2` (`intrinsic_core_v1`) pins which 78 columns the model consumes, and `feature_schema_hash` `c495ba3177dcb989` (`historical_features_v1`) pins the dataset's whole column contract. `assert_compatible` refuses to predict when either disagrees, so a dataset rebuild that quietly changes a column cannot silently change a board. The dataset manifest's content hashes are stored alongside them.

Training through 2025 is gated: `train-production --allow-unsealed` requires the same confirmation token as the holdout and refuses unless the holdout has already been consumed. The seal is one-way and the gate says so in code, not only in prose.

**Decision — what a 2026 build may know.** `current_build_as_of_v1` sets the information cutoff to `min(as_of, season anchor)`. A build that runs *before* the 2026 anchor uses its own timestamp, not the anchor: the anchor is in the future and pretending otherwise would let a build claim knowledge it does not have. A build that runs after the anchor uses the anchor, so a board is not silently refreshed with in-season information. The cutoff, its rule version and both timestamps are written into the build metadata.

Target-season statistics are not loaded at all for a current build (`include_target_statistics=False`). This is correct in general rather than a workaround for 2026 specifically: a preseason board may not consume the season it is predicting, and the historical loader's own behaviour — nflverse returns 404 for a season that has not been played — is a symptom of the same fact, not the reason for the rule.

**Decision — current status is metadata, never signal.** Today's roster status and team annotate a published row and can remove a retired player from the board, but they never enter a prediction. They have no development-era support and could not have been validated, so treating them as features would put an unvalidated input into a validated model.

**Decision — the tier artifacts ship with their failure attached.** `CurrentBuildConfig` records `tier_algorithm`, `tier_algorithm_version`, `tier_penalty` and `tier_stability_gate`, and the production value of the last is **`"fail"`** (ADR-035). A consumer of a Tier artifact can therefore see, from the artifact alone, that the boundaries are not sharply located. Publishing tiers without that field would have been the dishonest option; not publishing them at all would have left the artifact contract untested and the phase's deliverable unbuilt.

**Consequences:** the fixture stub `fixture-stub-0` is replaced by a real, versioned, digest-verified model for every launch preset. `models/` holds the artifact and **is committed**, not gitignored: `PRD.md` section 15 requires every production model artifact needed for deterministic inference to be versioned, and a digest-verified 15 MB of gzipped LightGBM text is the price of a board that can be reproduced months later. `train-production` is the one command that makes it, and a promoted model replaces the previous directory rather than accumulating beside it. The Phase-6 frontend must surface the tier stability caveat rather than drawing a hard line and leaving the reader to assume it was measured as sharp.

## ADR-038 — Point-in-time market history lives on a dedicated long-lived `market-data` branch

**Date:** 2026-08-20 (Phase 5, before the first retained snapshot)

**Status:** accepted

**Context:** ADR-006 requires point-in-time market history to be persisted in a durable versioned mechanism separate from transient Actions artifacts, and ADR-010 makes that history the *only* route to a future learned arbitrage model: MFL's historical export is a season-long aggregate recomputed at request time, so a price we do not capture on the day is a price that can never be reconstructed. `PRD.md` section 15 suggests a dedicated data branch. This ADR is written **before** the first snapshot is retained, because a retention scheme chosen after a month of snapshots exist is a migration rather than a decision.

**Decision — the store.** Snapshots live on a dedicated, permanently long-lived Git branch named **`market-data`**, in the same repository, sharing no history with `main` (an orphan branch). It is not a feature branch, is never merged into `main` and never rebased. Normal Phase-5 source code changes go on the ordinary implementation branch and its pull request; nothing but captures is ever committed to `market-data`.

Reasons, in order of weight: Actions artifacts expire and these captures must not; a data branch keeps a daily binary churn out of code review; Git already supplies immutable history and content addressing; and Phase 7's scheduled workflow can push to exactly the same store without a new mechanism.

**Decision — the layout.** Immutable, timestamp-keyed, one directory per retrieval run:

```text
market/myfantasyleague/<season>/<YYYY-MM-DDTHH-MM-SSZ>/
    manifest.json                        # schemas/market_snapshot_manifest.schema.json
    players.raw.json.gz                  # exact MFL player-directory payload bytes
    cohorts/<cohort_id>/adp.raw.json.gz  # exact MFL ADP payload bytes, one per cohort
    market.normalized.json.gz            # normalized, identity-resolved quotes
status/sleeper/<season>/<YYYY-MM-DDTHH-MM-SSZ>/
    manifest.json
    status.normalized.json.gz            # normalized Sleeper current-status rows
```

The `status/` prefix applies the same discipline to Sleeper current-state captures. It is retained for a different reason from the market prefix — not as future training data, which ADR-044 forbids, but so that a status artifact can be rebuilt offline and byte-for-byte from evidence rather than from a live feed that has since moved. Only the *normalized* Sleeper rows are retained; the 14.6 MB raw player map is not, because nothing downstream reads a field outside the normalized contract.

**Decision — what a snapshot must record.** `manifest.json` carries everything needed to reconstruct the capture's meaning without the code that wrote it: source id, target season, adapter version, source-policy/licence version, capture (retrieval) timestamp, the MFL response `timestamp` **as vendor response metadata only**, the filters actually sent per cohort, `totalDrafts`/`totalPicks` where supplied, raw and normalized content hashes, the player-directory hash, row counts, identity-resolution counts, cohort exact/approximate status, and the code SHA when available.

`source_as_of_utc` is **never** populated from MFL's response `timestamp`. That field is response-generation time (`docs/DATA_SOURCES.md` 13.5) and treating it as a data-as-of time would manufacture a freshness claim.

**Decision — append-only semantics.** A timestamped snapshot directory is immutable. Writing a *new* timestamp appends. Writing an *existing* path whose content hashes match is an idempotent no-op, so a retried workflow run is safe. Writing an existing path with different content **fails closed** and writes nothing. A later snapshot may never mutate an earlier one, and `ffdraft validate-market-history` re-hashes every retained file against its manifest so tampering or truncation is detected rather than assumed away.

**Consequences:** the repository stays private (ADR-016 still binds through Phase 6), so retaining a vendor payload here is a private research cache and not redistribution. `market-data` must be excluded from any future release archive or Pages publish. The store grows by roughly one hundred kilobytes a day at the retained cohort count, which is affordable for the three seasons ADR-010 needs before a learned arbitrage model can be revisited. Phase 7 owns scheduling the capture; Phase 5 ships the command and a manually triggered workflow, which is the minimum needed to prove the path works.

**Revisit if:** the branch outgrows what a clone can carry (move to release assets keyed by the same layout), or the repository becomes public and the retained vendor payloads need a redistribution review first.

## ADR-039 — The Phase-5 cohort sufficiency rule, frozen before its measurement

**Date:** 2026-08-20 (Phase 5, before the cohort measurement was run)

**Status:** accepted

**Context:** ADR-012 chose the widest reliable MFL cohort and required the measurement to be repeated at the start of Phase 5, because the 2026-08-17 counts came from only 410 aggregated drafts. The risk in repeating it is obvious: run the measurement first, then pick the threshold that blesses whichever cohort looks appealing. Phase 4 solved the same problem by writing the rule into code before the run that decided it (ADR-030), and Phase 5 does the same.

**Decision — the rule.** `phase5_cohort_v1`, implemented in `ffdraft.market.cohorts` as a frozen dataclass with a pure evaluator. A candidate cohort is **sufficient** only if all of:

| Clause | Bound | Why this bound |
|---|---:|---|
| priced players | >= 200 | A structural floor. The published board is 300 deep; a cohort pricing fewer than 200 players cannot describe it. |
| cohort drafts (`totalDrafts`) | >= 300 | The 2026-08-17 unfiltered aggregate carried 410 drafts and was already judged usable. Three hundred is the point below which a cohort is thinner than the evidence ADR-012 was written against. |
| top-100 fair-board coverage | >= 0.95 | The top 100 is where a draft is decided. Five missing prices out of a hundred is the most an arbitrage board can lose there and still be worth reading. |
| top-150 fair-board coverage | >= 0.90 | The deeper board tolerates more gaps, because a missing price there costs one row rather than a first-round decision. |
| median `draftsSelectedIn` over priced top-150 players | >= 25 | Cohort-level draft counts can be inflated by drafts that touched only a handful of players. The per-player median is the direct question: how many drafts actually priced *this* player? |
| identity coverage | >= 0.95 | The launch identity threshold (`docs/DATA_CONTRACTS.md` 12). A cohort we cannot join is not a cohort we can publish. |

**Decision — the selection policy.** For each launch (scoring preset, league size) pair, candidates are ordered by **specificity** — a cohort constraining both scoring and league size outranks one constraining a single axis, which outranks the unfiltered aggregate — and the **most specific sufficient** candidate wins. If no specific candidate is sufficient, the widest sufficient candidate wins. If nothing is sufficient, the widest candidate is used anyway and the assignment is flagged `cohort_insufficient`; a market that is thin is still the market, and refusing to publish would help nobody.

Specificity never beats sufficiency. A cohort whose filter text exactly matches a preset but which prices 40 players loses to the unfiltered aggregate, and the rule says so before the numbers are known.

**Decision — HALF-PPR can never be exact.** MFL exposes `IS_PPR` as a boolean. There is no verified filter that means half-PPR, so every HALF assignment is `cohort_approximate` regardless of what the measurement shows. Calling it exact would be a truthfulness failure of exactly the kind ADR-012 exists to prevent.

**Consequences:** the measurement command is offline and reproducible — it reads a retained snapshot (ADR-038) rather than the network, so its report can be regenerated and diffed. The selection is recorded per preset with the filters actually sent, the sufficiency verdict per clause, and the exact/approximate flag. Re-running the rule against a later snapshot may legitimately select a different cohort as the draft season matures; that is the rule working, and each build records which cohort it used.

**Clarification (2026-08-20, before the measurement was run).** The measured population is **core positions only** — QB/RB/WR/TE. No bound above changes; this fixes what the bounds are counted over, and it is recorded here because the first capture made the ambiguity visible before the decisive measurement existed.

MFL's ADP export also prices kickers, team defences and IDP. Every clause above is written about the published board, which is core-position only, and the identity clause cites `docs/DATA_CONTRACTS.md` 12, which defines its threshold over "current model-eligible QB/RB/WR/TE players". Counting a kicker in `priced_players` would inflate it, and counting one in the identity denominator would depress coverage for a population the threshold was never about — the first 2026 capture showed 360 unfiltered rows against 342 non-team-unit rows and 297 resolutions, a difference driven almost entirely by positions this project does not model. `total_rows`, `non_core_rows` and `unclassified_rows` are reported alongside so the whole payload stays visible; only the core-position counts feed the rule.

A row is core when the MFL player directory's position token parses exactly to QB/RB/WR/TE. Rows the directory cannot position at all are counted as `unclassified_rows` and excluded from both numerator and denominator, because an unclassifiable row is a directory gap worth seeing rather than a coverage failure to absorb.

**Revisit if:** MFL publishes a half-PPR filter or a per-cohort dispersion statistic, or a season of retained snapshots shows a clause is systematically un-meetable and the bound was wrong rather than the source.

## ADR-040 — A0, the deterministic arbitrage baseline, frozen before its ranking

**Date:** 2026-08-20 (Phase 5, before the 2026 arbitrage board was produced)

**Status:** accepted. Implements ADR-003 and ADR-010.

**Context:** V1 ships `arbitrage_mode = baseline` (ADR-010). What that baseline computes has to be fixed before anyone looks at which players it likes, for the same reason every Phase-4 rule was.

**Decision — the raw quantity stays raw.**

```text
rank_gap = market_adp - fair_rank
```

Positive means the model would take the player earlier than the market does — a bargain. Zero is agreement. Negative means the market is paying up relative to intrinsic value. This is published on every row and is never replaced by a derived score.

**Decision — draft-region normalization is a log ratio.**

```text
regional_value_gap = ln(market_adp / fair_rank)
```

Zero is exact agreement, positive is a bargain and negative is a market premium, with the same sign convention as `rank_gap`. It is used because the same absolute gap means different things in different regions of a draft: eight picks between fair rank 3 and ADP 11 is a round of value in the first round; eight picks between 180 and 188 is noise. A ratio says that directly, is monotone in `market_adp` for a fixed fair rank, and has no fitted parameter to tune. Both `market_adp > 0` and `fair_rank >= 1` hold by contract, so the logarithm is always finite.

**Decision — the score is a within-preset percentile of `regional_value_gap`.** `arbitrage_score` is the midpoint percentile of a row's `regional_value_gap` within its own (league preset, scoring preset) block, on 0-100, rounded to two decimals, with tied gaps receiving the mean of their group's midpoint percentiles. It is an *ordering*, not a magnitude: 100 means "the biggest bargain signal on this board", not "worth 100 of anything". Percentile rather than an affine transform because the gap's scale depends on how deep the market board runs, and any fixed linear mapping would pin most rows at one end.

**Decision — no reliability multiplier.** Market-data quality reaches the reader through `confidence` and `quality_flags` (ADR-041) and nowhere else. Folding a reliability weight into the score would produce a number that is neither a clean ordering of the signal nor an honest statement about the data, and would make two rows with the same gap incomparable for a reason the reader cannot see.

**Decision — what stays null.** Under `arbitrage_mode = baseline`, `expected_surplus_vorp` and `p_positive_surplus` are null on every row, `market_adp_sd` is null because MFL publishes no standard deviation, and `market_trend` is null until ADR-042's history requirement is met. None of them is approximated by a stand-in.

**Decision — fair rank, not tier.** A0 consumes the promoted median-simulated-VORP fair rank (ADR-034) and never the tier ordinal or a tier edge. Tier boundaries failed their stability gate (ADR-035); fair rank did not, and the two must not be confused. The tier instability therefore does *not* become an arbitrage confidence penalty, because A0 does not depend on the quantity that is unstable.

**Consequences:** the method version `a0_rank_gap_v1` is recorded in the arbitrage method card, in `build_metadata.json` and on the build. Changing the formula is a new version with its own ADR, not an edit. Because the score is a within-block percentile, an arbitrage board cannot be compared row-for-row across presets by score alone — `rank_gap` and `regional_value_gap` are the cross-preset comparable quantities, and both are published.

## ADR-041 — Arbitrage confidence is a data-quality rubric, not a probability

**Date:** 2026-08-20 (Phase 5, before the 2026 arbitrage board was produced)

**Status:** accepted

**Context:** `arbitrage_record.confidence` takes `high|medium|low|unknown`. In baseline mode there is no fitted model and therefore no probability of anything, so the field has to mean something else — or it would be read as one.

**Decision.** `confidence` states **how much the market price on this row can be trusted as a description of the reader's league**. It is computed by `phase5_confidence_v1`, a deterministic rubric over observable source properties, evaluated in a fixed order so that exactly one clause decides and Phase 6 can say which:

1. **unknown** — no market sample size at all.
2. **low** — any of: the cohort failed ADR-039's sufficiency rule; fewer than 30 drafts priced the player; identity resolved through the secondary (unlicensed-mirror) bridge only; the snapshot is older than the market freshness budget.
3. **high** — all of: the cohort is *exact* for this preset; at least 200 drafts priced the player; the snapshot is fresh; identity resolved through the primary bridge or both.
4. **medium** — everything else.

Every fired clause is recorded, so a row can be explained rather than merely labelled.

**Decision — dispersion is described, not scored.** `adp_low`/`adp_high` come from MFL's `minPick`/`maxPick`, which are extreme order statistics: they widen as more drafts are sampled. Two players with different sample sizes therefore cannot be compared on that range, and using it as a confidence input would systematically punish the best-sampled players. It is published, and a `wide_market_range` flag fires when the range spans five rounds or more, but it does not move the confidence tier.

**Observed (2026-08-20).** At the launch sample size — roughly 125 drafts per cohort — `wide_market_range` fires on 1,914 of 2,124 rows. The flag is *true*: a min-to-max span really does exceed five rounds for most players. It is also useless as a discriminator, and the honest response is to say so rather than to move the bound until the flag looks selective. Phase 6 should render `market_adp_low`/`market_adp_high` directly, which every row carries, and treat the flag as a footnote.

**Decision — the flag vocabulary.** `cohort_approximate`, `cohort_insufficient`, `low_market_sample`, `wide_market_range`, `insufficient_trend_history`, `market_snapshot_stale`, `secondary_identity_bridge_only`. Flags are additive and orthogonal to the tier; a `medium` row can carry three of them.

**Consequences:** `confidence` never appears in the score arithmetic (ADR-040), so a reader can sort by signal and filter by data quality independently. Because HALF is permanently approximate (ADR-039), HALF rows cannot reach `high`; that is the source's limitation stated plainly rather than smoothed over.

## ADR-042 — Market trend is a trailing seven-day slope over our own retained snapshots

**Date:** 2026-08-20 (Phase 5)

**Status:** accepted

**Context:** `arbitrage_record.market_trend` exists in the contract and has never had a definition. MFL's historical export cannot supply one (ADR-010): it is a season aggregate, not a series.

**Decision — the definition.** `phase5_trend_v1`. Over the retained snapshots (ADR-038) of the **same source, season and cohort**, in the seven days ending at the latest snapshot, fit an ordinary least-squares line of `market_adp` on days elapsed and publish

```text
market_trend = -slope        # picks per day
```

so that **positive means the player is moving earlier — getting more expensive**, matching the sign convention of `rank_gap`.

**Decision — the sufficiency requirement.** At least **three distinct observation days** spanning at least **three days**. Below that, `market_trend` is null and the row carries `insufficient_trend_history`. The window length never silently changes: a "7-day trend" computed over whatever history happens to exist would mean a different thing on every row, which is worse than no number.

**Decision — the mechanics.** Observations are keyed by canonical `player_id`; cohorts are never mixed, because a change of cohort changes the population being priced and would masquerade as movement. Duplicate snapshot timestamps are impossible by the store's own uniqueness rule; multiple snapshots within one day are all used as observations while still counting as one observation *day*. No outlier rejection: with three to seven points there is nothing to reject robustly, and silently dropping a point is how a trend becomes an artefact.

**Consequences:** the first production snapshot has no history, so **every 2026 launch row publishes `market_trend = null` with `insufficient_trend_history`**. That is the correct output and must not be replaced by a fabricated movement. The infrastructure and its tests exist now, driven by synthetic multi-day histories, so the field becomes informative on its own as the store fills — roughly three days after daily capture begins.

## ADR-043 — Current player status is a separate canonical artifact, and it is annotation only

**Date:** 2026-08-20 (Phase 5)

**Status:** accepted. Implements ADR-011 for the public layer.

**Context:** ADR-011 named Sleeper the current injury/status source. Phase 6 wants that data on the draft sheet. Two ways to deliver it are wrong: copying mutable injury text onto all nine tier rows per player (and again onto every arbitrage row), and letting it near the model.

**Decision — a dedicated artifact.** `player_status.json` / `player_status.csv`, one row per canonical `player_id`, validated against `schemas/player_status.schema.json` (1.0). Phase 6 joins it to Tier and Arbitrage rows in the browser by `player_id`. Keeping it physically separate keeps a nine-fold duplication out of the payload and keeps mutable current-state data out of artifacts whose numbers come from a frozen model.

**Decision — the fields.** nflverse roster status, team and depth-chart position; Sleeper `status`, `injury_status`, `injury_body_part`, `injury_notes`, `injury_start_date`, `practice_participation`, `practice_description`, `depth_chart_position`, `depth_chart_order`; the observation time; the contributing source ids; quality flags. The Sleeper contract (`sleeper_player_status`) moves to **1.1** to carry the three fields it did not previously normalize. All of them are nullable: Sleeper legitimately omits injury fields for healthy players, and making them required would force a fabricated value.

**Decision — the join direction is unchanged.** nflverse → Sleeper on `sleeper_id` (ADR-011/ADR-019). Sleeper's own `gsis_id` remains a cross-check that fails the record closed on a mismatch, never a key.

**Decision — annotation only, proved by test.** No status field may enter the intrinsic feature matrix, a projection, a VORP, a fair rank, a tier, or an arbitrage score. A test mutates every status field on a fixture and asserts the tier and arbitrage artifacts are byte-identical. The intrinsic model was validated on `intrinsic_core_v1` and on nothing else; a current-state field has no development-era support and could not have been.

**Decision — degraded mode.** If Sleeper is unreachable the build does not fail. nflverse roster status still populates the artifact, every Sleeper-specific field is null, the source is recorded `failed` in `build_metadata.json` with a warning, and the Tier board is untouched. A market or status outage may never invalidate or retrain the intrinsic model.

**Consequences:** Sleeper's non-commercial obligation (ADR-013 note, `docs/SECURITY_LICENSE.md` 10) now binds a published artifact, so the attribution and source metadata travel with the build for Phase 6's methodology panel. `player_status` joins the artifact envelope's `artifact` vocabulary, which is an additive change to a 1.0 contract.

## ADR-044 — Richer lagged historical injury features are a 2027 intrinsic-refresh candidate, not a Phase-5 addition

**Date:** 2026-08-20 (Phase 5)

**Status:** accepted

**Context:** integrating Sleeper's current injury data makes an adjacent idea tempting: nflverse publishes historical weekly injury reports, so the intrinsic model could learn from prior-season injury history. It probably should, eventually. It must not now.

**Decision.** No injury feature is added to `intrinsic_core_v1`, no `intrinsic_core_v2` is created, and `intrinsic-cb-hurdle-v1` is not retrained during Phase 5. The idea is recorded as a **2027 intrinsic-refresh candidate** in `docs/MODELING.md` and carried in `SESSION_STATE.md`'s open questions.

**Why not now.** Adding the family would require a new feature-set version, a full historical feature rebuild, a new rolling evaluation and a new candidate comparison — and, critically, a **new final holdout**. The 2025 holdout was evaluated once and is spent (ADR-036). There is no untouched season left to promote a new feature set against in 2026, and promoting one without a holdout would abandon the discipline that makes every other number in this project mean something.

**What a future refresh may investigate** (only if each can be reconstructed leakage-safely against the draft anchor, and the licensing and semantics still hold): prior-season injury-report weeks; repeated limited/DNP practice patterns; prior-season games missed by injury category; recurring body-part or injury-category signals.

**Decision — current annotations are not a substitute.** The Sleeper status artifact (ADR-043) describes *today*. It is not a model feature, it is not a proxy for one, and a reader who sees an injury badge next to a fair rank is seeing two independent things — a frozen preseason projection, and a current-state note the projection has never seen.

**Revisit at:** the 2027 model refresh, which gets its own feature-set version and its own untouched evaluation season.

## ADR-045 — A redraft board may only be priced by redraft drafts (`phase5_cohort_v2`)

**Date:** 2026-08-20 (Phase 5, after the `phase5_cohort_v1` measurement)

**Status:** accepted. Supersedes ADR-039's rule version; ADR-039's bounds are unchanged and its report is preserved.

**Context.** `phase5_cohort_v1` ran and selected `ppr` for the PPR presets and the unfiltered aggregate for the rest — both comfortably sufficient on every clause. Then the resulting board was read, and 2026 rookies came out as enormous market bargains-in-reverse: the model ranked them deep and the market appeared to be taking them in the third round.

Comparing cohorts inside the retained snapshot — which is what a retained store is for — showed why:

| player | `ppr` | `unfiltered` | `IS_KEEPER=N` |
|---|---:|---:|---:|
| Ty Simpson | 35.1 | 35.6 | 162.3 |
| Emmett Johnson | 50.1 | 50.4 | 193.1 |
| Chris Bell | 40.3 | 39.9 | 187.9 |
| Eli Stowers | 28.3 | 28.2 | 131.6 |
| Jeremiyah Love | 11.4 | 11.7 | 31.2 |
| Bijan Robinson | 2.5 | 2.5 | 2.6 |
| Amon-Ra St. Brown | 9.8 | 9.8 | 10.5 |
| De'Von Achane | 17.5 | 17.3 | 18.5 |

Rookies move by a factor of three to five; established veterans do not move at all. That is the signature of **dynasty rookie drafts** inside the aggregate: only rookies are selectable in one, so a rookie's "average pick" there is a pick number in a rookie-only draft, not a redraft ADP. Publishing it as one would say something false about roughly forty players — precisely the truthfulness failure ADR-012 exists to prevent.

A second capture separated the two available format filters and settled which was responsible. `IS_MOCK=0` returns **426 drafts, identical to unfiltered**: there are no mock drafts in this aggregate and that filter does nothing. `IS_KEEPER=N` returns 125. So keeper and dynasty leagues are 301 of 426 drafts, and they are the entire contamination.

**Decision.** `phase5_cohort_v2` adds exactly one clause, and it is a *qualifying* condition rather than a threshold: **a cohort may serve this project's board only if its filters exclude keeper and dynasty drafts.** `config/league-defaults.yaml` declares `season_mode: redraft`; a price for a redraft board has to come from redraft drafts, the same way a PPR preset may not be served by an `IS_PPR=0` cohort. It sits beside the existing "must not contradict the preset" check, not among the sufficiency bounds.

**No bound moved.** `min_priced_players`, `min_total_drafts`, both board-coverage clauses, the per-player median and the identity threshold are all exactly as ADR-039 froze them.

**Consequence, published rather than repaired.** Every keeper-free cohort fails `min_total_drafts` (125 and 115 against 300), because filtering to real redraft leagues necessarily shrinks the cohort-level count. No qualifying candidate is sufficient, so the rule falls through to its own documented last resort: use the widest qualifying candidate and flag it. The 2026 board therefore ships from `no-keeper` (and `ppr-no-keeper` for PPR), with `cohort_insufficient` on every row and consequently `low` confidence on every row, each carrying the reason that fired.

That is a worse-looking confidence distribution than v1 would have produced and it is the honest one. The alternative was a board whose rookie prices were wrong, and ADR-035 already set this project's precedent: when a frozen rule produces an awkward result, publish the result with its failure attached rather than repair it mid-flight.

**Open question, deliberately not answered here.** The evidence suggests `min_total_drafts` may be the wrong instrument for a *filtered* cohort. Filtering shrinks the cohort-level count structurally while leaving per-player evidence intact: `no-keeper` carries 125 drafts but a **median of 105 drafts per top-150 player**, against `ppr`'s 129 and a bar of 25 — and it has the best top-150 board coverage of any cohort measured (0.967). ADR-039 introduced the median clause precisely because cohort-level counts are inflatable, and it is the only clause any format-pure or preset-specific cohort fails. Re-specifying or removing it is a **new decision needing its own rule version and its own evidence**, and it must not be done in the same breath as reading the result it would change.

**A second open question, also left alone.** When nothing is sufficient, the fallback takes the *widest* qualifying candidate, because ADR-039 reasoned that a failed rule should fall back on more data. Here that hands the PPR presets `no-mock-no-keeper` (125 drafts, all scoring) rather than `ppr-no-keeper` (115 drafts, PPR only) — trading scoring specificity for an eight-per-cent larger sample. Whether a fallback should prefer specificity when the candidates are this close is a genuine question, and answering it *after* seeing which cohort it picks is exactly the trap this ADR is written to avoid. The dilution is roughly ten non-PPR drafts out of 125 and is covered by the report's composition caveat.

**Revisit when:** the volume clause is re-specified with evidence, MFL exposes a redraft-only or half-PPR filter, or the non-keeper cohort's own draft count clears the existing bar as the season matures — at which point the same rule selects it without any change at all.

---

### Amendment (2026-08-22, Phase 7) — the production capture did not retain a cohort this rule can choose

**Status:** implementation correction. **No threshold, clause or rule version changed.**

The first production run of `daily-refresh.yml` failed at cohort selection with

```
ValueError: no cohort qualifies for HALF/10-team; a board cannot be priced by a cohort
that contradicts it (ADR-039/ADR-045)
```

and the diagnosis is entirely on this ADR's side of the line. `phase5_cohort_v2` made
"excludes keeper and dynasty drafts" a **qualifying** condition, so a cohort without it can
never be selected however much volume it carries. But `PRODUCTION_COHORT_IDS` — the small set
a routine daily capture retains — was frozen earlier, under `phase5_cohort_v1`, and held
`("unfiltered", "ppr", "std")`. **Not one of those excludes keepers.** A production capture
therefore retained nothing the rule could legally choose, and `select_cohorts` refused to
price a board.

Phase 5 never noticed because the only capture it ever measured was a `study` capture, which
retains all sixteen candidates. The published 2026 board was built from `2026-08-20T14-38-44Z`
— a study snapshot — so the production path had, until now, never actually been run.

**What was wrong, and what was not.** The rule was right and behaved exactly as designed: it
failed closed rather than pricing a redraft board with dynasty rookie drafts in it, which is
the whole point of ADR-045. What was wrong is that the capture retained the wrong bytes. The
fix is therefore to retain what the rule needs, **never** to relax the requirement:

```python
PRODUCTION_COHORT_IDS = ("unfiltered", "no-keeper", "no-mock-no-keeper", "ppr-no-keeper")
```

Those are the three cohorts `_candidates_for` can return for a launch preset, plus
`unfiltered` — which can never be selected, and is retained anyway because ADR-045 was found
by *comparing* a keeper-free cohort against the contaminated aggregate, and keeping the
reference is what lets that comparison be re-run on any day's capture rather than once.
`ppr` and `std` are dropped: neither can be selected now, and `ppr-no-keeper` carries the
PPR axis.

**Why the tests did not catch it.** Every selection test in
`tests/unit/test_market_cohorts.py` handed `select_cohorts` measurements for all sixteen
candidates, so all of them passed on a set no daily capture would ever hold. Two tests now
close that gap: one asserts every launch preset can be priced **from `PRODUCTION_COHORT_IDS`
alone** and that each assignment excludes keepers, and one pins the contaminated reference's
presence and its unselectability.

**Consequences.** Daily captures grow slightly — four cohorts rather than three, still well
inside ADR-038's budget — and the retained per-cohort series for the keeper-free cohorts
continues from `2026-08-20T14-38-44Z`, which already contained all three, so ADR-042's trend
window is not restarted. The two captures taken on 2026-08-22 before this fix hold only the
old three cohorts and are left exactly as they are: the store is append-only, and a snapshot
records what was retrieved at the time, including when what was retrieved turned out to be
the wrong set.

---

## ADR-046 — The frontend presents a tier as a band, never as a line

**Status:** Accepted (2026-08-21, Phase 6)

**Decision:** the Tier Board separates tier groups with **whitespace and a change of surface** and draws no rule, no arrow, no divider stroke and no "value cliff" annotation between two tiers. Tier ordinals and labels are rendered exactly as the artifact publishes them; nothing is merged, split or moved in the browser. The chart, the legend and the player detail each carry a short standing note that tier groups are useful while exact tier edges are statistically soft.

**Why:** ADR-035 published the measurement rather than repairing it. Tier *membership* reproduces — bootstrap ARI 0.865 — while tier *boundaries* do not: boundary agreement 0.239 against a 0.500 bar, only about four of 299 candidate cut sites surviving in a majority across 1,200 replicates, and a median promoted boundary sitting on a 0.55-point P50 cliff against an 80-130-point interval, with P(player below outscores player above) = 0.497. A hard edge drawn between two such players is the interface asserting a quantity the measurement says is not identified. The UX spec's own section 5.4 offered a "value cliff" annotation; that offer predates the measurement and is declined here.

**What was considered and rejected.** Inventing a per-boundary confidence band would be the frontend manufacturing a statistic no artifact publishes — the same failure mode in the opposite direction. The remedy for unstable boundaries is a tier rule with its own evidence (ADR-035's open question), not a visual estimate.

**Consequences:** the board reads as an ordered set of comparable groups rather than as a ladder of thresholds, which is what the measurement supports. A component test asserts the strings "value cliff" and any hard-boundary stroke are absent, so a future contributor restoring the spec's original sketch fails a test rather than quietly overstating the model.

**Revisit if:** a new tier rule passes `phase4_tier_stability_v1`, or a boundary-confidence quantity is added to the tier artifact by a decision with its own evidence.

---

## ADR-047 — The browser explains a shared market condition once, at view level

**Status:** Accepted (2026-08-21, Phase 6)

**Decision:** where every arbitrage row in scope shares one `confidence` label, the Arbitrage view states the condition once at the top of the board and derives the reason from `build_metadata.market.assignments[].failed_clauses`. Per-row confidence remains a table column with an accessible expansion of what the word means. `wide_market_range` earns no per-row badge. `market_trend: null` renders as an em dash with the accessible text "Trend collecting", never as `0`, `Flat` or `No movement`.

To make that possible without embedding a measurement in TypeScript, the arbitrage build now publishes `failed_clauses` on each cohort assignment — the frozen rule's own words, e.g. `total_drafts 125 < 300`. `schemas/build_metadata.schema.json` declares the field; the market block was already `additionalProperties: true`, so no version moved.

**Why:** at launch all 2,122 rows read `low` for one recorded reason (ADR-045). Rendering 2,122 identical unexplained pills would be worse than useless: `confidence` is market-data quality (ADR-041), and an unexplained "low" beside a player's name reads as "the model is unsure about him", which is the opposite of what the field says. The alternative to publishing the clause was hardcoding "125 drafts" in a React component, which would be a stale lie within days as draft season fills the cohort out — the frontend must not become a second, drifting source of a measured number.

The view also shows the median per-player sample size computed over the rows in scope, because the direct evidence is materially better than the cohort-level label suggests and ADR-045 explicitly records that tension rather than resolving it.

**Consequences:** the reason travels in the artifact, so the sentence changes on its own when the market matures and no code changes when the cohort finally clears the bar. A unit test parses the clause format and passes an unrecognised clause through verbatim, so a future `phase5_cohort_v3` degrades to "readable" rather than "invisible".

**Revisit if:** the cohort rule is re-specified, or a build ever publishes a genuinely mixed confidence distribution — at which point the view-level notice suppresses itself and the per-row column carries the signal.

---

## ADR-048 — The frontend's dependency set, and what it is allowed to own

**Status:** Accepted (2026-08-21, Phase 6)

**Decision:** Phase 6 adds four runtime/dev dependencies and no more: **TanStack Table v8** for table state, **d3-scale** and **d3-array** for chart scales and geometry, and **Playwright** for end-to-end and visual QA. React owns state and DOM composition; D3 owns chart mathematics only, and no D3 selection touches a React-managed node. URL query state is `URLSearchParams` read through `useSyncExternalStore`; there is no router.

Explicitly not added: Next.js, any backend framework, Redux, a UI component library, Tailwind, a client router, or a charting framework that would replace the specified geometry.

**Why:** `docs/ARCHITECTURE.md` section 10 already assigned these responsibilities; this ADR records what was actually installed against them. Three tabs do not justify a routing dependency, and a router would add GitHub Pages SPA-fallback complexity to a site that has none. The CSS system is about 900 lines of tokens and component classes, which is smaller than the utility framework that would replace it. TanStack Table is pinned to **v8** rather than the v9 rewrite because v8 is the mature line and this is a launch, not an evaluation.

**One accepted cost.** `eslint-plugin-react-hooks`' compiler rules report that `useReactTable` returns functions the React Compiler cannot memoise, so it skips optimising the two table components. That is a warning, not an error, and it is left visible rather than silenced: the alternative is dropping the table library the UX spec asks for, and two unmemoised components on a 300-row board is not a measurable cost.

**Consequences:** the production bundle is roughly 105 KB gzipped including React. Everything the page needs is a static file under the artifact base path, and an end-to-end test fails any request that leaves localhost, so the browser boundary in `docs/ARCHITECTURE.md` section 3.2 is a check rather than a convention.

**Revisit if:** a chart genuinely needs D3-owned DOM (record the reason), or a fourth board makes hand-rolled tab state worse than a router.

---

## ADR-049 — The retained capture store moves to a separate private repository

**Date:** 2026-08-22 (Phase 7, before the application repository was made public)

**Status:** accepted. **Amends ADR-038**, which is otherwise unchanged and still binding.

**Context:** ADR-038 put the append-only point-in-time capture store on a dedicated long-lived branch named `market-data` **in this repository**, and its consequences paragraph said explicitly that this was safe *because the repository is private*, that the branch "must be excluded from any future release archive or Pages publish", and that the decision should be revisited "if the repository becomes public and the retained vendor payloads need a redistribution review first". ADR-016's amendment then settled that the repository becomes public in Phase 7.

That revisit condition has now fired, and it has an answer that no amount of workflow care could supply: **GitHub visibility is a property of a repository, not of a branch.** There is no private branch inside a public repository. Excluding `market-data` from the Pages artifact and from release packaging — which the workflows do — would not have helped at all, because `git clone` would hand any visitor the whole branch.

What is at stake is not a secret. It is the redistribution position recorded in `docs/SECURITY_LICENSE.md` section 10: the retained MyFantasyLeague payloads and the normalized Sleeper status captures are a **private research cache**, and Sleeper's terms are non-commercial with attribution requested. Publishing thousands of retained vendor payloads is a different act from publishing a derived board with attribution, and it is not one this project has cleared or wants to.

**Decision.** The store keeps every property ADR-038 gave it and changes exactly one: its address.

- It remains **one immutable, append-only, Git-backed history**, on a long-lived branch still named **`market-data`** — keeping the branch name means no command, path, manifest or document that names it has to change.
- That branch now lives in a **separate private repository**, `jeisey/jeisey-tiers-market-data`, where it is the default and only branch.
- The layout, the manifest contract, the immutability rules, the fail-closed rewrite behaviour, `source_as_of_utc` remaining null for MFL, and `ffdraft validate-market-history` are all **unchanged**. The store is the same store; a checkout is byte-identical to what the old branch held.
- The address is recorded in **one place**, `config/source-registry.yaml` (`market_history_repository`), and read from there by `.github/actions/market-data-store`. No workflow contains the literal, and `tests/unit/test_workflows.py` fails if one grows it.

**Decision — the credential.** A workflow in the public application repository cannot use its ordinary `GITHUB_TOKEN` to write another repository's contents, so a **fine-grained token scoped to `jeisey/jeisey-tiers-market-data` alone** is held as the `MARKET_DATA_REPO_TOKEN` repository secret. Following the ADR-017 convention, configuration records the secret's *name* and never its value.

Three rules bound it, and all three are enforced structurally rather than by care:

1. It is passed to `actions/checkout` through its `token:` input and never interpolated into a URL, a log line or a shell variable. The old workflow built `https://x-access-token:${GH_TOKEN}@github.com/...` in a shell block; that construction is gone.
2. Jobs that only read the store check out with `persist-credentials: false`, so no credential survives into a frontend build or a Pages artifact.
3. `ci.yml` — the workflow a pull request from anywhere can run — never references the secret and never checks out the store. A test asserts it.

**Consequences.**

- **The migration was byte-faithful and was verified as such.** Every one of the 40 retained files compares equal, the two trees hash identically (`1e60a552…`), and `validate-market-history` re-hashes the migrated checkout clean: 2 market snapshots (35 files), 2 status captures (4 files).
- **The capture job's privilege went down, not up.** It used to need `contents: write` on this repository to push to a branch here. It now needs `contents: read` here, plus a token scoped to one other repository. Separating the data from the code made the application repository's own permissions strictly narrower.
- **The old branch is deleted before the repository becomes public**, in that order, so no retained payload object is ever reachable in a public repository. It never shared history with `main`: no object on the old `market-data` branch is reachable from `main`, verified before deletion.
- **A contributor's clone no longer carries the store**, which was already true in practice (ADR-038 said to clone it separately) and is now true by construction. `docs/ARCHITECTURE.md` section 6.3 records the clone command.
- **A second repository is a second thing to keep alive.** If the token expires, captures stop; the daily refresh fails loudly at its first job with a message naming the secret, and the deployed site stays live and stale rather than degrading silently.

**Revisit if:** the store outgrows what a clone can carry (move to release assets keyed by the same layout, inside the same private repository), or a redistribution review ever concludes the retained payloads may be published — at which point this ADR is what has to be re-argued, not ADR-038.

---

## ADR-050 — Production deploys are a job graph, not a checklist

**Date:** 2026-08-22 (Phase 7)

**Status:** accepted

**Context:** `docs/OPERATIONS.md` sections 1, 7 and 8 ask for three properties that are easy to state and easy to lose: a stale correct site must beat a fresh incorrect one; two refreshes must not race or deploy out of order; and a critical validation failure must leave production untouched. Written as steps in one job with `if:` guards, all three decay the first time someone adds a step in the wrong place.

**Decision — last-known-good is the graph.** `daily-refresh.yml` is three jobs — `capture` → `build` → `deploy` — and the deploy job's only content is `actions/deploy-pages`. Every gate lives upstream of it, so "a gate failed" and "no deployment happened" are the same event rather than two things that have to agree. Nothing anywhere clears, empties or replaces the live site before a new one is validated, so "no deploy" leaves the previous deployment serving.

The Pages artifact is uploaded as the **last** step of the build job, after artifact validation, the frontend build, the rendered-board verification and the artifact-boundary assertion. There is no window in which a build that failed a gate exists as a deployable artifact.

**Decision — capture is separated from replaceable work.** The capture job appends to the immutable store and pushes, and only then does anything replaceable run. A retained snapshot is future training evidence that MFL's historical export cannot reconstruct (ADR-010), so if the frontend later fails to build, the correct outcome is that the history records what was observed *and* the old site stays live. That is why capture is its own job and why the store's push happens before the build begins.

**Decision — concurrency queues, it does not cancel.** The workflow-level group is `production-refresh` with `cancel-in-progress: false`. Cancelling is the dangerous option here: a cancellation between `git commit` and `git push` drops a validated snapshot on the floor. Queueing also supplies the ordering `docs/OPERATIONS.md` section 7 asks for — a superseding run waits, so it deploys *after* the run it superseded, and an older build can never land on top of a newer one. The deploy job additionally joins the `pages` group, again without cancellation, so it serializes against any other publisher.

**Decision — the forced-failure proof breaks a real invariant.** `workflow_dispatch` carries a `force_validation_failure` boolean, default false and unreachable from the schedule (`inputs` is empty on a scheduled run, and the step asserts the event name as well). When set, the run does **not** call `exit 1`. It corrupts a generated artifact so that VORP quantiles are no longer non-decreasing, and then runs the ordinary `validate-artifacts` gate. What rejects the build is `artifact.non_monotonic_quantiles` — the production check listed in `docs/ARCHITECTURE.md` section 12 — not a switch added for the test. A proof that only demonstrates `exit 1` works proves nothing about the gate.

**Decision — least privilege per job.** The workflow grants `contents: read`. The deploy job alone adds `pages: write` and `id-token: write` and uses the `github-pages` environment. `actions/configure-pages` lives in the deploy job for that reason: it is the only step needing a `pages:` scope for its own sake, and putting it in the build job would have meant widening that job's permissions for an output nothing consumes.

**Consequences:** the properties above are checkable, and `tests/unit/test_workflows.py` checks them — job dependencies, per-job permission maps, the environment name, both `cancel-in-progress: false` settings, the off-the-hour New York schedule, the dispatch-only guard on the proof flag, and the absence of any training command from the refresh. A change that quietly merges the deploy into the build, or grants the build a Pages scope, fails a test rather than passing review.

**Revisit if:** a second deployable surface appears (the `pages` group would then need to be shared deliberately), or Pages gains a documented atomic rollback that would make a different failure posture possible.

---

## ADR-051 — Retraining is gated on evidence, and cannot promote or deploy

**Date:** 2026-08-22 (Phase 7)

**Status:** accepted

**Context:** `docs/OPERATIONS.md` section 2.3 specifies a weekly retrain during draft season. Implemented literally in August 2026 that would be actively harmful. `intrinsic-cb-hurdle-v1` is trained on 2014-2025; 2025 was the sealed final holdout and has been **spent** (ADR-025, ADR-036), so it cannot become a fresh untouched holdout again; and 2026 has not been played. A weekly job would therefore either rebuild the same artifact from the same rows, or — the real hazard — pull partial in-season 2026 outcomes into a training corpus and present the result as an improvement.

**Decision — the gate is evidence, not a calendar.** `scripts/retrain_gate.py` asks one question: is there a season after the model's last training season whose **fantasy horizon** is complete in the upstream weekly statistics? The horizon rather than the NFL calendar, because that is what the label builder sums over and it moved from weeks 1-16 to 1-17 at 2021. The gate is conservative in both directions it could be wrong: an unplayed season (nflverse answers 404) is "no", and an in-progress season whose weekly file stops short of the horizon is "no". Only a finished season is "yes".

"Nothing to retrain" exits **0**. It is a correct outcome, not a failure, and the run summary says which season was checked and why it did not qualify.

**Decision — the workflow cannot promote.** `retrain.yml` holds `contents: read` at every level, has no `pages:` scope, contains no Pages action, never pushes, and asserts at the end that `models/` is unchanged. What it can produce is a **candidate**: development-fold evaluation reports, attached to the run as an artifact. Promotion needs, in order, a new evaluation/holdout protocol; a deliberate `ffdraft train-production` run with its confirmation token and a written reason; a regenerated model card; and then an ordinary `daily-refresh`, which is the only path to Pages.

The confirmation token stays out of the repository and out of GitHub secrets on purpose. A token in a secret is a token a scheduled job can use, which would convert a deliberate human act into an automatable one.

**Decision — the seal is not re-litigated here.** The candidate job runs `evaluate-intrinsic` on development folds only. `load_modeling_dataset` drops sealed seasons before anything sees the frame and the fold generator refuses to build a fold that validates one, so the job cannot reach the holdout even if asked; `--final-eval` needs a fixed token and a written reason and does not appear in the workflow.

**Consequences:** the weekly schedule is kept, and in the 2026 preseason every run stops at the gate in about two minutes. That is deliberate — the gate is exercised continuously rather than being a claim in a document, and the run history records that the evidence did not change. When 2026 completes, the same gate turns green on its own and produces a candidate report; what it will *not* do is promote it, because ADR-044's injury-feature question and a fresh holdout protocol both have to be answered first.

**Revisit at:** the 2027 refresh, which needs completed 2026 labels, a new holdout protocol, and a decision on ADR-044's historical injury features.

---

## ADR-052 — Market-data confidence is resolving on its own; do not re-specify `min_total_drafts` to make it pass

**Date:** 2026-08-24 (Phase 7 operations, four days after the first production capture)

**Status:** **Proposed — awaiting owner review.** Nothing in the code changes on the strength of this ADR; its whole point is to argue for *not* changing something.

**Context.** Every arbitrage row this project has ever published reads `low` confidence, for one recorded reason: the keeper-free cohort the frozen rule must use (ADR-045) fails a single clause, `min_total_drafts 300`. ADR-045 left an explicit open question about it:

> Whether `min_total_drafts` is the right instrument for a filtered cohort. It is the only clause any format-pure or preset-specific cohort fails, and **filtering shrinks the cohort-level count structurally** while leaving per-player evidence intact.

That "structurally" was the suspicion: that requiring `IS_KEEPER=N` caps the achievable count, so the clause could never pass and was measuring the filter rather than the evidence. Under that reading the clause is a badly chosen instrument and wants a new version.

**The measurement that settles it.** Four days of production captures, same cohort, same filter, same rule:

| observation day | `no-mock-no-keeper` total drafts | change |
|---|---:|---:|
| 2026-08-20 | 125 | — |
| 2026-08-22 | 143 | +18 |
| 2026-08-23 | 188 | +45 |
| 2026-08-24 | 227 | +39 |

Mean 25.5 drafts/day over the span; 39/day most recently; and **accelerating**, which is what late August does to fantasy drafting. The bar is 300. The gap is 73. At the recent rate that is **about two days**; at the mean, three.

**The cohort-level count was not structurally capped. It was early.** The filter has not changed and the count has grown 82% in four days. A rule that would have been re-specified on 2026-08-20 to "fix" a thin sample is about to pass unaided, on the sample maturing, which is exactly what a volume clause is for.

**Decision (proposed).**

1. **Do not touch `min_total_drafts`, `phase5_cohort_v2`, or any other clause.** Not now, and specifically not in the window where it is about to cross. ADR-045 named the trap — "re-specifying it must not happen in the same breath as reading the result it would change" — and the current timing is the worst possible version of it: a change made this week could never be distinguished from the season arriving.
2. **Let it cross, then re-read.** Once a build publishes a cohort at or above 300, the confidence label moves off `low` under the existing rubric with no code change, and ADR-047's view-level explanation suppresses itself once the distribution stops being uniform. That is the designed behaviour, and observing it is worth more than any argument here.
3. **Re-open the instrument question only if it does *not* cross** by roughly the first week of September. If the count stalls short of 300 at peak draft season, the structural reading was right after all, and *that* is the evidence a new rule version would need.

**What else the four days established.**

- **The store accumulates, and the trend went live.** Nine snapshots across four observation days now satisfy ADR-042's "three observation days spanning three days", and `market_trend` is populated on the board for the first time. It surfaced by breaking a stale check — `verify:board` was asserting that every trend cell renders an em dash, which was true only while the store was too young. A green product failed a test that had frozen the launch condition; the check now compares against the artifact's own value. Auditing the rest of that script for the same species found a second instance: the tier row's name assertion stripped the injury badge out of the cell text with a pattern that assumed the badge always reads `IR · Knee`, so a designation reported without a body part would have failed a correct board. It now reads the name from its own element. **A verification check must assert the contract, not the day's data.**
- **`wide_market_range` (ADR-041) should be re-measured, not re-specified.** It fires on ~90% of rows and was called "true and useless at this sample size". A min-to-max span narrows as drafts accumulate, so the flag may begin discriminating on its own for the same reason confidence will. Measure it after the crossing before deciding it is the wrong flag.
- **Identity coverage over the whole priced payload is drifting down** — 0.921 → 0.836 on the selected cohort across the four days — because a larger aggregate prices more obscure players. This is *not* the number `min_identity_coverage` judges, which is measured over core positions only (ADR-039 clarification) and is not close to its bound. Recorded as a thing to watch, not a finding.

**Consequences if accepted:** nothing is implemented. The site keeps publishing `low` and explaining exactly why, which is honest, until the evidence changes it. The open question in ADR-045 narrows from "is this the wrong instrument?" to "did it release on time?", which a week of captures answers by itself.

**Revisit at:** the first build whose selected cohort reports ≥ 300 drafts, or 2026-09-07 if that has not happened.

---

## ADR-053 — The free market-source sweep: what exists, what each would fix, and why none of it ships yet

**Date:** 2026-08-24 (Phase 7 operations)

**Status:** **Proposed — awaiting owner review.** No source is added, no policy changes, and `config/source-registry.yaml` is untouched by this ADR.

**Context.** The owner asked what else is out there: whether FantasyPros is being used, whether other free market-price sources exist, and whether sportsbook odds belong anywhere. `docs/DATA_SOURCES.md` §16 already records the *shape* of a multi-source study; this ADR records the **sweep's actual findings** so a Phase-8 session inherits candidates rather than a search.

**Evidence quality, stated up front.** This sweep was done by search from an egress-restricted environment: `help.fantasyfootballcalculator.com` and other candidate hosts answer 403 to `CONNECT` (ADR-009). **No endpoint below has been verified against the live service**, and none may become a production dependency until a runner-side probe records its contract and terms, per `AGENTS.md` §5. Everything here is a lead, not a verification.

### What is used today

**MyFantasyLeague only.** And, answering the question directly: **FantasyPros is used nowhere.** It is registered (`fantasypros_ecr_via_dynastyprocess`), terms-reviewed, `benchmark_only`, `criticality: optional` — and carries **no roles**. It is not fetched by any build, appears in no schema and no artifact, and its name is in `ffdraft/quality/forbidden.py`, so the intrinsic firewall actively rejects it as a feature. Approval to compare was granted in ADR-014 and never spent; no benchmark comparison was ever wired up.

### The candidates

**1. Fantasy Football Calculator — the only genuinely new candidate.**

A documented free REST ADP API (`/api/v1/adp/{format}?teams={n}&year={y}`) whose published terms reportedly permit personal *and commercial* use with attribution and a politeness rate limit. If that holds on inspection it is a **better redistribution position than anything else in the sweep, FantasyPros included.**

What it would fix, and it is the thing MFL structurally cannot: **exact cohorts.** `format` × `teams` gives PPR/12 as a real intersection rather than an approximation. ADR-012 exists because MFL's exact intersections are thin or empty, and every assignment this project publishes is flagged `approximate`.

What it would introduce: **a population problem in exchange.** FFC's ADP is generated from **mock drafts run on its own site**. MFL's aggregate is real league drafts. Phase 5 spent its cohort study proving that population differences are not cosmetic — dynasty rookie drafts inside the MFL aggregate moved rookie prices 3–5× while veterans did not move at all (ADR-045). A mock-draft population is a different distortion, not an absent one: mocks are cheap, abandonable and drafted by a self-selecting audience. Swapping one approximate cohort for one exact-but-mock cohort is not obviously an improvement, and asserting that it is without measuring would repeat the mistake ADR-045 was written to prevent.

**2. FantasyPros.** A public API exists with a free tier tied to membership. Repository policy is unchanged: `benchmark_only`, redistribution forbidden, so it cannot feed a published artifact. Promoting it is a source-policy decision needing its own ADR and evidence (ADR-014 as amended, `docs/DATA_SOURCES.md` §16). Nothing in this sweep changes that.

**3. Sleeper.** Still no verified global or platform-wide ADP endpoint; drafts are addressable only by a known user, league or draft id. Unchanged from §16, and the crawl design it would require — discoverability, representation bias, duplicate-league protection, rate limits, and a non-commercial licence that already binds what this site publishes — remains out of scope.

**4. Sportsbook odds — a category error, and worth saying plainly.**

Free-tier odds APIs exist (The Odds API, SportsGameOdds, SharpAPI; all key-gated with quotas). **None of them is an ADP substitute.** Arbitrage in this project is *fair rank versus draft cost*. Odds price expected production and game outcomes — they are neither the fair rank nor the cost, so they cannot enter the A0 comparison at all without redefining what arbitrage means.

They also cannot enter the intrinsic model. `AGENTS.md` §8 names "sportsbook/fantasy market rank intended as a proxy for crowd expectation" in the forbidden-feature list explicitly, and season win totals and player props are exactly that. Using them would breach the invariant the whole project is built around.

That leaves two legitimate homes, both new decisions rather than integrations: an **external benchmark** for evaluating the intrinsic model out-of-sample, or a **separately labelled published signal** that is not arbitrage and is not a model input. Either would also add a first API key with a quota — a new secret, a new failure mode, and a rate limit that a daily build must respect.

**5. Aggregators and scrapers** (BeatADP, RotoWire, DraftSharks, marketplace scrapers). Display products, not licensed APIs. Scraping them is outside `docs/SECURITY_LICENSE.md` §8 and is not considered.

### Decision (proposed)

1. **Add nothing now.** MFL remains the sole production price source.
2. **Sequence this behind ADR-052.** The motivating complaint is `low` confidence, and the measurement says that resolves itself in about two days. If it does, the case for a second source shrinks to a smaller and much more precise question — *exact cohorts, and HALF-PPR, which a boolean `IS_PPR` can never represent* — worth its own study rather than a rushed integration.
3. **If a study happens, Fantasy Football Calculator is the one to probe first**, and the probe must answer, on the runner: the endpoint contract and response fields; the terms text verbatim; whether the population is mock-only and in what proportion; per-player sample sizes at the cohorts we would actually use; the player-identity join path (MFL took two independent id bridges to reach 100% on core positions — FFC's is unknown); rate limits; and whether it publishes a data-as-of time, which MFL does not.
4. **Record it as `verify_before_use`** in the registry when and only when a study is commissioned. Until then it stays out of the registry entirely, because a listed source implies a checked one.
5. **The composite warning in §16 stands and is repeated here because it is the easiest thing to get wrong:** if more than one price source is ever approved, do not average the numbers. Normalize to source-specific quotes first — the shape `market_quote` 2.0 already has — and freeze the consensus formula **before** looking at which players it flatters.

**Consequences if accepted:** the sweep is on the record with its evidence quality labelled, the "why aren't we using FantasyPros" question has a durable answer, and nobody re-derives the odds-are-not-ADP argument. Nothing in the pipeline moves.

**Revisit at:** whichever comes first — ADR-052 resolving, or a decision to commission the multi-source study in `docs/DATA_SOURCES.md` §16.

---

## ADR-054 — Why the top-150 coverage gate failed on 2026-08-26, measured rather than guessed

**Date:** 2026-08-26 (Phase 7 operations)

**Status:** **Accepted** for the one change it makes (wiring the reviewed-alias file into the production capture). **The larger question it uncovered is Proposed — awaiting owner review.**

**What happened.** The scheduled refresh ([32963529477](https://github.com/jeisey/jeisey-tiers/actions/runs/32963529477)) failed a critical gate:

> `[critical] arbitrage.top_board_priced` — the market layer has no price for too much of the published top-150 board — observed: worst block 94.0%; expected: >= 95%

Nine of `HALF/redraft-10`'s top 150 had no price. The bar is 95%; nine misses is 94.0%. Last-known-good held and the 2026-08-25 site stayed up.

### The nine, each one accounted for

The retained snapshot `2026-08-26T11-29-17Z` and the live 2026 nflverse roster answer this exactly. There is no residual "and some others":

| blocker | in MFL's payload? | on the 2026 NFL roster? | why it has no price |
|---|---|---|---|
| Stefon Diggs #77 | **yes**, ADP 115.33 / 201 drafts | **no** | in the payload but unresolvable |
| Deebo Samuel #80 | **yes**, ADP 124.23 / 178 drafts | **no** | in the payload but unresolvable |
| Keenan Allen #104 | **yes**, ADP 155.18 / 96 drafts | **no** | in the payload but unresolvable |
| Theo Johnson #115 | only in `ppr-no-keeper`, ADP 221.15 | yes | priced in a cohort a HALF board may not use |
| Mason Taylor #133 | only in `ppr-no-keeper`, ADP 203.00 | yes | priced in a cohort a HALF board may not use |
| DeMario Douglas #148 | only in `ppr-no-keeper`, ADP 234.27 | yes | priced in a cohort a HALF board may not use |
| Zach Ertz #126 | **no** | no | MFL does not price him |
| Ricky Pearsall #140 | **no** | yes | MFL's list does not reach him |
| Dawson Knox #150 | **no** | yes | MFL's list does not reach him |

**This was not drift and not a regression.** Nothing in the pipeline changed between the run that passed on 2026-08-25 and the one that failed. What moved was the *board*: `build-current` reprojects daily, and one more permanently-unpriceable player crossed into `HALF/redraft-10`'s top 150. The gate had been sitting one player above its bar.

### Finding 1 — both "independent" bridges terminate at the same roster-scoped registry

`_resolve_one_quote` reads:

```python
primary   = registry.lookup(IdNamespace.ESPN, espn_by_mfl_id.get(external_id))
secondary = registry.lookup(IdNamespace.GSIS, gsis_by_mfl_id.get(external_id))
```

Both end in `registry.lookup`, and `build_registry` builds the canonical player set **from the current season's roster**, deliberately: "an unlicensed mirror must not be able to expand the canonical player set". The consequence is structural rather than accidental — **a player who is not on an NFL roster cannot be resolved by any bridge, however good the crosswalk is.** Diggs, Samuel and Allen are each priced by a real market with 96–201 drafts behind them and are each unrostered, so the market layer cannot represent them at all.

Six offensive rows fail to resolve in the selected cohort. Five are unrostered (Diggs, Samuel, Allen, Najee Harris, Darren Waller). The sixth is the one recoverable case, below. The other 47 unresolved rows are IDP and team defenses, which this project does not model — that is the whole of the "identity coverage is drifting down" effect ADR-052 flagged as a thing to watch, and it turns out to be benign.

### Finding 2 — the reviewed-alias escape hatch was never wired into production

`config/identity-aliases.yaml` exists, `load_alias_map` exists, the resolver implements the alias path with a fail-closed conflict rule, `docs/DATA_CONTRACTS.md` §2.3 documents it, and `ffdraft.pipeline.fixture_pipeline` passes it. **`ffdraft.market.capture` — the module every production snapshot actually runs — never loaded the file.** The hatch was shut in exactly the place it was built for. A review nobody loads is not a review.

**This ADR fixes that**, and adds the one alias the evidence supports: MFL `17482` is on the 2026 roster as `full_name="Mike Washington", team=LV, position=RB, gsis_id="00-0040878", status=ACT`, and MFL prices him at ADP 136.53 across 156 drafts — but his roster row publishes **no `espn_id`**, so the primary bridge has nothing to look up and the crosswalk has no row for him either. The alias is read off the live roster, not inferred from a name.

### What this change does *not* do

**It does not clear the gate.** Mike Washington is not among `HALF/redraft-10`'s nine, so that block stays at 94.0% and the next refresh fails the same way. This is stated plainly rather than discovered by running it: of the nine, three need a canonical player that does not exist, three are priced only in a cohort a HALF board may not use, and three are not priced by MFL at all. **Nothing in the identity lane can reach any of them.**

### Finding 3 — the question actually worth deciding

Four of the nine are **free agents on no NFL roster that the board ranks inside its top 126 of a ten-team redraft league** — Stefon Diggs at fair rank 77. The market is not failing to price them; the market is correctly declining to. The board is ranking players who cannot be drafted onto an NFL team, and the coverage gate is the first thing that noticed.

That is a board-universe defect, not a market defect, and fixing it would also fix most of the coverage shortfall. It is **not** made here, because it changes which players a published board contains and therefore renumbers every fair rank — a contract change that belongs to the owner (`AGENTS.md` §12, §19).

**Options, for the owner:**

1. **Restrict the published board to rostered players.** Most likely correct as a product: a redraft board should rank draftable players. It is an *eligibility* filter, not a model feature, so it does not put status into the model (ADR-030's annotation-only rule survives). It renumbers fair ranks and changes tier composition, so it needs a rule version and a re-measurement.
2. **Leave the board alone and accept that the gate fails whenever a marginal unrostered player crosses into a top-150.** Honest, and stops the site refreshing on an ordinary August morning.
3. **Reconsider the failure's blast radius** — one block below the bar currently withholds the tier board too, which has no market dependency at all. Rejected for now on the owner's instruction to fix the input rather than the gate; recorded because it will come back.

A fourth thing is worth measuring before any of the above: for the PPR blocks, `ppr-no-keeper` is the *exact* cohort, prices 254 players against `no-mock-no-keeper`'s 249, and covers three of these blockers — yet the fallback rule picks the **widest** qualifying candidate, so it went unused. That is ADR-039/ADR-045 territory and must not be changed in the same breath as reading the result it would change.

**Decision.** Wire the alias file into the production capture path; add the one measured alias; record the diagnosis. Change no threshold, no cohort rule, and no board universe.

**Consequences.** The escape hatch works for the first time in production, and one real price is recovered. The refresh still fails until option 1, 2 or 3 is chosen. Nobody has to re-derive any of the above: the table names all nine.

**Revisit at:** superseded the same day — see the correction below.

### Correction, 2026-08-26 (later the same day): Finding 3 was wrong

**Finding 3 above is retracted.** It claimed that Stefon Diggs, Deebo Samuel, Keenan Allen and Zach Ertz are "free agents on no NFL roster that the board ranks inside its top 126", and recommended restricting the published board to rostered players. **They are on NFL teams.** The owner said so, and nflverse's own player master agrees:

| player | `latest_team` | `status` | `last_season` | `espn_id` |
|---|---|---|---|---|
| Stefon Diggs | WAS | ACT | 2026 | 2976212 |
| Keenan Allen | IND | ACT | 2026 | 15818 |
| Deebo Samuel Sr. | SF | ACT | 2026 | 3126486 |
| Najee Harris | NYG | ACT | 2026 | 4241457 |
| Darren Waller | CAR | ACT | 2026 | 2576925 |

Those `espn_id` values are exactly what MFL publishes for them, so the primary bridge would have resolved every one of them on sight.

**How the error was made, which is the part worth keeping.** The claim rested on a single check: a name and `espn_id` search against `nflreadpy.load_rosters(seasons=[2026])`. They are absent from that file. From "absent from the roster file" the conclusion drawn was "not on a roster" — treating one source as the world. The file is 2930 rows, about 91 per team, so it *looked* complete, and nothing prompted a second source. `nflreadpy.load_players()` was one call away and answers the question directly.

The right lesson is not "check twice". It is that **a source's silence is not evidence of absence**, and that this repository already has a rule for exactly this shape — a source marked `verify_before_use` cannot become a production dependency until the check is done — which was applied to vendors and not to the source we trusted most.

**The real root cause, and the fix,** are in **ADR-055**: `load_rosters(2026)` omitted 101 skill-position players who are on NFL rosters, the canonical registry is built from that file alone, and both market bridges terminate at `registry.lookup`. So the price existed, the player existed, and the board could not join them.

**What survives from ADR-054:** the per-blocker table's *structure* (three groups: unresolvable, priced only in a cohort the block may not use, not priced at all) and its membership, except that the first group's cause was identity, not roster status. Finding 1 stands but is sharpened by ADR-055: both bridges do terminate at the registry, and that is precisely why the registry's universe has to be right. Finding 2 stands unchanged — the alias hatch really was never wired in, and the Mike Washington alias is still correct and still needed, because he *is* in the roster file and it is his `espn_id` that is missing.

**Also retracted:** the recommendation to restrict the published board to rostered players. On the corrected facts it would have removed three genuine starters from the board to fix a defect in our own identity layer. The owner's second point stands on its own merits regardless: a player between teams still carries a real ADP, because drafters price the job he is expected to get, so roster presence was never the right gate for *publication* either.

---

## ADR-055 — The canonical registry is built from nflverse's player universe, not from its roster file alone

**Date:** 2026-08-26 (Phase 7 operations)

**Status:** **Accepted and implemented.**

**Context.** `ffdraft.identity.registry.build_registry` builds the canonical player set by iterating a season roster frame, and `ffdraft.market.identity.load_market_identity` supplied `load_rosters(season)`. Its docstring gave the reasoning: "a current capture is asking *who is on a roster now*, which is exactly what that season's roster answers."

It does not answer that. Measured on 2026-08-26:

| | count |
|---|---:|
| `load_rosters(2026)` rows | 2,930 |
| `load_players()` rows with `last_season >= 2026` | 3,099 |
| …of those, QB/RB/WR/TE | 972 |
| **skill-position players active in 2026 and *missing* from the roster file** | **101** |

Among the 101: Stefon Diggs (WAS, ACT), Keenan Allen (IND, ACT), Deebo Samuel Sr. (SF, ACT), Brandon Aiyuk (SF), Joshua Dobbs (DET). Not fringe names — starters, and three of them were the direct cause of a critical production gate failure (ADR-054).

**Why this is severe rather than cosmetic.** Both market bridges end at `registry.lookup`:

```python
primary   = registry.lookup(IdNamespace.ESPN, espn_by_mfl_id.get(external_id))
secondary = registry.lookup(IdNamespace.GSIS, gsis_by_mfl_id.get(external_id))
```

A player the registry does not contain is unreachable by *either*, no matter how good the crosswalk is — and unreachable by a reviewed alias too, which fails `alias_target_unknown` for the same reason. Two bridges are a defence against a **wrong** answer. Neither is a defence against an **absent** one. So the failure mode is silent: MFL published Diggs at ADP 115.33 across 201 drafts, nflverse had him on Washington, and the board could not join the two.

**Decision.** The canonical spine for a current capture is the season roster **plus** nflverse's own player master, filtered to players whose `last_season` reaches the target season.

- A new `NflversePlayersAdapter` emits `ROSTER_CONTRACT` rows from `load_players()`. Same contract because it is the same thing: more rows of the same spine.
- `supplement_roster` concatenates, and **the roster wins every collision.** The roster record is richer — depth chart position, Sleeper id, sportradar and yahoo crosswalks — and the supplement exists to add players, never to restate them.
- The count is reported as a passing check, `identity.roster_supplemented`, so a build log says how many players the two files disagreed about. A supplement that suddenly adds hundreds or none means the upstream files disagree about who is in the league, and that is worth seeing before it is worth debugging.

**What this does not do.** It does not weaken ADR-019. The rule that an unlicensed mirror may not expand the canonical player set is about the dynastyprocess crosswalk; `load_players()` is nflverse's own master file under the same licence as the roster, and its schema was recorded in Phase 0 (`tests/fixtures/source_schemas/nflverse_players.schema.json`, captured 2026-08-17). No bridge is relaxed, nothing resolves by name, and a disagreement still fails closed.

**Accepted cost.** `load_players()` publishes no `sleeper_id`, `sportradar_id` or `yahoo_id`, so a supplemented player carries no Sleeper join and picks up **no injury or status annotation**. That is the right trade in this direction: status is annotation-only and never a model input (ADR-030), while a missing *price* silently distorts the arbitrage board. It should be revisited if a supplemented player ever needs a status badge.

**Validation.** Re-resolved the real retained capture `2026-08-26T13-45-18Z` through the production code path, with the secondary bridge deliberately withheld to prove the nflverse-native primary is sufficient:

| spine | resolved rows | Diggs / Allen / Samuel |
|---|---:|---|
| roster only | 258 | none |
| roster + players | **263** | all three |

`identity.roster_supplemented: 272 player(s) added to 2930 roster row(s)`. Six new unit tests pin that the supplement only adds, that the roster wins a collision, that players who left the league are excluded, and the end-to-end case: a priced player missing from the roster file resolves on the primary bridge only once supplemented.

**Expected effect on the gate that started this.** `HALF/redraft-10` had eight unpriced players in its top 150. Three of them — Diggs, Samuel, Allen — are recovered by this change, taking that block to 145/150 (96.7%) and clear of the 95% bar. The remaining five are not identity problems and are ADR-056's subject.

**Consequences.** Market coverage rises by a few players a day, permanently. No threshold, cohort rule, model or board universe changed. The alias hatch stays as the escape route for the residue — the Mike Washington case is unaffected, because he *is* in the roster file and it is his `espn_id` that is missing.

**Revisit at:** the first build where `identity.roster_supplemented` reports an implausible count, or a supplemented player needing a status annotation.

---

## ADR-056 — What `top_board_priced` actually measures, and whether one market source is enough

**Date:** 2026-08-26 (Phase 7 operations)

**Status:** **Proposed — awaiting owner review.** Section 1 clarifies existing behaviour and changes nothing. Section 3 was rewritten on 2026-08-26 from a **runner probe of the live endpoints** rather than from search; it changed the recommendation twice. No source is added, no adapter is written, `config/source-registry.yaml` is untouched, and the pipeline does not move.

### 1. The gate, stated plainly

The owner asked whether `min_top150_coverage >= 95%` means "at least 95% of players across MFL drafts need to be present in the top 150". **It is the other direction, and the difference matters.**

For each published block — one of the nine (scoring × league size) combinations — the check takes **our own board's top 150 by fair rank** and asks what fraction of *those players* the market has a price for. `coverage_summary` then takes the **minimum across the nine blocks**, deliberately: "a mean would hide the case this gate exists to catch: eight healthy presets and one that lost its cohort."

So it measures **how much of our board the market can price**. It says nothing about how much of the market our board covers, and nothing about draft volume. Nine missing prices out of 150 is 94.0%, and that is what failed on 2026-08-26.

Two properties are worth knowing:

- **`TOP_BOARD_PRICED_MINIMUM = IDENTITY_COVERAGE_MINIMUM`.** The board-coverage bar is an *alias* of the identity-resolution bar. They measure different quantities — "can we resolve the names a vendor sent" versus "does the vendor price the players we rank" — and 0.95 was chosen for the first and inherited by the second. **Proposed:** give it its own named constant and a stated derivation, changed at a moment when nobody is reading a number it would move.
- **The bar is hardest exactly where the board is thinnest.** In a ten-team league a top-150 *is* the entire draft, and ranks 100-150 are near-replacement players whose ordering is close to noise; in a fourteen-team league 150 picks is under eleven rounds of players who matter. The same constant is applied to all nine. Not wrong, but not derived either.

### 2. Is MFL systemically too thin? Measured: yes

The owner's instinct is right, and the numbers are not close. From the 2026-08-26 capture:

| | |
|---|---:|
| rows in the selected cohort (`no-mock-no-keeper`) | 346 |
| of those, resolvable players (not team units) | 319 |
| **actually priced and joined** | **~266** |
| total drafts behind that cohort | 265 |
| deepest resolved ADP | 222.7 |
| what the board publishes | 9 blocks × 150 deep |

A ~266-player priced universe against nine 150-deep boards leaves almost no margin, which is why a single player crossing into a top 150 flipped a gate. And 265 drafts in the last week of August is a thin sample for a public aggregate.

**But adding a source would not have fixed 2026-08-26.** Of `HALF/redraft-10`'s eight blockers: **three** were identity (Diggs, Samuel, Allen — fixed by ADR-055), **three** were priced by MFL only in `ppr-no-keeper`, a cohort a HALF board may not use, and **two** were not in MFL's list at all. A second source addresses the last two and possibly the middle three. It would not have touched the largest group. Diagnosing before buying is the whole point.
### 3. The FFC probe — measured on a runner, 2026-08-26

ADR-053 and the first draft of this ADR could only say "unverified", because this project's
development sandbox answers 403 to `CONNECT` for `fantasyfootballcalculator.com`. That is now
fixed: `.github/workflows/source-probe-ffc.yml` runs `scripts/probe_ffc.py` on a GitHub
runner, where egress is open. **Everything in this section is measured**, from run
[32996744422](https://github.com/jeisey/jeisey-tiers/actions/runs/32996744422). Re-run it
before acting on any of it — a source can change.

#### 3.1 Two findings that blocked the plan as proposed — one resolved, one open

**BLOCKER 1 — RESOLVED, 2026-08-26, by the publisher's own terms.** Read this subsection
in full before acting on it; the finding below was real, and so is its resolution.

Fantasy Football Calculator publishes terms for this exact endpoint at
<https://help.fantasyfootballcalculator.com/article/42-adp-rest-api>, and they are a grant:

> **Usage and Attribution.** Use of the ADP REST API is free for personal and commercial use.
> Fantasy Football Calculator requests that you provide attribution back to us in the form of
> a link or mention of some kind.
>
> Please do not call this API too frequently. The data only updates once per day.

The article also documents the four parameters — scoring format, number of teams, year,
position — and gives the canonical example
`https://fantasyfootballcalculator.com/api/v1/adp/standard?teams=12&year=2018`.

**How that squares with the `robots.txt` finding, which stands as measured.** Both are true at
once, and the reconciliation is the ordinary one: `robots.txt` is a directive to **crawlers**
— agents that discover and index by following links — and its `Disallow: /api/` keeps search
indexers out of a path whose responses would be junk in an index. The help article is the
**publisher's specific, published grant for that same path**, addressed to exactly the kind of
client this project would be. A blanket crawler directive and a specific documented licence
for the same endpoint do not conflict so much as address different audiences, and where they
appear to, the specific grant from the publisher governs — they are actively advertising the
endpoint for this use.

**This is a judgment, so it is recorded as one**, and it comes with a conservative posture
rather than a shrug: exactly one fetch per format per day (their own documentation says the
data updates daily, so a second fetch buys nothing), a descriptive User-Agent naming the
project, and visible attribution. If FFC ever asks this project to stop, it stops.

**Provenance:** the terms text above was supplied by the project owner from the help site;
this sandbox answers 403 to that host too. `scripts/probe_ffc.py` should fetch and echo the
help article on its next run so the wording is recorded verbatim in a run log rather than
transcribed.

<details>
<summary>The original finding, kept because the measurement is still the record</summary>

`robots.txt`, fetched verbatim by the probe:

```
User-agent: *
Disallow: /api/
Disallow: /ajax/
Disallow: /ajax-v2/
Disallow: /import/
Disallow: /adp/csv/
Disallow: /draft/
Disallow: /rate-my-team/results/
Disallow: /rankings/custom/
```

`/api/` and `/adp/csv/` are the two paths a daily snapshot would use, and both are
`Disallow`ed. Read alone, that says a scheduled job fetching either path every morning is
doing the thing the file asks robots not to do — which is why the first version of this ADR
recommended writing to FFC before writing any code. The help article answers that question
directly and more authoritatively, so the recommendation changed rather than the measurement.

**One thing does survive from it:** `/adp/csv/` is disallowed *and* is not covered by the API
terms, which name the REST API specifically. The CSV path also returns `text/html` and takes
no `year`. **Use the JSON API and leave the CSV path alone** — that is now a rule, not a
preference.

</details>

**BLOCKER 2 — CONFIRMED: the `teams` parameter is accepted and ignored.** The single biggest
reason to want FFC was exact `format × teams` cohorts. It does not have them.

A second probe run ([32998697322](https://github.com/jeisey/jeisey-tiers/actions/runs/32998697322))
compared the **per-player** `adp` and `times_drafted` across sizes rather than inferring from
totals, which settles it beyond argument:

```
standard  teams=8 vs 10 / 12 / 14:  shared=218  rows differing = 0  -> byte-identical
ppr       teams=8 vs 10 / 12 / 14:  shared=266  rows differing = 0  -> byte-identical
half-ppr  teams=8 vs 10 / 12 / 14:  shared=228  rows differing = 0  -> byte-identical
```

Not one player's ADP or sample size moves between an 8-team and a 14-team request. **FFC
supplies three cohorts, not twelve**, and every FFC quote is league-size *approximate*. The
help article lists `teams` as a supported parameter; the behaviour disagrees, and behaviour
is what may be published.

The aggregate evidence that first raised it:

| format | teams | players | total_drafts | deepest ADP | min/max times_drafted |
|---|---:|---:|---:|---:|---|
| standard | 8, 10, 12, 14 | 218 (all four) | **1828 (all four)** | 175.8 (all four) | 5 / 478 (all four) |
| ppr | 8, 10, 12, 14 | 266 (all four) | **7830 (all four)** | 192.8 (all four) | 5 / 3036 (all four) |
| half-ppr | 8, 10, 12, 14 | 228 (all four) | **3027 (all four)** | 201.5 (all four) | 5 / 727 (all four) |

The response `meta` faithfully echoes back whatever `teams` you asked for — and then returns
the same aggregate.

This is the same shape as a Phase-0 finding about MFL: `CUTOFF` is accepted with no effect and
`DAYS` is ignored, which is why `config/source-registry.yaml` says *"Only honoured filters
appear here, because a candidate built on an ignored filter would be a duplicate of the
unfiltered aggregate wearing a label."* **That rule now applies to `teams` here**, and the
registry entry must say so rather than repeating the vendor's parameter list.

#### 3.2 What the probe found that is genuinely good

**Scoring cohorts are real, and half-PPR is the prize.** Non-PPR, PPR and Half-PPR return
different player counts, different depths and different draft volumes. **A true half-PPR
market price is the one thing MFL structurally cannot produce** — `IS_PPR` is a boolean
(ADR-039) — and it is exactly the gap that makes the HALF board's ADP column an
approximation today.

**Volume is 7 to 30 times MFL's.** PPR carries 7,830 drafts against the 265 in the cohort
the frozen rule currently selects. The owner's instinct that MFL is systemically thin is
correct and now quantified.

**`stdev` is published per player.** MFL is not: every retained row carries the
`adp_sd_unavailable` quality flag, which is why ADR-041's `wide_market_range` had to be built
on min-to-max — an extreme order statistic that widens with sample size and was measured as
non-discriminating. A real standard deviation would let that flag be replaced rather than
re-tuned.

**A window is published.** `meta.start_date` / `meta.end_date` bound each aggregate: 7 days
for standard and PPR, 5 for half-PPR on the probe date. That is *better* than MFL, which
publishes no data-as-of time at all. (The probe's section 8 reported "no temporal keys"
because it scanned only top-level envelope keys and these are nested under `meta` — a probe
limitation, not a source one. Fix the probe before re-running.)

**Full player-row schema, all fields 100 % populated over 218 rows:**

| field | type | notes |
|---|---|---|
| `player_id` | int | FFC-internal; 218 distinct over 218 rows |
| `name` | str | |
| `position` | str | |
| `team` | str | |
| `adp` | float | |
| `adp_formatted` | str | display string, e.g. round.pick |
| `times_drafted` | int | per-player sample size |
| `high` / `low` | int | extreme order statistics, like MFL's min/max |
| `stdev` | float | **the field MFL lacks** |
| `bye` | int | |

#### 3.3 The identity problem, and why it is solvable but not free

`player_id` exists and is well-behaved — an integer, unique per player, populated on every
row. **But it is an FFC-internal id that bridges to nothing this project holds.** No
`gsis_id`, no `espn_id`, no `sleeper_id`, no `mfl_id`. An id that maps to nothing is not a
bridge.

The name diagnostic — **198 of 218 matched, 20 unmatched (90.8 %)** — is recorded only to
size the gap. It is not a route: `AGENTS.md` §6 forbids a production join that depends solely
on normalized names, and 90.8 % would be disqualifying even if it were allowed.

So a production integration needs a **built crosswalk**: FFC `player_id` → `gsis`, roughly
270 entries, established once and maintained as rookies and signings appear. This project
already has the machinery and the discipline for exactly that — `config/identity-aliases.yaml`
plus `load_alias_map`, now wired into the production capture path (ADR-054). Bootstrapping it
from name + team + position *with human review recorded per entry* is legitimate; doing the
same match silently at runtime is not. The difference is the whole point of that file.

#### 3.4 Recommendation — build it, scoped by what the terms and the measurements allow

**Proceed.** The access question is answered by the publisher in writing, the volume is real,
and half-PPR is a capability MFL cannot supply at any sample size. Three things bound the
build, and none of them is optional:

1. **The JSON API only.** `/api/v1/adp/{format}?teams={n}&year={y}&position=all`. The CSV
   path is `Disallow`ed, is not named in the terms, returns `text/html`, and takes no `year`.
2. **One fetch per format per day — three requests total.** Their documentation says the data
   updates once daily, so a second call is pure cost to them and buys nothing. This lands
   naturally inside the existing `daily-refresh` capture job.
3. **Attribution, visibly.** They ask for "a link or mention of some kind": the site's Data
   tab under sources, and `docs/DATA_SOURCES.md`. This is a condition of the grant, not a
   courtesy, so it ships in the same change as the adapter — not after it.

**And the shape of what gets built is now settled: three cohorts, not twelve.** `teams` is
ignored (§3.1 BLOCKER 2, confirmed per-player). Every FFC quote is league-size `approximate`,
and the UI and model card must not claim otherwise — publishing a 14-team price that is really
an all-sizes aggregate is precisely the error ADR-039 refuses for HALF on MFL.

**What FFC is therefore worth, stated honestly:** a genuine half-PPR *scoring* price with
7-30× MFL's sample and a published dispersion measure. That is a real gain and it is smaller
than the twelve-cohort version anyone would have designed from the documentation alone.

#### 3.5 The implementation path, for the session that picks this up

Ordered so that the cheapest disqualifying answer comes first. Do not skip ahead.

1. **Re-run the probe** (`source-probe-ffc.yml`) and confirm §3.1 and §3.2 still hold. A
   source can change, and everything below is built on one afternoon's measurements. The
   probe now also fetches and echoes the terms article, so a run log carries the grant
   verbatim.
2. **The cohort model is three, not twelve** — settled per-player, §3.1 BLOCKER 2. Do not
   re-derive it from the vendor's parameter list. If a future probe run ever shows `teams`
   differentiating, that is a new finding and a new ADR, not a quiet change.
3. **Register the source** in `config/source-registry.yaml`: `fantasyfootballcalculator_adp`,
   roles empty at first, `verify_before_use` cleared with the probe run id, the terms recorded
   verbatim with their source URL
   (<https://help.fantasyfootballcalculator.com/article/42-adp-rest-api>), and the cadence
   pinned at one fetch per format per day because the publisher says the data updates daily.
   Record the attribution obligation as a **requirement of the grant**, so a future reader
   cannot mistake it for a nicety and drop it.
4. **Record the schema fixture** — `tests/fixtures/source_schemas/ffc_adp.schema.json`, in the
   shape Phase 0 used, so a silent upstream change fails a check rather than a board.
5. **Write the adapter** — `FfcAdpAdapter` in `ffdraft/sources/`, emitting `market_quote`
   rows. Three cohorts only (`standard`, `ppr`, `half-ppr`), each flagged
   **`exact_cohort: true` for scoring and `false` for league size**, which is the honest
   reading of BLOCKER 2. Map `stdev` into the quote; keep `high`/`low` as MFL's min/max
   analogues; carry `times_drafted` as the per-player sample size; carry
   `meta.start_date`/`meta.end_date` as the source window, **separate** from retrieval time.
6. **Build the crosswalk** — `config/ffc-player-crosswalk.yaml` or an extension of
   `identity-aliases.yaml` keyed by `(source_id, external_id)`. Bootstrap by name + team +
   position, **review every entry by hand**, and record reviewer and date. Fail closed on
   anything unreviewed. Expect ~270 entries and a weekly trickle after that.
7. **Retain, do not merge.** Append FFC snapshots to the private store beside MFL's, under
   `market/fantasyfootballcalculator_adp/<season>/<snapshot>/`. Two sources, two retention
   trees, one manifest shape.
8. **Never average the two.** ADR-053 §5, and it is more important here than it was
   hypothetically: MFL publishes a **season-long cumulative** aggregate and FFC a **rolling
   5-to-7-day window**. Those are different statistics about different populations. Normalize
   to source-specific quotes — `market_quote` 2.0 already has the shape — and freeze any
   consensus formula **before** looking at which players it flatters.
9. **Measure the mock-draft population before promoting.** FFC's drafts are mocks run on its
   own site; MFL's are real league drafts. ADR-045 measured what a population difference does
   — dynasty rookie drafts moved rookie prices 3-5× while veterans did not move at all. Do the
   same measurement here, per position and per ADP band, and write it down before FFC prices
   anything the site publishes.
10. **Sequence the pay-off.** The first thing worth shipping is the **half-PPR** cohort, because
    it is the only place FFC can do something MFL cannot. Team-size exactness is *not*
    available and must not be claimed in the UI or the model card.

**A caution about the trend idea.** Snapshotting daily to compute per-player movement is
sound, and this project already retains and trends MFL that way (ADR-042). But FFC's window is
already rolling, so a day-over-day delta on FFC measures *"how the last week's drafters
differ from the week before"*, while the same delta on MFL measures *"how the season-to-date
aggregate shifted"*. They are not the same quantity and must not share a trend rule version.

### 4. The other candidates, unchanged

**FantasyPros / DraftWizard.** The mock-draft directory is a display product and the API is
membership-gated. Already registered `benchmark_only` with redistribution forbidden, and named
in `ffdraft/quality/forbidden.py` so the intrinsic firewall rejects it as a feature. May inform
a comparison; may never feed a published artifact.

**Sleeper by draft-id enumeration.** Recommended against, and the FFC `robots.txt` finding
sharpens why: iterating sequential ids against `https://api.sleeper.app/v1/draft/{id}/picks`
is a bulk scrape, their terms are non-commercial, the sample is biased by id allocation in a
way no post-hoc correction fixes, and the request volume is exactly what `AGENTS.md` §5
forbids. Sleeper stays a **status** source.

**MockoSheet and community aggregate sheets.** Redistribution of other vendors' aggregated
data under no licence this project can rely on.

### 5. Consequences

The gate's meaning is written down and its inherited threshold is flagged as inherited. FFC is
**measured rather than assumed**, and both the measurement and the reading changed: the
headline feature (team-size cohorts) is confirmed not to work — `teams` is accepted and
ignored, byte-identical per player across all four sizes — while the access question, which
`robots.txt` alone would have answered "no", is answered "yes, with attribution and restraint"
by the publisher's own documented terms. Nothing is added to the registry yet, no adapter is
written, and the pipeline is untouched; §3.5 is the path from here.

What a fresh session needs is here: the endpoints, the terms and where they are published,
the schema, the volumes, the one open question and the probe change that answers it, the
identity gap with its size, and a ten-step path ordered so the cheapest disqualifying answer
comes first.

**Revisit at:** a probe run that contradicts any of §3.1-§3.2, or the next
`top_board_priced` failure that is not an identity defect.
