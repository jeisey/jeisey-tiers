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

**Status:** **Accepted, and resolved by the event it predicted** (Phase 8, 2026-08-31). Nothing in the code changed on the strength of this ADR; its whole point was to argue for *not* changing something, and the argument held.

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

### Resolution — 2026-08-31 (Phase 8)

**It crossed, on time, with the rule untouched.** Continuing the same table from the daily-refresh summaries:

| observation day | selected cohort | total drafts | confidence on the published board |
|---|---|---:|---|
| 2026-08-20 | `no-mock-no-keeper` | 125 | 2,124 `low` |
| 2026-08-22 | `no-mock-no-keeper` | 143 | 2,021 `low` |
| 2026-08-24 | `no-mock-no-keeper` | 227 | `low` |
| 2026-08-27 | — | — | 1,966 priced rows |
| 2026-08-30 | `no-keeper` / `ppr-no-keeper` | 514 / 386 | 1,870 `medium`, 75 `low` |
| **2026-08-31** | `no-keeper` / `ppr-no-keeper` | **735 / 554** | **1,889 `medium`, 45 `low`** |

Every preset now reports `sufficient: yes` with **no failed clause**, and the median per-player sample has gone 93 → 345 → 487 drafts. The selection rule also moved on its own, from `no-mock-no-keeper` to `no-keeper` and `ppr-no-keeper`, because a qualifying scoring-specific cohort became available to it — the rule preferring specificity once specificity cleared the bar, which is what it was written to do.

**What that settles.**

1. **`min_total_drafts` was measuring the evidence, not the filter.** The structural reading — that requiring `IS_KEEPER=N` caps the achievable count — is refuted: the same filter, the same clause and the same bound went from 125 to 735 in eleven days. The clause is a volume clause and it did a volume clause's job.
2. **No bound moves, and none should have.** `min_total_drafts`, `phase5_cohort_v2` and the confidence rubric are unchanged. A re-specification in the week of 2026-08-24 would now be indistinguishable from the season arriving, and the repository would have lost the ability to tell the two apart forever.
3. **The frozen rule behaved as designed end to end.** Nobody edited anything; the label moved because the evidence did.

**What it exposed, which is the more valuable half.** The product transitioned `low` → mostly-`medium` with **no test in the repository rendering the new state**. Every market assertion — unit, end-to-end and mobile — was written against the launch board: uniform `low`, null trend, a cohort below the bar. That is the same defect class as the trend verifier ADR-052 itself describes, and it survived the ADR that described it. Phase 8's fix is a second fixture board (`MARKET_CONDITIONS` in `web/tests/fixtures/artifacts.ts`) carrying the matured condition — mixed confidence, a measured trend on most rows and a null one on at least one, a cohort that clears every clause, and one preset the build calls *exact* — with the market-sensitive tests run against both. Neither board is "the normal one". That is the point.

**Consequence for the UI.** `marketHeadline` reports whatever distribution the rows carry rather than asserting a condition, the Data view counts the labels instead of stating one, and the two limitation items that described a young market are now written from `build_metadata`. The product moves `low` → `medium` → `high` with no code change, and a future null trend still renders correctly through the same component.

---

## ADR-053 — The free market-source sweep: what exists, what each would fix, and why none of it ships yet

**Date:** 2026-08-24 (Phase 7 operations)

**Status:** **Accepted — V1 disposition; production integration deferred** (2026-09-01, Phase 9B). No source is added, no policy changes, and `config/source-registry.yaml` is untouched by this ADR. What is accepted is the sweep's conclusion — *add nothing now* — not a plan to add anything; see the V1 disposition at the end of this entry.

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

### V1 disposition — 2026-09-01, accepted at the launch release

**Both revisit conditions fired, and both resolved the same way: add nothing.**

*ADR-052 resolved*, on 2026-08-31 and without a bound moving. The keeper-free cohort went 125 → 735 drafts in eleven days, every preset now reports `sufficient: yes` with no failed clause, the median top-150 player is priced by 487 drafts, and the published board reads 1,889 `medium` against 45 `low`. Proposal 2 above sequenced this whole sweep behind exactly that event, on the reasoning that if confidence resolved on its own the case for a second source would shrink to something smaller and more precise. It did, and it has.

*The study was commissioned* for the one candidate this sweep named — and the answer changed the shape of the prize rather than the decision. `.github/workflows/source-probe-ffc.yml` ran on a runner and ADR-056 §3 records what it measured: the access question is answered *yes, with attribution and restraint* by the publisher's own terms; the volume is real; a per-player `stdev` and a source window are published, both of which MFL lacks. And the headline reason to want FFC — exact `format × teams` cohorts — **does not exist**: `teams` is accepted and ignored, byte-identical per player across all four league sizes. FFC offers three scoring cohorts, not twelve.

**Accepted for V1:** proposals 1 through 5 stand as written. MyFantasyLeague remains the sole production price source; nothing enters `config/source-registry.yaml`; FantasyPros stays `benchmark_only` and out of production; sportsbook odds remain a category error for both the arbitrage comparison and the intrinsic firewall; and the do-not-average rule in proposal 5 is carried forward unchanged and is now the more load-bearing half of this entry, because a real second candidate exists on paper.

**What this accepts is the deferral, not an integration.** No adapter is written, no crosswalk is built, no cohort rule moves and no published number changes. The remaining value — a genuine half-PPR price, which a boolean `IS_PPR` can never represent — is a market-methodology project with its own preconditions, and it is scoped in ADR-056's Phase-8 disposition rather than here.

**Revisit at:** the dedicated post-V1 market-methodology change. This entry is closed for V1.

---

## ADR-054 — Why the top-150 coverage gate failed on 2026-08-26, measured rather than guessed

**Date:** 2026-08-26 (Phase 7 operations)

**Status:** **Accepted**, and no part of it is still open (status corrected 2026-09-01, Phase 9B). It was accepted on the day for the one change it makes — wiring the reviewed-alias file into the production capture — and the "larger question" it raised alongside that, Finding 3's proposal to restrict the published board to rostered players, was **retracted the same day and superseded by ADR-055**; the correction is at the end of this entry. The status line said "awaiting owner review" for a question that no longer existed, which is what this correction fixes. Nothing here is a V1 blocker and nothing here changes.

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

**Status:** **Accepted — V1 disposition; production integration deferred** (2026-09-01, Phase 9B). Section 1 clarifies existing behaviour and changes nothing. Section 3 was rewritten on 2026-08-26 from a **runner probe of the live endpoints** rather than from search; it changed the recommendation twice. No source is added, no adapter is written, `config/source-registry.yaml` is untouched, and the pipeline does not move.

**Read §3.4 in the light of the Phase-8 disposition at the end of this entry, which supersedes it.** §3.4 says "Proceed", and it was right on the evidence it had; the premise it rested on — a market too thin to price the board — expired five days later. The measurements in §3.1-§3.3 are accepted as fact and carried forward in full. The *integration* is deferred to a dedicated post-V1 market-methodology change, and V1 ships with MyFantasyLeague as its sole price source. The one item §1 leaves genuinely open is a naming question, not a launch question: `TOP_BOARD_PRICED_MINIMUM` is still an alias of `IDENTITY_COVERAGE_MINIMUM`, and giving it its own constant and derivation is post-V1 work to be done "at a moment when nobody is reading a number it would move" — which a release week is not.

### 1. The gate, stated plainly

The owner asked whether `min_top150_coverage >= 95%` means "at least 95% of players across MFL drafts need to be present in the top 150". **It is the other direction, and the difference matters.**

For each published block — one of the nine (scoring × league size) combinations — the check takes **our own board's top 150 by fair rank** and asks what fraction of *those players* the market has a price for. `coverage_summary` then takes the **minimum across the nine blocks**, deliberately: "a mean would hide the case this gate exists to catch: eight healthy presets and one that lost its cohort."

So it measures **how much of our board the market can price**. It says nothing about how much of the market our board covers, and nothing about draft volume. Nine missing prices out of 150 is 94.0%, and that is what failed on 2026-08-26.

Two properties are worth knowing:

- **`TOP_BOARD_PRICED_MINIMUM = IDENTITY_COVERAGE_MINIMUM`.** The board-coverage bar is an *alias* of the identity-resolution bar. They measure different quantities — "can we resolve the names a vendor sent" versus "does the vendor price the players we rank" — and 0.95 was chosen for the first and inherited by the second. **Deferred to post-V1** (Phase 9B): give it its own named constant and a stated derivation, changed at a moment when nobody is reading a number it would move — which a release week is not. This is a naming and derivation question about a threshold that is currently passing, not an open V1 decision.
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

### Phase-8 disposition — 2026-08-31: evidence accepted, integration deferred

**Decision: Fantasy Football Calculator is not added to the production V1 market price, and MyFantasyLeague remains the sole V1 price source.** ADR-056's source findings are accepted as measured fact and carried forward; only the *integration* is deferred.

**Why the recommendation changed without the evidence changing.** ADR-056 recommended building, and its reasoning was sound on 2026-08-26: MFL's keeper-free cohort held 227 drafts against a bar of 300, no board could clear its sufficiency rule, and a second source with three genuine scoring cohorts, higher volume and a published standard deviation was the obvious remedy. The premise has since expired. As of 2026-08-31 the keeper-free cohort holds **735 drafts**, every preset reports `sufficient: yes` with no failed clause, the median top-150 player is priced by **487** drafts, and the published board reads 1,889 `medium` against 45 `low` (ADR-052 resolution). The volume problem FFC was going to solve solved itself.

**What adding it now would cost.** Not one change but five, in the final hardening phase:

1. a new production source, with its own availability, rate and terms obligations;
2. a **manually maintained identity crosswalk** — FFC's player id is FFC-internal and bridges to nothing this project already holds, so the join would be a reviewed file rather than a verified id, against ADR-019's whole design;
3. a source-composition methodology that does not exist;
4. new consensus or selection semantics — with two sources, "the market price" needs a rule for which one, or how to combine them;
5. **a changed definition of the published market price**, mid-phase, on a live product.

That is a market-methodology change wearing a hardening change's clothes. The exit gate for this phase is "no known launch-blocking defect"; adding a price source is not a defect fix.

**Specifically not done, and not to be done by halves.** No multi-source ADP. **Do not average MFL and FFC** — a mean of two aggregates over different draft populations, different windows and different scoring mixes is a number with no referent, and it would be published as if it were one. A0 is untouched. FantasyPros stays `benchmark_only` and out of production (ADR-014).

**What survives for the successor.** Everything ADR-056 measured, all of it runner-verified: FFC serves genuine `standard`, `ppr` and `half-ppr` cohorts; it carries substantially more draft volume than MFL; it publishes a per-player standard deviation, which MFL does not and which would replace the min/max range the product currently has to caveat; it publishes a source time window; and its own published terms permit use with attribution and ask clients not to poll unnecessarily. Also settled, and the most expensive thing to have discovered late: **`teams` is accepted and ignored** — per-player ADP and `times_drafted` are byte-identical across league sizes — so FFC offers three scoring cohorts, not twelve scoring × league-size cohorts, and team-size exactness must never be claimed from it.

**Where the value still is: exact half-PPR.** It remains the one thing FFC can do that MFL cannot, and the one place the product still prices a board with a population that is not its own — STD and HALF are priced by an all-scoring cohort, and the Data view says so. That is the pay-off a post-V1 market-methodology change should be aimed at, with a predeclared comparison rule written before any player-level result is looked at.

**Revisit at:** a dedicated post-V1 market-methodology change, not before. Two preconditions: a durable reviewed identity crosswalk with the same fail-closed discipline as the existing bridges, and a frozen source-selection rule committed before its evidence exists.

---

## ADR-057 — Simulation convergence is audited separately from tier-boundary stability

**Date:** 2026-08-31 (Phase 8)

**Status:** **Accepted and implemented.** Amends the open question ADR-034 recorded; does not amend ADR-034's own decision, and changes no production value.

**Context.** ADR-034 selected 10,000 Monte Carlo draws through `phase4_convergence_v1`'s *fallback* clause, because no count in the frozen ladder satisfied every tolerance. It recorded the reason the rule was suspect rather than repairing it mid-phase, and the repair was left as an open question. Two defects in the rule:

1. **It asks one question of two properties.** Monte Carlo sampling error shrinks with more draws. A tier boundary is a discrete cut on a nearly continuous value decline, so where it lands is a property of the curve, not of the sampling; more draws do not fix it and cannot. Combining them means a configuration whose sampling is fine reports "not converged" because its cut positions moved.
2. **Its tier clause is stricter than the gate it protects.** `min_tier_adjusted_rand` is 0.90 here; `phase4_tier_stability_v1` (ADR-035) asks for 0.60, and the promoted configuration measures 0.865 against it. The convergence rule could therefore fail a configuration whose tiers had already passed their own gate. It was also evaluated across draw counts the tier rule was never going to select.

**Decision.** `phase8_simulation_convergence_v1`, frozen in `ffdraft.modeling.convergence_audit` and committed at `87db5e5` **before** it was pointed at any report.

It changes the question, not the answer:

| | `phase4_convergence_v1` | `phase8_simulation_convergence_v1` |
|---|---|---|
| numeric bounds | ten simulation + two tier | the same ten simulation bounds, **inherited verbatim** |
| tier clauses | decisive | reported as observations; ADR-035 owns the property |
| scope | every count in the ladder | the promoted production count only |
| may select a draw count | yes | **no** — there is no code path from the rule to one |

Nothing is loosened; `tests/model/test_convergence_audit.py` asserts each bound equals its Phase-4 value, so a future edit that quietly relaxes one turns a test red. Removing the ladder search is the clause that matters most: it makes the rule structurally incapable of being read, after the fact, for a smaller and cheaper draw count.

**Result, measured after the freeze** (`uv run ffdraft audit-convergence`, over the committed `docs/experiments/phase4-simulation-ranking/experiment.json`, eight comparisons at 10,000 draws):

| criterion | worst observed | bound | |
|---|---:|---:|---|
| fair-rank Spearman | 0.9994 | ≥ 0.9990 | pass |
| top-50 overlap | 0.9800 | ≥ 0.9600 | pass |
| mean \|Δ rank\| top-150 | 1.3467 | ≤ 1.5000 | pass |
| max \|Δ replacement\| | 0.2491 | ≤ 0.5000 | pass |
| mean \|Δ outer VORP\| | 0.4507 | ≤ 0.6000 | pass |
| p99 \|Δ outer VORP\| | 2.7212 | ≤ 5.0000 | pass |
| p99 \|Δ P50 VORP\| | 2.8457 | ≤ 3.0000 | pass |
| **mean \|Δ expected VORP\|** | **0.3141** | ≤ 0.2500 | **fail** |
| **mean \|Δ P50 VORP\|** | **0.4160** | ≤ 0.3500 | **fail** |
| **p99 \|Δ expected VORP\|** | **1.9288** | ≤ 1.5000 | **fail** |

**The audit does not pass, and it says something much more specific than the composite rule did.** *Ranking is operationally converged and value is not.* Between two seeds at 10,000 draws the published order barely moves — Spearman 0.9994, 98% of the top fifty retained, an average top-150 player shifting 1.35 places — and the replacement level, which is what makes VORP league-relative at all, agrees to within half its tolerance. What still moves is a player's central value in fantasy points, by about a third of a point on average and 19–29% beyond tolerance on three of the four evaluated scenarios. Tier agreement at the promoted count is ARI 0.499 with a five-tier count difference; that is recorded here and decided by ADR-035, not by this rule.

**Consequences.**

- **The production draw count stays at 10,000.** This audit cannot change it and no reading of it should: sampling that has not settled is not an argument for fewer samples.
- **ADR-034 stays open**, but the open question is now a narrow one with a number attached — closing the last 25% of expected-VORP error, not "the convergence rule disagrees with itself".
- The residual is a published limitation, not a hidden one: the Data view already says a build is exactly reproducible for a fixed seed and is not seed-invariant.
- A future simulation refresh has a clean target. Whether it is worth spending draws on is a real question: the quantity that still moves is the one the product does *not* rank by (fair rank is median simulated VORP, and the ranking criteria pass), so the honest framing is that the board's order is trustworthy at this draw count while a player's printed VORP carries about ±0.3 points of Monte Carlo noise.
- ADR-035's threshold was **not** touched, and this ADR is not a route to touching it.

---

## ADR-058 — Methodology is stated once in Data; a board carries only what stops a number being misread

**Date:** 2026-08-31 (Phase 8)

**Status:** **Accepted and implemented.**

**Context.** ADR-041 requires that `confidence` never be shown as a bare label, because "low" beside a player's name reads as "the model is unsure about him" and means the opposite. ADR-043 requires that current status be disclosed as annotation only. ADR-045 requires that an approximate cohort be labelled. Phase 6 satisfied all three the direct way: it put the explanation next to the value, everywhere the value appeared.

On a three-hundred-player board with a card reachable from four surfaces, that produced three paragraphs repeated per player — the confidence rubric, the cohort caveat, and "Current status annotation — not included in the projection or the model. The board above was produced without any of these fields." The owner's Phase-8 review named all three. The problem is not that any of them is wrong; it is that a caveat a reader has met three hundred times is a caveat they have stopped reading, which makes the repetition self-defeating as well as noisy.

**Decision.** **Context on the board; methodology in Data.**

- A repeated surface carries the *minimum that stops a number being misread*: a label (`Market data · Medium`), a qualifier (`approximate cohort`), a badge (`Q · Hamstring`), a five-word marker (`Annotation only — not a model input.`).
- The **definition** — what the label is a statement about, what the cohort could not filter, what "annotation only" means and why an absent designation is not a clearance — lives once in the Data view, and the player card links to it.
- A flag that describes the **build** rather than the player (`cohort_approximate`, `cohort_insufficient`, `insufficient_trend_history`, `market_snapshot_stale`) is explained once at view level and suppressed per row. `web/src/data/flags.ts` names that set explicitly, so a new build-level flag is a one-line addition rather than a judgement call at each call site.
- Nothing is deleted. Every disclosure removed from a repeated surface has a home in Data, and `web/tests/app.test.tsx` pins the ones whose loss would be a truthfulness regression rather than a tidiness win.

**What this does not license.** It is not permission to move a caveat *out of sight*. The test that distinguishes the two: could a reader who never opens Data misread a number on the board? If yes, the board keeps enough to prevent it. That is why `approximate cohort` stays on the card beside the ADP and why the status badge stays on every row that has one — and why `Medium` stays a visible word rather than a colour.

**Consequences.** ADR-041, ADR-043 and ADR-045 are satisfied by the Data view plus the on-board markers, not by per-row prose. A future surface that shows a confidence label, a cohort-derived price or a status field inherits the same rule; adding a paragraph beside one of them is a regression, and adding a *new* disclosure means adding it to Data.

---

## ADR-059 — The behavioural suite is single-engine; a smoke suite is three-engine

**Date:** 2026-08-31 (Phase 8)

**Status:** **Accepted and implemented.** Amends ADR-048's dependency set.

**Context.** Phase 6 ran the entire end-to-end suite on Chromium and recorded browser coverage as Phase-8 work. Phase 8 then made the question urgent: the Tier Board and Draft Rail moved off SVG onto CSS grid, `color-mix()`, container-relative percentage geometry and `<dialog>` in two presentations. Those have materially different histories in Gecko and WebKit than in Blink, and WebKit shipped `<dialog>` and `::backdrop` last of the three.

Running the whole suite three times is the obvious answer and the wrong one. Roughly forty of its assertions are about logic — a table sorts, a query string round-trips, two artifacts join, a degraded artifact degrades one feature — none of which varies by rendering engine. Tripling the slowest gate in the repository to re-prove them would buy nothing and would be paid on every pull request.

**Decision.** Two suites, split by whether the property under test is engine-dependent.

| suite | engines | what it covers |
|---|---|---|
| `board.spec.ts`, `mobile.spec.ts`, `a11y.spec.ts` | Chromium | behaviour, URL state, degraded modes, accessibility conformance |
| `smoke.spec.ts` | Chromium, Firefox, WebKit | primary flows, layout and reflow, focus, `<dialog>` semantics, downloads, base path, reduced motion |

Chromium is in the smoke suite as well as the other two, so a smoke failure can be told apart from an engine difference: red everywhere is the product, red in one is the browser.

**Where it runs.** `.github/workflows/ci.yml` gains a `browsers` job. This is the one gate that genuinely cannot run in the development sandbox — its egress policy blocks `cdn.playwright.dev`, so Firefox and WebKit cannot be downloaded there at all, while Chromium is preinstalled. That is the same shape as ADR-009's source probes: the environment that can answer the question is the runner, so the question is asked there. First green run: [33407642729](https://github.com/jeisey/jeisey-tiers/actions/runs/33407642729).

**Dependencies (amending ADR-048).**

- **added** `@axe-core/playwright`, dev-only, exact-pinned. Automated WCAG scanning is not a substitute for the keyboard pass — `a11y.spec.ts` says so in code by asserting the properties a scanner cannot judge — but it found four real contrast and reflow defects on its first run against the redesign, which is a better return than any other dependency in the repository.
- **removed** `d3-scale`, `d3-array` and their `@types` packages. The Phase-8 encodings are CSS geometry rather than SVG, so nothing imports them. They were in ADR-048's set because Phase 6's charts used `scaleLinear`; keeping an unused runtime dependency in a published bundle is exactly the "unnecessary dependency" the Phase-8 review asks about.

The frontend's production dependency set is now `react`, `react-dom` and `@tanstack/react-table`. Still no router, no UI kit, no charting framework, no CSS framework.

---

## ADR-060 — The Phase-10 source evidence is taken on a runner, four passes deep, and the FantasyPros answer is not the one the roadmap expected

**Date:** 2026-09-02 (Phase 10)

**Status:** **Accepted.** Evidence: `docs/source-probes/2026-09-02/phase10-report.md`, runs [33642792347](https://github.com/jeisey/jeisey-tiers/actions/runs/33642792347), [33643152957](https://github.com/jeisey/jeisey-tiers/actions/runs/33643152957), [33643545952](https://github.com/jeisey/jeisey-tiers/actions/runs/33643545952) and [33643980189](https://github.com/jeisey/jeisey-tiers/actions/runs/33643980189).

**Context.** `AGENTS.md` section 3 forbids writing an adapter against a remembered schema, and the development sandbox's egress policy denies all four Phase-10 vendor hosts — the same constraint ADR-009 and ADR-053 recorded, unchanged. `docs/RELEASE2_ROADMAP.md` 10.1 also asks the phase *not* to rediscover settled facts, and to re-probe only what can change operationally.

**Decision.** Three probe scripts and one dispatch-only workflow, and a rule about how far to keep asking: a probe stops when the answer decides something, and asks again when the answer raises a question that decides something else. That took four passes, and only the first was planned.

Run 1 answered FFC and Sleeper completely and gave FantasyPros an answer that looked like a schema and was actually a symptom: ten rows, `count: 1777`, `public_api_limited: true`. Run 2 asked whether that was a page size, trying `limit`, `offset`, `start`, `page`, `max_results` and `ranks`; all eight variants returned the same ten rows and the same first player. Run 3 asked what the key could reach anyway — forty players across the four core positions, no ADP field in any response, `/adp` a 403 — and ran out of its own budget one section short. Run 4 spent four requests on that section rather than re-asking the thirty questions that already had answers.

**The probes are budget-aware because the budget is the constraint.** `scripts/probe_fantasypros.py` counts its own requests, refuses to exceed its allowance, paces at one per second, and routes every printed line through a guard that suppresses any line containing the API key. The job log of a public repository is world-readable; that guard is not decoration, and it is the reason the key can be used in a public-repo workflow at all.

**Discovery before assumption.** The FantasyPros probe fetches the published documentation and probes the paths the vendor names. When the documentation yielded no machine-readable path list, the probe said so and labelled its fallback list *candidates* — so a 404 is recorded as a measurement rather than mistaken for a schema.

**What this changes.** ADR-062 productionises FFC. ADR-064 records why FantasyPros ships as an implemented, retained, unpublished source. Nothing about MyFantasyLeague moves.

---

## ADR-061 — FFC identity is a one-time linkage with a reviewable artifact, not a nightly fuzzy match

**Date:** 2026-09-02 (Phase 10)

**Status:** **Accepted and implemented.** Measured: 222 of 222 relevant rows, **100.000%** coverage, zero quarantined, against a 90% gate. Evidence: `docs/source-probes/2026-09-02/fantasyfootballcalculator_adp-linkage/report.json`, run [33650112635](https://github.com/jeisey/jeisey-tiers/actions/runs/33650112635).

**Context.** `AGENTS.md` section 6 forbids a production join that depends solely on normalized names. MyFantasyLeague obeys that by construction: its export carries an `espn_id`, the registry indexes it, and a second bridge cross-checks the first. Fantasy Football Calculator publishes an internal `player_id` that maps to nothing outside FFC, and no bridge exists to build.

**Decision.** Split the join in two. The *proposal* is name-derived, runs once, and produces a file a person can read; the *production join* is an exact id lookup against that file. `ffdraft link-market-source` writes `config/market-aliases/fantasyfootballcalculator_adp.yaml` plus a machine-readable coverage report and a quarantine CSV; `ffdraft capture-market-source` never scores a name.

That is what makes this acceptable rather than a loophole. The fuzzy step is auditable, dated, versioned, and never repeated for a player already in the file.

**The rules, and why each exists.**

- **Block on position, exactly.** A QB may never reach an RB however similar the names. The blocking key is the same exact `Position.parse` table the rest of the project uses, so a team-unit token like `TMWR` cannot become WR.
- **Never block on team.** Teams go stale around trades and free agency. Team agreement is a tie-break and a diagnostic; the gold set contains a row whose team is wrong and which must still resolve.
- **Refuse on ambiguity.** A tie, a thin margin, or two canonical players who normalize to one name each quarantine with a reason. The failure being avoided is a confident wrong answer, not a missing one.
- **Surface the top-300 tail separately.** A 92% aggregate that hides three second-round picks is worse than an 88% one that does not.

**The gold set changed the code, not the other way round.** It exposed that `ffdraft.identity.names.normalize_name` — correct for the resolver's diagnostics — replaces all punctuation with a space, leaving `de andre` against `deandre` for one man's name. Linkage therefore has its own key, `linkage_key`, differing by exactly one rule: an apostrophe or a period is elided because it carries no word boundary, while a hyphen still becomes one. Two gold expectations were also wrong and were corrected to what the rule *should* do — Jonah is not Jonas, and a 91.7 near-miss at the same position is a refusal.

**RapidFuzz, not an entity-resolution framework** (`AGENTS.md` section 13). A few hundred football names need a normalized indel similarity, which is one small MIT-licensed dependency. `fuzz.ratio` rather than a token-set ratio, deliberately: a partial ratio treats "Michael Thomas" and "Thomas" as near-identical, which is exactly wrong at a position where several real players share a surname.

**The measured result is stronger than the gate.** Every one of the 222 accepted rows resolved by *exact* normalized name and position; the fuzzy path was not needed once against this population. That is not an argument for removing it — it is the machinery that keeps a future rookie spelling or a mid-season signing from silently going unpriced — but it does mean today's alias file rests entirely on exact matches, which is worth knowing when reading it.

**Generated aliases never outrank reviewed ones.** `config/identity-aliases.yaml` is loaded last and wins. A machine's reading of a name must not overwrite a person's decision about a player, usually written down precisely because the automatic path could not see him (ADR-019, ADR-054).

---

## ADR-062 — Fantasy Football Calculator ships; `teams` is still ignored, and the window is not MyFantasyLeague's

**Date:** 2026-09-02 (Phase 10)

**Status:** **Accepted and implemented.** Supersedes ADR-053's deferral. Confirms ADR-056's `teams` finding rather than overturning it.

**Context.** ADR-056 measured FFC in Phase 8 and ADR-053 deferred the integration because the volume problem it would have solved had solved itself. `docs/RELEASE2_ROADMAP.md` 10.1.1 reopens the integration and forbids reopening the general question.

**Decision.** FFC becomes a production ADP source with three exact scoring cohorts and an explicitly unknowable league size.

**`teams` is accepted and ignored — reproduced exactly.** Per-player `adp` and `times_drafted` compared across 8/10/12/14-team requests in all three formats: **zero rows differ in any of the nine comparisons**. ADR-056 stands, no successor is written, and `league_size` is null on every FFC quote with a `league_size_not_observed` flag saying the null is a refusal to claim rather than a gap. A semantic check fails the build if any FFC row ever carries one.

**The window is the finding this ADR adds.** `meta.start_date`/`end_date` came back as `2026-08-26`/`2026-09-02`: a **seven-day rolling window**. MyFantasyLeague aggregates the season to date. Both are called "ADP" and they are not the same measurement, so `market_quote` 3.0 carries an `aggregation_window_type`, the UI prints it beside the selector, and a semantic check refuses to let an FFC row claim to be cumulative. Presenting the two as interchangeable would be the opaque consensus Release 2's guardrail 2.3 forbids.

**Dispersion is two fields, not one.** FFC publishes `stdev` (221/221 populated, 0.60–31.90) *and* `high`/`low`. A standard deviation and two extreme order statistics are different quantities: the first estimates spread, the second widen with sample size. They occupy `adp_sd` and `min_pick`/`max_pick` respectively, and MyFantasyLeague's permanent `adp_sd` null is enforced by its own check.

**`high`/`low` are ordered numerically rather than by their labels.** FFC's table reads "High" for the *earliest* pick, which is the smaller number — the opposite of how "high" reads in English. The adapter sorts the pair, so it is correct under either convention and a vendor that swapped them could not silently invert a published range. The observed orientation is counted into the batch detail as evidence instead of being trusted.

**Cadence.** One request per cohort per day, three cohorts, with a descriptive contactable User-Agent. FFC's published terms permit API use with attribution and ask clients not to poll unnecessarily; every downstream stage reads the retained snapshot.

**Volume, for the record:** standard 1,794 drafts / 221 rows, half-PPR 3,142 / 233, PPR 8,007 / 264. The deepest ADP is 201.1. **FFC's entire population is smaller than 300**, so "FFC top 300" means the whole of FFC — which is what the surface rule uses, because the rule asks for the top of each market, not for a market to have 300 rows.

---

## ADR-063 — Three universes, not one `head(300)`

**Date:** 2026-09-02 (Phase 10)

**Status:** **Accepted and implemented.**

**Context.** Release 1 published `board.head(config.board_depth)` with a frozen depth of 300. That single line was three decisions wearing one number, and it produced a real defect: a player the market was drafting around RB20–30 could be absent from the public Tier Board, the status artifact and every market comparison, because his intrinsic fair rank fell below 300 — with nothing anywhere that would notice.

**Decision.** Separate the three decisions, and version the one that was frozen.

1. **Intrinsic/model universe** — every eligible QB/RB/WR/TE the football-only model can value. Market-blind and unchanged.
2. **Tier segmentation universe** — the contiguous fair-ranked prefix tiers are computed over. Versioned: `phase4_tier_depth_v1` (300) is kept so a Release 1 board stays reproducible, and `phase10_tier_depth_v2` supersedes it.
3. **Public surface universe** — who is searchable and displayable, because either the model or current external evidence says he matters.

**The invariant that makes this safe:** a market signal may change *whether a player is surfaced*; it may never change his projection, VORP, fair rank or tier. A surfaced player from beyond the tier depth therefore carries `outside_tier_board=true` and **no tier**, rather than a fabricated one. He has a fair rank — the model computed it — and that is exactly the number a reader needs beside a market price that disagrees with it.

**Every surfaced player carries machine-readable reasons.** `SurfaceReason` is a closed vocabulary, and a source with no declared reason raises rather than producing an unlabelled row: a surfaced player nobody can explain later is worse than an error. The vocabulary is deliberately larger than draft mode needs, because Phase 12 must surface a third-string back who became the starter in week 6, and a contract that changes shape mid-season is a contract nobody trusts.

**The coverage gate is critical, not a warning.** A warning is effectively what the old design had — nothing looked, so nothing complained. Resolved top-market players absent from the surface fail the build. Identity-unresolved source rows are counted **separately**, because folding them into the denominator is precisely how a coverage number stays at 100% while players go missing.

**A regression test reproduces the original bug.** `test_a_market_relevant_player_below_the_tier_depth_cannot_disappear` surfaces a synthetic player at fair rank 640, and `test_the_old_truncated_board_would_fail_the_gate` feeds the rule a pre-truncated board and asserts it fails — proof the gate is load-bearing rather than decorative.

**The depth itself is a reasoned choice, not a measured optimum, and that distinction is recorded rather than smoothed over.** Roadmap 10.5 asks for a depth chosen from the measured market-coverage distribution. `scripts/phase10_depth_analysis.py` was written to produce it and found the question unanswerable from published artifacts: an arbitrage row exists only for a player already on the tier board, so measured against a board published at depth 300, every "priced players beyond 300" count is **zero by construction** — including the deepest-priced figure the choice depends on. Run [33655647823](https://github.com/jeisey/jeisey-tiers/actions/runs/33655647823) returned exactly that, nine blocks of zeros, and reading it as "300 is sufficient" would have been the wrong-denominator mistake ADR-054 recorded in a different place. The script now detects the circularity and refuses to conclude from it.

What remains measured, and does bound the choice: 300 is definitively too shallow, because the roadmap's own motivating case is one market-priced player beyond it and one is enough; FFC's whole published population is 221–264 rows with a deepest ADP of 201.1; and the deepest launch preset drafts 182 players. **500 is the smallest simple value with real headroom over the one bound that is measured.**

What makes an unmeasured depth acceptable here is the thing that was missing before: the surface coverage gate is **critical**. If 500 is ever too shallow, a resolved top-market player fails the build rather than disappearing quietly. The unguarded 300 had no such backstop, which is why it failed silently for a whole preseason. Answering the question properly needs the full intrinsic board joined against a market snapshot — a production build with the retained store attached — and the first live multi-source refresh is where that happens.

---

## ADR-064 — FantasyPros is implemented, retained, and not published: the key's tier serves ten rows and no ADP

**Date:** 2026-09-02 (Phase 10)

**Status:** **Accepted.** This is a **failed exit criterion**, recorded rather than rounded up. Evidence: `docs/source-probes/2026-09-02/phase10-report.md` section 2.

**Context.** `docs/RELEASE2_ROADMAP.md` 10.1.3 promotes FantasyPros from `benchmark_only` to an approved production source for **both ADP and ECR**, publicly visible in the Tier and Arbitrage surfaces, with the owner's key already provisioned as `FANTASYPROS_API_KEY`. The roadmap notes responses are truncated and instructs the probe to find the official strategy for complete coverage — and warns, in item 7, not to mistake a truncated response for a complete top-300 market.

**What was measured.** The key is on the **free** tier. Every response carries `public_api_limited: true` and returns exactly **ten rows**; `limit`, `offset`, `start`, `page`, `max_results` and `ranks` were each tried and all eight variants returned the same ten rows and the same first player. There is no pagination to find. Per-position calls widen the *population* to the top ten of each, giving **forty distinct players** across QB/RB/WR/TE — against a documented `count` of 407 receivers and 225 tight ends alone.

**And there is no ADP at all.** `/json/nfl/{season}/adp` answers `403 Missing Authentication Token`; `type=adp` on the consensus endpoint returns the ECR row shape with no ADP-like field. A `fantasypros_adp` column would have nothing behind it.

**Decision.** Build it completely and publish nothing from it.

The adapter, the 50/day budget (half the vendor's stated 100, per the roadmap), the one-request-per-second pacing, the header-only key handling, the deterministic 12-request call plan and the append-only retention all ship and are tested. `MarketSourceSpec.publishable` is `False` with the reason attached, `semantic_checks` raises a **critical** check whenever a response declares itself limited, and the capture records the source as retained-not-published. Enabling it is a one-line registry change the day a key without the cap is provisioned.

**Why not ship the forty rows.** Because they would be read as "FantasyPros ECR" — a consensus — and they are 13% of one position. The roadmap's own surface gate compounds this: it requires 100% of each enabled source's top 300 to be publicly reachable, which is unevaluable for a source whose top 300 cannot be retrieved. Enabling FantasyPros would therefore make an honest gate dishonest. Publishing nothing keeps every other gate meaningful and makes the enablement trivial later.

**What did come out of it.** FantasyPros joins **by id**, not by name: `sportsdata_id` resolved 40/40 through the Sportradar index and `player_yahoo_id` 36/40 through Yahoo. It needs none of FFC's linkage. And the ECR itself is real and correctly scoped — `rank_ecr`, `rank_ave`, `rank_min/max/std`, `pos_rank`, 93–109 experts, and STD/HALF/PPR genuinely reorder — so the moment the tier allows a complete response, the work is done.

**Attribution ships regardless.** `Data` → `07 Sources and attribution` names FantasyPros, says the key never reaches the page, and says why no number is published. A source read server-side is a source used, and their terms ask for attribution whether or not a number is displayed.

**Revisit when:** a key whose responses omit `public_api_limited` (or set it false) and whose `count` equals the rows delivered. That is the exact, checkable condition, and the adapter already tests for it on every capture.

---

## ADR-065 — One comparison per source, and a median that is never promoted to a price

**Date:** 2026-09-02 (Phase 10)

**Status:** **Accepted and implemented.** `arbitrage_record` 1.1 → **1.2**, additive.

**Context.** Release 1 had one price and one gap, so "the market" needed no qualification. Release 2 has several. Release 2's guardrail 2.3 forbids averaging unlike market signals into an opaque consensus, and roadmap 10.4 requires every published comparison to be reconstructable from its components.

**Decision.** Compute one independent comparison per source using A0's frozen arithmetic (ADR-040) unchanged — `rank_gap = market_adp − fair_rank`, `regional_value_gap = ln(market_adp / fair_rank)` — and add a cross-market summary that is labelled a summary everywhere it appears.

**Additive, not a rewrite.** Every 1.1 field keeps its exact meaning and its MyFantasyLeague provenance, so a Release 1 consumer reading by name still finds what it read before (guardrail 2.1). The MFL entry inside `markets` is derived from the same `MarketPrice` the flat fields are written from, so the two views cannot drift.

**ECR is separated structurally, not by convention.** `markets[].market_signal_type` is `const: "adp"` and `expert_consensus.market_signal_type` is `const: "ecr"` in the schema; the cross-market summary filters on signal type; and the consensus gap is named `ecr_gap` rather than `rank_gap`, so a caller reaching for the wrong field gets an `AttributeError` instead of a plausible number. There is no code path that can put an expert rank into `market_adp_median`.

**Expert dispersion gets its own columns.** FantasyPros publishes `rank_ave`, `rank_min`, `rank_max` and `rank_std` across ninety-odd experts. Those are measured in *ranks*; writing them into `min_pick`/`max_pick`/`adp_sd` would put an expert-rank spread under a column named after a draft pick. `consensus_rank_*` exists for exactly that reason.

**`market_adp_median` is a convenience.** The sources describe different populations over different windows — FFC's rolling week against MyFantasyLeague's whole season — so a median across them is a summary with a caveat, and promoting it to canonical would require its own frozen methodology first. The interesting number beside it is `market_disagreement_range`, which is the thing a single-source board could not tell you.

**`league_size` is null unless it was observed.** `MarketPrice.league_size` is the *preset's* team count; it becomes an observation only when the selection rule found an exact cohort (ADR-039). An approximate cohort priced "any league size", so the column stays null — the same refusal FFC's null expresses, reached for a different reason.

**CSV needed a real answer.** A cell holds a scalar, and `str()` on an array of comparisons produces a Python repr. An artifact may now declare a *projection*: an explicit ordered column set and the function that fills it. The arbitrage projection names the source and the signal in every column, because roadmap 10.6 asks for explicit names and because a flattened CSV is exactly where the JSON's structural separation could quietly be undone.

---

## ADR-066 — The market trend is drawn from a published artifact, and up means earlier

**Date:** 2026-09-02 (Phase 10)

**Status:** **Accepted and implemented.** New artifact `market_trend_series.json`, record contract 1.0.

**Context.** Release 1 published the trend as a bare number — `-3.11`, "moving later (less expensive)". Accurate, and hard to feel: a steady drift and a two-day collapse produce the same slope, and only one of them is news. Roadmap 10.7 asks for the same quantity as a shape.

**Decision.** Publish the points, and draw them small.

**The browser must never call a vendor.** A chart that fetched history client-side would put a vendor on the critical path of a static page and would leak the reader's interest to a third party. So the series is generated at build time from the append-only snapshot store the trend was already computed over, published as its own artifact, and fetched like every other `/data/*.json`. The frontend bundle test asserts the fetch list contains no vendor host.

**The orientation is the design problem.** Lower ADP means *earlier* — more expensive, more wanted. Plotted naively, "the market likes him more" is a line that falls, which is the opposite of what a reader's eye reports. The y axis is inverted, the axis is labelled to say so, and the caption prints an arrow *and* a word so the direction survives greyscale and a screen reader. A test asserts the path's last y coordinate is above its first when the ADP fell.

**Sparse history is a state, not an empty chart.** Below three points the component says so in words. Two points make a line that implies a trend the store cannot support, and the store is genuinely young for any newly captured source.

> **Superseded in part by ADR-081 (2026-09-07).** This clause conflated two questions. It is
> right that two points cannot support a *slope*; it is wrong that they cannot be *shown*. A
> retained ADP is an observation whether or not another follows it, and refusing to draw one
> is how a market with seven real snapshots came to read "0 snapshots so far" on a live card.
> The scalar's gate is unchanged and still `phase5_trend_v1`; the chart's threshold is gone.
> The rest of this ADR stands, and the "asserted equal by the cross-artifact validator" claim
> below is now true — ADR-081 wrote the check that was described here and never implemented.

**The scalar stays.** `market_trend` still sorts the table, still exports to CSV, and is still what the accessible summary reads. The chart draws the history that produced it; it does not replace it.

**Scoped to the published surface.** A series for a player no card can open is weight every visitor downloads for nothing. The restriction is by *published row* rather than by tier depth, so a market-surfaced exception (ADR-063) keeps its chart.

> **Narrowed by ADR-081.** The scope is now the published row **per source**: a market that
> priced a player last Tuesday and dropped him by Friday still has observations inside the
> seven-day window, and charting them puts a history under a card that says it has no price.

---

## ADR-067 — Phase 10 is wired into production, and a column exists only if data fills it

**Date:** 2026-09-03 (post-Phase-10 correction)

**Status:** **Accepted and implemented.** No contract version changes; four always-empty CSV columns removed.

**Context.** Phase 10 shipped and merged. The first refreshes after it ran green, deployed, and produced a board that was — in every respect a reader could see — Release 1 with three extra column headings. FFC did not appear. The board was still 300 rows. `FP ECR` and `Spread` rendered an em dash on every row of every preset.

Nothing had failed. Every gate passed, because every gate was measuring the parts in isolation:

* `daily-refresh.yml` captured MyFantasyLeague and Sleeper. It never called `capture-market-source`, so no FFC snapshot was ever retained;
* `pipeline/market.py` called `build_arbitrage_records` with no `extra_quotes`, no `surfaces` and no `surfaced_rows`, so every published row carried one market;
* production published `board.head(TIER_BOARD_DEPTH)` — Phase 4's frozen study depth of 300. `TIER_DEPTH_V2` (500) and `build_surface_universe` were imported by no pipeline at all.

The adapters, contracts, linkage, comparison maths, surface rule and frontend were all built, tested and documented. None of them were connected to the thing that runs every morning. The unit tests passed because they drove the libraries directly; the artifact validator passed because a single-market artifact is a *valid* artifact.

**Decision.**

**The pipeline is wired, and the join is its own module.** `ffdraft.market.extra` reads retained non-MFL snapshots back into `SourceQuote`s and per-source top-N memberships. It is read-only over the store, and a source that is absent, stale (>48h) or wholly unresolved contributes nothing *and says so* in the quality gate and in `build_metadata.json`. A missing market must never again be indistinguishable from a market nobody asked for.

**Published depth is not modelling depth.** `TIER_BOARD_DEPTH = 300` stays exactly where it is: Phase 4's stability evidence was measured against it and changing it there would silently restate that evidence. The CLI now publishes at `TIER_DEPTH_RULE.depth`, and those two constants meet in exactly one line. Raising the published depth also widens the tier segmentation input from 300 to 500 players, which is what `TIER_DEPTH_V2` being a *tier* depth means.

**The surface rule gets the board it needs.** It cannot rescue a player from a board he was already cut from, and the arbitrage stage reads a published artifact that is truncated by definition. `build-current --full-board` writes the untruncated universe outside the published directory; `build-arbitrage --full-board` reads it. Absent, the build behaves exactly as it did before — publish the prefix, rescue nobody — and records that it did.

**A missing market player has two causes and one symptom.** From inside `build_surface_universe`, "not in the board I was given" is either a truncated board (the Release 1 bug, silent, critical) or a player the model never valued (a projection gap, real, not worth taking a live site down for). Only the caller knows which board it passed, so the caller certifies it: `board_is_complete` defaults to `False`, because a caller who has not thought about it is exactly the one who might be passing a prefix. Membership is also restricted to `CORE_POSITIONS` — a kicker was never eligible for a V1 board, and counting one as missing would fail a production build over a player the model is not supposed to rank.

**A column is a promise that there is something in it.** `FP ECR` is removed from the arbitrage table and its four `fantasypros_ecr*` columns from the CSV projection: FantasyPros publishes nothing at the provisioned API tier (ADR-064) and an always-empty column is a claim the artifact cannot keep. The remaining market-dependent columns — Dispersion, Spread — are rendered only when some row in the current view has a value, so a market that is absent, stale or newly added is handled without anyone editing a component. `Trend` is deliberately exempt: its empty state is *specified* (an em dash means "no evidence yet", never `0`; ADR-042), which is not the same thing as a column for a market that was never captured.

**Consequences.** FFC capture is `continue-on-error`: a second market is an enrichment, and its outage must degrade the board to one market rather than fail the refresh that publishes the intrinsic tiers. The tier board is 500 rows per block rather than 300, so artifact bytes and table rows grow by roughly two thirds. Tier boundaries in the top 300 may move, because the segmentation now sees 500 players — that is a consequence of the decision, not a side effect of it, and the first production build is where it becomes measurable.

**What this was really about.** Every individual piece of Phase 10 was correct. What was missing was the question "what will a reader see tomorrow morning?", asked against the pipeline that actually runs rather than against the tests. A test suite that drives libraries directly cannot answer it, and neither can a validator whose job is to accept any well-formed artifact.

**Correction, one refresh later.** The first production build after this shipped failed on `cross_artifact.arbitrage_player_not_in_tiers` for ten players in `redraft-10`. The rule says every arbitrage row must describe a player the tier artifact publishes — true for the whole of Release 1, and false the moment the surface rule started rescuing players from beyond the published depth. A surfaced player is *deliberately* on the arbitrage board and *deliberately* absent from tiers; requiring the subset relation forbids the rescue.

The invariant now exempts a row that **declares** itself an exception, in both `outside_tier_board` and `surface_reasons`. The failure the rule was written for — an arbitrage row for a player the board has no valuation for at all — is untouched and still critical, and half a declaration earns nothing. The exemption also makes a new lie reachable, so it is checked: a row flagged as beyond the tier depth while tiers publishes him is `cross_artifact.surface_exception_is_on_the_board`.

That this was found by a production build rather than by a test is the same lesson twice. Wiring the emission of surfaced rows without asking which existing invariants described the old shape is exactly the gap this ADR was written about.

**Correction, two refreshes later — and the reason there were three.** The next build failed `verify:board` on all thirty arbitrage rows against a page that was *right*: the board defaults to FFC, whose seven-day window prices a riser earlier than MyFantasyLeague's season aggregate, and the verifier compared the rendered cell to the flat V1 `market_adp`, which is MFL's.

The audit that followed found the same assumption in three more places. The draft rail rendered `market_adp` and said "MyFantasyLeague ADP" while the table followed the selector — and claimed, in its own words, that *"the arbitrage table below carries the same numbers."* The player card's tile was labelled `MFL ADP`. A `board.spec.ts` check read the Trend column by cell index and broke when Spread appeared, which is the third time positional indexing has broken a check here.

**The root cause of all of it: no fixture in the repository had ever carried a second market.** Not the Python golden artifact, not the TypeScript fixtures. Every local gate — 1,212 Python tests, 272 vitest, 70 Playwright, `verify:board`, `validate-artifacts` — ran against a single-market bundle with no surfaced rows. Every consumer that only misbehaves on the real shape was invisible until a production refresh hit it, and each fix revealed the next one because the fixture still could not reproduce any of them.

So the fixture now carries what production produces: two markets that **disagree** (agreement would hide a consumer reading the wrong one), a third of rows priced by only one market, asymmetric dispersion fields, and a surfaced player with a real price. Both fixture generators build it, so every gate exercises it without anyone remembering to.

Two decisions the owner took on the back of it. **The selector governs the whole page** — rail, card and table read the chosen market, and the card's readout is labelled by the source the number actually came from rather than by the selection, because the cross-market view resolves to one real source. **An unpriced row keeps its place** and shows an em dash: a source covering part of the board is normal, and hiding him would make the board's population depend on which market you were reading.

One regression this uncovered had nothing to do with markets. The selector renders only when a build publishes two or more, so on a phone it had never been laid out at all; as a numbered section with an explanatory paragraph it pushed the board itself below the fold. It is a control now, sized like one, and its note is dropped under 30rem — the labels already read `FFC Recent` and `MFL Cumulative`, so the window is in the control rather than in a sentence beneath it.

## ADR-068 — The rest-of-season grain, and why a snapshot's membership is a cutoff rule rather than a season rule

**Status.** Accepted, Phase 11.

**Context.** Phase 11 needs a training grain for a model that answers "given the season so far".
The roadmap fixes it as `season × through_week × player × scoring_preset` and asks for the
cutoff rule to be "explicit and testable".

**Decision.** `ros_cutoff_v1`: a snapshot **through week N** of season Y may read completed
regular-season weeks `1..N` of season Y and any season strictly before Y, and predicts weeks
`N+1..horizon.last_week` of season Y. Week 0 is refused, because that snapshot is the
preseason board and the preseason board is `intrinsic-cb-hurdle-v1`'s job. The last modelled
snapshot is `last_week − 1`, because a snapshot with an empty remaining horizon has no label
to learn from and would only teach the model that seasons end — which
`remaining_horizon_weeks` already says.

The universe is the union of the season's leakage-safe preseason eligible universe and
everyone with a scored appearance at or before the cutoff.

**The part that was nearly wrong.** The first implementation made universe membership a
*season* property: anyone who appeared anywhere in season Y got a row at every cutoff of
season Y. That puts the fact of a week-9 signing into a week-3 snapshot. The row looks
innocuous — zero games, zero points, every rate null — but its *existence* is information
from six weeks in the future, and a production week-3 build could not have produced it.

It was found by the constructive leakage audit rather than by review: rebuilding week 3 from a
panel truncated at week 3 produced 96 rows where the full build produced 120. The published
dataset had in fact never contained those rows — a downstream `position` filter dropped them,
because position for an unobserved arrival is null — so nothing shipped wrong. That is luck,
not design, and the rule is now enforced where it belongs, in
`ffdraft.ros.features.build_in_season_features`, where the audit can see it.

**Consequences.** A mid-season arrival exists in the dataset only from the snapshot that first
observes him; a preseason-universe player who never appears keeps a zero-labelled row at every
cutoff, because dropping him is survivorship bias. 8.7% of players in the 2017-2025 build are
in-season arrivals, and they are reported as their own predeclared cohort.

---

---

## ADR-069 — 2025 is the rest-of-season sealed season, and it is not a fully naive one

**Status.** Accepted, Phase 11.

**Context.** The roadmap requires "one final sealed season evaluated only after architecture and
promotion rules freeze". Two seasons were available: 2025, the most recent fully labelled one,
and 2024, which no part of this project has ever evaluated anything on.

2025 is not neutral. Phase 4 opened it once, as the **preseason** model's final holdout
(ADR-025), so this project has seen 2025 season-total outcomes.

**Decision.** Seal 2025, and state the qualification rather than glossing it.

2025 is the closest available analogue of the 2026 in-season environment the model will run in
— the same 18-week schedule, the same upstream coverage, the same depth-chart era. Sealing 2024
instead would buy a fully naive result at the cost of a season further from production and one
fewer development fold, and would leave the most production-like season permanently unusable
for evaluation.

What has never been examined is any 2025 *rest-of-season* snapshot, through-week label or
metric on them. The seal is structural, not conventional: `load_ros_dataset` drops the rows
unless a `RosFinalEvalAuthorization` carrying `RELEASE-ROS-FINAL-HOLDOUT-2025` is supplied, and
Release 1's token does not work here (nor this one there) — opening one holdout must never open
the other.

**Consequences.** A 2025 rest-of-season result is strong but not fully naive evidence, because
season totals correlate with rest-of-season totals. Every report and the model card say so.
The residual exposure is bounded and stated; it is not zero, and pretending otherwise would be
the more misleading choice.

---

---

## ADR-070 — `intrinsic-ros-v1` has no injury or practice-report feature

**Status.** Accepted, Phase 11.

**Context.** The single largest driver of rest-of-season availability is injury, and nflverse
publishes weekly injury reports back to 2009. Roadmap 11.3 nonetheless says: *"Current
injury/status data should remain annotation-only unless Phase 11 proves a historical,
point-in-time injury source with adequate coverage."*

**Decision.** No injury or practice-report feature enters the model. The reasons are
operational rather than aesthetic:

- this repository has never ingested the feed, so there is no adapter, no recorded schema, no
  measured coverage and no fail-closed behaviour for it;
- there is no production capture path, so a feature trained on it could not be served;
- the *point-in-time* question is unanswered. A weekly injury table can be rebuilt after the
  fact; whether the week-6 row reflects what was known in week 6 is exactly what
  `verify_before_use` exists to establish, and establishing it is a source-probe task, not a
  modelling one.

Admitting it on the strength of "the current data exists" is the move 11.3 forbids, and it is
the same move ADR-011 refused for preseason injuries.

**What carries the signal instead.** `weeks_since_last_game`, `consecutive_weeks_missed`,
`games_share_to_date` and `active_last_week`. They are football-only, reproducible at every
historical cutoff, and they say what an injury feed would say a week later: this player has not
been on the field.

**Consequences.** The model is worst on players returning from a long absence, which is
reported as its own predeclared cohort rather than pooled away. The revisit condition is
explicit: a recorded schema, a measured historical point-in-time coverage rate, a capture path
in the daily refresh, and a fail-closed check — the same four things every other source in
`config/source-registry.yaml` had to produce.

---

---

## ADR-071 — In-season replacement is the best **unrostered** player, not the best unstarted one

**Status.** Accepted, Phase 11. Rule `ros_replacement_v1`; measured in
`docs/experiments/phase11-ros-value/value_study.md`.

**Context.** Roadmap 11.5 refuses to let this be assumed: *"Do not silently assume preseason
draft opportunity cost and in-season roster replacement are identical concepts."* Release 1's
replacement baseline is the best player nobody **starts**, after allocating the whole board
into the league's starting slots. That is draft opportunity cost — what it costs to spend a
pick rather than take the next player at the position.

In November nobody is spending a pick. The alternative to holding a player is the waiver wire,
and the waiver wire is the best player nobody **rosters**.

**Decision.** The rest-of-season board uses `rostered_depth`: after the starting slots are
filled, fill `teams × bench` bench places, then take the best player nobody rosters.

**The bench is filled by surplus over the starting-slot baseline, not by raw points.** A
points-greedy bench would hoard quarterbacks, whose raw totals dwarf every other position and
whose marginal value over a freely available quarterback is almost nothing. Surplus is what a
manager actually compares, and it makes the rule self-consistent: the same quantity decides who
is rostered and what replacement is.

**The rule was frozen before the measurement, and it defaults the other way on a tie.** If the
two interpretations were indistinguishable on the published board — fair-rank Spearman ≥ 0.999,
mean |Δrank| in the top 150 ≤ 1.0 and top-50 overlap ≥ 0.98 in *every* scenario — Release 1's
rule would be retained for continuity.

**What was measured.** Twelve scenarios (three scoring presets × weeks 1, 4, 8 and 12), both
rules over identical simulated seasons, `redraft-12`, 10,000 draws:

- worst fair-rank Spearman **0.9981** (threshold 0.999);
- largest mean |Δrank| inside the top 150 **2.15** (threshold 1.0);
- smallest top-50 overlap **0.940** (threshold 0.98);
- largest single rank change **41 places**.

Every clause of the indistinguishability test fails somewhere, so the in-season meaning is
used. The disagreement is not enormous — the two boards agree on 94-100% of the top fifty — but
it is systematic, it is largest at the positions where bench depth is real, and a board that
called it noise would be asserting something the measurement contradicts.

**Consequences.** `ros_expected_vorp` is not comparable with the preseason `expected_vorp`, and
the public column names say so (`ros_fair_rank`, `ros_vorp_p25/p50/p75`, `ros_tier`). The
`bench` field of `config/league-defaults.yaml`, which V1 carried for user context only, becomes
load-bearing for the rest-of-season board. Release 1's draw loop takes the allocation rule as a
parameter whose default is unchanged, so every preseason artifact is byte-identical and there
is one draw loop in the repository rather than two that could drift.

---

---

## ADR-072 — The rest-of-season evaluation cell is one week's board

**Status.** Accepted, Phase 11.

**Context.** Phase 3's evaluation cell is `validation season × position × scoring preset`, and
the paired bootstrap resamples rows within it. At the rest-of-season grain that would be wrong:
a player contributes sixteen rows to a season, so a season-level cell contains the same player
sixteen times and a row bootstrap would treat those repeats as independent observations. The
interval would be too narrow, and the gate reads intervals.

**Decision.** The cell is `season × through_week × position × scoring_preset` — one week's
board. Within it every row is a different player, which is both the unit a fantasy decision is
made over and the unit a row bootstrap is valid on. Macro means across cells then weight a week
in September the same as a week in December, and a top-K retrieval metric means "the right
twenty-four receivers for the rest of *this* season", which is the question a reader is asking.

**Consequences.** There are roughly 960 development cells rather than 60, so the bootstrap is
the slowest stage of the experiment. Cohort rank correlations are macro-averaged over the cells
a cohort touches rather than pooled, because pooling would rank a week-2 quarterback against a
week-14 tight end — a comparison no board makes.

---

---

## ADR-073 — `RC1` beats every declared baseline and is not promoted, because the coverage clause fires on the zero-game cohort

**Status.** Accepted, Phase 11. The candidate is **not promoted** under `ros_promotion_v1`.

**Context.** The frozen gate was committed before the candidate existed (`c7815f9`, then
`af30b38`). Five chronological folds, 253,197 scored rows, 948 evaluation cells, four declared
baselines and one candidate. The comparator was picked by the frozen rule — lowest development
macro pinball loss — and that is `R2`, the shrinkage blend.

**What was measured.**

| model | MAE | pinball | Spearman | P10-P90 coverage |
|---|---|---|---|---|
| R0 preseason prorated | 14.05 | 5.313 | 0.578 | 0.785 |
| R1 current rate | 11.05 | 4.500 | 0.779 | 0.805 |
| **R2 shrinkage blend** | 12.32 | **4.444** | 0.677 | 0.790 |
| R3 availability prior | 15.83 | 5.520 | 0.751 | 0.693 |
| **RC1 hurdle** | **9.86** | **3.635** | **0.797** | 0.869 |

`RC1` minus `R2`, paired within cell over 1,000 replicates: MAE **−2.4632**
[−2.5305, −2.3958]; mean pinball **−0.8084** [−0.8328, −0.7857]; Spearman **+0.1203**
[+0.1184, +0.1229]. All three intervals exclude zero. Clauses 1, 2 and 3 pass comfortably.

**Clause 4 fails on one cohort.** `games_played_band / no_games` — 131,844 rows, 52% of the
frame, every player who has not appeared yet at his snapshot's cutoff — records a candidate
P10-P90 coverage of **0.964**, above the band's 0.95 ceiling.

**Decision. The threshold does not move, and the candidate is not promoted.**

The coverage band exists to catch an interval so wide it says nothing. The evidence says this
is not that:

| | baseline `R2` | candidate `RC1` |
|---|---|---|
| MAE | 5.82 | **2.05** |
| P10-P90 coverage | 0.825 | 0.964 |
| mean P10-P90 width | 17.1 | **14.5** |

The candidate's interval on this cohort is **narrower** than the baseline's and covers more of
the outcomes. That is not a vacuous interval; it is an interval correctly concentrated on an
atom. Rather more than half of these rows have a true remaining-points value of exactly zero,
because a player who has not played by week N frequently never plays at all, and a P10-P90
band that straddles zero contains the outcome exactly.

So the clause is firing on a property of the *target distribution* rather than on a defect in
the model. That is a finding about the rule, and the rule is not edited in response to the
result it produced — that is the move `AGENTS.md` section 8 and the whole Phase-3/Phase-4
precedent exist to prevent. Phase 4 shipped two failing gates as published limitations
(ADR-034, ADR-035) rather than moving their thresholds, and this is the third.

**What a successor rule would have to do**, and what it may not do: a coverage clause that
handles an atom needs to be *stated before* it is measured, not fitted to this cohort. The
obvious candidates — splitting coverage by whether the outcome is zero, or scoring the atom
separately from the continuous part — are both defensible and both need their own ADR, their
own freeze and their own evaluation. Raising the ceiling to 0.97 because 0.964 was observed is
not one of them.

**Consequences.**

- `intrinsic-ros-v1` is **not** a promoted production model. Phase 12 inherits a measured,
  reproducible, non-promoted candidate and the exact clause that stopped it.
- Nothing is published. No artifact, no schema, no frontend surface.
- The gate's other clauses did their job: the candidate is decisively better on every primary
  metric, no position collapses, and eleven of the twelve required cohorts are clean.
- The two cohorts a reader should look at next are `three_plus_games` (MAE 16.44 → 16.09, the
  smallest gain on the board: once a player has real current-season evidence, the blend is
  nearly as good) and `returning_from_absence` (Spearman 0.294 → 0.311, both near-random —
  the cohort ADR-070 predicted would be worst, and it is).

**The sealed season says the same thing.** 2025 was opened once, after the architecture, the
promotion rule and the replacement decision were all committed. 53,307 rows, 192 cells, one
fold trained on 2017-2024:

| model | MAE | pinball | Spearman | P10-P90 coverage |
|---|---|---|---|---|
| R2 (comparator) | 11.59 | 4.140 | 0.679 | 0.809 |
| RC1 | **9.34** | **3.427** | **0.795** | 0.870 |

Paired: MAE **−2.2497** [−2.3774, −2.1285]; pinball **−0.7136** [−0.7513, −0.6755]; Spearman
**+0.1163** [+0.1120, +0.1216]. Every development conclusion reproduces out of time, including
the failure: `no_games` coverage is **0.957**, still above the ceiling and still on a *narrower*
interval than the baseline's (11.3 against 14.6).

One additional cohort fails on 2025 and did not in development: `in_season_arrival`, MAE
**1.08 → 1.69** on 315 rows. It is worth reading rather than dismissing. On 2025's in-season
arrivals the baseline predicts approximately nothing with a 1.7-point interval and is mostly
right, because most of them scored approximately nothing; the candidate spreads 13.9 points of
interval over them. The candidate is nonetheless *better ordered* on the same rows — Spearman
−0.060 against +0.160, i.e. the baseline is worse than random and the candidate is weakly
positive. A 315-row cohort where the incumbent wins by confidently predicting zero is exactly
the kind of finding a cohort clause exists to surface, and it is surfaced rather than pooled
away.

**The holdout is spent.** It was opened once, for the frozen architecture, and it cannot be
reused. Any successor candidate needs a different evaluation strategy and a future season.

---

## ADR-074 — Rest-of-season convergence and tier stability fail the same frozen gates the preseason board failed

**Status.** Accepted, Phase 11. Both failures published, neither threshold moved.

**Context.** The frozen `phase4_convergence_v1` and `phase4_tier_stability_v1` rules are pure
functions of measured evidence, stated on quantities a reader of the board sees. Phase 11
reuses them unchanged rather than inventing rest-of-season versions, which is what holds the
in-season board to the same bar as the draft board.

**Convergence: no qualifying draw count.** The ladder is [1000, 2500, 5000, 10000]. At 10,000
draws, seed-to-seed comparison still breaks three tolerances:

- `PPR w04` mean |Δrank| in the top 150 **1.63** against a 1.50 bound;
- `PPR w04` tier ARI **0.451** against a 0.900 bound;
- `PPR w12` tier ARI **0.811** against a 0.900 bound.

The value quantities are fine — mean |Δ expected VORP| is 0.244 against a 0.25 bound and mean
|Δ P50 VORP| 0.278 against 0.35. What does not converge is the **tier partition**, which is a
restatement of the stability finding below rather than a separate one: a boundary that is not
sharply located moves between two seeds of the same simulation. 10,000 is used as the declared
fallback and the breaches are recorded, exactly as ADR-034 did preseason.

**Tier stability: boundary agreement 0.167 against a 0.500 bound.** Everything else passes, and
by a distance: bootstrap ARI **0.857**, singleton rate **0.000**, tier-count CV **0.074**,
cross-preset ARI **0.524**, and realized remaining VORP falls across **100%** of adjacent tier
pairs. So tier *membership* is highly reproducible and tiers *order realized value perfectly*;
what is not reproducible is exactly where one tier stops and the next begins.

That is the same failure mode Phase 4 measured preseason (agreement 0.239) and the same
response: a rest-of-season tier is a band, never a line, and any surface that shows one must say
so. `phase4_tier_v1` selects penalty **3.0** — 6.8 mean tiers, no singletons, largest tier 25%
of the board.

**Consequences.** Phase 12 inherits a tier boundary it may not draw as a hard edge, and a draw
count that is a fallback rather than a converged value. Both are published limitations rather
than repaired thresholds, for the third and fourth time in this repository.

---

## ADR-075 — `ros_promotion_v1` clause 4 measured the target, not the model; `ros_promotion_v2` states the same intent on quantities that survive an atom

**Status.** Accepted, Phase 11. Frozen and committed **before** being applied to any evidence.
`ros_promotion_v1` is unchanged, still in the codebase, still evaluated and still reported;
ADR-073's record that `RC1` failed it stands.

**Context.** v1 clause 4 required every decisive cohort's empirical P10-P90 coverage to lie
inside `[0.60, 0.95]`. `RC1` failed on one cohort, `games_played_band / no_games`, at 0.964.
ADR-073 recorded the failure, refused to move the threshold, and named the open question: is a
coverage clause stated as an absolute band the right instrument for this target at all?

**The arithmetic says no, and it is not a close call.**

A P10-P90 interval covers 80% of outcomes *for a continuous target*. That is a theorem about
continuity, not a property of good forecasting. Write `F` for a row's true predictive CDF and
`F⁻¹(u) = inf{y : F(y) ≥ u}` for the generalized inverse any quantile model reports. A
**perfectly calibrated** forecaster's closed interval covers

```text
P(F⁻¹(0.10) ≤ Y ≤ F⁻¹(0.90)) = F(F⁻¹(0.90)) − F(F⁻¹(0.10)−)
```

* continuous `F` — both terms are exact, coverage is 0.80;
* an atom of mass `p ≥ 0.10` at zero, with `Y` effectively bounded below by it — then
  `F⁻¹(0.10) = 0`, `F(0−) = 0`, and coverage is `F(F⁻¹(0.90)) = 0.90`, **exactly**, however
  large the atom;
* an atom of mass `p ≥ 0.90` — both reported quantiles are zero, the interval collapses to the
  single point zero, and coverage is `p` itself.

The third case is decisive: a **perfectly calibrated forecaster with an interval of width zero
breaches v1's 0.95 ceiling.** A clause written to catch "an interval so wide it says nothing"
refuses the narrowest possible correct interval. That is not a strict threshold; it is the
wrong measurement. A test asserts each of the three cases on synthetic data.

**And the measurement agrees.** The climatological reference (`ffdraft.ros.reference`) — the
coverage a forecaster that knows the evaluation cell and the cohort but nothing about the
player attains, computed from outcomes alone — across the twenty-two development cohorts:

| cohort | P(Y=0) | attainable coverage | climatological width |
|---|---|---|---|
| `full_universe / all` | 0.568 | 0.893 | 65.6 |
| `games_played_band / no_games` | **0.885** | **0.926** | **4.5** |
| `high_capital_rookie` | 0.099 | 0.898 | 136.0 |
| `high_capital_underperforming` | 0.180 | 0.843 | 63.4 |
| every cohort measured | 0.099-0.885 | **0.843-0.926** | 4.5-136.0 |

**Not one cohort has an attainable coverage near 0.80.** The band was centred on a value the
target distribution makes unreachable everywhere, and on the zero-game cohort the 0.95 ceiling
sits 0.024 above what calibration itself achieves. v1 clause 4 was measuring how much
probability mass the target puts on a single point.

**Decision. `ros_promotion_v2`.** Clauses 1-3 are v1's, unchanged — they were already stated on
a proper scoring rule, a point metric and a rank metric, none affected by the target's shape.
Clause 4 keeps v1's intent and states it on quantities that survive an atom:

| | clause | change |
|---|---|---|
| 4a | cohort MAE at most 5% worse | **unchanged from v1** |
| 4b | cohort Spearman at most 0.030 worse | **unchanged from v1** |
| 4c | cohort mean **pinball loss** at most 5% worse | **new** — proper, atom-safe, the local analogue of clause 1 |
| 4d | interval fails only if wider than **both** the baseline's **and** climatology's | **replaces** the coverage ceiling |
| 4e | coverage within **±0.15 of the cohort's attainable coverage** | **replaces** the absolute band |

*Why 4c.* Pinball loss is a proper scoring rule for quantile forecasts and is well defined for
a mixed discrete-continuous target. It is the clause that actually detects a distributionally
worse forecast — the job v1 was asking a coverage band to do, which a coverage band cannot do.

*Why 4d.* "An interval so wide it says nothing" means *wider than knowing nothing*, and
climatology is what knowing nothing looks like. An atom makes a calibrated interval **narrower**,
so 4d cannot be tripped by the phenomenon that tripped v1. A test asserts that the exact
configuration an atom produces — narrower than the baseline, better covered — can never fail it.

*Why 4e, and why it is not a loosening.* The band moves with what calibration can attain
instead of sitting at a fixed 0.80. On a continuous cohort the reference **is** 0.80 and 4e
reduces to `[0.65, 0.95]`. The tolerance, 0.15, is **v1's own upper allowance** (0.95 − 0.80)
applied to both sides, which **tightens** the under-coverage allowance from v1's 0.20 to 0.15.
A test asserts the consequence: a cohort covering 0.62 against a continuous reference passes v1
and **fails v2**. A rule reverse-engineered to admit a particular candidate would have loosened
a bound; this one loosens none, and adds a clause v1 did not have.

**The reference is a diagnostic of the target, never a competitor.** It is computed from
outcomes only — no model input, no prediction, no fitted parameter — is identical for every
model compared against it, and cannot win or lose a comparison. A test asserts it is invariant
to adding a prediction column.

**What v2 does not do.** It does not raise a ceiling. It does not exempt a cohort. It does not
weaken clauses 1-3. It does not alter, replace or repeal `ros_promotion_v1`, whose thresholds,
code and verdict on `RC1` are preserved verbatim, reported alongside v2's in every report, and
recorded in ADR-073.

**Freeze discipline.** This ADR and `ros_promotion_v2` were committed before the rule was
applied to any evidence, in the same shape the original gate was frozen before the candidate
existed. Clauses 4c, 4d and 4e are all live and all capable of refusing `RC1`; whatever they
say is what gets reported.

**Consequences.** Every rest-of-season report carries two verdicts. Comparing a future
candidate against `RC1` must use v2, because v1 cannot rank two models on a zero-inflated
cohort. The preseason model's gates are untouched: `phase3_promotion_v1` judges a season-total
target whose zero share is 44%, and whether its own coverage clause is mis-specified for the
same reason is a real question this ADR does not answer and does not touch.

---

## ADR-076 — The sparse-history and long-absence cohorts: no model change, and what each one costs

**Status.** Accepted, Phase 11. Decided on **development evidence only** (2020-2024, 253,197
rows). The sealed season is spent and is not an input to anything below.

### `in_season_arrival` — no special handling

4,296 development rows: players outside the season's preseason eligible universe, whose entire
preseason feature block is null. The question is whether the production model needs a
deterministic fallback to one of the declared simple baselines on sparse-history rows.

| | baseline `R2` | candidate `RC1` |
|---|---|---|
| mean pinball | 3.122 | **2.477** (−20.7%) |
| Spearman | 0.492 | **0.552** |
| MAE | 6.82 | **6.73** |
| P10-P90 coverage | 0.659 | **0.867** |
| attainable coverage | 0.896 | 0.896 |
| coverage gap | **−0.237** | **−0.029** |
| mean P10-P90 width | 12.0 | 25.3 |
| climatological width | 28.3 | 28.3 |

**Decision: no fallback, and no model change of any kind.**

The candidate wins the proper score by 21%, wins ordering, and edges MAE. What looks at first
like the baseline's advantage — a 12.0-wide interval against the candidate's 25.3 — is the
defect, not the merit: climatology on this cohort is 28.3 wide, so `R2` is claiming to know
these players more than twice as precisely as knowing nothing, and it pays for that with a
coverage of 0.659 against an attainable 0.896. It under-covers by 0.237. Were `R2` the
candidate it would fail `ros_promotion_v2` clause 4e outright.

Swapping a well-calibrated forecast for an overconfident one, on precisely the cohort with the
least information, would be the wrong trade in the direction that matters least visibly.

**Two constraints reinforce it.** First, `RC1` already carries the honest signal: the
`in_preseason_universe` indicator is a declared model input, so the model *knows* these rows are
sparse and widens accordingly — a fallback would be hand-coding what the model already does.
Second, and decisively: **a fallback would change production outputs, and there is no sealed
season left to make an honest promotion claim about the changed model.** 2025 is spent
(ADR-069). Inventing a fallback now would either be evaluated on the data that selected it or
not evaluated at all. Neither is acceptable, and the correct response to that is to not make
the change.

**On the already-published 2025 figure.** `final_holdout.md` records `in_season_arrival` MAE
1.08 → 1.69 on 315 rows, a cohort a twelfth the size of the development one. It is not an input
to this decision and was not used to reach it. Read against the development evidence it is the
same phenomenon rather than a contradiction: a baseline that predicts approximately zero with a
1.7-point interval wins MAE on a cohort that mostly scored approximately zero, and the same
baseline under-covers by 0.237 in development. Nothing here is a reason to change the model,
and if a future phase disagrees it needs a future season, not this one.

### `returning_from_absence` — a real limitation, no model change, a disclosure requirement

18,951 development rows (7.5% of the frame): players who have appeared this season but have
missed at least three consecutive weeks ending at the cutoff.

| | baseline `R2` | candidate `RC1` |
|---|---|---|
| mean pinball | 2.820 | **2.352** |
| MAE | 8.39 | **6.44** |
| Spearman | **0.294** | **0.311** |
| coverage / attainable | 0.814 / 0.864 | 0.912 / 0.864 |

`RC1` is better on every axis. **Both are close to unable to order this cohort at all.** A
Spearman of 0.311 means a rest-of-season ranking *within* the returning-from-absence group is
barely better than arbitrary — against 0.797 on the full universe. That is the measured price
of having no injury feed, and it is exactly the cohort ADR-070 predicted would be worst.

**No injury feature is added.** ADR-070's four conditions — a recorded schema, a measured
historical point-in-time coverage rate, a capture path in the daily refresh, and a fail-closed
check — are unchanged and unmet, and "the current data exists" is still not one of them.

**What Phase 12 must therefore communicate.** The model infers absence from the box score
alone: a player cleared to return this week and a player out for the season are, to it,
identical rows that have not appeared for N weeks. A rest-of-season number for such a player
is a statement about football history, not about medical status, and a reader who mistakes the
two is being misled by the product rather than by the model. Phase 12 must therefore:

1. carry a **machine-readable per-row flag** in the published artifact, set by the same
   condition this cohort is defined by — `has_played_this_season` and
   `consecutive_weeks_missed >= 3` — versioned in the artifact schema like every other public
   field;
2. publish `weeks_since_last_game` alongside it, so the claim is checkable rather than asserted;
3. state, wherever such a row is shown, that the estimate uses **no injury or practice-report
   information** and infers absence from appearances only;
4. never present the flag as a status, a designation, or medical knowledge — the honest phrasing
   is "has not appeared for N weeks", which is what the model actually knows;
5. not encode it by colour alone (`AGENTS.md` section 11), and
6. surface the measured ordering weakness rather than only the flag: within this cohort the
   board's order is close to uninformative, and the published limitation list must say so.

This ADR specifies the contract. Phase 12 implements it; Phase 11 builds no UI.

---

## ADR-077 — `RC1` is accepted for Phase 12, and what Phase 12 inherits with it

**Status.** Accepted, Phase 11.

## `RC1 ACCEPTED FOR PHASE 12`

`intrinsic-ros-v1` (`rc1_ros_hurdle_v1`) is a **production-ready rest-of-season model** under
`ros_promotion_v2`. It remains, permanently and on the record, a model that **failed**
`ros_promotion_v1` (ADR-073). Both statements are true, both are published, and neither
replaces the other.

**Why the v1 failure is a gate-specification issue and not a model defect.** ADR-075 has the
argument and the proof; in one line: v1 bounded cohort coverage against a nominal 0.80 that
only a continuous target attains, and this target is 56.8% zeros. A perfectly calibrated
forecaster with an interval of **width zero** breaches v1's ceiling — a clause written to catch
"an interval so wide it says nothing" refuses the narrowest possible correct interval. The
climatological reference confirms it across all twenty-two cohorts: calibration attains
0.843-0.926, never 0.80. On the cohort that failed v1, `RC1`'s interval is **narrower** than
the baseline's (14.5 against 17.1), its MAE is **a third** of it (2.05 against 5.82), its
pinball loss is **43% better** (0.994 against 1.754), and it sits **closer to attainable
calibration than the baseline does** (+0.039 against −0.101).

**Why this is not a threshold moved to fit a result.** The successor was committed in `5e532c7`
containing the rule and no result, and applied afterwards to the frozen prediction frame the
original run wrote — the same rows, no refit, macro metrics reproducing to the digit. It keeps
every v1 threshold that remained meaningful, adds a clause v1 did not have (4c, a proper local
score), and **tightens** the under-coverage allowance from 0.20 to 0.15.

The measured consequence of that tightening is the strongest evidence available, because it
cuts against the outcome:

| cohort | candidate coverage | attainable | gap | v2 headroom |
|---|---|---|---|---|
| `high_capital_rookie` | 0.763 | 0.898 | **−0.135** | **0.015** |
| `changed_team_in_season` | 0.782 | 0.900 | −0.118 | 0.032 |
| `extreme_uncertainty` | 0.781 | 0.880 | −0.098 | 0.052 |
| `games_played_band / no_games` | 0.964 | 0.926 | +0.039 | 0.111 |

Every one of those three near-misses is a **comfortable pass under v1** and a near-failure
under v2, and all three are on the *under*-coverage side. `RC1` passes its successor gate with
**0.015** of headroom on its tightest clause — a rule written to let it through would not have
left it hanging by a hundredth on a clause it made stricter. The cohort v1 refused it for is
now only the tenth-tightest of twenty-two.

**What Phase 12 inherits.** All of it is measured, none of it is repaired:

1. **The model is overconfident on high-draft-capital rookies.** Coverage 0.763 against an
   attainable 0.898 — the tightest clause in the gate, 0.015 from failing. A re-measurement on
   new data could push it over. This is the first thing to check on any future evidence.
2. **It cannot order the long-absence cohort.** Spearman 0.311 on 18,951 rows against 0.797 on
   the full universe. ADR-076 specifies the six-part disclosure contract this obliges.
3. **Its intervals on the zero-game cohort are conservative.** 14.5 wide against a
   climatological 4.5 — narrower than the baseline and better scored, but wider than the near
   point mass the cohort actually is. Not a gate failure; a real observation.
4. **The sealed season is spent.** 2025 was opened once, before this readiness pass began, and
   this pass changed no model output — no fallback, no retrain, no tuning, no feature — so the
   published out-of-time result still describes the model being accepted. **Any future change to
   `RC1`'s outputs invalidates that and needs a fresh sealed season.** That constraint is why
   ADR-076 declines a sparse-history fallback rather than designing one.
5. **The tiers are bands, not lines**, and the draw count is a fallback rather than a converged
   value (ADR-074). Unchanged.
6. **There is still no injury feature** (ADR-070), and the cohort that needs one is measurably
   the worst.

**What "accepted" does and does not license.** It licenses Phase 12 to build the in-season
product on `intrinsic-ros-v1` as a promoted model. It does not license publishing a number
without the ADR-076 disclosures, drawing a tier boundary as a line, changing the model's
outputs without a new sealed season, or presenting `ros_fair_rank` as comparable with the
preseason `fair_rank`.

**`ros_promotion_v2` was deliberately not applied to the sealed season.** The saved 2025
prediction frame is on disk and re-scoring it would have cost one command, so the omission is a
choice rather than an oversight. 2025 is spent: it was opened once to measure the frozen
architecture, and running a *newly written rule* against it would be using the sealed season to
evaluate the rule — a second bite at the one thing that only works once. `final_holdout.md`
therefore still carries the v1 verdict alone and is byte-identical to the version committed
before this pass. The acceptance rests on development evidence, which is where a promotion
decision belongs; the sealed season's contribution is what it always was, an out-of-time check
that every development conclusion reproduced.

**Evidence.** `docs/experiments/phase11-ros/experiment.md` (both verdicts, side by side),
`docs/experiments/phase11-ros/final_holdout.md` (the spent season, v1 verdict, unchanged),
`docs/experiments/phase11-ros-value/value_study.md`, `models/cards/intrinsic-ros-v1.md`.

---

## ADR-078 — A post-promotion production refit is not a model change: `ros_production_fit_v1`

**Status:** Accepted, Phase 12. Amends ADR-077's fourth inherited constraint by naming the one
operation it was never meant to prohibit. It **loosens nothing**: every rule about changing
`RC1` stands exactly as written.

### The problem this exists to settle

Phase 11 validated `intrinsic-ros-v1` chronologically and accepted it (ADR-077), and then
stopped. It persisted **no** `models/production/intrinsic-ros-v1`. Every prediction Phase 11
ever made came out of a fold: `RosHurdleCandidate.fit_predict` deliberately exposes no fitted
object, because fold isolation in this repository is structural rather than remembered
(`ffdraft/ros/estimators.py`). There is therefore nothing on disk for a 2026 build to load,
and no amount of care in Phase 12 conjures one.

Serving 2026 needs a fit. ADR-077 says:

> **Any future change to `RC1`'s outputs invalidates that and needs a fresh sealed season.**

Read literally and without a distinction, that sentence forbids fitting the accepted
architecture on data at all — which would mean the model accepted for Phase 12 can never be
served in Phase 12. That is not what ADR-077 decided; it is what its wording fails to
separate. ADR-077's target is unambiguous in its own text: the four things it enumerates are
*"no fallback, no retrain, no tuning, no feature"* — **design** changes, made in response to a
result, that would invalidate the claim the spent sealed season supports.

### Decision

Two operations exist and they are not the same operation.

| | **production refit** (routine) | **methodology change** (gated) |
|---|---|---|
| architecture | `rc1_ros_hurdle_v1`, byte-identical code path | changed |
| features | `ros_core_v1` (`f5ad9df207795351`) | changed |
| hyperparameters | `RC1_PARAMETERS`, `RC1_NUM_BOOST_ROUND` | changed |
| composition, copula, calibration | unchanged | changed |
| fallback behaviour | none, as ADR-076 decided | added |
| what may differ | **the labelled rows fitted on, and nothing else** | anything |
| evidence required | the frozen configuration hash matches | a fresh sealed season |
| sealed season | unaffected — the accepted claim is about the architecture | invalidated |

A **production refit** is `ros_production_fit_v1`. It is permitted, it is routine, it is the
only way a validated architecture reaches a reader, and it is exactly what
`train_production_model` already does for the preseason model — a path this repository has
run since Phase 4 without anyone calling it a model change.

A **methodology change** is everything else, and ADR-077 governs it unchanged. The rule
against actual model changes is **not weakened**: it is given the boundary it always implied.

### Why a refit does not spend the sealed season

The claim the 2025 holdout supports is a claim about an *architecture* — that
`rc1_ros_hurdle_v1`, fitted on seasons strictly before the season it scores, beats every
declared baseline out of time. That claim is evaluated by fitting the architecture on a
training window and scoring an unseen season, which is what all five development folds and
the one sealed fold did. A production fit is the *same operation with the same code* on the
widest permitted window; it produces a member of the family the holdout measured, not a new
family. Refusing it would make the holdout evidence for nothing, because no fit at all would
be permitted.

The converse is what ADR-077 forbids and what stays forbidden: choosing a different family
(a sparse-history fallback, a new feature, a tuned parameter) *after* looking at a result
means the sealed season selected the design, and no honest out-of-time claim survives that.

### The protocol — `ros_production_fit_v1`

1. **Freeze first, in code.** `ffdraft/ros/frozen.py` holds the accepted architecture as
   constants: model version, candidate version, parameters, boost rounds, composition draws,
   quantile levels, seed, feature set. `RosProductionSpec.configuration_hash()` is a digest
   over all of it, is written into the artifact, and is asserted by a test against the
   candidate class the evaluation actually ran. A refit whose hash differs is not a refit.
2. **Fit on the maximum historically permitted labelled data.** Seasons 2017-2025 inclusive:
   `ROS_TRAIN_START_SEASON` (Phase 3's inherited W2 window) through
   `ROS_PRODUCTION_LAST_TRAINING_SEASON = 2025`.
3. **2025 is included only because its holdout is spent.** It is sealed by
   `ROS_SEALED_SEASONS = "season >= 2025"`, so including it requires the same explicit
   `RosFinalEvalAuthorization` token the final evaluation required, and the artifact records
   that it was given and why. A model that could quietly widen its own window would make the
   seal decorative.
4. **2026 can never be trained on, by construction and by check.** The seal rule already
   covers it (2026 ≥ 2025), and `train_ros_production_model` additionally refuses any
   training season `>= serving_season`. Two independent barriers, because this is the one
   error that cannot be detected from the output.
5. **Persist and version everything.** One gzipped LightGBM text booster per component and
   quantile — never a pickle (`AGENTS.md` section 5) — a SHA-256 per booster, the feature-set
   and feature-schema hashes, the training seasons, the row counts, the dataset content hash
   and manifest, the library versions, the code SHA and the fit timestamp. Inference refuses
   a frame whose feature contract disagrees.
6. **Serving is not fitting.** `ffdraft build-ros` loads this artifact and never trains.
   A refresh that retrained would be a different model every day, which is the failure mode
   the whole freeze exists to prevent.

### When a refit may be run

Only these, and each is recorded in the artifact's `refit_reason`:

- **`initial_production_fit`** — the first fit after promotion. This one.
- **`new_completed_season`** — a season has completed and its labels exist, so the window
  extends by one. Routine, and still not a methodology change.
- **`reproduction`** — a byte-for-byte rebuild to verify the committed artifact.

Anything else is a methodology change and goes through ADR-077, a fresh sealed season and a
new model version.

### Consequences

- `models/production/intrinsic-ros-v1/` exists and is committed, as the preseason model is.
- The model card gains a production-fit section that is explicitly **not** an evaluation
  section: the fit reports rows, seasons and lineage, and points at Phase 11 for every
  performance number. A production fit produces no new performance claim, because it was
  scored on nothing.
- `final_holdout.md` is untouched and stays untouched. The spent season is not re-scored,
  not re-interpreted, and not cited as evidence about the production fit.
- The six inherited limitations in ADR-077 apply unchanged to the fitted artifact: it is the
  same architecture, so it has the same weaknesses, and Phase 12 publishes them.

---

## ADR-079 — The season starting and a rest-of-season board existing are two different facts

**Status:** Accepted (Phase 12, 2026-09-04)

### Context

Three rules, each correct on its own, disagreed about a window every season contains.

`season_state_v1` flips the product mode to In-Season at the season's **first kickoff**, which
is what `docs/RELEASE2_ROADMAP.md` 12.1 asks for in those words. `ros_cutoff_v1` refuses
**week 0**, because a rest-of-season snapshot needs at least one completed week — week 0 is the
preseason model's grain. `ros_source_freshness_v1` refuses a week upstream has not published.

Between the first kickoff and the first *published* week — Thursday night to the following
Tuesday or Wednesday, every year — the mode says In-Season and no board can be built. The
refresh workflow ran `build-ros` on the mode, the freshness gate returned a **critical**, the
build job failed, and a failed build job does not merely skip the in-season board: the deploy
job is downstream of it, so the **draft** board stopped refreshing too. The site would have
frozen for the first week of every season, and the cause would have looked like an outage.

The same disagreement recurs at the far end. Once the last scored week is played,
`available_through_week` is that week and `RosCutoff` refuses it — correctly, no remaining
horizon exists — by raising `ValueError`. Nothing caught it, so every refresh from the end of
the fantasy season onwards would have crashed rather than done nothing.

Neither window is a source failure. Both are lifecycle states, and both are deterministic from
a schedule published in May.

### Decision

**Separate "has the season started" from "can a rest-of-season board exist".**

1. **`season_state_v1` is unchanged.** The state still becomes `regular_season` at the first
   kickoff, and `SEASON_COMPLETE` still maps to `ProductMode.IN_SEASON`. The roadmap's literal
   semantics are preserved; what changes is that nothing downstream treats the mode as a claim
   that a board exists.
2. **`latest_snapshot_week` is the gate.** It is already `None` in both windows — before the
   first completed week, and once the horizon is spent — and it is now what the refresh
   workflow's `if:` reads, so `build-ros` is not attempted where it cannot succeed. The
   schedule alone decides this; no upstream read is needed.
3. **The freshness gate distinguishes a cadence from an outage.** Nothing buildable with at
   most one week played is `ros.awaiting_first_week`, a **warning**: the refresh stays green,
   the draft build deploys, and no board is published. Nothing buildable with **two or more**
   weeks played is still `ros.no_complete_week`, **critical** — that is not a publication lag.
4. **Season completion is a warning, not an exception.** `_resolve_week` bounds the cutoff by
   the remaining horizon and emits `ros.season_complete` rather than reaching a constructor
   that raises. The last published board is the final one. A structurally zero "week 17" board
   published to keep a tab populated would be a fiction, and is not produced.
5. **An explicitly requested week is exempt from both lifecycle refusals.** Every historical
   season is `season_complete`, so a refusal that also applied to `--through-week` would make
   replaying a finished season impossible — and replay is the only way to exercise this path
   before a season of one's own has started.
6. **The season state travels on `build_metadata.json`.** The draft build is the one thing
   that runs in every state, so its metadata is the only place the frontend can learn the
   season has started while no in-season bundle exists. The block carries the state, the
   product mode, the completed week, the latest snapshot week, a boolean
   `ros_board_expected`, and the build's own sentence about why.

### Why a block and not a season-state artifact

A separate `season_state.json` was considered and rejected. It would say the same thing in a
new file with a new schema, a new fetch, a new 404 path and a new way for two published files
to disagree about one season. `build_metadata.json` is already written by every build, already
fetched on every page load, already versioned, and already the place a reader looks for "what
is this build". The block is optional in the schema, so a build older than this ADR simply has
none and the page says only what it can prove.

### Consequences

- The product has **three** situations, not two: Draft, In-Season, and *season under way with
  no board yet*. The indicator names the third rather than calling it Draft mode, and a notice
  above the draft board states the reason in the build's own words.
- A refresh in either lifecycle window is **green** and publishes the draft bundle alone. The
  packaging gate keys on what the build actually produced rather than on the season, because
  in those windows the draft bundle alone is the correct package.
- Four states — before kickoff, after kickoff with no completed week, week 1 played but not
  published, week 1 available — plus the two at the far end have a test each, asserting the
  resolved cutoff, the gate verdict, and the value the workflow reads.
- `ros_cutoff_v1` is untouched. It still refuses week 0; this ADR routes around it rather than
  weakening it, and a test asserts the refusal directly.

---

## ADR-080 — FantasyPros stays `benchmark_only`, and that no longer blocks Release 2

**Status:** Accepted (Phase 12, 2026-09-04). Supersedes the FantasyPros half of Release 2's
definition-of-done clause 1; does not supersede ADR-064, which records the measurement.

### Context

Release 2's definition of done, clause 1, requires "independent FFC, MFL, and FantasyPros ADP
comparisons plus FantasyPros ECR without conflating the signal types". Phase 10 built the
adapter, the budget, the identity linkage and the capture, then measured what the provisioned
key actually returns (ADR-064):

- every response carries `public_api_limited: true` and `tier: "free"`;
- ten rows per call, and **40 distinct players** across QB/RB/WR/TE, against a documented
  `count` of 407 receivers and 225 tight ends;
- `limit`, `offset`, `start`, `page`, `max_results` and `ranks` all return the same ten rows;
- there is **no ADP at all**: `/json/nfl/{season}/adp` returns `403 Missing Authentication
  Token`, and `type=adp` returns the ECR row shape with no ADP field.

A 40-player consensus published as though it were a market comparison would be worse than
publishing none: it would look like a source and behave like a sample.

The owner has accepted this as an upstream entitlement limitation and does not want Release 2
held open waiting for a different vendor contract.

### Decision

1. **The original criterion is recorded as historically unmet.** It is not restated, softened,
   or marked passed. Clause 1 of the Release 2 definition of done was not met for FantasyPros.
2. **FantasyPros remains `benchmark_only`** under the current entitlement. It feeds no public
   comparison, no model, and no surface decision.
3. **Release 2's production source scope is stated positively**: FFC and MyFantasyLeague for
   draft ADP, published as independent comparisons and never conflated; Sleeper add/drop for
   in-season opportunity. That is the scope the release ships and the scope its documentation
   describes.
4. **The revisit condition is unchanged and stays tested on every capture**: a key whose
   responses omit `public_api_limited` (or set it false) and whose `count` equals the rows
   delivered. Meeting it flips `MarketSourceSpec.publishable` — one line.
5. **This entitlement no longer blocks `v2.0.0`.** A blocker is something the project can act
   on; a vendor tier is not, and holding a finished release against one converts a documented
   limitation into an indefinite hold.

### Consequences

- `docs/releases/v2.0.0.md` records clause 1 as **unmet, superseded by this ADR**, with the
  measurement and the revisit condition, and no longer lists it under release blockers.
- The one operational item that *is* still open — no live in-season week has been built,
  because the season starts on the 10th — stays open, because it is an observation the project
  will make rather than an entitlement it cannot obtain.
- If the entitlement changes, publishing FantasyPros is a Phase-13 source change under the
  ordinary rules, not a re-opening of Release 2.

---

## ADR-081 — Every retained market gets a history; a null slope is a measurement, not a gap

**Date:** 2026-09-07 (post-Release-2 correction)

**Status:** **Accepted and implemented.** No contract version changes; `market_trend_series.json`
gains records for a second source and loses none.

**Context.** A reader opened a player card, with the board's default market (FFC) selected, and
saw a current FFC ADP of 24.5 beside the sentence

> Not enough retained FFC Recent history to draw a trend yet — 0 snapshots so far.

Seven FFC snapshots were in the store at that moment, spanning 3 to 6 September. The card was
describing our own plumbing and phrasing it as a fact about the market. In the cross-market
view there was no chart at all.

Four independent defects produced it, and each had a passing test:

1. **`pipeline/market.py` loaded a trailing window for MyFantasyLeague only.** Every other
   source went through `load_extra_quotes`, which read `read_latest` and nothing else. A second
   market therefore arrived with a price and no past.
2. **`market/extra.py` built `SourceQuote`s with no `market_trend`** — the field existed and was
   never populated — so FFC's slope was `None` because nothing had computed one, which is a
   different fact from "the frozen rule declines to fit this window".
3. **`market_trend_series` was generated for the primary source alone**, so no FFC record was
   ever written, so the chart had nothing to draw whatever the store held.
4. **The frontend filled the resulting nulls in from MyFantasyLeague.** `selected?.market_trend
   ?? arbitrage.market_trend` on the card, `record.market_trend` outright in the Trend column,
   the flat V1 `rank_gap` in the identity rail. The flat fields are MyFantasyLeague's, so with
   FFC selected the reader was shown one market's price beside another market's movement.

And one structural impossibility: the App passed the *market selection* into an index keyed by
source id, so `"cross"` was looked up in a map that could never contain it.

**Decision.**

**The retained-history path is extracted, not duplicated.** `ffdraft.market.history` holds one
`RetainedHistory` per source — the trailing window, the cohort map, the trends — and both
`build_current_market` and `load_extra_quotes` build one. `phase5_trend_v1` is untouched:
`compute_trends` and `observations_from_snapshots` are the same functions Phase 5 froze, and
what changed is that a second source can reach them. Each source's window is anchored on **its
own** newest capture, because two markets are captured by two jobs hours apart and anchoring
one on the other's clock would ask the rule about days a source has no evidence for.

**A source's cohorts are read from its own rows.** A normalized row carries the scoring preset
it describes and the cohort it came from, which is the mapping. FFC resolves to one cohort per
scoring preset; MyFantasyLeague's filter-defined cohorts carry no scoring tag and keep the
ADR-039 selection rule. A scoring preset served by two cohorts is **refused and reported**, not
resolved — choosing would mix populations, which is the one thing the trend rule forbids
outright. Because FFC accepts `teams` and ignores it (ADR-056), its map repeats one cohort
across every league size; the repetition *is* the claim that the source does not observe league
size, and the published `league_size` stays null so nothing can read it as an observation.

**The frozen statistical gate is not weakened to make a chart appear.** FFC on the day this was
found had four observation days over 2.7 days of span: enough observation days,
not enough elapsed span. Its slope stays `null` and its card says `trend collecting`. What
changed is that the *chart* no longer waits for the slope.

**Drawing a history and estimating a trend are different questions.** The component refused to
draw below three points, on the reasoning that two points imply a trend the store cannot
support. That is right about the *slope* and wrong about the *history*: a retained ADP on a
Thursday is a fact whether or not a Saturday follows it. One point draws a point, two draw a
line, and the scalar stays `collecting` until `phase5_trend_v1` qualifies it, independently.

**The chart's x axis is time, and its point reduction is stated.** Captures are not evenly
spaced — the store holds three on one afternoon and none the next morning — so an index axis
would draw a cadence that never happened. Several captures on one UTC calendar day reduce to
**the latest observation of that day**: the reading that was current when the day ended, which
also makes the newest point of the series the price the board publishes. This is a
*presentation* reduction and is allowed to differ from the slope's input, which is still every
retained observation, unreduced.

**One resolution serves the whole card.** `marketView(record, selection)` returns the selected
source's comparison or nothing. The only fallback that remains is the one that was ever meant:
a Release 1 record has no `markets` array at all, and its flat fields are that single source's
own numbers, lifted into the same shape once. A selected market that did not price a player
says so — and still lists the markets that did, because "FFC does not price him" and "nothing
prices him" are different sentences.

**Cross-market mode overlays the real series and invents none.** There is no `cross` source
record, no synthetic averaged history, and no single scalar labelled "cross-market trend": the
per-source slopes are in the chart's legend, which is where a comparison belongs. A record
naming `cross` is refused by the artifact validator and ignored by the chart.

**A series belongs to the market that priced him.** The window is seven days wide and a
market's current price list is not: a player FFC quoted on Tuesday and dropped by Friday still
has observations inside it. Charting them would put a history under a card that says "no
current FFC ADP". The scope is now the published arbitrage row **per source**, which also keeps
ADR-063's market-surfaced exception charted.

**The agreement ADR-066 claimed is now checked.** ADR-066 said the series carries "the same
scalar the arbitrage row carries ... asserted equal by the cross-artifact validator". It was
not — nothing compared them, and the fixture published `market_trend: null` on the board beside
a fabricated slope in the series for two phases. `cross_artifact.trend_series_agreement` now
compares, per source: the slope, the newest point against that market's published ADP, and that
every series belongs to a market on the board. It found a real defect on its first real build
(the dropped-player case above, 20 rows).

**Why the tests missed all of it.** No fixture in this repository had ever carried a *second*
market's retained history. The Python fixture generated `market_trend_series` for the primary
source only; the TypeScript fixtures carried no series artifact at all, so the chart was
rendered by a component test and by nothing else. Both fixtures now carry two markets with
genuinely different cadences — MyFantasyLeague qualifying, FFC chartable-but-unqualified — and
`web/tests/e2e/markethistory.spec.ts` runs the whole path from published bytes to a rendered
card. This is the second time the same lesson has been recorded here (ADR-067); the difference
is that the fixture now expresses the *state*, not only the shape.

**Consequences.** `market_trend_series.json` roughly doubles: 2,232 records became 3,957 on the
2026-09-06 store. The fixture board's MyFantasyLeague rows now carry a measured trend where
they carried `null`, because the fixture's synthetic window qualifies and the artifacts have to
agree. The arbitrage table's Trend column follows the market selector, so the default FFC board
reads an em dash where it used to read MyFantasyLeague's number — that is the correction, not a
regression. `verify-real-build.mjs` opens a card per published market and compares the drawn
marks with the artifact's own bytes.

---

## ADR-082 — A status badge is not an injury report, and a check that lists today's roster codes is not a contract

**Date:** 2026-09-12 (in-season refresh failure)

**Status:** **Accepted and implemented.** No contract version changes; no artifact, schema or
rendered value moves. A verification check and the fixture it runs against do.

**Context.** The 2026-09-12 daily refresh failed its `verify:board` gate on one line:

```
"CJ Daniels: badge \"INA\" but the artifact reports no injury status"
```

The board was right. `player_status.json` carried `roster_status: "INA"` — nflverse's code for
a player declared inactive — with no Sleeper injury designation, and `statusBadge` marked him,
which is what ADR-043 asks for: a badge renders whenever the artifact carries *something*, and
`ACT`/`A01`/`DEV` is the only thing that says nothing. The check was what failed. It read:

```js
if (designation === null && row.badge !== null && !/^(RES|CUT|E14|INJU|NOTE)/.test(row.badge))
```

— an enumeration of the roster codes an August roster feed happens to publish. September
publishes `INA` every week a player is inactive, so the first in-season refresh failed a
correct board on a code nobody had written down.

**This is the third instance of one species in this file.** ADR-052's four-day note recorded the
first two — the Trend column asserted an em dash because the store was too young to have a
slope, and the tier row's name assertion stripped `IR · Knee` out of the cell because that was
the shape of the day's injury report — and stated the rule: **a verification check must assert
the contract, not the day's data.** Both earlier instances were fixed by re-deriving the
expectation from the artifact. This one was not caught by that audit because it does not read
like a pinned value; it reads like a list of valid states, which is the same mistake wearing a
different coat.

**Decision.** `verify-real-build.mjs` derives the badge condition from the bytes:

1. A badge appears **iff** the record carries an annotation — a non-empty `injury_status`,
   `injury_body_part`, `injury_notes` or `practice_participation`, a `sleeper_status` other
   than `Active`, or a `roster_status` outside `ACT`/`A01`/`DEV`. Both directions are checked;
   the old form only caught a badge with no injury behind it, so a *missing* badge on an
   annotated player was invisible unless the annotation happened to be an injury.
2. The badge's second half is compared literally with `injury_body_part`, which the artifact
   publishes verbatim and the badge quotes verbatim.
3. The abbreviation table is deliberately **not** reproduced in the checker. `Questionable`
   renders `Q` and `Injured Reserve` renders `IR` because `web/src/data/model.ts` says so;
   transcribing that into the verifier would make the check a copy of the code it checks, and
   a second place to forget. What is compared is what the artifact states in its own words.

Rows are joined to the artifact by display name, and a name the block publishes twice is now
skipped rather than guessed at — a wrong join would report a badge failure about a player the
row is not.

**Why no local gate caught it.** No fixture in this repository had ever carried a non-injury
roster code. The one reserve player, Jaylin Lane, is on IR and reports `injury_status: "IR"`,
so every badge on every fixture board had an injury designation behind it and the enumeration
was never exercised. This is the same finding as ADR-081's — *the fixture expressed the shape
and not the state* — on a different artifact. `Omarion Vance` is now `roster_status: "INA"`
with every injury field null, so `npm run e2e` and both CI `verify:board` runs meet the
in-season case before a production refresh does. On the pre-fix checker that fixture reproduces
the production failure exactly.

**Two things this deliberately does not change.**

- `FLAGGED_STATUSES` in `src/ffdraft/pipeline/current.py` names `RES`, `CUT` and `E14`, so an
  inactive player gets a badge and no `current_status_*` quality flag. Widening it changes a
  published artifact's `quality_flags`, which is a contract change and needs its own decision
  rather than riding a CI fix.
- The badge for a roster code shows the raw code — `INA`, like `RES` and `E14` before it — and
  its accessible text reads "Current status: INA". That is pre-existing and legible only to
  someone who knows the vocabulary. Worth fixing; not worth fixing silently inside a gate
  repair.

**Consequences.** The gate is strictly stronger than the one it replaces: it now fails a board
that omits a badge the artifact justifies, and one that reports a body part the artifact does
not. It cannot fail again because upstream published a status code that nobody had listed.

## ADR-083 — nflverse is the one critical source that retried nothing, and the season is what made that matter

**Date:** 2026-09-15 (first post-week-1 refresh failure)

**Status:** **Accepted and implemented.** No contract version changes; no artifact, schema,
feature or rendered value moves. One HTTP budget and the call sites that carry it do.

**Context.** The 2026-09-15 daily refresh — `daily-refresh` run 43, the first scheduled run
after week 1 completed — failed 24 seconds into the capture job:

```
ConnectionError: Failed to download
https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet:
500 Server Error: Internal Server Error
```

`capture` failed, so `build` and `deploy` never ran, and the site stayed on the previous
day's board. That much is the job graph working as ADR-050 designed it. What is not
working as designed is the reason the gate fired: the same URL served its 3,386,429 bytes
correctly on the first attempt an hour later. Nothing was missing. The request was unlucky,
and one unlucky request is currently enough to cost a day's publish.

**Why it became likely now.** An nflverse-data release asset is replaced by
delete-then-upload, and how often that happens is a function of the calendar. Measured on
the afternoon of the failure:

| asset | last modified |
|---|---|
| `players/players.parquet` | 2026-09-15 13:05 UTC |
| `depth_charts/depth_charts_2026.parquet` | 2026-09-15 12:39 UTC |
| `rosters/roster_2026.parquet` | 2026-09-15 12:40 UTC |
| `combine/combine.parquet` | 2026-03-12 17:51 UTC |

The three files a current capture reads were each rewritten within the hour; the static one
had not moved since March. Week 1 finishing is what starts that churn, and the daily capture
at 11:2x UTC now runs inside it. So the user's instinct that this failure had something to
do with the season starting is right, though not in the place it looked: the season-state
resolution was correct on this run (`product_mode: in_season`, `completed_week: 1`,
`latest_snapshot_week: 1`), and the mode logic is not what broke. The season changed the
*rate of upstream writes*, and the capture path had no tolerance for any of them.

**The gap was specific, not general.** `docs/ARCHITECTURE.md` section 5 scopes an adapter
to "fetch, retry/timeout, raw schema normalization", and every other vendor honours the
retry half: `_mfl_get`, the Fantasy Football Calculator adapter and the FantasyPros adapter
each own a bounded, backing-off request loop that reads `SourceConfig.max_retries`.
nflverse was the exception, because it is reached through `nflreadpy` rather than through
`requests` directly, and `nflreadpy` downloads on a plain `requests.Session` with no retry
configured at all. The single source `config/source-registry.yaml` marks
`criticality: critical` was the only one where the first answer was the last answer.

**Decision.** `ffdraft.sources.nflverse_http` owns the transport policy and mounts it on the
session `nflreadpy` downloads through: **4 retries** after the first attempt, urllib3 backoff
of 0s / 2s / 4s / 8s, on **429, 500, 502, 503 and 504**. Every nflverse call in `ffdraft`
now asks for its loaders through `nflverse_loaders()` rather than importing `nflreadpy`, so
the budget is a property of the call site by construction rather than something the next
call site has to remember; a test asserts no module under `src/ffdraft` imports `nflreadpy`
directly.

**404 is deliberately not retried.** nflverse publishes per-season files, so asking for a
season that has not been released yet is a legitimate 404 that several loaders produce, and
a 404 on a file that used to exist is a source-contract change — exactly the thing
`AGENTS.md` section 5 wants loud and immediate. Retrying either trades a clear answer for a
slow one. Only the server-side statuses, which are transient by definition, are worth
waiting on.

**What this is not.** It is not a fallback and it is not a cache. No mirror is substituted,
no stale copy is served, and a download that still fails after the budget is spent still
fails the capture job and still stops the deploy. A refresh can only ever publish bytes a
first-try success would have published too; what changes is how many times the same URL is
asked before the day is written off. The budget is bounded at roughly 14 seconds per
download against a 30-minute job timeout.

**Two things this deliberately does not change.**

- **The capture job still has no nflverse cache.** The build job caches nflverse downloads
  per UTC day (`docs/OPERATIONS.md` section 4); the capture job downloads fresh every run.
  Extending that cache to capture would cut vendor calls, but at the cost of building the
  identity spine from an earlier-in-the-day roster, and section 4's justification was
  written for a build rather than for a capture. That is a freshness decision and deserves
  its own, not a ride on an availability fix.
- **`scripts/source_probe.py` keeps importing `nflreadpy` directly.** A Phase-0 probe exists
  to measure raw upstream behaviour; a probe that quietly retried would report an
  availability the production path does not have.

**Consequences.** A transient nflverse 5xx now costs seconds instead of a day's publish. A
persistent one still fails, with the retry count in the error. The retry budget is stated in
`config/source-registry.yaml` under the nflreadpy entry as well as in code, and
`tests/unit/test_nflverse_retry.py` fails if the two ever disagree.

**What this does not fix, and is the next thing to watch.** Run 43 failed in `capture`,
which meant `build` never ran — and 2026-09-15 would have been the **first** day the
rest-of-season board was built in production. `latest_snapshot_week` was empty on every
previous run, so the `Build the rest-of-season board` step had been skipped every day since
the season opened (run 42, 2026-09-14: skipped). ADR-079's two windows were doing their job;
the window has now closed and the step is live. It is covered by fixture tests and by
`test_ros_production.py`, but it has never run against the real store, so the next refresh
is its first production exercise rather than a repeat of a known-good one.

## ADR-084 — `auto` is not a synonym for the Tier Board, and the board the site opens was the one board nothing checked

**Date:** 2026-09-15 (the first in-season production build)

**Status:** **Accepted and implemented.** No contract version changes; no artifact, schema,
model or rendered value moves. Four verification scripts and the CI matrix they run under do.

**Context.** With ADR-083's retry in place the capture job succeeded, the rest-of-season board
built for the first time in production, and `daily-refresh` run 44 then failed its
`verify:board` gate with 82 failures on a board that was correct. The first one says all of it:

```
tier table: no column headed Rank, Exp VORP, Median VORP, P25–P75 VORP, Exp FP
  — saw ROS Rank | Player | Pos | ROS PosRk | Team | ROS Tier | ROS Exp VORP | ROS P25–P75
    | Rem FP | Rem G | Uncertainty | Δ vs preseason | Weeks since last game | Current status
```

The other 81 follow from it: `tierBoardRowsRendered: 0` and 25 "no mark for …" because the ROS
view draws no tier chart, and `badgesRendered: 0` with 57 "artifact reports … but no badge is
rendered" because the ROS table carries a `Current status` **column** where the draft board
carries a badge beside the name.

**Root cause, in one line: the verifier asked for no view and assumed it would get the Tier
Board.** `web/src/data/state.ts` defines `view` with a default of `auto`, and `resolveView`
resolves `auto` to `tiers` before kickoff and to `ros` after it — deliberately, so that one
shared link stays correct in both modes. `verify-real-build.mjs` navigated to `?tiers=…` with
no `view`, which meant "the Tier Board" for exactly as long as the season had not started. On
2026-09-15 it stopped meaning that, and every check in the file ran against the rest-of-season
board by accident.

**This is the fourth instance of one species in this file**, and the first three are already
recorded against this same script: ADR-052's two (a Trend cell asserted as an em dash because
the store was too young to have a slope; a name assertion that stripped `IR · Knee` because
that was the shape of the day's injury report), and ADR-082's (a badge checked against a list
of the roster codes an August feed publishes). The rule they all state is the same one:
**a verification check must assert the contract, not the day's data.** An omitted parameter is
a way of asserting the day's data without appearing to assert anything — and it is worse than
the other three, because while the two boards resolved to the same thing the check *passed*,
for the wrong reason.

**Why no local gate caught it.** `globalSetup` has built `web/dist-in-season` since Phase 12,
and `npm run e2e` exercises it through `inseason.spec.ts`. But `verify:board` — the script that
broke — ran in CI against exactly two builds, the root fixture and the matured-market one, and
both are draft-mode builds. The fixture that reproduces this failure was sitting on disk in
every CI run for weeks, and nothing pointed the gate at it. The ADR-082 finding was *the fixture
expressed the shape and not the state*; this one is one turn further out: **the fixture
expressed the state and no gate was aimed at it.**

**Decision, in three parts.**

1. **Every check that means the draft board says so.** `verify-real-build.mjs`,
   `verify-presets.mjs`, `verify-csv.mjs` and `verify-live.mjs` now name `view=tiers` where
   they previously relied on the default. `verify-presets.mjs` was failing all nine preset
   blocks in-season with "the tier board rendered no rows"; `verify-csv.mjs` and
   `verify-live.mjs` carried the same assumption and would have failed the next live smoke.

2. **What `auto` resolves to is now a check rather than an assumption.** The verifier reads
   whether the build published `ros_tiers.json`, opens a bare link, and asserts the board that
   comes back is the one that bundle implies — the ROS board when there is one, the draft board
   when there is not. That covers ADR-079's two windows too, where the season has started and
   no rest-of-season board exists.

3. **The ROS board is verified against its own bytes.** This is the larger gap the failure
   exposed, and fixing only (1) would have left it: from September onward the rest-of-season
   board is what a visitor sees, and it was the one published board no pre-deploy gate compared
   against the artifact it was built from. A green refresh could have shipped it wrong. The
   verifier now checks its rank, name, expected VORP, P25–P75, remaining points, remaining games,
   uncertainty and `Current status` against `ros_tiers.json`, row by row.

**Two ROS columns are deliberately not compared.** `Δ vs preseason` and `Weeks since last game`
render chosen sentences — "Played latest week", "No appearances". Restating that table in the
verifier would make the check a transcription of the code it checks and a second place to
forget it, which is the reason ADR-082 left the badge abbreviations in `web/src/data/model.ts`.
Unlike ADR-082's abbreviations, though, nothing else covers these two yet: `rankChangeLabel`
and `longAbsenceLabel` are exported from `web/src/data/ros.ts` with no unit test and the
weeks-since cell is inline in `RosTable`. That gap is recorded in `TASKS.md` rather than closed
here, because the fix is a component test and not a second copy of the label table.

**The gate is now aimed at every lifecycle state.** CI runs `verify:board` against five builds
rather than two: the root fixture, the matured-market build, the in-season build, and both
ADR-079 windows. All five pass, and the in-season one reproduces the production failure exactly
on the pre-fix script — 22 failures, opening with the same column line.

**Verified.** Three negative controls, because a check that only passes proves nothing: a
`ros_expected_vorp` moved by 11.0 and a `current_status` invented in the artifact are both
reported against the page (`ROS row 1 …: rendered 63.0, artifact 74.0`); an in-season bundle
served to a draft-mode build is reported as a default-view failure naming both boards; and the
pre-fix script on the in-season build reproduces the production failure. `npm run e2e`,
`npm run lint`, `npm run typecheck`, `npm run test -- --run` and `uv run pytest` all pass.

**Left open on purpose.** `verify-presets.mjs` treats any console error as noise, and a
pre-kickoff build legitimately 404s `ros_build_metadata.json` — the optional in-season bundle it
is correct not to publish — so that script reports noise failures against a correct draft build.
It is pre-existing, orthogonal to the view-resolution bug, and does not run in `ci.yml`; it
belongs in its own change rather than riding this one.

**Consequences.** The rendered-versus-artifact gate now covers both product modes and both
lifecycle windows, and it fails on the transition rather than through it. What made this bug
invisible — a check that agreed because two different things happened to be the same thing —
cannot recur in these four scripts, because none of them asks for a board without naming it.

## ADR-085 — The in-season product gets the design system the draft product already had

**Date:** 2026-09-15 (post-Release-2 presentation pass)

**Status:** accepted.

**Context.** The first live in-season week published on 2026-09-15 (ADR-083, ADR-084), and the
owner reviewed the deployed site rather than the test suite. Four defects, and the useful thing
about all four is that **every gate passed on every one of them**: `verify:board` compared the
rest-of-season table against its bytes and agreed, the Playwright suite was green, axe found
nothing, and the artifacts validated. They were defects of presentation, and a suite that
checks whether numbers are *right* cannot see whether a board is *there*.

| what the owner saw | what was actually built |
|---|---|
| "NO TIER CHART RENDERING" | the rest-of-season view published tiers, quantiles and a tier label and drew none of it — a legend and a facts strip sat where the board should be |
| "NO OPPORTUNITY CHART RENDERING" / "DATA IS TOO BLAND" | the Opportunity Board was a hand-rolled `<table>` with no chart, no position chips, no sort and no glyphs, beside a draft board that had all four |
| "why did this column get created?" | `Current status` had a column of its own on both in-season boards, reading `ACT` on essentially every row |
| "DRAFT MARKET IS USELESS WHEN WE ARE IN IN-SEASON MODE" | the player card led with an FFC draft ADP and an arbitrage score in week 1 |
| "too much text" | four paragraphs of disclosure and a three-sentence section note above the board, on the first screen |

**Decision — the rest-of-season board is the Tier Board, not a second chart.** `TierBoard` now
takes a neutral view model (`charts/boardModel.ts`): a rank, five quantiles, a position, some
badges, a label, and a `BoardAxis` carrying every string it prints. Both views map their own
records into it. One component, one stylesheet, one set of responsive rules, and the 2a/2b
breakpoint pair works on the in-season board because it is literally the same DOM.

The mapping is deliberately lossy. A `BoardMark` carries no field names, so the component
cannot tell a preseason VORP from a remaining one — which is the point. ADR-071 forbids the
two quantities meeting; a chart that knew which it was drawing would be one coercion away
from letting them.

**Decision — the Opportunity Board draws two tracks and never one.** A rest-of-season value in
points and a count of roster transactions over a window have no common unit, and `AGENTS.md`
already forbids a blended score. The chart holds to that literally: two tracks, each with its
own zero line, its own tick strip and its own heading, separated by a border rather than a
gap. The transaction track is diverging and symmetric about zero, bounded by the 85th
percentile of the non-zero counts on the rows shown — `movesBound`, the same rule and the same
reason as the Draft Rail's `railBound`, because one surfaced waiver pickup with 2,400 adds
would otherwise draw every other row as a hairline. A count past the bound keeps its bar at
the axis edge and takes a chevron; its real number is printed beside the track either way.

This is not a constraint worked around. The useful in-season question — *is the wire moving on
someone the model still rates?* — **is** a comparison of two separate readings, and averaging
them would destroy the only thing the picture is for.

**Decision — current status is a mark on the name, never a column.** The same treatment, in the
same place, that the draft board has carried since Phase 6. It renders only when the artifact's
code is noteworthy; `ACT`, `A01` and `DEV` render nothing, because "active" is the ordinary
case and the absence of a designation is not a report (ADR-043). The visible text is the
artifact's own code, verbatim. A short expansion table names the eight codes whose meaning is
unambiguous and anything else reads as itself — ADR-082's lesson runs in both directions, and a
renderer that guessed at an expansion would put a designation in front of a reader that the
artifact never made.

The board's own `current_status` is the source, not `player_status.json`. One board, one
account of a player, and the CSV export carries the identical string.

**Decision — the card belongs to the board, not to the calendar.** From an in-season board the
`Draft market` section is replaced by `In-season usage`: production to date, workload shares
and roster moves over the declared window, in two blocks separated for the same reason the
board's tracks are. The identity rail leads with the rest-of-season rank and carries the change
since preseason and the net adds where a market verdict and an arbitrage score used to be.

It keys off the **view**, not the mode. The draft board stays reachable all season (roadmap
12.1), and a reader who asked for it asked for its card too — a row on the Tier Board is a
draft-model row and its market comparison is the draft market, whatever month it is. Keying it
off the mode gave the draft board an in-season card in November, which `verify:board` caught on
the in-season build. It also makes ADR-079's two lifecycle windows correct with no second
condition.

**Decision — state the disclosure, do not spend the fold on it.** ADR-076 requires the
in-season board to say that the model uses no injury or practice-report information, and to
publish the measured ordering weakness. That sentence is now the always-visible summary of a
`details`; the ordering weakness, the tier-boundary statement and the flag's definition open
from it. Nothing is removed and nothing is hidden from the accessibility tree — the axe scan
runs against the board both closed and open, because a contract nobody can reach is not met.
`Data` carries all of it again in full, which is where methodology lives (ADR-058).

**What did not change.** No model, artifact, schema, feature, simulation, tier, rank, count or
CSV column. `verify:board` runs against all five builds and reports zero disagreements, which
is the check that fails if one had.

**Consequences.**

- `TierBoard`'s props changed, so any future board wanting the 2a/2b treatment implements an
  adapter rather than a chart. That is the intended cost.
- `state.board` and `state.tiers` now govern whichever board is on screen. Only one is ever
  rendered, so the URL surface stays the size it was.
- The verifier's rest-of-season status check is a **contract** — the badge exists exactly when
  the code is noteworthy, and its text is that code — rather than a cell comparison against a
  list of codes. Both directions have a negative control.
- Four axe scans and a roving-focus check were added for surfaces that had never been scanned:
  neither in-season board nor the in-season card had ever been through one, because the ROS
  board did not exist and the opportunity board was a bare table.

## ADR-086 — A number with no scale is not a reading, and the card's own artifact can give it one

**Date:** 2026-09-15 (the card-meters pass, immediately after ADR-085)

**Status:** accepted.

**Context.** ADR-085 assembled the in-season player card and every number in it is correct.
The owner then looked at the same card and asked a question no gate can:

> `ROS Uncertainty` just shows a number, e.g. `82.8`. A viewer has no idea what that means. Is
> that really uncertain? A little uncertain? Are we confident?

He is right, and the example generalises to both in-season sections. `82.1` is the artifact's
own `ros_uncertainty`; `verify:board` compares it against the published bytes and agrees; axe
has nothing to say about it; the artifact validates. It is also, on its own, unreadable — and
so were `Change in intrinsic view +185`, `Points per game 11.9`, `Snap share 91%` and
`Remaining games 12.5`. Two sections of correct digits with a scale on none of them.

This is one turn past ADR-085's finding. That ADR recorded that a suite which checks whether
numbers are *right* cannot see whether a board is *there*. This one records the step after:
a board can be there, and every number on it can be right, and a reader can still not be able
to read it.

**Decision — three micro-charts, and not one score.** `charts/CardMeters.tsx` adds `RankShift`,
`PaceRail` and `CohortStrip` to the card. Each places a published value; none invents one.

| | what it draws | the rule that makes it honest |
|---|---|---|
| `RankShift` | the preseason and rest-of-season ranks as two anchors on the board's own rank axis | two shapes, two model names, the artifact's own `fair_rank_change` — never one rank that moved |
| `PaceRail` | points per appearance scored, against points per appearance the model projects | one unit on both bars, which is the only reason they may share an axis |
| `CohortStrip` | where a value sits among the same position's rows on the same board | the denominator printed on every reading |

**Decision — a cohort reading is a description of the artifact, not a new quantity.**
`AGENTS.md` section 11 requires every value shown in the UI to originate from a versioned
public artifact contract. A rank among the published rows of one artifact is arithmetic *over*
those rows rather than a quantity beside them, which is what licenses it. `data/cohort.ts`
(`cohort_context_v1`) holds the statistics and `data/ros.ts` assembles them, so the card stays
a renderer and the population cannot quietly become the reader's current filter — a rank that
moved when someone changed the position control would be a rank about the control.

Four sub-rules, each of which is a thing that would otherwise go quietly wrong:

1. **The denominator is always carried.** `docs/UX_SPEC.md` section 7.1A already requires this
   of a bar. A rank is worse than a bar without one, because it looks exact.
2. **A rank, never a percentile.** "Ninth of ninety-six" is a fact about a finite list;
   "ninety-first percentile" implies a distribution a board of published rows is not, and would
   need a sample-size caveat this product would then have to keep repeating.
3. **Ties share the better rank**, so two identical values cannot be ordered by an accident of
   the sort.
4. **A cohort too small to be one says nothing**, rather than "1st of 2"; the quartile band is
   withheld separately and later, at eight rows, because a quartile over four numbers is two
   values pretending to be a distribution.

**Decision — the pace comparison is legitimate and the blend next door is not.** `ros_label_v1`
decomposes the rest-of-season target into exactly three parts: remaining games, remaining points
**per appearance**, and their product. So points per appearance is a quantity the model is built
on, and `points_per_game_to_date` on the same record is the identical quantity measured before
the cutoff. Two numbers, one unit, one either side of the cutoff — which is precisely the
condition the Opportunity Board fails and why that board draws two tracks and no blend
(`AGENTS.md` section 10, ADR-085). The card states what it divided: *remaining points divided by
remaining games*, never "expected points per game", because the ratio of two published
expectations is not the expectation of the ratio and the artifact publishes no per-appearance
estimate.

**What this deliberately does not build: a single "luck" or "hot" score.** The owner asked
whether there could be a lucky meter. There could be a *number* — and it would be manufactured.
The honest version of that question is answered by putting the readings side by side and letting
the reader make the call: the rate against the model's rate, the production against the
position, and the workload that produced it. Averaging a rank move, a pace gap and an add count
into one figure would be the blended score `AGENTS.md` forbids, over three quantities with no
shared unit, and it would be the most confident-looking number on the page.

**The genuine luck metric exists, in the feature table and not in the artifact.**
`points_over_expected_per_game_to_date` — "points per game minus expected points per game;
separates a player who is scoring on volume from one who is scoring on conversion" — is already
computed in `ros_core_v1` (`docs/ROS_FEATURE_DICTIONARY.md`). Publishing it is **not** a
frontend change and not a one-line one:

- it is a data-contract change (`schemas/ros_tiers.schema.json`, `docs/DATA_CONTRACTS.md`, the
  validator, the CSV, the TypeScript contract, the golden artifacts) under `AGENTS.md` §18;
- and it carries a licensing question, which is why it is an ADR and not a task.
  ffopportunity's expected-points data is **CC-BY-SA 4.0** (`docs/SECURITY_LICENSE.md` §8).
  Using it as a model input and publishing a prediction is one thing; publishing a derived
  per-player expected-points figure on a public JSON artifact is a good deal closer to
  redistributing the licensed data, and the share-alike obligation would then bind what this
  site publishes — the same question backlog item 8 records against FTN and has never resolved.

Recorded as the next decision to take, deliberately not taken here.

**Decision — `movesBound` moves to the data layer.** The card's roster-moves strip was scaled to
`max(adds, drops)` for that one player, on the reasoning that a card has no population to scale
against. It has one: the board the reader just came from. The old scale made every strip the
same picture — whoever had more adds than drops filled the right half exactly, whether that was
four transactions or four hundred thousand — so the shape carried no magnitude at all. The rule
now lives in `data/ros.ts` with one definition and two callers, each stating in its own caption
which population it bounded against.

**Decision — the tiles stay, and the duplication is the point.** Every value a meter places also
keeps a readout tile. The tile grid is the *record* and the meters are the *reading*: a board
whose position cohort is too small loses the reading and must never lose the number.

**The fixture had to carry the states, again.** This is the fifth instance of one species in
this repository (ADR-081, ADR-082, ADR-084, ADR-085): a fixture that expresses the *shape* of a
field and not its *states* leaves the states nothing is aimed at. `snap_share_last3` was `0.72`
on every row, so every cohort reading over it could only ever say "1st of 6"; every row carried
a `preseason_fair_rank`, so the rookie who was never on the preseason board — the case a
rank-move rail most needs to get right — was unexercised. The fixture now carries a breakout
with a null preseason rank scoring at twice the rate the model projects, a player the model
expects to improve, varied usage shares, and a row whose shares the feed never published.

**What did not change.** No model, artifact, schema, feature, simulation, tier, rank, count,
CSV column or Python file. `verify:board` runs against all five builds and reports zero
disagreements, which is the check that fails if one had.

**Consequences.**

- `PlayerDetailData` gains `rosCohort`, assembled in `App` from the published block. A future
  surface wanting the same readings builds the same context rather than re-deriving a rank.
- `movesBound` is imported from `data/ros` by `charts/OpportunityBoard`. A third caller adds no
  third definition.
- The card is longer. It scrolls on the desktop variant and the sheet's tab bar was already the
  answer to that on a phone; the meters stack at the sheet breakpoint, and the 320px reflow
  check now opens a card rather than only a page.
- `cohort_context_v1` is a versioned rule. Changing what a reading means — the population, the
  ranking convention, the band threshold — bumps it.

---

## ADR-087 — The player card gets a portrait, and the site's one third-party request

**Date:** 2026-09-16

**Status:** accepted.

**Context.** The owner asked for ESPN headshots on the player card, rendered as layered
overlays that blend into the HUD, and supplied both an example address and a mock-up:

> all players images are public and freely accessible; confirmed via ESPN terms. We just need
> to attribute ESPN on our 'data' tab in the Source section.
> `https://a.espncdn.com/i/headshots/nfl/players/full/4429795.png` (gibbs)

He expected the hard part to be the identity mapping, and suggested an ad-hoc scrape: the ESPN
public API, the `espn-api` package, or one of the community gists that document ESPN's athlete
endpoints.

**The mapping already existed, and it is this project's own primary identity bridge.**
`4429795` is Jahmyr Gibbs' `espn_id`, and `espn_id` is the column ADR-019 named
`espn_id_via_nflverse_rosters` — the *primary* market bridge, read off the nflverse roster,
cross-checked against the `ff_playerids` mirror with any disagreeing row rejected whole, and
already carried on every `CanonicalPlayer` in `ffdraft.identity.registry`. Verified against the
2026 roster: `gsis:00-0039139` → `espn_id 4429795`, which is the number in the owner's URL.
Coverage on the 2026 roster is **793/925 core players (85.7%)**, and **494/499 of the active
ones (99.0%)** — the players it misses are cut and practice-squad rows that no fantasy board
publishes.

So no scrape was written, no ESPN endpoint was called, and no name match was introduced.
That last point is the load-bearing one: `AGENTS.md` section 6 forbids a production join that
depends on a normalized name, and a portrait under the wrong player's name is exactly the
failure that rule exists to prevent. The crosswalk this ships is one the build already
computed and already fails closed on.

**Decision 1 — the crosswalk is a published artifact, not a vendored file.**
`player_headshots.json` (`player_headshot_record` 1.0), one row per canonical player, scoped
to the players the tier board names — the same population and the same reasoning as
`player_status` (ADR-043): a row nobody can open is payload the browser downloads for nothing.
It carries `player_id`, `provider`, `provider_player_id` and the resolved `image_url`.

A hand-maintained JSON blob under `web/public/` would have been smaller and would have been a
second source of truth that goes stale the first time a player changes teams. A crosswalk that
is regenerated by every build cannot.

**Decision 2 — the address is published, not assembled in the browser.** `image_url` is
redundant with `provider_player_id`, and the redundancy is the point: it makes *the one host
this page may reach* a property the build validates rather than a string in a JavaScript
bundle. Three independent checks read it — the record schema's own `pattern`, the validator's
`artifact.headshot_foreign_host`, and `artifact.headshot_url_disagrees_with_id`, which is the
one that catches a row carrying one player's id beside another player's picture.

**Decision 3 — hotlinked, not copied.** The owner's permission is that the images are public
and freely accessible with attribution. Copying several hundred ESPN photographs into a public
repository is *redistribution*, which is a materially stronger claim than the one he checked,
and `docs/SECURITY_LICENSE.md` section 8 draws that distinction for every other source in the
project. So the browser fetches them from ESPN and this repository stores none.

**What that costs, stated plainly.** Until today this site made **no cross-origin request at
all**. That was not an accident: ADR-059 and `docs/ARCHITECTURE.md` section 3.2 vendored the
two typefaces rather than linking them *specifically* so that no visitor's browser would
announce itself to a third party, and `board.spec.ts` turned it into a check. A reader who
opens a card now tells ESPN their IP address and which athlete id they looked at. That is a
real change to a documented property of the deployment and it is the reason this is an ADR
rather than a frontend commit.

Four things bound it, and each is enforced rather than intended:

| bound | enforced by |
|---|---|
| one host, and no other | the schema pattern, the validator, and the e2e guard's single allowance |
| never on first paint — only when a card is opened | `board.spec.ts` counts portrait requests before and after opening one |
| `referrerpolicy="no-referrer"` — an IP and a path, not a page | asserted in `playercard-portrait.test.tsx` |
| never on a board row | a portrait on 300 rows would be 300 requests for decoration |

The alternative that keeps the old property intact is vendoring, and Decision 3 rejects it on
rights. If that trade is ever reconsidered, reconsider it as a rights question, not a
performance one.

**Decision 4 — it is decoration, and it says nothing.** `alt=""`, the monogram and the veil
are `aria-hidden`, and nothing about the portrait is sortable, exportable or presented as a
fact about the player. The name, position, team, tier and status are all text within a few
pixels of the frame, so an image announcing "photo of X" would read the heading twice. This is
one step weaker than `player_status`'s "annotation only" (ADR-043): a status is at least a
measurement of something, and a picture is not.

**Decision 5 — the monogram is always in the DOM, behind the image.** A player the crosswalk
cannot reach, a blocked request, a slow network and a provider 404 then all look the same and
all reserve the same space. There is no empty frame, no broken-image glyph and no layout shift
when the picture arrives — and no opacity transition either, because the stylesheet has none
and this does not add one.

**Decision 6 — no test in this repository fetches a real portrait.** The specs route the host
to a local pixel; `verify-real-build`, `verify:board`'s engine, **blocks** it outright. A gate
that stands between a build and the deployed site may not go red because somebody else's image
server was slow. `capture-screens` is the one exception and serves a drawn silhouette, because
a design review of the card's layered treatment against a monogram would be a review of the
fallback.

**Consequences.**

- `docs/ARCHITECTURE.md` section 3.2 now has an exception, and it is named, single and
  checked. "No third party in the critical render path" is unchanged and still true: the
  portrait is not in any render path a page load takes.
- `schemas/artifact_envelope.schema.json` gains `player_headshots`; `build_metadata` gains a
  `player_headshots` provenance block naming the provider, the host and the coverage the build
  achieved. No existing record schema moved and no published number changed.
- Its absence is **not** a degradation and is not listed as one. A build without the artifact
  renders every board and every card, minus one picture.
- There is deliberately no coverage floor. A gate that could stop a deploy over a missing
  picture would be able to take the whole board down for a cosmetic reason.
- **Adding a second provider is a rights decision, not a config change.** `provider` is an
  enum of one in the schema for that reason.
- The non-commercial boundary in `docs/SECURITY_LICENSE.md` section 10 is untouched: ESPN's
  images are displayed, not redistributed, and no ESPN ranking, projection or ADP enters this
  product at any point. ESPN remains `disabled` as a *data* source in
  `config/source-registry.yaml`, which is a separate question and stays answered the same way.

---

## ADR-088 — Pick of the Week: a gate, an ordering, and the rostered share that does not exist

**Date:** 2026-09-18

**Status:** accepted.

**Context.** The owner asked for a new in-season tab showing the number-one waiver target at
each of QB, RB, WR and TE, as a "player highlight" card rather than a board row, cycleable
through up to five locked sets of four. He supplied two mock-ups — phone and desktop — and one
piece of product reasoning that turned out to be the whole design problem:

> Ideally we use Rost% because we don't want to say someone like Kyren Williams is a PotW (they
> are 99% rostered). Should be a clear cut-off for Rost%. If we can't get rost% data try to
> explore how we could, and if that fails, explore the next best route for inferring that
> (e.g., add/drop volume + add/drop momentum).

### 1. A rostered percentage is not obtainable, and the four routes are closed for four reasons

Checked before any code was written, because the answer decides the design:

| route | what it publishes | why it is closed |
|---|---|---|
| **Sleeper** | nothing | no ownership field exists anywhere in the documented API. The recorded schema of `/players/nfl` has none, and both trending endpoints return a **bare list of `{player_id, count}`** with no envelope and no metadata at all (`src/ffdraft/behavior/capture.py`) |
| **FantasyPros** | `player_owned_avg`, `player_owned_espn`, `player_owned_yahoo` | closed **twice over**. It is `benchmark_only` under ADR-014 as amended: internal comparison allowed, redistribution forbidden, so an ownership figure may not reach a public artifact *whatever key we hold*. And the provisioned key is free-tier — 40 distinct players across four positions, `public_api_limited: true` (ADR-080) |
| **ESPN** | `percentOwned` on its fantasy API | `disabled` in `config/source-registry.yaml`. Enabling it is a source decision needing a probe, a terms review and an ADR of its own under `AGENTS.md` section 5 — not something a frontend change may do on the way past |
| **sampling public leagues** | a share, by counting | a scrape, at a request volume the cadence rule in `AGENTS.md` section 5 forbids, against a source whose licence is non-commercial-use-only |

This is recorded rather than worked around. The owner's example is the right test of any
substitute and it is answered in the next section.

### 2. The add count *is* availability evidence, in the one direction that matters

The owner's named fallback is what this implements, and the reason it works is stronger than a
fallback usually is:

> A roster that added a player did not have him.

So an add count is a **lower bound on rosters that did not hold him**, measured in
transactions. A player rostered in 99% of leagues can therefore not post a large one, because
at most 1% of leagues are in a position to add him at all — and those only after somebody drops
him first. **Kyren Williams is excluded by construction, not by a threshold somebody tuned.**

What an add count cannot do is recover the *level*. "38% rostered" is not derivable from it in
any direction, so no surface in this feature prints a percentage of leagues, implies one, or
leaves room to infer one. It prints the count, its window, and the population it is compared
with. `Data` says the same thing in the reader's own words, and two tests — one component, one
over the deployed bytes in `verify-real-build.mjs` — fail on any sentence that reads as a share.

### 3. Decision — behaviour gates, the intrinsic model orders. Never a score.

`potw_selection_v1`. The rule that makes this legal under `AGENTS.md` section 10 is the
Opportunity Board's own rule, applied one level up — to a *selection* rather than to a row:

> Behaviour may decide whether a player is surfaced. It may never change his projection, his
> remaining VORP, his fair rank, or his tier.

**Six gates**, all booleans over published fields:

1. acquisition evidence exists — `behavior_available`, and `add_count` is a number;
2. the volume clears the **position's own** bar: the median of that position's non-zero add
   counts on the published board;
3. `net_add_count > 0` — the one subtraction the opportunity schema sanctions, because both
   sides are the same unit over the same window from the same feed at the same moment;
4. not `long_absence` — the model's ordering inside that cohort is measurably near-random
   (Spearman 0.311 against 0.797, ADR-076), so a confident number-one pick there would
   contradict the published limitations;
5. no severe roster code (`RES`, `INA`, `PUP`, `NFI`, `SUS`, `CUT`, `RET`);
6. `ros_expected_vorp > 0`.

**Then one ordering:** `ros_expected_vorp` descending, tie-broken on `ros_fair_rank` then
`player_id`. The add count decides membership and has no say from there.

**Gate 6 is not a threshold somebody chose.** The in-season replacement rule is
`rostered_depth` (ADR-071), which defines replacement as *the best unrostered player* — so a
remaining VORP at or below zero is the model stating, in its own units, that the player is no
better than what is already on the wire. "Add him" and "he is not worth more than the waiver
wire" cannot both be true. The strictness is the point: when nothing clears it, the view says
nobody did.

**Why the bar is a population median rather than a constant.** Sleeper's feed is a top-100 list
whose absolute counts scale with how many leagues exist that season; a hard-coded 500 would mean
something different next August. It is taken **per position** because "the most-added QB" and
"the most-added TE" are different markets with different volumes, and one cross-position bar
would be a bar on running backs and receivers only. Below three non-zero counts there is no
distribution to take a median of, so the bar falls back to "the feed saw him at all" and the
card says which case it is in — the same discipline `cohortStat` uses when it withholds a
reading rather than printing `1st of 2`.

**A set is a depth, not a tier.** Set *k* is the *k*-th ranked eligible player at each position,
capped at five. The players in one set have nothing to do with each other beyond sharing that
depth, and where a position's pool runs out the view names the position and says which of three
things happened rather than rendering an empty frame.

**Picks change daily, by construction.** The add counts are a 24-hour window and the
rest-of-season values are rebuilt every refresh, so the board is deterministic for a build and
different between builds. That is the behaviour the owner asked for rather than a caveat.

### 4. What is deliberately not built

- **No blended score, at any point.** An add count is transactions and a remaining VORP is
  points; any weighting of the two is a coefficient nobody measured wearing the authority of a
  ranking. `AGENTS.md` section 10, ADR-085 and the Opportunity Board all say so already.
  `web/tests/potw.test.ts` asserts it *behaviourally* rather than by inspection: hold the adds
  equal and the winner follows the VORP; multiply one candidate's adds two-hundred-fold and the
  winner does not move. A blend of any weight fails the second.
- **No published `potw.json`.** The selection computes no player value — every number on a card
  is copied from `inseason_opportunity.json` or `ros_tiers.json` — so it is arithmetic over
  published rows in exactly the sense ADR-086 licensed for the card's cohort readings, and it
  lives in `web/src/data/potw.ts` beside them. A new artifact would be a data-contract change
  under `AGENTS.md` section 18 that bought nothing the reader can see.
- **No preseason-rank gate.** `preseason_fair_rank` is the closest published answer to "was he
  drafted", and it was considered as a second availability clause and rejected: a star who was
  mass-dropped during an absence and is being re-added *is* a waiver target, and that clause
  would have excluded exactly him. It appears on the card as **context** — "the preseason board
  never ranked him", "up N places since preseason rank M" — and never as a gate.
- **No CSV export.** The four rows are a selection from the Opportunity Board, which exports in
  full; a second export of the same bytes under a different name is a second thing to keep
  right.

### 5. The portrait rule, extended once and bounded

ADR-087 ended with "no portrait on any board row (300 rows would be 300 third-party requests
for decoration)". That rule stands and is the reason this needs saying: **Pick of the Week is
not a board.** It is at most four cards, on a tab a reader chose to open, and the picture is
the format the owner asked for rather than decoration added to a table.

The bound is structural: only the visible set's portraits are in the DOM, so cycling sets
*replaces* four requests rather than accumulating twenty, and `PlayerPortrait` is reused
unchanged, so the published address, the `no-referrer` policy, the monogram fallback and the
one-host allowance all come along. `inseason.spec.ts` counts the requests and asserts the image
count never exceeds the card count; `docs/ARCHITECTURE.md` section 3.2 records the widened
boundary.

### 6. The mock-up was read as a claim to check, not a string to copy

Three of its readouts are not in this build, and each absence is section 1 or a missing
artifact rather than a shortcut:

| mock-up | replaced by |
|---|---|
| `38% ROSTERED` | `Adds (24h)`, with the bar it cleared and the population that set it |
| `▲ +26% LAST 3 GAMES` | `Net roster moves` over the same single window, labelled as a direction and not a trend |
| `MATCHUP vs IND (18th vs QB)` | `ROS expected VORP` with its position-cohort reading — which is *why* he is the pick |
| `ADD MOMENTUM` sparkline | the diverging adds/drops strip, on the board's own `movesBound` |

The sparkline is the one that is a *data* gap rather than a rights gap: the retained store holds
a daily behaviour snapshot per day since the season opened, and nothing publishes a series over
them. A `behavior_trend_series.json` mirroring `market_trend_series.json` would make a genuine
momentum reading possible and is recorded in the post-V1 backlog rather than built here — it is
a data-contract change, and this pass publishes no new artifact on purpose.

**Consequences.**

- One new tab, one new URL parameter (`set`), one new module, one new view. No schema moved, no
  artifact changed, no Python file changed, and no model, feature, projection, rank, tier, VORP,
  ADP or CSV column moved.
- `verify-real-build.mjs` gains a Pick-of-the-Week block: every rendered number against the
  artifact's own, plus the four properties the claim itself requires. It does **not** recompute
  the floor or the ordering — restating a rule in its own checker gives a build two
  implementations that can disagree, which Phase 9B already paid for once.
- `.section-head h2` became shrinkable. It was `flex: none`, which held while every section
  title fitted at 320px and produced 3px of silent horizontal scroll on the first one that did
  not. Shrinking engages only on a line that overflows, so no existing heading moves.

---

## ADR-089 — The retained behaviour window is published, and a direction may be stated from two observations

**Status.** Accepted, 2026-09-19. Rule `behavior_trend_v1`. Supersedes nothing; extends
ADR-088's Pick of the Week and closes `SESSION_STATE.md` backlog item 0b.

**Context.** The append-only store has held a daily Sleeper add/drop snapshot under
`behavior/` since the season opened — nine days of observations by the time this was written,
appended by every successful `daily-refresh` since 2026-09-10. Exactly one thing read them:

```
src/ffdraft/pipeline/ros.py     read_behavior_capture(...)
src/ffdraft/behavior/capture.py resolved = key or behavior_store.latest_key(source_id, season)
```

`latest_key` returns the newest directory, so the whole retained history reached the published
board as **one 24-hour number per player**. ADR-088 recorded the consequence in the product's
own words: Pick of the Week can say "net +1,120 over 24 hours" and cannot say "rising for four
days", and the mockup's `ADD MOMENTUM` sparkline was listed as the one element of that design
that was a *data* gap rather than a rights gap.

Nothing was blocking it. The market side had already built the same machinery twice —
`ffdraft/market/history.py` reads a trailing window, `phase5_trend_v1` estimates a slope over
it, `market_trend_series.json` publishes the points and `MarketTrend.tsx` draws them. Behaviour
had none of the four.

**Decision 1 — read the window, and change nothing the board publishes.** A new module,
`ffdraft/behavior/history.py`, reads every retained capture inside the trend window, projects
each onto canonical ids nflverse-first (ADR-011, once per snapshot rather than once), and hands
the result to a frozen statistic. The Opportunity Board's `add_count`, `drop_count`,
`net_add_count`, `add_rank` and `drop_rank` still come from `resolve_behavior_signals` reading
the newest capture and are untouched. `test_behavior_history.py` asserts that a store with a
week behind it and a store holding only today's snapshot resolve **byte-identical** behaviour
signals, and that the two histories genuinely differ — so the invariance is not vacuous.

**Decision 2 — `behavior_trend_v1` states a direction from two observations, and
`phase5_trend_v1` is deliberately not reused.** The market rule refuses to estimate a slope
below three observation days spanning three days. That is right for a draft price: an ADP moves
slowly, a two-point line through one is mostly noise, and a reader comparing Tuesday's board
with Friday's needs the same window on both. An add count is the opposite kind of quantity — a
count of transactions inside a declared 24-hour window, moving in hours — and a waiver edge is
gone by the time a three-day bar admits it. So:

```
add_trend = OLS slope of add_count on days elapsed, over the retained window,
            using every observation that exists
```

with two observations enough. At two points that reduces exactly to the difference over the
elapsed days, which is what makes `min_observations = 2` a continuous extension of one
statistic rather than a second rule bolted beside it. One observation carries no direction,
which is arithmetic rather than policy: a line needs two.

**What keeps that honest is the label, not suppression.** A two-point slope is a real
measurement of a short window and a bad estimate of a long one, so `span_days` and
`observations` are **required** fields and no surface may print a direction without the span it
was measured over. The artifact validator fails a record carrying a trend with fewer than two
points, or a span that disagrees with its own points; `verify-real-build.mjs` fails a rendered
`/day` figure with no span text beside it; and the component test asserts the same from the
page's side.

**Decision 3 — the sign is not negated, and must not be "fixed" to match the market module.**
`phase5_trend_v1` negates its slope because a *falling* ADP means a player is getting more
expensive. There is no such inversion here: a bigger add count is straightforwardly more
interest, so positive means rising.

**Decision 4 — an absence is not a zero.** Sleeper's trending endpoints return the 100
most-added players and nothing else, so a player outside that list on a given day has a count
somewhere in `[0, the smallest count that did appear]` — unknown, not zero. A snapshot that did
not carry the player therefore produces **no point**, the record publishes
`snapshots_in_window` beside `observations` so the difference is visible, and the strip draws a
gap mark rather than a floor-height bar. Filling those days with zero would manufacture a
collapse in interest out of a player leaving a leaderboard.

There is one place a zero *is* correct and the code takes the distinction seriously: a player
can be in the top 100 adds and outside the top 100 drops, and the feed did report on him that
day. The union is therefore taken per *capture* rather than per feed.

**Decision 5 — one record per player, not per preset.** An add count is the same set of
transactions however points are scored. `inseason_opportunity` already deduplicates its role
columns across presets for this reason; keying the series by league and scoring would publish
nine identical copies of every history.

**What is published.** `behavior_trend_series.json`, record schema `behavior_trend_series` 1.0,
keyed `(build_id, player_id)`, restricted to players the Opportunity Board publishes. No CSV —
the record is a series, a row per point would be a different artifact from the one a reader
asked to export, and the Opportunity Board's CSV already carries the day's counts. The
in-season metadata gains `behavior.history`, describing the window the series was cut from.

**Degradation, at three levels rather than one.** The behaviour feed is optional by
construction (ADR-079); a history over it is optional again; and a series for a given player is
optional a third time. An unreadable store, an empty window or a registry that cannot be built
each produce a warning and no artifact, and both in-season boards publish exactly as they
would have. On the page, the three absences are **three sentences** — the build published no
history, the feed has not carried this player, or he has one observation and therefore no
direction yet — because a reader can act on the difference.

**What this does not change.** No model, feature, projection, rank, tier, VORP, ADP, arbitrage
score or existing schema. No Release 1 or Phase 10 record moved. `AGENTS.md` section 10's ban
on blending an add count with a VORP is untouched and the new surface is inside it: today's
counts and the window behind them sit side by side, in the same unit as each other and in no
unit shared with anything intrinsic, and there is no combined score anywhere. ADR-088's rule
that no surface in this feature may print, imply or leave room to infer a share of leagues
binds the history exactly as it binds the day — a count of transactions has no denominator in
leagues however many days of it are drawn — and both a component test and the pre-deploy gate
assert it on the rendered bytes.

**Five things a future session should not re-derive.**

1. **The store was always holding this.** Nothing was blocked, no source was added and no
   rights question was reached. The only thing missing was a reader that asked for more than
   `latest_key`, and the market module had shown what that looks like since Phase 5.
2. **A two-point slope is a feature, not a tolerance.** If a future session is tempted to raise
   `min_observations` to match the market rule, the thing to change is not the bound: it is to
   ask whether the *span* is still being printed, because that is what the bound would be
   standing in for.
3. **`snapshots_in_window` is what makes a gap legible.** Without it a short series and a
   sparse one look identical, and the difference between "the season is three days old" and "he
   was outside the top 100 for four of seven days" is the whole reading.
4. **`--dist` alone cannot negative-control `verify:board`.** The gate compares the rendered
   page with the bytes that page was served, so corrupting an artifact inside the dist corrupts
   both sides and the check correctly agrees. Controls must corrupt the *checker's* copy:
   `--dist <clean> --data <corrupted>`. Five controls were run that way and all five fire — a
   moved slope, a dropped point, a nulled direction, an invented gap and a deleted series.
5. **An in-season artifact must be added to `_IN_SEASON_ARTIFACTS`, and the fixture cannot
   tell you when you forget.** Added after the fact, because this shipped wrong. See the
   correction below.
6. **The fixture carries six states and none of them is "the normal one."** A full rising
   window, a two-point one, a single observation, a gap, a falling count and a board player with
   no series at all. Six instances of the fixture species are already recorded in
   `SESSION_STATE.md` (ADR-081, 082, 084, 085, 086, 088); this was built against that list
   rather than after joining it. The frontend fixture adds a seventh state a single bundle
   cannot hold — a window that is genuinely only two snapshots deep, which is what the site
   looks like the week a season opens.

### Correction, 2026-09-19 — the bundle boundary (daily-refresh run 54)

The first production refresh on this code **failed at `validate-artifacts`**, on a build whose
numbers were all correct:

```
[critical] build_metadata.build_id_mismatch (artifacts.build_metadata):
  behavior_trend_series carries a different build_id from build_metadata
  observed: 2026w01-intrinsic-ros-v1-20260919T112638Z
  expected: 2026-intrinsic-cb-hurdle-v1-20260919T112419Z
```

**The check was right and the membership list was wrong.** `daily-refresh` runs two builds into
one directory — `build-current` stamps the draft bundle, `build-ros` stamps the in-season one
minutes later — and `_IN_SEASON_ARTIFACTS` in `ffdraft/artifacts/validate.py` is the single
place that says which artifact belongs to which. A build id is compared *inside* a bundle and
never across one. `behavior_trend_series` is written by `run_ros_build` and was not added to
that set, so `_build_metadata_checks` read it as a draft artifact and compared its ROS build id
against the draft bundle's.

**The omission cost two things, and the loud one hid the quiet one.** The draft check failed on
it; and `_ros_metadata_checks` — which filters on the same set — silently skipped it, so the
build-id and `through_week` agreement it *should* have been getting was never asserted at all.
One membership list, two directions, one line.

**Why every local gate passed.** The fixture build produces every artifact in one pass under
**one** build id, so a draft artifact and an in-season artifact trivially agree there and an
artifact filed in the wrong bundle is invisible — its id matches whichever metadata it is
compared against. Tenth instance of the species, and the first aimed at the *bundle boundary*
rather than at a rendering.

**What was added, and the trap inside it.** `tests/contract/test_two_bundle_validation.py`
builds the two-bundle shape by re-stamping the in-season half with its own build id, and
asserts three things: the production shape validates; breaking an in-season artifact's id
raises `ros_build_metadata.build_id_mismatch` and *not* the draft one; and a draft artifact
stamped with the ROS id still fails, so the fix can never become "stop comparing build ids".

The first version of that file built its fixture by iterating `_IN_SEASON_ARTIFACTS` — **the
set under test**. Reverting the fix therefore also stopped the fixture re-stamping the missing
artifact, no mismatch occurred, and the test written to reproduce the production failure passed
on the broken code. It now derives the list from `pipeline/ros.py` instead, and a fifth test
compares the two directly, so a *future* in-season artifact fails on a unit test rather than
three minutes into a refresh. **A fixture derived from the thing it is testing asserts its own
assumptions** — that is the durable lesson, not the one-line fix.

**Production was never at risk.** The job graph did what ADR-050 built it to do: `validate`
failed, every step after it skipped including the Pages upload, `deploy` was **skipped**, and
the previously deployed site stayed live and unchanged. The capture job had already committed,
so the day's behaviour snapshot is in the store and the history is not short a day.


---

## ADR-090 — A snapshot is a run, not a day, and the momentum strip draws every one of them

**Status:** accepted, 2026-09-19
**Supersedes:** nothing. **Amends:** ADR-089's rendering, not its rule.

### What happened

The refresh immediately after ADR-089's bundle fix cleared `validate-artifacts` and stopped one
step later, at `verify:board`:

```
Bryce Young: momentum strip drew 12 bar(s), artifact publishes 14 observation(s)
Jacory Croskey-Merritt: momentum strip drew 12 bar(s), artifact publishes 15 observation(s)
Caleb Douglas: momentum strip drew 12 bar(s), artifact publishes 15 observation(s)
Dalton Kincaid: momentum strip drew 12 bar(s), artifact publishes 15 observation(s)
```

`BehaviorSparkline` held `const MAX_BARS = 12` and drew `points.slice(-MAX_BARS)`. The check was
right, the component was wrong, and the number that made them disagree was **fifteen**.

### Why fifteen, when the window is seven days

Because a snapshot is a `daily-refresh` run and not a day. The schedule is `17 7 * * *` plus
`40 12 * * 2`, so an ordinary week already holds eight; the week ending 2026-09-19 held sixteen
runs, one of which died before its capture step, because a `workflow_dispatch` re-run is how this
repository gets deployed and there had been a lot of deploying. Five of those runs were inside
eight hours of one afternoon.

Nothing downstream was wrong about this. `compute_behavior_trends` already fits on **elapsed
days** rather than on sample index, and already publishes `observation_days` beside
`observations` — the docstring says "several snapshots on one calendar day all count as
observations but only one observation day". The Python side anticipated the case exactly. The
frontend did not, the fixture did not, and the two agreed with each other.

### The decision

**The strip draws every published point. No cap, in the component or anywhere else.**

A cap looks like a legible-width guard and is not one, because *nothing else in the panel
truncates*:

| what the card shows | measured over |
|---|---|
| the slope, `+40.0/day` | the whole window |
| the span, `over 7 days` | the whole window |
| the gap mark and its count | the whole window |
| the bar heights, scaled to `peak` | the whole window |
| the bars — until this ADR | the newest twelve |

So a truncating cap does not shorten the reading. It makes the picture describe a different
window from the four numbers printed beside it, and it silently rescales the y-axis against a
maximum the cap can push off-screen. The component cannot fix that by restating the reading for
the stretch it drew, because `behavior_trend_v1` is the artifact's rule and Phase 9B already
paid for restating a rule in a second language. Draw all of it, or draw none of it.

**Width is not the constraint it looked like.** Measured on the built page: the narrowest strip
is 261px at a 320px viewport, and `.momentum-bar`'s `min-width: 2px` with a 2px gap fits **65
bars** before anything overflows. A seven-day window reaches that at ~9.4 runs a day sustained
for a week. At fifteen bars the bars are 15–20px wide at every breakpoint and the page overflows
by 0px at 1440, 1024, 768, 420 and 320. `max-width: 20px` stays exactly as ADR-089 left it —
that cap is for the *short* series, and it is still the only reason one observation does not
render as the picture of maximum momentum.

### Why the gates all passed, again

`FIXTURE_BEHAVIOR_SNAPSHOTS = 7`, one snapshot per calendar day, in both the Python fixture and
the frontend one. Twelve is a generous cap for a week of daily snapshots and a miserly one for a
week of runs, so **no fixture in the repository could reach the cap**, and `momentum.test.tsx`'s
"draws one bar per retained snapshot and no more" ran only against the two-point `young` case.
Eleventh instance of the species `SESSION_STATE.md` records: a fixture carrying a feature's shape
and not its state.

The fix is therefore in the fixture first and the component second. Both fixtures now build from
`daily-refresh`'s own run history for the week ending 2026-09-19, rounded to the hour:

```
167, 151, 127, 100, 99, 97, 95, 89, 79, 73, 55, 31, 26, 7, 0   (hours before the anchor)
```

Fifteen snapshots across **eight** calendar dates, five of them in one afternoon. Three things
that had never been true of a fixture in this repository are now true of this one:

- `observations` (15) differs from `observation_days` (8), so any consumer that reads one as the
  other is wrong on the goldens rather than only in production;
- the two-point case spans **seven hours** rather than a day, which is what two runs on one
  afternoon look like and the only case that drives `spanLabel`'s hours branch through a rendered
  card;
- the counts walk per *day elapsed* rather than per sample, so the fitted slope is not a function
  of how often we happened to capture. Five samples in an afternoon now read as an afternoon's
  drift — visible in the goldens as `548, 550, 553, 557`, four near-equal bars in the middle of a
  rising window.

### Evidence

Reproduced before fixing: the fixture change alone, against the unmodified component, produces
`momentum strip drew 12 bar(s), artifact publishes 15 observation(s)` — production's message on
a local build. After the fix, `verify:board` reports zero failures.

Negative control on the new unit test: restoring `slice(-12)` fails
`a window as long as the week actually was > draws one bar per published point on every card`
with `expected …(12) to have a length of 15 but got 12`. The two fixture-state assertions beside
it still pass under that control, which is the separation they are for — one test owns the
rendering, the others own the fixture being capable of catching it. That second guard is the
lesson ADR-089 wrote down and is applied here: a test that draws every point proves nothing if
the fixture never has more points than a cap would allow.

Captured: `docs/visual-qa/2026-09-19-momentum-window/` — all 73 screens inspected, the nine
Pick of the Week ones committed, and the strips read at 3× rather than at page scale, because a
count is exactly the thing a page-scale screenshot cannot settle. One note for a future reviewer that is **not** a defect: a fifteen-bar window
reads flatter than a seven-bar one at the same slope, because the bar scale is zero-based
(ADR-086) and more samples over the same span make a smoother picture. Bijan Robinson's window
runs 437→715 adds, which is `69%`→`100%` of peak and about 11px of rise across 34px of strip. The
alternative — scaling to the series' own min — would make every small move look dramatic, so the
zero base stays.

### What this does not change

`behavior_trend_v1` is untouched: same window, same `min_observations: 2`, same sign convention,
same fields. This is a rendering fix and a fixture correction, so no sealed season is spent
(ADR-078) and no model artifact moves. `_IN_SEASON_ARTIFACTS` and ADR-089's bundle fix are
unaffected. The only published bytes that change are the committed goldens, whose behaviour
series now carries the cadence production has.

---

## ADR-091 — The in-season signal layer: observed role and the next game, published beside the model and never inside it

**Status:** accepted, 2026-09-22
**Supersedes:** nothing. **Amends:** `docs/SIGNAL_EXPANSION_EDA.md`'s framing (Part 4), and the
Pick of the Week card's secondary tile row (ADR-088). **Takes:** the EDA's §2a.3 Vegas decision,
reading 3 only.

### The question, restated by the owner

The EDA framed signal expansion as preparation for a future sealed-season retrain. The owner
corrected that framing: the objective is **current-season decision support** — whether a player
is worth a waiver claim *this week* — and the rest-of-season model is one signal among several,
not the thing to be improved. A manager deciding on a claim asks whether a role is expanding,
whether snaps rose before the box score did, whether a receiver is earning downfield looks the
catches have not caught up with, whether scoring leans on touchdowns, who he plays next, and
whether the wire's interest is following a football change or just itself. The product answered
the last question (ADR-088, ADR-089) and none of the others.

### What was already downloaded, measured rather than assumed (2026-09-22)

This sandbox reached `github.com/nflverse/nflverse-data` release assets for the first time, so
the EDA's UNVERIFIED items were probed live on the 2026 files (weeks 1–2 complete):

| feed | finding |
|---|---|
| `load_player_stats(week)` | 2,225 rows; `target_share` recomputed from the same rows matches nflverse's exactly; nflverse's `air_yards_share` does **not** (up to 9 points apart — a different denominator) |
| `load_snap_counts` | 2,994 rows; 6 of 818 skill rows fail the `pfr_id` bridge |
| `load_schedules` | spread and total posted for **weeks 3–4 only**; rest and roof populated for every future game; **temperature and wind null for every unplayed game** |
| `load_injuries` | the 2026 file is live (433 rows); the registry's "refuses seasons after 2025" was stale drift, corrected |

### Decision 1 — two artifacts, both observed context

**`player_usage.json`** (`usage_signals_v1`, one record per Opportunity Board player): every
fantasy-horizon week through the cutoff with its status (`played` / `bye` / `did_not_play`),
snap, target, carry and air-yards share, targets, carries, pass attempts and fantasy points per
preset; a change per role metric; the share of points from touchdowns per preset; and pass EPA
per dropback. Arithmetic over nflverse's weekly rows and snap counts (CC-BY 4.0), which every
in-season build already downloads.

**`team_matchups.json`** (`next_game_v1`, one record per team): the team's earliest
regular-season game in the horizon that has not kicked off at build time — opponent, venue,
neutral-site flag, kickoff, rest days for both sides, roof — and the posted spread and total,
re-expressed from the team's own side, with the two implied scores.

Neither is a model input and neither reads a model output. Both are written by `run_ros_build`
after every board exists, reading from the boards only *which players exist*, and both are in
`_IN_SEASON_ARTIFACTS` in the same change (ADR-089's lesson).

### Decision 2 — the change rule, `role_change_v1`

**Latest appearance against the average of every earlier appearance this season.**

| | |
|---|---|
| window | latest appearance at or before the cutoff vs every earlier appearance — not a fixed trailing window, because in week 2 the only comparison that exists is week 2 against week 1, and a three-week rule says nothing until week 4, after the waiver runs that matter most |
| averaging | shares counted in team units (targets, carries, air yards) are **pooled**, as `target_share_to_date` is; snap share and raw attempts are a **per-game mean**, as `snap_pct_mean_to_date` is |
| minimum | one earlier appearance with the metric defined; below it the change is null and the latest value still publishes |
| sign | `change = latest − earlier` in the metric's own unit; positive is a bigger role |
| missing | a metric undefined in the latest game (no snap row) yields a null change — it never falls back to an older game |
| rounding | `change` is the difference of the two *published, rounded* halves, so a reader subtracting them gets exactly it |

**An appearance is a stats row or an offensive snap.** nflverse writes a stats row only when a
player records a statistic, so a receiver who ran routes and was never targeted has a snap row
and no stats row — the week a role reading most needs. On that week every count is a genuine
zero. This is deliberately wider than the ROS panel's "played" (a stats row), and the difference
is documented rather than hidden: games played on the card is still the ROS definition.

Two sustainability readings, each with a declared minimum: **points from touchdowns** (null
below 10 points to date; can exceed 100% when turnovers subtracted points) and **pass EPA per
dropback** (nflverse passing EPA over attempts plus sacks; null below 20 dropbacks).

### Decision 3 — the sportsbook lines are context, and only context (EDA §2a.3, reading 3)

AGENTS.md §8 requires a written decision before a market-expectation proxy is *added as a
feature*. This ADR adds none. It takes reading 3 exactly: the spread, the total and the implied
points are **printed beside a player** and computed into nothing — no projection, VORP, rank,
tier, cohort reading or Pick of the Week selection reads them. Readings 1 and 2 (lines as an
intrinsic or ROS feature) remain unmade and carry a sealed-season cost; nothing here pre-empts
them.

The firewall is enforced, not stated:

- `ffdraft.quality.forbidden` now refuses feature names carrying `spread`, `moneyline`,
  `vegas`, `sportsbook`, `odds`, `implied`, `total_line`, `expected_margin`, `implied_team`;
- `tests/unit/test_signal_matchup.py` asserts every sportsbook field is refused by name, and
  that no field either signal artifact publishes is a feature of `ros_core_v1` or
  `intrinsic_core_v1`;
- the schedule's new columns are *context columns* (Decision 5): a feature builder that read
  one would be reading a column the contract labels context-only.

The build metadata carries `sportsbook_context_statement`, printed wherever a line is shown.

**Provenance.** nflverse does not document which sportsbook its schedule lines come from (the
nflreadr dictionary and nfldata's DATASETS.md are both silent, checked 2026-09-22). The lines
are published under nflverse's CC-BY statement with nflverse attribution; this project publishes
the consensus **spread and total only — no odds prices, no moneylines** — and no CSV of them.
Recorded as a residual rights question for the owner, not a blocker.

**Weather is not published** — no source carries it for an unplayed game.

### Decision 4 — ffopportunity stays off the published layer

Expected fantasy points, team xFP share and points over expected are the readings a waiver card
would most like to show ("scoring on volume or on conversion"). ffopportunity's expected points
are CC-BY-SA 4.0 and whether a derived per-player figure may be published is the open ADR-086
owner decision. **Nothing in either artifact derives from ffopportunity**, and the build metadata
carries `expected_points_statement` saying why. The next-best signals were taken instead: touchdown
share for sustainability, air-yards share for unrealised downfield opportunity.

### Decision 5 — context columns do not block builds

`BaseSourceAdapter.context_source_columns` declares upstream columns read **only** into
published context. A missing one is a warning (`source_schema.missing_context_columns`) that
nulls a context field; a missing required column is still critical. The weekly adapter gains
`passing_epa` and `sacks_suffered`; the schedule adapter gains `location`, `away_rest`,
`home_rest`, `roof`, `spread_line`, `total_line` (contracts 1.1, additive). A test asserts the
two sets never overlap.

### Decision 6 — position decides what leads, in one place

`web/src/data/signals.ts` holds `ROLE_METRICS_BY_POSITION`:

| position | role rails | why |
|---|---|---|
| QB | pass attempts, rush attempts | a starter's snap share is ~100% and target share ~0%; the card used to rank those constants (EDA Part 2b) |
| RB | snap, carry, target share | "is he taking over the backfield" |
| WR | snap, target, air-yards share | "is he earning downfield looks the catches have not caught up with" |
| TE | snap, target share | the field and the targets |

The card's cohort strip and tiles follow the same map: a quarterback's rows are points per game,
EPA per dropback and points from touchdowns; everyone else keeps the two three-week shares and
gains points from touchdowns. The artifact carries all six metrics for every player — which ones
lead is presentation, and a quarterback's target share is still a fact.

### Decision 7 — Pick of the Week's selection does not change

`potw_selection_v1` is untouched: six gates, one ordering on `ros_expected_vorp`. A vitest builds
every set for every preset with and without the signal artifacts and requires identical picks.
What changes is the explanation: an evidence row — **Role · observed**, **Production**,
**Next game · context** — replaces the tile row that printed two three-week shares for every
position, and "why he is the pick" gains one sentence when (and only when) his leading role grew,
because that heading makes a claim; a shrinking role is shown in the evidence row, never hidden.
ADR-088's "no matchup rating" stands: the next game is sourced now, a *rating* still is not.

### Decision 8 — add momentum reaches the player card

The in-season card now carries the same `BehaviorSparkline` Pick of the Week draws (ADR-089),
from the same `behavior_trend_series.json` record, below the roster-moves strip. It is the
*market behaviour* concept, kept in its own block beside the observed role rather than blended
with it, and it is absent — with the reason stated — for a player the trending feed never
carried. ADR-089 left the card out because it was not asked for; a waiver decision made from the
card is exactly where "is the wire's interest building or fading" belongs next to "is his role
building or fading", and the two readings sit in separate, labelled blocks.

### Two pre-existing defects the captures found

1. **A card for a player the draft board never held was headed "Player".** The header read only
   draft records (tier, arbitrage, status). The in-season records are identity sources now.
2. **A surfaced player's card was a draft-market card.** A player surfaced from beyond the ROS
   depth has no ROS row by contract, so the in-season panel — keyed on that row — fell back to
   "No current FFC ADP" in-season. The panel now renders from the Opportunity Board row, withholds
   only the projection-dependent pace and tiles, and says why.

Plus three defects in this change's own first draft that no test failed on and the first capture
showed: the evidence row landed in the portrait column, the card's momentum strip painted every
bar but the latest transparent (its colour variable is scoped to Pick of the Week cards), and a
`▼` glyph sat beside "no change" (the glyph now follows the printed rounding). And one in the
frontend fixture: the surfaced row spread its anchor's record and inherited a starter's
three-week shares, so a one-appearance card drew a 55% tile beside a single 45% rail; its shares
and appearances now come from its own weeks. And one the final capture found: in a build with
no signal artifacts, Pick of the Week's next-game block said "No next game is published for
DET" — a claim that a schedule was read and was empty. It now says the build published no
schedule context, as the card does, and a test fails on the old sentence.

### Verification

`verify-real-build.mjs` compares every rendered role value, change and bar count, the points
rail, the next game and the implied points against the artifacts, on one card per position and
on every pick, and fails a quarterback card or pick that leads with a snap or target share.
The card's momentum strip is compared against `behavior_trend_series.json` by the same function
the pick cards use (`momentumFailures`), so the two surfaces cannot drift apart. Negative-controlled
six ways (a moved change, a dropped week, moved implied points, a deleted game, a patched bundle
leading a QB with snap share, and an inflated observation count, which fires on all four
cards) — all fire. A real `build-ros` on live
2026 week-2 data validates 0 critical / 0 warning and passes the gate with zero disagreements.

### Payload

588 usage records at week 2 are 1.36 MB (≈258 bytes per week entry), projecting to about 2.6 MB
at week 17 — against 6.6 MB for `ros_tiers.json` today. No CSV for either artifact: one is a
series, and a downloadable table of sportsbook lines is a redistribution step with no reason to
take it.

### Deliberately deferred

| signal | why not now |
|---|---|
| xFP, xFP share, points over expected | the open CC-BY-SA decision (ADR-086) |
| WOPR | a fixed-weight blend of two shares the card already shows separately |
| RACR, yards per target/carry, CPOE | one efficiency reading per position is enough to start; CPOE needs a play-weighting the weekly file cannot reproduce exactly |
| red-zone / goal-line opportunity | needs play-by-play; not built for one metric |
| opponent points allowed by position | derivable from the weekly rows, but two games is not a defensive profile; revisit around week 5 |
| weather | no source for an unplayed game |
| injuries | the feed is live; its point-in-time behaviour is unprobed (AGENTS §7) |
| POTW selection using role signals | a separate, explicit design decision; not taken |

---

## ADR-092 — The Opportunity Board reads the signal layer: one join, three readings, three filters, and no score

**Status:** accepted, 2026-09-23
**Supersedes:** nothing. **Amends:** ADR-085 (the Opportunity table's columns and the chart's
fourth readout), ADR-089 (the momentum reading gains an *ended* state on the board, and one
printed precision shared with the card), ADR-091 (the board is now a consumer of the signal
layer). **Leaves untouched:** every artifact, schema, model, rule version and
`potw_selection_v1`.

### The question

ADR-091 taught the player card and Pick of the Week to read observed role, add momentum and
the next game. The Opportunity Board — the one surface a manager scans five hundred waiver
candidates on — could read none of them: it printed ROS value, adds, drops, net adds and a
generic three-week snap share (a constant ~100% for every quarterback). A reader could learn
that a back's snap share went 6% → 41% only by opening his card, which is the thing a scanning
surface exists to spare them. The owner's brief: make the board the *triage* surface for the
signal layer — scan, find interesting combinations, open the card for the evidence — without
inventing a master score and without new data.

### Decision 1 — one join, in one module, and absences are kinds

`web/src/data/candidates.ts` joins each published Opportunity row to its `player_usage` record,
its `behavior_trend_series` record and its team's `team_matchups` record, and computes nothing:
every value is a published field, the role direction is `roleReading`'s (the card's function)
and the momentum direction is `momentumDirection` (the card's strip's function, moved to
`data/ros.ts` so the two cannot drift). Each reading is a discriminated union:

| reading | kinds |
|---|---|
| role | `unpublished` · `no_record` · `no_appearance` · `no_latest_value` · `one_game` · `measured` |
| momentum | `unpublished` · `not_in_feed` · `one_observation` · `ended` · `measured` |
| next game | `unpublished` · `no_team` · `no_record` · `published` |

"The build published no file", "it published one without him" and "his latest game has no
value for this measure" stay three sentences on the page, in the export and in `verify:board`.
`InSeasonBundle.hasUsage` / `hasMatchups` / `hasBehaviorSeries` now mean *the build published
the artifact* (non-null) rather than *it holds at least one record*; the Python side never
writes an empty signal artifact, so the two agree on every real build, and the stricter one is
the right name. `signalTeam()` is now the one rule for which team's next game a player gets —
the card, Pick of the Week and the board all ask it.

No backend artifact was added. A published `opportunity_candidates.json` would duplicate three
artifacts' bytes under a fourth contract for a join the browser can make exactly.

### Decision 2 — the position's leading role metric replaces the generic snap share

The board's role reading is `ROLE_METRICS_BY_POSITION[position][0]` — pass attempts for a
quarterback, snap share for backs, receivers and tight ends — with no second map. The table's
**Role** cell prints the latest value, the card's glyph and change (`▲ +34 pts`, `▲ +20`,
`▬ no change`) and the window (`wk 8 vs 7 gms`, `wk 2 only`); the chart's fourth readout, which
printed the generic `snap_share_last3`, prints the same reading as text. It is text rather than
a bar because a change in attempts and a change in share points have no common scale.
The table's `Snap share` and `Weeks since last game` columns are gone: the first was a constant
for a quarter of the board, and the second's one useful reading is the long-absence mark on the
name plus the role window. Both remain in the filtered export, unchanged.

### Decision 3 — momentum on the scan surface, and the window that ended

The board prints the published `add_trend` with its glyph and **always** its span (ADR-089),
and never recomputes the slope. Measured on the live week-2 build's PPR 12-team board, 47 of
the 184 published slopes come from windows that **ended before the latest snapshot** — the feed carried the
player earlier in the week and has not since (T.J. Hockenson: two points on Sep 16, "rising").
The slope is correct under `behavior_trend_v1`; reading it as "interest is accelerating now"
would not be. So a board reading is `measured` only when its newest point is the build's
behaviour snapshot (`ros_build_metadata.behavior.snapshot_at_utc`, else the newest point any
series carries); otherwise it is `ended`, printed muted with `over 10 hours · to Sep 16`, passes
no filter and sorts after every current slope. Treating the silence since as zero would invent a
collapse (ADR-089 Decision 4); treating the old slope as today's would invent a surge. This is a
presentation rule over two published fields, not a change to `behavior_trend_v1`.

Slopes at or past 100/day print in whole transactions with separators (`+72,054/day`) on the
board **and** the card — Sleeper's week-two counts run to six figures — and below that to one
decimal. `verify:board` compares at the precision printed.

### Decision 4 — the next game as a line of context, never a rating

`W3 vs CHI` over `25.5 implied`, `no line yet`, or `bye W9 · no line yet`. The implied team
points are the artifact's own and are sportsbook context read by no model. The column is not
sortable: ordering the board by a sportsbook number would make it the board's loudest claim
about matchups, and there is still no opponent-strength dataset (ADR-088, ADR-091). No cell,
tooltip or sentence says easy, hard, favourable or "Nth vs WR", and a test asserts it.

### Decision 5 — three filters, each one predicate over one reading

`only=role.momentum.surfaced` (canonical order; unknown tokens dropped with a rewrite):

| chip | keeps a row when |
|---|---|
| Role rising | the leading role metric's published `role_change_v1` reads up at the printed precision |
| Momentum rising | the published add slope is positive **and** its window reaches the latest snapshot |
| Surfaced | `outside_tier_board` |

They compose by AND with each other and with position and search. A row without a reading does
not pass and is **not counted as failing**: the status line prints both (`Role rising: 175 ·
150 with no published change, not counted either way`). A chip whose artifact the build did not
publish is disabled, and a link that names it is not applied and says so — an empty board would
read as "nobody's role rose", a claim built out of a missing file. There is no chip that counts
how many signals agree ("hot", "breakout", "3 of 4"): that is a score with the arithmetic hidden.

### Decision 6 — five orderings, and magnitudes only where they share a unit

`value`, `adds`, `net` are unchanged. `momentum` orders current slopes highest first (one unit:
transactions per day), then ended slopes, then every row with none — an unknown is never placed
between a rising and a falling player. `role` is **categorical** — rising, flat, falling, no
reading — and compares the size of a change only when every row on screen is one position; across
positions it orders by ROS rank inside a category. The rule lives in `compareRole`, which checks
position and metric on both rows itself, so a permissive caller still cannot compare "+6
attempts" with "+18 pts". The table's header sort uses the same comparators, and a row without a
reading sorts last in both directions.

### Decision 7 — chart and table, by width

The chart keeps its two tracks; only its fourth readout changed. The table is the richer triage
surface. Below 1280px the team and drop count step aside (the chart draws every drop count);
below 768px the rank and value go too (the chart prints both on every row it draws) and the
player's name is pinned while the readings scroll. Nothing is shrunk into illegibility: signal
cells wrap to a second line instead. Measured: no sideways scroll at 1024, 1280, 1440 or 1600px
on the fixture or the live 507-row board, under three orderings.

### Decision 8 — the filtered export carries a flattened summary, and no line

The 29 existing columns are unchanged in order and meaning. Eighteen are appended —
`role_reading`, `role_metric`, `role_latest_week`, `role_latest`, `role_earlier`,
`role_earlier_games`, `role_change`, `momentum_reading`, `add_trend_per_day`,
`add_trend_span_days`, `add_trend_observations`, `add_trend_snapshots_in_window`,
`add_trend_last_observed_at_utc`, `next_game_reading`, `next_game_week`, `next_game_opponent`,
`next_game_home_away`, `next_game_bye_week_before` — every one a published field, with the
`*_reading` columns naming which absence an empty cell is. **No sportsbook number is exported**:
ADR-091 published the lines with no CSV on purpose, and a filtered export that quietly became one
would reverse that from the browser. No direction column either: the glyph follows the printed
rounding, and the export carries the published change itself. Row order is still the visible
table's. The artifact CSV (`inseason_opportunity.csv`) is untouched.

### Decision 9 — Pick of the Week does not move

`potw_selection_v1` is untouched and reads none of this. `candidates.test.ts` builds every set
under every filter combination × ordering × position and requires identical picks, and asserts
the published records are never mutated (frozen-record run); `verify:board` compares the pick
names with and without `only=role.momentum.surfaced&opportunity=role` on the served page.

### Verification

`verify:board` now checks every Opportunity row and every charted row: the role reading (metric,
value, change, glyph, window), the momentum reading (kind, glyph, slope at printed precision,
span, the ended date), the next game (head and detail for the team the card reads), the three
filters against the artifacts, the momentum and role orderings, and Pick-of-the-Week invariance.
Five source mutations were built and served and all five fail both `verify:board` and vitest:
a reversed role direction (42 gate failures), a missing slope read as zero, another row's next
game (34), an ended slope read as current, and role magnitudes compared across positions. Zero
disagreements on the fixture builds (in-season, no-signals, no-behaviour) and on a real
`build-ros` of live week-2 data **with** the retained behaviour window (507 rows, 4 real picks).

### What the live week-2 board showed (2026-09-22T23:50Z build)

Recorded for a future POTW-v2 design session — observations, not a mandate to tune today's rule:

| observation | players |
|---|---|
| a set-1 pick whose leading role **declined** | QB Brock Purdy (22 attempts, ▼ −12; momentum falling), TE Dalton Kincaid (snap 66%, ▼ −6 pts; momentum falling) |
| an eligible player at the same position with a sharply rising role | QB C.J. Stroud (set 4: 55 attempts, ▲ +17); TE Terrance Ferguson (set 3: ▲ +7 pts, momentum rising); RB Jonah Coleman (set 4: snap ▲ +34 pts, ROS VORP 3.8) |
| rising role and momentum, strong ROS value, **not eligible** (adds under the position's bar) | Patrick Mahomes (▲ +20 attempts, 32,822 adds vs a 107,900 QB bar), Travis Kelce (▲ +14 pts, 18,908 vs 34,073) |
| market momentum and ROS value disagree | Emanuel Wilson (2.58M adds, +265,334/day, snap ▲ +35 pts, ROS VORP −6.6); Devaughn Vele (WR set 4 pick, momentum −371,427/day); Aaron Jones Sr. (snap ▲ +35 pts, ROS VORP 55.2, 0 adds in the latest window, momentum falling) |
| next-game environment differs materially | RB pick Rachaad White vs SEA, 16.8 implied (the board's lowest is 16.75); TE pick Kincaid vs LAC, 28.8; RB set-2 Emmett Johnson @ MIA, 29.0 (the highest) |

### Deliberately not done

- **Opponent strength.** Two games is not a defensive profile; `load_team_stats` is the next data
  expansion, not this one.
- **Expected opportunity / xFP.** The ffopportunity CC-BY-SA decision (ADR-086) is still open.
- **`role_change_v1`'s window.** Unchanged. *Checkpoint:* once weeks 5–6 are complete, compare the
  season-long earlier baseline with a trailing two-to-three-game baseline on the live board and
  ask whether the long baseline is too slow to flag a multi-week takeover (a back who took over
  in week 3 still reads against weeks 1–2 in week 7).
- **The board's `add_count: 0` for a player outside Sleeper's top 100.** Pre-existing: when the
  feed is up, `inseason_opportunity` publishes 0 (with `add_rank: null`) for a player the feed
  did not list, where the series publishes no point. The board now shows "not in feed" beside a
  0; making the day count null is an artifact-contract change for its own session.
- **Two live records with `display_name: "None"`** (`gsis:00-0041326`, `gsis:00-0041436`) in
  `ros_tiers`, `inseason_opportunity` and `player_usage` — an upstream name gap serialised as a
  string. Pre-existing and pipeline-side; recorded, not fixed here.

### Correction, 2026-09-23 — the table fitted on one rasteriser (CI run 35843180505)

The post-merge `ci` run failed `Frontend end-to-end` on one test — `fits the table without a
sideways scroll at 1440px`: the Opportunity table was **8px** wider than its container on CI's
Chromium. `daily-refresh` stayed green because it runs `verify:board`, not the Playwright layout
suite, so production published normally; the defect was a real 8px sideways scroll at 1440px
on that rasteriser.

**Root cause: two defects, the second hiding the first.**

1. *The fit had no margin.* Measured as container width minus the table's `min-content` width,
   the fixture table had **1px** of slack at 1440px, 17px at 1280px and 27px at 1024px on the
   machine it was built on. Signal cells were only allowed to wrap below 1440px, so at 1440 the
   longest unwrapped cell in each column (the surfaced player's name and badge, the role reading)
   set the floor. Eleven columns of glyph-width differences between font rasterisers is more
   than a pixel.
2. *The density rules never applied.* The tighter cell padding and header rules were written as
   `.opp-sheet thead th …` and `.opp-sheet tbody td`, one element weaker than the base
   `table.sheet thead th …` / `table.sheet tbody td` they meant to override, so they lost
   silently. The first ADR-092 build shipped with the base padding and single-line headers.

**Fix.** Wrapping (player badges, a change under its value, a window under its slope, a
two-word heading onto two lines) is allowed at every width — a flex row wraps only when its
column is actually short of room, so wide screens are unchanged — and the density rules are
selected as `table.sheet.opp-sheet …`. Slack is now 251 / 326 / 479 / 575px at 1024 / 1280 /
1440 / 1600px on the fixture, and 241 / 316 / 462 / 558px on the live week-2 board.

**The test asserted the outcome and not the margin, so it passed by luck on one machine.** It
now also requires ≥ 64px of `min-content` slack at 1024, 1280 and 1440px and checks that the
density rules apply (`white-space: normal` on a heading, 8px cell padding). Negative control:
the new assertions fail against the merged CSS on the machine where the old test passed
(1px / 17px / 27px of slack).
