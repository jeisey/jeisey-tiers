# Source probe summary

- run environment: `github-actions`
- started (UTC): `2026-08-17T17:01:02Z`
- finished (UTC): `2026-08-17T17:01:55Z`
- git sha: `5fb325bb60dd0855b2d8547735ca0753792d3392`
- python: `3.12.13`
- package versions: `nflreadpy==0.1.5`, `polars==1.43.2`, `requests==2.34.2`

## Derived decisions

- current market source viable: **True** (`ok`)
- MFL historical years returning >=100 priced players: 2019, 2020, 2021, 2022, 2023, 2024, 2025
- history dense enough: **True**; point-in-time capable: **False**
- `arbitrage_ml_historical_feasible`: **False** -> arbitrage mode **baseline**
  - rule: >=5 historical MFL ADP years each with >=100 priced players AND demonstrated point-in-time windowing of a historical aggregate; volume alone is insufficient because a season-long aggregate embeds in-season drafting that already knows the outcome
  - mfl_adp_history_window_days30: status=ok records=445 totalDrafts=15850 changed=False
  - mfl_adp_history_window_no_mock_redraft: status=ok records=384 totalDrafts=6885 changed=True
- market rows resolved to a canonical id without name matching: **0.9537**
- nflverse injury years with rows: 2019, 2024, 2025
- sources blocked by local egress policy: none

## Findings

| check | source | status | records | notes |
| --- | --- | --- | --- | --- |
| `rights_fantasycalc_robots` | fantasycalc | ok |  |  |
| `rights_fantasycalc_terms` | fantasycalc | ok |  | no keyword match in document |
| `rights_dynastyprocess_readme` | fantasypros_ecr_via_dynastyprocess | ok |  |  |
| `rights_fantasypros_terms` | fantasypros_ecr_via_dynastyprocess | ok |  | no keyword match in document |
| `rights_ffopportunity_description` | ffopportunity | ok |  |  |
| `rights_ffopportunity_readme` | ffopportunity | ok |  |  |
| `identity_market_to_gsis_bridge` | identity | ok | 367 | unresolved sample: mfl_id=0532 rank=215; mfl_id=0515 rank=218; mfl_id=0528 rank=228; mfl_id=0511 rank=235; mfl_id=0510 rank=249; mfl_id=0524 rank=251; mfl_id=05 |
| `mfl_adp_current_cutoff5` | myfantasyleague_adp | ok | 367 |  |
| `mfl_adp_current_default` | myfantasyleague_adp | ok | 367 |  |
| `mfl_adp_current_fcount10` | myfantasyleague_adp | ok | 325 |  |
| `mfl_adp_current_fcount12` | myfantasyleague_adp | ok | 356 |  |
| `mfl_adp_current_fcount14` | myfantasyleague_adp | ok | 242 |  |
| `mfl_adp_current_no_mock_redraft` | myfantasyleague_adp | ok | 383 |  |
| `mfl_adp_current_ppr_12team` | myfantasyleague_adp | ok | 361 |  |
| `mfl_adp_current_ppr_only` | myfantasyleague_adp | ok | 370 |  |
| `mfl_adp_current_recent_14days` | myfantasyleague_adp | ok | 367 |  |
| `mfl_adp_current_recent_1day` | myfantasyleague_adp | ok | 367 |  |
| `mfl_adp_current_std_10team` | myfantasyleague_adp | ok | 2 |  |
| `mfl_adp_current_std_only` | myfantasyleague_adp | ok | 229 |  |
| `mfl_adp_history_window_days30` | myfantasyleague_adp | ok | 445 |  |
| `mfl_adp_history_window_no_mock_redraft` | myfantasyleague_adp | ok | 384 |  |
| `mfl_adp_year_2019` | myfantasyleague_adp | ok | 445 |  |
| `mfl_adp_year_2020` | myfantasyleague_adp | ok | 442 |  |
| `mfl_adp_year_2021` | myfantasyleague_adp | ok | 397 |  |
| `mfl_adp_year_2022` | myfantasyleague_adp | ok | 391 |  |
| `mfl_adp_year_2023` | myfantasyleague_adp | ok | 416 |  |
| `mfl_adp_year_2024` | myfantasyleague_adp | ok | 413 |  |
| `mfl_adp_year_2025` | myfantasyleague_adp | ok | 362 |  |
| `mfl_api_info_adp` | myfantasyleague_adp | ok |  |  |
| `mfl_api_info_all` | myfantasyleague_adp | ok |  |  |
| `mfl_players_details` | myfantasyleague_adp | ok | 2600 |  |
| `rights_mfl_developer_page` | myfantasyleague_adp | ok |  | no keyword match in document |
| `rights_mfl_robots` | myfantasyleague_adp | ok |  |  |
| `rights_mfl_terms` | myfantasyleague_adp | http_error |  |  |
| `nflverse_combine` | nflreadpy | ok | 8968 |  |
| `nflverse_current_season` | nflreadpy | ok |  |  |
| `nflverse_depth_charts_2019` | nflreadpy | ok | 36308 |  |
| `nflverse_depth_charts_2024` | nflreadpy | ok | 37312 |  |
| `nflverse_depth_charts_2025` | nflreadpy | ok | 554215 |  |
| `nflverse_depth_charts_2026` | nflreadpy | ok | 442872 |  |
| `nflverse_draft_picks` | nflreadpy | ok | 12927 |  |
| `nflverse_ff_opportunity_2019` | nflreadpy | ok | 5633 |  |
| `nflverse_ff_opportunity_2024` | nflreadpy | ok | 6005 |  |
| `nflverse_ff_opportunity_2025` | nflreadpy | ok | 6054 |  |
| `nflverse_ff_playerids` | nflreadpy | ok | 12472 |  |
| `nflverse_ff_rankings_draft` | nflreadpy | ok | 5849 | rows suppressed: benchmark-only source, not redistributable |
| `nflverse_ftn_charting_2025` | nflreadpy | ok | 47316 |  |
| `nflverse_injuries_2019` | nflreadpy | ok | 5392 |  |
| `nflverse_injuries_2024` | nflreadpy | ok | 6215 |  |
| `nflverse_injuries_2025` | nflreadpy | ok | 6068 |  |
| `nflverse_injuries_2026` | nflreadpy | loader_error |  | ValueError: Season must be between 2009 and 2025 |
| `nflverse_loader_surface` | nflreadpy | ok |  | loaders=load_combine,load_contracts,load_depth_charts,load_draft_picks,load_ff_opportunity,load_ff_playerids,load_ff_rankings,load_ffverse,load_ftn_charting,loa |
| `nflverse_nextgen_receiving_2025` | nflreadpy | ok | 1402 |  |
| `nflverse_pfr_rec_season_2025` | nflreadpy | ok | 531 |  |
| `nflverse_player_stats_season_2012` | nflreadpy | ok | 1811 |  |
| `nflverse_player_stats_season_2019` | nflreadpy | ok | 1889 |  |
| `nflverse_player_stats_season_2024` | nflreadpy | ok | 1997 |  |
| `nflverse_player_stats_season_2025` | nflreadpy | ok | 2020 |  |
| `nflverse_player_stats_weekly_2025` | nflreadpy | ok | 19422 |  |
| `nflverse_players` | nflreadpy | ok | 25040 |  |
| `nflverse_rosters_2012` | nflreadpy | ok | 2120 |  |
| `nflverse_rosters_2019` | nflreadpy | ok | 3114 |  |
| `nflverse_rosters_2025` | nflreadpy | ok | 3137 |  |
| `nflverse_rosters_2026` | nflreadpy | ok | 2930 |  |
| `nflverse_rosters_weekly_2019` | nflreadpy | ok | 51632 |  |
| `nflverse_rosters_weekly_2025` | nflreadpy | ok | 46849 |  |
| `nflverse_schedules_2026` | nflreadpy | ok | 272 |  |
| `nflverse_snap_counts_2019` | nflreadpy | ok | 23862 |  |
| `nflverse_snap_counts_2025` | nflreadpy | ok | 26612 |  |
| `nflverse_teams` | nflreadpy | ok | 36 |  |
| `rights_nflreadpy_license` | nflreadpy | ok |  |  |
| `rights_nflreadpy_readme_data_license` | nflreadpy | ok |  |  |
| `rights_nflreadr_terms_of_use` | nflreadpy | ok |  |  |
| `rights_nflverse_data_readme` | nflreadpy | ok |  |  |
| `rights_nflverse_update_schedule` | nflreadpy | ok |  |  |
| `rights_sleeper_docs` | sleeper | ok |  |  |
| `rights_sleeper_robots` | sleeper | ok |  |  |
| `sleeper_players_nfl` | sleeper | ok | 12220 |  |
| `sleeper_state_nfl` | sleeper | ok |  |  |
| `sleeper_trending_add` | sleeper | ok | 25 |  |
