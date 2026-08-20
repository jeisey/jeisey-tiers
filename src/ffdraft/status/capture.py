"""Retaining a point-in-time Sleeper current-status capture (ADR-038, ADR-043).

Sleeper is a *current-state* feed with no history: ``/v1/players/nfl`` describes today and
nothing else. Retaining a normalized capture under the same append-only discipline as the
market store buys one specific thing — a status artifact that can be rebuilt offline, byte
for byte, from evidence rather than from a feed that has since moved. It is **not** future
training data; ADR-044 forbids that use explicitly.

Only the normalized rows are retained. The raw player map is ~14.6 MB, nothing downstream
reads a field outside the normalized contract, and a daily 14 MB commit would make the store
unusable long before it became useful.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ffdraft.contracts import SourceBatch
from ffdraft.quality import QualityGate
from ffdraft.retention import (
    MANIFEST_FILENAME,
    SnapshotConflictError,
    SnapshotStore,
    content_hash,
    parse_snapshot_key,
    snapshot_key,
)
from ffdraft.sources.base import SourceConfig
from ffdraft.sources.sleeper import SLEEPER_SOURCE_ID, SleeperPlayerAdapter
from ffdraft.timeutil import isoformat_utc, parse_utc, utc_now

__all__ = [
    "STATUS_NORMALIZED_FILENAME",
    "STATUS_PREFIX",
    "verify_status_store",
    "StatusCapture",
    "capture_status",
    "read_status_capture",
    "write_status_capture",
]

STATUS_NORMALIZED_FILENAME = "status.normalized.json.gz"
STATUS_MANIFEST_VERSION = "1.0"

#: Where status captures live inside the retention store, beside ``market/`` (ADR-038).
STATUS_PREFIX = "status"


@dataclass
class StatusCapture:
    """One retained Sleeper capture: the rows plus the provenance that describes them."""

    source_id: str
    season: int
    snapshot_key: str
    observed_at_utc: datetime
    adapter_version: str
    source_policy_version: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    git_sha: str | None = None
    warning_codes: tuple[str, ...] = ()

    def manifest(self, *, content_digest: str) -> dict[str, Any]:
        return {
            "manifest_version": STATUS_MANIFEST_VERSION,
            "source_id": self.source_id,
            "season": self.season,
            "snapshot_key": self.snapshot_key,
            "observed_at_utc": isoformat_utc(self.observed_at_utc),
            "adapter_version": self.adapter_version,
            "source_policy_version": self.source_policy_version,
            "capture_tool": "ffdraft capture-status",
            "git_sha": self.git_sha,
            "normalized_path": STATUS_NORMALIZED_FILENAME,
            "normalized_content_hash": content_digest,
            "normalized_row_count": len(self.rows),
            "warning_codes": list(self.warning_codes),
            "notes": [
                "Sleeper publishes no per-record observation time; observed_at_utc is the "
                "retrieval time and is not a data-as-of claim.",
                "Normalized rows only: the raw player map is not retained (ADR-038).",
                "Annotation data. Never a model feature, historical or current (ADR-044).",
            ],
        }


def _rows_from_batch(batch: SourceBatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in batch.frame.iter_rows(named=True):
        record = dict(row)
        observed = record.get("observed_at_utc")
        if isinstance(observed, datetime):
            record["observed_at_utc"] = isoformat_utc(observed)
        rows.append(record)
    return rows


def capture_status(
    *,
    season: int,
    as_of: datetime | None = None,
    timeout_seconds: float = 60.0,
    git_sha: str | None = None,
    payload: Mapping[str, Mapping[str, Any]] | None = None,
    gate: QualityGate | None = None,
) -> StatusCapture:
    """Retrieve and normalize Sleeper's player map. **Network I/O unless ``payload`` given.**"""
    stamped = (as_of or utc_now()).replace(microsecond=0)
    checks = gate or QualityGate()
    adapter = SleeperPlayerAdapter()
    if payload is None:
        batch = adapter.fetch(
            as_of=stamped,
            config=SourceConfig(season=season, timeout_seconds=timeout_seconds),
        )
    else:
        batch = adapter.normalize(payload, retrieved_at=stamped)
    checks.extend(adapter.validate_raw(batch).checks)
    return StatusCapture(
        source_id=SLEEPER_SOURCE_ID,
        season=season,
        snapshot_key=snapshot_key(stamped),
        observed_at_utc=stamped,
        adapter_version=adapter.adapter_version,
        source_policy_version=adapter.license_policy_version,
        rows=_rows_from_batch(batch),
        git_sha=git_sha,
        warning_codes=batch.metadata.warning_codes,
    )


def write_status_capture(capture: StatusCapture, *, store: SnapshotStore) -> list[str]:
    """Append the capture to the store, honouring the same append-only rules as market."""
    status_store = SnapshotStore(root=store.root, prefix=STATUS_PREFIX)
    directory = status_store.snapshot_dir(
        capture.source_id,
        capture.season,
        capture.snapshot_key,
    )
    body = json.dumps(
        capture.rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload = gzip.compress(body, compresslevel=9, mtime=0)
    manifest = (
        json.dumps(
            capture.manifest(content_digest=content_hash(payload)),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")

    files = {STATUS_NORMALIZED_FILENAME: payload, MANIFEST_FILENAME: manifest}
    conflicts = [
        name
        for name, blob in files.items()
        if (directory / name).is_file() and (directory / name).read_bytes() != blob
    ]
    if conflicts:
        raise SnapshotConflictError(
            f"{directory} already holds different content for {sorted(conflicts)}; a "
            "retained capture is immutable (ADR-038).",
        )
    written: list[str] = []
    for name, blob in sorted(files.items()):
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        written.append(str(target))
    return written


def read_status_capture(
    store: SnapshotStore,
    *,
    season: int,
    source_id: str = SLEEPER_SOURCE_ID,
    key: str | None = None,
) -> StatusCapture | None:
    """Load the latest (or a named) retained capture, verifying its content hash."""
    status_store = SnapshotStore(root=store.root, prefix=STATUS_PREFIX)
    resolved = key or status_store.latest_key(source_id, season)
    if resolved is None:
        return None
    directory = status_store.snapshot_dir(source_id, season, resolved)
    manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    payload = (directory / manifest["normalized_path"]).read_bytes()
    digest = content_hash(payload)
    if digest != manifest["normalized_content_hash"]:
        raise SnapshotConflictError(
            f"{directory}: status capture hashes to {digest}, manifest says "
            f"{manifest['normalized_content_hash']}",
        )
    rows: Sequence[dict[str, Any]] = json.loads(gzip.decompress(payload).decode("utf-8"))
    return StatusCapture(
        source_id=str(manifest["source_id"]),
        season=int(manifest["season"]),
        snapshot_key=str(manifest["snapshot_key"]),
        observed_at_utc=parse_utc(str(manifest["observed_at_utc"])),
        adapter_version=str(manifest["adapter_version"]),
        source_policy_version=str(manifest["source_policy_version"]),
        rows=list(rows),
        git_sha=manifest.get("git_sha"),
        warning_codes=tuple(manifest.get("warning_codes", ())),
    )


def verify_status_store(
    store: SnapshotStore,
    *,
    season: int,
    source_id: str = SLEEPER_SOURCE_ID,
) -> tuple[int, int, tuple[str, ...]]:
    """Re-hash every retained status capture against its manifest.

    Returns ``(snapshots, files_checked, problems)``. The market store has its own
    verifier because its manifest carries per-cohort raw payloads; this one is the same
    discipline over a simpler shape, and it exists so that
    ``ffdraft validate-market-history`` cannot report "pass" for a prefix it never opened.
    """
    status_store = SnapshotStore(root=store.root, prefix=STATUS_PREFIX)
    keys = status_store.keys(source_id, season)
    problems: list[str] = []
    checked = 0
    previous: datetime | None = None

    for key in keys:
        directory = status_store.snapshot_dir(source_id, season, key)
        try:
            moment = parse_snapshot_key(key)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if previous is not None and moment <= previous:
            problems.append(f"{key}: capture keys must strictly increase")
        previous = moment

        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            problems.append(f"{key}: no {MANIFEST_FILENAME}")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{key}: unreadable manifest: {exc}")
            continue
        checked += 1

        if str(manifest.get("snapshot_key")) != key:
            problems.append(f"{key}: manifest claims snapshot_key {manifest.get('snapshot_key')!r}")
        if parse_utc(str(manifest.get("observed_at_utc"))) != moment:
            problems.append(f"{key}: observed_at_utc disagrees with the path")

        payload_path = directory / str(manifest.get("normalized_path", ""))
        if not payload_path.is_file():
            problems.append(
                f"{key}: manifest names a missing file {manifest.get('normalized_path')}"
            )
            continue
        checked += 1
        digest = content_hash(payload_path.read_bytes())
        declared = str(manifest.get("normalized_content_hash", ""))
        if declared and digest != declared:
            problems.append(
                f"{key}: {payload_path.name} hashes to {digest}, manifest says {declared}"
            )
    return len(keys), checked, tuple(problems)
