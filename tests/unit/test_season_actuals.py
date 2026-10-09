"""`season_actuals_v1`: season-to-date points, games and positional ranks (ADR-105).

Each claim a surface leans on when it prints "Season QB4", tested on its own:

* **points are the scoring engine's**, per preset, so a reception moves PPR and not STD and a
  preset can change a rank;
* **ranks are competition ranks over everyone who appeared** (1, 2, 2, 4), at the board's
  position, and do not depend on which players a board publishes;
* **a game is a stats row or an offensive snap**; byes and missed weeks are not games, a
  traded player's two clubs are one season, and a negative or zero total still ranks;
* **no appearance is a known zero** with no rate and no rank, distinct from a missing record;
* **nothing after the cutoff counts**, and a missing team-week withholds rather than shrinks.
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.actuals_checks import actuals_cross_checks, actuals_record_checks
from ffdraft.artifacts.schemas import record_schema_version, validate_records
from ffdraft.config import load_app_config
from ffdraft.contracts import CheckStatus
from ffdraft.contracts.normalized import (
    SCHEDULE_CONTRACT,
    SNAP_COUNTS_CONTRACT,
    WEEKLY_STATS_CONTRACT,
)
from ffdraft.signals.actuals import build_season_actuals, competition_ranks

_SEASON = 2026
_TEAMS = ("MIN", "GB", "DET", "CHI")
_STAT_FIELDS = (
    "pass_attempts",
    "completions",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "passing_air_yards",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_air_yards",
    "fumbles_lost",
    "two_point_conversions",
)


def _stat(
    week: int,
    gsis: str,
    *,
    position: str = "WR",
    team: str = "MIN",
    **values: float,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "season": _SEASON,
        "week": week,
        "season_type": "REG",
        "gsis_id": gsis,
        "display_name": f"Player {gsis}",
        "position": position,
        "team": team,
        "opponent_team": None,
    }
    for name in _STAT_FIELDS:
        row[name] = float(values.get(name, 0.0))
    row["passing_epa"] = None
    row["sacks_suffered"] = 0.0
    return row


def _snap(
    week: int, gsis: str | None, *, team: str = "MIN", position: str = "WR"
) -> dict[str, Any]:
    return {
        "season": _SEASON,
        "week": week,
        "game_type": "REG",
        "pfr_player_id": f"pfr-{gsis}-{team}-{week}",
        "player_name": f"Player {gsis}",
        "position": position,
        "team": team,
        "offense_snaps": 30.0,
        "offense_pct": 0.5,
        "gsis_id": gsis,
    }


def _schedule(weeks: int, byes: dict[int, tuple[str, ...]] | None = None) -> pl.DataFrame:
    rows = []
    for week in range(1, weeks + 1):
        resting = set((byes or {}).get(week, ()))
        playing = [team for team in _TEAMS if team not in resting]
        for slot in range(0, len(playing) - 1, 2):
            rows.append(
                {
                    "game_id": f"{_SEASON}_{week:02d}_{playing[slot]}_{playing[slot + 1]}",
                    "season": _SEASON,
                    "game_type": "REG",
                    "week": week,
                    "gameday": None,
                    "gametime": None,
                    "away_team": playing[slot],
                    "home_team": playing[slot + 1],
                },
            )
    return SCHEDULE_CONTRACT.build(rows)


def _coverage(schedule: pl.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A depth player per scheduled team-week, in both sources, so coverage is complete."""
    stats: list[dict[str, Any]] = []
    snaps: list[dict[str, Any]] = []
    for row in schedule.iter_rows(named=True):
        for team in (row["home_team"], row["away_team"]):
            gsis = f"00-99{_TEAMS.index(team):05d}"
            stats.append(_stat(int(row["week"]), gsis, team=team, position="OL"))
            snaps.append(_snap(int(row["week"]), gsis, team=team, position="OL"))
    return stats, snaps


def _build(
    stats: list[dict[str, Any]],
    snaps: list[dict[str, Any]] | None = None,
    *,
    through_week: int,
    schedule: pl.DataFrame | None = None,
    positions: dict[str, str] | None = None,
    include: tuple[str, ...] = (),
    complete: bool = True,
) -> Any:
    plan = schedule if schedule is not None else _schedule(through_week + 1)
    filler_stats, filler_snaps = _coverage(plan) if complete else ([], [])
    snap_rows = [*(snaps or []), *filler_snaps]
    snap_frame = SNAP_COUNTS_CONTRACT.build(
        [{k: v for k, v in row.items() if k != "gsis_id"} for row in snap_rows],
    ).with_columns(
        pl.Series("gsis_id", [row["gsis_id"] for row in snap_rows], dtype=pl.String),
    )
    return build_season_actuals(
        weekly=WEEKLY_STATS_CONTRACT.build([*stats, *filler_stats]),
        snap_counts=snap_frame,
        schedule=plan,
        scoring=load_app_config().league.scoring,
        season=_SEASON,
        through_week=through_week,
        positions=positions or {},
        include=include,
        build_id="test",
        schema_version=record_schema_version("season_actuals_record"),
    )


def _row(result: Any, gsis: str, preset: str = "PPR") -> dict[str, Any]:
    matches = [
        r
        for r in result.records
        if r["player_id"] == f"gsis:{gsis}" and r["scoring_preset"] == preset
    ]
    assert len(matches) == 1, f"{gsis}/{preset}: {len(matches)} record(s)"
    return matches[0]


# ------------------------------------------------------------------------------- ranks


def test_competition_ranks_share_the_best_place():
    assert competition_ranks({"a": 900, "b": 800, "c": 800, "d": 700}) == {
        "a": 1,
        "b": 2,
        "c": 2,
        "d": 4,
    }


def test_points_come_from_the_scoring_engine_and_a_preset_can_change_a_rank():
    # A: 100 yards and no catches. B: 80 yards on 8 catches. STD: A 10.0 > B 8.0.
    # PPR: B 16.0 > A 10.0. HALF: B 12.0 > A 10.0.
    stats = [
        _stat(1, "00-0000001", receiving_yards=100.0),
        _stat(1, "00-0000002", receiving_yards=80.0, receptions=8.0, team="GB"),
    ]
    result = _build(stats, through_week=1)
    assert result.published
    assert _row(result, "00-0000001", "STD")["points"] == 10.0
    assert _row(result, "00-0000002", "PPR")["points"] == 16.0
    assert _row(result, "00-0000002", "HALF")["points"] == 12.0
    assert _row(result, "00-0000001", "STD")["season_position_rank"] == 1
    assert _row(result, "00-0000001", "PPR")["season_position_rank"] == 2
    assert _row(result, "00-0000002", "PPR")["season_position_rank"] == 1


def test_ties_negative_and_zero_totals_rank_together():
    stats = [
        _stat(1, "00-0000001", position="QB", passing_yards=250.0),  # 10.0
        _stat(1, "00-0000002", position="QB", passing_yards=250.0, team="GB"),  # 10.0
        _stat(1, "00-0000003", position="QB", team="DET"),  # 0.0 — appeared
        _stat(1, "00-0000004", position="QB", interceptions=1.0, team="CHI"),  # -2.0
    ]
    result = _build(stats, through_week=1)
    ranks = {
        gsis: _row(result, gsis)["season_position_rank"]
        for gsis in ("00-0000001", "00-0000002", "00-0000003", "00-0000004")
    }
    assert ranks == {"00-0000001": 1, "00-0000002": 1, "00-0000003": 3, "00-0000004": 4}
    assert _row(result, "00-0000004")["points"] == -2.0
    assert _row(result, "00-0000003")["points_per_game"] == 0.0


def test_precision_is_applied_before_ranking():
    # 0.1 + 0.2 in floating point is not 0.3; at the declared precision it is, so they tie.
    stats = [
        _stat(1, "00-0000001", rushing_yards=1.0),
        _stat(2, "00-0000001", rushing_yards=2.0),
        _stat(1, "00-0000002", rushing_yards=3.0, team="GB"),
    ]
    result = _build(
        stats, through_week=2, positions={"gsis:00-0000001": "RB", "gsis:00-0000002": "RB"}
    )
    assert _row(result, "00-0000001")["points"] == _row(result, "00-0000002")["points"] == 0.3
    assert _row(result, "00-0000001")["season_position_rank"] == 1
    assert _row(result, "00-0000002")["season_position_rank"] == 1


def test_ranks_do_not_depend_on_which_players_a_board_publishes():
    stats = [
        _stat(1, "00-0000001", receiving_yards=150.0),  # off every board, and the leader
        _stat(1, "00-0000002", receiving_yards=90.0, team="GB"),
    ]
    narrow = _build(stats, through_week=1, include=("gsis:00-0000002",))
    wide = _build(stats, through_week=1, include=("gsis:00-0000001", "gsis:00-0000002"))
    assert _row(narrow, "00-0000002")["season_position_rank"] == 2
    assert narrow.records == wide.records
    assert narrow.metadata["population"]["WR"] == 2


def test_the_board_position_is_the_standing():
    stats = [
        _stat(1, "00-0000001", position="TE", receiving_yards=100.0),
        _stat(1, "00-0000002", position="RB", receiving_yards=50.0, team="GB"),
    ]
    result = _build(stats, through_week=1, positions={"gsis:00-0000001": "RB"})
    assert _row(result, "00-0000001")["position"] == "RB"
    assert _row(result, "00-0000001")["season_position_rank"] == 1
    assert _row(result, "00-0000002")["season_position_rank"] == 2
    assert result.metadata["population"] == {"QB": 0, "RB": 2, "WR": 0, "TE": 0}


# ------------------------------------------------------------------------------- games


def test_byes_and_missed_weeks_are_not_games():
    schedule = _schedule(4, byes={2: ("MIN", "GB")})
    stats = [
        _stat(1, "00-0000001", receiving_yards=60.0),
        # week 2: MIN on bye; week 3: MIN played, he did not
        _stat(4, "00-0000001", receiving_yards=40.0),
    ]
    result = _build(stats, through_week=4, schedule=schedule)
    row = _row(result, "00-0000001")
    assert row["games_played"] == 2
    assert row["points"] == 10.0
    assert row["points_per_game"] == 5.0


def test_a_snaps_only_week_is_a_game_with_zero_points():
    stats = [_stat(1, "00-0000001", receiving_yards=60.0)]
    snaps = [_snap(1, "00-0000001"), _snap(2, "00-0000001")]
    result = _build(stats, snaps, through_week=2)
    row = _row(result, "00-0000001")
    assert row["games_played"] == 2
    assert row["points_per_game"] == 3.0
    assert result.metadata["coverage"]["snap_only_appearances"] == 1


def test_a_traded_player_is_one_season_across_both_clubs():
    stats = [
        _stat(1, "00-0000001", team="MIN", receiving_yards=50.0),
        _stat(2, "00-0000001", team="GB", receiving_yards=70.0),
    ]
    result = _build(stats, through_week=2)
    row = _row(result, "00-0000001")
    assert row["games_played"] == 2
    assert row["points"] == 12.0
    assert len([r for r in result.records if r["player_id"] == "gsis:00-0000001"]) == 3


def test_a_board_player_with_no_appearance_is_a_known_zero():
    stats = [_stat(1, "00-0000001", receiving_yards=60.0)]
    result = _build(
        stats,
        through_week=1,
        positions={"gsis:00-0000009": "WR"},
        include=("gsis:00-0000009", "gsis:00-0000001", "sleeper:123"),
    )
    row = _row(result, "00-0000009")
    assert (row["games_played"], row["points"]) == (0, 0.0)
    assert row["points_per_game"] is None
    assert row["season_position_rank"] is None
    assert result.metadata["population"]["WR"] == 1
    # A non-canonical id has no weekly rows by construction: no record, rather than a fake zero.
    assert not any(r["player_id"] == "sleeper:123" for r in result.records)


# ------------------------------------------------------------------------------ cutoff


def test_a_thursday_game_after_the_cutoff_is_not_counted():
    stats = [
        _stat(1, "00-0000001", receiving_yards=60.0),
        _stat(2, "00-0000001", receiving_yards=200.0),  # next week's Thursday game
    ]
    snaps = [_snap(2, "00-0000002")]  # a snaps-only appearance after the cutoff, too
    result = _build(stats, snaps, through_week=1)
    row = _row(result, "00-0000001")
    assert (row["games_played"], row["points"]) == (1, 6.0)
    assert not any(r["player_id"] == "gsis:00-0000002" for r in result.records)
    assert result.metadata["weeks"] == [1]


def test_a_missing_team_week_in_the_snap_counts_withholds_everything():
    schedule = _schedule(2)
    stats, snaps = _coverage(schedule)
    snaps = [row for row in snaps if not (row["week"] == 2 and row["team"] == "CHI")]
    stats.append(_stat(1, "00-0000001", receiving_yards=60.0))
    result = _build(stats, snaps, through_week=2, schedule=schedule, complete=False)
    assert not result.published
    assert result.records == []
    assert "week 2 snap counts missing CHI" in result.metadata["withheld_reason"]
    assert result.checks[0].check_id == "season_actuals.incomplete_sources"
    assert result.checks[0].severity.value == "warning"


def test_a_missing_team_week_in_the_weekly_stats_withholds_everything():
    schedule = _schedule(1)
    stats, snaps = _coverage(schedule)
    stats = [row for row in stats if row["team"] != "DET"]
    result = _build(stats, snaps, through_week=1, schedule=schedule, complete=False)
    assert not result.published
    assert "weekly stats missing DET" in result.metadata["withheld_reason"]


def test_unbridged_snap_rows_fail_closed_and_are_counted():
    stats = [_stat(1, "00-0000001", receiving_yards=60.0)]
    result = _build(stats, [_snap(1, None)], through_week=1)
    assert result.published
    assert result.metadata["coverage"]["unbridged_snap_rows"] == 1


# --------------------------------------------------------------------------- contract


def test_every_record_is_schema_valid_and_rederivable():
    stats = [
        _stat(1, "00-0000001", position="QB", passing_yards=250.0),
        _stat(1, "00-0000002", position="QB", passing_yards=250.0, team="GB"),
        _stat(1, "00-0000003", receiving_yards=60.0, receptions=5.0, team="DET"),
    ]
    result = _build(
        stats, through_week=1, positions={"gsis:00-0000009": "TE"}, include=("gsis:00-0000009",)
    )
    assert not any(
        c.status is CheckStatus.FAIL
        for c in validate_records("season_actuals_record", result.records)
    )
    checks = actuals_record_checks(result.records, "test")
    assert all(c.status is CheckStatus.PASS for c in checks), [c.to_dict() for c in checks]


def test_the_validator_refuses_a_rank_it_cannot_rederive():
    stats = [
        _stat(1, "00-0000001", receiving_yards=100.0),
        _stat(1, "00-0000002", receiving_yards=50.0, team="GB"),
    ]
    records = [dict(r) for r in _build(stats, through_week=1).records]
    for record in records:
        if record["player_id"] == "gsis:00-0000002" and record["scoring_preset"] == "PPR":
            record["season_position_rank"] = 1
    failed = {
        c.check_id for c in actuals_record_checks(records, "test") if c.status is CheckStatus.FAIL
    }
    assert failed == {"season_actuals.rank_not_rederivable"}


def test_the_validator_refuses_a_rate_or_rank_on_a_player_who_has_not_appeared():
    stats = [_stat(1, "00-0000001", receiving_yards=60.0)]
    result = _build(
        stats, through_week=1, positions={"gsis:00-0000009": "WR"}, include=("gsis:00-0000009",)
    )
    records = [dict(r) for r in result.records]
    for record in records:
        if record["player_id"] == "gsis:00-0000009":
            record["points_per_game"] = 0.0
    failed = {
        c.check_id for c in actuals_record_checks(records, "test") if c.status is CheckStatus.FAIL
    }
    assert "season_actuals.nullness" in failed


@pytest.mark.parametrize(
    ("field", "value", "check_id"),
    [
        ("points_to_date", 99.0, "season_actuals.points_disagree"),
        ("position", "TE", "season_actuals.position_disagrees"),
        ("games_played_to_date", 5.0, "season_actuals.games_disagree"),
    ],
)
def test_the_boards_must_agree_with_the_actuals(field, value, check_id):
    stats = [_stat(1, "00-0000001", receiving_yards=60.0)]
    records = _build(stats, through_week=1).records
    board = {
        "scoring_preset": "PPR",
        "player_id": "gsis:00-0000001",
        "position": "WR",
        "points_to_date": 6.0,
        "games_played_to_date": 1.0,
        field: value,
    }
    envelopes = {"season_actuals": {"records": records}, "ros_tiers": {"records": [board]}}
    failed = {c.check_id for c in actuals_cross_checks(envelopes) if c.status is CheckStatus.FAIL}
    assert failed == {check_id}


def test_every_board_player_must_have_an_actuals_record():
    stats = [_stat(1, "00-0000001", receiving_yards=60.0)]
    records = _build(stats, through_week=1).records
    board = {"scoring_preset": "PPR", "player_id": "gsis:00-0000077", "position": "WR"}
    envelopes = {
        "season_actuals": {"records": records},
        "inseason_opportunity": {"records": [board]},
    }
    failed = {c.check_id for c in actuals_cross_checks(envelopes) if c.status is CheckStatus.FAIL}
    assert failed == {"season_actuals.board_player_missing"}


def test_a_linemans_snaps_are_not_counted_as_a_snaps_only_appearance():
    stats = [_stat(1, "00-0000001", receiving_yards=60.0)]
    result = _build(stats, [_snap(1, "00-0000050", position="T")], through_week=1)
    assert result.metadata["coverage"]["snap_only_appearances"] == 0
    assert not any(r["player_id"] == "gsis:00-0000050" for r in result.records)
