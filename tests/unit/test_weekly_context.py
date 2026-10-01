"""The weekly model's game and opponent inputs: oriented correctly, point-in-time, exact."""

from __future__ import annotations

import csv
import random

import polars as pl
import pytest

from ffdraft.paths import repo_root
from ffdraft.weekly.context import opponent_allowed, team_game_context
from ffdraft.weekly.venues import VenueRegistry, load_venue_registry


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


def test_an_unannounced_roof_takes_the_stadiums_recorded_state() -> None:
    """Regression: the live 2026 week-4 DAL @ HOU game had lines and no roof (retractable)."""
    schedule = pl.concat(
        [
            _schedule(game_id="2024_01_NYJ_HOU", week=1, home_team="HOU", roof="closed"),
            _schedule(
                game_id="2024_02_HOU_KC", week=2, home_team="KC", away_team="HOU", roof="outdoors"
            ),
            _schedule(
                game_id="2024_04_DAL_HOU", week=4, home_team="HOU", away_team="DAL", roof=None
            ),
            _schedule(game_id="2024_05_NYJ_MIA", week=5, home_team="MIA", roof=None),
        ],
        how="diagonal_relaxed",
    )
    context = team_game_context(schedule, [2024])
    week4 = context.filter(pl.col("week") == 4)
    # The published roof stays what the schedule says; the model input is the recorded state.
    assert week4.get_column("roof").to_list() == [None, None]
    assert week4.get_column("game_indoors").to_list() == [1.0, 1.0]
    # No earlier home game at that stadium: left null (the model reads open air).
    assert context.filter(pl.col("week") == 5).get_column("game_indoors").null_count() == 2


def test_a_later_roof_is_never_read_back() -> None:
    schedule = pl.concat(
        [
            _schedule(
                game_id="2024_04_DAL_HOU", week=4, home_team="HOU", away_team="DAL", roof=None
            ),
            _schedule(game_id="2024_06_NYJ_HOU", week=6, home_team="HOU", roof="closed"),
        ],
        how="diagonal_relaxed",
    )
    week4 = team_game_context(schedule, [2024]).filter(pl.col("week") == 4)
    assert week4.get_column("game_indoors").null_count() == 2


def _registry() -> VenueRegistry:
    return load_venue_registry()


def test_a_verified_open_venue_overrides_a_dome_label() -> None:
    """2026 MUN01: nflverse files the Allianz Arena (open to the sky) as ``dome``."""
    game = _schedule(
        game_id="2026_10_NE_DET",
        season=2026,
        week=10,
        gameday="2026-11-15",
        home_team="DET",
        away_team="NE",
        location="Neutral",
        roof="dome",
        stadium_id="MUN01",
        stadium="FC Bayern Munich Stadium",
    )
    assert team_game_context(game, [2026]).get_column("game_indoors").to_list() == [1.0, 1.0]
    served = team_game_context(game, [2026], venues=_registry())
    assert served.get_column("game_indoors").to_list() == [0.0, 0.0]
    # The label is the venue's, and nothing is marked assumed.
    assert served.get_column("roof").to_list() == ["outdoors", "outdoors"]
    assert served.get_column("roof_inferred").to_list() == [False, False]


def test_a_verified_dome_fills_a_missing_roof_without_an_assumption() -> None:
    game = _schedule(roof=None, home_team="DET", stadium_id="DET00", stadium="Ford Field")
    served = team_game_context(game, [2024], venues=_registry())
    assert served.get_column("game_indoors").to_list() == [1.0, 1.0]
    assert served.get_column("roof_inferred").to_list() == [False, False]


def test_a_retractable_or_unresolved_venue_keeps_the_schedule_roof() -> None:
    houston = _schedule(roof="closed", home_team="HOU", stadium_id="HOU00", stadium="NRG Stadium")
    nowhere = _schedule(roof="dome", stadium_id="XXX00", stadium="Nowhere Field")
    for game in (houston, nowhere):
        assert team_game_context(game, [2024], venues=_registry()).equals(
            team_game_context(game, [2024]),
        )


def test_the_override_reproduces_every_recorded_roof_through_2025() -> None:
    """Training passes no registry because, on history, the registry changes nothing.

    Every 2017-2025 stadium-season the schedule prints, with every roof nflverse recorded
    there: at a venue the registry calls ``open`` or ``dome``, each recorded roof reads the same
    ``game_indoors`` as the venue does. A registry edit that broke this would make serving
    disagree with what v1 was trained on, and fails here.
    """
    registry = _registry()
    fixed = {"open": 0.0, "dome": 1.0}
    checked = 0
    with (repo_root() / "tests/fixtures/weekly/schedule_stadiums.csv").open() as handle:
        for row in csv.DictReader(handle):
            if int(row["season"]) > 2025:
                continue
            venue = registry.resolve(
                season=int(row["season"]), stadium_id=row["stadium_id"], stadium=row["stadium"]
            )
            assert venue is not None, row
            if venue.roof_type not in fixed:
                continue
            for recorded in filter(None, row["schedule_roofs"].split("|")):
                indoors = 1.0 if recorded in ("dome", "closed") else 0.0
                assert indoors == fixed[venue.roof_type], (row, venue.venue_id)
                checked += 1
    # Every recorded (stadium-season, roof) pair at a fixed-roof venue, 2017-2025.
    assert checked == 247
