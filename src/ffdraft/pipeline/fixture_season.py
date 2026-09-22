"""A synthetic in-season week-by-week record for the fixture players (ADR-091).

The fixture build derives its rest-of-season artifacts arithmetically from the draft tier
rows, because what it exercises is the contract rather than the model. The signal layer is
different: it is *nothing but* arithmetic over weekly rows, so the honest fixture for it is
weekly rows — nflverse-shaped stat lines, snap counts and a schedule — pushed through the
real adapters' contracts and the real builders. This module writes those rows.

**Built against the states, not the shape.** Eleven instances of one species are recorded
in `SESSION_STATE.md`: a fixture that carried a field's shape and not its states, so a gate
passed against a condition production reached weeks later. Every profile below is a state a
real season produces in its first half:

* a back whose role **rises** over the last three weeks, before his production does;
* a receiver whose role **declines**;
* a receiver whose latest game has **no snap-count row**, so a change must be withheld
  rather than compared against an older game;
* a tight end whose latest week is **snaps and no statistic** — on the field, never
  targeted — which is an appearance with genuine zeros;
* four players **absent** for the three weeks ending at the cutoff (the long-absence cohort);
* **byes** in weeks 5-8, which fall where the schedule puts them;
* a surfaced player with **one appearance**, which is a reading and not a change;
* quarterbacks with and without rushing volume, one of them efficient and one not.

The rest-of-season fixture then reads its to-date fields — games, points, weeks since the
last game, the three-week shares — off the same rows, so the card's weekly bars sum to the
points to date printed beside them and the cross-artifact check has something true to hold.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import polars as pl

from ffdraft.contracts.normalized import (
    SCHEDULE_CONTRACT,
    SNAP_COUNTS_CONTRACT,
    WEEKLY_STATS_CONTRACT,
)
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "FIXTURE_INSEASON_AS_OF",
    "FixtureSeason",
    "PlayerFacts",
    "build_fixture_season",
]

#: The in-season fixture's own "now": the Tuesday after week 8, when a through-week-8 board
#: is published and week 9 is the next game. Separate from the draft fixture's August stamp,
#: because "the next unplayed game" is only meaningful against an in-season instant.
FIXTURE_INSEASON_AS_OF = "2026-11-03T12:00:00Z"

_FIRST_SUNDAY = date(2026, 9, 13)
_TEAM_TARGETS = 34.0
_TEAM_CARRIES = 26.0
_TEAM_AIR_YARDS = 290.0

#: gsis id -> profile. Everyone not listed is steady.
_PROFILES: Mapping[str, str] = {
    "00-0000002": "rising",
    "00-0000004": "declining",
    "00-0000006": "missing_snaps",
    "00-0000011": "snap_only",
    "00-0000003": "absent",
    "00-0000007": "absent",
    "00-0000010": "absent",
    "00-0000012": "absent",
    "00-0000014": "rushing_qb",
    "00-0000002-surfaced": "breakout",
}

#: Weeks a profile appears in, through the fixture cutoff of 8.
_ABSENT_FROM = 6
_BREAKOUT_WEEKS = frozenset({8})


@dataclass(frozen=True, slots=True)
class PlayerFacts:
    """What the rest-of-season fixture reads back off the rows, per player."""

    games: int
    last_week: int | None
    points: Mapping[str, float]
    snap_share_last3: float | None
    target_share_last3: float | None

    def weeks_since_last_game(self, through_week: int) -> float:
        return float(through_week - self.last_week) if self.last_week is not None else 0.0


@dataclass
class FixtureSeason:
    weekly: pl.DataFrame
    snap_counts: pl.DataFrame
    schedule: pl.DataFrame
    facts: dict[str, PlayerFacts] = field(default_factory=dict)


def _bye_week(index: int) -> int:
    """Two teams per bye week, weeks 5-12, in team order.

    Offset so no profiled player's team is on bye in the cutoff week — a declining role or
    a snaps-only week that fell on a bye would be a state the fixture claims and never
    produces — while four teams still have their bye *ahead* of the cutoff, including one
    in the very next week.
    """
    return 5 + ((index + 4) % 8)


def _schedule(teams: Sequence[str], season: int) -> pl.DataFrame:
    ordered = sorted(teams)
    byes = {team: _bye_week(index) for index, team in enumerate(ordered)}
    rows: list[dict[str, Any]] = []
    for week in fantasy_horizon(season).weeks:
        playing = [team for team in ordered if byes[team] != week]
        shift = week % len(playing)
        playing = playing[shift:] + playing[:shift]
        for slot in range(0, len(playing) - 1, 2):
            home, away = playing[slot], playing[slot + 1]
            game = slot // 2
            # Lines are posted about two weeks out: all but one game of the next week, half
            # of the week after, none beyond. The one gap is the unposted-line state.
            lined = (week == 9 and game != 6) or (week == 10 and game < 3)
            spread = float((game % 5) - 2) * 3.5 if lined else None
            rows.append(
                {
                    "game_id": f"{season}_{week:02d}_{away}_{home}",
                    "season": season,
                    "game_type": "REG",
                    "week": week,
                    "gameday": _FIRST_SUNDAY + timedelta(days=7 * (week - 1)),
                    "gametime": "13:00" if game % 3 else "16:25",
                    "away_team": away,
                    "home_team": home,
                    "location": "Neutral" if (week == 9 and game == 2) else "Home",
                    "away_rest": 14 if byes[away] == week - 1 else 7,
                    "home_rest": 14 if byes[home] == week - 1 else 7,
                    "roof": "dome" if game == 4 else "outdoors",
                    "spread_line": spread,
                    "total_line": 43.5 + game if lined else None,
                },
            )
    return SCHEDULE_CONTRACT.build(rows)


def _snap(profile: str, position: str, week: int) -> float:
    base = {"QB": 1.0, "RB": 0.55, "WR": 0.86, "TE": 0.7}.get(position, 0.6)
    if profile == "rising":
        return {6: 0.61, 7: 0.74, 8: 0.83}.get(week, 0.42)
    if profile == "declining":
        return {6: 0.84, 7: 0.77, 8: 0.64}.get(week, 0.93)
    if profile == "breakout":
        return 0.31
    if profile == "snap_only" and week == 8:
        return 0.58
    return round(base - 0.01 * (week % 3), 2)


def _stat_line(profile: str, position: str, week: int, snap: float) -> dict[str, float]:
    """One synthetic, internally consistent stat line for a played week."""
    line: dict[str, float] = {}
    if position == "QB":
        attempts = 32.0 + 2 * (week % 3)
        carries = 8.0 if profile == "rushing_qb" else 3.0
        line |= {
            "pass_attempts": attempts,
            "completions": round(attempts * 0.65),
            "passing_yards": round(attempts * 7.2),
            "passing_air_yards": round(attempts * 8.0),
            "passing_tds": 1.0 + (week % 3 == 0) + (week % 4 == 0),
            "interceptions": 1.0 if week % 4 == 1 else 0.0,
            "carries": carries,
            "rushing_yards": carries * 5.0,
            "rushing_tds": 1.0 if profile == "rushing_qb" and week % 3 == 1 else 0.0,
            "sacks_suffered": 2.0,
            "passing_epa": round(attempts * (-0.04 if profile == "rushing_qb" else 0.14), 2),
        }
    elif position == "RB":
        carries = round(_TEAM_CARRIES * min(0.9, snap * 0.85))
        targets = round(_TEAM_TARGETS * 0.07 * snap / 0.55)
        receptions = round(targets * 0.75)
        line |= {
            "carries": float(carries),
            "rushing_yards": round(carries * 4.3),
            "rushing_tds": 1.0 if week % 3 == 0 else 0.0,
            "targets": float(targets),
            "receptions": float(receptions),
            "receiving_yards": receptions * 7.0,
            "receiving_air_yards": float(targets),
        }
    elif position in ("WR", "TE"):
        if profile == "declining":
            share = {6: 0.2, 7: 0.17, 8: 0.12}.get(week, 0.27)
        elif position == "WR":
            share = 0.2 + 0.01 * (week % 3)
        else:
            share = 0.14
        targets = round(_TEAM_TARGETS * share)
        receptions = round(targets * 0.66)
        depth = 13.0 if position == "WR" else 7.0
        line |= {
            "targets": float(targets),
            "receptions": float(receptions),
            "receiving_yards": receptions * (12.5 if position == "WR" else 10.0),
            "receiving_air_yards": targets * depth,
            "receiving_tds": 1.0 if week % 4 == 0 else 0.0,
        }
    return line


def _plays(profile: str, week: int) -> bool:
    if profile == "absent":
        return week < _ABSENT_FROM
    if profile == "breakout":
        return week in _BREAKOUT_WEEKS
    return True


def build_fixture_season(
    players: Sequence[Mapping[str, Any]],
    *,
    season: int,
    through_week: int,
    scoring_presets: Sequence[str],
    score: Any,
) -> FixtureSeason:
    """Weekly rows, snap counts and a schedule for ``players``, and the facts read off them.

    ``players`` carries ``player_id`` (``gsis:`` namespaced), ``position`` and ``team``.
    ``score`` is the scoring engine's frame scorer, injected so this module stays a writer of
    rows and never a second implementation of the scoring rules.
    """
    teams = sorted({str(player["team"]) for player in players if player.get("team")})
    schedule = _schedule(teams, season)
    byes = {team: _bye_week(index) for index, team in enumerate(teams)}

    stat_rows: list[dict[str, Any]] = []
    snap_rows: list[dict[str, Any]] = []
    stat_weeks: dict[str, set[int]] = {}
    team_used: dict[tuple[int, str], dict[str, float]] = {}

    for player in players:
        gsis = str(player["player_id"]).split(":", 1)[1]
        position = str(player["position"])
        team = str(player["team"])
        profile = _PROFILES.get(gsis, "steady")
        for week in range(1, through_week + 1):
            if byes.get(team) == week or not _plays(profile, week):
                continue
            snap = _snap(profile, position, week)
            if profile != "missing_snaps" or week != through_week:
                snap_rows.append(
                    {
                        "season": season,
                        "week": week,
                        "game_type": "REG",
                        "pfr_player_id": f"pfr-{gsis}",
                        "player_name": player.get("display_name"),
                        "position": position,
                        "team": team,
                        "offense_snaps": round(snap * 64),
                        "offense_pct": snap,
                        "gsis_id": gsis,
                    },
                )
            if profile == "snap_only" and week == through_week:
                continue
            line = _stat_line(profile, position, week, snap)
            used = team_used.setdefault((week, team), {"targets": 0.0, "carries": 0.0, "air": 0.0})
            used["targets"] += line.get("targets", 0.0)
            used["carries"] += line.get("carries", 0.0)
            used["air"] += line.get("receiving_air_yards", 0.0)
            stat_weeks.setdefault(str(player["player_id"]), set()).add(week)
            stat_rows.append(_row(season, week, gsis, player, team, line))

    # The rest of each roster, one row per team-week, so a share has a denominator.
    for index, team in enumerate(teams):
        for week in range(1, through_week + 1):
            if byes.get(team) == week:
                continue
            used = team_used.get((week, team), {"targets": 0.0, "carries": 0.0, "air": 0.0})
            rest = {
                "targets": max(0.0, _TEAM_TARGETS - used["targets"]),
                "carries": max(0.0, _TEAM_CARRIES - used["carries"]),
                "receiving_air_yards": max(0.0, _TEAM_AIR_YARDS - used["air"]),
            }
            stat_rows.append(
                _row(
                    season,
                    week,
                    f"00-99{index:05d}",
                    {"display_name": f"{team} depth", "position": "WR"},
                    team,
                    rest,
                ),
            )

    weekly = WEEKLY_STATS_CONTRACT.build(stat_rows)
    snaps = SNAP_COUNTS_CONTRACT.build(
        [{key: value for key, value in row.items() if key != "gsis_id"} for row in snap_rows],
    ).with_columns(
        pl.Series("gsis_id", [row["gsis_id"] for row in snap_rows], dtype=pl.String),
    )
    scored = score(weekly)
    facts = _facts(
        players,
        scored=scored,
        snaps=snaps,
        stat_weeks=stat_weeks,
        through_week=through_week,
        scoring_presets=scoring_presets,
    )
    return FixtureSeason(weekly=weekly, snap_counts=snaps, schedule=schedule, facts=facts)


def _row(
    season: int,
    week: int,
    gsis: str,
    player: Mapping[str, Any],
    team: str,
    line: Mapping[str, float],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "season": season,
        "week": week,
        "season_type": "REG",
        "gsis_id": gsis,
        "display_name": player.get("display_name"),
        "position": player.get("position"),
        "team": team,
        "opponent_team": None,
    }
    for name in (
        "pass_attempts",
        "completions",
        "passing_yards",
        "passing_tds",
        "interceptions",
        "passing_air_yards",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "receiving_air_yards",
        "fumbles_lost",
        "two_point_conversions",
    ):
        row[name] = float(line.get(name, 0.0))
    row["passing_epa"] = line.get("passing_epa")
    row["sacks_suffered"] = line.get("sacks_suffered", 0.0)
    return row


def _facts(
    players: Sequence[Mapping[str, Any]],
    *,
    scored: pl.DataFrame,
    snaps: pl.DataFrame,
    stat_weeks: Mapping[str, set[int]],
    through_week: int,
    scoring_presets: Sequence[str],
) -> dict[str, PlayerFacts]:
    """The rest-of-season fixture's to-date fields, by the definitions ``ros_core_v1`` uses.

    Games are weeks with a stat row — the ROS panel's definition of "played" — so the
    tight end's snaps-only week counts for the usage series and not here, which is the
    documented difference between the two and exactly what the fixture should carry.
    """
    team_totals = {
        (int(row["week"]), str(row["team"])): float(row["targets"])
        for row in scored.group_by("week", "team")
        .agg(pl.col("targets").sum())
        .iter_rows(named=True)
    }
    snap_pct = {
        (str(row["gsis_id"]), int(row["week"])): float(row["offense_pct"])
        for row in snaps.iter_rows(named=True)
    }
    facts: dict[str, PlayerFacts] = {}
    recent = set(range(max(1, through_week - 2), through_week + 1))
    for player in players:
        player_id = str(player["player_id"])
        gsis = player_id.split(":", 1)[1]
        weeks = sorted(stat_weeks.get(player_id, set()))
        rows = scored.filter(pl.col("gsis_id") == gsis)
        points = {
            str(preset): round(float(rows.get_column(f"fantasy_points_{preset}").sum()), 4)
            for preset in scoring_presets
        }
        recent_rows = rows.filter(pl.col("week").is_in(sorted(recent)))
        snaps_recent = [
            snap_pct[(gsis, week)] for week in weeks if week in recent and (gsis, week) in snap_pct
        ]
        team_targets = sum(
            team_totals.get((int(row["week"]), str(row["team"])), 0.0)
            for row in recent_rows.iter_rows(named=True)
        )
        targets = float(recent_rows.get_column("targets").sum()) if recent_rows.height else 0.0
        facts[player_id] = PlayerFacts(
            games=len(weeks),
            last_week=weeks[-1] if weeks else None,
            points=points,
            snap_share_last3=(
                round(sum(snaps_recent) / len(snaps_recent), 4) if snaps_recent else None
            ),
            target_share_last3=(round(targets / team_targets, 4) if team_targets > 0 else None),
        )
    return facts
