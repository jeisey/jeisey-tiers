"""Paired uncertainty and the frozen promotion rule.

The bootstrap tests are about *pairing* and *determinism*: a comparison that resampled the
two models independently, or that drifted between runs, could not support a promotion
decision. The gate tests are the `docs/TEST_STRATEGY.md` 7 requirement - a synthetic winner
must pass and a synthetic positional collapse must fail, so the comparator is verified on
metrics nobody had to run a model to produce.
"""

from __future__ import annotations

import numpy as np
import pytest

from ffdraft.modeling.bootstrap import (
    BootstrapDelta,
    PairedCell,
    paired_bootstrap,
    row_pinball_loss,
)
from ffdraft.modeling.folds import WindowPolicy
from ffdraft.modeling.gate import (
    PROMOTION_CRITERIA,
    PositionalEvidence,
    evaluate_promotion_gate,
    select_training_window,
)
from ffdraft.modeling.metrics import QUANTILE_LEVELS, mean_pinball

LEVELS = QUANTILE_LEVELS
OFFSETS = np.array([-40.0, -20.0, 0.0, 20.0, 40.0])


def _cell(key: str, *, n: int, candidate_noise: float, seed: int) -> PairedCell:
    generator = np.random.default_rng(seed)
    actual = generator.normal(120.0, 40.0, size=n)
    baseline_point = actual + generator.normal(0.0, 30.0, size=n)
    candidate_point = actual + generator.normal(0.0, candidate_noise, size=n)
    return PairedCell(
        key=key,
        actual=actual,
        baseline_point=baseline_point,
        candidate_point=candidate_point,
        baseline_quantiles=baseline_point[:, None] + OFFSETS[None, :],
        candidate_quantiles=candidate_point[:, None] + OFFSETS[None, :],
    )


def _cells(candidate_noise: float = 10.0) -> list[PairedCell]:
    return [
        _cell(f"2023|{position}|PPR", n=120, candidate_noise=candidate_noise, seed=index)
        for index, position in enumerate(("QB", "RB", "WR", "TE"))
    ]


# --------------------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------------------


def test_row_pinball_loss_averages_to_the_slice_metric():
    generator = np.random.default_rng(1)
    actual = generator.normal(100.0, 20.0, size=40)
    quantiles = actual[:, None] + OFFSETS[None, :]
    assert float(np.mean(row_pinball_loss(actual, quantiles, LEVELS))) == pytest.approx(
        mean_pinball(actual, quantiles, LEVELS),
    )


def test_the_bootstrap_is_deterministic_for_a_fixed_seed():
    cells = _cells()
    first = paired_bootstrap(cells, seed=99, replicates=200)
    second = paired_bootstrap(cells, seed=99, replicates=200)
    for metric, delta in first.items():
        assert delta.to_dict() == second[metric].to_dict()


def test_the_bootstrap_does_not_depend_on_cell_order():
    cells = _cells()
    forward = paired_bootstrap(cells, seed=99, replicates=200)
    backward = paired_bootstrap(list(reversed(cells)), seed=99, replicates=200)
    for metric, delta in forward.items():
        assert delta.ci_low == pytest.approx(backward[metric].ci_low)
        assert delta.ci_high == pytest.approx(backward[metric].ci_high)


def test_a_different_seed_moves_the_interval_but_not_the_point_estimate():
    cells = _cells()
    first = paired_bootstrap(cells, seed=1, replicates=200)
    second = paired_bootstrap(cells, seed=2, replicates=200)
    assert first["mae"].delta == pytest.approx(second["mae"].delta)
    assert (first["mae"].ci_low, first["mae"].ci_high) != (
        second["mae"].ci_low,
        second["mae"].ci_high,
    )


def test_a_clearly_better_candidate_produces_an_interval_below_zero():
    result = paired_bootstrap(_cells(candidate_noise=5.0), seed=7, replicates=500)
    assert result["mae"].delta < 0
    assert result["mae"].ci_high < 0
    assert result["mae"].favours_candidate
    assert result["mean_pinball"].favours_candidate
    assert result["spearman"].delta > 0


def test_two_identical_models_produce_a_zero_delta_and_a_zero_width_interval():
    cells = _cells()
    identical = [
        PairedCell(
            key=cell.key,
            actual=cell.actual,
            baseline_point=cell.baseline_point,
            candidate_point=cell.baseline_point,
            baseline_quantiles=cell.baseline_quantiles,
            candidate_quantiles=cell.baseline_quantiles,
        )
        for cell in cells
    ]
    result = paired_bootstrap(identical, seed=3, replicates=100)
    for metric in ("mae", "mean_pinball", "spearman"):
        assert result[metric].delta == pytest.approx(0.0)
        assert result[metric].ci_low == pytest.approx(0.0)
        assert result[metric].ci_high == pytest.approx(0.0)
        assert not result[metric].significant


def test_pairing_is_preserved_rather_than_resampled_independently():
    """Two models that differ by a constant have a delta whose interval is degenerate.

    Independent resampling could not produce that: it would give the difference of two
    noisy means. This is the property that makes the paired interval meaningful.
    """
    cells = _cells()
    shifted = [
        PairedCell(
            key=cell.key,
            actual=cell.actual,
            baseline_point=cell.actual + 10.0,
            candidate_point=cell.actual - 10.0,
            baseline_quantiles=(cell.actual + 10.0)[:, None] + OFFSETS[None, :],
            candidate_quantiles=(cell.actual - 10.0)[:, None] + OFFSETS[None, :],
        )
        for cell in cells
    ]
    result = paired_bootstrap(shifted, metrics=("mae",), seed=5, replicates=200)
    assert result["mae"].delta == pytest.approx(0.0, abs=1e-9)
    assert result["mae"].ci_low == pytest.approx(0.0, abs=1e-9)
    assert result["mae"].ci_high == pytest.approx(0.0, abs=1e-9)


def test_an_empty_comparison_is_refused():
    with pytest.raises(ValueError, match="at least one evaluation cell"):
        paired_bootstrap([], seed=1, replicates=10)


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------


def _delta(
    metric: str,
    delta: float,
    *,
    low: float,
    high: float,
    lower_is_better: bool = True,
) -> BootstrapDelta:
    return BootstrapDelta(
        metric=metric,
        lower_is_better=lower_is_better,
        baseline=10.0,
        candidate=10.0 + delta,
        delta=delta,
        ci_low=low,
        ci_high=high,
        replicates=1000,
        seed=1,
        share_favouring_candidate=1.0,
    )


def _winning_deltas() -> dict[str, BootstrapDelta]:
    return {
        "mae": _delta("mae", -2.0, low=-3.0, high=-1.0),
        "mean_pinball": _delta("mean_pinball", -0.8, low=-1.2, high=-0.4),
        "spearman": _delta("spearman", 0.02, low=0.01, high=0.03, lower_is_better=False),
    }


def _healthy_positions() -> list[PositionalEvidence]:
    return [
        PositionalEvidence(
            position=position,
            baseline_mae=30.0,
            candidate_mae=28.0,
            baseline_spearman=0.60,
            candidate_spearman=0.62,
            candidate_coverage_p10_p90=0.80,
        )
        for position in ("QB", "RB", "TE", "WR")
    ]


def test_a_genuinely_better_candidate_passes_the_frozen_gate():
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=_winning_deltas(),
        positional=_healthy_positions(),
    )
    assert result.passed
    assert not result.failures
    assert any("point accuracy" in reason for reason in result.reasons)


def test_a_hidden_positional_collapse_fails_a_large_aggregate_win():
    positions = _healthy_positions()
    positions[0] = PositionalEvidence(
        position="QB",
        baseline_mae=30.0,
        candidate_mae=45.0,  # 50% worse, hidden behind three healthy positions
        baseline_spearman=0.60,
        candidate_spearman=0.58,
        candidate_coverage_p10_p90=0.79,
    )
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=_winning_deltas(),
        positional=positions,
    )
    assert not result.passed
    assert result.positional_collapse
    assert "QB" in result.positional_collapse[0]


def test_a_rank_collapse_at_one_position_also_fails():
    positions = _healthy_positions()
    positions[2] = PositionalEvidence(
        position="TE",
        baseline_mae=30.0,
        candidate_mae=29.5,
        baseline_spearman=0.60,
        candidate_spearman=0.50,
        candidate_coverage_p10_p90=0.80,
    )
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=_winning_deltas(),
        positional=positions,
    )
    assert not result.passed
    assert any("Spearman" in item for item in result.positional_collapse)


def test_a_position_with_absurd_interval_coverage_fails():
    positions = _healthy_positions()
    positions[1] = PositionalEvidence(
        position="RB",
        baseline_mae=30.0,
        candidate_mae=28.0,
        baseline_spearman=0.60,
        candidate_spearman=0.62,
        candidate_coverage_p10_p90=0.99,
    )
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=_winning_deltas(),
        positional=positions,
    )
    assert not result.passed
    assert any("coverage" in item for item in result.positional_collapse)


def test_an_improvement_whose_interval_includes_zero_does_not_pass():
    deltas = _winning_deltas()
    deltas["mae"] = _delta("mae", -0.4, low=-1.5, high=0.6)
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=deltas,
        positional=_healthy_positions(),
    )
    assert not result.passed
    assert any("includes zero" in failure for failure in result.failures)


def test_point_accuracy_alone_is_not_enough():
    deltas = _winning_deltas()
    deltas["mean_pinball"] = _delta("mean_pinball", 0.3, low=0.1, high=0.5)
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=deltas,
        positional=_healthy_positions(),
    )
    assert not result.passed
    assert any("probabilistic quality" in failure for failure in result.failures)


def test_a_material_rank_regression_fails_even_with_better_errors():
    deltas = _winning_deltas()
    deltas["spearman"] = _delta(
        "spearman",
        -0.05,
        low=-0.07,
        high=-0.03,
        lower_is_better=False,
    )
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=deltas,
        positional=_healthy_positions(),
    )
    assert not result.passed
    assert any("ranking" in failure for failure in result.failures)


def test_a_tiny_rank_regression_inside_the_declared_tolerance_is_allowed():
    deltas = _winning_deltas()
    deltas["spearman"] = _delta(
        "spearman",
        -PROMOTION_CRITERIA.max_rank_regression / 2,
        low=-0.02,
        high=0.01,
        lower_is_better=False,
    )
    result = evaluate_promotion_gate(
        model_id="Q1",
        window=str(WindowPolicy.W2),
        deltas=deltas,
        positional=_healthy_positions(),
    )
    assert result.passed


# --------------------------------------------------------------------------------------
# Window selection
# --------------------------------------------------------------------------------------


def test_w1_is_selected_only_when_it_wins_both_primary_metrics_decisively():
    decision = select_training_window(
        {
            "mae": _delta("mae", -1.0, low=-1.6, high=-0.4),
            "mean_pinball": _delta("mean_pinball", -0.5, low=-0.9, high=-0.1),
        },
    )
    assert decision.selected is WindowPolicy.W1
    assert decision.decisive


def test_w2_is_selected_when_it_wins_both_primary_metrics_decisively():
    decision = select_training_window(
        {
            "mae": _delta("mae", 1.0, low=0.4, high=1.6),
            "mean_pinball": _delta("mean_pinball", 0.5, low=0.1, high=0.9),
        },
    )
    assert decision.selected is WindowPolicy.W2
    assert decision.decisive


def test_mixed_evidence_falls_back_to_the_conservative_window():
    decision = select_training_window(
        {
            "mae": _delta("mae", -1.0, low=-1.6, high=-0.4),
            "mean_pinball": _delta("mean_pinball", 0.2, low=-0.3, high=0.7),
        },
    )
    assert decision.selected is WindowPolicy.W2
    assert not decision.decisive
    assert "conservative tie-break" in decision.rationale


def test_an_interval_that_includes_zero_is_not_a_decisive_window_win():
    decision = select_training_window(
        {
            "mae": _delta("mae", -0.2, low=-0.9, high=0.4),
            "mean_pinball": _delta("mean_pinball", -0.05, low=-0.4, high=0.3),
        },
    )
    assert decision.selected is WindowPolicy.W2
    assert not decision.decisive


def test_missing_window_deltas_fall_back_conservatively():
    decision = select_training_window({})
    assert decision.selected is WindowPolicy.W2
    assert not decision.decisive
