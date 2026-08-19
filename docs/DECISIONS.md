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

## ADR-014 — FantasyPros-derived ECR benchmark is disabled pending a human terms review

**Status:** Accepted (2026-08-17)

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
