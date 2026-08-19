"""Source batch and metadata contracts.

`docs/DATA_SOURCES.md` section 11 fixes what every ingestion batch has to record. The two
timestamps are separate on purpose (AGENTS.md section 5): ``retrieved_at_utc`` is when we
asked, ``source_as_of_utc`` is when the data was true. MFL's ADP export supplies only the
first - its ``timestamp`` field is response-generation time - so conflating them would
manufacture a freshness claim the source never made.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.contracts.enums import SourceStatus
from ffdraft.contracts.quality import QualityCheck, critical_failures, failures
from ffdraft.timeutil import ensure_utc, isoformat_utc

__all__ = ["SourceBatch", "SourceMetadata", "ValidationReport", "frame_content_hash"]


def frame_content_hash(frame: pl.DataFrame) -> str:
    """A stable content hash for a normalized frame.

    Used for cache keys and drift detection. Hashing the frame's own row hashes keeps this
    independent of Polars' in-memory representation but sensitive to any value change.
    """
    digest = hashlib.sha256()
    digest.update("|".join(frame.columns).encode("utf-8"))
    digest.update(b"\x00")
    if frame.height:
        for value in frame.hash_rows(seed=0).to_list():
            digest.update(int(value).to_bytes(8, "little", signed=False))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Provenance for one ingestion batch."""

    source_id: str
    resource: str
    retrieved_at_utc: datetime
    record_count: int
    #: Internal adapter contract version, bumped when normalization output changes shape.
    source_schema_version: str
    status: SourceStatus = SourceStatus.PASS
    source_as_of_utc: datetime | None = None
    content_hash: str | None = None
    warning_codes: tuple[str, ...] = ()
    license_policy_version: str = ""
    detail: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "retrieved_at_utc", ensure_utc(self.retrieved_at_utc))
        if self.source_as_of_utc is not None:
            object.__setattr__(self, "source_as_of_utc", ensure_utc(self.source_as_of_utc))
        if self.record_count < 0:
            raise ValueError(f"{self.source_id}: negative record_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "resource": self.resource,
            "retrieved_at_utc": isoformat_utc(self.retrieved_at_utc),
            "source_as_of_utc": (
                isoformat_utc(self.source_as_of_utc) if self.source_as_of_utc else None
            ),
            "source_schema_version": self.source_schema_version,
            "record_count": self.record_count,
            "content_hash": self.content_hash,
            "status": str(self.status),
            "warning_codes": list(self.warning_codes),
            "license_policy_version": self.license_policy_version,
            "detail": dict(self.detail),
        }

    def build_metadata_entry(self) -> dict[str, Any]:
        """The subset that ``build_metadata.schema.json`` accepts for a source."""
        return {
            "source_id": self.source_id,
            "status": str(self.status),
            "retrieved_at_utc": isoformat_utc(self.retrieved_at_utc),
            "source_as_of_utc": (
                isoformat_utc(self.source_as_of_utc) if self.source_as_of_utc else None
            ),
            "record_count": self.record_count,
            "warnings": list(self.warning_codes),
        }


@dataclass(frozen=True, slots=True)
class SourceBatch:
    """A normalized frame plus its provenance."""

    metadata: SourceMetadata
    frame: pl.DataFrame

    @property
    def source_id(self) -> str:
        return self.metadata.source_id

    @property
    def is_empty(self) -> bool:
        return self.frame.height == 0


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The outcome of validating one batch."""

    source_id: str
    checks: tuple[QualityCheck, ...] = ()

    @property
    def ok(self) -> bool:
        """No critical failure. Warnings are recorded, not blocking."""
        return not critical_failures(self.checks)

    @property
    def failures(self) -> tuple[QualityCheck, ...]:
        return failures(self.checks)

    def extend(self, more: Sequence[QualityCheck]) -> ValidationReport:
        return ValidationReport(source_id=self.source_id, checks=(*self.checks, *more))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
        }
