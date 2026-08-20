"""The production model artifact: training it, storing it, and refusing the wrong frame.

The properties that matter here are operational rather than statistical. A model artifact
has to survive a round trip through disk without changing a prediction, has to be readable
without executing anything, and has to refuse a frame built under a different feature
contract rather than quietly serving it.
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.calibration import MonotoneOnly, ResidualShiftCalibration
from ffdraft.modeling.features import core_feature_selection
from ffdraft.modeling.folds import DEFAULT_SEED
from ffdraft.modeling.production import (
    ARCHITECTURE_DIRECT,
    ARCHITECTURE_HURDLE,
    METADATA_FILE,
    FeatureSchemaMismatch,
    ProductionModel,
    ProductionSpec,
    train_production_model,
)

SEASON = 2025


def _spec(architecture: str = ARCHITECTURE_HURDLE, **overrides: object) -> ProductionSpec:
    payload: dict[str, object] = {
        "model_version": "test-model-v1",
        "architecture": architecture,
        "calibration_strategy_id": MonotoneOnly().strategy_id,
        "target_scale_id": "season_total",
        "seed": DEFAULT_SEED,
        "composition_draws": 200,
        "num_boost_round": 40,
    }
    payload.update(overrides)
    return ProductionSpec(**payload)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def training_frame(synthetic_modeling_dataset) -> pl.DataFrame:
    return synthetic_modeling_dataset.frame.filter(pl.col("season") <= 2022)


@pytest.fixture(scope="module")
def inference_frame(synthetic_modeling_dataset) -> pl.DataFrame:
    selection = core_feature_selection()
    keep = ["player_id", "position", "scoring_preset", *selection.included]
    return (
        synthetic_modeling_dataset.frame.filter(pl.col("season") == 2023)
        .select(list(dict.fromkeys(keep)))
        .sort("scoring_preset", "player_id")
    )


@pytest.fixture(scope="module")
def trained(training_frame) -> ProductionModel:
    return train_production_model(training_frame, spec=_spec(), git_sha="0000000")


def test_training_covers_every_position_and_scoring_group(trained, training_frame) -> None:
    positions = set(training_frame.get_column("position").to_list())
    presets = set(training_frame.get_column("scoring_preset").to_list())
    assert len(trained.groups) == len(positions) * len(presets)
    assert trained.training_seasons == tuple(
        sorted(set(training_frame.get_column("season").to_list())),
    )


def test_the_artifact_records_its_feature_contract(trained) -> None:
    selection = core_feature_selection()
    assert trained.feature_set_version == selection.version
    assert trained.feature_set_hash == selection.fingerprint()
    assert len(trained.features) == len(selection.included)


def test_saving_writes_text_boosters_and_json_metadata(trained, tmp_path) -> None:
    """No pickle anywhere: loading reads numbers and a documented text format."""
    import gzip

    directory = tmp_path / "model"
    written = trained.save(directory)
    assert (directory / METADATA_FILE).is_file()
    boosters = sorted((directory / "boosters").glob("*.txt.gz"))
    assert boosters
    assert all(path.suffix in {".gz", ".json"} for path in written)
    payload = json.loads((directory / METADATA_FILE).read_text(encoding="utf-8"))
    assert payload["artifact_schema"] == "intrinsic_model_artifact_v1"
    assert payload["spec"]["architecture"] == ARCHITECTURE_HURDLE
    assert payload["groups"]
    with gzip.open(boosters[0], "rt", encoding="utf-8") as handle:
        assert "tree" in handle.read()


def test_saved_boosters_are_byte_identical_across_runs(trained, tmp_path) -> None:
    """A model artifact lives in version control; an identical model must diff as nothing."""
    first, second = tmp_path / "a", tmp_path / "b"
    trained.save(first)
    trained.save(second)
    for path in sorted((first / "boosters").glob("*.txt.gz")):
        assert path.read_bytes() == (second / "boosters" / path.name).read_bytes()


def test_a_tampered_booster_is_refused(trained, tmp_path) -> None:
    """The metadata records a digest per booster, so an altered artifact fails closed."""
    import gzip

    directory = tmp_path / "model"
    trained.save(directory)
    victim = sorted((directory / "boosters").glob("*.txt.gz"))[0]
    with gzip.open(victim, "rt", encoding="utf-8") as handle:
        text = handle.read()
    with gzip.GzipFile(victim, "wb", mtime=0) as handle:
        handle.write((text + "\n# tampered\n").encode("utf-8"))
    with pytest.raises(FeatureSchemaMismatch, match="digest"):
        ProductionModel.load(directory)


def test_a_round_trip_predicts_identically(trained, inference_frame, tmp_path) -> None:
    directory = tmp_path / "model"
    trained.save(directory)
    reloaded = ProductionModel.load(directory)
    before = trained.predict(inference_frame, season=SEASON)
    after = reloaded.predict(inference_frame, season=SEASON)
    assert before.equals(after)


def test_prediction_is_a_valid_monotone_distribution(trained, inference_frame) -> None:
    predicted = trained.predict(inference_frame, season=SEASON)
    assert predicted.height == inference_frame.height
    columns = ["p10_points", "p25_points", "p50_points", "p75_points", "p90_points"]
    matrix = predicted.select(columns).to_numpy()
    assert np.all(np.isfinite(matrix))
    assert np.all(np.diff(matrix, axis=1) >= -1e-9)


def test_training_twice_gives_the_same_predictions(training_frame, inference_frame) -> None:
    first = train_production_model(training_frame, spec=_spec())
    second = train_production_model(training_frame, spec=_spec())
    assert first.predict(inference_frame, season=SEASON).equals(
        second.predict(inference_frame, season=SEASON),
    )


def test_an_incompatible_feature_set_is_refused(trained) -> None:
    with pytest.raises(FeatureSchemaMismatch, match="feature set"):
        trained.assert_compatible(
            feature_set_hash="deadbeefdeadbeef",
            feature_schema_hash=trained.feature_schema_hash,
        )


def test_an_incompatible_feature_schema_is_refused(trained) -> None:
    with pytest.raises(FeatureSchemaMismatch, match="feature schema"):
        trained.assert_compatible(
            feature_set_hash=trained.feature_set_hash,
            feature_schema_hash="deadbeefdeadbeef",
        )


def test_a_matching_contract_is_accepted(trained) -> None:
    trained.assert_compatible(
        feature_set_hash=trained.feature_set_hash,
        feature_schema_hash=trained.feature_schema_hash,
    )


def test_an_unfitted_group_is_refused_rather_than_dropped(trained, inference_frame) -> None:
    rogue = inference_frame.head(1).with_columns(pl.lit("K").alias("position"))
    with pytest.raises(FeatureSchemaMismatch, match="no fitted model"):
        trained.predict(pl.concat([inference_frame, rogue]), season=SEASON)


def test_an_unknown_artifact_schema_is_refused(trained, tmp_path) -> None:
    directory = tmp_path / "model"
    trained.save(directory)
    path = directory / METADATA_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifact_schema"] = "something_else_v9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FeatureSchemaMismatch, match="artifact schema"):
        ProductionModel.load(directory)


def test_a_missing_artifact_says_so(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="model directory"):
        ProductionModel.load(tmp_path / "nowhere")


def test_the_direct_architecture_also_round_trips(
    training_frame, inference_frame, tmp_path
) -> None:
    """Candidate A remains a serializable production architecture even though B was promoted."""
    spec = _spec(
        ARCHITECTURE_DIRECT, calibration_strategy_id=ResidualShiftCalibration().strategy_id
    )
    model = train_production_model(training_frame, spec=spec)
    directory = tmp_path / "direct"
    model.save(directory)
    reloaded = ProductionModel.load(directory)
    assert reloaded.spec.architecture == ARCHITECTURE_DIRECT
    assert reloaded.spec.calibrates
    assert model.predict(inference_frame, season=SEASON).equals(
        reloaded.predict(inference_frame, season=SEASON),
    )


def test_point_bounds_come_from_training_and_are_grouped(trained, training_frame) -> None:
    bounds = trained.point_bounds()
    assert set(bounds) == set(training_frame.get_column("scoring_preset").to_list())
    for preset, by_position in bounds.items():
        observed = training_frame.filter(pl.col("scoring_preset") == preset)
        for position, item in by_position.items():
            values = observed.filter(pl.col("position") == position).get_column("target_points")
            assert item.lower <= float(values.min())
            assert item.upper >= float(values.max())
