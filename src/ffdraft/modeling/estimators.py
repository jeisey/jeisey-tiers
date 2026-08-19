"""The estimator interface every Phase-3 model implements.

A model is asked to do exactly one thing: given one fold's training rows and one fold's
validation rows for a single position and scoring preset, fit itself and emit predictions.
Fitting and predicting are one call because that is what makes fold isolation structural -
there is no fitted object that could survive a fold and no place to stash a statistic
computed over the whole dataset.

Every model returns the same shape: a point estimate and the five declared quantiles, so
pinball loss, coverage and interval width compare candidates and baselines fairly rather
than comparing a distribution against a point guess.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.dataset import TARGET_COLUMN
from ffdraft.modeling.folds import Fold
from ffdraft.modeling.metrics import QUANTILE_LEVELS

__all__ = [
    "FitContext",
    "IntrinsicModel",
    "PredictionBlock",
    "prediction_frame",
    "repair_monotonicity",
]

Floats = NDArray[np.float64]

_QUANTILE_COLUMNS: tuple[str, ...] = tuple(f"q{int(level * 100):02d}" for level in QUANTILE_LEVELS)


@dataclass(frozen=True, slots=True)
class FitContext:
    """Everything a model may know about the job it has been handed."""

    fold: Fold
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


@dataclass
class PredictionBlock:
    """One group's predictions, plus whatever the model wants recorded about the fit."""

    keys: pl.DataFrame
    point: Floats
    quantiles: Floats
    raw_quantiles: Floats
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rows = self.keys.height
        if self.point.shape != (rows,):
            raise ValueError(f"point shape {self.point.shape} does not match {rows} key rows")
        if self.quantiles.shape != (rows, len(QUANTILE_LEVELS)):
            raise ValueError(
                f"quantile shape {self.quantiles.shape} does not match "
                f"({rows}, {len(QUANTILE_LEVELS)})",
            )
        if not np.all(np.isfinite(self.point)) or not np.all(np.isfinite(self.quantiles)):
            raise ValueError("a model emitted a non-finite prediction")


class IntrinsicModel(Protocol):
    """A Phase-3 baseline or candidate."""

    model_id: str

    def describe(self) -> dict[str, Any]:
        """Static definition: family, parameters, versions. Recorded in the report."""
        ...

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: FitContext,
    ) -> PredictionBlock:
        """Fit on ``train`` only, then predict ``validate``."""
        ...


def repair_monotonicity(quantiles: Floats) -> Floats:
    """Sort each row's quantiles ascending.

    The deterministic minimum needed to make pinball loss and coverage well defined. The raw
    crossing rate is measured and reported *before* this runs, so the repair never hides the
    defect it repairs (`docs/MODELING.md` section 10).
    """
    if quantiles.size == 0:
        return quantiles
    return np.sort(quantiles, axis=1)


def prediction_frame(
    block: PredictionBlock,
    *,
    model_id: str,
    context: FitContext,
) -> pl.DataFrame:
    """The long prediction row set the metrics and the paired bootstrap both read."""
    frame = block.keys.select("season", "player_id", "position", "scoring_preset", TARGET_COLUMN)
    return frame.with_columns(
        pl.lit(model_id).alias("model_id"),
        pl.lit(str(context.fold.window)).alias("window_policy"),
        pl.lit(context.fold.fold_id).alias("fold_id"),
        pl.Series("pred_point", block.point, dtype=pl.Float64),
        *[
            pl.Series(column, block.quantiles[:, index], dtype=pl.Float64)
            for index, column in enumerate(_QUANTILE_COLUMNS)
        ],
    )


def quantile_columns() -> Sequence[str]:
    return _QUANTILE_COLUMNS
