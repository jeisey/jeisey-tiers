"""Monotone projection, quantile calibration and the horizon target scale.

Three things are load-bearing and each is asserted directly:

* the projection is the **L2 projection onto the monotone cone**, not a sort, and the
  contraction property that justifies choosing it holds on random inputs;
* a calibration shift is learned from residuals and nothing else, so it can be checked
  against its own definition rather than against a fitted model's behaviour;
* the horizon transform restores exactly what it removed, and leaves a 17-week season alone.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.calibration import (
    MINIMUM_CALIBRATION_ROWS,
    HorizonNormalizedTarget,
    IdentityTarget,
    MonotoneOnly,
    QuantileShift,
    ResidualShiftCalibration,
    monotone_projection,
)
from ffdraft.modeling.metrics import QUANTILE_LEVELS, crossing_rate

LEVELS = QUANTILE_LEVELS


def test_projection_leaves_a_monotone_row_untouched() -> None:
    row = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
    assert np.array_equal(monotone_projection(row), row)


def test_projection_pools_a_violating_block_to_its_mean() -> None:
    """The hand-worked case: a single inversion becomes the pair's average, not a swap."""
    projected = monotone_projection(np.array([[1.0, 6.0, 2.0, 7.0, 9.0]]))
    assert projected.tolist() == [[1.0, 4.0, 4.0, 7.0, 9.0]]


def test_projection_is_not_a_sort() -> None:
    """The distinction the production choice rests on, made concrete."""
    row = np.array([[1.0, 6.0, 2.0, 7.0, 9.0]])
    assert not np.array_equal(monotone_projection(row), np.sort(row, axis=1))


def test_projection_handles_a_long_violating_run() -> None:
    projected = monotone_projection(np.array([[10.0, 8.0, 6.0, 4.0, 2.0]]))
    assert projected.tolist() == [[6.0] * 5]


def test_projection_removes_every_crossing() -> None:
    generator = np.random.default_rng(3)
    raw = generator.normal(0.0, 10.0, size=(500, len(LEVELS)))
    assert crossing_rate(raw) > 0.5
    assert crossing_rate(monotone_projection(raw)) == 0.0


def test_projection_never_moves_away_from_a_monotone_truth() -> None:
    """The contraction property that justifies the projection over an arbitrary sort.

    Projection onto a closed convex set cannot increase the distance to any point of that
    set, and the true quantile vector is in the monotone cone, so the repair provably cannot
    hurt. A plain sort has no such guarantee on an unevenly spaced level grid.
    """
    generator = np.random.default_rng(11)
    for _ in range(200):
        truth = np.sort(generator.normal(0.0, 20.0, size=len(LEVELS)))
        noisy = truth + generator.normal(0.0, 5.0, size=len(LEVELS))
        projected = monotone_projection(noisy[None, :])[0]
        assert np.linalg.norm(projected - truth) <= np.linalg.norm(noisy - truth) + 1e-9


def test_projection_of_an_empty_matrix_is_empty() -> None:
    assert monotone_projection(np.zeros((0, 5))).shape == (0, 5)


def test_shift_makes_calibration_coverage_exact_by_construction() -> None:
    """``shift_j = Quantile_j(y - qhat_j)`` gives level ``j`` exactly nominal coverage."""
    generator = np.random.default_rng(5)
    actual = generator.normal(100.0, 30.0, size=4000)
    predicted = np.tile(np.array([70.0, 85.0, 100.0, 115.0, 130.0]), (4000, 1))
    shift = QuantileShift.fit(actual, predicted, LEVELS)
    calibrated = shift.apply(predicted)
    for index, level in enumerate(LEVELS):
        assert float(np.mean(actual <= calibrated[:, index])) == pytest.approx(level, abs=0.01)


def test_shift_refuses_to_fit_on_too_few_rows() -> None:
    """Five level-specific empirical quantiles from a handful of residuals would be noise."""
    generator = np.random.default_rng(6)
    rows = MINIMUM_CALIBRATION_ROWS - 1
    shift = QuantileShift.fit(
        generator.normal(0.0, 1.0, size=rows),
        generator.normal(0.0, 1.0, size=(rows, len(LEVELS))),
        LEVELS,
    )
    assert not shift.fitted
    assert np.array_equal(shift.shifts, np.zeros(len(LEVELS)))
    raw = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
    assert np.array_equal(shift.apply(raw), raw)


def test_shift_is_a_function_of_residuals_alone() -> None:
    """Adding a constant to both sides cannot change the correction."""
    generator = np.random.default_rng(7)
    actual = generator.normal(50.0, 20.0, size=500)
    predicted = generator.normal(50.0, 20.0, size=(500, len(LEVELS)))
    base = QuantileShift.fit(actual, predicted, LEVELS)
    moved = QuantileShift.fit(actual + 40.0, predicted + 40.0, LEVELS)
    assert np.allclose(base.shifts, moved.shifts)


def test_monotone_only_strategy_needs_no_calibration_data() -> None:
    strategy = MonotoneOnly()
    assert strategy.needs_calibration_split is False
    raw = np.array([[5.0, 4.0, 3.0, 2.0, 1.0]])
    assert crossing_rate(strategy.calibrate(raw)) == 0.0


def test_residual_shift_strategy_projects_after_shifting() -> None:
    """A per-level shift can itself create a crossing; nothing crossing may leave the module."""
    strategy = ResidualShiftCalibration()
    assert strategy.needs_calibration_split is True
    raw = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
    shift = QuantileShift(tuple(LEVELS), np.array([0.0, 0.0, 20.0, 0.0, 0.0]), 500, True)
    calibrated = strategy.calibrate(raw, shift=shift)
    assert crossing_rate(calibrated) == 0.0


def test_identity_target_is_a_no_op() -> None:
    target = IdentityTarget()
    values = np.array([100.0, 200.0])
    seasons = np.array([2018.0, 2023.0])
    assert np.array_equal(target.forward(values, seasons), values)
    assert np.array_equal(target.inverse(values[None, :], 2023), values[None, :])


def test_horizon_target_divides_by_the_row_season_horizon() -> None:
    target = HorizonNormalizedTarget()
    values = np.array([160.0, 170.0])
    seasons = np.array([2018.0, 2023.0])
    # 2018 is a 16-week fantasy horizon; 2023 is 17.
    assert target.forward(values, seasons).tolist() == [10.0, 10.0]


def test_horizon_target_restores_the_validation_season_scale() -> None:
    target = HorizonNormalizedTarget()
    scaled = np.array([[10.0, 11.0, 12.0, 13.0, 14.0]])
    assert target.inverse(scaled, 2020).tolist() == [[160.0, 176.0, 192.0, 208.0, 224.0]]
    assert target.inverse(scaled, 2024).tolist() == [[170.0, 187.0, 204.0, 221.0, 238.0]]


def test_horizon_round_trip_within_one_modern_season_is_the_identity() -> None:
    """A 17-week season scaled and unscaled by 17 is unchanged; no needless drift."""
    target = HorizonNormalizedTarget()
    values = np.array([170.0, 85.0, 0.0])
    seasons = np.array([2024.0, 2024.0, 2024.0])
    scaled = target.forward(values, seasons)
    restored = target.inverse(scaled[None, :], 2024)[0]
    assert np.allclose(restored, values)


def test_horizon_target_uses_each_rows_own_season() -> None:
    """A training window spanning the 2021 boundary must not be scaled by one constant."""
    target = HorizonNormalizedTarget()
    frame = pl.DataFrame({"season": [2019, 2020, 2021, 2022]})
    values = np.array([160.0, 160.0, 170.0, 170.0])
    scaled = target.forward(values, frame.get_column("season").cast(pl.Float64).to_numpy())
    assert scaled.tolist() == [10.0, 10.0, 10.0, 10.0]
