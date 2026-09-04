"""The in-season production build: freshness, features, frozen inference, ROS value, tiers.

The rest-of-season counterpart of :mod:`ffdraft.pipeline.current`, and the differences from
it are the whole design:

* **Its cutoff is a week, not a timestamp.** A draft build's information boundary is "now,
  bounded by the season anchor". An in-season build's is "completed week N", and which N is
  not a matter of opinion: :mod:`ffdraft.season.state` says which weeks have been played and
  :mod:`ffdraft.ros.freshness` says which of those have actually been released upstream. The
  build takes the smaller answer and records both.
* **Replacement means something else.** The alternative to holding a player in November is
  the waiver wire, not the next pick, so the allocation fills benches first and replacement
  is the best player nobody *rosters* (ADR-071). That is one argument to the same draw loop
  Release 1 uses; there is not a second simulator.
* **It never trains.** ``build-ros`` loads the artifact ``train-ros-production`` wrote and
  refuses a frame whose feature contract disagrees. A refresh that retrained would serve a
  different model every day, which is what the whole freeze exists to prevent (ADR-078).
* **It publishes what it does not know.** Every row carries the ADR-076 disclosure fields,
  and the build metadata carries the sentences that make them honest — that the model reads
  no injury or practice-report information, that a long absence is an observable fact about
  appearances rather than a status, and that ordering *within* the long-absence cohort is
  measurably weak. The frontend cannot show the flag without them because they travel on the
  artifact.

**Fail-closed, in the same shape as Release 1.** A critical finding means nothing is written,
so a partially refreshed in-season board cannot exist; the previously deployed one stays.
An optional signal (the behaviour feed, the preseason board for the delta column) degrades a
column and never the board.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
from typing import Any

import numpy as np
import polars as pl

from ffdraft.anchors import build_season_anchors
from ffdraft.artifacts import ARTIFACT_SCHEMA_VERSION, write_artifact
from ffdraft.artifacts.serialize import write_json_artifact
from ffdraft.config import AppConfig, LeaguePreset, ScoringPreset, load_app_config
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.features.build import build_feature_table
from ffdraft.features.sources import load_historical_sources
from ffdraft.market.surface import SURFACE_RULE_VERSION, TIER_DEPTH_RULE
from ffdraft.pipeline.current import current_cutoff
from ffdraft.quality import QualityGate
from ffdraft.ros.cutoff import ROS_CUTOFF_RULE_VERSION, RosCutoff
from ffdraft.ros.freshness import assess_ros_freshness
from ffdraft.ros.frozen import (
    ROS_BUILD_CONFIG,
    ROS_MODEL_VERSION,
    RosBuildConfig,
)
from ffdraft.ros.production import RosProductionModel
from ffdraft.ros.snapshot import build_current_ros_snapshot, strip_target_season_statistics
from ffdraft.ros.value import allocate_with_bench
from ffdraft.season.state import (
    SeasonState,
    SeasonStateResolution,
    build_season_calendar,
    resolve_season_state,
)
from ffdraft.simulation.vorp import (
    SimulationConfig,
    fair_ranking,
    sample_points,
    simulate_vorp,
)
from ffdraft.tiers.algorithms import segment_with
from ffdraft.tiers.labels import tier_label
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "ROS_BUILD_METADATA_FILENAME",
    "ROS_METHODOLOGY_VERSION",
    "RosBuildResult",
    "build_ros_board_records",
    "run_ros_build",
]

#: The methodology this build implements end to end: the accepted architecture, the sampler,
#: the in-season allocation, the ranking statistic and the segmentation.
ROS_METHODOLOGY_VERSION = "phase12_ros_v1"

ROS_BUILD_METADATA_FILENAME = "ros_build_metadata.json"
ROS_BUILD_METADATA_SCHEMA = "ros_build_metadata"

#: The long-absence condition, exactly as ADR-076 defines the cohort it discloses.
LONG_ABSENCE_MIN_CONSECUTIVE_WEEKS = 3

#: The sentences that must accompany the flag wherever it is shown (ADR-076 clauses 3-6).
LONG_ABSENCE_DEFINITION = (
    "has played at least once this season and has not appeared for "
    f"{LONG_ABSENCE_MIN_CONSECUTIVE_WEEKS} or more consecutive weeks ending at the cutoff"
)
LONG_ABSENCE_STATEMENT = (
    "This estimate uses no injury or practice-report information of any kind. The model "
    "infers absence from appearances alone, so a player cleared to return this week and a "
    "player out for the season are identical rows that have not appeared for N weeks. "
    '"Has not appeared for N weeks" is what is known; it is not a status or a designation.'
)
LONG_ABSENCE_ORDERING_WEAKNESS = (
    "Ranking quality inside this group is weak. Measured on 18,951 development rows, the "
    "rest-of-season ordering within the long-absence cohort reaches a Spearman correlation "
    "of 0.311 against 0.797 on the full universe, so the order of these players relative to "
    "each other carries little information."
)
TIER_BOUNDARY_STATEMENT = (
    "Rest-of-season tiers are bands, not lines. Membership is highly reproducible (bootstrap "
    "ARI 0.857) and tiers order realised remaining value across every adjacent pair, but the "
    "exact boundary position is not reproducible (agreement 0.167 against a 0.500 bar), so a "
    "player near an edge should be read as belonging to both neighbouring bands."
)

#: The measured limitations the accepted model carries into production (ADR-077). Published
#: with the board rather than filed in a document nobody opens.
ROS_LIMITATIONS: tuple[str, ...] = (
    "Overconfident on high-draft-capital rookies: interval coverage 0.763 against an "
    "attainable 0.898, the tightest clause in the promotion gate.",
    "Close to unable to order players returning from a long absence: Spearman 0.311 against "
    "0.797 on the full universe.",
    "Conservative intervals on players with no remaining games: 14.5 wide against a "
    "climatological 4.5.",
    "The sealed 2025 evaluation season is spent; any change to the model's outputs would "
    "need a fresh one.",
    "Tier boundaries failed the frozen stability gate: a tier is a band, not a line.",
    "There is no injury feature, and the cohort that needs one is measurably the worst.",
    "The simulation draw count is a declared fallback: no count in the frozen ladder met "
    "every convergence tolerance.",
)

_POSITIONS = ("QB", "RB", "WR", "TE")
_QUANTILE_TO_POINTS = {
    "q10": "p10_points",
    "q25": "p25_points",
    "q50": "p50_points",
    "q75": "p75_points",
    "q90": "p90_points",
}


@dataclass
class RosBuildResult:
    """Everything one in-season build produced."""

    season: int
    through_week: int
    build_id: str
    as_of_utc: datetime
    state: SeasonStateResolution
    config: RosBuildConfig
    model_version: str = ROS_MODEL_VERSION
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    full_board: list[dict[str, Any]] = field(default_factory=list)
    gate: QualityGate = field(default_factory=QualityGate)
    written: list[Path] = field(default_factory=list)


def run_ros_build(
    *,
    season: int,
    model_dir: Path,
    out_dir: Path,
    config: RosBuildConfig = ROS_BUILD_CONFIG,
    as_of: datetime | None = None,
    through_week: int | None = None,
    build_id: str | None = None,
    git_sha: str | None = None,
    app: AppConfig | None = None,
    sources: Any | None = None,
    scoring_presets: Sequence[str] | None = None,
    league_preset_ids: Sequence[str] | None = None,
    current_roster: pl.DataFrame | None = None,
    behavior_capture: Any | None = None,
    store: Path | None = None,
    preseason_board: Path | None = None,
    full_board_out: Path | None = None,
    snapshot_out: Path | None = None,
    write: bool = True,
) -> RosBuildResult:
    """Build the current rest-of-season board and write the in-season artifacts.

    ``through_week`` overrides the derived cutoff. It exists so a completed season can be
    replayed deterministically — the only way to exercise this path before a season starts —
    and it is still bounded by the cutoff rule and by what the sources actually contain.
    """
    stamped = (as_of or utc_now()).astimezone(UTC)
    settings = app or load_app_config()
    gate = QualityGate()
    model = RosProductionModel.load(model_dir)
    presets = list(scoring_presets or [str(preset) for preset in sorted(settings.league.scoring)])
    leagues = list(league_preset_ids or sorted(settings.league.presets))

    loaded = sources or load_historical_sources(
        target_seasons=[season],
        as_of=stamped,
        include_target_statistics=True,
    )
    gate.extend(loaded.checks)

    calendar = build_season_calendar(loaded.sources.schedule, season)
    state = resolve_season_state(calendar, stamped)
    freshness = assess_ros_freshness(state=state, weekly_stats=loaded.sources.weekly_stats)
    gate.extend(freshness.checks())

    resolved_week = _resolve_week(
        requested=through_week,
        freshness_week=freshness.available_through_week,
        state=state,
        gate=gate,
    )
    if resolved_week is None:
        return RosBuildResult(
            season=season,
            through_week=0,
            build_id=build_id or "",
            as_of_utc=stamped,
            state=state,
            config=config,
            gate=gate,
        )
    cutoff = RosCutoff(season=season, through_week=resolved_week)

    # The preseason block is built from the season anchor, from sources with this season's
    # own statistics deleted. Mid-season `current_cutoff` returns the anchor unchanged, so
    # the inherited half of an in-season row is exactly the draft board's.
    anchor = build_season_anchors(loaded.sources.schedule, [season])[season]
    preseason_cutoff = current_cutoff(anchor, stamped)
    preseason_sources = strip_target_season_statistics(loaded.sources, season)
    built = build_feature_table(
        preseason_sources,
        config=settings,
        seasons=[season],
        anchors={season: preseason_cutoff},
    )
    gate.extend(built.checks)
    if built.features.is_empty():
        gate.add(
            QualityCheck.fail(
                "ros.empty_preseason_universe",
                stage="ros_build",
                message=f"{season} produced no eligible players at the season anchor",
                observed="0 rows",
                expected="> 0",
            ),
        )
        return RosBuildResult(
            season=season,
            through_week=resolved_week,
            build_id=build_id or "",
            as_of_utc=stamped,
            state=state,
            config=config,
            gate=gate,
        )

    snapshot = build_current_ros_snapshot(
        loaded.sources,
        built.features,
        config=settings,
        cutoff=cutoff,
        positions=_POSITIONS,
        scoring_presets=presets,
    )
    gate.extend(snapshot.checks)
    if snapshot.is_empty:
        gate.add(
            QualityCheck.fail(
                "ros.empty_snapshot",
                stage="ros_build",
                message=f"snapshot {cutoff.snapshot_id} produced no rows",
                observed="0 rows",
                expected="> 0",
            ),
        )
        return RosBuildResult(
            season=season,
            through_week=resolved_week,
            build_id=build_id or "",
            as_of_utc=stamped,
            state=state,
            config=config,
            gate=gate,
        )

    from ffdraft.ros.dictionary import ros_feature_selection

    selection = ros_feature_selection()
    model.assert_compatible(
        feature_set_hash=selection.fingerprint(),
        feature_schema_hash=selection.schema_hash,
    )
    model.assert_serving_season(season)
    gate.add(
        QualityCheck.ok(
            "ros.model_feature_schema",
            stage="ros_build",
            message=(
                "the fitted rest-of-season model's feature contract matches this build's, "
                "and it trained on no season at or after the one it is serving"
            ),
            observed=(
                f"{selection.version} ({selection.fingerprint()}); trained "
                f"{model.fold.train_start_season}-{model.fold.train_end_season}; "
                f"configuration {model.spec.configuration_hash()}"
            ),
        ),
    )

    predictions = model.predict(snapshot.frame)
    if snapshot_out is not None and write:
        snapshot_out.parent.mkdir(parents=True, exist_ok=True)
        snapshot.frame.write_parquet(snapshot_out, compression="zstd")

    resolved_build_id = build_id or _ros_build_id(model.spec.model_version, stamped, cutoff)
    context = _context_columns(snapshot.frame)
    preseason_ranks = _preseason_ranks(preseason_board, gate)

    # Current roster status: annotation only, exactly as it is on the draft board. It is
    # joined after every value exists and cannot reach a feature, a projection or a rank.
    roster = _resolve_roster(
        loaded,
        season,
        override=current_roster,
        allow_fetch=sources is None,
        as_of=stamped,
        gate=gate,
    )
    status_by_player = _status_by_player(roster)

    records, diagnostics, full_board = build_ros_board_records(
        predictions,
        context,
        settings=settings,
        config=config,
        model=model,
        cutoff=cutoff,
        build_id=resolved_build_id,
        league_preset_ids=leagues,
        scoring_presets=presets,
        preseason_ranks=preseason_ranks,
        status_by_player=status_by_player,
        gate=gate,
    )
    if full_board_out is not None and write:
        full_board_out.parent.mkdir(parents=True, exist_ok=True)
        full_board_out.write_text(json.dumps(full_board), encoding="utf-8")

    signals, surface_universes, opportunity_diagnostics = _opportunity(
        records=records.get("ros_tiers", []),
        full_board=full_board,
        snapshot_frame=snapshot.frame,
        status_by_player=status_by_player,
        roster=roster,
        capture=behavior_capture,
        store=store,
        season=season,
        cutoff=cutoff,
        build_id=resolved_build_id,
        as_of=stamped,
        gate=gate,
    )
    records["inseason_opportunity"] = opportunity_diagnostics.pop("records")

    metadata = _ros_metadata(
        settings,
        loaded=loaded,
        gate=gate,
        model=model,
        cutoff=cutoff,
        state=state,
        freshness=freshness,
        config=config,
        build_id=resolved_build_id,
        as_of=stamped,
        git_sha=git_sha,
        records=records.get("ros_tiers", []),
        leagues=leagues,
        signals=signals,
        surface=[universe.to_dict() for universe in surface_universes],
    )

    written: list[Path] = []
    if write and gate.passed:
        written = _publish(
            records=records,
            metadata=metadata,
            out_dir=out_dir,
            build_id=resolved_build_id,
            as_of=stamped,
            gate=gate,
        )

    return RosBuildResult(
        season=season,
        through_week=resolved_week,
        build_id=resolved_build_id,
        as_of_utc=stamped,
        state=state,
        config=config,
        model_version=model.spec.model_version,
        records=records,
        metadata=metadata,
        diagnostics={**snapshot.diagnostics, **diagnostics, "opportunity": opportunity_diagnostics},
        full_board=full_board,
        gate=gate,
        written=written,
    )


def _publish(
    *,
    records: Mapping[str, Sequence[Mapping[str, Any]]],
    metadata: Mapping[str, Any],
    out_dir: Path,
    build_id: str,
    as_of: datetime,
    gate: QualityGate,
) -> list[Path]:
    """Write the in-season bundle, or write none of it.

    Staged into a sibling directory and moved into place only once every artifact **and** the
    metadata have validated. The reason is roadmap 12.5's exit criterion: a failed critical
    input must not deploy a partially updated board. Writing straight into the output would
    satisfy that for the artifacts — the serializer validates before it writes — and miss it
    for the metadata, which would otherwise be written *after* a failed artifact and describe
    a bundle that is not there.

    Each move is a single ``os.replace``, so a reader never sees a half-written file.
    """
    staging = Path(mkdtemp(prefix=".ros-staging-", dir=str(out_dir.parent)))
    try:
        staged: list[Path] = []
        for artifact, rows in sorted(records.items()):
            paths, checks = write_artifact(
                artifact,
                list(rows),
                out_dir=staging,
                build_id=build_id,
                generated_at=as_of,
            )
            gate.extend(checks)
            staged.extend(paths)
        paths, checks = write_json_artifact(
            metadata,
            path=staging / ROS_BUILD_METADATA_FILENAME,
            schema_name=ROS_BUILD_METADATA_SCHEMA,
        )
        gate.extend(checks)
        staged.extend(paths)
        if not gate.passed:
            return []
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for path in staged:
            target = out_dir / path.name
            os.replace(path, target)
            written.append(target)
        return written
    finally:
        rmtree(staging, ignore_errors=True)


def _resolve_week(
    *,
    requested: int | None,
    freshness_week: int,
    state: SeasonStateResolution,
    gate: QualityGate,
) -> int | None:
    """Decide the cutoff, and refuse rather than guess.

    A requested week is honoured only up to what the sources support. Asking for week 9 when
    week 6 is the deepest complete one is a request for a board built from six weeks of data
    and labelled nine, which is the exact failure the freshness gate exists to prevent.
    """
    if state.state is SeasonState.PRESEASON_DRAFT and requested is None:
        gate.add(
            QualityCheck.fail(
                "ros.not_in_season",
                stage="ros_build",
                message=(
                    "the season has not kicked off, so there is no rest-of-season board to "
                    "build; the draft board is the current product"
                ),
                observed=f"season state {state.state}; product mode {state.mode}",
                expected="regular_season or later",
                severity=Severity.WARNING,
            ),
        )
        return None
    if freshness_week < 1:
        return None
    if requested is None:
        return freshness_week
    if requested > freshness_week:
        gate.add(
            QualityCheck.fail(
                "ros.requested_week_unavailable",
                stage="ros_build",
                message=(
                    f"week {requested} was requested but upstream data is complete only "
                    f"through week {freshness_week}; refusing to label a shallower board "
                    "with a deeper cutoff"
                ),
                observed=f"requested {requested}, available {freshness_week}",
                expected=f"<= {freshness_week}",
            ),
        )
        return None
    return requested


def _context_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """The per-player columns the published record needs beside the model's output.

    One row per player and scoring preset, because the disclosure and to-date fields are
    preset-dependent (points) as well as preset-independent (appearances).
    """
    wanted = [
        "player_id",
        "scoring_preset",
        "display_name",
        "position",
        "team_to_date",
        "team_at_anchor",
        "games_to_date",
        "points_to_date",
        "ppg_to_date",
        "weeks_since_last_game",
        "consecutive_weeks_missed",
        "has_played_this_season",
        "in_preseason_universe",
        "remaining_horizon_weeks",
        "team_remaining_scheduled_games",
        "snap_pct_last3",
        "target_share_last3",
        "rookie_flag",
    ]
    present = [name for name in wanted if name in frame.columns]
    selected = frame.select(present)
    if "team_to_date" in present and "team_at_anchor" in present:
        selected = selected.with_columns(
            pl.coalesce(pl.col("team_to_date"), pl.col("team_at_anchor")).alias("team"),
        )
    elif "team_to_date" in present:
        selected = selected.with_columns(pl.col("team_to_date").alias("team"))
    elif "team_at_anchor" in present:
        selected = selected.with_columns(pl.col("team_at_anchor").alias("team"))
    else:
        selected = selected.with_columns(pl.lit(None, dtype=pl.String).alias("team"))
    return selected


def _preseason_ranks(
    board: Path | None,
    gate: QualityGate,
) -> dict[tuple[str, str, str], int]:
    """Preseason fair ranks from the published draft artifact, for the delta column.

    Read from ``tiers.json`` rather than recomputed, so the comparison is against the number
    the site actually shows. Optional: an absent or unreadable draft board removes one
    column and leaves every rest-of-season number untouched.
    """
    if board is None:
        return {}
    if not board.is_file():
        gate.add(
            QualityCheck.fail(
                "ros.preseason_board_absent",
                stage="ros_build",
                message=(
                    "no published preseason board was supplied, so the preseason-to-current "
                    "intrinsic change is not published; every rest-of-season value is "
                    "unaffected"
                ),
                observed=str(board),
                expected="a readable tiers.json",
                severity=Severity.WARNING,
            ),
        )
        return {}
    try:
        payload = json.loads(board.read_text(encoding="utf-8"))
        rows = payload.get("records", ())
    except (OSError, ValueError) as exc:
        gate.add(
            QualityCheck.fail(
                "ros.preseason_board_unreadable",
                stage="ros_build",
                message="the published preseason board could not be read; the delta column "
                "is omitted and the rest-of-season board is unaffected",
                observed=str(exc),
                expected="valid JSON",
                severity=Severity.WARNING,
            ),
        )
        return {}
    return {
        (
            str(row["league_preset_id"]),
            str(row["scoring_preset"]),
            str(row["player_id"]),
        ): int(row["fair_rank"])
        for row in rows
        if row.get("fair_rank") is not None
    }


def _resolve_roster(
    loaded: Any,
    season: int,
    *,
    override: pl.DataFrame | None,
    allow_fetch: bool,
    as_of: datetime,
    gate: QualityGate,
) -> pl.DataFrame:
    """The target season's roster. Annotation and identity only, never a model input.

    The same rule the draft build follows (ADR-011): the build is fetching it *now*, so
    "this is true now" is exactly what it knows. It supplies the status annotation and the
    Sleeper crosswalk the behaviour feed is joined through; it reaches no feature.
    """
    if override is not None:
        return override
    existing: pl.DataFrame | None = loaded.sources.rosters.get(season)
    if existing is not None:
        return existing
    if not allow_fetch:
        gate.add(
            QualityCheck.fail(
                "ros.roster_status_unavailable",
                stage="ros_build",
                message=(
                    "no current roster was supplied, so no row carries a status annotation "
                    "and behaviour rows cannot be joined to canonical players"
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
    return batch.frame


def _status_by_player(roster: pl.DataFrame) -> dict[str, str]:
    """Canonical player id -> current roster status. One string, annotation only."""
    if roster.is_empty() or "gsis_id" not in roster.columns:
        return {}
    scoped = (
        roster.select(
            (pl.lit("gsis:") + pl.col("gsis_id")).alias("player_id"),
            pl.col("status").alias("current_status"),
        )
        .group_by("player_id")
        .agg(pl.col("current_status").first())
    )
    return {
        str(row["player_id"]): str(row["current_status"])
        for row in scoped.iter_rows(named=True)
        if row.get("current_status") is not None
    }


def _opportunity(
    *,
    records: Sequence[Mapping[str, Any]],
    full_board: Sequence[Mapping[str, Any]],
    snapshot_frame: pl.DataFrame,
    status_by_player: Mapping[str, str],
    roster: pl.DataFrame,
    capture: Any | None,
    store: Path | None,
    season: int,
    cutoff: RosCutoff,
    build_id: str,
    as_of: datetime,
    gate: QualityGate,
) -> tuple[Any, list[Any], dict[str, Any]]:
    """Assemble the Opportunity Board. Every failure here degrades a column, not the board."""
    from ffdraft.behavior.capture import BEHAVIOR_PREFIX, read_behavior_capture
    from ffdraft.identity.registry import build_registry
    from ffdraft.opportunity.board import build_opportunity_records, resolve_behavior_signals
    from ffdraft.retention import SnapshotStore

    resolved_capture = capture
    if resolved_capture is None and store is not None:
        try:
            resolved_capture = read_behavior_capture(
                SnapshotStore(root=store, prefix=BEHAVIOR_PREFIX),
                season=season,
            )
        except (OSError, ValueError) as exc:
            gate.add(
                QualityCheck.fail(
                    "ros.behavior_capture_unreadable",
                    stage="ros_build",
                    message=(
                        "the retained behaviour capture could not be read; the Opportunity "
                        "Board degrades to intrinsic value alone and the rest-of-season "
                        "board is unaffected"
                    ),
                    observed=str(exc),
                    expected="a readable capture",
                    severity=Severity.WARNING,
                ),
            )
            resolved_capture = None

    registry = build_registry(roster) if not roster.is_empty() else None
    signals = resolve_behavior_signals(resolved_capture, registry=registry, as_of=as_of)
    context = _opportunity_context(snapshot_frame, status_by_player)
    rows, universes, diagnostics = build_opportunity_records(
        ros_records=records,
        full_board=full_board,
        context=context,
        signals=signals,
        build_id=build_id,
        season=season,
        through_week=cutoff.through_week,
        gate=gate,
    )
    return signals, universes, {**diagnostics, "records": rows}


def _opportunity_context(
    frame: pl.DataFrame,
    status_by_player: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Per-player role and status context, deduplicated across scoring presets.

    Role columns are preset-independent (snaps and targets are the same however points are
    scored), so one row per player is the right shape and picking the first preset's is not
    a choice about which preset matters.
    """
    if frame.is_empty():
        return {}
    wanted = [
        name
        for name in (
            "player_id",
            "games_to_date",
            "weeks_since_last_game",
            "snap_pct_last3",
            "target_share_last3",
        )
        if name in frame.columns
    ]
    context: dict[str, dict[str, Any]] = {}
    for row in frame.select(wanted).unique(subset=["player_id"]).iter_rows(named=True):
        player_id = str(row["player_id"])
        entry: dict[str, Any] = {key: row.get(key) for key in wanted if key != "player_id"}
        status = status_by_player.get(player_id)
        if status is not None:
            entry["current_status"] = status
        context[player_id] = entry
    return context


def build_ros_board_records(
    predictions: pl.DataFrame,
    context: pl.DataFrame,
    *,
    settings: AppConfig,
    config: RosBuildConfig,
    model: RosProductionModel,
    cutoff: RosCutoff,
    build_id: str,
    league_preset_ids: Sequence[str],
    scoring_presets: Sequence[str],
    preseason_ranks: Mapping[tuple[str, str, str], int],
    status_by_player: Mapping[str, str] | None = None,
    gate: QualityGate,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], list[dict[str, Any]]]:
    """Simulate, rank, tier and serialize every scoring x league preset.

    The third return value is the **whole** fair-ranked board for every block, not the
    published prefix. The in-season surface rule needs it for the same reason the draft one
    does: a player cannot be rescued from a board he was already cut from (ADR-063).

    Separated from the fetch-and-feature half so the entire value chain can be driven from a
    synthetic frame in a test, with no source, no model file and no network.
    """
    # `predictions` already carries position and scoring preset, so the context frame is
    # narrowed to what it does not: a duplicate join key produces a `_right` column that the
    # second join below would then produce twice.
    annotations = context.drop("position") if "position" in context.columns else context
    joined = predictions.join(annotations, on=["player_id", "scoring_preset"], how="inner")
    joined = joined.rename({old: new for old, new in _QUANTILE_TO_POINTS.items()})
    point_columns = list(_QUANTILE_TO_POINTS.values())
    bounds_by_preset = model.point_bounds()
    depth = TIER_DEPTH_RULE.depth

    tier_records: list[dict[str, Any]] = []
    full_board: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {"presets": [], "replacement": []}

    for scoring in scoring_presets:
        block = joined.filter(pl.col("scoring_preset") == scoring).sort("player_id")
        if block.is_empty():
            continue
        simulation_config = SimulationConfig(
            draws=config.draws,
            seed=config.seed,
            model_version=model.spec.model_version,
            scoring_preset=scoring,
            build_id=build_id,
        )
        bounds = bounds_by_preset.get(scoring, {})
        projections = block.select("player_id", "position", *point_columns)
        points = sample_points(
            projections,
            config=simulation_config,
            bounds=bounds,
            quantile_columns=point_columns,
        )
        for preset_id in league_preset_ids:
            preset = settings.league.preset(preset_id)
            result = simulate_vorp(
                projections,
                preset=preset,
                config=simulation_config,
                bounds=bounds,
                points=points,
                allocate=allocate_with_bench,
            )
            valued = result.players.filter(pl.col("expected_vorp").is_not_null())
            withheld = result.players.height - valued.height
            if withheld:
                gate.add(
                    QualityCheck.fail(
                        "ros.unvalued_players_withheld",
                        stage="ros_build",
                        message=(
                            f"{preset_id}/{scoring}: {withheld} player(s) had no replacement "
                            "baseline in any draw and are not published"
                        ),
                        observed=f"{withheld} of {result.players.height}",
                        severity=Severity.WARNING,
                    ),
                )
            # The simulation result already carries position, the point quantiles and the
            # value distribution; only the annotation columns are joined back on, so the
            # published row has exactly one source for every number.
            carried = [
                name for name in block.columns if name == "player_id" or name not in valued.columns
            ]
            board = fair_ranking(
                valued.join(block.select(carried), on="player_id", how="inner"),
                statistic=config.ranking_statistic,
            )
            full_board.extend(
                {
                    "player_id": str(row["player_id"]),
                    "fair_rank": int(row["fair_rank"]),
                    "display_name": row.get("display_name"),
                    "position": str(row.get("position") or ""),
                    "team": row.get("team"),
                    "scoring_preset": scoring,
                    "league_preset_id": preset_id,
                }
                for row in board.iter_rows(named=True)
            )
            published = board.head(depth)
            segmentation = segment_with(
                config.tier_algorithm,
                published,
                penalty=config.tier_penalty,
            )
            tier_records.extend(
                _ros_tier_records(
                    published,
                    segmentation.ordinals,
                    build_id=build_id,
                    preset=preset,
                    scoring=scoring,
                    cutoff=cutoff,
                    preseason_ranks=preseason_ranks,
                    status_by_player=status_by_player or {},
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
                    "rule": config.replacement_rule,
                    "replacement": result.replacement,
                    "unfilled_slots": dict(result.unfilled_slots),
                },
            )
    if config.tier_stability_verdict != "pass":
        gate.add(
            QualityCheck.fail(
                "ros.tier_stability",
                stage="ros_build",
                message=(
                    "rest-of-season tiers are published having failed the frozen tier "
                    "stability gate; read a tier as a band of comparable players, not as a "
                    "line - membership is reproducible but boundary positions are not "
                    "(ADR-074)"
                ),
                observed=(
                    f"{config.tier_algorithm} @ penalty {config.tier_penalty}: "
                    f"stability gate {config.tier_stability_verdict}"
                ),
                severity=Severity.WARNING,
            ),
        )
    if config.convergence_verdict != "pass":
        gate.add(
            QualityCheck.fail(
                "ros.simulation_convergence",
                stage="ros_build",
                message=(
                    f"the simulation runs at {config.draws} draws, which is the declared "
                    "fallback rather than a converged count: no count in the frozen ladder "
                    "met every tolerance, and what failed to converge is the tier partition "
                    "(ADR-074)"
                ),
                observed=f"draws={config.draws}; convergence gate {config.convergence_verdict}",
                severity=Severity.WARNING,
            ),
        )
    return {"ros_tiers": tier_records}, diagnostics, full_board


def _ros_tier_records(
    board: pl.DataFrame,
    ordinals: Sequence[int],
    *,
    build_id: str,
    preset: LeaguePreset,
    scoring: str,
    cutoff: RosCutoff,
    preseason_ranks: Mapping[tuple[str, str, str], int],
    status_by_player: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, row in zip(ordinals, board.iter_rows(named=True), strict=True):
        player_id = str(row["player_id"])
        preseason = preseason_ranks.get((preset.preset_id, str(ScoringPreset(scoring)), player_id))
        ros_rank = int(row["fair_rank"])
        weeks_since = _number(row.get("weeks_since_last_game"))
        consecutive = _number(row.get("consecutive_weeks_missed"))
        played = bool(row.get("has_played_this_season"))
        rows.append(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "build_id": build_id,
                "season": cutoff.season,
                "through_week": cutoff.through_week,
                "league_preset_id": preset.preset_id,
                "scoring_preset": str(ScoringPreset(scoring)),
                "player_id": player_id,
                "display_name": str(row["display_name"]),
                "team": row.get("team"),
                "position": str(row["position"]),
                "ros_fair_rank": ros_rank,
                "ros_position_rank": int(row["position_rank"]),
                "ros_tier": int(ordinal),
                "ros_tier_label": tier_label(int(ordinal)),
                "ros_expected_vorp": round(float(row["expected_vorp"]), 4),
                "ros_vorp_p10": round(float(row["p10_vorp"]), 4),
                "ros_vorp_p25": round(float(row["p25_vorp"]), 4),
                "ros_vorp_p50": round(float(row["p50_vorp"]), 4),
                "ros_vorp_p75": round(float(row["p75_vorp"]), 4),
                "ros_vorp_p90": round(float(row["p90_vorp"]), 4),
                "ros_expected_points": round(float(row["expected_points"]), 4),
                "ros_points_p10": round(float(row["p10_points"]), 4),
                "ros_points_p50": round(float(row["p50_points"]), 4),
                "ros_points_p90": round(float(row["p90_points"]), 4),
                "ros_expected_games": round(float(row.get("expected_remaining_games") or 0.0), 4),
                "ros_uncertainty": round(float(row["uncertainty"]), 4),
                "remaining_horizon_weeks": int(cutoff.remaining_horizon_weeks),
                "team_remaining_scheduled_games": _number(
                    row.get("team_remaining_scheduled_games"),
                ),
                "preseason_fair_rank": preseason,
                "fair_rank_change": None if preseason is None else preseason - ros_rank,
                "games_played_to_date": _number(row.get("games_to_date")) or 0.0,
                "points_to_date": round(float(row.get("points_to_date") or 0.0), 4),
                "points_per_game_to_date": _rounded(row.get("ppg_to_date")),
                "weeks_since_last_game": weeks_since or 0.0,
                "consecutive_weeks_missed": consecutive or 0.0,
                "has_played_this_season": played,
                # ADR-076 clause 1, stated on exactly the condition the cohort is defined by.
                "long_absence": played
                and (consecutive or 0.0) >= LONG_ABSENCE_MIN_CONSECUTIVE_WEEKS,
                "in_preseason_universe": bool(row.get("in_preseason_universe")),
                "current_status": status_by_player.get(player_id),
                "outside_tier_board": False,
                "surface_reasons": ["intrinsic_top_tier_depth"],
                "quality_flags": _ros_quality_flags(row),
            },
        )
    return rows


def _ros_quality_flags(row: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    if not row.get("has_played_this_season"):
        flags.append("no_appearances_this_season")
    if not row.get("in_preseason_universe"):
        flags.append("in_season_arrival")
    if row.get("rookie_flag"):
        flags.append("rookie")
    consecutive = _number(row.get("consecutive_weeks_missed")) or 0.0
    if row.get("has_played_this_season") and consecutive >= LONG_ABSENCE_MIN_CONSECUTIVE_WEEKS:
        flags.append("long_absence")
    return sorted(set(flags))


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(number) else number


def _rounded(value: Any) -> float | None:
    number = _number(value)
    return None if number is None else round(number, 4)


def _ros_build_id(model_version: str, as_of: datetime, cutoff: RosCutoff) -> str:
    return (
        f"{cutoff.season}w{cutoff.through_week:02d}-{model_version}-"
        f"{as_of.strftime('%Y%m%dT%H%M%SZ')}"
    )


def _ros_metadata(
    settings: AppConfig,
    *,
    loaded: Any,
    gate: QualityGate,
    model: RosProductionModel,
    cutoff: RosCutoff,
    state: SeasonStateResolution,
    freshness: Any,
    config: RosBuildConfig,
    build_id: str,
    as_of: datetime,
    git_sha: str | None,
    records: Sequence[Mapping[str, Any]],
    leagues: Sequence[str],
    signals: Any | None = None,
    surface: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from ffdraft.pipeline.current import _source_metadata

    summary = gate.summary()
    long_absence = sum(1 for record in records if record.get("long_absence"))
    freshness_payload = freshness.to_dict()
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "build_id": build_id,
        "generated_at_utc": isoformat_utc(as_of),
        "git_sha": git_sha or "0000000",
        "season": cutoff.season,
        "through_week": cutoff.through_week,
        "season_state": {
            "rule_version": state.rule_version,
            "season_state": str(state.state),
            "product_mode": str(state.mode),
            "completed_week": state.completed_week,
            "latest_snapshot_week": state.latest_snapshot_week,
            "next_transition_utc": (
                isoformat_utc(state.next_transition_utc) if state.next_transition_utc else None
            ),
        },
        "ros_model_version": model.spec.model_version,
        "ros_model_configuration_hash": model.spec.configuration_hash(),
        "production_fit_rule_version": model.metadata()["production_fit_rule_version"],
        "model_fitted_at_utc": model.generated_at_utc or None,
        "model_training_seasons": list(model.training_seasons),
        "model_refit_reason": model.refit_reason or None,
        "cutoff_rule_version": ROS_CUTOFF_RULE_VERSION,
        "feature_set_version": model.feature_set_version,
        "feature_set_hash": model.feature_set_hash,
        "methodology_version": ROS_METHODOLOGY_VERSION,
        "simulation": {**config.to_dict(), "tier_depth": TIER_DEPTH_RULE.depth},
        "source_freshness": {
            key: value for key, value in freshness_payload.items() if key != "weeks"
        },
        "behavior": signals.to_dict() if signals is not None else None,
        "surface": (
            {
                "rule_version": SURFACE_RULE_VERSION,
                "tier_depth": TIER_DEPTH_RULE.depth,
                "blocks": list(surface),
            }
            if surface is not None
            else None
        ),
        "disclosures": {
            "uses_injury_information": False,
            "long_absence_definition": LONG_ABSENCE_DEFINITION,
            "long_absence_statement": LONG_ABSENCE_STATEMENT,
            "long_absence_ordering_weakness": LONG_ABSENCE_ORDERING_WEAKNESS,
            "status_is_annotation_only": True,
            "long_absence_players": long_absence,
            "tier_boundary_statement": TIER_BOUNDARY_STATEMENT,
        },
        "limitations": list(ROS_LIMITATIONS),
        "supported_presets": sorted(leagues),
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
    }
