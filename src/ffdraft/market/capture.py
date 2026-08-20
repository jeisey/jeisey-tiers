"""Taking a point-in-time market snapshot and retaining it append-only.

**Boundary module.** Market data only. This is the one Phase-5 module that touches a vendor
network, and it does exactly two things: retrieve, and hand the result to the store.

The split matters. Everything downstream — cohort measurement, cohort selection, the A0
baseline, trend, the arbitrage board — reads a *retained snapshot*, never the network. That
is what makes the Phase-5 analysis reproducible offline and diffable against evidence, and
it is why a session behind an egress policy can still build and validate the whole product
from a capture a runner took (ADR-009).

Obligations honoured here, all from the Phase-0 verified contract and ADR-017:

* the ADP export is unauthenticated; the request carries the registered User-Agent and an
  Accept header and nothing else;
* the player database is requested at most once per capture, and MFL asks for at most one
  per day, so a capture reuses one directory across every cohort;
* requests are paced and 429 is backed off, by the adapter's own HTTP helper;
* the response ``timestamp`` is retained as vendor metadata and never becomes a
  data-as-of time.
"""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.config import AppConfig, load_app_config
from ffdraft.contracts import CORE_POSITIONS, EntityKind, MarketCohort, QualityCheck, SourceBatch
from ffdraft.contracts.enums import Severity
from ffdraft.identity.resolver import (
    resolve_market_quotes,
    summarize,
)
from ffdraft.market.cohorts import CANDIDATE_COHORTS, cohort_by_id
from ffdraft.market.identity import MarketIdentity, load_market_identity, mapping_from
from ffdraft.market.snapshot import (
    ADP_RAW_FILENAME,
    PLAYERS_RAW_FILENAME,
    SNAPSHOT_MANIFEST_VERSION,
    CohortCapture,
    SnapshotManifest,
    SnapshotStore,
    WriteResult,
    content_hash,
    snapshot_key,
)
from ffdraft.quality import QualityGate
from ffdraft.sources.base import SourceConfig
from ffdraft.sources.market import (
    MFL_SOURCE_ID,
    MflAdpAdapter,
    MflPlayerDirectory,
    MflPlayerDirectoryAdapter,
)
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "PRODUCTION_COHORT_IDS",
    "STUDY_COHORT_IDS",
    "CaptureResult",
    "RawPayloads",
    "build_snapshot",
    "capture_market",
    "cohort_set",
]

#: The cohorts a routine production capture retains: the widest aggregate plus the two
#: single-axis scoring cohorts, which are the only candidates ADR-039's rule can plausibly
#: pick from once the season matures. Kept small because a daily capture is committed.
PRODUCTION_COHORT_IDS: tuple[str, ...] = ("unfiltered", "ppr", "std")

#: Every candidate, for the Phase-5 cohort study (ADR-012 amendment, ADR-039).
STUDY_COHORT_IDS: tuple[str, ...] = tuple(cohort.cohort_id for cohort in CANDIDATE_COHORTS)


def cohort_set(name_or_ids: str | Sequence[str]) -> tuple[MarketCohort, ...]:
    """Resolve ``"study"``, ``"production"`` or an explicit id list to cohorts."""
    if isinstance(name_or_ids, str):
        ids = {"study": STUDY_COHORT_IDS, "production": PRODUCTION_COHORT_IDS}.get(name_or_ids)
        if ids is None:
            ids = tuple(part.strip() for part in name_or_ids.split(",") if part.strip())
    else:
        ids = tuple(name_or_ids)
    return tuple(cohort_by_id(cohort_id) for cohort_id in ids)


#: Snapshot-relative path -> gzipped bytes.
RawPayloads = dict[str, bytes]


@dataclass
class CaptureResult:
    """One capture: what was retrieved, what was written, and what the gate saw."""

    season: int
    snapshot_key: str
    retrieved_at_utc: datetime
    manifest: SnapshotManifest
    rows: list[dict[str, Any]]
    raw_payloads: RawPayloads = field(default_factory=dict)
    write: WriteResult | None = None
    gate: QualityGate = field(default_factory=QualityGate)


def _gzip_json(payload: Any) -> bytes:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return gzip.compress(body.encode("utf-8"), compresslevel=9, mtime=0)


def _envelope_scalars(payload: Any) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        return {}
    body = payload.get("adp")
    if not isinstance(body, Mapping):
        return {}
    return {
        key: str(body[key])
        for key in ("timestamp", "totalDrafts", "totalPicks")
        if key in body and not isinstance(body[key], list | dict)
    }


def build_snapshot(
    *,
    season: int,
    retrieved_at: datetime,
    raw_by_cohort: Mapping[str, Any],
    raw_players: Any,
    identity: MarketIdentity,
    app: AppConfig | None = None,
    git_sha: str | None = None,
    gate: QualityGate | None = None,
) -> CaptureResult:
    """Normalize, resolve and assemble a snapshot from already-retrieved payloads.

    Pure with respect to the network: every fixture test drives this, and the live capture
    path is a thin wrapper that supplies ``raw_by_cohort`` and ``raw_players``.
    """
    settings = app or load_app_config()
    checks = gate or QualityGate()
    key = snapshot_key(retrieved_at)

    directory_adapter = MflPlayerDirectoryAdapter()
    checks.extend(directory_adapter.check_source_schema(_directory_rows(raw_players)))
    directory_batch = directory_adapter.normalize(raw_players, retrieved_at=retrieved_at)
    checks.extend(directory_adapter.validate_raw(directory_batch).checks)
    directory = MflPlayerDirectory(frame=directory_batch.frame)
    espn_by_mfl = mapping_from(directory_batch.frame, "mfl_id", "espn_id")
    names_by_mfl = mapping_from(directory_batch.frame, "mfl_id", "name")

    adp_adapter = MflAdpAdapter()
    rows: list[dict[str, Any]] = []
    captures: list[CohortCapture] = []
    raw_payloads: RawPayloads = {
        PLAYERS_RAW_FILENAME: _gzip_json(raw_players),
    }

    for cohort_id, payload in sorted(raw_by_cohort.items()):
        cohort = cohort_by_id(cohort_id)
        batch = adp_adapter.normalize(
            payload,
            season=season,
            cohort=cohort,
            directory=directory,
            retrieved_at=retrieved_at,
        )
        checks.extend(_cohort_checks(adp_adapter, batch, cohort_id))
        outcomes = resolve_market_quotes(
            batch.frame,
            registry=identity.registry,
            espn_by_mfl_id=espn_by_mfl,
            gsis_by_mfl_id=identity.gsis_by_mfl_id,
            names_by_mfl_id=names_by_mfl,
            source_id=MFL_SOURCE_ID,
        )
        summary = summarize(outcomes, source_id=MFL_SOURCE_ID)
        resolved = {
            outcome.external_player_id: outcome
            for outcome in outcomes
            if outcome.resolved and outcome.player_id
        }
        rows.extend(_snapshot_rows(batch, resolved, identity))

        raw_path = f"cohorts/{cohort_id}/{ADP_RAW_FILENAME}"
        raw_bytes = _gzip_json(payload)
        raw_payloads[raw_path] = raw_bytes
        envelope = _envelope_scalars(payload)
        captures.append(
            CohortCapture(
                cohort_id=cohort_id,
                filters=dict(cohort.filters),
                label=cohort.label,
                raw_path=raw_path,
                raw_content_hash=content_hash(raw_bytes),
                row_count=batch.frame.height,
                response_timestamp=envelope.get("timestamp"),
                total_drafts=_as_int(envelope.get("totalDrafts")),
                total_picks=_as_int(envelope.get("totalPicks")),
                resolved_players=summary.resolved,
                resolvable_players=summary.resolvable_total,
                ambiguous_players=summary.ambiguous,
                non_player_entities=summary.non_player_entities,
                # A retained snapshot never claims exactness: that is a per-preset verdict
                # the selection rule reaches later (ADR-039).
                exact_cohort=False,
            ),
        )

    manifest = SnapshotManifest(
        manifest_version=SNAPSHOT_MANIFEST_VERSION,
        source_id=MFL_SOURCE_ID,
        season=season,
        snapshot_key=key,
        retrieved_at_utc=isoformat_utc(retrieved_at),
        adapter_version=adp_adapter.adapter_version,
        source_policy_version=settings.registry.source(MFL_SOURCE_ID).extra.get(
            "verified_at",
            "unknown",
        ),
        player_directory_path=PLAYERS_RAW_FILENAME,
        player_directory_content_hash=content_hash(raw_payloads[PLAYERS_RAW_FILENAME]),
        player_directory_row_count=directory_batch.frame.height,
        cohorts=tuple(captures),
        git_sha=git_sha,
        notes=(
            "MFL publishes no data-as-of time; response_timestamp is generation time only.",
            "MFL publishes no ADP standard deviation; dispersion is min/max pick.",
        ),
    )
    return CaptureResult(
        season=season,
        snapshot_key=key,
        retrieved_at_utc=retrieved_at,
        manifest=manifest,
        rows=rows,
        raw_payloads=raw_payloads,
        gate=checks,
    )


def _directory_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        body = payload.get("players", payload)
        rows = body.get("player", []) if isinstance(body, Mapping) else body
        if isinstance(rows, Mapping):
            rows = [rows]
        return [dict(row) for row in rows]
    return [dict(row) for row in payload]


def _cohort_checks(
    adapter: MflAdpAdapter,
    batch: SourceBatch,
    cohort_id: str,
) -> list[QualityCheck]:
    """Adapter validation, re-staged so a failure names the cohort that produced it."""
    report = adapter.validate_raw(batch)
    checks = [
        QualityCheck(
            check_id=check.check_id,
            stage=f"market.capture.{cohort_id}",
            status=check.status,
            severity=check.severity,
            message=check.message,
            observed=check.observed,
            expected=check.expected,
        )
        for check in report.checks
    ]
    if batch.frame.is_empty():
        checks.append(
            QualityCheck.fail(
                "market.empty_cohort",
                stage=f"market.capture.{cohort_id}",
                message="cohort returned no usable prices; retained for the record",
                observed="0 rows",
                expected="> 0",
                severity=Severity.WARNING,
            ),
        )
    return checks


def _snapshot_rows(
    batch: SourceBatch,
    resolved: Mapping[str, Any],
    identity: MarketIdentity,
) -> list[dict[str, Any]]:
    """Normalized quotes plus their identity outcome, ready to retain.

    Unresolved and team-unit rows are retained too, with a null ``player_id`` and their
    refusal reason. A snapshot is evidence: dropping the rows that did not join would hide
    exactly the coverage question a later session needs to answer.
    """
    rows: list[dict[str, Any]] = []
    for row in batch.frame.iter_rows(named=True):
        external = str(row["external_player_id"])
        outcome = resolved.get(external)
        player_id = outcome.player_id if outcome else None
        player = identity.registry.get(player_id) if player_id else None
        rows.append(
            {
                "source_id": str(row["source_id"]),
                "season": int(row["season"]),
                "cohort_id": str(row["cohort_id"]),
                "external_player_id": external,
                "player_id": player_id,
                "resolution_reason": outcome.reason if outcome else None,
                "resolution_bridges": list(outcome.bridges_agreed) if outcome else [],
                "display_name": player.display_name if player else None,
                "position": str(player.position) if player else None,
                "team": player.team if player else None,
                "average_pick": float(row["average_pick"]),
                "market_rank": row["market_rank"],
                "min_pick": row["min_pick"],
                "max_pick": row["max_pick"],
                "sample_size": row["sample_size"],
                "selection_pct": row["selection_pct"],
                "entity_kind": str(row["entity_kind"]),
                "raw_position": row["raw_position"],
                "source_format_detail": str(row["source_format_detail"]),
                "quality_flags": [
                    flag for flag in str(row["quality_flags"] or "").split(",") if flag
                ],
            },
        )
    return rows


def capture_market(
    *,
    season: int,
    store: SnapshotStore,
    cohorts: Sequence[MarketCohort] | None = None,
    as_of: datetime | None = None,
    app: AppConfig | None = None,
    git_sha: str | None = None,
    identity: MarketIdentity | None = None,
    write: bool = True,
    pause_seconds: float = 1.0,
) -> CaptureResult:
    """Retrieve every requested cohort and append one snapshot. **Network I/O.**"""
    settings = app or load_app_config()
    stamped = (as_of or utc_now()).replace(microsecond=0)
    wanted = tuple(cohorts) if cohorts is not None else cohort_set("production")
    gate = QualityGate()

    policy = settings.registry.source(MFL_SOURCE_ID)
    config = SourceConfig(
        season=season,
        policy=policy,
        options={"client": settings.mfl_client},
    )
    resolved_identity = identity or load_market_identity(season, as_of=stamped)
    gate.extend(resolved_identity.checks)

    raw_players = _fetch_json(
        season=season,
        params={"TYPE": "players", "DETAILS": "1", "JSON": "1"},
        config=config,
    )
    raw_by_cohort: dict[str, Any] = {}
    for cohort in wanted:
        time.sleep(pause_seconds)
        raw_by_cohort[cohort.cohort_id] = _fetch_json(
            season=season,
            params={"TYPE": "adp", "JSON": "1", **dict(cohort.filters)},
            config=config,
        )

    result = build_snapshot(
        season=season,
        retrieved_at=stamped,
        raw_by_cohort=raw_by_cohort,
        raw_players=raw_players,
        identity=resolved_identity,
        app=settings,
        git_sha=git_sha,
        gate=gate,
    )
    if write:
        result.write = store.write(
            manifest=result.manifest,
            normalized_rows=result.rows,
            raw_payloads=result.raw_payloads,
        )
    return result


def _fetch_json(*, season: int, params: Mapping[str, str], config: SourceConfig) -> Any:
    """One public MFL export request through the adapter's own 429-aware helper."""
    from ffdraft.sources.market import _mfl_get  # noqa: PLC0415 - internal helper by design

    client = config.options["client"]
    return _mfl_get(season=season, params=params, client=client, config=config)


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def board_positions() -> frozenset[Any]:
    """The positions a market capture cares about. Team units are structurally excluded."""
    return CORE_POSITIONS


def priced_frame(rows: Sequence[Mapping[str, Any]]) -> pl.DataFrame:
    """Resolved player rows from a retained snapshot, as a frame."""
    kept = [
        row
        for row in rows
        if row.get("player_id") and str(row.get("entity_kind")) == str(EntityKind.PLAYER)
    ]
    return pl.DataFrame(kept) if kept else pl.DataFrame()
