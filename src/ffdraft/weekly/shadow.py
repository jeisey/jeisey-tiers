"""The shadow record: v1 and v2 side by side, with every pregame input, never published (ADR-099).

v2 is judged prospectively (``frozen_v2.PROSPECTIVE_HOLDOUT``) on games that kick off after a
production refresh has retained, before kickoff, both models' quantiles and everything v2 read.
This module builds that record from the same frames the in-season build already holds. It is
written outside the public data directory, carried in the refresh's build record, and
appended to the private store by the job that retains it (``daily-refresh.yml``); the page
never reads it, and nothing in it changes a published number.

**When no promoted or shadow v2 artifact exists** the record still carries v1's quantiles and
the pregame inputs, so a later candidate can be judged on genuinely pregame evidence too.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ffdraft.timeutil import isoformat_utc
from ffdraft.weekly.forecast import reading_features
from ffdraft.weekly.frozen import WEEKLY_QUANTILE_LEVELS
from ffdraft.weekly.frozen_v2 import (
    DECISION_CUTOFF,
    V2_FAMILIES,
    WEEKLY_V2_MODEL_VERSION,
    WeeklySpecV2,
    v2_spec,
)
from ffdraft.weekly.lineup import health_features
from ffdraft.weekly.model import WeeklyModel, quantile_columns
from ffdraft.weekly.venues import VenueRegistry, roof_type_code

__all__ = [
    "DEFAULT_V2_MODEL_DIR",
    "SHADOW_RULE_VERSION",
    "attach_serving_v2_inputs",
    "build_shadow_rows",
    "load_v2_model",
]

SHADOW_RULE_VERSION = "weekly_shadow_record_v1"
DEFAULT_V2_MODEL_DIR = Path("models/shadow/weekly-startsit-v2")

#: What the prospective evaluation needs to rebuild v1's decision pools (the neutral B0 rule).
B0_INPUTS: tuple[str, ...] = (
    "ppg_to_date",
    "games_to_date",
    "prev1_fantasy_ppg_ppr",
    "prev1_fantasy_ppg_std",
    "games_last3",
    "ppg_last3",
    "game_team_points",
)


def load_v2_model(directory: Path) -> WeeklyModel | None:
    """The shadow v2 artifact, verified against the spec its own metadata declares, or None."""
    import json

    metadata_path = directory / "metadata.json"
    if not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    declared = metadata.get("spec") or {}
    if declared.get("model_version") != WEEKLY_V2_MODEL_VERSION:
        return None
    spec = v2_spec(
        tuple(declared.get("added_families") or ()),
        weather_parameters_digest=str(declared.get("weather_parameters_digest") or ""),
    )
    return WeeklyModel.load(directory, spec=spec)


def attach_serving_v2_inputs(
    playing: pl.DataFrame,
    *,
    forecasts: Mapping[str, Mapping[str, Any]],
    registry: VenueRegistry | None,
    schedule: pl.DataFrame,
    snaps: pl.DataFrame,
    weekly: pl.DataFrame,
    injuries: pl.DataFrame | None,
    season: int,
    through_week: int,
    as_of: datetime,
    team_column: str = "serve_team",
) -> tuple[pl.DataFrame, dict[str, str]]:
    """``playing`` plus every v2 input as serving sees it, and each game's weather status.

    The same functions training used: :func:`ffdraft.weekly.lineup.health_features` for the
    lineup and defence (the report as published at the build, ``null`` until it is final),
    and :func:`ffdraft.weekly.forecast.reading_features` for the weather (``null`` unless the
    retained reading is fresh, in range and plausible; the venue's roof type always).
    """
    target_week = through_week + 1
    stadiums = {
        str(row["game_id"]): (row.get("stadium_id"), row.get("stadium"))
        for row in schedule.filter(
            (pl.col("season") == season) & (pl.col("week") == target_week),
        ).iter_rows(named=True)
    }
    weather_rows: list[dict[str, Any]] = []
    statuses: dict[str, str] = {}
    for game_id in sorted({str(value) for value in playing.get_column("game_id").unique()}):
        stadium_id, stadium = stadiums.get(game_id, (None, None))
        venue = (
            registry.resolve(season=season, stadium_id=stadium_id, stadium=stadium)
            if registry is not None
            else None
        )
        code = roof_type_code(venue)
        reading = forecasts.get(game_id)
        kickoff_rows = playing.filter(pl.col("game_id") == game_id).get_column("kickoff_utc")
        kickoff = kickoff_rows[0] if kickoff_rows.len() else None
        if venue is None or venue.roof_type != "open" or kickoff is None:
            features = {
                "wx_roof_type": code,
                "wx_wind_mph": None,
                "wx_temp_f": None,
                "wx_precip": None,
            }
            status = (
                "no_venue"
                if venue is None
                else ("indoors" if venue.roof_type == "dome" else "roof_unknown")
            )
        else:
            features, status = reading_features(
                reading, as_of=as_of, kickoff=kickoff, roof_type_code=code
            )
        statuses[game_id] = status
        weather_rows.append({"game_id": game_id, **features})
    weather = pl.DataFrame(
        weather_rows,
        schema={
            "game_id": pl.String,
            "wx_roof_type": pl.Float64,
            "wx_wind_mph": pl.Float64,
            "wx_temp_f": pl.Float64,
            "wx_precip": pl.Float64,
        },
        orient="row",
    )
    frame = playing.drop([name for name in V2_FAMILIES["weather"] if name in playing.columns]).join(
        weather,
        on="game_id",
        how="left",
    )
    report = (
        injuries
        if injuries is not None
        else pl.DataFrame(
            schema={
                "season": pl.Int32,
                "week": pl.Int32,
                "gsis_id": pl.String,
                "team": pl.String,
                "position": pl.String,
                "report_status": pl.String,
                "practice_status": pl.String,
                "primary_injury": pl.String,
                "full_name": pl.String,
            },
        )
    )
    frame = health_features(
        frame,
        snaps=snaps,
        weekly=weekly,
        injuries=report,
        season=season,
        through_week=through_week,
        target_week=target_week,
        team_column=team_column,
        opponent_column="opponent",
    )
    return frame, statuses


def build_shadow_rows(
    *,
    frame: pl.DataFrame,
    v1_quantiles: np.ndarray,
    v2_model: WeeklyModel | None,
    as_of: datetime,
    weather_status: Mapping[str, str],
    build_id: str,
    sources: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """One shadow row per playing record: both models' quantiles and v2's inputs."""
    keys = quantile_columns(WEEKLY_QUANTILE_LEVELS)
    v2 = v2_model.predict(frame) if v2_model is not None else None
    v2_spec_obj: WeeklySpecV2 | None = v2_model.spec if v2_model is not None else None
    inputs = [name for names in V2_FAMILIES.values() for name in names]
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(frame.iter_rows(named=True)):
        kickoff = row.get("kickoff_utc")
        v1 = v1_quantiles[index]
        rows.append(
            {
                "rule": SHADOW_RULE_VERSION,
                "decision_cutoff": DECISION_CUTOFF["id"],
                "build_id": build_id,
                "as_of_utc": isoformat_utc(as_of),
                "season": int(row["season"]),
                "through_week": int(row["through_week"]),
                "target_week": int(row["target_week"]),
                "player_id": str(row["player_id"]),
                "gsis_id": row.get("gsis_id"),
                "position": str(row["position"]),
                "scoring_preset": str(row["scoring_preset"]),
                "team": row.get("serve_team") or row.get("team"),
                "opponent": row.get("opponent"),
                "game_id": str(row["game_id"]),
                "kickoff_utc": isoformat_utc(kickoff) if kickoff is not None else None,
                "pregame": kickoff is not None and kickoff > as_of,
                "v1": None
                if np.any(np.isnan(v1))
                else dict(zip(keys, [round(float(value), 4) for value in v1], strict=True)),
                "v2": None
                if v2 is None or np.any(np.isnan(v2[index]))
                else dict(zip(keys, [round(float(value), 4) for value in v2[index]], strict=True)),
                "v2_configuration_hash": v2_spec_obj.configuration_hash() if v2_spec_obj else None,
                "v2_inputs": {name: _number(row.get(name)) for name in inputs},
                "input_status": {
                    "weather": weather_status.get(str(row["game_id"])),
                    "own_report_final": row.get("own_report_final"),
                    "opp_report_final": row.get("opp_report_final"),
                },
                "b0_inputs": {name: _number(row.get(name)) for name in B0_INPUTS},
                "sources": dict(sources),
            },
        )
    return rows


def _number(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if number != number else round(number, 6)


def summarise(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "pregame": sum(1 for row in rows if row.get("pregame")),
        "with_v2": sum(1 for row in rows if row.get("v2") is not None),
    }
