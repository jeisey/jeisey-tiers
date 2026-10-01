"""The v2 development dataset: v1's rows, unchanged, plus the three candidate families.

Every v1 row (``data/weekly/weekly_rows.parquet``, 155,634 rows, 2017-2025) keeps its key,
its 55 features and its label; v2's candidate families are joined beside them, each from
information available before the row's game:

* ``weather`` — per game, :func:`ffdraft.weekly.weather.training_weather` (the venue
  registry's roof type; the game book's recorded weather mapped to what a forecast would have
  said);
* ``lineup`` and ``defense`` — per cutoff, :func:`ffdraft.weekly.lineup.health_features`
  (lagged starters from snap counts through the cutoff; the target week's injury report).

Keeping v1's rows exactly is what makes "the incremental value of a family over v1" a clean
comparison: the same rows, the same labels, the same folds, one family more.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.weekly.frozen_v2 import V2_FAMILIES
from ffdraft.weekly.lineup import health_features
from ffdraft.weekly.venues import VenueRegistry
from ffdraft.weekly.weather import WeatherErrorModel, training_weather

__all__ = ["V2_FEATURES", "WeeklyV2Dataset", "attach_v2_families", "game_weather_inputs"]

V2_FEATURES: tuple[str, ...] = tuple(name for names in V2_FAMILIES.values() for name in names)


@dataclass
class WeeklyV2Dataset:
    frame: pl.DataFrame
    checks: list[QualityCheck] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)


def game_weather_inputs(schedule: pl.DataFrame, weather_text: pl.DataFrame) -> pl.DataFrame:
    """Per regular-season game: stadium, recorded kickoff weather and the game-book text."""
    games = schedule.filter(pl.col("game_type") == "REG").select(
        "game_id",
        pl.col("season").cast(pl.Int32),
        "stadium_id",
        "stadium",
        pl.col("temp").cast(pl.Float64),
        pl.col("wind").cast(pl.Float64),
    )
    text = weather_text.select("game_id", pl.col("weather").alias("weather_text")).unique(
        "game_id",
        keep="first",
    )
    return games.join(text, on="game_id", how="left")


def attach_v2_families(
    rows: pl.DataFrame,
    *,
    snaps: pl.DataFrame,
    weekly: pl.DataFrame,
    injuries: pl.DataFrame,
    games: pl.DataFrame,
    registry: VenueRegistry,
    error_model: WeatherErrorModel,
) -> WeeklyV2Dataset:
    """v1's rows plus every v2 candidate input. Row order and count are preserved."""
    checks: list[QualityCheck] = []
    indexed = rows.with_row_index("_v2_row")
    weather = training_weather(games, registry=registry, error_model=error_model)
    parts: list[pl.DataFrame] = []
    cutoffs = (
        indexed.select("season", "through_week", "target_week")
        .unique()
        .sort(
            "season",
            "through_week",
        )
    )
    for cutoff in cutoffs.iter_rows(named=True):
        block = indexed.filter(
            (pl.col("season") == cutoff["season"])
            & (pl.col("through_week") == cutoff["through_week"]),
        )
        parts.append(
            health_features(
                block,
                snaps=snaps,
                weekly=weekly,
                injuries=injuries,
                season=int(cutoff["season"]),
                through_week=int(cutoff["through_week"]),
                target_week=int(cutoff["target_week"]),
            ),
        )
    healthy = pl.concat(parts, how="vertical_relaxed") if parts else indexed
    frame = healthy.join(weather, on="game_id", how="left").sort("_v2_row").drop("_v2_row")
    if frame.height != rows.height:
        raise ValueError(f"v2 families changed the row count: {rows.height} -> {frame.height}")
    missing = [name for name in V2_FEATURES if name not in frame.columns]
    if missing:
        raise ValueError(f"v2 dataset is missing declared features: {missing}")

    coverage = {
        "rows": frame.height,
        "venue_resolved": int(frame.filter(pl.col("venue_id").is_not_null()).height),
        "open_air_with_weather": int(frame.filter(pl.col("wx_wind_mph").is_not_null()).height),
        "precipitation_expected": int(frame.filter(pl.col("wx_precip") == 1.0).height),
        "own_report_final": int(frame.filter(pl.col("own_report_final").fill_null(False)).height),
        "opp_report_final": int(frame.filter(pl.col("opp_report_final").fill_null(False)).height),
        "own_ol_out_any": int(frame.filter(pl.col("own_ol_out") > 0).height),
        "own_qb_out": int(frame.filter(pl.col("own_qb_out") > 0).height),
        "opp_cb_out_any": int(frame.filter(pl.col("opp_cb_out") > 0).height),
        "vacated_targets_any": int(frame.filter(pl.col("own_vacated_targets") > 0).height),
    }
    unresolved = frame.filter(pl.col("venue_id").is_null()).height
    checks.append(
        QualityCheck.ok(
            "weekly_v2_dataset.venues",
            stage="weekly_v2_dataset",
            message="rows whose game resolves to exactly one registry venue",
            observed=f"{frame.height - unresolved}/{frame.height}",
        )
        if unresolved == 0
        else QualityCheck.fail(
            "weekly_v2_dataset.venues",
            stage="weekly_v2_dataset",
            message="rows whose game resolves to no registry venue have no weather or roof type",
            observed=f"{unresolved} rows",
            expected="0",
        ),
    )
    return WeeklyV2Dataset(frame=frame, checks=checks, coverage=coverage)


def v2_columns() -> Sequence[str]:
    return (*V2_FEATURES, "venue_id", "own_report_final", "opp_report_final")
