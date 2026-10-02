"""The shadow v2 at serve time: every input that can be missing is missing safely (ADR-099).

Training never saw a missing line, so v1 reads one as zero and the build refuses to project
without it (ADR-096). v2's game-day inputs are different by design: each can be unknown at a
refresh (no forecast yet, a stale one, a retractable roof, an unverified venue, a report with
no game statuses), and training carries the same unknowns as ``null``. These tests hold the
serving side to that: unknown is ``null`` (LightGBM's missing branch), never zero, and the
model still returns a finite, ordered distribution.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from ffdraft.weekly.frozen_v2 import V2_FAMILIES, v2_spec
from ffdraft.weekly.model import fit_weekly_model
from ffdraft.weekly.shadow import attach_serving_v2_inputs, build_shadow_rows, summarise
from ffdraft.weekly.venues import load_venue_registry

Rows = Callable[..., pl.DataFrame]
V2_INPUTS = [name for names in V2_FAMILIES.values() for name in names]
AS_OF = datetime(2026, 10, 3, 11, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)


def _with_inputs(frame: pl.DataFrame, *, missing: bool) -> pl.DataFrame:
    rng = np.random.default_rng(11)
    columns = []
    for name in V2_INPUTS:
        values = rng.uniform(0, 20, frame.height)
        gone = rng.uniform(size=frame.height) < 0.3
        data = [
            None if (missing or out) else float(value)
            for out, value in zip(gone, values, strict=True)
        ]
        columns.append(pl.Series(name, data, dtype=pl.Float64))
    return frame.with_columns(columns)


@pytest.fixture(scope="module")
def shadow_model(weekly_rows: Rows) -> Any:
    spec = replace(
        v2_spec(("weather", "lineup", "defense"), weather_parameters_digest="test"),
        num_boost_round=8,
    )
    return fit_weekly_model(
        _with_inputs(weekly_rows(range(2017, 2021), per_season=150), missing=False), spec=spec
    )


def _serving(weekly_rows: Rows) -> pl.DataFrame:
    frame = weekly_rows(range(2026, 2027), per_season=12)
    return frame.with_columns(
        pl.lit("2026_05_BUF_MIA").alias("game_id"),
        pl.lit(KICKOFF).alias("kickoff_utc"),
        pl.lit("BUF").alias("serve_team"),
        pl.lit("BUF").alias("team"),
        pl.lit("MIA").alias("opponent"),
    )


def test_every_v2_input_unknown_still_gives_a_finite_ordered_distribution(
    shadow_model, weekly_rows
) -> None:
    frame = _with_inputs(_serving(weekly_rows), missing=True)
    quantiles = shadow_model.predict(frame)
    assert np.isfinite(quantiles).all()
    assert (np.diff(quantiles, axis=1) >= -1e-9).all()


def test_unknown_is_the_missing_branch_never_a_zero(shadow_model, weekly_rows) -> None:
    unknown = _with_inputs(_serving(weekly_rows), missing=True)
    nan = unknown.with_columns([pl.col(name).fill_null(float("nan")) for name in V2_INPUTS])
    zero = unknown.with_columns([pl.col(name).fill_null(0.0) for name in V2_INPUTS])
    assert np.array_equal(shadow_model.predict(unknown), shadow_model.predict(nan))
    # A zero is a reading ("no wind", "nobody out"); the model was trained to tell them apart.
    assert not np.array_equal(shadow_model.predict(unknown), shadow_model.predict(zero))


REGISTRY = """
registry_version: venues_test
venues:
  - venue_id: buf
    name: Highmark Stadium
    country: US
    latitude: 42.773
    longitude: -78.792
    roof_type: open
    forecast_provider: nws
    schedule_ids: [BUF00]
    aliases: [Highmark Stadium]
    seasons: [2026, null]
    provenance: {coordinates: test, roof_type: test}
  - venue_id: det
    name: Ford Field
    country: US
    latitude: 42.34
    longitude: -83.0456
    roof_type: dome
    forecast_provider: nws
    schedule_ids: [DET00]
    aliases: [Ford Field]
    seasons: [null, null]
    provenance: {coordinates: test, roof_type: test}
  - venue_id: mel
    name: Melbourne Cricket Ground
    country: AU
    latitude: -37.82
    longitude: 144.983
    roof_type: unverified
    forecast_provider: open_meteo
    schedule_ids: [MEL00]
    aliases: [Melbourne Cricket Ground]
    seasons: [null, null]
    provenance: {coordinates: test, roof_type: test}
"""


def _playing() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "gsis_id": ["00-1", "00-2", "00-3", "00-4"],
            "game_id": ["G_BUF", "G_BUF", "G_DET", "G_MEL"],
            "kickoff_utc": [KICKOFF] * 4,
            "serve_team": ["BUF", "BUF", "DET", "LA"],
            "opponent": ["MIA", "MIA", "GB", "SF"],
        },
        schema_overrides={"kickoff_utc": pl.Datetime("us", "UTC")},
    )


def _schedule() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["G_BUF", "G_DET", "G_MEL"],
            "season": [2026, 2026, 2026],
            "week": [5, 5, 5],
            "stadium_id": ["BUF00", "DET00", "MEL00"],
            "stadium": ["Highmark Stadium", "Ford Field", "Melbourne Cricket Ground"],
        },
    )


def _empty_snaps() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "season": pl.Int32,
            "week": pl.Int32,
            "game_type": pl.String,
            "gsis_id": pl.String,
            "player_name": pl.String,
            "position": pl.String,
            "team": pl.String,
            "offense_pct": pl.Float64,
            "defense_pct": pl.Float64,
        },
    )


def _empty_weekly() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "season": pl.Int32,
            "week": pl.Int32,
            "season_type": pl.String,
            "gsis_id": pl.String,
            "team": pl.String,
            "targets": pl.Float64,
            "carries": pl.Float64,
        },
    )


def _attach(tmp_path: Path, forecasts: dict[str, Any], injuries: pl.DataFrame | None):
    path = tmp_path / "venues.yaml"
    path.write_text(REGISTRY, encoding="utf-8")
    return attach_serving_v2_inputs(
        _playing(),
        forecasts=forecasts,
        registry=load_venue_registry(path),
        schedule=_schedule(),
        snaps=_empty_snaps(),
        weekly=_empty_weekly(),
        injuries=injuries,
        season=2026,
        through_week=4,
        as_of=AS_OF,
    )


def test_serve_time_unknowns_are_null_and_each_says_why(tmp_path: Path) -> None:
    frame, statuses = _attach(tmp_path, forecasts={}, injuries=None)
    by_game = {row["game_id"]: row for row in frame.iter_rows(named=True)}
    # Open air with no retained forecast: the roof type is known, the weather is not.
    assert by_game["G_BUF"]["wx_roof_type"] == 0.0 and by_game["G_BUF"]["wx_wind_mph"] is None
    assert statuses["G_BUF"] != "ok"
    # A dome: no weather reaches the field.
    assert by_game["G_DET"]["wx_roof_type"] == 2.0 and by_game["G_DET"]["wx_wind_mph"] is None
    assert statuses["G_DET"] == "indoors"
    # An unverified venue fails closed: no roof type, no weather.
    assert by_game["G_MEL"]["wx_roof_type"] is None and by_game["G_MEL"]["wx_temp_f"] is None
    # No report at all: every health input unknown, never "nobody out".
    for row in frame.iter_rows(named=True):
        for name in (*V2_FAMILIES["lineup"], *V2_FAMILIES["defense"]):
            assert row[name] is None, name


def test_a_fresh_ok_forecast_reaches_the_model_and_a_stale_one_does_not(tmp_path: Path) -> None:
    reading = {
        "status": "ok",
        "provider": "nws",
        "wind_mph": 21.0,
        "gust_mph": 30.0,
        "temp_f": 35.0,
        "precip_probability": 80,
        "precip_in": 0.2,
        "short_forecast": "Rain",
        "valid_from_utc": "2026-10-04T16:00:00Z",
        "valid_to_utc": "2026-10-04T18:00:00Z",
        "provider_updated_utc": "2026-10-03T10:00:00+00:00",
        "retrieved_at_utc": (AS_OF - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    frame, statuses = _attach(tmp_path, forecasts={"G_BUF": reading}, injuries=None)
    buf = frame.filter(pl.col("game_id") == "G_BUF").row(0, named=True)
    assert statuses["G_BUF"] == "ok"
    assert (buf["wx_wind_mph"], buf["wx_temp_f"], buf["wx_precip"]) == (21.0, 35.0, 1.0)
    stale = dict(
        reading, retrieved_at_utc=(AS_OF - timedelta(hours=20)).isoformat().replace("+00:00", "Z")
    )
    frame, statuses = _attach(tmp_path, forecasts={"G_BUF": stale}, injuries=None)
    assert statuses["G_BUF"] == "stale"
    assert frame.filter(pl.col("game_id") == "G_BUF").row(0, named=True)["wx_wind_mph"] is None


def test_the_shadow_row_pairs_both_models_and_marks_what_was_pregame(
    shadow_model, weekly_rows
) -> None:
    frame = _with_inputs(_serving(weekly_rows), missing=True)
    v1 = np.tile(np.array([1.0, 2.0, 4.0, 7.0, 10.0, 14.0, 17.0]), (frame.height, 1))
    rows = build_shadow_rows(
        frame=frame,
        v1_quantiles=v1,
        v2_model=shadow_model,
        as_of=AS_OF,
        weather_status={"2026_05_BUF_MIA": "unavailable"},
        build_id="b",
        sources={},
    )
    assert len(rows) == frame.height
    first = rows[0]
    assert first["pregame"] is True and first["v1"]["q50"] == 7.0 and first["v2"] is not None
    assert first["v2_configuration_hash"] == shadow_model.spec.configuration_hash()
    assert all(value is None for value in first["v2_inputs"].values())
    assert first["input_status"]["weather"] == "unavailable"
    late = build_shadow_rows(
        frame=frame,
        v1_quantiles=v1,
        v2_model=None,
        as_of=KICKOFF + timedelta(minutes=1),
        weather_status={},
        build_id="b",
        sources={},
    )
    assert summarise(late) == {"rows": frame.height, "pregame": 0, "with_v2": 0}


def test_the_committed_shadow_artifact_is_the_selected_v2_and_refuses_tampering(
    tmp_path: Path,
) -> None:
    import json
    import shutil

    from ffdraft.paths import repo_root
    from ffdraft.weekly.shadow import DEFAULT_V2_MODEL_DIR, load_v2_model

    committed = repo_root() / DEFAULT_V2_MODEL_DIR
    model = load_v2_model(committed)
    assert model is not None
    assert model.spec.added_families == ("lineup",)
    assert model.spec.configuration_hash() == "24933c290a50a74c"
    report = json.loads(
        (repo_root() / "docs/experiments/weekly-startsit-v2/experiment.json").read_text("utf-8")
    )
    assert report["outcome"] == "selected" and report["v2_families"] == ["lineup"]
    copy = tmp_path / "v2"
    shutil.copytree(committed, copy)
    booster = sorted((copy / "boosters").iterdir())[0]
    import gzip

    text = gzip.decompress(booster.read_bytes()).replace(b"shrinkage=", b"shrinkage=9", 1)
    booster.write_bytes(gzip.compress(text, mtime=0))
    with pytest.raises(Exception, match="(?i)digest|hash|differ|changed"):
        load_v2_model(copy)
