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


def test_repository_visibility_decision_was_made_in_phase_7(registry):
    """ADR-016 as amended: the application repository is public and serves a public site."""
    decisions = registry["decisions"]
    assert decisions["repository_visibility"] == "public"
    assert decisions["repository_visibility_decided_phase"] == 7
    assert "ADR-016" in decisions["repository_visibility_decision_ref"]


def test_the_retained_store_lives_in_a_separate_private_repository(registry):
    """ADR-049. A public repository has no private branch, so the store had to move.

    This is the single place the address is written down: `.github/actions/market-data-store`
    reads it, and `tests/unit/test_workflows.py` proves no workflow repeats the literal.
    """
    decisions = registry["decisions"]
    repository = decisions["market_history_repository"]
    assert repository.count("/") == 1, "owner/name, not a URL"
    assert repository != "jeisey/jeisey-tiers", (
        "the retained vendor payloads may not live in the public application repository"
    )
    assert decisions["market_history_repository_visibility"] == "private"
    # The branch name is deliberately unchanged: only the repository moved (ADR-049).
    assert decisions["market_history_branch"] == "market-data"
    assert decisions["market_history_append_only"] is True


def test_the_store_credential_is_recorded_as_a_name_and_never_a_value(registry):
    """The ADR-017 convention: configuration records which secret, never what it is."""
    name = registry["decisions"]["market_history_repository_secret_name"]
    assert name.isupper()
    assert name.replace("_", "").isalnum()
    assert len(name) < 64


def test_market_cohort_remeasurement_is_scheduled_for_phase_5(registry):
    """ADR-012 amendment: do not attempt thin cohorts in Phase 1; re-measure in Phase 5."""
    decisions = registry["decisions"]
    assert decisions["market_cohort_remeasure_phase"] == 5
    rule = decisions["market_cohort_remeasure_rule"].lower()
    assert "widest reliable cohort" in rule
    assert "approximate" in rule


# --------------------------------------------------------------------------------------
# Phase 10 (ADR-060 … ADR-066)
# --------------------------------------------------------------------------------------


def test_the_registry_and_the_code_agree_on_every_frozen_phase10_version(registry):
    """Three places describe each version; a drift between them is a silent contract break.

    The registry is what a human reads, the module constant is what production uses, and a
    published artifact carries the string. Pinning the first two to each other here is the
    cheapest way to notice the day one of them moves alone.
    """
    from ffdraft.identity.linkage import LINKAGE_RULE
    from ffdraft.market.comparison import COMPARISON_METHOD_VERSION
    from ffdraft.market.surface import (
        MARKET_TOP_DEPTH,
        SURFACE_RULE_VERSION,
        TIER_DEPTH_RULE,
        TIER_DEPTH_V1,
    )

    decisions = registry["decisions"]
    assert decisions["market_linkage_rule_version"] == LINKAGE_RULE.version
    assert decisions["market_linkage_min_coverage"] == LINKAGE_RULE.min_coverage
    assert decisions["market_comparison_method_version"] == COMPARISON_METHOD_VERSION
    assert decisions["surface_rule_version"] == SURFACE_RULE_VERSION
    assert decisions["tier_depth_rule_version"] == TIER_DEPTH_RULE.version
    assert decisions["tier_depth_rule_v1_version"] == TIER_DEPTH_V1.version
    assert decisions["market_top_surface_depth"] == MARKET_TOP_DEPTH


def test_the_surface_coverage_requirement_is_total(registry):
    """Roadmap 10.5 asks for 100%, and anything less would let a drafted player vanish."""
    assert registry["decisions"]["market_top_surface_coverage_required"] == 1.0


def test_the_v1_tier_depth_is_retained_so_a_release_1_board_stays_reproducible(registry):
    """Release 2 guardrail 2.1: version alongside V1 evidence rather than rewriting it."""
    from ffdraft.market.surface import TIER_DEPTH_RULE, TIER_DEPTH_V1

    decisions = registry["decisions"]
    assert decisions["tier_depth_rule_v1_version"] != decisions["tier_depth_rule_version"]
    assert TIER_DEPTH_V1.depth == 300
    assert TIER_DEPTH_RULE.depth > TIER_DEPTH_V1.depth


def test_ffc_is_production_and_may_never_claim_a_league_size(registry):
    """ADR-056, re-measured 2026-09-02: `teams=` is accepted and ignored."""
    entry = registry["sources"]["fantasyfootballcalculator_adp"]
    assert entry["policy"] == "production_allowed"
    assert entry["verified_at"] == "2026-09-02"
    assert entry["attribution_required"] is True
    assert "league_size_cohort" in entry["forbidden_roles"]
    assert entry["aggregation"]["window_type"] == "rolling"
    assert entry["aggregation"]["window_days_observed"] == 7
    assert entry["identity"]["coverage"] == 1.0
    assert entry["identity"]["quarantined"] == 0

    issue = next(i for i in entry["known_issues"] if i["id"] == "teams_accepted_and_ignored")
    assert "byte-identical" in issue["detail"]


def test_ffcs_own_cohorts_and_the_code_agree(registry):
    """A registry that named a cohort the adapter cannot build would be documentation only."""
    from ffdraft.sources.ffc import FFC_COHORTS

    recorded = set(registry["sources"]["fantasyfootballcalculator_adp"]["verified_cohorts_2026"])
    built = {str(cohort.filters["format"]) for cohort in FFC_COHORTS}
    assert recorded == built

    for cohort in FFC_COHORTS:
        assert cohort.league_size_semantics is None, (
            f"{cohort.cohort_id} claims a league size the API does not substantiate"
        )
        assert cohort.scoring_semantics in {"STD", "HALF", "PPR"}


def test_fantasypros_is_retained_but_not_published_and_says_why(registry):
    """ADR-064: a failed exit criterion, kept visible rather than rounded up."""
    entry = registry["sources"]["fantasypros_ecr"]
    assert entry["published_to_public_artifacts"] is False
    assert entry["adp_available"] is False
    assert "public_artifact_field" in entry["forbidden_roles"]
    assert "adp_price" in entry["forbidden_roles"]
    assert "adp_aggregate_component" in entry["forbidden_roles"]

    # The reason must be specific enough to act on, not "unavailable".
    reason = entry["published_blocked_reason"].lower()
    assert "free" in reason and "ten rows" in reason

    # And the revisit condition must be checkable rather than aspirational.
    assert entry["revisit_if"], "a blocked source with no revisit condition never unblocks"
    assert "public_api_limited" in " ".join(entry["revisit_if"])


def test_the_fantasypros_budget_matches_the_code_that_enforces_it(registry):
    """A cap nothing checks is a comment. This asserts the two agree."""
    from ffdraft.sources.fantasypros import (
        FANTASYPROS_DAILY_REQUEST_CAP,
        FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS,
    )

    budget = registry["sources"]["fantasypros_ecr"]["request_budget"]
    assert budget["daily_cap"] == FANTASYPROS_DAILY_REQUEST_CAP
    assert budget["min_interval_seconds"] == FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS
    assert budget["daily_cap"] < budget["vendor_stated_daily"], (
        "the project's cap is deliberately below the vendor's allowance (roadmap 10.1.3)"
    )


def test_the_fantasypros_key_is_recorded_as_a_name_and_stays_off_the_browser(registry):
    """The ADR-017 convention, plus the rule that only the backend may hold this one."""
    settings = registry["sources"]["fantasypros_ecr"]["client_settings"]
    assert settings["api_key_env"] == "FANTASYPROS_API_KEY"
    assert settings["api_key_env"].isupper()
    assert settings["browser_access"] is False
    assert "header" in settings["api_key_transport"].lower()
    assert "query" in settings["api_key_transport"].lower(), (
        "the transport note must say where the key does NOT go, not only where it does"
    )


def test_each_market_source_declares_how_it_resolves_identity(registry):
    """Three sources, three strategies. The difference is the reason a spec exists."""
    from ffdraft.market.multisource import MARKET_SOURCE_SPECS

    strategies = registry["decisions"]["market_identity_strategies"]
    assert strategies["fantasyfootballcalculator_adp"] == "generated_alias_only"
    assert strategies["myfantasyleague_adp"] == "two_live_bridges_cross_checked"
    assert strategies["fantasypros_ecr"] == "two_live_bridges_cross_checked"

    for source_id, spec in MARKET_SOURCE_SPECS.items():
        declared = strategies[source_id]
        assert spec.identity.alias_only is (declared == "generated_alias_only")


def test_generated_aliases_never_outrank_the_reviewed_file(registry):
    """A machine's reading of a name must not overwrite a person's decision (ADR-061)."""
    from ffdraft.identity.aliases import (
        AliasEntry,
        AliasMap,
        load_alias_map,
        load_production_aliases,
    )

    note = registry["decisions"]["market_alias_precedence"].lower()
    assert "identity-aliases.yaml" in note
    assert "wins" in note

    # And the loader actually behaves that way, which the note alone cannot prove.
    merged = load_production_aliases(source_ids=("fantasyfootballcalculator_adp",))
    reviewed = load_alias_map(None)
    assert isinstance(merged, AliasMap)
    for key, entry in reviewed.entries.items():
        assert isinstance(entry, AliasEntry)
        assert merged.entries[key] == entry


def test_the_generated_ffc_alias_file_is_loadable_and_labelled(registry):
    """The committed alias file must parse, and must say what produced it."""
    from ffdraft.identity.aliases import generated_alias_path, load_alias_map

    path = generated_alias_path("fantasyfootballcalculator_adp")
    if not path.is_file():  # pragma: no cover - the file is committed; this is a guard
        return
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert "GENERATED" in header, "a generated file must announce itself"

    aliases = load_alias_map(path)
    assert len(aliases) > 0
    for (source_id, _), entry in aliases.entries.items():
        assert source_id == "fantasyfootballcalculator_adp"
        assert entry.player_id.count(":") == 1, "a canonical id is namespaced (ADR-019)"
        assert entry.reviewed_at
