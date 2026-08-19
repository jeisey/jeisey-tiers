"""The Phase-4 candidates: calibrated Candidate A and the Candidate B hurdle.

The assertions that matter are structural rather than numerical. A model here is handed one
fold's training rows and one fold's validation rows, so the tests can prove fold isolation
the same way the Phase-3 suite proves the holdout seal: poison the validation labels and
require the predictions to be byte-identical. Anything that had peeked would move.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.calibration import (
    HorizonNormalizedTarget,
    MonotoneOnly,
    ResidualShiftCalibration,
)
from ffdraft.modeling.candidates import (
    AvailabilityPerformanceCandidate,
    CalibratedQuantileCandidate,
    LightGbmQuantileCandidate,
)
from ffdraft.modeling.dataset import TARGET_COLUMN
from ffdraft.modeling.estimators import FitContext
from ffdraft.modeling.folds import WindowPolicy, development_folds
from ffdraft.modeling.metrics import crossing_rate
from ffdraft.simulation.sampler import DomainBounds, QuantileFunction


@pytest.fixture(scope="module")
def fold_frames(synthetic_modeling_dataset):
    fold = development_folds(WindowPolicy.W1, (2022,))[0]
    train, validate = synthetic_modeling_dataset.fold_frames(fold)
    mask = (pl.col("position") == "RB") & (pl.col("scoring_preset") == "PPR")
    context = FitContext(
        fold=fold,
        position="RB",
        scoring_preset="PPR",
        features=tuple(synthetic_modeling_dataset.selection.included),
        seed=101,
    )
    return train.filter(mask), validate.filter(mask), context


def _poison(frame: pl.DataFrame) -> pl.DataFrame:
    """Replace every outcome column with nonsense, leaving features untouched."""
    return frame.with_columns(
        pl.lit(9999.0).alias(TARGET_COLUMN),
        pl.lit(1).cast(pl.Int32).alias("actual_games_played"),
    )


# ---------------------------------------------------------------------------------------
# Candidate A, calibrated
# ---------------------------------------------------------------------------------------


def test_calibrated_candidate_never_emits_crossing_quantiles(fold_frames) -> None:
    train, validate, context = fold_frames
    for strategy in (MonotoneOnly(), ResidualShiftCalibration()):
        block = CalibratedQuantileCandidate("A", calibration=strategy).fit_predict(
            train,
            validate,
            context,
        )
        assert crossing_rate(block.quantiles) == 0.0
        assert block.quantiles.shape == (validate.height, 5)
        assert np.all(np.isfinite(block.quantiles))


def test_calibrated_candidate_reports_the_defect_it_repaired(fold_frames) -> None:
    """The raw crossing rate is measured before the repair, so the fix cannot hide it."""
    train, validate, context = fold_frames
    block = CalibratedQuantileCandidate("A", calibration=MonotoneOnly()).fit_predict(
        train,
        validate,
        context,
    )
    assert block.diagnostics["crossing_rate_post"] == 0.0
    assert block.diagnostics["crossing_rate_raw"] == crossing_rate(block.raw_quantiles)


def test_calibration_is_fitted_without_any_validation_outcome(fold_frames) -> None:
    train, validate, context = fold_frames
    model = CalibratedQuantileCandidate("A", calibration=ResidualShiftCalibration())
    clean = model.fit_predict(train, validate, context)
    poisoned = model.fit_predict(train, _poison(validate), context)
    assert np.array_equal(clean.quantiles, poisoned.quantiles)


def test_calibration_uses_an_inner_split_of_the_training_window(fold_frames) -> None:
    train, validate, context = fold_frames
    block = CalibratedQuantileCandidate("A", calibration=ResidualShiftCalibration()).fit_predict(
        train,
        validate,
        context,
    )
    fit_seasons = block.diagnostics["inner_fit_seasons"]
    residual_seasons = block.diagnostics["inner_residual_seasons"]
    assert max(fit_seasons) < min(residual_seasons)
    assert max(residual_seasons) < context.fold.validation_season
    assert block.diagnostics["shift"]["fitted"] is True


def test_calibration_moves_the_intervals_it_is_supposed_to_move(fold_frames) -> None:
    train, validate, context = fold_frames
    plain = CalibratedQuantileCandidate("A0", calibration=MonotoneOnly()).fit_predict(
        train,
        validate,
        context,
    )
    calibrated = CalibratedQuantileCandidate(
        "A1",
        calibration=ResidualShiftCalibration(),
    ).fit_predict(train, validate, context)
    assert not np.allclose(plain.quantiles, calibrated.quantiles)


def test_the_horizon_variant_changes_the_target_not_the_features(fold_frames) -> None:
    train, validate, context = fold_frames
    block = CalibratedQuantileCandidate(
        "AH",
        calibration=MonotoneOnly(),
        target=HorizonNormalizedTarget(),
    ).fit_predict(train, validate, context)
    plain = CalibratedQuantileCandidate("A0", calibration=MonotoneOnly()).fit_predict(
        train,
        validate,
        context,
    )
    assert block.diagnostics["target_scale"] == "points_per_horizon_week"
    assert block.diagnostics["features_used"] == plain.diagnostics["features_used"]
    # Predictions are on the fantasy-point scale, not the per-week one.
    assert float(np.median(block.quantiles[:, 2])) > 1.0


def test_q1_is_untouched_by_phase_four(fold_frames) -> None:
    """Phase-3 evidence must remain reproducible, so Q1 keeps its exact behaviour."""
    train, validate, context = fold_frames
    first = LightGbmQuantileCandidate().fit_predict(train, validate, context)
    second = LightGbmQuantileCandidate().fit_predict(train, validate, context)
    assert np.array_equal(first.quantiles, second.quantiles)
    assert first.diagnostics["crossing_rate_raw"] == second.diagnostics["crossing_rate_raw"]


# ---------------------------------------------------------------------------------------
# Candidate B
# ---------------------------------------------------------------------------------------


def test_candidate_b_produces_a_valid_distribution_for_every_row(fold_frames) -> None:
    train, validate, context = fold_frames
    block = AvailabilityPerformanceCandidate(composition_draws=400).fit_predict(
        train,
        validate,
        context,
    )
    assert block.quantiles.shape == (validate.height, 5)
    assert np.all(np.isfinite(block.quantiles))
    assert crossing_rate(block.quantiles) == 0.0


def test_candidate_b_composition_is_monotone_by_construction(fold_frames) -> None:
    """Empirical quantiles of one Monte Carlo sample cannot cross, which is the point."""
    train, validate, context = fold_frames
    block = AvailabilityPerformanceCandidate(composition_draws=400).fit_predict(
        train,
        validate,
        context,
    )
    assert block.diagnostics["crossing_rate_raw"] == 0.0


def test_candidate_b_is_deterministic(fold_frames) -> None:
    train, validate, context = fold_frames
    model = AvailabilityPerformanceCandidate(composition_draws=400)
    first = model.fit_predict(train, validate, context)
    second = model.fit_predict(train, validate, context)
    assert np.array_equal(first.quantiles, second.quantiles)
    assert (
        first.diagnostics["dependence_correlation"] == second.diagnostics["dependence_correlation"]
    )


def test_candidate_b_never_sees_a_validation_outcome(fold_frames) -> None:
    train, validate, context = fold_frames
    model = AvailabilityPerformanceCandidate(composition_draws=400)
    clean = model.fit_predict(train, validate, context)
    poisoned = model.fit_predict(train, _poison(validate), context)
    assert np.array_equal(clean.quantiles, poisoned.quantiles)


def test_candidate_b_keeps_every_row_including_low_information_ones(fold_frames) -> None:
    train, validate, context = fold_frames
    block = AvailabilityPerformanceCandidate(composition_draws=400).fit_predict(
        train,
        validate,
        context,
    )
    assert block.keys.height == validate.height
    rookies = validate.filter(pl.col("rookie_flag"))
    assert rookies.height > 0
    assert block.keys.filter(pl.col("rookie_flag")).height == rookies.height


def test_candidate_b_fits_dependence_and_records_it(fold_frames) -> None:
    train, validate, context = fold_frames
    block = AvailabilityPerformanceCandidate(composition_draws=400).fit_predict(
        train,
        validate,
        context,
    )
    correlation = block.diagnostics["dependence_correlation"]
    assert -0.95 <= correlation <= 0.95
    assert block.diagnostics["dependence_rows"] > 0


def test_candidate_b_performance_component_ignores_zero_game_rows(fold_frames) -> None:
    """Points per game is undefined without games, so a zero-game row cannot define it.

    Two training frames differ only in the *points* recorded against rows that played no
    games - zero in one, absurd in the other. The availability component sees identical
    games in both, and the performance component excludes those rows entirely, so the
    predictions must be bit-identical. If a zero-game row ever leaked into the conditional
    component this test would blow up rather than drift.
    """
    train, validate, context = fold_frames
    half = train.height // 3
    marker = pl.int_range(pl.len()) < half
    realistic = train.with_columns(
        pl.when(marker)
        .then(pl.lit(0))
        .otherwise(pl.col("actual_games_played"))
        .cast(pl.Int32)
        .alias(
            "actual_games_played",
        ),
        pl.when(marker).then(pl.lit(0.0)).otherwise(pl.col(TARGET_COLUMN)).alias(TARGET_COLUMN),
    )
    absurd = realistic.with_columns(
        pl.when(marker)
        .then(pl.lit(50_000.0))
        .otherwise(pl.col(TARGET_COLUMN))
        .alias(
            TARGET_COLUMN,
        ),
    )
    assert realistic.filter(pl.col("actual_games_played") == 0).height == half

    model = AvailabilityPerformanceCandidate(composition_draws=400)
    assert np.array_equal(
        model.fit_predict(realistic, validate, context).quantiles,
        model.fit_predict(absurd, validate, context).quantiles,
    )


def test_candidate_b_composition_respects_the_horizon_and_the_zero_case() -> None:
    """Games are bounded by the horizon, and zero games scores exactly zero."""
    model = AvailabilityPerformanceCandidate(composition_draws=64)
    frame = pl.DataFrame({"player_id": ["a", "b"], "season": [2023, 2023]})
    levels = (0.10, 0.25, 0.50, 0.75, 0.90)

    always = QuantileFunction(levels, np.ones((2, 5)), DomainBounds(0.0, 1.0))
    never = QuantileFunction(levels, np.zeros((2, 5)), DomainBounds(0.0, 1.0))
    performance = QuantileFunction(
        levels,
        np.tile(np.array([10.0, 10.0, 10.0, 10.0, 10.0]), (2, 1)),
        DomainBounds(0.0, 100.0),
    )

    full = model._compose(
        frame,
        always,
        performance,
        correlation=0.0,
        levels=levels,
        season=2023,
        context_key="test",
    )
    assert np.allclose(full, 17.0 * 10.0)

    empty = model._compose(
        frame,
        never,
        performance,
        correlation=0.0,
        levels=levels,
        season=2023,
        context_key="test",
    )
    assert np.allclose(empty, 0.0)


def test_candidate_b_composition_uses_the_seasons_own_horizon() -> None:
    """A 16-week season cannot produce 17 games."""
    model = AvailabilityPerformanceCandidate(composition_draws=32)
    frame = pl.DataFrame({"player_id": ["a"], "season": [2019]})
    levels = (0.10, 0.25, 0.50, 0.75, 0.90)
    always = QuantileFunction(levels, np.ones((1, 5)), DomainBounds(0.0, 1.0))
    performance = QuantileFunction(levels, np.ones((1, 5)), DomainBounds(0.0, 10.0))
    composed = model._compose(
        frame,
        always,
        performance,
        correlation=0.0,
        levels=levels,
        season=2019,
        context_key="test",
    )
    assert np.allclose(composed, 16.0)


def test_candidate_b_negative_totals_are_possible() -> None:
    """This project's scoring makes a negative season real; nothing clips at zero."""
    model = AvailabilityPerformanceCandidate(composition_draws=64)
    frame = pl.DataFrame({"player_id": ["a"], "season": [2023]})
    levels = (0.10, 0.25, 0.50, 0.75, 0.90)
    always = QuantileFunction(levels, np.ones((1, 5)), DomainBounds(0.0, 1.0))
    losing = QuantileFunction(
        levels,
        np.tile(np.array([-2.0, -2.0, -2.0, -2.0, -2.0]), (1, 1)),
        DomainBounds(-5.0, 0.0),
    )
    composed = model._compose(
        frame,
        always,
        losing,
        correlation=0.0,
        levels=levels,
        season=2023,
        context_key="test",
    )
    assert float(np.max(composed)) < 0.0
