"""Public artifact serialization and validation.

Everything the browser receives is produced here, and nothing reaches disk without passing
its JSON Schema and the semantic rules in `docs/DATA_CONTRACTS.md` sections 8 and 12.
"""

from __future__ import annotations

from ffdraft.artifacts.schemas import (
    ARTIFACT_SCHEMA_VERSION,
    RECORD_SCHEMAS,
    load_schema,
    record_field_order,
    validate_envelope,
    validate_records,
)
from ffdraft.artifacts.serialize import (
    CSV_LIST_SEPARATOR,
    build_envelope,
    records_to_csv,
    write_artifact,
    write_build_metadata,
)
from ffdraft.artifacts.spec import (
    ARTIFACT_SPECS,
    BUILD_METADATA_FILENAME,
    BUILD_METADATA_SCHEMA,
    ArtifactSpec,
    spec_for,
)
from ffdraft.artifacts.validate import validate_artifact_directory

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ARTIFACT_SPECS",
    "BUILD_METADATA_FILENAME",
    "BUILD_METADATA_SCHEMA",
    "CSV_LIST_SEPARATOR",
    "RECORD_SCHEMAS",
    "ArtifactSpec",
    "build_envelope",
    "load_schema",
    "record_field_order",
    "records_to_csv",
    "spec_for",
    "validate_artifact_directory",
    "validate_envelope",
    "validate_records",
    "write_artifact",
    "write_build_metadata",
]
