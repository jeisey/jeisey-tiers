"""The market snapshot manifest and the market view of the retention store (ADR-006/038).

**Boundary module.** Market data only. The append-only mechanics themselves are
source-neutral and live in :mod:`ffdraft.retention`, so a status capture can reuse them
without importing market code.

A snapshot is an immutable directory named for the instant it was retrieved::

    market/myfantasyleague/2026/2026-08-20T13-45-00Z/
        manifest.json
        players.raw.json.gz
        cohorts/<cohort_id>/adp.raw.json.gz
        market.normalized.json.gz

What this module adds to the generic store is **self-description**: a manifest carrying
enough provenance to reconstruct a capture's meaning without the code that wrote it - the
filters actually sent, the adapter version, the source policy version, the retrieval time,
MFL's response ``timestamp`` **as vendor metadata only**, row counts, content hashes and
identity-resolution counts - plus :func:`verify_store`, which re-hashes every retained file
against the manifest that claims to describe it.

MFL's response ``timestamp`` is response-generation time (`docs/DATA_SOURCES.md` 13.5). It
is retained under ``response_timestamp`` and is never promoted to ``source_as_of_utc``.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ffdraft.retention.store import (
    MANIFEST_FILENAME,
    SnapshotConflictError,
    SnapshotStore,
    WriteResult,
    canonical_json,
    content_hash,
    gzip_bytes,
    parse_snapshot_key,
    snapshot_key,
)
from ffdraft.timeutil import parse_utc

__all__ = [
    "MARKET_PREFIX",
    "NORMALIZED_FILENAME",
    "SNAPSHOT_MANIFEST_VERSION",
    "MarketSnapshot",
    "MarketSnapshotStore",
    "SnapshotConflictError",
    "SnapshotManifest",
    "content_hash",
    "parse_snapshot_key",
    "snapshot_key",
    "verify_store",
]

#: Bumped when the manifest's own shape changes. Independent of the artifact contracts:
#: this describes retained evidence, not a public artifact.
SNAPSHOT_MANIFEST_VERSION = "1.0"

NORMALIZED_FILENAME = "market.normalized.json.gz"
PLAYERS_RAW_FILENAME = "players.raw.json.gz"
ADP_RAW_FILENAME = "adp.raw.json.gz"

#: Where market captures live inside the store.
MARKET_PREFIX = "market"


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


@dataclass(frozen=True)
class MarketSnapshotStore(SnapshotStore):
    """The market view of the retention store: manifests in, manifests and rows out."""

    prefix: str = MARKET_PREFIX

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

    def write(
        self,
        *,
        manifest: SnapshotManifest,
        normalized_rows: Sequence[Mapping[str, Any]],
        raw_payloads: Mapping[str, bytes],
    ) -> WriteResult:
        """Append one snapshot.

        ``raw_payloads`` maps a snapshot-relative path to already-gzipped bytes. The
        manifest is stamped with the normalized payload's hash and row count here rather
        than by the caller, so a manifest can never describe bytes that were not written.
        """
        normalized = gzip_bytes(canonical_json(list(normalized_rows)))
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
        return self.write_files(
            source_id=manifest.source_id,
            season=manifest.season,
            key=manifest.snapshot_key,
            files=files,
        )


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
    store: MarketSnapshotStore,
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
