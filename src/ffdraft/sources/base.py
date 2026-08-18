"""Source adapter protocol and shared machinery.

`docs/ARCHITECTURE.md` section 5 scopes an adapter tightly: fetch, retry/timeout, raw
schema normalization, retrieval timestamp, source metadata. Cross-source identity and
feature engineering are explicitly *not* its job.

Every adapter here splits into two halves, and the split is what makes the Phase-1 exit
gate reachable without a network:

``normalize``
    Pure. Raw rows in, a contract-shaped :class:`~ffdraft.contracts.source.SourceBatch`
    out. Every fixture test drives this.

``fetch``
    The I/O wrapper. Calls the upstream, then hands the result to ``normalize``. It is the
    only part that needs the network, and it is covered by opt-in live tests only.

Adapters also declare ``required_source_columns``: the upstream columns normalization
actually reads. Checking those against the *raw* payload turns silent schema drift - the
failure mode where a renamed upstream column becomes a column of nulls three stages later -
into a critical quality record at the boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import polars as pl

from ffdraft.config import SourceEntry
from ffdraft.contracts import (
    FrameContract,
    QualityCheck,
    SourceBatch,
    SourceMetadata,
    SourceStatus,
    ValidationReport,
    frame_content_hash,
)
from ffdraft.contracts.enums import Severity
from ffdraft.timeutil import utc_now

__all__ = [
    "BaseSourceAdapter",
    "RawRecords",
    "SourceAdapter",
    "SourceConfig",
    "SourceFetchError",
    "as_rows",
]

#: Raw payloads arrive either as Polars frames (nflreadpy) or row dicts (JSON APIs).
RawRecords = Sequence[Mapping[str, Any]] | pl.DataFrame


class SourceFetchError(RuntimeError):
    """Raised when an upstream call fails in a way the adapter cannot normalize."""


@dataclass(frozen=True, slots=True)
class SourceConfig:
    """Per-call adapter configuration.

    ``policy`` is the registry entry for this source. Passing it in rather than looking it
    up inside the adapter keeps the policy decision auditable at the call site and lets a
    test drive an adapter under a hypothetical policy.
    """

    season: int
    policy: SourceEntry | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 3
    #: Seconds between consecutive requests to the same host. MFL and Sleeper both publish
    #: rate expectations; pacing is cheaper than being throttled.
    min_interval_seconds: float = 1.0
    options: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """The interface every source adapter implements."""

    source_id: str
    resource: str
    adapter_version: str
    contract: FrameContract

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        """Retrieve and normalize current data. Performs network I/O."""
        ...

    def validate_raw(self, batch: SourceBatch) -> ValidationReport:
        """Validate a normalized batch against its contract and semantic expectations."""
        ...


def as_rows(records: RawRecords) -> list[dict[str, Any]]:
    """Coerce either raw payload shape into a list of row dicts."""
    if isinstance(records, pl.DataFrame):
        return records.to_dicts()
    return [dict(record) for record in records]


def raw_columns(records: RawRecords) -> set[str]:
    """The set of columns present in a raw payload.

    JSON APIs omit absent keys per row, so the union across rows is the honest answer for
    row-dict payloads; a Polars frame states its columns directly.
    """
    if isinstance(records, pl.DataFrame):
        return set(records.columns)
    columns: set[str] = set()
    for record in records:
        columns.update(record.keys())
    return columns


class BaseSourceAdapter:
    """Shared adapter behaviour: metadata assembly and contract validation.

    Subclasses supply the class attributes and a ``normalize`` implementation.
    """

    source_id: str = ""
    resource: str = ""
    adapter_version: str = "1.0"
    contract: FrameContract
    required_source_columns: frozenset[str] = frozenset()
    #: Name of the Phase-0 recorded schema in ``tests/fixtures/source_schemas/`` that this
    #: adapter was written against. A test asserts the required columns are a subset of it,
    #: which keeps adapters tied to measured evidence rather than to assumption.
    recorded_schema_fixture: str = ""
    #: Minimum rows a healthy payload carries. 0 disables the check.
    min_expected_records: int = 0
    license_policy_version: str = ""

    def check_source_schema(self, records: RawRecords) -> list[QualityCheck]:
        """Compare the raw payload's columns against what normalization reads."""
        present = raw_columns(records)
        missing = sorted(self.required_source_columns - present)
        if missing:
            return [
                QualityCheck.fail(
                    "source_schema.missing_columns",
                    stage=self.source_id,
                    message=f"{self.resource} no longer supplies columns this adapter reads",
                    observed=", ".join(missing),
                    expected=", ".join(sorted(self.required_source_columns)),
                ),
            ]
        return [
            QualityCheck.ok(
                "source_schema.present",
                stage=self.source_id,
                message=f"{self.resource} supplies every required column",
                observed=f"{len(present)} column(s)",
            ),
        ]

    def build_batch(
        self,
        frame: pl.DataFrame,
        *,
        retrieved_at: datetime | None = None,
        source_as_of: datetime | None = None,
        warning_codes: Sequence[str] = (),
        detail: Mapping[str, str] | None = None,
        status: SourceStatus | None = None,
    ) -> SourceBatch:
        """Wrap a normalized frame with the source metadata contract."""
        coerced = self.contract.coerce(frame)
        metadata = SourceMetadata(
            source_id=self.source_id,
            resource=self.resource,
            retrieved_at_utc=retrieved_at or utc_now(),
            source_as_of_utc=source_as_of,
            source_schema_version=f"{self.contract.contract_id}/{self.contract.version}",
            record_count=coerced.height,
            content_hash=frame_content_hash(coerced),
            status=status or (SourceStatus.WARNING if warning_codes else SourceStatus.PASS),
            warning_codes=tuple(dict.fromkeys(warning_codes)),
            license_policy_version=self.license_policy_version,
            detail=dict(detail or {}),
        )
        return SourceBatch(metadata=metadata, frame=coerced)

    def validate_raw(self, batch: SourceBatch) -> ValidationReport:
        """Contract conformance plus the emptiness check every source shares."""
        checks: list[QualityCheck] = list(
            self.contract.validate(batch.frame, stage=self.source_id),
        )
        checks.extend(self.semantic_checks(batch))
        if self.min_expected_records and batch.frame.height < self.min_expected_records:
            checks.append(
                QualityCheck.fail(
                    "source.too_few_records",
                    stage=self.source_id,
                    message=f"{self.resource} returned fewer rows than a healthy payload",
                    observed=str(batch.frame.height),
                    expected=f">= {self.min_expected_records}",
                    # A core source going empty is critical; a thin-but-present payload is
                    # a warning, because upstream row counts legitimately move.
                    severity=Severity.CRITICAL if batch.frame.height == 0 else Severity.WARNING,
                ),
            )
        return ValidationReport(source_id=self.source_id, checks=tuple(checks))

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """Adapter-specific checks beyond the frame contract. Override as needed."""
        return ()
