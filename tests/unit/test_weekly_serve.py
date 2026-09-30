"""Serving the weekly model: the states a start/sit reader needs, and the injury layer.

The fixture pipeline runs the production serve path with the committed artifact; these tests
read that output and then call the same function with one input changed at a time.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts import record_schema_version
from ffdraft.paths import repo_root
from ffdraft.pipeline.fixture_pipeline import _fixture_season, weekly_serve_inputs
from ffdraft.pipeline.fixture_season import FIXTURE_INSEASON_AS_OF
from ffdraft.pipeline.ros import DEFAULT_WEEKLY_MODEL_DIR
from ffdraft.timeutil import parse_utc
from ffdraft.weekly.frozen import FEATURE_FAMILIES, WEEKLY_QUANTILE_LEVELS
from ffdraft.weekly.injuries import injury_base_rates, normalize_injuries, reports_for_week
from ffdraft.weekly.model import WeeklyModel, quantile_columns
from ffdraft.weekly.serve import build_weekly_projection_records

KEYS = quantile_columns(WEEKLY_QUANTILE_LEVELS)


@pytest.fixture(scope="module")
def weekly(pipeline_result) -> list[dict[str, Any]]:
    return pipeline_result.records["weekly_projections"]


@pytest.fixture(scope="module")
def serve(pipeline_result, app_config):
    """``serve(**overrides)`` re-runs the production serve with one input changed."""
    season = _fixture_season(pipeline_result.records["tiers"], app_config)
    snapshot, players, reports = weekly_serve_inputs(
        pipeline_result.records["inseason_opportunity"],
        pipeline_result.records["player_usage"],
        app=app_config,
    )
    model = WeeklyModel.load(repo_root() / DEFAULT_WEEKLY_MODEL_DIR)
    base: dict[str, Any] = {
        "model": model,
        "snapshot": snapshot,
        "players": players,
        "current_teams": {},
        "weekly": season.weekly,
        "schedule": season.schedule,
        "scoring": app_config.league.scoring,
        "season": 2026,
        "through_week": 8,
        "as_of": parse_utc(FIXTURE_INSEASON_AS_OF),
        "build_id": "test",
        "schema_version": record_schema_version("weekly_projection"),
        "injury_reports": reports,
    }

    def run(**overrides: Any):
        return build_weekly_projection_records(**{**base, **overrides})

    return run


def test_every_opportunity_player_is_projected_or_on_bye(pipeline_result, weekly) -> None:
    board = {row["player_id"] for row in pipeline_result.records["inseason_opportunity"]}
    served = {row["player_id"] for row in weekly}
    assert served <= board
    assert {row["game_state"] for row in weekly} <= {"upcoming", "bye"}
    assert any(row["game_state"] == "bye" for row in weekly)
    assert all(row["target_week"] == 9 for row in weekly)


def test_a_playing_record_is_monotone_and_its_account_closes(weekly) -> None:
    playing = [row for row in weekly if row["game_state"] != "bye"]
    assert playing
    for row in playing:
        values = [row["quantiles"][key] for key in KEYS]
        assert values == sorted(values)
        parts = row["drivers"]
        assert set(parts) == {"baseline", *FEATURE_FAMILIES, "calibration", "rearrangement"}
        assert sum(parts.values()) == pytest.approx(row["quantiles"]["q50"], abs=0.011)
        assert row["game"]["opponent"] == row["opponent"]["defense"]


def test_a_bye_is_published_as_a_bye_with_nothing_projected(weekly, pipeline_result) -> None:
    byes = [row for row in weekly if row["game_state"] == "bye"]
    matchups = {row["team"]: row for row in pipeline_result.records["team_matchups"]}
    for row in byes:
        assert row["quantiles"] is None and row["drivers"] is None and row["game"] is None
        # The matchup layer agrees the team's next game is not week 9.
        assert matchups[row["team"]]["week"] != 9


def test_an_unposted_line_is_null_not_a_pickem(weekly) -> None:
    lines = [row["game"]["total_line"] for row in weekly if row["game_state"] != "bye"]
    assert None in lines
    assert any(line is not None for line in lines)


def test_the_fixture_injury_reports_ride_on_the_record(weekly) -> None:
    designated = [row for row in weekly if row["injury"] is not None]
    assert {row["injury"]["designation"] for row in designated} == {"Questionable", "Out"}


def test_a_game_already_started_is_kept_and_marked(serve) -> None:
    late = serve(as_of=parse_utc(FIXTURE_INSEASON_AS_OF) + timedelta(days=5, hours=12))
    states = {row["game_state"] for row in late.records}
    assert "kicked_off" in states
    assert late.summary["kicked_off"] > 0
    assert late.summary["records"] == len(late.records)


def test_the_current_roster_moves_the_game(serve, weekly) -> None:
    mover = next(row for row in weekly if row["game_state"] == "upcoming")
    other = next(
        row
        for row in weekly
        if row["game_state"] == "upcoming"
        and row["game"]["opponent"] != mover["game"]["opponent"]
        and row["team"] != mover["team"]
    )
    moved = serve(current_teams={mover["player_id"]: other["team"]})
    record = next(
        row
        for row in moved.records
        if row["player_id"] == mover["player_id"]
        and row["scoring_preset"] == mover["scoring_preset"]
    )
    assert record["team"] == other["team"]
    assert record["game"]["game_id"] == other["game"]["game_id"]


def test_there_is_nothing_to_project_after_the_last_scored_week(serve) -> None:
    done = serve(through_week=17)
    assert done.records == []
    assert done.summary["reason"] == "season_complete"


def _injuries(rows: list[tuple[int, int, str, str | None, str]]) -> pl.DataFrame:
    return normalize_injuries(
        [
            {
                "season": season,
                "game_type": "REG",
                "week": week,
                "gsis_id": gsis,
                "team": "KC",
                "report_status": status,
                "practice_status": "Limited Participation in Practice",
                "report_primary_injury": "Ankle",
                "position": position,
            }
            for season, week, gsis, status, position in rows
        ],
    )


def test_the_base_rate_counts_every_designated_skill_player_week() -> None:
    injuries = _injuries(
        [
            (2024, 1, "a", "Questionable", "WR"),  # week 1: appeared
            (2024, 2, "a", "Questionable", "WR"),  # missed
            (2024, 3, "b", "Out", "RB"),  # missed
            (2024, 3, "c", "Questionable", "T"),  # a lineman: not the question
            (2024, 18, "d", "Questionable", "WR"),  # outside the scored weeks
            (2024, 4, "e", None, "WR"),  # practice note only
        ],
    )
    appeared = pl.DataFrame(
        {"season": [2024, 2024], "week": [1, 18], "gsis_id": ["a", "d"]},
        schema_overrides={"season": pl.Int32, "week": pl.Int32},
    )
    rates = injury_base_rates(injuries, appeared, seasons=[2024])
    assert rates["Questionable"] == {"reports": 2, "appeared": 1, "appearance_rate": 0.5}
    assert rates["Out"] == {"reports": 1, "appeared": 0, "appearance_rate": 0.0}
    assert rates["_rule"]["seasons"] == [2024]


def test_a_week_report_keeps_practice_notes_without_inventing_a_designation() -> None:
    reports = reports_for_week(
        _injuries([(2026, 4, "a", "Doubtful", "WR"), (2026, 4, "e", "Note", "WR")]),
        season=2026,
        week=4,
    )
    assert reports["a"]["designation"] == "Doubtful"
    assert reports["e"]["designation"] is None
    assert reports["e"]["practice_status"].startswith("Limited")
