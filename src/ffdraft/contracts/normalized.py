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
    "SLEEPER_BEHAVIOR_CONTRACT",
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


# Contract 1.1 adds the three optional injury/practice fields the verified Sleeper schema
# publishes and 1.0 did not read (ADR-043). All three are nullable: Sleeper omits them for
# healthy players, and a required field would have to be fabricated.
PLAYER_STATUS_CONTRACT = FrameContract(
    contract_id="sleeper_player_status",
    version="1.1",
    primary_key=("source_id", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("observed_at_utc", _UTC, nullable=False),
        ColumnSpec("team", pl.String),
        ColumnSpec("status", pl.String),
        ColumnSpec("injury_status", pl.String),
        ColumnSpec("injury_body_part", pl.String),
        ColumnSpec("injury_notes", pl.String),
        ColumnSpec("injury_start_date", pl.String, description="As published; often absent"),
        ColumnSpec("practice_participation", pl.String),
        ColumnSpec("practice_description", pl.String),
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


# A quote belongs to a *cohort request*, not to a league preset. Contract 1.0 carried
# `scoring_preset`, `league_size` and `cohort_approximate`, which forced an unfiltered
# aggregate to claim a preset it did not describe. Contract 2.0 records `cohort_id`
# instead; mapping cohorts onto presets is `ffdraft.market.cohorts`' job and its verdict
# (exact or approximate) is per assignment, not per row (ADR-039).
#
# Contract 3.0 generalises the same row across three sources without erasing what each
# number means (Phase 10, roadmap 10.3, ADR-062). Five columns are new and every one of them
# exists because two sources disagree about something the old contract could not express:
#
# * `market_signal_type` — MyFantasyLeague and FFC publish a *price*; FantasyPros publishes
#   a price and an *expert ranking*. They are different measurements, so the row says which
#   it is and the cross-market aggregate filters on it. This is the column that makes "ECR
#   never masquerades as ADP" checkable rather than aspirational.
# * `scoring_preset` / `league_size` — the cohort's *observed* dimensions, copied from
#   `MarketCohort` semantics and null when the source does not constrain that axis. FFC
#   accepts `teams=` and ignores it (ADR-056), so its `league_size` is null: a board may not
#   claim a league size the API does not substantiate, and the null is the claim's absence.
# * `aggregation_window_type` / `aggregation_window_days` — MFL aggregates the season to
#   date, FFC a bounded recent window. Both are "ADP". A product that showed them side by
#   side without saying which was which would be inviting the reader to average them.
# * `adp_sd` — a genuine per-player standard deviation, which FFC publishes and MFL does
#   not. It is deliberately NOT the same column as `min_pick`/`max_pick`: those are extreme
#   order statistics that widen with sample size, and relabelling one as the other is a data
#   error rather than a presentation choice.
#
# `average_pick` becomes nullable because an ECR row has no average pick. The name is kept
# rather than renamed to `market_adp`: the retained private store holds a season of
# snapshots whose normalized rows use it, and the trend window reads them. A rename would
# have made every historical capture unreadable to buy a tidier column name.
#
# `market_signal_type` joins the primary key. FantasyPros serves ADP and ECR for the same
# season and cohort, and without it the two would collide on one row.
MARKET_QUOTE_CONTRACT = FrameContract(
    contract_id="market_quote",
    version="3.0",
    primary_key=("source_id", "season", "cohort_id", "market_signal_type", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("cohort_id", pl.String, nullable=False),
        ColumnSpec(
            "market_signal_type",
            pl.String,
            nullable=False,
            description="adp | ecr - see contracts.enums.MarketSignalType",
        ),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("average_pick", pl.Float64, description="The ADP. Null on an ECR row."),
        ColumnSpec("market_rank", pl.Int32),
        ColumnSpec("min_pick", pl.Float64, description="Extreme order statistic, not an SD"),
        ColumnSpec("max_pick", pl.Float64, description="Extreme order statistic, not an SD"),
        ColumnSpec("adp_sd", pl.Float64, description="Genuine per-player SD where published"),
        # An expert consensus has a dispersion too, and it is measured in RANKS, not picks.
        # FantasyPros publishes `rank_ave`, `rank_min`, `rank_max` and `rank_std` across
        # ninety-odd experts. Writing those into `min_pick`/`max_pick`/`adp_sd` would put an
        # expert-rank spread under a column named after a draft pick — the exact relabelling
        # roadmap 10.3 forbids when it says a source ADP must retain its source identity.
        # ADP rows leave these null; ECR rows leave the pick columns null.
        ColumnSpec("consensus_rank_mean", pl.Float64, description="ECR only: mean expert rank"),
        ColumnSpec("consensus_rank_min", pl.Int32, description="ECR only: best expert rank"),
        ColumnSpec("consensus_rank_max", pl.Int32, description="ECR only: worst expert rank"),
        ColumnSpec("consensus_rank_sd", pl.Float64, description="ECR only: SD of expert ranks"),
        ColumnSpec(
            "sample_size",
            pl.Int32,
            description="Observations behind the quote: drafts for ADP, experts for ECR",
        ),
        ColumnSpec("selection_pct", pl.Float64),
        ColumnSpec("scoring_preset", pl.String, description="Observed, or null if unconstrained"),
        ColumnSpec("league_size", pl.Int32, description="Observed, or null if not claimable"),
        ColumnSpec(
            "aggregation_window_type",
            pl.String,
            nullable=False,
            description="rolling | season_cumulative | not_applicable | unknown",
        ),
        ColumnSpec("aggregation_window_days", pl.Int32, description="Null unless documented"),
        ColumnSpec("retrieved_at_utc", _UTC, nullable=False),
        ColumnSpec("source_as_of_utc", _UTC, description="Null for MFL: no data-as-of time"),
        ColumnSpec("entity_kind", pl.String, nullable=False),
        ColumnSpec("raw_position", pl.String),
        ColumnSpec("source_display_name", pl.String, description="As published; linkage input"),
        ColumnSpec("source_team", pl.String, description="As published; a linkage diagnostic"),
        ColumnSpec("source_format_detail", pl.String, nullable=False),
        ColumnSpec("quality_flags", pl.String),
    ),
)


# Waiver behaviour is not a draft price, and roadmap 10.3 refuses to let it become one by
# sharing a schema. An add count has no pick number, no dispersion, no cohort and no scoring
# preset; forcing it into `market_quote` would have left two thirds of that row null and
# invited a chart that plotted adds on an ADP axis.
#
# Phase 10 starts retaining these so Phase 12 inherits real in-season history rather than
# beginning from zero after kickoff. Nothing consumes them yet, which is the point: the
# append-only store has to be *started* before the season it describes.
SLEEPER_BEHAVIOR_CONTRACT = FrameContract(
    contract_id="sleeper_behavior_snapshot",
    version="1.0",
    primary_key=("source_id", "behavior_type", "external_player_id"),
    columns=(
        ColumnSpec("source_id", pl.String, nullable=False),
        ColumnSpec(
            "behavior_type",
            pl.String,
            nullable=False,
            description="add | drop - see contracts.enums.BehaviorType",
        ),
        ColumnSpec("external_player_id", pl.String, nullable=False),
        ColumnSpec("count", pl.Int32, nullable=False, description="Adds or drops in the window"),
        ColumnSpec(
            "lookback_hours",
            pl.Int32,
            nullable=False,
            description="The window REQUESTED. Whether it is honoured is measured, not assumed.",
        ),
        ColumnSpec("request_limit", pl.Int32, nullable=False, description="The `limit` sent"),
        ColumnSpec("snapshot_at_utc", _UTC, nullable=False),
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
