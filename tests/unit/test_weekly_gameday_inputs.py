"""Venue registry, weather parity, retained captures and PIT digests (ADR-099)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from ffdraft.retention import SnapshotConflictError, SnapshotStore
from ffdraft.weekly.capture import (
    FORECAST_SOURCE_ID,
    GamedayCapture,
    read_gameday_capture,
    verify_gameday_store,
    write_gameday_capture,
)
from ffdraft.weekly.frozen import WeeklySpec
from ffdraft.weekly.frozen_v2 import (
    CANDIDATE_VARIANTS,
    V2_FAMILIES,
    v2_spec,
    variant_families,
)
from ffdraft.weekly.pit import compare_captures, week_digests
from ffdraft.weekly.venues import ROOF_TYPES, load_venue_registry
from ffdraft.weekly.weather import (
    WeatherErrorModel,
    game_book_precipitation,
    training_weather,
)

REGISTRY_YAML = """
registry_version: venues_test
venues:
  - venue_id: jax-everbank
    name: EverBank Stadium
    country: US
    latitude: 30.3239
    longitude: -81.6373
    roof_type: open
    forecast_provider: nws
    schedule_ids: [JAX00]
    aliases: [EverBank Stadium, TIAA Bank Stadium]
    seasons: [2017, null]
    provenance: {coordinates: test, roof_type: test}
  - venue_id: lon-tottenham
    name: Tottenham Hotspur Stadium
    country: GB
    latitude: 51.6043
    longitude: -0.0665
    roof_type: open
    forecast_provider: open_meteo
    schedule_ids: [LON02]
    aliases: [Tottenham Hotspur Stadium]
    seasons: [2019, null]
    provenance: {coordinates: test, roof_type: test}
  - venue_id: hou-nrg
    name: NRG Stadium
    country: US
    latitude: 29.6847
    longitude: -95.4107
    roof_type: retractable
    forecast_provider: nws
    schedule_ids: [HOU00]
    aliases: [NRG Stadium, Reliant Stadium]
    seasons: [2017, null]
    provenance: {coordinates: test, roof_type: test}
  - venue_id: det-ford
    name: Ford Field
    country: US
    latitude: 42.34
    longitude: -83.0456
    roof_type: dome
    forecast_provider: nws
    schedule_ids: [DET00]
    aliases: [Ford Field]
    seasons: [2017, null]
    provenance: {coordinates: test, roof_type: test}
"""


@pytest.fixture
def registry(tmp_path: Path):
    path = tmp_path / "venues.yaml"
    path.write_text(REGISTRY_YAML, encoding="utf-8")
    return load_venue_registry(path)


def test_a_stadium_name_beats_a_stale_schedule_id(registry) -> None:
    # The 2026 file files a Jacksonville "home" game in London under JAX00.
    venue = registry.resolve(season=2026, stadium_id="JAX00", stadium="Tottenham Hotspur Stadium")
    assert venue is not None and venue.venue_id == "lon-tottenham"
    renamed = registry.resolve(season=2021, stadium_id="JAX00", stadium="TIAA Bank Stadium")
    assert renamed is not None and renamed.venue_id == "jax-everbank"
    assert registry.resolve(season=2026, stadium_id="ZZZ00", stadium="Nowhere Park") is None


def test_a_registry_entry_without_provenance_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "venues.yaml"
    path.write_text(
        REGISTRY_YAML.replace(
            "provenance: {coordinates: test, roof_type: test}", "provenance: {coordinates: test}", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="provenance.roof_type"):
        load_venue_registry(path)


def test_the_committed_registry_loads_with_provenance_for_every_venue() -> None:
    registry = load_venue_registry()
    assert registry.venues, "config/venues.yaml is empty"
    for venue in registry.venues:
        assert venue.roof_type in ROOF_TYPES
        assert venue.provenance.get("coordinates") and venue.provenance.get("roof_type")
        assert (venue.forecast_provider == "nws") == (venue.country == "US")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Light Rain Temp: 63° F, Humidity: 90%, Wind: SSE 10 mph", 1),
        ("Snow showers Temp: 28° F", 1),
        ("Cloudy, 30% chance of rain Temp: 55° F", 0),
        ("Sunny Temp: 71° F, Humidity: 59%, Wind: NE 5 mph", 0),
        ("", None),
        (None, None),
    ],
)
def test_game_book_precipitation(text: str | None, expected: int | None) -> None:
    assert game_book_precipitation(text) == expected


def _error_model() -> WeatherErrorModel:
    return WeatherErrorModel(
        digest="test",
        wind_intercept=1.0,
        wind_slope=0.9,
        wind_residuals=(-1.0, 0.0, 1.0),
        temp_intercept=0.5,
        temp_slope=1.0,
        temp_residuals=(-2.0, 2.0),
        precip_hit_rate=0.6,
        precip_false_alarm_rate=0.05,
        wind_range=(0.0, 60.0),
        temp_range=(-30.0, 120.0),
        document={},
    )


def _games() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": [
                "2025_01_A_JAX",
                "2025_02_B_HOU",
                "2025_03_C_DET",
                "2025_04_D_JAX",
                "2025_05_E_X",
            ],
            "season": [2025, 2025, 2025, 2025, 2025],
            "stadium_id": ["JAX00", "HOU00", "DET00", "JAX00", "ZZZ00"],
            "stadium": [
                "EverBank Stadium",
                "NRG Stadium",
                "Ford Field",
                "EverBank Stadium",
                "Mystery",
            ],
            "temp": [80.0, 75.0, None, None, 50.0],
            "wind": [10.0, 5.0, None, None, 3.0],
            "weather_text": ["Rain", "Sunny", None, "Clear", "Clear"],
        },
    )


def test_training_weather_reads_only_open_air_games_and_is_deterministic(registry) -> None:
    first = training_weather(_games(), registry=registry, error_model=_error_model())
    second = training_weather(_games(), registry=registry, error_model=_error_model())
    assert first.equals(second)
    rows = {row["game_id"]: row for row in first.to_dicts()}
    open_air = rows["2025_01_A_JAX"]
    assert open_air["wx_roof_type"] == 0.0
    assert open_air["wx_wind_mph"] == pytest.approx(1.0 + 0.9 * 10.0 + 0.0, abs=1.01)
    assert open_air["wx_precip"] in (0.0, 1.0)
    # A retractable roof's state is unknown before kickoff: no weather, at training as at serving.
    assert (
        rows["2025_02_B_HOU"]["wx_roof_type"] == 1.0
        and rows["2025_02_B_HOU"]["wx_wind_mph"] is None
    )
    assert (
        rows["2025_03_C_DET"]["wx_roof_type"] == 2.0 and rows["2025_03_C_DET"]["wx_temp_f"] is None
    )
    # An open-air game with nothing recorded is unknown, not calm.
    assert (
        rows["2025_04_D_JAX"]["wx_wind_mph"] is None and rows["2025_04_D_JAX"]["wx_precip"] is None
    )
    # A game the registry cannot place has no roof type and no weather.
    assert rows["2025_05_E_X"]["wx_roof_type"] is None


def test_a_capture_round_trips_and_is_immutable(tmp_path: Path) -> None:
    store = SnapshotStore(root=tmp_path, prefix="")
    observed = datetime(2026, 10, 4, 11, 17, tzinfo=UTC)
    capture = GamedayCapture(
        source_id=FORECAST_SOURCE_ID,
        season=2026,
        observed_at_utc=observed,
        rows=[{"game_id": "2026_04_A_B", "status": "ok", "wind_mph": 12.0}],
        details={"providers": {"nws": 1}},
    )
    write_gameday_capture(capture, store=store)
    write_gameday_capture(capture, store=store)  # an identical re-capture is a no-op
    read = read_gameday_capture(
        store, source_id=FORECAST_SOURCE_ID, season=2026, at_or_before=observed
    )
    assert read is not None and read.rows == capture.rows
    assert (
        read_gameday_capture(
            store,
            source_id=FORECAST_SOURCE_ID,
            season=2026,
            at_or_before=datetime(2026, 10, 4, 11, 0, tzinfo=UTC),
        )
        is None
    )
    altered = GamedayCapture(FORECAST_SOURCE_ID, 2026, observed, [{"game_id": "x"}])
    with pytest.raises(SnapshotConflictError):
        write_gameday_capture(altered, store=store)
    captures, checked, problems = verify_gameday_store(store, season=2026)
    assert (captures, checked, problems) == (1, 2, ())


def _injuries(status: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": [2026, 2026],
            "week": [1, 1],
            "game_type": ["REG", "REG"],
            "team": ["BUF", "MIA"],
            "gsis_id": ["00-1", "00-2"],
            "position": ["WR", "CB"],
            "full_name": ["A", "B"],
            "report_primary_injury": ["Knee", "Ankle"],
            "report_secondary_injury": [None, None],
            "report_status": [status, "Out"],
            "practice_primary_injury": [None, None],
            "practice_secondary_injury": [None, None],
            "practice_status": [None, None],
        },
    )


def test_a_revised_designation_shows_up_even_when_the_count_does_not() -> None:
    earlier = week_digests(_injuries("Questionable"))
    later = week_digests(_injuries("Out"))
    assert earlier["weeks"]["2026-01"]["rows"] == later["weeks"]["2026-01"]["rows"] == 2
    comparison = compare_captures(earlier, later)
    assert comparison["revised"] == 1
    assert comparison["weeks"]["2026-01"]["changed"] == ["BUF|00-1"]
    assert compare_captures(earlier, week_digests(_injuries("Questionable")))["identical"] == 1


def test_v1_keeps_its_configuration_hash_and_v2_variants_are_distinct() -> None:
    # The committed v1 artifact is checked against this hash at load (ADR-096).
    assert WeeklySpec().configuration_hash() == "692c1886548cde7f"
    hashes = {
        variant: v2_spec(
            variant_families(variant), weather_parameters_digest="x"
        ).configuration_hash()
        for variant in CANDIDATE_VARIANTS[1:]
    }
    assert len(set(hashes.values())) == len(hashes)
    spec = v2_spec(("defense", "weather"), weather_parameters_digest="x")
    assert spec.added_families == ("weather", "defense")
    assert spec.features[-len(V2_FAMILIES["defense"]) :] == V2_FAMILIES["defense"]
    with pytest.raises(KeyError):
        variant_families("v1+astrology")
