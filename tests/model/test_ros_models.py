"""The declared rest-of-season baselines and the single candidate.

Every model is exercised on the synthetic snapshot dataset through the real fold, the real
feature selection and the real estimator interface, so a test failing here means the model
is genuinely broken rather than a harness shim being wrong.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.metrics import QUANTILE_LEVELS, crossing_rate
from ffdraft.ros.baselines import (
    ROS_BASELINE_DECLARATION_ORDER,
    SHRINKAGE_GRID,
    AvailabilityPriorBaseline,
    CurrentFormBaseline,
    PreseasonProratedBaseline,
    ShrinkageBlendBaseline,
)
from ffdraft.ros.candidates import RC1_PARAMETERS, RC1_VERSION, RosHurdleCandidate
from ffdraft.ros.estimators import ROS_TARGET_COLUMN


def _split(dataset, context):
    group = (pl.col("position") == context.position) & (
        pl.col("scoring_preset") == context.scoring_preset
    )
    train = dataset.frame.filter(
        pl.col("season").is_in(list(context.fold.train_seasons)) & group,
    )
    validate = dataset.frame.filter(
        (pl.col("season") == context.fold.validation_season) & group,
    )
    return train, validate


def _models(preseason):
    return {
        "R0": PreseasonProratedBaseline(preseason),
        "R1": CurrentFormBaseline(),
        "R2": ShrinkageBlendBaseline(preseason),
        "R3": AvailabilityPriorBaseline(),
        "RC1": RosHurdleCandidate(num_boost_round=40, composition_draws=200),
    }


@pytest.fixture(scope="module")
def blocks(ros_dataset, ros_preseason_frame, ros_fit_context):
    train, validate = _split(ros_dataset, ros_fit_context)
    assert train.height and validate.height
    return {
        model_id: model.fit_predict(train, validate, ros_fit_context)
        for model_id, model in _models(ros_preseason_frame).items()
    }


def test_the_declaration_order_matches_the_implemented_baselines(ros_preseason_frame) -> None:
    assert tuple(_models(ros_preseason_frame))[:-1] == ROS_BASELINE_DECLARATION_ORDER


def test_every_model_predicts_one_row_per_validation_row(
    blocks, ros_dataset, ros_fit_context
) -> None:
    _, validate = _split(ros_dataset, ros_fit_context)
    for model_id, block in blocks.items():
        assert block.keys.height == validate.height, model_id
        assert block.point.shape == (validate.height,)
        assert block.quantiles.shape == (validate.height, len(QUANTILE_LEVELS))


def test_every_model_emits_monotone_quantiles(blocks) -> None:
    for model_id, block in blocks.items():
        assert crossing_rate(block.quantiles) == 0.0, model_id


def test_every_model_is_finite(blocks) -> None:
    for model_id, block in blocks.items():
        assert np.all(np.isfinite(block.point)), model_id
        assert np.all(np.isfinite(block.quantiles)), model_id


def test_the_candidate_is_deterministic_across_runs(
    ros_dataset,
    ros_preseason_frame,
    ros_fit_context,
) -> None:
    """Multi-threaded LightGBM with the frozen flags must reproduce bit for bit.

    RC1 differs from Q1 in exactly one parameter - the thread count - and the whole
    justification for changing it is that ``deterministic`` and ``force_row_wise`` make the
    result thread-count independent. That is asserted here rather than assumed.
    """
    train, validate = _split(ros_dataset, ros_fit_context)
    first = RosHurdleCandidate(num_boost_round=40, composition_draws=200)
    second = RosHurdleCandidate(num_boost_round=40, composition_draws=200)
    left = first.fit_predict(train, validate, ros_fit_context)
    right = second.fit_predict(train, validate, ros_fit_context)
    assert np.array_equal(left.point, right.point)
    assert np.array_equal(left.quantiles, right.quantiles)


def test_the_candidate_matches_a_single_threaded_fit(
    ros_dataset,
    ros_preseason_frame,
    ros_fit_context,
) -> None:
    train, validate = _split(ros_dataset, ros_fit_context)
    threaded = RosHurdleCandidate(num_boost_round=40, composition_draws=200)
    serial = RosHurdleCandidate(
        parameters={**RC1_PARAMETERS, "num_threads": 1},
        num_boost_round=40,
        composition_draws=200,
    )
    assert np.array_equal(
        threaded.fit_predict(train, validate, ros_fit_context).quantiles,
        serial.fit_predict(train, validate, ros_fit_context).quantiles,
    )


def test_the_baselines_are_deterministic(
    ros_dataset,
    ros_preseason_frame,
    ros_fit_context,
) -> None:
    train, validate = _split(ros_dataset, ros_fit_context)
    for model_id in ROS_BASELINE_DECLARATION_ORDER:
        left = _models(ros_preseason_frame)[model_id].fit_predict(train, validate, ros_fit_context)
        right = _models(ros_preseason_frame)[model_id].fit_predict(train, validate, ros_fit_context)
        assert np.array_equal(left.point, right.point), model_id


def test_the_prorated_prior_shrinks_as_the_season_runs_out(
    blocks,
    ros_dataset,
    ros_fit_context,
) -> None:
    """R0 is a season expectation times the share of the horizon left, so late is smaller."""
    _, validate = _split(ros_dataset, ros_fit_context)
    frame = validate.select("player_id", "through_week").with_columns(
        pl.Series("prediction", blocks["R0"].point, dtype=pl.Float64),
    )
    by_week = (
        frame.filter(pl.col("prediction") > 0)
        .group_by("through_week")
        .agg(pl.col("prediction").mean().alias("mean"))
        .sort("through_week")
    )
    values = by_week.get_column("mean").to_list()
    assert values[0] > values[-1]


def test_the_current_form_baseline_predicts_zero_before_a_player_appears(
    blocks,
    ros_dataset,
    ros_fit_context,
) -> None:
    _, validate = _split(ros_dataset, ros_fit_context)
    frame = validate.select("games_to_date").with_columns(
        pl.Series("prediction", blocks["R1"].point, dtype=pl.Float64),
    )
    unplayed = frame.filter(pl.col("games_to_date") == 0)
    assert unplayed.height > 0
    assert unplayed.get_column("prediction").abs().max() == 0.0


def test_the_blend_records_the_shrinkage_it_chose(blocks) -> None:
    diagnostics = blocks["R2"].diagnostics
    assert diagnostics["shrinkage"] in SHRINKAGE_GRID
    assert len(diagnostics["inner_mae_by_shrinkage"]) == len(SHRINKAGE_GRID)


def test_the_candidate_records_its_dependence_parameter(blocks) -> None:
    diagnostics = blocks["RC1"].diagnostics
    assert -0.95 <= diagnostics["dependence_correlation"] <= 0.95
    assert diagnostics["features_used"] <= diagnostics["features_offered"]


def test_the_candidate_scores_a_player_with_no_remaining_games_at_zero(
    ros_dataset,
    ros_fit_context,
) -> None:
    """The hurdle's composition rule: zero games scores exactly zero, never a small number."""
    train, validate = _split(ros_dataset, ros_fit_context)
    never = validate.filter(pl.col("gsis_id") == "00-WR0000")
    assert never.height > 0
    assert never.get_column(ROS_TARGET_COLUMN).abs().max() == 0.0


def test_the_candidate_describes_itself_with_its_version() -> None:
    described = RosHurdleCandidate().describe()
    assert described["version"] == RC1_VERSION
    assert described["tuning"].startswith("none")
    assert set(described["components"]) == {"availability", "performance"}
