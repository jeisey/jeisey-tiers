"""Public artifact contract tests.

`schemas/*.schema.json` is the single source of truth for a public record - including its
field order, which the CSV serializer reads back out of the schema. These tests pin that
relationship so a field cannot be added to the serializer without appearing in the schema,
or reordered in one without the other.
"""

from __future__ import annotations

import json

import pytest

from ffdraft.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    ARTIFACT_SPECS,
    RECORD_SCHEMAS,
    build_envelope,
    load_schema,
    record_field_order,
    records_to_csv,
    validate_envelope,
    validate_records,
    write_artifact,
)
from ffdraft.contracts import CheckStatus
from ffdraft.timeutil import parse_utc

GENERATED_AT = parse_utc("2026-08-18T12:00:00Z")


@pytest.mark.parametrize("name", RECORD_SCHEMAS)
def test_every_record_schema_is_a_valid_2020_12_document(name):
    schema = load_schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False, "public contracts must be closed"
    assert schema["properties"]["schema_version"]["const"] == ARTIFACT_SCHEMA_VERSION


@pytest.mark.parametrize("artifact", sorted(ARTIFACT_SPECS))
def test_every_artifact_spec_points_at_a_real_schema(artifact):
    spec = ARTIFACT_SPECS[artifact]
    order = record_field_order(spec.schema_name)
    assert order, f"{spec.schema_name} declares no properties"
    missing_keys = set(spec.key_fields) - set(order)
    assert not missing_keys, f"{artifact} keys on undeclared fields {sorted(missing_keys)}"
    missing_sort = set(spec.sort_fields) - set(order)
    assert not missing_sort, f"{artifact} sorts on undeclared fields {sorted(missing_sort)}"


@pytest.mark.parametrize("artifact", sorted(ARTIFACT_SPECS))
def test_sort_order_ends_in_a_stable_tie_break(artifact):
    """A total ordering is what makes two identical builds byte-identical."""
    assert ARTIFACT_SPECS[artifact].sort_fields[-1] == "player_id"


def test_date_time_format_is_asserted_not_merely_annotated():
    """jsonschema ignores `format` unless a checker is installed; a bad timestamp must fail."""
    checks = validate_records(
        "market_snapshot",
        [
            {
                "schema_version": "1.0",
                "source_id": "myfantasyleague_adp",
                "snapshot_at_utc": "not-a-timestamp",
                "season": 2026,
                "league_size": 12,
                "scoring_preset": "PPR",
                "player_id": "gsis:00-0000001",
                "market_adp": 2.4,
                "quality_flags": [],
            },
        ],
    )
    assert any(check.status is CheckStatus.FAIL for check in checks)


def test_an_undeclared_field_is_rejected_rather_than_silently_dropped():
    envelope = build_envelope(
        "projections",
        [_projection(extra="surprise")],
        build_id="b",
        generated_at=GENERATED_AT,
    )
    assert "extra" in envelope["records"][0], "the serializer must not hide undeclared fields"
    checks = validate_records("player_projection", envelope["records"])
    assert any(check.status is CheckStatus.FAIL for check in checks)


def test_envelope_declares_the_schema_version_outside_the_records():
    """docs/DATA_CONTRACTS.md 13: a frontend must reject a bad major version before parsing."""
    envelope = build_envelope(
        "projections",
        [_projection()],
        build_id="b",
        generated_at=GENERATED_AT,
    )
    assert envelope["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert envelope["record_schema"] == "player_projection"
    assert envelope["record_count"] == 1
    assert not [c for c in validate_envelope(envelope) if c.status is CheckStatus.FAIL]


def test_a_lying_record_count_is_caught():
    envelope = build_envelope(
        "projections",
        [_projection()],
        build_id="b",
        generated_at=GENERATED_AT,
    )
    envelope["record_count"] = 99
    assert any(
        check.check_id == "artifact.record_count_mismatch" for check in validate_envelope(envelope)
    )


def test_csv_columns_are_the_schema_columns_in_schema_order():
    csv_text = records_to_csv("projections", [_projection()])
    header = csv_text.splitlines()[0].split(",")
    assert header == list(record_field_order("player_projection"))


def test_csv_renders_nulls_lists_and_booleans_predictably():
    record = _projection(team=None, quality_flags=["rookie", "no_sleeper_status"])
    row = records_to_csv("projections", [record]).splitlines()[1].split(",")
    columns = list(record_field_order("player_projection"))
    assert row[columns.index("team")] == ""
    assert row[columns.index("quality_flags")] == "rookie|no_sleeper_status"


def test_nothing_is_written_when_validation_fails(tmp_path):
    """A half-written invalid artifact is worse than none (docs/OPERATIONS.md section 8)."""
    written, checks = write_artifact(
        "projections",
        [_projection(expected_points="not a number")],
        out_dir=tmp_path,
        build_id="b",
        generated_at=GENERATED_AT,
    )
    assert written == []
    assert any(check.blocking for check in checks)
    assert list(tmp_path.iterdir()) == []


def test_records_are_written_in_the_specs_sort_order(tmp_path):
    records = [
        _projection(player_id="gsis:00-0000002"),
        _projection(player_id="gsis:00-0000001"),
    ]
    written, checks = write_artifact(
        "projections",
        records,
        out_dir=tmp_path,
        build_id="b",
        generated_at=GENERATED_AT,
    )
    assert not [check for check in checks if check.blocking]
    payload = json.loads((tmp_path / "projections.json").read_text())
    assert [record["player_id"] for record in payload["records"]] == [
        "gsis:00-0000001",
        "gsis:00-0000002",
    ]
    assert written


def _projection(**overrides: object) -> dict:
    record = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "build_id": "b",
        "model_version": "fixture-stub-0",
        "season": 2026,
        "as_of_utc": "2026-08-18T12:00:00Z",
        "player_id": "gsis:00-0000001",
        "display_name": "Marcus Vandelay",
        "team": "ATL",
        "position": "QB",
        "scoring_preset": "PPR",
        "expected_points": 355.0,
        "p10_points": 255.6,
        "p25_points": 312.4,
        "p50_points": 355.0,
        "p75_points": 397.6,
        "p90_points": 454.4,
        "uncertainty_points": 99.4,
        "expected_games": 17.0,
        "quality_flags": [],
    }
    record.update(overrides)
    return record
