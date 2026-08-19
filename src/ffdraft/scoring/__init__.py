"""The one authoritative fantasy scoring implementation and its season horizon."""

from __future__ import annotations

from ffdraft.scoring.engine import (
    SCORING_ENGINE_VERSION,
    STAT_COMPONENTS,
    StatLine,
    points_expression,
    reconcile_with_upstream,
    score_stat_line,
    score_weekly_frame,
    season_totals,
)
from ffdraft.scoring.horizon import (
    EIGHTEEN_WEEK_FIRST_SEASON,
    FantasyHorizon,
    fantasy_horizon,
    horizon_weeks,
    is_in_horizon,
    regular_season_weeks,
)

__all__ = [
    "EIGHTEEN_WEEK_FIRST_SEASON",
    "SCORING_ENGINE_VERSION",
    "STAT_COMPONENTS",
    "FantasyHorizon",
    "StatLine",
    "fantasy_horizon",
    "horizon_weeks",
    "is_in_horizon",
    "points_expression",
    "reconcile_with_upstream",
    "regular_season_weeks",
    "score_stat_line",
    "score_weekly_frame",
    "season_totals",
]
