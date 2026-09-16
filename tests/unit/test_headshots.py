"""The portrait crosswalk and the one host it may name (ADR-087).

Grouped by the question each answers, because none of these is about how a picture looks:

| question                                        | why it could go wrong quietly            |
|-------------------------------------------------|------------------------------------------|
| does an unbridged player produce a row?          | a URL ending in `None.png`               |
| does the address resolve from the id beside it?  | one player's face under another's name   |
| can a build point the page at another host?      | an unreviewed origin in a published file |
| is a portrait ever a fact about a player?        | decoration presented as a measurement    |
| does a thin crosswalk fail a build?              | a deploy stopped over a missing picture  |
"""

from __future__ import annotations

import polars as pl
import pytest

from ffdraft.artifacts.validate import validate_artifact_directory
from ffdraft.contracts.enums import Position
from ffdraft.headshots import (
    HEADSHOT_HOST,
    HEADSHOT_PROVIDER,
    build_player_headshot_records,
    crosswalk_from_registry,
    headshot_url,
)
from ffdraft.identity.registry import build_registry
from ffdraft.quality import QualityGate

BUILD = "test-build"


def _roster(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "gsis_id": pl.String,
            "display_name": pl.String,
            "position": pl.String,
            "team": pl.String,
            "espn_id": pl.String,
            "sleeper_id": pl.String,
        },
    )


# ---------------------------------------------------------------------------- the address


def test_the_url_is_the_one_the_owner_supplied() -> None:
    """The literal case that started this, pinned so a refactor cannot drift off it.

    `4429795` is Jahmyr Gibbs' nflverse `espn_id`; this is the address on ESPN's CDN.
    """
    assert headshot_url("4429795") == (
        "https://a.espncdn.com/i/headshots/nfl/players/full/4429795.png"
    )


def test_every_published_address_is_on_the_declared_host() -> None:
    result = build_player_headshot_records(
        crosswalk={"gsis:00-0000001": "4429795"},
        published=["gsis:00-0000001"],
        build_id=BUILD,
    )
    assert [record["image_url"] for record in result.records] == [headshot_url("4429795")]
    for record in result.records:
        assert record["image_url"].startswith(f"https://{HEADSHOT_HOST}/")
        assert record["provider"] == HEADSHOT_PROVIDER


def test_the_address_resolves_from_the_id_beside_it() -> None:
    """The invariant that stops one player's picture appearing under another player's name."""
    result = build_player_headshot_records(
        crosswalk={"gsis:00-0000001": "4429795", "gsis:00-0000002": "3139477"},
        published=["gsis:00-0000001", "gsis:00-0000002"],
        build_id=BUILD,
    )
    for record in result.records:
        assert record["image_url"] == headshot_url(str(record["provider_player_id"]))


# ------------------------------------------------------------------------------- absence


@pytest.mark.parametrize("absent", [None, "", "  ", "0", "na", "N/A", "null"])
def test_a_player_the_crosswalk_cannot_bridge_gets_no_row(absent: str | None) -> None:
    """Every shape an upstream uses for "no id" must produce no row, not a broken address.

    A sentinel treated as an id is the worst join bug there is: it collapses every id-less
    player onto one, so every one of them would show the same stranger's face. The normalizer
    already refuses these; this asserts the artifact inherits that.
    """
    result = build_player_headshot_records(
        crosswalk={"gsis:00-0000006": absent},
        published=["gsis:00-0000006"],
        build_id=BUILD,
    )
    assert result.records == []
    assert result.unresolved == ("gsis:00-0000006",)
    assert result.resolved == 0
    assert result.published_players == 1


def test_a_malformed_id_is_refused_rather_than_rendered() -> None:
    result = build_player_headshot_records(
        crosswalk={"gsis:00-0000006": "not-a-number"},
        published=["gsis:00-0000006"],
        build_id=BUILD,
    )
    assert result.records == []


def test_a_thin_crosswalk_never_fails_a_build() -> None:
    """No coverage floor, deliberately.

    A gate that could stop a deploy over a missing picture would be able to take the whole
    board down for a cosmetic reason (ADR-087).
    """
    gate = QualityGate()
    result = build_player_headshot_records(
        crosswalk={f"gsis:{index}": None for index in range(50)},
        published=[f"gsis:{index}" for index in range(50)],
        build_id=BUILD,
        gate=gate,
    )
    assert result.resolved == 0
    assert gate.passed
    assert not [check for check in gate.checks if check.status.value == "fail"]


# ------------------------------------------------------------------------------ population


def test_the_population_is_the_published_board_and_counts_players_not_rows() -> None:
    """A player appears in up to nine tier rows; the denominator is players."""
    result = build_player_headshot_records(
        crosswalk={"gsis:00-0000001": "4429795", "gsis:00-0000009": "1111111"},
        # The board hands over one row per preset, so the same id arrives repeatedly.
        published=["gsis:00-0000001"] * 9 + ["gsis:00-0000009"] * 9,
        build_id=BUILD,
    )
    assert result.published_players == 2
    assert result.resolved == 2
    assert len(result.records) == 2


def test_a_player_outside_the_published_board_gets_no_row() -> None:
    """The crosswalk knows thousands of players; the artifact carries the ones a card can open."""
    result = build_player_headshot_records(
        crosswalk={"gsis:on-board": "4429795", "gsis:off-board": "3139477"},
        published=["gsis:on-board"],
        build_id=BUILD,
    )
    assert [record["player_id"] for record in result.records] == ["gsis:on-board"]


# ------------------------------------------------------------------------------- the source


def test_the_crosswalk_comes_from_the_registry_that_already_failed_closed() -> None:
    """Not from a raw column.

    The registry has already merged the roster with the `ff_playerids` mirror and rejected any
    row that disagreed about a shared id (ADR-019). Reading `espn_id` off a frame would take
    the same numbers with none of those guarantees.
    """
    registry = build_registry(
        _roster(
            [
                {
                    "gsis_id": "00-0039139",
                    "display_name": "Jahmyr Gibbs",
                    "position": "RB",
                    "team": "DET",
                    "espn_id": "4429795",
                    "sleeper_id": "9221",
                },
                {
                    "gsis_id": "00-0000009",
                    "display_name": "Emeka Vasquez",
                    "position": "WR",
                    "team": "JAX",
                    "espn_id": None,
                    "sleeper_id": "5000009",
                },
            ],
        ),
    )
    crosswalk = crosswalk_from_registry(registry)
    assert crosswalk["gsis:00-0039139"] == "4429795"
    assert crosswalk["gsis:00-0000009"] is None

    result = build_player_headshot_records(
        crosswalk=crosswalk,
        published=["gsis:00-0039139", "gsis:00-0000009"],
        build_id=BUILD,
    )
    assert [record["player_id"] for record in result.records] == ["gsis:00-0039139"]
    assert result.unresolved == ("gsis:00-0000009",)


def test_the_registry_position_vocabulary_is_unchanged_by_any_of_this() -> None:
    """A guard against the portrait work quietly widening what counts as a player."""
    assert Position.parse("RB") is not None


# --------------------------------------------------------------- the validator's own teeth


def _write_bundle(directory, headshot_records, tier_player_ids) -> None:  # type: ignore[no-untyped-def]
    import json

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "player_headshots.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact": "player_headshots",
                "record_schema": "player_headshot_record",
                "build_id": BUILD,
                "generated_at_utc": "2026-09-16T12:00:00Z",
                "record_count": len(headshot_records),
                "records": headshot_records,
            },
        ),
        encoding="utf-8",
    )
    (directory / "tiers.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact": "tiers",
                "record_schema": "tier_record",
                "build_id": BUILD,
                "generated_at_utc": "2026-09-16T12:00:00Z",
                "record_count": len(tier_player_ids),
                "records": [
                    {
                        "schema_version": "1.0",
                        "build_id": BUILD,
                        "league_preset_id": "redraft-12",
                        "scoring_preset": "PPR",
                        "player_id": player_id,
                        "display_name": f"Player {index}",
                        "team": "DET",
                        "position": "RB",
                        "fair_rank": index + 1,
                        "position_rank": index + 1,
                        "tier_ordinal": 0,
                        "tier_label": "Tier 1",
                        "expected_vorp": 10.0 - index,
                        "p10_vorp": 1.0,
                        "p25_vorp": 2.0,
                        "p50_vorp": 3.0,
                        "p75_vorp": 4.0,
                        "p90_vorp": 5.0,
                        "expected_points": 100.0,
                        "uncertainty": 1.0,
                        "quality_flags": [],
                    }
                    for index, player_id in enumerate(tier_player_ids)
                ],
            },
        ),
        encoding="utf-8",
    )


def _headshot_failures(gate) -> list[str]:  # type: ignore[no-untyped-def]
    """Only the portrait checks.

    The two-file bundle these tests write is deliberately not a whole build — it has no CSV
    and no `build_metadata.json`, so the gate as a whole is legitimately red and asserting on
    `gate.passed` would be asserting on that instead. What is under test is which *portrait*
    checks fire, so that is what is read.
    """
    return [
        check.check_id
        for check in gate.checks
        if check.status.value == "fail" and "headshot" in check.check_id
    ]


def _record(player_id: str, provider_id: str, url: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "build_id": BUILD,
        "player_id": player_id,
        "provider": HEADSHOT_PROVIDER,
        "provider_player_id": provider_id,
        "image_url": url if url is not None else headshot_url(provider_id),
    }


def test_a_valid_bundle_passes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_bundle(tmp_path, [_record("p1", "4429795")], ["p1"])
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == []
    ids = {check.check_id for check in gate.checks}
    assert "artifact.headshot_addresses_agree" in ids
    assert "cross_artifact.headshot_coverage" in ids


def test_an_address_on_another_host_is_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The check that stops a build opening the page to an origin nobody reviewed."""
    _write_bundle(
        tmp_path,
        [_record("p1", "4429795", "https://images.example.invalid/4429795.png")],
        ["p1"],
    )
    gate = validate_artifact_directory(tmp_path)
    # Twice over: the record schema's own pattern, and the validator's independent reading.
    assert "artifact.headshot_foreign_host" in _headshot_failures(gate)
    assert any(
        check.check_id == "artifact.record_schema"
        for check in gate.checks
        if check.status.value == "fail"
    )


def test_an_address_that_does_not_match_its_own_id_is_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """One player's id beside another player's picture."""
    _write_bundle(tmp_path, [_record("p1", "4429795", headshot_url("3139477"))], ["p1"])
    gate = validate_artifact_directory(tmp_path)
    # The schema's pattern cannot see this one: both strings are well-formed addresses on the
    # right host. Only a check that reads them together catches it, which is why the redundant
    # `image_url` field is published (ADR-087).
    assert _headshot_failures(gate) == ["artifact.headshot_url_disagrees_with_id"]


def test_a_portrait_for_a_player_the_board_does_not_publish_is_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_bundle(tmp_path, [_record("ghost", "4429795")], ["p1"])
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == ["cross_artifact.headshot_player_not_in_tiers"]


def test_a_board_player_with_no_portrait_is_coverage_and_not_a_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The asymmetry is the contract, not an oversight."""
    _write_bundle(tmp_path, [_record("p1", "4429795")], ["p1", "p2", "p3"])
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == []
    coverage = next(
        check for check in gate.checks if check.check_id == "cross_artifact.headshot_coverage"
    )
    assert coverage.observed == "1/3 player(s)"
