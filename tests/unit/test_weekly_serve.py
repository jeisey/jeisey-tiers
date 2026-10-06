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
    assert {row["game_state"] for row in weekly} <= {"upcoming", "bye", "lines_pending"}
    assert any(row["game_state"] == "bye" for row in weekly)
    assert all(row["target_week"] == 9 for row in weekly)


def test_a_playing_record_is_monotone_and_its_account_closes(weekly) -> None:
    playing = [row for row in weekly if row["game_state"] in {"upcoming", "kicked_off"}]
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


def test_a_game_without_a_posted_line_is_published_not_projected(weekly) -> None:
    """The fixture's week-9 KC-LAC game has no line: the game is stated, nothing is projected."""
    pending = [row for row in weekly if row["game_state"] == "lines_pending"]
    assert pending
    for row in pending:
        assert row["game"] is not None and row["opponent"] is not None
        assert row["game"]["total_line"] is None  # null, never a pick'em
        assert row["quantiles"] is None and row["drivers"] is None
    projected = [row for row in weekly if row["quantiles"] is not None]
    assert projected
    assert all(row["game"]["total_line"] is not None for row in projected)


def test_a_lined_game_with_an_unannounced_roof_is_projected(
    serve, pipeline_result, app_config
) -> None:
    """Regression (live 2026 week 4, DAL @ HOU): only a missing line withholds a projection."""
    season = _fixture_season(pipeline_result.records["tiers"], app_config)
    lined = season.schedule.filter(
        (pl.col("week") == 9) & pl.col("total_line").is_not_null(),
    ).row(0, named=True)
    schedule = season.schedule.with_columns(
        pl.when(pl.col("game_id") == lined["game_id"])
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(pl.col("roof"))
        .alias("roof"),
    )
    result = serve(schedule=schedule)
    game = [
        row for row in result.records if row["game"] and row["game"]["game_id"] == lined["game_id"]
    ]
    assert game
    assert {row["game_state"] for row in game} == {"upcoming"}
    assert all(row["game"]["roof"] is None and row["quantiles"] is not None for row in game)


def test_the_committed_model_reads_a_missing_line_as_zero(serve, pipeline_result) -> None:
    """Why ``lines_pending`` exists: every training row had a line, so NaN routes as 0.0.

    If a refit ever learns the missing case this fails, and the rule can be revisited.
    """
    import numpy as np

    from ffdraft.weekly.frozen import WEEKLY_FEATURES

    model = WeeklyModel.load(repo_root() / DEFAULT_WEEKLY_MODEL_DIR)
    row: dict[str, Any] = dict.fromkeys(WEEKLY_FEATURES)
    row.update(
        {
            "position": "WR",
            "scoring_preset": "PPR",
            "ppg_to_date": 14.0,
            "target_share_to_date": 0.22,
            "games_to_date": 4,
            "game_is_home": 1.0,
            "game_rest_advantage": 0.0,
            "game_indoors": 0.0,
        },
    )
    lines = ("game_total_line", "game_team_margin", "game_team_points")
    missing = pl.DataFrame([{**row, **dict.fromkeys(lines)}], infer_schema_length=None)
    zero = pl.DataFrame([{**row, **dict.fromkeys(lines, 0.0)}], infer_schema_length=None)
    posted = pl.DataFrame(
        [{**row, "game_total_line": 47.5, "game_team_margin": 3.0, "game_team_points": 25.25}],
        infer_schema_length=None,
    )
    assert np.array_equal(model.predict(missing), model.predict(zero))
    assert model.predict(posted)[0, 3] > model.predict(missing)[0, 3]


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


def test_a_player_with_no_current_club_gets_no_next_game(serve, weekly) -> None:
    """ADR-102: an explicit None (verified unsigned) means no club, not "use the last one".

    Before, `coalesce(current_team, team_to_date)` handed a released, unsigned player the
    next game of the club he last appeared for.
    """
    player = next(row for row in weekly if row["game_state"] == "upcoming")
    unsigned = serve(current_teams={player["player_id"]: None})
    assert all(row["player_id"] != player["player_id"] for row in unsigned.records)
    others = {row["player_id"] for row in weekly} - {player["player_id"]}
    assert others <= {row["player_id"] for row in unsigned.records}


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
