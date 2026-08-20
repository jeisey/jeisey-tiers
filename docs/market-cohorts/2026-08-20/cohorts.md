# MFL cohort measurement — 2026

Snapshot `2026-08-20T14-38-44Z` retrieved 2026-08-20T14:38:44Z, source `myfantasyleague_adp`. Rule `phase5_cohort_v2` (ADR-039), frozen before this measurement existed.

Board coverage is measured against the `redraft-12` fair board and reported as the minimum over the launch scoring presets, so a cohort cannot pass by covering one preset well and another badly.

`rows` is the whole cohort payload; `core` counts the QB/RB/WR/TE rows every rule clause is written about. MyFantasyLeague also prices kickers, team defences and IDP, and counting those would inflate `priced_players` and depress an identity threshold that was never about them (ADR-039).

## Cohorts

| cohort | filters | rows | core | drafts | top-100 | top-150 | median sample | identity | verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `fcount10` | `FCOUNT=10` | 319 | 257 | 102 | 0.960 | 0.927 | 39 | 0.984 | insufficient |
| `fcount12` | `FCOUNT=12` | 353 | 285 | 222 | 0.970 | 0.953 | 62 | 0.982 | insufficient |
| `fcount14` | `FCOUNT=14` | 247 | 220 | 27 | 0.930 | 0.873 | 7 | 0.982 | insufficient |
| `no-keeper` | `IS_KEEPER=N` | 353 | 291 | 125 | 0.970 | 0.967 | 105 | 0.973 | insufficient |
| `no-mock` | `IS_MOCK=0` | 360 | 283 | 426 | 0.970 | 0.960 | 141 | 0.982 | **sufficient** |
| `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | 353 | 291 | 125 | 0.970 | 0.967 | 105 | 0.973 | insufficient |
| `ppr` | `IS_PPR=1` | 358 | 281 | 401 | 0.970 | 0.960 | 129 | 0.982 | **sufficient** |
| `ppr-fcount10` | `FCOUNT=10&IS_PPR=1` | 325 | 264 | 94 | 0.960 | 0.940 | 36 | 0.985 | insufficient |
| `ppr-fcount12` | `FCOUNT=12&IS_PPR=1` | 355 | 287 | 211 | 0.970 | 0.953 | 57 | 0.983 | insufficient |
| `ppr-fcount14` | `FCOUNT=14&IS_PPR=1` | 210 | 186 | 25 | 0.880 | 0.780 | 6 | 0.984 | insufficient |
| `ppr-no-keeper` | `IS_KEEPER=N&IS_PPR=1` | 358 | 300 | 115 | 0.970 | 0.967 | 97 | 0.973 | insufficient |
| `std` | `IS_PPR=0` | 251 | 201 | 25 | 0.930 | 0.860 | 12 | 0.985 | insufficient |
| `std-fcount10` | `FCOUNT=10&IS_PPR=0` | 18 | 18 | 8 | 0.030 | 0.053 | 6 | 0.944 | insufficient |
| `std-fcount12` | `FCOUNT=12&IS_PPR=0` | 144 | 139 | 11 | 0.770 | 0.673 | 5 | 0.978 | insufficient |
| `std-fcount14` | `FCOUNT=14&IS_PPR=0` | 0 | 0 | 2 | 0.000 | 0.000 | — | 0.000 | insufficient |
| `unfiltered` | `—` | 360 | 283 | 426 | 0.970 | 0.960 | 141 | 0.982 | **sufficient** |

## Why each cohort failed

- `fcount10`: total_drafts 102 < 300
- `fcount12`: total_drafts 222 < 300
- `fcount14`: total_drafts 27 < 300; top100_board_coverage 0.930 < 0.95; top150_board_coverage 0.873 < 0.9; median_top150_sample_size 7.0 < 25.0
- `no-keeper`: total_drafts 125 < 300
- `no-mock-no-keeper`: total_drafts 125 < 300
- `ppr-fcount10`: total_drafts 94 < 300
- `ppr-fcount12`: total_drafts 211 < 300
- `ppr-fcount14`: priced_players 186 < 200; total_drafts 25 < 300; top100_board_coverage 0.880 < 0.95; top150_board_coverage 0.780 < 0.9; median_top150_sample_size 6.0 < 25.0
- `ppr-no-keeper`: total_drafts 115 < 300
- `std`: total_drafts 25 < 300; top100_board_coverage 0.930 < 0.95; top150_board_coverage 0.860 < 0.9; median_top150_sample_size 12.0 < 25.0
- `std-fcount10`: priced_players 18 < 200; total_drafts 8 < 300; top100_board_coverage 0.030 < 0.95; top150_board_coverage 0.053 < 0.9; median_top150_sample_size 6.5 < 25.0; identity_coverage 0.944 < 0.95
- `std-fcount12`: priced_players 139 < 200; total_drafts 11 < 300; top100_board_coverage 0.770 < 0.95; top150_board_coverage 0.673 < 0.9; median_top150_sample_size 5.0 < 25.0
- `std-fcount14`: priced_players 0 < 200; total_drafts 2 < 300; top100_board_coverage 0.000 < 0.95; top150_board_coverage 0.000 < 0.9; median_top150_sample_size None < 25.0; identity_coverage 0.000 < 0.95

## Selection

| scoring | teams | cohort | filters | exact | sufficient | reason |
|---|---:|---|---|---|---|---|
| HALF | 10 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| HALF | 12 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| HALF | 14 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| PPR | 10 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| PPR | 12 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| PPR | 14 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| STD | 10 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| STD | 12 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |
| STD | 14 | `no-mock-no-keeper` | `IS_KEEPER=N&IS_MOCK=0` | no | no | no candidate met the sufficiency rule; widest candidate used and flagged |

HALF-PPR can never be exact on this source: MFL exposes `IS_PPR` as a boolean and publishes no half-PPR filter (ADR-039).
