"""Kickoff forecasts: fetched once per venue per refresh, retained, read at the decision cutoff.

**Providers** (``config/source-registry.yaml``, docs/DATA_SOURCES.md §20):

* **NWS** for a U.S. venue: ``/points/{lat},{lon}`` resolves the venue to a forecast grid
  cell, and the two links it returns are followed — ``forecastGridData`` for the numbers
  (temperature, wind speed and gusts, probability and amount of precipitation, each a layer of
  ISO-8601 ``start/duration`` intervals with an explicit unit) and ``forecastHourly`` for the
  forecaster's words at the kickoff hour. Public domain (a U.S. Government work); a
  descriptive User-Agent is required.
* **Open-Meteo** for any other venue, under its free non-commercial terms, attributed
  ("Weather data by Open-Meteo.com", CC BY 4.0).

**One fetch per venue per refresh.** Games at the same venue share it.

**What a reading carries.** Provider, its update time, our retrieval time, the valid interval
the kickoff fell in, units (always converted to mph, deg F, inches and percent here), and a
status. A reading is usable only with status ``ok``: missing, stale, out of range or out of
the plausible bounds is an explicit unknown, never a number.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ffdraft.timeutil import isoformat_utc, parse_utc
from ffdraft.weekly.frozen_v2 import WEATHER_PARITY_RULE
from ffdraft.weekly.venues import Venue

__all__ = [
    "FORECAST_RULE_VERSION",
    "NWS_SOURCE_ID",
    "OPEN_METEO_SOURCE_ID",
    "USER_AGENT",
    "ForecastStatus",
    "fetch_venue_forecast",
    "kickoff_reading",
    "reading_features",
]

FORECAST_RULE_VERSION = "kickoff_forecast_v1"
NWS_SOURCE_ID = "nws_api"
OPEN_METEO_SOURCE_ID = "open_meteo"
USER_AGENT = "jeisey-tiers (https://github.com/jeisey/jeisey-tiers)"

OPEN_METEO_HOURLY = (
    "temperature_2m",
    "wind_speed_10m",
    "wind_gusts_10m",
    "precipitation",
    "precipitation_probability",
)


class ForecastStatus:
    OK = "ok"
    INDOORS = "indoors"
    ROOF_UNKNOWN = "roof_unknown"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    OUT_OF_RANGE = "out_of_range"
    IMPLAUSIBLE = "implausible"
    NO_VENUE = "no_venue"


Getter = Callable[[str, str], tuple[int, Any]]


def http_get(url: str, accept: str) -> tuple[int, Any]:
    """One polite GET: descriptive User-Agent, bounded retries on 429/5xx. Network I/O."""
    last = 0
    for attempt in range(3):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last = int(error.code)
            if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            return last, None
        except (urllib.error.URLError, TimeoutError, ValueError):
            time.sleep(2 ** (attempt + 1))
    return last, None


# ------------------------------------------------------------------------------- units


def _c_to_f(value: float) -> float:
    return value * 9.0 / 5.0 + 32.0


_KMH_TO_MPH = 0.621371192
_MS_TO_MPH = 2.236936292
_MM_TO_IN = 1.0 / 25.4


def _convert(value: float | None, uom: str | None) -> float | None:
    """A grid value in its declared unit, as mph, deg F, inches or percent."""
    if value is None:
        return None
    unit = (uom or "").split(":")[-1]
    if unit == "degC":
        return _c_to_f(value)
    if unit == "degF":
        return value
    if unit == "km_h-1":
        return value * _KMH_TO_MPH
    if unit == "m_s-1":
        return value * _MS_TO_MPH
    if unit == "mm":
        return value * _MM_TO_IN
    if unit in ("percent", "in"):
        return value
    raise ValueError(f"unexpected unit {uom!r}")


_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


def _interval(valid_time: str) -> tuple[datetime, datetime]:
    start_text, duration = valid_time.split("/")
    start = parse_utc(start_text)
    match = _DURATION.match(duration)
    if not match:
        raise ValueError(f"unparsable duration {duration!r}")
    days, hours, minutes = (int(value or 0) for value in match.groups())
    return start, start + timedelta(days=days, hours=hours, minutes=minutes)


def _layer_at(layer: Mapping[str, Any] | None, at: datetime) -> tuple[float | None, str | None]:
    if not layer:
        return None, None
    for item in layer.get("values") or []:
        start, end = _interval(str(item["validTime"]))
        if start <= at < end:
            value = item.get("value")
            return _convert(None if value is None else float(value), layer.get("uom")), str(
                item["validTime"],
            )
    return None, None


# ----------------------------------------------------------------------------- fetching


@dataclass
class VenueForecast:
    """One venue's forecast payloads as retrieved, with the provider's own times."""

    venue_id: str
    provider: str
    retrieved_at_utc: datetime
    status: int
    grid: Mapping[str, Any] | None = None
    hourly: Mapping[str, Any] | None = None
    open_meteo: Mapping[str, Any] | None = None
    points: Mapping[str, Any] | None = None
    error: str | None = None


def fetch_venue_forecast(
    venue: Venue,
    *,
    get: Getter = http_get,
    now: Callable[[], datetime] | None = None,
) -> VenueForecast:
    """Fetch one venue's forecast from its provider. **Network I/O** unless ``get`` is a stub."""
    clock = now or (lambda: datetime.now(UTC))
    if venue.forecast_provider == "nws":
        point_url = f"https://api.weather.gov/points/{venue.latitude:.4f},{venue.longitude:.4f}"
        status, point = get(point_url, "application/geo+json")
        if point is None:
            return VenueForecast(venue.venue_id, "nws", clock(), status, error="points")
        properties = point.get("properties") or {}
        grid_status, grid = get(str(properties.get("forecastGridData")), "application/geo+json")
        hourly_status, hourly = get(str(properties.get("forecastHourly")), "application/geo+json")
        return VenueForecast(
            venue.venue_id,
            "nws",
            clock(),
            grid_status if grid is None else hourly_status,
            grid=(grid or {}).get("properties"),
            hourly=(hourly or {}).get("properties"),
            points={
                key: properties.get(key)
                for key in ("gridId", "gridX", "gridY", "forecastGridData", "forecastHourly")
            },
            error=None if grid is not None else "forecastGridData",
        )
    query = urllib.parse.urlencode(
        {
            "latitude": f"{venue.latitude:.4f}",
            "longitude": f"{venue.longitude:.4f}",
            "hourly": ",".join(OPEN_METEO_HOURLY),
            "timezone": "GMT",
            "forecast_days": "16",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        },
    )
    status, payload = get(f"https://api.open-meteo.com/v1/forecast?{query}", "application/json")
    return VenueForecast(
        venue.venue_id,
        "open_meteo",
        clock(),
        status,
        open_meteo=payload,
        error=None if payload is not None else "forecast",
    )


# ------------------------------------------------------------------------------ reading


def _empty(provider: str | None, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "rule": FORECAST_RULE_VERSION,
        "provider": provider,
        "status": status,
        "wind_mph": None,
        "gust_mph": None,
        "temp_f": None,
        "precip_probability": None,
        "precip_in": None,
        "short_forecast": None,
        "valid_from_utc": None,
        "valid_to_utc": None,
        "provider_updated_utc": None,
        "retrieved_at_utc": None,
        **extra,
    }


def kickoff_reading(
    forecast: VenueForecast | None,
    *,
    venue: Venue | None,
    kickoff: datetime,
) -> dict[str, Any]:
    """The forecast at the kickoff hour, converted, with its status. Never raises on data."""
    if venue is None:
        return _empty(None, ForecastStatus.NO_VENUE)
    if venue.roof_type == "dome":
        return _empty(None, ForecastStatus.INDOORS)
    if forecast is None or forecast.error is not None:
        return _empty(forecast.provider if forecast else None, ForecastStatus.UNAVAILABLE)
    retrieved = isoformat_utc(forecast.retrieved_at_utc)
    hour = kickoff.replace(minute=0, second=0, microsecond=0)
    if forecast.provider == "nws":
        grid = forecast.grid or {}
        temp, valid = _layer_at(grid.get("temperature"), hour)
        wind, _ = _layer_at(grid.get("windSpeed"), hour)
        gust, _ = _layer_at(grid.get("windGust"), hour)
        pop, _ = _layer_at(grid.get("probabilityOfPrecipitation"), hour)
        qpf, _ = _layer_at(grid.get("quantitativePrecipitation"), hour)
        short = None
        for period in (forecast.hourly or {}).get("periods") or []:
            if parse_utc(str(period["startTime"])) <= hour < parse_utc(str(period["endTime"])):
                short = period.get("shortForecast")
                break
        updated = grid.get("updateTime")
        start, end = (None, None) if valid is None else _interval(valid)
    else:
        payload = forecast.open_meteo or {}
        hourly = payload.get("hourly") or {}
        times = list(hourly.get("time") or [])
        key = hour.strftime("%Y-%m-%dT%H:%M")
        if key not in times:
            return _empty(
                forecast.provider,
                ForecastStatus.OUT_OF_RANGE,
                retrieved_at_utc=retrieved,
            )
        index = times.index(key)

        def value(name: str) -> float | None:
            series = hourly.get(name) or []
            item = series[index] if index < len(series) else None
            return None if item is None else float(item)

        temp, wind, gust = value("temperature_2m"), value("wind_speed_10m"), value("wind_gusts_10m")
        pop, qpf = value("precipitation_probability"), value("precipitation")
        short = None
        updated = None
        start, end = hour, hour + timedelta(hours=1)
    if temp is None and wind is None:
        return _empty(forecast.provider, ForecastStatus.OUT_OF_RANGE, retrieved_at_utc=retrieved)
    reading = _empty(
        forecast.provider,
        ForecastStatus.OK,
        wind_mph=None if wind is None else round(wind, 1),
        gust_mph=None if gust is None else round(gust, 1),
        temp_f=None if temp is None else round(temp, 1),
        precip_probability=None if pop is None else round(pop, 0),
        precip_in=None if qpf is None else round(qpf, 3),
        short_forecast=short,
        valid_from_utc=isoformat_utc(start) if start else None,
        valid_to_utc=isoformat_utc(end) if end else None,
        provider_updated_utc=str(updated) if updated else None,
        retrieved_at_utc=retrieved,
    )
    if venue.roof_type in ("retractable", "unverified"):
        # Outside conditions, published as context: whether they reach the field is unknown.
        reading["status"] = ForecastStatus.ROOF_UNKNOWN
    return reading


def reading_features(
    reading: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    kickoff: datetime,
    roof_type_code: float | None,
) -> tuple[dict[str, float | None], str]:
    """The four ``weather`` family inputs from a reading at the refresh, and the status used.

    ``null`` unless the reading is ``ok``, the forecast was retrieved within the declared age
    of the refresh, the kickoff is within the declared lead, and the values are plausible.
    """
    rule = WEATHER_PARITY_RULE
    unknown: dict[str, float | None] = {
        "wx_roof_type": roof_type_code,
        "wx_wind_mph": None,
        "wx_temp_f": None,
        "wx_precip": None,
    }
    if reading is None:
        return unknown, ForecastStatus.UNAVAILABLE
    status = str(reading.get("status"))
    if status != ForecastStatus.OK:
        return unknown, status
    retrieved = reading.get("retrieved_at_utc")
    if retrieved is None or as_of - parse_utc(str(retrieved)) > timedelta(
        hours=rule.max_forecast_age_hours,
    ):
        return unknown, ForecastStatus.STALE
    if kickoff - as_of > timedelta(hours=rule.max_lead_hours):
        return unknown, ForecastStatus.OUT_OF_RANGE
    wind = reading.get("wind_mph")
    temp = reading.get("temp_f")
    pop = reading.get("precip_probability")
    if wind is None or temp is None:
        return unknown, ForecastStatus.OUT_OF_RANGE
    if not (
        rule.wind_mph_range[0] <= float(wind) <= rule.wind_mph_range[1]
        and rule.temp_f_range[0] <= float(temp) <= rule.temp_f_range[1]
    ):
        return unknown, ForecastStatus.IMPLAUSIBLE
    precip = (
        None
        if pop is None
        else (1.0 if float(pop) >= rule.precipitation_probability_threshold else 0.0)
    )
    return (
        {
            "wx_roof_type": roof_type_code,
            "wx_wind_mph": float(wind),
            "wx_temp_f": float(temp),
            "wx_precip": precip,
        },
        ForecastStatus.OK,
    )


def forecast_capture_rows(
    venues: Sequence[Venue],
    games: Sequence[Mapping[str, Any]],
    forecasts: Mapping[str, VenueForecast],
) -> list[dict[str, Any]]:
    """One retained row per upcoming game: the venue, the kickoff and the kickoff reading."""
    by_id = {venue.venue_id: venue for venue in venues}
    rows: list[dict[str, Any]] = []
    for game in sorted(games, key=lambda item: (str(item["kickoff_utc"]), str(item["game_id"]))):
        venue = by_id.get(str(game.get("venue_id") or ""))
        kickoff = game["kickoff_utc"]
        reading = kickoff_reading(
            forecasts.get(venue.venue_id) if venue else None,
            venue=venue,
            kickoff=kickoff,
        )
        rows.append(
            {
                "game_id": str(game["game_id"]),
                "season": int(game["season"]),
                "week": int(game["week"]),
                "kickoff_utc": isoformat_utc(kickoff),
                "venue_id": venue.venue_id if venue else None,
                "roof_type": venue.roof_type if venue else None,
                **reading,
            },
        )
    return rows
