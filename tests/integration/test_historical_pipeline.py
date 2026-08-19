"""The network-free historical mini-pipeline.

`docs/TEST_STRATEGY.md` 2.3 makes the fixture pipeline the key CI smoke path. This is the
Phase-2 equivalent: synthetic source rows flow through the real adapters, the real anchor
rule, the real eligibility rules, the real feature builder, the real scoring engine and the
real VORP allocation, and out to Parquet - with no network anywhere.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from ffdraft.anchors import DRAFT_ANCHOR_RULE_VERSION
from ffdraft.contracts import frame_content_hash
from ffdraft.features.dictionary import (
    FANTASY_LABEL_CONTRACT,
    HISTORICAL_FEATURE_CONTRACT,
    VORP_LABEL_CONTRACT,
    feature_schema_hash,
)
from ffdraft.features.eligibility import DepthContextState
from ffdraft.features.sources import (
    FIXTURE_TARGET_SEASONS,
    load_fixture_sources,
    season_windows,
)
from ffdraft.leakage import validate_historical_directory
from ffdraft.pipeline import (
    build_historical_dataset,
    default_target_seasons,
    load_historical_dataset,
    write_historical_dataset,
)
from ffdraft.quality.thresholds import HistoricalThresholds
from ffdraft.timeutil import parse_utc

# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------


def test_loading_the_fixtures_produces_no_critical_finding(historical_sources):
    blocking = [check for check in historical_sources.checks if check.blocking]
    assert not blocking, [check.to_dict() for check in blocking]


def test_the_loader_asks_only_for_previous_season_rosters(historical_sources):
    """The eligibility spine is the *previous* season's roster, by construction.

    In a multi-season build one season is both a target and the next season's prior year, so
    "no target-season roster is ever loaded" is not the invariant. The invariant is that the
    loader only ever requests ``Y-1`` and the builder only ever looks up ``rosters[Y-1]``.
    """
    assert set(historical_sources.sources.rosters) == {
        season - 1 for season in FIXTURE_TARGET_SEASONS
    }


def test_a_later_seasons_roster_supplies_nothing_but_time_invariant_biography(
    historical_sources,
    app_config,
):
    """Dropping the 2024 roster must not change the 2024 feature rows.

    The biography table draws birth dates from every loaded roster, which is safe only
    because a birth date cannot change. If any *other* value ever leaked in from a later
    roster, this comparison would show it.
    """
    from dataclasses import replace

    from ffdraft.features.build import build_feature_table

    sources = historical_sources.sources
    without_later = replace(
        sources,
        rosters={season: frame for season, frame in sources.rosters.items() if season < 2024},
    )
    full = build_feature_table(sources, config=app_config, seasons=[2024]).features
    trimmed = build_feature_table(without_later, config=app_config, seasons=[2024]).features
    differing = [
        name
        for name in full.columns
        if not full.get_column(name).equals(trimmed.get_column(name), null_equal=True)
    ]
    assert set(differing) <= {
        "age_at_anchor",
        "age_at_anchor_known",
        "position_age_z",
        "height_in",
        "weight_lb",
    }, differing


def test_season_windows_extend_back_by_the_deepest_declared_lookback():
    windows = season_windows([2024, 2025])
    assert windows.target == (2024, 2025)
    assert windows.statistics[0] == 2019
    assert windows.rosters == (2023, 2024)
    # Only seasons with timestamped depth charts are fetched at all.
    assert windows.depth_charts == (2025,)


def test_default_target_seasons_start_where_snap_counts_do():
    assert default_target_seasons(2025)[0] == 2014
    assert default_target_seasons(2025)[-1] == 2025
    with pytest.raises(ValueError, match="precedes the first supported"):
        default_target_seasons(2000)


# --------------------------------------------------------------------------------------
# The built dataset
# --------------------------------------------------------------------------------------


def test_the_pipeline_produces_all_three_tables(historical_dataset):
    assert historical_dataset.features.height > 0
    assert historical_dataset.fantasy_labels.height > 0
    assert historical_dataset.vorp_labels.height > 0
    assert historical_dataset.seasons == FIXTURE_TARGET_SEASONS


def test_every_table_conforms_to_its_contract(historical_dataset):
    for frame, contract in (
        (historical_dataset.features, HISTORICAL_FEATURE_CONTRACT),
        (historical_dataset.fantasy_labels, FANTASY_LABEL_CONTRACT),
        (historical_dataset.vorp_labels, VORP_LABEL_CONTRACT),
    ):
        checks = contract.validate(frame, stage="test")
        assert not [check for check in checks if check.blocking], [
            check.to_dict() for check in checks if check.blocking
        ]


def test_the_feature_key_has_zero_duplicates(historical_dataset):
    features = historical_dataset.features
    assert features.height == features.select("season", "player_id").n_unique()


def test_the_label_keys_have_zero_duplicates(historical_dataset):
    labels = historical_dataset.fantasy_labels
    assert labels.height == labels.select("season", "player_id", "scoring_preset").n_unique()
    vorp = historical_dataset.vorp_labels
    assert (
        vorp.height
        == vorp.select(
            "season",
            "player_id",
            "scoring_preset",
            "league_preset_id",
        ).n_unique()
    )


def test_every_eligible_row_gets_a_label_under_every_scoring_preset(historical_dataset, app_config):
    expected = historical_dataset.features.height * len(app_config.league.scoring)
    assert historical_dataset.fantasy_labels.height == expected


def test_vorp_labels_cover_every_launch_preset(historical_dataset, app_config):
    presets = sorted(app_config.league.presets)
    assert (
        sorted(
            historical_dataset.vorp_labels.get_column("league_preset_id").unique().to_list(),
        )
        == presets
    )


def test_a_player_who_never_played_scores_zero_rather_than_going_missing(historical_dataset):
    """`Ghost Roster` is eligible in both seasons and produces nothing in either."""
    ghost = historical_dataset.features.filter(pl.col("display_name") == "Ghost Roster")
    assert ghost.height == len(FIXTURE_TARGET_SEASONS)
    labels = historical_dataset.fantasy_labels.join(
        ghost.select("season", "player_id"),
        on=["season", "player_id"],
        how="inner",
    )
    assert labels.height == ghost.height * 3
    assert labels.get_column("actual_fantasy_points").to_list() == [0.0] * labels.height
    assert labels.get_column("actual_games_played").to_list() == [0] * labels.height


def test_both_depth_eras_are_present_in_one_build(historical_dataset):
    states = (
        historical_dataset.features.group_by("season")
        .agg(pl.col("depth_context_state").unique().alias("states"))
        .sort("season")
    )
    by_season = {row["season"]: set(row["states"]) for row in states.iter_rows(named=True)}
    assert str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR) not in by_season[2024]
    assert str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR) in by_season[2025]


def test_the_gate_passes_on_the_fixture_dataset(historical_dataset):
    assert historical_dataset.gate.passed, [
        check.to_dict() for check in historical_dataset.gate.critical_failures
    ]


def test_the_build_is_reproducible(historical_sources, app_config):
    """Same inputs, same content hashes - which is what the manifest's claim rests on."""
    built = [
        build_historical_dataset(
            historical_sources.sources,
            config=app_config,
            seasons=FIXTURE_TARGET_SEASONS,
            generated_at=parse_utc("2026-01-01T00:00:00Z"),
            git_sha="0000000",
            thresholds=HistoricalThresholds.fixture(),
            verify_target_season_independence=False,
        )
        for _ in range(2)
    ]
    first, second = (dataset.manifest["content_hashes"] for dataset in built)
    assert first == second
    assert built[0].report.to_json() == built[1].report.to_json()


def test_the_manifest_records_what_a_rebuild_would_need(historical_dataset):
    manifest = historical_dataset.manifest
    assert manifest["feature_schema_hash"] == feature_schema_hash()
    assert manifest["feature_cutoff_rule_version"] == DRAFT_ANCHOR_RULE_VERSION
    assert manifest["season_windows"]["target"] == list(FIXTURE_TARGET_SEASONS)
    assert manifest["row_counts"]["features.parquet"] == historical_dataset.features.height
    assert manifest["content_hashes"]["features.parquet"] == frame_content_hash(
        historical_dataset.features,
    )


# --------------------------------------------------------------------------------------
# Writing and re-validating
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def written(tmp_path_factory, historical_dataset):
    out_dir = tmp_path_factory.mktemp("historical")
    write_historical_dataset(historical_dataset, out_dir)
    return out_dir


def test_every_expected_file_is_written(written):
    names = {path.name for path in written.iterdir()}
    assert names == {
        "features.parquet",
        "labels_fantasy.parquet",
        "labels_vorp.parquet",
        "anchors.parquet",
        "excluded_rows.parquet",
        "quality_report.json",
        "quality_report.md",
        "build_manifest.json",
        "feature_dictionary.md",
    }


def test_the_written_tables_round_trip(written, historical_dataset):
    tables = load_historical_dataset(written)
    assert tables["features.parquet"].equals(historical_dataset.features)
    assert tables["labels_vorp.parquet"].equals(historical_dataset.vorp_labels)


def test_validate_historical_passes_on_a_written_dataset(written):
    gate = validate_historical_directory(written)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]
    assert any(check.check_id == "historical.manifest_hash" for check in gate.checks)


def test_validate_historical_notices_a_dataset_that_no_longer_matches_its_manifest(
    written,
    tmp_path,
    historical_dataset,
):
    import shutil

    tampered = tmp_path / "tampered"
    shutil.copytree(written, tampered)
    historical_dataset.features.head(1).write_parquet(tampered / "features.parquet")
    gate = validate_historical_directory(tampered)
    assert "historical.manifest_hash_mismatch" in {
        check.check_id for check in gate.critical_failures
    }


def test_validate_historical_reports_a_missing_dataset(tmp_path):
    gate = validate_historical_directory(tmp_path / "nothing-here")
    assert not gate.passed
    assert gate.critical_failures[0].check_id == "leakage.dataset_missing"


def test_a_failed_gate_writes_nothing(historical_sources, app_config, tmp_path):
    """`docs/OPERATIONS.md` section 8: a bad run must leave the previous dataset intact."""
    from ffdraft.quality import QualityGateError

    dataset = build_historical_dataset(
        historical_sources.sources,
        config=app_config,
        seasons=FIXTURE_TARGET_SEASONS,
        generated_at=parse_utc("2026-01-01T00:00:00Z"),
        thresholds=HistoricalThresholds.production(),  # too strict for an 18-row fixture
        verify_target_season_independence=False,
    )
    assert not dataset.gate.passed
    out_dir = tmp_path / "never-written"
    with pytest.raises(QualityGateError):
        write_historical_dataset(dataset, out_dir)
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_the_written_report_and_manifest_are_valid_json(written):
    report = json.loads((written / "quality_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((written / "build_manifest.json").read_text(encoding="utf-8"))
    assert report["dataset"]["feature_schema_hash"] == manifest["feature_schema_hash"]


def test_the_written_dictionary_matches_the_code(written):
    from ffdraft.features.dictionary import dictionary_markdown

    text = (written / "feature_dictionary.md").read_text(encoding="utf-8")
    assert dictionary_markdown() in text


def test_the_fixture_loader_and_the_module_fixture_agree(historical_fixture_dir):
    reloaded = load_fixture_sources(historical_fixture_dir)
    assert reloaded.sources.weekly_stats.height > 0
    assert reloaded.windows.target == FIXTURE_TARGET_SEASONS
