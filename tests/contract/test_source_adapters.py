"""Adapter contract tests.

Two things are checked here that a normal unit test would miss.

First, **every adapter is tied back to Phase-0 evidence**: the columns an adapter reads must
exist in the schema the probe actually recorded from the live source
(`tests/fixtures/source_schemas/`). That turns "the adapter assumes a column" into a test
failure rather than a production surprise, and it is the mechanism that keeps
`docs/DATA_SOURCES.md` section 13 and this code honest about each other.

Second, the **measured upstream quirks** are asserted rather than trusted: MFL supplies no
standard deviation and no data-as-of time, Sleeper ids carry whitespace, depth charts have
two eras. Each of those is a Phase-0 measurement that a later refactor could quietly undo.
"""

from __future__ import annotations

import pytest

from ffdraft.contracts import DepthChartEra, EntityKind, SourceStatus
from ffdraft.market.cohorts import COHORT_APPROXIMATE, CohortAssignment, cohort_by_id, widest_cohort
from ffdraft.sources import (
    NflverseDepthChartAdapter,
    NflversePlayerIdsAdapter,
    NflverseRosterAdapter,
    SleeperPlayerAdapter,
    parse_sleeper_state,
)
from ffdraft.sources.market import (
    ADP_SD_UNAVAILABLE,
    SOURCE_AS_OF_UNAVAILABLE,
    MflAdpAdapter,
    MflPlayerDirectory,
    MflPlayerDirectoryAdapter,
    classify_mfl_entity,
)
from ffdraft.sources.nflverse_history import (
    NflverseCombineAdapter,
    NflverseDraftPickAdapter,
    NflverseExpectedPointsAdapter,
    NflversePlayerMasterAdapter,
    NflverseScheduleAdapter,
    NflverseSnapCountAdapter,
    NflverseWeeklyStatsAdapter,
)

ADAPTERS = [
    NflverseRosterAdapter(),
    NflversePlayerIdsAdapter(),
    NflverseDepthChartAdapter(season=2026),
    NflverseDepthChartAdapter(season=2024),
    SleeperPlayerAdapter(),
    MflAdpAdapter(),
    MflPlayerDirectoryAdapter(),
    # Phase-2 historical adapters. Their recorded schemas were captured by
    # `scripts/capture_source_schemas.py` in the same format Phase 0 used, so the
    # "adapters are tied to measured evidence" rule extends to them unchanged.
    NflverseWeeklyStatsAdapter(),
    NflverseSnapCountAdapter(),
    NflverseScheduleAdapter(),
    NflverseDraftPickAdapter(),
    NflverseCombineAdapter(),
    NflversePlayerMasterAdapter(),
    NflverseExpectedPointsAdapter(),
]


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: f"{a.source_id}:{a.resource}")
def test_required_columns_exist_in_the_phase0_recorded_schema(adapter, read_source_schema):
    recorded = read_source_schema(adapter.recorded_schema_fixture)
    available = {column["name"] for column in recorded["columns"]} or set(
        recorded.get("sample_rows", [{}])[0],
    )
    missing = adapter.required_source_columns - available
    assert not missing, (
        f"{adapter.source_id}/{adapter.resource} reads columns absent from the recorded "
        f"{adapter.recorded_schema_fixture} schema: {sorted(missing)}"
    )


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: f"{a.source_id}:{a.resource}")
def test_every_adapter_declares_its_contract_and_licence(adapter):
    assert adapter.source_id
    assert adapter.contract.contract_id
    assert adapter.contract.version
    assert adapter.license_policy_version, "the source metadata contract requires a policy version"


def test_missing_upstream_column_is_a_critical_schema_break():
    adapter = NflverseRosterAdapter()
    checks = adapter.check_source_schema([{"gsis_id": "00-0000001"}])
    assert any(check.check_id == "source_schema.missing_columns" for check in checks)
    assert any(check.blocking for check in checks)


# --------------------------------------------------------------------------------------
# nflverse
# --------------------------------------------------------------------------------------


def test_roster_normalization_drops_id_less_rows_and_counts_them(fixture_inputs):
    batch = NflverseRosterAdapter().normalize(fixture_inputs.roster, season=2026)
    assert "roster_rows_without_gsis_id" in batch.metadata.warning_codes
    assert batch.metadata.detail["roster_rows_without_gsis_id"] == "1"
    assert batch.frame.get_column("gsis_id").null_count() == 0


def test_roster_batch_conforms_to_its_contract(fixture_inputs):
    adapter = NflverseRosterAdapter()
    report = adapter.validate_raw(adapter.normalize(fixture_inputs.roster, season=2026))
    assert report.ok, [check.to_dict() for check in report.failures]


def test_roster_metadata_carries_the_source_metadata_contract(fixture_inputs):
    batch = NflverseRosterAdapter().normalize(fixture_inputs.roster, season=2026)
    metadata = batch.metadata.to_dict()
    for field in (
        "source_id",
        "retrieved_at_utc",
        "source_as_of_utc",
        "source_schema_version",
        "record_count",
        "content_hash",
        "status",
        "warning_codes",
        "license_policy_version",
    ):
        assert field in metadata, f"docs/DATA_SOURCES.md section 11 requires {field}"
    assert metadata["status"] == str(SourceStatus.WARNING)


def test_content_hash_is_stable_and_value_sensitive(fixture_inputs):
    adapter = NflverseRosterAdapter()
    first = adapter.normalize(fixture_inputs.roster, season=2026)
    second = adapter.normalize(fixture_inputs.roster, season=2026)
    assert first.metadata.content_hash == second.metadata.content_hash

    mutated = [dict(row) for row in fixture_inputs.roster]
    mutated[0]["team"] = "ZZZ"
    changed = adapter.normalize(mutated, season=2026)
    assert changed.metadata.content_hash != first.metadata.content_hash


def test_snapshot_era_depth_charts_carry_a_point_in_time_timestamp(fixture_inputs):
    adapter = NflverseDepthChartAdapter(season=2026)
    batch = adapter.normalize(fixture_inputs.depth_snapshot)
    assert adapter.era is DepthChartEra.SNAPSHOT_2025_PLUS
    assert batch.frame.get_column("observed_at_utc").null_count() == 0
    assert batch.metadata.source_as_of_utc is not None
    assert adapter.validate_raw(batch).ok


def test_weekly_era_depth_charts_never_claim_a_timestamp(fixture_inputs):
    """ADR-018: a pre-2025 row must not look like a point-in-time observation."""
    adapter = NflverseDepthChartAdapter(season=2024)
    batch = adapter.normalize(fixture_inputs.depth_weekly)
    assert adapter.era is DepthChartEra.WEEKLY_PRE_2025
    assert batch.frame.get_column("observed_at_utc").null_count() == batch.frame.height
    assert batch.metadata.source_as_of_utc is None
    assert batch.frame.get_column("week").to_list() == [1] * batch.frame.height

    checks = adapter.validate_raw(batch).checks
    assert any(check.check_id == "depth_chart.no_preseason_observation" for check in checks)
    assert adapter.validate_raw(batch).ok, "the era note is informational, not a failure"


def test_the_two_depth_eras_normalize_to_one_contract(fixture_inputs):
    snapshot = NflverseDepthChartAdapter(season=2026).normalize(fixture_inputs.depth_snapshot)
    weekly = NflverseDepthChartAdapter(season=2024).normalize(fixture_inputs.depth_weekly)
    assert snapshot.frame.columns == weekly.frame.columns
    assert snapshot.frame.schema == weekly.frame.schema


def test_depth_adapter_refuses_to_fetch_a_season_it_was_not_built_for():
    from ffdraft.sources import SourceConfig
    from ffdraft.timeutil import utc_now

    adapter = NflverseDepthChartAdapter(season=2026)
    with pytest.raises(ValueError, match="era determines the upstream schema"):
        adapter.fetch(as_of=utc_now(), config=SourceConfig(season=2024))


def test_player_ids_adapter_keys_on_mfl_id(fixture_inputs):
    adapter = NflversePlayerIdsAdapter()
    batch = adapter.normalize(fixture_inputs.player_ids)
    assert batch.frame.get_column("mfl_id").null_count() == 0
    assert adapter.validate_raw(batch).ok


# --------------------------------------------------------------------------------------
# Sleeper
# --------------------------------------------------------------------------------------


def test_sleeper_normalization_trims_ids_and_records_the_finding(fixture_inputs):
    batch = SleeperPlayerAdapter().normalize(fixture_inputs.sleeper_players)
    assert "whitespace_trimmed_gsis_id" in batch.metadata.warning_codes
    row = batch.frame.filter(batch.frame.get_column("external_player_id") == "5000001")
    assert row.get_column("reported_gsis_id").item() == "00-0000001"
    assert "whitespace_trimmed_gsis_id" in row.get_column("quality_flags").item()


def test_sleeper_observation_time_is_retrieval_time_not_a_freshness_claim(fixture_inputs):
    from ffdraft.timeutil import parse_utc

    when = parse_utc("2026-08-18T09:00:00Z")
    batch = SleeperPlayerAdapter().normalize(fixture_inputs.sleeper_players, retrieved_at=when)
    assert batch.metadata.source_as_of_utc is None
    assert set(batch.frame.get_column("observed_at_utc").to_list()) == {when}


def test_sleeper_state_parses_the_season_cross_check():
    state = parse_sleeper_state(
        {"season": "2026", "week": 2, "season_type": "pre", "season_start_date": "2026-08-06"},
    )
    assert state.season == 2026
    assert state.agrees_with(2026)
    assert not state.agrees_with(2025)


# --------------------------------------------------------------------------------------
# Market (MFL)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("QB", EntityKind.PLAYER),
        ("WR", EntityKind.PLAYER),
        ("Def", EntityKind.TEAM_UNIT),
        ("TMWR", EntityKind.TEAM_UNIT),
        ("TMQB", EntityKind.TEAM_UNIT),
        ("Coach", EntityKind.TEAM_UNIT),
        (None, EntityKind.UNKNOWN),
    ],
)
def test_mfl_entities_are_classified_before_identity(raw, expected):
    """`TMWR` must never be read as a WR (AGENTS.md section 6)."""
    assert classify_mfl_entity(raw) is expected


def test_position_parsing_refuses_team_aggregate_tokens():
    from ffdraft.contracts import Position

    assert Position.parse("Def") is Position.DST
    assert Position.parse("TMWR") is None
    assert Position.parse("TMRB") is None


def test_market_quotes_never_claim_a_data_as_of_time(fixture_inputs):
    """MFL's envelope timestamp is response-generation time (Phase-0 13.5)."""
    adapter = MflAdpAdapter()
    batch = adapter.normalize(
        fixture_inputs.mfl_adp,
        season=2026,
        cohort=widest_cohort(),
    )
    assert batch.metadata.source_as_of_utc is None
    assert batch.frame.get_column("source_as_of_utc").null_count() == batch.frame.height
    # The response timestamp is still recorded, as evidence rather than as freshness.
    assert batch.metadata.detail["response_timestamp"] == "1786974291"
    assert batch.metadata.detail["response_totalDrafts"] == "410"


def test_every_quote_is_flagged_for_the_missing_standard_deviation(fixture_inputs):
    batch = MflAdpAdapter().normalize(
        fixture_inputs.mfl_adp,
        season=2026,
        cohort=widest_cohort(),
    )
    for flags in batch.frame.get_column("quality_flags").to_list():
        assert ADP_SD_UNAVAILABLE in flags
        assert SOURCE_AS_OF_UNAVAILABLE in flags


def test_a_quote_records_its_cohort_not_a_preset(fixture_inputs):
    """Contract 2.0: cohort approximation is a per-preset verdict, not a row property.

    A quote knows which *request* produced it. Whether that request is an exact match for
    a published preset is decided later by the frozen selection rule (ADR-039), which is
    why the row carries `cohort_id` and the assignment carries `exact`.
    """
    cohort = widest_cohort()
    assert cohort.filters == {}
    assert cohort.specificity == 0
    assert cohort.is_exact_for("PPR", 12) is False

    batch = MflAdpAdapter().normalize(fixture_inputs.mfl_adp, season=2026, cohort=cohort)
    assert set(batch.frame.get_column("cohort_id").to_list()) == {"unfiltered"}
    assert "cohort_approximate" not in batch.frame.columns
    assert set(batch.frame.get_column("source_format_detail").to_list()) == {"no filters"}


def test_a_single_axis_cohort_is_never_exact_for_a_preset():
    """ADR-012/ADR-039: "any league size" is not "twelve teams"."""
    ppr = cohort_by_id("ppr")
    assert ppr.scoring_semantics == "PPR"
    assert ppr.league_size_semantics is None
    assert ppr.is_exact_for("PPR", 12) is False

    exact = cohort_by_id("ppr-fcount12")
    assert exact.is_exact_for("PPR", 12) is True
    assert exact.is_exact_for("PPR", 14) is False
    assert exact.filter_query == "FCOUNT=12&IS_PPR=1"


def test_an_approximate_assignment_labels_itself(fixture_inputs):
    """ADR-012: never present an approximate cohort as preset-specific ADP."""
    approximate = CohortAssignment(
        scoring_preset="HALF",
        league_size=12,
        cohort=widest_cohort(),
        exact=False,
        sufficient=True,
        reason="widest sufficient candidate",
    )
    assert approximate.approximate is True
    assert COHORT_APPROXIMATE in approximate.quality_flags
    assert approximate.source_format_detail == "no filters (approximate cohort)"

    exact = CohortAssignment(
        scoring_preset="PPR",
        league_size=12,
        cohort=cohort_by_id("ppr-fcount12"),
        exact=True,
        sufficient=True,
        reason="most specific sufficient candidate",
    )
    assert exact.quality_flags == ()
    assert exact.source_format_detail == "FCOUNT=12&IS_PPR=1 (exact cohort)"


def test_directory_classifies_team_units_and_supplies_the_espn_bridge(fixture_inputs):
    batch = MflPlayerDirectoryAdapter().normalize(fixture_inputs.mfl_directory)
    directory = MflPlayerDirectory(frame=batch.frame)
    assert directory.entity_kind("151") is EntityKind.TEAM_UNIT
    assert directory.entity_kind("152") is EntityKind.TEAM_UNIT
    assert directory.entity_kind("6000001") is EntityKind.PLAYER
    assert directory.espn_id("6000001") == "4000001"
    assert "mfl_team_unit_row" in batch.metadata.warning_codes


def test_quotes_without_a_directory_are_flagged_as_unclassified(fixture_inputs):
    adapter = MflAdpAdapter()
    batch = adapter.normalize(
        fixture_inputs.mfl_adp,
        season=2026,
        cohort=widest_cohort(),
    )
    checks = adapter.validate_raw(batch).checks
    assert any(check.check_id == "market.unclassified_entities" for check in checks)


def test_adp_envelope_and_bare_rows_normalize_identically(fixture_inputs):
    """Fixtures store bare rows and the live endpoint wraps them; both must take one path."""
    from ffdraft.timeutil import parse_utc

    adapter = MflAdpAdapter()
    cohort = widest_cohort()
    when = parse_utc("2026-08-18T12:00:00Z")
    from_envelope = adapter.normalize(
        fixture_inputs.mfl_adp,
        season=2026,
        cohort=cohort,
        retrieved_at=when,
    )
    from_rows = adapter.normalize(
        fixture_inputs.mfl_adp["adp"]["player"],
        season=2026,
        cohort=cohort,
        retrieved_at=when,
    )
    assert from_envelope.frame.equals(from_rows.frame)


def test_zero_or_missing_prices_are_dropped_and_counted():
    adapter = MflAdpAdapter()
    batch = adapter.normalize(
        [
            {"id": "6000001", "averagePick": "0", "rank": "1"},
            {"id": "6000002", "averagePick": "", "rank": "2"},
            {"id": "6000003", "averagePick": "4.5", "rank": "3"},
        ],
        season=2026,
        cohort=widest_cohort(),
    )
    assert batch.frame.height == 1
    assert batch.metadata.detail["market_rows_without_usable_price"] == "2"


def test_market_module_is_the_only_place_market_normalization_lives():
    """ARCHITECTURE 3.1: the intrinsic boundary is enforced by module layout, not habit."""
    import ffdraft.sources as sources_package

    exported = set(sources_package.__all__)
    assert not {name for name in exported if "Mfl" in name or "Market" in name}, (
        "market adapters must be imported from ffdraft.sources.market explicitly"
    )


# --------------------------------------------------------------------------------------
# Phase-2 historical adapters
# --------------------------------------------------------------------------------------


def test_draft_capital_normalization_drops_every_post_draft_outcome(historical_sources):
    """`load_draft_picks` publishes games played, approximate value and Pro Bowls.

    All of those are knowledge from after the draft, so the contract excludes them and a
    semantic check asserts none survived. The fixture deliberately supplies them.
    """
    adapter = NflverseDraftPickAdapter()
    frame = historical_sources.sources.draft_picks
    assert adapter.POST_DRAFT_OUTCOME_COLUMNS.isdisjoint(set(frame.columns))
    report = adapter.validate_raw(
        adapter.normalize([{"season": 2025, "round": 1, "pick": 1, "gsis_id": "00-0090005"}]),
    )
    assert not [check for check in report.checks if check.blocking]


def test_the_player_master_carries_no_current_state_column(historical_sources):
    """`status`, `latest_team`, `last_season` and `years_of_experience` describe today.

    Using any of them on a 2016 row would import 2026 knowledge, so they are absent from the
    contract entirely - and the fixture supplies them to prove the exclusion is real.
    """
    adapter = NflversePlayerMasterAdapter()
    frame = historical_sources.sources.player_master
    assert adapter.CURRENT_STATE_COLUMNS.isdisjoint(set(frame.columns))


def test_a_weekly_row_beyond_its_seasons_week_count_is_a_semantic_failure():
    adapter = NflverseWeeklyStatsAdapter()
    batch = adapter.normalize(
        [
            {
                "season": 2019,
                "week": 18,
                "season_type": "REG",
                "player_id": "00-0000001",
            },
        ],
    )
    checks = adapter.semantic_checks(batch)
    assert any(check.check_id == "weekly_stats.week_out_of_range" for check in checks)


def test_the_weekly_adapter_sums_offensive_fumbles_and_two_point_conversions():
    batch = NflverseWeeklyStatsAdapter().normalize(
        [
            {
                "season": 2024,
                "week": 3,
                "season_type": "REG",
                "player_id": "00-0000001",
                "rushing_fumbles_lost": 1,
                "receiving_fumbles_lost": 1,
                "sack_fumbles_lost": 1,
                "passing_2pt_conversions": 1,
                "rushing_2pt_conversions": 1,
                "receiving_2pt_conversions": 0,
            },
        ],
    )
    row = batch.frame.to_dicts()[0]
    assert row["fumbles_lost"] == 3.0
    assert row["two_point_conversions"] == 2.0


def test_combine_heights_are_parsed_from_feet_and_inches():
    batch = NflverseCombineAdapter().normalize(
        [{"season": 2020, "pfr_id": "Test0000", "ht": "6-2", "wt": 210}],
    )
    assert batch.frame.to_dicts()[0]["height_in"] == 74.0


def test_a_roster_gsis_id_naming_two_players_is_reported():
    from ffdraft.sources.nflverse import collided_gsis_ids

    adapter = NflverseRosterAdapter()
    batch = adapter.normalize(
        [
            {"season": 2019, "gsis_id": "00-0035718", "full_name": "Isaiah Searight"},
            {"season": 2019, "gsis_id": "00-0035718", "full_name": "Quinnen Williams"},
        ],
        season=2019,
    )
    assert collided_gsis_ids(batch.frame) == frozenset({"00-0035718"})
    checks = adapter.semantic_checks(batch)
    assert any(check.check_id == "nflverse_roster.gsis_id_names_two_players" for check in checks)


def test_one_player_on_two_teams_is_not_a_collision():
    """A mid-season trade produces two roster rows for one player, which is normal."""
    from ffdraft.sources.nflverse import collided_gsis_ids

    batch = NflverseRosterAdapter().normalize(
        [
            {"season": 2014, "gsis_id": "00-0027325", "full_name": "L. Blount", "team": "PIT"},
            {"season": 2014, "gsis_id": "00-0027325", "full_name": "L. Blount", "team": "NE"},
        ],
        season=2014,
    )
    assert collided_gsis_ids(batch.frame) == frozenset()
    assert batch.frame.height == 2
