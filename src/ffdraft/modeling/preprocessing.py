"""Fold-local preprocessing, inner splits and residual quantiles.

Everything in this module is fitted on training rows and applied to validation rows. There
is no global step: a preprocessor is constructed from a training frame and thrown away with
the fold, which makes "preprocessing was fitted only on the training fold" a structural
property rather than a promise.

Three pieces:

``design_matrix``
    Columns to numbers, booleans to 0/1, nulls to NaN. LightGBM consumes NaN natively; the
    linear baseline imputes it explicitly and keeps an indicator so the missingness itself
    stays visible.

``FoldPreprocessor``
    Median imputation plus standardization, both learned on the training rows, with an
    explicit missingness indicator for every column that had a null in training.

``ResidualQuantiles``
    Predictive quantiles for a model that emits only a point estimate. Residuals come from
    an inner *chronological* split of the training window - fit on the earlier training
    seasons, collect residuals on the latest one or two - so no validation-season row ever
    influences its own predictive interval, and the baseline gets a legitimate uncertainty
    comparator rather than a fabricated fixed-width band.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

__all__ = [
    "MINIMUM_RESIDUAL_STRATUM",
    "scalar_float",
    "FoldPreprocessor",
    "InnerSplit",
    "ResidualQuantiles",
    "design_matrix",
    "inner_chronological_split",
]

Floats = NDArray[np.float64]

#: A residual stratum needs this many rows before it is trusted with its own quantiles;
#: below it the pooled position-and-scoring residual distribution is used instead.
MINIMUM_RESIDUAL_STRATUM = 100


def scalar_float(value: object, default: float = 0.0) -> float:
    """A Polars aggregate as a plain float.

    Polars types its reductions as a union covering every dtype it can hold, so an aggregate
    over an empty or all-null group is ``None`` and one over a temporal column is not a
    number at all. Converting in one place keeps that narrowing honest rather than scattering
    ``float(... or 0.0)`` - which would also turn a legitimate zero into the default.
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return default


def design_matrix(frame: pl.DataFrame, features: Sequence[str]) -> Floats:
    """Feature columns as a float matrix with nulls represented by NaN."""
    if not features:
        return np.zeros((frame.height, 0), dtype=np.float64)
    casted = frame.select(
        [pl.col(name).cast(pl.Float64, strict=False).alias(name) for name in features],
    )
    return casted.to_numpy().astype(np.float64, copy=False)


@dataclass(frozen=True)
class FoldPreprocessor:
    """Imputation and standardization learned on one fold's training rows."""

    features: tuple[str, ...]
    kept: tuple[int, ...]
    medians: Floats
    means: Floats
    scales: Floats
    indicator_for: tuple[int, ...]

    @classmethod
    def fit(cls, matrix: Floats, features: Sequence[str]) -> FoldPreprocessor:
        columns = matrix.shape[1]
        kept: list[int] = []
        for index in range(columns):
            column = matrix[:, index]
            observed = column[~np.isnan(column)]
            # A column with no training values, or one constant value, carries nothing a
            # linear model can use and would only inflate the design matrix.
            if observed.size == 0 or np.unique(observed).size < 2:
                continue
            kept.append(index)
        if not kept:
            empty = np.zeros(0, dtype=np.float64)
            return cls(tuple(features), (), empty, empty, empty, ())

        medians = np.array(
            [float(np.median(matrix[:, i][~np.isnan(matrix[:, i])])) for i in kept],
            dtype=np.float64,
        )
        indicator_for = tuple(
            position for position, i in enumerate(kept) if bool(np.any(np.isnan(matrix[:, i])))
        )
        filled = cls._fill(matrix, tuple(kept), medians, indicator_for)
        means = filled.mean(axis=0)
        scales = filled.std(axis=0)
        scales = np.where(scales < 1e-12, 1.0, scales)
        return cls(
            features=tuple(features),
            kept=tuple(kept),
            medians=medians,
            means=means,
            scales=scales,
            indicator_for=indicator_for,
        )

    @staticmethod
    def _fill(
        matrix: Floats,
        kept: tuple[int, ...],
        medians: Floats,
        indicator_for: tuple[int, ...],
    ) -> Floats:
        selected = matrix[:, list(kept)] if kept else np.zeros((matrix.shape[0], 0))
        missing = np.isnan(selected)
        filled = np.where(missing, medians[None, :], selected)
        if indicator_for:
            indicators = missing[:, list(indicator_for)].astype(np.float64)
            filled = np.hstack([filled, indicators])
        return filled

    def transform(self, matrix: Floats) -> Floats:
        """Impute with training medians, append indicators, standardize with training scale."""
        if not self.kept:
            return np.zeros((matrix.shape[0], 0), dtype=np.float64)
        filled = self._fill(matrix, self.kept, self.medians, self.indicator_for)
        return (filled - self.means[None, :]) / self.scales[None, :]

    @property
    def width(self) -> int:
        return len(self.kept) + len(self.indicator_for)

    def describe(self) -> dict[str, Any]:
        return {
            "features_offered": len(self.features),
            "features_kept": len(self.kept),
            "missingness_indicators": len(self.indicator_for),
            "design_width": self.width,
        }


@dataclass(frozen=True, slots=True)
class InnerSplit:
    """A chronological split *inside* a fold's training window."""

    fit_seasons: tuple[int, ...]
    residual_seasons: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "inner_fit_seasons": list(self.fit_seasons),
            "inner_residual_seasons": list(self.residual_seasons),
        }


def inner_chronological_split(train_seasons: Sequence[int]) -> InnerSplit:
    """Hold out the last one or two training seasons to collect honest residuals.

    Two residual seasons whenever the window has at least four, so the residual sample is
    large enough to stratify; one otherwise. The split is chronological for the same reason
    the outer folds are: residuals from a season the model already fitted would understate
    the spread of a genuine out-of-time prediction.
    """
    seasons = tuple(sorted(train_seasons))
    if len(seasons) < 2:
        raise ValueError(
            f"a training window of {len(seasons)} season(s) cannot be split for residuals",
        )
    held = 2 if len(seasons) >= 4 else 1
    return InnerSplit(fit_seasons=seasons[:-held], residual_seasons=seasons[-held:])


@dataclass(frozen=True)
class ResidualQuantiles:
    """Additive predictive quantiles estimated from out-of-sample training residuals."""

    levels: tuple[float, ...]
    pooled: Floats
    cut_points: Floats
    strata: tuple[Floats, ...]
    stratum_counts: tuple[int, ...]

    @classmethod
    def fit(
        cls,
        residuals: Floats,
        predictions: Floats,
        levels: Sequence[float],
        *,
        minimum_stratum: int = MINIMUM_RESIDUAL_STRATUM,
    ) -> ResidualQuantiles:
        """Learn residual quantiles, stratified by predicted level where samples allow.

        Fantasy totals are strongly heteroscedastic - the spread around a projected RB1 is
        nothing like the spread around a projected RB60 - so a single pooled residual
        distribution would be too wide at the bottom and too narrow at the top. Terciles of
        the *predicted* value are the simplest stratification that captures that, and they
        are used only when a stratum is large enough to estimate a quantile from.
        """
        level_tuple = tuple(levels)
        if residuals.size == 0:
            zeros = np.zeros(len(level_tuple), dtype=np.float64)
            return cls(level_tuple, zeros, np.array([], dtype=np.float64), (), ())
        pooled = np.quantile(residuals, level_tuple).astype(np.float64)
        cut_points = np.quantile(predictions, [1.0 / 3.0, 2.0 / 3.0]).astype(np.float64)
        assignment = np.digitize(predictions, cut_points, right=False)
        strata: list[Floats] = []
        counts: list[int] = []
        for stratum in range(3):
            mask = assignment == stratum
            count = int(np.count_nonzero(mask))
            counts.append(count)
            if count >= minimum_stratum:
                strata.append(np.quantile(residuals[mask], level_tuple).astype(np.float64))
            else:
                strata.append(pooled)
        return cls(level_tuple, pooled, cut_points, tuple(strata), tuple(counts))

    def apply(self, point: Floats) -> Floats:
        """Predictive quantiles for each row: its point estimate plus its stratum's offsets."""
        if point.size == 0:
            return np.zeros((0, len(self.levels)), dtype=np.float64)
        if self.cut_points.size == 0:
            offsets = np.tile(self.pooled, (point.size, 1))
        else:
            assignment = np.digitize(point, self.cut_points, right=False)
            offsets = np.vstack([self.strata[int(index)] for index in assignment])
        return point[:, None] + offsets

    def describe(self) -> dict[str, Any]:
        return {
            "levels": list(self.levels),
            "pooled_offsets": [round(float(value), 4) for value in self.pooled],
            "prediction_cut_points": [round(float(value), 4) for value in self.cut_points],
            "stratum_counts": list(self.stratum_counts),
            "stratified": [
                bool(count >= MINIMUM_RESIDUAL_STRATUM) for count in self.stratum_counts
            ],
        }
