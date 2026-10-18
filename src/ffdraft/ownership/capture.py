"""Retaining ESPN's public roster and start percentages (ADR-112).

**Boundary module. Crowd interest only — never a price, never a rank, never a model feature.**

One capture is one retrieval of ESPN's whole QB/RB/WR/TE ownership universe, appended to the
same immutable, content-addressed store the market, status and behaviour captures use, under
its own ``ownership/`` prefix. The manifest records what was *requested* (the URL, the view,
the filter, that no scoring period was sent), what was *measured* (rows, ESPN's own universe
count, bytes, duration, attempts), what ESPN *reported* (its current scoring period, each
row's own update stamp) and when *we* retrieved it — four different facts kept apart.

**Validated before it is written.** :func:`capture_problems` runs on the normalized rows and a
capture with any problem is refused, so an incomplete, truncated or corrupt retrieval can
never replace a good snapshot: the previous one simply stays the newest.

**Once a day.** :func:`same_day_capture` finds a valid capture already retained for today's
America/New_York date, and the CLI then reuses it without calling ESPN. A reused capture keeps
its original key and retrieval time, so its age is never refreshed by being read again.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ffdraft.contracts import SourceBatch
from ffdraft.quality import QualityGate
from ffdraft.retention import (
    MANIFEST_FILENAME,
    UNREADABLE_SNAPSHOT_ERRORS,
    SnapshotConflictError,
    SnapshotStore,
    WriteResult,
    canonical_json,
    content_hash,
    gzip_bytes,
    parse_snapshot_key,
    snapshot_key,
)
from ffdraft.sources.espn import (
    ESPN_SOURCE_ID,
    EspnFetch,
    EspnOwnershipAdapter,
    fetch_espn_current_period,
    fetch_espn_ownership,
)
from ffdraft.timeutil import isoformat_utc, parse_utc, utc_now

__all__ = [
    "OWNERSHIP_MANIFEST_VERSION",
    "OWNERSHIP_NORMALIZED_FILENAME",
    "OWNERSHIP_PREFIX",
    "OwnershipCapture",
    "capture_espn_ownership",
    "capture_problems",
    "read_ownership_capture",
    "same_day_capture",
    "verify_ownership_store",
    "write_ownership_capture",
]

OWNERSHIP_NORMALIZED_FILENAME = "ownership.normalized.json.gz"
OWNERSHIP_MANIFEST_VERSION = "1.0"
#: Beside ``market/``, ``status/`` and ``behavior/``: a separate kind of evidence.
OWNERSHIP_PREFIX = "ownership"
#: The capture day is the refresh's own calendar (the schedule is America/New_York).
CAPTURE_DAY_ZONE = ZoneInfo("America/New_York")
#: A healthy capture carries roughly 960 core players; fewer than this is refused.
MIN_CORE_ROWS = 500


@dataclass
class OwnershipCapture:
    """One retained ESPN ownership snapshot and the request that produced it."""

    source_id: str
    season: int
    snapshot_key: str
    observed_at_utc: datetime
    adapter_version: str
    source_policy_version: str
    #: ``currentScoringPeriod.id`` from ESPN's season endpoint at retrieval, or ``None``.
    espn_current_period: int | None
    request: Mapping[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    git_sha: str | None = None
    warning_codes: tuple[str, ...] = ()

    def readings(self) -> dict[str, dict[str, Any]]:
        """ESPN id -> normalized row."""
        return {str(row["external_player_id"]): row for row in self.rows}

    def coverage(self) -> dict[str, int]:
        rostered = sum(1 for row in self.rows if row.get("percent_rostered") is not None)
        started = sum(1 for row in self.rows if row.get("percent_started") is not None)
        return {
            "core_rows": len(self.rows),
            "rows_with_percent_rostered": rostered,
            "rows_with_percent_started": started,
        }

    def source_updated_range(self) -> tuple[str | None, str | None]:
        stamps = sorted(
            str(row["source_updated_at_utc"])
            for row in self.rows
            if row.get("source_updated_at_utc")
        )
        return (stamps[0], stamps[-1]) if stamps else (None, None)

    def manifest(self, *, content_digest: str) -> dict[str, Any]:
        earliest, latest = self.source_updated_range()
        return {
            "manifest_version": OWNERSHIP_MANIFEST_VERSION,
            "source_id": self.source_id,
            "season": self.season,
            "snapshot_key": self.snapshot_key,
            "observed_at_utc": isoformat_utc(self.observed_at_utc),
            "adapter_version": self.adapter_version,
            "source_policy_version": self.source_policy_version,
            "capture_tool": "ffdraft capture-espn-ownership",
            "git_sha": self.git_sha,
            "espn_current_period": self.espn_current_period,
            "request": dict(self.request),
            "coverage": self.coverage(),
            "source_updated_at_min_utc": earliest,
            "source_updated_at_max_utc": latest,
            "normalized_path": OWNERSHIP_NORMALIZED_FILENAME,
            "normalized_content_hash": content_digest,
            "normalized_row_count": len(self.rows),
            "warning_codes": list(self.warning_codes),
            "notes": [
                "observed_at_utc is our retrieval instant; source_updated_at_utc on each row is "
                "ESPN's own ownership.date stamp. The two are different facts.",
                "No scoring period was requested: the 2026-10-17 probe found ownership "
                "identical for every scoringPeriodId. espn_current_period is the period ESPN's "
                "season endpoint reported as current at retrieval, not a statement of which "
                "week's lineups percent_started counts.",
                "espn_percent_change is ESPN's ownership.percentChange. Its window is not "
                "stated; it is retained here and published nowhere.",
                "Crowd interest, never a price and never a model feature. ADP, auction "
                "values, ranks, projections and stats were discarded by the adapter.",
            ],
        }


def _rows_from_batch(batch: SourceBatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in batch.frame.iter_rows(named=True):
        record = dict(row)
        for name in ("snapshot_at_utc", "source_updated_at_utc"):
            value = record.get(name)
            if isinstance(value, datetime):
                record[name] = isoformat_utc(value)
        rows.append(record)
    return rows


def capture_espn_ownership(
    *,
    season: int,
    as_of: datetime | None = None,
    timeout_seconds: float = 30.0,
    git_sha: str | None = None,
    fetched: EspnFetch | None = None,
    current_period: int | None = None,
    gate: QualityGate | None = None,
) -> OwnershipCapture:
    """Retrieve and normalize the universe. **Network I/O unless ``fetched`` is given.**

    Two requests at most: the ownership universe, and ESPN's 201-byte season object for the
    current scoring period. ``fetched``/``current_period`` drive this offline in tests.
    """
    stamped = (as_of or utc_now()).replace(microsecond=0)
    checks = gate or QualityGate()
    adapter = EspnOwnershipAdapter()
    if fetched is None:
        fetched = fetch_espn_ownership(season, timeout=timeout_seconds)
        current_period = fetch_espn_current_period(season)
    batch = adapter.normalize(fetched.players, retrieved_at=stamped)
    checks.extend(adapter.validate_raw(batch).checks)
    return OwnershipCapture(
        source_id=ESPN_SOURCE_ID,
        season=season,
        snapshot_key=snapshot_key(stamped),
        observed_at_utc=stamped,
        adapter_version=adapter.adapter_version,
        source_policy_version=adapter.license_policy_version,
        espn_current_period=current_period,
        request=fetched.request_record(),
        rows=_rows_from_batch(batch),
        git_sha=git_sha,
        warning_codes=tuple(batch.metadata.warning_codes),
    )


def capture_problems(capture: OwnershipCapture) -> list[str]:
    """Why a capture must not be retained. Empty when it may be.

    The adapter already dropped malformed ids and nulled invalid percentages; this is the
    capture-level gate: the request must have been complete, the universe must be the size a
    healthy one is, ids must be unique, and every published percentage must be in [0, 100].
    """
    problems: list[str] = []
    request = capture.request
    rows_returned = request.get("rows_returned")
    universe = request.get("universe_count_header")
    if universe is None or rows_returned is None or int(universe) != int(rows_returned):
        problems.append(
            f"request incomplete: {rows_returned} rows returned against ESPN count {universe}",
        )
    if len(capture.rows) < MIN_CORE_ROWS:
        problems.append(f"{len(capture.rows)} core rows, fewer than {MIN_CORE_ROWS}")
    ids = [str(row.get("external_player_id")) for row in capture.rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate ESPN ids in one capture")
    for row in capture.rows:
        for name in ("percent_rostered", "percent_started"):
            value = row.get(name)
            if value is not None and not (0.0 <= float(value) <= 100.0):
                problems.append(f"{row.get('external_player_id')}: {name}={value} out of range")
    if not any(row.get("percent_rostered") is not None for row in capture.rows):
        problems.append("no row carries a roster percentage")
    if capture.observed_at_utc > utc_now().replace(microsecond=0) + _CLOCK_SLACK:
        problems.append("retrieval instant is in the future")
    return problems


_CLOCK_SLACK = timedelta(minutes=10)


def _encode(capture: OwnershipCapture) -> dict[str, bytes]:
    payload = gzip_bytes(
        canonical_json(sorted(capture.rows, key=lambda r: str(r["external_player_id"])))
    )
    manifest = (
        json.dumps(
            capture.manifest(content_digest=content_hash(payload)),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return {OWNERSHIP_NORMALIZED_FILENAME: payload, MANIFEST_FILENAME: manifest}


def write_ownership_capture(capture: OwnershipCapture, *, store: SnapshotStore) -> WriteResult:
    """Validate, then append under the store's append-only rules (ADR-038)."""
    problems = capture_problems(capture)
    if problems:
        raise ValueError(
            "refusing to retain an ESPN ownership capture: " + "; ".join(problems[:5]),
        )
    ownership_store = SnapshotStore(root=store.root, prefix=OWNERSHIP_PREFIX)
    return ownership_store.write_files(
        source_id=capture.source_id,
        season=capture.season,
        key=capture.snapshot_key,
        files=_encode(capture),
    )


def read_ownership_capture(
    store: SnapshotStore,
    *,
    season: int,
    source_id: str = ESPN_SOURCE_ID,
    key: str | None = None,
) -> OwnershipCapture | None:
    """Load the latest (or a named) retained capture, verifying its content hash."""
    ownership_store = SnapshotStore(root=store.root, prefix=OWNERSHIP_PREFIX)
    resolved = key or ownership_store.latest_key(source_id, season)
    if resolved is None:
        return None
    directory = ownership_store.snapshot_dir(source_id, season, resolved)
    manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    payload = (directory / manifest["normalized_path"]).read_bytes()
    digest = content_hash(payload)
    if digest != manifest["normalized_content_hash"]:
        raise SnapshotConflictError(
            f"{directory}: ownership capture hashes to {digest}, manifest says "
            f"{manifest['normalized_content_hash']}",
        )
    rows: Sequence[dict[str, Any]] = json.loads(gzip.decompress(payload).decode("utf-8"))
    period = manifest.get("espn_current_period")
    return OwnershipCapture(
        source_id=str(manifest["source_id"]),
        season=int(manifest["season"]),
        snapshot_key=str(manifest["snapshot_key"]),
        observed_at_utc=parse_utc(str(manifest["observed_at_utc"])),
        adapter_version=str(manifest["adapter_version"]),
        source_policy_version=str(manifest["source_policy_version"]),
        espn_current_period=int(period) if isinstance(period, int) else None,
        request=dict(manifest.get("request") or {}),
        rows=list(rows),
        git_sha=manifest.get("git_sha"),
        warning_codes=tuple(manifest.get("warning_codes", ())),
    )


def same_day_capture(
    store: SnapshotStore,
    *,
    season: int,
    now: datetime,
    source_id: str = ESPN_SOURCE_ID,
) -> OwnershipCapture | None:
    """A valid capture already retained for ``now``'s America/New_York date, or ``None``.

    Only a capture that reads back and still passes :func:`capture_problems` counts, so a
    damaged snapshot never suppresses today's retrieval.
    """
    ownership_store = SnapshotStore(root=store.root, prefix=OWNERSHIP_PREFIX)
    today = now.astimezone(CAPTURE_DAY_ZONE).date()
    for key in reversed(ownership_store.keys(source_id, season)):
        try:
            moment = parse_snapshot_key(key)
        except ValueError:
            continue
        if moment.astimezone(CAPTURE_DAY_ZONE).date() != today or moment > now:
            continue
        try:
            capture = read_ownership_capture(store, season=season, source_id=source_id, key=key)
        except UNREADABLE_SNAPSHOT_ERRORS:
            continue
        if capture is not None and not _stored_problems(capture):
            return capture
    return None


def _stored_problems(capture: OwnershipCapture) -> list[str]:
    """:func:`capture_problems` minus the clock check, which a retained capture passed."""
    return [problem for problem in capture_problems(capture) if "future" not in problem]


def verify_ownership_store(
    store: SnapshotStore,
    *,
    season: int,
    source_id: str = ESPN_SOURCE_ID,
) -> tuple[int, int, tuple[str, ...]]:
    """Re-hash every retained ownership capture against its manifest.

    Returns ``(snapshots, files_checked, problems)``, the shape the other prefixes report.
    """
    ownership_store = SnapshotStore(root=store.root, prefix=OWNERSHIP_PREFIX)
    keys = ownership_store.keys(source_id, season)
    problems: list[str] = []
    checked = 0
    for key in keys:
        directory = ownership_store.snapshot_dir(source_id, season, key)
        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            problems.append(f"ownership {key}: no manifest")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = (directory / manifest["normalized_path"]).read_bytes()
            rows = json.loads(gzip.decompress(payload).decode("utf-8"))
        except (OSError, ValueError, KeyError, EOFError) as exc:
            problems.append(f"ownership {key}: {exc}")
            continue
        checked += 1
        digest = content_hash(payload)
        if digest != manifest.get("normalized_content_hash"):
            problems.append(
                f"ownership {key}: content hash {digest} != manifest "
                f"{manifest.get('normalized_content_hash')}",
            )
        if manifest.get("snapshot_key") != key:
            problems.append(f"ownership {key}: manifest names {manifest.get('snapshot_key')}")
        if len(rows) != manifest.get("normalized_row_count"):
            problems.append(f"ownership {key}: row count disagrees with its manifest")
    return len(keys), checked, tuple(problems)
