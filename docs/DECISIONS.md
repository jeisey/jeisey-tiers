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
