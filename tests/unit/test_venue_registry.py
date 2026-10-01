"""The committed venue registry against its own evidence (ADR-099, docs/DATA_SOURCES.md §20).

Every stadium the 2017-2026 schedule prints resolves to exactly one venue, and every venue's
coordinates and Wikidata item are the ones the runner probe recorded: nothing in
``config/venues.yaml`` is from memory.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ffdraft.paths import repo_root
from ffdraft.weekly.venues import ROOF_TYPE_CODES, load_venue_registry, roof_type_code

EVIDENCE = repo_root() / "docs/source-probes/2026-10-01/weather"
STADIUMS = repo_root() / "tests/fixtures/weekly/schedule_stadiums.csv"


def _stadium_rows() -> list[dict[str, str]]:
    with STADIUMS.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _evidence_coordinates() -> dict[str, tuple[float, float]]:
    """Wikidata item -> P625 from both probe files."""
    found: dict[str, tuple[float, float]] = {}
    venues = json.loads((EVIDENCE / "venues.json").read_text(encoding="utf-8"))
    for record in venues.values():
        for point in record.get("wikidata_P625") or []:
            found.setdefault(record["wikidata_item"], (point["lat"], point["lon"]))
    resolution = json.loads((EVIDENCE / "venue_resolution.json").read_text(encoding="utf-8"))
    for key, block in resolution.items():
        if key.startswith("_") or "titles" not in block:
            continue
        for page in [*block["titles"], *block["searched"]]:
            for point in page.get("wikidata_P625") or []:
                found.setdefault(page["wikidata_item"], (point["lat"], point["lon"]))
    return found


def test_every_scheduled_stadium_resolves_to_exactly_one_venue() -> None:
    registry = load_venue_registry()
    unresolved = [
        (row["season"], row["stadium_id"], row["stadium"])
        for row in _stadium_rows()
        if registry.resolve(
            season=int(row["season"]),
            stadium_id=row["stadium_id"],
            stadium=row["stadium"],
        )
        is None
    ]
    assert unresolved == []


@pytest.mark.parametrize(
    ("season", "stadium_id", "stadium", "venue_id"),
    [
        # The 2026 file files Jacksonville's London "home" game under JAX00.
        (2026, "JAX00", "Tottenham Hotspur Stadium", "lon-tottenham-hotspur-stadium"),
        # One building, two Munich ids and a name the 2026 file invents.
        (2022, "GER00", "Allianz Arena", "mun-allianz-arena"),
        (2026, "MUN01", "FC Bayern Munich Stadium", "mun-allianz-arena"),
        # Buffalo moved into a new building in 2026 under the same id.
        (2025, "BUF00", "New Era Field", "buf-ralph-wilson-stadium"),
        (2026, "BUF00", "Highmark Stadium", "buf-highmark-stadium"),
        # Renamed, not moved.
        (2026, "HOU00", "Reliant Stadium", "hou-reliant-stadium"),
        (2026, "MEX00", "Estadio Banorte", "mex-estadio-azteca"),
    ],
)
def test_ambiguous_schedule_rows_resolve_to_the_documented_building(
    season: int, stadium_id: str, stadium: str, venue_id: str
) -> None:
    venue = load_venue_registry().resolve(season=season, stadium_id=stadium_id, stadium=stadium)
    assert venue is not None and venue.venue_id == venue_id


def test_coordinates_are_the_probed_wikidata_coordinates() -> None:
    import yaml

    document = yaml.safe_load((repo_root() / "config/venues.yaml").read_text(encoding="utf-8"))
    evidence = _evidence_coordinates()
    for entry in document["venues"]:
        item = entry["wikidata"]
        assert item in evidence, f"{entry['venue_id']}: {item} is not in the probe evidence"
        lat, lon = evidence[item]
        assert entry["latitude"] == pytest.approx(lat, abs=6e-5), entry["venue_id"]
        assert entry["longitude"] == pytest.approx(lon, abs=6e-5), entry["venue_id"]
        assert item in entry["provenance"]["coordinates"]


def test_roof_types_follow_the_recorded_history_and_fail_closed() -> None:
    registry = load_venue_registry()
    recorded: dict[str, set[str]] = {}
    for row in _stadium_rows():
        if int(row["season"]) > 2025:
            continue  # 2026 roof values are pre-game, not recorded
        venue = registry.resolve(
            season=int(row["season"]), stadium_id=row["stadium_id"], stadium=row["stadium"]
        )
        assert venue is not None
        recorded.setdefault(venue.venue_id, set()).update(
            value for value in row["schedule_roofs"].split("|") if value
        )
    for venue_id, roofs in recorded.items():
        venue = registry.by_id(venue_id)
        assert venue is not None
        if roofs <= {"outdoors"}:
            # Every recorded game outdoors; Frankfurt's retractable roof was open both times.
            assert venue.roof_type in ("open", "retractable"), venue_id
        elif roofs <= {"dome"}:
            assert venue.roof_type == "dome", venue_id
        else:
            assert roofs <= {"open", "closed"} and venue.roof_type == "retractable", venue_id
    unverified = [venue for venue in registry.venues if venue.roof_type == "unverified"]
    assert {venue.venue_id for venue in unverified} == {
        "mel-melbourne-cricket-ground",
        "par-stade-de-france",
    }
    assert all(roof_type_code(venue) is None for venue in unverified)
    assert set(ROOF_TYPE_CODES) == {"open", "retractable", "dome"}


def test_every_name_the_probe_resolved_points_at_the_same_item_as_its_venue() -> None:
    import yaml

    document = yaml.safe_load((repo_root() / "config/venues.yaml").read_text(encoding="utf-8"))
    items = {
        alias: entry["wikidata"] for entry in document["venues"] for alias in entry["aliases"]
    }
    resolution = json.loads((EVIDENCE / "venue_resolution.json").read_text(encoding="utf-8"))
    checked = 0
    for name, page in resolution["schedule_names"].items():
        if name in items and page.get("wikidata_item") and not page.get("disambiguation"):
            assert page["wikidata_item"] == items[name], name
            checked += 1
    assert checked >= 15


def test_the_registry_digest_changes_with_its_bytes(tmp_path: Path) -> None:
    source = repo_root() / "config/venues.yaml"
    copy = tmp_path / "venues.yaml"
    copy.write_bytes(source.read_bytes() + b"\n# touched\n")
    assert load_venue_registry(copy).digest != load_venue_registry(source).digest
