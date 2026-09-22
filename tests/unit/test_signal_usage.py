"""`usage_signals_v1`: observed role and production, week by week (ADR-091).

The claims a card leans on when it draws a player's role, each tested on its own:

* **the change rule is latest appearance against the earlier average**, pooled for shares
  counted in team units and a per-game mean for snap share and raw attempts;
* **an absence is not a zero** — a bye and a missed week publish null metrics, and a week
  with snaps and no statistic is an appearance with genuine zeros;
* **the latest game never silently moves** — a metric missing from the latest game yields
  a null change rather than a comparison against an older game;
* **a reading below its sample minimum is withheld**, not printed from noise.
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.schemas import validate_records
from ffdraft.artifacts.validate import _usage_checks
from ffdraft.config import load_app_config
from ffdraft.contracts.normalized import (
    SCHEDULE_CONTRACT,
    SNAP_COUNTS_CONTRACT,
    WEEKLY_STATS_CONTRACT,
)
from ffdraft.signals.usage import (
    ROLE_CHANGE_METRICS,
    USAGE_RULE,
    build_player_usage_records,
    current_teams_from_roster,
)

_SEASON = 2026
_PLAYER = "gsis:00-0000001"
_GSIS = "00-0000001"


def _stat(week: int, gsis: str = _GSIS, team: str = "MIN", **values: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "season": _SEASON,
        "week": week,
        "season_type": "REG",
        "gsis_id": gsis,
        "display_name": gsis,
        "position": "RB",
        "team": team,
        "opponent_team": None,
    }
    for name in (
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
    ):
        row[name] = float(values.get(name, 0.0))
    row["passing_epa"] = values.get("passing_epa")
    row["sacks_suffered"] = values.get("sacks_suffered", 0.0)
    return row


def _teammate(week: int, team: str = "MIN", **values: float) -> dict[str, Any]:
    """The rest of the team in one row, so team totals are what a test says they are."""
    return _stat(week, gsis="00-0009999", team=team, **values)


def _snap(week: int, pct: float, snaps: float = 40.0, gsis: str = _GSIS) -> dict[str, Any]:
    return {
        "season": _SEASON,
        "week": week,
        "game_type": "REG",
        "pfr_player_id": f"pfr{gsis}",
        "player_name": gsis,
        "position": "RB",
        "team": "MIN",
        "offense_snaps": snaps,
        "offense_pct": pct,
        "gsis_id": gsis,
    }


def _schedule(weeks: int = 4, bye: int | None = None) -> pl.DataFrame:
    rows = []
    for week in range(1, weeks + 1):
        if week == bye:
            continue
        rows.append(
            {
                "game_id": f"{_SEASON}_{week:02d}_GB_MIN",
                "season": _SEASON,
                "game_type": "REG",
                "week": week,
                "gameday": None,
                "gametime": None,
                "away_team": "GB",
                "home_team": "MIN",
            },
        )
    return SCHEDULE_CONTRACT.build(rows)


def _build(
    stats: list[dict[str, Any]],
    snaps: list[dict[str, Any]],
    *,
    through_week: int,
    schedule: pl.DataFrame | None = None,
    players: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    weekly = WEEKLY_STATS_CONTRACT.build(stats)
    snap_frame = SNAP_COUNTS_CONTRACT.build(
        [{k: v for k, v in row.items() if k != "gsis_id"} for row in snaps],
    ).with_columns(pl.Series("gsis_id", [row["gsis_id"] for row in snaps], dtype=pl.String))
    records = build_player_usage_records(
        players=players or {_PLAYER: {"display_name": "Test Back", "position": "RB"}},
        weekly=weekly,
        snap_counts=snap_frame,
        schedule=schedule if schedule is not None else _schedule(),
        scoring=load_app_config().league.scoring,
        season=_SEASON,
        through_week=through_week,
        build_id="test",
        schema_version="1.0",
    )
    assert len(records) == 1
    return records[0]


def test_a_rising_role_reads_as_latest_against_the_earlier_average() -> None:
    record = _build(
        [
            _stat(1, carries=4),
            _teammate(1, carries=16),
            _stat(2, carries=18),
            _teammate(2, carries=6),
        ],
        [_snap(1, 0.30), _snap(2, 0.81)],
        through_week=2,
    )
    snap = record["role_changes"]["snap_share"]
    assert snap == {
        "latest_week": 2,
        "latest": 0.81,
        "earlier": 0.3,
        "earlier_games": 1,
        "change": 0.51,
    }
    carry = record["role_changes"]["carry_share"]
    assert carry["latest"] == 0.75 and carry["earlier"] == 0.2 and carry["change"] == 0.55


def test_a_share_counted_in_team_units_is_pooled_and_snap_share_is_a_mean() -> None:
    record = _build(
        [
            _stat(1, targets=2),
            _teammate(1, targets=38),
            _stat(2, targets=10),
            _teammate(2, targets=20),
            _stat(3, targets=5),
            _teammate(3, targets=15),
        ],
        [_snap(1, 0.2), _snap(2, 0.6), _snap(3, 0.7)],
        through_week=3,
    )
    target = record["role_changes"]["target_share"]
    # Pooled over weeks 1-2: 12 of 70 targets. The mean of the two weekly shares would be
    # (0.05 + 0.333) / 2 = 0.192 and is deliberately not what is published.
    assert target["earlier"] == round(12 / 70, 3)
    assert target["latest"] == 0.25
    snap = record["role_changes"]["snap_share"]
    assert snap["earlier"] == 0.4  # mean of 0.2 and 0.6
    assert snap["change"] == pytest.approx(0.3)


def test_a_declining_role_has_a_negative_change() -> None:
    record = _build(
        [
            _stat(1, targets=9),
            _teammate(1, targets=21),
            _stat(2, targets=2),
            _teammate(2, targets=28),
        ],
        [_snap(1, 0.9), _snap(2, 0.45)],
        through_week=2,
    )
    assert record["role_changes"]["snap_share"]["change"] == -0.45
    assert record["role_changes"]["target_share"]["change"] < 0


def test_the_change_is_exactly_the_difference_of_the_published_numbers() -> None:
    record = _build(
        [
            _stat(1, targets=3),
            _teammate(1, targets=26),
            _stat(2, targets=7),
            _teammate(2, targets=24),
        ],
        [_snap(1, 0.333), _snap(2, 0.667)],
        through_week=2,
    )
    for change in record["role_changes"].values():
        if change is None or change["earlier"] is None:
            continue
        assert change["change"] == pytest.approx(change["latest"] - change["earlier"], abs=1e-9)


def test_a_bye_and_a_missed_week_are_absences_not_zeros() -> None:
    record = _build(
        [
            _stat(1, carries=10),
            _teammate(1, carries=10),
            _teammate(3, carries=20),
            _stat(4, carries=12),
            _teammate(4, carries=8),
        ],
        [_snap(1, 0.5), _snap(4, 0.6)],
        through_week=4,
        schedule=_schedule(bye=2),
    )
    statuses = [week["status"] for week in record["weeks"]]
    assert statuses == ["played", "bye", "did_not_play", "played"]
    for week in record["weeks"][1:3]:
        assert week["snap_share"] is None
        assert week["carry_share"] is None
        assert week["fantasy_points"] is None
    assert record["appearances"] == 2
    # The rule compares appearances, so week 4 is compared with week 1 alone.
    assert record["role_changes"]["snap_share"]["earlier_games"] == 1
    assert record["role_changes"]["snap_share"]["earlier"] == 0.5


def test_a_week_with_snaps_and_no_statistic_is_an_appearance_with_real_zeros() -> None:
    record = _build(
        [_stat(1, targets=5), _teammate(1, targets=25), _teammate(2, targets=30)],
        [_snap(1, 0.7), _snap(2, 0.75, snaps=50)],
        through_week=2,
    )
    week2 = record["weeks"][1]
    assert week2["status"] == "played"
    assert week2["target_share"] == 0.0
    assert week2["fantasy_points"] == {"HALF": 0.0, "PPR": 0.0, "STD": 0.0}
    assert record["role_changes"]["target_share"]["latest"] == 0.0


def test_a_metric_missing_from_the_latest_game_never_falls_back_to_an_older_one() -> None:
    record = _build(
        [
            _stat(1, carries=5),
            _teammate(1, carries=15),
            _stat(2, carries=9),
            _teammate(2, carries=11),
        ],
        [_snap(1, 0.4)],  # no snap row bridged for week 2
        through_week=2,
    )
    assert record["weeks"][1]["snap_share"] is None
    assert record["role_changes"]["snap_share"] is None
    assert record["role_changes"]["carry_share"]["latest_week"] == 2


def test_one_appearance_is_a_reading_and_not_a_change() -> None:
    record = _build(
        [_stat(1, carries=12), _teammate(1, carries=8)], [_snap(1, 0.6)], through_week=1
    )
    carry = record["role_changes"]["carry_share"]
    assert carry["latest"] == 0.6
    assert carry["earlier"] is None
    assert carry["change"] is None
    assert carry["earlier_games"] == 0


def test_a_player_who_never_appeared_has_every_change_null() -> None:
    record = _build([_teammate(1, carries=20)], [], through_week=1)
    assert record["appearances"] == 0
    assert all(change is None for change in record["role_changes"].values())
    assert set(record["role_changes"]) == set(ROLE_CHANGE_METRICS)


def test_weeks_after_the_cutoff_are_never_read() -> None:
    record = _build(
        [
            _stat(1, carries=5),
            _teammate(1, carries=15),
            _stat(3, carries=20),
            _teammate(3, carries=0),
        ],
        [_snap(1, 0.3), _snap(3, 1.0)],
        through_week=2,
    )
    assert [week["week"] for week in record["weeks"]] == [1, 2]
    assert record["role_changes"]["carry_share"]["latest_week"] == 1


def test_touchdown_share_is_per_preset_and_withheld_below_ten_points() -> None:
    # 60 rushing yards (6) + one rushing touchdown (6) + four receptions for 20 yards.
    record = _build(
        [
            _stat(
                1,
                carries=12,
                rushing_yards=60,
                rushing_tds=1,
                targets=4,
                receptions=4,
                receiving_yards=20,
            ),
            _teammate(1, carries=8, targets=26),
        ],
        [_snap(1, 0.6)],
        through_week=1,
    )
    share = record["touchdown_points_share"]
    assert share["STD"] == round(6 / 14, 4)
    assert share["PPR"] == round(6 / 18, 4)
    thin = _build(
        [_stat(1, carries=3, rushing_yards=20), _teammate(1, carries=17)],
        [_snap(1, 0.2)],
        through_week=1,
    )
    assert thin["touchdown_points_share"] == {"HALF": None, "PPR": None, "STD": None}


def test_epa_per_dropback_needs_twenty_dropbacks_and_skips_weeks_without_epa() -> None:
    passer = {_PLAYER: {"display_name": "Test Passer", "position": "QB"}}
    record = _build(
        [
            _stat(1, pass_attempts=30, sacks_suffered=2, passing_epa=8.0),
            _stat(2, pass_attempts=25, sacks_suffered=1),  # nflverse published no EPA
            _teammate(1),
            _teammate(2),
        ],
        [_snap(1, 1.0), _snap(2, 1.0)],
        through_week=2,
        players=passer,
    )
    assert record["dropbacks"] == 32.0
    assert record["pass_epa_per_dropback"] == 0.25
    backup = _build(
        [_stat(1, pass_attempts=12, passing_epa=3.0), _teammate(1)],
        [_snap(1, 0.2)],
        through_week=1,
        players=passer,
    )
    assert backup["pass_epa_per_dropback"] is None


def test_published_records_validate_and_pass_the_semantic_checks() -> None:
    record = _build(
        [
            _stat(1, carries=4),
            _teammate(1, carries=16),
            _stat(2, carries=18, rushing_tds=1),
            _teammate(2, carries=6),
        ],
        [_snap(1, 0.30), _snap(2, 0.81)],
        through_week=2,
    )
    schema = validate_records("player_usage", [record], stage="test")
    assert not any(check.blocking for check in schema), [c.observed for c in schema]
    semantic = _usage_checks([record], "test")
    assert [check.check_id for check in semantic] == ["player_usage.series_well_formed"]


def test_the_validator_refuses_a_zero_where_the_player_did_not_play() -> None:
    record = _build(
        [_stat(1, carries=4), _teammate(1, carries=16), _teammate(2, carries=20)],
        [_snap(1, 0.3)],
        through_week=2,
    )
    record["weeks"][1]["snap_share"] = 0.0
    checks = _usage_checks([record], "test")
    assert any(check.check_id == "player_usage.absence_published_as_a_value" for check in checks)


def test_the_validator_refuses_a_change_that_is_not_the_difference() -> None:
    record = _build(
        [
            _stat(1, carries=4),
            _teammate(1, carries=16),
            _stat(2, carries=18),
            _teammate(2, carries=6),
        ],
        [_snap(1, 0.3), _snap(2, 0.8)],
        through_week=2,
    )
    record["role_changes"]["snap_share"]["change"] = 0.9
    checks = _usage_checks([record], "test")
    assert any(check.check_id == "player_usage.change_is_not_the_difference" for check in checks)


def test_a_traded_player_has_no_single_current_team() -> None:
    roster = pl.DataFrame(
        {
            "gsis_id": ["00-1", "00-2", "00-2"],
            "team": ["MIN", "MIN", "DEN"],
        },
    )
    assert current_teams_from_roster(roster) == {"gsis:00-1": "MIN"}


def test_the_rule_declares_its_minimums() -> None:
    declared = USAGE_RULE.to_dict()
    assert declared["change_rule_version"] == "role_change_v1"
    assert declared["min_earlier_games"] == 1
