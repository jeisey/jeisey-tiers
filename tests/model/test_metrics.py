"""Metric correctness, on hand-worked examples first and an independent implementation second.

Every number in the Phase-3 report is one of these functions applied to a slice, so a subtle
tie-handling or denominator error here would silently corrupt the whole comparison. The
hand-worked cases pin the definitions; the SciPy cross-checks catch anything the hand-worked
cases are too small to expose.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ffdraft.modeling.metrics import (
    QUANTILE_LEVELS,
    average_ranks,
    coverage,
    crossing_magnitude,
    crossing_rate,
    kendall_tau_b,
    mae,
    mean_pinball,
    pinball,
    rmse,
    slice_metrics,
    spearman,
    top_k_recall,
)

# --------------------------------------------------------------------------------------
# Point accuracy
# --------------------------------------------------------------------------------------


def test_mae_and_rmse_on_a_hand_worked_example():
    actual = [10.0, 20.0, 30.0]
    predicted = [12.0, 18.0, 36.0]
    # errors 2, 2, 6 -> mean 10/3; squares 4, 4, 36 -> mean 44/3
    assert mae(actual, predicted) == pytest.approx(10.0 / 3.0)
    assert rmse(actual, predicted) == pytest.approx(math.sqrt(44.0 / 3.0))


def test_a_perfect_prediction_has_zero_error():
    values = [1.0, 5.0, 9.0]
    assert mae(values, values) == 0.0
    assert rmse(values, values) == 0.0


# --------------------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------------------


def test_average_ranks_share_the_rank_of_a_tie():
    assert average_ranks([10.0, 20.0, 20.0, 40.0]).tolist() == [1.0, 2.5, 2.5, 4.0]


def test_spearman_is_one_for_any_monotone_transform():
    actual = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert spearman(actual, [1.0, 4.0, 9.0, 16.0, 25.0]) == pytest.approx(1.0)
    assert spearman(actual, [-1.0, -4.0, -9.0, -16.0, -25.0]) == pytest.approx(-1.0)


def test_spearman_on_a_hand_worked_example_with_one_swap():
    # ranks 1,2,3,4 against 1,2,4,3: sum d^2 = 2, rho = 1 - 6*2/(4*15) = 0.8
    assert spearman([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 40.0, 30.0]) == pytest.approx(0.8)


def test_a_constant_prediction_has_no_rank_information():
    assert math.isnan(spearman([1.0, 2.0, 3.0], [5.0, 5.0, 5.0]))


def test_kendall_tau_b_on_a_hand_worked_example():
    # one discordant pair out of six: (6 concordant - ... ) -> 4/6
    actual = [1.0, 2.0, 3.0, 4.0]
    predicted = [1.0, 2.0, 4.0, 3.0]
    assert kendall_tau_b(actual, predicted) == pytest.approx((5 - 1) / 6)


def test_kendall_tau_b_corrects_for_ties():
    # x has one tied pair, so the denominator is sqrt(5 * 6) rather than 6
    actual = [1.0, 1.0, 2.0, 3.0]
    predicted = [1.0, 2.0, 3.0, 4.0]
    expected = 5.0 / math.sqrt(5.0 * 6.0)
    assert kendall_tau_b(actual, predicted) == pytest.approx(expected)


def test_rank_statistics_match_an_independent_implementation():
    scipy_stats = pytest.importorskip("scipy.stats")
    generator = np.random.default_rng(3)
    for _ in range(5):
        actual = np.round(generator.normal(size=60), 1)  # rounding forces ties
        predicted = np.round(generator.normal(size=60), 1)
        assert spearman(actual, predicted) == pytest.approx(
            float(scipy_stats.spearmanr(actual, predicted).statistic),
        )
        assert kendall_tau_b(actual, predicted) == pytest.approx(
            float(scipy_stats.kendalltau(actual, predicted, variant="b").statistic),
        )


def test_top_k_recall_counts_the_overlap_of_the_two_top_ks():
    actual = [100.0, 90.0, 80.0, 10.0, 5.0]
    predicted = [90.0, 100.0, 1.0, 80.0, 2.0]  # top-3 predicted: rows 0, 1, 3
    assert top_k_recall(actual, predicted, 3) == pytest.approx(2.0 / 3.0)
    assert top_k_recall(actual, actual, 3) == 1.0


# --------------------------------------------------------------------------------------
# Probabilistic
# --------------------------------------------------------------------------------------


def test_pinball_loss_penalizes_the_two_sides_asymmetrically():
    # at the 0.9 quantile, under-predicting by 10 costs 9 and over-predicting by 10 costs 1
    assert pinball([100.0], [90.0], 0.9) == pytest.approx(9.0)
    assert pinball([100.0], [110.0], 0.9) == pytest.approx(1.0)
    # the median quantile is half the absolute error
    assert pinball([100.0], [90.0], 0.5) == pytest.approx(5.0)


def test_mean_pinball_averages_the_declared_levels():
    actual = np.array([100.0])
    quantiles = np.array([[80.0, 90.0, 100.0, 110.0, 120.0]])
    expected = float(
        np.mean(
            [
                pinball(actual, quantiles[:, index], level)
                for index, level in enumerate(QUANTILE_LEVELS)
            ],
        ),
    )
    assert mean_pinball(actual, quantiles) == pytest.approx(expected)


def test_mean_pinball_rejects_a_mismatched_matrix():
    with pytest.raises(ValueError, match="does not match"):
        mean_pinball([1.0, 2.0], np.zeros((2, 3)))


def test_coverage_is_the_share_inside_a_closed_interval():
    actual = [1.0, 5.0, 10.0, 20.0]
    lower = [0.0, 6.0, 10.0, 0.0]
    upper = [2.0, 8.0, 12.0, 15.0]
    assert coverage(actual, lower, upper) == pytest.approx(0.5)  # rows 0 and 2


def test_crossing_diagnostics_report_rate_and_magnitude_separately():
    quantiles = np.array(
        [
            [1.0, 2.0, 3.0, 4.0, 5.0],  # clean
            [1.0, 2.0, 1.5, 4.0, 5.0],  # one crossing of 0.5
            [5.0, 4.0, 3.0, 2.0, 1.0],  # fully reversed
        ],
    )
    assert crossing_rate(quantiles) == pytest.approx(2.0 / 3.0)
    assert crossing_magnitude(quantiles) == pytest.approx((0.0 + 0.5 + 4.0) / 3.0)


def test_slice_metrics_reports_every_declared_metric():
    generator = np.random.default_rng(5)
    actual = generator.normal(100.0, 30.0, size=50)
    point = actual + generator.normal(0.0, 10.0, size=50)
    offsets = np.array([-40.0, -20.0, 0.0, 20.0, 40.0])
    quantiles = point[:, None] + offsets[None, :]
    metrics = slice_metrics(actual, point, quantiles, position="RB")
    for key in (
        "n",
        "mae",
        "rmse",
        "spearman",
        "kendall_tau_b",
        "top_k_recall",
        "mean_pinball",
        "coverage_p10_p90",
        "coverage_p25_p75",
        "mean_width_p10_p90",
        "crossing_rate_raw",
        "crossing_magnitude_raw",
    ):
        assert key in metrics
    assert metrics["n"] == 50
    assert metrics["crossing_rate_raw"] == 0.0
    assert metrics["mean_width_p10_p90"] == pytest.approx(80.0)
    assert 0.0 <= metrics["coverage_p10_p90"] <= 1.0
