"""One current-season rest-of-season snapshot: the inference frame, with no labels.

:mod:`ffdraft.ros.dataset` builds *training* snapshots — features joined to labels, for every
cutoff of every completed season. This module builds the other half of the same idea: the
single snapshot a production build serves from, at cutoff week N of the season now being
played, where the labels do not exist because the weeks they sum over have not happened.

The two paths share every feature-producing function, which is the property that matters:
a served row and a trained row are the same computation over the same panel under the same
cutoff rule, or the model is being served on features it was never validated with.

**Three guards, each earning its place.**

*The panel is truncated before it is built.* ``build_weekly_panel`` lays a dense week grid
over the whole fantasy horizon, so a partial season would produce rows for weeks that have
not been played with ``played = 0`` — indistinguishable, to every cumulative feature, from a
week a player missed. Every week after the cutoff is therefore deleted from the weekly frame
first. Phase 11's cutoff audit proves the week-N row is identical either way; this makes it
true by construction as well as by measurement.

*The preseason block never sees the current season's statistics.* The 78 inherited preseason
columns are draft-time features, and Phase 2 proved constructively that a season's feature
table is byte-identical with its own statistics deleted. Deleting them here anyway costs one
filter and turns that proof into a property of this code path rather than a property of a
different one.

*The preseason block is anchored, not stamped.* Mid-season, ``current_cutoff`` returns the
season anchor itself, because the anchor has already passed. So the preseason half of a
week-9 row is exactly the preseason half of the draft board — which is what makes
``preseason_fair_rank`` and ``ros_fair_rank`` comparable as *a change in the model's view*
rather than as two unrelated numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from ffdraft.config import AppConfig, ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.features.build import HistoricalSources
from ffdraft.features.dictionary import ALL_CORE_POSITIONS
from ffdraft.identity.ids import IdNamespace, make_player_id
from ffdraft.ros.cutoff import ROS_CUTOFF_RULE_VERSION, RosCutoff
from ffdraft.ros.dataset import bridged_snap_counts, universe_from_preseason
from ffdraft.ros.dictionary import ros_feature_selection
from ffdraft.ros.features import build_in_season_features
from ffdraft.ros.leakage import audit_ros_feature_names
from ffdraft.ros.panel import build_weekly_panel

__all__ = [
    "RosSnapshot",
    "build_current_ros_snapshot",
    "strip_target_season_statistics",
    "truncate_to_cutoff",
]


@dataclass
class RosSnapshot:
    """The inference frame for one cutoff, plus what a reader needs to trust it."""

    cutoff: RosCutoff
    frame: pl.DataFrame
    checks: tuple[QualityCheck, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.frame.is_empty()


def truncate_to_cutoff(weekly: pl.DataFrame, cutoff: RosCutoff) -> pl.DataFrame:
    """Delete every week of the cutoff's season after the cutoff. Other seasons untouched."""
    if weekly.is_empty():
        return weekly
    return weekly.filter(
        (pl.col("season") != cutoff.season) | (pl.col("week") <= cutoff.through_week),
    )


def strip_target_season_statistics(sources: HistoricalSources, season: int) -> HistoricalSources:
    """A copy of ``sources`` with the target season's own statistics removed.

    Used only for the preseason feature block. The rest-of-season block is *supposed* to
    read those weeks; the preseason block is not, and handing it a frame that does not
    contain them is cheaper than trusting that it ignores them.
    """
    from dataclasses import replace

    def drop(frame: pl.DataFrame) -> pl.DataFrame:
        if frame.is_empty() or "season" not in frame.columns:
            return frame
        return frame.filter(pl.col("season") != season)

    return replace(
        sources,
        weekly_stats=drop(sources.weekly_stats),
        snap_counts=drop(sources.snap_counts),
        expected_points=drop(sources.expected_points),
    )


def build_current_ros_snapshot(
    sources: HistoricalSources,
    preseason_features: pl.DataFrame,
    *,
    config: AppConfig,
    cutoff: RosCutoff,
    positions: Sequence[str] = ALL_CORE_POSITIONS,
    scoring_presets: Sequence[str] | None = None,
) -> RosSnapshot:
    """Build the ``through_week = cutoff.through_week`` inference frame for one season.

    ``preseason_features`` is the current season's Phase-2 feature table, built at the
    season anchor. It supplies both the eligible universe and the 78 inherited preseason
    columns; a player outside it appears only from the snapshot that first observes him,
    which is the cutoff-rule membership fix ADR-068 records.
    """
    scoring: Mapping[ScoringPreset, ScoringRules] = config.league.scoring
    season = cutoff.season
    checks: list[QualityCheck] = []

    universe = universe_from_preseason(preseason_features, [season])
    weekly = truncate_to_cutoff(sources.weekly_stats, cutoff)
    truncated = _with_weekly(sources, weekly)

    panel = build_weekly_panel(
        weekly,
        scoring,
        seasons=[season],
        universe=universe,
        snap_counts=truncate_to_cutoff(bridged_snap_counts(truncated), cutoff),
        expected_points=truncate_to_cutoff(sources.expected_points, cutoff),
    )
    features = build_in_season_features(
        panel,
        scoring,
        schedule=sources.schedule,
        universe=universe,
    )
    checks.extend(audit_ros_feature_names())

    at_cutoff = features.filter(pl.col("through_week") == cutoff.through_week)
    if scoring_presets is not None:
        at_cutoff = at_cutoff.filter(pl.col("scoring_preset").is_in(list(scoring_presets)))
    frame = _attach_preseason(at_cutoff, preseason_features, positions=positions)

    checks.append(
        QualityCheck.ok(
            "ros_snapshot.cutoff",
            stage="ros_snapshot",
            message=(
                f"snapshot {cutoff.snapshot_id} reads weeks "
                f"{cutoff.observed_weeks[0] if cutoff.observed_weeks else 0}-"
                f"{cutoff.through_week} and predicts weeks "
                f"{cutoff.remaining_weeks[0] if cutoff.remaining_weeks else 0}-"
                f"{cutoff.horizon.last_week} ({ROS_CUTOFF_RULE_VERSION})"
            ),
            observed=f"{frame.height} row(s) across {_players(frame)} player(s)",
        ),
    )
    checks.append(
        QualityCheck.ok(
            "ros_snapshot.preseason_block_is_anchored",
            stage="ros_snapshot",
            message=(
                "the inherited preseason feature block is built from the season anchor with "
                "the target season's own statistics removed, so no in-season outcome can "
                "reach a draft-time feature"
            ),
            observed=f"season {season} statistics removed from the preseason source frames",
        ),
    )

    arrivals = 0
    if not frame.is_empty() and "in_preseason_universe" in frame.columns:
        arrivals = int(frame.filter(~pl.col("in_preseason_universe")).height)
    return RosSnapshot(
        cutoff=cutoff,
        frame=frame,
        checks=tuple(checks),
        diagnostics={
            "cutoff": cutoff.to_dict(),
            "rows": frame.height,
            "players": _players(frame),
            "in_season_arrivals": arrivals,
            "panel_rows": panel.height,
            "feature_set_version": ros_feature_selection().version,
            "feature_set_hash": ros_feature_selection().fingerprint(),
        },
    )


def _players(frame: pl.DataFrame) -> int:
    return 0 if frame.is_empty() else int(frame.get_column("player_id").n_unique())


def _with_weekly(sources: HistoricalSources, weekly: pl.DataFrame) -> HistoricalSources:
    from dataclasses import replace

    return replace(sources, weekly_stats=weekly)


def _attach_preseason(
    joined: pl.DataFrame,
    preseason: pl.DataFrame,
    *,
    positions: Sequence[str],
) -> pl.DataFrame:
    """Join the season's preseason feature block. The inference-time twin of the dataset's.

    Identical to :func:`ffdraft.ros.dataset._attach_preseason_block` except that there is no
    label to carry: an in-season arrival still gets a canonical id derived from his GSIS id
    and a position taken from what has actually been observed, and a row whose position is
    outside the core four is dropped rather than served to a model with no group for it.
    """
    selection = ros_feature_selection()
    columns = [
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
    block = preseason.select(*dict.fromkeys(columns)) if columns else preseason
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
    )
    return frame.filter(pl.col("position").is_in(list(positions))).sort(
        "scoring_preset",
        "position",
        "player_id",
    )
