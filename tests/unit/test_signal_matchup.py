"""`next_game_v1`: each team's next unplayed game, as published context (ADR-091).

Three claims, and the first is the one a plausible-looking bug would break:

* **the spread is re-expressed from the team's own side exactly once.** nflverse's
  ``spread_line`` is positive when the *home* team is favoured; a card that read it the
  betting-slip way would tell every reader the underdog was favoured, and every number
  would still look reasonable;
* **"next" means not yet kicked off**, measured against the build's own timestamp;
* **the sportsbook numbers are context and nothing else** — the firewall tests at the
  bottom fail if any feature the intrinsic or rest-of-season model reads is named for them,
  or is a field either signal artifact publishes.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ffdraft.artifacts.schemas import validate_records
from ffdraft.artifacts.validate import _matchup_checks
from ffdraft.contracts.normalized import SCHEDULE_CONTRACT
from ffdraft.features.dictionary import FEATURE_DICTIONARY
from ffdraft.paths import schemas_dir
from ffdraft.quality.forbidden import forbidden_reason
from ffdraft.ros.dictionary import ros_feature_selection
from ffdraft.signals.matchup import build_team_matchup_records
from ffdraft.sources.nflverse_history import NflverseScheduleAdapter

_SEASON = 2026
_RETRIEVED = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _game(
    week: int,
    away: str,
    home: str,
    *,
    day: date,
    time: str = "13:00",
    spread: float | None = None,
    total: float | None = None,
    location: str = "Home",
    away_rest: int | None = 7,
    home_rest: int | None = 7,
) -> dict[str, Any]:
    return {
        "game_id": f"{_SEASON}_{week:02d}_{away}_{home}",
        "season": _SEASON,
        "game_type": "REG",
        "week": week,
        "gameday": day,
        "gametime": time,
        "away_team": away,
        "home_team": home,
        "location": location,
        "away_rest": away_rest,
        "home_rest": home_rest,
        "roof": "outdoors",
        "spread_line": spread,
        "total_line": total,
    }


def _matchups(games: list[dict[str, Any]], *, as_of: datetime, through_week: int = 2):
    return {
        record["team"]: record
        for record in build_team_matchup_records(
            schedule=SCHEDULE_CONTRACT.build(games),
            season=_SEASON,
            through_week=through_week,
            as_of=as_of,
            build_id="test",
            schema_version="1.0",
            lines_source_id="nflreadpy",
            lines_retrieved_at=_RETRIEVED,
        )
    }


def test_a_positive_upstream_spread_favours_the_home_team() -> None:
    games = [_game(3, "LAC", "BUF", day=date(2026, 9, 27), spread=7.0, total=50.5)]
    records = _matchups(games, as_of=_RETRIEVED)
    assert records["BUF"]["team_expected_margin"] == 7.0
    assert records["LAC"]["team_expected_margin"] == -7.0
    assert records["BUF"]["implied_team_points"] == 28.75
    assert records["LAC"]["implied_team_points"] == 21.75
    assert records["BUF"]["home_away"] == "home"
    assert records["LAC"]["opponent"] == "BUF"


def test_a_negative_upstream_spread_favours_the_away_team() -> None:
    games = [_game(3, "KC", "MIA", day=date(2026, 9, 27), spread=-11.5, total=46.5)]
    records = _matchups(games, as_of=_RETRIEVED)
    assert records["KC"]["team_expected_margin"] == 11.5
    assert records["KC"]["implied_team_points"] == 29.0
    assert records["MIA"]["implied_team_points"] == 17.5


def test_next_means_not_yet_kicked_off() -> None:
    games = [
        _game(3, "ATL", "GB", day=date(2026, 9, 24), time="20:15"),
        _game(4, "GB", "DET", day=date(2026, 10, 1), time="20:15"),
        _game(3, "DET", "CHI", day=date(2026, 9, 27)),
        _game(4, "CHI", "ATL", day=date(2026, 10, 4)),
    ]
    friday = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)
    records = _matchups(games, as_of=friday)
    # Thursday's game is over by Friday, so Green Bay's next game is week 4.
    assert records["GB"]["week"] == 4
    assert records["DET"]["week"] == 3
    assert records["GB"]["kickoff_utc"] == "2026-10-02T00:15:00Z"


def test_an_unposted_line_is_null_and_never_a_pickem() -> None:
    games = [_game(5, "NYJ", "NE", day=date(2026, 10, 11))]
    record = _matchups(games, as_of=_RETRIEVED)["NYJ"]
    assert record["team_expected_margin"] is None
    assert record["total_line"] is None
    assert record["implied_team_points"] is None
    assert record["lines_source_id"] is None
    assert record["lines_retrieved_at_utc"] is None


def test_a_neutral_site_is_flagged_and_keeps_the_leagues_home_designation() -> None:
    games = [
        _game(3, "BAL", "DAL", day=date(2026, 9, 27), spread=-3.0, total=52.5, location="Neutral")
    ]
    records = _matchups(games, as_of=_RETRIEVED)
    assert records["BAL"]["neutral_site"] is True
    assert records["DAL"]["home_away"] == "home"
    assert records["BAL"]["team_expected_margin"] == 3.0


def test_rest_days_are_read_from_the_teams_own_side() -> None:
    games = [_game(3, "LAC", "BUF", day=date(2026, 9, 27), away_rest=7, home_rest=10)]
    records = _matchups(games, as_of=_RETRIEVED)
    assert records["BUF"]["team_rest_days"] == 10
    assert records["BUF"]["opponent_rest_days"] == 7
    assert records["LAC"]["team_rest_days"] == 7


def test_upcoming_byes_are_the_horizon_weeks_after_the_cutoff_without_a_game() -> None:
    games = [
        _game(week, "GB", "MIN", day=date(2026, 9, 13) + timedelta(days=7 * (week - 1)))
        for week in range(1, 18)
        if week != 6
    ]
    records = _matchups(games, as_of=_RETRIEVED, through_week=2)
    assert records["MIN"]["upcoming_bye_weeks"] == [6]
    late = _matchups(games, as_of=datetime(2026, 10, 30, tzinfo=UTC), through_week=7)
    assert late["MIN"]["upcoming_bye_weeks"] == []


def test_a_team_with_nothing_left_publishes_no_record() -> None:
    games = [_game(2, "GB", "MIN", day=date(2026, 9, 20))]
    assert _matchups(games, as_of=_RETRIEVED) == {}


def test_records_validate_and_pass_the_mirror_checks() -> None:
    games = [
        _game(3, "LAC", "BUF", day=date(2026, 9, 27), spread=7.0, total=50.5),
        _game(3, "NYJ", "NE", day=date(2026, 9, 27)),
    ]
    records = list(_matchups(games, as_of=_RETRIEVED).values())
    schema = validate_records("team_matchup", records, stage="test")
    assert not any(check.blocking for check in schema), [c.observed for c in schema]
    assert [check.check_id for check in _matchup_checks(records, "test")] == [
        "team_matchups.well_formed",
    ]


def test_the_validator_catches_a_spread_read_the_wrong_way_round() -> None:
    games = [_game(3, "LAC", "BUF", day=date(2026, 9, 27), spread=7.0, total=50.5)]
    records = list(_matchups(games, as_of=_RETRIEVED).values())
    flipped = [dict(record) for record in records]
    for record in flipped:
        if record["team"] == "LAC":
            record["team_expected_margin"] = 7.0
    ids = {check.check_id for check in _matchup_checks(flipped, "test")}
    assert "team_matchups.sides_disagree" in ids
    assert "team_matchups.implied_points_disagree" in ids


def test_the_schedule_adapter_reads_context_columns_and_nulls_what_is_absent() -> None:
    adapter = NflverseScheduleAdapter()
    raw = [
        {
            "game_id": "2026_03_LAC_BUF",
            "season": 2026,
            "game_type": "REG",
            "week": 3,
            "gameday": "2026-09-27",
            "gametime": "13:00",
            "away_team": "LAC",
            "home_team": "BUF",
            "spread_line": 7.0,
            "total_line": "NA",
            "away_rest": 7,
            "home_rest": 10,
            "roof": "outdoors",
            "location": "Home",
        },
    ]
    frame = adapter.normalize(raw).frame
    row = frame.row(0, named=True)
    assert row["spread_line"] == 7.0
    assert row["total_line"] is None
    assert row["home_rest"] == 10


# ------------------------------------------------------------------------------ firewall


def _published_signal_fields() -> set[str]:
    fields: set[str] = set()
    for name in ("team_matchup", "player_usage"):
        schema = json.loads((schemas_dir() / f"{name}.schema.json").read_text(encoding="utf-8"))
        fields |= set(schema["properties"])
    return fields - {
        "schema_version",
        "build_id",
        "season",
        "through_week",
        "player_id",
        "display_name",
        "position",
        "team",
        "week",
    }


@pytest.mark.parametrize(
    "field",
    [
        "total_line",
        "team_expected_margin",
        "implied_team_points",
        "implied_opponent_points",
        "spread_line",
    ],
)
def test_every_sportsbook_field_is_refused_as_a_feature_name(field: str) -> None:
    assert forbidden_reason(field) is not None


def test_no_model_feature_is_a_field_the_signal_layer_publishes() -> None:
    selection = ros_feature_selection()
    model_inputs = {
        *selection.preseason,
        *selection.in_season,
        *(spec.name for spec in FEATURE_DICTIONARY),
    }
    assert not model_inputs & _published_signal_fields()
    assert not [name for name in model_inputs if forbidden_reason(name) is not None]
