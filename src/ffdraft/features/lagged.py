"""Season-lagged aggregates.

Everything here reduces weekly source rows to one row per ``(source_season, gsis_id)`` (or
``(source_season, team)``). The historical builder then joins those aggregates onto a target
season at offsets 1, 2 and 3, which is what makes "no target-season data" a property of the
join rather than a property of a filter somebody has to remember to apply.

Two conventions hold throughout and are documented in the feature dictionary:

* **Aggregates use the fantasy horizon**, not the full NFL regular season. Lagged production
  is therefore directly comparable with the label a model is trying to predict, which is
  what a prior-production baseline (`docs/MODELING.md` section 8, B0) needs. It costs one
  week of usage data per prior season and buys one consistent rule.
* **A ratio with too small a denominator is null, not noisy.** Yards per carry on four
  carries is not an efficiency estimate. The minimum denominators live in the feature
  dictionary and the paired ``*_denominator_met`` indicator tells an estimator the
  difference between "no attempts" and "not enough attempts".
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.scoring.engine import score_weekly_frame
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "PASS_ATTEMPT_MINIMUM",
    "RUSH_ATTEMPT_MINIMUM",
    "TARGET_MINIMUM",
    "expected_points_by_season",
    "horizon_filter",
    "player_season_usage",
    "role_rank_by_season",
    "snap_usage_by_season",
    "team_games_by_season",
    "team_season_context",
]

#: Minimum denominators for lagged efficiency ratios. Chosen to be roughly "a couple of
#: games of real volume" at each position rather than to make any particular season pass:
#: 20 carries or 20 targets is about two starter games, and 100 pass attempts is about
#: three. Below these, the ratio's sampling error dominates its signal.
RUSH_ATTEMPT_MINIMUM = 20
TARGET_MINIMUM = 20
PASS_ATTEMPT_MINIMUM = 100

_REGULAR_SEASON = "REG"


def horizon_filter(frame: pl.DataFrame, *, season_column: str = "season") -> pl.DataFrame:
    """Keep only regular-season rows inside each season's fantasy horizon."""
    if frame.is_empty():
        return frame
    predicate = pl.lit(False)
    for season in frame.get_column(season_column).unique().to_list():
        horizon = fantasy_horizon(int(season))
        predicate = predicate | (
            (pl.col(season_column) == season)
            & (pl.col("week") >= horizon.first_week)
            & (pl.col("week") <= horizon.last_week)
        )
    if "season_type" in frame.columns:
        predicate = predicate & (pl.col("season_type") == _REGULAR_SEASON)
    if "game_type" in frame.columns:
        predicate = predicate & (pl.col("game_type") == _REGULAR_SEASON)
    return frame.filter(predicate)


def _primary_team(frame: pl.DataFrame, *, keys: tuple[str, ...]) -> pl.DataFrame:
    """The team a player appeared for most often, ties broken alphabetically."""
    counted = (
        frame.filter(pl.col("team").is_not_null())
        .group_by([*keys, "team"])
        .agg(pl.len().alias("_games"))
        .sort([*keys, "_games", "team"], descending=[*([False] * len(keys)), True, False])
    )
    return counted.unique(subset=list(keys), keep="first", maintain_order=True).select(
        [*keys, pl.col("team").alias("primary_team")],
    )


def _mode_position(frame: pl.DataFrame, *, keys: tuple[str, ...]) -> pl.DataFrame:
    counted = (
        frame.filter(pl.col("position").is_not_null())
        .group_by([*keys, "position"])
        .agg(pl.len().alias("_rows"))
        .sort([*keys, "_rows", "position"], descending=[*([False] * len(keys)), True, False])
    )
    return counted.unique(subset=list(keys), keep="first", maintain_order=True).select(
        [*keys, pl.col("position").alias("primary_position")],
    )


def player_season_usage(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
) -> pl.DataFrame:
    """Per ``(season, gsis_id)`` usage, production and share aggregates.

    Target and rush shares are computed against the player's own teams **in the weeks he
    played**, not against a season total, so a player who missed half a season is not
    credited with a share of games he was absent for.
    """
    scored = horizon_filter(score_weekly_frame(weekly, scoring))
    if scored.is_empty():
        return _empty_usage(scoring)

    team_week = scored.group_by(["season", "week", "team"]).agg(
        pl.col("targets").sum().alias("team_week_targets"),
        pl.col("carries").sum().alias("team_week_carries"),
    )
    joined = scored.join(team_week, on=["season", "week", "team"], how="left")

    point_columns = [f"fantasy_points_{preset}" for preset in sorted(scoring)]
    aggregated = joined.group_by(["season", "gsis_id"]).agg(
        pl.len().cast(pl.Int32).alias("games"),
        *[pl.col(name).sum().alias(name) for name in point_columns],
        pl.col("carries").sum().alias("carries"),
        pl.col("targets").sum().alias("targets"),
        pl.col("receptions").sum().alias("receptions"),
        pl.col("rushing_yards").sum().alias("rushing_yards"),
        pl.col("receiving_yards").sum().alias("receiving_yards"),
        pl.col("passing_yards").sum().alias("passing_yards"),
        pl.col("pass_attempts").sum().alias("pass_attempts"),
        pl.col("completions").sum().alias("completions"),
        pl.col("passing_tds").sum().alias("passing_tds"),
        pl.col("interceptions").sum().alias("interceptions"),
        pl.col("rushing_tds").sum().alias("rushing_tds"),
        pl.col("receiving_tds").sum().alias("receiving_tds"),
        pl.col("team_week_targets").sum().alias("team_targets_in_played_weeks"),
        pl.col("team_week_carries").sum().alias("team_carries_in_played_weeks"),
    )

    keys = ("season", "gsis_id")
    aggregated = aggregated.join(_primary_team(scored, keys=keys), on=list(keys), how="left")
    aggregated = aggregated.join(_mode_position(scored, keys=keys), on=list(keys), how="left")

    return aggregated.with_columns(
        (pl.col("rushing_tds") + pl.col("receiving_tds")).alias("total_tds"),
        _safe_ratio("targets", "team_targets_in_played_weeks").alias("target_share"),
        _safe_ratio("carries", "team_carries_in_played_weeks").alias("rush_share"),
    ).sort(["season", "gsis_id"])


def _empty_usage(scoring: Mapping[ScoringPreset, ScoringRules]) -> pl.DataFrame:
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "season": pl.Int32,
        "gsis_id": pl.String,
        "games": pl.Int32,
    }
    for preset in sorted(scoring):
        schema[f"fantasy_points_{preset}"] = pl.Float64
    for name in (
        "carries",
        "targets",
        "receptions",
        "rushing_yards",
        "receiving_yards",
        "passing_yards",
        "pass_attempts",
        "completions",
        "passing_tds",
        "interceptions",
        "rushing_tds",
        "receiving_tds",
        "team_targets_in_played_weeks",
        "team_carries_in_played_weeks",
        "total_tds",
        "target_share",
        "rush_share",
    ):
        schema[name] = pl.Float64
    schema["primary_team"] = pl.String
    schema["primary_position"] = pl.String
    return pl.DataFrame(schema=schema)


def _safe_ratio(numerator: str, denominator: str, *, minimum: float = 0.0) -> pl.Expr:
    """``numerator / denominator``, or null when the denominator is too small."""
    denom = pl.col(denominator).cast(pl.Float64)
    return (
        pl.when(denom.is_null() | (denom <= minimum))
        .then(None)
        .otherwise(pl.col(numerator).cast(pl.Float64) / denom)
        .cast(pl.Float64)
    )


def team_games_by_season(schedule: pl.DataFrame) -> pl.DataFrame:
    """Games each team played inside each season's fantasy horizon.

    Derived from the schedule rather than from a constant, because the horizon excludes the
    final NFL week and whether a team played that week varies by bye placement.
    """
    if schedule.is_empty():
        return pl.DataFrame(schema={"season": pl.Int32, "team": pl.String, "team_games": pl.Int32})
    regular = horizon_filter(
        schedule.filter(pl.col("game_type") == _REGULAR_SEASON).with_columns(
            pl.lit(_REGULAR_SEASON).alias("season_type"),
        ),
    )
    home = regular.select("season", pl.col("home_team").alias("team"))
    away = regular.select("season", pl.col("away_team").alias("team"))
    return (
        pl.concat([home, away])
        .filter(pl.col("team").is_not_null())
        .group_by(["season", "team"])
        .agg(pl.len().cast(pl.Int32).alias("team_games"))
        .sort(["season", "team"])
    )


def team_season_context(weekly: pl.DataFrame, schedule: pl.DataFrame) -> pl.DataFrame:
    """Per ``(season, team)`` offensive volume, per game.

    Only passing and rushing touchdowns are summed: a receiving touchdown and the passing
    touchdown that produced it are the same score, so adding both would double-count team
    scoring.
    """
    scoped = horizon_filter(weekly)
    if scoped.is_empty():
        return pl.DataFrame(
            schema={
                "season": pl.Int32,
                "team": pl.String,
                "team_pass_attempts_pg": pl.Float64,
                "team_carries_pg": pl.Float64,
                "team_pass_yards_pg": pl.Float64,
                "team_rush_yards_pg": pl.Float64,
                "team_offense_tds_pg": pl.Float64,
            },
        )
    totals = (
        scoped.filter(pl.col("team").is_not_null())
        .group_by(["season", "team"])
        .agg(
            pl.col("pass_attempts").sum().alias("_pass_attempts"),
            pl.col("carries").sum().alias("_carries"),
            pl.col("passing_yards").sum().alias("_pass_yards"),
            pl.col("rushing_yards").sum().alias("_rush_yards"),
            (pl.col("passing_tds").sum() + pl.col("rushing_tds").sum()).alias("_offense_tds"),
        )
    )
    games = team_games_by_season(schedule)
    joined = totals.join(games, on=["season", "team"], how="left")
    return joined.select(
        "season",
        "team",
        _safe_ratio("_pass_attempts", "team_games").alias("team_pass_attempts_pg"),
        _safe_ratio("_carries", "team_games").alias("team_carries_pg"),
        _safe_ratio("_pass_yards", "team_games").alias("team_pass_yards_pg"),
        _safe_ratio("_rush_yards", "team_games").alias("team_rush_yards_pg"),
        _safe_ratio("_offense_tds", "team_games").alias("team_offense_tds_pg"),
    ).sort(["season", "team"])


def snap_usage_by_season(
    snaps: pl.DataFrame,
    pfr_to_gsis: Mapping[str, str],
) -> pl.DataFrame:
    """Per ``(season, gsis_id)`` offensive snap totals and mean share.

    Snap counts are keyed by ``pfr_player_id`` because they come from Pro Football
    Reference; rows whose PFR id has no canonical mapping are dropped rather than
    name-matched (ADR-005), and the builder reports the resulting join coverage.
    """
    empty = pl.DataFrame(
        schema={
            "season": pl.Int32,
            "gsis_id": pl.String,
            "snap_games": pl.Int32,
            "offense_snaps": pl.Float64,
            "snap_share": pl.Float64,
            "snap_team": pl.String,
            "snap_position": pl.String,
        },
    )
    if snaps.is_empty() or not pfr_to_gsis:
        return empty
    bridge = pl.DataFrame(
        {
            "pfr_player_id": list(pfr_to_gsis.keys()),
            "gsis_id": list(pfr_to_gsis.values()),
        },
        schema={"pfr_player_id": pl.String, "gsis_id": pl.String},
    )
    scoped = horizon_filter(snaps).join(bridge, on="pfr_player_id", how="inner")
    if scoped.is_empty():
        return empty
    aggregated = scoped.group_by(["season", "gsis_id"]).agg(
        pl.len().cast(pl.Int32).alias("snap_games"),
        pl.col("offense_snaps").sum().alias("offense_snaps"),
        pl.col("offense_pct").mean().alias("snap_share"),
    )
    keys = ("season", "gsis_id")
    aggregated = aggregated.join(_primary_team(scoped, keys=keys), on=list(keys), how="left")
    aggregated = aggregated.join(_mode_position(scoped, keys=keys), on=list(keys), how="left")
    return aggregated.rename(
        {"primary_team": "snap_team", "primary_position": "snap_position"},
    ).sort(["season", "gsis_id"])


def role_rank_by_season(
    snap_usage: pl.DataFrame,
    usage: pl.DataFrame,
) -> pl.DataFrame:
    """Rank within ``(season, team, position)`` by offensive snaps.

    This is ADR-018's ``prior_season_role_proxy``: the honest lagged stand-in for a depth
    rank in seasons that have no pre-anchor depth observation. Team and position come from
    the player's *own* prior season, so the rank describes where he finished, not where he
    is projected to start.
    """
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "season": pl.Int32,
        "gsis_id": pl.String,
        "role_rank": pl.Int32,
    }
    if snap_usage.is_empty():
        return pl.DataFrame(schema=schema)
    positions = (
        usage.select("season", "gsis_id", "primary_position")
        if not usage.is_empty()
        else pl.DataFrame(
            schema={"season": pl.Int32, "gsis_id": pl.String, "primary_position": pl.String},
        )
    )
    joined = snap_usage.join(positions, on=["season", "gsis_id"], how="left").with_columns(
        pl.coalesce(pl.col("primary_position"), pl.col("snap_position")).alias("_position"),
    )
    ranked = (
        joined.filter(pl.col("snap_team").is_not_null() & pl.col("_position").is_not_null())
        .sort(
            ["season", "snap_team", "_position", "offense_snaps", "gsis_id"],
            descending=[False, False, False, True, False],
        )
        .with_columns(
            pl.int_range(1, pl.len() + 1)
            .over(["season", "snap_team", "_position"])
            .cast(pl.Int32)
            .alias("role_rank"),
        )
    )
    return ranked.select("season", "gsis_id", "role_rank").sort(["season", "gsis_id"])


def expected_points_by_season(expected: pl.DataFrame) -> pl.DataFrame:
    """Per ``(season, gsis_id)`` ffopportunity expected points and actual-minus-expected."""
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "season": pl.Int32,
        "gsis_id": pl.String,
        "xfp_games": pl.Int32,
        "expected_points": pl.Float64,
        "points_over_expected": pl.Float64,
    }
    if expected.is_empty():
        return pl.DataFrame(schema=schema)
    scoped = horizon_filter(expected)
    if scoped.is_empty():
        return pl.DataFrame(schema=schema)
    # A two-way player can receive one expected-points row per position in the same week.
    # Summing them would double-count a single set of opportunities, so the largest
    # attribution wins and the position name breaks ties deterministically.
    scoped = scoped.sort(
        ["season", "week", "gsis_id", "expected_points", "position"],
        descending=[False, False, False, True, False],
        nulls_last=True,
    ).unique(subset=["season", "week", "gsis_id"], keep="first", maintain_order=True)
    return (
        scoped.group_by(["season", "gsis_id"])
        .agg(
            pl.len().cast(pl.Int32).alias("xfp_games"),
            pl.col("expected_points").sum().alias("expected_points"),
            pl.col("points_over_expected").sum().alias("points_over_expected"),
        )
        .sort(["season", "gsis_id"])
    )
