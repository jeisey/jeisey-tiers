"""The append-only, content-addressed capture store (ADR-038).

**Deliberately not a market module.** The retention mechanism is a filesystem discipline:
immutable timestamp-keyed directories, hashed content, fail-closed rewrites. Market
snapshots use it and so do Sleeper status captures, and if it lived under
``ffdraft.market`` the status path would have to import market code to retain a file. That
would be a false edge in the import graph the intrinsic/market firewall is checked on
(`tests/contract/test_architecture_boundary.py`), and a false edge in a boundary test is
worse than no test: it teaches people the boundary is noisy.

Three rules, and they are the whole module:

*append-only* — a new timestamp appends; an existing path with identical content is an
idempotent no-op, so a retried workflow run is safe; an existing path with different
content raises and writes nothing.

*content-addressed* — every retained file has a SHA-256 the caller records in its manifest,
so truncation and hand-editing are detectable rather than assumed away.

*deterministic bytes* — canonical JSON and ``mtime=0`` gzip, so unchanged data re-captured
hashes identically instead of conflicting on key order or a timestamp in a gzip header.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ffdraft.timeutil import ensure_utc, isoformat_utc, parse_utc

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

MANIFEST_FILENAME = "manifest.json"

#: ``YYYY-MM-DDTHH-MM-SSZ``. Zero-padded, so lexical order is chronological order.
SNAPSHOT_KEY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


class SnapshotConflictError(RuntimeError):
    """Raised when a write would change bytes a retained snapshot already holds."""


def snapshot_key(moment: datetime) -> str:
    """The directory name for a retrieval instant.

    Colons are illegal on some filesystems and awkward in URLs, so the RFC 3339 form is
    rendered with hyphens. The mapping is total and reversible.
    """
    return isoformat_utc(ensure_utc(moment)).replace(":", "-")


def parse_snapshot_key(key: str) -> datetime:
    """Invert :func:`snapshot_key`."""
    if not SNAPSHOT_KEY_PATTERN.match(key):
        raise ValueError(f"{key!r} is not a snapshot key (YYYY-MM-DDTHH-MM-SSZ)")
    date_part, time_part = key.split("T", 1)
    return parse_utc(f"{date_part}T{time_part[:-1].replace('-', ':')}Z")


def content_hash(payload: bytes) -> str:
    """SHA-256 of raw bytes, hex encoded. The store's only integrity primitive."""
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, fixed separators, no trailing whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8",
    )


def gzip_bytes(payload: bytes) -> bytes:
    """Gzip with ``mtime=0`` so identical content produces identical bytes."""
    return gzip.compress(payload, compresslevel=9, mtime=0)


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What a write did, and to which paths."""

    directory: Path
    written: tuple[Path, ...]
    #: True when every file already existed with identical content (ADR-038 idempotency).
    idempotent: bool


@dataclass(frozen=True)
class SnapshotStore:
    """A checkout of the ``market-data`` branch, or any directory shaped like one."""

    root: Path
    prefix: str

    def season_dir(self, source_id: str, season: int) -> Path:
        return self.root / self.prefix / source_id / str(season)

    def snapshot_dir(self, source_id: str, season: int, key: str) -> Path:
        return self.season_dir(source_id, season) / key

    def keys(self, source_id: str, season: int) -> list[str]:
        """Retained snapshot keys for a source and season, oldest first."""
        directory = self.season_dir(source_id, season)
        if not directory.is_dir():
            return []
        return sorted(
            entry.name
            for entry in directory.iterdir()
            if entry.is_dir() and SNAPSHOT_KEY_PATTERN.match(entry.name)
        )

    def latest_key(self, source_id: str, season: int) -> str | None:
        keys = self.keys(source_id, season)
        return keys[-1] if keys else None

    def write_files(
        self,
        *,
        source_id: str,
        season: int,
        key: str,
        files: Mapping[str, bytes],
    ) -> WriteResult:
        """Append one snapshot's files.

        Every path is checked against what is already retained **before** anything is
        written, so a conflict leaves the store exactly as it was rather than half updated.
        """
        directory = self.snapshot_dir(source_id, season, key)
        conflicts: list[str] = []
        unchanged = 0
        for relative, payload in sorted(files.items()):
            existing = directory / relative
            if not existing.is_file():
                continue
            if existing.read_bytes() == payload:
                unchanged += 1
            else:
                conflicts.append(relative)
        if conflicts:
            raise SnapshotConflictError(
                f"{directory} already holds different content for {sorted(conflicts)}; a "
                "retained snapshot is immutable (ADR-038). Take a new snapshot instead.",
            )
        if unchanged == len(files):
            return WriteResult(
                directory=directory,
                written=tuple(sorted(directory / name for name in files)),
                idempotent=True,
            )
        written: list[Path] = []
        for relative, payload in sorted(files.items()):
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            written.append(target)
        return WriteResult(directory=directory, written=tuple(written), idempotent=False)
