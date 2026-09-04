"""The production-fit protocol: `ros_production_fit_v1` (ADR-078).

Two questions these tests exist to answer, and both are about the difference between a
*refit* and a *change*:

**Is the frozen spec still the model Phase 11 evaluated?** If someone edits a parameter in
`ffdraft.ros.frozen`, the artifact would still be called `intrinsic-ros-v1` and would no
longer be the accepted model. The configuration hash catches an edited artifact; this suite
catches an edited constant, by comparing the spec against the candidate class itself.

**Can the training window widen by accident?** Two independent barriers say no: the sealed
season needs its token, and a season at or after the served one is refused outright. The
second is the error that cannot be detected from the output, so it is asserted directly.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.candidates import HURDLE_COMPOSITION_DRAWS
from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.ros.candidates import (
    RC1_NUM_BOOST_ROUND,
    RC1_PARAMETERS,
    RC1_VERSION,
    RosHurdleCandidate,
)
from ffdraft.ros.dictionary import ros_feature_selection
from ffdraft.ros.folds import RosFoldKind
from ffdraft.ros.frozen import (
    ROS_PRODUCTION_LAST_TRAINING_SEASON,
    ROS_PRODUCTION_SPEC,
    ROS_SERVING_SEASON,
    RosProductionSpec,
    RosRefitReason,
)
from ffdraft.ros.holdout import ROS_FINAL_EVAL_CONFIRMATION_TOKEN, RosFinalEvalAuthorization
from ffdraft.ros.production import (
    RosFeatureSchemaMismatch,
    RosProductionModel,
    production_fold,
    train_ros_production_model,
)


def _fast_spec() -> RosProductionSpec:
    """The frozen architecture at a size a test can afford.

    Only the two knobs that decide *how long the fit takes* are reduced; the family, the
    parameters, the calibration, the copula and the composition rule are the frozen ones, so
    every path these tests exercise is the production path. The production values themselves
    are asserted against the evaluated candidate in
    :func:`test_frozen_spec_matches_the_evaluated_candidate`, which fits nothing.
    """
    return RosProductionSpec(num_boost_round=8, composition_draws=200)


def _frame(seasons: tuple[int, ...], *, rows_per_season: int = 60) -> pl.DataFrame:
    """A tiny modelling frame in the shape the fitter expects."""
    selection = ros_feature_selection()
    features = list(selection.included[:6])
    rng = np.random.default_rng(11)
    records: list[dict[str, object]] = []
    for season in seasons:
        for index in range(rows_per_season):
            games = float(index % 5)
            records.append(
                {
                    "season": season,
                    "through_week": 4 + (index % 3),
                    "player_id": f"gsis:00-{season}{index:04d}",
                    "position": "RB" if index % 2 else "WR",
                    "scoring_preset": "PPR",
                    "actual_remaining_games": games,
                    "actual_remaining_points": games * 8.0 + float(rng.normal(0, 2)),
                    "remaining_horizon_weeks": 9,
                    **{name: float(rng.normal(0, 1)) for name in features},
                },
            )
    return pl.DataFrame(records)


def test_frozen_spec_matches_the_evaluated_candidate() -> None:
    """A drifted constant fails here rather than shipping under an accepted model's name."""
    candidate = RosHurdleCandidate()
    assert ROS_PRODUCTION_SPEC.candidate_version == RC1_VERSION
    assert dict(ROS_PRODUCTION_SPEC.parameters) == dict(candidate.parameters) == RC1_PARAMETERS
    assert ROS_PRODUCTION_SPEC.num_boost_round == candidate.num_boost_round == RC1_NUM_BOOST_ROUND
    assert ROS_PRODUCTION_SPEC.composition_draws == HURDLE_COMPOSITION_DRAWS
    assert ROS_PRODUCTION_SPEC.levels == QUANTILE_LEVELS
    # The Monte Carlo stream key is a determinism device rather than a modelling choice, so
    # it is the one field a production fit declares differently — and it is declared, hashed
    # and recorded rather than left implicit.
    assert ROS_PRODUCTION_SPEC.composition_seed_material == ("ros_candidate", "production")
    assert candidate.seed_material == ("ros_candidate", "development")


def test_the_configuration_hash_ignores_the_window_and_catches_a_tuned_parameter() -> None:
    baseline = ROS_PRODUCTION_SPEC.configuration_hash()
    assert RosProductionSpec().configuration_hash() == baseline

    tuned = RosProductionSpec(
        parameters={**dict(ROS_PRODUCTION_SPEC.parameters), "learning_rate": 0.5},
    )
    assert tuned.configuration_hash() != baseline

    more_rounds = RosProductionSpec(num_boost_round=RC1_NUM_BOOST_ROUND + 1)
    assert more_rounds.configuration_hash() != baseline


def test_the_production_fold_trains_before_the_season_it_serves() -> None:
    fold = production_fold(serving_season=ROS_SERVING_SEASON)
    assert fold.kind is RosFoldKind.PRODUCTION
    assert fold.train_end_season == ROS_PRODUCTION_LAST_TRAINING_SEASON
    assert fold.validation_season == ROS_SERVING_SEASON
    assert fold.train_end_season < fold.validation_season


def test_training_on_the_served_season_is_refused() -> None:
    """The one error that cannot be detected from the output, so it is refused at the door."""
    with pytest.raises(ValueError, match="at or after the serving season"):
        train_ros_production_model(_frame((2020, 2021)), serving_season=2021, spec=_fast_spec())


def test_a_sealed_training_season_needs_the_explicit_token() -> None:
    with pytest.raises(ValueError, match="sealed"):
        train_ros_production_model(_frame((2023, 2025)), serving_season=2026, spec=_fast_spec())

    model = train_ros_production_model(
        _frame((2023, 2025)),
        serving_season=2026,
        spec=_fast_spec(),
        authorization=RosFinalEvalAuthorization(
            confirmation=ROS_FINAL_EVAL_CONFIRMATION_TOKEN,
            reason="the holdout is spent; ADR-078 step 3",
        ),
    )
    assert model.sealed_season_authorization is not None
    assert model.sealed_season_authorization["sealed_training_seasons"] == [2025]


def test_an_empty_frame_is_refused_rather_than_producing_an_empty_model() -> None:
    with pytest.raises(ValueError, match="no training rows"):
        train_ros_production_model(
            _frame((2020,)).head(0),
            serving_season=2026,
            spec=_fast_spec(),
        )


def test_the_artifact_round_trips_and_serves_the_same_numbers(tmp_path: Path) -> None:
    frame = _frame((2020, 2021, 2022, 2023))
    model = train_ros_production_model(
        frame,
        serving_season=2026,
        spec=_fast_spec(),
        refit_reason=RosRefitReason.REPRODUCTION,
        cutoff_rule_version="ros_cutoff_v1",
        label_version="ros_label_v1",
        git_sha="abc1234",
    )
    written = model.save(tmp_path / "model")
    assert any(path.name == "metadata.json" for path in written)

    loaded = RosProductionModel.load(tmp_path / "model")
    assert loaded.spec.configuration_hash() == model.spec.configuration_hash()
    assert loaded.training_seasons == (2020, 2021, 2022, 2023)
    assert loaded.refit_reason == RosRefitReason.REPRODUCTION.value

    serve = frame.filter(pl.col("season") == 2023).head(20)
    before = model.predict(serve)
    after = loaded.predict(serve)
    assert before.equals(after)
    # The availability half of the hurdle is published, from the same draws as the totals.
    assert "expected_remaining_games" in before.columns
    assert (before.get_column("expected_remaining_games") >= 0).all()


def test_saving_twice_produces_identical_bytes(tmp_path: Path) -> None:
    """`mtime=0` is what makes a committed artifact checkable against a rebuild."""
    model = train_ros_production_model(
        _frame((2020, 2021, 2022)),
        serving_season=2026,
        spec=_fast_spec(),
    )
    first = tmp_path / "a"
    second = tmp_path / "b"
    model.save(first)
    model.save(second)
    for path in sorted((first / "boosters").iterdir()):
        assert path.read_bytes() == (second / "boosters" / path.name).read_bytes()


def test_an_altered_booster_is_refused_on_load(tmp_path: Path) -> None:
    model = train_ros_production_model(
        _frame((2020, 2021, 2022)),
        serving_season=2026,
        spec=_fast_spec(),
    )
    model.save(tmp_path / "model")
    booster = sorted((tmp_path / "model" / "boosters").iterdir())[0]
    # A *valid* gzip whose payload differs. Appending trailing bytes would not do: the gzip
    # reader ignores garbage after the member, so the digest would still match and the test
    # would pass without testing anything.
    with gzip.open(booster, "rt", encoding="utf-8") as handle:
        text = handle.read()
    with gzip.GzipFile(booster, "wb", mtime=0) as out:
        out.write((text + "\n").encode("utf-8"))
    with pytest.raises(RosFeatureSchemaMismatch, match="does not match the digest"):
        RosProductionModel.load(tmp_path / "model")


def test_serving_a_season_the_model_trained_on_is_refused(tmp_path: Path) -> None:
    model = train_ros_production_model(
        _frame((2020, 2021, 2022)),
        serving_season=2026,
        spec=_fast_spec(),
    )
    model.assert_serving_season(2026)
    with pytest.raises(RosFeatureSchemaMismatch, match="saw its outcomes"):
        model.assert_serving_season(2022)


def test_a_disagreeing_feature_contract_is_refused() -> None:
    model = train_ros_production_model(
        _frame((2020, 2021, 2022)),
        serving_season=2026,
        spec=_fast_spec(),
    )
    selection = ros_feature_selection()
    model.assert_compatible(
        feature_set_hash=selection.fingerprint(),
        feature_schema_hash=selection.schema_hash,
    )
    with pytest.raises(RosFeatureSchemaMismatch, match="feature set"):
        model.assert_compatible(
            feature_set_hash="0000000000000000",
            feature_schema_hash=selection.schema_hash,
        )


def test_the_metadata_records_the_lineage_a_reader_needs(tmp_path: Path) -> None:
    model = train_ros_production_model(
        _frame((2020, 2021, 2022)),
        serving_season=2026,
        spec=_fast_spec(),
        dataset_manifest={"content_hash": "deadbeef", "rows": 180},
        cutoff_rule_version="ros_cutoff_v1",
        label_version="ros_label_v1",
        git_sha="abc1234",
    )
    metadata = model.metadata()
    assert metadata["production_fit_rule_version"] == "ros_production_fit_v1"
    assert metadata["dataset_manifest"]["content_hash"] == "deadbeef"
    assert metadata["cutoff_rule_version"] == "ros_cutoff_v1"
    assert metadata["fold"]["kind"] == "production"
    # A production fit carries no performance claim: it was scored on nothing.
    assert any("scored on nothing" in note for note in metadata["notes"])
    assert any("not re-scored" in note for note in metadata["notes"])
