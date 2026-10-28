"""The facts every story reads: one line per player per appearance, with exact components.

Nothing here is a new definition. An **appearance** and its **points** are season actuals'
(``season_actuals_v1``: a stats row or an offensive snap, the scoring engine's points summed in
exact hundredths), assembled by recent form's own :func:`ffdraft.signals.recent._season_games`
so a story's weekly points equal the published ``recent_form.span_points``. **Team totals** are
summed from the same player rows, as ``usage_signals_v1`` does. **Touchdown points** use the
usage layer's definition (passing, rushing and receiving touchdowns times the preset's values).
**Red zone** and **inside the five** count the plays drive breadth already reduces
(:func:`ffdraft.signals.drive_play.drive_plays`), and are published only when every scheduled
team-week in scope is present in play-by-play — otherwise they are absent, never partial.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts.enums import normalize_team_code
from ffdraft.identity.ids import IdNamespace, make_player_id
from ffdraft.scoring.engine import score_weekly_frame
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.signals.actuals import _scheduled_teams, _scoped_stats
from ffdraft.signals.recent import (
    BYE,
    DID_NOT_PLAY,
    PLAYED,
    RecentGame,
    _season_games,
    _teams_by_week,
    window_weeks,
)

__all__ = ["Line", "SeasonFacts", "TeamWeek", "build_facts", "competition_rank_of", "pooled"]


@dataclass(slots=True)
class Line:
    """One appearance. Counts are zero on a snaps-only week, which is an observation."""

    week: int
    team: str | None
    points: dict[str, float]
    td_points: dict[str, float]
    targets: float
    carries: float
    pass_attempts: float = 0.0
    team_pass_attempts: float | None = None
    receptions: float = 0.0
    receiving_yards: float = 0.0
    rushing_yards: float = 0.0
    touchdowns: float = 0.0
    snap_share: float | None = None
    team_targets: float | None = None
    team_carries: float | None = None
    red_zone_targets: int | None = None
    red_zone_carries: int | None = None
    inside_five_targets: int | None = None
    inside_five_carries: int | None = None

    def opportunities(self, position: str) -> float:
        """Targets, plus carries for a running back."""
        return self.targets + (self.carries if position == "RB" else 0.0)

    def team_opportunities(self, position: str) -> float | None:
        if self.team_targets is None:
            return None
        if position == "RB":
            return None if self.team_carries is None else self.team_targets + self.team_carries
        return self.team_targets

    def yards(self, position: str) -> float:
        return self.receiving_yards + (self.rushing_yards if position == "RB" else 0.0)

    def red_zone(self, position: str) -> int | None:
        if self.red_zone_targets is None:
            return None
        return self.red_zone_targets + ((self.red_zone_carries or 0) if position == "RB" else 0)


@dataclass(slots=True)
class TeamWeek:
    """Team-level play-by-play counts for one (week, team)."""

    red_zone_targets: int = 0
    red_zone_carries: int = 0
    inside_five_targets: int = 0
    inside_five_carries: int = 0


@dataclass(slots=True)
class SeasonFacts:
    season: int
    last_week: int
    first_week: int
    window: list[int]
    baseline: list[int]
    presets: list[str]
    lines: dict[str, dict[int, Line]]
    games: dict[str, dict[int, RecentGame]]
    positions: dict[str, str]
    scheduled: dict[int, set[str]]
    team_weeks: dict[tuple[int, str], TeamWeek] = field(default_factory=dict)
    pbp_state: str = "unavailable"
    pbp_detail: str | None = None

    def weeks(self) -> list[int]:
        return list(range(self.first_week, self.last_week + 1))

    def teams_by_week(self, player_id: str) -> dict[int, str | None]:
        return _teams_by_week(self.games.get(player_id, {}), self.weeks())

    def status(self, player_id: str, week: int) -> str:
        """``P`` played, ``B`` his team had no game, ``D`` his team played without him."""
        if week in self.lines.get(player_id, {}):
            return PLAYED
        team = self.teams_by_week(player_id).get(week)
        if team is None or team not in self.scheduled.get(week, set()):
            return BYE
        return DID_NOT_PLAY

    def played(self, player_id: str, weeks: Iterable[int]) -> list[Line]:
        by_week = self.lines.get(player_id, {})
        return [by_week[week] for week in weeks if week in by_week]

    def recent_games(self, player_id: str, weeks: Iterable[int]) -> list[RecentGame]:
        by_week = self.games.get(player_id, {})
        return [by_week[week] for week in weeks if week in by_week]

    def missed_after(self, player_id: str, week: int) -> int:
        """Team games he missed (``D``, never a bye) after ``week`` through the cutoff."""
        return sum(
            1
            for later in range(week + 1, self.last_week + 1)
            if self.status(player_id, later) == DID_NOT_PLAY
        )

    @property
    def red_zone_available(self) -> bool:
        return self.pbp_state == "available"


def competition_rank_of(values: Mapping[str, int], key: str) -> int | None:
    """``key``'s competition rank by value descending (ties share the best rank), or None."""
    if key not in values:
        return None
    mine = values[key]
    return 1 + sum(1 for value in values.values() if value > mine)


def _touchdown_points(row: Mapping[str, Any], rules: ScoringRules) -> float:
    """``usage_signals_v1``'s definition: touchdowns times the preset's touchdown values."""

    def count(name: str) -> float:
        return float(row.get(name) or 0.0)

    return (
        count("passing_tds") * rules.passing_td
        + count("rushing_tds") * rules.rushing_td
        + count("receiving_tds") * rules.receiving_td
    )


def build_facts(
    *,
    weekly: pl.DataFrame,
    snap_counts: pl.DataFrame,
    schedule: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    season: int,
    through_week: int,
    positions: Mapping[str, str],
    plays: pl.DataFrame | None,
    window_size: int,
    red_zone_yardline: int = 20,
    inside_five_yardline: int = 5,
) -> SeasonFacts:
    """Every appearance through the cutoff, with the components the families read."""
    horizon = fantasy_horizon(season)
    last_week = min(int(through_week), horizon.last_week)
    first_week = horizon.first_week
    window = window_weeks(last_week, first_week, window_size)
    baseline = list(range(first_week, window[0])) if window else []
    presets = sorted(str(preset) for preset in scoring)

    games = _season_games(
        weekly=weekly,
        snap_counts=snap_counts,
        season=season,
        last_week=last_week,
        scoring=scoring,
    )
    extras = _components(weekly, season=season, last_week=last_week, scoring=scoring)
    lines: dict[str, dict[int, Line]] = {}
    for player_id, by_week in games.items():
        for week, game in by_week.items():
            extra = extras.get((player_id, week), {})
            lines.setdefault(player_id, {})[week] = Line(
                week=week,
                team=game.team,
                points={preset: game.cents[preset] / 100 for preset in presets},
                td_points={preset: float(extra.get(f"td_{preset}", 0.0)) for preset in presets},
                targets=game.targets,
                carries=game.carries,
                pass_attempts=game.pass_attempts,
                receptions=float(extra.get("receptions", 0.0)),
                receiving_yards=float(extra.get("receiving_yards", 0.0)),
                rushing_yards=float(extra.get("rushing_yards", 0.0)),
                touchdowns=float(extra.get("touchdowns", 0.0)),
                snap_share=game.snap_share,
                team_targets=game.team_targets,
                team_carries=game.team_carries,
            )

    # Team pass attempts per (week, team), summed from the same player rows as the other team
    # totals: the denominator of a passer's share in a documented quarterback change.
    passes: dict[tuple[int, str], float] = {}
    for appearances in lines.values():
        for week, line in appearances.items():
            if line.team is not None:
                passes[(week, line.team)] = passes.get((week, line.team), 0.0) + line.pass_attempts
    for appearances in lines.values():
        for week, line in appearances.items():
            if line.team is not None:
                line.team_pass_attempts = passes.get((week, line.team))

    facts = SeasonFacts(
        season=season,
        last_week=last_week,
        first_week=first_week,
        window=window,
        baseline=baseline,
        presets=presets,
        lines=lines,
        games=games,
        positions={key: str(value) for key, value in positions.items()},
        scheduled=_scheduled_teams(schedule, season=season, last_week=last_week),
    )
    _attach_red_zone(
        facts,
        plays,
        red_zone_yardline=red_zone_yardline,
        inside_five_yardline=inside_five_yardline,
    )
    return facts


def _components(
    weekly: pl.DataFrame,
    *,
    season: int,
    last_week: int,
    scoring: Mapping[ScoringPreset, ScoringRules],
) -> dict[tuple[str, int], dict[str, float]]:
    """``(player_id, week) -> receptions, yards, touchdowns and touchdown points per preset``."""
    stats = _scoped_stats(weekly, season=season, last_week=last_week)
    if stats.is_empty():
        return {}
    scored = score_weekly_frame(stats, scoring)
    out: dict[tuple[str, int], dict[str, float]] = {}
    for row in scored.iter_rows(named=True):
        gsis = row.get("gsis_id")
        if not gsis:
            continue
        key = (make_player_id(IdNamespace.GSIS, str(gsis)), int(row["week"]))
        entry = out.setdefault(key, {})
        for name in ("receptions", "receiving_yards", "rushing_yards"):
            entry[name] = entry.get(name, 0.0) + float(row.get(name) or 0.0)
        entry["touchdowns"] = entry.get("touchdowns", 0.0) + sum(
            float(row.get(name) or 0.0) for name in ("passing_tds", "rushing_tds", "receiving_tds")
        )
        for preset, rules in scoring.items():
            name = f"td_{preset}"
            entry[name] = entry.get(name, 0.0) + _touchdown_points(row, rules)
    return out


def _attach_red_zone(
    facts: SeasonFacts,
    plays: pl.DataFrame | None,
    *,
    red_zone_yardline: int,
    inside_five_yardline: int,
) -> None:
    """Red-zone and inside-five counts per appearance and per team-week, or none at all."""
    from ffdraft.signals.drive_play import drive_plays

    if plays is None:
        facts.pbp_state, facts.pbp_detail = "unavailable", "play-by-play was not loaded"
        return
    try:
        reduced = drive_plays(plays)
    except ValueError as exc:
        facts.pbp_state, facts.pbp_detail = "unavailable", str(exc)
        return
    scoped = reduced.filter(
        (pl.col("season") == facts.season)
        & (pl.col("week") >= facts.first_week)
        & (pl.col("week") <= facts.last_week),
    )
    present: set[tuple[int, str]] = set()
    for week, raw in scoped.select("week", "team").unique().iter_rows():
        team = normalize_team_code(raw)
        if team is not None:
            present.add((int(week), team))
    missing = sorted(
        (week, team)
        for week, teams in facts.scheduled.items()
        if facts.first_week <= week <= facts.last_week
        for team in teams
        if (week, team) not in present
    )
    if missing:
        facts.pbp_state = "partial"
        facts.pbp_detail = (
            f"{len(missing)} scheduled team-week(s) missing from play-by-play, first "
            f"W{missing[0][0]} {missing[0][1]}; red-zone counts are withheld"
        )
        return

    inside = scoped.filter(
        pl.col("kind").is_in(["rush", "target"])
        & pl.col("player").is_not_null()
        & (pl.col("yardline_100") <= red_zone_yardline),
    )
    team_weeks: dict[tuple[int, str], TeamWeek] = {}
    player_counts: dict[tuple[str, int], dict[str, int]] = {}
    for row in inside.iter_rows(named=True):
        team = normalize_team_code(row["team"])
        if team is None:
            continue
        week = int(row["week"])
        carry = row["kind"] == "rush"
        five = float(row["yardline_100"]) <= inside_five_yardline
        totals = team_weeks.setdefault((week, team), TeamWeek())
        counts = player_counts.setdefault(
            (make_player_id(IdNamespace.GSIS, str(row["player"])), week),
            {"rz_t": 0, "rz_c": 0, "i5_t": 0, "i5_c": 0},
        )
        if carry:
            totals.red_zone_carries += 1
            counts["rz_c"] += 1
            if five:
                totals.inside_five_carries += 1
                counts["i5_c"] += 1
        else:
            totals.red_zone_targets += 1
            counts["rz_t"] += 1
            if five:
                totals.inside_five_targets += 1
                counts["i5_t"] += 1
    for player_id, by_week in facts.lines.items():
        for week, line in by_week.items():
            counts = player_counts.get((player_id, week), {})
            line.red_zone_targets = counts.get("rz_t", 0)
            line.red_zone_carries = counts.get("rz_c", 0)
            line.inside_five_targets = counts.get("i5_t", 0)
            line.inside_five_carries = counts.get("i5_c", 0)
    facts.team_weeks = team_weeks
    facts.pbp_state, facts.pbp_detail = "available", None


def pooled(lines: Sequence[Line], numerator: Any, denominator: Any) -> tuple[float, float] | None:
    """``(sum numerator, sum denominator)`` over games where the denominator exists, or None.

    Every game must have the denominator, as ``usage_signals_v1`` pools it; one game without a
    team total makes the pooled share undefined rather than a share of fewer games.
    """
    if not lines:
        return None
    nums: list[float] = []
    dens: list[float] = []
    for line in lines:
        den = denominator(line)
        if den is None:
            return None
        nums.append(float(numerator(line)))
        dens.append(float(den))
    total = sum(dens)
    if total <= 0:
        return None
    return sum(nums), total
