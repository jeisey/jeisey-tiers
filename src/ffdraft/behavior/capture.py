"""Retaining Sleeper's trending add/drop feed (roadmap 10.1.4, 12.3, 12.5).

Phase 10 built the adapter and deliberately consumed nothing, so that a real series would
exist by the time Phase 12 needed one. This module is the retention half: it captures both
behaviour feeds, appends them to the same immutable store the market and status captures use,
and reads the latest one back offline.

**What a retained row means, exactly.** Sleeper's trending endpoints return a *bare JSON
list* of ``{player_id, count}`` — no envelope, no timestamp, no window, no metadata of any
kind. Everything that makes a count interpretable a month later therefore has to come from
the request: which window was asked for, what limit was sent, and when. The manifest records
the request and says so, rather than dressing the retrieval time up as a data-as-of claim.

**What it is not.** It is not a price, not an ADP, not a rank, and not a model feature. An
add count is a number of transactions; a draft pick number is a position in an ordering. The
project keeps them in different artifacts with different schemas precisely so that nobody
can later subtract one from the other and call the difference an edge (roadmap 10.3).

**Two feeds, one snapshot.** Adds and drops are captured together under one snapshot key,
because a drop count is only interpretable against the add count from the same moment and
the same window. A capture with one half missing is refused rather than retained: a partial
behaviour snapshot is the shape that produces a confident, wrong "net interest" number.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ffdraft.contracts import SourceBatch
from ffdraft.contracts.enums import BehaviorType
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
from ffdraft.sources.sleeper import (
    SLEEPER_SOURCE_ID,
    TRENDING_LIMIT,
    TRENDING_LOOKBACK_HOURS,
    SleeperTrendingAdapter,
)
from ffdraft.timeutil import isoformat_utc, parse_utc, utc_now

__all__ = [
    "BEHAVIOR_NORMALIZED_FILENAME",
    "BEHAVIOR_PREFIX",
    "BehaviorCapture",
    "capture_behavior",
    "read_behavior_capture",
    "verify_behavior_store",
    "write_behavior_capture",
]

BEHAVIOR_NORMALIZED_FILENAME = "behavior.normalized.json.gz"
BEHAVIOR_MANIFEST_VERSION = "1.0"

#: Where behaviour captures live inside the retention store, beside ``market/`` and
#: ``status/`` (ADR-038). A separate prefix because it is a separate kind of evidence.
BEHAVIOR_PREFIX = "behavior"


@dataclass
class BehaviorCapture:
    """One retained behaviour snapshot: both feeds plus the request that produced them."""

    source_id: str
    season: int
    snapshot_key: str
    observed_at_utc: datetime
    adapter_version: str
    source_policy_version: str
    lookback_hours: int = TRENDING_LOOKBACK_HOURS
    request_limit: int = TRENDING_LIMIT
    rows: list[dict[str, Any]] = field(default_factory=list)
    git_sha: str | None = None
    warning_codes: tuple[str, ...] = ()

    def counts(self, behavior: BehaviorType) -> dict[str, int]:
        """External Sleeper player id -> count, for one feed."""
        return {
            str(row["external_player_id"]): int(row["count"])
            for row in self.rows
            if str(row.get("behavior_type")) == str(behavior)
        }

    def ranks(self, behavior: BehaviorType) -> dict[str, int]:
        """External player id -> position in the feed, 1 being the most added or dropped.

        An ordering *of the feed itself*. It exists so a reader can say "third most added
        this week" without the board inventing a scale; it is never differenced against a
        fair rank, which is a different quantity in different units.
        """
        ordered = sorted(
            self.counts(behavior).items(),
            key=lambda item: (-item[1], item[0]),
        )
        return {player_id: index + 1 for index, (player_id, _) in enumerate(ordered)}

    def rows_for(self, behavior: BehaviorType) -> int:
        return sum(1 for row in self.rows if str(row.get("behavior_type")) == str(behavior))

    @property
    def is_complete(self) -> bool:
        return self.rows_for(BehaviorType.ADD) > 0 and self.rows_for(BehaviorType.DROP) > 0

    def age_hours(self, as_of: datetime) -> float:
        delta = as_of.astimezone(self.observed_at_utc.tzinfo) - self.observed_at_utc
        return max(0.0, delta.total_seconds() / 3600.0)

    def manifest(self, *, content_digest: str) -> dict[str, Any]:
        return {
            "manifest_version": BEHAVIOR_MANIFEST_VERSION,
            "source_id": self.source_id,
            "season": self.season,
            "snapshot_key": self.snapshot_key,
            "observed_at_utc": isoformat_utc(self.observed_at_utc),
            "adapter_version": self.adapter_version,
            "source_policy_version": self.source_policy_version,
            "capture_tool": "ffdraft capture-behavior",
            "git_sha": self.git_sha,
            "lookback_hours": self.lookback_hours,
            "request_limit": self.request_limit,
            "normalized_path": BEHAVIOR_NORMALIZED_FILENAME,
            "normalized_content_hash": content_digest,
            "normalized_row_count": len(self.rows),
            "add_rows": self.rows_for(BehaviorType.ADD),
            "drop_rows": self.rows_for(BehaviorType.DROP),
            "warning_codes": list(self.warning_codes),
            "notes": [
                "Sleeper's trending endpoints publish no timestamp and no window; "
                "observed_at_utc is the retrieval time and lookback_hours is the window "
                "REQUESTED, not one the source confirms.",
                "Behaviour, never a price: an add count is a number of transactions and is "
                "never converted into a draft position or differenced against a rank.",
                "Never a model feature, historical or current. It may decide whether a "
                "player is surfaced and may not change any intrinsic value.",
            ],
        }


def _rows_from_batch(batch: SourceBatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in batch.frame.iter_rows(named=True):
        record = dict(row)
        observed = record.get("snapshot_at_utc")
        if isinstance(observed, datetime):
            record["snapshot_at_utc"] = isoformat_utc(observed)
        rows.append(record)
    return rows


def capture_behavior(
    *,
    season: int,
    as_of: datetime | None = None,
    lookback_hours: int = TRENDING_LOOKBACK_HOURS,
    limit: int = TRENDING_LIMIT,
    timeout_seconds: float = 30.0,
    git_sha: str | None = None,
    payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    gate: QualityGate | None = None,
) -> BehaviorCapture:
    """Retrieve and normalize both trending feeds. **Network I/O unless ``payloads`` given.**

    ``payloads`` maps ``"add"``/``"drop"`` to already-retrieved rows, which is how the
    network-free tests drive this without touching Sleeper.
    """
    stamped = (as_of or utc_now()).replace(microsecond=0)
    checks = gate or QualityGate()
    adapter = SleeperTrendingAdapter()
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for behavior in (BehaviorType.ADD, BehaviorType.DROP):
        if payloads is None:
            batch = adapter.fetch(
                as_of=stamped,
                config=SourceConfig(
                    season=season,
                    timeout_seconds=timeout_seconds,
                    options={
                        "behavior_type": behavior,
                        "lookback_hours": lookback_hours,
                        "limit": limit,
                    },
                ),
            )
        else:
            batch = adapter.normalize(
                list(payloads.get(str(behavior), ())),
                behavior_type=behavior,
                lookback_hours=lookback_hours,
                limit=limit,
                retrieved_at=stamped,
            )
        checks.extend(adapter.validate_raw(batch).checks)
        checks.extend(adapter.semantic_checks(batch))
        rows.extend(_rows_from_batch(batch))
        warnings.extend(batch.metadata.warning_codes)

    return BehaviorCapture(
        source_id=SLEEPER_SOURCE_ID,
        season=season,
        snapshot_key=snapshot_key(stamped),
        observed_at_utc=stamped,
        adapter_version=adapter.adapter_version,
        source_policy_version=adapter.license_policy_version,
        lookback_hours=lookback_hours,
        request_limit=limit,
        rows=rows,
        git_sha=git_sha,
        warning_codes=tuple(dict.fromkeys(warnings)),
    )


def write_behavior_capture(capture: BehaviorCapture, *, store: SnapshotStore) -> list[str]:
    """Append the capture to the store under the same append-only rules as status."""
    if not capture.is_complete:
        raise ValueError(
            "refusing to retain a behaviour snapshot missing one of its two feeds: a drop "
            "count is only interpretable against the add count from the same moment",
        )
    behavior_store = SnapshotStore(root=store.root, prefix=BEHAVIOR_PREFIX)
    directory = behavior_store.snapshot_dir(
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

    files = {BEHAVIOR_NORMALIZED_FILENAME: payload, MANIFEST_FILENAME: manifest}
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


def read_behavior_capture(
    store: SnapshotStore,
    *,
    season: int,
    source_id: str = SLEEPER_SOURCE_ID,
    key: str | None = None,
) -> BehaviorCapture | None:
    """Load the latest (or a named) retained capture, verifying its content hash."""
    behavior_store = SnapshotStore(root=store.root, prefix=BEHAVIOR_PREFIX)
    resolved = key or behavior_store.latest_key(source_id, season)
    if resolved is None:
        return None
    directory = behavior_store.snapshot_dir(source_id, season, resolved)
    manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    payload = (directory / manifest["normalized_path"]).read_bytes()
    digest = content_hash(payload)
    if digest != manifest["normalized_content_hash"]:
        raise SnapshotConflictError(
            f"{directory}: behaviour capture hashes to {digest}, manifest says "
            f"{manifest['normalized_content_hash']}",
        )
    rows: Sequence[dict[str, Any]] = json.loads(gzip.decompress(payload).decode("utf-8"))
    return BehaviorCapture(
        source_id=str(manifest["source_id"]),
        season=int(manifest["season"]),
        snapshot_key=str(manifest["snapshot_key"]),
        observed_at_utc=parse_utc(str(manifest["observed_at_utc"])),
        adapter_version=str(manifest["adapter_version"]),
        source_policy_version=str(manifest["source_policy_version"]),
        lookback_hours=int(manifest.get("lookback_hours", TRENDING_LOOKBACK_HOURS)),
        request_limit=int(manifest.get("request_limit", TRENDING_LIMIT)),
        rows=list(rows),
        git_sha=manifest.get("git_sha"),
        warning_codes=tuple(manifest.get("warning_codes", ())),
    )


def verify_behavior_store(
    store: SnapshotStore,
    *,
    season: int,
    source_id: str = SLEEPER_SOURCE_ID,
) -> tuple[int, int, tuple[str, ...]]:
    """Re-hash every retained behaviour capture against its manifest.

    Returns ``(snapshots, files_checked, problems)``, matching the status verifier's shape
    so ``validate-market-history`` reports one number per prefix rather than claiming a pass
    for a prefix it never opened.
    """
    behavior_store = SnapshotStore(root=store.root, prefix=BEHAVIOR_PREFIX)
    keys = behavior_store.keys(source_id, season)
    problems: list[str] = []
    checked = 0
    previous: datetime | None = None

    for key in keys:
        directory = behavior_store.snapshot_dir(source_id, season, key)
        try:
            moment = parse_snapshot_key(key)
        except ValueError as exc:
            problems.append(f"{key}: {exc}")
            continue
        if previous is not None and moment < previous:
            problems.append(f"{key}: snapshot keys are not in chronological order")
        previous = moment
        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            problems.append(f"{key}: no manifest")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = (directory / manifest["normalized_path"]).read_bytes()
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"{key}: {exc}")
            continue
        checked += 1
        digest = content_hash(payload)
        if digest != manifest.get("normalized_content_hash"):
            problems.append(
                f"{key}: content hash {digest} != manifest "
                f"{manifest.get('normalized_content_hash')}",
            )
    return len(keys), checked, tuple(problems)
