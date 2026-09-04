"""The rest-of-season replacement interpretation and its frozen selection rule."""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.config import LeaguePreset
from ffdraft.ros.value import (
    REPLACEMENT_SELECTION,
    ROS_PUBLIC_COLUMNS,
    RosReplacementRule,
    allocate_with_bench,
    decide_replacement,
    to_public_names,
)
from ffdraft.simulation.allocation import PlayerPoints, allocate_starters


@pytest.fixture()
def tiny_preset() -> LeaguePreset:
    """Four teams, one starter per position, one bench place each: sixteen starters, four benches."""
    return LeaguePreset(
        preset_id="test-4",
        teams=4,
        starters={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "FLEX": 0},
        flex_eligible=("RB", "WR", "TE"),
        bench=1,
    )


#: Hand-built so every baseline below is arithmetic rather than a fixture's accident. Each
#: position's fifth player sits exactly at the fresh-allocation baseline, so his surplus is
#: zero and every player behind him is negative.
_POINTS = {
    "QB": [300.0, 290.0, 280.0, 270.0, 260.0, 250.0, 240.0, 230.0],
    "RB": [200.0, 190.0, 180.0, 170.0, 120.0, 110.0, 100.0, 90.0],
    "WR": [180.0, 175.0, 170.0, 165.0, 100.0, 95.0, 90.0, 85.0],
    "TE": [150.0, 140.0, 130.0, 120.0, 60.0, 50.0, 40.0, 30.0],
}


def _pool() -> list[PlayerPoints]:
    return [
        PlayerPoints(player_id=f"{position}{index}", position=position, points=points)
        for position, points_list in _POINTS.items()
        for index, points in enumerate(points_list)
    ]


def test_the_two_rules_agree_on_who_starts(tiny_preset) -> None:
    fresh = allocate_starters(_pool(), tiny_preset)
    rostered = allocate_with_bench(_pool(), tiny_preset)
    assert fresh.positional_starters == rostered.positional_starters
    assert fresh.flex_starters == rostered.flex_starters
    assert fresh.unfilled_slots == rostered.unfilled_slots


def test_the_fresh_rule_takes_the_best_unstarted_player(tiny_preset) -> None:
    fresh = allocate_starters(_pool(), tiny_preset)
    assert fresh.replacement_points == {"QB": 260.0, "RB": 120.0, "WR": 100.0, "TE": 60.0}


def test_the_in_season_rule_takes_the_best_unrostered_player(tiny_preset) -> None:
    """Two bench places go to the largest surpluses, and replacement moves down behind them.

    Surplus, not points: quarterbacks score the most and would take every bench place under a
    points-greedy fill, which is exactly the artefact the rule is written to avoid. Here the
    four largest surpluses are one per position - each position's fifth player, at surplus
    zero - so the bench spreads across the board and every baseline moves down exactly one.
    """
    rostered = allocate_with_bench(_pool(), tiny_preset)
    assert rostered.replacement_points == {"QB": 250.0, "RB": 110.0, "WR": 95.0, "TE": 50.0}
    assert rostered.replacement_player_id["QB"] == "QB5"


def test_the_in_season_replacement_is_never_better_than_the_fresh_one(tiny_preset) -> None:
    fresh = allocate_starters(_pool(), tiny_preset)
    rostered = allocate_with_bench(_pool(), tiny_preset)
    for position, baseline in fresh.replacement_points.items():
        other = rostered.replacement_points[position]
        if baseline is None or other is None:
            continue
        assert other <= baseline


def test_an_exhausted_position_reports_no_replacement(tiny_preset) -> None:
    pool = [
        PlayerPoints(player_id=f"QB{index}", position="QB", points=300.0 - index)
        for index in range(4)
    ]
    assert allocate_with_bench(pool, tiny_preset).replacement_points["QB"] is None


def test_the_selection_rule_keeps_release_one_when_the_boards_agree() -> None:
    rows = [
        {
            "fair_rank_spearman": 0.9999,
            "mean_abs_rank_change_top_150": 0.2,
            "top_50_overlap": 1.0,
        },
    ]
    decision = decide_replacement(rows)
    assert decision.selected == RosReplacementRule.FRESH_ALLOCATION.value
    assert decision.decisive


def test_the_selection_rule_uses_the_in_season_meaning_when_the_boards_differ() -> None:
    rows = [
        {
            "fair_rank_spearman": 0.98,
            "mean_abs_rank_change_top_150": 4.0,
            "top_50_overlap": 0.90,
        },
    ]
    decision = decide_replacement(rows)
    assert decision.selected == RosReplacementRule.ROSTERED_DEPTH.value
    assert decision.decisive


def test_one_disagreeing_scenario_is_enough_to_move_the_decision() -> None:
    rows = [
        {
            "fair_rank_spearman": 0.9999,
            "mean_abs_rank_change_top_150": 0.1,
            "top_50_overlap": 1.0,
        },
        {
            "fair_rank_spearman": 0.9999,
            "mean_abs_rank_change_top_150": 0.1,
            "top_50_overlap": 0.90,
        },
    ]
    assert decide_replacement(rows).selected == RosReplacementRule.ROSTERED_DEPTH.value


def test_no_measurement_is_not_a_decision() -> None:
    decision = decide_replacement([])
    assert not decision.decisive
    assert decision.failures


def test_the_criteria_serialize_with_their_version() -> None:
    payload = REPLACEMENT_SELECTION.to_dict()
    assert payload["criteria_version"] == "ros_replacement_v1"
    assert payload["default_rule"] == RosReplacementRule.ROSTERED_DEPTH.value


def test_public_names_never_collide_with_the_preseason_vocabulary() -> None:
    frame = pl.DataFrame(
        {
            "player_id": ["a"],
            "fair_rank": [1],
            "expected_vorp": [10.0],
            "p50_vorp": [9.0],
        },
    )
    renamed = to_public_names(frame)
    assert "fair_rank" not in renamed.columns
    assert renamed.columns == ["player_id", "ros_fair_rank", "ros_expected_vorp", "ros_vorp_p50"]
    assert all(name.startswith("ros_") for name in ROS_PUBLIC_COLUMNS.values())


def test_renaming_is_a_no_op_for_columns_that_are_not_there() -> None:
    frame = pl.DataFrame({"player_id": ["a"], "something_else": [1]})
    assert to_public_names(frame).columns == ["player_id", "something_else"]
