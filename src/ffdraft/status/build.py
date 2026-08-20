"""The current player-status artifact: annotation, and only annotation (ADR-043).

One row per canonical ``player_id``, carrying today's roster status from nflverse and
today's injury/practice context from Sleeper. Phase 6 joins it to Tier and Arbitrage rows in
the browser by ``player_id``.

Two properties are the whole point of the module:

**it is keyed once.** A player appears in nine tier rows (three scoring presets x three
league presets) and up to nine arbitrage rows. Copying mutable injury text onto all
eighteen would multiply the payload and invite eighteen copies to disagree.

**it cannot move a number.** No field here enters the feature matrix, a projection, a VORP,
a fair rank, a tier or an arbitrage score. The intrinsic model was validated on
``intrinsic_core_v1`` and nothing else; a current-state field has no development-era support
and could not have been. `tests/integration/test_status_annotation_only.py` proves it by
mutating every status field and asserting the other artifacts are byte-identical.

Degraded mode is a first-class path, not an error branch: with Sleeper unavailable the
artifact still ships with nflverse roster status, every Sleeper field null, and a
``sleeper_unavailable`` flag on every row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.artifacts import record_schema_version
from ffdraft.contracts import CORE_POSITIONS, PLAYER_STATUS_CONTRACT, Position, QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.identity.registry import CanonicalRegistry
from ffdraft.identity.resolver import (
    REASON_SLEEPER_GSIS_MISMATCH,
    resolve_sleeper_status,
    summarize,
)
from ffdraft.quality import QualityGate
from ffdraft.status.capture import StatusCapture
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "NO_CURRENT_ROSTER_ENTRY",
    "SLEEPER_UNAVAILABLE",
    "STATUS_SOURCE_IDS",
    "PlayerStatusResult",
    "build_player_status_records",
]

_STATUS_SCHEMA = "player_status"

#: Row flags this artifact can carry.
SLEEPER_UNAVAILABLE = "sleeper_unavailable"
SLEEPER_RECORD_MISSING = "sleeper_record_missing"
SLEEPER_IDENTITY_CONFLICT = "sleeper_identity_conflict"
NO_CURRENT_ROSTER_ENTRY = "no_current_roster_entry"

STATUS_SOURCE_IDS = ("nflreadpy", "sleeper")


@dataclass
class PlayerStatusResult:
    """The status records plus the coverage evidence a build metadata block wants."""

    build_id: str
    season: int
    records: list[dict[str, Any]] = field(default_factory=list)
    sleeper_available: bool = True
    sleeper_matched: int = 0
    sleeper_conflicts: int = 0
    observed_at_utc: str | None = None
    gate: QualityGate = field(default_factory=QualityGate)

    def summary(self) -> dict[str, Any]:
        return {
            "players": len(self.records),
            "sleeper_available": self.sleeper_available,
            "sleeper_matched": self.sleeper_matched,
            "sleeper_identity_conflicts": self.sleeper_conflicts,
            "observed_at_utc": self.observed_at_utc,
            "source_ids": list(STATUS_SOURCE_IDS if self.sleeper_available else ("nflreadpy",)),
        }


def _roster_index(roster: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """``player_id -> roster row``, first entry per player.

    A seasonal roster's grain is ``(season, gsis_id, team)`` — a traded player appears once
    per club (contract 1.1) — so "which one" has to be an explicit choice. First by team in
    sorted order is deterministic; the team a status badge shows is the same team the tier
    row shows, because both come from this index.
    """
    if roster.is_empty() or "gsis_id" not in roster.columns:
        return {}
    ordered = roster.sort([column for column in ("gsis_id", "team") if column in roster.columns])
    index: dict[str, dict[str, Any]] = {}
    for row in ordered.iter_rows(named=True):
        gsis = row.get("gsis_id")
        if not gsis:
            continue
        index.setdefault(f"gsis:{gsis}", dict(row))
    return index


def build_player_status_records(
    *,
    registry: CanonicalRegistry,
    roster: pl.DataFrame,
    capture: StatusCapture | None,
    build_id: str,
    season: int,
    generated_at: datetime,
    player_ids: Sequence[str] | None = None,
    positions: Sequence[Position] | None = None,
    gate: QualityGate | None = None,
) -> PlayerStatusResult:
    """Assemble the status artifact.

    ``player_ids`` restricts the artifact to the published board when supplied, which is
    what a production build does: a status row for a player no artifact references is dead
    weight in a payload the browser downloads. Passing ``None`` emits every eligible player,
    which is what the coverage diagnostics want.
    """
    checks = gate or QualityGate()
    wanted_positions = tuple(positions) if positions is not None else tuple(CORE_POSITIONS)
    schema_version = record_schema_version(_STATUS_SCHEMA)
    roster_by_player = _roster_index(roster)

    sleeper_rows: dict[str, Mapping[str, Any]] = {}
    conflicts = 0
    observed_at: str | None = None
    available = capture is not None and bool(capture.rows)

    if capture is not None and capture.rows:
        observed_at = isoformat_utc(capture.observed_at_utc)
        # Built through the contract, not by inference. A retained capture is 12,000 rows of
        # mostly-null free text, and Polars infers a schema from the first few of them — so
        # the first player to carry an injury note several thousand rows in would fail the
        # whole build. The contract already declares every dtype; use it.
        frame = PLAYER_STATUS_CONTRACT.build(
            {**row, "observed_at_utc": capture.observed_at_utc} for row in capture.rows
        )
        outcomes = resolve_sleeper_status(
            frame,
            registry=registry,
            source_id=capture.source_id,
            positions=wanted_positions,
        )
        summary = summarize(outcomes, source_id=capture.source_id)
        by_external = {str(row["external_player_id"]): row for row in capture.rows}
        for outcome in outcomes:
            if outcome.reason == REASON_SLEEPER_GSIS_MISMATCH:
                # A failed cross-check is fatal for the record, never averaged over
                # (ADR-019). The player keeps a status row; it just carries no Sleeper data.
                conflicts += 1
                continue
            if outcome.resolved and outcome.player_id:
                row = by_external.get(outcome.external_player_id)
                if row is not None:
                    sleeper_rows[outcome.player_id] = row
        checks.add(
            QualityCheck.ok(
                "status.sleeper_join",
                stage="status.build",
                message="nflverse -> Sleeper joined on sleeper_id (ADR-011/ADR-019)",
                observed=(
                    f"{summary.resolved} matched, {summary.ambiguous} ambiguous, "
                    f"{summary.unresolved} unresolved of {summary.resolvable_total}"
                ),
            ),
        )
        if conflicts:
            checks.add(
                QualityCheck.fail(
                    "status.sleeper_gsis_conflict",
                    stage="status.build",
                    message=(
                        "Sleeper's reported gsis_id disagreed with the canonical id; those "
                        "records fail closed and carry no Sleeper annotation"
                    ),
                    observed=f"{conflicts} record(s)",
                    expected="0",
                    severity=Severity.WARNING,
                ),
            )
    else:
        observed_at = isoformat_utc(generated_at)
        checks.add(
            QualityCheck.fail(
                "status.sleeper_unavailable",
                stage="status.build",
                message=(
                    "no Sleeper capture was available; the status artifact ships degraded "
                    "and the intrinsic board is untouched (ADR-043)"
                ),
                observed="0 Sleeper rows",
                expected="a current capture",
                severity=Severity.WARNING,
            ),
        )

    candidates = (
        list(player_ids)
        if player_ids is not None
        else list(registry.eligible_players(wanted_positions))
    )
    records: list[dict[str, Any]] = []
    matched = 0
    for player_id in sorted(dict.fromkeys(candidates)):
        player = registry.get(player_id)
        if player is None:
            continue
        roster_row = roster_by_player.get(player_id, {})
        sleeper = sleeper_rows.get(player_id)
        if sleeper is not None:
            matched += 1

        flags: list[str] = []
        if not roster_row:
            flags.append(NO_CURRENT_ROSTER_ENTRY)
        if not available:
            flags.append(SLEEPER_UNAVAILABLE)
        elif sleeper is None:
            flags.append(SLEEPER_RECORD_MISSING)

        records.append(
            {
                "schema_version": schema_version,
                "build_id": build_id,
                "season": season,
                "player_id": player_id,
                "display_name": player.display_name,
                "current_team": roster_row.get("team") or player.team,
                "position": str(player.position),
                "roster_status": roster_row.get("status"),
                "roster_depth_chart_position": roster_row.get("depth_chart_position"),
                "sleeper_status": _text(sleeper, "status"),
                "injury_status": _text(sleeper, "injury_status"),
                "injury_body_part": _text(sleeper, "injury_body_part"),
                "injury_notes": _text(sleeper, "injury_notes"),
                "injury_start_date": _text(sleeper, "injury_start_date"),
                "practice_participation": _text(sleeper, "practice_participation"),
                "practice_description": _text(sleeper, "practice_description"),
                "depth_chart_position": _text(sleeper, "depth_chart_position"),
                "depth_chart_order": _positive_int(sleeper, "depth_chart_order"),
                "observed_at_utc": observed_at or isoformat_utc(generated_at),
                "source_ids": list(STATUS_SOURCE_IDS if available else ("nflreadpy",)),
                "quality_flags": sorted(set(flags)),
            },
        )

    checks.add(
        QualityCheck.ok(
            "status.rows",
            stage="status.build",
            message="one status row per canonical player (ADR-043)",
            observed=f"{len(records)} row(s), {matched} with Sleeper data",
        ),
    )
    return PlayerStatusResult(
        build_id=build_id,
        season=season,
        records=records,
        sleeper_available=available,
        sleeper_matched=matched,
        sleeper_conflicts=conflicts,
        observed_at_utc=observed_at,
        gate=checks,
    )


def _text(row: Mapping[str, Any] | None, key: str) -> str | None:
    if row is None:
        return None
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_int(row: Mapping[str, Any] | None, key: str) -> int | None:
    """Depth-chart order, or ``None``.

    The schema bounds it at ``>= 1``. Sleeper occasionally publishes ``0``, which is not a
    depth-chart slot; it becomes ``None`` rather than being clamped into a rank that would
    read as "starter".
    """
    if row is None:
        return None
    value = row.get(key)
    if value is None:
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None
