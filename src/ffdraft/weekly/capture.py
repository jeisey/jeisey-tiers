"""Retaining game-day inputs and shadow predictions, point in time (ADR-099).

The prospective holdout (``frozen_v2.PROSPECTIVE_HOLDOUT``) is only as good as what was kept
before each kickoff, and a current file cannot be rewound. Three captures go into the private
retained store (ADR-049) under ``gameday/``, with the same append-only, content-hashed
discipline as the market and status captures (ADR-038):

``weather_forecast``
    One row per upcoming game: the venue, the kickoff and the kickoff-hour forecast with its
    provider, update and retrieval times and status. Written by the capture job, which is the
    only job that calls a vendor; fetched once per venue per refresh.
``nflverse_injuries``
    The season's injury report as nflverse publishes it at the refresh, with per-week row
    digests (``injury_report_pit_v1``) so a completed week's later revision is visible.
``weekly_shadow``
    The build's paired v1/v2 predictions and every input v2 read, with the build time. Written
    after the build, by the job that retains it (``daily-refresh.yml``), never published.
``weekly_v2_look``
    One record per prospective look taken (``prospective.due_look``): the exact scored rows it
    judged and its verdict. Written by ``weekly-v2-prospective.yml`` before the verdict is
    reported; a look already recorded is never taken again.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ffdraft.retention import (
    MANIFEST_FILENAME,
    SnapshotConflictError,
    SnapshotStore,
    content_hash,
    parse_snapshot_key,
    snapshot_key,
)
from ffdraft.timeutil import isoformat_utc, parse_utc

__all__ = [
    "FORECAST_SOURCE_ID",
    "GAMEDAY_PREFIX",
    "INJURY_SOURCE_ID",
    "LOOK_SOURCE_ID",
    "SHADOW_SOURCE_ID",
    "GamedayCapture",
    "read_gameday_capture",
    "recorded_looks",
    "verify_gameday_store",
    "write_gameday_capture",
]

GAMEDAY_PREFIX = "gameday"
FORECAST_SOURCE_ID = "weather_forecast"
INJURY_SOURCE_ID = "nflverse_injuries"
SHADOW_SOURCE_ID = "weekly_shadow"
LOOK_SOURCE_ID = "weekly_v2_look"
GAMEDAY_SOURCES: tuple[str, ...] = (
    FORECAST_SOURCE_ID,
    INJURY_SOURCE_ID,
    SHADOW_SOURCE_ID,
    LOOK_SOURCE_ID,
)

PAYLOAD_FILENAME = "rows.json.gz"
GAMEDAY_MANIFEST_VERSION = "1.0"


@dataclass
class GamedayCapture:
    source_id: str
    season: int
    observed_at_utc: datetime
    rows: list[dict[str, Any]]
    details: dict[str, Any] = field(default_factory=dict)
    git_sha: str | None = None

    @property
    def snapshot_key(self) -> str:
        return snapshot_key(self.observed_at_utc)

    def manifest(self, *, content_digest: str) -> dict[str, Any]:
        return {
            "manifest_version": GAMEDAY_MANIFEST_VERSION,
            "source_id": self.source_id,
            "season": self.season,
            "snapshot_key": self.snapshot_key,
            "observed_at_utc": isoformat_utc(self.observed_at_utc),
            "capture_tool": f"ffdraft {self.source_id}",
            "git_sha": self.git_sha,
            "payload_path": PAYLOAD_FILENAME,
            "payload_content_hash": content_digest,
            "row_count": len(self.rows),
            "details": self.details,
        }


def _payload(rows: Sequence[Mapping[str, Any]]) -> bytes:
    body = json.dumps(
        list(rows),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return gzip.compress(body, compresslevel=9, mtime=0)


def write_gameday_capture(capture: GamedayCapture, *, store: SnapshotStore) -> list[str]:
    """Append ``capture`` to the store. A different payload under an existing key refuses."""
    gameday = SnapshotStore(root=store.root, prefix=GAMEDAY_PREFIX)
    directory = gameday.snapshot_dir(capture.source_id, capture.season, capture.snapshot_key)
    payload = _payload(capture.rows)
    manifest = (
        json.dumps(
            capture.manifest(content_digest=content_hash(payload)),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n"
    ).encode("utf-8")
    files = {PAYLOAD_FILENAME: payload, MANIFEST_FILENAME: manifest}
    conflicts = [
        name
        for name, blob in files.items()
        if (directory / name).is_file() and (directory / name).read_bytes() != blob
    ]
    if conflicts:
        raise SnapshotConflictError(
            f"{directory} already holds different content for {sorted(conflicts)}; a retained "
            "capture is immutable (ADR-038).",
        )
    written: list[str] = []
    for name, blob in sorted(files.items()):
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        written.append(str(target))
    return written


def read_gameday_capture(
    store: SnapshotStore,
    *,
    source_id: str,
    season: int,
    at_or_before: datetime | None = None,
    key: str | None = None,
) -> GamedayCapture | None:
    """The newest capture at or before ``at_or_before`` (or a named one), hash-verified."""
    gameday = SnapshotStore(root=store.root, prefix=GAMEDAY_PREFIX)
    keys = gameday.keys(source_id, season)
    if key is None:
        eligible = [
            candidate
            for candidate in keys
            if at_or_before is None or parse_snapshot_key(candidate) <= at_or_before
        ]
        if not eligible:
            return None
        key = eligible[-1]
    directory = gameday.snapshot_dir(source_id, season, key)
    manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    payload = (directory / str(manifest["payload_path"])).read_bytes()
    digest = content_hash(payload)
    if digest != manifest["payload_content_hash"]:
        raise SnapshotConflictError(
            f"{directory}: payload hashes to {digest}, manifest says "
            f"{manifest['payload_content_hash']}",
        )
    return GamedayCapture(
        source_id=str(manifest["source_id"]),
        season=int(manifest["season"]),
        observed_at_utc=parse_utc(str(manifest["observed_at_utc"])),
        rows=list(json.loads(gzip.decompress(payload).decode("utf-8"))),
        details=dict(manifest.get("details") or {}),
        git_sha=manifest.get("git_sha"),
    )


def verify_gameday_store(store: SnapshotStore, *, season: int) -> tuple[int, int, tuple[str, ...]]:
    """Re-hash every retained game-day capture: ``(captures, files checked, problems)``."""
    gameday = SnapshotStore(root=store.root, prefix=GAMEDAY_PREFIX)
    problems: list[str] = []
    captures = 0
    checked = 0
    for source_id in GAMEDAY_SOURCES:
        previous: datetime | None = None
        for key in gameday.keys(source_id, season):
            captures += 1
            try:
                moment = parse_snapshot_key(key)
            except ValueError as exc:
                problems.append(f"{source_id}/{key}: {exc}")
                continue
            if previous is not None and moment <= previous:
                problems.append(f"{source_id}/{key}: keys must strictly increase")
            previous = moment
            directory = gameday.snapshot_dir(source_id, season, key)
            manifest_path = directory / MANIFEST_FILENAME
            if not manifest_path.is_file():
                problems.append(f"{source_id}/{key}: no {MANIFEST_FILENAME}")
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            checked += 1
            if str(manifest.get("snapshot_key")) != key:
                problems.append(f"{source_id}/{key}: manifest names {manifest.get('snapshot_key')}")
            payload_path = directory / str(manifest.get("payload_path", ""))
            if not payload_path.is_file():
                problems.append(f"{source_id}/{key}: missing payload")
                continue
            checked += 1
            if content_hash(payload_path.read_bytes()) != manifest.get("payload_content_hash"):
                problems.append(f"{source_id}/{key}: payload does not match its manifest hash")
    return captures, checked, tuple(problems)


def recorded_looks(store: SnapshotStore, *, season: int) -> dict[str, dict[str, Any]]:
    """``look -> verdict`` for every prospective look already recorded, hash-verified.

    Two records of one look would mean the ledger was bypassed; that refuses rather than
    choosing one.
    """
    gameday = SnapshotStore(root=store.root, prefix=GAMEDAY_PREFIX)
    looks: dict[str, dict[str, Any]] = {}
    for key in gameday.keys(LOOK_SOURCE_ID, season):
        capture = read_gameday_capture(store, source_id=LOOK_SOURCE_ID, season=season, key=key)
        if capture is None:
            continue
        look = str(capture.details.get("look"))
        if look in looks:
            raise SnapshotConflictError(
                f"the {look} look of {season} is recorded twice; a look is taken at most once",
            )
        looks[look] = dict(capture.details.get("verdict") or {})
    return looks
