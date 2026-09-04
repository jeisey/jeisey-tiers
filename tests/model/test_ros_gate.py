"""The frozen rest-of-season promotion rule.

Every clause is exercised with synthetic evidence, so the rule's behaviour is checkable
without running a forty-minute experiment - and so a future edit to a threshold shows up as
a failing test rather than as a quietly different verdict.
"""

from __future__ import annotations

import pytest

from ffdraft.modeling.bootstrap import BootstrapDelta
from ffdraft.ros.baselines import ROS_BASELINE_DECLARATION_ORDER
from ffdraft.ros.gate import (
    ROS_PROMOTION_CRITERIA,
    RosCohortEvidence,
    evaluate_ros_promotion_gate,
    select_primary_baseline,
)


def _delta(
    metric: str, delta: float, low: float, high: float, baseline: float = 10.0
) -> BootstrapDelta:
    return BootstrapDelta(
        metric=metric,
        lower_is_better=metric in {"mae", "mean_pinball"},
        baseline=baseline,
        candidate=baseline + delta,
        delta=delta,
        ci_low=low,
        ci_high=high,
        replicates=100,
        seed=1,
        share_favouring_candidate=0.9,
    )


def _passing_deltas() -> dict[str, BootstrapDelta]:
    return {
        "mean_pinball": _delta("mean_pinball", -0.5, -0.8, -0.2, baseline=4.0),
        "mae": _delta("mae", -0.3, -0.6, -0.1),
        "spearman": _delta("spearman", 0.02, 0.01, 0.03, baseline=0.7),
    }


def _cohort(slice_id: str, **overrides: float) -> RosCohortEvidence:
    values = {
        "rows": 1000,
        "baseline_mae": 10.0,
        "candidate_mae": 9.5,
        "baseline_spearman": 0.70,
        "candidate_spearman": 0.72,
        "candidate_coverage": 0.80,
    }
    values.update(overrides)
    return RosCohortEvidence(slice_id=slice_id, label=slice_id, **values)  # type: ignore[arg-type]


def _all_cohorts(**overrides: RosCohortEvidence) -> list[RosCohortEvidence]:
    cohorts = [_cohort(slice_id) for slice_id in ROS_PROMOTION_CRITERIA.required_cohorts]
    for index, cohort in enumerate(cohorts):
        if cohort.slice_id in overrides:
            cohorts[index] = overrides[cohort.slice_id]
    return cohorts


def test_a_candidate_that_wins_everywhere_is_promoted() -> None:
    result = evaluate_ros_promotion_gate(
        _passing_deltas(),
        _all_cohorts(),
        primary_baseline="R2",
        candidate="RC1",
    )
    assert result.promoted, result.reasons
    assert len(result.satisfied) == 4


def test_clause_one_refuses_an_unresolved_probabilistic_improvement() -> None:
    deltas = _passing_deltas()
    deltas["mean_pinball"] = _delta("mean_pinball", -0.05, -0.30, 0.20, baseline=4.0)
    result = evaluate_ros_promotion_gate(
        deltas,
        _all_cohorts(),
        primary_baseline="R2",
        candidate="RC1",
    )
    assert not result.promoted
    assert any("clause 1" in reason for reason in result.reasons)


def test_clause_one_refuses_a_worse_probabilistic_score_even_when_resolved() -> None:
    deltas = _passing_deltas()
    deltas["mean_pinball"] = _delta("mean_pinball", 0.4, 0.2, 0.6, baseline=4.0)
    result = evaluate_ros_promotion_gate(
        deltas,
        _all_cohorts(),
        primary_baseline="R2",
        candidate="RC1",
    )
    assert not result.promoted
    assert any("clause 1" in reason for reason in result.reasons)


def test_clause_two_allows_a_small_point_regression_and_refuses_a_large_one() -> None:
    deltas = _passing_deltas()
    deltas["mae"] = _delta("mae", 0.09, 0.05, 0.13)  # 0.9% of a 10.0 baseline
    assert evaluate_ros_promotion_gate(
        deltas,
        _all_cohorts(),
        primary_baseline="R2",
        candidate="RC1",
    ).promoted
    deltas["mae"] = _delta("mae", 0.5, 0.3, 0.7)
    result = evaluate_ros_promotion_gate(
        deltas,
        _all_cohorts(),
        primary_baseline="R2",
        candidate="RC1",
    )
    assert not result.promoted
    assert any("clause 2" in reason for reason in result.reasons)


def test_clause_three_refuses_a_rank_collapse() -> None:
    deltas = _passing_deltas()
    deltas["spearman"] = _delta("spearman", -0.05, -0.07, -0.03, baseline=0.7)
    result = evaluate_ros_promotion_gate(
        deltas,
        _all_cohorts(),
        primary_baseline="R2",
        candidate="RC1",
    )
    assert not result.promoted
    assert any("clause 3" in reason for reason in result.reasons)


def test_clause_four_refuses_a_missing_required_cohort() -> None:
    cohorts = [cohort for cohort in _all_cohorts() if cohort.slice_id != "returning_from_absence"]
    result = evaluate_ros_promotion_gate(
        _passing_deltas(),
        cohorts,
        primary_baseline="R2",
        candidate="RC1",
    )
    assert not result.promoted
    assert any("returning_from_absence" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    ("field", "value"),
    [("candidate_mae", 12.0), ("candidate_spearman", 0.60), ("candidate_coverage", 0.45)],
)
def test_clause_four_refuses_a_cohort_collapse(field: str, value: float) -> None:
    broken = _cohort("rookie", **{field: value})
    result = evaluate_ros_promotion_gate(
        _passing_deltas(),
        _all_cohorts(rookie=broken),
        primary_baseline="R2",
        candidate="RC1",
    )
    assert not result.promoted
    assert any("clause 4" in reason for reason in result.reasons)


def test_a_thin_cohort_is_reported_but_cannot_veto() -> None:
    thin = _cohort("high_capital_rookie", rows=50, candidate_spearman=0.10)
    assert not thin.decisive
    result = evaluate_ros_promotion_gate(
        _passing_deltas(),
        _all_cohorts(high_capital_rookie=thin),
        primary_baseline="R2",
        candidate="RC1",
    )
    assert result.promoted
    assert any(item.slice_id == "high_capital_rookie" for item in result.cohorts)


def test_the_primary_baseline_is_the_one_with_the_lowest_pinball_loss() -> None:
    macro = {
        "R0": {"mean_pinball": 5.0, "mae": 12.0},
        "R1": {"mean_pinball": 4.2, "mae": 11.0},
        "R2": {"mean_pinball": 4.0, "mae": 11.5},
        "R3": {"mean_pinball": 6.0, "mae": 14.0},
    }
    assert select_primary_baseline(macro, ROS_BASELINE_DECLARATION_ORDER) == "R2"


def test_a_pinball_tie_is_broken_by_point_accuracy_then_declaration_order() -> None:
    macro = {
        "R0": {"mean_pinball": 4.0, "mae": 12.0},
        "R1": {"mean_pinball": 4.0, "mae": 11.0},
        "R2": {"mean_pinball": 4.0, "mae": 11.0},
    }
    assert select_primary_baseline(macro, ROS_BASELINE_DECLARATION_ORDER) == "R1"


def test_the_criteria_serialize_with_their_version() -> None:
    payload = ROS_PROMOTION_CRITERIA.to_dict()
    assert payload["criteria_version"] == "ros_promotion_v1"
    assert payload["primary_probabilistic_metric"] == "mean_pinball"
    assert "returning_from_absence" in payload["required_cohorts"]
