"""Append-only, content-addressed retention of point-in-time source captures (ADR-038).

Source-neutral by design: market snapshots and current-status captures share one mechanism,
and neither package has to import the other to retain a file.
"""

from __future__ import annotations

from ffdraft.retention.store import (
    MANIFEST_FILENAME,
    SNAPSHOT_KEY_PATTERN,
    SnapshotConflictError,
    SnapshotStore,
    WriteResult,
    canonical_json,
    content_hash,
    gzip_bytes,
    parse_snapshot_key,
    snapshot_key,
)

__all__ = [
    "MANIFEST_FILENAME",
    "SNAPSHOT_KEY_PATTERN",
    "SnapshotConflictError",
    "SnapshotStore",
    "WriteResult",
    "canonical_json",
    "content_hash",
    "gzip_bytes",
    "parse_snapshot_key",
    "snapshot_key",
]
