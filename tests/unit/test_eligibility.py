"""Preseason-universe tests (ADR-021, ADR-018).

The universe is the row list, and the row list is the leakage surface nobody looks at. These
tests pin what may put a player in it, what may not, and how the ADR-018 depth states are
resolved.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.anchors import anchor_for_kickoff, first_week1_kickoff
from ffdraft.contracts import DEPTH_CHART_CONTRACT
from ffdraft.contracts.enums import DepthChartEra
from ffdraft.features.eligibility import (
    CORE_POSITION_NAMES,
    DepthContextState,
    EligibilityBasis,
    ExclusionReason,
    TeamAtAnchorSource,
    UniverseEra,
    build_preseason_universe,
    depth_context_state,
    latest_pre_anchor_depth,
)
from ffdraft.sources.nflverse import NflverseDepthChartAdapter


@pytest.fixture(scope="module")
def anchors(historical_sources):
    schedule = historical_sources.sources.schedule
    return {
        season: anchor_for_kickoff(first_week1_kickoff(schedule, season)) for season in (2024, 2025)
    }


def universe(historical_sources, anchors, season: int):
    sources = historical_sources.sources
    return build_preseason_universe(
        season,
        anchor=anchors[season],
        prior_roster=sources.rosters[season - 1],
        draft_picks=sources.draft_picks,
        depth_chart=sources.depth_charts.get(season, DEPTH_CHART_CONTRACT.empty()),
        player_master=sources.player_master,
    )


# --------------------------------------------------------------------------------------
# Membership
# --------------------------------------------------------------------------------------


def test_every_membership_basis_is_one_of_the_three_documented_kinds(
    historical_sources,
    anchors,
):
    bases = set()
    for season in (2024, 2025):
        for value in universe(historical_sources, anchors, season).members.get_column(
            "eligibility_basis",
        ):
            bases.update(str(value).split("|"))
    assert bases <= {str(basis) for basis in EligibilityBasis}


def test_a_lagged_only_season_never_uses_a_depth_snapshot(historical_sources, anchors):
    built = universe(historical_sources, anchors, 2024)
    assert built.era is UniverseEra.LAGGED_ONLY
    assert not any(
        str(EligibilityBasis.DEPTH_SNAPSHOT_PRE_ANCHOR) in str(value)
        for value in built.members.get_column("eligibility_basis")
    )


def test_the_snapshot_era_admits_a_player_no_lagged_source_can_see(
    historical_sources,
    anchors,
):
    """The undrafted rookie exists only on the pre-anchor depth chart.

    He has no previous-season roster row and no draft pick, so a lagged-only universe cannot
    contain him. That is the era boundary the quality report has to make visible.
    """
    built = universe(historical_sources, anchors, 2025)
    row = built.members.filter(pl.col("gsis_id") == "00-0090006").to_dicts()
    assert row, "the snapshot-only rookie must be eligible in 2025"
    assert row[0]["eligibility_basis"] == str(EligibilityBasis.DEPTH_SNAPSHOT_PRE_ANCHOR)

    lagged = universe(historical_sources, anchors, 2024)
    assert lagged.members.filter(pl.col("gsis_id") == "00-0090006").is_empty()


def test_a_target_season_draftee_is_eligible_on_draft_capital_alone(
    historical_sources,
    anchors,
):
    built = universe(historical_sources, anchors, 2025)
    row = built.members.filter(pl.col("gsis_id") == "00-0090005").to_dicts()[0]
    assert str(EligibilityBasis.DRAFT_CLASS) in row["eligibility_basis"]
    assert row["team_at_anchor_source"] in {
        str(TeamAtAnchorSource.DRAFT_TEAM),
        str(TeamAtAnchorSource.DEPTH_SNAPSHOT_PRE_ANCHOR),
    }


def test_a_player_with_no_target_season_production_stays_eligible(
    historical_sources,
    anchors,
):
    """Eligibility cannot depend on what happened after the anchor.

    `Ghost Roster` never records a stat line in either target season. He was on the previous
    season's roster, so a preseason drafter would have seen him, and dropping him would make
    the training set a survivorship sample.
    """
    for season in (2024, 2025):
        built = universe(historical_sources, anchors, season)
        assert not built.members.filter(pl.col("gsis_id") == "00-0090007").is_empty()


# --------------------------------------------------------------------------------------
# Exclusions
# --------------------------------------------------------------------------------------


def test_a_non_core_position_is_excluded_with_its_real_position_recorded(
    historical_sources,
    anchors,
):
    built = universe(historical_sources, anchors, 2024)
    guard = built.exclusions.filter(pl.col("gsis_id") == "00-0090008").to_dicts()
    assert guard, "an offensive lineman must be excluded, not modelled"
    assert guard[0]["reason"] == str(ExclusionReason.NON_CORE_POSITION)
    assert guard[0]["detail"] == "G", "the ledger must say which position, not just 'unknown'"


def test_a_gsis_id_naming_two_players_fails_closed(historical_sources, anchors):
    """ADR-019's poisoned-key rule, on the roster collision the fixture carries."""
    built = universe(historical_sources, anchors, 2024)
    assert built.members.filter(pl.col("gsis_id") == "00-0090009").is_empty()
    excluded = built.exclusions.filter(pl.col("gsis_id") == "00-0090009").to_dicts()
    assert excluded[0]["reason"] == str(ExclusionReason.AMBIGUOUS_IDENTITY)


def test_every_member_carries_a_core_position(historical_sources, anchors):
    for season in (2024, 2025):
        positions = universe(historical_sources, anchors, season).members.get_column("position")
        assert set(positions.to_list()) <= set(CORE_POSITION_NAMES)


def test_members_are_unique_by_player(historical_sources, anchors):
    """A player rostered by two clubs last season is still one row this season."""
    for season in (2024, 2025):
        members = universe(historical_sources, anchors, season).members
        assert members.height == members.get_column("gsis_id").n_unique()


# --------------------------------------------------------------------------------------
# Depth snapshots
# --------------------------------------------------------------------------------------


def test_only_the_latest_snapshot_at_or_before_the_anchor_is_used(
    historical_sources,
    anchors,
):
    depth = historical_sources.sources.depth_charts[2025]
    kept = latest_pre_anchor_depth(depth, anchors[2025])
    assert not kept.is_empty()
    observed = kept.get_column("observed_at_utc").unique().to_list()
    assert len(observed) == 1
    assert observed[0] <= anchors[2025].anchor_at_utc
    # The fixture also carries a snapshot dated after the anchor; it must be gone.
    assert kept.height < depth.height


def test_a_weekly_era_depth_chart_contributes_nothing(historical_sources, anchors):
    weekly = historical_sources.sources.depth_charts[2024]
    assert weekly.get_column("era").unique().to_list() == [str(DepthChartEra.WEEKLY_PRE_2025)]
    assert latest_pre_anchor_depth(weekly, anchors[2024]).is_empty()


def test_a_return_specialist_slot_does_not_become_a_players_depth_rank(
    historical_sources,
    anchors,
):
    """The fixture lists the WR1 as punt returner with rank 1 at position `PR`.

    Choosing the globally shallowest rank would report a receiver's returner slot as his
    depth rank - a rank at a position this project does not model.
    """
    built = universe(historical_sources, anchors, 2025)
    row = built.members.filter(pl.col("gsis_id") == "00-0090001").to_dicts()[0]
    assert row["position"] == "WR"
    assert row["depth_rank_at_anchor"] == 1  # his WR rank, which happens to be 1 as well
    assert row["team_at_anchor_source"] == str(TeamAtAnchorSource.DEPTH_SNAPSHOT_PRE_ANCHOR)


def test_an_empty_depth_frame_is_handled(historical_sources, anchors):
    assert latest_pre_anchor_depth(DEPTH_CHART_CONTRACT.empty(), anchors[2025]).is_empty()


def test_the_adapter_and_the_filter_agree_on_the_era(historical_sources):
    adapter = NflverseDepthChartAdapter(season=2024)
    assert adapter.era is DepthChartEra.WEEKLY_PRE_2025
    assert NflverseDepthChartAdapter(season=2025).era is DepthChartEra.SNAPSHOT_2025_PLUS


# --------------------------------------------------------------------------------------
# ADR-018 states
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("observed", "prior", "expected"),
    [
        (True, True, DepthContextState.DEPTH_OBSERVED_AT_ANCHOR),
        (True, False, DepthContextState.DEPTH_OBSERVED_AT_ANCHOR),
        (False, True, DepthContextState.PRIOR_SEASON_ROLE_PROXY),
        (False, False, DepthContextState.DEPTH_UNAVAILABLE),
    ],
)
def test_the_three_depth_states_resolve_in_the_documented_order(observed, prior, expected):
    assert depth_context_state(depth_rank_observed=observed, prior_role_known=prior) is expected


def test_the_universe_era_switches_at_2025():
    assert UniverseEra.for_season(2024) is UniverseEra.LAGGED_ONLY
    assert UniverseEra.for_season(2025) is UniverseEra.SNAPSHOT_2025_PLUS
