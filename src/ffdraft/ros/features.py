"""The in-season feature block.

Every column here is a cumulative or windowed read of :mod:`ffdraft.ros.panel` restricted to
weeks at or before the snapshot cutoff. The restriction is structural rather than
conventional: the builder computes running quantities in week order and reads them *at* the
cutoff row, so there is no expression in the module that could reach forward even by
accident. :mod:`ffdraft.ros.leakage` proves it by deleting the post-cutoff weeks and
re-deriving.

Three implementation notes are decisions rather than mechanics.

**Team context is accumulated over the weeks the player actually played.** A share is
``his volume / his team's volume in the same games``, so a player who missed six weeks is
compared against the six games he was there for, not against a team-season he had no part in.

**Rate features have declared minimum denominators.** Yards per target on two targets is
noise wearing a number's clothes; below the floor declared in :mod:`ffdraft.ros.dictionary`
the column is null, and null goes to LightGBM as "unknown" rather than as a made-up mean.

**A player with no appearances yet keeps his row.** Every rate is null, every count is zero,
``has_played_this_season`` is false, and the preseason block carries the whole signal. Those
rows are the ones an in-season model is worst at, so they are reported as their own slice
rather than dropped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.ros.cutoff import FIRST_THROUGH_WEEK
from ffdraft.ros.dictionary import ROS_FEATURE_SCHEMA_VERSION
from ffdraft.ros.labels import cumulative_columns
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "RECENT_WINDOW_WEEKS",
    "build_in_season_features",
    "team_schedule_weeks",
]

#: The short-form window. Three weeks is one bye-length gap and matches the recency block
#: Phase 2 already uses across seasons; it is declared here so "recent" means one thing.
RECENT_WINDOW_WEEKS = 3

_MIN_TARGETS = 5
_MIN_CARRIES = 5
_MIN_OPPORTUNITIES = 10

_NEGATIVE_SENTINEL = -1.0e30

#: Weekly columns accumulated to date. Each becomes ``to_date_<name>``.
_ACCUMULATED: tuple[str, ...] = (
    "played",
    "pass_attempts",
    "completions",
    "carries",
    "targets",
    "receptions",
    "rushing_yards",
    "receiving_yards",
    "receiving_air_yards",
    "passing_tds",
    "rushing_tds",
    "receiving_tds",
    "snap_pct_played",
    "snap_games",
    "expected_points_played",
    "expected_games",
    "team_targets_played",
    "team_carries_played",
    "team_pass_attempts_played",
    "team_points_std_played",
    "team_games_played",
)

#: Weekly columns also summed over the trailing window.
_WINDOWED: tuple[str, ...] = (
    "played",
    "targets",
    "team_targets_played",
    "snap_pct_played",
    "snap_games",
)


def team_schedule_weeks(schedule: pl.DataFrame, seasons: Sequence[int]) -> pl.DataFrame:
    """Per ``(season, team, week)`` scheduled regular-season games inside the horizon.

    The schedule is published before Week 1 and records no outcome, so it is available at
    every cutoff. It is what turns "eleven weeks left" into "ten games left" for a team whose
    bye is still ahead.
    """
    wanted = [int(season) for season in seasons]
    empty = pl.DataFrame(
        schema={"season": pl.Int32, "team": pl.String, "week": pl.Int32, "scheduled": pl.Int32},
    )
    if schedule.is_empty() or not wanted:
        return empty
    in_horizon = pl.lit(False)
    for season in wanted:
        horizon = fantasy_horizon(season)
        in_horizon = in_horizon | (
            (pl.col("season") == season)
            & (pl.col("week") >= horizon.first_week)
            & (pl.col("week") <= horizon.last_week)
        )
    games = schedule.filter(
        pl.col("season").is_in(wanted) & (pl.col("game_type") == "REG") & in_horizon,
    )
    if games.is_empty():
        return empty
    sides = pl.concat(
        [
            games.select("season", "week", pl.col("home_team").alias("team")),
            games.select("season", "week", pl.col("away_team").alias("team")),
        ],
    ).filter(pl.col("team").is_not_null())
    return (
        sides.group_by("season", "team", "week")
        .agg(pl.len().cast(pl.Int32).alias("scheduled"))
        .sort("season", "team", "week")
    )


def _weekly_derived(panel: pl.DataFrame) -> pl.DataFrame:
    """Per-week quantities the accumulators need, all zero-or-null on an unplayed week."""
    played = pl.col("played") == 1
    return panel.with_columns(
        pl.when(played & pl.col("offense_pct").is_not_null())
        .then(pl.col("offense_pct"))
        .otherwise(0.0)
        .alias("snap_pct_played"),
        pl.when(played & pl.col("offense_pct").is_not_null())
        .then(1.0)
        .otherwise(0.0)
        .alias("snap_games"),
        pl.when(played & pl.col("expected_points").is_not_null())
        .then(pl.col("expected_points"))
        .otherwise(0.0)
        .alias("expected_points_played"),
        pl.when(played & pl.col("expected_points").is_not_null())
        .then(1.0)
        .otherwise(0.0)
        .alias("expected_games"),
        pl.when(played)
        .then(pl.col("team_targets").fill_null(0.0))
        .otherwise(0.0)
        .alias("team_targets_played"),
        pl.when(played)
        .then(pl.col("team_carries").fill_null(0.0))
        .otherwise(0.0)
        .alias("team_carries_played"),
        pl.when(played)
        .then(pl.col("team_pass_attempts").fill_null(0.0))
        .otherwise(0.0)
        .alias("team_pass_attempts_played"),
        pl.when(played)
        .then(pl.col("team_points_std").fill_null(0.0))
        .otherwise(0.0)
        .alias("team_points_std_played"),
        pl.when(played).then(1.0).otherwise(0.0).alias("team_games_played"),
    )


def _point_in_time_identity(frame: pl.DataFrame) -> pl.DataFrame:
    """Team, position, last-appearance week and team changes, all carried forward only."""
    ordered = frame.sort("season", "gsis_id", "week")
    played = pl.col("played") == 1
    with_carry = ordered.with_columns(
        pl.when(played)
        .then(pl.col("team"))
        .otherwise(None)
        .forward_fill()
        .over("season", "gsis_id")
        .alias("team_to_date"),
        pl.when(played)
        .then(pl.col("position"))
        .otherwise(None)
        .forward_fill()
        .over("season", "gsis_id")
        .alias("position_to_date"),
        pl.when(played)
        .then(pl.col("week"))
        .otherwise(None)
        .forward_fill()
        .over("season", "gsis_id")
        .alias("last_played_week"),
    )
    return with_carry.with_columns(
        (
            pl.col("team_to_date").ne_missing(
                pl.col("team_to_date").shift(1).over("season", "gsis_id"),
            )
            & pl.col("team_to_date").is_not_null()
            & pl.col("team_to_date").shift(1).over("season", "gsis_id").is_not_null()
        )
        .cast(pl.Int32)
        .cum_sum()
        .over("season", "gsis_id")
        .alias("team_changes_to_date"),
    )


def _ratio(numerator: pl.Expr, denominator: pl.Expr, *, minimum: float) -> pl.Expr:
    """A rate that is null rather than wrong when its denominator is too thin."""
    return pl.when(denominator >= minimum).then(numerator / denominator).otherwise(None)


def build_in_season_features(
    panel: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    *,
    schedule: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Build the ``(season, through_week, gsis_id, scoring_preset)`` in-season feature block."""
    if panel.is_empty():
        return pl.DataFrame(
            schema={
                "season": pl.Int32,
                "through_week": pl.Int32,
                "gsis_id": pl.String,
                "scoring_preset": pl.String,
            },
        )

    presets = sorted(scoring)
    point_columns = [f"fantasy_points_{preset}" for preset in presets]

    derived = _weekly_derived(panel)
    derived = derived.with_columns(
        [pl.col(name).pow(2).alias(f"{name}_sq") for name in point_columns],
    )
    identity = _point_in_time_identity(derived)

    accumulate = [*_ACCUMULATED, *point_columns, *(f"{name}_sq" for name in point_columns)]
    accumulated = cumulative_columns(identity, accumulate)

    windowed = accumulated.with_columns(
        [
            pl.col(name)
            .rolling_sum(window_size=RECENT_WINDOW_WEEKS, min_samples=1)
            .over("season", "gsis_id")
            .alias(f"recent_{name}")
            for name in (*_WINDOWED, *point_columns)
        ],
    )
    windowed = windowed.with_columns(
        [
            pl.when(pl.col("played") == 1)
            .then(pl.col(name))
            .otherwise(_NEGATIVE_SENTINEL)
            .cum_max()
            .over("season", "gsis_id")
            .alias(f"best_{name}")
            for name in point_columns
        ],
    )

    seasons = sorted({int(value) for value in windowed.get_column("season").unique()})
    last_modelled = {season: fantasy_horizon(season).last_week - 1 for season in seasons}
    horizon_last = {season: fantasy_horizon(season).last_week for season in seasons}
    horizon_length = {season: fantasy_horizon(season).week_count for season in seasons}

    scoped = windowed.filter(
        (pl.col("week") >= FIRST_THROUGH_WEEK)
        & (pl.col("week") <= pl.col("season").replace_strict(last_modelled, return_dtype=pl.Int32)),
    )
    scoped = _attach_remaining_schedule(scoped, schedule, seasons, horizon_last)

    shared = _shared_columns(scoped, horizon_last, horizon_length)
    frames = [_preset_columns(shared, preset) for preset in presets]
    stacked = pl.concat(frames)
    return stacked.sort("season", "through_week", "scoring_preset", "gsis_id")


def _attach_remaining_schedule(
    scoped: pl.DataFrame,
    schedule: pl.DataFrame | None,
    seasons: Sequence[int],
    horizon_last: Mapping[int, int],
) -> pl.DataFrame:
    """Games the observed team still has inside the horizon after the cutoff."""
    if schedule is None:
        return scoped.with_columns(
            pl.lit(None, dtype=pl.Int32).alias("team_remaining_scheduled_games"),
        )
    weeks = team_schedule_weeks(schedule, seasons)
    if weeks.is_empty():
        return scoped.with_columns(
            pl.lit(None, dtype=pl.Int32).alias("team_remaining_scheduled_games"),
        )
    totals = weeks.group_by("season", "team").agg(
        pl.col("scheduled").sum().cast(pl.Int32).alias("team_scheduled_total"),
    )
    through = (
        weeks.sort("season", "team", "week")
        .with_columns(
            pl.col("scheduled").cum_sum().over("season", "team").cast(pl.Int32).alias("through"),
        )
        .join(totals, on=["season", "team"], how="left")
        .with_columns(
            (pl.col("team_scheduled_total") - pl.col("through"))
            .cast(pl.Int32)
            .alias("team_remaining_scheduled_games"),
        )
        .select("season", "team", "week", "team_remaining_scheduled_games")
    )
    joined = scoped.join(
        through.rename({"team": "team_to_date"}),
        on=["season", "team_to_date", "week"],
        how="left",
    )
    # A team with no scheduled row for the cutoff week is on its bye that week; the count of
    # games still ahead of it is unchanged, so carry the nearest earlier week's value.
    return joined.with_columns(
        pl.col("team_remaining_scheduled_games")
        .fill_null(strategy="forward")
        .over("season", "gsis_id")
        .alias("team_remaining_scheduled_games"),
    )


def _shared_columns(
    scoped: pl.DataFrame,
    horizon_last: Mapping[int, int],
    horizon_length: Mapping[int, int],
) -> pl.DataFrame:
    """The preset-independent half of the in-season block."""
    week = pl.col("week").cast(pl.Float64)
    games = pl.col("to_date_played")
    recent_games = pl.col("recent_played")
    opportunities = (
        pl.col("to_date_pass_attempts")
        + pl.col("to_date_carries")
        + pl.col(
            "to_date_targets",
        )
    )
    touchdowns = (
        pl.col("to_date_passing_tds")
        + pl.col("to_date_rushing_tds")
        + pl.col("to_date_receiving_tds")
    )
    return scoped.select(
        pl.col("season"),
        pl.col("week").alias("through_week"),
        pl.col("gsis_id"),
        pl.col("position_to_date"),
        pl.col("team_to_date"),
        (pl.col("season").replace_strict(horizon_last, return_dtype=pl.Int32) - pl.col("week"))
        .cast(pl.Int32)
        .alias("remaining_horizon_weeks"),
        (
            (
                pl.col("season").replace_strict(horizon_last, return_dtype=pl.Int32)
                - pl.col("week")
            ).cast(pl.Float64)
            / pl.col("season")
            .replace_strict(horizon_length, return_dtype=pl.Int32)
            .cast(pl.Float64)
        ).alias("season_share_remaining"),
        games.cast(pl.Int32).alias("games_to_date"),
        (games.cast(pl.Float64) / week).alias("games_share_to_date"),
        (pl.col("week") - games).cast(pl.Int32).alias("weeks_missed_to_date"),
        (pl.col("week") - pl.col("last_played_week")).cast(pl.Int32).alias("weeks_since_last_game"),
        (pl.col("week") - pl.col("last_played_week").fill_null(0))
        .cast(pl.Int32)
        .alias("consecutive_weeks_missed"),
        (pl.col("last_played_week") == pl.col("week")).fill_null(False).alias("active_last_week"),
        recent_games.cast(pl.Int32).alias("games_last3"),
        (games > 0).alias("has_played_this_season"),
        pl.col("team_remaining_scheduled_games"),
        _ratio(pl.col("to_date_targets"), games, minimum=1).alias("targets_per_game_to_date"),
        _ratio(pl.col("to_date_carries"), games, minimum=1).alias("carries_per_game_to_date"),
        _ratio(pl.col("to_date_pass_attempts"), games, minimum=1).alias(
            "pass_attempts_per_game_to_date",
        ),
        _ratio(pl.col("to_date_carries") + pl.col("to_date_receptions"), games, minimum=1).alias(
            "touches_per_game_to_date",
        ),
        _ratio(
            pl.col("to_date_targets"),
            pl.col("to_date_team_targets_played"),
            minimum=_MIN_TARGETS,
        ).alias("target_share_to_date"),
        _ratio(
            pl.col("to_date_carries"),
            pl.col("to_date_team_carries_played"),
            minimum=_MIN_CARRIES,
        ).alias("carry_share_to_date"),
        _ratio(pl.col("to_date_receiving_air_yards"), games, minimum=1).alias(
            "air_yards_per_game_to_date",
        ),
        _ratio(pl.col("to_date_snap_pct_played"), pl.col("to_date_snap_games"), minimum=1).alias(
            "snap_pct_mean_to_date",
        ),
        _ratio(pl.col("recent_snap_pct_played"), pl.col("recent_snap_games"), minimum=1).alias(
            "snap_pct_last3",
        ),
        _ratio(pl.col("recent_targets"), pl.col("recent_team_targets_played"), minimum=1).alias(
            "target_share_last3",
        ),
        _ratio(
            pl.col("to_date_expected_points_played"),
            pl.col("to_date_expected_games"),
            minimum=1,
        ).alias("expected_points_per_game_to_date"),
        _ratio(
            pl.col("to_date_receiving_yards"),
            pl.col("to_date_targets"),
            minimum=_MIN_TARGETS,
        ).alias("yards_per_target_to_date"),
        _ratio(
            pl.col("to_date_rushing_yards"),
            pl.col("to_date_carries"),
            minimum=_MIN_CARRIES,
        ).alias("yards_per_carry_to_date"),
        _ratio(
            pl.col("to_date_receptions"),
            pl.col("to_date_targets"),
            minimum=_MIN_TARGETS,
        ).alias("catch_rate_to_date"),
        _ratio(touchdowns, opportunities, minimum=_MIN_OPPORTUNITIES).alias(
            "td_per_opportunity_to_date",
        ),
        _ratio(
            pl.col("to_date_team_points_std_played"),
            pl.col("to_date_team_games_played"),
            minimum=1,
        ).alias("team_points_per_game_to_date"),
        _ratio(
            pl.col("to_date_team_pass_attempts_played"),
            pl.col("to_date_team_pass_attempts_played") + pl.col("to_date_team_carries_played"),
            minimum=1,
        ).alias("team_pass_rate_to_date"),
        _ratio(
            pl.col("to_date_team_pass_attempts_played") + pl.col("to_date_team_carries_played"),
            pl.col("to_date_team_games_played"),
            minimum=1,
        ).alias("team_plays_per_game_to_date"),
        (pl.col("team_changes_to_date") > 0).alias("team_changed_in_season"),
        opportunities.alias("_opportunities"),
        pl.col("to_date_played").alias("_games"),
        pl.col("recent_played").alias("_recent_games"),
        pl.col("^to_date_fantasy_points_.*$"),
        pl.col("^recent_fantasy_points_.*$"),
        pl.col("^best_fantasy_points_.*$"),
    )


def _preset_columns(shared: pl.DataFrame, preset: ScoringPreset) -> pl.DataFrame:
    """The preset-specific half, stacked onto the shared block."""
    points = f"fantasy_points_{preset}"
    to_date = pl.col(f"to_date_{points}")
    to_date_sq = pl.col(f"to_date_{points}_sq")
    games = pl.col("_games")
    recent = pl.col(f"recent_{points}")
    recent_games = pl.col("_recent_games")
    variance = (to_date_sq - to_date.pow(2) / games) / (games - 1)
    ppg = _ratio(to_date, games, minimum=1)
    recent_ppg = _ratio(recent, recent_games, minimum=1)
    return shared.select(
        pl.exclude(
            "^to_date_fantasy_points_.*$",
            "^recent_fantasy_points_.*$",
            "^best_fantasy_points_.*$",
            "_opportunities",
            "_games",
            "_recent_games",
        ),
        pl.lit(str(preset)).alias("scoring_preset"),
        to_date.alias("points_to_date"),
        ppg.alias("ppg_to_date"),
        (to_date / pl.col("through_week").cast(pl.Float64)).alias("points_per_week_to_date"),
        recent_ppg.alias("ppg_last3"),
        (recent_ppg - ppg).alias("ppg_trend"),
        pl.when(games > 0)
        .then(pl.col(f"best_{points}"))
        .otherwise(None)
        .alias("best_week_points_to_date"),
        pl.when(games >= 2)
        .then(pl.when(variance > 0).then(variance.sqrt()).otherwise(0.0))
        .otherwise(None)
        .alias("points_sd_to_date"),
        (pl.col("snap_pct_last3") - pl.col("snap_pct_mean_to_date")).alias("snap_pct_trend"),
        (pl.col("target_share_last3") - pl.col("target_share_to_date")).alias(
            "target_share_trend",
        ),
        _ratio(to_date, pl.col("_opportunities"), minimum=_MIN_OPPORTUNITIES).alias(
            "points_per_opportunity_to_date",
        ),
        (ppg - pl.col("expected_points_per_game_to_date")).alias(
            "points_over_expected_per_game_to_date",
        ),
        pl.lit(ROS_FEATURE_SCHEMA_VERSION).alias("ros_feature_schema_version"),
    )
