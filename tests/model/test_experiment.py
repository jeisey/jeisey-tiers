"""The whole harness, end to end, on synthetic data.

`docs/TEST_STRATEGY.md` 2.3 makes the network-free mini pipeline the key CI smoke path. This
is the Phase-3 equivalent: real folds, real feature selection, real models, real metrics,
real bootstrap and the real frozen gate, over a synthetic table small enough to run in
seconds - and with a sealed season present the whole time.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from ffdraft.modeling.experiment import (
    EXPERIMENT_VERSION,
    ExperimentConfig,
    aggregate_cells,
    build_models,
    experiment_checks,
    run_experiment,
    run_final_holdout_evaluation,
)
from ffdraft.modeling.folds import FoldKind, WindowPolicy
from ffdraft.modeling.holdout import (
    FINAL_EVAL_CONFIRMATION_TOKEN,
    FINAL_HOLDOUT_SEASON,
    FinalEvalAuthorization,
)
from ffdraft.modeling.report import to_json, to_markdown, write_report

CONFIG = ExperimentConfig(
    windows=(WindowPolicy.W1, WindowPolicy.W2),
    model_ids=("B0", "B1"),
    validation_seasons=(2023, 2024),
    include_w1_diagnostic_folds=False,
    bootstrap_replicates=50,
)


@pytest.fixture(scope="module")
def result(synthetic_modeling_dataset):
    return run_experiment(synthetic_modeling_dataset, config=CONFIG)


def test_the_experiment_produces_a_cell_for_every_fold_position_and_scoring(result):
    expected = (
        len(CONFIG.windows)
        * len(CONFIG.validation_seasons)
        * 4  # positions
        * 3  # scoring presets
        * len(CONFIG.model_ids)
    )
    assert len(result.cells) == expected
    assert {cell["fold_kind"] for cell in result.cells} == {str(FoldKind.DEVELOPMENT)}


def test_every_cell_carries_its_fold_window_and_slice_keys(result):
    for cell in result.cells:
        assert cell["train_end_season"] < cell["validation_season"]
        assert cell["window_policy"] in {str(policy) for policy in CONFIG.windows}
        assert cell["position"] in {"QB", "RB", "WR", "TE"}
        assert cell["scoring_preset"] in {"STD", "HALF", "PPR"}
        assert cell["n"] > 0


def test_the_run_is_reproducible(synthetic_modeling_dataset):
    first = run_experiment(synthetic_modeling_dataset, config=CONFIG)
    second = run_experiment(synthetic_modeling_dataset, config=CONFIG)
    assert first.aggregates == second.aggregates
    assert first.deltas == second.deltas
    assert first.selection == second.selection


def test_macro_and_row_weighted_aggregates_are_both_emitted(result):
    for record in result.aggregates:
        assert "macro_mae" in record
        assert "weighted_mae" in record
        assert record["cells"] > 0
        assert record["rows"] >= record["cells"]


def test_macro_aggregation_is_not_row_weighted():
    cells = [
        {
            "fold_kind": str(FoldKind.DEVELOPMENT),
            "window_policy": "W2_modern_era",
            "model_id": "B0",
            "n": 10,
            "mae": 100.0,
            **{key: 0.0 for key in _OTHER_METRICS},
        },
        {
            "fold_kind": str(FoldKind.DEVELOPMENT),
            "window_policy": "W2_modern_era",
            "model_id": "B0",
            "n": 990,
            "mae": 0.0,
            **{key: 0.0 for key in _OTHER_METRICS},
        },
    ]
    record = aggregate_cells(cells)[0]
    assert record["macro_mae"] == pytest.approx(50.0)
    assert record["weighted_mae"] == pytest.approx(1.0)


_OTHER_METRICS = (
    "rmse",
    "spearman",
    "kendall_tau_b",
    "top_k_recall",
    "mean_pinball",
    "coverage_p10_p90",
    "coverage_p25_p75",
    "mean_width_p10_p90",
    "mean_width_p25_p75",
    "crossing_rate_raw",
    "crossing_magnitude_raw",
)


def test_the_experiment_records_the_window_decision_and_a_selection(result):
    assert result.window_decision.selected in set(WindowPolicy)
    assert result.selection["window_policy"] == str(result.window_decision.selected)
    assert "rule" in result.selection


def test_the_holdout_is_reported_untouched(result):
    checks = {check.check_id for check in experiment_checks(result)}
    assert "phase3.final_holdout_untouched" in checks
    payload = to_json(result, git_sha="0000000")
    assert payload["final_holdout"]["status"] == "UNTOUCHED / NOT EVALUATED"
    assert payload["final_holdout"]["final_holdout_season"] == FINAL_HOLDOUT_SEASON
    seasons = {cell["validation_season"] for cell in result.cells}
    assert FINAL_HOLDOUT_SEASON not in seasons


def test_the_json_report_contains_everything_a_decision_needs(result):
    payload = to_json(result, git_sha="abc1234")
    for key in (
        "experiment_id",
        "experiment_version",
        "git_sha",
        "configuration",
        "promotion_criteria",
        "dataset",
        "feature_set",
        "feature_development_coverage",
        "folds",
        "models",
        "metrics_by_cell",
        "aggregates",
        "aggregates_by_position",
        "aggregates_by_season",
        "aggregates_by_scoring",
        "paired_deltas",
        "training_window_decision",
        "promotion_gate",
        "selection",
        "final_holdout",
        "checks",
    ):
        assert key in payload, key
    assert payload["experiment_version"] == EXPERIMENT_VERSION
    assert payload["git_sha"] == "abc1234"
    assert payload["feature_set"]["feature_set_hash"]
    json.dumps(payload)  # must be serializable without custom encoders


def test_the_markdown_report_leads_with_the_conclusion(result):
    text = to_markdown(result, git_sha="abc1234")
    assert text.startswith("# Phase 3")
    assert "## Conclusion" in text
    assert text.index("## Conclusion") < text.index("## What the numbers say")
    for heading in ("The promotion gate", "Folds", "Feature set", "Final holdout"):
        assert f"## {heading}" in text


def test_writing_the_report_produces_both_files(result, tmp_path):
    written = write_report(result, tmp_path, git_sha="abc1234")
    assert {path.name for path in written} == {"experiment.json", "experiment.md"}
    payload = json.loads((tmp_path / "experiment.json").read_text(encoding="utf-8"))
    assert payload["status"] in {"pass", "fail"}


def test_diagnostic_folds_are_emitted_but_excluded_from_the_aggregates(
    synthetic_modeling_dataset,
):
    config = ExperimentConfig(
        windows=(WindowPolicy.W1,),
        model_ids=("B0",),
        validation_seasons=(2020,),
        include_w1_diagnostic_folds=True,
        bootstrap_replicates=25,
    )
    outcome = run_experiment(synthetic_modeling_dataset, config=config)
    kinds = {cell["fold_kind"] for cell in outcome.cells}
    assert str(FoldKind.W1_DIAGNOSTIC) in kinds
    for record in outcome.aggregates:
        assert record["cells"] == 12  # one validation season x 4 positions x 3 scorings


def test_an_unknown_model_id_is_refused():
    with pytest.raises(ValueError, match="unknown model id"):
        build_models(["B0", "B9"])


def test_the_final_holdout_path_needs_an_unsealed_frame(synthetic_modeling_dataset):
    authorization = FinalEvalAuthorization(
        confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="unit test",
    )
    with pytest.raises(ValueError, match="no sealed season"):
        run_final_holdout_evaluation(
            synthetic_modeling_dataset,
            authorization=authorization,
            window=WindowPolicy.W2,
        )


def test_the_final_holdout_path_reports_every_predeclared_slice(
    synthetic_feature_frame,
    synthetic_label_frame,
):
    """Exercised on synthetic data only. The real 2025 season is never evaluated in Phase 3."""
    from ffdraft.modeling.dataset import build_modeling_frame

    authorization = FinalEvalAuthorization(
        confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
        reason="unit test of the sealed path",
    )
    dataset = build_modeling_frame(
        synthetic_feature_frame,
        synthetic_label_frame,
        authorization=authorization,
    )
    outcome = run_final_holdout_evaluation(
        dataset,
        authorization=authorization,
        window=WindowPolicy.W2,
        config=ExperimentConfig(model_ids=("B0",), bootstrap_replicates=25),
    )
    assert all(cell["validation_season"] == FINAL_HOLDOUT_SEASON for cell in outcome.cells)
    slice_ids = {record["slice_id"] for record in outcome.slices}
    assert "full_universe" in slice_ids
    assert "era_stable_universe" in slice_ids
    payload = outcome.to_dict()
    assert payload["final_holdout"]["status"] == "CONSUMED"
    assert any(check.check_id == "phase3.final_holdout_consumed" for check in outcome.checks)


def test_predictions_cover_every_validation_row_once_per_model(result):
    predictions = result.predictions
    assert predictions is not None
    counts = predictions.group_by("model_id", "window_policy", "season").agg(
        pl.len().alias("rows"),
        pl.col("player_id").n_unique().alias("players"),
    )
    for row in counts.iter_rows(named=True):
        assert row["rows"] == row["players"] * 3  # one row per scoring preset
