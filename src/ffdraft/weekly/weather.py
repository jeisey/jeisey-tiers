"""Weather at kickoff: what training reads, what serving reads, and why they match.

Three inputs per game at an **open-air** venue — wind (mph), temperature (deg F) and whether
precipitation is expected at kickoff — plus the venue's fixed roof type for every game
(``wx_roof_type``: 0 open, 1 retractable, 2 dome, from ``config/venues.yaml``).

**Serving reads a forecast** (``ffdraft.weekly.forecast``): NWS's gridded forecast for a U.S.
venue, Open-Meteo's for any other, at the kickoff hour, from the newest capture at or before
the refresh. A forecast that is missing, older than the declared age, does not cover the
kickoff hour or is out of range is ``null`` — unknown, never a number.

**Training cannot read a forecast** for 2017-2025 — nobody archived NWS's at kickoff — so it
reads the game book's recorded kickoff weather (nflverse's schedule ``temp``/``wind`` and the
play-by-play ``weather`` text) and maps it to what a forecast would have said
(:func:`training_weather`, ``weather_training_parity_v1``): ``a + b * recorded + e`` with the
map and the residual pool measured on archived day-before forecasts, ``e`` drawn by a hash of
the game id, and recorded precipitation turned into "expected" with the measured hit and
false-alarm rates. A model trained on recorded weather would read a forecast as if it were the
truth; this one has seen the noise.

**What is never weather.** A dome's game gets no weather (``null``) — nothing reaches the
field. A retractable roof's game gets none either, at training and at serving alike, because
its state is announced only on game day; an earlier closed-roof game is not evidence that this
one is indoors. A game whose venue the registry cannot resolve, or whose venue's roof type
the evidence does not establish (``unverified``), gets no roof type and no weather.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from ffdraft.paths import repo_root
from ffdraft.weekly.venues import VenueRegistry, roof_type_code

__all__ = [
    "GAME_BOOK_PRECIP_RULE",
    "WEATHER_FEATURES",
    "WeatherErrorModel",
    "game_book_precipitation",
    "load_error_model",
    "training_weather",
]

GAME_BOOK_PRECIP_RULE = "game_book_precip_v1"

WEATHER_FEATURES: tuple[str, ...] = ("wx_roof_type", "wx_wind_mph", "wx_temp_f", "wx_precip")

#: A precipitation word in the game book's conditions. "Chance of rain" and "40% rain" are
#: forecasts printed in the book, not conditions, and do not count.
_PRECIP = re.compile(
    r"\b(rain\w*|showers?|drizzle\w*|snow\w*|sleet|flurr\w*|thunder\w*|t-?storms?|storms?|"
    r"wintry|hail|precip\w*)\b",
    re.IGNORECASE,
)
_HEDGE = re.compile(r"(chance|%|possible|possibility|threat)\W*(of\W*)?$", re.IGNORECASE)


def game_book_precipitation(text: str | None) -> int | None:
    """1 when the game book's kickoff conditions name precipitation, 0 when not, None blank.

    ``game_book_precip_v1``: a precipitation word not immediately hedged as a chance.
    """
    if text is None or not str(text).strip():
        return None
    for match in _PRECIP.finditer(str(text)):
        before = str(text)[max(0, match.start() - 20) : match.start()]
        if _HEDGE.search(before):
            continue
        return 1
    return 0


@dataclass(frozen=True)
class WeatherErrorModel:
    """The measured map from recorded kickoff weather to a short-lead forecast."""

    digest: str
    wind_intercept: float
    wind_slope: float
    wind_residuals: tuple[float, ...]
    temp_intercept: float
    temp_slope: float
    temp_residuals: tuple[float, ...]
    precip_hit_rate: float
    precip_false_alarm_rate: float
    wind_range: tuple[float, float]
    temp_range: tuple[float, float]
    document: Mapping[str, Any]


DEFAULT_ERROR_MODEL = Path("config/weather-forecast-error-v1.json")


def load_error_model(path: Path | None = None) -> WeatherErrorModel:
    resolved = path or (repo_root() / DEFAULT_ERROR_MODEL)
    raw = resolved.read_bytes()
    document = json.loads(raw)
    wind = document["wind_mph"]
    temp = document["temp_f"]
    precip = document["precipitation"]
    return WeatherErrorModel(
        digest=hashlib.sha256(raw).hexdigest()[:16],
        wind_intercept=float(wind["intercept"]),
        wind_slope=float(wind["slope"]),
        wind_residuals=tuple(float(value) for value in wind["residuals"]),
        temp_intercept=float(temp["intercept"]),
        temp_slope=float(temp["slope"]),
        temp_residuals=tuple(float(value) for value in temp["residuals"]),
        precip_hit_rate=float(precip["hit_rate"]),
        precip_false_alarm_rate=float(precip["false_alarm_rate"]),
        wind_range=(
            float(document["ranges"]["wind_mph"][0]),
            float(document["ranges"]["wind_mph"][1]),
        ),
        temp_range=(float(document["ranges"]["temp_f"][0]), float(document["ranges"]["temp_f"][1])),
        document=document,
    )


def _unit(*parts: object) -> float:
    """A deterministic uniform draw in [0, 1) from the parts' hash."""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _pick(pool: Sequence[float], *parts: object) -> float:
    return pool[int(_unit(*parts) * len(pool)) % len(pool)]


def _clip(value: float, bounds: tuple[float, float]) -> float:
    return min(bounds[1], max(bounds[0], value))


def training_weather(
    games: pl.DataFrame,
    *,
    registry: VenueRegistry,
    error_model: WeatherErrorModel,
) -> pl.DataFrame:
    """``weather_training_parity_v1`` per game: one row per ``game_id``.

    ``games`` carries ``game_id, season, stadium_id, stadium, temp, wind, weather_text``.
    Returns ``game_id, venue_id, wx_roof_type, wx_wind_mph, wx_temp_f, wx_precip``.
    """
    rows: list[dict[str, Any]] = []
    for game in games.iter_rows(named=True):
        venue = registry.resolve(
            season=int(game["season"]),
            stadium_id=game.get("stadium_id"),
            stadium=game.get("stadium"),
        )
        game_id = str(game["game_id"])
        row: dict[str, Any] = {
            "game_id": game_id,
            "venue_id": venue.venue_id if venue else None,
            "wx_roof_type": roof_type_code(venue),
            "wx_wind_mph": None,
            "wx_temp_f": None,
            "wx_precip": None,
        }
        if venue is not None and venue.roof_type == "open":
            wind = game.get("wind")
            temp = game.get("temp")
            if wind is not None and temp is not None:
                residual_w = _pick(error_model.wind_residuals, game_id, "wind")
                residual_t = _pick(error_model.temp_residuals, game_id, "temp")
                row["wx_wind_mph"] = round(
                    _clip(
                        error_model.wind_intercept
                        + error_model.wind_slope * float(wind)
                        + residual_w,
                        error_model.wind_range,
                    ),
                    2,
                )
                row["wx_temp_f"] = round(
                    _clip(
                        error_model.temp_intercept
                        + error_model.temp_slope * float(temp)
                        + residual_t,
                        error_model.temp_range,
                    ),
                    2,
                )
            observed = game_book_precipitation(game.get("weather_text"))
            if observed is not None and row["wx_wind_mph"] is not None:
                rate = (
                    error_model.precip_hit_rate if observed else error_model.precip_false_alarm_rate
                )
                row["wx_precip"] = 1.0 if _unit(game_id, "precip") < rate else 0.0
        rows.append(row)
    schema = {
        "game_id": pl.String(),
        "venue_id": pl.String(),
        "wx_roof_type": pl.Float64(),
        "wx_wind_mph": pl.Float64(),
        "wx_temp_f": pl.Float64(),
        "wx_precip": pl.Float64(),
    }
    return pl.DataFrame(rows, schema=schema, orient="row")
