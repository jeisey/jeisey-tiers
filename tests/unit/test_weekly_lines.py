"""``pregame_line_reuse_v1`` (ADR-117): retained pregame lines may stand in for a blank schedule.

The reported failure, reproduced from the source itself: nflverse/nfldata's 2026-11-06T11:45:17Z
update (``63cbbc1``) blanked the odds block of all 14 unplayed week-9 games while the completed
Thursday game kept its lines; the 12:32Z refresh read that state and published every upcoming
player ``lines_pending``. The fixture holds the week-9 rows of that commit and of the 08:35Z one
before it (``92eff3e``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ffdraft.retention import SnapshotStore
from ffdraft.timeutil import parse_utc
from ffdraft.weekly.capture import (
    GAMEDAY_SOURCES,
    LINES_SOURCE_ID,
    GamedayCapture,
    write_gameday_capture,
)
from ffdraft.weekly.lines import (
    MAX_AGE,
    LineObservation,
    apply_retained_lines,
    line_capture_rows,
    lines_summary,
    observations_from_rows,
    retained_observations,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "weekly" / "schedule_lines_2026w09.json"
)
BUILD = parse_utc("2026-11-06T12:32:07Z")
PREVIOUS_BUILD = parse_utc("2026-11-05T22:53:00Z")
TNF = "2026_09_JAX_BAL"


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "game_id": pl.String,
            "season": pl.Int32,
            "game_type": pl.String,
            "week": pl.Int32,
            "gameday": pl.String,
            "gametime": pl.String,
            "away_team": pl.String,
            "away_score": pl.Int32,
            "home_team": pl.String,
            "home_score": pl.Int32,
            "location": pl.String,
            "spread_line": pl.Float64,
            "total_line": pl.Float64,
            "away_rest": pl.Int32,
            "home_rest": pl.Int32,
            "roof": pl.String,
            "stadium_id": pl.String,
            "stadium": pl.String,
        },
    )


@pytest.fixture(scope="module")
def states() -> dict[str, pl.DataFrame]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {name: _frame(data[name]["rows"]) for name in ("before", "blank")}


def _capture(schedule: pl.DataFrame, at: datetime) -> list[LineObservation]:
    rows, _ = line_capture_rows(schedule, season=2026, now=at)
    return observations_from_rows(rows, observed_at_utc=at)


def test_the_source_state_the_build_read() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blank, before = data["blank"]["rows"], data["before"]["rows"]
    assert len(blank) == len(before) == 15
    lined = [row["game_id"] for row in blank if row["total_line"] is not None]
    assert lined == [TNF]  # only the completed Thursday game kept its lines
    assert all(row["total_line"] is not None for row in before)


def test_the_blank_state_alone_lines_only_thursday(states) -> None:
    _, provenance = apply_retained_lines(
        states["blank"],
        [],
        season=2026,
        week=9,
        as_of=BUILD,
        schedule_observed_at=BUILD,
    )
    summary = lines_summary(provenance, schedule_observed_at=BUILD)
    assert (summary["from_schedule"], summary["from_retained"], summary["unlined"]) == (1, 0, 14)


def test_the_previous_evenings_capture_lines_every_upcoming_game(states) -> None:
    # The Nov 5 22:53Z capture: every week-9 game lined, all before their kickoffs.
    observations = _capture(states["before"], PREVIOUS_BUILD)
    assert len(observations) == 15
    patched, provenance = apply_retained_lines(
        states["blank"],
        observations,
        season=2026,
        week=9,
        as_of=BUILD,
        schedule_observed_at=BUILD,
    )
    summary = lines_summary(provenance, schedule_observed_at=BUILD)
    assert (summary["from_schedule"], summary["from_retained"], summary["unlined"]) == (1, 14, 0)
    assert provenance[TNF].source == "schedule"
    assert {item["observed_at_utc"] for item in summary["retained"]} == {"2026-11-05T22:53:00Z"}
    # The reused lines are the source's own pregame numbers for the same game.
    before = {row["game_id"]: row for row in states["before"].iter_rows(named=True)}
    for row in patched.filter(pl.col("week") == 9).iter_rows(named=True):
        assert row["spread_line"] == before[row["game_id"]]["spread_line"]
        assert row["total_line"] == before[row["game_id"]]["total_line"]


def test_a_capture_after_the_thursday_kickoff_still_lines_only_unplayed_games(states) -> None:
    # A capture of the pre-blank file at 08:35Z Friday: Thursday had kicked off, so it is not
    # captured at all, and the Sunday games are lined from it.
    at = parse_utc("2026-11-06T08:35:17Z")
    observations = _capture(states["before"], at)
    assert TNF not in {observation.game_id for observation in observations}
    assert len(observations) == 14


def _one(game_id: str = "2026_09_ARI_SEA", **overrides: Any) -> LineObservation:
    base = {
        "game_id": game_id,
        "season": 2026,
        "week": 9,
        "home_team": "SEA",
        "away_team": "ARI",
        "kickoff_utc": parse_utc("2026-11-08T21:25:00Z"),
        "spread_line": 8.5,
        "total_line": 39.5,
        "observed_at_utc": PREVIOUS_BUILD,
    }
    return LineObservation(**{**base, **overrides})


def _apply(states, observations, **kwargs: Any):
    return apply_retained_lines(
        states["blank"],
        observations,
        season=2026,
        week=9,
        as_of=kwargs.pop("as_of", BUILD),
        schedule_observed_at=BUILD,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("label", "observation"),
    [
        ("after kickoff", _one(observed_at_utc=parse_utc("2026-11-08T21:26:00Z"))),
        ("at kickoff", _one(observed_at_utc=parse_utc("2026-11-08T21:25:00Z"))),
        ("after the build", _one(observed_at_utc=BUILD + timedelta(minutes=1))),
        ("too old", _one(observed_at_utc=BUILD - MAX_AGE - timedelta(seconds=1))),
        ("only a spread", _one(total_line=None)),
        ("only a total", _one(spread_line=None)),
        ("another game", _one(game_id="2026_09_GB_NE")),
        ("swapped teams", _one(home_team="ARI", away_team="SEA")),
        ("another week", _one(week=10)),
        ("another season", _one(season=2025)),
    ],
)
def test_an_observation_that_is_not_a_pregame_line_of_this_game_is_refused(
    states,
    label: str,
    observation: LineObservation,
) -> None:
    _, provenance = _apply(states, [observation])
    assert provenance["2026_09_ARI_SEA"].source is None, label


def test_the_age_limit_is_inclusive_and_the_newest_eligible_wins(states) -> None:
    exactly = _one(observed_at_utc=BUILD - MAX_AGE, total_line=40.0)
    newer = _one(observed_at_utc=BUILD - timedelta(hours=3), total_line=41.5)
    late = _one(observed_at_utc=parse_utc("2026-11-08T22:00:00Z"), total_line=99.0)
    patched, provenance = _apply(states, [exactly, newer, late])
    assert provenance["2026_09_ARI_SEA"].source == "retained"
    assert provenance["2026_09_ARI_SEA"].observed_at_utc == newer.observed_at_utc
    row = patched.filter(pl.col("game_id") == "2026_09_ARI_SEA").row(0, named=True)
    assert row["total_line"] == 41.5
    _, only_exact = _apply(states, [exactly])
    assert only_exact["2026_09_ARI_SEA"].source == "retained"


def test_a_game_without_a_published_kickoff_time_cannot_prove_an_observation_pregame(
    states,
) -> None:
    schedule = states["blank"].with_columns(
        pl.when(pl.col("game_id") == "2026_09_ARI_SEA")
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(pl.col("gametime"))
        .alias("gametime"),
    )
    _, provenance = apply_retained_lines(
        schedule,
        [_one()],
        season=2026,
        week=9,
        as_of=BUILD,
        schedule_observed_at=BUILD,
    )
    assert provenance["2026_09_ARI_SEA"].source is None


def test_the_schedule_wins_and_only_the_target_week_changes(states) -> None:
    other_week = states["blank"].with_columns(pl.lit(10, dtype=pl.Int32).alias("week"))
    schedule = pl.concat([states["before"], other_week])
    observations = _capture(states["before"], PREVIOUS_BUILD)
    patched, provenance = apply_retained_lines(
        schedule,
        [_one(total_line=1.0)],
        season=2026,
        week=9,
        as_of=BUILD,
        schedule_observed_at=BUILD,
    )
    assert all(item.source == "schedule" for item in provenance.values())
    assert patched.equals(schedule)
    patched, _ = apply_retained_lines(
        schedule,
        observations,
        season=2026,
        week=10,
        as_of=BUILD,
        schedule_observed_at=BUILD,
    )
    # Week-9 observations never line week 10 (another week, so another game identity).
    assert patched.filter(pl.col("week") == 10)["total_line"].null_count() == 14


def test_a_capture_keeps_blanks_as_blanks(states) -> None:
    rows, details = line_capture_rows(states["blank"], season=2026, now=BUILD)
    assert details["games"] == 14 and details["lined"] == 0 and details["unlined"] == 14
    assert all(row["spread_line"] is None and row["total_line"] is None for row in rows)
    assert all(row["kickoff_time_published"] for row in rows)


def test_the_store_reads_only_captures_inside_the_window(states, tmp_path: Path) -> None:
    store = SnapshotStore(root=tmp_path, prefix="")
    for at in (
        BUILD - MAX_AGE - timedelta(hours=1),  # too old
        PREVIOUS_BUILD,  # the one that counts
        BUILD + timedelta(hours=1),  # after the build: never read
    ):
        rows, details = line_capture_rows(states["before"], season=2026, now=at)
        write_gameday_capture(
            GamedayCapture(
                source_id=LINES_SOURCE_ID,
                season=2026,
                observed_at_utc=at,
                rows=rows,
                details=details,
            ),
            store=store,
        )
    observations, keys = retained_observations(tmp_path, season=2026, as_of=BUILD)
    assert keys == ["2026-11-05T22-53-00Z"]
    assert {observation.observed_at_utc for observation in observations} == {PREVIOUS_BUILD}
    assert LINES_SOURCE_ID in GAMEDAY_SOURCES


def test_observation_times_are_utc_and_keys_round_trip() -> None:
    observation = _one()
    assert observation.observed_at_utc.tzinfo is not None
    assert observation.observed_at_utc == datetime(2026, 11, 5, 22, 53, tzinfo=UTC)


def test_the_build_reads_the_store_and_warns_about_what_it_reused(states, tmp_path: Path) -> None:
    """``build-ros``'s step: the Nov 6 blank schedule plus the Nov 5 22:53Z capture lines all 15
    games, says which came from the store, and warns (never fails) so the refresh log shows it."""
    from ffdraft.contracts.enums import Severity
    from ffdraft.pipeline.ros import _target_week_lines
    from ffdraft.quality import QualityGate

    rows, details = line_capture_rows(states["before"], season=2026, now=PREVIOUS_BUILD)
    write_gameday_capture(
        GamedayCapture(
            source_id=LINES_SOURCE_ID,
            season=2026,
            observed_at_utc=PREVIOUS_BUILD,
            rows=rows,
            details=details,
        ),
        store=SnapshotStore(root=tmp_path, prefix=""),
    )
    gate = QualityGate()
    _, provenance, summary = _target_week_lines(
        states["blank"], season=2026, week=9, as_of=BUILD, store=tmp_path, gate=gate
    )
    assert summary["captures_read"] == ["2026-11-05T22-53-00Z"]
    assert (summary["from_schedule"], summary["from_retained"], summary["unlined"]) == (1, 14, 0)
    assert gate.passed
    retained = [check for check in gate.checks if check.check_id == "ros.weekly_lines_retained"]
    assert len(retained) == 1 and retained[0].severity == Severity.WARNING
    assert not any(check.check_id == "ros.weekly_lines_unavailable" for check in gate.checks)

    # No store, or nothing retained in the window: the honest outcome is lines_pending, warned.
    gate = QualityGate()
    _, _, summary = _target_week_lines(
        states["blank"], season=2026, week=9, as_of=BUILD, store=None, gate=gate
    )
    assert summary["unlined"] == 14 and len(summary["unlined_game_ids"]) == 14
    assert gate.passed
    assert any(check.check_id == "ros.weekly_lines_unavailable" for check in gate.checks)
