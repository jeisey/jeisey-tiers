"""The rest-of-season evaluation protocol: folds, the seal, and the predeclared slices."""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.modeling.holdout import (
    FINAL_EVAL_CONFIRMATION_TOKEN,
    FinalEvalAuthorization,
    HoldoutSealError,
)
from ffdraft.ros.folds import (
    ROS_DEVELOPMENT_VALIDATION_SEASONS,
    ROS_TRAIN_START_SEASON,
    RosFold,
    RosFoldKind,
    ros_development_folds,
    ros_final_fold,
    ros_fold_table,
)
from ffdraft.ros.holdout import (
    PREDECLARED_ROS_SLICES,
    ROS_FINAL_EVAL_CONFIRMATION_TOKEN,
    ROS_SEALED_SEASON,
    RosFinalEvalAuthorization,
    RosSliceKind,
    assert_ros_seasons_sealed,
    ros_holdout_policy,
    ros_slice_masks,
)


def test_every_fold_trains_strictly_before_the_season_it_scores() -> None:
    for fold in ros_development_folds():
        assert fold.train_end_season < fold.validation_season
        assert fold.train_start_season == ROS_TRAIN_START_SEASON
        assert fold.kind is RosFoldKind.DEVELOPMENT


def test_the_window_expands_and_the_validation_seasons_are_the_declared_ones() -> None:
    folds = ros_development_folds()
    assert [fold.validation_season for fold in folds] == list(
        ROS_DEVELOPMENT_VALIDATION_SEASONS,
    )
    assert [fold.n_train_seasons for fold in folds] == [3, 4, 5, 6, 7]


def test_a_fold_that_trains_on_its_own_validation_season_is_refused() -> None:
    with pytest.raises(ValueError, match="strictly before"):
        RosFold(train_start_season=2017, train_end_season=2021, validation_season=2021)


def test_a_window_starting_before_the_inherited_first_season_is_refused() -> None:
    with pytest.raises(ValueError, match="first allowed training season"):
        RosFold(train_start_season=2014, train_end_season=2019, validation_season=2020)


def test_development_folds_refuse_the_sealed_season() -> None:
    with pytest.raises(HoldoutSealError, match="sealed"):
        ros_development_folds([2025])


def test_the_final_fold_needs_the_rest_of_season_token() -> None:
    with pytest.raises(HoldoutSealError, match="RELEASE-ROS-FINAL-HOLDOUT-2025"):
        RosFinalEvalAuthorization(confirmation="wrong", reason="curiosity")
    with pytest.raises(HoldoutSealError, match="recorded reason"):
        RosFinalEvalAuthorization(
            confirmation=ROS_FINAL_EVAL_CONFIRMATION_TOKEN,
            reason="   ",
        )
    authorization = RosFinalEvalAuthorization(
        confirmation=ROS_FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="the frozen architecture is being evaluated once",
    )
    fold = ros_final_fold(authorization=authorization)
    assert fold.validation_season == ROS_SEALED_SEASON
    assert fold.kind is RosFoldKind.FINAL_HOLDOUT


def test_release_one_s_token_does_not_open_the_rest_of_season_holdout() -> None:
    """Opening one holdout must never open the other."""
    with pytest.raises(HoldoutSealError):
        RosFinalEvalAuthorization(
            confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
            reason="wrong holdout",
        )
    # ...and the reverse, so the asymmetry is not an accident of spelling.
    with pytest.raises(HoldoutSealError):
        FinalEvalAuthorization(
            confirmation=ROS_FINAL_EVAL_CONFIRMATION_TOKEN,
            reason="wrong holdout",
        )


def test_the_seal_assertion_passes_only_with_an_authorization() -> None:
    with pytest.raises(HoldoutSealError):
        assert_ros_seasons_sealed([2024, 2025], context="a test")
    assert_ros_seasons_sealed([2024])
    assert_ros_seasons_sealed(
        [2025],
        authorization=RosFinalEvalAuthorization(
            confirmation=ROS_FINAL_EVAL_CONFIRMATION_TOKEN,
            reason="explicit",
        ),
    )


def test_the_fold_table_serializes_in_a_stable_order() -> None:
    table = ros_fold_table(list(reversed(ros_development_folds())))
    assert [row["validation_season"] for row in table] == sorted(
        ROS_DEVELOPMENT_VALIDATION_SEASONS,
    )


def test_exactly_one_slice_is_primary_and_the_rest_are_diagnostic() -> None:
    primary = [item for item in PREDECLARED_ROS_SLICES if item.kind is RosSliceKind.PRIMARY]
    assert len(primary) == 1
    assert primary[0].slice_id == "full_universe"


def test_every_declared_slice_has_an_executable_mask(ros_dataset) -> None:
    frame = ros_dataset.frame.with_columns(
        pl.lit(1.0).alias("baseline_interval_width"),
    )
    masks = ros_slice_masks(frame)
    assert {mask.slice_id for mask in masks} == {item.slice_id for item in PREDECLARED_ROS_SLICES}
    for mask in masks:
        # Every mask has to evaluate against the real frame, not merely be constructible.
        frame.filter(mask.mask)


def test_the_rookie_and_veteran_slices_partition_the_frame(ros_dataset) -> None:
    frame = ros_dataset.frame.with_columns(pl.lit(1.0).alias("baseline_interval_width"))
    masks = {mask.slice_id: mask for mask in ros_slice_masks(frame)}
    rookie = frame.filter(masks["rookie"].mask).height
    veteran = frame.filter(masks["veteran"].mask).height
    assert rookie + veteran == frame.height


def test_the_games_played_bands_partition_the_frame(ros_dataset) -> None:
    frame = ros_dataset.frame.with_columns(pl.lit(1.0).alias("baseline_interval_width"))
    bands = [mask for mask in ros_slice_masks(frame) if mask.slice_id == "games_played_band"]
    assert len(bands) == 3
    assert sum(frame.filter(mask.mask).height for mask in bands) == frame.height


def test_the_holdout_policy_records_the_prior_exposure() -> None:
    policy = ros_holdout_policy()
    assert policy["sealed_season"] == ROS_SEALED_SEASON
    assert policy["declared_before_candidate_comparison"] is True
    assert "Phase 4" in policy["prior_exposure"]
    assert len(policy["slices"]) == len(PREDECLARED_ROS_SLICES)
