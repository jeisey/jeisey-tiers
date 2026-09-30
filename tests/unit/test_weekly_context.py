"""The weekly model's game and opponent inputs: oriented correctly, point-in-time, exact."""

from __future__ import annotations

import random

import polars as pl
import pytest

from ffdraft.weekly.context import opponent_allowed, team_game_context


def _schedule(**overrides: object) -> pl.DataFrame:
    row = {
        "game_id": "2024_05_NYJ_BUF",
        "season": 2024,
        "game_type": "REG",
        "week": 5,
        "gameday": "2024-10-06",
        "gametime": "13:00",
        "away_team": "NYJ",
        "home_team": "BUF",
        "location": "Home",
        "away_rest": 7,
        "home_rest": 10,
        "roof": "dome",
        "spread_line": 6.5,
        "total_line": 44.5,
    }
    row.update(overrides)
    return pl.DataFrame([row])


def test_the_spread_is_expressed_from_each_side_with_home_favoured_positive() -> None:
    context = team_game_context(_schedule(), [2024])
    home = context.filter(pl.col("team") == "BUF").row(0, named=True)
    away = context.filter(pl.col("team") == "NYJ").row(0, named=True)
    assert home["game_team_margin"] == 6.5
    assert away["game_team_margin"] == -6.5
    assert home["game_team_points"] == pytest.approx((44.5 + 6.5) / 2)
    assert away["game_team_points"] == pytest.approx((44.5 - 6.5) / 2)
    assert home["game_is_home"] == 1.0 and away["game_is_home"] == 0.0
    assert home["game_rest_advantage"] == 3 and away["game_rest_advantage"] == -3
    assert home["game_indoors"] == 1.0
    assert home["opponent"] == "NYJ" and away["opponent"] == "BUF"


def test_a_neutral_site_is_nobodys_home() -> None:
    context = team_game_context(_schedule(location="Neutral"), [2024])
    assert set(context.get_column("game_is_home").to_list()) == {0.0}


def test_a_missing_line_is_null_never_a_pickem() -> None:
    context = team_game_context(_schedule(spread_line=None, total_line=None), [2024])
    assert context.get_column("game_team_margin").null_count() == 2
    assert context.get_column("game_team_points").null_count() == 2


def _scored(rows: list[tuple[int, int, str, str, float]]) -> pl.DataFrame:
    """(season, week, defense, position, points) -> the long scored frame, PPR only."""
    return pl.DataFrame(
        [
            {
                "season": season,
                "week": week,
                "gsis_id": f"00-{index:07d}",
                "team": "XXX",
                "defense": defense,
                "position": position,
                "scoring_preset": "PPR",
                "points": points,
            }
            for index, (season, week, defense, position, points) in enumerate(rows)
        ],
        schema_overrides={"season": pl.Int32, "week": pl.Int32},
    )


ROWS = [
    (2024, 1, "AAA", "WR", 30.12),
    (2024, 1, "BBB", "WR", 10.04),
    (2024, 2, "AAA", "WR", 24.3),
    (2024, 2, "BBB", "WR", 12.18),
    (2024, 3, "AAA", "WR", 99.9),  # the future, relative to a week-2 cutoff
    (2024, 3, "BBB", "WR", 0.0),
    (2023, 10, "AAA", "WR", 20.0),
]


def test_a_cutoff_never_reads_a_later_week() -> None:
    """Delete the future and nothing moves: the constructive proof of point-in-time."""
    full = opponent_allowed(_scored(ROWS), season=2024, through_week=2)
    past = opponent_allowed(
        _scored([row for row in ROWS if not (row[0] == 2024 and row[1] > 2)]),
        season=2024,
        through_week=2,
    )
    assert full.equals(past)


def test_the_reading_is_shrunk_toward_the_league_and_ranked() -> None:
    frame = opponent_allowed(_scored(ROWS), season=2024, through_week=2, shrinkage_games=4.0)
    wr = frame.filter(pl.col("position") == "WR").sort("defense")
    league = (30.12 + 10.04 + 24.3 + 12.18) / 4
    a = wr.row(0, named=True)
    assert a["league_ppg"] == pytest.approx(league)
    assert a["opp_allowed_ppg"] == pytest.approx((30.12 + 24.3 + 4 * league) / (2 + 4))
    assert a["opp_allowed_index"] == pytest.approx(a["opp_allowed_ppg"] / league)
    assert a["opp_allowed_rank"] == 1
    assert a["opp_allowed_prior_ppg"] == pytest.approx(20.0)
    assert wr.row(1, named=True)["opp_allowed_prior_ppg"] is None


def test_the_sums_are_exact_in_any_row_order() -> None:
    """Integer hundredths: a shuffled frame gives identical bytes (ADR-096)."""
    rows = [
        (
            2024,
            week,
            defense,
            "RB",
            round(random.Random(week * 31 + ord(defense[0])).uniform(0, 30), 2),
        )
        for week in range(1, 9)
        for defense in ("AAA", "BBB", "CCC")
    ]
    ordered = opponent_allowed(_scored(rows), season=2024, through_week=8)
    shuffled_rows = rows[:]
    random.Random(7).shuffle(shuffled_rows)
    shuffled = opponent_allowed(_scored(shuffled_rows), season=2024, through_week=8)
    assert ordered.equals(shuffled)


def test_attached_game_columns_replace_a_prefilled_null() -> None:
    """Regression: a snapshot pre-filled with null feature names once kept its nulls."""
    from ffdraft.weekly.dataset import attach_game_and_opponent

    frame = pl.DataFrame(
        {
            "season": [2024],
            "through_week": [4],
            "target_week": [5],
            "team": ["BUF"],
            "position": ["WR"],
            "scoring_preset": ["PPR"],
            "game_total_line": [None],
            "opp_allowed_ppg": [None],
        },
        schema_overrides={
            "season": pl.Int32,
            "through_week": pl.Int32,
            "target_week": pl.Int32,
            "game_total_line": pl.Float64,
            "opp_allowed_ppg": pl.Float64,
        },
    )
    allowed = opponent_allowed(
        _scored([(2024, week, "NYJ", "WR", 15.0) for week in range(1, 5)]),
        season=2024,
        through_week=4,
    )
    joined = attach_game_and_opponent(
        frame,
        context=team_game_context(_schedule(), [2024]),
        allowed=allowed,
        team_column="team",
    )
    assert not any(column.endswith("_right") for column in joined.columns)
    row = joined.row(0, named=True)
    assert row["game_total_line"] == 44.5
    assert row["opponent"] == "NYJ"
    assert row["opp_allowed_ppg"] == pytest.approx(15.0)
