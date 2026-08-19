"""Data-quality checks, the gate, and the intrinsic boundary.

`docs/TEST_STRATEGY.md` section 3 requires the critical checks to have direct tests showing
they block. A check that reports a problem but does not stop the build is worse than no
check, because it manufactures confidence.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl
import pytest

from ffdraft.contracts import CheckStatus, QualityCheck, Severity
from ffdraft.contracts.frames import ColumnSpec, FrameContract
from ffdraft.quality import (
    QualityGate,
    QualityGateError,
    audit_intrinsic_feature_names,
    audit_intrinsic_source_lineage,
    check_duplicate_keys,
    check_finite,
    check_quantiles_monotonic,
    check_range,
    check_source_freshness,
    check_unique_contiguous_tiers,
    forbidden_reason,
)
from ffdraft.quality.thresholds import IDENTITY_COVERAGE_MINIMUM, TOP_OVERALL_COVERAGE_MINIMUM
from ffdraft.timeutil import parse_utc


def _fails(checks, check_id: str) -> bool:
    return any(check.check_id == check_id and check.status is CheckStatus.FAIL for check in checks)


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------


def test_a_critical_failure_blocks_and_a_warning_does_not():
    gate = QualityGate()
    gate.add(
        QualityCheck.fail("w", stage="s", message="m", severity=Severity.WARNING),
        QualityCheck.ok("ok", stage="s", message="m"),
    )
    assert gate.passed
    gate.raise_if_blocked()

    gate.add(QualityCheck.fail("c", stage="s", message="boom"))
    assert not gate.passed
    with pytest.raises(QualityGateError, match="boom"):
        gate.raise_if_blocked()


def test_gate_summary_matches_the_build_metadata_schema_shape():
    gate = QualityGate()
    gate.add(QualityCheck.fail("c", stage="s", message="m"))
    gate.add(QualityCheck.fail("w", stage="s", message="m", severity=Severity.WARNING))
    assert gate.summary() == {"status": "fail", "critical_failures": 1, "warnings": 1}


def test_the_gate_collects_every_finding_before_stopping():
    """One run must diagnose a broken build fully, not one problem at a time."""
    gate = QualityGate()
    for index in range(5):
        gate.add(QualityCheck.fail(f"c{index}", stage="s", message="m"))
    assert len(gate.critical_failures) == 5


# --------------------------------------------------------------------------------------
# Frame contracts
# --------------------------------------------------------------------------------------


def test_frame_contract_reports_every_problem_at_once():
    contract = FrameContract(
        contract_id="demo",
        version="1.0",
        primary_key=("key",),
        columns=(
            ColumnSpec("key", pl.String, nullable=False),
            ColumnSpec("value", pl.Int32),
        ),
    )
    frame = pl.DataFrame({"key": ["a", "a", None], "value": [1.0, 2.0, 3.0], "extra": [1, 2, 3]})
    checks = contract.validate(frame)
    assert _fails(checks, "frame_contract.dtype_mismatch")
    assert _fails(checks, "frame_contract.unexpected_nulls")
    assert _fails(checks, "frame_contract.duplicate_primary_key")
    assert _fails(checks, "frame_contract.unexpected_columns")


def test_frame_contract_coerces_missing_columns_to_typed_nulls():
    contract = FrameContract(
        contract_id="demo",
        version="1.0",
        columns=(ColumnSpec("a", pl.String), ColumnSpec("b", pl.Int32)),
    )
    coerced = contract.coerce(pl.DataFrame({"a": ["x"]}))
    assert coerced.columns == ["a", "b"]
    assert coerced.schema["b"] == pl.Int32
    assert contract.validate(coerced)[-1].status is CheckStatus.PASS


def test_a_contract_cannot_key_on_a_column_it_does_not_declare():
    with pytest.raises(ValueError, match="primary key references unknown"):
        FrameContract(
            contract_id="bad",
            version="1.0",
            primary_key=("missing",),
            columns=(ColumnSpec("a", pl.String),),
        )


# --------------------------------------------------------------------------------------
# Semantic checks
# --------------------------------------------------------------------------------------


def test_non_monotonic_quantiles_are_critical():
    def row(player_id, *values):
        keys = ("p10_vorp", "p25_vorp", "p50_vorp", "p75_vorp", "p90_vorp")
        return {"player_id": player_id, **dict(zip(keys, values, strict=True))}

    records = [row("p1", 1, 2, 3, 4, 5), row("p2", 5, 2, 3, 4, 5)]
    checks = check_quantiles_monotonic(records, prefix="vorp")
    assert _fails(checks, "artifact.non_monotonic_quantiles")
    assert checks[0].blocking
    assert "p2" in checks[0].observed


def test_a_missing_quantile_is_also_a_failure():
    records = [{"player_id": "p1", "p10_vorp": 1, "p25_vorp": 2, "p50_vorp": 3, "p75_vorp": 4}]
    checks = check_quantiles_monotonic(records, prefix="vorp")
    assert _fails(checks, "artifact.non_monotonic_quantiles")


def test_duplicate_canonical_keys_are_critical():
    records = [{"player_id": "p1", "preset": "a"}, {"player_id": "p1", "preset": "a"}]
    checks = check_duplicate_keys(records, key_fields=("player_id", "preset"))
    assert _fails(checks, "artifact.duplicate_keys")


def test_non_finite_public_values_are_critical():
    checks = check_finite([{"player_id": "p1", "x": float("nan")}], fields=("x",))
    assert _fails(checks, "artifact.non_finite_value")
    checks = check_finite([{"player_id": "p1", "x": float("inf")}], fields=("x",))
    assert _fails(checks, "artifact.non_finite_value")


def test_out_of_range_values_are_reported():
    checks = check_range([{"player_id": "p1", "score": 120}], field="score", minimum=0, maximum=100)
    assert _fails(checks, "artifact.value_out_of_range")


def test_tier_semantics_catch_duplicates_gaps_and_inversions():
    base = {"league_preset_id": "redraft-12", "scoring_preset": "PPR"}
    duplicated = [
        {**base, "fair_rank": 1, "tier_ordinal": 0},
        {**base, "fair_rank": 1, "tier_ordinal": 0},
    ]
    assert _fails(check_unique_contiguous_tiers(duplicated), "tier.duplicate_fair_rank")

    inverted = [
        {**base, "fair_rank": 1, "tier_ordinal": 1},
        {**base, "fair_rank": 2, "tier_ordinal": 0},
    ]
    assert _fails(check_unique_contiguous_tiers(inverted), "tier.ordinal_not_monotonic")

    split = [
        {**base, "fair_rank": 1, "tier_ordinal": 0},
        {**base, "fair_rank": 2, "tier_ordinal": 1},
        {**base, "fair_rank": 3, "tier_ordinal": 0},
    ]
    assert _fails(check_unique_contiguous_tiers(split), "tier.not_contiguous")


def test_contiguous_tiers_pass():
    base = {"league_preset_id": "redraft-12", "scoring_preset": "PPR"}
    good = [
        {**base, "fair_rank": 1, "tier_ordinal": 0},
        {**base, "fair_rank": 2, "tier_ordinal": 1},
        {**base, "fair_rank": 3, "tier_ordinal": 1},
    ]
    checks = check_unique_contiguous_tiers(good)
    assert all(check.status is CheckStatus.PASS for check in checks)


def test_a_stale_critical_source_blocks_the_build():
    now = parse_utc("2026-08-18T12:00:00Z")
    stale = parse_utc("2026-06-01T04:15:00Z")
    checks = check_source_freshness(
        stale,
        now=now,
        max_age=timedelta(days=2),
        source_id="myfantasyleague_adp",
    )
    assert _fails(checks, "source.stale")
    assert checks[0].blocking

    lenient = check_source_freshness(
        stale,
        now=now,
        max_age=timedelta(days=2),
        source_id="optional",
        critical=False,
    )
    assert not lenient[0].blocking


def test_the_stale_fixture_is_actually_stale(pipeline_fixture_dir):
    import json

    record = json.loads((pipeline_fixture_dir / "stale_batch.json").read_text())
    checks = check_source_freshness(
        parse_utc(record["retrieved_at_utc"]),
        now=parse_utc("2026-08-18T12:00:00Z"),
        max_age=timedelta(days=2),
        source_id=record["source_id"],
    )
    assert checks[0].blocking


# --------------------------------------------------------------------------------------
# The intrinsic boundary (ADR-002)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "adp",
        "market_adp",
        "prev1_adp",
        "ecr_rank",
        "fantasypros_consensus",
        "fantasycalc_value",
        "expert_rank",
        "arbitrage_score",
        "auction_value",
        "average_draft_position",
        "ktc_value",
    ],
)
def test_market_and_expert_feature_names_are_rejected(name):
    assert forbidden_reason(name) is not None
    assert _fails(audit_intrinsic_feature_names([name]), "intrinsic.forbidden_feature_name")


@pytest.mark.parametrize(
    "name",
    [
        "prev1_fantasy_ppg",
        "prev1_targets_pg",
        "age_position_z",
        "depth_rank_at_anchor",
        "draft_round",
        "combine_speed_score",
        "team_change_flag",
        "prior_games_missed",
    ],
)
def test_legitimate_football_features_are_accepted(name):
    """The names in docs/DATA_CONTRACTS.md section 4 must not trip the guard."""
    assert forbidden_reason(name) is None


def test_lineage_through_a_market_source_is_rejected(app_config):
    checks = audit_intrinsic_source_lineage(
        {"prev1_value_score": ["nflreadpy", "myfantasyleague_adp"]},
        registry=app_config.registry,
    )
    assert _fails(checks, "intrinsic.forbidden_feature_lineage")
    assert "myfantasyleague_adp" in checks[0].observed


def test_lineage_through_the_approved_benchmark_source_is_still_rejected(app_config):
    """ADR-014 approved comparison, not use. A benchmark source is not an intrinsic input."""
    checks = audit_intrinsic_source_lineage(
        {"consensus_delta": ["fantasypros_ecr_via_dynastyprocess"]},
        registry=app_config.registry,
    )
    assert _fails(checks, "intrinsic.forbidden_feature_lineage")


def test_nflverse_lineage_is_accepted(app_config):
    checks = audit_intrinsic_source_lineage(
        {"prev1_fantasy_ppg": ["nflreadpy"], "prev1_xfp_pg": ["ffopportunity"]},
        registry=app_config.registry,
    )
    assert all(check.status is CheckStatus.PASS for check in checks)


def test_launch_thresholds_match_the_documented_contract():
    """docs/DATA_CONTRACTS.md section 12. Tuning these needs evidence, so pin them."""
    assert IDENTITY_COVERAGE_MINIMUM == 0.95
    assert TOP_OVERALL_COVERAGE_MINIMUM == 1.0


def test_the_fixture_threshold_is_a_deliberate_local_relaxation():
    """The fixture pipeline must not be able to weaken the production threshold."""
    from ffdraft.pipeline.fixture_pipeline import FIXTURE_IDENTITY_COVERAGE_MINIMUM

    assert FIXTURE_IDENTITY_COVERAGE_MINIMUM < IDENTITY_COVERAGE_MINIMUM
    assert IDENTITY_COVERAGE_MINIMUM == 0.95, "the production constant must stay untouched"
