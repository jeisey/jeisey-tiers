# Phase-10 source measurements — 2026-09-02

Evidence for the Phase-10 source dispositions. Every number below was measured on a GitHub
runner, because the development sandbox's egress policy denies all four vendor hosts
(ADR-009, ADR-053). Nothing here was carried forward from an earlier phase without being
re-measured, and nothing was inferred from documentation.

| Run | Scope | Workflow run |
|---|---|---|
| 1 | FFC, FantasyPros, Sleeper | [33642792347](https://github.com/jeisey/jeisey-tiers/actions/runs/33642792347) |
| 2 | FantasyPros — is the 10-row cap a page size? | [33643152957](https://github.com/jeisey/jeisey-tiers/actions/runs/33643152957) |
| 3 | FantasyPros — per-position depth, scoring axis, ADP search | [33643545952](https://github.com/jeisey/jeisey-tiers/actions/runs/33643545952) |
| 4 | FantasyPros — identity bridges | [33643980189](https://github.com/jeisey/jeisey-tiers/actions/runs/33643980189) |

Scripts: `scripts/probe_ffc.py`, `scripts/probe_fantasypros.py`,
`scripts/probe_sleeper_trending.py`. Workflow: `.github/workflows/source-probe-phase10.yml`.
No payload was retained, no player rows were printed beyond redacted schema descriptions,
and the FantasyPros key was never emitted — every printed line passes a guard that suppresses
any line containing it.

---

## 1. Fantasy Football Calculator — **production ADP source**

`GET https://fantasyfootballcalculator.com/api/v1/adp/{format}?teams={n}&year=2026&position=all`

### Schema, measured

```text
status: "Success"
meta:    type, teams, rounds, total_drafts, start_date, end_date
players[]: player_id (int)  name (str)  position (str)  team (str)
           adp (float)  adp_formatted (str)  times_drafted (int)
           high (int)   low (int)   stdev (float)   bye (int)
```

Every field is 100% populated on the measured cohort. `player_id` is present on 221/221 rows
and fully distinct — an FFC-internal integer, stable, and a bridge to nothing outside FFC.

### `teams` is still accepted and ignored — ADR-056 reproduced

Per-player `adp` and `times_drafted` compared across 8/10/12/14-team requests:

| Format | 8 vs 10 | 8 vs 12 | 8 vs 14 | Shared rows |
|---|---|---|---|---|
| standard | byte-identical | byte-identical | byte-identical | 221 |
| ppr | byte-identical | byte-identical | byte-identical | 264 |
| half-ppr | byte-identical | byte-identical | byte-identical | 233 |

**Zero rows differ in any comparison.** ADR-056's finding stands unchanged, so no successor
ADR is written and `league_size` is null on every FFC quote. The roadmap anticipated both
outcomes; this is the one where nothing moves.

### Scoring cohorts, depth and volume

| Format | Rows | Core QB/RB/WR/TE | Deepest ADP | `meta.total_drafts` |
|---|---|---|---|---|
| standard | 221 | 186 | 172.6 | 1,794 |
| half-ppr | 233 | — | 188.6 | 3,142 |
| ppr | 264 | — | 201.1 | 8,007 |

Position mix on `standard`: `{DEF: 17, PK: 18, QB: 24, RB: 60, TE: 20, WR: 82}`.

`times_drafted` ranges 5 → 460 (standard), 5 → 3,482 (ppr), 5 → 848 (half-ppr).

**FFC's population is smaller than 300.** The deepest ADP is 201.1 and the largest cohort is
264 rows including kickers and defences. "FFC top 300" is therefore the whole of FFC, which
is what the Phase-10 surface rule uses rather than a literal 300th row that does not exist.

### Aggregation window — rolling, and now measured

```text
meta.start_date = '2026-08-26'
meta.end_date   = '2026-09-02'
```

Exactly seven days. MyFantasyLeague aggregates the season to date (Phase 0 measured `DAYS`
ignored and historical requests returning season aggregates). The two are different
measurements and the product labels them separately.

### Dispersion

`stdev` populated 221/221, range 0.60 → 31.90. `high` and `low` are also published — extreme
order statistics, not a standard deviation. They occupy different columns
(`adp_sd` vs `min_pick`/`max_pick`) and the adapter orders `high`/`low` numerically rather
than trusting which of the two the vendor means by "high".

### CSV transport

`/adp/csv/{fmt}.csv` returned `content-type: text/html` and a `<pre>` header row: not a
usable CSV path. The JSON path takes an explicit `year` and is the reproducible one.

### Identity linkage — the 90% gate, measured against live rows

Run with the production rule `phase10_linkage_v1` (`ffdraft.identity.linkage`), against the
canonical registry (1,034 players):

```text
relevant core rows: 186
accepted:           186 (100.000%)
quarantined:        0
gate:               >= 90% -> PASS
top-300 unresolved: 0
quarantine reasons: {}
```

Name-only diagnostics for comparison: 204 matched / 17 unmatched over all 221 rows including
kickers and defences, which is why the linkage runs over core positions only.

---

## 2. FantasyPros — **ECR only, and the key cannot serve a market**

This is the finding that changes what Phase 10 can ship, so it is recorded in full.

### The endpoint that works

```text
GET https://api.fantasypros.com/public/v2/json/nfl/2026/consensus-rankings
    ?position={QB|RB|WR|TE|FLX|ALL}&scoring={STD|HALF|PPR}&type=draft&week=0
x-api-key: <secret>
```

`position=ALL` returns `400 {"message":"Invalid Position","parameter":"position",
"valid_format":"QB, RB, WR, TE, K, OP, FLX, DST, IDP, DL, LB, DB, TK, TQB, TRB, TWR, TTE,
TOL, HC, P"}` **unless** `type=draft&week=0` accompany it.

Row schema:

```text
cbs_player_id  player_bye_week  player_ecr_delta  player_eligibility  player_filename
player_id      player_name      player_owned_avg  player_owned_espn   player_owned_yahoo
player_page_url  player_position_id  player_positions  player_short_name
player_team_id  player_yahoo_id  player_yahoo_positions  pos_rank
rank_ave  rank_ecr  rank_max  rank_min  rank_std  sportsdata_id  tier
```

Envelope: `sport, type ("Draft Half PPR"), ranking_type_name, year, week, position_id,
scoring, filters (expert id list), count, total_experts, last_updated, limit,
public_api_limited, tier`.

### The response is capped at ten rows, and the cap is the tier

Eight widening attempts, all on `position=ALL&scoring=HALF`:

| Parameter | Rows returned | Envelope |
|---|---|---|
| `limit=300` | 10 | `count=1777 limit=10 public_api_limited=true tier=free` |
| `limit=100` | 10 | identical |
| `limit=25` | 10 | identical |
| `offset=10` | 10 | identical, **same first player** |
| `start=10` | 10 | identical, same first player |
| `page=2` | 10 | identical, same first player |
| `max_results=300` | 10 | identical |
| `ranks=1-300` | 10 | identical |

No parameter widens the window and no parameter advances it. The first row is
`'Arizona Cardinals'` in all eight. The vendor names the reason itself:
`public_api_limited: true`, `tier: "free"`.

Per-position calls do widen the *population*, but only to the top ten of each:

| Position | Rows | `count` (full population) | `total_experts` | `last_updated` |
|---|---|---|---|---|
| WR | 10 | 407 | 109 | `9/02` |
| TE | 10 | 225 | 93 | `9/02` |

**Distinct players reachable across QB/RB/WR/TE: 40.**

No rate-limit, quota or tier headers are returned; the envelope is the only account.

### There is no ADP behind this key

* `GET /json/nfl/2026/adp` → `403 {"message":"Missing Authentication Token"}` — the path does
  not exist.
* `type=adp` on `consensus-rankings` → `200`, with the **ECR row shape** and
  `adp-like row fields: NONE`.
* `/json/nfl/2026/rankings` (a different endpoint) returns a player *catalogue* whose `rank`
  field is a dict of availability counts —
  `ADP: {'BB-HALF': {'ALL': 531, 'DST': 32}}`,
  `ECR: {'PPR': {'ALL': 460}, 'HALF': {'ALL': 449}, 'DYN': {'ALL': 337}, ...}` — not
  per-player ranking values.

A `fantasypros_adp` column would have nothing behind it. It is not emitted.

### The ECR itself is real and correctly scoped

`rank_ecr` runs 1..10 with real names, `rank_ave`/`rank_min`/`rank_max`/`rank_std` carry the
expert dispersion, and the scoring axis genuinely reorders:

```text
scoring=STD   RB: Jahmyr Gibbs, Bijan Robinson, Jonathan Taylor, James Cook III
scoring=HALF  RB: Jahmyr Gibbs, Bijan Robinson, Jonathan Taylor, Christian McCaffrey
scoring=PPR   RB: Jahmyr Gibbs, Bijan Robinson, Christian McCaffrey, Jonathan Taylor
HALF vs PPR: different order
HALF vs STD: different order
```

`last_updated` is `"9/02"` — a month and a day, with no year and no time. It is retained as
evidence and never promoted to `source_as_of_utc`.

### Identity — two id bridges, no fuzzy linkage needed

Measured over the 40 reachable core-position rows:

| Field | Populated | Distinct | Resolves through the registry |
|---|---|---|---|
| `player_id` | 40/40 | 40 | vendor-internal, no namespace |
| `player_yahoo_id` | 40/40 | 40 | **36/40** via `IdNamespace.YAHOO` |
| `sportsdata_id` | 40/40 | 40 | **40/40** via `IdNamespace.SPORTRADAR` |
| `cbs_player_id` | 40/40 | 40 | not indexed by this project |

FantasyPros joins **by id**, with the same two-bridge cross-check MyFantasyLeague uses. It
needs none of the fuzzy name linkage FFC needs.

### Request accounting

Runs 1-4 issued 18 + 34 + 45 + 4 = 101 requests across four separate days' worth of probing
in one day, each run self-limited and paced at one request per second. The production
adapter's own budget is 50/day with a 12-request call plan (4 positions x 3 scoring cohorts).

---

## 3. Sleeper — **player map re-measured, trending add/drop verified**

### Player map

```text
GET https://api.sleeper.app/v1/players/nfl
status 200   bytes = 14,651,318 (13.97 MiB)   records = 12,226   elapsed ~1.2s
```

Phase 0 recorded 12,220 records / 14,640,182 bytes. The payload has moved by 11 KB and six
records in a year, which is why the roadmap treats size as an operational fact rather than a
schema contract. The **once-per-day maximum** is the rule that matters and is unchanged.

Identity coverage over the 4,041 QB/RB/WR/TE records:

| Field | Populated | Share |
|---|---|---|
| `player_id` | 4,041 | 1.000 |
| `sportradar_id` | 3,831 | 0.948 |
| `yahoo_id` | 2,258 | 0.559 |
| `espn_id` | 2,210 | 0.547 |
| `gsis_id` | 1,259 | 0.312 |
| `search_rank` | 3,934 | 0.974 |

`search_rank` is present and is **not** ADP. Roadmap 10.1.4 forbids using it as pseudo-ADP;
it is recorded only so its presence is on the record.

### Trending add and drop

```text
GET /v1/players/nfl/trending/{add|drop}?lookback_hours={h}&limit={n}
```

Both return a **bare JSON list** of `{count: int, player_id: str}`. No envelope, no
timestamp, no metadata of any kind — which is exactly why the retained snapshot has to record
the request parameters, or the counts are uninterpretable later.

* `add`, 24h/25: 25 rows, counts 17,793 → 259,065.
* `drop`, 24h/25: 25 rows, counts 13,815 → 63,840.
* `limit` is honoured exactly: 5 → 5 rows, 25 → 25, 100 → 100.
* `lookback_hours` is honoured: 6h vs 24h share 24 of 25 ids; 6h vs 72h share 22 of 25.

### League state

```text
season 2026, week 1, season_type regular, season_start_date 2026-09-09,
previous_season 2025, season_has_scores true
```

---

## 4. What these measurements decide

| Question | Answer | Where it is written down |
|---|---|---|
| Is FFC a production ADP source? | **Yes** — three exact scoring cohorts, real dispersion, a published window, 100% identity linkage | ADR-062, `docs/DATA_SOURCES.md` 14.1 |
| Does FFC differentiate league size? | **No**, still. ADR-056 stands | ADR-062 |
| Can FantasyPros supply ADP? | **No.** The path 403s and no response carries an ADP field | ADR-064 |
| Can FantasyPros supply a complete ECR? | **No.** Ten rows per response, forty players total, tier-capped | ADR-064 |
| Does FantasyPros need fuzzy linkage? | **No.** `sportsdata_id` resolves 40/40, `player_yahoo_id` 36/40 | ADR-064 |
| Is the Sleeper player map still once-a-day? | **Yes**, and it now weighs 13.97 MiB | `docs/DATA_SOURCES.md` 14.3 |
| Are Sleeper's trending parameters honoured? | **Yes**, both `limit` and `lookback_hours` | ADR-062 |
