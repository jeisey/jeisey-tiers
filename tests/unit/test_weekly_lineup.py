"""Lagged starters and who is missing: point-in-time, confirmed vs uncertain, null when unknown."""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.weekly.lineup import (
    absence_lists,
    designations_for_week,
    health_features,
    lagged_starters,
    recent_usage_shares,
    team_health,
)


def _snap(week: int, team: str, gsis: str, position: str, offense: float, defense: float = 0.0):
    return {
        "season": 2025,
        "week": week,
        "game_type": "REG",
        "gsis_id": gsis,
        "player_name": f"P {gsis}",
        "position": position,
        "team": team,
        "offense_pct": offense,
        "defense_pct": defense,
    }


def _snaps(extra: list[dict[str, object]] | None = None) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for week in (1, 2, 3, 4):
        # BUF's line: five regulars, a sixth man who played only in week 1.
        for index in range(5):
            rows.append(_snap(week, "BUF", f"OL{index}", "T" if index < 2 else "G", 1.0))
        rows.append(_snap(week, "BUF", "QB1", "QB", 1.0))
        # MIA's secondary: three corners, two safeties, a fill-in corner at 0.2.
        for index in range(3):
            rows.append(_snap(week, "MIA", f"CB{index}", "CB", 0.0, 0.9 - index * 0.1))
        rows.append(_snap(week, "MIA", "CBX", "CB", 0.0, 0.2))
        rows.append(_snap(week, "MIA", "S0", "FS", 0.0, 1.0))
        rows.append(_snap(week, "MIA", "S1", "SS", 0.0, 0.95))
    rows.append(_snap(1, "BUF", "OL9", "G", 1.0))
    rows.extend(extra or [])
    return pl.DataFrame(rows)


def _report(rows: list[tuple[str, str, str | None]], week: int = 5) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "season": 2025,
                "week": week,
                "gsis_id": gsis,
                "team": team,
                "position": "T",
                "full_name": f"Name {gsis}",
                "report_status": status,
                "practice_status": None,
                "primary_injury": "Knee",
            }
            for gsis, team, status in rows
        ],
        schema={
            "season": pl.Int32,
            "week": pl.Int32,
            "gsis_id": pl.String,
            "team": pl.String,
            "position": pl.String,
            "full_name": pl.String,
            "report_status": pl.String,
            "practice_status": pl.String,
            "primary_injury": pl.String,
        },
    )


def test_starters_are_the_top_snap_shares_over_the_last_three_games() -> None:
    starters = lagged_starters(_snaps(), season=2025, through_week=4)
    ol = starters.filter((pl.col("team") == "BUF") & (pl.col("group") == "OL"))
    assert sorted(ol.get_column("gsis_id").to_list()) == [f"OL{i}" for i in range(5)]
    corners = starters.filter((pl.col("team") == "MIA") & (pl.col("group") == "CB"))
    # The 0.2 fill-in is below the starter line, and the three regulars rank by share.
    assert corners.sort("starter_rank").get_column("gsis_id").to_list() == ["CB0", "CB1", "CB2"]
    assert starters.filter(pl.col("gsis_id") == "OL9").is_empty()


def test_a_missed_game_counts_as_zero_in_the_window() -> None:
    snaps = _snaps().filter(~((pl.col("gsis_id") == "OL0") & (pl.col("week") >= 3)))
    starters = lagged_starters(snaps, season=2025, through_week=4)
    share = starters.filter(pl.col("gsis_id") == "OL0").get_column("share").to_list()
    assert share == [] or share == [pytest.approx(1 / 3)]


def test_the_future_cannot_reach_a_starter() -> None:
    """Weeks after the cutoff are deleted first; adding them changes nothing."""
    future = [_snap(5, "BUF", "NEW", "T", 1.0), _snap(6, "BUF", "NEW", "T", 1.0)]
    before = lagged_starters(_snaps(), season=2025, through_week=4)
    after = lagged_starters(_snaps(future), season=2025, through_week=4)
    assert before.equals(after)


def test_confirmed_and_uncertain_designations_are_counted_apart() -> None:
    starters = lagged_starters(_snaps(), season=2025, through_week=4)
    report = designations_for_week(
        _report(
            [
                ("OL0", "BUF", "Out"),
                ("OL1", "BUF", "Doubtful"),
                ("OL2", "BUF", "Questionable"),
                ("CB0", "MIA", "Out"),
                ("S1", "MIA", "Questionable"),
                ("CB1", "MIA", None),
            ],
        ),
        season=2025,
        week=5,
    )
    health = {row["team"]: row for row in team_health(starters, report, ["BUF", "MIA"]).to_dicts()}
    assert health["BUF"]["own_ol_out"] == 2.0
    assert health["BUF"]["own_ol_questionable"] == 1.0
    assert health["BUF"]["own_qb_out"] == 0.0
    assert health["MIA"]["def_cb_out"] == 1.0
    assert health["MIA"]["def_db_questionable"] == 1.0
    assert health["MIA"]["def_s_out"] == 0.0


def test_a_team_with_no_published_status_is_unknown_not_healthy() -> None:
    starters = lagged_starters(_snaps(), season=2025, through_week=4)
    # Practice participation only: no game status anywhere on BUF's report yet.
    report = designations_for_week(_report([("OL0", "BUF", None)]), season=2025, week=5)
    row = team_health(starters, report, ["BUF"]).row(0, named=True)
    assert row["report_final"] is False
    assert row["own_ol_out"] is None and row["def_cb_out"] is None


def _weekly(week: int, team: str, gsis: str, targets: float, carries: float = 0.0):
    return {
        "season": 2025,
        "week": week,
        "season_type": "REG",
        "gsis_id": gsis,
        "team": team,
        "targets": targets,
        "carries": carries,
    }


def test_vacated_targets_exclude_his_own_share_and_need_a_final_report() -> None:
    weekly = pl.DataFrame(
        [_weekly(week, "BUF", "WR1", 8) for week in (2, 3, 4)]
        + [_weekly(week, "BUF", "WR2", 4) for week in (2, 3, 4)]
        + [_weekly(week, "BUF", "TE1", 4) for week in (2, 3, 4)],
    )
    shares = recent_usage_shares(weekly, season=2025, through_week=4)
    assert shares.filter(pl.col("gsis_id") == "WR1").get_column("target_share_recent").item() == (
        pytest.approx(0.5)
    )
    rows = pl.DataFrame(
        {"gsis_id": ["WR2", "TE1"], "team": ["BUF", "BUF"], "opponent": ["MIA", "MIA"]},
    )
    report = _report([("WR1", "BUF", "Out"), ("TE1", "BUF", "Questionable")])
    attached = health_features(
        rows,
        snaps=_snaps(),
        weekly=weekly,
        injuries=report,
        season=2025,
        through_week=4,
        target_week=5,
    )
    wr2 = attached.filter(pl.col("gsis_id") == "WR2").row(0, named=True)
    te1 = attached.filter(pl.col("gsis_id") == "TE1").row(0, named=True)
    assert wr2["own_vacated_targets"] == pytest.approx(0.5)
    assert wr2["own_questionable_targets"] == pytest.approx(0.25)
    # TE1's own questionable share is not his own opportunity.
    assert te1["own_questionable_targets"] == pytest.approx(0.0)
    # MIA's report has no status at all: its defence is unknown, not healthy.
    assert wr2["opp_cb_out"] is None
    assert wr2["own_report_final"] is True and wr2["opp_report_final"] is False


def test_the_published_absence_list_names_listed_starters_first() -> None:
    starters = lagged_starters(_snaps(), season=2025, through_week=4)
    shares = pl.DataFrame(
        {
            "team": ["BUF"],
            "gsis_id": ["WR1"],
            "target_share_recent": [0.3],
            "carry_share_recent": [0.0],
        },
    )
    report = designations_for_week(
        _report([("WR1", "BUF", "Questionable"), ("OL3", "BUF", "Out")]),
        season=2025,
        week=5,
    )
    lists = absence_lists(starters, shares, report, ["BUF", "MIA"])
    names = [entry["player_id"] for entry in lists["BUF"]["listed"]]
    assert names == ["gsis:OL3", "gsis:WR1"]
    assert lists["BUF"]["listed"][0]["role"] == "OL4" or lists["BUF"]["listed"][0]["group"] == "OL"
    assert lists["MIA"] == {"report_final": False, "listed": []}
