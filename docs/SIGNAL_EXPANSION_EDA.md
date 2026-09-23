# Signal Expansion EDA — 2026-09-19

> **Framing corrected by the owner, 2026-09-22 (ADR-091). Read this before anything below.**
> This audit was written as preparation for a future sealed-season retrain, and Part 4 ordered the
> backlog around that. That is not the objective. **The objective of signal expansion is better
> fantasy decisions in the current season** — is this player worth a waiver claim this week, did
> his role change before his box score did, is his scoring built on volume or on touchdowns, who
> does he play next. The rest-of-season model is one signal among several, not the thing being
> improved, and most of what this audit ranks can reach a reader as *published, observed context*
> without touching either model.
>
> What that changed, concretely:
>
> - **Built (ADR-091):** `player_usage.json` (`usage_signals_v1`, `role_change_v1`) — weekly
>   snap, target, carry and air-yards share, pass and rush attempts, fantasy points per preset,
>   a change per role metric, points from touchdowns, and pass EPA per dropback; and
>   `team_matchups.json` (`next_game_v1`) — each team's next game, rest, roof, and the posted
>   spread and total as context only. A position-aware card (Part 2b fixed) and an evidence row on
>   Pick of the Week. Pick of the Week's selection rule is unchanged.
> - **Decided:** the Vegas question (§2a.3) for **reading 3 only** — sportsbook lines are
>   published context and read by no model. Readings 1 and 2 remain open and are not pre-empted.
> - **Still open:** the CC-BY-SA publication question (§2a.2) — nothing published derives from
>   ffopportunity; ESPN QBR (#18) and FTN (#19) are out of scope; `load_pbp` (#20) not built.
> - **Unchanged:** Part 4's table is still an accurate statement of what a *model* may consume
>   and when. It no longer orders the product backlog.
>
> Items below are annotated **[built]**, **[partly built]** or **[deferred]** with the reason, in
> place, so the measurements stay readable as they were taken.

**Status (as of 2026-09-19): exploratory, with one item since built.** The audit added no source, wrote no adapter
and touched no model. Its purpose is to hand a future build session a *measured* starting
position instead of a search, and — where the repository's own rules say a decision is required
before work begins — to name the decision rather than pre-empt it.

**One finding was acted on the same week.** Part 1's — that the retained Sleeper add/drop window
had never been read — turned out to need no decision at all, and shipped as **ADR-089**
(`behavior_trend_v1`, `behavior_trend_series.json`, the Pick of the Week momentum strip). That
section is marked accordingly and records what the build actually cost. Everything else here is
still analysis, and the three decisions named in Part 4 are still unmade.

Read `AGENTS.md` first. Three of its rules decide most of what follows and are cited by number
throughout: §5 (a source marked `verify_before_use` is not a production dependency until the
check is done), §8 (the intrinsic model's forbidden features, and the instruction to **stop and
document** when a feature is *arguably* a market-expectation proxy), and §18 (a code change that
moves a documented contract updates the documentation in the same change).

---

## 0. Evidence base, and what could not be checked

| tier of evidence | what it is | used for |
|---|---|---|
| **Live, this session** | GitHub release asset listings for `nflverse/nflverse-data`, fetched 2026-09-19; nflreadr data dictionaries fetched from `raw.githubusercontent.com`; production workflow logs read through the GitHub API | whether a feed exists **today**, when it was last written, and what its columns mean |
| **Recorded probe** | `docs/source-probes/2026-08-31/report.json` — 80 findings from a GitHub runner, with per-column dtypes, null fractions, row counts, coverage windows and sample rows | exact column inventories for loaders this repository has never used |
| **Repository** | adapters, feature dictionaries, schemas, frontend, `config/source-registry.yaml` | what is actually consumed, as opposed to what is downloaded |

**What could not be checked, and why it is recorded rather than guessed.** This sandbox answers
`403` to `CONNECT` for every vendor host (ADR-009), so no loader was executed and no endpoint was
called from here. `curl` to `api.sleeper.app`, `api.myfantasyleague.com`,
`fantasyfootballcalculator.com` and `github.com` release downloads all failed at the proxy;
`nflreadr.nflverse.com`, `docs.sleeper.com` and `site.api.espn.com` are blocked to the fetch tool
as well. Everything below is therefore marked with one of three validation states:

- **VALIDATED** — checked live this session, or recorded by a runner probe with columns and counts.
- **DOCUMENTED** — the publisher's own dictionary says so; the data itself was not read.
- **UNVERIFIED** — needs a runner probe. The exact probe is named each time.

ADR-053's rule applies: *egress denial is not a reason to guess.*

### Repository state this EDA was taken against

`HEAD` = `8584983` = `origin/main`. Last production refresh: run 53, 2026-09-18, **success**,
deployed. Build `2026-intrinsic-cb-hurdle-v1-20260918T161715Z`; 4,500 tier rows, 3,195
projections, 1,993 arbitrage rows, 540 player-status rows; quality gate **PASS**, 0 critical,
12 warnings, all of them the standing published limitations. `verify:board` reported
`defaultBoard: "ros"`, `publishedInSeason: true`, `potwCardsChecked: 4`, `failures: []`.

**"Rest of season — through week 1" is correct, not a defect.** `ros_source_freshness_v1` builds
week *N* only when upstream carries every scheduled club for weeks 1..*N*. The first 2026 kickoff
was `2026-09-10T00:20:00Z`; week 1 completed the night of Monday 2026-09-14; week 2 runs
2026-09-17 to 2026-09-21 and is **in progress** as this is written. The next opportunity for the
label to move is the Tuesday post-week slot, `"40 12 * * 2"` — 2026-09-22 — and if upstream is
complete by then it will read *through week 2*. Nothing needs fixing; the gate is doing its job.

---

# Part 1 — How Sleeper data is fetched and stored

**Short answer: daily point-in-time snapshots, yes. Trends built from them — no, until this
week. The data was always there; the read was not. Built as ADR-089 on 2026-09-19.**

## 1.1 The three Sleeper reads, and where each one lands

| read | endpoint | when | retained where | consumed by |
|---|---|---|---|---|
| player map | `GET /v1/players/nfl` | every refresh, once/day (14.6 MB, 12,225 records) | `status/sleeper/{season}/{key}/status.normalized.json.gz` | `player_status.json` — annotation only (ADR-043) |
| trending adds | `GET /v1/players/nfl/trending/add?lookback_hours=24&limit=100` | refresh, **only when `mode == in_season`** | `behavior/sleeper/{season}/{key}/behavior.normalized.json.gz` | Opportunity Board, Pick of the Week |
| trending drops | `GET /v1/players/nfl/trending/drop?…` | same snapshot key as adds | same file | same |
| season state | `GET /v1/state/nfl` | cross-check only | not retained | anchor sanity |

`{key}` is `YYYY-MM-DDTHH-MM-SSZ`, zero-padded so lexical order is chronological order. The store
is the private `jeisey/jeisey-tiers-market-data@market-data` (ADR-049) — append-only,
content-addressed, `mtime=0` gzip so an unchanged re-capture hashes identically instead of
conflicting (`ffdraft/retention/store.py`).

Adds and drops are captured under **one** snapshot key and a capture missing either half is
refused outright, because "a drop count is only interpretable against the add count from the same
moment and the same window" (`ffdraft/behavior/capture.py`).

## 1.2 Are we creating daily snapshots? — Yes, and they are accumulating

**VALIDATED.** Run 53's capture job committed, among 16 files:

```
behavior/sleeper/2026/2026-09-18T16-16-17Z/behavior.normalized.json.gz
behavior/sleeper/2026/2026-09-18T16-16-17Z/manifest.json
status/sleeper/2026/2026-09-18T16-16-38Z/status.normalized.json.gz
status/sleeper/2026/2026-09-18T16-16-38Z/manifest.json
```

`daily-refresh` has completed successfully on **every calendar day since the season opened** —
runs 37 (09-10), 38 (09-11), 40 (09-12), 41 (09-13), 42 (09-14), 44–47 (09-15), 48–50 (09-16),
51 (09-17), 52–53 (09-18). Two runs failed (39 and 43) and both were covered by a later successful
run the same day. So the behaviour store holds **at least nine days** of add/drop observations,
and more on multi-run days, since each run appends its own key. The exact count is not directly
observable from this sandbox because the store is a private repository.

Two properties of the capture worth carrying forward:

- The behaviour step is `continue-on-error: true` **and** gated on `mode == 'in_season'`. It is an
  enrichment by construction: its failure empties three columns and cannot touch a ROS number.
- The capture job **commits once, at the end, after `validate-market-history` re-hashes the whole
  store.** A failure anywhere in the job therefore drops that run's snapshots entirely, which is
  why 2026-09-15's behaviour snapshot came from a later run rather than from run 43.

## 1.3 Are we using them to create trends? — We are now. Until 2026-09-19 we were not.

**The finding, in one sentence: nothing was stopping it, and nobody had written the read.**

The data was being saved. The store held nine days of observations. There was exactly one
reader and it asked for the newest file:

```
src/ffdraft/pipeline/ros.py      read_behavior_capture(...)
src/ffdraft/behavior/capture.py  resolved = key or behavior_store.latest_key(source_id, season)
```

`latest_key` returns the last directory. `SnapshotStore.keys()` — the function that returns
*all* of them, oldest first — was on the same class, and the market side had been using it to
draw an ADP chart since Phase 5. Behaviour had none of the four pieces the market had:

| | market | behaviour, before | behaviour, now |
|---|---|---|---|
| retained daily | since 2026-08-20 | since 2026-09-10 | unchanged |
| trailing-window reader | `market/history.py` | **none** | `behavior/history.py` |
| frozen slope rule | `phase5_trend_v1` | **none** | `behavior_trend_v1` |
| published series | `market_trend_series.json` | **none** | `behavior_trend_series.json` |
| chart | `MarketTrend.tsx` | **none** | `BehaviorSparkline.tsx` |

**This was built on 2026-09-19 (ADR-089).** The rest of this section is the analysis that led
to it, kept because two of its conclusions are load-bearing and one of them was wrong.

## 1.4 What it took, and the one judgement inside it

The mechanical part was as small as it looks: read a window instead of a key, compute a slope,
publish the points, draw them. No new source, no new licence question, no model change.

The one judgement was **how short a window may state a direction**, and the first draft of this
document got it wrong by assuming the market rule should be copied. `phase5_trend_v1` refuses
to estimate a slope below three observation days spanning three days. That is right for an
ADP — it moves slowly, and a two-point line through one is mostly noise. It is wrong for an add
count, which is a count of transactions over 24 hours, moves in hours, and describes a waiver
edge that is gone by the time a three-day bar admits it.

So `behavior_trend_v1` states a direction from **two** observations, and pays for the shorter
bar with a required field rather than with a threshold: `span_days` travels with every
direction, so `+320/day` is always printed beside `over 2 days`. A validator check, a
pre-deploy gate check and a component test each assert that independently.

**Two things this document first called "wrinkles" and one of them was inflation.**

- **Right, and it shipped:** the feed is a top-100 list, so a day the player was outside it
  carries an unknown count rather than a zero. That is a real distinction — filling those days
  with zero would draw a collapse in interest out of a player leaving a leaderboard — and it is
  now three fields (`snapshots_in_window`, `observations`, `request_limit`) and a gap mark.
- **Overstated:** that absolute counts scale with how many leagues exist. True across seasons,
  irrelevant inside a seven-day window, and it should not have been raised beside the first.

---

# Part 2a — Fields we already download and do not use

The pipeline fetches six nflverse tables and a 14.6 MB Sleeper payload every day. Measured against
each adapter's `required_source_columns` and the recorded Phase-0 schemas:

| file already fetched daily | columns available | consumed | **unconsumed** |
|---|---:|---:|---:|
| `load_player_stats(summary_level="week")` | 150 | 32 | **118** |
| `load_ff_opportunity(stat_type="weekly")` | 159 | 12 | **147** |
| `load_schedules()` | 46 | 8 | **38** |
| `load_draft_picks()` | 36 | 9 | **27** |
| `load_snap_counts()` | 16 | 9 | **7** |
| `load_combine()` | 18 | 12 | **6** |
| Sleeper `/v1/players/nfl` | 53 | 14 | **39** |

Not every unconsumed column is a missed signal — most of `player_stats` is kicking, punting and
IDP, which this product does not rank. What follows is the subset that *is* signal, with the rule
each one collides with.

## 2a.1 `player_stats` weekly — the efficiency and role block, free, already on disk

**VALIDATED** (recorded schema, 2024 and 2025 seasons, 150 columns).

| unconsumed column | what it is | maps to the launchpad list |
|---|---|---|
| `target_share`, `air_yards_share`, `wopr` | nflverse's own shares and the `1.5×TS + 0.7×AYS` composite | Tier A #3, Tier B #15, #16 |
| `racr`, `pacr` | receiving/passing air-conversion ratios | Tier B efficiency |
| `passing_epa`, `rushing_epa`, `receiving_epa` | per-player EPA | Tier B #24 |
| `passing_cpoe` | completion % over expected | Tier B #25 |
| `receiving_yards_after_catch`, `passing_yards_after_catch` | YAC | Tier C #31 (the raw half) |
| `passing_first_downs`, `rushing_first_downs`, `receiving_first_downs` | first downs generated | Tier B #21 (the numerator) |
| `receiving_10/16/20/40`, `rushing_10/12/20/40`, `passing_10/16/20/40` | explosive-play counts by yardage bucket | volatility / ceiling |
| `sacks_suffered`, `sack_yards_lost` | sacks taken | Tier C #27 (the denominator-free half) |

**Note the duplication.** The ROS feature set already computes `target_share_to_date` from player
and team targets in the same weekly rows — deliberately, so "the ratio has one provenance"
(`docs/ROS_FEATURE_DICTIONARY.md`). nflverse's `target_share` is a *different* number with a
different denominator. Adopting it would be a change to a computed feature, not a free addition,
and the existing one is better documented. **Do not swap them.** `air_yards_share` and `wopr` have
no local equivalent and are genuine additions.

> **[partly built, ADR-091]** Air-yards share is published — computed here from
> `receiving_air_yards` over the team's, the same pooled way as target share, because nflverse's
> `air_yards_share` was measured up to 9 points away from that on the 2026 rows (a different
> denominator). `passing_epa` and `sacks_suffered` are read into **pass EPA per dropback**.
> WOPR is **deferred**: a fixed-weight blend of two shares the card already shows separately.
> RACR, PACR, CPOE, YAC, first downs and the explosive-play buckets are **deferred** — one
> efficiency reading per position to start.

## 2a.2 `ff_opportunity` — 147 unconsumed columns, and the whole `_team` denominator block

**VALIDATED** (recorded schema, 159 columns).

The adapter reads seven quantities: `total_fantasy_points_exp`, the three per-phase `_exp`
variants, `receptions_exp`, `total_fantasy_points` and `total_fantasy_points_diff`. What it leaves
behind:

- the `*_exp` family for **every** component — yards, touchdowns, first downs, two-point
  conversions, interceptions, per phase;
- the `*_diff` family — actual minus expected — for the same;
- **the entire `*_team` block**: `total_fantasy_points_exp_team`, `rec_yards_gained_exp_team`,
  `pass_attempt_team`, `rec_attempt_team`, `rush_attempt_team`, `rec_air_yards_team` and ~60 more.

That last block is the launchpad's Tier A #11 — *team xFP share / weighted opportunity share* —
and it is already in a file this project downloads daily. `player_xfp / team_xfp` is a division of
two columns of one row. **This is the single cheapest high-value quantity in the whole audit.**

**The rule it collides with.** ffopportunity's expected-points data is **CC-BY-SA 4.0**
(`docs/SECURITY_LICENSE.md` §8, `config/source-registry.yaml` `share_alike_obligation: true`).
ADR-086 and `SESSION_STATE.md` backlog item 0 already record the exact question: a *prediction made
from* licensed data is one thing; a *derived per-player expected-points figure on a public
artifact* is much closer to redistributing it, and the share-alike obligation would bind what this
site publishes. The project already carries `expected_points_per_game_to_date` and
`points_over_expected_per_game_to_date` inside `ros_core_v1` and publishes neither, for this
reason.

**So the licence question gates publication, not use.** Using these columns as model inputs raises
no new licence question that `ros_core_v1` has not already answered. Publishing them does. That
distinction runs through the whole of Part 3 and is restated in Part 4.

> **[deferred, ADR-091 Decision 4]** xFP share and points over expected are the readings a
> waiver card would most like to show, and neither is published: the ADR-086 decision is still
> open. Touchdown share (sustainability) and air-yards share (unrealised downfield opportunity)
> were taken as the next-best signals, and the build metadata's `expected_points_statement`
> says why the expected-points reading is absent.

## 2a.3 `load_schedules` — Vegas lines, weather and rest, in a file fetched every day

**VALIDATED** (recorded schema, 46 columns, 2026 season, 272 rows).

The schedule adapter's own docstring is exact about why it reads eight columns:

> "Only the calendar columns are normalized. The loader also publishes scores, betting lines and
> weather; **none of that is preseason-known**, and none of it is needed to answer 'when does week
> 1 kick off'."

That reasoning is correct for the preseason draft anchor and **does not transfer to the in-season
product**, which is the thing that did not exist when it was written. Unconsumed:

| column group | columns | launchpad rank |
|---|---|---|
| **market** | `spread_line`, `total_line`, `away_moneyline`, `home_moneyline`, `away_spread_odds`, `home_spread_odds`, `over_odds`, `under_odds` | **Tier A #7** — the highest-ranked free item on the list |
| weather | `temp`, `wind`, `roof`, `surface` | Tier D #44 |
| rest / context | `away_rest`, `home_rest`, `div_game`, `weekday`, `location` | Tier D #45 |
| outcome | `away_score`, `home_score`, `result`, `total`, `overtime` | — (an outcome; leakage by construction for the week it describes) |
| crosswalk ids | `pfr`, `pff`, `espn`, `ftn`, `gsis`, `old_game_id`, `nfl_detail_id` | game-level joins to FTN/PFR |
| people | `away_qb_id`, `home_qb_id`, `away_coach`, `home_coach`, `referee` | starting-QB context |

**STOP — this is the decision AGENTS.md §8 demands, and it must be taken before any code.** A game
total and a spread are *sportsbook* quantities. §8's forbidden list names "sportsbook/fantasy
market rank intended as a proxy for crowd expectation" and then says: *"If a feature is arguably a
market expectation proxy, stop and document the decision before adding it."* A team implied total
is arguably exactly that. Three readings are defensible and the project must pick one **in an ADR,
before it has seen a result**, the way `ffdraft.modeling.rules` was frozen before Phase 4:

1. **Forbidden in the intrinsic/ROS model, allowed in arbitrage.** The cleanest reading of PRD §11.1
   and the one that preserves the invariant with no argument. Vegas is market information; the
   arbitrage pipeline may consume market information; the intrinsic pipeline may not.
2. **Allowed, because it prices *teams* and not *this player's draft cost*.** Defensible, and the
   thing that makes it defensible is that the circularity §8 exists to prevent — market → intrinsic
   → arbitrage-gap → market — does not close through a game total. It is also the reading that
   would make the model materially better, on the launchpad's own evidence.
3. **Allowed as published context only, never as a model input.** A matchup panel that says "DEN
   implied 26.5" beside a ROS row, computing nothing. No firewall question at all, because no
   feature exists.

Reading 3 is available *today* and costs no sealed season (see Part 4). Readings 1 and 2 are a
modelling decision with a sealed-season cost. **Weather, rest and `div_game` are not market data
and raise none of this** — they are football facts published before kickoff, and they sit under
reading 3 or under an ordinary feature addition.

One practical caveat, **UNVERIFIED**: whether `spread_line`/`total_line` are populated for
*future* games in the live 2026 file, or only backfilled for played ones. A forward-looking
matchup panel needs the former. Probe: `load_schedules()` on a runner, filter `season == 2026 &
week > completed_week`, count non-null `total_line`.

> **[answered and built, 2026-09-22, ADR-091]** Populated ahead of play: at week 2, `spread_line`
> and `total_line` are posted for **weeks 3–4** (about two weeks out); rest and roof for every
> future game; `temp` and `wind` are **null for every unplayed game**, so weather is not
> published. `spread_line` is positive for a home favourite (31 of 31 lined games agree with the
> moneyline favourite). **Reading 3 was taken**: `team_matchups.json` prints the spread, total
> and implied points as context; no model reads them, and `ffdraft.quality.forbidden` now
> refuses sportsbook tokens as feature names. `div_game` and the moneylines/odds are not
> published. Details: `docs/DATA_SOURCES.md` §18.

## 2a.4 Sleeper's player map — 39 unconsumed fields

**VALIDATED** (recorded schema, 53 fields, 12,225 records). Worth noting, none worth much:

- `news_updated` (epoch ms of last news touch) and `team_changed_at` — two timestamps that could
  give "something changed for this player recently" without any editorial content. Cheap, and
  genuinely novel relative to anything else in the stack.
- `age`, `years_exp`, `birth_date`, `height`, `weight`, `college` — all already available from
  nflverse with better coverage and a canonical key. No reason to take Sleeper's.
- `search_rank` — **not ADP** and the registry says so explicitly. Leave it alone.
- `kalshi_id`, `oddsjam_id`, `stats_id`, `swish_id`, `rotoworld_id`, `pandascore_id`, `opta_id` —
  more id bridges, none needed; `espn_id` and `mfl_id` already carry the market join.
- `player_owned_avg`-equivalent: **does not exist.** ADR-088's finding stands and this audit
  re-confirms it against the recorded schema — Sleeper publishes no ownership field anywhere.

---

# Part 2b — Position-specific metrics

**Confirmed, and it is worse than "noise": the cohort reading ranks the noise.**

> **[fixed, ADR-091]** Position now decides which role metrics lead, in one place
> (`ROLE_METRICS_BY_POSITION`, `web/src/data/signals.ts`): QB pass and rush attempts; RB snap,
> carry and target share; WR snap, target and air-yards share; TE snap and target share. A
> quarterback's card and cohort rows are points per game, EPA per dropback and points from TDs,
> and Pick of the Week no longer states a quarterback's snap share as a reason. The readings come
> from `player_usage.json` (weekly rows and snap counts), not from newly published `ros_core_v1`
> columns: the card needed a week-by-week series the feature table does not hold, and building
> it beside the model rather than out of it keeps the model's contract untouched. The
> Opportunity table's snap-share column was left unchanged by ADR-091 — a column is one quantity
> for every row, and a reader filtering to quarterbacks sees the constant for what it is.
>
> **Superseded 2026-09-23 (ADR-092).** The column is now **Role**: the position's leading
> measure from the same map (pass attempts for a QB), with the published `role_change_v1`
> change and window, beside Add momentum and Next game, and three one-reading filters. The
> table below is the pre-ADR-091 inventory and is kept as the record it was.

## 2b.1 What is actually shown today, per surface

There is **no position-conditional metric selection anywhere in the frontend.** Every occurrence
of a position in `web/src/` is a filter chip, a colour token, a label or a cohort *population* —
never a decision about *which metric to show*.

| surface | usage columns shown | position-aware? |
|---|---|---|
| Opportunity table (`OpportunityTable.tsx`) | `Adds`, `Drops`, `Net adds`, **`Snap share`**, `Weeks since last game` | no |
| ROS table (`RosTable.tsx`) | no usage columns at all | n/a |
| Player card, `03 In-season usage` (`PlayerDetail.tsx`) | `Games played`, `Fantasy points`, `Points per game`, `Weeks since last game`, **`Snap share`**, **`Target share`** | no |
| Player card cohort strip (`CohortStrip`) | `Points per game`, **`Snap share`**, **`Target share`**, each ranked among the same position's published rows | population only |
| Pick of the Week card (`PotwView.tsx`) | `Projected rate`, **`Snap share`**, **`Target share`**, `Rest-of-season rank` | no |

## 2b.2 Why a QB's two shares are structurally empty

Both quantities are computed for every position with no gating — `grep` for a position literal in
`src/ffdraft/ros/features.py` returns nothing but `position_to_date` carried forward:

- `snap_pct_last3` = mean share of team **offensive** snaps. A full-time starting quarterback is on
  the field for essentially every offensive snap, so the value is ~1.00 and renders **100%**.
- `target_share_last3` = player targets ÷ team targets. A quarterback is thrown to on trick plays
  and otherwise never, so the value is ~0.00 and renders **0%**.

Neither carries information *within* the position. Two consequences:

1. **The card spends two of its six in-season tiles on constants** for a quarter of the board.
2. **The cohort strip then ranks the constants.** `buildRosCohortContext` filters the board to the
   row's own position and ranks the value inside it, so a quarterback's card reads something like
   *Target share 0% — 1st of 7 QBs*, where the ordering among a column of zeros is decided by
   floating-point dust. ADR-086 added the cohort strip precisely because "a number with no scale is
   not a reading"; on these two rows it supplies a scale to a number that has no content, which is
   the same defect one turn further out.

**The model is not affected.** `intrinsic-ros-v1` fits **12 group boosters** keyed
`{position}-{scoring_preset}`, so a quarterback's model never sees another position's target-share
distribution and a constant column is simply a feature with no split gain. This is a presentation
defect, not a modelling one — which is good news, because presentation changes carry no
sealed-season cost (Part 4).

## 2b.3 What the published artifacts could already support, per position

`inseason_opportunity_record` carries only `snap_share_last3` and `target_share_last3` as role
columns. But `ros_core_v1` **already computes**, at every cutoff, for every player:

`carry_share_to_date` · `pass_attempts_per_game_to_date` · `touches_per_game_to_date` ·
`targets_per_game_to_date` · `carries_per_game_to_date` · `air_yards_per_game_to_date` ·
`yards_per_target_to_date` · `yards_per_carry_to_date` · `catch_rate_to_date` ·
`points_per_opportunity_to_date` · `td_per_opportunity_to_date` ·
`expected_points_per_game_to_date` · `points_over_expected_per_game_to_date` ·
`team_pass_rate_to_date` · `team_plays_per_game_to_date` · `team_points_per_game_to_date` ·
`snap_pct_trend` · `target_share_trend` · `ppg_trend`

A position-aware card could be built from that list alone, with **no new source**:

| position | the two or three role readings that mean something | all present in `ros_core_v1` |
|---|---|---|
| **QB** | `pass_attempts_per_game_to_date`, `carries_per_game_to_date` (designed rushing is the QB fantasy separator — launchpad Tier B #13), `team_pass_rate_to_date` | yes |
| **RB** | `snap_pct_last3`, `carry_share_to_date`, `targets_per_game_to_date` | yes |
| **WR** | `target_share_last3`, `air_yards_per_game_to_date`, `snap_pct_last3` | yes |
| **TE** | `target_share_last3`, `snap_pct_last3`, `catch_rate_to_date` | yes |

Two of those are genuinely the *same* tile with a position-dependent source, which keeps the card's
grid shape fixed: a "role share" slot (snap share for RB/WR/TE, pass attempts per game for QB) and
a "usage" slot (target share for WR/TE, carry share for RB, designed rushes for QB).

**Three constraints any fix must respect.** They are load-bearing and each was paid for:

1. **ADR-086: a cohort reading is a description of an artifact, not a new quantity.** A rank among
   the published rows of one artifact is arithmetic over those rows, which is what makes it legal
   under AGENTS.md §11. The moment a card computes something the artifact does not carry, it stops
   being a description.
2. **AGENTS.md §10 / ADR-088: never blend unlike units into one score.** The temptation with a
   per-position tile set is a per-position composite. There is no shared scale between an air-yard
   count and a carry share; averaging them would produce the most confident-looking number on the
   page. ADR-088 refused exactly this for the "lucky meter" and the refusal should hold.
3. **ADR-085: `TierBoard` is generic and deliberately lossy.** It takes a `BoardMark` and a
   `BoardAxis` and never learns which board it is drawing, because ADR-071 forbids the preseason
   and rest-of-season quantities meeting. A position-aware card is a *card* change; it must not
   teach the chart what position it is looking at.

**Scope.** Publishing additional `ros_core_v1` columns on `inseason_opportunity` is a data-contract
change under AGENTS.md §18 (schema, validator, CSV, TypeScript contract, goldens,
`verify-real-build.mjs`). `expected_points_per_game_to_date` and
`points_over_expected_per_game_to_date` additionally carry the CC-BY-SA question from §2a.2 —
which is why they are listed separately in the ranking below. The other seventeen do not.

---

# Part 3 — Audit of free public sources

## 3.1 Method

The installed `nflreadpy` exposes **25 loaders** (`dir(nflreadpy)`, recorded by the Phase-0 probe).
This project uses **10**. Everything in the launchpad's Tier A–D that is marked *free* resolves to
one of the 15 unused loaders, to an unconsumed column of a used one, or to a derivation over the
two. There was no free source of consequence *outside* nflverse: the one non-nflverse candidate
the audit surfaced (a commercial aggregator with a free request tier) fails ADR-013's standard —
convenient access is not sanction, and an undocumented or resold feed is not a licence.

Live asset checks were run against `nflverse/nflverse-data` releases on 2026-09-19 to establish
that each candidate feed is **alive for 2026 and updating in season**, which is the property that
decides whether it can serve an in-season product at all.

## 3.2 Live feed status — VALIDATED 2026-09-19

| release | 2026 asset | last written | in-season cadence |
|---|---|---|---|
| `injuries` | `injuries_2026.parquet` | **2026-09-18** | daily |
| `espn_data` | `qbr_week_level.parquet`, `qbr_season_level.parquet` | **2026-09-18T13:15Z** | daily |
| `nextgen_stats` | `ngs_passing/receiving/rushing.parquet` (all seasons, one file each) | **2026-09-18T12:00Z** | daily |
| `pfr_advstats` | `advstats_week_{pass,rush,rec,def}_2026.parquet` | **2026-09-17** | weekly |
| `ftn_charting` | `ftn_charting_2026.parquet` | **2026-09-18T15:48Z** | daily |
| `weekly_rosters` | `roster_weekly_2026.parquet` | **2026-09-18T12:15Z** | daily |
| `pbp` | `play_by_play_2026.parquet` (1.37 MB vs ~19.5 MB full season) | **2026-09-18T13:38Z** | daily |
| `pbp_participation` | **none — stops at 2025**, itself last written 2026-02-10 | — | **dead for 2026** |

**Two of these overturn something the repository currently records.**

- **[corrected 2026-09-22]** `config/source-registry.yaml`'s known issue `injuries_in_season_only` said `load_injuries`
  "refuses seasons after 2025". That was true when probed on 2026-08-31 and is **false today** —
  the 2026 asset exists and was rewritten yesterday. The `loader_error` the probe recorded was a
  preseason 404 for a file that had not been published yet, which is exactly the case ADR-083
  deliberately does not retry. **This is documentation drift under AGENTS.md §18** and should be
  corrected whether or not anything is built on it.
- `pbp_participation` — the source of personnel groupings and box counts in most public analysis —
  **has no 2026 file and is not updating.** Anything needing defenders-in-box for the current
  season must use FTN (live) or NGS rushing (live), not participation.

## 3.3 The ranked inventory

Ranking criterion: **value added over what this project already has**, discounted by acquisition
cost (identity, licence, payload, point-in-time risk) — not raw predictive value in the abstract.
"Publish" means it can reach an artifact; "model" means it can become a feature.

### Band 1 — already downloaded; no new source, no new licence

| # | quantity | where it already is | cost | publish | model |
|---:|---|---|---|---|---|
| **1** | **Team xFP share / weighted opportunity share** | `ff_opportunity` `*_team` block, 147 unconsumed columns | one division | CC-BY-SA question (§2a.2) | no new question |
| **2** | **Per-position role tiles** (carry share, pass attempts/G, air yards/G, catch rate, the three `_trend` columns) — **[built differently, ADR-091]**: a weekly role series and `role_change_v1` in `player_usage.json`, from the weekly rows | `ros_core_v1`, 19 computed and unpublished | schema + contract | yes | already features |
| **3** | **Air-yards share, WOPR, RACR, PACR, EPA, CPOE, YAC, first downs, explosive-play buckets** — **[partly built]**: air-yards share, pass EPA per dropback | `player_stats` weekly, 118 unconsumed columns | adapter column additions | yes | sealed season |
| ~~4~~ | ~~**Behaviour trend series** (Part 1)~~ — **done 2026-09-19, ADR-089** | `behavior/` store | one module, one schema, one chart | shipped | never — behaviour gates, it does not value |
| **5** | **Weather, rest differential, divisional game** — **[partly built]**: rest and roof; weather has no value before kickoff | `load_schedules`, 38 unconsumed columns | adapter column additions | yes | sealed season |
| **6** | **Team implied total / spread** — **[built as reading 3, ADR-091]** | `load_schedules` | **ADR required first** (AGENTS.md §8, §2a.3) | reading 3 only | reading 1 or 2 |
| 7 | Defensive snap share, ST snap share | `load_snap_counts`, 7 unconsumed | trivial | yes | low value here |
| 8 | `news_updated`, `team_changed_at` | Sleeper player map | trivial | annotation only | never (ADR-043/044) |

### Band 2 — a new nflverse loader, licence-clean, live for 2026

| # | loader | what it gives that nothing here has | identity | validation |
|---:|---|---|---|---|
| **9** | **`load_injuries`** | weekly `report_status`, `report_primary_injury`, `practice_status`, `practice_primary_injury` — the thing ADR-070 named as the model's largest measured weakness | **`gsis_id`, null fraction 0.0000** — canonical key, perfect coverage | VALIDATED (16 cols, 6,068 rows for 2025, weeks 1–22; 2026 asset live) |
| **10** | **`load_nextgen_stats`** | receiving: `avg_separation`, `avg_cushion`, `avg_yac_above_expectation`, `percent_share_of_intended_air_yards`. rushing: `rush_yards_over_expected_per_att`, `percent_attempts_gte_eight_defenders`, `efficiency`, `avg_time_to_los`. passing: `avg_time_to_throw`, `aggressiveness`, `completion_percentage_above_expectation`, `avg_air_yards_to_sticks` | **`player_gsis_id`, null 0.0000** | VALIDATED receiving (probe, 23 cols, 1,402 rows, weeks 0–23 where week 0 = season aggregate); passing/rushing fields DOCUMENTED from the nflreadr dictionary, columns UNVERIFIED |
| **11** | **`load_pfr_advstats(stat_type="pass")`** | `times_pressured`, `pressure_pct`, `times_blitzed`, `times_hurried`, `times_hit`, `pocket_time`, `bad_throw_pct`, `on_tgt_pct`, `drop_pct`, `pa_pass_att`, `rpo_*` — pass protection and pressure, at QB level | `pfr_id` — **the project already carries a PFR bridge at 0.977 coverage** (snap counts) | DOCUMENTED (nflreadr dictionary, 28 fields, fetched live); weekly 2026 asset VALIDATED alive |
| **12** | **`load_rosters_weekly`** | a **point-in-time** weekly `status` + `depth_chart_position` per player per week, back to 2002 | full id block incl. `gsis_id` (null 0.0004) | VALIDATED (probe, 36 cols, 46,849 rows for 2025; 2026 asset live) |
| **13** | **`load_pfr_advstats(stat_type="rush"/"def")`** | the closest free proxies to run blocking (yards before contact per attempt) and D-line pressure generated | `pfr_id` | **UNVERIFIED** — columns are whatever PFR's HTML table carries, cleaned by `janitor::clean_names()`; nflreadr documents only the passing table |
| **14** | **`load_team_stats`** | team-week `passing_epa`, `rushing_epa`, `passing_cpoe`, first downs, YAC, and the full defensive block — **opponent-quality and pace without touching play-by-play** | `team` + `opponent_team` | DOCUMENTED (`dictionary_team_stats.json`, fetched live) |
| **15** | **`load_teams`** | 36 rows of team colours, logos, conference, division | `team_abbr` | VALIDATED (probe, 16 cols) — pure frontend value |
| 16 | `load_contracts` | OverTheCap `apy_cap_pct`, `guaranteed`, `inflated_apy` — a team-investment proxy for role | **`gsis_id`** | DOCUMENTED (dictionary fetched live) |
| 17 | `load_trades` | in-season trades, which move opportunity before a roster file does | — | not probed |

### Band 3 — real signal, real obligation

| # | source | what it gives | the obligation |
|---:|---|---|---|
| **18** | **ESPN QBR** (`espn_data` release: `qbr_week_level`) | `qbr_total`, `qbr_raw`, `pts_added`, `epa_total`, `qb_plays`, `rank`, `qualified` — the user's explicit QBR ask, weekly, updated 2026-09-18. Keyed on **ESPN player id**, which ADR-087 measured at **99.0% coverage on active rows** — it joins by id with zero linkage work | **ESPN is `disabled` as a data source in the registry**, and `docs/SECURITY_LICENSE.md` §8 says so in terms: "No ESPN data is used… ESPN stays `disabled` as a *data* source; that is a separate question and its answer is unchanged." Arriving through nflverse does not change whose data it is — the same reasoning ADR-014 applied to FantasyPros via dynastyprocess ("convenient access through nflverse tooling does not transfer rights"). **This needs an owner rights decision, exactly like the headshots did.** Note `nflreadpy` 0.1.5 exposes no `load_espn_qbr`; the asset would be fetched directly through `NflverseDownloader`. |
| **19** | **`load_ftn_charting`** | `read_thrown` — **first-read share, the launchpad's Tier A #4, and free** (0=primary, 1=second, 2=third+, CHK=checkdown, DES=designed, SD=scramble). Plus `n_defense_box`, `n_blitzers`, `n_pass_rushers`, `is_play_action`, `is_rpo`, `is_motion`, `is_screen_pass`, `is_catchable_ball`, `is_contested_ball`, `is_drop`, `is_created_reception` | **CC-BY-SA 4.0** — the one nflverse loader with share-alike, open since Phase 2 and listed as backlog item 8. **And a second cost the licence discussion usually hides: FTN is keyed by `nflverse_play_id` and carries no player id.** Turning `read_thrown` into a per-receiver first-read share requires `load_pbp` joined to it. History starts at **2022** — four seasons. |
| **20** | **`load_pbp`** | the spine under most of Tier A–C: designed-target share, red-zone and inside-10 opportunity, end-zone target share, situation-neutral pass rate, pace, RB high-value opportunities, and the join key FTN needs | CC-BY 4.0, no rights problem. The cost is **volume and time**: ~19.5 MB per completed season × 13 training seasons, plus a live 2026 file. `docs/DATA_SOURCES.md` §3 already says "only if feature needs justify data volume", and the daily refresh's build job currently takes ~3.5 minutes for `build-current` and 5.5 for `build-ros`. |
| 21 | `load_ff_rankings` | ECR, `sd`, `best`/`worst`, `rank_delta` — and **`player_owned_avg`, null fraction 0.0000**: the rostered percentage ADR-088 went looking for | **`benchmark_only` (ADR-014).** May not reach a public artifact whatever key we hold. This audit *confirms ADR-088's finding against the recorded schema*: the field exists and is fully populated; the block is a rights block, not a data gap. `player_owned_espn` and `player_owned_yahoo` are 100% null anyway. |

### Band 4 — asked for, and not available free

| ask | verdict |
|---|---|
| **O-line grades / pass-block win rate / run-block win rate** | **No free, licence-clean, structured source exists.** ESPN's win rates are derived from NGS tracking and published only as editorial articles (`espn.com/nfl/story/...`), with no documented API; `site.api.espn.com` is not reachable from here to check further, and ESPN is `disabled` regardless. PFF is a paid subscription. The honest free substitutes are #11 (`pressure_pct`, `times_pressured`, `pocket_time` — pressure *allowed*, at QB level not line level) and #13 (yards before contact per attempt — UNVERIFIED). |
| **D-line grades** | Same. Free substitutes: `load_pfr_advstats(stat_type="def")` (#13, UNVERIFIED), `load_team_stats` `def_sacks`/`def_qb_hits` (#14), FTN `n_pass_rushers`/`n_blitzers` (#19). |
| **Coverage-shell splits (Cover 1/2/3/4/6)** | Paid only (SIS, Fantasy Points). No free equivalent. The launchpad's own note is right that sample sizes collapse quickly. |
| **Routes run / TPRR / YPRR / 1D-per-route** | Paid only (PFF, Fantasy Points). There is no free route-participation denominator. This is the single largest genuine gap between this product and a paid one, and no amount of nflverse work closes it. |
| **Strength of schedule by position** | Not a source — a **derivation**. `load_schedules` (opponent per week, already fetched) + `load_team_stats` (opponent defensive EPA and points allowed, #14) is the whole recipe. `docs/UX_SPEC.md` already records the absence: Pick of the Week replaced a "matchup vs IND" mock-up readout because "there is no opponent or schedule-strength artifact". |
| **Missed tackles forced / yards after contact** | Partially free via PFR advstats (`brk_tkl`, `yac`, `ybc` — VALIDATED in the receiving table); full coverage is PFF. |

## 3.4 Cross-cutting acquisition costs

**Identity is mostly solved, which is unusual.** Every Band-2 candidate joins on a key this
project already holds and already fails closed on: `gsis_id` for injuries, NGS, contracts and
weekly rosters; `pfr_id` for PFR advstats, already bridged at 0.977; ESPN id for QBR, already
computed and validated at 99.0% on active rows. **The only candidate with an identity problem is
FTN, and its problem is that it has no player at all** — it is play-keyed. Nothing here needs the
name-matching resolver, which is the usual cost of a new source and is absent from this list.

**Point-in-time is the real open question, and it is different per source.** ADR-070 named the
four things a source must produce before it can be a feature: a recorded schema, a measured
historical point-in-time coverage rate, a capture path in the daily refresh, and a fail-closed
check. Against that bar:

| source | recorded schema | point-in-time measured | capture path | fail-closed |
|---|---|---|---|---|
| `load_injuries` | **yes** (`tests/fixtures/source_schemas/nflverse_injuries_2025.schema.json`) | **no — this is the open question** | no | no |
| NGS | no (probe columns only) | no | no | no |
| PFR advstats | no | no | no | no |
| weekly rosters | no (probe columns only) | no | no | no |
| QBR | no | no | no | no |

The injury feed is one of four conditions away rather than four, which is worth stating precisely:
its schema is recorded, and the 2026 file is live and daily. **What nobody has established is
whether the week-6 row reflects what was known in week 6, or what was known afterwards.** That is
a runner probe, not a modelling question, and it is the same question ADR-070 asked. A concrete
version of it: fetch `injuries_2026.parquet` on two consecutive days a week apart and diff the
rows for a completed week. If historical weeks are immutable once written, the feed is
point-in-time by construction and ADR-070's second condition falls.

**Payload budget.** Band 1 costs nothing — the bytes are already downloaded. Band 2 adds
roughly: injuries ~21 KB/season, NGS three single files, PFR four small weekly files, weekly
rosters ~1 MB/season, QBR two small files. **Band 3's `load_pbp` is the outlier at ~19.5 MB per
season**, and it is the one item on the list that would materially change the daily refresh's
shape. The nflverse cache key is per-UTC-day with no `restore-keys`, deliberately, so a new large
download is paid once per day rather than per job.

---

# Part 4 — The constraint that orders all of this

> **[superseded as an ordering, 2026-09-22]** The table below still states correctly what a
> *model* may consume and when. It is no longer how the backlog is ordered: the owner set the
> objective as current-season decisions, and published context — which this Part already says
> needs no sealed season — is where that work lives. ADR-091 is the first slice of it.

**Any new *model feature* is gated on a sealed season that does not exist yet. Any new *published
context* is not.** This is the single most important thing for a follow-up session to internalise,
because it changes the order of the backlog completely.

ADR-078 draws the line explicitly:

| a refit is | a methodology change is |
|---|---|
| the same architecture, parameters, calibration, composition and seed rule | any edit to any of those |
| a wider *training window* of already-permitted seasons | **a wider *feature set***, a new target, a new fallback |
| checkable: the configuration hash is unchanged | the configuration hash moves |
| carries **no** performance claim | **needs a fresh sealed season** |

And ADR-077, on the rest-of-season model: *"Any future change to `RC1`'s outputs invalidates
[the 2025 out-of-time result] and needs a fresh sealed season."* The 2025 holdout is **spent** for
both models — once for `intrinsic-cb-hurdle-v1` (ADR-036, 2026-08-19) and once for
`intrinsic-ros-v1` (ADR-075/077, 2026-09-04). `SESSION_STATE.md` records the consequence for
injuries already: ADR-044 calls historical injury features "a 2027 intrinsic-refresh candidate"
because "the 2025 holdout is spent, so there is nothing to promote them against."

**The next sealed season is 2026, and it does not complete until January 2027.**

So the work splits cleanly, and the split is not the one the launchpad's ranking implies:

### Available now — no sealed season required

- Publishing `ros_core_v1` columns the model already uses (Part 2b.3, Band 1 #2). The model does
  not change; the artifact gains columns it already had internally.
- The per-position card (Part 2b). Presentation only.
- The behaviour trend series (Part 1, Band 1 #4). Behaviour never enters a model by construction.
- A matchup / SoS panel derived from `load_schedules` + `load_team_stats` (#14), published as
  context and computing no player value (Band 1 #6, reading 3).
- Weather and rest as published context (Band 1 #5).
- Team colours (#15) and the injury-feed documentation-drift fix (§3.2).

Each of these is an AGENTS.md §18 data-contract change — schema, validator, CSV, TypeScript
contract, goldens, cross-artifact check, `verify-real-build.mjs` — and none is a model change.

### Blocked until a fresh sealed season (≈ January 2027)

Everything that would enter `ros_core_v1` or `intrinsic_core_v1`: the injury feature ADR-070
wants, NGS separation and RYOE, PFR pressure, EPA/CPOE, air-yards share, WOPR, xFP share as a
*feature*, Vegas totals under reading 1 or 2, FTN first-read share.

**This is not a reason to wait.** It is a reason to spend the intervening months doing the thing
ADR-070 actually asked for — recording schemas, measuring point-in-time coverage, building capture
paths and fail-closed checks — so that when a sealed season *does* exist, the features are ready to
be evaluated instead of starting from a probe. The same logic that made Phase 10 retain Sleeper
behaviour with nothing consuming it (*"a feed first captured in week 3 can only describe week 3
onward"*) applies here with more force: an injury or NGS capture started today gives a 2027 refit
a point-in-time history that a 2027 session cannot reconstruct.

### Decisions to take before code, not during it

1. **The Vegas firewall question** (§2a.3). AGENTS.md §8 requires it in writing, before a result
   exists. Three readings are laid out above; pick one in an ADR. **Reading 3 taken for
   published context (ADR-091); readings 1 and 2 remain undecided.**
2. **The CC-BY-SA publication question** (§2a.2). Already recorded twice as backlog items 0 and 8
   and now blocking three separate items. It is one question — *does publishing a derived
   per-player figure from CC-BY-SA data bind this site's output?* — and answering it once unblocks
   xFP share, points-over-expected and FTN together.
3. **The ESPN QBR rights question** (#18). An owner decision of the same kind as the headshots, and
   the registry entry for ESPN is the thing that would move.
4. **Whether `load_pbp` earns its volume** (#20). Nothing above it in the ranking needs it; several
   things below it are impossible without it. Decide it once rather than per-feature.

---

## Part 5 — Suggested sequencing

Ordered by value per unit of risk, respecting everything above. This is a recommendation, not a
plan, and the phase-gate discipline in `docs/IMPLEMENTATION_PLAN.md` still applies.

| | work | why here | gate |
|---|---|---|---|
| 1 | Correct the `injuries_in_season_only` registry note **[done 2026-09-22]**; probe `load_injuries` on a runner for 2026 and for point-in-time immutability **[not done]** | AGENTS.md §18 drift, and it is the cheapest step toward the model's largest measured weakness | none — a probe and a doc fix |
| 2 | Per-position card tiles **[done, ADR-091 — from the weekly rows, not `ros_core_v1` columns]** | fixes a live defect the owner found, no new source, no model change | schema + contract |
| ~~3~~ | ~~Behaviour trend series, slope on its own frozen rule~~ **done (ADR-089)** | nine days were already retained and unread | shipped: `behavior_trend_v1`, frozen before its evidence |
| 4 | Decide the three rights/firewall questions in ADRs | they block six separate items and cost nothing to answer | ADR |
| 5 | Matchup / SoS panel from schedules + `load_team_stats` **[next game done, ADR-091, from schedules alone; opponent strength deferred — two games is not a defensive profile]** | the product has no opponent artifact at all and the UX spec already records the hole | new loader + schema |
| 6 | Capture paths and fail-closed checks for injuries, NGS and PFR advstats — **retained, consumed by nothing** | ADR-070's four conditions, built in the order Phase 10 used for Sleeper behaviour | registry + capture |
| 7 | After the 2026 season completes: evaluate the accumulated features against a fresh sealed season | the only honest way any of Band 2 becomes a model input | ADR-077 / ADR-078 |

---

## Appendix — probes a runner should run

These are the checks this sandbox could not make. Each answers a question named above.

```bash
# §3.2 — is the injury feed live and does it back-fill, or is it point-in-time?
uv run python -c "import nflreadpy as n; f=n.load_injuries([2026]); print(f.shape, f.columns)"
#   then re-run a week later and diff the rows for a completed week

# §3.3 #13 — the two PFR tables nflreadr does not document
uv run python -c "import nflreadpy as n; print(n.load_pfr_advstats([2026], stat_type='rush', summary_level='week').columns)"
uv run python -c "import nflreadpy as n; print(n.load_pfr_advstats([2026], stat_type='def',  summary_level='week').columns)"

# §3.3 #10 — NGS passing and rushing columns, which the Phase-0 probe did not cover
uv run python -c "import nflreadpy as n; print(n.load_nextgen_stats([2026], stat_type='passing').columns)"
uv run python -c "import nflreadpy as n; print(n.load_nextgen_stats([2026], stat_type='rushing').columns)"

# §2a.3 — are Vegas lines populated for FUTURE games, or only back-filled?  [ANSWERED 2026-09-22: weeks 3–4 at week 2]
uv run python -c "import nflreadpy as n, polars as pl; f=n.load_schedules([2026]); print(f.select(['week','total_line','spread_line']).filter(pl.col('week')>2))"

# §3.3 #14 / #16 / #18 — loaders this repository has never called
uv run python -c "import nflreadpy as n; print(n.load_team_stats([2026]).columns)"
uv run python -c "import nflreadpy as n; print(n.load_contracts().columns)"
#   QBR has no loader in nflreadpy 0.1.5; fetch the release asset directly if the rights
#   question in #18 is ever answered yes.

# Part 1 — how many behaviour snapshots actually exist
git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data
uv run ffdraft validate-market-history ../market-data --season 2026
ls ../market-data/behavior/sleeper/2026/ | wc -l
```

Run these through `scripts/source_probe.py` rather than ad hoc where the shape fits, so the
evidence lands in `docs/source-probes/` like every other source decision in this repository.
