"""The Phase-5 market pipeline: retained snapshot + published board -> arbitrage artifact.

**Boundary module.** This is the join point of the two halves of the product, and the join
is one-directional by construction:

* the **published tier artifact** supplies fair rank. Nothing here re-runs the model, so a
  market outage, a market bug or a cohort change can never cause an intrinsic rebuild;
* the **retained snapshot** supplies price. Nothing here touches a vendor, so an arbitrage
  board is reproducible from evidence months later;
* the result is written beside the intrinsic artifacts, and `build_metadata.json` is
  **merged**, never rewritten — Phase 4's tier-stability warning and every source it
  recorded survive intact (ADR-035, and the Phase-5 brief's requirement that the partial
  exit-gate warnings stay attached).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ffdraft.arbitrage.build import build_arbitrage_records
from ffdraft.arbitrage.frozen import (
    ARBITRAGE_CONFIDENCE_VERSION,
    ARBITRAGE_METHOD_VERSION,
    ARBITRAGE_MODE,
)
from ffdraft.artifacts import record_schema_version, write_artifact, write_build_metadata
from ffdraft.config import AppConfig, load_app_config
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import SourceStatus
from ffdraft.market.cohorts import assignments_from_report
from ffdraft.market.current import build_current_market, load_trend_window
from ffdraft.market.snapshot import MarketSnapshotStore
from ffdraft.market.trend import TREND_RULE, observations_from_snapshots, trend_series_records
from ffdraft.quality import QualityGate
from ffdraft.sources.market import MFL_SOURCE_ID
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = ["ArbitrageBuildRequest", "ArbitrageBuildResponse", "run_arbitrage_build"]


@dataclass(frozen=True)
class ArbitrageBuildRequest:
    """Everything one arbitrage build needs. All of it is on disk."""

    season: int
    store: MarketSnapshotStore
    artifacts_dir: Path
    selection_path: Path
    snapshot_key: str | None = None
    as_of: datetime | None = None
    git_sha: str | None = None
    write: bool = True
    app: AppConfig | None = None


@dataclass
class ArbitrageBuildResponse:
    """What the build produced."""

    build_id: str
    season: int
    snapshot_key: str
    arbitrage_mode: str
    method_version: str
    records: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    confidence_counts: dict[str, int] = field(default_factory=dict)
    unpriced_top_players: list[dict[str, Any]] = field(default_factory=list)
    trend_available: bool = False
    trend_history_keys: tuple[str, ...] = ()
    trend_series: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    written: list[Path] = field(default_factory=list)
    gate: QualityGate = field(default_factory=QualityGate)


def run_arbitrage_build(request: ArbitrageBuildRequest) -> ArbitrageBuildResponse:
    """Build and write the current arbitrage artifact from retained evidence."""
    settings = request.app or load_app_config()
    gate = QualityGate()
    stamped = (request.as_of or utc_now()).replace(microsecond=0)

    tiers = _read_json(request.artifacts_dir / "tiers.json")
    metadata = _read_json(request.artifacts_dir / "build_metadata.json")
    build_id = str(tiers["build_id"])
    tier_records = list(tiers["records"])

    selection = _read_json(request.selection_path)
    assignments = assignments_from_report(selection)
    gate.add(
        QualityCheck.ok(
            "arbitrage.cohort_selection",
            stage="arbitrage.pipeline",
            message=(
                f"cohort selection read from {request.selection_path.name} under rule "
                f"{selection.get('rule_version')} (ADR-039)"
            ),
            observed=f"{len(assignments)} preset assignment(s)",
        ),
    )

    key = request.snapshot_key or request.store.latest_key(MFL_SOURCE_ID, request.season)
    if key is None:
        gate.add(
            QualityCheck.fail(
                "arbitrage.no_retained_snapshot",
                stage="arbitrage.pipeline",
                message="no retained market snapshot; the Tier board is unaffected",
                observed=str(request.store.root),
                expected="at least one snapshot (ADR-038)",
            ),
        )
        return ArbitrageBuildResponse(
            build_id=build_id,
            season=request.season,
            snapshot_key="",
            arbitrage_mode=str(ARBITRAGE_MODE),
            method_version=ARBITRAGE_METHOD_VERSION,
            gate=gate,
        )

    snapshot = request.store.read(MFL_SOURCE_ID, request.season, key)
    history = load_trend_window(
        request.store,
        source_id=MFL_SOURCE_ID,
        season=request.season,
        now=snapshot.retrieved_at,
    )
    market = build_current_market(
        snapshot,
        assignments=assignments,
        now=stamped,
        history=history,
    )

    league_sizes = {
        preset_id: preset.teams for preset_id, preset in settings.league.presets.items()
    }
    league_sizes.update(
        {preset_id: preset.teams for preset_id, preset in settings.league.optional_presets.items()},
    )
    result = build_arbitrage_records(
        tier_records,
        market=market,
        league_size_by_preset=league_sizes,
        build_id=build_id,
        season=request.season,
        generated_at=stamped,
        gate=gate,
    )

    response = ArbitrageBuildResponse(
        build_id=build_id,
        season=request.season,
        snapshot_key=key,
        arbitrage_mode=result.arbitrage_mode,
        method_version=result.method_version,
        records=result.records,
        coverage=result.coverage,
        confidence_counts=result.confidence_counts,
        unpriced_top_players=result.unpriced_top_players,
        trend_available=market.trend_available,
        trend_history_keys=market.trend_history_keys,
        gate=gate,
    )
    response.metadata = _merge_metadata(
        metadata,
        response=response,
        market=market,
        snapshot_row_count=len(snapshot.rows),
        selection=selection,
        git_sha=request.git_sha,
        gate=gate,
    )

    response.trend_series = _trend_series(
        history,
        market=market,
        tier_records=tier_records,
        build_id=build_id,
        league_sizes=league_sizes,
    )

    if request.write and gate.passed:
        paths, checks = write_artifact(
            "arbitrage",
            result.records,
            out_dir=request.artifacts_dir,
            build_id=build_id,
            generated_at=_generated_at(tiers, stamped),
            arbitrage_mode=result.arbitrage_mode,
        )
        gate.extend(checks)
        response.written.extend(paths)
        if response.trend_series:
            # The chart's data, written from the retained snapshots the trend was computed
            # over. This is what lets a static page draw a history without the browser
            # calling a vendor (ADR-066). An empty series simply is not written: a young
            # store has nothing to draw, and an artifact of empty arrays would be bytes
            # shipped to say so.
            series_paths, series_checks = write_artifact(
                "market_trend_series",
                response.trend_series,
                out_dir=request.artifacts_dir,
                build_id=build_id,
                generated_at=_generated_at(tiers, stamped),
            )
            gate.extend(series_checks)
            response.written.extend(series_paths)
        metadata_paths, metadata_checks = write_build_metadata(
            response.metadata,
            out_dir=request.artifacts_dir,
        )
        gate.extend(metadata_checks)
        response.written.extend(metadata_paths)
    return response


def _trend_series(
    history: list[Any],
    *,
    market: Any,
    tier_records: list[dict[str, Any]],
    build_id: str,
    league_sizes: dict[str, int],
) -> list[dict[str, Any]]:
    """One history series per published player, per preset block.

    Restricted to players the board actually shows. A series for a player no card can open is
    weight every visitor downloads for nothing, and the restriction is by published row
    rather than by tier depth so a market-surfaced exception keeps its chart.
    """
    if not history:
        return []
    schema_version = record_schema_version("market_trend_series")
    published: dict[tuple[str, str], set[str]] = {}
    for record in tier_records:
        key = (str(record["league_preset_id"]), str(record["scoring_preset"]))
        published.setdefault(key, set()).add(str(record["player_id"]))

    records: list[dict[str, Any]] = []
    for (preset_id, scoring), players in sorted(published.items()):
        league_size = league_sizes.get(preset_id)
        if league_size is None:
            continue
        assignment = market.assignments.get((scoring, league_size))
        if assignment is None:
            continue
        cohort_id = assignment.cohort.cohort_id
        records.extend(
            trend_series_records(
                observations_from_snapshots(history, cohort_id=cohort_id),
                trends=market.trend_by_cohort.get(cohort_id, {}),
                build_id=build_id,
                market_source_id=market.source_id,
                scoring_preset=scoring,
                league_preset_id=preset_id,
                cohort_id=cohort_id,
                window_days=TREND_RULE.window_days,
                schema_version=schema_version,
                players=players,
            ),
        )
    return records


def _generated_at(tiers: dict[str, Any], fallback: datetime) -> datetime:
    """The arbitrage envelope carries the tier build's generation time.

    Both artifacts describe one build. Stamping the arbitrage envelope with the moment the
    market layer happened to run would make two files from the same build disagree about
    when that build was.
    """
    from ffdraft.timeutil import parse_utc

    raw = tiers.get("generated_at_utc")
    return parse_utc(str(raw)) if raw else fallback


def _merge_metadata(
    metadata: dict[str, Any],
    *,
    response: ArbitrageBuildResponse,
    market: Any,
    snapshot_row_count: int,
    selection: dict[str, Any],
    git_sha: str | None,
    gate: QualityGate,
) -> dict[str, Any]:
    """Add the arbitrage block to the intrinsic build's metadata, keeping everything else.

    Phase 4 published a board that had failed its tier stability gate and recorded a warning
    saying so. An arbitrage build that overwrote this file would erase that warning, which
    is the exact failure the Phase-5 brief forbids. So the existing warnings, sources and
    quality-gate summary are preserved and only added to.
    """
    merged = dict(metadata)
    warnings = list(merged.get("warnings", ()))
    sources = [dict(source) for source in merged.get("sources", ())]

    market_source = {
        "source_id": market.source_id,
        "status": str(SourceStatus.WARNING if gate.warnings else SourceStatus.PASS),
        "retrieved_at_utc": isoformat_utc(market.snapshot_at_utc),
        # MFL publishes no data-as-of time and never will (docs/DATA_SOURCES.md 13.5).
        "source_as_of_utc": None,
        "record_count": snapshot_row_count,
        "warnings": sorted(
            {flag for price in market.prices.values() for flag in price.quality_flags},
        ),
    }
    sources = [source for source in sources if source.get("source_id") != market.source_id]
    sources.append(market_source)

    for check in gate.warnings:
        if check.message not in warnings:
            warnings.append(check.message)

    merged["arbitrage_mode"] = response.arbitrage_mode
    merged["arbitrage_model_version"] = None
    merged["arbitrage_method_version"] = response.method_version
    merged["sources"] = sorted(sources, key=lambda source: str(source["source_id"]))
    merged["warnings"] = warnings
    merged["market"] = {
        "source_id": market.source_id,
        "snapshot_key": response.snapshot_key,
        "snapshot_at_utc": isoformat_utc(market.snapshot_at_utc),
        "source_as_of_utc": None,
        "cohort_rule_version": str(selection.get("rule_version", "")),
        "cohort_report": str(selection.get("snapshot_key", "")),
        "confidence_rubric_version": ARBITRAGE_CONFIDENCE_VERSION,
        "trend_rule_version": TREND_RULE.version,
        "trend_available": response.trend_available,
        "trend_history_snapshots": len(response.trend_history_keys),
        "assignments": [
            {
                "scoring_preset": assignment.scoring_preset,
                "league_size": assignment.league_size,
                "cohort_id": assignment.cohort.cohort_id,
                "exact": assignment.exact,
                "sufficient": assignment.sufficient,
                "source_format_detail": assignment.source_format_detail,
                # The clauses that failed, verbatim ("total_drafts 125 < 300"). Published so a
                # consumer can say *why* every row on this board reads `low` confidence
                # without embedding today's measurement in its own source. Without it the
                # frontend would either hardcode a number that goes stale within a day or
                # show an unexplained label on 2,122 rows (ADR-041, ADR-045).
                "failed_clauses": list(assignment.failed_clauses),
            }
            for _, assignment in sorted(market.assignments.items())
        ],
        "coverage": response.coverage,
        "confidence_counts": response.confidence_counts,
        "unpriced_top_players": len(response.unpriced_top_players),
    }
    if git_sha:
        merged["git_sha"] = git_sha
    summary = gate.summary()
    existing = dict(merged.get("quality_gate", {}))
    merged["quality_gate"] = {
        "status": "fail"
        if summary["status"] == "fail" or existing.get("status") == "fail"
        else "pass",
        "critical_failures": int(existing.get("critical_failures", 0))
        + len(gate.critical_failures),
        "warnings": int(existing.get("warnings", 0)) + len(gate.warnings),
    }
    return merged


def _read_json(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload
