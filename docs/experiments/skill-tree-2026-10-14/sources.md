# Official field definitions used by the Skill Tree (verbatim)

Retrieved 2026-10-14 from `https://github.com/nflverse/nflreadr/tree/main/data-raw` (`dictionary_pbp.csv`, `dictionary_player_stats.json`, `dictionary_nextgenstats.csv`, `dictionary_combine.csv`, `dictionary_snap_counts.csv`), the source of the rendered pages https://nflreadr.nflverse.com/articles/dictionary_pbp.html, `dictionary_player_stats.html`, `dictionary_nextgen_stats.html` and `dictionary_combine.html`. Quoted exactly, typos included. Where the live data differs from the wording, `README.md` §1 says so (`cpoe` is in percentage points).

## Play-by-play (`load_pbp`)

Source: `dictionary_pbp.csv`

| field | official description |
|---|---|
| `season_type` | 'REG' or 'POST' indicating if the game belongs to regular or post season. |
| `play_type` | String indicating the type of play: pass (includes sacks), run (includes scrambles), punt, field_goal, kickoff, extra_point, qb_kneel, qb_spike, no_play (timeouts and penalties), and missing for rows indicating end of play. |
| `pass_attempt` | Binary indicator for if the play was a pass attempt (includes sacks). |
| `rush_attempt` | Binary indicator for if the play was a run. |
| `sack` | Binary indicator for if the play ended in a sack. |
| `qb_dropback` | Binary indicator for whether or not the QB dropped back on the play (pass attempt, sack, or scrambled). |
| `qb_scramble` | Binary indicator for whether or not the QB scrambled. |
| `two_point_attempt` | Binary indicator for two point conversion attempt. |
| `passer_player_id` | Unique identifier for the player that attempted the pass. |
| `rusher_player_id` | Unique identifier for the player that attempted the run. |
| `receiver_player_id` | Unique identifier for the receiver that was targeted on the pass. |
| `yardline_100` | Numeric distance in the number of yards from the opponent's endzone for the posteam. |
| `air_yards` | Numeric value for distance in yards perpendicular to the line of scrimmage at where the targeted receiver either caught or didn't catch the ball. |
| `yards_after_catch` | Numeric value for distance in yards perpendicular to the yard line where the receiver made the reception to where the play ended. |
| `receiving_yards` | Numeric yards by the receiver_player_name, excluding yards gained in pass plays with laterals. This should equal official receiving statistics but could miss yards gained in pass plays with laterals. Please see the description of `lateral_receiver_player_name` for further information. |
| `rushing_yards` | Numeric yards by the rusher_player_name, excluding yards gained in rush plays with laterals. This should equal official rushing statistics but could miss yards gained in rush plays with laterals. Please see the description of `lateral_rusher_player_name` for further information. |
| `complete_pass` | Binary indicator for if the pass was completed. |
| `epa` | Expected points added (EPA) by the posteam for the given play. |
| `qb_epa` | Gives QB credit for EPA for up to the point where a receiver lost a fumble after a completed catch and makes EPA work more like passing yards on plays with fumbles. |
| `success` | Binary indicator wheter epa > 0 in the given play. |
| `cpoe` | For a single pass play this is 1 - cp when the pass was completed or 0 - cp when the pass was incomplete. Analyzed for a whole game or season an indicator for the passer how much over or under expectation his completion percentage was. |

## Player stats (`load_player_stats`, week level)

Source: `dictionary_player_stats.json`

| field | official description |
|---|---|
| `player_id` | Player's gsis_id. Use this to join to other sources, e.g. load_players(). |
| `season_type` | `REG` for regular season, `POST` for postseason |
| `attempts` | The number of pass attempts as defined by the NFL. |
| `completions` | The number of completed passes. |
| `passing_yards` | Yards gained on pass plays. |
| `passing_tds` | The number of passing touchdowns. |
| `passing_interceptions` | Number of passing interceptions |
| `sacks_suffered` | Number of sacks taken as a QB |
| `passing_air_yards` | Passing air yards (includes incomplete passes). |
| `passing_epa` | Total expected points added on pass attempts and sacks. NOTE: this uses the variable `qb_epa`, which gives QB credit for EPA for up to the point where a receiver lost a fumble after a completed catch and makes EPA work more like passing yards on plays with fumbles. |
| `passing_cpoe` | Completion percentage over expected for this player. |
| `carries` | The number of official rush attempts (incl. scrambles and kneel downs). Rushes after a lateral reception don't count as carry. |
| `rushing_yards` | Yards gained when rushing with the ball (incl. scrambles and kneel downs). Also includes yards gained after obtaining a lateral on a play that started with a rushing attempt. |
| `rushing_tds` | The number of rushing touchdowns (incl. scrambles). Also includes touchdowns after obtaining a lateral on a play that started with a rushing attempt. |
| `targets` | The number of pass plays where the player was the targeted receiver. |
| `receptions` | The number of pass receptions. Lateral receptions officially don't count as reception. |
| `receiving_yards` | Yards gained after a pass reception. Includes yards gained after receiving a lateral on a play that started as a pass play. |
| `receiving_tds` | The number of touchdowns following a pass reception. Also includes touchdowns after receiving a lateral on a play that started as a pass play. |
| `receiving_air_yards` | Receiving air yards (incl. incomplete passes). |
| `receiving_yards_after_catch` | Yards after the catch gained on plays in which player was receiver (this is an unofficial stat and may differ slightly between different sources). |
| `target_share` | Player's share of team receiving targets in this game |
| `air_yards_share` | Player's share of the team's air yards in this game |

## Next Gen Stats (`load_nextgen_stats`)

Source: `dictionary_nextgenstats.csv`

| field | official description |
|---|---|
| `season_type` | Either "REG" or "POST" |
| `week` | The week of the NFL season the game occurs in. Please note that the `game_type` will differ for weeks = 18 because of the season expansion in 2021. Please use `game_type` to filter for regular season or postseason |
| `player_gsis_id` | Unique identifier of the player |
| `player_position` | Position of the player accordinng to NGS |
| `attempts` | The number of pass attempts |
| `avg_time_to_throw` | Average time elapsed from the time of snap to throw on every pass attempt for a passer (sacks excluded). |
| `rush_attempts` | The number of rushing attempts |
| `rush_yards_over_expected_per_att` | Average rush yards above expectation |
| `targets` | The numnber of targets for the receiver |
| `receptions` | The number of receptions for the receiver |
| `avg_separation` | The distance (in yards) measured between a WR/TE and the nearest defender at the time of catch or incompletion. |
| `avg_cushion` | The distance (in yards) measured between a WR/TE and the defender they're lined up against at the time of snap on all targets. |
| `avg_yac_above_expectation` | A receiver's YAC compared to their Expected YAC. |

## Combine (`load_combine`)

Source: `dictionary_combine.csv`

| field | official description |
|---|---|
| `season` | 4 digit number indicating which season(s) the specified combine occurred. |
| `pfr_id` | Pro-Football-Reference ID for player |
| `pos` | Position of player |
| `forty` | Player's 40 yard dash time at combine (seconds) |

## Snap counts (`load_snap_counts`)

Source: `dictionary_snap_counts.csv`

| field | official description |
|---|---|
| `game_type` | Type of game (regular or postseason) |
| `pfr_player_id` | Player PFR ID |
| `offense_snaps` | Number of snaps on offense |
| `offense_pct` | Percent of offensive snaps taken |

NGS loader documentation (`R/load_nextgen_stats.R`): "Regular season summary is given for `week == 0`."
