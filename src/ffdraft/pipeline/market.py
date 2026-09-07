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
from collections.abc import Mapping, Sequence
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
from ffdraft.contracts.enums import MarketSignalType, Severity, SourceStatus
from ffdraft.market.cohorts import assignments_from_report
from ffdraft.market.current import build_current_market
from ffdraft.market.extra import load_extra_quotes
from ffdraft.market.history import RetainedHistory, load_trend_window
from ffdraft.market.snapshot import MarketSnapshotStore
from ffdraft.market.surface import build_surface_universe, coverage_checks
from ffdraft.market.trend import TREND_RULE, trend_series_records
from ffdraft.quality import QualityGate
from ffdraft.sources.ffc import FFC_SOURCE_ID
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
    #: The untruncated fair-ranked board `build-current` wrote. Without it the surface rule
    #: cannot run, because a player outside the published depth is absent from the tier
    #: artifact this stage reads — which is the whole reason the blind spot existed.
    full_board_path: Path | None = None
    #: Retained market sources beyond MyFantasyLeague to price this board with.
    extra_source_ids: tuple[str, ...] = (FFC_SOURCE_ID,)


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
    #: Which markets the published history actually covers. A source that priced the board
    #: but has no retained window is absent here, which is the fact the card needs.
    trend_series_sources: tuple[str, ...] = ()
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
    # The second market. Phase 10 built every part of this and connected none of it; a
    # published board that renders a market selector must actually carry more than one
    # market (ADR-067).
    extra = load_extra_quotes(
        request.store,
        season=request.season,
        source_ids=request.extra_source_ids,
        now=stamped,
        gate=gate,
        league_sizes=sorted(set(league_sizes.values())),
    )

    # The surface rule needs the whole board, so it runs only when `build-current` handed one
    # over. Absent, the build behaves exactly as it did before: the published prefix is the
    # surface, and nothing is rescued.
    full_board = _load_full_board(request.full_board_path, gate=gate)
    surfaces = {}
    surfaced_rows: list[dict[str, Any]] = []
    if full_board:
        published = {
            (str(row["league_preset_id"]), str(row["scoring_preset"]), str(row["player_id"]))
            for row in tier_records
        }
        blocks = sorted(
            {(str(row["league_preset_id"]), str(row["scoring_preset"])) for row in tier_records},
        )
        for preset_id, scoring in blocks:
            block_board = [
                row
                for row in full_board
                if str(row["league_preset_id"]) == preset_id
                and str(row["scoring_preset"]) == scoring
            ]
            universe = build_surface_universe(
                block_board,
                scoring_preset=scoring,
                league_preset_id=preset_id,
                memberships=extra.memberships,
                # `build-current --full-board` writes the untruncated universe, so an
                # absent market player here is genuinely unvalued rather than cut.
                board_is_complete=True,
            )
            surfaces[(preset_id, scoring)] = universe
            by_id = {str(row["player_id"]): row for row in block_board}
            surfaced_rows.extend(
                {**by_id[player_id], "league_preset_id": preset_id, "scoring_preset": scoring}
                for player_id in universe.exceptions
                if (preset_id, scoring, player_id) not in published and player_id in by_id
            )
        gate.extend(coverage_checks(list(surfaces.values())))

    result = build_arbitrage_records(
        tier_records,
        market=market,
        league_size_by_preset=league_sizes,
        build_id=build_id,
        season=request.season,
        generated_at=stamped,
        gate=gate,
        extra_quotes=extra.quotes or None,
        surfaces=surfaces or None,
        surfaced_rows=surfaced_rows,
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
    # Every retained ADP source contributes its own history, MyFantasyLeague included. Until
    # this was a list, it was one source's window passed by hand, and the second market's
    # chart could not exist however many snapshots the store held (ADR-081).
    response.trend_series = _trend_series(
        [market.retained, *(extra.histories[source] for source in sorted(extra.histories))],
        arbitrage_records=result.records,
        build_id=build_id,
        league_sizes=league_sizes,
    )
    response.trend_series_sources = tuple(
        sorted({str(record["market_source_id"]) for record in response.trend_series}),
    )

    response.metadata = _merge_metadata(
        metadata,
        response=response,
        market=market,
        snapshot_row_count=len(snapshot.rows),
        selection=selection,
        git_sha=request.git_sha,
        gate=gate,
        extra_sources=extra.sources,
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
    histories: Sequence[RetainedHistory | None],
    *,
    arbitrage_records: Sequence[Mapping[str, Any]],
    build_id: str,
    league_sizes: dict[str, int],
) -> list[dict[str, Any]]:
    """One history series per source, per player **that source priced**, per preset block.

    Scoped by the published arbitrage rows rather than by the tier board, and per source
    rather than per player. That is narrower than it first looks, and both halves matter:

    * *per player* keeps ADR-066's rule that a series for a card nobody can open is weight
      every visitor downloads for nothing — and, because the scope is the arbitrage row, a
      market-surfaced exception (ADR-063) keeps his chart;
    * *per source* is the half a single-market build could not have needed. The trailing
      window is seven days wide, so it holds players a source priced on Tuesday and dropped
      by Friday. Charting those would put a history under a market that has no current price
      for him — which the card would render as "no FFC ADP" beside an FFC line. Found by the
      cross-artifact check on a real 2026 build, on 20 players (ADR-081).

    **The artifact stays source-specific.** A player both markets price gets two records —
    one FFC, one MyFantasyLeague — carrying their own cohorts, their own points and their own
    slopes. There is deliberately no ``cross`` record: a synthetic cross-market ADP history
    would be a line no capture produced, and the cross view's job is to show the two real
    series beside each other rather than to average them away.
    """
    schema_version = record_schema_version("market_trend_series")
    priced: dict[tuple[str, str, str], set[str]] = {}
    for record in arbitrage_records:
        block = (str(record["league_preset_id"]), str(record["scoring_preset"]))
        for entry in record.get("markets") or ():
            if str(entry.get("market_signal_type")) != str(MarketSignalType.ADP):
                continue
            priced.setdefault((*block, str(entry["source_id"])), set()).add(
                str(record["player_id"]),
            )

    records: list[dict[str, Any]] = []
    for history in histories:
        if history is None or history.is_empty:
            continue
        for (preset_id, scoring, source_id), players in sorted(priced.items()):
            if source_id != history.source_id:
                continue
            league_size = league_sizes.get(preset_id)
            if league_size is None:
                continue
            cohort_id = history.cohort_for(scoring, league_size)
            if cohort_id is None:
                continue
            records.extend(
                trend_series_records(
                    history.observations_for(cohort_id),
                    trends=history.trends_for(cohort_id),
                    build_id=build_id,
                    market_source_id=history.source_id,
                    scoring_preset=scoring,
                    league_preset_id=preset_id,
                    cohort_id=cohort_id,
                    window_days=history.rule.window_days,
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


def _load_full_board(path: Path | None, *, gate: QualityGate) -> list[dict[str, Any]]:
    """The untruncated board `build-current` wrote, or an empty list with the reason.

    Missing is not an error. The fixture pipeline and every offline rebuild run without it,
    and the correct behaviour there is the pre-surface one — publish the prefix, rescue
    nobody — rather than a crash. What must never happen is a *silent* skip, so an absent or
    unreadable file is recorded either way.
    """
    if path is None:
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        gate.add(
            QualityCheck.fail(
                "arbitrage.full_board_unreadable",
                stage="arbitrage.pipeline",
                message=(
                    f"the untruncated board at {path} could not be read, so no player is "
                    f"surfaced from beyond the published depth: {error}"
                ),
                observed=type(error).__name__,
                expected="the board written by build-current --full-board",
                severity=Severity.WARNING,
            ),
        )
        return []
    return [dict(row) for row in rows]


def _merge_metadata(
    metadata: dict[str, Any],
    *,
    response: ArbitrageBuildResponse,
    market: Any,
    snapshot_row_count: int,
    selection: dict[str, Any],
    git_sha: str | None,
    gate: QualityGate,
    extra_sources: Sequence[Mapping[str, Any]] = (),
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
        # Per source, because "is there a chart?" is a per-source question and answering it
        # with MyFantasyLeague's number is exactly how a real FFC history went unnoticed
        # (ADR-081). A source listed here with `series: false` priced the board and has no
        # retained window; one with `trend_available: false` has a window whose span has not
        # yet reached the frozen rule, which is a different and temporary state.
        "trend_sources": [
            {
                "source_id": market.source_id,
                "snapshots": len(response.trend_history_keys),
                "trend_available": response.trend_available,
                "series": market.source_id in response.trend_series_sources,
            },
            *(
                {
                    "source_id": str(entry["source_id"]),
                    "snapshots": int(entry.get("trend_history_snapshots", 0)),
                    "trend_available": bool(entry.get("trend_available", False)),
                    "series": str(entry["source_id"]) in response.trend_series_sources,
                }
                for entry in extra_sources
                if entry.get("status") == "priced"
            ),
        ],
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
