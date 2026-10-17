"""The ESPN validator checks, negative-controlled against the committed goldens (ADR-112).

Each test corrupts one fact in a copy of the golden ``espn_ownership`` artifacts and requires
the specific check to fire; the clean goldens must pass. A check that never fires against a
real mistake is decoration.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from ffdraft.artifacts.ownership_checks import (
    ownership_cross_checks,
    ownership_record_checks,
    ownership_series_checks,
)
from ffdraft.contracts.enums import CheckStatus

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "artifacts"
GENERATED = datetime.fromisoformat("2026-08-18T12:00:00+00:00")


@pytest.fixture(scope="module")
def envelopes():
    return {
        name: json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("espn_ownership", "espn_ownership_series", "inseason_opportunity")
    }


def _failed(checks) -> set[str]:
    return {check.check_id for check in checks if check.status is not CheckStatus.PASS}


def _measured(records):
    return next(r for r in records if r["rostered_change_7d"]["state"] == "measured")


def test_the_goldens_pass(envelopes):
    records = envelopes["espn_ownership"]["records"]
    series = envelopes["espn_ownership_series"]["records"]
    assert not _failed(ownership_record_checks(records, "s", generated_at=GENERATED))
    assert not _failed(ownership_series_checks(series, "s", generated_at=GENERATED))
    assert not _failed(ownership_cross_checks(envelopes))


def test_a_wrong_difference_fails(envelopes):
    records = copy.deepcopy(envelopes["espn_ownership"]["records"])
    _measured(records)["rostered_change_7d"]["change_pp"] += 1.0
    assert "espn_ownership.change_is_not_the_difference" in _failed(
        ownership_record_checks(records, "s", generated_at=GENERATED),
    )


def test_a_baseline_outside_its_window_fails(envelopes):
    records = copy.deepcopy(envelopes["espn_ownership"]["records"])
    _measured(records)["rostered_change_7d"]["span_hours"] = 200.0
    assert "espn_ownership.change_outside_its_window" in _failed(
        ownership_record_checks(records, "s", generated_at=GENERATED),
    )


def test_an_absent_reading_published_as_zero_fails(envelopes):
    records = copy.deepcopy(envelopes["espn_ownership"]["records"])
    absent = next(r for r in records if r["reading_state"] == "not_published")
    absent["percent_rostered"] = 0.0
    assert "espn_ownership.state_disagrees_with_values" in _failed(
        ownership_record_checks(records, "s", generated_at=GENERATED),
    )


def test_a_missing_start_share_published_as_zero_fails(envelopes):
    records = copy.deepcopy(envelopes["espn_ownership"]["records"])
    roster_only = next(r for r in records if r["start_state"] == "not_published")
    roster_only["percent_started"] = 0.0
    assert "espn_ownership.state_disagrees_with_values" in _failed(
        ownership_record_checks(records, "s", generated_at=GENERATED),
    )


def test_a_future_instant_fails(envelopes):
    records = copy.deepcopy(envelopes["espn_ownership"]["records"])
    next(r for r in records if r["reading_state"] == "observed")["observed_at_utc"] = (
        "2026-08-19T12:00:00Z"
    )
    assert "espn_ownership.instant_in_future" in _failed(
        ownership_record_checks(records, "s", generated_at=GENERATED),
    )


def test_a_series_out_of_order_or_duplicated_fails(envelopes):
    series = copy.deepcopy(envelopes["espn_ownership_series"]["records"])
    full = next(r for r in series if r["observations"] > 2)
    full["points"][1] = copy.deepcopy(full["points"][0])
    assert "espn_ownership_series.malformed" in _failed(
        ownership_series_checks(series, "s", generated_at=GENERATED),
    )


def test_a_series_ending_on_another_value_fails(envelopes):
    corrupted = copy.deepcopy(envelopes)
    record = corrupted["espn_ownership_series"]["records"][0]
    record["points"][-1]["percent_rostered"] = 77.7
    assert "cross_artifact.espn_series_disagrees_with_summary" in _failed(
        ownership_cross_checks(corrupted),
    )


def test_a_player_the_board_does_not_publish_fails(envelopes):
    corrupted = copy.deepcopy(envelopes)
    extra = copy.deepcopy(corrupted["espn_ownership"]["records"][0])
    extra["player_id"] = "gsis:00-9999999"
    corrupted["espn_ownership"]["records"].append(extra)
    assert "cross_artifact.espn_players_disagree_with_board" in _failed(
        ownership_cross_checks(corrupted),
    )
