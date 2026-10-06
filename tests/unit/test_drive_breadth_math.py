"""The occupancy arithmetic behind drive breadth (ADR-103), checked against brute force.

The rarefaction expectation is a closed form; these tests make it earn its place by agreeing
with an exhaustive enumeration of every way to place K opportunities in N slots, and by
behaving as the definition says at the edges: no opportunities, one, saturation, and
permutations of the same drives.
"""

from __future__ import annotations

import itertools
import random

import pytest

from ffdraft.signals.breadth import (
    DISPLAY_MIN_APPEARANCES,
    GameBreadth,
    expected_reach,
    game_breadth,
    window_breadth,
)


def _brute_force(slots_per_drive: list[int], k: int) -> float:
    """Mean drives reached over every K-subset of the game's slots, enumerated."""
    owner = [drive for drive, n in enumerate(slots_per_drive) for _ in range(n)]
    reached = [
        len({owner[i] for i in chosen}) for chosen in itertools.combinations(range(len(owner)), k)
    ]
    return sum(reached) / len(reached)


@pytest.mark.parametrize(
    "slots",
    [
        [1],
        [3],
        [1, 1],
        [2, 1],
        [3, 1, 2],
        [4, 4, 4],
        [1, 2, 3, 4],
        [5, 1, 1, 1, 2],
        [2, 2, 2, 2, 2, 2],
    ],
)
def test_the_closed_form_equals_exhaustive_enumeration(slots: list[int]) -> None:
    for k in range(0, sum(slots) + 1):
        assert expected_reach(slots, k) == pytest.approx(_brute_force(slots, k), abs=1e-12)


def test_the_illustration_in_the_brief() -> None:
    """Ten drives of four targets, eight player targets: E ≈ 6.065 either way, share 20%."""
    slots = [4] * 10
    expected = expected_reach(slots, 8)
    assert expected == pytest.approx(6.065, abs=5e-4)
    spread = game_breadth(
        season=2024,
        week=1,
        slots_by_drive=dict(enumerate(slots)),
        opportunities_by_drive={d: 1 for d in range(8)},
    )
    clustered = game_breadth(
        season=2024,
        week=1,
        slots_by_drive=dict(enumerate(slots)),
        opportunities_by_drive={0: 4, 1: 3, 2: 1},
    )
    assert spread.opportunities == clustered.opportunities == 8
    assert round(100 * spread.gap / 10, 1) == 19.3
    assert round(100 * clustered.gap / 10, 1) == -30.7


def test_drive_order_does_not_matter() -> None:
    rng = random.Random(7)
    slots = [rng.randint(1, 9) for _ in range(12)]
    for k in (1, 5, 17, sum(slots)):
        base = expected_reach(slots, k)
        for _ in range(20):
            shuffled = slots[:]
            rng.shuffle(shuffled)
            assert expected_reach(shuffled, k) == pytest.approx(base, abs=1e-12)


def test_identical_totals_can_have_different_references() -> None:
    """Same N and K, different concentration of the team's slots: a different reference."""
    even = expected_reach([5, 5, 5, 5], 6)
    lumpy = expected_reach([17, 1, 1, 1], 6)
    assert sum([5, 5, 5, 5]) == sum([17, 1, 1, 1])
    assert even > lumpy


def test_edges_zero_one_and_saturation() -> None:
    assert expected_reach([3, 4, 5], 0) == 0.0
    # One opportunity reaches exactly one drive under any allocation: the gap is always zero.
    assert expected_reach([3, 4, 5], 1) == pytest.approx(1.0)
    # Every slot taken: every drive is reached, with certainty.
    assert expected_reach([3, 4, 5], 12) == pytest.approx(3.0)
    # Ten of eleven slots: the ten-slot drive cannot be missed (C(1, 10) = 0, an impossible
    # combination) and the one-slot drive is missed only by the single all-in-one draw.
    assert expected_reach([1, 10], 10) == pytest.approx(2 - 1 / 11)
    with pytest.raises(ValueError):
        expected_reach([1, 2], 4)
    with pytest.raises(ValueError):
        game_breadth(season=2024, week=1, slots_by_drive={1: 1}, opportunities_by_drive={1: 2})


def test_zero_slot_drives_are_not_drives() -> None:
    game = game_breadth(
        season=2024,
        week=3,
        slots_by_drive={1: 0, 2: 3, 3: 2},
        opportunities_by_drive={2: 1},
    )
    assert game.eligible_drives == 2
    assert game.expected_drives == pytest.approx(1.0)


def _game(week: int, drives: int, reached: int, expected: float, k: int) -> GameBreadth:
    return GameBreadth(2026, week, drives, drives * 3, k, reached, expected)


def test_the_window_is_the_latest_appearances_and_computes_per_game() -> None:
    games = [_game(w, 10, 4, 3.0, 5) for w in (1, 2, 3, 5, 6)]
    reading = window_breadth(games)
    assert (reading.first_week, reading.last_week, reading.appearances) == (2, 6, 4)
    assert reading.breadth_gap_pp == pytest.approx(100 * 4 * (4 - 3.0) / 40)
    assert reading.displayable


def test_minimums_withhold_rather_than_show_a_misleading_zero() -> None:
    assert (
        window_breadth([_game(1, 10, 2, 2.0, 2)] * (DISPLAY_MIN_APPEARANCES - 1)).withheld_reason
        == "too_few_appearances"
    )
    thin = window_breadth([_game(w, 5, 1, 1.0, 1) for w in (1, 2, 3)])
    assert thin.withheld_reason == "too_few_eligible_drives" and not thin.displayable
    quiet = window_breadth([_game(w, 10, 1, 1.0, 1) for w in (1, 2, 3)])
    assert quiet.withheld_reason == "too_few_opportunities"
    assert window_breadth([]).breadth_gap_pp is None
