"""Which product the site is: Draft, or In-Season. Derived, never dated.

`docs/RELEASE2_ROADMAP.md` 12.1 asks for "a versioned season-state rule using the NFL
schedule rather than hard-coded calendar guesses", and the distinction is the whole point of
this module. A constant like ``SEASON_START = date(2026, 9, 9)`` is correct for exactly one
season and silently wrong afterwards; it also cannot answer "is week 6 over?", which is the
question the rest-of-season build actually needs.

Everything here is therefore a function of two inputs: the published NFL schedule, and a
timestamp.

**The four states.**

``preseason_draft``
    Before the season's first regular-season kickoff. The draft product is the current
    product, and the preseason board is current intelligence.
``regular_season``
    From that kickoff. The rest-of-season board becomes the current product; the preseason
    board remains reachable and reproducible but stops being presented as current.
``fantasy_postseason``
    The last three scored weeks of the fantasy horizon. Same product as ``regular_season``;
    the state exists because a reader in week 16 wants to be told so.
``season_complete``
    Every scored week has been played. There is no remaining horizon, so there is no
    rest-of-season quantity left to estimate, and the board says so rather than publishing a
    board of zeros.

**When a week is over.** A week is complete :data:`GAME_COMPLETE_BUFFER_HOURS` after its last
scheduled kickoff. That is deliberately derived from kickoff times rather than from
``result``: a schedule row's result is an upstream *outcome* that lands whenever nflverse
publishes it, so a state machine reading it would change its mind about the past depending on
a release cadence. Kickoff times are published in May and do not move.

The buffer is generous on purpose. It decides only what this module calls "played"; whether
the *data* for that week exists upstream is a separate question with its own gate
(:mod:`ffdraft.ros.freshness`), and a rest-of-season build needs both to say yes.

**The transition is the kickoff, not the first completed week.** Roadmap 12.1: "The first
regular-season kickoff transitions the default product from Draft to In-Season." So the mode
flips at kickoff, while ``completed_week`` stays 0 until that week finishes — which is the
correct shape for the several days in week 1 when the draft is over but no game has finished.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from ffdraft.anchors import ANCHOR_TIMEZONE, AnchorError
from ffdraft.scoring.horizon import FantasyHorizon, fantasy_horizon

__all__ = [
    "FANTASY_POSTSEASON_WEEKS",
    "GAME_COMPLETE_BUFFER_HOURS",
    "SEASON_STATE_RULE_VERSION",
    "ProductMode",
    "SeasonCalendar",
    "SeasonState",
    "SeasonStateResolution",
    "WeekWindow",
    "build_season_calendar",
    "resolve_season_state",
]

#: Bump when the meaning of a state changes. Travels on every build's metadata, so a board
#: can be read against the rule that produced it.
SEASON_STATE_RULE_VERSION = "season_state_v1"

#: How long after its last scheduled kickoff a week counts as played. Six hours comfortably
#: covers a regulation game plus overtime plus a delayed start; it is a floor on "the games
#: are over", not an estimate of when data arrives.
GAME_COMPLETE_BUFFER_HOURS = 6

#: How many of the horizon's final weeks are the fantasy postseason. Three is the near
#: universal redraft convention and it is a **product** convention rather than a schedule
#: fact, so it is stated once, here, and derived from the horizon's own last week rather
#: than written as "weeks 15-17" - which would be wrong for every season before 2021.
FANTASY_POSTSEASON_WEEKS = 3

_REGULAR_SEASON = "REG"
_EASTERN = ZoneInfo(ANCHOR_TIMEZONE)
_MIDNIGHT_FALLBACK = "00:00"


class SeasonState(StrEnum):
    """Where a season is, as a function of the schedule and the clock."""

    PRESEASON_DRAFT = "preseason_draft"
    REGULAR_SEASON = "regular_season"
    FANTASY_POSTSEASON = "fantasy_postseason"
    SEASON_COMPLETE = "season_complete"

    @property
    def mode(self) -> ProductMode:
        return ProductMode.DRAFT if self is SeasonState.PRESEASON_DRAFT else ProductMode.IN_SEASON

    @property
    def description(self) -> str:
        if self is SeasonState.PRESEASON_DRAFT:
            return "before the season's first regular-season kickoff"
        if self is SeasonState.REGULAR_SEASON:
            return "the regular season is under way"
        if self is SeasonState.FANTASY_POSTSEASON:
            return "the last three scored weeks of the fantasy horizon"
        return "every scored week has been played; no remaining horizon exists"


class ProductMode(StrEnum):
    """The two product modes Release 2 ships."""

    DRAFT = "draft"
    IN_SEASON = "in_season"

    @property
    def label(self) -> str:
        return "Draft" if self is ProductMode.DRAFT else "In-Season"


@dataclass(frozen=True, slots=True)
class WeekWindow:
    """One regular-season week's schedule window, in UTC."""

    week: int
    first_kickoff_utc: datetime
    last_kickoff_utc: datetime
    games: int

    @property
    def complete_at_utc(self) -> datetime:
        return self.last_kickoff_utc + timedelta(hours=GAME_COMPLETE_BUFFER_HOURS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "games": self.games,
            "first_kickoff_utc": _iso(self.first_kickoff_utc),
            "last_kickoff_utc": _iso(self.last_kickoff_utc),
            "complete_at_utc": _iso(self.complete_at_utc),
        }


@dataclass(frozen=True)
class SeasonCalendar:
    """Every regular-season week of one season, with its kickoff window."""

    season: int
    weeks: tuple[WeekWindow, ...]
    horizon: FantasyHorizon

    def __post_init__(self) -> None:
        if not self.weeks:
            raise AnchorError(f"{self.season}: schedule has no regular-season games")

    @property
    def first_kickoff_utc(self) -> datetime:
        return self.weeks[0].first_kickoff_utc

    @property
    def fantasy_postseason_first_week(self) -> int:
        return max(self.horizon.first_week, self.horizon.last_week - FANTASY_POSTSEASON_WEEKS + 1)

    def window(self, week: int) -> WeekWindow | None:
        for candidate in self.weeks:
            if candidate.week == week:
                return candidate
        return None

    def completed_week(self, as_of: datetime) -> int:
        """The highest **scored** week whose games are over at ``as_of``; 0 before any.

        Bounded by the fantasy horizon rather than by the schedule: NFL week 18 exists and
        is deliberately outside every label this project produces, so calling it "completed
        week 18" would invite a snapshot the cutoff rule refuses.
        """
        stamped = as_of.astimezone(UTC)
        completed = 0
        for window in self.weeks:
            if window.week > self.horizon.last_week:
                continue
            if window.complete_at_utc <= stamped:
                completed = max(completed, window.week)
        return completed

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "regular_season_weeks": len(self.weeks),
            "horizon": self.horizon.describe(),
            "horizon_first_week": self.horizon.first_week,
            "horizon_last_week": self.horizon.last_week,
            "fantasy_postseason_first_week": self.fantasy_postseason_first_week,
            "first_kickoff_utc": _iso(self.first_kickoff_utc),
            "game_complete_buffer_hours": GAME_COMPLETE_BUFFER_HOURS,
        }


@dataclass(frozen=True)
class SeasonStateResolution:
    """One deterministic answer: what state the season is in, and which product that is."""

    season: int
    as_of_utc: datetime
    state: SeasonState
    completed_week: int
    calendar: SeasonCalendar
    rule_version: str = SEASON_STATE_RULE_VERSION

    @property
    def mode(self) -> ProductMode:
        return self.state.mode

    @property
    def latest_snapshot_week(self) -> int | None:
        """The deepest rest-of-season snapshot the cutoff rule permits right now.

        ``None`` before the first week is complete, and ``None`` once the horizon is spent:
        `ros_cutoff_v1` refuses week 0 (that is the preseason model's grain) and refuses a
        snapshot with no remaining weeks to predict.
        """
        if self.completed_week < 1:
            return None
        if self.completed_week > self.calendar.horizon.last_week - 1:
            return None
        return self.completed_week

    @property
    def next_transition_utc(self) -> datetime | None:
        """When this answer next changes, so a caller can say so rather than poll blindly."""
        stamped = self.as_of_utc.astimezone(UTC)
        if self.state is SeasonState.PRESEASON_DRAFT:
            return self.calendar.first_kickoff_utc
        for window in self.calendar.weeks:
            if window.week > self.calendar.horizon.last_week:
                continue
            if window.complete_at_utc > stamped:
                return window.complete_at_utc
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_version": self.rule_version,
            "season": self.season,
            "as_of_utc": _iso(self.as_of_utc),
            "season_state": str(self.state),
            "season_state_description": self.state.description,
            "product_mode": str(self.mode),
            "completed_week": self.completed_week,
            "latest_snapshot_week": self.latest_snapshot_week,
            "next_transition_utc": (
                _iso(self.next_transition_utc) if self.next_transition_utc else None
            ),
            "calendar": self.calendar.to_dict(),
            "derivation": (
                "the product mode is the season's first regular-season kickoff and nothing "
                "else; a week counts as played "
                f"{GAME_COMPLETE_BUFFER_HOURS}h after its last scheduled kickoff"
            ),
        }


def build_season_calendar(schedule: pl.DataFrame, season: int) -> SeasonCalendar:
    """Every regular-season week of ``season``, in week order, from the published schedule."""
    rows = schedule.filter(
        (pl.col("season") == season) & (pl.col("game_type") == _REGULAR_SEASON),
    )
    if rows.is_empty():
        raise AnchorError(f"{season}: schedule has no regular-season games")

    by_week: dict[int, list[datetime]] = {}
    for record in rows.iter_rows(named=True):
        week = record.get("week")
        gameday = record.get("gameday")
        if week is None or gameday is None:
            continue
        day = gameday if isinstance(gameday, date) else _parse_date(str(gameday))
        if day is None:
            continue
        # A missing kickoff time makes the window *earlier*, which would call a week
        # complete too soon, so an unknown time is treated as the end of the day instead:
        # every ambiguity here resolves towards "not yet played".
        moment = datetime.combine(
            day,
            _parse_time(record.get("gametime")) or _end_of_day(),
            tzinfo=_EASTERN,
        ).astimezone(UTC)
        by_week.setdefault(int(week), []).append(moment)

    weeks = tuple(
        WeekWindow(
            week=week,
            first_kickoff_utc=min(moments),
            last_kickoff_utc=max(moments),
            games=len(moments),
        )
        for week, moments in sorted(by_week.items())
        if moments
    )
    return SeasonCalendar(season=season, weeks=weeks, horizon=fantasy_horizon(season))


def resolve_season_state(
    calendar: SeasonCalendar,
    as_of: datetime,
) -> SeasonStateResolution:
    """Apply `season_state_v1` to a calendar and a timestamp. Pure; no I/O, no clock."""
    stamped = as_of.astimezone(UTC)
    completed = calendar.completed_week(stamped)
    horizon = calendar.horizon

    if stamped < calendar.first_kickoff_utc:
        state = SeasonState.PRESEASON_DRAFT
    elif completed >= horizon.last_week:
        state = SeasonState.SEASON_COMPLETE
    elif completed + 1 >= calendar.fantasy_postseason_first_week:
        # The week now in progress is the first fantasy-postseason week or later. Stated on
        # the week being *played* rather than the last one finished, because a reader on the
        # Sunday of week 15 is in the fantasy postseason, not still in week 14.
        state = SeasonState.FANTASY_POSTSEASON
    else:
        state = SeasonState.REGULAR_SEASON

    return SeasonStateResolution(
        season=calendar.season,
        as_of_utc=stamped,
        state=state,
        completed_week=completed,
        calendar=calendar,
    )


def season_state_from_schedule(
    schedule: pl.DataFrame,
    *,
    season: int,
    as_of: datetime,
) -> SeasonStateResolution:
    """Convenience: build the calendar and resolve in one call."""
    return resolve_season_state(build_season_calendar(schedule, season), as_of)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _parse_time(value: object) -> Any:
    from datetime import time

    if value is None:
        return None
    if isinstance(value, time):
        return value
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def _end_of_day() -> Any:
    from datetime import time

    return time(23, 59, 59)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def season_state_summary(seasons: Sequence[int]) -> dict[str, Any]:
    """The rule, without any data. Written into documentation and build metadata."""
    return {
        "rule_version": SEASON_STATE_RULE_VERSION,
        "states": {str(state): state.description for state in SeasonState},
        "modes": {str(state): str(state.mode) for state in SeasonState},
        "game_complete_buffer_hours": GAME_COMPLETE_BUFFER_HOURS,
        "fantasy_postseason_weeks": FANTASY_POSTSEASON_WEEKS,
        "seasons": list(seasons),
    }
