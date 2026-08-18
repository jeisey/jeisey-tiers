# Data Sources, Rights, and Feasibility Gates

**Important:** Sections 1–12 are the original research decisions as of 2026-08-12. **Phase-0 live verification was completed on 2026-08-17; section 13 is the authoritative verified record** and supersedes any earlier statement it contradicts. Machine-readable evidence lives in `docs/source-probes/2026-08-17/report.json`, regenerable with `uv run python scripts/source_probe.py`. Re-verify before each launch: web pages and APIs change.

## 1. Source policy states

Every source is assigned one of:

- `production_allowed` — verified for the intended non-commercial public project and technically stable enough.
- `allowed_optional` — permitted/useful but product must not fail without it.
- `benchmark_only` — may be used for internal model comparison but not serialized to public artifacts.
- `verify_before_use` — promising, but exact endpoint/rights/history must be proved in Phase 0.
- `disabled` — do not access in production.
- `paid_optional` — not required; documents what additional value paid access could unlock.

## 2. Research-backed source matrix

The "initial policy" column below is the pre-verification research position, kept for provenance. **Section 13.1 holds the verified policy that governs implementation.**

| Source | Initial policy | Cost | Intended role | Important facts / caveats |
|---|---|---:|---|---|
| nflverse / nflreadpy | `production_allowed` pending live smoke | Free | historical/current football feature backbone | nflreadpy exposes player stats, rosters, depth charts, draft/combine, IDs, FantasyPros-derived rankings, ffopportunity and more. Majority of nflverse data is broadly CC-BY 4.0; FTN-derived data carries CC-BY-SA obligations. |
| ffopportunity | `production_allowed` pending live smoke | Free | expected opportunity / expected fantasy points features | Models/precomputed expected-points data are CC-BY-SA 4.0; R package code is GPL. Data quantifies average expected points given play situations/opportunities. |
| MyFantasyLeague API / ADP | `verify_before_use` | Free/public developer API historically | primary current/historical market ADP | MFL publicly encourages third-party API use, but Phase 0 must prove the exact 2026 ADP endpoint, filters, historical-year behavior, rate expectations, terms, and fields before dependency. |
| Sleeper API | `production_allowed` pending live smoke | Free, no auth for documented endpoints | current player map, status/injury sanity, optional trend | Official docs expose NFL player map and trending add/drop endpoints; player map need not be fetched more than daily. Trending data requests attribution. |
| FantasyCalc | `allowed_optional` only if exact access method is permitted | Free for non-commercial reuse under current terms | secondary market signal / corroboration | Current terms state FantasyCalc owns its data and permits non-commercial website use subject to policy. Re-check before use and especially before monetization. Do not assume an undocumented API is sanctioned merely because it is reachable. CSV/download or explicitly allowed mechanism preferred. |
| FantasyPros-derived ECR via dynastyprocess/nflreadpy | `benchmark_only` unless rights are re-cleared | Free access path exists | benchmark Boris/ECR-like consensus | nflreadpy can load FantasyPros-derived rankings, but ownership/terms are separate from nflverse code. Never expose raw benchmark data publicly unless current terms clearly permit redistribution. |
| SportsDataIO | `paid_optional` | Commercial agreement | reliable injuries/depth/news/projections/odds | Commercial NFL product provides maintained injuries, depth charts, projections, news, odds and support/SLA. Not necessary for V1. |

## 3. Primary nflverse fields/datasets to investigate

The implementation agent should favor loader functions rather than hardcoded GitHub release URLs where practical.

Candidate loaders include:

- `load_player_stats`
- `load_pbp` only if feature needs justify data volume
- `load_rosters` / player master
- `load_depth_charts`
- `load_combine`
- `load_draft_picks`
- `load_nextgen_stats`
- `load_pfr_advstats` where license/source reliability fits
- `load_snap_counts`
- `load_ff_playerids`
- `load_ff_opportunity`
- `load_ff_rankings` for benchmark-only ECR if approved

### Known update behavior worth designing around

At research time nflverse documents:

- rosters: daily around 7 AM UTC;
- depth charts: daily around 7 AM UTC year-round;
- Next Gen player stats: nightly around 3–5 AM ET in season;
- PFR advanced stats: daily around 7 AM UTC during season;
- player/team stats and PBP: nightly after game days;
- nflverse injury source died after 2024 and had no 2025 feed at the documented time.

This supports a daily pre-draft refresh but makes a second current injury/status source necessary.

> **Phase-0 correction (2026-08-17):** the last bullet is wrong. `load_injuries(2025)` returns 6,068 rows; the loader simply refuses seasons after 2025. The real gap is different and larger: injury rows are weekly in-season reports, so **no** season provides an injury report at a preseason draft anchor. Observed depth-chart refreshes for 2026 land at roughly 07:25–08:25 UTC daily, consistent with the cadence above. See section 13.2, 13.3 and ADR-011.

## 4. ffopportunity usage

Potential feature families:

- expected fantasy points per week/season
- expected rushing/receiving TD opportunity
- actual minus expected fantasy points
- expected points per opportunity
- rolling prior-season opportunity efficiency

Temporal rule: only aggregate prior seasons/weeks that would have been known at the draft-time anchor for the target season.

Do not accidentally use current-season expected points when constructing preseason historical training rows.

## 5. MyFantasyLeague Phase-0 probe

The coding agent must write a small, reproducible `source_probe` rather than validating manually in a browser only.

Verify:

1. exact current ADP export endpoint for 2026;
2. JSON/XML parameter options;
3. league size parameter;
4. scoring parameter(s) or how scoring cohorts are represented;
5. mock vs real draft controls if available;
6. minimum/maximum draft date or time-window controls;
7. player ID field and crosswalk coverage;
8. ADP mean/median and min/max/std/sample-size fields;
9. historical year endpoints for at least 2019–2025;
10. whether historical responses remain reproducible later;
11. documented request/rate expectations;
12. current terms/licensing appropriate to a public non-commercial derived-data site.

Save only small schema fixtures on main. Do not commit a full vendor dataset until rights/storage strategy is documented.

> **Phase-0 result (2026-08-17):** all twelve items were probed by `scripts/source_probe.py`; the answers are in section 13.5. Items to note: there is no standard-deviation field (8), there is no working date-window control (6), the export exposes no `gsis_id` (7), and XML/JSON are both available with JSON selected via `JSON=1` (2). Schema fixtures are committed under `tests/fixtures/source_schemas/`.

### ML feasibility decision

Set `arbitrage_ml_historical_feasible=true` only if the project can construct sufficiently dense, point-in-time market-cost data for multiple historical seasons with stable player identity and scoring context.

A useful minimum target is >= 3 chronological holdout seasons after creating earlier train seasons. If that cannot be met honestly, use deterministic arbitrage baseline mode and begin accumulating daily snapshots for future learned models.

> **Phase-0 decision (2026-08-17): `arbitrage_ml_historical_feasible = false`.** Volume is sufficient but the data is not point-in-time, so baseline mode ships. Evidence and the revisit rule are in section 13.8 and ADR-010.

## 6. Sleeper Phase-0 probe

Verify:

- `players/nfl` or filtered active-player endpoint;
- fields for player ID, full name, team, fantasy positions, active status, injury status/body part/notes if currently exposed;
- update behavior;
- mapping to `ff_playerids`/GSIS;
- trending endpoint attribution if used.

Sleeper data is a current-state supplement, not the historical statistical backbone.

## 7. FantasyCalc gate

Current research finding: FantasyCalc's terms state its data is copyrighted by FantasyCalc and allow other websites to use it for non-commercial purposes under the policy; commercial use requires express permission.

Therefore:

- V1 may use it only if the site remains non-commercial and the Phase-0 agent confirms the exact retrieval mechanism is permitted.
- Prefer a published CSV/download mechanism over reverse-engineering a private endpoint.
- Attribution should be explicit even if the terms do not require a specific string.
- If ads, sponsorship, paid features, affiliate monetization, or commercial licensing are introduced, disable FantasyCalc ingestion until written permission/updated legal decision is recorded.

It must remain optional; MFL/another verified market source should carry the critical arbitrage path.

> **Phase-0 decision (2026-08-17): `disabled` for V1.** `https://fantasycalc.com/terms-of-usage` returns 113,878 bytes of client-rendered HTML containing none of the terms text in the served markup, so the policy cannot be verified programmatically, and no published CSV/download or documented public API was found. The gate above requires a *permitted, documented* mechanism; none exists, so no FantasyCalc access happens at all. `robots.txt` is permissive, but that is not a licence. See ADR-013.

## 8. FantasyPros/ECR gate

The original `fftiers` repository states its data is exclusively FantasyPros and its R implementation clusters average rank using `Mclust`. Our system uses ECR only as a potential benchmark.

Rules:

- no ECR in intrinsic features;
- no ECR required to render the production site;
- no raw ECR public artifact unless rights explicitly permit it;
- benchmark metrics may be published only if that use is allowed and does not leak the underlying proprietary dataset.

If terms are unclear, disable the benchmark and compare against public naive/market baselines instead.

> **Phase-0 decision (2026-08-17): `disabled` pending human terms review.** The data is reachable (`load_ff_rankings(type="draft")` → 5,849 rows), but the dynastyprocess mirror that serves it publishes no licence or terms statement, and `https://www.fantasypros.com/terms-of-use/` returns 215,237 bytes of client-rendered HTML with no terms text in the served markup. That is "unclear", so this section's own rule applies. Consensus comparison for V1 therefore uses the verified public MFL ADP plus naive baselines. Revisit needs a human to read the FantasyPros terms and record the decision here. See ADR-014.

> **Owner decision (2026-08-18): `benchmark_only`.** The project owner manually reviewed the current FantasyPros terms and approved use for this non-commercial project. The registry policy moves `disabled` → `benchmark_only`, and `load_ff_rankings(type="draft")` may be used as an **internal** comparison benchmark. The four rules at the top of this section are unchanged and remain binding: no ECR in intrinsic features, no ECR needed to render the site, **no raw ECR in any public artifact**, and published benchmark metrics only where that publication is itself permitted. Two additions make the boundary machine-checkable — `draftvalue_input` and `public_redistribution` are recorded as forbidden roles, and `redistribution_permitted: false` is explicit. Approval to compare is not approval to republish, and the probe keeps suppressing benchmark-only rows from reports and fixtures. The source also carries `non_commercial_only: true`, so it now sits inside the `docs/SECURITY_LICENSE.md` section 10 boundary alongside Sleeper. See ADR-014 as amended 2026-08-18.

## 9. Paid optional sources

### SportsDataIO

Value unlocked:

- maintained injury feed
- year-round depth charts
- weekly projections baseline
- news
- odds / implied team environments
- SLA/support
- fewer brittle public-source failures

Why not V1:

- recurring commercial cost
- project goal is to prove capability with free/public data
- core modeling can be built from nflverse + a verified market source

### Other paid/proprietary data

PFF-style route/coverage/grade data could add signal, but licensing/redistribution and cost make it inappropriate as a V1 dependency. Add only behind an adapter after a separate rights/ROI decision.

## 10. Source failure hierarchy

### Intrinsic critical

nflverse core historical/current inputs fail or are materially stale:

- **stop intrinsic refresh**;
- do not deploy a new Tier artifact;
- keep last-known-good site.

Optional advanced feature source fails:

- allow fallback only if production model was trained to tolerate its absence or a predeclared missing-value path exists;
- record degradation in metadata.

### Market critical

Primary market ADP fails:

- Tier Board may still be independently refreshed;
- Arbitrage must either remain last-known-good with a stale badge or be disabled for that build;
- do not substitute an unverified source.

Secondary market source fails:

- continue primary market path;
- set warning.

## 11. Source metadata contract

Each ingestion batch records:

```text
source_id
retrieved_at_utc
source_data_as_of_utc (if supplied/derivable)
source_schema_version (internal adapter version)
record_count
content_hash (when practical)
status
warning_codes
license_policy_version
```

## 12. Research references for Phase-0 verification

The source registry contains exact URLs. The most important research pages used to seed this specification are:

- nflreadpy documentation and GitHub README/license
- nflverse data update schedule
- ffopportunity documentation/license
- Sleeper official API docs
- MyFantasyLeague Developer API page / current API docs
- FantasyCalc redraft rankings and Terms of Use
- SportsDataIO NFL developer/workflow pages
- GitHub Actions/Pages official docs

Do not treat this list as a substitute for live Phase-0 validation.

---

## 13. Phase-0 verification record — retrieved 2026-08-17 (authoritative)

Every number and quotation below comes from `docs/source-probes/2026-08-17/report.json`, produced by `scripts/source_probe.py` on a GitHub-hosted runner (`nflreadpy==0.1.5`, `polars==1.43.2`, `requests==2.34.2`, Python 3.12.13). Re-run the probe to regenerate it. Where a claim in sections 1–12 conflicts with this section, this section wins.

### 13.1 Verified policy decisions

| Source | Verified policy | Basis |
|---|---|---|
| nflverse via `nflreadpy` | `production_allowed` | All 30 probed loader calls returned data. Code MIT; data CC-BY-4.0 with FTN subsets CC-BY-SA-4.0. |
| ffopportunity via `load_ff_opportunity` | `production_allowed` | 2019/2024/2025 all return weekly expected-points rows. Data CC-BY-SA-4.0, package code GPL-3. |
| MyFantasyLeague ADP export | `production_allowed` (obligations in 13.5) | `TYPE=adp` works for 2019–2026; published rules permit free reuse "in almost any way" with a forbidden-use list we do not touch. |
| Sleeper API | `production_allowed`, **non-commercial only** | Documented endpoints work; docs state free for non-commercial use, commercial use requires licensing. |
| FantasyCalc | `disabled` for V1 | No documented public API or published download, and the terms page is client-rendered so its text cannot be verified programmatically. See ADR-013. |
| FantasyPros-derived ECR via dynastyprocess | `benchmark_only` (2026-08-18) | Reachable (5,849 rows). Phase 0 disabled it because terms were unread, not because a prohibition was measured; the owner completed the terms review on 2026-08-18 and approved internal benchmark use for this non-commercial project. Redistribution still forbidden. See ADR-014 as amended. |
| SportsDataIO | `paid_optional` (unchanged) | Not probed; no V1 dependency. |

### 13.2 nflverse coverage actually observed

| Loader | Probed seasons → rows |
|---|---|
| `load_players` | 25,040 (gsis master, includes draft/PFR/ESPN/PFF ids) |
| `load_ff_playerids` | 12,472 (`mfl_id` 100%, `gsis_id` 64%, `sleeper_id` 51%, `espn_id` 65%) |
| `load_player_stats(summary_level="reg")` | 2012→1,811; 2019→1,889; 2024→1,997; 2025→2,020 |
| `load_player_stats(summary_level="week")` | 2025→19,422 |
| `load_rosters` | 2012→2,120; 2019→3,114; 2025→3,137; **2026→2,930** |
| `load_rosters_weekly` | 2019→51,632; 2025→46,849 |
| `load_depth_charts` | 2019→36,308; 2024→37,312; **2025→554,215; 2026→442,872** (schema break, see 13.3) |
| `load_snap_counts` | 2019→23,862; 2025→26,612 |
| `load_ff_opportunity(stat_type="weekly")` | 2019→5,633; 2024→6,005; 2025→6,054 |
| `load_injuries` | 2019→5,392; 2024→6,215; **2025→6,068**; 2026 → `ValueError: Season must be between 2009 and 2025` |
| `load_draft_picks` / `load_combine` | 12,927 / 8,968 (all seasons, single file each) |
| `load_nextgen_stats(receiving)` / `load_pfr_advstats(rec, season)` | 2025→1,402 / 531 |
| `load_ftn_charting` | 2025→47,316 (**CC-BY-SA**; avoid unless a feature justifies the share-alike obligation) |
| `load_schedules` | 2026→272 rows, weeks 1–18, `game_type=REG` only |

Season-level `load_player_stats` carries every component the scoring engine needs (`passing_yards`, `passing_tds`, `receptions`, `receiving_yards`, `rushing_tds`, fumbles, 2-point conversions, …), so STD/HALF/PPR can be computed in-house rather than trusting the upstream `fantasy_points` columns.

Downloads come from `github.com/nflverse/nflverse-data/releases/download/`, `github.com/dynastyprocess/data/raw/master/files/`, `github.com/ffverse/ffopportunity/releases/download/` and `github.com/nflverse/espnscrapeR-data/raw/master/data/`. Any egress allowlist must cover all four.

**Two corrections to earlier assumptions.** The nflverse injury feed did *not* die after 2024 — 2025 returns 6,068 rows. But `load_injuries` is capped at 2025 by the installed library and injury rows are weekly in-season reports (weeks 1–22), so **there is no injury report for a preseason draft anchor from nflverse at all**, in any season. That is a different problem from the one the spec anticipated, and it is why ADR-011 exists.

### 13.3 The 2025 depth-chart schema break (Phase-2 critical)

| | ≤ 2024 | 2025 onward |
|---|---|---|
| Grain | one row per team/week/position slot | one row per **timestamped snapshot** |
| Key columns | `season, club_code, week, game_type, depth_team, depth_position, gsis_id, position` | `dt, team, gsis_id, espn_id, pos_grp, pos_abb, pos_rank, pos_slot, player_name` |
| Earliest observation | week 1 (no week 0, no preseason) | 2025-08-03 (2025), 2026-03-22 (2026) |
| Snapshot count | 21–22 weeks | 221 (2025), 150 (2026 to date) |

Consequences the adapter and feature builder must honour:

- Two normalisation paths are required; a single schema assumption will silently produce nulls (ADR-015).
- **2025 onward supports a true point-in-time depth chart**: pick the latest snapshot with `dt <= anchor`. The 2026 series is refreshed daily at roughly 07:25–08:25 UTC; the latest snapshot observed on 2026-08-17 held 3,257 rows across all 32 teams, 924 of them QB/RB/WR/TE with `gsis_id` missing on only 1.4%.
- **2024 and earlier cannot supply a preseason depth rank.** The earliest available row is week 1, which is published *after* a late-August draft and after final roster cuts, so using it as an "anchor" feature would leak. Phase 2 must either derive anchor depth from prior-season usage plus roster status, or declare the week-1 proxy and its leakage risk explicitly in the feature dictionary.

### 13.4 Current-season anchor inputs (2026)

- `load_rosters(2026)`: 2,930 rows, `status` ACT 2,852 / RES 36 / E14 28 / RET 11 / CUT 3. For the 915 QB/RB/WR/TE rows, `gsis_id` is 100% present, `depth_chart_position` 100% present, `sleeper_id` 82% present, `espn_id` 84% present.
- `nflreadpy.get_current_season()` returns **2025** while `get_current_season(roster=True)` returns **2026** and `get_current_week()` returns 22. **Do not derive the draft-target season from `get_current_season()`** — in August it still points at the prior season. Sleeper's `/v1/state/nfl` independently reports `season=2026, season_type="pre", week=2, season_start_date=2026-08-06`, and the pipeline should take the target season from configuration cross-checked against these two.

### 13.5 MyFantasyLeague — verified contract

Endpoint: `https://api.myfantasyleague.com/{YEAR}/export?TYPE=adp&JSON=1`. No authentication. `APIKEY` exists but is only for access-restricted league calls, not this export.

Response: `{"adp": {"version", "encoding", "timestamp", "totalDrafts", "totalPicks", "player": [...]}}`. Each player row carries exactly `id, rank, averagePick, minPick, maxPick, draftsSelectedIn, draftSelPct` — all as strings.

- **There is no standard-deviation field.** `market_snapshot.adp_sd` must stay null; dispersion comes from `minPick`/`maxPick` (`adp_low`/`adp_high`) and sample size from `draftsSelectedIn`.
- `timestamp` is the response generation time, not a data-as-of time. `source_as_of_utc` cannot be recovered for historical years.
- 2026 unfiltered: 367 priced players, `totalDrafts=410`, `averagePick` 2.57–218.41.

Filter behaviour (2026 unless noted):

| Request | Rows | Reading |
|---|---:|---|
| no filters | 367 | baseline |
| `IS_PPR=1` | 370 | honoured |
| `IS_PPR=0` | 229 | honoured; standard scoring is much thinner |
| `FCOUNT=12` | 356 | honoured |
| `FCOUNT=10` | 325 | honoured |
| `FCOUNT=14` | 242 | honoured |
| `IS_PPR=0&FCOUNT=10` | **2** | cohort intersections collapse — see ADR-012 |
| `IS_MOCK=0&IS_KEEPER=N` | 383 (`totalDrafts=101`) | honoured |
| `CUTOFF=5` | 367 | accepted, no effect at this threshold |
| `DAYS=14`, `DAYS=1` | 367, 367 | **ignored** — identical to unfiltered |

Historical years (unfiltered, retrieved 2026-08-17): 2019→445 rows / 15,850 drafts; 2020→442; 2021→397; 2022→391; 2023→416; 2024→413; 2025→362 / 7,185 drafts.

Player database: `TYPE=players&DETAILS=1&JSON=1` → 2,600 records. **No `gsis_id`.** `espn_id` 82.1%, `nfl_id` 3.4%, plus `stats_id`, `stats_global_id`, `sportsdata_id`, `cbs_id`, `rotowire_id`, `rotoworld_id`, `fleaflicker_id`. The export also contains non-player rows (e.g. `id=0151`, `name="Bills, Buffalo"`, `position="TMWR"`) that must be filtered out.

**Published obligations** (quoted from `api.myfantasyleague.com/2026/api_info`, "General Rules and Terms of Service"): access "is provided free to anyone to use in almost any way", with these uses forbidden — "Harvesting league and/or user data", "Looking for loop holes or other ways to cheat or circumvent league rules", "Overloading or disrupting the MFL service", "Collecting user information without their per[mission]". None applies to reading the public ADP aggregate. Additionally:

- "Starting in 2020 we will be monitoring and restricting usage of the API" and clients should "include the User-Agent you chose in the Client Registration on all API requests". **Closed 2026-08-18:** the project owner registered an MFL developer client and provisioned `MFL_API_CLIENT_NAME`, `MFL_API_USERNAME`, `MFL_API_PASSWORD` and `MFL_API_USER_AGENT` as GitHub repository secrets. The adapter reads the *names* from the environment and transmits only the User-Agent; the public ADP export stays unauthenticated, and a missing secret degrades to the descriptive contact User-Agent with an `unregistered_user_agent` warning rather than failing. Official 2026 documentation: `https://www41.myfantasyleague.com/2026/api_info`. See ADR-017.
- Over-limit requests are throttled and "return a 429 'Too Many Requests' HTTP status code" — the adapter must handle 429 with backoff, not retry blindly.
- "our player database is only changed once a day, so your application should request that info no more than once a day" — cache the player export daily.
- `robots.txt` on the API host disallows only `/fflnetdynamic*/` league directories, not `/{YEAR}/export`. `https://www.myfantasyleague.com/terms.html` does not exist (404); the developer page above is the operative statement.

### 13.6 Sleeper — verified contract

- `/v1/state/nfl` → season/week/season_type/season_start_date (see 13.4).
- `/v1/players/nfl` → 12,220 records, **14.6 MB**, `player_id` 100%. Crosswalk: `sportradar_id` 94.7%, `espn_id` 55.1%, `gsis_id` only **31.9%** (31.4% among active QB/RB/WR/TE). Therefore **join nflverse → Sleeper on `sleeper_id` (82% present on current skill rosters), never Sleeper → gsis on Sleeper's own field.**
- Status/injury fields present and usable: `status`, `injury_status` (populated on 5.1% of rows, i.e. only currently affected players), `injury_body_part`, `injury_notes`, `injury_start_date`, `practice_participation`, `practice_description`, `depth_chart_order`, `depth_chart_position`, `team_changed_at`, `search_rank`.
- **Data hygiene:** observed `gsis_id` values carry a leading space (e.g. `" 00-0035057"`). The identity layer must trim and validate id formats and fail closed on malformed values.
- `/v1/players/nfl/trending/add?lookback_hours=24&limit=25` → 25 `{player_id, count}` rows.
- Published terms (quoted from `docs.sleeper.com`): "The Sleeper API is a read-only HTTP API that is free to use for non-commercial purposes… For commercial use of the Sleeper API, please reach out to us directly to discuss licensing. No API Token is necessary". Rate guidance: "stay under 1000 API calls per minute, otherwise, you risk being IP-blocked". Attribution: "Please give attribution to Sleeper you are using our trending data." `robots.txt` contains no active restrictions.
- **This puts Sleeper inside the non-commercial boundary of `docs/SECURITY_LICENSE.md` section 10**, alongside FantasyCalc. Monetising the site requires re-clearing Sleeper, not just FantasyCalc.

### 13.7 Market → canonical identity is proven without name matching

Measured on the 367 priced 2026 players, using two independent id bridges:

| Metric | Result |
|---|---|
| `mfl_id` → `load_ff_playerids()` → `gsis_id` | 350 / 367 |
| MFL `espn_id` → `load_rosters(2026).espn_id` → `gsis_id` | 331 / 367 |
| resolved by either bridge | 350 / 367 = **95.4%** |
| **QB/RB/WR/TE only** | **287 / 287 = 100%** |
| top-100 by market rank | 100 / 100 |
| bridges both resolve and **agree** | 331 |
| bridges both resolve and **disagree** | **0** |
| unresolved rows | 17, all MFL `position="Def"` team units, none modelled in V1 |

This satisfies the PRD section 21 identity criterion for the market join and means ADR-005 is achievable as specified. Two independent bridges with zero disagreement also give Phase 1 a cheap cross-check: resolve both ways, accept on agreement, and fail closed when they differ. Phase 1 implements exactly that (ADR-019). Note the dependency asymmetry — `mfl_id` exists only in the dynastyprocess crosswalk (which publishes no licence), whereas the `espn_id` path is entirely nflverse-native, so the `espn_id` bridge is the more durable primary and the crosswalk is the higher-coverage secondary.

### 13.8 Arbitrage ML feasibility: **no** — launch in baseline mode

Historical volume is not the binding constraint; point-in-time reconstruction is.

- Seven historical seasons each price 362–445 players, which is enough rows.
- But the export returns a **season-long aggregate recomputed at request time**, and the day-window filter is ignored: `DAYS=30` against 2019 returned byte-identical coverage to the unfiltered request (445 rows, `totalDrafts=15850`). Draft-type filters do still work on historical years (`IS_MOCK=0&IS_KEEPER=N` → 384 rows / 6,885 drafts), but excluding mocks says nothing about *when* a price was set.
- So a 2019 "market cost" includes drafts held during and after the 2019 season, by which time the season's outcomes were partly known. Training a learned surplus target on that cost would embed target-season information in the feature the model is supposed to be exploiting.

Therefore `arbitrage_ml_historical_feasible = false` and V1 ships the deterministic fair-rank-vs-ADP baseline, exactly as ADR-003 anticipated. Revisit only from **our own** append-only daily snapshots (ADR-006): at least three draft seasons of retained point-in-time snapshots are needed before an out-of-time promotion gate can be honest.

### 13.9 Attribution strings to ship in the UI methodology panel

- Player, roster, depth-chart, stat, draft and combine data from **nflverse** (`nflreadpy`, MIT; data broadly CC-BY-4.0, FTN-derived subsets CC-BY-SA-4.0).
- Expected fantasy points from **ffopportunity** (ffverse), expected-points data **CC-BY-SA-4.0** — derived artifacts inherit share-alike obligations.
- Market ADP from **MyFantasyLeague.com** public developer API.
- Current player status/injury context from the **Sleeper** API (non-commercial use).
