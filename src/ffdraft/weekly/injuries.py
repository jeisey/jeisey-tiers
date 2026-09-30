"""The week's injury report, printed beside a projection and never read by one.

nflverse's ``load_injuries`` publishes the league's official weekly report: a game
designation (``Out``, ``Doubtful``, ``Questionable``) and the practice participation that led
to it. The weekly model deliberately does **not** read it — its target is points *given that
he plays* — because a designation changes what a manager should do far more than it changes
what a player scores once he is active. So the build prints the designation next to the
projection, and pairs it with the one number that makes it actionable: **how often players
carrying that designation actually appeared**, measured over completed seasons.

The file carries no timestamp of its own, so a report is stamped with the build's retrieval
time and labelled that way — the same treatment ``next_game_v1`` gives sportsbook lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import polars as pl

from ffdraft.contracts.enums import normalize_team_code
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "DESIGNATIONS",
    "INJURY_BASE_RATE_RULE_VERSION",
    "INJURY_REQUIRED_COLUMNS",
    "InjurySchemaError",
    "injury_base_rates",
    "normalize_injuries",
    "reports_for_week",
]

INJURY_BASE_RATE_RULE_VERSION = "designation_appearance_rate_v1"

#: The three designations the league's report uses for game status. ``Note`` and a null
#: status are not designations and are published as practice information only.
DESIGNATIONS: tuple[str, ...] = ("Out", "Doubtful", "Questionable")

INJURY_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "season",
        "game_type",
        "week",
        "gsis_id",
        "team",
        "report_status",
        "practice_status",
        "report_primary_injury",
        "position",
    },
)


class InjurySchemaError(ValueError):
    """The upstream injury file lost a column this layer reads."""


def normalize_injuries(raw: Any) -> pl.DataFrame:
    """Regular-season rows, one per ``(season, week, gsis_id)``, statuses as published."""
    frame = raw if isinstance(raw, pl.DataFrame) else pl.DataFrame(raw)
    missing = sorted(INJURY_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise InjurySchemaError(f"nflverse injuries is missing {missing}")
    return (
        frame.filter((pl.col("game_type") == "REG") & pl.col("gsis_id").is_not_null())
        .select(
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col("gsis_id").cast(pl.String),
            pl.col("team")
            .cast(pl.String)
            .map_elements(normalize_team_code, return_dtype=pl.String)
            .alias("team"),
            pl.col("position").cast(pl.String),
            pl.col("report_status").cast(pl.String),
            pl.col("practice_status").cast(pl.String),
            pl.col("report_primary_injury").cast(pl.String).alias("primary_injury"),
        )
        .unique(subset=["season", "week", "gsis_id"], keep="last", maintain_order=True)
    )


def injury_base_rates(
    injuries: pl.DataFrame,
    appeared: pl.DataFrame,
    *,
    seasons: Sequence[int],
) -> dict[str, dict[str, Any]]:
    """For each designation, the share of designated players who appeared that week.

    ``appeared`` holds one row per ``(season, week, gsis_id)`` appearance (a stats row or an
    offensive snap) in **every** scored week — not only the weeks a model targets, or a
    week-1 designation would always read as a missed game. Only skill positions a fantasy
    manager starts are counted, because a lineman's designation is not the question.
    """
    wanted = [int(season) for season in seasons]
    # Scored weeks only: a designation for the excluded final week would be compared with an
    # appearance table that, by construction, holds none for it.
    in_horizon = pl.lit(False)
    for season in wanted:
        horizon = fantasy_horizon(season)
        in_horizon = in_horizon | (
            (pl.col("season") == season)
            & (pl.col("week") >= horizon.first_week)
            & (pl.col("week") <= horizon.last_week)
        )
    scoped = injuries.filter(
        pl.col("season").is_in(wanted)
        & in_horizon
        & pl.col("report_status").is_in(list(DESIGNATIONS))
        & pl.col("position").is_in(["QB", "RB", "WR", "TE"]),
    )
    if scoped.is_empty():
        return {}
    marks = (
        appeared.select("season", "week", "gsis_id")
        .unique()
        .with_columns(
            pl.lit(True).alias("appeared"),
        )
    )
    joined = scoped.join(marks, on=["season", "week", "gsis_id"], how="left").with_columns(
        pl.col("appeared").fill_null(False),
    )
    rates: dict[str, dict[str, Any]] = {}
    for row in (
        joined.group_by("report_status")
        .agg(pl.len().alias("reports"), pl.col("appeared").sum().alias("appeared"))
        .iter_rows(named=True)
    ):
        reports = int(row["reports"])
        rates[str(row["report_status"])] = {
            "reports": reports,
            "appeared": int(row["appeared"]),
            "appearance_rate": round(int(row["appeared"]) / reports, 4) if reports else None,
        }
    rates["_rule"] = {
        "version": INJURY_BASE_RATE_RULE_VERSION,
        "seasons": wanted,
        "definition": (
            "Among QB/RB/WR/TE players the official report designated for a regular-season "
            "game, the share who then appeared in it (a stats row or an offensive snap)."
        ),
    }
    return rates


def reports_for_week(
    injuries: pl.DataFrame,
    *,
    season: int,
    week: int,
) -> dict[str, dict[str, Any]]:
    """``gsis_id -> report`` for one week, only for rows that say something."""
    rows = injuries.filter(
        (pl.col("season") == season)
        & (pl.col("week") == week)
        & (pl.col("report_status").is_not_null() | pl.col("practice_status").is_not_null()),
    )
    reports: dict[str, dict[str, Any]] = {}
    for row in rows.iter_rows(named=True):
        reports[str(row["gsis_id"])] = {
            "week": int(row["week"]),
            "designation": row["report_status"] if row["report_status"] in DESIGNATIONS else None,
            "practice_status": row["practice_status"],
            "primary_injury": row["primary_injury"],
        }
    return reports
