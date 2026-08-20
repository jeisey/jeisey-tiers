"""The append-only point-in-time market snapshot store (ADR-006, ADR-038).

**Boundary module.** Market data only.

A snapshot is an immutable directory named for the instant it was retrieved::

    market/myfantasyleague/2026/2026-08-20T13-45-00Z/
        manifest.json
        players.raw.json.gz
        cohorts/<cohort_id>/adp.raw.json.gz
        market.normalized.json.gz

Three rules make the store trustworthy rather than merely present:

*append-only* — a new timestamp appends; an existing path with **identical** content is an
idempotent no-op, so a retried workflow run is safe; an existing path with **different**
content fails closed and writes nothing. A later snapshot can never mutate an earlier one.

*content-addressed* — the manifest records a SHA-256 for every file it describes, and
:func:`verify_store` re-hashes them. Truncation, corruption and hand-editing are detected
rather than assumed away.

*self-describing* — a manifest carries enough provenance to reconstruct the capture's
meaning without the code that wrote it: the filters actually sent, the adapter version, the
source policy version, the retrieval time, MFL's response ``timestamp`` **as vendor
metadata only**, row counts and identity-resolution counts.

MFL's response ``timestamp`` is response-generation time (`docs/DATA_SOURCES.md` 13.5). It
is retained under ``response_timestamp`` and is never promoted to ``source_as_of_utc``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ffdraft.timeutil import ensure_utc, isoformat_utc, parse_utc

__all__ = [
    "MANIFEST_FILENAME",
    "MARKET_PREFIX",
    "NORMALIZED_FILENAME",
    "SNAPSHOT_MANIFEST_VERSION",
    "STATUS_PREFIX",
    "MarketSnapshot",
    "SnapshotConflictError",
    "SnapshotManifest",
    "SnapshotStore",
    "content_hash",
    "parse_snapshot_key",
    "snapshot_key",
    "verify_store",
]

#: Bumped when the manifest's own shape changes. Independent of the artifact contracts:
#: this describes retained evidence, not a public artifact.
SNAPSHOT_MANIFEST_VERSION = "1.0"

MANIFEST_FILENAME = "manifest.json"
NORMALIZED_FILENAME = "market.normalized.json.gz"
PLAYERS_RAW_FILENAME = "players.raw.json.gz"
ADP_RAW_FILENAME = "adp.raw.json.gz"

MARKET_PREFIX = "market"
STATUS_PREFIX = "status"

_KEY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


class SnapshotConflictError(RuntimeError):
    """Raised when a write would change bytes that a retained snapshot already holds."""


def snapshot_key(moment: datetime) -> str:
    """The directory name for a retrieval instant: ``YYYY-MM-DDTHH-MM-SSZ``.

    Colons are illegal on some filesystems and awkward in URLs, so the RFC 3339 form is
    rendered with hyphens. The mapping is total and reversible.
    """
    return isoformat_utc(ensure_utc(moment)).replace(":", "-")


def parse_snapshot_key(key: str) -> datetime:
    """Invert :func:`snapshot_key`."""
    if not _KEY_PATTERN.match(key):
        raise ValueError(f"{key!r} is not a snapshot key (YYYY-MM-DDTHH-MM-SSZ)")
    date_part, time_part = key.split("T", 1)
    return parse_utc(f"{date_part}T{time_part[:-1].replace('-', ':')}Z")


def content_hash(payload: bytes) -> str:
    """SHA-256 of raw bytes, hex encoded. The store's only integrity primitive."""
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(payload: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, fixed separators, no trailing whitespace.

    Determinism is what lets an idempotent re-capture of unchanged data hash identically
    instead of conflicting on key order.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8",
    )


def _gzip_bytes(payload: bytes) -> bytes:
    """Gzip with ``mtime=0`` so identical content produces identical bytes."""
    return gzip.compress(payload, compresslevel=9, mtime=0)


# --------------------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortCapture:
    """One cohort's slice of a snapshot."""

    cohort_id: str
    filters: Mapping[str, str]
    label: str
    raw_path: str
    raw_content_hash: str
    row_count: int
    #: MFL's envelope fields. ``response_timestamp`` is generation time, not data-as-of.
    response_timestamp: str | None = None
    total_drafts: int | None = None
    total_picks: int | None = None
    resolved_players: int = 0
    resolvable_players: int = 0
    ambiguous_players: int = 0
    non_player_entities: int = 0
    exact_cohort: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "filters": dict(self.filters),
            "label": self.label,
            "raw_path": self.raw_path,
            "raw_content_hash": self.raw_content_hash,
            "row_count": self.row_count,
            "response_timestamp": self.response_timestamp,
            "total_drafts": self.total_drafts,
            "total_picks": self.total_picks,
            "resolved_players": self.resolved_players,
            "resolvable_players": self.resolvable_players,
            "ambiguous_players": self.ambiguous_players,
            "non_player_entities": self.non_player_entities,
            "exact_cohort": self.exact_cohort,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CohortCapture:
        return cls(
            cohort_id=str(payload["cohort_id"]),
            filters={str(k): str(v) for k, v in dict(payload.get("filters", {})).items()},
            label=str(payload.get("label", "")),
            raw_path=str(payload["raw_path"]),
            raw_content_hash=str(payload["raw_content_hash"]),
            row_count=int(payload["row_count"]),
            response_timestamp=_optional_str(payload.get("response_timestamp")),
            total_drafts=_optional_int(payload.get("total_drafts")),
            total_picks=_optional_int(payload.get("total_picks")),
            resolved_players=int(payload.get("resolved_players", 0)),
            resolvable_players=int(payload.get("resolvable_players", 0)),
            ambiguous_players=int(payload.get("ambiguous_players", 0)),
            non_player_entities=int(payload.get("non_player_entities", 0)),
            exact_cohort=bool(payload.get("exact_cohort", False)),
        )


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Everything needed to read a retained snapshot without the code that wrote it."""

    manifest_version: str
    source_id: str
    season: int
    snapshot_key: str
    retrieved_at_utc: str
    adapter_version: str
    source_policy_version: str
    #: Never a data-as-of claim. MFL publishes none (ADR-038).
    source_as_of_utc: None = None
    normalized_path: str = NORMALIZED_FILENAME
    normalized_content_hash: str = ""
    normalized_row_count: int = 0
    player_directory_path: str | None = None
    player_directory_content_hash: str | None = None
    player_directory_row_count: int | None = None
    cohorts: tuple[CohortCapture, ...] = ()
    git_sha: str | None = None
    capture_tool: str = "ffdraft snapshot-market"
    notes: tuple[str, ...] = ()

    @property
    def retrieved_at(self) -> datetime:
        return parse_utc(self.retrieved_at_utc)

    def cohort(self, cohort_id: str) -> CohortCapture | None:
        return next((item for item in self.cohorts if item.cohort_id == cohort_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "source_id": self.source_id,
            "season": self.season,
            "snapshot_key": self.snapshot_key,
            "retrieved_at_utc": self.retrieved_at_utc,
            "source_as_of_utc": None,
            "adapter_version": self.adapter_version,
            "source_policy_version": self.source_policy_version,
            "capture_tool": self.capture_tool,
            "git_sha": self.git_sha,
            "player_directory_path": self.player_directory_path,
            "player_directory_content_hash": self.player_directory_content_hash,
            "player_directory_row_count": self.player_directory_row_count,
            "normalized_path": self.normalized_path,
            "normalized_content_hash": self.normalized_content_hash,
            "normalized_row_count": self.normalized_row_count,
            "cohorts": [cohort.to_dict() for cohort in self.cohorts],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SnapshotManifest:
        return cls(
            manifest_version=str(payload["manifest_version"]),
            source_id=str(payload["source_id"]),
            season=int(payload["season"]),
            snapshot_key=str(payload["snapshot_key"]),
            retrieved_at_utc=str(payload["retrieved_at_utc"]),
            adapter_version=str(payload["adapter_version"]),
            source_policy_version=str(payload["source_policy_version"]),
            normalized_path=str(payload.get("normalized_path", NORMALIZED_FILENAME)),
            normalized_content_hash=str(payload.get("normalized_content_hash", "")),
            normalized_row_count=int(payload.get("normalized_row_count", 0)),
            player_directory_path=_optional_str(payload.get("player_directory_path")),
            player_directory_content_hash=_optional_str(
                payload.get("player_directory_content_hash"),
            ),
            player_directory_row_count=_optional_int(payload.get("player_directory_row_count")),
            cohorts=tuple(CohortCapture.from_dict(item) for item in payload.get("cohorts", ())),
            git_sha=_optional_str(payload.get("git_sha")),
            capture_tool=str(payload.get("capture_tool", "ffdraft snapshot-market")),
            notes=tuple(str(note) for note in payload.get("notes", ())),
        )


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """A manifest plus the normalized rows it describes, loaded from the store."""

    manifest: SnapshotManifest
    rows: tuple[Mapping[str, Any], ...]

    @property
    def retrieved_at(self) -> datetime:
        return self.manifest.retrieved_at

    def rows_for(self, cohort_id: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(row for row in self.rows if str(row.get("cohort_id")) == cohort_id)


# --------------------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------------------


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
    prefix: str = MARKET_PREFIX

    def season_dir(self, source_id: str, season: int) -> Path:
        return self.root / self.prefix / source_id / str(season)

    def snapshot_dir(self, source_id: str, season: int, key: str) -> Path:
        return self.season_dir(source_id, season) / key

    def keys(self, source_id: str, season: int) -> list[str]:
        """Retained snapshot keys for a source and season, oldest first.

        Sorted lexically, which for this key format is chronological order - that is the
        point of a zero-padded RFC 3339 name.
        """
        directory = self.season_dir(source_id, season)
        if not directory.is_dir():
            return []
        return sorted(
            entry.name
            for entry in directory.iterdir()
            if entry.is_dir() and _KEY_PATTERN.match(entry.name)
        )

    def latest_key(self, source_id: str, season: int) -> str | None:
        keys = self.keys(source_id, season)
        return keys[-1] if keys else None

    def read_manifest(self, source_id: str, season: int, key: str) -> SnapshotManifest:
        path = self.snapshot_dir(source_id, season, key) / MANIFEST_FILENAME
        return SnapshotManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def read(self, source_id: str, season: int, key: str) -> MarketSnapshot:
        """Load one retained snapshot, verifying the normalized payload's hash."""
        directory = self.snapshot_dir(source_id, season, key)
        manifest = self.read_manifest(source_id, season, key)
        payload = (directory / manifest.normalized_path).read_bytes()
        digest = content_hash(payload)
        if manifest.normalized_content_hash and digest != manifest.normalized_content_hash:
            raise SnapshotConflictError(
                f"{directory / manifest.normalized_path}: content hash {digest} does not "
                f"match the manifest's {manifest.normalized_content_hash}",
            )
        rows = json.loads(gzip.decompress(payload).decode("utf-8"))
        return MarketSnapshot(manifest=manifest, rows=tuple(rows))

    def read_latest(self, source_id: str, season: int) -> MarketSnapshot | None:
        key = self.latest_key(source_id, season)
        return None if key is None else self.read(source_id, season, key)

    def read_window(
        self,
        source_id: str,
        season: int,
        *,
        keys: Sequence[str] | None = None,
    ) -> list[MarketSnapshot]:
        """Load several snapshots, oldest first. Used by the trend computation."""
        wanted = list(keys) if keys is not None else self.keys(source_id, season)
        return [self.read(source_id, season, key) for key in wanted]

    # -- writing -----------------------------------------------------------------------

    def write(
        self,
        *,
        manifest: SnapshotManifest,
        normalized_rows: Sequence[Mapping[str, Any]],
        raw_payloads: Mapping[str, bytes],
    ) -> WriteResult:
        """Append one snapshot.

        ``raw_payloads`` maps a snapshot-relative path to already-gzipped bytes. Nothing is
        written until every file has been checked against what is already retained, so a
        conflict leaves the store exactly as it was.
        """
        directory = self.snapshot_dir(manifest.source_id, manifest.season, manifest.snapshot_key)
        normalized = _gzip_bytes(_canonical_json(list(normalized_rows)))
        stamped = SnapshotManifest(
            **{
                **{
                    key: value
                    for key, value in _as_fields(manifest).items()
                    if key not in {"normalized_content_hash", "normalized_row_count"}
                },
                "normalized_content_hash": content_hash(normalized),
                "normalized_row_count": len(normalized_rows),
            },
        )
        files: dict[str, bytes] = {
            manifest.normalized_path: normalized,
            **dict(raw_payloads),
        }
        files[MANIFEST_FILENAME] = (
            json.dumps(stamped.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")

        conflicts = []
        unchanged = 0
        for relative, payload in sorted(files.items()):
            existing = directory / relative
            if not existing.is_file():
                continue
            if existing.read_bytes() == payload:
                unchanged += 1
                continue
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


def _as_fields(manifest: SnapshotManifest) -> dict[str, Any]:
    return {
        "manifest_version": manifest.manifest_version,
        "source_id": manifest.source_id,
        "season": manifest.season,
        "snapshot_key": manifest.snapshot_key,
        "retrieved_at_utc": manifest.retrieved_at_utc,
        "adapter_version": manifest.adapter_version,
        "source_policy_version": manifest.source_policy_version,
        "normalized_path": manifest.normalized_path,
        "normalized_content_hash": manifest.normalized_content_hash,
        "normalized_row_count": manifest.normalized_row_count,
        "player_directory_path": manifest.player_directory_path,
        "player_directory_content_hash": manifest.player_directory_content_hash,
        "player_directory_row_count": manifest.player_directory_row_count,
        "cohorts": manifest.cohorts,
        "git_sha": manifest.git_sha,
        "capture_tool": manifest.capture_tool,
        "notes": manifest.notes,
    }


# --------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoreVerification:
    """What :func:`verify_store` found."""

    snapshots: int = 0
    files_checked: int = 0
    problems: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.problems


def verify_store(
    store: SnapshotStore,
    *,
    source_id: str,
    season: int,
) -> StoreVerification:
    """Re-hash every retained file against its manifest and check key ordering.

    This is what makes "immutable" a checkable claim rather than a promise. It catches
    truncation, a hand-edited normalized payload, a manifest that names a missing file, and
    a directory whose name is not a valid snapshot key.
    """
    problems: list[str] = []
    checked = 0
    keys = store.keys(source_id, season)
    previous: datetime | None = None

    for key in keys:
        directory = store.snapshot_dir(source_id, season, key)
        try:
            moment = parse_snapshot_key(key)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if previous is not None and moment <= previous:
            problems.append(f"{key}: snapshot keys must strictly increase")
        previous = moment

        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            problems.append(f"{key}: no {MANIFEST_FILENAME}")
            continue
        try:
            manifest = SnapshotManifest.from_dict(
                json.loads(manifest_path.read_text(encoding="utf-8")),
            )
        except (ValueError, KeyError) as exc:
            problems.append(f"{key}: unreadable manifest: {exc}")
            continue
        checked += 1

        if manifest.snapshot_key != key:
            problems.append(
                f"{key}: manifest claims snapshot_key {manifest.snapshot_key!r}",
            )
        if manifest.retrieved_at != moment:
            problems.append(
                f"{key}: retrieved_at_utc {manifest.retrieved_at_utc} disagrees with the path",
            )
        if manifest.source_as_of_utc is not None:  # pragma: no cover - typed as None
            problems.append(f"{key}: source_as_of_utc must stay null for MFL (ADR-038)")

        expected: list[tuple[str, str]] = [
            (manifest.normalized_path, manifest.normalized_content_hash),
        ]
        if manifest.player_directory_path and manifest.player_directory_content_hash:
            expected.append(
                (manifest.player_directory_path, manifest.player_directory_content_hash),
            )
        expected.extend((cohort.raw_path, cohort.raw_content_hash) for cohort in manifest.cohorts)
        for relative, digest in expected:
            target = directory / relative
            if not target.is_file():
                problems.append(f"{key}: manifest names a missing file {relative}")
                continue
            checked += 1
            actual = content_hash(target.read_bytes())
            if digest and actual != digest:
                problems.append(
                    f"{key}: {relative} hashes to {actual}, manifest says {digest}",
                )
    return StoreVerification(
        snapshots=len(keys),
        files_checked=checked,
        problems=tuple(problems),
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
