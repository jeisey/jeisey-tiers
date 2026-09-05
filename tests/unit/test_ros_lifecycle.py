"""The season's two edges, where "the season has started" and "a board can exist" disagree.

`season_state_v1` flips the product mode at the first kickoff, which is what the roadmap
asks for. `ros_cutoff_v1` refuses week 0, which is also right — there is no rest-of-season
snapshot before a week has been played. Between those two correct rules is a window of
several days in which the season has started and no board can be built, and a pipeline that
treated it as a source failure would fail every scheduled refresh in it. A failed refresh
does not merely skip the in-season board: it stops the **draft** build deploying too, so the
site would freeze for the first week of every season (ADR-079).

The same disagreement happens again at the other end. Once the last scored week is played,
`available_through_week` is that week and `RosCutoff` refuses it — correctly, there is no
remaining horizon — and reaching the constructor with it raises an uncaught `ValueError`.
Every refresh from the end of the season onwards would crash rather than do nothing.

These tests walk the four states the reviewer asked for, plus the fifth at the far end, and
assert the *production outcome* of each: which cutoff is resolved, whether the gate passes,
and what the workflow reads to decide whether to run the build at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from ffdraft.pipeline.ros import _resolve_week
from ffdraft.quality import QualityGate
from ffdraft.ros.freshness import assess_ros_freshness
from ffdraft.season.state import ProductMode, SeasonState, season_state_from_schedule

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

#: 2026's first regular-season kickoff in this synthetic schedule, in UTC.
FIRST_KICKOFF = "2026-09-11T00:15:00Z"


def _schedule(weeks: int = 18) -> pl.DataFrame:
    """Thursday night, Sunday afternoon, Monday night — the real weekly shape."""
    rows: list[dict[str, object]] = []
    start = datetime(2026, 9, 10, tzinfo=UTC).date()
    for week in range(1, weeks + 1):
        thursday = start.fromordinal(start.toordinal() + (week - 1) * 7)
        for index in range(16):
            offset, kickoff = (0, "20:15") if index == 0 else (3, "13:00")
            if index == 15:
                offset, kickoff = 4, "20:15"
            rows.append(
                {
                    "game_id": f"2026_{week:02d}_G{index:02d}",
                    "season": 2026,
                    "game_type": "REG",
                    "week": week,
                    "gameday": thursday.fromordinal(thursday.toordinal() + offset).isoformat(),
                    "gametime": kickoff,
                    "home_team": TEAMS[index * 2],
                    "away_team": TEAMS[index * 2 + 1],
                },
            )
    return pl.DataFrame(rows)


def _weekly(weeks: dict[int, int]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for week, count in weeks.items():
        for index, club in enumerate(TEAMS[:count]):
            rows.append(
                {
                    "season": 2026,
                    "week": week,
                    "season_type": "REG",
                    "gsis_id": f"00-{week:02d}{index:03d}",
                    "team": club,
                },
            )
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def _outcome(as_of: str, weekly: dict[int, int]) -> dict[str, object]:
    """One refresh, decided exactly as production decides it.

    Three answers come out, and they are the three the workflow and the build each use:
    ``snapshot_week`` is what the workflow's ``if:`` reads to decide whether to run the ROS
    build at all, ``cutoff`` is what the build resolves, and ``blocking`` is whether the
    quality gate would fail the job.
    """
    state = season_state_from_schedule(
        _schedule(),
        season=2026,
        as_of=datetime.fromisoformat(as_of.replace("Z", "+00:00")),
    )
    freshness = assess_ros_freshness(state=state, weekly_stats=_weekly(weekly))
    gate = QualityGate().extend(freshness.checks())
    cutoff = _resolve_week(
        requested=None,
        freshness_week=freshness.available_through_week,
        state=state,
        gate=gate,
    )
    return {
        "state": state.state,
        "mode": state.mode,
        "completed_week": state.completed_week,
        # The workflow's gate. Empty string is what an absent snapshot week becomes in YAML.
        "snapshot_week": state.latest_snapshot_week,
        "cutoff": cutoff,
        "blocking": not gate.passed,
        "checks": [check.check_id for check in gate.checks if check.status.name == "FAIL"],
    }


def test_a_one_minute_before_the_first_kickoff() -> None:
    """State A. The draft product, and nothing about the in-season path runs."""
    outcome = _outcome("2026-09-11T00:14:00Z", {})
    assert outcome["state"] is SeasonState.PRESEASON_DRAFT
    assert outcome["mode"] is ProductMode.DRAFT
    assert outcome["snapshot_week"] is None
    assert outcome["cutoff"] is None
    assert outcome["blocking"] is False


def test_b_after_the_first_kickoff_with_no_completed_week() -> None:
    """State B. The season has started; no week has finished; no board can exist.

    The mode has flipped, which is what the roadmap asks for, and the workflow does not run
    the ROS build because no snapshot week exists. Deterministic from the schedule alone —
    no upstream read is needed to know this, which is why the workflow can skip rather than
    attempt and fail.
    """
    outcome = _outcome("2026-09-11T04:00:00Z", {})
    assert outcome["state"] is SeasonState.REGULAR_SEASON
    assert outcome["mode"] is ProductMode.IN_SEASON
    assert outcome["completed_week"] == 0
    assert outcome["snapshot_week"] is None
    assert outcome["cutoff"] is None
    assert outcome["blocking"] is False


def test_c_week_one_played_but_its_data_has_not_been_published() -> None:
    """State C. The clock says a week is done; nflverse has not released it yet.

    The workflow *does* run the build here — the schedule cannot know what upstream holds —
    and the build refuses the week and publishes nothing. The refusal is a warning, so the
    job stays green and the draft build deploys, which is the whole point: an unreleased week
    is a cadence, not an outage.
    """
    outcome = _outcome("2026-09-15T12:00:00Z", {})
    assert outcome["state"] is SeasonState.REGULAR_SEASON
    assert outcome["completed_week"] == 1
    assert outcome["snapshot_week"] == 1
    assert outcome["cutoff"] is None
    assert outcome["blocking"] is False
    assert outcome["checks"] == ["ros.awaiting_first_week"]


def test_d_week_one_available() -> None:
    """State D. Both gates say yes, and the first board of the season is built."""
    outcome = _outcome("2026-09-15T12:00:00Z", {1: 32})
    assert outcome["snapshot_week"] == 1
    assert outcome["cutoff"] == 1
    assert outcome["blocking"] is False
    assert outcome["checks"] == []


def test_a_partial_week_one_release_is_not_week_one() -> None:
    """The failure state C must not be confused with: released, and missing four clubs."""
    outcome = _outcome("2026-09-15T12:00:00Z", {1: 28})
    assert outcome["cutoff"] is None
    assert outcome["blocking"] is False
    assert outcome["checks"] == ["ros.awaiting_first_week"]


def test_the_season_ends_without_a_crash_loop_or_a_board_of_zeros() -> None:
    """The far edge. Every scored week is played and the horizon is spent.

    `RosCutoff` refuses the last scored week, correctly — but it must be refused *before* the
    constructor, or every refresh from January onwards raises an uncaught `ValueError`. The
    outcome is a warning and no board: the last published board stands, and a structurally
    zero "week 17" board published to keep the tab populated would be a fiction.
    """
    outcome = _outcome("2027-01-05T12:00:00Z", {week: 32 for week in range(1, 18)})
    assert outcome["state"] is SeasonState.SEASON_COMPLETE
    assert outcome["mode"] is ProductMode.IN_SEASON
    assert outcome["snapshot_week"] is None
    assert outcome["cutoff"] is None
    assert outcome["blocking"] is False
    assert outcome["checks"] == ["ros.season_complete"]


def test_the_final_valid_snapshot_is_the_week_before_the_last_scored_one() -> None:
    """The step immediately before it: the deepest board a season ever produces."""
    state = season_state_from_schedule(
        _schedule(),
        season=2026,
        as_of=datetime.fromisoformat("2026-12-29T12:00:00+00:00"),
    )
    assert state.state is SeasonState.FANTASY_POSTSEASON
    assert state.latest_snapshot_week == state.calendar.horizon.last_week - 1

    outcome = _outcome("2026-12-29T12:00:00Z", {week: 32 for week in range(1, 17)})
    assert outcome["cutoff"] == state.calendar.horizon.last_week - 1
    assert outcome["blocking"] is False


def test_a_completed_season_is_still_replayable_by_request() -> None:
    """The exemption that keeps the rehearsal path alive.

    Every historical season is `season_complete`, so a season-complete refusal that also
    applied to an explicit `--through-week` would make replaying a finished season — the only
    way to exercise this path before a season of one's own has started — impossible.
    """
    state = season_state_from_schedule(
        _schedule(),
        season=2026,
        as_of=datetime.fromisoformat("2027-06-01T12:00:00+00:00"),
    )
    gate = QualityGate()
    assert state.state is SeasonState.SEASON_COMPLETE
    assert _resolve_week(requested=8, freshness_week=17, state=state, gate=gate) == 8
    assert gate.passed


def test_a_requested_week_past_the_horizon_is_refused_rather_than_raised() -> None:
    """`RosCutoff` would raise; the gate says so instead, with the bound in the message."""
    state = season_state_from_schedule(
        _schedule(),
        season=2026,
        as_of=datetime.fromisoformat("2027-06-01T12:00:00+00:00"),
    )
    gate = QualityGate()
    assert _resolve_week(requested=17, freshness_week=17, state=state, gate=gate) is None
    assert [check.check_id for check in gate.checks if check.status.name == "FAIL"] == [
        "ros.requested_week_unavailable",
    ]


@pytest.mark.parametrize("week", [0, -1])
def test_the_cutoff_rule_still_refuses_week_zero_directly(week: int) -> None:
    """Nothing above weakens the rule it is routing around."""
    from ffdraft.ros.cutoff import RosCutoff

    with pytest.raises(ValueError, match="below 1"):
        RosCutoff(season=2026, through_week=week)
