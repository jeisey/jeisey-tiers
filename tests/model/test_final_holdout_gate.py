"""The sealed final holdout, and what Phase 4 added to it.

Phase 3 proved the seal holds. Phase 4 adds three commands that could each become a second
door to 2025, plus an acceptance gate that decides whether the model is released. These tests
check the door is still locked from every side, and that the gate is applied to the promoted
architecture rather than to whatever the harness happens to default to.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from ffdraft.cli import main
from ffdraft.modeling.experiment import ExperimentConfig, build_models
from ffdraft.modeling.holdout import (
    FINAL_EVAL_CONFIRMATION_TOKEN,
    FINAL_HOLDOUT_SEASON,
    PREDECLARED_HOLDOUT_SLICES,
    FinalEvalAuthorization,
    HoldoutSealError,
)
from ffdraft.modeling.rules import FINAL_HOLDOUT_GATE


@pytest.fixture
def dataset_dir(tmp_path, synthetic_feature_frame, synthetic_label_frame):
    directory = tmp_path / "historical"
    directory.mkdir()
    synthetic_feature_frame.write_parquet(directory / "features.parquet")
    synthetic_label_frame.write_parquet(directory / "labels_fantasy.parquet")
    return directory


def test_the_registry_can_build_the_promoted_architecture() -> None:
    """The final holdout has to be able to evaluate what Phase 4 actually promoted."""
    models = build_models(("B0", "CB"))
    assert set(models) == {"B0", "CB"}
    assert models["CB"].describe()["version"].startswith("cb_hurdle")


def test_phase_three_models_are_unchanged() -> None:
    models = build_models(("B0", "B1", "Q1"))
    assert models["Q1"].describe()["version"] == "q1_lgbm_quantile_v1"


def test_the_acceptance_gate_is_frozen_and_full_universe_only() -> None:
    payload = FINAL_HOLDOUT_GATE.to_dict()
    assert payload["criteria_version"] == "phase4_final_holdout_v1"
    assert payload["primary_slice"] == "full_universe"
    assert payload["primary_baseline"] == "B0"
    assert payload["max_post_crossing_rate"] == 0.0
    assert any("diagnostics" in rule for rule in payload["rules"])


def test_the_predeclared_slices_are_unchanged_since_phase_three() -> None:
    """ADR-025 fixed these before any candidate comparison; Phase 4 may not edit them."""
    ids = [item.slice_id for item in PREDECLARED_HOLDOUT_SLICES]
    assert ids == [
        "full_universe",
        "era_stable_universe",
        "rookie",
        "veteran",
        "depth_context_state",
        "position",
        "scoring_preset",
        "information_rich",
        "low_information",
    ]
    primaries = [item for item in PREDECLARED_HOLDOUT_SLICES if str(item.kind) == "primary"]
    assert len(primaries) == 1


def test_an_authorization_needs_the_exact_token() -> None:
    with pytest.raises(HoldoutSealError):
        FinalEvalAuthorization(confirmation="please", reason="because")
    with pytest.raises(HoldoutSealError):
        FinalEvalAuthorization(confirmation=FINAL_EVAL_CONFIRMATION_TOKEN, reason="  ")
    authorized = FinalEvalAuthorization(
        confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="a recorded reason",
    )
    assert authorized.to_dict()["authorized"] is True


def test_the_distribution_command_cannot_reach_the_holdout(dataset_dir, tmp_path) -> None:
    """The stage-B study has no flag that opens the seal, and its report proves it."""
    out_dir = tmp_path / "report"
    status = main(
        [
            "evaluate-distribution",
            "--data",
            str(dataset_dir),
            "--out",
            str(out_dir),
            "--predictions-out",
            str(tmp_path / "phase4"),
            "--validation-season",
            "2024",
            "--bootstrap-replicates",
            "40",
            "--composition-draws",
            "150",
            "--no-references",
        ],
    )
    assert status in {0, 1}
    payload = json.loads((out_dir / "experiment.json").read_text(encoding="utf-8"))
    seasons = {int(row["validation_season"]) for row in payload["aggregates_by_season"]}
    assert FINAL_HOLDOUT_SEASON not in seasons
    predictions = pl.read_parquet(tmp_path / "phase4" / "oof_predictions.parquet")
    assert FINAL_HOLDOUT_SEASON not in set(predictions.get_column("season").to_list())


def test_the_final_eval_defaults_do_not_silently_evaluate_phase_three(dataset_dir) -> None:
    """A final-holdout run must name the models it is judging, not inherit a stale default."""
    defaults = ExperimentConfig()
    assert defaults.model_ids == ("B0", "B1", "Q1")
    assert "CB" in build_models(("B0", "CB"))


def test_the_authorized_path_reports_the_gate_and_marks_the_holdout_consumed(
    dataset_dir,
    tmp_path,
    capsys,
) -> None:
    out_dir = tmp_path / "holdout"
    status = main(
        [
            "evaluate-intrinsic",
            "--final-eval",
            "--confirm-final-eval",
            FINAL_EVAL_CONFIRMATION_TOKEN,
            "--final-eval-reason",
            "synthetic-data exercise of the sealed path",
            "--window",
            "W1_all_history",
            "--model",
            "B0",
            "--model",
            "CB",
            "--data",
            str(dataset_dir),
            "--out",
            str(out_dir),
            "--bootstrap-replicates",
            "40",
        ],
    )
    output = capsys.readouterr().out
    assert status in {0, 1}
    assert "FINAL HOLDOUT CONSUMED" in output
    payload = json.loads((out_dir / "final_holdout.json").read_text(encoding="utf-8"))
    assert payload["final_holdout"]["status"] == "CONSUMED"
    assert payload["candidate_model_id"] == "CB"
    assert payload["acceptance_criteria"]["criteria_version"] == "phase4_final_holdout_v1"
    assert payload["acceptance"]["selected"] in {"pass", "fail"}
    assert payload["primary"]
    assert payload["diagnostic_slices"]
    assert {row["slice_id"] for row in payload["diagnostic_slices"]} >= {"full_universe"}
