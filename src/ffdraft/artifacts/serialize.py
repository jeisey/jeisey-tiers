"""Public artifact serialization.

Three properties matter more than convenience here:

*deterministic* - records are sorted by the artifact's declared total ordering and JSON is
written with fixed separators and sorted-by-schema keys, so two identical builds produce
byte-identical files;

*schema-driven* - column order comes from the record schema, so JSON and CSV cannot drift
apart and a new field cannot be added to one without the other;

*validated before writing* - nothing reaches disk until it conforms. A half-written invalid
artifact is worse than no artifact, because `docs/OPERATIONS.md` section 8 wants a build to
fail safe rather than fail fresh.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ffdraft.artifacts.csv_flatten import flattener_for
from ffdraft.artifacts.schemas import (
    ARTIFACT_SCHEMA_VERSION,
    record_field_order,
    validate_envelope,
    validate_records,
)
from ffdraft.artifacts.spec import (
    BUILD_METADATA_FILENAME,
    BUILD_METADATA_SCHEMA,
    ArtifactSpec,
    spec_for,
)
from ffdraft.contracts import QualityCheck
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "CSV_LIST_SEPARATOR",
    "build_envelope",
    "records_to_csv",
    "write_artifact",
    "write_build_metadata",
]

#: Arrays (``quality_flags``) are joined with ``|`` in CSV. Commas would need quoting and
#: semicolons collide with European spreadsheet delimiters.
CSV_LIST_SEPARATOR = "|"


def build_envelope(
    artifact: str,
    records: Sequence[Mapping[str, Any]],
    *,
    build_id: str,
    generated_at: datetime,
    arbitrage_mode: str | None = None,
) -> dict[str, Any]:
    """Wrap records in the shared envelope (ADR-020)."""
    spec = spec_for(artifact)
    ordered = spec.sorted_records(records)
    envelope: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact": spec.artifact,
        "record_schema": spec.schema_name,
        "build_id": build_id,
        "generated_at_utc": isoformat_utc(generated_at),
        "record_count": len(ordered),
        "records": [_ordered_record(spec.schema_name, record) for record in ordered],
    }
    if arbitrage_mode is not None:
        envelope["arbitrage_mode"] = arbitrage_mode
    return envelope


def _ordered_record(schema_name: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Reorder a record's keys to the schema's declared order, dropping nothing.

    Undeclared keys are preserved at the end rather than silently discarded, so schema
    validation reports them instead of the serializer hiding them.
    """
    order = record_field_order(schema_name)
    ordered = {field: record[field] for field in order if field in record}
    extras = {key: value for key, value in record.items() if key not in ordered}
    return {**ordered, **extras}


def records_to_csv(artifact: str, records: Sequence[Mapping[str, Any]]) -> str:
    """Render records as CSV with declared columns and stable row order.

    An artifact whose JSON record nests declares a flattener (Phase 10, ADR-065): a CSV cell
    holds a scalar, and rendering an array of per-source comparisons with ``str()`` would
    produce a cell containing a Python repr. Everything else keeps the previous behaviour -
    columns from the record schema, values copied through.
    """

    def identity(record: Mapping[str, Any]) -> Mapping[str, Any]:
        return record

    spec = spec_for(artifact)
    flattener = flattener_for(artifact)
    columns: Sequence[str]
    project: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    if flattener is None:
        columns, project = record_field_order(spec.schema_name), identity
    else:
        columns, project = flattener
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(columns))
    for record in spec.sorted_records(records):
        row = project(record)
        writer.writerow([_csv_cell(row.get(column)) for column in columns])
    return buffer.getvalue()


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return CSV_LIST_SEPARATOR.join(str(item) for item in value)
    return str(value)


def write_artifact(
    artifact: str,
    records: Sequence[Mapping[str, Any]],
    *,
    out_dir: Path,
    build_id: str,
    generated_at: datetime,
    arbitrage_mode: str | None = None,
) -> tuple[list[Path], list[QualityCheck]]:
    """Validate then write one artifact's JSON (and CSV where the spec declares one).

    Returns the paths written and the validation record. Nothing is written when a critical
    check fails, so a failed build leaves the previous artifacts untouched.
    """
    spec = spec_for(artifact)
    envelope = build_envelope(
        artifact,
        records,
        build_id=build_id,
        generated_at=generated_at,
        arbitrage_mode=arbitrage_mode,
    )
    checks: list[QualityCheck] = []
    checks.extend(validate_envelope(envelope, stage=f"artifacts.{artifact}"))
    checks.extend(
        validate_records(spec.schema_name, envelope["records"], stage=f"artifacts.{artifact}"),
    )
    if any(check.blocking for check in checks):
        return [], checks

    out_dir.mkdir(parents=True, exist_ok=True)
    written = [_write_json(out_dir / spec.json_filename, envelope)]
    if spec.csv_filename:
        csv_path = out_dir / spec.csv_filename
        csv_path.write_text(records_to_csv(artifact, envelope["records"]), encoding="utf-8")
        written.append(csv_path)
    return written, checks


def write_build_metadata(
    metadata: Mapping[str, Any],
    *,
    out_dir: Path,
) -> tuple[list[Path], list[QualityCheck]]:
    """Validate and write ``build_metadata.json``."""
    ordered = _ordered_record(BUILD_METADATA_SCHEMA, metadata)
    checks = validate_records(BUILD_METADATA_SCHEMA, [ordered], stage="artifacts.build_metadata")
    if any(check.blocking for check in checks):
        return [], checks
    out_dir.mkdir(parents=True, exist_ok=True)
    return [_write_json(out_dir / BUILD_METADATA_FILENAME, ordered)], checks


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    # Fixed separators and a trailing newline keep diffs and hashes stable across runs.
    path.write_text(
        json.dumps(payload, indent=2, separators=(",", ": "), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def artifact_specs() -> Mapping[str, ArtifactSpec]:
    from ffdraft.artifacts.spec import ARTIFACT_SPECS

    return ARTIFACT_SPECS
