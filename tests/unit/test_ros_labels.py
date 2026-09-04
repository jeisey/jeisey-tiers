"""Rest-of-season labels, checked against an independent recomputation.

The builder computes the label with a reverse cumulative sum over a dense panel. These tests
recompute the same quantity the obvious way - filter to the weeks after the cutoff and add
them up - so the two paths have to agree. A windowing bug that shifted by one would pass a
test written against the builder's own arithmetic and fails here.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.ros.labels import ROS_LABEL_VERSION, build_ros_labels, reconcile_ros_labels
from ffdraft.ros.panel import horizon_weekly_rows
from ffdraft.scoring.engine import season_totals


@pytest.fixture(scope="module")
def labels(ros_panel, app_config) -> pl.DataFrame:
    return build_ros_labels(ros_panel, app_config.league.scoring)


def test_the_grain_is_one_row_per_snapshot_player_and_preset(labels, ros_panel) -> None:
    keys = ["season", "through_week", "gsis_id", "scoring_preset"]
    assert labels.select(keys).n_unique() == labels.height
    assert set(labels.get_column("scoring_preset").unique()) == {"STD", "HALF", "PPR"}
    assert labels.get_column("label_version").unique().to_list() == [ROS_LABEL_VERSION]


def test_remaining_points_equal_a_direct_sum_over_the_weeks_after_the_cutoff(
    labels,
    ros_weekly_stats,
    app_config,
) -> None:
    scoring = app_config.league.scoring
    scored = horizon_weekly_rows(ros_weekly_stats, [2019])
    from ffdraft.scoring.engine import score_weekly_frame

    weekly = score_weekly_frame(scored, scoring)
    for week in (1, 5, 9, 14):
        direct = (
            weekly.filter(pl.col("week") > week)
            .group_by("gsis_id")
            .agg(
                pl.col("fantasy_points_PPR").sum().alias("expected_points"),
                pl.len().cast(pl.Int32).alias("expected_games"),
            )
        )
        rows = labels.filter(
            (pl.col("season") == 2019)
            & (pl.col("through_week") == week)
            & (pl.col("scoring_preset") == "PPR"),
        ).join(direct, on="gsis_id", how="left")
        assert rows.height > 0
        mismatched = rows.filter(
            (pl.col("actual_remaining_points") - pl.col("expected_points").fill_null(0.0)).abs()
            > 1e-9,
        )
        assert mismatched.is_empty(), mismatched.head(3).to_dicts()
        assert rows.filter(
            pl.col("actual_remaining_games") != pl.col("expected_games").fill_null(0),
        ).is_empty()


def test_a_player_who_never_appears_scores_zero_rather_than_null(labels) -> None:
    never = labels.filter(pl.col("gsis_id") == "00-WR0000")
    assert never.height > 0
    assert never.get_column("actual_remaining_points").to_list() == [0.0] * never.height
    assert never.get_column("actual_remaining_games").to_list() == [0] * never.height
    assert never.get_column("actual_remaining_ppg").null_count() == never.height


def test_points_per_remaining_game_is_null_only_when_there_are_no_remaining_games(
    labels,
) -> None:
    assert labels.filter(
        (pl.col("actual_remaining_games") > 0) & pl.col("actual_remaining_ppg").is_null(),
    ).is_empty()
    assert labels.filter(
        (pl.col("actual_remaining_games") == 0) & pl.col("actual_remaining_ppg").is_not_null(),
    ).is_empty()


def test_the_split_reconciles_against_the_scoring_engines_season_total(
    labels,
    ros_weekly_stats,
    app_config,
) -> None:
    seasons = sorted({int(value) for value in labels.get_column("season").unique()})
    totals = season_totals(
        horizon_weekly_rows(ros_weekly_stats, seasons), app_config.league.scoring
    )
    checks = reconcile_ros_labels(labels, totals)
    assert checks
    assert all(check.status.value == "pass" for check in checks), [
        check.observed for check in checks if check.status.value != "pass"
    ]


def test_the_label_never_includes_the_excluded_final_nfl_week(
    labels,
    ros_weekly_stats,
    app_config,
) -> None:
    """The fixture gives every player a postseason row in the excluded week.

    A sum over *every* later row - postseason and excluded week included - must therefore be
    strictly larger than the label for at least one player. If the horizon filter ever
    stopped applying, the two would become equal and this test would fail.
    """
    from ffdraft.scoring.engine import score_weekly_frame

    scored = score_weekly_frame(
        ros_weekly_stats.filter(pl.col("season") == 2019),
        app_config.league.scoring,
    )
    unfiltered = (
        scored.filter(pl.col("week") > 1)
        .group_by("gsis_id")
        .agg(pl.col("fantasy_points_PPR").sum().alias("everything_after_week_one"))
    )
    rows = (
        labels.filter(
            (pl.col("season") == 2019)
            & (pl.col("through_week") == 1)
            & (pl.col("scoring_preset") == "PPR"),
        )
        .join(unfiltered, on="gsis_id", how="inner")
        .filter(pl.col("actual_remaining_games") > 0)
    )
    assert rows.height > 0
    difference = rows.select(
        (pl.col("everything_after_week_one") - pl.col("actual_remaining_points")).alias("d"),
    ).get_column("d")
    assert difference.min() >= -1e-9, "the label may never exceed an unfiltered sum"
    assert difference.max() > 1e-6, "nothing was excluded, so the horizon filter is not running"
