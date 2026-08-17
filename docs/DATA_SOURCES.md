# Data Sources, Rights, and Feasibility Gates

**Important:** This document contains research decisions as of 2026-08-12, but production use still requires the Phase-0 coding agent to verify live endpoint behavior and re-check current terms. Web pages and APIs change.

## 1. Source policy states

Every source is assigned one of:

- `production_allowed` — verified for the intended non-commercial public project and technically stable enough.
- `allowed_optional` — permitted/useful but product must not fail without it.
- `benchmark_only` — may be used for internal model comparison but not serialized to public artifacts.
- `verify_before_use` — promising, but exact endpoint/rights/history must be proved in Phase 0.
- `disabled` — do not access in production.
- `paid_optional` — not required; documents what additional value paid access could unlock.

## 2. Research-backed source matrix

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

### ML feasibility decision

Set `arbitrage_ml_historical_feasible=true` only if the project can construct sufficiently dense, point-in-time market-cost data for multiple historical seasons with stable player identity and scoring context.

A useful minimum target is >= 3 chronological holdout seasons after creating earlier train seasons. If that cannot be met honestly, use deterministic arbitrage baseline mode and begin accumulating daily snapshots for future learned models.

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

## 8. FantasyPros/ECR gate

The original `fftiers` repository states its data is exclusively FantasyPros and its R implementation clusters average rank using `Mclust`. Our system uses ECR only as a potential benchmark.

Rules:

- no ECR in intrinsic features;
- no ECR required to render the production site;
- no raw ECR public artifact unless rights explicitly permit it;
- benchmark metrics may be published only if that use is allowed and does not leak the underlying proprietary dataset.

If terms are unclear, disable the benchmark and compare against public naive/market baselines instead.

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
