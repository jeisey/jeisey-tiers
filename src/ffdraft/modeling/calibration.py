"""Quantile monotonicity and calibration for the production distribution.

Phase 3 measured a defect and repaired it with an expedient: Q1 fits five independent
LightGBM boosters, 38.7% of rows come back with at least one crossing, and the harness
sorted each row so that pinball loss and coverage were well defined. ADR-029 recorded that
sorting is not the production answer. This module is the production answer.

## Monotonicity

The production repair is the **L2 projection onto the monotone cone**, computed by
pool-adjacent-violators. Sorting is *not* used, and the difference is not cosmetic.

Sorting a row's five values is the increasing rearrangement of the estimated quantile curve
on that grid. Rearrangement has a genuine theoretical basis - Chernozhukov, Fernandez-Val
and Galichon (2010) show it weakly reduces estimation error in :math:`L^p` for the quantile
*function* - but the guarantee is stated for the function on ``[0, 1]``, and recovering it
from a finite grid requires the grid to carry equal weight. This project's levels are
0.10, 0.25, 0.50, 0.75, 0.90: they are not evenly spaced, so a plain sort is not the
rearrangement of any weighting of them, and no contraction property follows.

Isotonic projection needs no such argument. The true quantile vector lies in the monotone
cone, the cone is closed and convex, and projection onto a closed convex set is a
contraction towards every point of that set. So for the projection ``P``:

    ``||P(q) - q_true||_2 <= ||q - q_true||_2``

always, for any level grid. The repair provably cannot move the estimate away from the
truth. That is the property worth having, and it is why the pool-adjacent-violators
algorithm is the production method here.

The two coincide when a row has at most one adjacent inversion, which is most of them; they
differ when a row has several, and the projection averages the offending block rather than
permuting values between levels. The experiment reports both the raw crossing rate and the
post-projection rate, which is zero by construction.

## Calibration

Monotonicity is not calibration. Q1's P10-P90 interval covered 0.771 of observations against
a nominal 0.80, so the intervals are slightly overconfident, and a projection does nothing
about that.

:class:`QuantileShift` learns one additive constant per quantile level from *out-of-sample*
residuals, on an inner chronological split of the training window:

    ``shift_j = Quantile_{tau_j}( y - qhat_j )`` over calibration rows.

The identity behind it is exact on the calibration sample: ``P(y <= qhat_j + shift_j)``
is ``P(y - qhat_j <= shift_j)``, which is ``tau_j`` by the definition of the empirical
quantile. It is split-conformal quantile calibration applied level by level, with the
familiar semantics - marginal coverage over the calibration distribution, not conditional
coverage for any one player.

Three properties matter for leakage:

* the residuals come from a model fitted on strictly earlier seasons than the ones the
  residuals are collected on, so they are honest out-of-time errors rather than training
  residuals;
* the model whose predictions are shifted is refitted on the full training window, so
  calibration costs no training data. It does mean the shifts describe a slightly
  *weaker* model than the one they are applied to, which biases the intervals marginally
  wide - a conservative direction, and recorded rather than corrected;
* nothing from the validation season, and nothing from the sealed holdout, is visible at any
  point. The whole thing is fitted inside :meth:`IntrinsicModel.fit_predict`, which is
  handed one fold's training rows.

Calibration is fitted per position and scoring preset, because the models are, which is what
makes the reported position-level calibration a property of the method rather than an
average over positions with different biases.

## Target scale

:class:`HorizonNormalizedTarget` is the one predeclared sensitivity from ADR-030's horizon
rule. It divides the training target by that season's fantasy-horizon length and multiplies
the predicted quantiles back by the validation season's, which puts 16-week and 17-week
seasons on one scale without touching the Phase-2 label contract and without adding a
calendar feature.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "MINIMUM_CALIBRATION_ROWS",
    "CalibrationStrategy",
    "HorizonNormalizedTarget",
    "IdentityTarget",
    "MonotoneOnly",
    "QuantileShift",
    "ResidualShiftCalibration",
    "TargetScale",
    "monotone_projection",
]

Floats = NDArray[np.float64]

#: Below this many calibration rows a shift is not estimated at all. Five level-specific
#: empirical quantiles from a handful of residuals would be noise dressed as a correction,
#: and a group that small is exactly where a bad correction does most damage.
MINIMUM_CALIBRATION_ROWS = 60


def monotone_projection(quantiles: Floats) -> Floats:
    """Project each row onto the monotone cone by pool-adjacent-violators.

    Equal weights, so a violating block is replaced by its unweighted mean. This is the L2
    projection: for any non-decreasing target vector the result is no further away than the
    input, which is the guarantee a plain sort cannot offer on an unevenly spaced level grid.
    """
    matrix = np.asarray(quantiles, dtype=np.float64)
    if matrix.size == 0:
        return matrix.copy()
    if matrix.ndim != 2:
        raise ValueError(f"expected a 2-d quantile matrix, got shape {matrix.shape}")
    output = np.empty_like(matrix)
    width = matrix.shape[1]
    for row in range(matrix.shape[0]):
        values: list[float] = []
        weights: list[int] = []
        for index in range(width):
            values.append(float(matrix[row, index]))
            weights.append(1)
            # Pool backwards while the last block violates the ordering.
            while len(values) > 1 and values[-2] > values[-1]:
                total = weights[-2] + weights[-1]
                pooled = (values[-2] * weights[-2] + values[-1] * weights[-1]) / total
                values[-2:] = [pooled]
                weights[-2:] = [total]
        position = 0
        for value, weight in zip(values, weights, strict=True):
            output[row, position : position + weight] = value
            position += weight
    return output


# ---------------------------------------------------------------------------------------
# Target scale
# ---------------------------------------------------------------------------------------


class TargetScale(Protocol):
    """How a model's target is scaled before fitting and unscaled after predicting."""

    @property
    def scale_id(self) -> str:
        """Stable identifier recorded in every model artifact and report."""
        ...

    def forward(self, values: Floats, seasons: Floats) -> Floats:
        """Training targets, on the scale the model is fitted against."""
        ...

    def inverse(self, quantiles: Floats, season: int) -> Floats:
        """Predicted quantiles, back on the fantasy-point scale."""
        ...

    def describe(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class IdentityTarget:
    """The season fantasy-point total, exactly as Phase 2 defines it."""

    scale_id: str = "season_total"

    def forward(self, values: Floats, seasons: Floats) -> Floats:
        return values

    def inverse(self, quantiles: Floats, season: int) -> Floats:
        return quantiles

    def describe(self) -> dict[str, Any]:
        return {"scale_id": self.scale_id, "transform": "none"}


@dataclass(frozen=True, slots=True)
class HorizonNormalizedTarget:
    """Fantasy points per week of that season's fantasy horizon.

    The horizon is 16 weeks before target season 2021 and 17 from 2021 on, so season totals
    sit on a ~6% different scale either side of the boundary. The 2021 validation fold is the
    one development fold trained entirely on 16-week seasons, and this transform is the
    single predeclared sensitivity ADR-030 allows for it. It rescales the target and nothing
    else: the fantasy-season *definition*, the label contract and the feature set are
    untouched.
    """

    scale_id: str = "points_per_horizon_week"

    def forward(self, values: Floats, seasons: Floats) -> Floats:
        return values / self._weeks(seasons)

    def inverse(self, quantiles: Floats, season: int) -> Floats:
        return quantiles * float(fantasy_horizon(int(season)).week_count)

    @staticmethod
    def _weeks(seasons: Floats) -> Floats:
        unique = np.unique(seasons)
        lookup = {int(season): float(fantasy_horizon(int(season)).week_count) for season in unique}
        return np.array([lookup[int(season)] for season in seasons], dtype=np.float64)

    def describe(self) -> dict[str, Any]:
        return {
            "scale_id": self.scale_id,
            "transform": "target / fantasy_horizon_weeks; predictions x validation horizon",
            "horizon_weeks": {"pre_2021": 16, "2021_onwards": 17},
        }


# ---------------------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantileShift:
    """One additive correction per quantile level, learned from out-of-sample residuals."""

    levels: tuple[float, ...]
    shifts: Floats
    calibration_rows: int
    fitted: bool

    @classmethod
    def none(cls, levels: Sequence[float], *, rows: int = 0) -> QuantileShift:
        return cls(tuple(levels), np.zeros(len(levels), dtype=np.float64), rows, False)

    @classmethod
    def fit(
        cls,
        actual: Floats,
        predicted: Floats,
        levels: Sequence[float],
        *,
        minimum_rows: int = MINIMUM_CALIBRATION_ROWS,
    ) -> QuantileShift:
        """Learn ``shift_j = Quantile_{tau_j}(actual - predicted_j)``."""
        observed = np.asarray(actual, dtype=np.float64)
        matrix = np.asarray(predicted, dtype=np.float64)
        level_tuple = tuple(levels)
        if observed.size < minimum_rows or matrix.shape != (observed.size, len(level_tuple)):
            return cls.none(level_tuple, rows=int(observed.size))
        shifts = np.array(
            [
                float(np.quantile(observed - matrix[:, index], level))
                for index, level in enumerate(level_tuple)
            ],
            dtype=np.float64,
        )
        return cls(level_tuple, shifts, int(observed.size), True)

    def apply(self, quantiles: Floats) -> Floats:
        matrix = np.asarray(quantiles, dtype=np.float64)
        if matrix.size == 0:
            return matrix
        return matrix + self.shifts[None, :]

    def describe(self) -> dict[str, Any]:
        return {
            "levels": list(self.levels),
            "shifts": [round(float(value), 4) for value in self.shifts],
            "calibration_rows": self.calibration_rows,
            "fitted": self.fitted,
        }


class CalibrationStrategy(Protocol):
    """What a model does to its raw quantiles before anyone sees them."""

    @property
    def strategy_id(self) -> str:
        """Stable identifier recorded in every model artifact and report."""
        ...

    @property
    def needs_calibration_split(self) -> bool:
        """Whether the strategy needs an inner chronological split of the training window."""
        ...

    def calibrate(
        self,
        raw: Floats,
        *,
        shift: QuantileShift | None,
    ) -> Floats: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MonotoneOnly:
    """C0 - project onto the monotone cone and nothing else."""

    strategy_id: str = "monotone_projection_v1"

    @property
    def needs_calibration_split(self) -> bool:
        return False

    def calibrate(self, raw: Floats, *, shift: QuantileShift | None = None) -> Floats:
        return monotone_projection(raw)

    def describe(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "steps": ["isotonic (PAV) projection onto the monotone cone"],
            "fitted_parameters": 0,
            "rationale": (
                "L2 projection onto a closed convex cone containing the true quantile "
                "vector, so the repair provably cannot move the estimate away from it"
            ),
        }


@dataclass(frozen=True, slots=True)
class ResidualShiftCalibration:
    """C1 - fold-fitted per-level residual shift, then monotone projection.

    Projection runs *after* the shift, because shifting five levels by five different
    constants can itself create a crossing, and the production contract is that nothing
    crossing ever leaves this module.
    """

    strategy_id: str = "residual_shift_then_monotone_v1"

    @property
    def needs_calibration_split(self) -> bool:
        return True

    def calibrate(self, raw: Floats, *, shift: QuantileShift | None = None) -> Floats:
        shifted = raw if shift is None else shift.apply(raw)
        return monotone_projection(shifted)

    def describe(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "steps": [
                "per-level additive shift from out-of-sample residual quantiles",
                "isotonic (PAV) projection onto the monotone cone",
            ],
            "fitted_parameters": "one constant per quantile level per position x scoring",
            "calibration_data": (
                "inner chronological split of the training window; the model producing the "
                "residuals is fitted on strictly earlier seasons than they are collected on"
            ),
            "coverage_semantics": (
                "marginal split-conformal coverage per level over the calibration "
                "distribution, not conditional coverage for an individual player"
            ),
        }


def season_array(frame: pl.DataFrame) -> Floats:
    """The season column as floats, for target scaling."""
    return frame.get_column("season").cast(pl.Float64).to_numpy()
