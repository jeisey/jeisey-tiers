"""The rest-of-season value study, end to end on the synthetic snapshot dataset.

Small draw counts and a single fold: the point is that the three frozen rules are wired to
real measurements and produce a decision, not that the synthetic numbers mean anything.
"""

from __future__ import annotations

import pytest

from ffdraft.modeling.rules import CONVERGENCE_TOLERANCE, TIER_SELECTION
from ffdraft.ros.folds import RosFold
from ffdraft.ros.study import RosValueStudyConfig, run_ros_value_study
from ffdraft.ros.value import RosReplacementRule
from ffdraft.ros.value_report import to_json, to_markdown, write_ros_value_report


@pytest.fixture(scope="module")
def study(ros_dataset, app_config):
    config = RosValueStudyConfig(
        fold=RosFold(train_start_season=2017, train_end_season=2019, validation_season=2020),
        weeks=(4, 12),
        convergence_weeks=(12,),
        draws=200,
        stability_replicates=5,
        board_depth=60,
    )
    return run_ros_value_study(ros_dataset, app_config.league, config=config)


def test_both_replacement_rules_are_measured_on_every_scenario(study) -> None:
    rows = study.replacement_sensitivity
    assert rows
    for row in rows:
        assert set(row["replacement_by_rule"]) == {str(rule) for rule in RosReplacementRule}
        assert 0.0 <= row["top_50_overlap"] <= 1.0


def test_the_in_season_replacement_is_never_above_the_fresh_one(study) -> None:
    for row in study.replacement_sensitivity:
        fresh = row["replacement_by_rule"][str(RosReplacementRule.FRESH_ALLOCATION)]
        rostered = row["replacement_by_rule"][str(RosReplacementRule.ROSTERED_DEPTH)]
        for position, baseline in fresh.items():
            other = rostered.get(position)
            if baseline is None or other is None:
                continue
            assert other <= baseline + 1e-9, position


def test_the_replacement_decision_names_one_of_the_two_rules(study) -> None:
    assert study.replacement_decision.selected in {str(rule) for rule in RosReplacementRule}
    assert study.replacement_decision.rule == "ros_replacement_v1"


def test_convergence_is_measured_against_both_comparisons(study) -> None:
    comparisons = {item.comparison for item in study.convergence_evidence}
    assert comparisons == {
        f"vs {CONVERGENCE_TOLERANCE.reference_draws} draws",
        "seed to seed",
    }
    assert {item.draws for item in study.convergence_evidence} == set(
        CONVERGENCE_TOLERANCE.draw_ladder,
    )


def test_every_penalty_in_the_frozen_grid_is_segmented(study) -> None:
    penalties = {float(row["penalty"]) for row in study.tier_shape}
    assert penalties == {float(value) for value in TIER_SELECTION.penalties}
    algorithms = {row["algorithm"] for row in study.tier_shape}
    assert algorithms == {"pelt_rbf", "dp_quantile"}


def test_the_stability_gate_returns_a_verdict(study) -> None:
    assert study.stability_decision.selected in {"pass", "fail"}
    assert study.stability_decision.rule == "phase4_tier_stability_v1"


def test_the_study_reports_serialize(study, tmp_path) -> None:
    written = write_ros_value_report(study, tmp_path)
    assert {path.name for path in written} == {"value_study.json", "value_study.md"}
    assert "Rest-of-season value study" in to_markdown(study)
    assert '"criteria_version"' in to_json(study)


def test_the_boards_use_the_internal_vocabulary_until_they_are_published(study) -> None:
    """The study's own tables keep Release 1's column names; only artifacts get `ros_` names."""
    for rows in study.boards.values():
        assert rows
        assert set(rows[0]) >= {"player_id", "fair_rank", "p50_vorp"}
