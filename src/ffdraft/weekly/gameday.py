"""The week's game-day context, per team (``weekly_gameday_context_v1``, ADR-099).

Published facts about each team's target-week game that a start/sit reader needs and that
the projection may or may not read:

* **the venue** — from the versioned registry (``config/venues.yaml``), with its fixed roof
  type, and the roof as v1 reads it: recorded, or for an unannounced retractable roof the
  stadium's state at its latest earlier home game, *flagged as assumed*;
* **the forecast** at the kickoff hour — provider, its update time, our retrieval time, the
  valid interval, the values in mph, deg F, inches and percent, and a status (``ok``,
  ``indoors``, ``roof_unknown``, ``stale``, ``out_of_range``, ``unavailable``, ...);
* **who is listed** — the team's lagged starters and notable skill players on the target
  week's report, with their designations, and whether the report carries game statuses yet;
* **his typical week and this one** — the team's shrunk mean lines over its completed games
  (the reference every explanation is measured against) and this week's game inputs.

Every value here is a fact or a published reference. None of it is a point adjustment: the
point effect of an input is published only where a served model reads it, in the projection's
``explanation`` block.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.timeutil import isoformat_utc
from ffdraft.weekly.context import team_game_context
from ffdraft.weekly.explain import team_line_reference
from ffdraft.weekly.forecast import ForecastStatus
from ffdraft.weekly.lineup import (
    absence_lists,
    designations_for_week,
    lagged_starters,
    recent_usage_shares,
)
from ffdraft.weekly.venues import VenueRegistry

__all__ = ["GAMEDAY_CONTEXT_RULE_VERSION", "build_weekly_context_records"]

GAMEDAY_CONTEXT_RULE_VERSION = "weekly_gameday_context_v1"


def _round(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if number != number else round(number, digits)


def build_weekly_context_records(
    *,
    schedule: pl.DataFrame,
    season: int,
    through_week: int,
    as_of: datetime,
    build_id: str,
    schema_version: str,
    registry: VenueRegistry | None,
    forecasts: Mapping[str, Mapping[str, Any]] | None,
    injuries: pl.DataFrame | None,
    snaps: pl.DataFrame | None,
    weekly: pl.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One record per team playing in the week after the cutoff, and a summary."""
    target_week = through_week + 1
    season_context = team_game_context(schedule, [season], venues=registry)
    games = season_context.filter(pl.col("week") == target_week)
    if games.is_empty():
        return [], {"target_week": target_week, "records": 0}
    lines = team_line_reference(season_context, season=season, through_week=through_week)
    teams = sorted(str(team) for team in games.get_column("team").unique())

    listed: dict[str, dict[str, Any]] = {}
    report_rows = 0
    if injuries is not None and snaps is not None:
        report = designations_for_week(injuries, season=season, week=target_week)
        report_rows = report.height
        starters = lagged_starters(snaps, season=season, through_week=through_week)
        shares = recent_usage_shares(weekly, season=season, through_week=through_week)
        listed = absence_lists(starters, shares, report, teams)

    stadiums: dict[str, tuple[str | None, str | None]] = {}
    #: The schedule's own roof value, published as ``roof.recorded`` even where a verified
    #: venue corrects the label the projection reads (context.py).
    scheduled_roofs: dict[str, str | None] = {}
    for row in schedule.filter(
        (pl.col("season") == season) & (pl.col("week") == target_week),
    ).iter_rows(named=True):
        stadiums[str(row["game_id"])] = (row.get("stadium_id"), row.get("stadium"))
        scheduled_roofs[str(row["game_id"])] = str(row.get("roof") or "").strip().lower() or None

    records: list[dict[str, Any]] = []
    statuses: dict[str, int] = {}
    for row in games.sort("team").iter_rows(named=True):
        team = str(row["team"])
        game_id = str(row["game_id"])
        stadium_id, stadium = stadiums.get(game_id, (None, None))
        venue = (
            registry.resolve(season=season, stadium_id=stadium_id, stadium=stadium)
            if registry is not None
            else None
        )
        forecast = dict((forecasts or {}).get(game_id) or {})
        if venue is not None and venue.roof_type == "dome":
            status = ForecastStatus.INDOORS
        elif venue is None:
            status = ForecastStatus.NO_VENUE
        else:
            status = str(forecast.get("status") or ForecastStatus.UNAVAILABLE)
        statuses[status] = statuses.get(status, 0) + 1
        weather = {
            "status": status,
            "provider": forecast.get("provider"),
            "wind_mph": forecast.get("wind_mph"),
            "gust_mph": forecast.get("gust_mph"),
            "temp_f": forecast.get("temp_f"),
            "precip_probability": forecast.get("precip_probability"),
            "precip_in": forecast.get("precip_in"),
            "short_forecast": forecast.get("short_forecast"),
            "valid_from_utc": forecast.get("valid_from_utc"),
            "valid_to_utc": forecast.get("valid_to_utc"),
            "provider_updated_utc": forecast.get("provider_updated_utc"),
            "retrieved_at_utc": forecast.get("retrieved_at_utc"),
        }
        if status in (ForecastStatus.INDOORS, ForecastStatus.NO_VENUE, ForecastStatus.UNAVAILABLE):
            for key in ("wind_mph", "gust_mph", "temp_f", "precip_probability", "precip_in"):
                weather[key] = None
        typical = lines.get(team) or lines.get("__league__") or {}
        kickoff = row.get("kickoff_utc")
        team_listed = listed.get(team) or {"report_final": False, "listed": []}
        records.append(
            {
                "schema_version": schema_version,
                "build_id": build_id,
                "season": season,
                "through_week": through_week,
                "target_week": target_week,
                "team": team,
                "game_id": game_id,
                "opponent": str(row["opponent"]),
                "home_away": str(row["home_away"]),
                "neutral_site": bool(row["neutral_site"]),
                "kickoff_utc": isoformat_utc(kickoff) if kickoff is not None else None,
                "context_rule_version": GAMEDAY_CONTEXT_RULE_VERSION,
                "venue": venue.public() if venue is not None else None,
                "roof": {
                    "recorded": scheduled_roofs.get(game_id),
                    "model_indoors": _round(row.get("game_indoors"), 0),
                    "assumed_from_last_home_game": bool(row.get("roof_inferred")),
                },
                "weather": weather,
                "lineup": {
                    "report_available": injuries is not None,
                    "report_final": bool(team_listed["report_final"]),
                    "listed": list(team_listed["listed"]),
                },
                "typical": {
                    "games": int(typical.get("games", 0.0)),
                    "total_line": _round(typical.get("total")),
                    "team_margin": _round(typical.get("margin")),
                    "team_points": _round(typical.get("team_points")),
                    "home_share": 0.5,
                    "indoors_share": _round(typical.get("indoors_share"), 3),
                },
                "this_week": {
                    "total_line": _round(row.get("game_total_line"), 1),
                    "team_margin": _round(row.get("game_team_margin"), 1),
                    "team_points": _round(row.get("game_team_points")),
                    "is_home": _round(row.get("game_is_home"), 0),
                    "rest_advantage": _round(row.get("game_rest_advantage"), 0),
                    "indoors": _round(row.get("game_indoors"), 0),
                },
            },
        )
    return records, {
        "target_week": target_week,
        "records": len(records),
        "weather_status": dict(sorted(statuses.items())),
        "report_rows": report_rows,
        "reports_final": sum(1 for record in records if record["lineup"]["report_final"]),
        "listed_players": sum(len(record["lineup"]["listed"]) for record in records),
        "venues_unresolved": sum(1 for record in records if record["venue"] is None),
    }
