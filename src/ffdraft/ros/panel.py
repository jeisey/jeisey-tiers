"""The dense weekly panel every rest-of-season quantity is read off.

One row per ``(season, gsis_id, week)`` for every week in the fantasy horizon, whether or
not the player appeared. The density is the point: "points scored through week 6" has to be
zero rather than missing for a player who has not played, and "the player's team in week 6"
has to be the last team actually observed rather than a team taken from week 14.

Everything downstream is a cumulative read of this panel:

* :mod:`ffdraft.ros.labels` sums the weeks **after** the cutoff;
* :mod:`ffdraft.ros.features` sums, averages and windows the weeks **through** the cutoff.

Two rules are enforced here rather than trusted to callers.

**Only scored regular-season weeks exist.** The panel is built from the same filter
:func:`ffdraft.scoring.engine.season_totals` applies - ``season_type == "REG"`` inside
:func:`ffdraft.scoring.horizon.fantasy_horizon` - so no cumulative quantity can quietly
include the excluded final NFL week or a playoff game.

**Point-in-time identity columns are carried forward, never backward.** ``team`` and
``position`` at week N are the last values observed at or before week N. A player with no
observation yet carries null, which is a fact about week N, not a gap to be filled from the
future.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.scoring.engine import STAT_COMPONENTS, score_weekly_frame
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "OPPORTUNITY_COMPONENTS",
    "PANEL_VERSION",
    "build_weekly_panel",
    "carry_forward",
    "horizon_weekly_rows",
    "team_weekly_totals",
]

#: Bump when the panel's construction changes in a way that moves a cumulative value.
PANEL_VERSION = "ros_weekly_panel_v1"

#: Volume columns beyond the scorable components. Fantasy points measure what happened;
#: these measure how many chances a player was given, which is the half that persists.
OPPORTUNITY_COMPONENTS: tuple[str, ...] = (
    "pass_attempts",
    "completions",
    "passing_air_yards",
    "carries",
    "targets",
    "receiving_air_yards",
)

_IDENTITY_COLUMNS: tuple[str, ...] = ("team", "position")


def horizon_weekly_rows(weekly: pl.DataFrame, seasons: Sequence[int]) -> pl.DataFrame:
    """The scorable weekly rows for ``seasons``: regular season, inside the horizon."""
    wanted = [int(season) for season in seasons]
    if weekly.is_empty() or not wanted:
        return weekly.clear()
    in_horizon = pl.lit(False)
    for season in wanted:
        horizon = fantasy_horizon(season)
        in_horizon = in_horizon | (
            (pl.col("season") == season)
            & (pl.col("week") >= horizon.first_week)
            & (pl.col("week") <= horizon.last_week)
        )
    return weekly.filter(
        pl.col("season").is_in(wanted) & (pl.col("season_type") == "REG") & in_horizon,
    )


def team_weekly_totals(rows: pl.DataFrame) -> pl.DataFrame:
    """Per ``(season, week, team)`` offensive volume, from the same weekly rows.

    Team context is derived from the player rows rather than from a separate team table so
    that a player's share of his team is a ratio of two numbers with identical provenance;
    a share built from two sources disagrees at the edges for reasons no feature should carry.
    """
    if rows.is_empty():
        return pl.DataFrame(
            schema={
                "season": pl.Int32,
                "week": pl.Int32,
                "team": pl.String,
                "team_pass_attempts": pl.Float64,
                "team_carries": pl.Float64,
                "team_targets": pl.Float64,
                "team_points_std": pl.Float64,
            },
        )
    return (
        rows.filter(pl.col("team").is_not_null())
        .group_by("season", "week", "team")
        .agg(
            pl.col("pass_attempts").sum().alias("team_pass_attempts"),
            pl.col("carries").sum().alias("team_carries"),
            pl.col("targets").sum().alias("team_targets"),
            pl.col("fantasy_points_STD").sum().alias("team_points_std"),
        )
        .sort("season", "week", "team")
    )


def build_weekly_panel(
    weekly: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    *,
    seasons: Sequence[int],
    universe: pl.DataFrame,
    snap_counts: pl.DataFrame | None = None,
    expected_points: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Build the dense panel.

    ``universe`` supplies ``(season, gsis_id)`` pairs that must exist even if the player
    never appears - the preseason-eligible players whose zero seasons are exactly the rows a
    survivorship-free dataset needs. Players who appear in the weekly rows but not in
    ``universe`` are added, because a mid-season arrival is visible at any cutoff after his
    first game and excluding him would make the in-season universe smaller than reality.
    """
    wanted = sorted({int(season) for season in seasons})
    presets = sorted(scoring)
    point_columns = [f"fantasy_points_{preset}" for preset in presets]

    rows = horizon_weekly_rows(weekly, wanted)
    scored = score_weekly_frame(rows, scoring) if not rows.is_empty() else rows
    if not scored.is_empty():
        scored = scored.select(
            "season",
            "week",
            "gsis_id",
            "team",
            "position",
            *STAT_COMPONENTS,
            *(name for name in OPPORTUNITY_COMPONENTS if name not in STAT_COMPONENTS),
            *point_columns,
        ).with_columns(pl.lit(1, dtype=pl.Int32).alias("played"))

    teams = team_weekly_totals(scored)

    members = _panel_members(scored, universe, wanted)
    weeks = pl.DataFrame(
        {
            "season": [season for season in wanted for _ in fantasy_horizon(season).weeks],
            "week": [week for season in wanted for week in fantasy_horizon(season).weeks],
        },
        schema={"season": pl.Int32, "week": pl.Int32},
    )
    grid = members.join(weeks, on="season", how="inner")

    panel = grid.join(scored, on=["season", "week", "gsis_id"], how="left")
    if "played" not in panel.columns:
        panel = panel.with_columns(pl.lit(0, dtype=pl.Int32).alias("played"))
    # A week with no upstream row is a week the player did not appear in, which is a zero
    # rather than an unknown: the panel is dense precisely so that "has not played" and
    # "we have no idea" are not the same value.
    panel = panel.with_columns(pl.col("played").fill_null(0).cast(pl.Int32))

    numeric = [
        *STAT_COMPONENTS,
        *(name for name in OPPORTUNITY_COMPONENTS if name not in STAT_COMPONENTS),
        *point_columns,
    ]
    panel = panel.with_columns(
        [pl.col(name).cast(pl.Float64).fill_null(0.0) for name in numeric],
    )

    panel = _attach_snaps(panel, snap_counts)
    panel = _attach_expected_points(panel, expected_points)
    panel = panel.join(teams, on=["season", "week", "team"], how="left")

    return panel.sort("season", "gsis_id", "week")


def _panel_members(
    scored: pl.DataFrame,
    universe: pl.DataFrame,
    seasons: Sequence[int],
) -> pl.DataFrame:
    """Every ``(season, gsis_id)`` the panel must carry a full week grid for."""
    frames: list[pl.DataFrame] = []
    if not universe.is_empty():
        frames.append(
            universe.filter(pl.col("season").is_in(list(seasons)))
            .select(pl.col("season").cast(pl.Int32), pl.col("gsis_id").cast(pl.String))
            .unique(),
        )
    if not scored.is_empty():
        frames.append(
            scored.select(
                pl.col("season").cast(pl.Int32),
                pl.col("gsis_id").cast(pl.String),
            ).unique(),
        )
    if not frames:
        return pl.DataFrame(schema={"season": pl.Int32, "gsis_id": pl.String})
    return pl.concat(frames).unique().sort("season", "gsis_id")


def _attach_snaps(panel: pl.DataFrame, snap_counts: pl.DataFrame | None) -> pl.DataFrame:
    """Weekly offensive snap participation, keyed through the gsis bridge upstream."""
    if snap_counts is None or snap_counts.is_empty() or "gsis_id" not in snap_counts.columns:
        return panel.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("offense_snaps"),
            pl.lit(None, dtype=pl.Float64).alias("offense_pct"),
        )
    weekly_snaps = (
        snap_counts.filter(pl.col("gsis_id").is_not_null() & (pl.col("game_type") == "REG"))
        .group_by("season", "week", "gsis_id")
        .agg(
            pl.col("offense_snaps").sum().alias("offense_snaps"),
            pl.col("offense_pct").max().alias("offense_pct"),
        )
    )
    return panel.join(weekly_snaps, on=["season", "week", "gsis_id"], how="left")


def _attach_expected_points(
    panel: pl.DataFrame,
    expected_points: pl.DataFrame | None,
) -> pl.DataFrame:
    """ffopportunity's weekly expected fantasy points, an opportunity measure not an outcome."""
    if expected_points is None or expected_points.is_empty():
        return panel.with_columns(pl.lit(None, dtype=pl.Float64).alias("expected_points"))
    weekly_expected = (
        expected_points.filter(pl.col("gsis_id").is_not_null())
        .group_by("season", "week", "gsis_id")
        .agg(pl.col("expected_points").sum().alias("expected_points"))
    )
    return panel.join(weekly_expected, on=["season", "week", "gsis_id"], how="left")


def carry_forward(panel: pl.DataFrame, columns: Sequence[str] = _IDENTITY_COLUMNS) -> pl.DataFrame:
    """Forward-fill point-in-time identity columns within a player-season.

    Only forward: week N may see week N-1's team, never week N+1's.
    """
    return panel.sort("season", "gsis_id", "week").with_columns(
        [
            pl.col(name).forward_fill().over("season", "gsis_id").alias(f"{name}_to_date")
            for name in columns
        ],
    )
