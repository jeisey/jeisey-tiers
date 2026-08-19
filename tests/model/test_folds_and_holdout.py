"""Fold chronology, the two window policies, and the seal over the final holdout.

`docs/TEST_STRATEGY.md` 2.5 requires a test proving the final holdout cannot be used without
an explicit flag. These are those tests, plus the chronology guarantees every fold-based
claim in the experiment report rests on.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.modeling.dataset import build_modeling_frame, load_modeling_dataset
from ffdraft.modeling.folds import (
    DEVELOPMENT_VALIDATION_SEASONS,
    W1_DIAGNOSTIC_VALIDATION_SEASONS,
    Fold,
    FoldKind,
    WindowPolicy,
    development_folds,
    diagnostic_folds,
    final_holdout_fold,
    fold_table,
)
from ffdraft.modeling.holdout import (
    FINAL_EVAL_CONFIRMATION_TOKEN,
    FINAL_HOLDOUT_SEASON,
    PREDECLARED_HOLDOUT_SLICES,
    FinalEvalAuthorization,
    HoldoutSealError,
    HoldoutSliceKind,
    assert_seasons_sealed,
    slice_masks,
)

# --------------------------------------------------------------------------------------
# Chronology
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("window", list(WindowPolicy))
def test_every_development_fold_trains_strictly_before_it_validates(window):
    for fold in development_folds(window):
        assert fold.train_end_season < fold.validation_season
        assert max(fold.train_seasons) < fold.validation_season
        assert fold.validation_season not in fold.train_seasons


@pytest.mark.parametrize("window", list(WindowPolicy))
def test_both_windows_validate_exactly_the_same_seasons(window):
    seasons = tuple(fold.validation_season for fold in development_folds(window))
    assert seasons == DEVELOPMENT_VALIDATION_SEASONS


def test_the_windows_differ_only_in_where_training_starts():
    w1 = {fold.validation_season: fold for fold in development_folds(WindowPolicy.W1)}
    w2 = {fold.validation_season: fold for fold in development_folds(WindowPolicy.W2)}
    for season, fold in w1.items():
        assert fold.train_start_season == 2014
        assert w2[season].train_start_season == 2017
        assert fold.train_end_season == w2[season].train_end_season == season - 1


def test_w2_always_has_at_least_three_training_seasons():
    for fold in development_folds(WindowPolicy.W2):
        assert fold.n_train_seasons >= 3


def test_a_fold_that_trains_on_its_validation_season_is_refused():
    with pytest.raises(ValueError, match="strictly before"):
        Fold(
            window=WindowPolicy.W2,
            train_start_season=2017,
            train_end_season=2021,
            validation_season=2021,
        )


def test_a_fold_may_not_start_before_its_window_allows():
    with pytest.raises(ValueError, match="first allowed training season"):
        Fold(
            window=WindowPolicy.W2,
            train_start_season=2014,
            train_end_season=2019,
            validation_season=2020,
        )


def test_diagnostic_folds_are_w1_only_and_labelled_as_such():
    folds = diagnostic_folds()
    assert tuple(fold.validation_season for fold in folds) == W1_DIAGNOSTIC_VALIDATION_SEASONS
    assert {fold.kind for fold in folds} == {FoldKind.W1_DIAGNOSTIC}
    with pytest.raises(ValueError, match="cannot validate"):
        diagnostic_folds(WindowPolicy.W2)


def test_the_fold_table_is_deterministic_and_carries_the_window_policy():
    folds = [*development_folds(WindowPolicy.W1), *development_folds(WindowPolicy.W2)]
    first, second = fold_table(folds), fold_table(list(reversed(folds)))
    assert first == second
    assert {row["window_policy"] for row in first} == {
        str(WindowPolicy.W1),
        str(WindowPolicy.W2),
    }


# --------------------------------------------------------------------------------------
# The seal
# --------------------------------------------------------------------------------------


def test_development_folds_refuse_the_final_holdout_season():
    with pytest.raises(HoldoutSealError, match="sealed"):
        development_folds(WindowPolicy.W2, [2024, FINAL_HOLDOUT_SEASON])


def test_assert_seasons_sealed_names_the_offending_seasons():
    with pytest.raises(HoldoutSealError, match=r"\[2025\]"):
        assert_seasons_sealed([2020, 2025], context="unit test")


def test_a_final_holdout_fold_needs_an_authorization():
    with pytest.raises(TypeError):
        final_holdout_fold(WindowPolicy.W2)  # type: ignore[call-arg]


def test_the_authorization_requires_the_exact_token():
    with pytest.raises(HoldoutSealError, match="confirmation token"):
        FinalEvalAuthorization(confirmation="please", reason="curiosity")
    with pytest.raises(HoldoutSealError, match="recorded reason"):
        FinalEvalAuthorization(confirmation=FINAL_EVAL_CONFIRMATION_TOKEN, reason="  ")


def test_an_authorized_final_fold_is_chronological_and_labelled():
    authorization = FinalEvalAuthorization(
        confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="phase 4 final evaluation",
    )
    fold = final_holdout_fold(WindowPolicy.W2, authorization=authorization)
    assert fold.validation_season == FINAL_HOLDOUT_SEASON
    assert fold.train_end_season == FINAL_HOLDOUT_SEASON - 1
    assert fold.kind is FoldKind.FINAL_HOLDOUT


def test_the_modelling_frame_physically_drops_the_sealed_season(
    synthetic_feature_frame,
    synthetic_label_frame,
):
    dataset = build_modeling_frame(synthetic_feature_frame, synthetic_label_frame)
    assert FINAL_HOLDOUT_SEASON not in dataset.seasons
    assert dataset.withheld_seasons == (FINAL_HOLDOUT_SEASON,)
    assert dataset.withheld_rows > 0
    assert dataset.sealed


def test_an_authorized_frame_keeps_the_sealed_season(
    synthetic_feature_frame,
    synthetic_label_frame,
):
    authorization = FinalEvalAuthorization(
        confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="phase 4 final evaluation",
    )
    dataset = build_modeling_frame(
        synthetic_feature_frame,
        synthetic_label_frame,
        authorization=authorization,
    )
    assert FINAL_HOLDOUT_SEASON in dataset.seasons
    assert not dataset.sealed


def test_a_development_experiment_refuses_an_unsealed_frame(
    synthetic_feature_frame,
    synthetic_label_frame,
):
    from ffdraft.modeling.experiment import ExperimentConfig, run_experiment

    authorization = FinalEvalAuthorization(
        confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="deliberate misuse",
    )
    dataset = build_modeling_frame(
        synthetic_feature_frame,
        synthetic_label_frame,
        authorization=authorization,
    )
    with pytest.raises(ValueError, match="unsealed"):
        run_experiment(dataset, config=ExperimentConfig(model_ids=("B0",)))


def test_poisoning_the_sealed_labels_cannot_change_a_development_result(
    synthetic_feature_frame,
    synthetic_label_frame,
):
    """The constructive proof: replace every 2025 label and the development run is identical.

    Phase 2 proved target-season independence by rebuilding with the season's statistics
    deleted rather than by inspecting code. This is the Phase-3 equivalent for the holdout:
    if any development number moved, something read a sealed label.
    """
    from ffdraft.contracts import frame_content_hash
    from ffdraft.modeling.experiment import ExperimentConfig, run_experiment

    config = ExperimentConfig(
        windows=(WindowPolicy.W2,),
        model_ids=("B0",),
        validation_seasons=(2023, 2024),
        include_w1_diagnostic_folds=False,
        bootstrap_replicates=25,
    )
    honest = build_modeling_frame(synthetic_feature_frame, synthetic_label_frame)
    poisoned_labels = synthetic_label_frame.with_columns(
        pl.when(pl.col("season") >= FINAL_HOLDOUT_SEASON)
        .then(pl.lit(-99999.0))
        .otherwise(pl.col("actual_fantasy_points"))
        .alias("actual_fantasy_points"),
    )
    poisoned = build_modeling_frame(synthetic_feature_frame, poisoned_labels)

    first = run_experiment(honest, config=config)
    second = run_experiment(poisoned, config=config)
    assert first.aggregates == second.aggregates
    assert frame_content_hash(first.predictions) == frame_content_hash(second.predictions)


# --------------------------------------------------------------------------------------
# Predeclared final-holdout slices
# --------------------------------------------------------------------------------------


def test_exactly_one_slice_is_primary_and_it_is_the_full_universe():
    primary = [item for item in PREDECLARED_HOLDOUT_SLICES if item.kind is HoldoutSliceKind.PRIMARY]
    assert len(primary) == 1
    assert primary[0].slice_id == "full_universe"


def test_the_predeclared_slices_cover_the_required_dimensions():
    declared = {item.slice_id for item in PREDECLARED_HOLDOUT_SLICES}
    assert {
        "era_stable_universe",
        "rookie",
        "veteran",
        "depth_context_state",
        "position",
        "scoring_preset",
        "information_rich",
        "low_information",
    } <= declared


def test_every_declared_slice_has_an_executable_mask(
    synthetic_feature_frame,
    synthetic_label_frame,
):
    authorization = FinalEvalAuthorization(
        confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="slice definition check",
    )
    dataset = build_modeling_frame(
        synthetic_feature_frame,
        synthetic_label_frame,
        authorization=authorization,
    )
    frame = dataset.frame.filter(pl.col("season") == FINAL_HOLDOUT_SEASON)
    masks = slice_masks(frame)
    assert {mask.slice_id for mask in masks} == {
        item.slice_id for item in PREDECLARED_HOLDOUT_SLICES
    }
    for mask in masks:
        frame.filter(mask.mask)  # must evaluate without raising


def test_the_era_stable_subset_excludes_snapshot_only_eligibility():
    frame = pl.DataFrame(
        {
            "eligibility_basis": [
                "prior_season_roster",
                "draft_class",
                "depth_snapshot_pre_anchor",
                "depth_snapshot_pre_anchor|prior_season_roster",
            ],
            "rookie_flag": [False, True, False, False],
            "has_prior_season_stats": [True, False, True, True],
            "prev1_games": [16, None, 12, 9],
            "depth_context_state": ["a", "a", "a", "a"],
            "position": ["RB", "RB", "RB", "RB"],
            "scoring_preset": ["PPR", "PPR", "PPR", "PPR"],
        },
    )
    mask = next(item for item in slice_masks(frame) if item.slice_id == "era_stable_universe")
    kept = frame.filter(mask.mask)
    assert kept.height == 3
    assert "depth_snapshot_pre_anchor" not in kept.get_column("eligibility_basis").to_list()


def test_loading_from_disk_seals_the_holdout(
    tmp_path, synthetic_feature_frame, synthetic_label_frame
):
    synthetic_feature_frame.write_parquet(tmp_path / "features.parquet")
    synthetic_label_frame.write_parquet(tmp_path / "labels_fantasy.parquet")
    dataset = load_modeling_dataset(tmp_path)
    assert FINAL_HOLDOUT_SEASON not in dataset.seasons
    assert dataset.withheld_rows > 0
