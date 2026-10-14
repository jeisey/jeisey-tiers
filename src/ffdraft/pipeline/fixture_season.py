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


#: Real registry venues for the fixture's games (config/venues.yaml, ADR-099), by game slot:
#: open air, retractable, open air, open air, a fixed dome (the slot the schedule marks
#: ``dome``), open air, open air, open air. The game-day context resolves them by name.
_FIXTURE_STADIUMS: tuple[str, ...] = (
    "Lambeau Field",
    "NRG Stadium",
    "Soldier Field",
    "Highmark Stadium",
    "Ford Field",
    "Gillette Stadium",
    "GEHA Field at Arrowhead Stadium",
    "Lumen Field",
)


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
                    "stadium": _FIXTURE_STADIUMS[game % len(_FIXTURE_STADIUMS)],
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
            # The rest of the roster took snaps too, so every team that played a week has a
            # snap-count row for it, as a real release does — the season-actuals coverage
            # check refuses a week a club is missing from (ADR-105). Below every starter
            # threshold, so no game-day reading moves.
            snap_rows.append(
                {
                    "season": season,
                    "week": week,
                    "game_type": "REG",
                    "pfr_player_id": f"pfr-00-99{index:05d}",
                    "player_name": f"{team} depth",
                    "position": "WR",
                    "team": team,
                    "offense_snaps": 8,
                    "offense_pct": 0.12,
                    "gsis_id": f"00-99{index:05d}",
                },
            )

    # Who each row played, from the schedule the rows were written against: the weekly
    # start/sit layer reads a defence's allowed points off `opponent_team` (ADR-096), and a
    # fixture whose every opponent is null would test only the reading's absence.
    opponents: dict[tuple[int, str], str] = {}
    for game in schedule.iter_rows(named=True):
        opponents[(int(game["week"]), str(game["home_team"]))] = str(game["away_team"])
        opponents[(int(game["week"]), str(game["away_team"]))] = str(game["home_team"])
    for row in stat_rows:
        row["opponent_team"] = opponents.get((int(row["week"]), str(row["team"])))

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
    # ADR-107: yards after the catch, a third to a half of receiving yards by position.
    share = {"RB": 0.8, "TE": 0.45, "WR": 0.32}.get(str(player.get("position")), 0.0)
    row["receiving_yards_after_catch"] = round(float(line.get("receiving_yards", 0.0)) * share)
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


#: Drives per team-game in the synthetic play-by-play, and the plays each holds that are
#: nobody's opportunity (an incompletion with no receiver, a sack): QB slots only.
_FIXTURE_DRIVES = 11
_FIXTURE_FILLER_PER_DRIVE = 3
#: Weeks after the cutoff the synthetic file also carries, so the truncation is exercised:
#: a Thursday game of the next week is in a real file before the board is cut.
_FIXTURE_FUTURE_WEEKS = 1


def fixture_drive_plays(weekly: pl.DataFrame, *, through_week: int) -> pl.DataFrame:
    """A play-by-play-shaped frame from the fixture's weekly rows (ADR-103). Synthetic.

    Each player's carries and targets in a week are placed on his team's drives by a fixed
    rule: players whose id characters sum to an even number spread one opportunity per
    drive, the rest take them in bunches of three — so the fixture holds both signs of the
    gap. Every third
    target is snapped inside the red zone, so the tight-end variant has slots to exclude, and
    every other quarterback rush is a scramble, so the designed-run variant (ADR-104) has
    plays to exclude. One week beyond the cutoff is written too, and the build must ignore it.
    """
    rows: list[dict[str, object]] = []
    frame = weekly.filter(pl.col("week") <= through_week + _FIXTURE_FUTURE_WEEKS)
    for (week, team), group in sorted(
        frame.filter(pl.col("team").is_not_null()).group_by("week", "team"),
        key=lambda item: (int(item[0][0]), str(item[0][1])),
    ):
        game = f"2026_{int(week):02d}_{team}"

        def play(
            drive: int,
            kind: str,
            player: str | None,
            yardline: float,
            scramble: bool = False,
            week: int = int(week),
            game: str = game,
            team: str = str(team),
        ) -> None:
            rows.append(
                {
                    "season": 2026,
                    "week": week,
                    "season_type": "REG",
                    "game_id": game,
                    "posteam": team,
                    "fixed_drive": drive,
                    "play_type": "run" if kind == "rush" else "pass",
                    "rush_attempt": 1.0 if kind == "rush" else 0.0,
                    "pass_attempt": 0.0 if kind == "rush" else 1.0,
                    "sack": 1.0 if kind == "sack" else 0.0,
                    "qb_kneel": 0.0,
                    "qb_spike": 0.0,
                    "two_point_attempt": 0.0,
                    "aborted_play": 0.0,
                    "special_teams_play": 0.0,
                    "play_deleted": 0.0,
                    "rusher_player_id": player if kind == "rush" else None,
                    "receiver_player_id": player if kind == "target" else None,
                    "yardline_100": yardline,
                    "qb_scramble": 1.0 if scramble else 0.0,
                },
            )

        for drive in range(1, _FIXTURE_DRIVES + 1):
            for filler in range(_FIXTURE_FILLER_PER_DRIVE):
                play(drive, "sack" if filler == 0 else "throwaway", None, 55.0)
        for row in group.sort("gsis_id").iter_rows(named=True):
            gsis = str(row["gsis_id"])
            code = sum(ord(char) for char in gsis)
            spread = code % 2 == 0
            chances = [
                ("rush", int(row.get("carries") or 0)),
                ("target", int(row.get("targets") or 0)),
            ]
            slot = code % _FIXTURE_DRIVES
            placed = 0
            for kind, count in chances:
                for _ in range(count):
                    drive = (
                        1 + (slot + placed) % _FIXTURE_DRIVES
                        if spread
                        else 1 + (slot + placed // 3) % _FIXTURE_DRIVES
                    )
                    yardline = 12.0 if kind == "target" and placed % 3 == 2 else 48.0
                    scramble = kind == "rush" and row.get("position") == "QB" and placed % 2 == 1
                    play(drive, kind, gsis, yardline, scramble)
                    placed += 1
    return pl.DataFrame(rows)


# ------------------------------------------------------------------ Skill Tree (ADR-107)

#: Pass and rush plays every synthetic team-game carries beyond its players' own: a
#: two-point try (excluded everywhere) and, for the cutoff's next week, a whole extra game.
_SKILL_RED_ZONE_EVERY = 4
_SKILL_GOAL_LINE_EVERY = 9


def _spread(total: float, parts: int) -> list[float]:
    """``total`` over ``parts`` plays as whole yards, the remainder on the first plays."""
    if parts <= 0:
        return []
    base, extra = divmod(int(round(total)), parts)
    return [float(base + (1 if index < extra else 0)) for index in range(parts)]


def _epa(gsis: str, week: int, index: int) -> float:
    code = sum(ord(char) for char in gsis) + 7 * week + 13 * index
    return round(((code % 17) - 7) * 0.12, 3)


def fixture_skill_plays(weekly: pl.DataFrame, *, through_week: int) -> pl.DataFrame:
    """A play-by-play frame carrying every column the Skill Tree reads (ADR-107). Synthetic.

    Built from the fixture's own weekly rows so the universes reconcile with the box score:
    each target, carry and sack is one play; a quarterback's extra attempts are throwaways; a
    rushing quarterback's alternate carries are scrambles and, in the cutoff week, one carry
    is a kneel-down. Every fourth play is snapped in the red zone and every ninth at the goal
    line. Each team-game also carries a two-point try, and the file holds one game past the
    cutoff and one postseason play — all three must be ignored.
    """
    rows: list[dict[str, object]] = []
    frame = weekly.filter((pl.col("week") <= through_week) & pl.col("team").is_not_null())

    def play(**fields: object) -> None:
        base: dict[str, object] = {
            "season": 2026,
            "season_type": "REG",
            "play_type": "pass",
            "pass_attempt": 0.0,
            "rush_attempt": 0.0,
            "sack": 0.0,
            "qb_scramble": 0.0,
            "two_point_attempt": 0.0,
            "passer_player_id": None,
            "rusher_player_id": None,
            "receiver_player_id": None,
            "yardline_100": 45.0,
            "air_yards": None,
            "receiving_yards": None,
            "rushing_yards": None,
            "complete_pass": 0.0,
            "epa": 0.0,
            "cpoe": None,
        }
        base.update(fields)
        rows.append(base)

    for (week, team), group in sorted(
        frame.group_by("week", "team"),
        key=lambda item: (int(item[0][0]), str(item[0][1])),
    ):
        week_i, team_s = int(week), str(team)
        ordered = group.sort("gsis_id")
        quarterbacks = [
            str(row["gsis_id"])
            for row in ordered.iter_rows(named=True)
            if row.get("position") == "QB"
        ]
        passer = quarterbacks[0] if quarterbacks else None
        index = 0
        targets_thrown = 0
        for row in ordered.iter_rows(named=True):
            gsis = str(row["gsis_id"])
            targets = int(row.get("targets") or 0)
            receptions = int(row.get("receptions") or 0)
            yards = _spread(float(row.get("receiving_yards") or 0.0), receptions)
            air = _spread(float(row.get("receiving_air_yards") or 0.0), targets)
            for slot in range(targets):
                index += 1
                complete = slot < receptions
                yardline = (
                    3.0
                    if index % _SKILL_GOAL_LINE_EVERY == 0
                    else 15.0
                    if index % _SKILL_RED_ZONE_EVERY == 0
                    else 45.0
                )
                gained = yards[slot] if complete else 0.0
                play(
                    week=week_i,
                    posteam=team_s,
                    pass_attempt=1.0,
                    passer_player_id=passer,
                    receiver_player_id=gsis,
                    yardline_100=yardline,
                    air_yards=air[slot] if air else 0.0,
                    receiving_yards=gained,
                    complete_pass=1.0 if complete else 0.0,
                    epa=_epa(gsis, week_i, slot),
                    cpoe=round((1.0 if complete else 0.0) * 100 - 64.0 - (index % 5), 3),
                )
            targets_thrown += targets
            carries = int(row.get("carries") or 0)
            rushed = _spread(float(row.get("rushing_yards") or 0.0), carries)
            for slot in range(carries):
                index += 1
                is_qb = row.get("position") == "QB"
                kneel = is_qb and week_i == through_week and slot == carries - 1 and carries >= 3
                yardline = (
                    3.0
                    if index % _SKILL_GOAL_LINE_EVERY == 0
                    else 15.0
                    if index % _SKILL_RED_ZONE_EVERY == 0
                    else 45.0
                )
                play(
                    week=week_i,
                    posteam=team_s,
                    play_type="qb_kneel" if kneel else "run",
                    rush_attempt=1.0,
                    rusher_player_id=gsis,
                    qb_scramble=1.0 if is_qb and slot % 2 == 1 and not kneel else 0.0,
                    yardline_100=yardline,
                    rushing_yards=-1.0 if kneel else rushed[slot],
                    epa=-0.4 if kneel else _epa(gsis, week_i, 100 + slot),
                )
        if passer is not None:
            qb_row = next(
                row for row in ordered.iter_rows(named=True) if str(row["gsis_id"]) == passer
            )
            for slot in range(int(qb_row.get("sacks_suffered") or 0)):
                play(
                    week=week_i,
                    posteam=team_s,
                    pass_attempt=1.0,
                    sack=1.0,
                    passer_player_id=passer,
                    epa=-1.5,
                    yardline_100=40.0 + slot,
                )
            for slot in range(max(0, int(qb_row.get("pass_attempts") or 0) - targets_thrown)):
                play(
                    week=week_i,
                    posteam=team_s,
                    pass_attempt=1.0,
                    passer_player_id=passer,
                    air_yards=5.0,
                    epa=-0.3,
                    yardline_100=50.0 + slot % 5,
                )
        # A two-point try: a play, never an opportunity.
        play(
            week=week_i,
            posteam=team_s,
            play_type="run",
            rush_attempt=1.0,
            two_point_attempt=1.0,
            rusher_player_id=passer,
            yardline_100=2.0,
            rushing_yards=2.0,
            epa=0.9,
        )
    regular = pl.DataFrame(rows, infer_schema_length=None)
    if regular.is_empty():
        return regular
    beyond = regular.filter(pl.col("week") == through_week).with_columns(
        (pl.col("week") + 1).alias("week"),
    )
    postseason = regular.head(1).with_columns(
        pl.lit("POST").alias("season_type"),
        pl.lit(19).cast(regular.schema["week"]).alias("week"),
    )
    return pl.concat([regular, beyond, postseason], how="vertical_relaxed")


def _code(gsis: str) -> int:
    return sum(ord(char) for char in gsis)


def fixture_nextgen(weekly: pl.DataFrame, *, through_week: int) -> dict[str, pl.DataFrame]:
    """Next Gen Stats-shaped frames (normalized) for the fixture players. Synthetic.

    Season summaries (week 0) for passers with 48+ attempts, rushers with 30+ carries and
    receivers with 15+ targets, matching the official volume — except one receiver whose
    summary is off by five targets, which must be refused. Weekly rows exist only for
    qualifying weeks and end at the cutoff, as a real file's do on build day.
    """
    from ffdraft.contracts.normalized import NEXTGEN_STATS_CONTRACT

    stats = weekly.filter(
        (pl.col("week") <= through_week)
        & pl.col("position").is_in(["QB", "RB", "WR", "TE"])
        & ~pl.col("gsis_id").str.starts_with("00-99"),
    )
    totals = stats.group_by("gsis_id", "position").agg(
        pl.col("pass_attempts").sum(),
        pl.col("carries").sum(),
        pl.col("targets").sum(),
        pl.col("receptions").sum(),
    )
    frames: dict[str, list[dict[str, object]]] = {"passing": [], "rushing": [], "receiving": []}
    mismatched = False
    for row in totals.sort("gsis_id").iter_rows(named=True):
        gsis, position = str(row["gsis_id"]), str(row["position"])
        code = _code(gsis)
        base = {"season": 2026, "season_type": "REG", "gsis_id": gsis, "position": position}
        if position == "QB" and row["pass_attempts"] >= 48:
            frames["passing"].append(
                {
                    **base,
                    "week": 0,
                    "stat_type": "passing",
                    "volume": row["pass_attempts"],
                    "avg_time_to_throw": round(2.5 + (code % 10) * 0.07, 3),
                },
            )
        if position == "RB" and row["carries"] >= 30:
            frames["rushing"].append(
                {
                    **base,
                    "week": 0,
                    "stat_type": "rushing",
                    "volume": row["carries"],
                    "rush_yards_over_expected_per_att": round(((code % 9) - 4) * 0.2, 3),
                },
            )
        if position in ("WR", "TE") and row["targets"] >= 15:
            volume = float(row["targets"])
            if not mismatched and position == "WR":
                volume += 5.0
                mismatched = True
            frames["receiving"].append(
                {
                    **base,
                    "week": 0,
                    "stat_type": "receiving",
                    "volume": volume,
                    "receptions": row["receptions"],
                    "avg_separation": round(2.0 + (code % 12) * 0.15, 3),
                    "avg_cushion": round(5.0 + (code % 7) * 0.3, 3),
                    "avg_yac_above_expectation": round(((code % 11) - 5) * 0.15, 3),
                },
            )
    for row in stats.iter_rows(named=True):
        base = {
            "season": 2026,
            "season_type": "REG",
            "week": int(row["week"]),
            "gsis_id": str(row["gsis_id"]),
            "position": row["position"],
        }
        if float(row["pass_attempts"] or 0) >= 15:
            frames["passing"].append(
                {**base, "stat_type": "passing", "volume": row["pass_attempts"]}
            )
        if float(row["carries"] or 0) >= 10:
            frames["rushing"].append({**base, "stat_type": "rushing", "volume": row["carries"]})
        if float(row["targets"] or 0) >= 5:
            frames["receiving"].append(
                {**base, "stat_type": "receiving", "volume": row["targets"]},
            )
    return {kind: NEXTGEN_STATS_CONTRACT.build(rows) for kind, rows in frames.items()}


def fixture_combine(weekly: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, str]]:
    """Combine testers and the PFR → GSIS bridge for the fixture players. Synthetic.

    Every third fixture player has no combine time (not covered); one GSIS id is linked from
    two combine rows (ambiguous, so it fails closed); forty unnamed testers per position make
    the cohorts real.
    """
    players = (
        weekly.filter(
            pl.col("position").is_in(["QB", "RB", "WR", "TE"])
            & ~pl.col("gsis_id").str.starts_with("00-99"),
        )
        .select("gsis_id", "position")
        .unique()
        .sort("gsis_id")
    )
    rows: list[dict[str, object]] = []
    bridge: dict[str, str] = {}
    base_time = {"QB": 4.75, "RB": 4.45, "WR": 4.40, "TE": 4.65}
    for index, (gsis, position) in enumerate(players.iter_rows()):
        pfr = f"pfr-{gsis}"
        bridge[pfr] = str(gsis)
        if index % 3 == 2:
            continue
        rows.append(
            {
                "combine_year": 2018 + index % 8,
                "pfr_id": pfr,
                "position": position,
                "forty": round(base_time[str(position)] + (_code(str(gsis)) % 15) * 0.02, 2),
            },
        )
        if index == 0:
            # A second row claiming the same player: ambiguous, so he gets no reading.
            rows.append(
                {"combine_year": 2017, "pfr_id": pfr, "position": position, "forty": 4.99},
            )
    for position, start in base_time.items():
        for slot in range(40):
            rows.append(
                {
                    "combine_year": 2001 + slot % 25,
                    "pfr_id": None,
                    "position": position,
                    "forty": round(start - 0.15 + slot * 0.012, 2),
                },
            )
    frame = pl.DataFrame(
        rows,
        schema={
            "combine_year": pl.Int32,
            "pfr_id": pl.String,
            "position": pl.String,
            "forty": pl.Float64,
        },
    )
    return frame, bridge


#: Peer clubs the Skill Tree fixture adds so every position has a rankable cohort (the fixture
#: board has three quarterbacks and three tight ends; a rank needs five). Their rows reach the
#: Skill Tree builder only — no board, actuals or usage record describes them.
_PEER_TEAMS: tuple[str, ...] = ("PHA", "PHB", "PHC", "PHD", "PHE", "PHF")


def fixture_skill_peers(
    *,
    season: int,
    through_week: int,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Weekly rows and snap counts for six synthetic peer clubs (QB, RB, WR, TE each). Synthetic."""
    stat_rows: list[dict[str, Any]] = []
    snap_rows: list[dict[str, Any]] = []
    for index, team in enumerate(_PEER_TEAMS):
        for slot, position in enumerate(("QB", "RB", "WR", "TE")):
            gsis = f"00-98{index:02d}{slot:03d}"
            player = {"display_name": f"{team} {position}", "position": position}
            snap = 0.55 + 0.07 * index if position != "QB" else 1.0
            for week in range(1, through_week + 1):
                if week == 5 + index % 3 and position != "QB":
                    continue  # a missed game, so games differ across the cohort
                line = _stat_line("steady", position, week + index, min(snap, 0.95))
                stat_rows.append(_row(season, week, gsis, player, team, line))
                snap_rows.append(
                    {
                        "season": season,
                        "week": week,
                        "game_type": "REG",
                        "pfr_player_id": f"pfr-{gsis}",
                        "player_name": player["display_name"],
                        "position": position,
                        "team": team,
                        "offense_snaps": round(min(snap, 1.0) * 64),
                        "offense_pct": round(min(snap, 1.0), 2),
                        "gsis_id": gsis,
                    },
                )
    weekly = WEEKLY_STATS_CONTRACT.build(stat_rows)
    snaps = SNAP_COUNTS_CONTRACT.build(
        [{key: value for key, value in row.items() if key != "gsis_id"} for row in snap_rows],
    ).with_columns(
        pl.Series("gsis_id", [row["gsis_id"] for row in snap_rows], dtype=pl.String),
    )
    return weekly, snaps
