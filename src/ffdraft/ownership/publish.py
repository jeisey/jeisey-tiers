"""The in-season build's ESPN ownership step: retained window in, two artifacts out (ADR-112).

Shared by the production rest-of-season build and the fixture pipeline, so both publish the
same records, metadata and quality checks. **Every failure here costs ESPN readings and
nothing else**: a missing store, an empty window, an unreadable capture or an exception in the
metric all produce a metadata block saying so, a warning, and no artifact — and the boards
are byte-identical to a build that never looked (`tests/integration/test_ownership_invariance.py`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.identity.registry import CanonicalRegistry
from ffdraft.ownership.capture import OwnershipCapture
from ffdraft.ownership.history import (
    OWNERSHIP_RULE,
    OWNERSHIP_RULE_VERSION,
    build_ownership,
    load_ownership_window,
)
from ffdraft.sources.espn import ESPN_SOURCE_ID

__all__ = [
    "ATTRIBUTION",
    "POPULATION_STATEMENT",
    "OwnershipLayer",
    "ownership_layer",
    "start_context_statement",
]

ATTRIBUTION = (
    "Rostered % and started %: ESPN Fantasy Football (fantasy.espn.com), read once a day from "
    "ESPN's public player data."
)
POPULATION_STATEMENT = (
    "ESPN's percentages describe ESPN leagues, not yours: whether a player is free in your "
    "league is a separate question. Popularity is crowd interest, not a projection."
)


def start_context_statement(period: int | None) -> str:
    """How every surface qualifies a start percentage: what ESPN does and does not state."""
    read = (
        f"read while ESPN reported scoring period {period} as current"
        if period is not None
        else "read at the time shown"
    )
    return (
        f"Started % is ESPN's figure, {read}. ESPN does not say which week's lineups it counts "
        "or how it is calculated, so no start change or started-among-rostered ratio is shown."
    )


@dataclass(frozen=True)
class OwnershipLayer:
    latest: list[dict[str, Any]] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] | None = None
    checks: list[QualityCheck] = field(default_factory=list)


def _block(status: str, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "rule_version": OWNERSHIP_RULE_VERSION,
        "status": status,
        "reason": reason,
        "source_id": ESPN_SOURCE_ID,
        "rule": OWNERSHIP_RULE.to_dict(),
        "attribution": ATTRIBUTION,
        "population_statement": POPULATION_STATEMENT,
        **extra,
    }


def _warning(check_id: str, message: str, observed: str) -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage="ros_build",
        message=message,
        observed=observed,
        expected="a retained ESPN capture inside the window",
        severity=Severity.WARNING,
    )


def ownership_layer(
    *,
    opportunity_records: Sequence[Mapping[str, Any]],
    registry: CanonicalRegistry | None,
    store: Path | None,
    season: int,
    through_week: int,
    build_id: str,
    generated_at: datetime,
    captures: Sequence[OwnershipCapture] | None = None,
) -> OwnershipLayer:
    """Read the window (or take ``captures``), resolve identity, and shape both artifacts."""
    from ffdraft.artifacts.schemas import record_schema_version

    players: dict[str, str] = {}
    for record in opportunity_records:
        players.setdefault(str(record["player_id"]), str(record.get("position")))
    if registry is None or not len(registry):
        reason = "no identity registry, so no ESPN id can be resolved"
        return OwnershipLayer(
            metadata=_block("unavailable", reason),
            checks=[_warning("ros.espn_ownership_unavailable", reason, "registry empty")],
        )
    skipped: list[str] = []
    if captures is None:
        if store is None:
            reason = "no retained store was supplied to this build"
            return OwnershipLayer(
                metadata=_block("unavailable", reason),
                checks=[_warning("ros.espn_ownership_unavailable", reason, "store=None")],
            )
        try:
            window, skipped = load_ownership_window(store, season=season, now=generated_at)
        except OSError as exc:
            reason = "the retained ESPN store could not be read"
            return OwnershipLayer(
                metadata=_block("failed", reason),
                checks=[_warning("ros.espn_ownership_failed", reason, str(exc))],
            )
    else:
        window = [capture for capture in captures if capture.observed_at_utc <= generated_at]
    if not window:
        reason = (
            f"no retained ESPN capture falls inside the {OWNERSHIP_RULE.series_window_days:g}-day "
            "window"
        )
        return OwnershipLayer(
            metadata=_block("unavailable", reason, skipped_captures=len(skipped)),
            checks=[_warning("ros.espn_ownership_unavailable", reason, f"{len(skipped)} skipped")],
        )
    try:
        built = build_ownership(
            window,
            registry=registry,
            players=players.items(),
            build_id=build_id,
            season=season,
            through_week=through_week,
            generated_at=generated_at,
            schema_versions={
                "espn_ownership": record_schema_version("espn_ownership_record"),
                "espn_ownership_series": record_schema_version("espn_ownership_series"),
            },
        )
    except Exception as exc:  # noqa: BLE001 - an enrichment failure costs its own artifacts
        reason = "the ESPN ownership metric could not be computed"
        return OwnershipLayer(
            metadata=_block("failed", reason),
            checks=[_warning("ros.espn_ownership_failed", reason, repr(exc))],
        )
    summary = dict(built.summary)
    metadata = _block(
        "published",
        None,
        skipped_captures=len(skipped),
        start_context_statement=start_context_statement(summary.get("espn_current_period")),
        **summary,
    )
    checks: list[QualityCheck] = []
    if summary.get("stale"):
        checks.append(
            QualityCheck.fail(
                "ros.espn_ownership_stale",
                stage="ros_build",
                message=(
                    "the newest retained ESPN capture is older than the freshness bound; every "
                    "reading is published as stale and passes no ESPN filter"
                ),
                observed=f"{summary.get('latest_age_hours')} h",
                expected=f"<= {OWNERSHIP_RULE.stale_after_hours:g} h",
                severity=Severity.WARNING,
            ),
        )
    if skipped:
        checks.append(
            _warning(
                "ros.espn_ownership_capture_skipped",
                "retained ESPN captures failed their hash check and were left out",
                "; ".join(skipped[:5]),
            ),
        )
    states = summary.get("reading_states", {})
    checks.append(
        QualityCheck.ok(
            "ros.espn_ownership_published",
            stage="ros_build",
            message=(
                f"{OWNERSHIP_RULE_VERSION}: one ESPN record per Opportunity Board player, every "
                "absence a named state, changes in percentage points with their baselines"
            ),
            observed=(
                f"{len(built.latest)} player(s): {states.get('observed', 0)} observed, "
                f"{states.get('stale', 0)} stale, {states.get('not_published', 0)} not "
                f"published, {states.get('no_espn_id', 0)} without an ESPN id, "
                f"{states.get('ambiguous_espn_id', 0)} ambiguous; {len(built.series)} series "
                f"over {summary.get('captures_in_window')} capture(s)"
            ),
        ),
    )
    return OwnershipLayer(
        latest=list(built.latest),
        series=list(built.series),
        metadata=metadata,
        checks=checks,
    )
