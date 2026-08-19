# Feature dictionary

Generated from `ffdraft.features.dictionary`; run `uv run ffdraft feature-dictionary`
to reproduce. A test asserts this file matches the code, so edit the module, not this file.

Schema `historical_features_v1`, contract hash `c495ba3177dcb989`.

| Feature | Family | Role | Type | Unit | Sources | Availability | Lookback | Missing semantics | Indicator | Intrinsic |
|---|---|---|---|---|---|---|---|---|---|---|
| `season` | key | key | Int32 | identifier | nflreadpy | anchor_metadata | - | never missing | - | yes |
| `player_id` | key | key | String | identifier | nflreadpy | anchor_metadata | - | never missing | - | yes |
| `anchor_at_utc` | anchor | anchor | Datetime(time_unit='us', time_zone='UTC') | timestamp | nflreadpy | anchor_metadata | - | never missing | - | yes |
| `feature_cutoff_rule_version` | anchor | anchor | String | version | - | anchor_metadata | - | never missing | - | yes |
| `gsis_id` | identity | context | String | identifier | nflreadpy | anchor_metadata | - | never missing | - | yes |
| `display_name` | identity | context | String | text | nflreadpy | static_biographical | - | never missing | - | yes |
| `position` | identity | context | String | category | nflreadpy | preseason_universe | - | never missing; a row without an anchor-safe position is excluded | - | yes |
| `position_source` | identity | lineage | String | category | nflreadpy | preseason_universe | - | never missing | - | yes |
| `eligibility_basis` | eligibility | lineage | String | category | nflreadpy | preseason_universe | - | never missing | - | yes |
| `universe_era` | eligibility | lineage | String | category | nflreadpy | preseason_universe | - | never missing | - | yes |
| `team_at_anchor` | team_context | context | String | category | nflreadpy | pre_anchor_observation | - | null when no pre-anchor team observation exists for the season | `team_at_anchor_known` | yes |
| `team_at_anchor_source` | team_context | lineage | String | category | nflreadpy | pre_anchor_observation | - | never missing | - | yes |
| `depth_context_state` | depth | lineage | String | category | nflreadpy | pre_anchor_observation | - | never missing | - | yes |
| `depth_observed_at_utc` | depth | lineage | Datetime(time_unit='us', time_zone='UTC') | timestamp | nflreadpy | pre_anchor_observation | - | null unless depth_context_state is depth_observed_at_anchor | - | yes |
| `max_lagged_source_season` | lineage | lineage | Int32 | season | nflreadpy, ffopportunity | season_lagged | -1, -2, -3 | null for a player with no prior-season data at all | - | yes |
| `prev1_team` | team_context | context | String | category | nflreadpy | season_lagged | -1 | null when the player recorded no previous-season game | - | yes |
| `age_at_anchor` | career | feature | Float64 | years | nflreadpy | anchor_derived | - | null when nflverse publishes no birth date | `age_at_anchor_known` | yes |
| `age_at_anchor_known` | career | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `position_age_z` | career | feature | Float64 | z-score | nflreadpy | anchor_derived | - | null when age_at_anchor is null or the cohort has no spread | - | yes |
| `experience_years` | career | feature | Int32 | seasons | nflreadpy | season_lagged | -1 | null when the player was on the previous season's roster but nflverse published no `years_exp` for him - 510 rows of the 2016 roster are like this. Missing experience is recorded as missing rather than imputed as zero, which would misclassify an established player as a rookie | `experience_years_known` | yes |
| `experience_years_known` | career | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `rookie_flag` | career | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `has_prior_season_stats` | career | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `height_in` | athletic | feature | Float64 | inches | nflreadpy | static_biographical | - | null when neither the player master nor the combine publishes a height | - | yes |
| `weight_lb` | athletic | feature | Float64 | pounds | nflreadpy | static_biographical | - | null when neither the player master nor the combine publishes a weight | - | yes |
| `draft_year` | draft | feature | Int32 | season | nflreadpy | static_biographical | - | null for an undrafted player | `drafted_flag` | yes |
| `draft_round` | draft | feature | Int32 | round | nflreadpy | static_biographical | - | null for an undrafted player; missingness is informative, not imputable | `drafted_flag` | yes |
| `draft_overall` | draft | feature | Int32 | pick | nflreadpy | static_biographical | - | null for an undrafted player | `drafted_flag` | yes |
| `drafted_flag` | draft | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `draft_team` | draft | context | String | category | nflreadpy | static_biographical | - | null for an undrafted player | - | yes |
| `seasons_since_draft` | draft | feature | Int32 | seasons | nflreadpy | anchor_derived | - | null for an undrafted player | - | yes |
| `combine_forty` | athletic | feature | Float64 | seconds | nflreadpy | static_biographical | - | null when the player has no combine observation; never imputed | `combine_observed_flag` | yes |
| `combine_bench` | athletic | feature | Float64 | reps | nflreadpy | static_biographical | - | null when not measured | `combine_observed_flag` | yes |
| `combine_vertical` | athletic | feature | Float64 | inches | nflreadpy | static_biographical | - | null when not measured | `combine_observed_flag` | yes |
| `combine_broad_jump` | athletic | feature | Float64 | inches | nflreadpy | static_biographical | - | null when not measured | `combine_observed_flag` | yes |
| `combine_cone` | athletic | feature | Float64 | seconds | nflreadpy | static_biographical | - | null when not measured | `combine_observed_flag` | yes |
| `combine_shuttle` | athletic | feature | Float64 | seconds | nflreadpy | static_biographical | - | null when not measured | `combine_observed_flag` | yes |
| `combine_speed_score` | athletic | feature | Float64 | index | nflreadpy | static_biographical | - | null unless both a combine forty and a weight exist | `combine_observed_flag` | yes |
| `combine_observed_flag` | athletic | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `depth_rank_at_anchor` | depth | feature | Int32 | rank | nflreadpy | pre_anchor_observation | - | null whenever depth_context_state is not depth_observed_at_anchor; the state column, not an imputed value, carries the meaning | `depth_rank_observed` | yes |
| `depth_rank_observed` | depth | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `prior_season_role_rank` | depth | feature | Int32 | rank | nflreadpy | season_lagged | -1 | null when the player has no previous-season snap-count rows | `prior_season_role_known` | yes |
| `prior_season_role_known` | depth | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `prev1_snap_share` | opportunity | feature | Float64 | share | nflreadpy | season_lagged | -1 | null without previous-season snap-count rows | - | yes |
| `prev1_offense_snaps_pg` | opportunity | feature | Float64 | snaps/game | nflreadpy | season_lagged | -1 | null without previous-season snap-count rows | - | yes |
| `prev1_games` | durability | feature | Int32 | games | nflreadpy | season_lagged | -1 | null when the player recorded no previous-season game | - | yes |
| `prev1_team_games` | durability | feature | Int32 | games | nflreadpy | season_lagged | -1 | null when no previous-season team is known | - | yes |
| `prev1_games_missed` | durability | feature | Int32 | games | nflreadpy | season_lagged | -1 | null when either component is missing | - | yes |
| `prev1_fantasy_points_std` | production | feature | Float64 | points | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_fantasy_points_ppr` | production | feature | Float64 | points | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_fantasy_ppg_std` | production | feature | Float64 | points/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_fantasy_ppg_ppr` | production | feature | Float64 | points/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_carries_pg` | opportunity | feature | Float64 | carries/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_targets_pg` | opportunity | feature | Float64 | targets/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_receptions_pg` | opportunity | feature | Float64 | rec/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_pass_attempts_pg` | opportunity | feature | Float64 | attempts/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_rushing_yards_pg` | production | feature | Float64 | yards/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_receiving_yards_pg` | production | feature | Float64 | yards/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_passing_yards_pg` | production | feature | Float64 | yards/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_total_tds_pg` | production | feature | Float64 | tds/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_target_share` | opportunity | feature | Float64 | share | nflreadpy | season_lagged | -1 | null when the player's teams recorded no targets in his games | - | yes |
| `prev1_rush_share` | opportunity | feature | Float64 | share | nflreadpy | season_lagged | -1 | null when the player's teams recorded no carries in his games | - | yes |
| `prev1_xfp_pg` | opportunity | feature | Float64 | expected points/game | ffopportunity | season_lagged | -1 | null when ffopportunity has no previous-season rows for the player | - | yes |
| `prev1_fp_over_expected_pg` | efficiency | feature | Float64 | points/game | ffopportunity | season_lagged | -1 | null when ffopportunity has no previous-season rows for the player | - | yes |
| `prev1_yards_per_carry` | efficiency | feature | Float64 | yards/carry | nflreadpy | season_lagged | -1 | null below the minimum denominator; an unstable ratio is worse than a gap | `prev1_rush_denominator_met` | yes |
| `prev1_rush_denominator_met` | efficiency | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `prev1_yards_per_target` | efficiency | feature | Float64 | yards/target | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_target_denominator_met` | yes |
| `prev1_catch_rate` | efficiency | feature | Float64 | rate | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_target_denominator_met` | yes |
| `prev1_rec_td_rate` | efficiency | feature | Float64 | rate | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_target_denominator_met` | yes |
| `prev1_target_denominator_met` | efficiency | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `prev1_rush_td_rate` | efficiency | feature | Float64 | rate | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_rush_denominator_met` | yes |
| `prev1_yards_per_attempt` | efficiency | feature | Float64 | yards/attempt | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_pass_denominator_met` | yes |
| `prev1_completion_pct` | efficiency | feature | Float64 | rate | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_pass_denominator_met` | yes |
| `prev1_pass_td_rate` | efficiency | feature | Float64 | rate | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_pass_denominator_met` | yes |
| `prev1_interception_rate` | efficiency | feature | Float64 | rate | nflreadpy | season_lagged | -1 | null below the minimum denominator | `prev1_pass_denominator_met` | yes |
| `prev1_pass_denominator_met` | efficiency | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `prev2_games` | durability | feature | Int32 | games | nflreadpy | season_lagged | -2 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev2_fantasy_ppg_ppr` | production | feature | Float64 | points/game | nflreadpy | season_lagged | -2 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev2_carries_pg` | opportunity | feature | Float64 | carries/game | nflreadpy | season_lagged | -2 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev2_targets_pg` | opportunity | feature | Float64 | targets/game | nflreadpy | season_lagged | -2 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev2_xfp_pg` | opportunity | feature | Float64 | expected points/game | ffopportunity | season_lagged | -2 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev3_games` | durability | feature | Int32 | games | nflreadpy | season_lagged | -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev3_fantasy_ppg_ppr` | production | feature | Float64 | points/game | nflreadpy | season_lagged | -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev3_carries_pg` | opportunity | feature | Float64 | carries/game | nflreadpy | season_lagged | -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev3_targets_pg` | opportunity | feature | Float64 | targets/game | nflreadpy | season_lagged | -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev3_xfp_pg` | opportunity | feature | Float64 | expected points/game | ffopportunity | season_lagged | -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `prior5_seasons` | career | feature | Int32 | seasons | nflreadpy | season_lagged | -1, -2, -3, -4, -5 | 0 for a player with no prior stat line in the window | - | yes |
| `prior5_games` | career | feature | Int32 | games | nflreadpy | season_lagged | -1, -2, -3, -4, -5 | 0 for a player with no prior stat line in the window | - | yes |
| `prior5_fantasy_ppg_ppr` | career | feature | Float64 | points/game | nflreadpy | season_lagged | -1, -2, -3, -4, -5 | missing when the player has no qualifying prior-season rows | - | yes |
| `prior5_carries_pg` | career | feature | Float64 | carries/game | nflreadpy | season_lagged | -1, -2, -3, -4, -5 | missing when the player has no qualifying prior-season rows | - | yes |
| `prior5_targets_pg` | career | feature | Float64 | targets/game | nflreadpy | season_lagged | -1, -2, -3, -4, -5 | missing when the player has no qualifying prior-season rows | - | yes |
| `recent3_fantasy_ppg_ppr_w` | career | feature | Float64 | points/game | nflreadpy | season_lagged | -1, -2, -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `recent3_targets_pg_w` | career | feature | Float64 | targets/game | nflreadpy | season_lagged | -1, -2, -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `recent3_carries_pg_w` | career | feature | Float64 | carries/game | nflreadpy | season_lagged | -1, -2, -3 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_team_pass_attempts_pg` | team_context | feature | Float64 | attempts/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_team_carries_pg` | team_context | feature | Float64 | carries/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_team_pass_yards_pg` | team_context | feature | Float64 | yards/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_team_rush_yards_pg` | team_context | feature | Float64 | yards/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `prev1_team_offense_tds_pg` | team_context | feature | Float64 | tds/game | nflreadpy | season_lagged | -1 | missing when the player has no qualifying prior-season rows | - | yes |
| `team_change_flag` | team_context | feature | Boolean | boolean | nflreadpy | pre_anchor_observation | - | null when no pre-anchor team observation exists; free agency and trades are unobservable before the 2025 snapshot era, and guessing would leak or lie | `team_change_known` | yes |
| `team_at_anchor_known` | team_context | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
| `team_change_known` | team_context | indicator | Boolean | boolean | nflreadpy | anchor_derived | - | never missing; this column *is* the missingness statement | - | yes |
