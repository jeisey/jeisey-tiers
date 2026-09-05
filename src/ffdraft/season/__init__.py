"""Season state: which product mode the site is in, derived from the NFL schedule."""

from __future__ import annotations

from ffdraft.season.state import (
    GAME_COMPLETE_BUFFER_HOURS,
    SEASON_STATE_RULE_VERSION,
    ProductMode,
    SeasonCalendar,
    SeasonState,
    SeasonStateResolution,
    WeekWindow,
    build_season_calendar,
    resolve_season_state,
    season_state_from_schedule,
    season_state_summary,
)

__all__ = [
    "GAME_COMPLETE_BUFFER_HOURS",
    "SEASON_STATE_RULE_VERSION",
    "ProductMode",
    "SeasonCalendar",
    "SeasonState",
    "SeasonStateResolution",
    "WeekWindow",
    "build_season_calendar",
    "resolve_season_state",
    "season_state_from_schedule",
    "season_state_summary",
]
