"""Each team's next unplayed game, as published context (``next_game_v1``, ADR-091).

**The decision this serves.** "Should I pick him up *this week*" depends on who he plays and
in what kind of game, and before this module the product had no opponent artifact at all —
Pick of the Week replaced its mock-up's ``MATCHUP vs IND`` readout precisely because nothing
could source it (ADR-088). ``load_schedules`` has carried the answer in every in-season
build: the opponent, home or away, rest days, the roof, and — for roughly the next two weeks
— a sportsbook spread and total.

**The sportsbook numbers are context, and that is a decision, not a caveat.**
``docs/SIGNAL_EXPANSION_EDA.md`` §2a.3 laid out three readings of AGENTS.md section 8 for a
game total. This module takes the third and only the third: the lines are **printed beside
a player** and computed into nothing. No feature reads them, no model is trained on them,
no rank or selection moves with them, and :mod:`ffdraft.quality.forbidden` fails any
intrinsic or rest-of-season feature named for them. Whether a line may ever become a model
input is a separate question with a sealed-season cost, and this module does not answer it.

**The rule, ``next_game_v1``.**

* *Which game.* The team's earliest regular-season game inside the fantasy horizon whose
  scheduled kickoff is after the build's timestamp. Not "the week after the cutoff": on a
  Saturday the Thursday game is over, and a card showing it as next would be wrong.
* *Orientation.* nflverse's ``spread_line`` is positive when the **home** team is favoured,
  the opposite of a betting slip. It is re-expressed once, here, as
  ``team_expected_margin`` — positive means *this* team is expected to win by that many — so
  no consumer ever has to know the upstream convention.
* *Implied points.* ``(total + margin) / 2`` and ``(total - margin) / 2``: the two scores
  consistent with the published total and spread. Arithmetic over two published numbers,
  null unless both exist, and labelled as the sportsbook's implication rather than a
  projection of this product.
* *Missing data.* Lines are posted about two weeks ahead (probed 2026-09-22: weeks 3-4 carry
  them, week 5 onwards does not). A game with no posted line publishes null lines, never a
  zero spread, which would read as a pick'em.
* *Weather.* Not published. The live file carries no temperature or wind for any unplayed
  game, so there is no forward-looking weather reading to publish.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.contracts.enums import normalize_team_code
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.season.state import scheduled_kickoff_utc
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "MATCHUP_RULE_VERSION",
    "SPORTSBOOK_CONTEXT_STATEMENT",
    "build_team_matchup_records",
]

MATCHUP_RULE_VERSION = "next_game_v1"

#: Travels on the build metadata and is printed wherever a line is shown, so the interface
#: cannot state a line without also stating what it is not.
SPORTSBOOK_CONTEXT_STATEMENT = (
    "The spread, total and implied points are sportsbook numbers read from nflverse's "
    "schedule and shown as matchup context only. No model reads them: they move no "
    "projection, VORP, rank, tier or Pick of the Week selection."
)


def build_team_matchup_records(
    *,
    schedule: pl.DataFrame,
    season: int,
    through_week: int,
    as_of: datetime,
    build_id: str,
    schema_version: str,
    lines_source_id: str,
    lines_retrieved_at: datetime | None,
    teams: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """One record per team that still has a game inside the horizon after ``as_of``.

    ``teams`` narrows the output; by default every club in the season's schedule gets a
    record, because a card may open any player and the frontend joins on the team code
    the player's usage record names.
    """
    if schedule.is_empty():
        return []
    horizon = fantasy_horizon(season)
    games = schedule.filter(
        (pl.col("season") == season)
        & (pl.col("game_type") == "REG")
        & (pl.col("week") >= horizon.first_week)
        & (pl.col("week") <= horizon.last_week),
    )
    if games.is_empty():
        return []

    by_team: dict[str, list[dict[str, Any]]] = {}
    weeks_by_team: dict[str, set[int]] = {}
    for row in games.iter_rows(named=True):
        home = normalize_team_code(row.get("home_team"))
        away = normalize_team_code(row.get("away_team"))
        kickoff = scheduled_kickoff_utc(row.get("gameday"), row.get("gametime"))
        if home is None or away is None:
            continue
        for team in (home, away):
            weeks_by_team.setdefault(team, set()).add(int(row["week"]))
        if kickoff is None or kickoff <= as_of:
            continue
        entry = {**row, "_home": home, "_away": away, "_kickoff": kickoff}
        by_team.setdefault(home, []).append(entry)
        by_team.setdefault(away, []).append(entry)

    wanted = sorted(set(teams) if teams is not None else set(weeks_by_team))
    records: list[dict[str, Any]] = []
    for team in wanted:
        upcoming = sorted(
            by_team.get(team, ()),
            key=lambda game: (game["_kickoff"], str(game.get("game_id"))),
        )
        if not upcoming:
            continue
        records.append(
            _record(
                team=team,
                game=upcoming[0],
                season=season,
                through_week=through_week,
                byes=[
                    week
                    for week in horizon.weeks
                    if week > through_week and week not in weeks_by_team.get(team, set())
                ],
                build_id=build_id,
                schema_version=schema_version,
                lines_source_id=lines_source_id,
                lines_retrieved_at=lines_retrieved_at,
            ),
        )
    return records


def _record(
    *,
    team: str,
    game: Mapping[str, Any],
    season: int,
    through_week: int,
    byes: Sequence[int],
    build_id: str,
    schema_version: str,
    lines_source_id: str,
    lines_retrieved_at: datetime | None,
) -> dict[str, Any]:
    home = team == game["_home"]
    spread = _number(game.get("spread_line"))
    total = _number(game.get("total_line"))
    # `+ 0.0` so a pick'em reads 0.0 from both sides rather than -0.0 from the away one.
    margin = None if spread is None else (spread if home else -spread) + 0.0
    implied_team = None if margin is None or total is None else (total + margin) / 2
    implied_opponent = None if margin is None or total is None else (total - margin) / 2
    team_rest = game.get("home_rest") if home else game.get("away_rest")
    opponent_rest = game.get("away_rest") if home else game.get("home_rest")
    has_lines = spread is not None or total is not None
    return {
        "schema_version": schema_version,
        "build_id": build_id,
        "season": season,
        "through_week": through_week,
        "team": team,
        "matchup_rule_version": MATCHUP_RULE_VERSION,
        "game_id": str(game.get("game_id")),
        "week": int(game["week"]),
        "kickoff_utc": isoformat_utc(game["_kickoff"]),
        "opponent": game["_away"] if home else game["_home"],
        "home_away": "home" if home else "away",
        "neutral_site": str(game.get("location") or "").strip().lower() == "neutral",
        "team_rest_days": _integer(team_rest),
        "opponent_rest_days": _integer(opponent_rest),
        "roof": game.get("roof") or None,
        "total_line": total,
        "team_expected_margin": margin,
        "implied_team_points": None if implied_team is None else round(implied_team, 2),
        "implied_opponent_points": (
            None if implied_opponent is None else round(implied_opponent, 2)
        ),
        "upcoming_bye_weeks": list(byes),
        "lines_source_id": lines_source_id if has_lines else None,
        "lines_retrieved_at_utc": (
            isoformat_utc(lines_retrieved_at) if has_lines and lines_retrieved_at else None
        ),
    }


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _integer(value: object) -> int | None:
    parsed = _number(value)
    return None if parsed is None else int(parsed)
