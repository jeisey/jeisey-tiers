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

#: The 32 clubs. Named rather than counted, because membership is what the gate compares.
TEAMS = [
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LA",
    "LAC",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
]


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
                    "home_team": TEAMS[index * 2],
                    "away_team": TEAMS[index * 2 + 1],
                },
            )
    return pl.DataFrame(rows)


def _weekly(
    weeks: dict[int, int],
    *,
    season: int = 2026,
    teams: dict[int, list[str]] | None = None,
) -> pl.DataFrame:
    """Weekly player rows.

    ``weeks`` maps a week to how many clubs appear in it, taken from the front of the real
    club list so the observed set is a genuine subset of the scheduled one. ``teams`` names
    the clubs outright, which is how a week with the right *count* and the wrong membership
    is expressed.
    """
    rows: list[dict[str, object]] = []
    for week, count in weeks.items():
        present = (teams or {}).get(week, TEAMS[:count])
        for index, club in enumerate(present):
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "season_type": "REG",
                    "gsis_id": f"00-{week:02d}{index:03d}",
                    "team": club,
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


def test_the_opening_week_wait_is_a_product_state_rather_than_a_failure() -> None:
    """The window ADR-079 exists for, from the gate's side.

    The season has kicked off, at most one week has been played, and nflverse has not
    published it. No board can be built and none should be — but a *critical* here would fail
    the refresh, and a failed refresh stops the ordinary draft build deploying for as long as
    the wait lasts. It is a warning, so the pipeline stays green and publishes what it has.
    """
    state = _state("2026-09-13T12:00:00Z")
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly({}))
    assert not freshness.buildable
    assert freshness.awaiting_first_week
    checks = freshness.checks()
    assert [check.check_id for check in checks] == ["ros.awaiting_first_week"]
    assert not checks[0].blocking


def test_two_played_weeks_with_nothing_available_is_still_critical() -> None:
    """The other side of the same line: a cadence lasts days, an outage does not."""
    state = _state("2026-09-22T12:00:00Z")  # weeks 1 and 2 played
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly({}))
    assert state.completed_week == 2
    assert not freshness.buildable
    assert not freshness.awaiting_first_week
    checks = freshness.checks()
    assert [check.check_id for check in checks] == ["ros.no_complete_week"]
    assert checks[0].blocking


def test_the_right_team_count_with_the_wrong_teams_fails() -> None:
    """A count proves the totals match. This gate claims something stronger than that.

    Thirty-two clubs are present and one of them was not scheduled this week, which means one
    that *was* scheduled is missing. Every cumulative feature over this week would be short by
    that club's games, and nothing about the row count would look wrong.
    """
    state = _state("2026-09-15T12:00:00Z")
    swapped = [*TEAMS[:31], "SEA2"]
    freshness = assess_ros_freshness(
        state=state,
        weekly_stats=_weekly({1: 32}, teams={1: swapped}),
    )
    entry = freshness.week(1)
    assert entry is not None
    assert entry.observed_teams == entry.scheduled_teams == 32
    assert entry.missing_teams == ("WAS",)
    assert entry.unexpected_teams == ("SEA2",)
    assert not entry.data_complete
    assert not freshness.buildable


def test_a_relocated_club_s_alias_is_the_same_club() -> None:
    """Normalized on both sides, so a vocabulary difference is not read as an absence."""
    state = _state("2026-09-15T12:00:00Z")
    aliased = [*TEAMS[:16], "STL", *TEAMS[17:]]  # "LA" under its pre-2016 abbreviation
    freshness = assess_ros_freshness(
        state=state,
        weekly_stats=_weekly({1: 32}, teams={1: aliased}),
    )
    entry = freshness.week(1)
    assert entry is not None
    assert entry.missing_teams == ()
    assert freshness.buildable


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
