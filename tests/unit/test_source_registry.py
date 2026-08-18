"""Contract tests for `config/source-registry.yaml`.

The registry is the machine-readable half of the source-of-truth pair with
`docs/DATA_SOURCES.md` (AGENTS.md section 18). These tests keep the two honest about the
things a later phase will trust blindly: the policy vocabulary, the Phase-0 verification
record, and the invariant that a disabled source has a recorded reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "source-registry.yaml"


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_every_policy_is_in_the_declared_vocabulary(registry):
    allowed = set(registry["policy_states"])
    for source_id, source in registry["sources"].items():
        assert source["policy"] in allowed, f"{source_id} has unknown policy {source['policy']!r}"


def test_verified_sources_record_a_verification_date(registry):
    for source_id, source in registry["sources"].items():
        if source.get("verified"):
            assert source.get("verified_at"), f"{source_id} is verified without a date"


def test_disabled_sources_record_a_decision_and_a_revisit_path(registry):
    disabled = {
        source_id: source
        for source_id, source in registry["sources"].items()
        if source["policy"] == "disabled"
    }
    assert disabled, "expected the Phase-0 record to disable at least one source"
    for source_id, source in disabled.items():
        assert source.get("decision_ref"), f"{source_id} is disabled without an ADR reference"
        assert source.get("decision_reason"), f"{source_id} is disabled without a reason"
        assert source.get("revisit_if"), f"{source_id} is disabled with no way back"


def test_production_sources_declare_a_licence(registry):
    for source_id, source in registry["sources"].items():
        if source["policy"] != "production_allowed":
            continue
        assert source.get("license") or source.get("data_license"), (
            f"{source_id} is production_allowed without a recorded licence"
        )


def test_arbitrage_mode_matches_the_feasibility_decision(registry):
    """Baseline vs ML labelling must never contradict the feasibility flag (ADR-010)."""
    decisions = registry["decisions"]
    feasible = decisions["arbitrage_ml_historical_feasible"]
    mode = decisions["arbitrage_mode"]
    assert mode in {"baseline", "ml"}
    assert (mode == "ml") == bool(feasible)
    if not feasible:
        assert decisions["arbitrage_ml_revisit_rule"]


def test_market_source_forbids_being_used_as_a_training_target(registry):
    """The verified MFL history is not point-in-time, so it must stay out of ML targets."""
    market = registry["sources"]["myfantasyleague_adp"]
    assert "historical_arbitrage_training_target" in market["forbidden_roles"]


def test_market_source_records_its_published_obligations(registry):
    obligations = " ".join(registry["sources"]["myfantasyleague_adp"]["obligations"]).lower()
    assert "user-agent" in obligations
    assert "429" in obligations
    assert "once per day" in obligations


def test_non_commercial_sources_are_flagged_for_the_monetisation_gate(registry):
    """docs/SECURITY_LICENSE.md section 10 needs the full non-commercial list, not just one."""
    flagged = set(registry["decisions"]["non_commercial_deployment_required_by"])
    for source_id in flagged:
        assert registry["sources"][source_id].get("non_commercial_only") is True
    for source_id, source in registry["sources"].items():
        if source.get("non_commercial_only"):
            assert source_id in flagged, f"{source_id} is non-commercial but not flagged globally"


def test_phase0_evidence_file_referenced_by_the_registry_exists(registry):
    evidence = REPO_ROOT / registry["phase0_evidence"]
    assert evidence.is_file(), f"missing probe evidence: {evidence}"


def test_benchmark_only_data_cannot_reach_public_artifacts(registry):
    ecr = registry["sources"]["fantasypros_ecr_via_dynastyprocess"]
    assert "intrinsic_feature" in ecr["forbidden_roles"]
    assert "public_artifact_field" in ecr["forbidden_roles"]
