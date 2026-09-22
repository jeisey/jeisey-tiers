"""Observed role and production, week by week (``usage_signals_v1``, ADR-091).

**The decision this serves.** A waiver claim turns on whether a player's *role* changed —
whether he is on the field more, getting more of his team's targets or carries, earning
downfield looks — often a week or two before his box score shows it. The rest-of-season
model reads a three-week window of some of this and publishes none of it; the card showed a
snap share and a target share as two bare numbers, the same two for every position, which
for a quarterback meant two constants (``docs/SIGNAL_EXPANSION_EDA.md`` Part 2b).

This module publishes the facts behind that judgement, and **only facts**:

* a **week-by-week series** for every week of the season through the cutoff — whether he
  played, his share of his team's offensive snaps, targets, carries and receiving air
  yards, his raw attempts, and his fantasy points in each scoring preset;
* one **change rule** per role metric, ``role_change_v1`` (below);
* two **sustainability readings**: the share of his fantasy points that came from
  touchdowns, and — for a passer — EPA per dropback.

Every quantity is arithmetic over nflverse's weekly player rows and snap counts, both
CC-BY 4.0 and both already downloaded by every in-season build. **Nothing here is from
ffopportunity**: its expected-points figures are CC-BY-SA 4.0 and whether this site may
publish a per-player figure derived from them is an open owner decision (ADR-086), so the
expected-points reading this layer would most like to carry is deliberately absent.

**The change rule, ``role_change_v1``.** Latest appearance against the average of every
earlier appearance this season.

* *Window.* "Latest" is the player's most recent appearance at or before the cutoff;
  "earlier" is every appearance before it. Not a fixed trailing window: in week 2 the only
  comparison that exists is week 2 against week 1, and a three-week rule would say nothing
  until week 4 — after the waiver runs that matter most.
* *Averaging.* A share counted in team units (targets, carries, air yards) is **pooled** —
  his total over his team's total in the games he played — which is how
  ``target_share_to_date`` is defined, so one quantity has one provenance. Snap share and
  raw attempts are a **mean per game**, as ``snap_pct_mean_to_date`` is.
* *Minimum.* One earlier appearance with the metric defined. Below it the change is null
  and the latest value still publishes: a rookie's first game is a reading, not a trend.
* *Sign.* ``change = latest − earlier``, in the metric's own unit (a share's change is a
  difference of shares, printed as percentage points). Positive means a bigger role in his
  latest game than before it.
* *Missing data.* A metric undefined in the latest game — no snap-count row, a team with no
  targets that week — yields a null change. It never falls back to an older game, because a
  "latest" that silently moves is a window nobody can read.

**What an appearance is.** A week with a weekly stats row **or** an offensive snap.
nflverse writes a stats row only when a player records a statistic, so a receiver who ran
thirty routes and was never targeted has a snap row and no stats row — and that week is
exactly the one a role reading must not drop. On such a week every count is zero, which is
the observation rather than a fill.

**Absences are not zeros.** A week he did not appear is published as ``bye`` (his team had
no game) or ``did_not_play`` with every metric null.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts.enums import normalize_team_code
from ffdraft.identity.ids import IdNamespace, parse_player_id
from ffdraft.scoring.engine import score_weekly_frame
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "EXPECTED_POINTS_STATEMENT",
    "ROLE_CHANGE_METRICS",
    "ROLE_CHANGE_RULE_VERSION",
    "USAGE_RULE",
    "USAGE_RULE_VERSION",
    "UsageRule",
    "WEEK_STATUSES",
    "build_player_usage_records",
    "current_teams_from_roster",
]

#: Bump when the meaning of any published usage quantity changes.
USAGE_RULE_VERSION = "usage_signals_v1"

#: The change rule, versioned separately because it is the one judgement in the module.
ROLE_CHANGE_RULE_VERSION = "role_change_v1"

#: Every metric the change rule is published for. All six for every player: which ones a
#: card *shows* is a presentation decision per position (``web/src/data/signals.ts``), and
#: a quarterback's target share is still a fact even though no card leads with it.
ROLE_CHANGE_METRICS: tuple[str, ...] = (
    "snap_share",
    "target_share",
    "carry_share",
    "air_yards_share",
    "pass_attempts",
    "carries",
)

#: How a metric is averaged across the earlier games: pooled numerator over denominator,
#: or a mean of the per-game values. See the module docstring for why each is which.
_POOLED: Mapping[str, tuple[str, str]] = {
    "target_share": ("targets", "team_targets"),
    "carry_share": ("carries", "team_carries"),
    "air_yards_share": ("air_yards", "team_air_yards"),
}

WEEK_STATUSES: tuple[str, ...] = ("played", "bye", "did_not_play")

#: Why the reading a waiver card would most like to show is not here. Travels on the build
#: metadata so the Data view states it from the artifact rather than from a hardcoded string.
EXPECTED_POINTS_STATEMENT = (
    "No expected-fantasy-points reading is published. ffopportunity's expected points are "
    "licensed CC-BY-SA 4.0, and whether this site may publish a per-player figure derived "
    "from them is an open decision (ADR-086). The rest-of-season model reads them as an "
    "input; the card does not print them."
)


@dataclass(frozen=True, slots=True)
class UsageRule:
    """The declared minimums. Each is the smallest sample that is a reading at all."""

    version: str = USAGE_RULE_VERSION
    change_rule_version: str = ROLE_CHANGE_RULE_VERSION
    #: Earlier appearances with the metric defined before a change is stated.
    min_earlier_games: int = 1
    #: Fantasy points to date below which a touchdown share is not published. Two points
    #: of which one touchdown is "300%" or "0%" depending on a fumble, and neither is a
    #: statement about how he scores.
    min_touchdown_share_points: float = 10.0
    #: Dropbacks (pass attempts plus sacks) before EPA per dropback is published. A backup's
    #: six garbage-time throws are not an efficiency.
    min_epa_dropbacks: float = 20.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "change_rule_version": self.change_rule_version,
            "min_earlier_games": self.min_earlier_games,
            "min_touchdown_share_points": self.min_touchdown_share_points,
            "min_epa_dropbacks": self.min_epa_dropbacks,
        }


USAGE_RULE = UsageRule()


@dataclass(frozen=True, slots=True)
class _Week:
    week: int
    status: str
    team: str | None
    opponent: str | None
    snap_share: float | None = None
    targets: float | None = None
    team_targets: float | None = None
    carries: float | None = None
    team_carries: float | None = None
    air_yards: float | None = None
    team_air_yards: float | None = None
    pass_attempts: float | None = None
    sacks: float | None = None
    passing_epa: float | None = None
    touchdown_points: Mapping[str, float] | None = None
    fantasy_points: Mapping[str, float] | None = None

    @property
    def played(self) -> bool:
        return self.status == "played"

    def value(self, metric: str) -> float | None:
        """This week's value for ``metric``, or None when it is undefined."""
        if not self.played:
            return None
        if metric in _POOLED:
            numerator, denominator = _POOLED[metric]
            return _share(getattr(self, numerator), getattr(self, denominator))
        value = getattr(self, metric)
        return None if value is None else float(value)


def _share(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def build_player_usage_records(
    *,
    players: Mapping[str, Mapping[str, Any]],
    weekly: pl.DataFrame,
    snap_counts: pl.DataFrame,
    schedule: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    season: int,
    through_week: int,
    build_id: str,
    schema_version: str,
    current_teams: Mapping[str, str] | None = None,
    rule: UsageRule = USAGE_RULE,
) -> list[dict[str, Any]]:
    """One published usage record per player in ``players``.

    ``players`` maps a canonical ``gsis:`` id to its published identity (``display_name``,
    ``position``) — in production, the players the Opportunity Board publishes, so a card
    that can be opened always has a record and no record exists for a card nobody can open.
    A player whose id is not a GSIS id has no nflverse weekly rows by construction and is
    skipped rather than given an empty series that would read as "never played".

    ``weekly`` and ``snap_counts`` are the normalized frames the in-season build already
    holds; rows after ``through_week`` are ignored here as well as upstream, so the series
    can never describe a week the rest-of-season board does not.
    """
    presets = sorted(scoring)
    horizon = fantasy_horizon(season)
    weeks = [week for week in horizon.weeks if week <= through_week]
    if not weeks:
        return []

    rows = _weekly_rows(weekly, season=season, through_week=through_week, scoring=scoring)
    teams = _team_totals(rows)
    snaps = _snap_rows(snap_counts, season=season, through_week=through_week)
    opponents = _opponents(schedule, season=season, through_week=through_week)
    scheduled_teams = frozenset(team for _, team in opponents)

    by_player_rows: dict[str, dict[int, dict[str, Any]]] = {}
    for row in rows.iter_rows(named=True):
        by_player_rows.setdefault(str(row["gsis_id"]), {})[int(row["week"])] = row
    by_player_snaps: dict[str, dict[int, dict[str, Any]]] = {}
    for row in snaps.iter_rows(named=True):
        by_player_snaps.setdefault(str(row["gsis_id"]), {})[int(row["week"])] = row

    records: list[dict[str, Any]] = []
    for player_id in sorted(players):
        try:
            namespace, gsis = parse_player_id(player_id)
        except ValueError:
            continue
        if namespace != IdNamespace.GSIS:
            continue
        identity = players[player_id]
        stat_weeks = by_player_rows.get(gsis, {})
        snap_weeks = by_player_snaps.get(gsis, {})
        observed_team = _last_observed_team(stat_weeks, snap_weeks)
        team = (current_teams or {}).get(player_id) or observed_team

        series: list[_Week] = []
        carried_team: str | None = None
        for week in weeks:
            stat = stat_weeks.get(week)
            snap = snap_weeks.get(week)
            series.append(
                _week_entry(
                    week=week,
                    stat=stat,
                    snap=snap,
                    teams=teams,
                    opponents=opponents,
                    scheduled_teams=scheduled_teams,
                    presets=presets,
                    scoring=scoring,
                    fallback_team=carried_team or observed_team or team,
                ),
            )
            if series[-1].played and series[-1].team is not None:
                carried_team = series[-1].team

        records.append(
            _record(
                player_id=player_id,
                identity=identity,
                team=team,
                series=series,
                presets=presets,
                season=season,
                through_week=through_week,
                build_id=build_id,
                schema_version=schema_version,
                rule=rule,
            ),
        )
    return records


def current_teams_from_roster(roster: pl.DataFrame) -> dict[str, str]:
    """``player_id -> team`` for every player nflverse's season roster places on ONE club.

    The seasonal roster carries one row per player per club he was rostered by, so a traded
    player appears twice and the file alone cannot say which club is current. Those players
    are left out here and fall back to the club of their latest appearance — a weaker answer,
    stated as such in the schema, rather than a guess between two rows.
    """
    if roster.is_empty() or "gsis_id" not in roster.columns or "team" not in roster.columns:
        return {}
    grouped = (
        roster.filter(pl.col("gsis_id").is_not_null() & pl.col("team").is_not_null())
        .group_by("gsis_id")
        .agg(pl.col("team").unique().alias("teams"))
    )
    teams: dict[str, str] = {}
    for row in grouped.iter_rows(named=True):
        clubs = {normalize_team_code(team) for team in row["teams"]} - {None}
        if len(clubs) == 1:
            teams[f"gsis:{row['gsis_id']}"] = str(next(iter(clubs)))
    return teams


def _weekly_rows(
    weekly: pl.DataFrame,
    *,
    season: int,
    through_week: int,
    scoring: Mapping[ScoringPreset, ScoringRules],
) -> pl.DataFrame:
    """The season's scorable regular-season rows through the cutoff, scored per preset."""
    if weekly.is_empty():
        return pl.DataFrame(schema={"gsis_id": pl.String, "week": pl.Int32, "team": pl.String})
    horizon = fantasy_horizon(season)
    rows = weekly.filter(
        (pl.col("season") == season)
        & (pl.col("season_type") == "REG")
        & (pl.col("week") >= horizon.first_week)
        & (pl.col("week") <= min(through_week, horizon.last_week)),
    )
    if rows.is_empty():
        return rows
    for name in ("passing_epa", "sacks_suffered"):
        if name not in rows.columns:
            rows = rows.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
    scored = score_weekly_frame(rows, scoring)
    return scored.with_columns(
        pl.col("team").map_elements(normalize_team_code, return_dtype=pl.String).alias("team"),
    )


def _team_totals(rows: pl.DataFrame) -> dict[tuple[int, str], dict[str, float]]:
    """Per ``(week, team)`` targets, carries and receiving air yards, from the same rows.

    Derived from the player rows rather than a team table for the reason
    :func:`ffdraft.ros.panel.team_weekly_totals` gives: a share of two numbers with one
    provenance cannot disagree with itself at the edges.
    """
    if rows.is_empty() or "targets" not in rows.columns:
        return {}
    totals = (
        rows.filter(pl.col("team").is_not_null())
        .group_by("week", "team")
        .agg(
            pl.col("targets").sum().alias("team_targets"),
            pl.col("carries").sum().alias("team_carries"),
            pl.col("receiving_air_yards").sum().alias("team_air_yards"),
        )
    )
    return {
        (int(row["week"]), str(row["team"])): {
            "team_targets": float(row["team_targets"] or 0.0),
            "team_carries": float(row["team_carries"] or 0.0),
            "team_air_yards": float(row["team_air_yards"] or 0.0),
        }
        for row in totals.iter_rows(named=True)
    }


def _snap_rows(snap_counts: pl.DataFrame, *, season: int, through_week: int) -> pl.DataFrame:
    """One offensive-snap row per ``(week, gsis_id)``, bridged upstream."""
    empty = pl.DataFrame(
        schema={
            "week": pl.Int32,
            "gsis_id": pl.String,
            "team": pl.String,
            "offense_snaps": pl.Float64,
            "offense_pct": pl.Float64,
        },
    )
    if snap_counts.is_empty() or "gsis_id" not in snap_counts.columns:
        return empty
    scoped = snap_counts.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") <= through_week)
        & pl.col("gsis_id").is_not_null(),
    )
    if scoped.is_empty():
        return empty
    return (
        scoped.group_by("week", "gsis_id")
        .agg(
            pl.col("team").first().alias("team"),
            pl.col("offense_snaps").sum().alias("offense_snaps"),
            pl.col("offense_pct").max().alias("offense_pct"),
        )
        .with_columns(
            pl.col("team").map_elements(normalize_team_code, return_dtype=pl.String),
        )
    )


def _opponents(
    schedule: pl.DataFrame,
    *,
    season: int,
    through_week: int,
) -> dict[tuple[int, str], str]:
    """``(week, team) -> opponent`` for every regular-season game through the cutoff.

    A team with no entry for a week had a bye that week, which is how a week a player did
    not appear is told apart from a week his team did not play.
    """
    if schedule.is_empty():
        return {}
    games = schedule.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") <= through_week),
    )
    mapping: dict[tuple[int, str], str] = {}
    for row in games.select("week", "home_team", "away_team").iter_rows(named=True):
        home = normalize_team_code(row["home_team"])
        away = normalize_team_code(row["away_team"])
        if home is None or away is None:
            continue
        mapping[(int(row["week"]), home)] = away
        mapping[(int(row["week"]), away)] = home
    return mapping


def _last_observed_team(
    stat_weeks: Mapping[int, Mapping[str, Any]],
    snap_weeks: Mapping[int, Mapping[str, Any]],
) -> str | None:
    for week in sorted(set(stat_weeks) | set(snap_weeks), reverse=True):
        team = (stat_weeks.get(week) or {}).get("team") or (snap_weeks.get(week) or {}).get("team")
        if team:
            return str(team)
    return None


def _week_entry(
    *,
    week: int,
    stat: Mapping[str, Any] | None,
    snap: Mapping[str, Any] | None,
    teams: Mapping[tuple[int, str], Mapping[str, float]],
    opponents: Mapping[tuple[int, str], str],
    scheduled_teams: frozenset[str],
    presets: Sequence[ScoringPreset],
    scoring: Mapping[ScoringPreset, ScoringRules],
    fallback_team: str | None,
) -> _Week:
    snapped = snap is not None and float(snap.get("offense_snaps") or 0.0) > 0
    if stat is None and not snapped:
        # A bye is a claim about the schedule, so it needs a schedule that knows the team;
        # without one the honest status is the weaker one — he did not appear.
        known = fallback_team is not None and fallback_team in scheduled_teams
        opponent = opponents.get((week, fallback_team)) if known and fallback_team else None
        status = "bye" if known and opponent is None else "did_not_play"
        return _Week(
            week=week,
            status=status,
            team=fallback_team if status == "bye" else None,
            opponent=None,
        )

    team = (stat or {}).get("team") or (snap or {}).get("team")
    team = str(team) if team else None
    totals = teams.get((week, team), {}) if team else {}
    snap_share = None
    if snap is not None and snap.get("offense_pct") is not None:
        snap_share = float(snap["offense_pct"])

    def count(name: str) -> float:
        return 0.0 if stat is None else float(stat.get(name) or 0.0)

    touchdown_points = {
        str(preset): (
            count("passing_tds") * scoring[preset].passing_td
            + count("rushing_tds") * scoring[preset].rushing_td
            + count("receiving_tds") * scoring[preset].receiving_td
        )
        for preset in presets
    }
    fantasy_points = {str(preset): count(f"fantasy_points_{preset}") for preset in presets}
    passing_epa = None if stat is None else stat.get("passing_epa")
    return _Week(
        week=week,
        status="played",
        team=team,
        opponent=opponents.get((week, team)) if team else None,
        snap_share=snap_share,
        targets=count("targets"),
        team_targets=totals.get("team_targets"),
        carries=count("carries"),
        team_carries=totals.get("team_carries"),
        air_yards=count("receiving_air_yards"),
        team_air_yards=totals.get("team_air_yards"),
        pass_attempts=count("pass_attempts"),
        sacks=count("sacks_suffered"),
        passing_epa=None if passing_epa is None else float(passing_epa),
        touchdown_points=touchdown_points,
        fantasy_points=fantasy_points,
    )


def _role_change(series: Sequence[_Week], metric: str, rule: UsageRule) -> dict[str, Any] | None:
    """``role_change_v1`` for one metric, or None when the latest game has no value."""
    appearances = [week for week in series if week.played]
    if not appearances:
        return None
    latest = appearances[-1]
    latest_value = latest.value(metric)
    if latest_value is None:
        return None
    earlier = [week for week in appearances[:-1] if week.value(metric) is not None]
    earlier_value: float | None = None
    if len(earlier) >= rule.min_earlier_games:
        if metric in _POOLED:
            numerator_name, denominator_name = _POOLED[metric]
            numerator = sum(float(getattr(week, numerator_name) or 0.0) for week in earlier)
            denominator = sum(float(getattr(week, denominator_name) or 0.0) for week in earlier)
            earlier_value = _share(numerator, denominator)
        else:
            values = [float(week.value(metric) or 0.0) for week in earlier]
            earlier_value = sum(values) / len(values)
    digits = 3 if metric.endswith("_share") else 2
    latest_rounded = _round(latest_value, digits)
    earlier_rounded = _round(earlier_value, digits)
    return {
        "latest_week": latest.week,
        "latest": latest_rounded,
        "earlier": earlier_rounded,
        "earlier_games": len(earlier),
        # From the rounded halves, so the published difference is exactly the difference of
        # the two published numbers and no reader can subtract them and get something else.
        "change": (
            None
            if earlier_rounded is None or latest_rounded is None
            else round(latest_rounded - earlier_rounded, digits)
        ),
    }


def _record(
    *,
    player_id: str,
    identity: Mapping[str, Any],
    team: str | None,
    series: Sequence[_Week],
    presets: Sequence[str],
    season: int,
    through_week: int,
    build_id: str,
    schema_version: str,
    rule: UsageRule,
) -> dict[str, Any]:
    played = [week for week in series if week.played]
    points = {
        str(p): sum((week.fantasy_points or {}).get(str(p), 0.0) for week in played)
        for p in presets
    }
    td_points = {
        str(p): sum((week.touchdown_points or {}).get(str(p), 0.0) for week in played)
        for p in presets
    }
    touchdown_share = {
        preset: (
            round(td_points[preset] / points[preset], 4)
            if points[preset] >= rule.min_touchdown_share_points
            else None
        )
        for preset in points
    }

    epa_weeks = [
        week for week in played if week.passing_epa is not None and week.pass_attempts is not None
    ]
    dropbacks = sum(
        float(week.pass_attempts or 0.0) + float(week.sacks or 0.0) for week in epa_weeks
    )
    epa_total = sum(float(week.passing_epa or 0.0) for week in epa_weeks)
    epa_per_dropback = (
        round(epa_total / dropbacks, 3) if dropbacks >= rule.min_epa_dropbacks else None
    )

    return {
        "schema_version": schema_version,
        "build_id": build_id,
        "season": season,
        "through_week": through_week,
        "player_id": player_id,
        "display_name": str(identity.get("display_name") or player_id),
        "position": str(identity.get("position") or ""),
        "team": team,
        "usage_rule_version": rule.version,
        "appearances": len(played),
        "weeks": [_week_record(week, presets) for week in series],
        "role_changes": {
            metric: _role_change(series, metric, rule) for metric in ROLE_CHANGE_METRICS
        },
        "fantasy_points_to_date": {preset: round(value, 2) for preset, value in points.items()},
        "touchdown_points_share": touchdown_share,
        "dropbacks": round(dropbacks, 1),
        "pass_epa_per_dropback": epa_per_dropback,
    }


def _week_record(week: _Week, presets: Sequence[str]) -> dict[str, Any]:
    played = week.played
    return {
        "week": week.week,
        "status": week.status,
        "team": week.team,
        "opponent": week.opponent,
        "snap_share": _round(week.snap_share, 3) if played else None,
        "target_share": _round(week.value("target_share"), 3),
        "carry_share": _round(week.value("carry_share"), 3),
        "air_yards_share": _round(week.value("air_yards_share"), 3),
        "targets": _round(week.targets, 1) if played else None,
        "carries": _round(week.carries, 1) if played else None,
        "pass_attempts": _round(week.pass_attempts, 1) if played else None,
        "fantasy_points": (
            {str(p): round((week.fantasy_points or {}).get(str(p), 0.0), 2) for p in presets}
            if played
            else None
        ),
    }
