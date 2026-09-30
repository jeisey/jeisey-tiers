"""The three declared weekly baselines (``weekly_promotion_v1``'s comparators).

Each is a point rule plus the same predictive distribution: the empirical quantiles of
``actual - point`` over the training window, per position and scoring preset, added to the
point. The residual quantiles are the only thing "fitted", and only on training seasons.

These exist to make a claim about the candidate falsifiable. A learned model that cannot beat
"he has scored 14 a game" (B0), "he has scored 17 a game lately" (B1) or "14 a game, nudged by
the sportsbook's team total" (B2) on the start/sit question is not worth printing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.preprocessing import scalar_float
from ffdraft.weekly.dataset import TARGET_COLUMN
from ffdraft.weekly.frozen import B2_PRIOR_GAMES, BASELINE_IDS, WEEKLY_QUANTILE_LEVELS

__all__ = ["BaselineModel", "baseline_points", "fit_baseline"]

Floats = NDArray[np.float64]


def _prior_rate() -> pl.Expr:
    """Last season's rate in the row's own preset. HALF is halfway between STD and PPR."""
    std = pl.col("prev1_fantasy_ppg_std")
    ppr = pl.col("prev1_fantasy_ppg_ppr")
    return (
        pl.when(pl.col("scoring_preset") == "STD")
        .then(std)
        .when(pl.col("scoring_preset") == "PPR")
        .then(ppr)
        .otherwise((std + ppr) / 2.0)
    )


def baseline_points(
    baseline_id: str,
    frame: pl.DataFrame,
    *,
    position_medians: dict[tuple[str, str], float],
    mean_team_points: float | None,
) -> Floats:
    """The point rule for ``baseline_id`` over ``frame``, row order preserved."""
    if baseline_id not in BASELINE_IDS:
        raise KeyError(baseline_id)
    median_expr = pl.struct("position", "scoring_preset").map_elements(
        lambda key: position_medians.get((str(key["position"]), str(key["scoring_preset"])), 0.0),
        return_dtype=pl.Float64,
    )
    prior = _prior_rate()
    played = pl.col("games_to_date").fill_null(0) > 0
    b0 = (
        pl.when(played)
        .then(pl.col("ppg_to_date"))
        .when(prior.is_not_null())
        .then(prior)
        .otherwise(median_expr)
    )
    if baseline_id == "b0_season_rate":
        expression = b0
    elif baseline_id == "b1_recent_form":
        expression = (
            pl.when(pl.col("games_last3").fill_null(0) > 0).then(pl.col("ppg_last3")).otherwise(b0)
        )
    else:
        games = pl.col("games_to_date").fill_null(0).cast(pl.Float64)
        anchor = pl.when(prior.is_not_null()).then(prior).otherwise(median_expr)
        shrunk = (
            pl.when(played)
            .then(
                (games * pl.col("ppg_to_date") + B2_PRIOR_GAMES * anchor)
                / (games + B2_PRIOR_GAMES),
            )
            .otherwise(anchor)
        )
        if mean_team_points is None or mean_team_points <= 0:
            expression = shrunk
        else:
            factor = (
                pl.when(pl.col("game_team_points").is_not_null())
                .then(pl.col("game_team_points") / mean_team_points)
                .otherwise(1.0)
            )
            expression = shrunk * factor
    values = frame.select(expression.cast(pl.Float64).alias("point")).get_column("point")
    return values.fill_null(0.0).to_numpy().astype(np.float64)


@dataclass
class BaselineModel:
    baseline_id: str
    position_medians: dict[tuple[str, str], float]
    mean_team_points: float | None
    residual_quantiles: dict[tuple[str, str], Floats]
    levels: tuple[float, ...] = WEEKLY_QUANTILE_LEVELS

    def point(self, frame: pl.DataFrame) -> Floats:
        return baseline_points(
            self.baseline_id,
            frame,
            position_medians=self.position_medians,
            mean_team_points=self.mean_team_points,
        )

    def predict(self, frame: pl.DataFrame) -> Floats:
        points = self.point(frame)
        result = np.full((frame.height, len(self.levels)), np.nan, dtype=np.float64)
        keys = frame.select("position", "scoring_preset").iter_rows()
        for row, key in enumerate(keys):
            residuals = self.residual_quantiles.get((str(key[0]), str(key[1])))
            if residuals is not None:
                result[row] = points[row] + residuals
        return result


def fit_baseline(
    baseline_id: str,
    train: pl.DataFrame,
    *,
    levels: Sequence[float] = WEEKLY_QUANTILE_LEVELS,
) -> BaselineModel:
    """Fit the residual distribution (and the medians/means the rule needs) on ``train``."""
    medians: dict[tuple[str, str], float] = {
        (str(row["position"]), str(row["scoring_preset"])): float(row["median"])
        for row in train.group_by("position", "scoring_preset")
        .agg(pl.col(TARGET_COLUMN).median().alias("median"))
        .iter_rows(named=True)
    }
    lined = train.filter(pl.col("game_team_points").is_not_null())
    mean_team_points = (
        None if lined.is_empty() else scalar_float(lined.get_column("game_team_points").mean())
    )
    model = BaselineModel(
        baseline_id=baseline_id,
        position_medians=medians,
        mean_team_points=mean_team_points,
        residual_quantiles={},
        levels=tuple(levels),
    )
    points = model.point(train)
    actual = train.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
    residual = actual - points
    keys = train.select("position", "scoring_preset").to_numpy()
    for key in {(str(a), str(b)) for a, b in keys}:
        mask = (keys[:, 0] == key[0]) & (keys[:, 1] == key[1])
        model.residual_quantiles[key] = np.quantile(residual[mask], list(levels), method="linear")
    return model
