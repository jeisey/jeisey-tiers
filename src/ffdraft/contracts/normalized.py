"""Concrete frame contracts for every normalized source dataset.

Centralising the column names here is what `AGENTS.md` section 12 means by avoiding
"stringly typed" coupling: an adapter, a test and a downstream stage all refer to the same
constant, so a rename is one edit rather than a hunt through string literals.

Bump a contract's ``version`` whenever its output shape changes, and update the adapter
that produces it in the same change (AGENTS.md section 18).
"""

from __future__ import annotations

import polars as pl

from ffdraft.contracts.frames import ColumnSpec, FrameContract

__all__ = [
    "CANONICAL_PLAYER_CONTRACT",
    "COMBINE_CONTRACT",
    "DEPTH_CHART_CONTRACT",
    "DRAFT_PICK_CONTRACT",
    "EXPECTED_POINTS_CONTRACT",
    "MARKET_QUOTE_CONTRACT",
    "MFL_PLAYER_CONTRACT",
    "PLAYER_IDS_CONTRACT",
    "PLAYER_MASTER_CONTRACT",
    "PLAYER_STATUS_CONTRACT",
    "RESOLUTION_CONTRACT",
    "ROSTER_CONTRACT",
    "SCHEDULE_CONTRACT",
    "SNAP_COUNTS_CONTRACT",
    "WEEKLY_STATS_CONTRACT",
]

_UTC = pl.Datetime(time_unit="us", time_zone="UTC")


# The seasonal roster's grain is one row per player *per team*: a player traded mid-season
# appears once for each club he was rostered by. Phase 1 keyed it `(season, gsis_id)` because
# the 2026 fixture had no such player; the historical seasons do - 99 in 2014, 125 in 2015 -
# so the key names the team as well (contract 1.1). Downstream consumers that want one row
# per player must say which one they want rather than relying on the key to have deduplicated.
ROSTER_CONTRACT = FrameContract(
    contract_id="nflverse_roster",
    version="1.1",
    primary_key=("season", "gsis_id", "team"),
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False, description="Roster season"),
        ColumnSpec("gsis_id", pl.String, nullable=False, description="Canonical nflverse id"),
        ColumnSpec("display_name", pl.String, nullable=False),
        ColumnSpec("position", pl.String, nullable=False, description="Raw source position"),
        ColumnSpec("team", pl.String),
        ColumnSpec("status", pl.String, description="ACT/RES/CUT/... as published"),
        ColumnSpec("depth_chart_position", pl.String),
        ColumnSpec("espn_id", pl.String, description="Primary market bridge (ADR-019)"),
        ColumnSpec("sleeper_id", pl.String, description="Join direction: nflverse -> Sleeper"),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("sportradar_id", pl.String),
        ColumnSpec("yahoo_id", pl.String),
        ColumnSpec("birth_date", pl.Date),
        ColumnSpec("years_exp", pl.Int32),
        ColumnSpec("rookie_season", pl.Int32),
    ),
)


# The dynastyprocess crosswalk mirror. `mfl_id` is the only column Phase 0 measured at 100%
# coverage, which is why it is the key and why this source is the *secondary* market bridge:
# the mirror publishes no licence, so nflverse-native ids are preferred where both exist.
PLAYER_IDS_CONTRACT = FrameContract(
    contract_id="nflverse_ff_playerids",
    version="1.0",
    primary_key=("mfl_id",),
    columns=(
        ColumnSpec("mfl_id", pl.String, nullable=False),
        ColumnSpec("gsis_id", pl.String),
        ColumnSpec("espn_id", pl.String),
        ColumnSpec("sleeper_id", pl.String),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("sportradar_id", pl.String),
        ColumnSpec("yahoo_id", pl.String),
        ColumnSpec("name", pl.String),
        ColumnSpec("position", pl.String),
        ColumnSpec("team", pl.String),
    ),
)


CANONICAL_PLAYER_CONTRACT = FrameContract(
    contract_id="canonical_player",
    version="1.0",
    primary_key=("player_id",),
    columns=(
        ColumnSpec("player_id", pl.String, nullable=False, description="Namespaced canonical key"),
        ColumnSpec("display_name", pl.String, nullable=False),
        ColumnSpec("position", pl.String, nullable=False),
        ColumnSpec("team", pl.String),
        ColumnSpec("status", pl.String),
        ColumnSpec("entity_kind", pl.String, nullable=False),
        ColumnSpec("gsis_id", pl.String),
        ColumnSpec("espn_id", pl.String),
        ColumnSpec("sleeper_id", pl.String),
        ColumnSpec("mfl_id", pl.String),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("sportradar_id", pl.String),
        ColumnSpec("yahoo_id", pl.String),
        ColumnSpec("birth_date", pl.Date),
        ColumnSpec("years_exp", pl.Int32),
        ColumnSpec("rookie_season", pl.Int32),
        ColumnSpec("source_ids", pl.String, description="Comma-joined contributing sources"),
    ),
)


PLAYER_STATUS_CONTRACT = FrameContract(
    contract_id="sleeper_player_status",
    version="1.0",
    primary_key=("source_id", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("observed_at_utc", _UTC, nullable=False),
        ColumnSpec("team", pl.String),
        ColumnSpec("status", pl.String),
        ColumnSpec("injury_status", pl.String),
        ColumnSpec("injury_body_part", pl.String),
        ColumnSpec("practice_participation", pl.String),
        ColumnSpec("depth_chart_position", pl.String),
        ColumnSpec("depth_chart_order", pl.Int32),
        ColumnSpec("reported_gsis_id", pl.String, description="Cross-check only, never a key"),
        ColumnSpec("quality_flags", pl.String),
    ),
)


DEPTH_CHART_CONTRACT = FrameContract(
    contract_id="nflverse_depth_chart",
    version="1.0",
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("era", pl.String, nullable=False, description="ADR-015 schema era"),
        ColumnSpec("team", pl.String, nullable=False),
        ColumnSpec("position", pl.String),
        ColumnSpec("depth_rank", pl.Int32),
        ColumnSpec("gsis_id", pl.String),
        ColumnSpec("espn_id", pl.String),
        ColumnSpec("player_name", pl.String),
        ColumnSpec("observed_at_utc", _UTC, description="Snapshot era only"),
        ColumnSpec("week", pl.Int32, description="Weekly era only"),
    ),
)


MARKET_QUOTE_CONTRACT = FrameContract(
    contract_id="market_quote",
    version="1.0",
    primary_key=("source_id", "season", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("average_pick", pl.Float64, nullable=False),
        ColumnSpec("market_rank", pl.Int32),
        ColumnSpec("min_pick", pl.Float64),
        ColumnSpec("max_pick", pl.Float64),
        ColumnSpec("sample_size", pl.Int32),
        ColumnSpec("selection_pct", pl.Float64),
        ColumnSpec("retrieved_at_utc", _UTC, nullable=False),
        ColumnSpec("source_as_of_utc", _UTC, description="Null for MFL: no data-as-of time"),
        ColumnSpec("entity_kind", pl.String, nullable=False),
        ColumnSpec("raw_position", pl.String),
        ColumnSpec("scoring_preset", pl.String, nullable=False),
        ColumnSpec("league_size", pl.Int32, nullable=False),
        ColumnSpec("cohort_approximate", pl.Boolean, nullable=False),
        ColumnSpec("source_format_detail", pl.String, nullable=False),
        ColumnSpec("quality_flags", pl.String),
    ),
)


# MFL's player database. It carries no `gsis_id` at all (Phase 0: 0% coverage), which is why
# `espn_id` is the bridge and why every row's entity kind has to be classified here: the
# export mixes real players with team aggregates such as `TMWR` and `Def`.
MFL_PLAYER_CONTRACT = FrameContract(
    contract_id="mfl_player_directory",
    version="1.0",
    primary_key=("mfl_id",),
    columns=(
        ColumnSpec("mfl_id", pl.String, nullable=False),
        ColumnSpec("name", pl.String),
        ColumnSpec("raw_position", pl.String),
        ColumnSpec("team", pl.String),
        ColumnSpec("espn_id", pl.String, description="Primary market bridge"),
        ColumnSpec("entity_kind", pl.String, nullable=False),
    ),
)


RESOLUTION_CONTRACT = FrameContract(
    contract_id="identity_resolution",
    version="1.0",
    primary_key=("source_id", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("status", pl.String, nullable=False),
        ColumnSpec("player_id", pl.String),
        ColumnSpec("reason", pl.String, nullable=False),
        ColumnSpec("entity_kind", pl.String, nullable=False),
        ColumnSpec("bridges_agreed", pl.String),
        ColumnSpec("bridges_disagreed", pl.String),
        ColumnSpec("name_candidates", pl.String),
        ColumnSpec("quality_flags", pl.String),
    ),
)


# --------------------------------------------------------------------------------------
# Phase-2 historical source contracts
# --------------------------------------------------------------------------------------
#
# These normalize the nflverse loaders the historical feature builder reads. Two naming
# decisions are load-bearing:
#
# * the scorable columns are named exactly as `ffdraft.scoring.engine.STAT_COMPONENTS`
#   expects, so the scoring engine consumes a weekly frame directly rather than through a
#   rename that could silently map the wrong column;
# * nflverse's own fantasy-point columns are prefixed `upstream_`, because
#   `docs/MODELING.md` section 3 makes them a sanity comparison and never the label. A name
#   that reads like ours would invite exactly the substitution the specification forbids.


WEEKLY_STATS_CONTRACT = FrameContract(
    contract_id="nflverse_weekly_player_stats",
    version="1.0",
    primary_key=("season", "week", "season_type", "gsis_id"),
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("week", pl.Int32, nullable=False),
        ColumnSpec("season_type", pl.String, nullable=False, description="REG or POST"),
        ColumnSpec("gsis_id", pl.String, nullable=False),
        ColumnSpec("display_name", pl.String),
        ColumnSpec("position", pl.String),
        ColumnSpec("team", pl.String),
        ColumnSpec("opponent_team", pl.String),
        ColumnSpec("pass_attempts", pl.Float64),
        ColumnSpec("completions", pl.Float64),
        ColumnSpec("passing_yards", pl.Float64),
        ColumnSpec("passing_tds", pl.Float64),
        ColumnSpec("interceptions", pl.Float64),
        ColumnSpec("passing_air_yards", pl.Float64),
        ColumnSpec("carries", pl.Float64),
        ColumnSpec("rushing_yards", pl.Float64),
        ColumnSpec("rushing_tds", pl.Float64),
        ColumnSpec("targets", pl.Float64),
        ColumnSpec("receptions", pl.Float64),
        ColumnSpec("receiving_yards", pl.Float64),
        ColumnSpec("receiving_tds", pl.Float64),
        ColumnSpec("receiving_air_yards", pl.Float64),
        ColumnSpec("fumbles_lost", pl.Float64, description="rushing + receiving + sack fumbles"),
        ColumnSpec("two_point_conversions", pl.Float64, description="pass + rush + rec 2pt"),
        ColumnSpec("upstream_fantasy_points_std", pl.Float64, description="sanity check only"),
        ColumnSpec("upstream_fantasy_points_ppr", pl.Float64, description="sanity check only"),
        ColumnSpec("upstream_fumbles_lost_total", pl.Float64, description="sanity check only"),
        ColumnSpec(
            "upstream_special_teams_tds",
            pl.Float64,
            description="return touchdowns; not scored (see ffdraft.scoring.engine), sanity only",
        ),
    ),
)


SNAP_COUNTS_CONTRACT = FrameContract(
    contract_id="nflverse_snap_counts",
    version="1.0",
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("week", pl.Int32, nullable=False),
        ColumnSpec("game_type", pl.String, nullable=False),
        ColumnSpec("pfr_player_id", pl.String, nullable=False),
        ColumnSpec("player_name", pl.String),
        ColumnSpec("position", pl.String),
        ColumnSpec("team", pl.String),
        ColumnSpec("offense_snaps", pl.Float64),
        ColumnSpec("offense_pct", pl.Float64, description="share of team offensive snaps, 0-1"),
    ),
)


SCHEDULE_CONTRACT = FrameContract(
    contract_id="nflverse_schedule",
    version="1.0",
    primary_key=("game_id",),
    columns=(
        ColumnSpec("game_id", pl.String, nullable=False),
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("game_type", pl.String, nullable=False),
        ColumnSpec("week", pl.Int32, nullable=False),
        ColumnSpec("gameday", pl.Date),
        ColumnSpec("gametime", pl.String, description="kickoff HH:MM, America/New_York"),
        ColumnSpec("away_team", pl.String),
        ColumnSpec("home_team", pl.String),
    ),
)


# Only draft-time facts are normalized. `load_draft_picks` also publishes career outcomes
# (games, car_av, allpro, probowls, hof, seasons_started, career passing/rushing/receiving
# totals); every one of those is knowledge from *after* the draft, so they are excluded at
# the contract boundary rather than filtered later where an accidental select could readmit
# them.
DRAFT_PICK_CONTRACT = FrameContract(
    contract_id="nflverse_draft_picks",
    version="1.0",
    columns=(
        ColumnSpec("draft_year", pl.Int32, nullable=False),
        ColumnSpec("draft_round", pl.Int32),
        ColumnSpec("draft_overall", pl.Int32, description="overall pick number"),
        ColumnSpec("gsis_id", pl.String),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("player_name", pl.String),
        ColumnSpec("position", pl.String),
        ColumnSpec("draft_team", pl.String),
        ColumnSpec("college", pl.String),
    ),
)


COMBINE_CONTRACT = FrameContract(
    contract_id="nflverse_combine",
    version="1.0",
    columns=(
        ColumnSpec("combine_year", pl.Int32, nullable=False),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("player_name", pl.String),
        ColumnSpec("position", pl.String),
        ColumnSpec("height_in", pl.Float64),
        ColumnSpec("weight_lb", pl.Float64),
        ColumnSpec("forty", pl.Float64),
        ColumnSpec("bench", pl.Float64),
        ColumnSpec("vertical", pl.Float64),
        ColumnSpec("broad_jump", pl.Float64),
        ColumnSpec("cone", pl.Float64),
        ColumnSpec("shuttle", pl.Float64),
    ),
)


# The player master supplies biographical facts only. `status`, `latest_team`,
# `last_season` and `years_of_experience` describe the player *now*, not at any historical
# anchor, so they are absent from this contract by design: a column that cannot be selected
# cannot leak into a 2016 feature row.
PLAYER_MASTER_CONTRACT = FrameContract(
    contract_id="nflverse_player_master",
    version="1.0",
    primary_key=("gsis_id",),
    columns=(
        ColumnSpec("gsis_id", pl.String, nullable=False),
        ColumnSpec("display_name", pl.String),
        ColumnSpec("position", pl.String),
        ColumnSpec("birth_date", pl.Date),
        ColumnSpec("height_in", pl.Float64),
        ColumnSpec("weight_lb", pl.Float64),
        ColumnSpec("pfr_id", pl.String),
        ColumnSpec("espn_id", pl.String),
        ColumnSpec("college_name", pl.String),
    ),
)


# ffopportunity attributes expected points per position, and a two-way player can receive a
# row under each - `00-0028079` appears in 2013 as both TE and OLB. The key therefore names
# the position; :func:`ffdraft.features.lagged.expected_points_by_season` reduces to one row
# per player-week deterministically rather than summing the split attributions.
EXPECTED_POINTS_CONTRACT = FrameContract(
    contract_id="ffopportunity_expected_points",
    version="1.1",
    primary_key=("season", "week", "gsis_id", "position"),
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("week", pl.Int32, nullable=False),
        ColumnSpec("gsis_id", pl.String, nullable=False),
        ColumnSpec("position", pl.String),
        ColumnSpec("team", pl.String),
        ColumnSpec("expected_points", pl.Float64, description="total_fantasy_points_exp"),
        ColumnSpec("expected_pass_points", pl.Float64),
        ColumnSpec("expected_rush_points", pl.Float64),
        ColumnSpec("expected_rec_points", pl.Float64),
        ColumnSpec("expected_receptions", pl.Float64),
        ColumnSpec("actual_points", pl.Float64, description="ffopportunity's own actual"),
        ColumnSpec("points_over_expected", pl.Float64),
    ),
)
