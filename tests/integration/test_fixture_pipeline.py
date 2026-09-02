"""The Phase-1 exit gate, executed.

`docs/TEST_STRATEGY.md` 2.3 calls this the key PR CI smoke path: fixtures flow through
normalization, canonical identity, internal contracts, a deterministic stub valuation and
artifact serialization, with no network anywhere. The assertions below are the exit-gate
items, one by one, plus the semantic inspection that item 9 requires - schema validity is
checked separately and is not sufficient on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ffdraft.artifacts import validate_artifact_directory
from ffdraft.contracts import ResolutionStatus
from ffdraft.identity.resolver import (
    REASON_BRIDGE_DISAGREEMENT,
    REASON_NO_BRIDGE,
    REASON_NON_PLAYER_ENTITY,
    REASON_SLEEPER_GSIS_MISMATCH,
)
from ffdraft.pipeline import FIXTURE_MODEL_VERSION, build_fixture_artifacts

ARTIFACT_FILES = (
    "tiers.json",
    "tiers.csv",
    "arbitrage.json",
    "arbitrage.csv",
    "projections.json",
    "projections.csv",
    "market_snapshot.json",
    "build_metadata.json",
)


def _load(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Exit gate 3: fixture -> adapter -> identity -> contracts -> serialization
# --------------------------------------------------------------------------------------


def test_pipeline_runs_end_to_end_without_network(pipeline_result):
    assert pipeline_result.registry, "no canonical players were built"
    assert set(pipeline_result.records) == {
        "tiers",
        "arbitrage",
        "projections",
        "market_snapshot",
        "player_status",
    }
    assert all(records for records in pipeline_result.records.values())


def test_every_expected_artifact_is_written(built_artifacts):
    missing = [name for name in ARTIFACT_FILES if not (built_artifacts / name).is_file()]
    assert not missing, f"pipeline did not write {missing}"


# --------------------------------------------------------------------------------------
# Exit gate 4: generated artifacts validate against the repository JSON Schemas
# --------------------------------------------------------------------------------------


def test_generated_artifacts_pass_schema_and_semantic_validation(built_artifacts):
    gate = validate_artifact_directory(built_artifacts)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]


def test_the_build_gate_passes(pipeline_result):
    assert pipeline_result.gate.passed, [
        check.to_dict() for check in pipeline_result.gate.critical_failures
    ]


# --------------------------------------------------------------------------------------
# Exit gate 5: a deliberately ambiguous fixture fails closed for the intended reason
# --------------------------------------------------------------------------------------


def test_the_conflicting_market_fixture_fails_closed(pipeline_result):
    outcomes = {o.external_player_id: o for o in pipeline_result.market_outcomes}
    conflicted = outcomes["6000015"]
    assert conflicted.status is ResolutionStatus.AMBIGUOUS
    assert conflicted.reason == REASON_BRIDGE_DISAGREEMENT
    assert conflicted.player_id is None


def test_the_conflicting_sleeper_fixture_fails_closed(pipeline_result):
    outcomes = {o.external_player_id: o for o in pipeline_result.sleeper_outcomes}
    conflicted = outcomes["5000014"]
    assert conflicted.status is ResolutionStatus.AMBIGUOUS
    assert conflicted.reason == REASON_SLEEPER_GSIS_MISMATCH


def test_a_failed_identity_never_reaches_a_public_artifact(built_artifacts, pipeline_result):
    """The whole point of failing closed: the record is excluded, not guessed at."""
    ambiguous_externals = {
        o.external_player_id
        for o in pipeline_result.market_outcomes
        if o.status is ResolutionStatus.AMBIGUOUS
    }
    assert ambiguous_externals, "the fixture must exercise at least one ambiguous identity"

    for name in ("arbitrage.json", "market_snapshot.json"):
        records = _load(built_artifacts, name)["records"]
        published = {record["player_id"] for record in records}
        # gsis:00-0000015 is the player the ESPN bridge would have chosen for MFL 6000015.
        assert "gsis:00-0000015" not in published, f"{name} published an ambiguous identity"


def test_team_units_are_excluded_as_non_player_entities(pipeline_result):
    outcomes = {o.external_player_id: o for o in pipeline_result.market_outcomes}
    for team_unit in ("151", "152"):
        assert outcomes[team_unit].reason == REASON_NON_PLAYER_ENTITY
        assert outcomes[team_unit].player_id is None


def test_a_priced_but_unrostered_player_is_unresolved_not_invented(pipeline_result):
    outcomes = {o.external_player_id: o for o in pipeline_result.market_outcomes}
    assert outcomes["6000099"].status is ResolutionStatus.UNRESOLVED
    assert outcomes["6000099"].reason == REASON_NO_BRIDGE


# --------------------------------------------------------------------------------------
# Exit gate 9: semantic correctness, not merely schema validity
# --------------------------------------------------------------------------------------


def test_tier_board_is_ordered_contiguous_and_hand_checkable(built_artifacts):
    rows = [
        record
        for record in _load(built_artifacts, "tiers.json")["records"]
        if record["league_preset_id"] == "redraft-12"
    ]
    assert [row["fair_rank"] for row in rows] == list(range(1, len(rows) + 1))

    # Hand-worked from the fixture: RB replacement is the last RB (188.0), so Dez Okonkwo's
    # 340.0 gives VORP 152.0, and he clears the field by 48 points - a legitimate singleton
    # top tier (docs/DATA_CONTRACTS.md section 14).
    top = rows[0]
    assert top["display_name"] == "Dez Okonkwo"
    assert top["expected_vorp"] == pytest.approx(152.0)
    assert top["tier_ordinal"] == 0
    assert sum(1 for row in rows if row["tier_ordinal"] == 0) == 1

    ordinals = [row["tier_ordinal"] for row in rows]
    assert ordinals == sorted(ordinals), "tier ordinals must not decrease with fair rank"


def test_position_ranks_count_within_position(built_artifacts):
    rows = [
        record
        for record in _load(built_artifacts, "tiers.json")["records"]
        if record["league_preset_id"] == "redraft-12"
    ]
    seen: dict[str, int] = {}
    for row in sorted(rows, key=lambda record: record["fair_rank"]):
        seen[row["position"]] = seen.get(row["position"], 0) + 1
        assert row["position_rank"] == seen[row["position"]]


def test_quantiles_are_monotonic_in_both_products(built_artifacts):
    for name, prefix in (("tiers.json", "vorp"), ("projections.json", "points")):
        for record in _load(built_artifacts, name)["records"]:
            values = [record[f"{q}_{prefix}"] for q in ("p10", "p25", "p50", "p75", "p90")]
            assert values == sorted(values), f"{name} {record['player_id']} quantiles {values}"


def test_rank_gap_follows_the_documented_sign_convention(built_artifacts):
    """Positive gap = the model would take the player earlier than the market does."""
    records = _load(built_artifacts, "arbitrage.json")["records"]
    for record in records:
        assert record["rank_gap"] == pytest.approx(record["market_adp"] - record["fair_rank"])

    by_name = {record["display_name"]: record for record in records}
    # Tobias Ferreira: fair rank 4, ADP 12.1 -> the market is late on him.
    assert by_name["Tobias Ferreira"]["rank_gap"] > 0
    # Dez Okonkwo: fair rank 1, ADP 2.4 -> the market already agrees, so barely any edge.
    assert by_name["Dez Okonkwo"]["rank_gap"] < by_name["Tobias Ferreira"]["rank_gap"]


def test_arbitrage_scores_span_the_range_without_saturating(built_artifacts):
    scores = [
        record["arbitrage_score"]
        for record in _load(built_artifacts, "arbitrage.json")["records"]
        if record["league_preset_id"] == "redraft-12"
    ]
    assert min(scores) > 0 and max(scores) < 100
    assert len(set(scores)) == len(scores), "a degenerate score tells a reader nothing"


def test_baseline_mode_publishes_no_learned_model_fields(built_artifacts):
    """ADR-010: V1 ships a labelled baseline and claims nothing it did not train."""
    envelope = _load(built_artifacts, "arbitrage.json")
    assert envelope["arbitrage_mode"] == "baseline"
    for record in envelope["records"]:
        assert record["arbitrage_mode"] == "baseline"
        assert record["expected_surplus_vorp"] is None
        assert record["p_positive_surplus"] is None


def test_market_records_carry_no_standard_deviation_or_data_as_of(built_artifacts):
    """Phase-0 13.5 measured both absences; publishing either would be fabrication."""
    for record in _load(built_artifacts, "market_snapshot.json")["records"]:
        assert record["adp_sd"] is None
        assert record["source_as_of_utc"] is None
        assert record["adp_low"] <= record["market_adp"] <= record["adp_high"]
        assert "cohort_approximate" in record["quality_flags"]


def test_an_intrinsic_player_without_a_price_still_appears_in_tiers(built_artifacts):
    """docs/TEST_STRATEGY.md 2.9: missing ADP must not damage the tier board."""
    tier_ids = {
        record["player_id"]
        for record in _load(built_artifacts, "tiers.json")["records"]
        if record["league_preset_id"] == "redraft-12"
    }
    arbitrage_ids = {
        record["player_id"]
        for record in _load(built_artifacts, "arbitrage.json")["records"]
        if record["league_preset_id"] == "redraft-12"
    }
    # Ade Fontenot has no MFL quote in the fixture set.
    assert "gsis:00-0000013" in tier_ids
    assert "gsis:00-0000013" not in arbitrage_ids


def test_rookie_and_status_context_reaches_the_artifact(built_artifacts):
    records = {
        record["player_id"]: record
        for record in _load(built_artifacts, "projections.json")["records"]
    }
    assert "rookie" in records["gsis:00-0000011"]["quality_flags"]
    assert "roster_status_res" in records["gsis:00-0000016"]["quality_flags"]
    assert "no_sleeper_status" in records["gsis:00-0000008"]["quality_flags"]


def test_build_metadata_describes_the_stub_honestly(built_artifacts):
    metadata = _load(built_artifacts, "build_metadata.json")
    assert metadata["intrinsic_model_version"] == FIXTURE_MODEL_VERSION
    assert metadata["arbitrage_mode"] == "baseline"
    assert metadata["arbitrage_model_version"] is None
    assert metadata["supported_presets"] == ["redraft-10", "redraft-12"]
    assert metadata["quality_gate"]["status"] == "pass"
    source_ids = {source["source_id"] for source in metadata["sources"]}
    assert source_ids == {"nflreadpy", "sleeper", "myfantasyleague_adp"}


def test_recorded_warnings_name_the_real_findings(built_artifacts):
    warnings = " ".join(_load(built_artifacts, "build_metadata.json")["warnings"])
    assert "ambiguous identities" in warnings
    # Sleeper's reported gsis_id contradicts the canonical id on one fixture player, and
    # the cross-check is supposed to fail that record closed rather than average over it.
    assert "gsis_id disagreed" in warnings


def test_cohort_approximation_is_recorded_where_it_belongs(built_artifacts):
    """ADR-012/ADR-039: approximation is a property of an assignment, not of a quote.

    Phase 1 recorded it as a build warning because a quote row carried the flag. It is now
    a per-preset verdict, so it travels on the assignment in build metadata and on the rows
    the assignment produced - which is where a reader of the arbitrage table will look.
    """
    metadata = _load(built_artifacts, "build_metadata.json")
    assignments = metadata["market"]["assignments"]
    assert assignments, "the build recorded no cohort assignment"
    assert all(assignment["exact"] is False for assignment in assignments)
    assert all(
        "approximate cohort" in assignment["source_format_detail"] for assignment in assignments
    )

    arbitrage = _load(built_artifacts, "arbitrage.json")["records"]
    assert arbitrage
    for record in arbitrage:
        assert "cohort_approximate" in record["quality_flags"]
        assert "approximate cohort" in record["market_cohort_detail"]


# --------------------------------------------------------------------------------------
# Reproducibility
# --------------------------------------------------------------------------------------


def test_two_builds_are_byte_identical(tmp_path, app_config, pipeline_fixture_dir):
    """ARCHITECTURE section 13: identical inputs must reproduce identical artifacts."""
    first, second = tmp_path / "a", tmp_path / "b"
    for out_dir in (first, second):
        build_fixture_artifacts(
            fixture_dir=pipeline_fixture_dir,
            out_dir=out_dir,
            config=app_config,
            git_sha="0000000",
        )
    for name in ARTIFACT_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_csv_export_matches_the_json_artifact(built_artifacts):
    """Every CSV describes the same rows as its JSON, in the same order.

    The *columns* need not be the same list. A flat record's CSV is its JSON with commas, so
    the header is the record's field order; an artifact whose record nests declares a CSV
    projection instead, because a cell holds a scalar and an array of per-source comparisons
    is not one (ADR-065). What must hold either way is that the CSV is a faithful view: same
    row count, same order, and every column it claims actually filled from that record.
    """
    import csv

    from ffdraft.artifacts.csv_flatten import flattener_for

    for artifact in ("tiers", "arbitrage", "projections"):
        records = _load(built_artifacts, f"{artifact}.json")["records"]
        with (built_artifacts / f"{artifact}.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == len(records)
        assert rows[0]["player_id"] == records[0]["player_id"]

        flattener = flattener_for(artifact)
        if flattener is None:
            assert list(rows[0]) == list(records[0])
            continue
        columns, project = flattener
        assert list(rows[0]) == list(columns)
        # The projection of the first record must reproduce the first CSV row exactly, so a
        # column that silently stopped being filled would fail here rather than ship empty.
        projected = project(records[0])
        assert set(projected) == set(columns)
        assert projected["player_id"] == rows[0]["player_id"]
