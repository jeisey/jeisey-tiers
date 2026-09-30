"""The validator rules a schema cannot state, for the records ADR-096 and ADR-097 added.

Each test starts from the fixture pipeline's real output (which passes), breaks one thing,
and asserts the named check fires.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from ffdraft.artifacts.schemas import validate_records
from ffdraft.artifacts.validate import (
    _display_name_checks,
    _surfaced_rank_violations,
    _weekly_checks,
    _weekly_cross_checks,
)
from ffdraft.contracts.quality import critical_failures, failures


@pytest.fixture
def weekly(pipeline_result) -> list[dict[str, Any]]:
    return copy.deepcopy(pipeline_result.records["weekly_projections"])


@pytest.fixture
def opportunity(pipeline_result) -> list[dict[str, Any]]:
    return copy.deepcopy(pipeline_result.records["inseason_opportunity"])


def _failed(checks) -> set[str]:
    """The checks that would block a publish."""
    return {check.check_id for check in critical_failures(checks)}


def test_the_fixture_output_passes_every_weekly_rule(weekly, opportunity) -> None:
    assert not failures(validate_records("weekly_projection", weekly))
    assert _failed(_weekly_checks(weekly, "test")) == set()
    envelopes = {
        "weekly_projections": {"records": weekly},
        "inseason_opportunity": {"records": opportunity},
    }
    assert _failed(_weekly_cross_checks(envelopes)) == set()


def _playing(weekly: list[dict[str, Any]]) -> dict[str, Any]:
    return next(record for record in weekly if record["game_state"] != "bye")


def test_crossed_quantiles_fail(weekly) -> None:
    record = _playing(weekly)
    record["quantiles"]["q90"] = record["quantiles"]["q75"] - 1.0
    assert "weekly.quantiles_monotonic" in _failed(_weekly_checks(weekly, "test"))


def test_a_driver_account_that_does_not_close_fails(weekly) -> None:
    _playing(weekly)["drivers"]["opponent"] += 0.5
    assert "weekly.driver_account_closes" in _failed(_weekly_checks(weekly, "test"))


def test_a_bye_carrying_a_distribution_fails(weekly) -> None:
    bye = next(record for record in weekly if record["game_state"] == "bye")
    bye["quantiles"] = copy.deepcopy(_playing(weekly)["quantiles"])
    assert "weekly.record_shape" in _failed(_weekly_checks(weekly, "test"))


def test_a_projection_for_the_wrong_week_fails(weekly) -> None:
    _playing(weekly)["target_week"] += 1
    assert "weekly.record_shape" in _failed(_weekly_checks(weekly, "test"))


def test_a_projection_nobody_can_open_fails(weekly, opportunity) -> None:
    weekly[0]["player_id"] = "gsis:00-9999999"
    envelopes = {
        "weekly_projections": {"records": weekly},
        "inseason_opportunity": {"records": opportunity},
    }
    assert "cross_artifact.weekly_projection_unpublished" in _failed(
        _weekly_cross_checks(envelopes),
    )


@pytest.mark.parametrize("placeholder", ["None", "null", "NaN", "", "  "])
def test_a_placeholder_name_is_critical(placeholder: str) -> None:
    records = [
        {"player_id": "gsis:00-1", "display_name": "Real Name"},
        {"player_id": "gsis:00-2", "display_name": placeholder},
    ]
    checks = _display_name_checks(records, "test")
    assert "artifact.placeholder_display_name" in _failed(checks)


def test_an_id_as_name_is_a_warning_not_a_failure() -> None:
    checks = _display_name_checks([{"player_id": "gsis:00-1", "display_name": "gsis:00-1"}], "t")
    assert _failed(checks) == set()
    assert {check.check_id for check in failures(checks)} == {"artifact.id_as_display_name"}


def test_the_published_board_has_no_placeholder_name(pipeline_result) -> None:
    for artifact in ("ros_tiers", "inseason_opportunity", "weekly_projections"):
        assert _failed(_display_name_checks(pipeline_result.records[artifact], artifact)) == set()


def _surfaced_block() -> list[dict[str, Any]]:
    base = {"league_preset_id": "redraft-12", "scoring_preset": "PPR"}
    return [
        {
            **base,
            "player_id": "a",
            "position": "WR",
            "ros_fair_rank": 1,
            "ros_position_rank": 1,
            "ros_vorp_p50": 40.0,
            "outside_tier_board": False,
        },
        {
            **base,
            "player_id": "b",
            "position": "WR",
            "ros_fair_rank": 2,
            "ros_position_rank": 2,
            "ros_vorp_p50": -3.0,
            "outside_tier_board": False,
        },
        {
            **base,
            "player_id": "c",
            "position": "WR",
            "ros_fair_rank": 9,
            "ros_position_rank": 7,
            "ros_vorp_p50": -11.0,
            "outside_tier_board": True,
        },
    ]


def test_a_surfaced_row_with_the_models_values_passes() -> None:
    assert _surfaced_rank_violations(_surfaced_block()) == []


def test_the_pre_adr_096_invented_row_is_caught_three_ways() -> None:
    """Rank 1 at his position and 0.0 VORP: the defect as it shipped."""
    block = _surfaced_block()
    block[2].update({"ros_fair_rank": 2, "ros_position_rank": 1, "ros_vorp_p50": 0.0})
    violations = _surfaced_rank_violations(block)
    assert len(violations) == 3
    assert any("fair rank" in line for line in violations)
    assert any("WR1" in line for line in violations)
    assert any("median VORP" in line for line in violations)
