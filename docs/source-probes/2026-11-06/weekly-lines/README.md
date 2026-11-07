# Weekly lines outage — evidence, 2026-11-06 (ADR-117)

Retrieved 2026-11-06 between 18:40Z and 00:30Z. Every number here is reproducible from the
sources named; nothing in this directory is a vendor dump.

## 1. The published builds (retained `daily-refresh` build records)

| run | build | target week | teams lined (`weekly_context.this_week.total_line`) | upcoming | kicked off | bye | lines pending |
|---|---|---|---|---|---|---|---|
| 41829273904 | `2026w08-intrinsic-ros-v1-20261104T123135Z` | 9 | 30 / 30 | 1,530 | 0 | 114 | 0 |
| 42027269614 | `2026w08-intrinsic-ros-v1-20261105T123106Z` | 9 | 30 / 30 | 1,545 | 0 | 111 | 0 |
| 42124743199 | `2026w08-intrinsic-ros-v1-20261105T225300Z` | 9 | 30 / 30 | 1,545 | 0 | 114 | 0 |
| **42217730020** | `2026w08-intrinsic-ros-v1-20261106T123207Z` | 9 | **2 / 30** (JAX, BAL) | **0** | 99 | 114 | **1,437** |

All four ran the same code (`ce9fe82`). Counts are across the three scoring presets.

## 2. The upstream history (`nflverse/nfldata`, `data/games.csv`)

Week-9 games without a final score, and how many of them carry a `total_line`, at every commit
on 2026-11-06 up to the build:

| committed (UTC) | commit | unplayed | lined |
|---|---|---|---|
| 2026-11-06T00:05:19+00:00 | `00af1d7` | 15 | 15 |
| 2026-11-06T00:15:19+00:00 | `9065fde` | 15 | 15 |
| 2026-11-06T00:35:17+00:00 | `8dd3c60` | 15 | 15 |
| 2026-11-06T00:45:18+00:00 | `a2bfea6` | 15 | 15 |
| 2026-11-06T01:05:17+00:00 | `89e98f3` | 15 | 15 |
| 2026-11-06T01:15:18+00:00 | `7bc154a` | 15 | 15 |
| 2026-11-06T01:20:27+00:00 | `1a73ca6` | 15 | 15 |
| 2026-11-06T01:35:18+00:00 | `e65dbbc` | 15 | 15 |
| 2026-11-06T03:45:17+00:00 | `dd0352f` | 15 | 15 |
| 2026-11-06T04:11:24+00:00 | `91e316f` | 14 | 14 |
| 2026-11-06T04:35:17+00:00 | `9d8b4e8` | 14 | 14 |
| 2026-11-06T04:55:17+00:00 | `7c61f84` | 14 | 14 |
| 2026-11-06T05:05:19+00:00 | `0f83eef` | 14 | 14 |
| 2026-11-06T08:35:17+00:00 | `92eff3e` | 14 | 14 |
| 2026-11-06T11:45:17+00:00 | `63cbbc1` | 14 | 0 |
| 2026-11-06T11:55:20+00:00 | `13d8e46` | 14 | 14 |
| 2026-11-06T12:45:18+00:00 | `489cc5f` | 14 | 14 |

`63cbbc1` emptied every odds column (moneylines, `spread_line`, spread odds, `total_line`,
over/under odds) of the 14 unplayed games; `13d8e46` restored them ten minutes later. The 12:32Z
refresh read the `nflverse-data` schedules release built from the blank state (its first
nflverse download of the UTC day, then cached for the day). The two states are committed as
`tests/fixtures/weekly/schedule_lines_2026w09.json`.

## 3. Replay with the fix

`replay_nov6.py` re-runs `ffdraft build-ros --season 2026 --as-of 2026-11-06T12:32:07Z
--through-week 8` on live nflverse data with the 14 unplayed week-9 games' odds blanked exactly as
`63cbbc1` did, against a temporary store holding one `schedule_lines` capture taken from the
pre-blank rows at the previous build's time (2026-11-05T22:53:00Z). Quality gate: pass, 0
critical, 9 warnings (store-dependent captures absent, as expected, and
`ros.weekly_lines_retained`).

## Replay of the 2026-11-06T12:32:07Z build, through week 8 (blank week-9 lines + one retained capture)

metadata counts: {'records': 1659, 'upcoming': 1446, 'kicked_off': 96, 'bye': 117, 'lines_pending': 0, 'unmodelled': 0}
lines: {'target_games': 15, 'from_schedule': 1, 'from_retained': 14, 'unlined': 0, 'captures_read': ['2026-11-05T22-53-00Z']}

state by preset: {('HALF', 'bye'): 39, ('HALF', 'upcoming'): 482, ('HALF', 'kicked_off'): 32, ('PPR', 'bye'): 39, ('PPR', 'upcoming'): 482, ('PPR', 'kicked_off'): 32, ('STD', 'bye'): 39, ('STD', 'upcoming'): 482, ('STD', 'kicked_off'): 32}

| game | kickoff (UTC) | line source | HALF with/without dist | PPR | STD |
|---|---|---|---|---|---|
| 2026_09_JAX_BAL | 2026-11-06T01:15:00Z | schedule | 32/0 | 32/0 | 32/0 |
| 2026_09_CIN_ATL | 2026-11-08T14:30:00Z | retained | 29/0 | 29/0 | 29/0 |
| 2026_09_CLE_NO | 2026-11-08T18:00:00Z | retained | 35/0 | 35/0 | 35/0 |
| 2026_09_DAL_IND | 2026-11-08T18:00:00Z | retained | 34/0 | 34/0 | 34/0 |
| 2026_09_DEN_CAR | 2026-11-08T18:00:00Z | retained | 37/0 | 37/0 | 37/0 |
| 2026_09_DET_MIA | 2026-11-08T18:00:00Z | retained | 32/0 | 32/0 | 32/0 |
| 2026_09_LA_WAS | 2026-11-08T18:00:00Z | retained | 35/0 | 35/0 | 35/0 |
| 2026_09_NYG_PHI | 2026-11-08T18:00:00Z | retained | 32/0 | 32/0 | 32/0 |
| 2026_09_NYJ_KC | 2026-11-08T18:00:00Z | retained | 34/0 | 34/0 | 34/0 |
| 2026_09_HOU_LAC | 2026-11-08T21:05:00Z | retained | 36/0 | 36/0 | 36/0 |
| 2026_09_LV_SF | 2026-11-08T21:05:00Z | retained | 34/0 | 34/0 | 34/0 |
| 2026_09_ARI_SEA | 2026-11-08T21:25:00Z | retained | 37/0 | 37/0 | 37/0 |
| 2026_09_GB_NE | 2026-11-08T21:25:00Z | retained | 41/0 | 41/0 | 41/0 |
| 2026_09_TB_CHI | 2026-11-09T01:20:00Z | retained | 34/0 | 34/0 | 34/0 |
| 2026_09_BUF_MIN | 2026-11-10T01:15:00Z | retained | 32/0 | 32/0 | 32/0 |
| bye | - | - | 0/39 | 0/39 | 0/39 |

context teams by line_source: {'retained': 28, 'schedule': 2}
