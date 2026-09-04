"""The season-state rule: derived from the schedule, never from a date in the code.

The Week-1 transition is the fixture the roadmap asks for by name (12.1 exit criterion), and
these tests are deliberately written against a *synthetic* schedule rather than the real one:
a test that passed only because the 2026 opener happens to be a Wednesday would prove nothing
about 2027.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from ffdraft.anchors import AnchorError
from ffdraft.season.state import (
    GAME_COMPLETE_BUFFER_HOURS,
    ProductMode,
    SeasonState,
    build_season_calendar,
    resolve_season_state,
    season_state_from_schedule,
)


def _schedule(season: int = 2026, weeks: int = 18) -> pl.DataFrame:
    """A synthetic schedule: sixteen games a week, Thursday through Monday."""
    rows: list[dict[str, object]] = []
    # 2026-09-10 is a Thursday. Every week starts there and steps by seven days.
    start = datetime(2026, 9, 10, tzinfo=UTC).date()
    for week in range(1, weeks + 1):
        thursday = start.fromordinal(start.toordinal() + (week - 1) * 7)
        for index in range(16):
            # One Thursday night game, fourteen on the Sunday, one on the Monday.
            offset, time = (0, "20:15") if index == 0 else (3, "13:00")
            if index == 15:
                offset, time = 4, "20:15"
            day = thursday.fromordinal(thursday.toordinal() + offset)
            rows.append(
                {
                    "game_id": f"{season}_{week:02d}_G{index:02d}",
                    "season": season,
                    "game_type": "REG",
                    "week": week,
                    "gameday": day.isoformat(),
                    "gametime": time,
                },
            )
    # A postseason row, which must never be counted as a regular-season week.
    rows.append(
        {
            "game_id": f"{season}_19_POST",
            "season": season,
            "game_type": "POST",
            "week": 19,
            "gameday": "2027-01-10",
            "gametime": "13:00",
        },
    )
    return pl.DataFrame(rows)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_the_calendar_covers_the_regular_season_only() -> None:
    calendar = build_season_calendar(_schedule(), 2026)
    assert len(calendar.weeks) == 18
    assert calendar.weeks[0].week == 1
    assert calendar.weeks[0].games == 16
    # NFL week 18 exists on the schedule and is outside every label this project produces.
    assert calendar.horizon.last_week == 17


def test_the_mode_flips_at_the_first_kickoff_and_not_before() -> None:
    calendar = build_season_calendar(_schedule(), 2026)
    kickoff = calendar.first_kickoff_utc

    before = resolve_season_state(calendar, kickoff.replace(minute=kickoff.minute - 1))
    assert before.state is SeasonState.PRESEASON_DRAFT
    assert before.mode is ProductMode.DRAFT
    # The draft is over and no game has finished. Both are true, and the shape says so.
    assert before.completed_week == 0

    after = resolve_season_state(calendar, kickoff.replace(minute=kickoff.minute + 1))
    assert after.state is SeasonState.REGULAR_SEASON
    assert after.mode is ProductMode.IN_SEASON
    assert after.completed_week == 0
    assert after.latest_snapshot_week is None


def test_a_week_is_complete_only_after_the_buffer_past_its_last_kickoff() -> None:
    calendar = build_season_calendar(_schedule(), 2026)
    window = calendar.window(1)
    assert window is not None

    # Kickoff of the last game is not "played": the buffer is what makes it so.
    assert resolve_season_state(calendar, window.last_kickoff_utc).completed_week == 0
    assert (
        resolve_season_state(
            calendar,
            window.complete_at_utc - timedelta(seconds=1),
        ).completed_week
        == 0
    )
    assert resolve_season_state(calendar, window.complete_at_utc).completed_week == 1
    assert (window.complete_at_utc - window.last_kickoff_utc) == timedelta(
        hours=GAME_COMPLETE_BUFFER_HOURS,
    )


def test_the_snapshot_week_follows_the_cutoff_rule_at_both_ends() -> None:
    calendar = build_season_calendar(_schedule(), 2026)

    # Week 0 is the preseason model's grain and is refused, so there is no snapshot yet.
    early = resolve_season_state(calendar, calendar.first_kickoff_utc)
    assert early.latest_snapshot_week is None

    mid = resolve_season_state(calendar, _at("2026-10-20T12:00:00Z"))
    assert mid.latest_snapshot_week == mid.completed_week
    assert mid.state is SeasonState.REGULAR_SEASON

    # Once the horizon's last week is played there is no remaining horizon to estimate.
    end = resolve_season_state(calendar, _at("2027-01-20T12:00:00Z"))
    assert end.state is SeasonState.SEASON_COMPLETE
    assert end.latest_snapshot_week is None
    assert end.mode is ProductMode.IN_SEASON


def test_the_fantasy_postseason_is_the_horizon_s_last_three_weeks() -> None:
    calendar = build_season_calendar(_schedule(), 2026)
    assert calendar.fantasy_postseason_first_week == 15

    week_14 = calendar.window(14)
    week_15 = calendar.window(15)
    assert week_14 is not None and week_15 is not None

    # Stated on the week being *played*: a reader on the Sunday of week 15 is in the fantasy
    # postseason, not still in week 14.
    before = resolve_season_state(calendar, week_14.complete_at_utc - timedelta(seconds=1))
    assert before.state is SeasonState.REGULAR_SEASON
    after = resolve_season_state(calendar, week_14.complete_at_utc)
    assert after.state is SeasonState.FANTASY_POSTSEASON


def test_a_pre_2021_season_has_a_shorter_horizon_and_an_earlier_postseason() -> None:
    schedule = _schedule(season=2019, weeks=17).with_columns(pl.lit(2019).alias("season"))
    calendar = build_season_calendar(schedule, 2019)
    assert calendar.horizon.last_week == 16
    # Derived from the horizon, not written as "weeks 15-17", which would be wrong here.
    assert calendar.fantasy_postseason_first_week == 14


def test_an_unknown_kickoff_time_resolves_towards_not_yet_played() -> None:
    known = build_season_calendar(_schedule(), 2026).window(1)
    unknown = build_season_calendar(
        _schedule().with_columns(
            pl.when(pl.col("week") == 1)
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(pl.col("gametime"))
            .alias("gametime"),
        ),
        2026,
    ).window(1)
    assert known is not None and unknown is not None
    # End of the local day rather than midnight. Every ambiguity here has to make the week
    # look *less* complete, because the opposite error publishes a board from data that does
    # not exist yet — so the unknown-time window can only ever end later than a known one.
    assert unknown.last_kickoff_utc > known.last_kickoff_utc


def test_a_season_with_no_regular_season_games_is_refused_rather_than_guessed() -> None:
    empty = _schedule().filter(pl.col("game_type") == "POST")
    with pytest.raises(AnchorError):
        build_season_calendar(empty, 2026)


def test_the_resolution_serializes_everything_a_build_has_to_record() -> None:
    state = season_state_from_schedule(_schedule(), season=2026, as_of=_at("2026-10-20T12:00:00Z"))
    payload = state.to_dict()
    assert payload["rule_version"] == "season_state_v1"
    assert payload["product_mode"] == "in_season"
    assert payload["completed_week"] == state.completed_week
    assert payload["calendar"]["fantasy_postseason_first_week"] == 15
    assert "first regular-season kickoff" in payload["derivation"]
