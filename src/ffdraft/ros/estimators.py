"""The estimator interface every rest-of-season baseline and candidate implements.

Identical in spirit to :mod:`ffdraft.modeling.estimators`, and different in exactly two
ways: the grain carries ``through_week``, and the target is remaining points rather than a
season total. Fitting and predicting remain one call, so fold isolation stays structural -
there is no fitted object that could survive a fold and no place to stash a statistic
computed over the whole dataset.

Every model returns a point estimate and the same five declared quantiles, so pinball loss,
coverage and interval width compare a two-component hurdle against a one-line prorated prior
fairly rather than comparing a distribution against a point guess.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.estimators import PredictionBlock, repair_monotonicity
from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.ros.folds import RosFold

__all__ = [
    "ROS_TARGET_COLUMN",
    "PredictionBlock",
    "RosFitContext",
    "RosModel",
    "quantile_column_names",
    "repair_monotonicity",
    "ros_prediction_frame",
]

Floats = NDArray[np.float64]

#: What every Phase-11 model predicts: fantasy points over the weeks after the cutoff.
ROS_TARGET_COLUMN = "actual_remaining_points"

_QUANTILE_COLUMNS: tuple[str, ...] = tuple(f"q{int(level * 100):02d}" for level in QUANTILE_LEVELS)


def quantile_column_names() -> tuple[str, ...]:
    return _QUANTILE_COLUMNS


@dataclass(frozen=True, slots=True)
class RosFitContext:
    """Everything a rest-of-season model may know about the job it has been handed."""

    fold: RosFold
    position: str
    scoring_preset: str
    features: tuple[str, ...]
    seed: int
    levels: tuple[float, ...] = QUANTILE_LEVELS

    @property
    def group_seed(self) -> int:
        """A deterministic per-group seed, so two runs of the same experiment agree exactly."""
        parts = (
            self.seed,
            self.fold.validation_season,
            self.fold.train_start_season,
            sum(ord(character) for character in f"{self.position}{self.scoring_preset}"),
        )
        combined = 0
        for part in parts:
            combined = (combined * 1_000_003 + int(part)) % 2_147_483_647
        return combined


class RosModel(Protocol):
    """A Phase-11 baseline or candidate."""

    model_id: str

    def describe(self) -> dict[str, Any]:
        """Static definition: family, parameters, versions. Recorded in the report."""
        ...

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: RosFitContext,
    ) -> PredictionBlock:
        """Fit on ``train`` only, then predict ``validate``."""
        ...


def ros_prediction_frame(
    block: PredictionBlock,
    *,
    model_id: str,
    context: RosFitContext,
) -> pl.DataFrame:
    """The long prediction row set the metrics and the paired bootstrap both read."""
    frame = block.keys.select(
        "season",
        "through_week",
        "player_id",
        "position",
        "scoring_preset",
        ROS_TARGET_COLUMN,
    )
    return frame.with_columns(
        pl.lit(model_id).alias("model_id"),
        pl.lit(context.fold.fold_id).alias("fold_id"),
        pl.Series("pred_point", block.point, dtype=pl.Float64),
        *[
            pl.Series(column, block.quantiles[:, index], dtype=pl.Float64)
            for index, column in enumerate(_QUANTILE_COLUMNS)
        ],
    )


def as_floats(frame: pl.DataFrame, column: str, *, default: float = 0.0) -> Floats:
    """One column as a dense float array, nulls replaced by ``default``."""
    return (
        frame.get_column(column)
        .cast(pl.Float64)
        .fill_null(default)
        .to_numpy()
        .astype(
            np.float64,
        )
    )


def nullable_floats(frame: pl.DataFrame, column: str) -> Floats:
    """One column as a float array with nulls as NaN, which is what LightGBM wants."""
    return frame.get_column(column).cast(pl.Float64).to_numpy().astype(np.float64)


def levels_as_array(levels: Sequence[float]) -> Floats:
    return np.asarray(levels, dtype=np.float64)
