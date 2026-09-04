"""The rest-of-season snapshot dataset: features joined to labels, sealed season removed.

One row per ``(season, through_week, player_id, scoring_preset)``. The build is a join of
three things that are each leakage-safe on their own:

1. the **preseason block** - Phase 2's feature table for the same season, built entirely
   from evidence dated before that season's draft anchor and therefore available at every
   in-season cutoff;
2. the **in-season block** - :mod:`ffdraft.ros.features`, cumulative reads of weeks at or
   before the cutoff;
3. the **label** - :mod:`ffdraft.ros.labels`, sums over weeks strictly after the cutoff.

The universe is the union of two observable populations: the season's leakage-safe preseason
eligible universe, and anyone who has appeared in a scored game at or before the cutoff. The
second half is what stops a mid-season arrival from being invisible until the following
August; the first is what stops the dataset from containing only players who worked out.
Rows for a preseason-universe player who never appears are kept, with a zero label, for
exactly the survivorship reason :mod:`ffdraft.labels.fantasy` states.

The sealed season is dropped at load time, not at use time, so a development run physically
does not have the rows.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from ffdraft.config import AppConfig, ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck, frame_content_hash
from ffdraft.contracts.enums import Severity
from ffdraft.features.build import HistoricalSources, pfr_to_gsis_bridge
from ffdraft.features.dictionary import ALL_CORE_POSITIONS
from ffdraft.identity.ids import IdNamespace, make_player_id
from ffdraft.ros.cutoff import ROS_CUTOFF_RULE_VERSION, cutoff_rule_document, season_cutoffs
from ffdraft.ros.dictionary import (
    ROS_FEATURE_SCHEMA_VERSION,
    RosFeatureSelection,
    ros_feature_schema_hash,
    ros_feature_selection,
)
from ffdraft.ros.features import build_in_season_features
from ffdraft.ros.holdout import ROS_SEALED_SEASONS, RosFinalEvalAuthorization, is_ros_sealed
from ffdraft.ros.labels import ROS_LABEL_VERSION, build_ros_labels, reconcile_ros_labels
from ffdraft.ros.panel import PANEL_VERSION, build_weekly_panel, horizon_weekly_rows
from ffdraft.scoring.engine import SCORING_ENGINE_VERSION, season_totals
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "ROS_DATASET_VERSION",
    "ROS_KEY_COLUMNS",
    "ROS_TARGET_COLUMNS",
    "RosDataset",
    "build_ros_dataset",
    "load_ros_dataset",
    "write_ros_dataset",
]

#: Bump when the dataset's construction changes in a way that makes an existing build stale.
ROS_DATASET_VERSION = "ros_dataset_v1"

ROS_KEY_COLUMNS: tuple[str, ...] = (
    "season",
    "through_week",
    "player_id",
    "position",
    "scoring_preset",
)

#: The three quantities 11.2 requires every snapshot to persist, plus the composition target.
ROS_TARGET_COLUMNS: tuple[str, ...] = (
    "actual_remaining_games",
    "actual_remaining_points",
    "actual_remaining_ppg",
    "remaining_horizon_weeks",
)

#: Carried for slicing and for the transparent baselines. None of these is a model input.
ROS_CONTEXT_COLUMNS: tuple[str, ...] = (
    "gsis_id",
    "display_name",
    "team_to_date",
    "eligibility_basis",
    "universe_era",
    "rookie_flag",
    "has_prior_season_stats",
    "actual_games_to_date",
    "actual_points_to_date",
    "preseason_expected_points",
)

_SNAPSHOTS_FILE = "ros_snapshots.parquet"
_MANIFEST_FILE = "ros_build_manifest.json"
_DICTIONARY_FILE = "ros_feature_dictionary.md"


@dataclass
class RosDataset:
    """The joined snapshot frame plus everything a report needs to describe it."""

    frame: pl.DataFrame
    selection: RosFeatureSelection
    seasons: tuple[int, ...]
    withheld_seasons: tuple[int, ...] = ()
    withheld_rows: int = 0
    manifest: dict[str, Any] = field(default_factory=dict)
    checks: tuple[QualityCheck, ...] = ()

    @property
    def sealed(self) -> bool:
        return not any(is_ros_sealed(season) for season in self.seasons)

    def describe(self) -> dict[str, Any]:
        by_season = (
            self.frame.group_by("season")
            .agg(
                pl.len().alias("rows"),
                pl.col("player_id").n_unique().alias("players"),
                pl.col("through_week").n_unique().alias("snapshots"),
            )
            .sort("season")
        )
        return {
            "grain": "season x through_week x player_id x scoring_preset",
            "dataset_version": ROS_DATASET_VERSION,
            "cutoff_rule_version": ROS_CUTOFF_RULE_VERSION,
            "label_version": ROS_LABEL_VERSION,
            "feature_schema_version": ROS_FEATURE_SCHEMA_VERSION,
            "feature_schema_hash": ros_feature_schema_hash(),
            "rows": self.frame.height,
            "seasons": list(self.seasons),
            "withheld_seasons": list(self.withheld_seasons),
            "withheld_rows": self.withheld_rows,
            "by_season": by_season.to_dicts(),
        }


def _universe_from_preseason(preseason: pl.DataFrame, seasons: Sequence[int]) -> pl.DataFrame:
    if preseason.is_empty():
        return pl.DataFrame(schema={"season": pl.Int32, "gsis_id": pl.String})
    return (
        preseason.filter(pl.col("season").is_in([int(season) for season in seasons]))
        .select("season", "gsis_id")
        .unique()
    )


def _bridged_snap_counts(sources: HistoricalSources) -> pl.DataFrame:
    """Snap counts keyed by ``gsis_id`` through the same bridge Phase 2 uses."""
    if sources.snap_counts.is_empty():
        return sources.snap_counts
    bridge = pfr_to_gsis_bridge(sources.player_master, sources.rosters)
    mapping = pl.DataFrame(
        {"pfr_player_id": list(bridge.keys()), "gsis_id": list(bridge.values())},
        schema={"pfr_player_id": pl.String, "gsis_id": pl.String},
    )
    if mapping.is_empty():
        return sources.snap_counts.with_columns(pl.lit(None, dtype=pl.String).alias("gsis_id"))
    return sources.snap_counts.join(mapping, on="pfr_player_id", how="left")


def build_ros_dataset(
    sources: HistoricalSources,
    preseason_features: pl.DataFrame,
    *,
    config: AppConfig,
    seasons: Sequence[int],
    generated_at: datetime | None = None,
    git_sha: str | None = None,
    positions: Sequence[str] = ALL_CORE_POSITIONS,
) -> RosDataset:
    """Build every modelled snapshot for ``seasons`` from already-normalized frames."""
    built_at = generated_at or utc_now()
    wanted = sorted({int(season) for season in seasons})
    scoring: Mapping[ScoringPreset, ScoringRules] = config.league.scoring

    universe = _universe_from_preseason(preseason_features, wanted)
    panel = build_weekly_panel(
        sources.weekly_stats,
        scoring,
        seasons=wanted,
        universe=universe,
        snap_counts=_bridged_snap_counts(sources),
        expected_points=sources.expected_points,
    )
    labels = build_ros_labels(panel, scoring)
    features = build_in_season_features(panel, scoring, schedule=sources.schedule)

    checks: list[QualityCheck] = list(
        reconcile_ros_labels(
            labels,
            season_totals(horizon_weekly_rows(sources.weekly_stats, wanted), scoring),
        ),
    )

    joined = features.join(
        labels,
        on=["season", "through_week", "gsis_id", "scoring_preset"],
        how="inner",
    )
    frame = _attach_preseason_block(joined, preseason_features, positions=positions)
    checks.extend(_universe_checks(frame, panel, wanted))

    # The *dataset* carries every requested season, sealed ones included: the sealed
    # evaluation has to have something to read when it is eventually authorized. The seal is
    # enforced where a model could reach the rows - :func:`load_ros_dataset` - not here.
    sealed = tuple(season for season in wanted if is_ros_sealed(season))
    checks.append(
        QualityCheck.ok(
            "ros_dataset.sealed_season_present",
            stage="ros_dataset",
            message=(
                "sealed seasons are written but are dropped at load time unless a "
                "RosFinalEvalAuthorization is supplied"
            ),
            observed=f"sealed={list(sealed)}; rule={ROS_SEALED_SEASONS}",
        ),
    )

    present = tuple(sorted({int(value) for value in frame.get_column("season").unique()}))
    dataset = RosDataset(
        frame=frame,
        selection=ros_feature_selection(),
        seasons=present,
        checks=tuple(checks),
    )
    dataset.manifest = _manifest(
        dataset,
        config=config,
        generated_at=built_at,
        git_sha=git_sha,
        requested_seasons=wanted,
    )
    return dataset


def _attach_preseason_block(
    joined: pl.DataFrame,
    preseason: pl.DataFrame,
    *,
    positions: Sequence[str],
) -> pl.DataFrame:
    """Join Phase 2's season-level feature table and settle identity for in-season arrivals."""
    selection = ros_feature_selection()
    preseason_columns = [
        name
        for name in (
            "season",
            "gsis_id",
            "player_id",
            "position",
            "display_name",
            "eligibility_basis",
            "universe_era",
            *selection.preseason,
        )
        if name in preseason.columns
    ]
    block = preseason.select(*dict.fromkeys(preseason_columns)) if preseason_columns else preseason
    frame = joined.join(block, on=["season", "gsis_id"], how="left")
    frame = frame.with_columns(
        pl.col("player_id")
        .fill_null(
            pl.col("gsis_id").map_elements(
                lambda value: make_player_id(IdNamespace.GSIS, value),
                return_dtype=pl.String,
            ),
        )
        .alias("player_id"),
        pl.coalesce(pl.col("position"), pl.col("position_to_date")).alias("position"),
        pl.col("player_id").is_not_null().alias("in_preseason_universe"),
    )
    return frame.filter(pl.col("position").is_in(list(positions))).sort(
        "season",
        "through_week",
        "scoring_preset",
        "position",
        "player_id",
    )


def _universe_checks(
    frame: pl.DataFrame,
    panel: pl.DataFrame,
    seasons: Sequence[int],
) -> list[QualityCheck]:
    """Report how much of the in-season universe the preseason table could not have known."""
    if frame.is_empty():
        return []
    arrivals = frame.filter(~pl.col("in_preseason_universe"))
    share = arrivals.get_column("player_id").n_unique() / max(
        frame.get_column("player_id").n_unique(),
        1,
    )
    checks = [
        QualityCheck.ok(
            "ros_dataset.in_season_arrivals",
            stage="ros_dataset",
            message=(
                "players first observed in season are admitted at the cutoff that observes "
                "them; the preseason feature block is null for them"
            ),
            observed=f"{arrivals.get_column('player_id').n_unique()} player(s), {share:.1%}",
        ),
    ]
    # A snapshot with no rows at all would mean a season silently produced nothing.
    expected = {
        season: len(season_cutoffs(season))
        for season in seasons
        if season in set(frame.get_column("season").unique().to_list())
    }
    observed = {
        int(row["season"]): int(row["snapshots"])
        for row in frame.group_by("season")
        .agg(pl.col("through_week").n_unique().alias("snapshots"))
        .to_dicts()
    }
    missing = {season: count for season, count in expected.items() if observed.get(season) != count}
    if missing:
        checks.append(
            QualityCheck.fail(
                "ros_dataset.snapshot_grid_incomplete",
                stage="ros_dataset",
                message="a season did not produce every modelled snapshot week",
                observed=str({season: observed.get(season, 0) for season in missing}),
                expected=str(missing),
                severity=Severity.CRITICAL,
            ),
        )
    return checks


def _manifest(
    dataset: RosDataset,
    *,
    config: AppConfig,
    generated_at: datetime,
    git_sha: str | None,
    requested_seasons: Sequence[int],
) -> dict[str, Any]:
    return {
        "dataset_version": ROS_DATASET_VERSION,
        "generated_at_utc": isoformat_utc(generated_at),
        "git_sha": git_sha or "unknown",
        "panel_version": PANEL_VERSION,
        "cutoff": cutoff_rule_document(requested_seasons),
        "label_version": ROS_LABEL_VERSION,
        "scoring_engine_version": SCORING_ENGINE_VERSION,
        "feature_schema_version": ROS_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": ros_feature_schema_hash(),
        "feature_selection": dataset.selection.to_dict(),
        "league_config_version": config.league.schema_version,
        "requested_seasons": list(requested_seasons),
        "retained_seasons": list(dataset.seasons),
        "withheld_seasons": list(dataset.withheld_seasons),
        "rows": dataset.frame.height,
        "content_hash": frame_content_hash(dataset.frame),
        "checks": [check.to_dict() for check in dataset.checks],
    }


def write_ros_dataset(dataset: RosDataset, out_dir: Path) -> list[Path]:
    """Write the snapshot table, the manifest and the published feature dictionary."""
    from ffdraft.ros.dictionary import ros_dictionary_markdown

    blocking = [check for check in dataset.checks if check.severity is Severity.CRITICAL]
    if blocking:
        raise RuntimeError(
            "refusing to write a ROS dataset with critical findings: "
            + "; ".join(check.check_id for check in blocking),
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    path = out_dir / _SNAPSHOTS_FILE
    dataset.frame.write_parquet(path, compression="zstd")
    written.append(path)

    for name, text in (
        (_MANIFEST_FILE, json.dumps(dataset.manifest, indent=2, sort_keys=True) + "\n"),
        (
            _DICTIONARY_FILE,
            "# Rest-of-season feature dictionary\n\n"
            f"Schema `{ROS_FEATURE_SCHEMA_VERSION}` (`{ros_feature_schema_hash()}`). "
            "The preseason block is inherited from `intrinsic_core_v1` unchanged; only the "
            "in-season block is listed here.\n\n" + ros_dictionary_markdown() + "\n",
        ),
    ):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def load_ros_dataset(
    directory: Path,
    *,
    authorization: RosFinalEvalAuthorization | None = None,
    scoring_presets: Sequence[str] | None = None,
) -> RosDataset:
    """Read a written snapshot dataset back, dropping the sealed season unless authorized."""
    path = directory / _SNAPSHOTS_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found; run `ffdraft build-ros-dataset --last-season 2025` first",
        )
    frame = pl.read_parquet(path)
    withheld: tuple[int, ...] = ()
    withheld_rows = 0
    if authorization is None:
        sealed = sorted(
            {
                int(season)
                for season in frame.get_column("season").unique().to_list()
                if is_ros_sealed(int(season))
            },
        )
        if sealed:
            withheld = tuple(sealed)
            withheld_rows = int(frame.filter(pl.col("season").is_in(sealed)).height)
            frame = frame.filter(~pl.col("season").is_in(sealed))
    if scoring_presets is not None:
        frame = frame.filter(pl.col("scoring_preset").is_in(list(scoring_presets)))

    manifest_path = directory / _MANIFEST_FILE
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return RosDataset(
        frame=frame,
        selection=ros_feature_selection(),
        seasons=tuple(sorted({int(value) for value in frame.get_column("season").unique()})),
        withheld_seasons=withheld,
        withheld_rows=withheld_rows,
        manifest=manifest,
    )
