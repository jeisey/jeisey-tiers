"""The fantasy-season horizon.

`docs/MODELING.md` section 3 and `docs/DATA_CONTRACTS.md` section 5 fix one rule for every
label the project produces:

* 2021 onward - NFL Weeks 1-17 (the 18-week schedule, final week excluded);
* before 2021 - NFL Weeks 1-16 (the 17-week schedule, final week excluded).

The excluded week is the one where playoff-bound teams rest starters, so including it would
add noise that no preseason model can or should predict, and it is outside most fantasy
championship schedules anyway.

The consequence that matters for implementation: **season-level upstream totals cover the
full regular season and therefore cannot be the label.** Labels are aggregated from weekly
rows filtered to this horizon, which is why :mod:`ffdraft.scoring.engine` scores weeks.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "EIGHTEEN_WEEK_FIRST_SEASON",
    "FantasyHorizon",
    "fantasy_horizon",
    "horizon_weeks",
    "is_in_horizon",
    "regular_season_weeks",
]

#: The NFL moved from a 17-week to an 18-week regular season in 2021.
EIGHTEEN_WEEK_FIRST_SEASON = 2021

_REGULAR_SEASON_TYPE = "REG"


@dataclass(frozen=True, slots=True)
class FantasyHorizon:
    """The scored week range for one season, plus the NFL week it deliberately excludes."""

    season: int
    first_week: int
    last_week: int
    excluded_week: int
    regular_season_weeks: int

    @property
    def weeks(self) -> tuple[int, ...]:
        return tuple(range(self.first_week, self.last_week + 1))

    @property
    def week_count(self) -> int:
        return self.last_week - self.first_week + 1

    @property
    def season_type(self) -> str:
        """Only regular-season rows are scored; postseason is never a fantasy label."""
        return _REGULAR_SEASON_TYPE

    def contains(self, week: int) -> bool:
        return self.first_week <= week <= self.last_week

    def describe(self) -> str:
        return f"weeks {self.first_week}-{self.last_week} (excluding NFL week {self.excluded_week})"


def regular_season_weeks(season: int) -> int:
    """Number of regular-season weeks the NFL played in ``season``."""
    return 18 if season >= EIGHTEEN_WEEK_FIRST_SEASON else 17


def fantasy_horizon(season: int) -> FantasyHorizon:
    """The scored horizon for ``season``."""
    total = regular_season_weeks(season)
    return FantasyHorizon(
        season=season,
        first_week=1,
        last_week=total - 1,
        excluded_week=total,
        regular_season_weeks=total,
    )


def horizon_weeks(season: int) -> tuple[int, ...]:
    return fantasy_horizon(season).weeks


def is_in_horizon(season: int, week: int, season_type: str = _REGULAR_SEASON_TYPE) -> bool:
    """Whether one weekly row belongs in the fantasy label for ``season``."""
    return season_type == _REGULAR_SEASON_TYPE and fantasy_horizon(season).contains(week)
