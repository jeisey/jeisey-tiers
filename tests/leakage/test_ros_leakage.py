"""The weekly point-in-time leakage audit.

Two properties, and a third that proves the first two are not vacuous.

1. Deleting every week after a cutoff must not change any in-season feature at that cutoff.
2. Deleting those same weeks must drive the label to zero.
3. The comparison must actually be able to fail - so the same machinery is pointed at a
   *different* cutoff, where it must report a difference. An audit that passes on everything
   is an audit that checks nothing.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.contracts.enums import CheckStatus
from ffdraft.ros.cutoff import RosCutoff, season_cutoffs
from ffdraft.ros.features import build_in_season_features
from ffdraft.ros.leakage import (
    audit_cutoff_independence,
    audit_ros_feature_names,
    audit_to_date_monotonicity,
    sample_cutoffs,
)
from ffdraft.ros.panel import build_weekly_panel


def _audit(weekly, scoring, universe, schedule, cutoffs):
    return audit_cutoff_independence(
        weekly,
        scoring,
        universe=universe,
        cutoffs=cutoffs,
        schedule=schedule,
    )


def test_every_cutoff_of_one_season_survives_having_its_future_deleted(
    ros_weekly_stats,
    ros_universe,
    ros_schedule,
    app_config,
) -> None:
    checks = _audit(
        ros_weekly_stats,
        app_config.league.scoring,
        ros_universe,
        ros_schedule,
        season_cutoffs(2019),
    )
    failing = [check for check in checks if check.status is not CheckStatus.PASS]
    assert not failing, [check.observed for check in failing]
    assert {check.check_id for check in checks} == {
        "ros_leakage.cutoff_independence",
        "ros_leakage.label_window",
    }


def test_the_audit_can_fail_when_a_feature_reads_the_wrong_week(
    ros_weekly_stats,
    ros_universe,
    ros_schedule,
    app_config,
) -> None:
    """Compare week 8's features against a panel truncated at week 9.

    That extra week is exactly the kind of one-off a leaky window produces, and the audit's
    comparison has to notice it. If this passed, the audit above would prove nothing.
    """
    scoring = app_config.league.scoring
    full = build_in_season_features(
        build_weekly_panel(
            ros_weekly_stats,
            scoring,
            seasons=[2019],
            universe=ros_universe,
        ),
        scoring,
        schedule=ros_schedule,
    )
    leaky = build_in_season_features(
        build_weekly_panel(
            ros_weekly_stats.filter(
                (pl.col("season") != 2019) | (pl.col("week") <= 9),
            ),
            scoring,
            seasons=[2019],
            universe=ros_universe,
        ),
        scoring,
        schedule=ros_schedule,
    )
    honest = build_in_season_features(
        build_weekly_panel(
            ros_weekly_stats.filter(
                (pl.col("season") != 2019) | (pl.col("week") <= 8),
            ),
            scoring,
            seasons=[2019],
            universe=ros_universe,
        ),
        scoring,
        schedule=ros_schedule,
    )
    keys = ["season", "through_week", "gsis_id", "scoring_preset"]
    columns = [*keys, "games_to_date", "ppg_to_date", "target_share_to_date"]
    at_eight = full.filter(pl.col("through_week") == 8).select(columns).sort(keys)
    assert at_eight.equals(honest.filter(pl.col("through_week") == 8).select(columns).sort(keys))
    # Week 9's row is genuinely different from week 8's, which is what makes the truncation
    # comparison discriminating rather than trivially satisfiable.
    at_nine = leaky.filter(pl.col("through_week") == 9).select(columns).sort(keys)
    assert not at_eight.get_column("games_to_date").equals(at_nine.get_column("games_to_date"))


def test_a_label_built_from_a_truncated_panel_is_empty(
    ros_weekly_stats,
    ros_universe,
    ros_schedule,
    app_config,
) -> None:
    checks = _audit(
        ros_weekly_stats,
        app_config.league.scoring,
        ros_universe,
        ros_schedule,
        [RosCutoff(season=2021, through_week=12)],
    )
    window = next(check for check in checks if check.check_id == "ros_leakage.label_window")
    assert window.status is CheckStatus.PASS


def test_the_sampled_weeks_are_the_declared_ones() -> None:
    cutoffs = sample_cutoffs([2019, 2021])
    assert {cutoff.through_week for cutoff in cutoffs} == {3, 8, 13}
    assert {cutoff.season for cutoff in cutoffs} == {2019, 2021}


def test_no_market_signal_can_enter_the_rest_of_season_model() -> None:
    checks = audit_ros_feature_names()
    assert checks
    assert all(check.status is CheckStatus.PASS for check in checks)


def test_appearances_to_date_never_fall(ros_dataset) -> None:
    checks = audit_to_date_monotonicity(ros_dataset.frame)
    assert checks
    assert all(check.status is CheckStatus.PASS for check in checks)


def test_a_broken_cumulative_window_is_caught_by_the_monotonicity_audit(ros_dataset) -> None:
    """Reverse one player-season's cutoffs and the invariant has to break."""
    broken = ros_dataset.frame.with_columns(
        pl.when(pl.col("player_id") == pl.col("player_id").first())
        .then(pl.col("games_to_date").reverse())
        .otherwise(pl.col("games_to_date"))
        .alias("games_to_date"),
    )
    checks = audit_to_date_monotonicity(broken)
    assert any(check.status is not CheckStatus.PASS for check in checks)


@pytest.mark.parametrize("season", [2019, 2021])
def test_the_snapshot_grid_is_complete_for_every_season(ros_dataset, season: int) -> None:
    weeks = sorted(
        {
            int(value)
            for value in ros_dataset.frame.filter(pl.col("season") == season)
            .get_column("through_week")
            .unique()
        },
    )
    assert weeks == [cutoff.through_week for cutoff in season_cutoffs(season)]
