"""Measure ``config/weather-forecast-error-v1.json`` from the forecast-archive probe (ADR-099).

``weather_training_parity_v1`` (``ffdraft.weekly.frozen_v2``) trains on recorded game-book
weather mapped to what a forecast would have said. This script measures that map — a source
measurement, made before the freeze and before any model was fitted on weather:

* **wind and temperature:** the least-squares line ``F = a + b * A`` from the game book's
  recorded kickoff value ``A`` (nflverse schedule ``wind``/``temp``) to the forecast ``F``
  issued the day before (Open-Meteo Previous Runs API, ``*_previous_day1`` at the kickoff
  hour), and the residual pool ``F - (a + b * A)``. The serving forecast is at most ~14 hours
  old at the 07:17 ET refresh for the latest kickoff, so day-before error bounds serving error
  from above; the short-lead (Historical Forecast) and two-day fits are printed beside it.
* **precipitation:** the hit rate ``P(PoP >= 50 | the game book names precipitation)`` and
  the false-alarm rate ``P(PoP >= 50 | it does not)``, with Open-Meteo's short-lead
  ``precipitation_probability`` — the Previous Runs API publishes amounts, not probabilities,
  and serving thresholds a probability.

Only open-air games (nflverse ``roof == "outdoors"``) with both values recorded count.

    uv run python scripts/weather_error_model.py \\
        --archive docs/source-probes/2026-10-01/weather/archive_games.csv \\
        --schedules schedules.parquet --pbp pbp_2024.parquet pbp_2025.parquet \\
        --out config/weather-forecast-error-v1.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ffdraft.weekly.frozen_v2 import WEATHER_PARITY_RULE
from ffdraft.weekly.weather import game_book_precipitation

FITS = {
    "short_lead": ("hf_wind_speed_10m", "hf_temperature_2m"),
    "previous_day1": ("pr_wind_speed_10m_previous_day1", "pr_temperature_2m_previous_day1"),
    "previous_day2": ("pr_wind_speed_10m_previous_day2", "pr_temperature_2m_previous_day2"),
    "era5_reanalysis": ("era5_wind_speed_10m", "era5_temperature_2m"),
}
CHOSEN = "previous_day1"


def _line(recorded: np.ndarray, forecast: np.ndarray) -> dict[str, Any]:
    slope, intercept = np.polyfit(recorded, forecast, 1)
    residuals = forecast - (intercept + slope * recorded)
    return {
        "intercept": round(float(intercept), 4),
        "slope": round(float(slope), 4),
        "residual_sd": round(float(residuals.std()), 4),
        "correlation": round(float(np.corrcoef(recorded, forecast)[0, 1]), 4),
        "mean_forecast_minus_recorded": round(float((forecast - recorded).mean()), 4),
        "mean_absolute_error": round(float(np.abs(forecast - recorded).mean()), 4),
        "residuals": sorted(round(float(value), 2) for value in residuals),
    }


def _wilson(successes: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 4), round(centre + half, 4)]


def measure(archive: pl.DataFrame, schedules: pl.DataFrame, text: pl.DataFrame) -> dict[str, Any]:
    joined = (
        archive.join(schedules.select("game_id", "temp", "wind", "roof"), on="game_id", how="left")
        .join(text, on="game_id", how="left")
        .filter(pl.col("roof") == "outdoors")
        .drop_nulls(["temp", "wind"])
        .sort("game_id")
    )
    recorded_wind = joined.get_column("wind").cast(pl.Float64).to_numpy()
    recorded_temp = joined.get_column("temp").cast(pl.Float64).to_numpy()
    fits = {
        name: {
            "wind_mph": _line(recorded_wind, joined.get_column(wind).cast(pl.Float64).to_numpy()),
            "temp_f": _line(recorded_temp, joined.get_column(temp).cast(pl.Float64).to_numpy()),
        }
        for name, (wind, temp) in FITS.items()
    }
    observed = [game_book_precipitation(value) for value in joined.get_column("weather")]
    probability = joined.get_column("hf_precipitation_probability").to_list()
    threshold = WEATHER_PARITY_RULE.precipitation_probability_threshold
    pairs = [
        (o, p is not None and float(p) >= threshold)
        for o, p in zip(observed, probability, strict=True)
        if o is not None
    ]
    positives = [hit for o, hit in pairs if o == 1]
    negatives = [hit for o, hit in pairs if o == 0]
    chosen = fits[CHOSEN]
    summary = {
        key: {k: v for k, v in value.items() if k != "residuals"} for key, value in chosen.items()
    }
    return {
        "version": "weather-forecast-error-v1",
        "rule": WEATHER_PARITY_RULE.version,
        "measured_from": {
            "archive": "docs/source-probes/2026-10-01/weather/archive_games.csv",
            "provider": (
                "Open-Meteo (Previous Runs API for wind/temperature; Historical Forecast API "
                "for precipitation probability), CC BY 4.0, non-commercial free tier"
            ),
            "recorded": "nflverse schedule temp/wind and play-by-play weather text (game book)",
            "seasons": sorted({int(value) for value in joined.get_column("season")}),
            "games": joined.height,
            "filter": "nflverse roof == 'outdoors' with temp and wind recorded",
        },
        "chosen_fit": CHOSEN,
        "wind_mph": {**summary["wind_mph"], "residuals": chosen["wind_mph"]["residuals"]},
        "temp_f": {**summary["temp_f"], "residuals": chosen["temp_f"]["residuals"]},
        "precipitation": {
            "indicator": f"short-lead precipitation_probability >= {threshold:g}",
            "text_rule": WEATHER_PARITY_RULE.precipitation_text_rule,
            "observed_games": len(positives),
            "not_observed_games": len(negatives),
            "hit_rate": round(sum(positives) / len(positives), 4) if positives else 0.0,
            "hit_rate_wilson_95": _wilson(sum(positives), len(positives)),
            "false_alarm_rate": round(sum(negatives) / len(negatives), 4) if negatives else 0.0,
            "false_alarm_rate_wilson_95": _wilson(sum(negatives), len(negatives)),
        },
        "ranges": {
            "wind_mph": list(WEATHER_PARITY_RULE.wind_mph_range),
            "temp_f": list(WEATHER_PARITY_RULE.temp_f_range),
        },
        "comparison": {
            name: {
                key: {k: v for k, v in value.items() if k != "residuals"}
                for key, value in fit.items()
            }
            for name, fit in fits.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--pbp", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    archive = pl.read_csv(args.archive, infer_schema_length=100_000)
    schedules = pl.read_parquet(args.schedules)
    text = pl.concat(
        [
            pl.read_parquet(path, columns=["game_id", "weather"]).unique("game_id", keep="first")
            for path in args.pbp
        ],
    ).unique("game_id", keep="first")
    document = measure(archive, schedules, text)
    args.out.write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps({k: v for k, v in document.items() if k not in ("wind_mph", "temp_f")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
