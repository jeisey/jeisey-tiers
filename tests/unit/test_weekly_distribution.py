"""``quantile_distribution_v1``: the arithmetic the evaluation scored and the page prints.

The golden vector under ``tests/fixtures/weekly/`` is the contract between the two
implementations: this file holds the Python half to it, and ``web/tests/startsit.test.ts``
holds the TypeScript half to the same bytes. A change to either side that moves a
probability fails one of the two.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ffdraft.weekly.distribution import (
    grid_from_quantiles,
    grids_from_matrix,
    knots,
    pairwise_matrix,
    prob_greater,
    prob_greater_grids,
    win_probability,
)
from ffdraft.weekly.frozen import PAIRWISE_GRID_POINTS, TAIL_RULE, WEEKLY_QUANTILE_LEVELS

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "weekly" / "distribution_golden.json"

STEADY = [7.07, 8.43, 10.88, 13.6, 16.32, 19.04, 20.67]
BOOM = [1.03, 2.32, 6.19, 12.9, 20.9, 29.03, 34.83]


def test_the_golden_vector_is_what_this_code_computes() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rule = golden["rule"]
    assert rule["levels"] == list(WEEKLY_QUANTILE_LEVELS)
    assert rule["tail_lower_factor"] == TAIL_RULE["lower_factor"]
    assert rule["tail_upper_factor"] == TAIL_RULE["upper_factor"]
    assert rule["grid_points"] == PAIRWISE_GRID_POINTS
    for name, sample in golden["grid_samples"].items():
        grid = grid_from_quantiles(golden["cases"][name])
        assert np.allclose(grid[[0, 9, 99, 100, 189, 199]], sample, atol=1e-9), name
    for row in golden["prob_greater"]:
        assert prob_greater(golden["cases"][row["a"]], golden["cases"][row["b"]]) == pytest.approx(
            row["p"],
            abs=1e-12,
        )
    for row in golden["win_probability"]:
        grid = grid_from_quantiles(golden["cases"][row["case"]])
        assert win_probability(grid, margin=row["margin"], sigma=row["sigma"]) == pytest.approx(
            row["p"],
            abs=1e-12,
        )


def test_tails_extend_the_adjacent_segment_once_below_and_twice_above() -> None:
    taus, values = knots(STEADY)
    assert taus[0] == 0.0 and taus[-1] == 1.0
    assert values[0] == pytest.approx(STEADY[0] - (STEADY[1] - STEADY[0]))
    assert values[-1] == pytest.approx(STEADY[-1] + 2 * (STEADY[-1] - STEADY[-2]))


def test_a_grid_is_ascending_and_centred_on_the_median() -> None:
    grid = grid_from_quantiles(BOOM)
    assert grid.shape == (PAIRWISE_GRID_POINTS,)
    assert np.all(np.diff(grid) >= 0)
    assert grid[99] <= BOOM[3] <= grid[100]


def test_crossed_quantiles_are_sorted_rather_than_trusted() -> None:
    crossed = [5.0, 4.0, 8.0, 10.0, 9.0, 14.0, 16.0]
    assert np.all(np.diff(grid_from_quantiles(crossed)) >= 0)


def test_head_to_head_is_complementary_and_identical_players_are_even() -> None:
    forward = prob_greater(STEADY, BOOM)
    backward = prob_greater(BOOM, STEADY)
    assert forward + backward == pytest.approx(1.0, abs=1e-12)
    assert prob_greater(STEADY, STEADY) == pytest.approx(0.5)


def test_a_shifted_distribution_is_favoured_by_the_shift() -> None:
    better = [value + 3.0 for value in STEADY]
    assert prob_greater(better, STEADY) > 0.6


def test_the_pool_matrix_agrees_with_the_pairwise_function() -> None:
    matrix = pairwise_matrix(grids_from_matrix(np.array([STEADY, BOOM, [q + 1 for q in STEADY]])))
    assert matrix[0, 1] == pytest.approx(prob_greater(STEADY, BOOM))
    assert matrix[2, 0] == pytest.approx(prob_greater([q + 1 for q in STEADY], STEADY))
    assert np.allclose(np.diag(matrix), 0.5)
    assert np.allclose(matrix + matrix.T, 1.0)


def test_ties_count_half() -> None:
    constant = np.full(PAIRWISE_GRID_POINTS, 4.0)
    assert prob_greater_grids(constant, constant) == pytest.approx(0.5)


def test_win_probability_rises_with_the_margin() -> None:
    grid = grid_from_quantiles(STEADY)
    values = [win_probability(grid, margin=m, sigma=30.0) for m in (-30, -10, 0, 10, 30)]
    assert values == sorted(values)
    assert 0.0 < values[0] < values[-1] < 1.0


def test_the_wide_player_is_the_better_start_when_trailing_and_the_steady_one_when_leading() -> (
    None
):
    """The reason the tab exists: the pick depends on the reader's matchup."""
    steady, boom = grid_from_quantiles(STEADY), grid_from_quantiles(BOOM)
    assert prob_greater(STEADY, BOOM) > 0.5
    behind = win_probability(boom, margin=-25, sigma=31.4) - win_probability(
        steady,
        margin=-25,
        sigma=31.4,
    )
    ahead = win_probability(steady, margin=25, sigma=31.4) - win_probability(
        boom,
        margin=25,
        sigma=31.4,
    )
    assert behind > 0
    assert ahead > 0


def test_sigma_must_be_positive() -> None:
    with pytest.raises(ValueError, match="sigma"):
        win_probability(grid_from_quantiles(STEADY), margin=0, sigma=0)


def test_the_wrong_number_of_quantiles_is_refused() -> None:
    with pytest.raises(ValueError, match="expected 7"):
        knots([1.0, 2.0, 3.0])
