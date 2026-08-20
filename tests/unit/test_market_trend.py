"""Market trend over our own retained snapshots (ADR-042).

The first production snapshot cannot produce a trend, and the correct output in that case
is ``null`` — not a one-day delta wearing a seven-day label. These tests drive synthetic
multi-day histories so the infrastructure is proved now and becomes informative on its own
as the store fills.
"""

from __future__ import annotations

import pytest

from ffdraft.market.snapshot import MarketSnapshot, SnapshotManifest
from ffdraft.market.trend import (
    INSUFFICIENT_TREND_HISTORY,
    TREND_RULE,
    TrendObservation,
    compute_trends,
    observations_from_snapshots,
)
from ffdraft.timeutil import isoformat_utc, parse_utc

NOW = parse_utc("2026-08-20T12:00:00Z")


def series(prices: list[float], *, days: list[int] | None = None, cohort: str = "ppr"):
    """One observation per named day of August 2026, oldest first."""
    offsets = days or list(range(14, 14 + len(prices)))
    return [
        TrendObservation(
            player_id="gsis:00-0000002",
            cohort_id=cohort,
            observed_at=parse_utc(f"2026-08-{day:02d}T12:00:00Z"),
            market_adp=price,
        )
        for day, price in zip(offsets, prices, strict=True)
    ]


# --------------------------------------------------------------------------------------
# Sufficiency
# --------------------------------------------------------------------------------------


def test_a_single_snapshot_yields_no_trend():
    """The first production snapshot. Null is the correct answer, and it says why."""
    results = compute_trends(series([30.0], days=[20]), now=NOW, cohort_id="ppr")
    result = results["gsis:00-0000002"]
    assert result.trend is None
    assert result.quality_flags == (INSUFFICIENT_TREND_HISTORY,)
    assert result.observation_days == 1


def test_two_days_are_not_enough_however_clean_the_line():
    results = compute_trends(series([30.0, 20.0], days=[19, 20]), now=NOW, cohort_id="ppr")
    assert results["gsis:00-0000002"].trend is None


def test_three_days_spanning_three_days_are_enough():
    results = compute_trends(
        series([30.0, 25.0, 20.0], days=[17, 18, 20]), now=NOW, cohort_id="ppr"
    )
    assert results["gsis:00-0000002"].trend is not None


def test_three_observations_inside_two_days_are_not_enough():
    """The window never silently shrinks: three points in 36 hours is not a 7-day trend."""
    observations = [
        TrendObservation("gsis:00-0000002", "ppr", parse_utc(stamp), price)
        for stamp, price in (
            ("2026-08-19T00:00:00Z", 30.0),
            ("2026-08-19T12:00:00Z", 27.0),
            ("2026-08-20T12:00:00Z", 24.0),
        )
    ]
    result = compute_trends(observations, now=NOW, cohort_id="ppr")["gsis:00-0000002"]
    assert result.observation_days == 2
    assert result.trend is None


# --------------------------------------------------------------------------------------
# Sign convention and magnitude
# --------------------------------------------------------------------------------------


def test_a_player_being_taken_earlier_trends_positive():
    """ADR-042: positive = moving earlier = getting more expensive, like `rank_gap`."""
    results = compute_trends(series([40.0, 35.0, 30.0, 25.0]), now=NOW, cohort_id="ppr")
    trend = results["gsis:00-0000002"].trend
    assert trend is not None and trend > 0
    assert trend == pytest.approx(5.0)


def test_a_player_falling_down_boards_trends_negative():
    results = compute_trends(series([25.0, 30.0, 35.0, 40.0]), now=NOW, cohort_id="ppr")
    trend = results["gsis:00-0000002"].trend
    assert trend is not None and trend < 0
    assert trend == pytest.approx(-5.0)


def test_a_flat_price_trends_zero():
    results = compute_trends(series([30.0, 30.0, 30.0, 30.0]), now=NOW, cohort_id="ppr")
    assert results["gsis:00-0000002"].trend == pytest.approx(0.0)


def test_the_slope_is_per_day_not_per_observation():
    """Same three observations and the same total move, spread over more days: less slope.

    A slope measured per observation would report the same number for both, which would
    make a fast riser and a slow drifter indistinguishable.
    """
    tight = compute_trends(series([40.0, 30.0, 20.0], days=[17, 18, 20]), now=NOW, cohort_id="ppr")[
        "gsis:00-0000002"
    ]
    spread = compute_trends(
        series([40.0, 30.0, 20.0], days=[13, 17, 20]), now=NOW, cohort_id="ppr"
    )["gsis:00-0000002"]
    assert tight.trend == pytest.approx(6.4286, abs=1e-3)
    assert spread.trend == pytest.approx(2.8378, abs=1e-3)
    assert tight.trend > spread.trend


# --------------------------------------------------------------------------------------
# Window, cohorts, and irregular input
# --------------------------------------------------------------------------------------


def test_observations_outside_the_window_are_excluded():
    old = series([90.0, 88.0], days=[1, 2])
    recent = series([30.0, 25.0, 20.0], days=[17, 18, 20])
    results = compute_trends(old + recent, now=NOW, cohort_id="ppr")
    result = results["gsis:00-0000002"]
    assert result.observations == 3
    assert result.trend == pytest.approx(3.2143, abs=1e-3)


def test_cohorts_are_never_mixed():
    """A cohort change changes the population priced; combining them fakes movement."""
    ppr = series([30.0, 28.0, 26.0], days=[17, 18, 20], cohort="ppr")
    std = series([90.0, 92.0, 94.0], days=[17, 18, 20], cohort="std")
    results = compute_trends(ppr + std, now=NOW, cohort_id="ppr")
    assert results["gsis:00-0000002"].observations == 3
    assert results["gsis:00-0000002"].trend == pytest.approx(1.2857, abs=1e-3)


def test_several_snapshots_in_one_day_count_as_observations_but_one_day():
    observations = [
        TrendObservation("gsis:00-0000002", "ppr", parse_utc(stamp), price)
        for stamp, price in (
            ("2026-08-17T06:00:00Z", 32.0),
            ("2026-08-17T18:00:00Z", 31.0),
            ("2026-08-18T12:00:00Z", 28.0),
            ("2026-08-20T12:00:00Z", 24.0),
        )
    ]
    result = compute_trends(observations, now=NOW, cohort_id="ppr")["gsis:00-0000002"]
    assert result.observations == 4
    assert result.observation_days == 3
    assert result.trend is not None


def test_irregular_spacing_is_handled_by_using_elapsed_time_not_position():
    even = compute_trends(series([40.0, 35.0, 30.0], days=[18, 19, 20]), now=NOW, cohort_id="ppr")
    uneven = compute_trends(series([40.0, 35.0, 30.0], days=[14, 19, 20]), now=NOW, cohort_id="ppr")
    assert even["gsis:00-0000002"].trend != uneven["gsis:00-0000002"].trend


def test_the_result_is_deterministic_under_input_permutation():
    observations = series([40.0, 35.0, 32.0, 30.0])
    forward = compute_trends(observations, now=NOW, cohort_id="ppr")
    backward = compute_trends(list(reversed(observations)), now=NOW, cohort_id="ppr")
    assert forward["gsis:00-0000002"].trend == backward["gsis:00-0000002"].trend


def test_the_rule_declares_its_own_semantics():
    rule = TREND_RULE.to_dict()
    assert rule["rule_version"] == "phase5_trend_v1"
    assert rule["window_days"] == 7.0
    assert rule["min_observation_days"] == 3
    assert "positive = moving earlier" in rule["sign_convention"]


# --------------------------------------------------------------------------------------
# Reading observations out of retained snapshots
# --------------------------------------------------------------------------------------


def _snapshot(stamp: str, rows: list[dict[str, object]]) -> MarketSnapshot:
    moment = parse_utc(stamp)
    return MarketSnapshot(
        manifest=SnapshotManifest(
            manifest_version="1.0",
            source_id="myfantasyleague_adp",
            season=2026,
            snapshot_key=stamp.replace(":", "-"),
            retrieved_at_utc=isoformat_utc(moment),
            adapter_version="2.0",
            source_policy_version="mfl-developer-rules/2026-08-17",
        ),
        rows=tuple(rows),
    )


def test_observations_come_from_retained_rows_keyed_by_canonical_id():
    snapshots = [
        _snapshot(
            f"2026-08-{day:02d}T12:00:00Z",
            [
                {"cohort_id": "ppr", "player_id": "gsis:00-0000002", "average_pick": price},
                {"cohort_id": "std", "player_id": "gsis:00-0000002", "average_pick": 99.0},
                # Unresolved rows have no board position to move against, so they are
                # skipped rather than keyed by a crosswalk that could change.
                {"cohort_id": "ppr", "player_id": None, "average_pick": 44.0},
            ],
        )
        for day, price in ((17, 30.0), (18, 28.0), (20, 24.0))
    ]
    observations = observations_from_snapshots(snapshots, cohort_id="ppr")
    assert len(observations) == 3
    assert {item.player_id for item in observations} == {"gsis:00-0000002"}
    result = compute_trends(observations, now=NOW, cohort_id="ppr")["gsis:00-0000002"]
    assert result.trend is not None and result.trend > 0
