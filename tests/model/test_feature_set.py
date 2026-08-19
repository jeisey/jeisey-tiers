"""The Phase-3 core feature set: what it contains, what it refuses, and why.

Two different guarantees are tested here. The first is a contract: the Phase-3 view may only
*narrow* the Phase-2 model inputs, so ADR-002's forbidden-feature guard still covers it. The
second is evidence: the exclusions claim things about development-era coverage, and the
era-stability audit re-measures those claims rather than trusting the comment.
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.contracts import CheckStatus
from ffdraft.features.dictionary import dictionary_by_name, intrinsic_feature_names
from ffdraft.modeling.features import (
    CORE_FEATURE_SET_VERSION,
    ExclusionReason,
    assert_no_forbidden_features,
    audit_era_stability,
    core_feature_selection,
)
from ffdraft.quality import audit_intrinsic_feature_names, audit_intrinsic_source_lineage

SNAPSHOT_ERA_COLUMNS = {
    "depth_rank_at_anchor",
    "depth_rank_observed",
    "team_change_flag",
    "team_change_known",
    "team_at_anchor_known",
}


def test_the_core_set_is_a_strict_subset_of_the_phase_2_model_inputs():
    selection = core_feature_selection()
    declared = set(intrinsic_feature_names())
    assert set(selection.included) < declared
    assert set(selection.included).isdisjoint({item.name for item in selection.excluded})
    assert len(selection.included) + len(selection.excluded) == len(declared)


def test_every_snapshot_era_only_column_is_excluded():
    selection = core_feature_selection()
    excluded = {item.name for item in selection.excluded}
    assert excluded >= SNAPSHOT_ERA_COLUMNS
    assert SNAPSHOT_ERA_COLUMNS.isdisjoint(selection.included)


def test_the_horizon_and_calendar_indices_are_excluded():
    reasons = {item.name: item.reason for item in core_feature_selection().excluded}
    assert reasons["prev1_team_games"] is ExclusionReason.HORIZON_ERA_INDEX
    assert reasons["draft_year"] is ExclusionReason.TIME_INDEX


def test_the_durability_signal_survives_the_horizon_exclusion():
    """Dropping the horizon index must not drop the availability feature built on it."""
    included = set(core_feature_selection().included)
    assert "prev1_games_missed" in included
    assert "prev1_games" in included


def test_every_exclusion_records_a_reason_and_a_disposition():
    for item in core_feature_selection().excluded:
        assert item.evidence.strip()
        assert item.disposition.strip()


def test_the_selection_is_versioned_and_hashed():
    selection = core_feature_selection()
    assert selection.version == CORE_FEATURE_SET_VERSION
    fingerprint = selection.fingerprint()
    assert len(fingerprint) == 16
    assert selection.fingerprint() == fingerprint
    payload = selection.to_dict()
    assert payload["feature_set_hash"] == fingerprint
    assert payload["included_count"] == len(selection.included)


def test_the_core_set_still_passes_the_forbidden_feature_audits(app_config):
    selection = core_feature_selection()
    specs = dictionary_by_name()
    name_checks = audit_intrinsic_feature_names(selection.included)
    lineage_checks = audit_intrinsic_source_lineage(
        {name: specs[name].sources for name in selection.included},
        registry=app_config.registry,
    )
    for check in (*name_checks, *lineage_checks):
        assert check.status is CheckStatus.PASS, check.to_dict()


def test_a_column_outside_the_phase_2_inputs_cannot_be_selected():
    with pytest.raises(ValueError, match="unknown columns"):
        assert_no_forbidden_features(["market_adp"])


def test_the_era_audit_accepts_a_selection_with_development_support(synthetic_modeling_dataset):
    selection = synthetic_modeling_dataset.selection
    checks, coverage = audit_era_stability(
        synthetic_modeling_dataset.audit_frame,
        selection=selection,
        development_seasons=(2020, 2021, 2022, 2023, 2024),
    )
    assert not [check for check in checks if check.blocking], [
        check.to_dict() for check in checks if check.blocking
    ]
    assert set(coverage) >= set(selection.included)
    for name in selection.included:
        assert coverage[name]["included"] is True


def test_the_era_audit_fails_an_included_feature_with_no_development_support():
    """Poison a core feature to null across every development season."""
    selection = core_feature_selection()
    target = "prev1_targets_pg"
    frame = pl.DataFrame(
        {
            "season": [2020, 2021, 2022, 2023, 2024],
            **{name: [None] * 5 for name in selection.included},
        },
    ).with_columns(
        [pl.col(name).cast(dictionary_by_name()[name].dtype) for name in selection.included],
    )
    frame = frame.with_columns(pl.lit(1.0).alias("prev1_carries_pg"))
    checks, _ = audit_era_stability(
        frame,
        selection=selection,
        development_seasons=(2020, 2021, 2022, 2023, 2024),
    )
    failures = {check.check_id for check in checks if check.status is CheckStatus.FAIL}
    assert "phase3.included_feature_has_no_development_support" in failures
    assert any(target in check.observed for check in checks if check.status is CheckStatus.FAIL)


def test_the_era_audit_warns_when_an_exclusion_reason_goes_stale(synthetic_modeling_dataset):
    """If a snapshot-only column suddenly has development coverage, say so."""
    selection = synthetic_modeling_dataset.selection
    audit = synthetic_modeling_dataset.audit_frame
    frame = audit.with_columns(
        pl.lit(3).cast(pl.Int32).alias("depth_rank_at_anchor"),
        pl.Series("depth_rank_observed", [index % 2 == 0 for index in range(audit.height)]),
    )
    checks, _ = audit_era_stability(
        frame,
        selection=selection,
        development_seasons=(2020, 2021, 2022, 2023, 2024),
    )
    stale = [check for check in checks if check.check_id == "phase3.exclusion_evidence_stale"]
    assert stale
    assert all(not check.blocking for check in stale)
