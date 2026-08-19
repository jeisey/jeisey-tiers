"""Actual fantasy-point labels.

One row per ``(season, player_id, scoring_preset)``, computed from weekly stat components
by :mod:`ffdraft.scoring.engine` over the horizon in :mod:`ffdraft.scoring.horizon`.

Two properties are deliberate.

**An eligible player who never played scores zero, not null.** He was in the preseason
universe and delivered nothing; that is the outcome a draft-time model is supposed to be
able to be wrong about. Dropping such rows would train the model only on players who
panned out, which is survivorship bias dressed up as data cleaning.

**Labels are joined onto the eligible universe, never the other way round.** The universe
comes from :mod:`ffdraft.features.eligibility` and knows nothing about the target season, so
a player who appeared out of nowhere in season Y - a mid-season signing, a UDFA the pre-2025
sources cannot see - contributes no row. That is a coverage limitation, reported by season
in the quality report, and it is the correct direction to err in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.features.dictionary import FANTASY_LABEL_CONTRACT
from ffdraft.scoring.engine import SCORING_ENGINE_VERSION, season_totals
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = ["build_fantasy_labels", "season_point_totals"]


def season_point_totals(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    *,
    seasons: Sequence[int],
) -> pl.DataFrame:
    """Per ``(season, gsis_id)`` horizon totals for the requested target seasons."""
    if weekly.is_empty():
        return pl.DataFrame(schema={"season": pl.Int32, "gsis_id": pl.String})
    scoped = weekly.filter(pl.col("season").is_in(list(seasons)))
    if scoped.is_empty():
        return pl.DataFrame(schema={"season": pl.Int32, "gsis_id": pl.String})
    return season_totals(scoped, scoring, key=("season", "gsis_id"))


def build_fantasy_labels(
    eligible: pl.DataFrame,
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
) -> pl.DataFrame:
    """Build the ``(season, player_id, scoring_preset)`` label table.

    ``eligible`` must carry ``season``, ``player_id``, ``gsis_id`` and ``position``.
    """
    if eligible.is_empty():
        return FANTASY_LABEL_CONTRACT.empty()

    seasons = [int(season) for season in eligible.get_column("season").unique().to_list()]
    totals = season_point_totals(weekly, scoring, seasons=seasons)

    base = eligible.select("season", "player_id", "gsis_id", "position")
    if totals.is_empty():
        joined = base.with_columns(
            pl.lit(0, dtype=pl.Int32).alias("actual_games_played"),
            *[
                pl.lit(0.0, dtype=pl.Float64).alias(f"fantasy_points_{preset}")
                for preset in sorted(scoring)
            ],
        )
    else:
        joined = base.join(totals, on=["season", "gsis_id"], how="left").with_columns(
            pl.col("actual_games_played").fill_null(0).cast(pl.Int32),
            *[pl.col(f"fantasy_points_{preset}").fill_null(0.0) for preset in sorted(scoring)],
        )

    horizons = {season: fantasy_horizon(season) for season in seasons}
    frames: list[pl.DataFrame] = []
    for preset in sorted(scoring):
        frames.append(
            joined.select(
                pl.col("season"),
                pl.col("player_id"),
                pl.lit(str(preset)).alias("scoring_preset"),
                pl.col("position"),
                pl.col(f"fantasy_points_{preset}").alias("actual_fantasy_points"),
                pl.col("actual_games_played"),
                pl.when(pl.col("actual_games_played") > 0)
                .then(pl.col(f"fantasy_points_{preset}") / pl.col("actual_games_played"))
                .otherwise(None)
                .alias("actual_points_per_game"),
                pl.col("season")
                .replace_strict(
                    {season: horizon.first_week for season, horizon in horizons.items()},
                    return_dtype=pl.Int32,
                )
                .alias("horizon_first_week"),
                pl.col("season")
                .replace_strict(
                    {season: horizon.last_week for season, horizon in horizons.items()},
                    return_dtype=pl.Int32,
                )
                .alias("horizon_last_week"),
                pl.lit(SCORING_ENGINE_VERSION).alias("scoring_engine_version"),
            ),
        )

    stacked = pl.concat(frames)
    ranked = stacked.sort(
        ["season", "scoring_preset", "position", "actual_fantasy_points", "player_id"],
        descending=[False, False, False, True, False],
    ).with_columns(
        pl.int_range(1, pl.len() + 1)
        .over(["season", "scoring_preset", "position"])
        .cast(pl.Int32)
        .alias("actual_positional_rank"),
    )
    return FANTASY_LABEL_CONTRACT.coerce(ranked).sort(
        ["season", "scoring_preset", "player_id"],
    )
