"""The frozen Phase-4 decision rules, driven by synthetic evidence.

Every rule in :mod:`ffdraft.modeling.rules` is pure, so each one can be handed numbers that
make it say yes and numbers that make it say no. That is the point of writing them as data
plus a function: the behaviour of the gate is checkable in milliseconds, without running a
five-minute experiment, and a later edit that quietly loosens a threshold breaks a test.

The recurring assertion across the module is the same one: **mixed or indistinguishable
evidence resolves to the simpler incumbent.**
"""

from __future__ import annotations

import pytest

from ffdraft.modeling.rules import (
    CALIBRATION_ACCEPTANCE,
    CONVERGENCE_TOLERANCE,
    PHASE4_RULES_VERSION,
    TIER_PENALTY_GRID,
    CalibrationEvidence,
    ConvergenceEvidence,
    HorizonEvidence,
    PairedDelta,
    PositionalCalibration,
    RankingEvidence,
    TierCandidateEvidence,
    TierStabilityEvidence,
    all_rules,
    evaluate_calibration_choice,
    evaluate_candidate_choice,
    evaluate_convergence,
    evaluate_final_holdout,
    evaluate_horizon_choice,
    evaluate_ranking_choice,
    evaluate_tier_stability,
    select_tier_penalty,
)

POSITIONS = ("QB", "RB", "TE", "WR")


def _healthy_positional(
    outer: float = 0.79,
    inner: float = 0.50,
) -> tuple[PositionalCalibration, ...]:
    return tuple(PositionalCalibration(position, outer, inner) for position in POSITIONS)


def _calibration(
    variant_id: str,
    *,
    pinball: float = 8.0,
    mae: float = 22.0,
    outer: float = 0.77,
    inner: float = 0.51,
    width: float = 62.0,
    raw_crossing: float = 0.387,
    post_crossing: float = 0.0,
    positional: tuple[PositionalCalibration, ...] | None = None,
) -> CalibrationEvidence:
    return CalibrationEvidence(
        variant_id=variant_id,
        macro_mean_pinball=pinball,
        macro_mae=mae,
        coverage_p10_p90=outer,
        coverage_p25_p75=inner,
        mean_width_p10_p90=width,
        crossing_rate_raw=raw_crossing,
        crossing_rate_post=post_crossing,
        positional=positional if positional is not None else _healthy_positional(outer, inner),
    )


# ---------------------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------------------


def test_calibration_upgrade_requires_a_real_coverage_gain() -> None:
    """A fitted layer that only moves coverage by a whisker does not earn its complexity."""
    reference = _calibration("C0", outer=0.771)
    barely_better = _calibration("C1", outer=0.775)
    decision = evaluate_calibration_choice(reference, barely_better)
    assert decision.selected == "C0"
    assert not decision.decisive
    assert "coverage gap closed by only" in " ".join(decision.reasons)


def test_calibration_upgrade_is_taken_when_it_is_earned() -> None:
    reference = _calibration("C0", outer=0.771, pinball=8.13, width=62.7)
    better = _calibration("C1", outer=0.793, pinball=8.05, width=66.0)
    decision = evaluate_calibration_choice(reference, better)
    assert decision.selected == "C1"
    assert decision.decisive
    assert decision.passed


def test_calibration_refuses_coverage_bought_with_width() -> None:
    """Nominal coverage reached by inflating the interval is not calibration."""
    reference = _calibration("C0", outer=0.771, width=62.7)
    inflated = _calibration("C1", outer=0.800, width=90.0)
    decision = evaluate_calibration_choice(reference, inflated)
    assert decision.selected == "C0"
    assert "width inflated" in " ".join(decision.reasons)


def test_calibration_refuses_a_pinball_regression() -> None:
    reference = _calibration("C0", outer=0.771, pinball=8.13)
    worse_loss = _calibration("C1", outer=0.795, pinball=8.30)
    decision = evaluate_calibration_choice(reference, worse_loss)
    assert decision.selected == "C0"
    assert "pinball loss worsened" in " ".join(decision.reasons)


def test_calibration_hard_requirement_rejects_post_processing_crossings() -> None:
    """No production distribution may ship crossing quantiles, however good its loss."""
    reference = _calibration("C0", post_crossing=0.01)
    candidate = _calibration("C1", post_crossing=0.02, outer=0.80)
    decision = evaluate_calibration_choice(reference, candidate)
    assert not decision.passed
    assert any("crossing rate" in failure for failure in decision.failures)


def test_calibration_hard_requirement_rejects_positional_miscalibration() -> None:
    broken = _healthy_positional()
    broken = (*broken[:-1], PositionalCalibration("WR", 0.55, 0.50))
    reference = _calibration("C0", outer=0.771)
    candidate = _calibration("C1", outer=0.795, positional=broken)
    decision = evaluate_calibration_choice(reference, candidate)
    assert decision.selected == "C0"
    assert any("WR" in reason for reason in decision.reasons)


# ---------------------------------------------------------------------------------------
# Horizon sensitivity
# ---------------------------------------------------------------------------------------


def _horizon(
    *,
    mae_delta: float,
    mae_ci: tuple[float, float],
    pinball_delta: float,
    pinball_ci: tuple[float, float],
    season_mae: dict[int, float],
    baseline_mae: dict[int, float],
) -> HorizonEvidence:
    return HorizonEvidence(
        deltas={
            "mae": PairedDelta("mae", mae_delta, *mae_ci),
            "mean_pinball": PairedDelta("mean_pinball", pinball_delta, *pinball_ci),
        },
        baseline_mae_by_season=baseline_mae,
        candidate_mae_by_season=season_mae,
    )


def test_horizon_route_a_adopts_on_a_clean_double_win() -> None:
    evidence = _horizon(
        mae_delta=-0.40,
        mae_ci=(-0.60, -0.20),
        pinball_delta=-0.10,
        pinball_ci=(-0.16, -0.05),
        baseline_mae={2020: 21.0, 2021: 23.0, 2022: 22.5},
        season_mae={2020: 20.7, 2021: 22.4, 2022: 22.2},
    )
    decision = evaluate_horizon_choice(evidence)
    assert decision.selected == "Q1H"
    assert decision.decisive


def test_horizon_route_b_adopts_when_it_repairs_2021_for_free() -> None:
    evidence = _horizon(
        mae_delta=-0.05,
        mae_ci=(-0.20, 0.10),
        pinball_delta=-0.01,
        pinball_ci=(-0.05, 0.02),
        baseline_mae={2020: 21.0, 2021: 23.0, 2022: 22.5, 2023: 22.0, 2024: 21.8},
        season_mae={2020: 21.05, 2021: 22.3, 2022: 22.55, 2023: 22.0, 2024: 21.8},
    )
    decision = evaluate_horizon_choice(evidence)
    assert decision.selected == "Q1H"
    assert "route (b)" in " ".join(decision.reasons)


def test_horizon_keeps_q1_when_the_evidence_is_mixed() -> None:
    evidence = _horizon(
        mae_delta=-0.02,
        mae_ci=(-0.18, 0.14),
        pinball_delta=0.01,
        pinball_ci=(-0.03, 0.05),
        baseline_mae={2020: 21.0, 2021: 23.0, 2022: 22.5},
        season_mae={2020: 21.1, 2021: 22.9, 2022: 22.4},
    )
    decision = evaluate_horizon_choice(evidence)
    assert decision.selected == "Q1"
    assert not decision.decisive


def test_horizon_route_b_refuses_to_trade_another_fold_away() -> None:
    """Repairing 2021 at the cost of 2023 is a different model, not a repair."""
    evidence = _horizon(
        mae_delta=-0.01,
        mae_ci=(-0.20, 0.18),
        pinball_delta=-0.01,
        pinball_ci=(-0.04, 0.02),
        baseline_mae={2020: 21.0, 2021: 23.0, 2023: 22.0},
        season_mae={2020: 21.0, 2021: 22.0, 2023: 23.0},
    )
    decision = evaluate_horizon_choice(evidence)
    assert decision.selected == "Q1"


# ---------------------------------------------------------------------------------------
# Candidate A versus Candidate B
# ---------------------------------------------------------------------------------------


def _candidate_decision(
    *,
    pinball: PairedDelta,
    mae: PairedDelta,
    spearman: PairedDelta,
    top_k: PairedDelta,
    candidate: CalibrationEvidence | None = None,
    positional_mae: dict[str, float] | None = None,
) -> object:
    return evaluate_candidate_choice(
        deltas={
            "mean_pinball": pinball,
            "mae": mae,
            "spearman": spearman,
            "top_k_recall": top_k,
        },
        reference=_calibration("A", outer=0.78),
        candidate=candidate if candidate is not None else _calibration("B", outer=0.79),
        positional_mae_regression=positional_mae or dict.fromkeys(POSITIONS, -0.01),
        positional_rank_regression=dict.fromkeys(POSITIONS, -0.005),
    )


def test_candidate_b_needs_probabilistic_and_something_else() -> None:
    decision = _candidate_decision(
        pinball=PairedDelta("mean_pinball", -0.20, -0.30, -0.10),
        mae=PairedDelta("mae", -0.02, -0.30, 0.26),
        spearman=PairedDelta("spearman", 0.0005, -0.004, 0.005),
        top_k=PairedDelta("top_k_recall", 0.002, -0.01, 0.014),
    )
    assert decision.selected == "A"  # type: ignore[attr-defined]


def test_candidate_b_is_promoted_on_a_convincing_win() -> None:
    decision = _candidate_decision(
        pinball=PairedDelta("mean_pinball", -0.35, -0.48, -0.22),
        mae=PairedDelta("mae", -0.60, -0.90, -0.30),
        spearman=PairedDelta("spearman", 0.012, 0.004, 0.020),
        top_k=PairedDelta("top_k_recall", 0.025, 0.010, 0.040),
    )
    assert decision.selected == "B"  # type: ignore[attr-defined]
    assert decision.decisive  # type: ignore[attr-defined]


def test_candidate_b_loses_on_a_positional_collapse() -> None:
    decision = _candidate_decision(
        pinball=PairedDelta("mean_pinball", -0.35, -0.48, -0.22),
        mae=PairedDelta("mae", -0.60, -0.90, -0.30),
        spearman=PairedDelta("spearman", 0.012, 0.004, 0.020),
        top_k=PairedDelta("top_k_recall", 0.025, 0.010, 0.040),
        positional_mae={"QB": 0.09, "RB": -0.01, "TE": -0.01, "WR": -0.01},
    )
    assert decision.selected == "A"  # type: ignore[attr-defined]
    assert any("QB" in item for item in decision.evidence["blockers"])  # type: ignore[attr-defined]


def test_candidate_b_loses_when_its_intervals_degrade() -> None:
    decision = _candidate_decision(
        pinball=PairedDelta("mean_pinball", -0.35, -0.48, -0.22),
        mae=PairedDelta("mae", -0.60, -0.90, -0.30),
        spearman=PairedDelta("spearman", 0.012, 0.004, 0.020),
        top_k=PairedDelta("top_k_recall", 0.025, 0.010, 0.040),
        candidate=_calibration("B", outer=0.70),
    )
    assert decision.selected == "A"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------------
# Monte Carlo convergence
# ---------------------------------------------------------------------------------------


def _convergence(
    draws: int, *, scale: float, scenario: str = "ppr/redraft-12"
) -> list[ConvergenceEvidence]:
    """Two comparisons at one draw count, with error scaled by ``scale``."""
    return [
        ConvergenceEvidence(
            scenario=scenario,
            comparison=comparison,
            draws=draws,
            mean_abs_expected_vorp=0.10 * scale,
            p99_abs_expected_vorp=0.60 * scale,
            mean_abs_p50_vorp=0.15 * scale,
            p99_abs_p50_vorp=1.20 * scale,
            mean_abs_outer_vorp=0.25 * scale,
            p99_abs_outer_vorp=2.00 * scale,
            max_abs_replacement=0.20 * scale,
            fair_rank_spearman=1.0 - 0.0005 * scale,
            top_50_overlap=1.0 - 0.02 * scale,
            mean_abs_rank_change_top_150=0.6 * scale,
            tier_adjusted_rand=1.0 - 0.05 * scale,
            tier_count_difference=0,
        )
        for comparison in ("vs_reference", "vs_second_seed")
    ]


def test_convergence_selects_the_smallest_qualifying_draw_count() -> None:
    evidence = [
        *_convergence(1000, scale=4.0),
        *_convergence(2500, scale=2.0),
        *_convergence(5000, scale=1.0),
        *_convergence(10000, scale=0.7),
    ]
    decision = evaluate_convergence(evidence)
    assert decision.selected == "2500"
    assert decision.decisive


def test_convergence_falls_back_to_the_reference_when_nothing_qualifies() -> None:
    evidence = [*_convergence(1000, scale=8.0), *_convergence(10000, scale=6.0)]
    decision = evaluate_convergence(evidence)
    assert decision.selected == str(CONVERGENCE_TOLERANCE.reference_draws)
    assert not decision.decisive
    assert decision.failures


def test_convergence_requires_every_scenario_to_pass() -> None:
    """One preset failing is enough; the draw count is a single global choice."""
    evidence = [
        *_convergence(2500, scale=1.0, scenario="ppr/redraft-12"),
        *_convergence(2500, scale=9.0, scenario="std/redraft-14"),
        *_convergence(5000, scale=1.0, scenario="ppr/redraft-12"),
        *_convergence(5000, scale=1.2, scenario="std/redraft-14"),
    ]
    decision = evaluate_convergence(evidence)
    assert decision.selected == "5000"


# ---------------------------------------------------------------------------------------
# Ranking statistic
# ---------------------------------------------------------------------------------------


def _ranking(
    statistic: str,
    *,
    spearman: float,
    kendall: float,
    top_k: float,
    by_position: dict[str, float] | None = None,
) -> RankingEvidence:
    return RankingEvidence(
        statistic=statistic,
        macro_spearman=spearman,
        macro_kendall=kendall,
        macro_top_k_recall=top_k,
        macro_top_k_precision=top_k,
        top_k_recall_by_position=by_position or dict.fromkeys(POSITIONS, top_k),
        seed_rank_stability=0.999,
    )


def test_ranking_defaults_to_median_when_the_gain_is_small() -> None:
    decision = evaluate_ranking_choice(
        _ranking("median_vorp", spearman=0.72, kendall=0.56, top_k=0.540),
        _ranking("expected_vorp", spearman=0.72, kendall=0.56, top_k=0.545),
    )
    assert decision.selected == "median_vorp"
    assert not decision.decisive


def test_ranking_selects_expected_on_a_real_top_of_board_gain() -> None:
    decision = evaluate_ranking_choice(
        _ranking("median_vorp", spearman=0.720, kendall=0.560, top_k=0.540),
        _ranking("expected_vorp", spearman=0.719, kendall=0.559, top_k=0.575),
    )
    assert decision.selected == "expected_vorp"
    assert decision.decisive


def test_ranking_refuses_expected_when_a_position_collapses() -> None:
    decision = evaluate_ranking_choice(
        _ranking(
            "median_vorp",
            spearman=0.720,
            kendall=0.560,
            top_k=0.540,
            by_position={"QB": 0.60, "RB": 0.52, "TE": 0.55, "WR": 0.50},
        ),
        _ranking(
            "expected_vorp",
            spearman=0.720,
            kendall=0.560,
            top_k=0.575,
            by_position={"QB": 0.55, "RB": 0.60, "TE": 0.58, "WR": 0.56},
        ),
    )
    assert decision.selected == "median_vorp"


def test_ranking_refuses_expected_when_global_order_deteriorates() -> None:
    decision = evaluate_ranking_choice(
        _ranking("median_vorp", spearman=0.740, kendall=0.580, top_k=0.540),
        _ranking("expected_vorp", spearman=0.720, kendall=0.560, top_k=0.600),
    )
    assert decision.selected == "median_vorp"


# ---------------------------------------------------------------------------------------
# Tier penalty and stability
# ---------------------------------------------------------------------------------------


def _tier_candidate(
    penalty: float,
    *,
    tiers: float,
    singleton: float = 0.05,
    largest: float = 0.15,
    boundary: float = 1.2,
    within: float = 0.4,
    ari: float = 0.70,
) -> TierCandidateEvidence:
    return TierCandidateEvidence(
        penalty=penalty,
        mean_tier_count=tiers,
        singleton_rate=singleton,
        largest_tier_share=largest,
        mean_boundary_effect_size=boundary,
        median_within_tier_effect_size=within,
        bootstrap_adjusted_rand=ari,
        boundary_agreement=0.6,
    )


def test_tier_penalty_rejects_singleton_proliferation_and_degenerate_boards() -> None:
    evidence = [
        _tier_candidate(1.0, tiers=40.0, singleton=0.45),
        _tier_candidate(2.0, tiers=18.0, singleton=0.08, ari=0.62),
        _tier_candidate(12.0, tiers=3.0),
    ]
    decision = select_tier_penalty(evidence)
    assert decision.selected == "2.0"
    assert 1.0 in decision.evidence["inadmissible"] or "1.0" in decision.evidence["inadmissible"]


def test_tier_penalty_prefers_the_more_stable_admissible_candidate() -> None:
    evidence = [
        _tier_candidate(2.0, tiers=20.0, ari=0.61),
        _tier_candidate(5.0, tiers=11.0, ari=0.74),
        _tier_candidate(8.0, tiers=8.0, ari=0.72),
    ]
    decision = select_tier_penalty(evidence)
    assert decision.selected == "5.0"


def test_tier_penalty_tie_breaks_towards_the_simpler_board() -> None:
    """Inside the tie band, better separation wins, then the larger penalty."""
    evidence = [
        _tier_candidate(3.0, tiers=15.0, ari=0.700, boundary=1.0),
        _tier_candidate(8.0, tiers=9.0, ari=0.695, boundary=1.4),
    ]
    decision = select_tier_penalty(evidence)
    assert decision.selected == "8.0"


def test_tier_penalty_reports_failure_when_nothing_is_admissible() -> None:
    decision = select_tier_penalty([_tier_candidate(1.0, tiers=90.0, singleton=0.8)])
    assert decision.selected == "none"
    assert decision.failures


def test_tier_penalty_grid_is_frozen_and_ordered() -> None:
    assert TIER_PENALTY_GRID == (1.0, 2.0, 3.0, 5.0, 8.0, 12.0)
    assert list(TIER_PENALTY_GRID) == sorted(TIER_PENALTY_GRID)


def test_tier_stability_gate_passes_and_fails_on_declared_thresholds() -> None:
    healthy = TierStabilityEvidence(
        bootstrap_adjusted_rand=0.71,
        boundary_agreement=0.62,
        singleton_rate=0.06,
        tier_count_cv=0.11,
        monotonic_pair_share=0.92,
        cross_preset_adjusted_rand=0.68,
    )
    assert evaluate_tier_stability(healthy).selected == "pass"

    unstable = TierStabilityEvidence(
        bootstrap_adjusted_rand=0.41,
        boundary_agreement=0.30,
        singleton_rate=0.06,
        tier_count_cv=0.40,
        monotonic_pair_share=0.92,
        cross_preset_adjusted_rand=0.68,
    )
    decision = evaluate_tier_stability(unstable)
    assert decision.selected == "fail"
    assert len(decision.failures) == 3


# ---------------------------------------------------------------------------------------
# Final holdout
# ---------------------------------------------------------------------------------------


def _holdout(**overrides: object) -> object:
    payload: dict[str, object] = {
        "deltas": {
            "mae": PairedDelta("mae", -3.0, -3.6, -2.4),
            "mean_pinball": PairedDelta("mean_pinball", -1.6, -1.9, -1.3),
            "spearman": PairedDelta("spearman", 0.05, 0.03, 0.07),
        },
        "positional_mae_regression": dict.fromkeys(POSITIONS, -0.10),
        "positional_rank_regression": dict.fromkeys(POSITIONS, -0.05),
        "positional_coverage": dict.fromkeys(POSITIONS, 0.78),
        "post_crossing_rate": 0.0,
        "all_finite": True,
    }
    payload.update(overrides)
    return evaluate_final_holdout(**payload)  # type: ignore[arg-type]


def test_final_holdout_gate_passes_a_convincing_result() -> None:
    decision = _holdout()
    assert decision.selected == "pass"  # type: ignore[attr-defined]
    assert decision.decisive  # type: ignore[attr-defined]


def test_final_holdout_gate_fails_an_interval_that_includes_zero() -> None:
    decision = _holdout(
        deltas={
            "mae": PairedDelta("mae", -0.5, -1.4, 0.4),
            "mean_pinball": PairedDelta("mean_pinball", -1.6, -1.9, -1.3),
            "spearman": PairedDelta("spearman", 0.05, 0.03, 0.07),
        },
    )
    assert decision.selected == "fail"  # type: ignore[attr-defined]
    assert any("includes zero" in item for item in decision.failures)  # type: ignore[attr-defined]


def test_final_holdout_gate_fails_a_crossing_distribution() -> None:
    decision = _holdout(post_crossing_rate=0.001)
    assert decision.selected == "fail"  # type: ignore[attr-defined]


def test_final_holdout_gate_fails_a_positional_collapse() -> None:
    decision = _holdout(positional_coverage={**dict.fromkeys(POSITIONS, 0.78), "TE": 0.52})
    assert decision.selected == "fail"  # type: ignore[attr-defined]
    assert any("TE" in item for item in decision.failures)  # type: ignore[attr-defined]


def test_final_holdout_gate_is_not_swayed_by_diagnostic_slices() -> None:
    """ADR-025's slices are diagnostics. The gate signature has no place to put them."""
    import inspect

    parameters = set(inspect.signature(evaluate_final_holdout).parameters)
    assert "slices" not in parameters
    assert parameters == {
        "deltas",
        "positional_mae_regression",
        "positional_rank_regression",
        "positional_coverage",
        "post_crossing_rate",
        "all_finite",
        "criteria",
    }


# ---------------------------------------------------------------------------------------
# The freeze itself
# ---------------------------------------------------------------------------------------


def test_every_rule_is_versioned_and_serializable() -> None:
    rules = all_rules()
    assert rules["rules_version"] == PHASE4_RULES_VERSION
    expected = {
        "calibration",
        "horizon_sensitivity",
        "candidate_comparison",
        "monte_carlo_convergence",
        "ranking_statistic",
        "tier_selection",
        "tier_stability",
        "final_holdout",
    }
    assert expected <= set(rules)
    for name in expected:
        payload = rules[name]
        assert payload["criteria_version"].startswith("phase4_")
        assert payload["rules"], f"{name} must state its rules in words as well as numbers"


@pytest.mark.parametrize(
    ("delta", "low", "high", "significant"),
    [(-1.0, -1.5, -0.5, True), (-1.0, -2.0, 0.5, False), (1.0, 0.5, 1.5, True)],
)
def test_paired_delta_significance_matches_the_interval(
    delta: float,
    low: float,
    high: float,
    significant: bool,
) -> None:
    assert PairedDelta("m", delta, low, high).significant is significant


def test_calibration_criteria_are_the_frozen_instance() -> None:
    """A study must not be able to pass its own thresholds in by accident."""
    assert CALIBRATION_ACCEPTANCE.version == "phase4_calibration_v1"
    assert CALIBRATION_ACCEPTANCE.max_post_crossing_rate == 0.0
