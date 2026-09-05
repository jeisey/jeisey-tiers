"""Is week N's data actually here? The gate a rest-of-season build has to pass first.

`ffdraft/ros/cutoff.py` ends with the sentence this module implements:

> The operational counterpart lives in `docs/OPERATIONS.md`: a production week-N snapshot may
> only be built once the upstream weekly release covering week N exists, because the rule
> says "week N is *available*", not "week N has been played".

Phase 11 documented that and left it for Phase 12 to enforce, because Phase 11 published
nothing. Phase 12 publishes, so the rule needs a gate rather than a paragraph.

**Why "played" is not enough.** :mod:`ffdraft.season.state` answers "are the games over?" from
kickoff times alone, which is exactly right for deciding what product the site is. It is not
enough to decide what to *compute*: nflverse publishes its weekly player statistics on its own
cadence, so there is a window - hours on a good week, longer on a bad one - in which the games
are over and the rows are not there yet. A build that trusted the clock in that window would
produce a week-N board from week-(N-1) data and label it week N. Every number would be wrong
by one week and nothing would look broken.

**What completeness means here.** A week is complete when every team that the schedule says
played in it appears in the weekly statistics for that week. That is a comparison between two
upstream sources rather than a threshold anyone picked: the schedule names 32 clubs across a
week's games, and a released week names all of them. A partial release - one late game, one
club missing - fails, which is the intended outcome, because a partially released week is
exactly the shape that produces a plausible wrong board.

The gate returns the deepest week that satisfies both conditions and refuses to skip a hole:
if week 5 is complete and week 4 is not, the answer is 3. A rest-of-season feature is a
cumulative quantity over weeks 1..N, so a missing interior week is not a gap in the output,
it is a silently smaller total.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity, normalize_team_code
from ffdraft.ros.cutoff import FIRST_THROUGH_WEEK
from ffdraft.season.state import SeasonCalendar, SeasonStateResolution

__all__ = [
    "ROS_FRESHNESS_RULE_VERSION",
    "RosSourceFreshness",
    "WeekAvailability",
    "assess_ros_freshness",
]

#: Bump when the meaning of "week N is available" changes.
ROS_FRESHNESS_RULE_VERSION = "ros_source_freshness_v1"

_REGULAR_SEASON = "REG"


@dataclass(frozen=True, slots=True)
class WeekAvailability:
    """One week's verdict, with the evidence that produced it.

    The two team fields are **sets**, not counts. A count proves the totals match, which is
    a weaker statement than the rule this module documents: a week that lost Buffalo and
    gained a stray postseason row for Miami has the right total and the wrong membership,
    and a cumulative rest-of-season feature built over it would be quietly short by one
    club's games. The missing names are kept so the diagnostic says which club, not how many.
    """

    week: int
    scheduled: frozenset[str]
    observed: frozenset[str]
    player_rows: int
    games_complete: bool

    @property
    def scheduled_teams(self) -> int:
        return len(self.scheduled)

    @property
    def observed_teams(self) -> int:
        return len(self.observed)

    @property
    def missing_teams(self) -> tuple[str, ...]:
        """Clubs the schedule says played that the weekly statistics do not carry."""
        return tuple(sorted(self.scheduled - self.observed))

    @property
    def unexpected_teams(self) -> tuple[str, ...]:
        """Clubs in the statistics that the schedule does not place in this week.

        Not a failure on its own — it is the evidence that would distinguish a vocabulary
        drift from a genuinely absent club, and reporting it is what makes the missing list
        actionable rather than mysterious.
        """
        return tuple(sorted(self.observed - self.scheduled))

    @property
    def teams_missing(self) -> int:
        return len(self.missing_teams)

    @property
    def data_complete(self) -> bool:
        return bool(self.scheduled) and not (self.scheduled - self.observed)

    @property
    def available(self) -> bool:
        return self.games_complete and self.data_complete

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "scheduled_teams": self.scheduled_teams,
            "observed_teams": self.observed_teams,
            "teams_missing": self.teams_missing,
            "missing_teams": list(self.missing_teams),
            "unexpected_teams": list(self.unexpected_teams),
            "player_rows": self.player_rows,
            "games_complete": self.games_complete,
            "data_complete": self.data_complete,
            "available": self.available,
        }


@dataclass(frozen=True)
class RosSourceFreshness:
    """The deepest buildable snapshot week, and why it is not deeper."""

    season: int
    as_of_utc: datetime
    weeks: tuple[WeekAvailability, ...]
    completed_week: int
    rule_version: str = ROS_FRESHNESS_RULE_VERSION

    @property
    def available_through_week(self) -> int:
        """The deepest week N with every week ``1..N`` available. 0 when none is."""
        deepest = 0
        for week in range(FIRST_THROUGH_WEEK, self.completed_week + 1):
            entry = self.week(week)
            if entry is None or not entry.available:
                break
            deepest = week
        return deepest

    @property
    def buildable(self) -> bool:
        return self.available_through_week >= FIRST_THROUGH_WEEK

    @property
    def blocking_week(self) -> int | None:
        """The first week the games are over for but the data is not complete."""
        for week in range(FIRST_THROUGH_WEEK, self.completed_week + 1):
            entry = self.week(week)
            if entry is None or not entry.available:
                return week
        return None

    @property
    def awaiting_first_week(self) -> bool:
        """Nothing is buildable yet, and that is the ordinary opening-week wait.

        The season has kicked off but at most one week has been played and its statistics
        have not landed. That is a **lifecycle state**, not a source failure: nflverse
        publishes on its own cadence and the first board of a season simply does not exist
        until the first week does. It is told apart from a real outage by how many weeks have
        been played — two completed weeks with nothing available is not a publication lag.
        """
        return not self.buildable and self.completed_week <= FIRST_THROUGH_WEEK

    def week(self, week: int) -> WeekAvailability | None:
        for entry in self.weeks:
            if entry.week == week:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_version": self.rule_version,
            "season": self.season,
            "as_of_utc": self.as_of_utc.isoformat().replace("+00:00", "Z"),
            "schedule_completed_week": self.completed_week,
            "available_through_week": self.available_through_week,
            "blocking_week": self.blocking_week,
            "buildable": self.buildable,
            "weeks": [entry.to_dict() for entry in self.weeks],
            "rule": (
                "a week is available when its games are over and every team the schedule "
                "says played in it appears in the weekly player statistics; the deepest "
                "buildable snapshot is the last week with no gap behind it"
            ),
        }

    def checks(self, *, stage: str = "ros_build") -> list[QualityCheck]:
        """The gate itself.

        Three outcomes rather than two, because "no board" has two very different causes:

        * **The opening-week wait.** The season has started and week 1 is not published yet.
          Expected, deterministic, and over within days — a *warning*, so the refresh stays
          green and the draft board keeps deploying while the first ROS board is waited for.
        * **A real outage.** Two or more weeks have been played and not one of them is
          available upstream. That is not a cadence, and it stays **critical**.
        * **A shallow board.** The current week is not published, so the board is built at the
          last complete week. A warning, and the board is real.
        """
        results: list[QualityCheck] = []
        if not self.buildable:
            waiting = self.awaiting_first_week
            results.append(
                QualityCheck.fail(
                    "ros.awaiting_first_week" if waiting else "ros.no_complete_week",
                    stage=stage,
                    message=(
                        (
                            "the season has started and week 1's upstream data has not been "
                            "published yet, so there is no rest-of-season board to build; the "
                            "draft board remains the current product until there is"
                        )
                        if waiting
                        else (
                            "no rest-of-season snapshot can be built: weeks have been played "
                            "and none of them is complete upstream, and the cutoff rule "
                            "refuses week 0"
                        )
                    ),
                    observed=(
                        f"schedule completed week {self.completed_week}; "
                        f"available through week {self.available_through_week}"
                        + (
                            f"; week {self.blocking_week} missing {', '.join(entry.missing_teams)}"
                            if (entry := self.week(self.blocking_week or 0)) is not None
                            and entry.missing_teams
                            else ""
                        )
                    ),
                    expected=f"at least week {FIRST_THROUGH_WEEK} available",
                    severity=Severity.WARNING if waiting else Severity.CRITICAL,
                ),
            )
            return results

        results.append(
            QualityCheck.ok(
                "ros.source_freshness",
                stage=stage,
                message=(
                    f"weekly data is complete through week {self.available_through_week}; "
                    f"the snapshot is built at that cutoff ({self.rule_version})"
                ),
                observed=(
                    f"schedule completed week {self.completed_week}; "
                    f"available through week {self.available_through_week}"
                ),
            ),
        )
        blocking = self.blocking_week
        if blocking is not None:
            entry = self.week(blocking)
            results.append(
                QualityCheck.fail(
                    "ros.upstream_week_incomplete",
                    stage=stage,
                    message=(
                        f"week {blocking}'s games are over but its upstream data is not "
                        "complete, so the board is built at the last complete week rather "
                        "than at the current one"
                    ),
                    observed=(
                        f"week {blocking}: {entry.observed_teams if entry else 0} of "
                        f"{entry.scheduled_teams if entry else 0} team(s) present"
                        + (
                            f"; missing {', '.join(entry.missing_teams)}"
                            if entry and entry.missing_teams
                            else ""
                        )
                        + (
                            f"; unexpected {', '.join(entry.unexpected_teams)}"
                            if entry and entry.unexpected_teams
                            else ""
                        )
                    ),
                    expected="every scheduled team present in the weekly statistics",
                    severity=Severity.WARNING,
                ),
            )
        return results


def assess_ros_freshness(
    *,
    state: SeasonStateResolution,
    weekly_stats: pl.DataFrame,
) -> RosSourceFreshness:
    """Measure which weeks of ``state.season`` are genuinely available.

    ``weekly_stats`` is the normalized nflverse weekly player frame. Only regular-season
    rows count: a postseason row is not part of any label this project produces, and letting
    one satisfy a week would be the same class of error as reading NFL week 18.
    """
    calendar: SeasonCalendar = state.calendar
    season = state.season
    scheduled = _scheduled_teams_by_week(calendar)

    observed: dict[int, tuple[frozenset[str], int]] = {}
    if not weekly_stats.is_empty():
        scoped = weekly_stats.filter(
            (pl.col("season") == season) & (pl.col("season_type") == _REGULAR_SEASON),
        )
        if not scoped.is_empty():
            grouped = scoped.group_by("week").agg(
                pl.col("team").unique().alias("teams"),
                pl.len().alias("rows"),
            )
            for row in grouped.iter_rows(named=True):
                clubs = {
                    code
                    for code in (normalize_team_code(value) for value in row["teams"])
                    if code is not None
                }
                observed[int(row["week"])] = (frozenset(clubs), int(row["rows"]))

    entries: list[WeekAvailability] = []
    for week in sorted(scheduled):
        if week > calendar.horizon.last_week:
            continue
        window = calendar.window(week)
        teams, rows = observed.get(week, (frozenset(), 0))
        entries.append(
            WeekAvailability(
                week=week,
                scheduled=scheduled[week],
                observed=teams,
                player_rows=rows,
                games_complete=(window is not None and window.complete_at_utc <= state.as_of_utc),
            ),
        )

    return RosSourceFreshness(
        season=season,
        as_of_utc=state.as_of_utc,
        weeks=tuple(entries),
        completed_week=state.completed_week,
    )


def _scheduled_teams_by_week(calendar: SeasonCalendar) -> dict[int, frozenset[str]]:
    """Which clubs the schedule says played each week, by name.

    Names rather than a count: ``games * 2`` is an exact *total* and proves nothing about
    membership, and membership is what this gate claims to check. Both sides go through
    :func:`normalize_team_code`, so a relocated franchise's historical abbreviation matches
    its current one instead of reading as a missing club.
    """
    return {window.week: window.teams for window in calendar.weeks}
