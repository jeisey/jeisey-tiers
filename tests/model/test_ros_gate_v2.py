"""The successor promotion rule, and the property that makes it a fix rather than a loosening.

Two things are asserted here that a threshold change could not satisfy:

* on a **continuous** cohort, where the climatological reference sits at the textbook 0.80,
  v2's calibration clause is *stricter* than v1's — it refuses under-coverage v1 allowed;
* v2's width clause cannot fire on a candidate whose interval is narrower than the baseline's,
  which is the configuration an atom at zero produces.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.bootstrap import BootstrapDelta
from ffdraft.ros.gate import (
    ROS_PROMOTION_CRITERIA,
    ROS_PROMOTION_CRITERIA_V2,
    RosCohortEvidence,
    evaluate_ros_promotion_gate,
    evaluate_ros_promotion_gate_v2,
)
from ffdraft.ros.reference import MINIMUM_CELL_ROWS, cohort_reference


def _delta(metric: str, delta: float, low: float, high: float, baseline: float = 10.0):
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
    values: dict[str, float] = {
        "rows": 1000,
        "baseline_mae": 10.0,
        "candidate_mae": 9.5,
        "baseline_spearman": 0.70,
        "candidate_spearman": 0.72,
        "candidate_coverage": 0.80,
        "baseline_coverage": 0.79,
        "baseline_width": 30.0,
        "candidate_width": 25.0,
        "baseline_pinball": 4.0,
        "candidate_pinball": 3.5,
        "reference_coverage": 0.80,
        "reference_width": 40.0,
        "reference_zero_share": 0.05,
    }
    values.update(overrides)
    return RosCohortEvidence(slice_id=slice_id, label=slice_id, **values)  # type: ignore[arg-type]


def _all_cohorts(**overrides: RosCohortEvidence) -> list[RosCohortEvidence]:
    cohorts = [_cohort(slice_id) for slice_id in ROS_PROMOTION_CRITERIA_V2.required_cohorts]
    return [overrides.get(cohort.slice_id, cohort) for cohort in cohorts]


def _v2(cohorts, deltas=None):
    return evaluate_ros_promotion_gate_v2(
        deltas or _passing_deltas(),
        cohorts,
        primary_baseline="R2",
        candidate="RC1",
    )


def test_v1_is_untouched_and_still_reachable() -> None:
    """The successor is additive. v1's thresholds are exactly what they were."""
    assert ROS_PROMOTION_CRITERIA.version == "ros_promotion_v1"
    assert ROS_PROMOTION_CRITERIA.coverage_band == (0.60, 0.95)
    assert ROS_PROMOTION_CRITERIA_V2.supersedes == "ros_promotion_v1"


def test_a_candidate_that_wins_everywhere_passes_v2() -> None:
    result = _v2(_all_cohorts())
    assert result.promoted, result.reasons
    assert result.criteria.version == "ros_promotion_v2"


def test_clauses_one_to_three_are_v1s_unchanged() -> None:
    for metric, bad in (
        ("mean_pinball", _delta("mean_pinball", -0.05, -0.30, 0.20, baseline=4.0)),
        ("mae", _delta("mae", 0.5, 0.3, 0.7)),
        ("spearman", _delta("spearman", -0.05, -0.07, -0.03, baseline=0.7)),
    ):
        deltas = _passing_deltas()
        deltas[metric] = bad
        assert not _v2(_all_cohorts(), deltas).promoted, metric
        assert not evaluate_ros_promotion_gate(
            deltas,
            _all_cohorts(),
            primary_baseline="R2",
            candidate="RC1",
        ).promoted, metric


def test_v2_is_stricter_than_v1_on_under_coverage_for_a_continuous_cohort() -> None:
    """A continuous cohort's reference is 0.80, so v2's band is [0.65, 0.95].

    Coverage of 0.62 is inside v1's [0.60, 0.95] and outside v2's. A rule written to let a
    candidate through would not have made this case fail.
    """
    under = _cohort("rookie", candidate_coverage=0.62, reference_coverage=0.80)
    assert evaluate_ros_promotion_gate(
        _passing_deltas(),
        _all_cohorts(rookie=under),
        primary_baseline="R2",
        candidate="RC1",
    ).promoted
    result = _v2(_all_cohorts(rookie=under))
    assert not result.promoted
    assert any("4e" in reason for reason in result.reasons)


def test_v2_moves_the_band_with_the_attainable_coverage_not_with_the_result() -> None:
    """Same candidate coverage, two targets: admissible against an atom, not against a
    continuous one."""
    atom = _cohort("rookie", candidate_coverage=0.96, reference_coverage=0.93)
    continuous = _cohort("rookie", candidate_coverage=0.96, reference_coverage=0.80)
    assert _v2(_all_cohorts(rookie=atom)).promoted
    assert not _v2(_all_cohorts(rookie=continuous)).promoted


def test_the_width_clause_cannot_fire_on_a_narrower_interval() -> None:
    """The configuration an atom produces — narrower and better covered — is never a failure."""
    narrow = _cohort(
        "games_played_band",
        candidate_width=14.5,
        baseline_width=17.1,
        reference_width=4.5,
        candidate_coverage=0.964,
        reference_coverage=0.926,
    )
    result = _v2(_all_cohorts(games_played_band=narrow))
    assert result.promoted, result.reasons


def test_the_width_clause_fires_on_an_interval_wider_than_knowing_nothing() -> None:
    useless = _cohort(
        "in_season_arrival",
        candidate_width=80.0,
        baseline_width=30.0,
        reference_width=40.0,
    )
    result = _v2(_all_cohorts(in_season_arrival=useless))
    assert not result.promoted
    assert any("4d" in reason for reason in result.reasons)


def test_a_wider_interval_that_beats_climatology_is_not_a_failure() -> None:
    """Wider than the baseline is fine when it is still narrower than knowing nothing."""
    wider = _cohort(
        "in_season_arrival", candidate_width=35.0, baseline_width=30.0, reference_width=40.0
    )
    assert _v2(_all_cohorts(in_season_arrival=wider)).promoted


def test_the_proper_local_score_clause_catches_a_worse_distribution() -> None:
    worse = _cohort("veteran", baseline_pinball=4.0, candidate_pinball=4.5)
    result = _v2(_all_cohorts(veteran=worse))
    assert not result.promoted
    assert any("4c" in reason for reason in result.reasons)


def test_v1s_point_and_rank_sub_clauses_are_carried_over_unchanged() -> None:
    for field, value, tag in (
        ("candidate_mae", 12.0, "4a"),
        ("candidate_spearman", 0.60, "4b"),
    ):
        broken = _cohort("rookie", **{field: value})
        result = _v2(_all_cohorts(rookie=broken))
        assert not result.promoted
        assert any(tag in reason for reason in result.reasons)


def test_a_missing_required_cohort_still_fails() -> None:
    cohorts = [c for c in _all_cohorts() if c.slice_id != "returning_from_absence"]
    assert not _v2(cohorts).promoted


# -- the reference itself ---------------------------------------------------------------


def _frame(values: np.ndarray) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": [2020] * values.size,
            "through_week": [4] * values.size,
            "position": ["WR"] * values.size,
            "scoring_preset": ["PPR"] * values.size,
            "actual_remaining_points": values.astype(float),
        },
    )


def test_a_continuous_cohort_puts_the_reference_at_the_textbook_eighty_percent() -> None:
    generator = np.random.default_rng(3)
    reference = cohort_reference(
        _frame(generator.normal(50.0, 20.0, 5_000)),
        target_column="actual_remaining_points",
    )
    assert reference.coverage == pytest.approx(0.80, abs=0.01)
    assert reference.zero_share == 0.0


@pytest.mark.parametrize("mass", [0.15, 0.50, 0.85])
def test_an_atom_pins_the_attainable_coverage_at_ninety_percent(mass: float) -> None:
    """The arithmetic the successor rule exists for.

    With an atom of mass ``p >= 0.10`` at zero and a continuous part above it, the tenth
    percentile *is* zero, nothing sits below it, and a perfectly calibrated closed interval
    covers ``F(q90) = 0.90`` — exactly, and regardless of how large the atom is. 0.80 is not
    approached from either side; it is simply not the attainable value.
    """
    generator = np.random.default_rng(5)
    values = np.where(
        generator.random(20_000) < mass,
        0.0,
        np.abs(generator.normal(40.0, 15.0, 20_000)),
    )
    reference = cohort_reference(_frame(values), target_column="actual_remaining_points")
    assert reference.zero_share == pytest.approx(mass, abs=0.02)
    assert reference.coverage == pytest.approx(0.90, abs=0.005)


def test_an_atom_above_ninety_percent_takes_a_perfect_forecaster_past_v1s_ceiling() -> None:
    """The decisive case: calibration itself breaches v1's bound.

    When the atom holds more than 90% of the mass, both reported quantiles are zero, the
    interval collapses to the single point zero, and a *perfectly calibrated* forecaster covers
    the atom's whole mass. v1 would refuse it for being uninformative while it is in fact
    exactly right — and its interval has width zero, the opposite of "so wide it says nothing".
    """
    generator = np.random.default_rng(7)
    values = np.where(
        generator.random(20_000) < 0.96,
        0.0,
        np.abs(generator.normal(40.0, 15.0, 20_000)),
    )
    reference = cohort_reference(_frame(values), target_column="actual_remaining_points")
    assert reference.coverage > ROS_PROMOTION_CRITERIA.coverage_band[1]
    assert reference.width == 0.0


def test_a_thin_cell_falls_back_to_the_pooled_quantiles() -> None:
    values = np.arange(float(MINIMUM_CELL_ROWS - 1))
    reference = cohort_reference(_frame(values), target_column="actual_remaining_points")
    assert reference.pooled_rows == values.size
    assert reference.cells == 1


def test_the_reference_is_a_function_of_the_outcome_alone(ros_dataset) -> None:
    """No model column can change it — that is what makes it usable as a gate reference."""
    frame = _frame(np.array([0.0, 0.0, 5.0, 10.0, 20.0] * 40))
    left = cohort_reference(frame, target_column="actual_remaining_points")
    right = cohort_reference(
        frame.with_columns(pl.lit(999.0).alias("pred_point_RC1")),
        target_column="actual_remaining_points",
    )
    assert left.to_dict() == right.to_dict()
