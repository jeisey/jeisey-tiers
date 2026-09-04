"""The weekly source-freshness gate.

`ros_cutoff_v1` says a snapshot through week N may read weeks 1..N — and the operational
half of that sentence is "week N is *available*", not "week N has been played". Phase 11
documented it; these tests are the enforcement.

The case that matters most is the quiet one: the games are over, nflverse has not published
yet, and a build that trusted the clock would produce a week-N board from week-(N-1) data and
label it week N. Nothing would look broken and every number would be wrong by a week.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from ffdraft.ros.freshness import assess_ros_freshness
from ffdraft.season.state import build_season_calendar, resolve_season_state


def _schedule(weeks: int = 18) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = datetime(2026, 9, 10, tzinfo=UTC).date()
    for week in range(1, weeks + 1):
        thursday = start.fromordinal(start.toordinal() + (week - 1) * 7)
        for index in range(16):
            day = thursday.fromordinal(thursday.toordinal() + (0 if index == 0 else 3))
            rows.append(
                {
                    "game_id": f"2026_{week:02d}_G{index:02d}",
                    "season": 2026,
                    "game_type": "REG",
                    "week": week,
                    "gameday": day.isoformat(),
                    "gametime": "13:00",
                },
            )
    return pl.DataFrame(rows)


def _weekly(weeks: dict[int, int], *, season: int = 2026) -> pl.DataFrame:
    """Weekly player rows, ``weeks`` mapping a week to how many clubs appear in it."""
    rows: list[dict[str, object]] = []
    for week, teams in weeks.items():
        for team in range(teams):
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "season_type": "REG",
                    "gsis_id": f"00-{week:02d}{team:03d}",
                    "team": f"T{team:02d}",
                },
            )
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def _state(as_of: str) -> object:
    calendar = build_season_calendar(_schedule(), 2026)
    return resolve_season_state(calendar, datetime.fromisoformat(as_of.replace("Z", "+00:00")))


def test_a_complete_week_is_available_and_the_cutoff_follows_it() -> None:
    state = _state("2026-09-22T12:00:00Z")  # weeks 1 and 2 played
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly({1: 32, 2: 32}))
    assert freshness.available_through_week == state.completed_week
    assert freshness.buildable
    assert freshness.blocking_week is None
    assert [check.check_id for check in freshness.checks()] == ["ros.source_freshness"]


def test_played_but_unpublished_stops_the_cutoff_at_the_last_complete_week() -> None:
    """The failure this module exists for. The clock says two weeks; the data says one."""
    state = _state("2026-09-22T12:00:00Z")
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly({1: 32, 2: 0}))
    assert state.completed_week == 2
    assert freshness.available_through_week == 1
    assert freshness.blocking_week == 2
    ids = [check.check_id for check in freshness.checks()]
    assert "ros.upstream_week_incomplete" in ids
    # A warning, not a critical: building at week 1 is correct, it is merely shallower.
    blocked = next(c for c in freshness.checks() if c.check_id == "ros.upstream_week_incomplete")
    assert not blocked.blocking


def test_a_partially_released_week_is_not_a_complete_week() -> None:
    """One late game is exactly the shape that produces a plausible, wrong board."""
    state = _state("2026-09-22T12:00:00Z")
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly({1: 32, 2: 30}))
    assert freshness.available_through_week == 1
    entry = freshness.week(2)
    assert entry is not None
    assert entry.games_complete
    assert not entry.data_complete
    assert entry.teams_missing == 2


def test_a_hole_in_the_middle_stops_the_cutoff_behind_it() -> None:
    """A missing interior week is not a gap in the output; it is a smaller cumulative total."""
    state = _state("2026-10-13T12:00:00Z")
    freshness = assess_ros_freshness(
        state=state,
        weekly_stats=_weekly({1: 32, 2: 32, 3: 32, 4: 0, 5: 32}),
    )
    assert freshness.available_through_week == 3
    assert freshness.blocking_week == 4


def test_no_complete_week_is_critical_because_week_zero_is_refused() -> None:
    state = _state("2026-09-13T12:00:00Z")
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly({}))
    assert not freshness.buildable
    checks = freshness.checks()
    assert [check.check_id for check in checks] == ["ros.no_complete_week"]
    assert checks[0].blocking


def test_postseason_rows_never_satisfy_a_regular_season_week() -> None:
    state = _state("2026-09-15T12:00:00Z")
    postseason = _weekly({1: 32}).with_columns(pl.lit("POST").alias("season_type"))
    freshness = assess_ros_freshness(state=state, weekly_stats=postseason)
    assert not freshness.buildable


def test_another_season_s_rows_never_satisfy_this_season_s_week() -> None:
    state = _state("2026-09-15T12:00:00Z")
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly({1: 32}, season=2025))
    assert not freshness.buildable


def test_the_verdict_serializes_the_evidence_that_produced_it() -> None:
    state = _state("2026-09-22T12:00:00Z")
    payload = assess_ros_freshness(
        state=state,
        weekly_stats=_weekly({1: 32, 2: 20}),
    ).to_dict()
    assert payload["rule_version"] == "ros_source_freshness_v1"
    assert payload["available_through_week"] == 1
    assert payload["blocking_week"] == 2
    week_two = next(entry for entry in payload["weeks"] if entry["week"] == 2)
    assert week_two["observed_teams"] == 20
    assert week_two["scheduled_teams"] == 32
