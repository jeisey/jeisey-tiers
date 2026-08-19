"""Historical quality-report tests.

The report is what a human reads before signing off the Phase-2 gate, so it has to be
deterministic (a diff means the data changed, not that the clock moved), it has to slice by
season and position rather than averaging eras together, and it has to state the thresholds
it judged against.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from ffdraft.anchors import DRAFT_ANCHOR_RULE_VERSION
from ffdraft.features.eligibility import DepthContextState
from ffdraft.features.report import build_quality_report, threshold_table
from ffdraft.quality.thresholds import (
    HISTORICAL_AGE_COVERAGE_MINIMUM,
    HistoricalThresholds,
)
from ffdraft.timeutil import parse_utc


@pytest.fixture(scope="module")
def report(historical_dataset):
    return historical_dataset.report


def test_the_report_is_deterministic(historical_dataset, app_config):
    """Two reports over the same data must be byte-identical."""
    kwargs = {
        "features": historical_dataset.features,
        "fantasy_labels": historical_dataset.fantasy_labels,
        "vorp_labels": historical_dataset.vorp_labels,
        "anchors": historical_dataset.anchors,
        "exclusions": historical_dataset.exclusions,
        "config": app_config,
        "generated_at": parse_utc("2026-01-01T00:00:00Z"),
        "dataset_version": "test",
        "thresholds": HistoricalThresholds.fixture(),
    }
    first = build_quality_report(**kwargs)
    second = build_quality_report(**kwargs)
    assert first.to_json() == second.to_json()
    assert first.to_markdown() == second.to_markdown()


def test_the_report_records_every_version_a_rebuild_would_need(report):
    dataset = report.payload["dataset"]
    for key in (
        "dataset_version",
        "feature_schema_version",
        "feature_schema_hash",
        "scoring_engine_version",
        "feature_cutoff_rule_version",
        "league_config_version",
        "source_registry_version",
    ):
        assert dataset[key]
    assert dataset["feature_cutoff_rule_version"] == DRAFT_ANCHOR_RULE_VERSION


def test_every_season_reports_its_anchor_and_horizon(report):
    for season in report.payload["seasons"]:
        assert season["anchor_at_utc"].endswith("Z")
        assert "excluding NFL week" in season["fantasy_horizon"]
        assert season["days_before_kickoff"] > 0


def test_coverage_is_reported_by_season_and_position(report):
    for season in report.payload["seasons"]:
        assert season["by_position"], f"{season['season']} has no positional breakdown"
        for row in season["by_position"]:
            assert row["position"] in {"QB", "RB", "TE", "WR"}
            assert set(row["coverage"]) >= {
                "age_at_anchor",
                "prev1_games",
                "prev1_snap_share",
                "prev1_xfp_pg",
                "draft_round",
                "combine_forty",
                "depth_rank_at_anchor",
                "prior_season_role_rank",
            }
            assert row["rookies"] + row["veterans"] == row["eligible_rows"]


def test_the_era_boundary_is_visible_rather_than_averaged_away(report):
    """A lagged-only season and a snapshot season must not look the same."""
    states = {
        season["season"]: season["depth_context_state"] for season in report.payload["seasons"]
    }
    observed = str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR)
    assert observed not in states[2024]
    assert states[2025].get(observed, 0) > 0


def test_missingness_is_reported_per_feature_family(report):
    families = report.payload["seasons"][0]["by_position"][0]["missingness_by_family"]
    assert set(families) >= {"opportunity", "efficiency", "draft", "athletic"}
    assert all(0.0 <= rate <= 1.0 for rate in families.values())


def test_label_coverage_is_complete(report):
    for season in report.payload["seasons"]:
        assert season["fantasy_label_coverage"] == pytest.approx(1.0)
        assert season["vorp_label_coverage"] == pytest.approx(1.0)


def test_exclusions_are_reported_with_reasons(report):
    assert report.payload["exclusions_by_reason"]
    assert "non_core_position" in report.payload["exclusions_by_reason"]


def test_every_threshold_carries_a_justification():
    for row in threshold_table():
        assert row["justification"].strip()
        assert "minimum" in row or "maximum" in row or "value" in row


def test_the_threshold_profile_is_recorded_in_the_report(report):
    profiles = [row for row in report.payload["thresholds"] if row["name"] == "threshold_profile"]
    assert profiles and profiles[0]["value"] == "fixture"


def test_the_fixture_profile_is_strictly_looser_than_production():
    """A relaxation that could quietly become the production standard is worthless."""
    production = HistoricalThresholds.production()
    fixture = HistoricalThresholds.fixture()
    assert production.age_coverage_minimum == HISTORICAL_AGE_COVERAGE_MINIMUM
    assert fixture.age_coverage_minimum < production.age_coverage_minimum
    assert fixture.expected_points_minimum < production.expected_points_minimum
    assert fixture.row_count_tolerance > production.row_count_tolerance
    # The rules that are structural rather than statistical do not relax at all.
    assert fixture.canonical_key_minimum == production.canonical_key_minimum
    assert fixture.duplicate_key_maximum == production.duplicate_key_maximum
    assert fixture.label_coverage_minimum == production.label_coverage_minimum


def test_the_report_carries_the_feature_dictionary(report):
    names = {record["name"] for record in report.payload["feature_dictionary"]}
    assert "depth_rank_at_anchor" in names
    assert "prev1_fantasy_ppg_ppr" in names


def test_the_report_json_round_trips(report):
    reloaded = json.loads(report.to_json())
    assert reloaded == report.payload


def test_the_markdown_renders_the_sections_a_reviewer_needs(report):
    text = report.to_markdown()
    for heading in (
        "# Historical dataset quality report",
        "## Gate summary",
        "## Identity and coverage",
        "## Declared thresholds",
        "## By season",
        "## By season and position",
        "## Failing checks",
        "## Excluded candidates",
    ):
        assert heading in text


def test_an_empty_dataset_produces_a_report_rather_than_an_exception(app_config):
    from ffdraft.features.dictionary import (
        FANTASY_LABEL_CONTRACT,
        HISTORICAL_FEATURE_CONTRACT,
        VORP_LABEL_CONTRACT,
    )

    empty_exclusions = pl.DataFrame(
        schema={"season": pl.Int32, "gsis_id": pl.String, "reason": pl.String, "detail": pl.String},
    )
    report = build_quality_report(
        features=HISTORICAL_FEATURE_CONTRACT.empty(),
        fantasy_labels=FANTASY_LABEL_CONTRACT.empty(),
        vorp_labels=VORP_LABEL_CONTRACT.empty(),
        anchors={},
        exclusions=empty_exclusions,
        config=app_config,
        generated_at=parse_utc("2026-01-01T00:00:00Z"),
        dataset_version="test",
    )
    assert report.payload["dataset"]["feature_rows"] == 0
    assert report.to_markdown()
