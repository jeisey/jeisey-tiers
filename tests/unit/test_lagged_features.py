"""Lagged-aggregate tests.

Each aggregate is checked against an arithmetic expectation on a hand-built frame, because
"the number looks plausible" is exactly how an off-by-one lag survives review.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.config import load_league_config
from ffdraft.contracts import SNAP_COUNTS_CONTRACT, WEEKLY_STATS_CONTRACT
from ffdraft.features.lagged import (
    PASS_ATTEMPT_MINIMUM,
    RUSH_ATTEMPT_MINIMUM,
    TARGET_MINIMUM,
    expected_points_by_season,
    horizon_filter,
    player_season_usage,
    role_rank_by_season,
    snap_usage_by_season,
    team_games_by_season,
    team_season_context,
)
from ffdraft.scoring import STAT_COMPONENTS


@pytest.fixture(scope="module")
def scoring(repo_root):
    return load_league_config(repo_root / "config" / "league-defaults.yaml").scoring


def weekly(rows: list[dict[str, object]]) -> pl.DataFrame:
    defaults: dict[str, object] = {name: 0.0 for name in STAT_COMPONENTS}
    defaults.update(
        {
            "carries": 0.0,
            "targets": 0.0,
            "pass_attempts": 0.0,
            "completions": 0.0,
            "team": "AAA",
            "position": "WR",
            "season_type": "REG",
        },
    )
    return pl.DataFrame([{**defaults, **row} for row in rows])


# --------------------------------------------------------------------------------------
# Horizon filtering
# --------------------------------------------------------------------------------------


def test_the_horizon_filter_drops_the_excluded_week_and_the_postseason():
    frame = weekly(
        [
            {"season": 2024, "week": 1, "gsis_id": "a"},
            {"season": 2024, "week": 17, "gsis_id": "a"},
            {"season": 2024, "week": 18, "gsis_id": "a"},
            {"season": 2024, "week": 20, "gsis_id": "a", "season_type": "POST"},
            {"season": 2019, "week": 16, "gsis_id": "a"},
            {"season": 2019, "week": 17, "gsis_id": "a"},
        ],
    )
    kept = horizon_filter(frame)
    assert sorted(zip(kept.get_column("season"), kept.get_column("week"), strict=True)) == [
        (2019, 16),
        (2024, 1),
        (2024, 17),
    ]


def test_the_horizon_filter_also_respects_a_game_type_column():
    frame = pl.DataFrame(
        [
            {"season": 2024, "week": 3, "game_type": "REG"},
            {"season": 2024, "week": 3, "game_type": "WC"},
        ],
    )
    assert horizon_filter(frame).height == 1


# --------------------------------------------------------------------------------------
# Usage
# --------------------------------------------------------------------------------------


def test_usage_sums_only_horizon_weeks_and_computes_per_team_shares(scoring):
    frame = weekly(
        [
            # Two receivers on one team: 6 and 4 targets in week 1, 8 and 2 in week 2.
            {"season": 2024, "week": 1, "gsis_id": "a", "targets": 6.0, "receptions": 4.0},
            {"season": 2024, "week": 1, "gsis_id": "b", "targets": 4.0, "receptions": 3.0},
            {"season": 2024, "week": 2, "gsis_id": "a", "targets": 8.0, "receptions": 5.0},
            {"season": 2024, "week": 2, "gsis_id": "b", "targets": 2.0, "receptions": 2.0},
            # Week 18 is outside the horizon and must not move any share.
            {"season": 2024, "week": 18, "gsis_id": "a", "targets": 50.0},
        ],
    )
    usage = player_season_usage(frame, scoring)
    row_a = usage.filter(pl.col("gsis_id") == "a").to_dicts()[0]
    assert row_a["games"] == 2
    assert row_a["targets"] == pytest.approx(14.0)
    assert row_a["target_share"] == pytest.approx(14.0 / 20.0)
    assert row_a["primary_team"] == "AAA"


def test_share_denominators_only_count_the_weeks_a_player_played(scoring):
    """A player absent in week 2 must not be charged with his team's week-2 volume."""
    frame = weekly(
        [
            {"season": 2024, "week": 1, "gsis_id": "a", "targets": 5.0},
            {"season": 2024, "week": 1, "gsis_id": "b", "targets": 5.0},
            {"season": 2024, "week": 2, "gsis_id": "b", "targets": 20.0},
        ],
    )
    usage = player_season_usage(frame, scoring)
    row_a = usage.filter(pl.col("gsis_id") == "a").to_dicts()[0]
    assert row_a["target_share"] == pytest.approx(0.5)


def test_the_primary_team_is_the_one_the_player_appeared_for_most(scoring):
    frame = weekly(
        [
            {"season": 2024, "week": 1, "gsis_id": "a", "team": "AAA", "targets": 1.0},
            {"season": 2024, "week": 2, "gsis_id": "a", "team": "BBB", "targets": 1.0},
            {"season": 2024, "week": 3, "gsis_id": "a", "team": "BBB", "targets": 1.0},
        ],
    )
    usage = player_season_usage(frame, scoring)
    assert usage.to_dicts()[0]["primary_team"] == "BBB"


def test_usage_of_an_empty_frame_returns_the_declared_shape(scoring):
    empty = player_season_usage(WEEKLY_STATS_CONTRACT.empty(), scoring)
    assert empty.is_empty()
    assert "target_share" in empty.columns


# --------------------------------------------------------------------------------------
# Team context
# --------------------------------------------------------------------------------------


def schedule(rows: list[tuple[int, int, str, str, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "game_id": f"{season}_{week}_{away}_{home}",
                "season": season,
                "week": week,
                "game_type": game_type,
                "away_team": away,
                "home_team": home,
            }
            for season, week, game_type, away, home in rows
        ],
    )


def test_team_games_counts_both_clubs_and_excludes_the_final_week():
    frame = schedule(
        [
            (2024, 1, "REG", "AAA", "BBB"),
            (2024, 2, "REG", "BBB", "AAA"),
            (2024, 18, "REG", "AAA", "BBB"),
            (2024, 20, "WC", "AAA", "BBB"),
        ],
    )
    games = team_games_by_season(frame)
    assert set(games.get_column("team")) == {"AAA", "BBB"}
    assert games.get_column("team_games").to_list() == [2, 2]


def test_team_offensive_context_is_per_game(scoring):
    stats = weekly(
        [
            {"season": 2024, "week": 1, "gsis_id": "a", "carries": 20.0, "rushing_yards": 100.0},
            {"season": 2024, "week": 2, "gsis_id": "a", "carries": 10.0, "rushing_yards": 50.0},
        ],
    )
    games = schedule([(2024, 1, "REG", "AAA", "BBB"), (2024, 2, "REG", "BBB", "AAA")])
    context = team_season_context(stats, games)
    row = context.filter(pl.col("team") == "AAA").to_dicts()[0]
    assert row["team_carries_pg"] == pytest.approx(15.0)
    assert row["team_rush_yards_pg"] == pytest.approx(75.0)


def test_team_context_counts_a_touchdown_once():
    """A passing touchdown and the receiving touchdown it produced are one score."""
    stats = weekly(
        [
            {"season": 2024, "week": 1, "gsis_id": "qb", "passing_tds": 3.0},
            {"season": 2024, "week": 1, "gsis_id": "wr", "receiving_tds": 3.0},
            {"season": 2024, "week": 1, "gsis_id": "rb", "rushing_tds": 1.0},
        ],
    )
    games = schedule([(2024, 1, "REG", "AAA", "BBB")])
    row = team_season_context(stats, games).filter(pl.col("team") == "AAA").to_dicts()[0]
    assert row["team_offense_tds_pg"] == pytest.approx(4.0)


# --------------------------------------------------------------------------------------
# Snaps and role rank
# --------------------------------------------------------------------------------------


def snaps(rows: list[dict[str, object]]) -> pl.DataFrame:
    defaults = {"game_type": "REG", "position": "WR", "team": "AAA"}
    return pl.DataFrame([{**defaults, **row} for row in rows])


def test_snap_usage_resolves_through_the_pfr_bridge_and_drops_unmapped_rows():
    frame = snaps(
        [
            {
                "season": 2024,
                "week": 1,
                "pfr_player_id": "Known01",
                "player_name": "Known",
                "offense_snaps": 50.0,
                "offense_pct": 0.8,
            },
            {
                "season": 2024,
                "week": 1,
                "pfr_player_id": "Unknown1",
                "player_name": "Unknown",
                "offense_snaps": 50.0,
                "offense_pct": 0.8,
            },
        ],
    )
    usage = snap_usage_by_season(frame, {"Known01": "00-0000001"})
    assert usage.height == 1
    assert usage.to_dicts()[0]["gsis_id"] == "00-0000001"


def test_role_rank_orders_teammates_at_one_position_by_snaps(scoring):
    frame = snaps(
        [
            {
                "season": 2024,
                "week": 1,
                "pfr_player_id": f"Pfr{index:02d}",
                "player_name": f"P{index}",
                "offense_snaps": float(snap),
                "offense_pct": snap / 60.0,
            }
            for index, snap in enumerate((55, 30, 12), start=1)
        ],
    )
    bridge = {f"Pfr{index:02d}": f"00-000000{index}" for index in (1, 2, 3)}
    usage = snap_usage_by_season(frame, bridge)
    stats = weekly(
        [
            {"season": 2024, "week": 1, "gsis_id": f"00-000000{index}", "targets": 1.0}
            for index in (1, 2, 3)
        ],
    )
    ranks = role_rank_by_season(usage, player_season_usage(stats, scoring))
    assert dict(ranks.select("gsis_id", "role_rank").iter_rows()) == {
        "00-0000001": 1,
        "00-0000002": 2,
        "00-0000003": 3,
    }


def test_role_rank_of_an_empty_snap_frame_is_empty():
    empty_snaps = snap_usage_by_season(SNAP_COUNTS_CONTRACT.empty(), {})
    assert role_rank_by_season(empty_snaps, pl.DataFrame()).is_empty()


# --------------------------------------------------------------------------------------
# Expected points
# --------------------------------------------------------------------------------------


def test_expected_points_sum_over_horizon_weeks_only():
    frame = pl.DataFrame(
        [
            {
                "season": 2024,
                "week": 1,
                "gsis_id": "a",
                "position": "WR",
                "team": "AAA",
                "expected_points": 10.0,
                "points_over_expected": 1.0,
            },
            {
                "season": 2024,
                "week": 18,
                "gsis_id": "a",
                "position": "WR",
                "team": "AAA",
                "expected_points": 99.0,
                "points_over_expected": 9.0,
            },
        ],
    )
    aggregated = expected_points_by_season(frame)
    row = aggregated.to_dicts()[0]
    assert row["xfp_games"] == 1
    assert row["expected_points"] == pytest.approx(10.0)


def test_a_two_way_player_is_not_double_counted():
    """ffopportunity can emit one row per position for the same player-week."""
    frame = pl.DataFrame(
        [
            {
                "season": 2024,
                "week": 1,
                "gsis_id": "a",
                "position": "TE",
                "team": "AAA",
                "expected_points": 3.85,
                "points_over_expected": 0.0,
            },
            {
                "season": 2024,
                "week": 1,
                "gsis_id": "a",
                "position": "OLB",
                "team": "AAA",
                "expected_points": 3.78,
                "points_over_expected": 0.0,
            },
        ],
    )
    aggregated = expected_points_by_season(frame)
    assert aggregated.height == 1
    assert aggregated.to_dicts()[0]["expected_points"] == pytest.approx(3.85)


# --------------------------------------------------------------------------------------
# Minimum denominators
# --------------------------------------------------------------------------------------


def test_the_declared_minimum_denominators_are_the_documented_ones():
    assert (RUSH_ATTEMPT_MINIMUM, TARGET_MINIMUM, PASS_ATTEMPT_MINIMUM) == (20, 20, 100)
