"""Reviewed availability overrides and the in-season status population (ADR-101).

An override is evidence that rides a ``player_status`` record and nothing else: these tests
pin the strict loader, the record field, the population rule, the compact served family, and
that no model, simulation, tier, arbitrage or weekly module can import the overrides at all.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from ffdraft.artifacts.csv_flatten import PLAYER_STATUS_CSV_COLUMNS, flatten_player_status_record
from ffdraft.artifacts.schemas import record_field_order
from ffdraft.artifacts.serving import FAMILIES
from ffdraft.identity.registry import build_registry
from ffdraft.pipeline.current import _rostered_core_players
from ffdraft.status.build import build_player_status_records
from ffdraft.status.overrides import (
    AvailabilityOverrideError,
    active_overrides,
    load_availability_overrides,
)

REPO = Path(__file__).resolve().parents[2]

ENTRY = """
schema_version: "1.0"
overrides:
  - player_id: "gsis:00-0000001"
    display_name: "Alpha Back"
    season: 2026
    horizon: season
    summary: Placed on injured reserve; reported out for the season.
    sources:
      - url: https://example.org/report
        publisher: Example
    reviewed_by: tester
    reviewed_at: "2026-10-02"
    expires_at: "2027-01-12"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "overrides.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_committed_file_loads_and_every_entry_is_sourced():
    entries = load_availability_overrides(REPO / "config" / "availability-overrides.yaml")
    assert entries, "the reviewed file should hold at least the verified 2026 entry"
    for entry in entries:
        assert entry.player_id.startswith("gsis:")
        assert entry.horizon == "season"
        assert entry.source_urls and all(url.startswith("https://") for url in entry.source_urls)
        assert entry.expires_at > entry.reviewed_at


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        ('"gsis:00-0000001"', '"00-0000001"', "canonical"),
        ("horizon: season", "horizon: weeks", "horizon"),
        ('expires_at: "2027-01-12"', 'expires_at: "2026-09-01"', "expires_at"),
        (
            "      - url: https://example.org/report\n        publisher: Example\n",
            "      []\n",
            "source",
        ),
        ("https://example.org/report", "http://example.org/report", "https"),
        ("    reviewed_by: tester\n", "", "missing keys"),
    ],
)
def test_the_loader_refuses_a_malformed_entry(tmp_path, needle, replacement, message):
    broken = ENTRY.replace(needle, replacement)
    assert broken != ENTRY
    with pytest.raises(AvailabilityOverrideError, match=message):
        load_availability_overrides(_write(tmp_path, broken))


def test_the_loader_refuses_two_entries_for_one_player_and_season(tmp_path):
    body = ENTRY + ENTRY.split("overrides:\n", 1)[1]
    with pytest.raises(AvailabilityOverrideError, match="one entry"):
        load_availability_overrides(_write(tmp_path, body))


def test_an_entry_is_in_force_only_for_its_season_and_before_expiry(tmp_path):
    entries = load_availability_overrides(_write(tmp_path, ENTRY))
    october = datetime(2026, 10, 2, 12, tzinfo=UTC)
    assert set(active_overrides(entries, season=2026, as_of=october)) == {"gsis:00-0000001"}
    assert active_overrides(entries, season=2027, as_of=october) == {}
    assert (
        active_overrides(entries, season=2026, as_of=datetime(2027, 1, 12, 0, 1, tzinfo=UTC)) == {}
    )


def _roster() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "season": 2026,
                "gsis_id": "00-0000001",
                "display_name": "Alpha Back",
                "position": "RB",
                "team": "SEA",
                "status": "RES",
                "sleeper_id": "1001",
            },
            {
                "season": 2026,
                "gsis_id": "00-0000002",
                "display_name": "Bravo Wideout",
                "position": "WR",
                "team": "DAL",
                "status": "ACT",
                "sleeper_id": "1002",
            },
            {
                "season": 2026,
                "gsis_id": "00-0000003",
                "display_name": "Charlie Squad",
                "position": "WR",
                "team": "DAL",
                "status": "DEV",
                "sleeper_id": "1003",
            },
            {
                "season": 2026,
                "gsis_id": "00-0000004",
                "display_name": "Delta Guard",
                "position": "OL",
                "team": "DAL",
                "status": "ACT",
                "sleeper_id": None,
            },
            {
                "season": 2026,
                "gsis_id": "00-0000005",
                "display_name": "Echo Cut",
                "position": "TE",
                "team": None,
                "status": "CUT",
                "sleeper_id": "1005",
            },
        ],
    )


def test_a_status_row_carries_the_override_and_exists_even_off_the_board(tmp_path):
    entries = load_availability_overrides(_write(tmp_path, ENTRY))
    roster = _roster()
    result = build_player_status_records(
        registry=build_registry(roster),
        roster=roster,
        capture=None,
        build_id="b",
        season=2026,
        generated_at=datetime(2026, 10, 2, 12, tzinfo=UTC),
        # The published board does not name him; the override still reaches the page.
        player_ids=["gsis:00-0000002"],
        overrides=active_overrides(entries, season=2026, as_of=datetime(2026, 10, 2, tzinfo=UTC)),
    )
    by_id = {record["player_id"]: record for record in result.records}
    assert set(by_id) == {"gsis:00-0000001", "gsis:00-0000002"}
    override = by_id["gsis:00-0000001"]["availability_override"]
    assert override == {
        "horizon": "season",
        "summary": "Placed on injured reserve; reported out for the season.",
        "source_urls": ["https://example.org/report"],
        "reviewed_at": "2026-10-02",
        "expires_at": "2027-01-12",
    }
    assert by_id["gsis:00-0000002"]["availability_override"] is None
    # Field order is the contract's.
    assert list(by_id["gsis:00-0000002"]) == list(record_field_order("player_status"))
    # The CSV projection is scalar.
    flat = flatten_player_status_record(by_id["gsis:00-0000001"])
    assert set(flat) == set(PLAYER_STATUS_CSV_COLUMNS)
    assert flat["availability_override_expires_at"] == "2027-01-12"


def test_the_in_season_population_is_every_rostered_core_player():
    assert _rostered_core_players(_roster()) == ["gsis:00-0000001", "gsis:00-0000002"]


def test_the_availability_family_serves_only_what_the_policy_reads():
    family = next(family for family in FAMILIES if family.name == "player_availability")
    assert family.artifact == "player_status"
    assert family.partition == "all"
    assert family.only is not None
    assert "injury_notes" not in family.only
    assert {
        "player_id",
        "roster_status",
        "sleeper_status",
        "injury_status",
        "observed_at_utc",
        "quality_flags",
        "availability_override",
        "season",
    } <= set(family.only)


def test_no_model_path_can_import_the_overrides():
    """Structural: an override is status evidence and has no route into any number."""
    model_packages = (
        "modeling",
        "simulation",
        "tiers",
        "arbitrage",
        "ros",
        "weekly",
        "features",
        "market",
        "opportunity",
        "signals",
    )
    offenders: list[str] = []
    for package in model_packages:
        for path in (REPO / "src" / "ffdraft" / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                if any(name.startswith("ffdraft.status") for name in names):
                    offenders.append(str(path.relative_to(REPO)))
    assert offenders == []
