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
from ffdraft.ros.cutoff import FIRST_THROUGH_WEEK, ROS_CUTOFF_RULE_VERSION, RosCutoff
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
from ffdraft.sources.nflverse_http import nflverse_loaders
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
    weekly_model_dir: Path | None = None,
    injuries: pl.DataFrame | None = None,
    forecast_rows: Sequence[Mapping[str, Any]] | None = None,
    shadow_out: Path | None = None,
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

    # Current roster status: annotation only, exactly as it is on the draft board. It is
    # joined after every value exists and cannot reach a feature, a projection or a rank.
    # Resolved before the annotation columns because it is also where a name and a team come
    # from for a player the snapshot cannot name (ADR-097).
    roster = _resolve_roster(
        loaded,
        season,
        override=current_roster,
        allow_fetch=sources is None,
        as_of=stamped,
        gate=gate,
    )
    status_by_player = _status_by_player(roster)
    context = fill_published_identity(
        _context_columns(snapshot.frame),
        weekly=loaded.sources.weekly_stats,
        roster=roster,
        player_master=loaded.sources.player_master,
        season=season,
        gate=gate,
    )
    preseason_ranks = _preseason_ranks(preseason_board, gate)

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

    # The retained behaviour window, published for the first time (ADR-089). Strictly after
    # the Opportunity Board exists, because the series is restricted to the players that
    # board publishes — a history for a player no card can open is bytes for nothing. It
    # reads the same store the board just read and cannot change a value on it: the board's
    # counts come from `resolve_behavior_signals` reading the newest capture, and nothing
    # below touches that object.
    history, series_records = _behavior_series(
        opportunity_records=records["inseason_opportunity"],
        roster=roster,
        store=store,
        season=season,
        cutoff=cutoff,
        build_id=resolved_build_id,
        as_of=stamped,
        gate=gate,
    )
    if series_records:
        records["behavior_trend_series"] = series_records

    # The in-season signal layer (ADR-091): observed role week by week, and each team's next
    # game. Strictly after every board exists and reading none of them beyond which players
    # to describe, so nothing below can move a published value — and, like the series above,
    # an enrichment whose failure costs its own artifacts and nothing else.
    usage_records, matchup_records, signal_summary = _signal_layer(
        opportunity_records=records["inseason_opportunity"],
        loaded=loaded,
        roster=roster,
        settings=settings,
        season=season,
        cutoff=cutoff,
        build_id=resolved_build_id,
        as_of=stamped,
        gate=gate,
    )
    if usage_records:
        records["player_usage"] = usage_records
    if matchup_records:
        records["team_matchups"] = matchup_records

    # The weekly start/sit layer (ADR-096): the next game as a distribution, from the same
    # snapshot the board was valued from. A decision-layer model — it reads the sportsbook
    # environment the boards may not — and, like every enrichment after the boards, one
    # whose failure costs its own artifact and nothing else.
    weekly_records, weekly_summary = _weekly_layer(
        model_dir=weekly_model_dir,
        snapshot_frame=snapshot.frame,
        opportunity_records=records["inseason_opportunity"],
        roster=roster,
        loaded=loaded,
        settings=settings,
        season=season,
        cutoff=cutoff,
        build_id=resolved_build_id,
        as_of=stamped,
        gate=gate,
        injuries=injuries,
        allow_fetch=sources is None,
        store=store,
        forecast_rows=forecast_rows,
        shadow_out=shadow_out if write else None,
        git_sha=git_sha,
    )
    if weekly_records:
        records["weekly_projections"] = weekly_records
        context_records = weekly_summary.pop("_context_records", []) if weekly_summary else []
        if context_records:
            records["weekly_context"] = context_records

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
        history=history,
        surface=[universe.to_dict() for universe in surface_universes],
        signal_layer=signal_summary,
        weekly=weekly_summary,
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

    Two of the three refusals here are lifecycle states rather than faults — before the first
    kickoff, and after the last scored week — and both are warnings, so a scheduled refresh
    in either window is green and the draft build deploys as usual.
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
    # The other end of the season. Once the horizon is spent, `available_through_week` is the
    # *last scored week*, and `RosCutoff` refuses it — correctly, because no remaining horizon
    # is left to estimate. Reaching the constructor with it raises an uncaught `ValueError`,
    # so every scheduled refresh from the end of the season onwards would crash rather than
    # do nothing. The last valid board is the final one; a week-of-zeros board published to
    # keep a tab populated would be a fiction.
    #
    # A *requested* week is exempt from both lifecycle refusals, and that exemption is what
    # makes a finished season replayable: `--through-week 8` on 2024 is the only way to
    # exercise this path before a season of one's own has started.
    last_modelled = state.calendar.horizon.last_week - 1
    if requested is None and state.state is SeasonState.SEASON_COMPLETE:
        gate.add(
            QualityCheck.fail(
                "ros.season_complete",
                stage="ros_build",
                message=(
                    "every scored week has been played, so no rest-of-season quantity "
                    "remains to estimate; the last published board is the final one and "
                    "nothing is rebuilt"
                ),
                observed=(
                    f"completed week {state.completed_week}; last scored week "
                    f"{state.calendar.horizon.last_week}"
                ),
                expected=f"<= week {last_modelled}",
                severity=Severity.WARNING,
            ),
        )
        return None

    ceiling = min(freshness_week, last_modelled)
    if ceiling < FIRST_THROUGH_WEEK:
        return None
    if requested is None:
        return ceiling
    if requested > ceiling:
        gate.add(
            QualityCheck.fail(
                "ros.requested_week_unavailable",
                stage="ros_build",
                message=(
                    f"week {requested} was requested but the deepest snapshot this season "
                    f"supports is week {ceiling}; refusing to label a shallower board with a "
                    "deeper cutoff"
                ),
                observed=(
                    f"requested {requested}; available through {freshness_week}; "
                    f"last modelled week {last_modelled}"
                ),
                expected=f"<= {ceiling}",
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


def fill_published_identity(
    context: pl.DataFrame,
    *,
    weekly: pl.DataFrame,
    roster: pl.DataFrame,
    player_master: pl.DataFrame,
    season: int,
    gate: QualityGate,
) -> pl.DataFrame:
    """Give every published row a real name and, where one is known, a team (ADR-097).

    **Annotation only.** ``context`` is the frame of columns printed *beside* the model's
    output; the model read ``snapshot.frame`` before this runs, so nothing here can reach a
    feature, a projection, a VORP or a rank. ``team_remaining_scheduled_games`` — the one
    team-derived model input — is untouched, and stays null for a player the snapshot could
    not place, exactly as it was in every training season.

    Two gaps, measured on the 2026 week-3 build:

    * **name** — an in-season arrival has no preseason block, so no preseason name, and the
      board printed ``str(None)``: four players, 32 rows, as ``"None"``. Filled from his own
      weekly rows this season, then the current roster, then nflverse's player master.
    * **team** — ``team_to_date`` is the last team he *played* for, so a player who has not
      appeared had none: 69 rows per preset, 17 of them on an active roster. Filled from the
      current roster when it places him on exactly one club, the same rule the usage layer
      already uses (:func:`ffdraft.signals.usage.current_teams_from_roster`).
    """
    from ffdraft.signals.usage import current_teams_from_roster

    if context.is_empty():
        return context
    names: dict[str, str] = {}
    for frame, column in (
        (player_master, "display_name"),
        (roster, "display_name"),
    ):
        if frame.is_empty() or "gsis_id" not in frame.columns or column not in frame.columns:
            continue
        for row in frame.select("gsis_id", column).iter_rows():
            if row[0] and row[1]:
                names[f"gsis:{row[0]}"] = str(row[1])
    if not weekly.is_empty() and "display_name" in weekly.columns:
        latest = (
            weekly.filter((pl.col("season") == season) & pl.col("display_name").is_not_null())
            .sort("week")
            .group_by("gsis_id")
            .agg(pl.col("display_name").last())
        )
        for gsis, name in latest.iter_rows():
            names[f"gsis:{gsis}"] = str(name)
    teams = current_teams_from_roster(roster)

    had_name = context.get_column("display_name").is_not_null()
    had_team = context.get_column("team").is_not_null()
    filled = context.with_columns(
        pl.coalesce(
            pl.col("display_name"),
            pl.col("player_id").replace_strict(names, default=None, return_dtype=pl.String),
            pl.col("player_id"),
        ).alias("display_name"),
        pl.coalesce(
            pl.col("team"),
            pl.col("player_id").replace_strict(teams, default=None, return_dtype=pl.String),
        ).alias("team"),
    )
    named = int(
        (~had_name & (filled.get_column("display_name") != filled.get_column("player_id"))).sum()
    )
    unnamed = int((~had_name).sum()) - named
    placed = int((~had_team & filled.get_column("team").is_not_null()).sum())
    gate.add(
        QualityCheck.ok(
            "ros.published_identity",
            stage="ros_build",
            message=(
                "names and teams missing from the snapshot were filled from this season's "
                "weekly rows, the current roster and the player master; annotation only"
            ),
            observed=(
                f"{named} name(s) filled, {unnamed} left as the player id; "
                f"{placed} team(s) filled from the roster"
            ),
        ),
    )
    return filled


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

    nflreadpy = nflverse_loaders()

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


def _behavior_series(
    *,
    opportunity_records: Sequence[Mapping[str, Any]],
    roster: pl.DataFrame,
    store: Path | None,
    season: int,
    cutoff: RosCutoff,
    build_id: str,
    as_of: datetime,
    gate: QualityGate,
) -> tuple[Any | None, list[dict[str, Any]]]:
    """Read the retained behaviour window and shape it into the published series (ADR-089).

    **Every failure here costs a sparkline and nothing else.** The series is an enrichment of
    an enrichment: the behaviour feed is already optional by construction (ADR-079), and a
    history over it is optional again. An unreadable store, an empty window or a registry
    that cannot be built all produce a warning and no artifact, and the two in-season boards
    are published exactly as they would have been.

    The one thing this must never do is move a number the Opportunity Board published, which
    is why it takes that board's records as *input* rather than sharing its computation: the
    only thing it reads from them is which players exist.
    """
    from ffdraft.artifacts.schemas import record_schema_version
    from ffdraft.behavior.history import build_behavior_history, load_behavior_window
    from ffdraft.behavior.trend import BEHAVIOR_TREND_RULE, behavior_series_records
    from ffdraft.identity.registry import build_registry

    if store is None or roster.is_empty():
        return None, []

    try:
        captures = load_behavior_window(store, season=season, now=as_of)
    except (OSError, ValueError) as exc:
        gate.add(
            QualityCheck.fail(
                "ros.behavior_history_unreadable",
                stage="ros_build",
                message=(
                    "the retained behaviour window could not be read; the momentum series "
                    "is withheld and every published board and count is unaffected"
                ),
                observed=str(exc),
                expected="a readable behaviour store",
                severity=Severity.WARNING,
            ),
        )
        return None, []

    history = build_behavior_history(captures, registry=build_registry(roster), now=as_of)
    if history.is_empty:
        gate.add(
            QualityCheck.fail(
                "ros.behavior_history_empty",
                stage="ros_build",
                message=(
                    "no retained behaviour observation falls inside the trend window, so no "
                    "momentum series is published; the boards are unaffected"
                ),
                observed=f"{len(captures)} capture(s) in the window",
                expected="at least one resolved observation",
                severity=Severity.WARNING,
            ),
        )
        return history, []

    published = {str(record.get("player_id")) for record in opportunity_records}
    records = behavior_series_records(
        history.observations,
        trends=history.trends,
        build_id=build_id,
        season=season,
        through_week=cutoff.through_week,
        behavior_source_id=history.source_id,
        lookback_hours=history.lookback_hours,
        request_limit=history.request_limit,
        window_days=BEHAVIOR_TREND_RULE.window_days,
        schema_version=record_schema_version("behavior_trend_series"),
        players=published,
    )
    single = sum(1 for record in records if record.get("add_trend") is None)
    gate.add(
        QualityCheck.ok(
            "ros.behavior_history_published",
            stage="ros_build",
            message=(
                f"{BEHAVIOR_TREND_RULE.version}: a direction is stated from "
                f"{BEHAVIOR_TREND_RULE.min_observations} observations and every record "
                "carries the span it was measured over"
            ),
            observed=(
                f"{len(records)} series over {history.snapshots_in_window} retained "
                f"snapshot(s); {single} with one observation and no direction"
            ),
        ),
    )
    return history, records


def _signal_layer(
    *,
    opportunity_records: Sequence[Mapping[str, Any]],
    loaded: Any,
    roster: pl.DataFrame,
    settings: AppConfig,
    season: int,
    cutoff: RosCutoff,
    build_id: str,
    as_of: datetime,
    gate: QualityGate,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """Build ``player_usage`` and ``team_matchups`` (ADR-091), or explain why not.

    **Every failure here costs the evidence blocks and nothing else.** Both artifacts are
    observed context beside a board that is already complete; a defect in either must not
    take a correct rest-of-season board down with it. So a failure is a warning naming what
    was withheld, and the boards publish exactly as they would have.

    The only thing read from the published boards is *which players exist*: the usage
    records describe the Opportunity Board's players, so every card that can be opened has
    one and none exists for a card nobody can open.
    """
    from ffdraft.artifacts.schemas import record_schema_version
    from ffdraft.ros.dataset import bridged_snap_counts
    from ffdraft.signals import (
        EXPECTED_POINTS_STATEMENT,
        MATCHUP_RULE_VERSION,
        SPORTSBOOK_CONTEXT_STATEMENT,
        USAGE_RULE,
        build_player_usage_records,
        build_team_matchup_records,
        current_teams_from_roster,
    )
    from ffdraft.sources.nflverse import NFLVERSE_SOURCE_ID

    players: dict[str, dict[str, Any]] = {}
    for record in opportunity_records:
        players.setdefault(
            str(record["player_id"]),
            {"display_name": record.get("display_name"), "position": record.get("position")},
        )
    sources = loaded.sources
    lines_retrieved_at = next(
        (
            item.retrieved_at_utc
            for item in getattr(loaded, "metadata", ())
            if getattr(item, "resource", "") == "load_schedules"
        ),
        as_of,
    )

    try:
        usage = build_player_usage_records(
            players=players,
            weekly=sources.weekly_stats,
            snap_counts=bridged_snap_counts(sources),
            schedule=sources.schedule,
            scoring=settings.league.scoring,
            season=season,
            through_week=cutoff.through_week,
            build_id=build_id,
            schema_version=record_schema_version("player_usage"),
            current_teams=current_teams_from_roster(roster),
        )
    except Exception as exc:  # noqa: BLE001 - an enrichment; its failure must not cost a board
        usage = []
        gate.add(
            QualityCheck.fail(
                "ros.player_usage_failed",
                stage="ros_build",
                message=(
                    "the observed-role series could not be built, so player_usage.json is "
                    "withheld; every board, count and value is unaffected"
                ),
                observed=f"{type(exc).__name__}: {exc}",
                expected="a usage record per Opportunity Board player",
                severity=Severity.WARNING,
            ),
        )
    try:
        matchups = build_team_matchup_records(
            schedule=sources.schedule,
            season=season,
            through_week=cutoff.through_week,
            as_of=as_of,
            build_id=build_id,
            schema_version=record_schema_version("team_matchup"),
            lines_source_id=NFLVERSE_SOURCE_ID,
            lines_retrieved_at=lines_retrieved_at,
        )
    except Exception as exc:  # noqa: BLE001 - an enrichment; its failure must not cost a board
        matchups = []
        gate.add(
            QualityCheck.fail(
                "ros.team_matchups_failed",
                stage="ros_build",
                message=(
                    "the next-game context could not be built, so team_matchups.json is "
                    "withheld; every board, count and value is unaffected"
                ),
                observed=f"{type(exc).__name__}: {exc}",
                expected="a next-game record per team with one left",
                severity=Severity.WARNING,
            ),
        )

    lined = [record for record in matchups if record.get("total_line") is not None]
    changes = sum(
        1 for record in usage if any(value is not None for value in record["role_changes"].values())
    )
    gate.add(
        QualityCheck.ok(
            "ros.signal_layer",
            stage="ros_build",
            message=(
                f"{USAGE_RULE.version} and {MATCHUP_RULE_VERSION}: observed role and next-game "
                "context published beside the boards; no model reads either"
            ),
            observed=(
                f"{len(usage)} usage record(s), {changes} with a role change; "
                f"{len(matchups)} next game(s), {len(lined)} with posted lines"
            ),
        ),
    )
    if not usage and not matchups:
        return usage, matchups, None
    return (
        usage,
        matchups,
        {
            "usage_rule": USAGE_RULE.to_dict(),
            "usage_records": len(usage),
            "matchup_rule_version": MATCHUP_RULE_VERSION,
            "matchup_records": len(matchups),
            "lines_source_id": NFLVERSE_SOURCE_ID if lined else None,
            "lines_retrieved_at_utc": (
                isoformat_utc(lines_retrieved_at) if lined and lines_retrieved_at else None
            ),
            "lines_posted_teams": len(lined),
            "sportsbook_context_statement": SPORTSBOOK_CONTEXT_STATEMENT,
            "expected_points_statement": EXPECTED_POINTS_STATEMENT,
        },
    )


#: The default location of the promoted weekly artifact, relative to the repository.
DEFAULT_WEEKLY_MODEL_DIR = Path("models/production/weekly-startsit-v1")


def _weekly_layer(
    *,
    model_dir: Path | None,
    snapshot_frame: pl.DataFrame,
    opportunity_records: Sequence[Mapping[str, Any]],
    roster: pl.DataFrame,
    loaded: Any,
    settings: AppConfig,
    season: int,
    cutoff: RosCutoff,
    build_id: str,
    as_of: datetime,
    gate: QualityGate,
    injuries: pl.DataFrame | None,
    allow_fetch: bool,
    store: Path | None = None,
    forecast_rows: Sequence[Mapping[str, Any]] | None = None,
    shadow_out: Path | None = None,
    git_sha: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Build ``weekly_projections`` (ADR-096) and ``weekly_context`` (ADR-099), or explain why
    not. Never costs a board. The context records ride in the summary under
    ``_context_records`` and are withheld together with the projections."""
    from ffdraft.artifacts.schemas import record_schema_version
    from ffdraft.paths import repo_root
    from ffdraft.signals.usage import current_teams_from_roster
    from ffdraft.weekly.model import WeeklyModel
    from ffdraft.weekly.serve import build_weekly_projection_records

    resolved = model_dir or (repo_root() / DEFAULT_WEEKLY_MODEL_DIR)
    if not (resolved / "metadata.json").is_file():
        gate.add(
            QualityCheck.fail(
                "ros.weekly_model_absent",
                stage="ros_build",
                message=(
                    "no promoted weekly start/sit model is on disk, so weekly_projections.json "
                    "is not published; every board is unaffected"
                ),
                observed=str(resolved),
                expected="models/production/weekly-startsit-v1/metadata.json",
                severity=Severity.WARNING,
            ),
        )
        return [], None
    try:
        model = WeeklyModel.load(resolved)
        players = {
            str(record["player_id"]): {
                "display_name": record.get("display_name"),
                "position": record.get("position"),
            }
            for record in opportunity_records
        }
        reports, reports_at, report_frame = _injury_reports(
            injuries,
            season=season,
            week=cutoff.through_week + 1,
            allow_fetch=allow_fetch,
            as_of=as_of,
            gate=gate,
        )
        result = build_weekly_projection_records(
            model=model,
            snapshot=snapshot_frame,
            players=players,
            current_teams=current_teams_from_roster(roster),
            weekly=loaded.sources.weekly_stats,
            schedule=loaded.sources.schedule,
            scoring=settings.league.scoring,
            season=season,
            through_week=cutoff.through_week,
            as_of=as_of,
            build_id=build_id,
            schema_version=record_schema_version("weekly_projection"),
            injury_reports=reports,
        )
    except Exception as exc:  # noqa: BLE001 - an enrichment; its failure must not cost a board
        gate.add(
            QualityCheck.fail(
                "ros.weekly_projections_failed",
                stage="ros_build",
                message=(
                    "the weekly start/sit projections could not be built, so "
                    "weekly_projections.json is withheld; every board is unaffected"
                ),
                observed=f"{type(exc).__name__}: {exc}",
                severity=Severity.WARNING,
            ),
        )
        return [], None

    summary = result.summary
    # The pre-deploy validator's own weekly rules, run here so that a record the validator
    # would refuse withholds this artifact with a warning instead of failing the whole deploy
    # at `validate-artifacts` (found on the live 2026 week-4 build, ADR-096).
    from ffdraft.artifacts.validate import weekly_record_checks
    from ffdraft.contracts.quality import critical_failures

    refused = critical_failures(weekly_record_checks(result.records, "ros_build"))
    if refused:
        gate.add(
            QualityCheck.fail(
                "ros.weekly_projections_invalid",
                stage="ros_build",
                message=(
                    "the weekly start/sit records fail the artifact validator's own rules, so "
                    "weekly_projections.json is withheld; every board is unaffected"
                ),
                observed="; ".join(f"{check.check_id}: {check.observed}" for check in refused)[
                    :600
                ],
                severity=Severity.WARNING,
            ),
        )
        return [], None
    if not result.records:
        gate.add(
            QualityCheck.fail(
                "ros.weekly_projections_empty",
                stage="ros_build",
                message="no weekly projection could be built for the week after the cutoff",
                observed=str(summary.get("reason")),
                severity=Severity.WARNING,
            ),
        )
        return [], None
    context_records, context_summary = _weekly_context_layer(
        loaded=loaded,
        season=season,
        cutoff=cutoff,
        as_of=as_of,
        build_id=build_id,
        gate=gate,
        report_frame=report_frame,
        store=store,
        forecast_rows=forecast_rows,
    )
    shadow_summary = _weekly_shadow(
        result=result,
        loaded=loaded,
        season=season,
        cutoff=cutoff,
        as_of=as_of,
        build_id=build_id,
        git_sha=git_sha,
        gate=gate,
        report_frame=report_frame,
        store=store,
        forecast_rows=forecast_rows,
        shadow_out=shadow_out,
    )
    gate.add(
        QualityCheck.ok(
            "ros.weekly_projections",
            stage="ros_build",
            message=(
                f"{model.spec.model_version}: week {summary['target_week']} distributions "
                "published; the model reads the game's sportsbook lines and no board reads it"
            ),
            observed=(
                f"{summary['records']} record(s): {summary['upcoming']} upcoming, "
                f"{summary['kicked_off']} kicked off, {summary['bye']} on bye, "
                f"{summary.get('lines_pending', 0)} awaiting a posted line; "
                f"{summary['injury_reports_matched']} with an injury report"
            ),
        ),
    )
    metadata = weekly_metadata(
        model,
        summary,
        through_week=cutoff.through_week,
        injuries_retrieved_at=reports_at,
        context=context_summary,
    )
    metadata["_context_records"] = context_records
    metadata["shadow"] = shadow_summary
    return result.records, metadata


def _weekly_shadow(
    *,
    result: Any,
    loaded: Any,
    season: int,
    cutoff: RosCutoff,
    as_of: datetime,
    build_id: str,
    git_sha: str | None,
    gate: QualityGate,
    report_frame: pl.DataFrame | None,
    store: Path | None,
    forecast_rows: Sequence[Mapping[str, Any]] | None,
    shadow_out: Path | None,
) -> dict[str, Any]:
    """The private shadow record (ADR-099): written beside the build, never published.

    Its summary is public (``ros_build_metadata.weekly.shadow``) so a reader can see that a
    candidate is under prospective evaluation and how much evidence it has; the rows are not.
    """
    from ffdraft.paths import repo_root
    from ffdraft.ros.dataset import bridged_snap_counts
    from ffdraft.weekly.frozen_v2 import WEEKLY_V2_MODEL_VERSION
    from ffdraft.weekly.shadow import (
        DEFAULT_V2_MODEL_DIR,
        attach_serving_v2_inputs,
        build_shadow_rows,
        load_v2_model,
        summarise,
    )
    from ffdraft.weekly.venues import load_venue_registry

    summary: dict[str, Any] = {
        "model_version": WEEKLY_V2_MODEL_VERSION,
        "status": "absent",
        "rows": 0,
    }
    if result.frame is None or result.quantiles is None or result.frame.is_empty():
        return summary
    try:
        v2 = load_v2_model(repo_root() / DEFAULT_V2_MODEL_DIR)
        forecasts, forecast_meta = _forecast_readings(
            season=season,
            as_of=as_of,
            store=store,
            forecast_rows=forecast_rows,
            gate=QualityGate(),
        )
        frame, statuses = attach_serving_v2_inputs(
            result.frame,
            forecasts=forecasts,
            registry=load_venue_registry(),
            schedule=loaded.sources.schedule,
            snaps=bridged_snap_counts(loaded.sources),
            weekly=loaded.sources.weekly_stats,
            injuries=report_frame,
            season=season,
            through_week=cutoff.through_week,
            as_of=as_of,
        )
        rows = build_shadow_rows(
            frame=frame,
            v1_quantiles=result.quantiles,
            v2_model=v2,
            as_of=as_of,
            weather_status=statuses,
            build_id=build_id,
            sources={"forecast": forecast_meta},
        )
    except Exception as exc:  # noqa: BLE001 - private evidence; its failure costs only itself
        gate.add(
            QualityCheck.fail(
                "ros.weekly_shadow_failed",
                stage="ros_build",
                message="the private weekly shadow record could not be built; nothing public moves",
                observed=f"{type(exc).__name__}: {exc}",
                severity=Severity.WARNING,
            ),
        )
        return {**summary, "status": "failed"}
    counts = summarise(rows)
    summary = {
        **summary,
        "status": "shadow" if v2 is not None else "absent",
        "configuration_hash": v2.spec.configuration_hash() if v2 is not None else None,
        **counts,
    }
    if shadow_out is not None:
        shadow_out.parent.mkdir(parents=True, exist_ok=True)
        shadow_out.write_text(
            json.dumps(
                {
                    "season": season,
                    "as_of_utc": isoformat_utc(as_of),
                    "build_id": build_id,
                    "git_sha": git_sha,
                    "summary": summary,
                    "rows": rows,
                },
                sort_keys=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
    gate.add(
        QualityCheck.ok(
            "ros.weekly_shadow",
            stage="ros_build",
            message=(
                "the private weekly shadow record: v1 and the shadow v2 side by side with every "
                "pregame input (ADR-099); never published"
            ),
            observed=(
                f"{counts['rows']} row(s), {counts['pregame']} before kickoff, "
                f"{counts['with_v2']} with a v2 projection; written={shadow_out is not None}"
            ),
        ),
    )
    return summary


def _weekly_context_layer(
    *,
    loaded: Any,
    season: int,
    cutoff: RosCutoff,
    as_of: datetime,
    build_id: str,
    gate: QualityGate,
    report_frame: pl.DataFrame | None,
    store: Path | None,
    forecast_rows: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """``weekly_context`` (ADR-099): published facts beside the projections, or nothing."""
    from ffdraft.artifacts.schemas import record_schema_version
    from ffdraft.artifacts.validate import weekly_context_checks
    from ffdraft.contracts.quality import critical_failures
    from ffdraft.ros.dataset import bridged_snap_counts
    from ffdraft.weekly.gameday import build_weekly_context_records
    from ffdraft.weekly.venues import load_venue_registry

    try:
        forecasts, forecast_meta = _forecast_readings(
            season=season,
            as_of=as_of,
            store=store,
            forecast_rows=forecast_rows,
            gate=gate,
        )
        records, summary = build_weekly_context_records(
            schedule=loaded.sources.schedule,
            season=season,
            through_week=cutoff.through_week,
            as_of=as_of,
            build_id=build_id,
            schema_version=record_schema_version("weekly_game_context"),
            registry=load_venue_registry(),
            forecasts=forecasts,
            injuries=report_frame,
            snaps=bridged_snap_counts(loaded.sources),
            weekly=loaded.sources.weekly_stats,
        )
    except Exception as exc:  # noqa: BLE001 - published context; its failure costs only itself
        gate.add(
            QualityCheck.fail(
                "ros.weekly_context_failed",
                stage="ros_build",
                message=(
                    "the game-day context could not be built, so weekly_context.json is "
                    "withheld; the projections and every board are unaffected"
                ),
                observed=f"{type(exc).__name__}: {exc}",
                severity=Severity.WARNING,
            ),
        )
        return [], None
    refused = critical_failures(weekly_context_checks(records, "ros_build"))
    if refused:
        gate.add(
            QualityCheck.fail(
                "ros.weekly_context_invalid",
                stage="ros_build",
                message=(
                    "the game-day context fails the artifact validator's own rules, so "
                    "weekly_context.json is withheld; the projections are unaffected"
                ),
                observed="; ".join(f"{check.check_id}: {check.observed}" for check in refused)[
                    :600
                ],
                severity=Severity.WARNING,
            ),
        )
        return [], None
    gate.add(
        QualityCheck.ok(
            "ros.weekly_context",
            stage="ros_build",
            message="game-day context published beside the weekly projections (ADR-099)",
            observed=(
                f"{summary['records']} team(s); forecasts {summary.get('weather_status')}; "
                f"{summary.get('reports_final', 0)} report(s) with game statuses, "
                f"{summary.get('listed_players', 0)} listed player(s)"
            ),
        ),
    )
    return records, {**summary, "forecast": forecast_meta}


def _forecast_readings(
    *,
    season: int,
    as_of: datetime,
    store: Path | None,
    forecast_rows: Sequence[Mapping[str, Any]] | None,
    gate: QualityGate,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """The newest retained forecast capture at or before ``as_of``: ``game_id -> reading``."""
    from ffdraft.retention import SnapshotStore
    from ffdraft.weekly.capture import FORECAST_SOURCE_ID, read_gameday_capture

    rows: Sequence[Mapping[str, Any]]
    if forecast_rows is not None:
        rows = list(forecast_rows)
        meta: dict[str, Any] = {"source": "given", "capture_key": None, "observed_at_utc": None}
    elif store is not None:
        capture = read_gameday_capture(
            SnapshotStore(root=store, prefix=""),
            source_id=FORECAST_SOURCE_ID,
            season=season,
            at_or_before=as_of,
        )
        if capture is None:
            gate.add(
                QualityCheck.fail(
                    "ros.forecast_capture_absent",
                    stage="ros_build",
                    message=(
                        "no forecast capture is retained at or before this build, so every "
                        "game's weather reads unavailable"
                    ),
                    observed=str(store),
                    severity=Severity.WARNING,
                ),
            )
            return {}, {"source": "store", "capture_key": None, "observed_at_utc": None}
        rows = capture.rows
        meta = {
            "source": "store",
            "capture_key": capture.snapshot_key,
            "observed_at_utc": isoformat_utc(capture.observed_at_utc),
            "providers": capture.details.get("providers"),
        }
    else:
        return {}, {"source": "none", "capture_key": None, "observed_at_utc": None}
    return {str(row["game_id"]): dict(row) for row in rows}, meta


def weekly_metadata(
    model: Any,
    summary: Mapping[str, Any],
    *,
    through_week: int,
    injuries_retrieved_at: datetime | None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``ros_build_metadata.weekly``: one definition for the build and the fixture (ADR-096)."""
    from ffdraft.weekly.frozen import (
        FEATURE_FAMILY_LABELS,
        PAIRWISE_GRID_POINTS,
        TAIL_RULE,
        WEEKLY_DISTRIBUTION_RULE_VERSION,
        WEEKLY_QUANTILE_LEVELS,
    )

    measurements = dict(model.metadata.get("measurements") or {})
    return {
        "model_version": model.spec.model_version,
        "candidate_version": model.spec.candidate_version,
        "configuration_hash": model.spec.configuration_hash(),
        "training_seasons": list(model.training_seasons),
        "fitted_at_utc": model.metadata.get("fitted_at_utc"),
        "through_week": through_week,
        "target_week": summary["target_week"],
        "records": summary["records"],
        "upcoming": summary["upcoming"],
        "kicked_off": summary["kicked_off"],
        "bye": summary["bye"],
        "lines_pending": summary.get("lines_pending", 0),
        "quantile_levels": list(WEEKLY_QUANTILE_LEVELS),
        "distribution_rule": {
            "version": WEEKLY_DISTRIBUTION_RULE_VERSION,
            "tail_lower_factor": float(TAIL_RULE["lower_factor"]),
            "tail_upper_factor": float(TAIL_RULE["upper_factor"]),
            "grid_points": PAIRWISE_GRID_POINTS,
        },
        "families": dict(FEATURE_FAMILY_LABELS),
        "margin": measurements.get("margin", {}),
        "correlation": measurements.get("correlation", {}),
        "startable": measurements.get("startable", {}),
        "injury_base_rates": measurements.get("injuries", {}),
        "evaluation": measurements.get("evaluation", {}),
        "injuries_retrieved_at_utc": (
            isoformat_utc(injuries_retrieved_at) if injuries_retrieved_at else None
        ),
        "statement": WEEKLY_STATEMENT,
        "explanation": explanation_metadata(),
        "context": dict(context) if context is not None else None,
    }


def explanation_metadata() -> dict[str, Any]:
    """How every record's ``explanation`` was made, printed beside it (ADR-099)."""
    from ffdraft.weekly.explain import (
        EXPLAINED_LEVELS,
        EXPLANATION_RULE_VERSION,
        REFERENCE_SHRINK_GAMES,
        V1_EXPLANATION_GROUPS,
    )

    return {
        "rule": EXPLANATION_RULE_VERSION,
        "levels": [f"q{round(level * 100):02d}" for level in EXPLAINED_LEVELS],
        "groups": {group.key: group.label for group in V1_EXPLANATION_GROUPS},
        "reference_shrink_games": REFERENCE_SHRINK_GAMES,
        "reference": (
            "His typical week: everything about him held at this week's values, in ordinary "
            "games for him: his team's mean posted lines over its completed games (shrunk "
            "toward the league by three games), half at home, his team's indoor share, equal "
            "rest and a league-average defence at this cutoff."
        ),
        "statement": (
            "Each term is how far this model's number moved with that input, the others held "
            "(exact Shapley values over the game inputs). A model attribution, not a measured "
            "causal effect. Weather and injuries are printed as context; weekly-startsit-v1 "
            "reads neither, so they carry no points."
        ),
    }


#: Travels with every weekly projection, so the page cannot print one without saying what the
#: model reads and what it does not (ADR-096).
WEEKLY_STATEMENT = (
    "Next-game fantasy points given that he plays, from weekly-startsit-v1: his role, form "
    "and track record through the cutoff, his offence, the opposing defence's allowed "
    "points, and the game's sportsbook total and spread. It reads no injury report; the "
    "league's report is printed beside it instead. No draft or rest-of-season number reads "
    "this model."
)


def _injury_reports(
    injuries: pl.DataFrame | None,
    *,
    season: int,
    week: int,
    allow_fetch: bool,
    as_of: datetime,
    gate: QualityGate,
) -> tuple[dict[str, dict[str, Any]], datetime | None, pl.DataFrame | None]:
    """The target week's official report, or nothing. Optional in every sense."""
    from ffdraft.weekly.injuries import normalize_injuries, reports_for_week

    frame = injuries
    retrieved: datetime | None = as_of if injuries is not None else None
    if frame is None and allow_fetch:
        try:
            frame = normalize_injuries(nflverse_loaders().load_injuries(seasons=[season]))
            retrieved = utc_now()
        except Exception as exc:  # noqa: BLE001 - a report beside a projection, never a gate
            gate.add(
                QualityCheck.fail(
                    "ros.injury_report_unavailable",
                    stage="ros_build",
                    message=(
                        "the league's injury report could not be read, so no designation is "
                        "printed beside a weekly projection; every projection is unaffected"
                    ),
                    observed=f"{type(exc).__name__}: {exc}",
                    severity=Severity.WARNING,
                ),
            )
            return {}, None, None
    if frame is None:
        return {}, None, None
    return reports_for_week(frame, season=season, week=week), retrieved, frame


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
            # Null **and** NaN. A position whose pool is entirely consumed by starting and
            # bench slots has no replacement baseline in any draw, and the draw loop records
            # that as NaN rather than null — `np.nanmean` over an all-NaN row returns NaN.
            # Filtering only nulls would publish `NaN`, which is not valid JSON and would
            # break the browser rather than withholding a row nobody can value.
            valued = result.players.filter(
                pl.col("expected_vorp").is_not_null() & pl.col("expected_vorp").is_finite(),
            )
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
            # The whole board, with the values the model gave every player on it (ADR-097). A
            # player surfaced from beyond the published depth is copied from here, so these
            # must be his own simulated numbers: before this block carried them, a surfaced
            # row was published as his position's number 1 with 0.0 VORP and 0.0 uncertainty.
            full_board.extend(
                {
                    "player_id": str(row["player_id"]),
                    "fair_rank": int(row["fair_rank"]),
                    "position_rank": int(row["position_rank"]),
                    "display_name": row.get("display_name"),
                    "position": str(row.get("position") or ""),
                    "team": row.get("team"),
                    "scoring_preset": scoring,
                    "league_preset_id": preset_id,
                    "expected_vorp": round(float(row["expected_vorp"]), 4),
                    "p50_vorp": round(float(row["p50_vorp"]), 4),
                    "uncertainty": round(float(row["uncertainty"]), 4),
                    "expected_points": round(float(row["expected_points"]), 4),
                    "expected_games": round(float(row.get("expected_remaining_games") or 0.0), 4),
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
                # Never `str(None)`: that is how "None" became a player's name (ADR-097).
                "display_name": str(row.get("display_name") or player_id),
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
    history: Any | None = None,
    surface: Sequence[Mapping[str, Any]] | None = None,
    signal_layer: Mapping[str, Any] | None = None,
    weekly: Mapping[str, Any] | None = None,
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
        "behavior": (
            None
            if signals is None
            else {
                **signals.to_dict(),
                # The window behind the day's counts, beside them rather than instead of
                # them: `snapshot_at_utc` above is the instant the board's numbers came
                # from, and this is every instant the sparkline draws (ADR-089).
                "history": None if history is None or history.is_empty else history.summary(),
            }
        ),
        "surface": (
            {
                "rule_version": SURFACE_RULE_VERSION,
                "tier_depth": TIER_DEPTH_RULE.depth,
                "blocks": list(surface),
            }
            if surface is not None
            else None
        ),
        "signals": None if signal_layer is None else dict(signal_layer),
        "weekly": None if weekly is None else dict(weekly),
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
