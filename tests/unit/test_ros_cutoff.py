"""The rest-of-season cutoff rule.

Every property asserted here is a sentence from `docs/RELEASE2_ROADMAP.md` 11.1 turned into
an executable statement, because the cutoff is the whole leakage argument and a cutoff rule
that is only documented is a cutoff rule nobody checks.
"""

from __future__ import annotations

import pytest

from ffdraft.ros.cutoff import (
    FIRST_THROUGH_WEEK,
    ROS_CUTOFF_RULE_VERSION,
    RosCutoff,
    cutoff_rule_document,
    season_cutoffs,
)
from ffdraft.scoring.horizon import fantasy_horizon


@pytest.mark.parametrize("season", [2019, 2020, 2021, 2024])
def test_snapshots_run_from_week_one_to_the_penultimate_scored_week(season: int) -> None:
    horizon = fantasy_horizon(season)
    cutoffs = season_cutoffs(season)
    assert [cutoff.through_week for cutoff in cutoffs] == list(
        range(FIRST_THROUGH_WEEK, horizon.last_week),
    )


def test_week_zero_is_refused_because_it_is_the_preseason_model() -> None:
    with pytest.raises(ValueError, match="preseason"):
        RosCutoff(season=2023, through_week=0)


def test_a_snapshot_with_no_remaining_horizon_is_refused() -> None:
    horizon = fantasy_horizon(2023)
    with pytest.raises(ValueError, match="no remaining horizon"):
        RosCutoff(season=2023, through_week=horizon.last_week)


def test_observed_and_remaining_weeks_partition_the_horizon() -> None:
    cutoff = RosCutoff(season=2023, through_week=6)
    horizon = fantasy_horizon(2023)
    assert set(cutoff.observed_weeks) | set(cutoff.remaining_weeks) == set(horizon.weeks)
    assert not set(cutoff.observed_weeks) & set(cutoff.remaining_weeks)
    assert max(cutoff.observed_weeks) < min(cutoff.remaining_weeks)


def test_remaining_horizon_weeks_counts_calendar_weeks_not_games() -> None:
    cutoff = RosCutoff(season=2021, through_week=10)
    assert cutoff.remaining_horizon_weeks == fantasy_horizon(2021).last_week - 10
    assert cutoff.remaining_horizon_weeks == len(cutoff.remaining_weeks)


def test_the_horizon_shortens_before_2021() -> None:
    assert len(season_cutoffs(2019)) == 15
    assert len(season_cutoffs(2021)) == 16


def test_the_document_records_the_rule_and_the_grid() -> None:
    document = cutoff_rule_document([2020, 2021])
    assert document["cutoff_rule_version"] == ROS_CUTOFF_RULE_VERSION
    assert document["snapshots_per_season"] == {"2020": 15, "2021": 16}
    assert "through_week=0" in document["excluded_snapshot"]


def test_snapshot_ids_sort_in_week_order() -> None:
    ids = [cutoff.snapshot_id for cutoff in season_cutoffs(2022)]
    assert ids == sorted(ids)
    assert ids[0] == "2022w01"
