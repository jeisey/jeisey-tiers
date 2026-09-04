# Rest-of-season feature dictionary

Generated from `ffdraft.ros.dictionary`; run `uv run ffdraft feature-dictionary --ros`
to reproduce. A test asserts this file matches the code, so edit the module, not this file.

Schema `ros_features_v1`, contract hash `f0384c75cac8218a`.
Model input set `ros_core_v1` (`f5ad9df207795351`): 121 inputs, of which 78 are Phase 3's
frozen `intrinsic_core_v1` block inherited unchanged and 43 are the Phase-11 in-season block
listed below.

The preseason block is **not** restated here. It is `docs/FEATURE_DICTIONARY.md` minus the
columns Phase 3 excluded for era instability, and restating it would create a second
definition that could drift from the first.

| name | family | availability | unit | definition |
|---|---|---|---|---|
| `through_week` | cutoff | cutoff_derived | week | The snapshot cutoff: the last completed regular-season week the row may read. |
| `remaining_horizon_weeks` | cutoff | cutoff_derived | weeks | Scored horizon weeks after the cutoff, byes included. Calendar weeks, not games. |
| `season_share_remaining` | cutoff | cutoff_derived | ratio | remaining_horizon_weeks divided by the season's full scored horizon length. |
| `games_to_date` | in_season_availability | in_season_to_date | games | Scored appearances in weeks 1..through_week. |
| `games_share_to_date` | in_season_availability | in_season_to_date | ratio | games_to_date divided by through_week: the share of elapsed weeks played. |
| `weeks_missed_to_date` | in_season_availability | in_season_to_date | weeks | Elapsed weeks in which the player did not appear, byes included. |
| `weeks_since_last_game` | in_season_availability | in_season_to_date | weeks | Weeks between the cutoff and the last appearance; 0 means he played in the cutoff week. |
| `consecutive_weeks_missed` | in_season_availability | in_season_to_date | weeks | Unbroken run of missed weeks ending at the cutoff. |
| `active_last_week` | in_season_availability | in_season_to_date | flag | Whether the player appeared in the cutoff week itself. |
| `games_last3` | in_season_availability | in_season_to_date | games | Appearances in the three calendar weeks ending at the cutoff. |
| `has_played_this_season` | in_season_availability | in_season_to_date | flag | Whether the player has at least one appearance at or before the cutoff. |
| `in_preseason_universe` | in_season_availability | in_season_to_date | flag | Whether the player was in the season's leakage-safe preseason eligible universe. False marks an in-season arrival, whose preseason feature block is null. |
| `team_remaining_scheduled_games` | in_season_availability | in_season_to_date | games | Regular-season games inside the scored horizon still scheduled for the player's observed team after the cutoff. The schedule is published before Week 1 and is not an outcome; the team assignment is the last one actually observed. |
| `points_to_date` | in_season_production | in_season_to_date | points | Fantasy points in weeks 1..through_week, in the row's own scoring preset. |
| `ppg_to_date` | in_season_production | in_season_to_date | points/game | points_to_date divided by games_to_date. |
| `points_per_week_to_date` | in_season_production | in_season_to_date | points/week | points_to_date divided by through_week: production per elapsed week, missed weeks counted as zero. Availability and rate collapsed into one number on purpose. |
| `ppg_last3` | in_season_production | in_season_to_date | points/game | Points per appearance over the three calendar weeks ending at the cutoff. |
| `ppg_trend` | in_season_production | in_season_to_date | points/game | ppg_last3 minus ppg_to_date. Positive means the recent form is above the season rate. |
| `best_week_points_to_date` | in_season_production | in_season_to_date | points | Highest single-week fantasy total at or before the cutoff. |
| `points_sd_to_date` | in_season_production | in_season_to_date | points | Sample standard deviation of weekly points across appearances at or before the cutoff. |
| `targets_per_game_to_date` | in_season_opportunity | in_season_to_date | targets/game | Targets per appearance at or before the cutoff. |
| `carries_per_game_to_date` | in_season_opportunity | in_season_to_date | carries/game | Rushing attempts per appearance at or before the cutoff. |
| `pass_attempts_per_game_to_date` | in_season_opportunity | in_season_to_date | attempts/game | Pass attempts per appearance at or before the cutoff. |
| `touches_per_game_to_date` | in_season_opportunity | in_season_to_date | touches/game | Carries plus receptions per appearance at or before the cutoff. |
| `target_share_to_date` | in_season_opportunity | in_season_to_date | ratio | Player targets divided by his team's targets, summed over the weeks he played. Both halves come from the same weekly rows, so the ratio has one provenance. |
| `carry_share_to_date` | in_season_opportunity | in_season_to_date | ratio | Player carries divided by his team's carries over the weeks he played. |
| `air_yards_per_game_to_date` | in_season_opportunity | in_season_to_date | yards/game | Receiving air yards per appearance at or before the cutoff. |
| `snap_pct_mean_to_date` | in_season_opportunity | in_season_to_date | ratio | Mean share of team offensive snaps across appearances at or before the cutoff. |
| `snap_pct_last3` | in_season_opportunity | in_season_to_date | ratio | Mean offensive snap share over the three calendar weeks ending at the cutoff. |
| `snap_pct_trend` | in_season_opportunity | in_season_to_date | ratio | snap_pct_last3 minus snap_pct_mean_to_date: a role gaining or losing ground. |
| `target_share_last3` | in_season_opportunity | in_season_to_date | ratio | Target share over the three calendar weeks ending at the cutoff. |
| `target_share_trend` | in_season_opportunity | in_season_to_date | ratio | target_share_last3 minus target_share_to_date. |
| `expected_points_per_game_to_date` | in_season_opportunity | in_season_to_date | points/game | ffopportunity expected fantasy points per appearance at or before the cutoff. |
| `points_over_expected_per_game_to_date` | in_season_opportunity | in_season_to_date | points/game | Points per game minus expected points per game. Separates a player who is scoring on volume from one who is scoring on conversion. |
| `yards_per_target_to_date` | in_season_efficiency | in_season_to_date | yards/target | Receiving yards divided by targets at or before the cutoff. |
| `yards_per_carry_to_date` | in_season_efficiency | in_season_to_date | yards/carry | Rushing yards divided by carries at or before the cutoff. |
| `catch_rate_to_date` | in_season_efficiency | in_season_to_date | ratio | Receptions divided by targets at or before the cutoff. |
| `td_per_opportunity_to_date` | in_season_efficiency | in_season_to_date | ratio | Touchdowns divided by opportunities (pass attempts plus carries plus targets). The most regression-prone quantity in the block, and carried for that reason. |
| `points_per_opportunity_to_date` | in_season_efficiency | in_season_to_date | points | Fantasy points divided by opportunities at or before the cutoff. |
| `team_points_per_game_to_date` | in_season_team_context | in_season_to_date | points/game | Standard-scoring fantasy points scored by the player's team's skill players per team game at or before the cutoff. Preset-independent by design: this is an offence-quality measure, not the row's own scoring flavour. |
| `team_pass_rate_to_date` | in_season_team_context | in_season_to_date | ratio | Team pass attempts divided by attempts plus carries at or before the cutoff. |
| `team_plays_per_game_to_date` | in_season_team_context | in_season_to_date | plays/game | Team pass attempts plus carries per team game at or before the cutoff. |
| `team_changed_in_season` | in_season_team_context | in_season_to_date | flag | Whether more than one team has been observed for the player at or before the cutoff. |
