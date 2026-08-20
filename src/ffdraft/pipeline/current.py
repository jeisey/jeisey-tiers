"""The current-season production build: features, inference, simulation, tiers, artifacts.

This is the path a daily refresh runs, and it differs from the historical build in exactly
one important way: **its information cutoff is the build timestamp, not the season's draft
anchor.**

A historical row for season Y is a claim about what was knowable at Y's anchor - 23:59:59
Eastern on the Tuesday before Week 1 (ADR-021). A build running in August 2026 is standing
*before* the 2026 anchor, so pretending that anchor has already happened would be claiming
knowledge of roster moves that have not occurred. The cutoff used here is therefore
``min(build timestamp, season anchor)``, recorded under its own rule version
``current_build_as_of_v1`` so a row's provenance says which bound applied. Taking the
minimum also means a current row can never see *more* than a training row would have, which
keeps the train/serve gap in the safe direction.

In practice the cutoff moves very little: `intrinsic_core_v1` is almost entirely lagged
features from completed seasons, which do not change between August and September. What it
does change is the **eligible universe**, because the pre-anchor depth snapshots that admit
undrafted rookies accumulate through the preseason.

Three other rules hold here:

* **Current status is metadata, never a model input.** The production model consumes exactly
  the frozen `intrinsic_core_v1` feature set. Today's roster status, today's team, today's
  depth chart and today's injury report may annotate a published row or remove an entity that
  is demonstrably not a player, but none of them can move a prediction. Anything else would be
  serving a model on features it was never validated with. Phase 5 adds the Sleeper
  injury/practice half of that annotation as a *separate* artifact keyed once per player
  (ADR-043); it is assembled after the board exists and cannot reach back into it.
* **Exclusion needs positive evidence.** A player is dropped from the board only when the
  current roster records him as retired. Absence from a roster is not evidence of absence
  from the league - unsigned free agents sign in September - so those rows stay, flagged.
* **The build is deterministic.** Identical model version, simulation version, build id,
  seed and inputs produce identical artifacts, byte for byte.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from ffdraft.anchors import ANCHOR_TIMEZONE, SeasonAnchor, build_season_anchors
from ffdraft.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    write_artifact,
    write_build_metadata,
)
from ffdraft.config import AppConfig, LeaguePreset, ScoringPreset, load_app_config
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.features.build import build_feature_table
from ffdraft.features.dictionary import feature_schema_hash
from ffdraft.features.sources import load_historical_sources
from ffdraft.modeling.build_config import CurrentBuildConfig
from ffdraft.modeling.features import core_feature_selection
from ffdraft.modeling.production import ProductionModel
from ffdraft.quality import QualityGate, audit_intrinsic_feature_names
from ffdraft.simulation.vorp import (
    SimulationConfig,
    fair_ranking,
    quantile_column_names,
    sample_points,
    simulate_vorp,
)
from ffdraft.status.build import build_player_status_records
from ffdraft.status.capture import StatusCapture, read_status_capture
from ffdraft.tiers.algorithms import segment_with
from ffdraft.tiers.labels import tier_label
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "CURRENT_CUTOFF_RULE_VERSION",
    "CURRENT_METHODOLOGY_VERSION",
    "build_board_records",
    "DEFAULT_CURRENT_ARTIFACT_DIR",
    "RETIRED_STATUS",
    "CurrentBuildConfig",
    "CurrentBuildResult",
    "current_cutoff",
    "run_current_build",
]

#: The methodology this build implements, end to end: the promoted architecture, the
#: sampler, the allocation, the ranking statistic and the segmentation. Published in
#: ``build_metadata.json`` so a reader can tell one pipeline generation from another without
#: reading the model version, which changes on a retrain that keeps the same methodology.
CURRENT_METHODOLOGY_VERSION = "phase4_intrinsic_v1"

#: The versioned cutoff rule for current inference. Distinct from ADR-021's historical rule
#: because it means something different: "everything the build could see when it ran".
CURRENT_CUTOFF_RULE_VERSION = "current_build_as_of_v1"

#: The one nflverse roster status that removes a player from the board. Everything else -
#: reserve, cut, exempt, or absent entirely - is a flag, because none of them is evidence
#: that the player will not be on a roster in September.
RETIRED_STATUS = "RET"

#: Roster statuses that annotate a published row rather than removing it.
FLAGGED_STATUSES: Mapping[str, str] = {
    "RES": "current_status_reserve",
    "CUT": "current_status_cut",
    "E14": "current_status_exempt",
}

DEFAULT_CURRENT_ARTIFACT_DIR = Path("web/public/data")

_EASTERN = ZoneInfo(ANCHOR_TIMEZONE)


def current_cutoff(anchor: SeasonAnchor, as_of: datetime) -> SeasonAnchor:
    """The information cutoff for a current build: ``min(as_of, anchor)``.

    When the build runs before the anchor - the normal case for a preseason refresh - the
    cutoff is the build timestamp and the row records ``current_build_as_of_v1``. When it
    runs after, the anchor still binds and the historical rule version stands, so a
    late-August build and a mid-September build cannot disagree about what a "draft-time"
    feature means.
    """
    stamped = as_of.astimezone(UTC)
    if stamped >= anchor.anchor_at_utc:
        return anchor
    return replace(
        anchor,
        anchor_at_utc=stamped,
        anchor_local=stamped.astimezone(_EASTERN),
        rule_version=CURRENT_CUTOFF_RULE_VERSION,
    )


@dataclass
class CurrentBuildResult:
    """Everything one current build produced."""

    season: int
    build_id: str
    as_of_utc: datetime
    cutoff: SeasonAnchor
    config: CurrentBuildConfig
    model_version: str
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    gate: QualityGate = field(default_factory=QualityGate)
    written: list[Path] = field(default_factory=list)


def _model_frame(features: pl.DataFrame, presets: Sequence[str]) -> pl.DataFrame:
    """One row per player and scoring preset, carrying only declared model inputs."""
    selection = core_feature_selection()
    keep = [
        name
        for name in ("player_id", "display_name", "position", "team_at_anchor", *selection.included)
        if name in features.columns
    ]
    ordered = list(dict.fromkeys(keep))
    base = features.select(ordered)
    return base.join(
        pl.DataFrame({"scoring_preset": list(presets)}),
        how="cross",
    ).sort("scoring_preset", "player_id")


def _current_status(roster: pl.DataFrame) -> pl.DataFrame:
    """Today's roster status and team, keyed by canonical id. Metadata only."""
    if roster.is_empty():
        return pl.DataFrame(
            schema={"player_id": pl.String, "current_status": pl.String, "current_team": pl.String},
        )
    return (
        roster.select(
            (pl.lit("gsis:") + pl.col("gsis_id")).alias("player_id"),
            pl.col("status").alias("current_status"),
            pl.col("team").alias("current_team"),
        )
        .group_by("player_id")
        .agg(pl.col("current_status").first(), pl.col("current_team").first())
    )


def _quality_flags(row: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    status = row.get("current_status")
    if status is None:
        flags.append("no_current_roster_entry")
    elif isinstance(status, str) and status in FLAGGED_STATUSES:
        flags.append(FLAGGED_STATUSES[status])
    if row.get("rookie_flag"):
        flags.append("rookie")
    if not row.get("has_prior_season_stats", True):
        flags.append("no_prior_season_stats")
    if str(row.get("depth_context_state", "")) == "depth_unavailable":
        flags.append("no_depth_context")
    return sorted(set(flags))


def run_current_build(
    *,
    season: int,
    model_dir: Path,
    out_dir: Path,
    config: CurrentBuildConfig,
    as_of: datetime | None = None,
    build_id: str | None = None,
    git_sha: str | None = None,
    app: AppConfig | None = None,
    sources: Any | None = None,
    current_roster: pl.DataFrame | None = None,
    status_capture: StatusCapture | None = None,
    status_store: Any | None = None,
    write: bool = True,
) -> CurrentBuildResult:
    """Build the current season's intrinsic tier board and write its artifacts.

    ``sources`` lets a caller supply already-loaded source frames, which is how the
    network-free integration test drives the whole path without touching a vendor. When it
    is supplied the build never fetches anything of its own, including the current roster:
    the caller owns loading, entirely.
    """
    stamped = (as_of or utc_now()).astimezone(UTC)
    settings = app or load_app_config()
    gate = QualityGate()
    model = ProductionModel.load(model_dir)

    selection = core_feature_selection()
    model.assert_compatible(
        feature_set_hash=selection.fingerprint(),
        feature_schema_hash=feature_schema_hash(),
    )
    gate.add(
        QualityCheck.ok(
            "current.model_feature_schema",
            stage="current_build",
            message="the production model's feature contract matches this build's",
            observed=f"{selection.version} ({selection.fingerprint()})",
        ),
    )

    # The target season's own statistics are never loaded here. Before the season they do
    # not exist; during it they are outcomes of the season being predicted. Either way a
    # current build has no use for them, and saying so explicitly beats depending on which
    # of the two is currently true.
    loaded = sources or load_historical_sources(
        target_seasons=[season],
        as_of=stamped,
        include_target_statistics=False,
    )
    gate.extend(loaded.checks)
    anchor = build_season_anchors(loaded.sources.schedule, [season])[season]
    cutoff = current_cutoff(anchor, stamped)
    gate.add(
        QualityCheck.ok(
            "current.information_cutoff",
            stage="current_build",
            message=f"cutoff rule {cutoff.rule_version}",
            observed=(
                f"as_of={isoformat_utc(stamped)}; season anchor="
                f"{isoformat_utc(anchor.anchor_at_utc)}; cutoff="
                f"{isoformat_utc(cutoff.anchor_at_utc)}"
            ),
        ),
    )

    built = build_feature_table(
        loaded.sources,
        config=settings,
        seasons=[season],
        anchors={season: cutoff},
    )
    gate.extend(built.checks)
    features = built.features
    if features.is_empty():
        gate.add(
            QualityCheck.fail(
                "current.empty_universe",
                stage="current_build",
                message=f"{season} produced no eligible players at the build cutoff",
                observed="0 rows",
                expected="> 0",
            ),
        )
        return CurrentBuildResult(
            season=season,
            build_id=build_id or "",
            as_of_utc=stamped,
            cutoff=cutoff,
            config=config,
            model_version=model.spec.model_version,
            gate=gate,
        )

    gate.extend(audit_intrinsic_feature_names(selection.included))

    roster = _resolve_current_roster(
        loaded,
        season,
        override=current_roster,
        allow_fetch=sources is None,
        as_of=stamped,
        gate=gate,
    )
    status = _current_status(roster)
    annotated = features.join(status, on="player_id", how="left")
    retired = annotated.filter(pl.col("current_status") == RETIRED_STATUS)
    eligible = annotated.filter(
        pl.col("current_status").is_null() | (pl.col("current_status") != RETIRED_STATUS),
    )
    gate.add(
        QualityCheck.ok(
            "current.status_filter",
            stage="current_build",
            message=(
                "players the current roster records as retired are excluded; every other "
                "status annotates the row rather than removing it"
            ),
            observed=f"{retired.height} excluded of {annotated.height}",
        ),
    )

    if config.tier_stability_gate != "pass":
        gate.add(
            QualityCheck.fail(
                "current.tier_stability",
                stage="current_build",
                message=(
                    "tiers are published having not passed the frozen tier stability gate; "
                    "read a tier as a group of comparable players, not as a hard line - "
                    "membership is reproducible but boundary positions are not (ADR-035)"
                ),
                observed=(
                    f"{config.tier_algorithm} @ penalty {config.tier_penalty}: "
                    f"stability gate {config.tier_stability_gate}"
                ),
                severity=Severity.WARNING,
            ),
        )

    resolved_build_id = build_id or _build_id(model.spec.model_version, stamped, season)
    frame = _model_frame(eligible, config.scoring_presets)
    projections = model.predict(frame, season=season)

    context = eligible.select(
        "player_id",
        "display_name",
        "position",
        pl.coalesce(pl.col("current_team"), pl.col("team_at_anchor")).alias("team"),
        "current_status",
        "rookie_flag",
        "has_prior_season_stats",
        "depth_context_state",
    )
    records, diagnostics = build_board_records(
        projections,
        context,
        settings=settings,
        config=config,
        model=model,
        season=season,
        build_id=resolved_build_id,
        as_of=stamped,
        gate=gate,
    )

    # The status artifact is assembled *after* the board and from a different registry
    # instance, so it cannot participate in producing a single published number. It is
    # deliberately restricted to players the board actually names: a status row nobody
    # references is payload the browser downloads for nothing (ADR-043).
    status = _player_status(
        roster=roster,
        capture=status_capture or _retained_status(status_store, season, gate),
        build_id=resolved_build_id,
        season=season,
        as_of=stamped,
        published=[str(row["player_id"]) for row in records.get("tiers", ())],
        gate=gate,
    )
    records["player_status"] = status.records

    metadata = _build_metadata(
        settings,
        loaded=loaded,
        gate=gate,
        season=season,
        build_id=resolved_build_id,
        as_of=stamped,
        git_sha=git_sha,
        model=model,
        status=status,
    )
    written: list[Path] = []
    if write and gate.passed:
        out_dir.mkdir(parents=True, exist_ok=True)
        for artifact, rows in sorted(records.items()):
            paths, checks = write_artifact(
                artifact,
                rows,
                out_dir=out_dir,
                build_id=resolved_build_id,
                generated_at=stamped,
                arbitrage_mode=settings.arbitrage_mode,
            )
            gate.extend(checks)
            written.extend(paths)
        metadata_paths, metadata_checks = write_build_metadata(metadata, out_dir=out_dir)
        gate.extend(metadata_checks)
        written.extend(metadata_paths)
    return CurrentBuildResult(
        season=season,
        build_id=resolved_build_id,
        as_of_utc=stamped,
        cutoff=cutoff,
        config=config,
        model_version=model.spec.model_version,
        records=records,
        metadata=metadata,
        diagnostics=diagnostics,
        gate=gate,
        written=written,
    )


def _resolve_current_roster(
    loaded: Any,
    season: int,
    *,
    override: pl.DataFrame | None,
    allow_fetch: bool,
    as_of: datetime,
    gate: QualityGate,
) -> pl.DataFrame:
    """The target season's roster. Status metadata only, never a model input.

    The historical loader deliberately fetches only the *previous* season's roster: ADR-022
    refuses a target-season roster as eligibility evidence because it carries no observation
    timestamp. Current inference is a different question with a different answer - the build
    is fetching it *now*, so "this is true now" is exactly what it knows, and ADR-011 names
    nflverse rosters as a current-status source. It informs the published board's status
    flags and nothing else.
    """
    if override is not None:
        return override
    existing: pl.DataFrame | None = loaded.sources.rosters.get(season)
    if existing is not None:
        return existing
    if not allow_fetch:
        gate.add(
            QualityCheck.fail(
                "current.roster_status_unavailable",
                stage="current_build",
                message=(
                    "no current roster was supplied, so no player can be excluded on status "
                    "evidence; every row is flagged as having no roster entry"
                ),
                observed=f"season {season}",
                severity=Severity.WARNING,
            ),
        )
        return pl.DataFrame()

    import nflreadpy

    from ffdraft.sources.nflverse import NflverseRosterAdapter

    adapter = NflverseRosterAdapter()
    batch = adapter.normalize(
        nflreadpy.load_rosters(seasons=[season]),
        season=season,
        retrieved_at=as_of,
    )
    gate.extend(adapter.validate_raw(batch).checks)
    loaded.metadata.append(batch.metadata)
    gate.add(
        QualityCheck.ok(
            "current.roster_status_source",
            stage="current_build",
            message="current roster status fetched for the target season (ADR-011)",
            observed=f"{batch.frame.height} row(s) as of {isoformat_utc(as_of)}",
        ),
    )
    return batch.frame


def _build_id(model_version: str, as_of: datetime, season: int) -> str:
    return f"{season}-{model_version}-{as_of.strftime('%Y%m%dT%H%M%SZ')}"


def _retained_status(store: Any, season: int, gate: QualityGate) -> StatusCapture | None:
    """The latest retained Sleeper capture, when a store was supplied.

    A build behind an egress policy - or any build that wants byte-reproducible output -
    reads the capture a runner retained instead of calling Sleeper live (ADR-038). No store
    means no capture, and the status artifact degrades rather than the build failing.
    """
    if store is None:
        return None
    try:
        return read_status_capture(store, season=season)
    except (OSError, ValueError) as exc:
        gate.add(
            QualityCheck.fail(
                "current.status_capture_unreadable",
                stage="current_build",
                message="the retained Sleeper capture could not be read; status degrades",
                observed=str(exc),
                expected="a readable capture",
                severity=Severity.WARNING,
            ),
        )
        return None


def _player_status(
    *,
    roster: pl.DataFrame,
    capture: StatusCapture | None,
    build_id: str,
    season: int,
    as_of: datetime,
    published: Sequence[str],
    gate: QualityGate,
) -> Any:
    """Build the annotation artifact from a registry of its own.

    The registry is rebuilt here rather than shared with the feature build, which is not
    duplication for its own sake: it makes the status path structurally incapable of
    handing anything to the model path, because the two never touch the same object.
    """
    from ffdraft.identity.registry import build_registry

    registry = build_registry(roster) if not roster.is_empty() else build_registry(pl.DataFrame())
    return build_player_status_records(
        registry=registry,
        roster=roster,
        capture=capture,
        build_id=build_id,
        season=season,
        generated_at=as_of,
        player_ids=sorted(dict.fromkeys(published)),
        gate=gate,
    )


def build_board_records(
    projections: pl.DataFrame,
    context: pl.DataFrame,
    *,
    settings: AppConfig,
    config: CurrentBuildConfig,
    model: ProductionModel,
    season: int,
    build_id: str,
    as_of: datetime,
    gate: QualityGate,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Simulate, rank, tier and serialize every scoring x league preset.

    Separated from the fetch-and-feature half so the whole value chain - sampling,
    allocation, ranking, segmentation and record shape - can be driven from a synthetic pool
    in a test without a source, a model file or a network.
    """
    joined = projections.join(context, on="player_id", how="inner")
    point_columns = quantile_column_names("points", config.levels)
    bounds_by_preset = model.point_bounds()

    projection_records: list[dict[str, Any]] = []
    tier_records: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {"presets": [], "replacement": []}

    for scoring in config.scoring_presets:
        block = joined.filter(pl.col("scoring_preset") == scoring).sort("player_id")
        if block.is_empty():
            continue
        simulation_config = SimulationConfig(
            draws=config.draws,
            seed=config.seed,
            model_version=model.spec.model_version,
            scoring_preset=scoring,
            build_id=build_id,
            levels=config.levels,
        )
        bounds = bounds_by_preset.get(scoring, {})
        points = sample_points(block, config=simulation_config, bounds=bounds)
        projection_records.extend(
            _projection_records(
                block,
                points,
                model_version=model.spec.model_version,
                season=season,
                build_id=build_id,
                as_of=as_of,
                columns=point_columns,
            ),
        )
        for preset_id in config.league_preset_ids:
            preset = settings.league.preset(preset_id)
            result = simulate_vorp(
                block,
                preset=preset,
                config=simulation_config,
                bounds=bounds,
                points=points,
            )
            # A position whose pool was entirely consumed by starting slots has no
            # replacement baseline, so its players have no league-relative value to publish.
            # That cannot happen with a production-sized pool; when it does, the rows are
            # withheld and counted rather than shipped as an invented zero.
            valued = result.players.filter(pl.col("expected_vorp").is_not_null())
            withheld = result.players.height - valued.height
            if withheld:
                gate.add(
                    QualityCheck.fail(
                        "current.unvalued_players_withheld",
                        stage="current_build",
                        message=(
                            f"{preset_id}/{scoring}: {withheld} player(s) had no replacement "
                            "baseline in any draw and are not published"
                        ),
                        observed=f"{withheld} of {result.players.height}",
                        severity=Severity.WARNING,
                    ),
                )
            board = fair_ranking(
                valued.join(context, on="player_id", how="inner"),
                statistic=config.ranking_statistic,
            )
            published = board.head(config.board_depth)
            segmentation = segment_with(
                config.tier_algorithm,
                published,
                penalty=config.tier_penalty,
            )
            tier_records.extend(
                _tier_records(
                    published,
                    segmentation.ordinals,
                    build_id=build_id,
                    preset=preset,
                    scoring=scoring,
                ),
            )
            diagnostics["presets"].append(
                {
                    "scoring_preset": scoring,
                    "league_preset_id": preset_id,
                    "players": result.players.height,
                    "published": published.height,
                    **segmentation.to_dict(),
                },
            )
            diagnostics["replacement"].append(
                {
                    "scoring_preset": scoring,
                    "league_preset_id": preset_id,
                    "replacement": result.replacement,
                    "unfilled_slots": dict(result.unfilled_slots),
                },
            )
            if result.unfilled_slots:
                gate.add(
                    QualityCheck.fail(
                        "current.unfilled_starting_slots",
                        stage="current_build",
                        message=(
                            f"{preset_id}/{scoring} could not fill every starting slot from "
                            "the eligible pool"
                        ),
                        observed=str(dict(result.unfilled_slots)),
                        severity=Severity.WARNING,
                    ),
                )
    return (
        {"projections": projection_records, "tiers": tier_records},
        diagnostics,
    )


def _projection_records(
    block: pl.DataFrame,
    points: Any,
    *,
    model_version: str,
    season: int,
    build_id: str,
    as_of: datetime,
    columns: Sequence[str],
) -> list[dict[str, Any]]:
    import numpy as np

    expected = np.mean(points, axis=1)
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(block.iter_rows(named=True)):
        quantiles = {name: float(row[name]) for name in columns}
        rows.append(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "build_id": build_id,
                "model_version": model_version,
                "season": season,
                "as_of_utc": isoformat_utc(as_of),
                "player_id": str(row["player_id"]),
                "display_name": str(row["display_name"]),
                "team": row.get("team"),
                "position": str(row["position"]),
                "scoring_preset": str(row["scoring_preset"]),
                "expected_points": round(float(expected[index]), 4),
                **{name: round(value, 4) for name, value in quantiles.items()},
                "uncertainty_points": round(
                    float(quantiles["p75_points"] - quantiles["p25_points"]),
                    4,
                ),
                "quality_flags": _quality_flags(row),
            },
        )
    return rows


def _tier_records(
    board: pl.DataFrame,
    ordinals: Sequence[int],
    *,
    build_id: str,
    preset: LeaguePreset,
    scoring: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, row in zip(ordinals, board.iter_rows(named=True), strict=True):
        rows.append(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "build_id": build_id,
                "league_preset_id": preset.preset_id,
                "scoring_preset": str(ScoringPreset(scoring)),
                "player_id": str(row["player_id"]),
                "display_name": str(row["display_name"]),
                "team": row.get("team"),
                "position": str(row["position"]),
                "fair_rank": int(row["fair_rank"]),
                "position_rank": int(row["position_rank"]),
                "tier_ordinal": int(ordinal),
                "tier_label": tier_label(int(ordinal)),
                "expected_vorp": round(float(row["expected_vorp"]), 4),
                "p10_vorp": round(float(row["p10_vorp"]), 4),
                "p25_vorp": round(float(row["p25_vorp"]), 4),
                "p50_vorp": round(float(row["p50_vorp"]), 4),
                "p75_vorp": round(float(row["p75_vorp"]), 4),
                "p90_vorp": round(float(row["p90_vorp"]), 4),
                "expected_points": round(float(row["expected_points"]), 4),
                "uncertainty": round(float(row["uncertainty"]), 4),
                "quality_flags": _quality_flags(row),
            },
        )
    return rows


def _build_metadata(
    settings: AppConfig,
    *,
    loaded: Any,
    gate: QualityGate,
    season: int,
    build_id: str,
    as_of: datetime,
    git_sha: str | None,
    model: ProductionModel,
    status: Any | None = None,
) -> dict[str, Any]:
    summary = gate.summary()
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "build_id": build_id,
        "generated_at_utc": isoformat_utc(as_of),
        "git_sha": git_sha or "0000000",
        "season": season,
        "intrinsic_model_version": model.spec.model_version,
        "arbitrage_mode": settings.arbitrage_mode,
        "arbitrage_model_version": None,
        # Phase 5 writes this when `build-arbitrage` runs; an intrinsic-only build has no
        # arbitrage method to name, and inventing one would be a claim about a board that
        # does not exist yet.
        "arbitrage_method_version": None,
        "player_status": status.summary() if status is not None else None,
        "supported_presets": sorted(settings.league.presets),
        "sources": [
            {
                "source_id": item.source_id,
                "status": str(item.status),
                "retrieved_at_utc": isoformat_utc(item.retrieved_at_utc),
                "source_as_of_utc": (
                    isoformat_utc(item.source_as_of_utc) if item.source_as_of_utc else None
                ),
                "record_count": item.record_count,
                "warnings": list(item.warning_codes),
            }
            for item in _source_metadata(loaded)
        ],
        "quality_gate": {
            "status": summary["status"],
            "critical_failures": len(gate.critical_failures),
            "warnings": len(gate.warnings),
        },
        "warnings": [check.message for check in gate.warnings],
        "methodology_version": CURRENT_METHODOLOGY_VERSION,
    }


def _source_metadata(loaded: Any) -> list[Any]:
    """One record per source, aggregating its resources.

    The public contract wants source-level freshness, not one row per loader call, so the
    earliest retrieval and the largest record count for a source stand for it and every
    warning code is carried through.
    """
    aggregated: dict[str, Any] = {}
    for item in loaded.metadata:
        current = aggregated.get(item.source_id)
        if current is None:
            aggregated[item.source_id] = item
            continue
        aggregated[item.source_id] = replace(
            current,
            record_count=current.record_count + item.record_count,
            retrieved_at_utc=min(current.retrieved_at_utc, item.retrieved_at_utc),
            status=current.status if current.status != "pass" else item.status,
            warning_codes=tuple(dict.fromkeys([*current.warning_codes, *item.warning_codes])),
        )
    return list(aggregated.values())
