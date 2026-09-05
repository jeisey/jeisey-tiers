"""JSON Schema loading and validation for the public artifact contracts.

`schemas/*.schema.json` is a versioned contract (AGENTS.md section 18), so it is the single
source of truth for what a public record contains - including field order, which the CSV
serializer reads straight out of the schema rather than duplicating in Python. A field can
therefore only be added in one place.

``format: date-time`` is asserted rather than ignored: ``jsonschema`` treats formats as
annotations by default, so a malformed timestamp would pass silently. The validators here
install a :class:`~jsonschema.FormatChecker` backed by ``rfc3339-validator``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ffdraft.contracts import QualityCheck
from ffdraft.paths import schemas_dir

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ENVELOPE_SCHEMA",
    "RECORD_SCHEMAS",
    "RECORD_SCHEMA_VERSIONS",
    "load_schema",
    "record_field_order",
    "record_schema_version",
    "validate_envelope",
    "validate_records",
    "validator_for",
]

#: The version every Phase-1 artifact declares. A breaking change bumps this in the schema
#: files, the serializers, the frontend loader and the fixtures together.
ARTIFACT_SCHEMA_VERSION = "1.0"

ENVELOPE_SCHEMA = "artifact_envelope"

#: Record schemas, keyed by the name used in ``ArtifactSpec.schema_name``.
RECORD_SCHEMAS: tuple[str, ...] = (
    "tier_record",
    "arbitrage_record",
    "player_projection",
    "market_snapshot",
    "market_trend_series",
    "player_status",
    "build_metadata",
    # Phase 12. Additive: no Release 1 or Phase 10 record changes, and a bundle without
    # these two is still a complete draft-mode bundle (Release 2 guardrail 2.1).
    "ros_tier_record",
    "inseason_opportunity_record",
)

#: Per-record contract versions. The envelope's ``schema_version`` is the *bundle* version
#: and stays :data:`ARTIFACT_SCHEMA_VERSION`; a record schema versions independently so one
#: artifact can gain fields without forcing a bundle-wide break. Phase 5 moves
#: ``arbitrage_record`` to 1.1 (ADR-040); Phase 10 moves it to 1.2 (ADR-065), which is
#: **additive** - every 1.1 field keeps its exact meaning and its MyFantasyLeague
#: provenance, so a Release 1 board stays readable and reproducible (Release 2 guardrail
#: 2.1). Every other record stays at 1.0. A record whose declared version disagrees with its
#: schema's ``const`` fails validation, and ``tests/contract/test_artifact_contracts.py``
#: pins this map to the schema files.
RECORD_SCHEMA_VERSIONS: Mapping[str, str] = {
    "tier_record": "1.0",
    "arbitrage_record": "1.2",
    "player_projection": "1.0",
    "market_snapshot": "1.0",
    "market_trend_series": "1.0",
    "player_status": "1.0",
    "build_metadata": "1.0",
    "ros_tier_record": "1.0",
    "inseason_opportunity_record": "1.0",
}


def record_schema_version(name: str) -> str:
    """The contract version a record of this schema must declare."""
    try:
        return RECORD_SCHEMA_VERSIONS[name]
    except KeyError as exc:  # pragma: no cover - guarded by a contract test
        raise KeyError(f"unknown record schema {name!r}") from exc


_FORMAT_CHECKER = FormatChecker()


@cache
def load_schema(name: str, *, root: Path | None = None) -> Mapping[str, Any]:
    """Load one schema document by name (without the ``.schema.json`` suffix)."""
    path = schemas_dir(root=root) / f"{name}.schema.json"
    if not path.is_file():
        raise FileNotFoundError(f"no such artifact schema: {path}")
    loaded: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


@cache
def validator_for(name: str) -> Draft202012Validator:
    """A cached validator with RFC 3339 ``date-time`` assertion enabled."""
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=_FORMAT_CHECKER)


@cache
def record_field_order(name: str) -> tuple[str, ...]:
    """Declared property order for a record schema - also the CSV column order.

    JSON object key order is preserved by ``json.loads``, so the schema file's own layout
    is the column order. Reordering columns is therefore a visible schema edit.
    """
    schema = load_schema(name)
    properties = schema.get("properties", {})
    return tuple(properties.keys())


@cache
def required_fields(name: str) -> frozenset[str]:
    schema = load_schema(name)
    return frozenset(schema.get("required", ()))


def _errors_to_checks(
    validator: Draft202012Validator,
    instance: Mapping[str, Any],
    *,
    check_id: str,
    stage: str,
    label: str,
) -> list[QualityCheck]:
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    if not errors:
        return []
    rendered = "; ".join(
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors[:5]
    )
    schema = validator.schema
    title = schema.get("title", "schema") if isinstance(schema, Mapping) else "schema"
    return [
        QualityCheck.fail(
            check_id,
            stage=stage,
            message=f"{label} failed JSON Schema validation",
            observed=rendered,
            expected=f"conforms to {title}",
        ),
    ]


def validate_envelope(
    payload: Mapping[str, Any],
    *,
    stage: str = "artifacts",
) -> list[QualityCheck]:
    """Validate an artifact envelope (not its records)."""
    checks = _errors_to_checks(
        validator_for(ENVELOPE_SCHEMA),
        payload,
        check_id="artifact.envelope_schema",
        stage=stage,
        label="artifact envelope",
    )
    if checks:
        return checks
    declared = payload.get("record_count")
    actual = len(payload.get("records", ()))
    if declared != actual:
        return [
            QualityCheck.fail(
                "artifact.record_count_mismatch",
                stage=stage,
                message="envelope record_count disagrees with the records it carries",
                observed=f"declared {declared}, found {actual}",
                expected="equal",
            ),
        ]
    return [
        QualityCheck.ok(
            "artifact.envelope_schema",
            stage=stage,
            message=f"{payload.get('artifact')} envelope conforms",
            observed=f"{actual} record(s)",
        ),
    ]


def validate_records(
    schema_name: str,
    records: Sequence[Mapping[str, Any]],
    *,
    stage: str = "artifacts",
) -> list[QualityCheck]:
    """Validate every record against its record schema.

    All failures are reported, not just the first: a schema break usually affects an entire
    artifact, and one error message per build is a slow way to fix twenty fields.
    """
    validator = validator_for(schema_name)
    failures: list[QualityCheck] = []
    for index, record in enumerate(records):
        found = _errors_to_checks(
            validator,
            record,
            check_id="artifact.record_schema",
            stage=stage,
            label=f"{schema_name}[{index}]",
        )
        failures.extend(found)
        if len(failures) >= 20:
            break
    if failures:
        return failures
    return [
        QualityCheck.ok(
            "artifact.record_schema",
            stage=stage,
            message=f"all {schema_name} records conform",
            observed=f"{len(records)} record(s)",
        ),
    ]
