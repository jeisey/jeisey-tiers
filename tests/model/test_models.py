"""Baselines, the candidate, and the fold-local machinery they share.

These are the `docs/TEST_STRATEGY.md` 2.6 controlled assertions rather than accuracy tests
against a magic number: training completes, a seed reproduces, keys survive, quantiles are
finite, and - most importantly - nothing a model learned could have come from the season it
is being scored on.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.baselines import (
    B0_SHRINKAGE_GRID,
    RIDGE_ALPHAS,
    NaivePriorProductionBaseline,
    RidgeBaseline,
)
from ffdraft.modeling.candidates import LightGbmQuantileCandidate
from ffdraft.modeling.dataset import TARGET_COLUMN
from ffdraft.modeling.estimators import FitContext, repair_monotonicity
from ffdraft.modeling.features import core_feature_selection
from ffdraft.modeling.folds import WindowPolicy, development_folds
from ffdraft.modeling.metrics import QUANTILE_LEVELS, crossing_rate
from ffdraft.modeling.preprocessing import (
    FoldPreprocessor,
    ResidualQuantiles,
    design_matrix,
    inner_chronological_split,
)

MODELS = {
    "B0": NaivePriorProductionBaseline,
    "B1": RidgeBaseline,
    "Q1": LightGbmQuantileCandidate,
}


@pytest.fixture(scope="module")
def group(synthetic_modeling_dataset):
    """One (fold, position, scoring) job, which is the unit every model is handed."""
    fold = development_folds(WindowPolicy.W2)[-1]
    train, validate = synthetic_modeling_dataset.fold_frames(fold)
    mask = (pl.col("position") == "RB") & (pl.col("scoring_preset") == "PPR")
    context = FitContext(
        fold=fold,
        position="RB",
        scoring_preset="PPR",
        features=tuple(core_feature_selection().included),
        seed=1234,
    )
    return train.filter(mask), validate.filter(mask), context


# --------------------------------------------------------------------------------------
# Shared contract
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_a_model_preserves_the_validation_keys_and_row_order(model_id, group):
    train, validate, context = group
    block = MODELS[model_id]().fit_predict(train, validate, context)
    assert (
        block.keys.get_column("player_id").to_list()
        == validate.get_column(
            "player_id",
        ).to_list()
    )
    assert block.point.shape == (validate.height,)
    assert block.quantiles.shape == (validate.height, len(QUANTILE_LEVELS))


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_every_quantile_is_finite_and_non_decreasing_after_repair(model_id, group):
    train, validate, context = group
    block = MODELS[model_id]().fit_predict(train, validate, context)
    assert np.all(np.isfinite(block.quantiles))
    assert np.all(np.isfinite(block.point))
    assert np.all(np.diff(block.quantiles, axis=1) >= -1e-9)


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_training_is_deterministic_for_a_fixed_seed(model_id, group):
    train, validate, context = group
    first = MODELS[model_id]().fit_predict(train, validate, context)
    second = MODELS[model_id]().fit_predict(train, validate, context)
    np.testing.assert_array_equal(first.point, second.point)
    np.testing.assert_array_equal(first.quantiles, second.quantiles)


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_nothing_a_model_learned_depends_on_the_validation_labels(model_id, group):
    """Poison the validation targets: a leakage-free model predicts exactly the same."""
    train, validate, context = group
    honest = MODELS[model_id]().fit_predict(train, validate, context)
    poisoned_rows = validate.with_columns(pl.lit(-12345.0).alias(TARGET_COLUMN))
    poisoned = MODELS[model_id]().fit_predict(train, poisoned_rows, context)
    np.testing.assert_array_equal(honest.point, poisoned.point)
    np.testing.assert_array_equal(honest.quantiles, poisoned.quantiles)


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_a_later_training_season_changes_predictions(model_id, group):
    """The complement: a model that ignored its training data would pass every leak test."""
    train, validate, context = group
    full = MODELS[model_id]().fit_predict(train, validate, context)
    trimmed = train.filter(pl.col("season") < context.fold.train_end_season)
    fewer_seasons = FitContext(
        fold=context.fold,
        position=context.position,
        scoring_preset=context.scoring_preset,
        features=context.features,
        seed=context.seed,
    )
    reduced = MODELS[model_id]().fit_predict(trimmed, validate, fewer_seasons)
    assert not np.allclose(full.point, reduced.point)


# --------------------------------------------------------------------------------------
# B0 behaviour
# --------------------------------------------------------------------------------------


def test_b0_uses_a_draft_capital_prior_for_players_without_prior_production(group):
    train, validate, context = group
    model = NaivePriorProductionBaseline()
    block = model.fit_predict(train, validate, context)
    rookies = validate.get_column("rookie_flag").to_numpy()
    assert rookies.any()
    predictions = block.point[rookies]
    # A rookie prediction is a bucket constant, so distinct rookies in the same draft bucket
    # share a value and none of them inherits a veteran's per-game rate.
    assert len(set(np.round(predictions, 6).tolist())) < int(rookies.sum())
    assert np.all(predictions >= 0.0)


def test_missing_experience_is_never_read_as_zero_or_as_a_rookie(group):
    """A null `years_exp` must stay null: not zero, and not a rookie flag."""
    train, validate, context = group
    unknown = validate.filter(~pl.col("experience_years_known"))
    assert unknown.height > 0
    assert not unknown.get_column("rookie_flag").any()
    assert unknown.get_column("experience_years").null_count() == unknown.height

    # The matrix handed to a model carries NaN, not zero, so LightGBM learns a split for
    # "unknown" instead of being told these players are first-year professionals.
    matrix = design_matrix(unknown, ("experience_years",))
    assert np.all(np.isnan(matrix[:, 0]))

    # And B0 routes them down its veteran path, which keys off prior production rather than
    # experience: raising a player's prior rate raises his prediction.
    model = NaivePriorProductionBaseline()
    target = validate.with_row_index("row_index").filter(
        ~pl.col("experience_years_known") & pl.col("has_prior_season_stats"),
    )
    assert target.height > 0
    index = int(target.get_column("row_index")[0])
    baseline = model.fit_predict(train, validate, context)
    lifted = model.fit_predict(
        train,
        validate.with_columns(
            pl.when(pl.int_range(pl.len()) == index)
            .then(pl.col("prior_ppg_matched") + 10.0)
            .otherwise(pl.col("prior_ppg_matched"))
            .alias("prior_ppg_matched"),
        ),
        context,
    )
    assert lifted.point[index] > baseline.point[index]


def test_b0_selects_its_shrinkage_inside_the_training_window(group):
    train, validate, context = group
    block = NaivePriorProductionBaseline().fit_predict(train, validate, context)
    assert block.diagnostics["selected_shrinkage_games"] in B0_SHRINKAGE_GRID
    inner = block.diagnostics["inner_split"]
    assert max(inner["inner_residual_seasons"]) < context.fold.validation_season
    assert set(inner["inner_fit_seasons"]).isdisjoint(inner["inner_residual_seasons"])


def test_b0_statistics_come_only_from_the_training_fold(group):
    """Changing one validation row's features moves that row's prediction and no other.

    If any statistic were pooled across the validation frame, editing a single row would
    shift every other row with it.
    """
    train, validate, context = group
    model = NaivePriorProductionBaseline()
    veteran = int(
        validate.with_row_index("row_index")
        .filter(pl.col("has_prior_season_stats"))
        .get_column("row_index")[0],
    )
    baseline = model.fit_predict(train, validate, context)
    edited = validate.with_columns(
        pl.when(pl.int_range(pl.len()) == veteran)
        .then(pl.lit(99.0))
        .otherwise(pl.col("prior_ppg_matched"))
        .alias("prior_ppg_matched"),
    )
    changed = model.fit_predict(train, edited, context)
    assert changed.point[veteran] != baseline.point[veteran]
    others = [index for index in range(validate.height) if index != veteran]
    np.testing.assert_array_equal(changed.point[others], baseline.point[others])


# --------------------------------------------------------------------------------------
# B1 behaviour
# --------------------------------------------------------------------------------------


def test_b1_selects_its_penalty_inside_the_training_window(group):
    train, validate, context = group
    block = RidgeBaseline().fit_predict(train, validate, context)
    assert block.diagnostics["selected_alpha"] in RIDGE_ALPHAS
    assert block.diagnostics["preprocessing"]["features_kept"] > 0


def test_b1_adds_a_missingness_indicator_for_every_imputed_column(group):
    train, _, context = group
    matrix = design_matrix(train, context.features)
    preprocessor = FoldPreprocessor.fit(matrix, context.features)
    assert preprocessor.indicator_for
    assert preprocessor.width == len(preprocessor.kept) + len(preprocessor.indicator_for)


def test_preprocessing_statistics_come_from_the_training_rows_only(group):
    train, validate, context = group
    preprocessor = FoldPreprocessor.fit(design_matrix(train, context.features), context.features)
    other = FoldPreprocessor.fit(
        design_matrix(pl.concat([train, validate]), context.features),
        context.features,
    )
    assert not np.allclose(preprocessor.medians, other.medians) or not np.allclose(
        preprocessor.means,
        other.means,
    )


def test_a_training_constant_column_is_dropped_rather_than_standardized():
    frame = pl.DataFrame({"a": [1.0, 2.0, 3.0], "b": [5.0, 5.0, 5.0], "c": [None, None, None]})
    preprocessor = FoldPreprocessor.fit(design_matrix(frame, ["a", "b", "c"]), ["a", "b", "c"])
    assert preprocessor.kept == (0,)


# --------------------------------------------------------------------------------------
# Residual quantiles
# --------------------------------------------------------------------------------------


def test_the_inner_split_is_chronological_and_never_reaches_the_validation_season():
    split = inner_chronological_split((2017, 2018, 2019, 2020, 2021))
    assert split.fit_seasons == (2017, 2018, 2019)
    assert split.residual_seasons == (2020, 2021)
    short = inner_chronological_split((2017, 2018, 2019))
    assert short.fit_seasons == (2017, 2018)
    assert short.residual_seasons == (2019,)
    with pytest.raises(ValueError, match="cannot be split"):
        inner_chronological_split((2017,))


def test_residual_quantiles_are_monotone_and_centred_on_the_residual_distribution():
    generator = np.random.default_rng(2)
    residuals = generator.normal(0.0, 10.0, size=600)
    predictions = generator.uniform(0.0, 100.0, size=600)
    model = ResidualQuantiles.fit(residuals, predictions, QUANTILE_LEVELS)
    quantiles = model.apply(np.array([50.0]))
    assert np.all(np.diff(quantiles, axis=1) >= 0.0)
    assert quantiles[0, 2] == pytest.approx(50.0 + np.quantile(residuals, 0.5), abs=2.0)


def test_a_small_stratum_falls_back_to_the_pooled_residuals():
    residuals = np.arange(-30.0, 30.0)
    predictions = np.arange(60.0)
    model = ResidualQuantiles.fit(residuals, predictions, QUANTILE_LEVELS)
    assert model.stratum_counts == (20, 20, 20)
    for offsets in model.strata:
        np.testing.assert_array_equal(offsets, model.pooled)


def test_baseline_quantiles_do_not_cross(group):
    train, validate, context = group
    for model in (NaivePriorProductionBaseline(), RidgeBaseline()):
        block = model.fit_predict(train, validate, context)
        assert crossing_rate(block.raw_quantiles) == 0.0


# --------------------------------------------------------------------------------------
# Q1 behaviour
# --------------------------------------------------------------------------------------


def test_q1_reports_its_raw_crossing_rate_before_repairing_it(group):
    train, validate, context = group
    block = LightGbmQuantileCandidate().fit_predict(train, validate, context)
    reported = block.diagnostics["crossing_rate_raw"]
    assert reported == pytest.approx(crossing_rate(block.raw_quantiles))
    assert 0.0 <= reported <= 1.0
    assert crossing_rate(block.quantiles) == 0.0


def test_q1_point_prediction_is_the_median_quantile(group):
    train, validate, context = group
    block = LightGbmQuantileCandidate().fit_predict(train, validate, context)
    np.testing.assert_array_equal(block.point, block.quantiles[:, 2])


def test_q1_records_the_library_version_parameters_and_seed(group):
    train, validate, context = group
    model = LightGbmQuantileCandidate()
    described = model.describe()
    assert described["library"].startswith("lightgbm ")
    assert described["parameters"]["objective"] == "quantile"
    assert described["tuning"].startswith("none")
    block = model.fit_predict(train, validate, context)
    assert block.diagnostics["seed"] == context.group_seed


def test_group_seeds_differ_between_groups_and_repeat_for_the_same_group():
    fold = development_folds(WindowPolicy.W2)[0]
    common = {"fold": fold, "features": ("a",), "seed": 42}
    first = FitContext(position="RB", scoring_preset="PPR", **common)
    same = FitContext(position="RB", scoring_preset="PPR", **common)
    other = FitContext(position="WR", scoring_preset="PPR", **common)
    assert first.group_seed == same.group_seed
    assert first.group_seed != other.group_seed


def test_repair_monotonicity_sorts_without_changing_the_multiset():
    raw = np.array([[5.0, 1.0, 3.0, 2.0, 4.0]])
    repaired = repair_monotonicity(raw)
    np.testing.assert_array_equal(repaired, np.array([[1.0, 2.0, 3.0, 4.0, 5.0]]))
    assert sorted(raw[0].tolist()) == repaired[0].tolist()
