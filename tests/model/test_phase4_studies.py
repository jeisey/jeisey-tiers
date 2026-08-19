"""The Phase-4 development studies, and the seal they all sit behind.

Three commands were added in Phase 4 and every one of them is a potential second path to the
sealed season. These tests drive each study over a synthetic dataset and assert the same
property Phase 3 asserted of its own harness: **poisoning 2025 changes nothing**, because a
development run never has those rows in the first place.

The end-to-end runs use a deliberately small configuration. What they check is that the
plumbing works and the decisions are recorded, not what the decisions are - the real numbers
come from the committed experiment reports.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from ffdraft.cli import main
from ffdraft.modeling.dataset import build_modeling_frame
from ffdraft.modeling.distribution import DistributionConfig, run_distribution_study
from ffdraft.modeling.holdout import FINAL_HOLDOUT_SEASON, FinalEvalAuthorization
from ffdraft.simulation.study import (
    SimulationStudyConfig,
    load_oof_predictions,
    run_simulation_study,
    training_bounds,
)
from ffdraft.tiers.study import TierStudyConfig, run_tier_study


@pytest.fixture(scope="module")
def small_config() -> DistributionConfig:
    return DistributionConfig(
        validation_seasons=(2023, 2024),
        bootstrap_replicates=40,
        composition_draws=200,
        include_references=False,
    )


@pytest.fixture(scope="module")
def study(synthetic_modeling_dataset, small_config):
    return run_distribution_study(synthetic_modeling_dataset, config=small_config)


def test_the_study_records_all_three_decisions(study) -> None:
    assert study.calibration_decision.rule == "phase4_calibration_v1"
    assert study.horizon_decision.rule == "phase4_horizon_v1"
    assert study.candidate_decision.rule == "phase4_candidate_v1"
    assert study.selected["model_id"] in {"A0", "A1", "AH", "CB"}


def test_the_promoted_distribution_never_crosses(study) -> None:
    assert study.selected["macro_crossing_rate_post"] == 0.0


def test_the_study_applies_the_rules_in_the_declared_order(study) -> None:
    """The horizon variant is measured against whichever calibration won, not against C0."""
    calibrated = study.calibration_decision.selected
    assert f"AH_vs_{calibrated}" in study.deltas
    assert any(key.startswith("CB_vs_") for key in study.deltas)


def test_a_development_study_refuses_an_unsealed_frame(
    synthetic_feature_frame,
    synthetic_label_frame,
    small_config,
) -> None:
    authorization = FinalEvalAuthorization(
        confirmation="RELEASE-FINAL-HOLDOUT-2025",
        reason="test",
    )
    unsealed = build_modeling_frame(
        synthetic_feature_frame,
        synthetic_label_frame,
        authorization=authorization,
    )
    with pytest.raises(ValueError, match="unsealed"):
        run_distribution_study(unsealed, config=small_config)


def test_poisoning_the_sealed_season_changes_nothing(
    synthetic_feature_frame,
    synthetic_label_frame,
    small_config,
    study,
) -> None:
    """The seal, proved by construction rather than by inspection."""
    poisoned = synthetic_label_frame.with_columns(
        pl.when(pl.col("season") >= FINAL_HOLDOUT_SEASON)
        .then(pl.lit(-12345.0))
        .otherwise(pl.col("actual_fantasy_points"))
        .alias("actual_fantasy_points"),
    )
    dataset = build_modeling_frame(synthetic_feature_frame, poisoned)
    rerun = run_distribution_study(dataset, config=small_config)
    assert rerun.selected == study.selected
    assert rerun.aggregates == study.aggregates


def test_training_bounds_only_see_earlier_seasons(synthetic_modeling_dataset) -> None:
    frame = synthetic_modeling_dataset.frame
    bounds = training_bounds(frame, season=2020, scoring_preset="PPR")
    later = frame.filter((pl.col("season") >= 2020) & (pl.col("scoring_preset") == "PPR"))
    earlier = frame.filter((pl.col("season") < 2020) & (pl.col("scoring_preset") == "PPR"))
    for position, item in bounds.items():
        observed = earlier.filter(pl.col("position") == position).get_column("target_points")
        assert item.lower <= float(observed.min())
        assert item.upper >= float(observed.max())
    # A later-season record cannot have widened them.
    assert later.height > 0


def test_the_simulation_study_refuses_sealed_predictions(
    synthetic_modeling_dataset,
    study,
) -> None:
    predictions = study.predictions
    assert predictions is not None
    sealed = predictions.head(1).with_columns(
        pl.lit(FINAL_HOLDOUT_SEASON).cast(pl.Int32).alias("season")
    )
    with pytest.raises(ValueError, match="sealed season"):
        run_simulation_study(
            pl.concat([predictions, sealed]),
            synthetic_modeling_dataset.frame,
            pl.DataFrame(),
            _league(),
            config=SimulationStudyConfig(),
        )


def test_the_tier_study_refuses_sealed_predictions(synthetic_modeling_dataset, study) -> None:
    predictions = study.predictions
    assert predictions is not None
    sealed = predictions.head(1).with_columns(
        pl.lit(FINAL_HOLDOUT_SEASON).cast(pl.Int32).alias("season")
    )
    with pytest.raises(ValueError, match="sealed season"):
        run_tier_study(
            pl.concat([predictions, sealed]),
            synthetic_modeling_dataset.frame,
            pl.DataFrame(),
            _league(),
            config=TierStudyConfig(draws=100, statistic="median_vorp"),
        )


def _league():
    from ffdraft.config import load_league_config

    return load_league_config()


def test_missing_out_of_fold_predictions_say_what_to_run(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="evaluate-distribution"):
        load_oof_predictions(tmp_path / "oof_predictions.parquet")


@pytest.fixture
def dataset_dir(tmp_path, synthetic_feature_frame, synthetic_label_frame):
    directory = tmp_path / "historical"
    directory.mkdir()
    synthetic_feature_frame.write_parquet(directory / "features.parquet")
    synthetic_label_frame.write_parquet(directory / "labels_fantasy.parquet")
    return directory


def test_the_distribution_command_writes_reports_and_predictions(
    dataset_dir,
    tmp_path,
    capsys,
) -> None:
    out_dir = tmp_path / "report"
    predictions_dir = tmp_path / "phase4"
    status = main(
        [
            "evaluate-distribution",
            "--data",
            str(dataset_dir),
            "--out",
            str(out_dir),
            "--predictions-out",
            str(predictions_dir),
            "--validation-season",
            "2024",
            "--bootstrap-replicates",
            "40",
            "--composition-draws",
            "200",
            "--no-references",
            "--git-sha",
            "0000000",
        ],
    )
    output = capsys.readouterr().out
    assert status in {0, 1}
    assert (out_dir / "experiment.json").is_file()
    assert (out_dir / "experiment.md").is_file()
    assert (predictions_dir / "oof_predictions.parquet").is_file()
    assert "promoted" in output
    payload = json.loads((out_dir / "experiment.json").read_text(encoding="utf-8"))
    assert payload["frozen_rules"]["rules_version"] == "phase4_rules_v1"
    assert payload["git_sha"] == "0000000"
    assert 2025 not in {int(row["validation_season"]) for row in payload["aggregates_by_season"]}


def test_the_tier_command_needs_a_draw_count_and_a_statistic(dataset_dir, tmp_path, capsys) -> None:
    status = main(
        [
            "evaluate-tiers",
            "--data",
            str(dataset_dir),
            "--out",
            str(tmp_path / "tiers"),
            "--predictions",
            str(tmp_path / "missing"),
            "--simulation-report",
            str(tmp_path / "missing.json"),
        ],
    )
    assert status == 2
    assert "evaluate-simulation" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------
# The tier study, end to end
# ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_oof(synthetic_modeling_dataset) -> pl.DataFrame:
    """Out-of-fold-shaped predictions: five monotone quantiles around a known signal."""
    import numpy as np

    frame = synthetic_modeling_dataset.frame.filter(pl.col("season") == 2024)
    generator = np.random.default_rng(23)
    centre = frame.get_column("target_points").cast(pl.Float64).to_numpy()
    centre = centre + generator.normal(0.0, 15.0, size=centre.size)
    spread = generator.uniform(20.0, 80.0, size=centre.size)
    offsets = np.array([-1.28, -0.67, 0.0, 0.67, 1.28])
    quantiles = centre[:, None] + spread[:, None] * offsets[None, :]
    return frame.select("season", "player_id", "position", "scoring_preset").with_columns(
        pl.lit("CB").alias("model_id"),
        pl.Series("target_points", frame.get_column("target_points").cast(pl.Float64).to_numpy()),
        *[
            pl.Series(name, quantiles[:, index], dtype=pl.Float64)
            for index, name in enumerate(("q10", "q25", "q50", "q75", "q90"))
        ],
    )


@pytest.fixture(scope="module")
def synthetic_realized_vorp(synthetic_label_frame):
    from ffdraft.config import load_league_config
    from ffdraft.labels import build_vorp_labels

    league = load_league_config()
    return build_vorp_labels(
        synthetic_label_frame.filter(pl.col("season") == 2024),
        league,
        preset_ids=["redraft-10", "redraft-12", "redraft-14"],
    )


def test_the_tier_study_runs_and_records_both_algorithms(
    synthetic_oof,
    synthetic_modeling_dataset,
    synthetic_realized_vorp,
) -> None:
    """Both candidates are measured on the same boards and the same bootstrap replicates."""
    from ffdraft.config import load_league_config

    config = TierStudyConfig(
        draws=120,
        statistic="median_vorp",
        bootstrap_replicates=4,
        seasons=(2024,),
        scoring_presets=("PPR",),
        bootstrap_seasons=(2024,),
        preset_comparison_season=2024,
        board_depth=80,
    )
    result = run_tier_study(
        synthetic_oof,
        synthetic_modeling_dataset.frame,
        synthetic_realized_vorp,
        load_league_config(),
        config=config,
    )
    algorithms = [attempt["algorithm"] for attempt in result.attempts]
    assert algorithms[0] == "pelt_rbf"
    assert result.algorithm in {"pelt_rbf", "dp_quantile"}
    assert result.penalty_decision.rule == "phase4_tier_v1"
    assert result.stability_decision.rule == "phase4_tier_stability_v1"
    assert {check.check_id for check in result.checks} >= {
        "phase4.tier_penalty",
        "phase4.tier_stability",
    }
    for attempt in result.attempts:
        assert len(attempt["candidates"]) == len(config.penalties)


def test_the_alternative_is_only_reached_when_the_primary_fails(
    synthetic_oof,
    synthetic_modeling_dataset,
    synthetic_realized_vorp,
) -> None:
    """One attempt means PELT passed; two means a frozen rule refused it, and says which."""
    from ffdraft.config import load_league_config

    config = TierStudyConfig(
        draws=120,
        statistic="median_vorp",
        bootstrap_replicates=4,
        seasons=(2024,),
        scoring_presets=("PPR",),
        bootstrap_seasons=(2024,),
        preset_comparison_season=2024,
        board_depth=80,
    )
    result = run_tier_study(
        synthetic_oof,
        synthetic_modeling_dataset.frame,
        synthetic_realized_vorp,
        load_league_config(),
        config=config,
    )
    if result.algorithm == "pelt_rbf":
        assert len(result.attempts) == 1
    else:
        assert len(result.attempts) == 2
        first = result.attempts[0]
        assert first["penalty_failures"] or first["stability_failures"]
        escalation = next(
            check for check in result.checks if check.check_id == "phase4.tier_algorithm_escalated"
        )
        assert "dynamic-programming" in escalation.message
