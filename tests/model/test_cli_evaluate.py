"""The ``ffdraft evaluate-intrinsic`` command.

The seal is only real if the command line enforces it, so most of these tests are about what
the CLI *refuses*. The one end-to-end run uses a synthetic dataset written to a temporary
directory: the real historical dataset is gitignored and CI never has it.
"""

from __future__ import annotations

import json

import pytest

from ffdraft.cli import main
from ffdraft.modeling.holdout import FINAL_EVAL_CONFIRMATION_TOKEN, FINAL_HOLDOUT_SEASON


@pytest.fixture
def dataset_dir(tmp_path, synthetic_feature_frame, synthetic_label_frame):
    directory = tmp_path / "historical"
    directory.mkdir()
    synthetic_feature_frame.write_parquet(directory / "features.parquet")
    synthetic_label_frame.write_parquet(directory / "labels_fantasy.parquet")
    return directory


def _run(dataset_dir, out_dir, *extra: str) -> int:
    return main(
        [
            "evaluate-intrinsic",
            "--data",
            str(dataset_dir),
            "--out",
            str(out_dir),
            "--model",
            "B0",
            "--model",
            "B1",
            "--validation-season",
            "2024",
            "--no-diagnostic-folds",
            "--bootstrap-replicates",
            "40",
            *extra,
        ],
    )


def test_the_command_writes_both_reports_and_reports_the_gate(dataset_dir, tmp_path, capsys):
    out_dir = tmp_path / "report"
    status = _run(dataset_dir, out_dir, "--git-sha", "0000000")
    output = capsys.readouterr().out
    assert status in {0, 1}
    assert (out_dir / "experiment.json").is_file()
    assert (out_dir / "experiment.md").is_file()
    assert "training window" in output
    payload = json.loads((out_dir / "experiment.json").read_text(encoding="utf-8"))
    assert payload["git_sha"] == "0000000"
    assert payload["final_holdout"]["status"] == "UNTOUCHED / NOT EVALUATED"


def test_an_ordinary_run_never_touches_the_sealed_season(dataset_dir, tmp_path, capsys):
    out_dir = tmp_path / "report"
    _run(dataset_dir, out_dir)
    capsys.readouterr()
    payload = json.loads((out_dir / "experiment.json").read_text(encoding="utf-8"))
    assert FINAL_HOLDOUT_SEASON not in payload["dataset"]["seasons"]
    assert payload["dataset"]["withheld_seasons"] == [FINAL_HOLDOUT_SEASON]
    assert payload["dataset"]["withheld_rows"] > 0
    seasons = {cell["validation_season"] for cell in payload["metrics_by_cell"]}
    assert FINAL_HOLDOUT_SEASON not in seasons


def test_writing_predictions_is_opt_in(dataset_dir, tmp_path, capsys):
    out_dir = tmp_path / "report"
    _run(dataset_dir, out_dir)
    capsys.readouterr()
    assert not (out_dir / "predictions.parquet").exists()
    _run(dataset_dir, out_dir, "--write-predictions")
    capsys.readouterr()
    assert (out_dir / "predictions.parquet").is_file()


def test_final_eval_without_a_token_is_refused(dataset_dir, tmp_path, capsys):
    status = main(
        ["evaluate-intrinsic", "--data", str(dataset_dir), "--out", str(tmp_path), "--final-eval"],
    )
    assert status == 2
    assert "refusing to unseal" in capsys.readouterr().err


def test_final_eval_with_the_wrong_token_is_refused(dataset_dir, tmp_path, capsys):
    status = main(
        [
            "evaluate-intrinsic",
            "--data",
            str(dataset_dir),
            "--out",
            str(tmp_path),
            "--final-eval",
            "--confirm-final-eval",
            "yes-please",
            "--final-eval-reason",
            "curiosity",
        ],
    )
    assert status == 2
    assert "sealed" in capsys.readouterr().err


def test_final_eval_requires_exactly_one_frozen_window(dataset_dir, tmp_path, capsys):
    status = main(
        [
            "evaluate-intrinsic",
            "--data",
            str(dataset_dir),
            "--out",
            str(tmp_path),
            "--final-eval",
            "--confirm-final-eval",
            FINAL_EVAL_CONFIRMATION_TOKEN,
            "--final-eval-reason",
            "phase 4",
        ],
    )
    assert status == 2
    assert "single --window" in capsys.readouterr().err


def test_the_authorized_final_eval_path_runs_and_says_what_it_consumed(
    dataset_dir,
    tmp_path,
    capsys,
):
    """Synthetic data only. The real 2025 season is never evaluated during Phase 3."""
    out_dir = tmp_path / "final"
    status = main(
        [
            "evaluate-intrinsic",
            "--data",
            str(dataset_dir),
            "--out",
            str(out_dir),
            "--model",
            "B0",
            "--window",
            "W2_modern_era",
            "--final-eval",
            "--confirm-final-eval",
            FINAL_EVAL_CONFIRMATION_TOKEN,
            "--final-eval-reason",
            "unit test of the sealed path",
        ],
    )
    output = capsys.readouterr().out
    assert status == 0
    assert "FINAL HOLDOUT CONSUMED" in output
    payload = json.loads((out_dir / "final_holdout.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "final_holdout"
    assert payload["final_holdout"]["status"] == "CONSUMED"
    assert payload["authorization_reason"] == "unit test of the sealed path"


def test_a_missing_dataset_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="build-historical"):
        main(["evaluate-intrinsic", "--data", str(tmp_path / "nope"), "--out", str(tmp_path)])
