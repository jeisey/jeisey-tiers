# Skill Tree EDA — 2026-10-14 (evidence for ADR-107)

**Question.** What can nflverse honestly say, today, about a player's fine-grained positional
profile — through the board's cutoff, for every QB, RB, WR and TE — and which of the requested
statistics are correct, covered, complementary and readable enough to become nodes on a card?

**Answer in one line.** Workload, shares and red-zone roles are well covered and stable from
week 1; efficiency rates are covered but noisy early (several barely persist from weeks 1–5 to
the rest of a season), so they ship with their samples and minimums printed; three Next Gen
Stats readings ship conditionally on a verified season summary; route-based metrics, FTN and
PFR charting, and any "current speed" claim are deferred.

| file | what it is |
|---|---|
| `eda.py` | the analysis, runnable (network, nflreadpy cache) — every metric computed independently of production |
| `report.json` | every number below, one result object |
| `report.md` | tables rendered from `report.json` by `eda.py` (coverage, distributions, reliability, recent window, redundancy, NGS checks, combine, examples) |
| `README.md` | this argument: findings, the metric inventory, and a decision for every requested statistic |

Reproduce (about three minutes with a warm cache; raw downloads stay in the cache directory and
are never committed):

```
NFLREADPY_CACHE=filesystem NFLREADPY_CACHE_DIR=/tmp/nflcache \
  uv run python docs/experiments/skill-tree-2026-10-14/eda.py \
    --current 2026 --cutoff-week 5 --history 2023 2024 2025 --out docs/experiments/skill-tree-2026-10-14
```

`--check-artifact <player_skill_tree.json>` re-derives sampled players from a built artifact
with this file's independent formulas (ADR-107 validation; see the bottom of this file).

## 1. Evidence base

* **Live, 2026-10-14, nflreadpy 0.1.5** through `ffdraft.sources.nflverse_http.nflverse_loaders`
  (the production retry policy). The live board's cutoff was **2026 week 5**
  (`2026w05-intrinsic-ros-v1-20261014T113357Z`); play-by-play's latest game was 2026-10-12
  (79 games, 13,842 plays), Next Gen Stats carried weeks 1–5 plus the week-0 summary.
* **Official dictionaries**, fetched the same day from `nflverse/nflreadr` `data-raw/`
  (`dictionary_pbp.csv`, `dictionary_player_stats.json`, `dictionary_nextgenstats.csv`,
  `dictionary_combine.csv`, `dictionary_participation.csv`) and the data-schedule article. Field
  meanings cited in ADR-107 are quoted from those files, not paraphrased from memory. Three
  dictionary facts that differ from what a reader would guess: `cpoe` is published in
  **percentage points** (100 × (complete − cp)), not the dictionary's 0–1 wording; there is **no
  designed-run flag, end-zone flag or numeric pass-depth field** in play-by-play; and the player
  stats dictionary lists 114 fields against 150 live columns (the rest are nflfastR's).
* **History**: complete 2023, 2024 and 2025 regular seasons for reliability, early-season
  stability, recent-window and redundancy checks. Nothing here was used to fit or select any
  model; the skill tree is descriptive (ADR-107).

## 2. Datasets: grain, coverage, identity

| dataset | grain | 2026 through week 5 | identity | notes |
|---|---|---|---|---|
| `load_player_stats(week)` | player × week × season_type | 5,506 rows, weeks 1–5, REG only, 0 duplicate player-weeks; QB 55 / RB 124 / WR 204 / TE 113 players | `player_id` = GSIS, 100% in the season roster | official box score. `passing_cpoe` is a **per-week mean** (pooled season CPOE must come from play-by-play) |
| `load_snap_counts` | player × game (PFR id) | 7,370 rows, 2,915 with offensive snaps | 99.66% bridged PFR → GSIS (5 QB/RB/WR/TE rows unbridged; fail closed) | no team total; the highest-share player per team-game is at 100% in 99.4% of team-games, so team snaps = his snaps ÷ his share |
| `load_pbp` | play | 13,842 plays, 79 games, every completed game | passer / rusher / receiver ids 100% in roster | 35 two-point tries, 24 spikes, 125 kneels, 24 aborted, 0 deleted plays. `yards_after_catch` null on incompletions only |
| `load_nextgen_stats` × 3 | player × week; **week 0 = season-to-date summary** | passing 37 / rushing 42 / receiving 118 summary rows (receiving: WR 85, TE 33; rushing: RB only) | `player_gsis_id` 100% | weekly rows exist only for qualifying weeks (≥15 att, ≥10 rushes, ≥5 targets observed), covering 72% of WR and 59% of TE targets — **never sum weekly rows** |
| `load_combine` | tester | 8,968 rows, 2000–2026 | `pfr_id` present 83%; 2,363 rows link to a GSIS id; 3 GSIS ids carry two combine rows (fail closed) | a forty for 33/58 appearing QBs, 73/134 RBs, 128/210 WRs, 68/124 TEs |
| `load_rosters` | player × team | 3,041 players | — | 9 season-roster positions disagree with the box score's; the board's position wins (ADR-105) |
| `load_schedules` | game | 79 completed REG games through week 5 | — | the completeness check: every completed game must be in play-by-play |

**Reconciliation, every season 2023–2026** (`report.json` → `reconciliation`): play-by-play
pass attempts (sacks included, two-point tries excluded) equal official attempts + sacks for
**every** player; targets equal official targets for every player; non-kneel carries equal
official carries − kneels for every player. Spikes are official attempts and are kept; kneels
are official carries and are kept in the official totals and dropped only from rushing
efficiency. Receiving yards differ for 14 players in 2025 (laterals), so official yards stay the
total and play-level yards are used only for the 20+ yard catch flag. CPOE pooled over attempts
differs from the mean of weekly `passing_cpoe` by a median 0.6–0.9 pp and up to 34 pp.

**Trades.** No 2026 QB/RB/WR/TE has appeared for two clubs through week 5; shares are pooled over
the team-games he actually played, keyed by the club he played for that week, so a trade adds
the new club's games and never re-assigns old ones (fixture-tested).

## 3. What the numbers say

**Coverage (2026, week 5; full table in `report.md`).** Volume and shares are defined for every
appearing player. Efficiency rates need a sample: with the minimums chosen below, 36–37 QBs,
53 RBs (rushing), 40 RBs (receiving, 10 targets), 85 WRs and 33 TEs qualify. Red-zone and
goal-line roles are genuinely sparse: 79 of 134 appearing RBs have no goal-line carry and
186 of 334 WR/TE have no end-zone target — a real zero, published as 0, never as missing.

**Stability is the decisive finding** (`report.md`, "Reliability and early-season stability").
Weeks 1–5 against the rest of the season, Spearman, 2023 / 2024 / 2025:

| reading | early→rest ρ | full-season split-half reliability |
|---|---|---|
| RB carry share | 0.83 / 0.86 / 0.89 | 0.96–0.97 |
| WR target share | 0.81 / 0.83 / 0.84 | 0.95–0.97 |
| WR snap share | 0.79 / 0.82 / 0.81 | 0.96–0.98 |
| RB goal-line carry share | 0.47 / 0.63 / 0.73 | 0.76–0.79 |
| WR aDOT | 0.59 / 0.65 / 0.40 | 0.77–0.87 |
| QB EPA per dropback | 0.54 / 0.24 / 0.50 | 0.60–0.79 |
| RB yards per carry | 0.41 / 0.21 / −0.01 | 0.33–0.60 |
| RB rushing EPA per carry | 0.35 / 0.17 / 0.01 | −0.37–0.43 |
| WR receiving EPA per target | 0.07 / 0.34 / 0.12 | 0.15–0.29 |
| QB interception rate | −0.11 / −0.05 / −0.17 | 0.36–0.50 |

So **role** (shares, workload, red-zone usage, depth of target) describes the player; early
**efficiency** mostly describes his first five games. Both are true statements about what
happened, which is all the tree claims, but an efficiency node must print its sample and the
fact that early rates are noisy, and must never be blended into a score.

**Recent window — deferred.** At week 8, a last-three-games rate anticipated the rest of the
season worse than the season-to-date rate in 34 of 46 metric × position readings in 2023, 35 of
46 in 2024 and 41 of 46 in 2025 (`report.json` → `history.<season>.recent_window`), and no
reading favoured the recent window in all three seasons. A second window would halve every
sample, disagree with itself from season to season, and add nothing the card's week-by-week
rails do not already show.

**Minimums** (`threshold_sensitivity`): rank agreement with the full season is flat across a 4×
range of minimums, so the minimum's job is to keep one-attempt rates out of a ranking, not to
buy reliability. Chosen: 50 attempts / dropbacks (QB), 25 carries (RB rushing), 10 targets (RB
receiving), 15 targets (WR/TE), 10 receptions for per-reception rates, 2 appearances for a share.
Below a minimum the value still prints, unranked, with its sample ("12 of 50 dropbacks").

**Redundancy** (`report.md`, "Redundancy", |ρ| ≥ 0.8 in 2025 and 2026). Totals within a
workload family move together (attempts~yards 0.99; targets~receptions 0.99; carries~carry
share 0.94–0.98), so related totals are grouped into one node with the others as detail.
Among rates: EPA per dropback ~ dropback success 0.88; completion % ~ CPOE 0.83; YPC ~ rushing
EPA per carry 0.80; yards per target ~ receiving EPA per target 0.81–0.83; target share ~
air-yard share 0.91–0.96 (WR and TE); NGS intended air yards ~ official aDOT **0.98**; NGS CPOE ~ play-by-play
CPOE 0.86. Each redundant pair keeps one node and moves the other into the node's detail.
Complementary pairs stay separate: separation ~ aDOT −0.49 (context, not skill); YAC over
expected ~ YAC per reception 0.53; RYOE per attempt ~ YPC 0.80 but ~ success rate only 0.50.

**Next Gen Stats.** The week-0 row is a season-to-date summary for NGS's own qualifying
population and it reconciles: in 2023–2026 the summary volume equals the official volume through
the same week for every passer and all but one rusher (2023), and is within one target for every
receiver. Weekly rows cover only qualifying weeks, so a weighted sum of them would describe 59–74%
of a player's targets and must not be used. Rule adopted: use the week-0 row only when the file's
REG weeks end exactly at the board's cutoff and the player's NGS volume is within one of his
official volume; otherwise the reading is "not covered", never filled.

**Combine.** Historical context only. 55–63% of appearing players have a linked forty; a
percentile among same-position testers 2000–2026 (QB n 414, RB 718, WR 1,162, TE 452) is well
defined and dated. Nothing in nflverse measures current on-field speed: NGS publishes no max
speed in these files, and yards or explosive plays are not speed.

## 4. Decision for every requested statistic

`ship` = node or node detail; `conditional` = ships only when its source check passes for that
player; `defer` = not built, with the reason. Source: **off** = official player stats, **pbp** =
play-by-play, **snap** = snap counts, **ngs** = Next Gen Stats week-0 summary, **comb** = combine.

**QB**

| requested | decision | as | source |
|---|---|---|---|
| attempts, completions | ship | node *Pass attempts* (+ completions) | off |
| passing yards, TDs | ship | nodes (+ TD rate) | off |
| completion rate | ship | detail of *CPOE* (ρ 0.83) | off |
| YPA | ship | node | off |
| CPOE | ship | node, pooled over attempts, nflfastR model | pbp |
| intended air yards | ship | node, context (official air yards ÷ attempts; NGS duplicate ρ 0.98 not used) | off |
| EPA per dropback | ship | node — the existing `pass_epa_per_dropback` definition (ADR-091) | off |
| EPA-positive success rate | ship | detail of EPA per dropback (ρ 0.88), same dropbacks | pbp |
| sack rate, INT rate | ship | nodes, lower is better | off |
| designed rushes, scrambles | ship | nodes (+ scramble rate) | pbp |
| rushing yards / TDs | ship | node (+ TDs) | off |
| red-zone involvement | ship | node *Red-zone rushes* (+ goal-line rushes, red-zone dropbacks) | pbp |
| time to throw | conditional | detail of sack rate, context | ngs |
| NGS CPOE, aggressiveness | defer | duplicate model of CPOE (ρ 0.86, 37-QB cohort) / niche | — |

**RB**

| requested | decision | as | source |
|---|---|---|---|
| carries, yards, TDs | ship | node *Carries* (+ yards, TDs) | off |
| team carry share | ship | node — `carry_share` (ADR-091): his carries ÷ all his team's official carries (every position; QB scrambles and kneels included) in his games. Kneels move it by a median 0.3 pp, max 4.5 pp | off |
| snaps | ship | node *Offensive snap share*, pooled | snap |
| YPC | ship | node (+ rushing EPA per carry, ρ 0.80) | off / pbp |
| rushing EPA/attempt | ship | detail of YPC; kneels excluded | pbp |
| success rate | ship | node, EPA > 0 on non-kneel carries | pbp |
| explosive-run rate | ship | node, 10+ yard carries ÷ carries | pbp |
| RYOE per attempt | conditional | node | ngs |
| targets, receptions, yards, rec TDs | ship | nodes *Targets* (+ receptions, catch rate), *Receiving yards* (+ TDs, yards per target) | off |
| target share | ship | node — `target_share` (ADR-091) | off |
| red-zone and goal-line carries / share | ship | nodes (count, share as detail; share of all team non-kneel carries inside the 20 / 5) | pbp |
| red-zone targets | ship | node | pbp |

**WR**

| requested | decision | as | source |
|---|---|---|---|
| targets, receptions, yards, TDs | ship | nodes *Targets* (+ receptions), *Receiving yards* (+ TDs) | off |
| target / air-yard share | ship | node *Target share* (+ air-yard share, ρ 0.91–0.96) | off |
| snaps | ship | node | snap |
| aDOT | ship | node, context | off |
| yards per target | ship | detail of receiving EPA per target (ρ 0.81–0.83) | off |
| yards per reception | ship | node | off |
| explosive catches | ship | node *20+ yard catches* (+ rate per target) | pbp |
| catch rate | ship | node | off |
| receiving EPA per target | ship | node | pbp |
| YAC per reception | ship | node | off |
| YAC over expected | conditional | node (yards per reception) | ngs |
| red-zone / end-zone targets and shares | ship | nodes *Red-zone targets* (+ share), *End-zone targets* (air yards reach the goal line) | pbp |
| NGS separation | conditional | node, context, labelled "at catch or incompletion, on targets" | ngs |
| yards per route run, route participation | **defer** | no valid live route denominator: `load_participation` refuses 2026 ("Season must be between 2016 and 2025"); the feed is FTN-supplied after the season (CC-BY-SA 4.0) | — |

**TE** — the WR inventory, arranged around role and reliability: *Snap share*, *Target share*,
*Targets* (usage); *Catch rate*, *Yards per target* (TE yards per target ~ per reception 0.88–0.91,
so per target is kept), *YAC per reception*, *YAC over expected* (reliability); *Receiving yards*,
*Receiving EPA per target* (production); *Red-zone targets*, *End-zone targets*, *aDOT*,
*Separation* (scoring and depth, the last two context).

**All positions**

| requested | decision | as | source |
|---|---|---|---|
| "Speed rank" | **defer** as stated; ship the supported fallback | *Combine 40-yard dash* — time, test year, percentile among same-position testers 2000–2026, labelled historical, never "speed" | comb |
| recent completed-game window | **defer** | measured worse than season to date (§3) | — |
| FTN charting (drops, catchable balls, play action) | **defer** | CC-BY-SA 4.0; the per-player publication question is the open ADR-086 decision | — |
| PFR advanced stats (broken tackles, drops) | **defer** | scraped from Pro-Football-Reference; terms not reviewed; not needed | — |
| any overall skill rating or branch score | **refuse** | ADR-107: the tree describes observations; it never blends them | — |

## 5. Player examples (2026 through week 5)

`report.md` lists every candidate for a data-chosen star (volume leader), role player (median)
and sparse player (fewest opportunities with ≥ 2 games) at each position, plus earlier ADRs'
cases. Highlights:

* **QB** — Stafford (star): 216 att, CPOE +0.3 pp, EPA/dropback +0.143, sack rate 3.1%. Kyler
  Murray (role, 4 g): CPOE +5.7, 13 scrambles. Pickett (sparse, 1 attempt): CPOE −77 on one
  throw — exactly why a value prints unranked below its minimum. Shough: CPOE +1.9,
  EPA/dropback −0.023, 9 designed rushes, 5 red-zone rushes.
* **RB** — Henry (star): 113 carries, 69.8% of team carries, 28 red-zone carries (82%), 13
  goal-line carries. Gibbs: 80.8% carry share, 17.1% 10+ yard runs, 18.1% target share.
  Montgomery: 44% carry share, 2.65 YPC, success 25% — and 50% of goal-line carries.
  Frank Gore Jr. (sparse): 1 carry, every rate unranked.
* **WR** — St. Brown (star): 30.3% target share, 16 red-zone targets (41%), 5 end-zone
  targets. Harrison Jr. (role): 13 targets, aDOT 15.5 — below the 15-target minimum, unranked.
  Shaheed: catch rate 47%, aDOT 10.9, EPA/target −0.44.
* **TE** — McBride (star): 89% snaps, 28.9% target share, 75% catch rate, aDOT 5.8, 11 red-zone
  targets. Tanner Hudson (role): 7 targets, all rates unranked. Marlin Klein (sparse): 1 target.

## 6. Production cross-check

After ADR-107 was implemented, `eda.py --check-artifact` re-derived every published node for
sampled players from the raw loaders with this file's formulas; the result is recorded in
`artifact_check.json` and summarised in ADR-107's Evidence.
