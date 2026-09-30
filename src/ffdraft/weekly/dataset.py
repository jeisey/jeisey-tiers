"""The weekly start/sit dataset: a rest-of-season snapshot, its next game, and what he scored.

One row per ``(season, through_week, player_id, scoring_preset)`` where the player **appeared**
in week ``through_week + 1``. Three leakage-safe pieces are joined, each for its own reason:

1. **The snapshot** — the rest-of-season dataset's row at cutoff ``N``, unchanged. Every
   in-season and preseason feature in it is already point-in-time and already audited
   (:mod:`ffdraft.ros.leakage`); re-deriving them here would be a second implementation of
   features that already have one.
2. **The game** — :func:`ffdraft.weekly.context.team_game_context` for the team he actually
   played for in week ``N + 1``. A team assignment is public before kickoff, and so are the
   lines; neither is an outcome.
3. **The opponent** — :func:`ffdraft.weekly.context.opponent_allowed` at cutoff ``N``: weeks
   ``1..N`` only.

The label is his week ``N + 1`` points in the row's preset. A snap-only appearance scores zero
(he played and recorded nothing), which is what ``usage_signals_v1`` calls an appearance too.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import normalize_team_code
from ffdraft.features.build import HistoricalSources
from ffdraft.ros.dataset import bridged_snap_counts
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.weekly.context import (
    GAME_CONTEXT_COLUMNS,
    OPPONENT_COLUMNS,
    opponent_allowed,
    scored_position_rows,
    team_game_context,
)
from ffdraft.weekly.frozen import WEEKLY_FEATURES, WEEKLY_POSITIONS, WEEKLY_TARGET_RULE_VERSION

__all__ = [
    "TARGET_COLUMN",
    "WEEKLY_KEY_COLUMNS",
    "WeeklyDataset",
    "appearances",
    "attach_game_and_opponent",
    "build_weekly_dataset",
]

TARGET_COLUMN = "target_points"

WEEKLY_KEY_COLUMNS: tuple[str, ...] = (
    "season",
    "through_week",
    "target_week",
    "player_id",
    "gsis_id",
    "position",
    "scoring_preset",
)

#: Carried for slicing, joining and the page. None is a model input.
CONTEXT_COLUMNS: tuple[str, ...] = (
    "display_name",
    "team",
    "opponent",
    "home_away",
    "game_id",
    "ppg_to_date",
    "prev1_fantasy_ppg_ppr",
    "prev1_fantasy_ppg_std",
    "games_to_date",
    "ppg_last3",
    "games_last3",
)


@dataclass
class WeeklyDataset:
    frame: pl.DataFrame
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def seasons(self) -> tuple[int, ...]:
        return tuple(sorted({int(value) for value in self.frame.get_column("season").unique()}))


def appearances(
    scored: pl.DataFrame,
    snap_counts: pl.DataFrame,
    seasons: Sequence[int],
) -> pl.DataFrame:
    """Every ``(season, week, gsis_id, scoring_preset)`` appearance with its points and team.

    A stats row is an appearance; so is an offensive snap with no stats row, which scores
    zero in every preset.
    """
    stat_rows = scored.select(
        "season",
        "week",
        "gsis_id",
        "scoring_preset",
        pl.col("team").alias("played_for"),
        pl.col("points").alias("target_points"),
    )
    if snap_counts.is_empty() or "gsis_id" not in snap_counts.columns:
        return stat_rows
    wanted = sorted({int(season) for season in seasons})
    presets = scored.select("scoring_preset").unique()
    in_horizon = pl.lit(False)
    for season in wanted:
        horizon = fantasy_horizon(season)
        in_horizon = in_horizon | (
            (pl.col("season") == season)
            & (pl.col("week") >= horizon.first_week)
            & (pl.col("week") <= horizon.last_week)
        )
    snapped = (
        snap_counts.filter(
            pl.col("season").is_in(wanted)
            & (pl.col("game_type") == "REG")
            & pl.col("gsis_id").is_not_null()
            & (pl.col("offense_snaps") > 0)
            & in_horizon,
        )
        .group_by("season", "week", "gsis_id")
        .agg(pl.col("team").first().alias("played_for"))
        .with_columns(
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col("played_for").map_elements(normalize_team_code, return_dtype=pl.String),
        )
    )
    snap_only = snapped.join(
        stat_rows.select("season", "week", "gsis_id").unique(),
        on=["season", "week", "gsis_id"],
        how="anti",
    )
    if snap_only.is_empty():
        return stat_rows
    snap_only = snap_only.join(presets, how="cross").with_columns(
        pl.lit(0.0).alias("target_points"),
    )
    return pl.concat(
        [stat_rows, snap_only.select(stat_rows.columns)],
        how="vertical_relaxed",
    )


def attach_game_and_opponent(
    frame: pl.DataFrame,
    *,
    context: pl.DataFrame,
    allowed: pl.DataFrame,
    team_column: str,
) -> pl.DataFrame:
    """Join the target week's game (by ``team_column``) and the opponent reading at cutoff.

    ``frame`` must carry ``season``, ``through_week``, ``target_week``, ``position`` and
    ``scoring_preset``. A row whose team has no game in the target week drops out: a bye is
    not a start/sit question.

    The attached columns are authoritative. A frame that already carries one (a caller that
    pre-filled every feature name with null) has it replaced, never suffixed ``_right`` beside
    a stale copy the model would then read.
    """
    games = context.rename({"week": "target_week", "team": team_column})
    game_keys = {"season", "target_week", team_column}
    attached = (set(games.columns) - game_keys) | {
        *OPPONENT_COLUMNS,
        "league_ppg",
        "opp_allowed_rank",
        "opp_defenses",
    }
    frame = frame.drop([column for column in frame.columns if column in attached])
    joined = frame.join(games, on=["season", "target_week", team_column], how="inner")
    opponent = allowed.select(
        "season",
        "through_week",
        pl.col("defense").alias("opponent"),
        "position",
        "scoring_preset",
        *OPPONENT_COLUMNS,
        "league_ppg",
        "opp_allowed_rank",
        "opp_defenses",
    )
    return joined.join(
        opponent,
        on=["season", "through_week", "opponent", "position", "scoring_preset"],
        how="left",
    )


def build_weekly_dataset(
    ros_frame: pl.DataFrame,
    sources: HistoricalSources,
    *,
    scoring: Mapping[ScoringPreset, ScoringRules],
    seasons: Sequence[int],
) -> WeeklyDataset:
    """Build every labelled weekly row for ``seasons`` from the rest-of-season snapshots."""
    wanted = sorted({int(season) for season in seasons})
    checks: list[QualityCheck] = []
    scored = scored_position_rows(
        sources.weekly_stats,
        scoring,
        sorted({*wanted, *(season - 1 for season in wanted)}),
    )
    labels = appearances(
        scored.filter(pl.col("season").is_in(wanted)),
        bridged_snap_counts(sources),
        wanted,
    )
    context = team_game_context(sources.schedule, wanted)

    snapshots = (
        ros_frame.filter(
            pl.col("season").is_in(wanted) & pl.col("position").is_in(list(WEEKLY_POSITIONS)),
        )
        .with_columns((pl.col("through_week") + 1).cast(pl.Int32).alias("target_week"))
        .filter(
            pl.struct("season", "target_week").map_elements(
                lambda key: fantasy_horizon(int(key["season"])).contains(int(key["target_week"])),
                return_dtype=pl.Boolean,
            ),
        )
    )
    cutoffs = snapshots.select("season", "through_week").unique().sort("season", "through_week")
    allowed = pl.concat(
        [
            opponent_allowed(
                scored, season=int(row["season"]), through_week=int(row["through_week"])
            )
            for row in cutoffs.iter_rows(named=True)
        ],
        how="vertical_relaxed",
    )

    labelled = snapshots.join(
        labels.rename({"week": "target_week"}),
        on=["season", "target_week", "gsis_id", "scoring_preset"],
        how="inner",
    )
    frame = attach_game_and_opponent(
        labelled,
        context=context,
        allowed=allowed,
        team_column="played_for",
    ).rename({"played_for": "team"})

    missing = [name for name in WEEKLY_FEATURES if name not in frame.columns]
    if missing:
        raise ValueError(f"weekly dataset is missing declared features: {missing}")
    keep = [
        *WEEKLY_KEY_COLUMNS,
        *(
            name
            for name in CONTEXT_COLUMNS
            if name in frame.columns and name not in WEEKLY_FEATURES
        ),
        *WEEKLY_FEATURES,
        "league_ppg",
        "opp_allowed_rank",
        "kickoff_utc",
        TARGET_COLUMN,
    ]
    frame = frame.select(list(dict.fromkeys(keep))).sort(
        "season",
        "through_week",
        "scoring_preset",
        "position",
        "player_id",
    )

    leaks = frame.filter(pl.col("target_week") <= pl.col("through_week")).height
    checks.append(
        QualityCheck.ok(
            "weekly_dataset.target_after_cutoff",
            stage="weekly_dataset",
            message=f"{WEEKLY_TARGET_RULE_VERSION}: every label is from a week after its cutoff",
            observed=f"{frame.height} rows; {leaks} violating",
        )
        if leaks == 0
        else QualityCheck.fail(
            "weekly_dataset.target_after_cutoff",
            stage="weekly_dataset",
            message="a label is from a week at or before its own cutoff",
            observed=f"{leaks} rows",
            expected="0",
        ),
    )
    lined = frame.filter(pl.col("game_total_line").is_not_null()).height
    checks.append(
        QualityCheck.ok(
            "weekly_dataset.game_lines",
            stage="weekly_dataset",
            message="share of rows whose game carries a sportsbook total",
            observed=f"{lined}/{frame.height}",
        ),
    )
    return WeeklyDataset(frame=frame, checks=checks)


def describe(dataset: WeeklyDataset) -> dict[str, Any]:
    frame = dataset.frame
    return {
        "rows": frame.height,
        "seasons": list(dataset.seasons),
        "by_position": {
            str(row["position"]): int(row["len"])
            for row in frame.group_by("position").len().sort("position").iter_rows(named=True)
        },
        "features": len(WEEKLY_FEATURES),
        "context_columns": [*GAME_CONTEXT_COLUMNS, *OPPONENT_COLUMNS],
    }
