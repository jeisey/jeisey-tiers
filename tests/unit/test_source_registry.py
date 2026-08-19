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


# --------------------------------------------------------------------------------------
# Owner decisions recorded 2026-08-18. These are contract tests over durable state: each
# one fails if a later change quietly reverses a decision a human made.
# --------------------------------------------------------------------------------------


def test_fantasypros_benchmark_is_approved_but_not_redistributable(registry):
    """ADR-014 as amended: approval to compare is not approval to republish."""
    ecr = registry["sources"]["fantasypros_ecr_via_dynastyprocess"]
    assert ecr["policy"] == "benchmark_only"
    assert ecr["redistribution_permitted"] is False
    assert "internal_benchmark" in ecr["permitted_roles"]
    for forbidden in (
        "intrinsic_feature",
        "draftvalue_input",
        "critical_production_dependency",
        "public_artifact_field",
        "public_redistribution",
    ):
        assert forbidden in ecr["forbidden_roles"], f"{forbidden} must stay forbidden"
    assert "internal_benchmark_until_reviewed" not in ecr["forbidden_roles"]


def test_benchmark_only_sources_are_listed_globally(registry):
    listed = set(registry["decisions"]["benchmark_only_sources"])
    derived = {
        source_id
        for source_id, source in registry["sources"].items()
        if source["policy"] == "benchmark_only"
    }
    assert listed == derived


def test_mfl_client_records_env_names_and_never_a_value(registry):
    """ADR-017. A value in this file would be a committed secret."""
    market = registry["sources"]["myfantasyleague_adp"]
    settings = market["client_settings"]
    assert settings["developer_client_registered"] is True
    assert settings["credentials_used_by_adp_adapter"] is False
    assert market["public_adp_requires_authentication"] is False
    for key in ("user_agent_env", "client_name_env", "username_env", "password_env"):
        value = settings[key]
        assert value.startswith("MFL_API_"), f"{key} must name an environment variable"
        assert value.isupper()


def test_the_registry_file_contains_no_secret_looking_values():
    raw = REGISTRY_PATH.read_text(encoding="utf-8")
    for forbidden in ("password:", "api_key:", "apikey:", "token:"):
        assert forbidden not in raw.lower(), f"{forbidden} suggests a committed credential"


def test_repository_visibility_decision_is_recorded_for_phase_7(registry):
    """ADR-016: private through Phase 6; the choice is a required Phase-7 decision."""
    decisions = registry["decisions"]
    assert decisions["repository_visibility"] == "private"
    assert decisions["repository_visibility_revisit_phase"] == 7
    assert "ADR-016" in decisions["repository_visibility_decision_ref"]


def test_market_cohort_remeasurement_is_scheduled_for_phase_5(registry):
    """ADR-012 amendment: do not attempt thin cohorts in Phase 1; re-measure in Phase 5."""
    decisions = registry["decisions"]
    assert decisions["market_cohort_remeasure_phase"] == 5
    rule = decisions["market_cohort_remeasure_rule"].lower()
    assert "widest reliable cohort" in rule
    assert "approximate" in rule
