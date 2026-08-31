"""The Phase-8 simulation-convergence audit, driven by constructed evidence.

These run before the audit is pointed at the committed report, which is the whole point: a
rule written after its result is not a rule. Every case below is synthetic.
"""

from __future__ import annotations

import pytest

from ffdraft.modeling.convergence_audit import (
    SIMULATION_CONVERGENCE_AUDIT,
    evidence_from_report,
)
from ffdraft.modeling.rules import CONVERGENCE_TOLERANCE, ConvergenceEvidence


def evidence(**overrides: object) -> ConvergenceEvidence:
    """A comparison that satisfies every simulation criterion, before overrides."""
    base: dict[str, object] = {
        "scenario": "2022/PPR/redraft-12",
        "comparison": "vs_second_seed",
        "draws": 10000,
        "mean_abs_expected_vorp": 0.10,
        "p99_abs_expected_vorp": 1.00,
        "mean_abs_p50_vorp": 0.20,
        "p99_abs_p50_vorp": 2.00,
        "mean_abs_outer_vorp": 0.40,
        "p99_abs_outer_vorp": 4.00,
        "max_abs_replacement": 0.30,
        "fair_rank_spearman": 0.9999,
        "top_50_overlap": 0.98,
        "mean_abs_rank_change_top_150": 1.0,
        # Tier agreement far below the Phase-4 composite rule's 0.90 clause, on purpose.
        "tier_adjusted_rand": 0.55,
        "tier_count_difference": 5,
    }
    base.update(overrides)
    return ConvergenceEvidence(**base)  # type: ignore[arg-type]


def test_no_bound_was_loosened_against_the_phase_4_freeze() -> None:
    """The audit changes the question, not the answer. Every number is inherited."""
    audit = SIMULATION_CONVERGENCE_AUDIT
    for name in (
        "mean_abs_expected_vorp",
        "p99_abs_expected_vorp",
        "mean_abs_p50_vorp",
        "p99_abs_p50_vorp",
        "mean_abs_outer_vorp",
        "p99_abs_outer_vorp",
        "max_abs_replacement",
        "min_fair_rank_spearman",
        "min_top_50_overlap",
        "max_mean_abs_rank_change_top_150",
    ):
        assert getattr(audit, name) == getattr(CONVERGENCE_TOLERANCE, name), name


def test_a_tier_disagreement_alone_does_not_fail_the_audit() -> None:
    """The finding ADR-034 records: the two properties are not the same property.

    This comparison would fail `phase4_convergence_v1` on its tier clause while every
    simulation quantity is comfortably inside tolerance.
    """
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate([evidence()], promoted_draws=10000)
    assert result.converged
    assert result.failures == ()
    # ...and the tier disagreement is still on the record rather than deleted.
    assert result.tier_observations["worst_tier_adjusted_rand"] == pytest.approx(0.55)
    assert result.tier_observations["worst_abs_tier_count_difference"] == pytest.approx(5.0)


def test_a_value_residual_still_fails_it() -> None:
    """Removing the tier clause must not make the audit unable to fail."""
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate(
        [evidence(mean_abs_expected_vorp=0.31)],
        promoted_draws=10000,
    )
    assert not result.converged
    assert any("mean_abs_expected_vorp 0.3100 exceeds 0.2500" in item for item in result.failures)


def test_a_ranking_residual_still_fails_it() -> None:
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate(
        [evidence(fair_rank_spearman=0.99, top_50_overlap=0.90)],
        promoted_draws=10000,
    )
    assert not result.converged
    assert any("fair_rank_spearman" in item for item in result.failures)
    assert any("top_50_overlap" in item for item in result.failures)


def test_only_the_promoted_draw_count_is_evaluated() -> None:
    """A configuration production never selected cannot decide anything."""
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate(
        [
            evidence(draws=1000, mean_abs_expected_vorp=9.9),
            evidence(draws=2500, mean_abs_expected_vorp=9.9),
            evidence(draws=10000),
        ],
        promoted_draws=10000,
    )
    assert result.converged
    assert result.comparisons == 1


def test_the_audit_cannot_select_a_smaller_count() -> None:
    """There is no code path from this rule to a draw count. The result carries none."""
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate([evidence()], promoted_draws=10000)
    assert result.promoted_draws == 10000
    assert not hasattr(result, "selected")
    assert "cannot select a draw count" in " ".join(
        SIMULATION_CONVERGENCE_AUDIT.to_dict()["rules"],
    )


def test_no_evidence_at_the_promoted_count_is_undetermined_not_passed() -> None:
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate([evidence(draws=1000)], promoted_draws=10000)
    assert not result.converged
    assert result.comparisons == 0
    assert any("undetermined" in note for note in result.notes)


def test_a_self_comparison_is_flagged_as_carrying_no_information() -> None:
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate(
        [
            evidence(
                comparison="vs_reference",
                mean_abs_expected_vorp=0.0,
                fair_rank_spearman=1.0,
            ),
        ],
        promoted_draws=10000,
    )
    assert any("degenerate" in note for note in result.notes)


def test_an_unmeasurable_comparison_fails_rather_than_passing_quietly() -> None:
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate(
        [evidence(mean_abs_p50_vorp=float("nan"))],
        promoted_draws=10000,
    )
    assert not result.converged
    assert any("not measured" in item for item in result.failures)


def test_residuals_report_the_worst_observation_per_criterion() -> None:
    result = SIMULATION_CONVERGENCE_AUDIT.evaluate(
        [
            evidence(scenario="a", mean_abs_expected_vorp=0.11, top_50_overlap=0.99),
            evidence(scenario="b", mean_abs_expected_vorp=0.19, top_50_overlap=0.97),
        ],
        promoted_draws=10000,
    )
    assert result.residuals["mean_abs_expected_vorp"]["worst"] == pytest.approx(0.19)
    assert result.residuals["top_50_overlap"]["worst"] == pytest.approx(0.97)


def test_evidence_is_rebuilt_from_a_report_row_without_loss() -> None:
    row = {key: getattr(evidence(), key) for key in ConvergenceEvidence.__slots__}
    rebuilt = evidence_from_report([row])
    assert rebuilt == [evidence()]
