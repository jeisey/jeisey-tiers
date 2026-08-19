"""Temporal-availability guards.

Phase 2 owns feature engineering and its full leakage suite. What Phase 1 owes is the
*structural* guarantee those tests will rest on: a depth observation must carry an honest
statement of when it was available, and the pre-2025 era must be incapable of claiming a
point-in-time reading it never had (ADR-015, ADR-018).

Getting this wrong is invisible in metrics - a model trained on week-1 depth simply looks
good - so the invariant is enforced in the type, not in a convention.
"""

from __future__ import annotations

import pytest

from ffdraft.contracts import DepthChartEra, DepthChartObservation
from ffdraft.sources import NflverseDepthChartAdapter
from ffdraft.sources.nflverse import normalized_depth_is_anchor_safe
from ffdraft.timeutil import parse_utc

ANCHOR = parse_utc("2026-08-25T12:00:00Z")


def test_a_weekly_era_observation_cannot_carry_a_timestamp():
    """Inventing a timestamp for a week-indexed row would fabricate availability."""
    with pytest.raises(ValueError, match="weekly-era rows carry a week"):
        DepthChartObservation(
            source_id="nflreadpy",
            season=2024,
            era=DepthChartEra.WEEKLY_PRE_2025,
            team="ATL",
            observed_at_utc=parse_utc("2024-08-20T00:00:00Z"),
        )


def test_a_snapshot_era_observation_requires_a_timestamp():
    with pytest.raises(ValueError, match="without a timestamp"):
        DepthChartObservation(
            source_id="nflreadpy",
            season=2026,
            era=DepthChartEra.SNAPSHOT_2025_PLUS,
            team="ATL",
        )


def test_only_the_snapshot_era_is_anchor_available():
    weekly = DepthChartObservation(
        source_id="nflreadpy",
        season=2024,
        era=DepthChartEra.WEEKLY_PRE_2025,
        team="ATL",
        week=1,
    )
    snapshot = DepthChartObservation(
        source_id="nflreadpy",
        season=2026,
        era=DepthChartEra.SNAPSHOT_2025_PLUS,
        team="ATL",
        observed_at_utc=parse_utc("2026-08-18T07:32:09Z"),
    )
    assert weekly.available_at_anchor is False
    assert snapshot.available_at_anchor is True


@pytest.mark.parametrize(
    ("season", "expected"),
    [(2019, False), (2024, False), (2025, True), (2026, True)],
)
def test_the_era_boundary_is_2025(season, expected):
    assert DepthChartEra.for_season(season).supports_point_in_time_anchor is expected


def test_no_pre_2025_depth_row_is_anchor_safe(fixture_inputs):
    """The ADR-018 rule, on a real normalized frame rather than a single object."""
    weekly = NflverseDepthChartAdapter(season=2024).normalize(fixture_inputs.depth_weekly)
    assert weekly.frame.height > 0
    assert normalized_depth_is_anchor_safe(weekly.frame, ANCHOR) is False


def test_a_snapshot_before_the_anchor_is_anchor_safe(fixture_inputs):
    snapshot = NflverseDepthChartAdapter(season=2026).normalize(fixture_inputs.depth_snapshot)
    assert normalized_depth_is_anchor_safe(snapshot.frame, ANCHOR) is True


def test_a_snapshot_after_the_anchor_is_not_anchor_safe(fixture_inputs):
    snapshot = NflverseDepthChartAdapter(season=2026).normalize(fixture_inputs.depth_snapshot)
    earlier_anchor = parse_utc("2026-08-01T00:00:00Z")
    assert normalized_depth_is_anchor_safe(snapshot.frame, earlier_anchor) is False


def test_an_empty_frame_is_vacuously_safe():
    from ffdraft.contracts import DEPTH_CHART_CONTRACT

    assert normalized_depth_is_anchor_safe(DEPTH_CHART_CONTRACT.empty(), ANCHOR) is True
