"""Serving the weekly start/sit model inside the in-season build (ADR-096).

The in-season build already holds everything this needs: the rest-of-season snapshot at the
cutoff (the model's feature frame), the season's weekly rows (for the opponent reading), and
the schedule (for the game). This module joins them for the week after the cutoff, predicts,
explains the median, and writes one record per player and scoring preset.

**Which players.** The Opportunity Board's players — the same population the usage layer
describes — so every card that can be opened can be compared, and nothing is projected for a
card nobody can open. A player the build cannot place on a team is skipped; a player whose
team is on bye is published as ``bye`` with no distribution, because "he is not playing" is
the answer a start/sit reader needs, not an absence.

**Which team.** The current roster's club when the roster names exactly one, else the club
he last played for. A trade between the cutoff and the game moves the game, and the roster
is what knows.

**Kicked off.** A Thursday game read on a Friday is marked ``kicked_off`` and kept: the
decision is gone but the projection is part of the record of what the model said.

**Lines pending.** Every training row had a posted total and spread (155,634 of 155,634), so
the boosters never learned a missing line, and LightGBM routes a missing value exactly as it
routes 0.0: a game with no posted line would be projected as a zero-point total, about 0.7
points low for a typical receiver, with nothing on the page to say so. Such a game is
published as ``lines_pending`` instead: the game and the opponent reading, no distribution,
no drivers. Imputing a line would be inventing a market number, and a projection the model
was never validated on is not one to publish.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.timeutil import isoformat_utc
from ffdraft.weekly.context import opponent_allowed, scored_position_rows, team_game_context
from ffdraft.weekly.dataset import attach_game_and_opponent
from ffdraft.weekly.explain import (
    explain_frame,
    opponent_reference,
    published_explanation,
    team_line_reference,
)
from ffdraft.weekly.frozen import (
    FEATURE_FAMILIES,
    WEEKLY_MODEL_VERSION,
    WEEKLY_POSITIONS,
    WEEKLY_QUANTILE_LEVELS,
)
from ffdraft.weekly.model import WeeklyModel, quantile_columns
from ffdraft.weekly.venues import VenueRegistry

__all__ = ["WeeklyServeResult", "build_weekly_projection_records"]

_QUANTILE_KEYS = quantile_columns(WEEKLY_QUANTILE_LEVELS)

#: The sportsbook inputs a projection cannot be made without (see the module docstring).
LINE_COLUMNS: tuple[str, ...] = ("game_total_line", "game_team_margin", "game_team_points")


class WeeklyServeResult:
    """The records plus a summary the metadata and the quality gate read.

    ``frame`` and ``quantiles`` are the playing rows exactly as the model read them and its
    calibrated quantiles, for the private shadow record (ADR-099); never published.
    """

    def __init__(
        self,
        records: list[dict[str, Any]],
        summary: dict[str, Any],
        *,
        frame: pl.DataFrame | None = None,
        quantiles: np.ndarray | None = None,
    ) -> None:
        self.records = records
        self.summary = summary
        self.frame = frame
        self.quantiles = quantiles


def build_weekly_projection_records(
    *,
    model: WeeklyModel,
    snapshot: pl.DataFrame,
    players: Mapping[str, Mapping[str, Any]],
    current_teams: Mapping[str, str | None],
    weekly: pl.DataFrame,
    schedule: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    season: int,
    through_week: int,
    as_of: datetime,
    build_id: str,
    schema_version: str,
    injury_reports: Mapping[str, Mapping[str, Any]] | None = None,
    venues: VenueRegistry | None = None,
) -> WeeklyServeResult:
    target_week = through_week + 1
    horizon = fantasy_horizon(season)
    if not horizon.contains(target_week):
        return WeeklyServeResult([], {"target_week": None, "reason": "season_complete"})

    # ADR-102: a player the employment reading settles as having no club (verified unsigned,
    # retired) maps to an explicit None. He has no next game, and the last club he played
    # for — `team_to_date` — must not stand in for one.
    no_club = sorted(player_id for player_id, team in current_teams.items() if team is None)
    known_clubs = {player_id: team for player_id, team in current_teams.items() if team is not None}
    frame = (
        snapshot.filter(
            pl.col("player_id").is_in(list(players))
            & pl.col("position").is_in(list(WEEKLY_POSITIONS))
            & ~pl.col("player_id").is_in(no_club),
        )
        .with_columns(
            pl.lit(season, dtype=pl.Int32).alias("season"),
            pl.lit(through_week, dtype=pl.Int32).alias("through_week"),
            pl.lit(target_week, dtype=pl.Int32).alias("target_week"),
        )
        .with_columns(
            pl.coalesce(
                pl.col("player_id").replace_strict(
                    known_clubs,
                    default=None,
                    return_dtype=pl.String,
                ),
                pl.col("team_to_date"),
            ).alias("serve_team"),
        )
        .filter(pl.col("serve_team").is_not_null())
    )
    if frame.is_empty():
        return WeeklyServeResult([], {"target_week": target_week, "reason": "no_players"})

    # The venue registry's verified fixed roof wins over the schedule's (context.py).
    season_context = team_game_context(schedule, [season], venues=venues)
    context = season_context.filter(pl.col("week") == target_week)
    scored = scored_position_rows(weekly, scoring, [season - 1, season])
    allowed = opponent_allowed(scored, season=season, through_week=through_week)
    playing = attach_game_and_opponent(
        frame,
        context=context,
        allowed=allowed,
        team_column="serve_team",
    ).sort("scoring_preset", "position", "player_id")
    byes = frame.join(
        playing.select("player_id", "scoring_preset"),
        on=["player_id", "scoring_preset"],
        how="anti",
    ).sort("scoring_preset", "position", "player_id")

    # The posted lines, or no projection (see the module docstring). Only the lines: a missing
    # total reads as a zero-point game, far outside anything trained on, while a missing rest
    # or roof reads as equal rest or open air, which are ordinary values (an unannounced roof
    # is first filled from the stadium's recorded state, `team_game_context`).
    complete = pl.all_horizontal(
        [
            pl.col(column).cast(pl.Float64).is_not_null()
            & pl.col(column).cast(pl.Float64).is_not_nan()
            for column in LINE_COLUMNS
        ],
    )
    pending = playing.filter(~complete)
    playing = playing.filter(complete)

    quantiles = model.predict(playing)
    drivers = model.drivers(playing)
    # His typical week (typical_week_shapley_v1): the same player in an ordinary game for him,
    # from his team's completed games and a league-average defence at this cutoff.
    lines = team_line_reference(season_context, season=season, through_week=through_week)
    explanations = explain_frame(
        model,
        playing,
        lines=lines,
        opponent_typical=opponent_reference(allowed),
        team_column="serve_team",
    )
    reports = injury_reports or {}
    records: list[dict[str, Any]] = []
    counts = {"upcoming": 0, "kicked_off": 0, "bye": 0, "lines_pending": 0, "unmodelled": 0}

    for index, row in enumerate(playing.iter_rows(named=True)):
        values = quantiles[index]
        if np.any(np.isnan(values)):
            counts["unmodelled"] += 1
            continue
        kickoff = row.get("kickoff_utc")
        state = "upcoming" if kickoff is None or kickoff > as_of else "kicked_off"
        counts[state] += 1
        rounded = [round(float(value), 2) for value in values]
        published = dict(zip(_QUANTILE_KEYS, rounded, strict=True))
        records.append(
            _record(
                row,
                players=players,
                state=state,
                game=_game(row),
                quantiles=published,
                drivers=_drivers(drivers[index], rounded[WEEKLY_QUANTILE_LEVELS.index(0.5)]),
                explanation=published_explanation(explanations[index], published),
                opponent=_opponent(row),
                injury=reports.get(str(row["gsis_id"]) if row.get("gsis_id") else ""),
                build_id=build_id,
                schema_version=schema_version,
                season=season,
                through_week=through_week,
                target_week=target_week,
            ),
        )
    for row in pending.iter_rows(named=True):
        counts["lines_pending"] += 1
        records.append(
            _record(
                row,
                players=players,
                state="lines_pending",
                game=_game(row),
                quantiles=None,
                drivers=None,
                opponent=_opponent(row),
                injury=reports.get(str(row["gsis_id"]) if row.get("gsis_id") else ""),
                build_id=build_id,
                schema_version=schema_version,
                season=season,
                through_week=through_week,
                target_week=target_week,
            ),
        )
    for row in byes.iter_rows(named=True):
        counts["bye"] += 1
        records.append(
            _record(
                row,
                players=players,
                state="bye",
                game=None,
                quantiles=None,
                drivers=None,
                opponent=None,
                injury=reports.get(str(row["gsis_id"]) if row.get("gsis_id") else ""),
                build_id=build_id,
                schema_version=schema_version,
                season=season,
                through_week=through_week,
                target_week=target_week,
            ),
        )
    lined = int(playing.filter(pl.col("game_total_line").is_not_null()).height)
    return WeeklyServeResult(
        records,
        frame=playing,
        quantiles=quantiles,
        summary={
            "target_week": target_week,
            "records": len(records),
            **counts,
            "rows_with_lines": lined,
            "rows_playing": playing.height + pending.height,
            "injury_reports_matched": sum(1 for record in records if record["injury"] is not None),
        },
    )


def _game(row: Mapping[str, Any]) -> dict[str, Any]:
    kickoff = row.get("kickoff_utc")
    return {
        "game_id": str(row["game_id"]),
        "opponent": str(row["opponent"]),
        "home_away": str(row["home_away"]),
        "neutral_site": bool(row["neutral_site"]),
        "kickoff_utc": isoformat_utc(kickoff) if kickoff is not None else None,
        "roof": row.get("roof"),
        "total_line": _maybe(row.get("game_total_line")),
        "team_margin": _maybe(row.get("game_team_margin")),
        "team_points": _maybe(row.get("game_team_points"), 2),
    }


def _opponent(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "defense": str(row["opponent"]),
        "allowed_ppg": _maybe(row.get("opp_allowed_ppg"), 2),
        "league_ppg": _maybe(row.get("league_ppg"), 2),
        "index": _maybe(row.get("opp_allowed_index"), 3),
        "rank": _integer(row.get("opp_allowed_rank")),
        "defenses": _integer(row.get("opp_defenses")),
        "games": _maybe(row.get("opp_games_to_date"), 1),
    }


def _record(
    row: Mapping[str, Any],
    *,
    players: Mapping[str, Mapping[str, Any]],
    state: str,
    game: Mapping[str, Any] | None,
    quantiles: Mapping[str, float] | None,
    drivers: Mapping[str, float] | None,
    opponent: Mapping[str, Any] | None,
    explanation: Mapping[str, Any] | None = None,
    injury: Mapping[str, Any] | None,
    build_id: str,
    schema_version: str,
    season: int,
    through_week: int,
    target_week: int,
) -> dict[str, Any]:
    player_id = str(row["player_id"])
    identity = players.get(player_id, {})
    return {
        "schema_version": schema_version,
        "build_id": build_id,
        "season": season,
        "through_week": through_week,
        "target_week": target_week,
        "player_id": player_id,
        "display_name": str(identity.get("display_name") or row.get("display_name") or player_id),
        "position": str(row["position"]),
        "team": str(row["serve_team"]),
        "scoring_preset": str(row["scoring_preset"]),
        "model_version": WEEKLY_MODEL_VERSION,
        "game_state": state,
        "game": dict(game) if game is not None else None,
        "quantiles": dict(quantiles) if quantiles is not None else None,
        "drivers": dict(drivers) if drivers is not None else None,
        "explanation": dict(explanation) if explanation is not None else None,
        "opponent": dict(opponent) if opponent is not None else None,
        "injury": dict(injury) if injury is not None else None,
    }


def _drivers(account: Mapping[str, Any] | None, median: float) -> dict[str, float] | None:
    """Rounded, and closed: ``rearrangement`` absorbs rounding so the ten sum to the median."""
    if account is None:
        return None
    parts = {"baseline": round(float(account["baseline"]), 2)}
    for family in FEATURE_FAMILIES:
        parts[str(family)] = round(float(account["families"][family]), 2)
    parts["calibration"] = round(float(account["calibration"]), 2)
    parts["rearrangement"] = round(median - sum(parts.values()), 2)
    return parts


def _maybe(value: Any, digits: int = 1) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if number != number else round(number, digits)


def _integer(value: Any) -> int | None:
    return None if value is None else int(value)
