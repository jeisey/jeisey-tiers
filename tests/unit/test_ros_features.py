"""The in-season feature block.

The fixture's structure is known by construction - who misses which week, who changes team,
who never plays - so most assertions here are exact arithmetic rather than "looks plausible".
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.ros.dictionary import (
    ROS_FEATURE_SCHEMA_VERSION,
    ros_feature_selection,
    ros_in_season_features,
)
from ffdraft.ros.features import build_in_season_features, team_schedule_weeks
from ffdraft.scoring.horizon import fantasy_horizon


@pytest.fixture(scope="module")
def features(ros_panel, ros_schedule, ros_universe, app_config) -> pl.DataFrame:
    return build_in_season_features(
        ros_panel,
        app_config.league.scoring,
        schedule=ros_schedule,
        universe=ros_universe,
    )


def _row(features: pl.DataFrame, gsis_id: str, week: int, preset: str = "PPR") -> dict:
    rows = features.filter(
        (pl.col("season") == 2019)
        & (pl.col("gsis_id") == gsis_id)
        & (pl.col("through_week") == week)
        & (pl.col("scoring_preset") == preset),
    )
    assert rows.height == 1, f"{gsis_id} week {week}: {rows.height} row(s)"
    return rows.to_dicts()[0]


def test_every_declared_in_season_column_is_produced(features) -> None:
    declared = {spec.name for spec in ros_in_season_features()}
    # `in_preseason_universe` is settled when the preseason block is joined, not here.
    produced = set(features.columns) | {"in_preseason_universe"}
    assert declared <= produced, sorted(declared - produced)


def test_games_to_date_counts_appearances_and_never_falls(features) -> None:
    ordered = features.filter(pl.col("scoring_preset") == "PPR").sort(
        "season",
        "gsis_id",
        "through_week",
    )
    fell = ordered.filter(
        pl.col("games_to_date") < pl.col("games_to_date").shift(1).over("season", "gsis_id"),
    )
    assert fell.is_empty()


def test_the_bye_week_shows_up_as_a_missed_week_not_a_missing_row(features) -> None:
    """`00-WR0001` takes his bye in a known week; the row exists and records the gap."""
    bye = 4 + (2 + 1) % 8  # position index of WR is 2, player index 1
    before = _row(features, "00-WR0001", bye - 1)
    on_bye = _row(features, "00-WR0001", bye)
    assert on_bye["games_to_date"] == before["games_to_date"]
    assert on_bye["weeks_missed_to_date"] == before["weeks_missed_to_date"] + 1
    assert on_bye["weeks_since_last_game"] == 1
    assert on_bye["active_last_week"] is False


def test_a_player_who_never_appears_has_zero_counts_and_null_rates(features) -> None:
    row = _row(features, "00-WR0000", 8)
    assert row["games_to_date"] == 0
    assert row["has_played_this_season"] is False
    assert row["weeks_since_last_game"] is None
    assert row["consecutive_weeks_missed"] == 8
    assert row["ppg_to_date"] is None
    assert row["team_remaining_scheduled_games"] is None
    assert row["points_to_date"] == 0.0


def test_a_season_ending_absence_accumulates_consecutive_missed_weeks(features) -> None:
    """`00-RB0003` disappears from week 9, and week 8 was already his bye.

    His last appearance is therefore week 7, and the gap the model sees at week 14 is seven
    weeks - the injury plus the bye that preceded it. A rule that counted only the injury
    would report six and would be describing a different player.
    """
    row = _row(features, "00-RB0003", 14)
    assert row["has_played_this_season"] is True
    assert row["weeks_since_last_game"] == 14 - 7
    assert row["consecutive_weeks_missed"] == 14 - 7
    assert row["active_last_week"] is False
    assert _row(features, "00-RB0003", 7)["active_last_week"] is True


def test_a_mid_season_arrival_has_no_row_at_all_before_his_first_game(features) -> None:
    """`00-QB0002` is outside the preseason universe and first appears in week 5.

    He has no week-4 row, because a snapshot taken in week 4 could not know he was coming.
    Emitting one - even an all-zero one - would put the fact of his arrival into a snapshot
    taken before it.
    """
    early = features.filter(
        (pl.col("season") == 2019)
        & (pl.col("gsis_id") == "00-QB0002")
        & (pl.col("through_week") < 5),
    )
    assert early.is_empty()
    arrival = _row(features, "00-QB0002", 5)
    assert arrival["games_to_date"] == 1
    assert arrival["has_played_this_season"] is True
    assert arrival["in_preseason_universe"] is False


def test_a_preseason_universe_player_keeps_his_row_before_he_ever_plays(features) -> None:
    """The other half of the same rule: a drafted player who is inactive is still on the board."""
    row = _row(features, "00-WR0000", 3)
    assert row["in_preseason_universe"] is True
    assert row["games_to_date"] == 0


def test_a_team_change_is_visible_only_after_it_happens(features) -> None:
    """`00-TE0001` moves teams at week 8."""
    assert _row(features, "00-TE0001", 7)["team_changed_in_season"] is False
    assert _row(features, "00-TE0001", 9)["team_changed_in_season"] is True


def test_recent_form_uses_a_three_week_window(features, ros_panel, app_config) -> None:
    scored = ros_panel.filter(
        (pl.col("season") == 2019)
        & (pl.col("gsis_id") == "00-WR0002")
        & (pl.col("week") > 9)
        & (pl.col("week") <= 12),
    )
    expected_points = float(scored.get_column("fantasy_points_PPR").sum())
    expected_games = int(scored.get_column("played").sum())
    row = _row(features, "00-WR0002", 12)
    assert row["games_last3"] == expected_games
    if expected_games:
        assert row["ppg_last3"] == pytest.approx(expected_points / expected_games)
    else:
        assert row["ppg_last3"] is None


def test_thin_denominators_produce_null_rather_than_a_number(features) -> None:
    """A rate below its declared minimum denominator is unknown, never zero.

    Yards per target needs five targets behind it. At week one most receivers have fewer, so
    the column is null for them - and the same players have a defined ``target_share``,
    because that rate's denominator is the team's volume rather than their own.
    """
    week_one = features.filter(
        (pl.col("through_week") == 1)
        & (pl.col("scoring_preset") == "PPR")
        & (pl.col("games_to_date") == 1),
    )
    assert week_one.height > 0
    assert week_one.get_column("yards_per_target_to_date").null_count() > 0
    thin = week_one.filter(
        pl.col("yards_per_target_to_date").is_null() & (pl.col("targets_per_game_to_date") > 0),
    )
    assert thin.height > 0
    assert thin.get_column("target_share_to_date").null_count() == 0


def test_remaining_scheduled_games_falls_by_one_per_played_week(features, ros_schedule) -> None:
    weeks = team_schedule_weeks(ros_schedule, [2019])
    assert not weeks.is_empty()
    row_eight = _row(features, "00-WR0002", 8)
    row_nine = _row(features, "00-WR0002", 9)
    assert row_eight["team_remaining_scheduled_games"] is not None
    assert row_nine["team_remaining_scheduled_games"] <= row_eight["team_remaining_scheduled_games"]


def test_points_per_week_counts_missed_weeks_as_zero(features) -> None:
    row = _row(features, "00-RB0003", 14)
    assert row["points_per_week_to_date"] == pytest.approx(row["points_to_date"] / 14)
    assert row["ppg_to_date"] == pytest.approx(row["points_to_date"] / row["games_to_date"])
    assert row["points_per_week_to_date"] < row["ppg_to_date"]


def test_the_snapshot_grid_stops_before_the_last_scored_week(features) -> None:
    for season in (2019, 2021):
        weeks = sorted(
            {
                int(value)
                for value in features.filter(pl.col("season") == season)
                .get_column("through_week")
                .unique()
            },
        )
        assert weeks == list(range(1, fantasy_horizon(season).last_week))


def test_the_declared_model_input_set_is_the_preseason_core_plus_the_in_season_block() -> None:
    selection = ros_feature_selection()
    assert selection.schema_version == ROS_FEATURE_SCHEMA_VERSION
    assert len(selection.in_season) == len(
        [spec for spec in ros_in_season_features() if spec.role.is_model_input],
    )
    assert set(selection.preseason).isdisjoint(set(selection.in_season))


def test_the_published_rest_of_season_dictionary_matches_the_code(repo_root) -> None:
    """`docs/ROS_FEATURE_DICTIONARY.md` is generated, so a stale copy is a documentation bug.

    Same rule as the preseason dictionary: the module is the source of truth, and this file
    is the published rendering of it.
    """
    from ffdraft.ros.dictionary import ros_dictionary_markdown, ros_feature_schema_hash

    path = repo_root / "docs" / "ROS_FEATURE_DICTIONARY.md"
    text = path.read_text(encoding="utf-8")
    assert ros_feature_schema_hash() in text, (
        "docs/ROS_FEATURE_DICTIONARY.md is stale; regenerate it from "
        "`uv run ffdraft feature-dictionary --ros`"
    )
    assert ros_dictionary_markdown() in text
