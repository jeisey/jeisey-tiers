"""Kickoff forecasts: units converted, intervals honoured, unknowns explicit (ADR-099)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ffdraft.weekly.forecast import (
    ForecastStatus,
    VenueForecast,
    fetch_venue_forecast,
    kickoff_reading,
    reading_features,
)
from ffdraft.weekly.venues import Venue

KICKOFF = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
RETRIEVED = datetime(2026, 10, 4, 11, 0, tzinfo=UTC)


def _venue(roof: str = "open", provider: str = "nws") -> Venue:
    return Venue(
        venue_id="buf-highmark",
        name="Highmark Stadium",
        country="US" if provider == "nws" else "GB",
        latitude=42.7738,
        longitude=-78.787,
        roof_type=roof,
        forecast_provider=provider,
        schedule_ids=("BUF00",),
        aliases=("Highmark Stadium",),
        first_season=2026,
        last_season=None,
        provenance={"coordinates": "test", "roof_type": "test"},
    )


def _grid() -> dict[str, object]:
    return {
        "updateTime": "2026-10-04T10:12:00+00:00",
        "temperature": {
            "uom": "wmoUnit:degC",
            "values": [{"validTime": "2026-10-04T15:00:00+00:00/PT3H", "value": 5.0}],
        },
        "windSpeed": {
            "uom": "wmoUnit:km_h-1",
            "values": [{"validTime": "2026-10-04T16:00:00+00:00/PT2H", "value": 32.0}],
        },
        "windGust": {
            "uom": "wmoUnit:km_h-1",
            "values": [{"validTime": "2026-10-04T16:00:00+00:00/PT2H", "value": 48.0}],
        },
        "probabilityOfPrecipitation": {
            "uom": "wmoUnit:percent",
            "values": [{"validTime": "2026-10-04T12:00:00+00:00/PT6H", "value": 70}],
        },
        "quantitativePrecipitation": {
            "uom": "wmoUnit:mm",
            "values": [{"validTime": "2026-10-04T12:00:00+00:00/PT6H", "value": 2.54}],
        },
    }


def _nws(grid: dict[str, object] | None = None) -> VenueForecast:
    return VenueForecast(
        venue_id="buf-highmark",
        provider="nws",
        retrieved_at_utc=RETRIEVED,
        status=200,
        grid=grid if grid is not None else _grid(),
        hourly={
            "periods": [
                {
                    "startTime": "2026-10-04T13:00:00-04:00",
                    "endTime": "2026-10-04T14:00:00-04:00",
                    "shortForecast": "Rain And Breezy",
                },
            ],
        },
    )


def test_an_nws_grid_reading_is_converted_to_mph_fahrenheit_and_inches() -> None:
    reading = kickoff_reading(_nws(), venue=_venue(), kickoff=KICKOFF)
    assert reading["status"] == ForecastStatus.OK
    assert reading["temp_f"] == pytest.approx(41.0)
    assert reading["wind_mph"] == pytest.approx(19.9)
    assert reading["gust_mph"] == pytest.approx(29.8)
    assert reading["precip_probability"] == 70
    assert reading["precip_in"] == pytest.approx(0.1)
    assert reading["short_forecast"] == "Rain And Breezy"
    assert reading["valid_from_utc"] == "2026-10-04T15:00:00Z"
    assert reading["provider_updated_utc"] == "2026-10-04T10:12:00+00:00"


def test_a_kickoff_beyond_every_interval_is_out_of_range_not_a_number() -> None:
    reading = kickoff_reading(_nws(), venue=_venue(), kickoff=KICKOFF + timedelta(days=3))
    assert reading["status"] == ForecastStatus.OUT_OF_RANGE
    assert reading["wind_mph"] is None and reading["temp_f"] is None


def test_a_dome_never_has_weather_and_a_retractable_roof_is_unknown() -> None:
    assert kickoff_reading(_nws(), venue=_venue("dome"), kickoff=KICKOFF)["status"] == "indoors"
    retractable = kickoff_reading(_nws(), venue=_venue("retractable"), kickoff=KICKOFF)
    assert retractable["status"] == ForecastStatus.ROOF_UNKNOWN
    assert retractable["wind_mph"] is not None  # outside conditions, published as context


def test_an_unknown_unit_refuses_rather_than_guessing() -> None:
    grid = _grid()
    grid["windSpeed"] = {"uom": "wmoUnit:furlongs", "values": grid["windSpeed"]["values"]}  # type: ignore[index]
    with pytest.raises(ValueError, match="unexpected unit"):
        kickoff_reading(_nws(grid), venue=_venue(), kickoff=KICKOFF)


def test_open_meteo_reads_the_kickoff_hour_and_reports_a_gap() -> None:
    payload = {
        "hourly": {
            "time": ["2026-10-04T16:00", "2026-10-04T17:00"],
            "temperature_2m": [60.1, 61.2],
            "wind_speed_10m": [9.0, 11.5],
            "wind_gusts_10m": [15.0, 18.0],
            "precipitation": [0.0, 0.02],
            "precipitation_probability": [10, 40],
        },
    }
    forecast = VenueForecast("lon", "open_meteo", RETRIEVED, 200, open_meteo=payload)
    reading = kickoff_reading(forecast, venue=_venue(provider="open_meteo"), kickoff=KICKOFF)
    assert reading["status"] == "ok"
    assert (reading["wind_mph"], reading["temp_f"], reading["precip_probability"]) == (
        11.5,
        61.2,
        40,
    )
    late = kickoff_reading(
        forecast,
        venue=_venue(provider="open_meteo"),
        kickoff=KICKOFF + timedelta(days=20),
    )
    assert late["status"] == ForecastStatus.OUT_OF_RANGE


def test_a_failed_fetch_is_unavailable() -> None:
    forecast = VenueForecast("x", "nws", RETRIEVED, 503, error="points")
    assert kickoff_reading(forecast, venue=_venue(), kickoff=KICKOFF)["status"] == "unavailable"


def test_features_are_null_unless_the_reading_is_fresh_in_range_and_plausible() -> None:
    reading = kickoff_reading(_nws(), venue=_venue(), kickoff=KICKOFF)
    features, status = reading_features(
        reading,
        as_of=RETRIEVED + timedelta(hours=1),
        kickoff=KICKOFF,
        roof_type_code=0.0,
    )
    assert status == "ok"
    assert features["wx_precip"] == 1.0 and features["wx_wind_mph"] == pytest.approx(19.9)

    stale, why = reading_features(
        reading,
        as_of=RETRIEVED + timedelta(hours=13),
        kickoff=KICKOFF,
        roof_type_code=0.0,
    )
    assert why == ForecastStatus.STALE and stale["wx_wind_mph"] is None
    assert stale["wx_roof_type"] == 0.0  # the venue type is still known

    wild = dict(reading, wind_mph=95.0)
    _, why = reading_features(wild, as_of=RETRIEVED, kickoff=KICKOFF, roof_type_code=0.0)
    assert why == ForecastStatus.IMPLAUSIBLE


def test_one_fetch_follows_the_points_links() -> None:
    calls: list[str] = []

    def get(url: str, accept: str) -> tuple[int, object]:
        calls.append(url)
        if "/points/" in url:
            return 200, {
                "properties": {
                    "forecastGridData": "https://api.weather.gov/gridpoints/BUF/35,47",
                    "forecastHourly": "https://api.weather.gov/gridpoints/BUF/35,47/forecast/hourly",
                    "gridId": "BUF",
                },
            }
        if url.endswith("/hourly"):
            return 200, {"properties": {"periods": []}}
        return 200, {"properties": _grid()}

    forecast = fetch_venue_forecast(_venue(), get=get, now=lambda: RETRIEVED)
    assert calls[0] == "https://api.weather.gov/points/42.7738,-78.7870"
    assert calls[1:] == [
        "https://api.weather.gov/gridpoints/BUF/35,47",
        "https://api.weather.gov/gridpoints/BUF/35,47/forecast/hourly",
    ]
    assert forecast.error is None and forecast.grid is not None
