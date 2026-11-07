"""The portrait crosswalk, its population, and the one host it may name (ADR-087).

Grouped by the question each answers, because none of these is about how a picture looks:

| question                                           | why it could go wrong quietly            |
|----------------------------------------------------|------------------------------------------|
| does an unbridged player produce a row?            | a URL ending in `None.png`               |
| does the address resolve from the id beside it?    | one player's face under another's name   |
| can a build point the page at another host?        | an unreviewed origin in a published file |
| does every card a reader can open get its picture? | in-season cards drawing a monogram       |
| is an id two players share refused for both?       | one picture under two names              |
| does a thin crosswalk fail a build?                | a deploy stopped over a missing picture  |
| does the metadata describe the published file?     | a coverage figure about another set      |

The population cases are the 2026-11-06 trace: Kirk Cousins (`gsis:00-0029604`, ESPN 14880)
was on the rest-of-season board, the Opportunity Board, the week's projections and the season
actuals, the identity registry held his ESPN id uniquely, and his card drew a monogram because
the portrait population was the tier board alone.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.validate import (
    _headshot_cross_checks,
    portrait_bundle,
    validate_artifact_directory,
)
from ffdraft.contracts.enums import Position
from ffdraft.headshots import (
    HEADSHOT_HOST,
    HEADSHOT_PROVIDER,
    PORTRAIT_POPULATION_RULE,
    PORTRAIT_SURFACE_ARTIFACTS,
    PortraitBridge,
    PortraitCrosswalk,
    PortraitGap,
    build_player_headshot_records,
    crosswalk_from_registry,
    headshot_url,
    portrait_population,
)
from ffdraft.identity.registry import build_registry
from ffdraft.quality import QualityGate
from ffdraft.status.employment import build_identity_registry

BUILD = "test-build"
ROS_BUILD = "2026w08-test-ros"

COUSINS = "gsis:00-0029604"
GIBBS = "gsis:00-0039139"


def _roster(rows: list[dict[str, object]], *, season: int = 2026) -> pl.DataFrame:
    return pl.DataFrame(
        [{"season": season, "status": "ACT", **row} for row in rows],
        schema={
            "season": pl.Int32,
            "gsis_id": pl.String,
            "display_name": pl.String,
            "position": pl.String,
            "team": pl.String,
            "status": pl.String,
            "espn_id": pl.String,
            "sleeper_id": pl.String,
        },
    )


def _tiers_only(*player_ids: str):  # type: ignore[no-untyped-def]
    return portrait_population({"tiers": [{"player_id": pid} for pid in player_ids]})


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
        population=_tiers_only("gsis:00-0000001"),
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
        population=_tiers_only("gsis:00-0000001", "gsis:00-0000002"),
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
        population=_tiers_only("gsis:00-0000006"),
        build_id=BUILD,
    )
    assert result.records == []
    assert result.unresolved == ("gsis:00-0000006",)
    assert result.gaps == {"gsis:00-0000006": PortraitGap.NO_PROVIDER_ID}
    assert result.resolved == 0
    assert result.published_players == 1


def test_a_malformed_id_is_refused_rather_than_rendered() -> None:
    result = build_player_headshot_records(
        crosswalk={"gsis:00-0000006": "not-a-number"},
        population=_tiers_only("gsis:00-0000006"),
        build_id=BUILD,
    )
    assert result.records == []
    assert result.gaps == {"gsis:00-0000006": PortraitGap.INVALID_PROVIDER_ID}


def test_a_player_the_registry_does_not_know_is_counted_as_such() -> None:
    result = build_player_headshot_records(
        crosswalk={},
        population=_tiers_only("gsis:00-0000006"),
        build_id=BUILD,
    )
    assert result.gaps == {"gsis:00-0000006": PortraitGap.NOT_IN_REGISTRY}


def test_a_thin_crosswalk_never_fails_a_build() -> None:
    """No coverage floor, deliberately.

    A gate that could stop a deploy over a missing picture would be able to take the whole
    board down for a cosmetic reason (ADR-087).
    """
    gate = QualityGate()
    result = build_player_headshot_records(
        crosswalk={f"gsis:{index}": None for index in range(50)},
        population=_tiers_only(*(f"gsis:{index}" for index in range(50))),
        build_id=BUILD,
        gate=gate,
    )
    assert result.resolved == 0
    assert gate.passed
    assert not [check for check in gate.checks if check.status.value == "fail"]


# ------------------------------------------------------------------------------ population


def test_the_population_counts_players_not_rows() -> None:
    """A player appears in up to nine tier rows; the denominator is players."""
    population = portrait_population(
        {"tiers": [{"player_id": "gsis:00-0000001"}] * 9 + [{"player_id": "gsis:00-0000009"}] * 9},
    )
    result = build_player_headshot_records(
        crosswalk={"gsis:00-0000001": "4429795", "gsis:00-0000009": "1111111"},
        population=population,
        build_id=BUILD,
    )
    assert result.published_players == 2
    assert result.resolved == 2
    assert len(result.records) == 2


def test_the_population_is_every_card_surface_and_nothing_else() -> None:
    """Every surface a card opens from is in; card sections and annotation are not."""
    records: dict[str, Any] = {
        "tiers": [{"player_id": "p-draft", "position": "RB"}],
        "arbitrage": [{"player_id": "p-arb", "position": "WR"}],
        "ros_tiers": [{"player_id": "p-ros", "position": "QB"}],
        "inseason_opportunity": [{"player_id": "p-opp", "position": "TE"}],
        "weekly_projections": [{"player_id": "p-week", "position": "QB"}],
        "season_actuals": [{"player_id": "p-act", "position": "WR"}],
        "insights": [{"player_id": "p-story", "position": "RB"}],
        # Not surfaces: a card section, annotation, and a card-only artifact.
        "player_usage": [{"player_id": "p-usage-only"}],
        "player_status": [{"player_id": "p-status-only"}],
        "projections": [{"player_id": "p-projection-only"}],
    }
    population = portrait_population(records)
    assert population.players == tuple(
        sorted(["p-draft", "p-arb", "p-ros", "p-opp", "p-week", "p-act", "p-story"]),
    )
    assert population.surfaces_read == PORTRAIT_SURFACE_ARTIFACTS
    assert population.membership("p-ros") == ("ros_tiers",)
    assert population.positions["p-opp"] == "TE"


def test_a_surface_not_read_is_absent_rather_than_empty() -> None:
    """The metadata has to say which denominator it used; "not read" is not "nobody"."""
    population = portrait_population({"tiers": [], "ros_tiers": None})
    assert population.surfaces_read == ("tiers",)
    assert population.players == ()


def test_an_in_season_player_off_the_tier_board_gets_his_portrait() -> None:
    """The 2026-11-06 Cousins trace, end to end through the real registry.

    On the ROS board, the Opportunity Board, the week's projections and the season actuals,
    never on the draft board. Before, the population was the tier board and he had no row.
    """
    registry = build_identity_registry(
        _roster(
            [
                {
                    "gsis_id": "00-0029604",
                    "display_name": "Kirk Cousins",
                    "position": "QB",
                    "team": "LV",
                    "espn_id": "14880",
                    "sleeper_id": "1166",
                },
                {
                    "gsis_id": "00-0039139",
                    "display_name": "Jahmyr Gibbs",
                    "position": "RB",
                    "team": "DET",
                    "espn_id": "4429795",
                    "sleeper_id": "9221",
                },
            ],
        ),
    )
    in_season = {
        "tiers": [{"player_id": GIBBS, "position": "RB"}],
        "ros_tiers": [{"player_id": COUSINS, "position": "QB"}, {"player_id": GIBBS}],
        "inseason_opportunity": [{"player_id": COUSINS, "position": "QB"}],
        "weekly_projections": [{"player_id": COUSINS, "position": "QB"}],
        "season_actuals": [{"player_id": COUSINS, "position": "QB"}],
    }
    result = build_player_headshot_records(
        crosswalk=crosswalk_from_registry(registry),
        population=portrait_population(in_season),
        build_id=BUILD,
    )
    by_player = {record["player_id"]: record for record in result.records}
    assert by_player[COUSINS]["image_url"] == headshot_url("14880")
    assert GIBBS in by_player

    # The old population - the tier board alone - is the defect reproduced.
    draft_only = build_player_headshot_records(
        crosswalk=crosswalk_from_registry(registry),
        population=portrait_population({"tiers": in_season["tiers"]}),
        build_id=BUILD,
    )
    assert COUSINS not in {record["player_id"] for record in draft_only.records}


def test_a_player_off_both_rosters_has_no_portrait_and_says_why() -> None:
    registry = build_identity_registry(
        _roster(
            [
                {
                    "gsis_id": "00-0039139",
                    "display_name": "Jahmyr Gibbs",
                    "position": "RB",
                    "team": "DET",
                    "espn_id": "4429795",
                    "sleeper_id": "9221",
                }
            ]
        ),
    )
    result = build_player_headshot_records(
        crosswalk=crosswalk_from_registry(registry),
        population=portrait_population({"season_actuals": [{"player_id": "gsis:00-0099999"}]}),
        build_id=BUILD,
    )
    assert result.records == []
    assert result.gaps == {"gsis:00-0099999": PortraitGap.NOT_IN_REGISTRY}


def test_last_seasons_roster_identifies_an_off_roster_player() -> None:
    """ADR-102's identity spine: an unsigned player named in season keeps his crosswalk."""
    current = _roster(
        [
            {
                "gsis_id": "00-0039139",
                "display_name": "Jahmyr Gibbs",
                "position": "RB",
                "team": "DET",
                "espn_id": "4429795",
                "sleeper_id": "9221",
            }
        ]
    )
    prior = _roster(
        [
            {
                "gsis_id": "00-0033040",
                "display_name": "Tyreek Hill",
                "position": "WR",
                "team": "MIA",
                "espn_id": "3116406",
                "sleeper_id": "3321",
            }
        ],
        season=2025,
    )
    result = build_player_headshot_records(
        crosswalk=crosswalk_from_registry(build_identity_registry(current, [prior])),
        population=portrait_population(
            {"inseason_opportunity": [{"player_id": "gsis:00-0033040", "position": "WR"}]},
        ),
        build_id=BUILD,
    )
    assert [record["provider_player_id"] for record in result.records] == ["3116406"]


# ------------------------------------------------------------------------- fail closed


def test_an_id_two_registry_players_share_is_refused_for_both() -> None:
    """One picture under two names is the identity mistake this artifact must not make."""
    registry = build_registry(
        _roster(
            [
                {
                    "gsis_id": "00-0000001",
                    "display_name": "Chris Johnson",
                    "position": "WR",
                    "team": "TEN",
                    "espn_id": "4000004",
                    "sleeper_id": "1",
                },
                {
                    "gsis_id": "00-0000002",
                    "display_name": "Chris Johnson Jr.",
                    "position": "WR",
                    "team": "JAX",
                    "espn_id": "4000004",
                    "sleeper_id": "2",
                },
                {
                    "gsis_id": "00-0000003",
                    "display_name": "Someone Else",
                    "position": "QB",
                    "team": "BUF",
                    "espn_id": "4000003",
                    "sleeper_id": "3",
                },
            ],
        ),
    )
    crosswalk = crosswalk_from_registry(registry)
    population = _tiers_only("gsis:00-0000001", "gsis:00-0000002", "gsis:00-0000003")
    result = build_player_headshot_records(
        crosswalk=crosswalk, population=population, build_id=BUILD
    )
    assert [record["player_id"] for record in result.records] == ["gsis:00-0000003"]
    assert result.gaps == {
        "gsis:00-0000001": PortraitGap.AMBIGUOUS_PROVIDER_ID,
        "gsis:00-0000002": PortraitGap.AMBIGUOUS_PROVIDER_ID,
    }
    assert result.summary()["unresolved_reasons"]["ambiguous_espn_id"] == 2


def test_a_plain_mapping_is_held_to_the_same_rule() -> None:
    crosswalk = PortraitCrosswalk.from_mapping({"a": "123", "b": "0123", "c": "456"})
    # "0123" normalizes to "123": the same athlete, claimed twice.
    assert crosswalk.resolve("a") == (None, PortraitGap.AMBIGUOUS_PROVIDER_ID)
    assert crosswalk.resolve("b") == (None, PortraitGap.AMBIGUOUS_PROVIDER_ID)
    assert crosswalk.resolve("c") == ("456", None)


def _master(rows: list[tuple[str, str | None]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema={"gsis_id": pl.String, "espn_id": pl.String}, orient="row")


def _bridge_registry():  # type: ignore[no-untyped-def]
    return build_identity_registry(
        _roster(
            [
                {
                    "gsis_id": "00-0039550",
                    "display_name": "Shawn Bowman",
                    "position": "TE",
                    "team": "ARI",
                    "espn_id": None,
                    "sleeper_id": None,
                },
                {
                    "gsis_id": "00-0039139",
                    "display_name": "Jahmyr Gibbs",
                    "position": "RB",
                    "team": "DET",
                    "espn_id": "4429795",
                    "sleeper_id": "9221",
                },
                {
                    "gsis_id": "00-0040046",
                    "display_name": "Rivaldo Fairweather",
                    "position": "TE",
                    "team": "ARI",
                    "espn_id": None,
                    "sleeper_id": None,
                },
            ],
        ),
    )


def test_the_player_master_fills_a_roster_gap_by_gsis_key() -> None:
    crosswalk = crosswalk_from_registry(
        _bridge_registry(), player_master=_master([("00-0039550", "4366910")])
    )
    assert crosswalk.resolve("gsis:00-0039550") == ("4366910", None)
    assert crosswalk.bridges["gsis:00-0039550"] is PortraitBridge.PLAYER_MASTER
    assert crosswalk.bridges["gsis:00-0039139"] is PortraitBridge.ROSTER


def test_the_master_never_overrides_the_roster() -> None:
    crosswalk = crosswalk_from_registry(
        _bridge_registry(), player_master=_master([("00-0039139", "9999999")])
    )
    assert crosswalk.resolve("gsis:00-0039139") == ("4429795", None)


def test_a_master_id_another_player_holds_is_refused() -> None:
    """Gibbs' roster id offered to a TE by the master: refused, and Gibbs keeps his."""
    crosswalk = crosswalk_from_registry(
        _bridge_registry(), player_master=_master([("00-0039550", "4429795")])
    )
    assert crosswalk.resolve("gsis:00-0039550") == (None, PortraitGap.AMBIGUOUS_PROVIDER_ID)
    assert crosswalk.resolve("gsis:00-0039139") == ("4429795", None)


def test_a_master_id_two_master_rows_share_is_refused() -> None:
    crosswalk = crosswalk_from_registry(
        _bridge_registry(),
        player_master=_master([("00-0039550", "4366910"), ("00-0011111", "4366910")]),
    )
    assert crosswalk.resolve("gsis:00-0039550") == (None, PortraitGap.AMBIGUOUS_PROVIDER_ID)


def test_the_master_never_adds_a_player_the_registry_does_not_know() -> None:
    crosswalk = crosswalk_from_registry(
        _bridge_registry(), player_master=_master([("00-0077777", "5555555")])
    )
    assert crosswalk.resolve("gsis:00-0077777") == (None, PortraitGap.NOT_IN_REGISTRY)


# --------------------------------------------------------------------------- the metadata


def test_the_summary_names_its_denominator() -> None:
    population = portrait_population(
        {
            "tiers": [{"player_id": "a", "position": "QB"}],
            "ros_tiers": [{"player_id": "a"}, {"player_id": "b", "position": "WR"}],
            "weekly_projections": [{"player_id": "c", "position": "RB"}],
        },
    )
    result = build_player_headshot_records(
        crosswalk={"a": "1", "b": "2", "c": None},
        population=population,
        build_id=BUILD,
    )
    summary = result.summary()
    assert summary["population"] == {
        "rule_version": PORTRAIT_POPULATION_RULE,
        "surfaces_read": ["tiers", "ros_tiers", "weekly_projections"],
        "players": 3,
    }
    assert summary["published_players"] == 3
    assert summary["resolved"] == 2
    assert summary["coverage"] == round(2 / 3, 4)
    assert summary["by_surface"] == {
        "tiers": {"players": 1, "resolved": 1},
        "ros_tiers": {"players": 2, "resolved": 2},
        "weekly_projections": {"players": 1, "resolved": 0},
    }
    assert summary["by_position"] == {
        "QB": {"players": 1, "resolved": 1},
        "RB": {"players": 1, "resolved": 0},
        "WR": {"players": 1, "resolved": 1},
    }
    assert summary["unresolved_reasons"] == {
        "not_in_identity_registry": 0,
        "no_espn_id": 1,
        "invalid_espn_id": 0,
        "ambiguous_espn_id": 0,
    }
    assert summary["bridges"] == {"nflverse_roster": 2, "nflverse_player_master": 0}


def test_the_registry_position_vocabulary_is_unchanged_by_any_of_this() -> None:
    """A guard against the portrait work quietly widening what counts as a player."""
    assert Position.parse("RB") is not None


# ------------------------------------------------------------------------ the firewall


def test_no_value_producing_module_reads_a_portrait() -> None:
    """Portraits never feed a model, a projection, a rank, a tier or a board value.

    The import graph, walked the way `tests/contract/test_architecture_boundary.py` walks it.
    One edge is allowed and removed before the walk: the artifact validator imports the
    host constants to re-check published addresses, and every value package can reach the
    validator through the serializer package without reading a single portrait.
    """
    src = Path(__file__).resolve().parents[2] / "src"
    package = src / "ffdraft"

    def name(path: Path) -> str:
        parts = list(path.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    graph: dict[str, set[str]] = {}
    for path in sorted(package.rglob("*.py")):
        found: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names if a.name.startswith("ffdraft"))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.level == 0
                and node.module.startswith("ffdraft")
            ):
                found.add(node.module)
                found.update(
                    f"{node.module}.{alias.name}"
                    for alias in node.names
                    if (src / Path(*node.module.split(".")) / f"{alias.name}.py").is_file()
                )
        graph[name(path)] = found
    graph["ffdraft.artifacts.validate"].discard("ffdraft.headshots")

    def reach(start: str) -> set[str]:
        seen: set[str] = set()
        queue = [start]
        while queue:
            for target in graph.get(queue.pop(), set()):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen

    value_packages = (
        "ffdraft.features",
        "ffdraft.labels",
        "ffdraft.modeling",
        "ffdraft.simulation",
        "ffdraft.tiers",
        "ffdraft.scoring",
        "ffdraft.ros",
        "ffdraft.weekly",
        "ffdraft.opportunity",
        "ffdraft.arbitrage",
        "ffdraft.signals",
        "ffdraft.insights",
    )
    offenders = [
        module
        for module in graph
        if any(module == p or module.startswith(f"{p}.") for p in value_packages)
        and "ffdraft.headshots" in reach(module)
    ]
    assert not offenders, offenders
    # And the allowed direction is real: both builds publish it.
    assert "ffdraft.headshots" in reach("ffdraft.pipeline.ros")
    assert "ffdraft.headshots" in reach("ffdraft.pipeline.current")


# --------------------------------------------------------------- the validator's own teeth


def _envelope(
    artifact: str, schema: str, records: list[dict[str, Any]], build_id: str = BUILD
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact": artifact,
        "record_schema": schema,
        "build_id": build_id,
        "generated_at_utc": "2026-09-16T12:00:00Z",
        "record_count": len(records),
        "records": records,
    }


def _write(directory: Path, name: str, payload: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def _tier_rows(player_ids: list[str]) -> list[dict[str, Any]]:
    return [
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
        for index, player_id in enumerate(player_ids)
    ]


def _write_bundle(  # type: ignore[no-untyped-def]
    directory: Path,
    headshot_records,
    tier_player_ids,
    *,
    headshot_build: str = BUILD,
    surfaces: dict[str, list[str]] | None = None,
) -> None:
    _write(
        directory,
        "player_headshots.json",
        _envelope("player_headshots", "player_headshot_record", headshot_records, headshot_build),
    )
    _write(directory, "tiers.json", _envelope("tiers", "tier_record", _tier_rows(tier_player_ids)))
    for artifact, player_ids in (surfaces or {}).items():
        # Only the player ids matter to the portrait checks; the record schema of these
        # stand-ins is not under test, and `_headshot_failures` reads portrait checks only.
        _write(
            directory,
            f"{artifact}.json",
            _envelope(
                artifact,
                artifact,
                [{"player_id": pid, "position": "QB"} for pid in player_ids],
                ROS_BUILD,
            ),
        )


def _headshot_failures(gate) -> list[str]:  # type: ignore[no-untyped-def]
    """Only the portrait checks.

    The bundles these tests write are deliberately not a whole build — no CSV and partial
    metadata — so the gate as a whole is legitimately red and asserting on `gate.passed` would
    be asserting on that instead. What is under test is which *portrait* checks fire.
    """
    return sorted(
        check.check_id
        for check in gate.checks
        if check.status.value == "fail" and "headshot" in check.check_id
    )


def _check(gate, check_id: str):  # type: ignore[no-untyped-def]
    return next(check for check in gate.checks if check.check_id == check_id)


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


def test_one_provider_id_published_for_two_players_is_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_bundle(tmp_path, [_record("p1", "4429795"), _record("p2", "4429795")], ["p1", "p2"])
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == ["artifact.headshot_provider_id_shared"]


def test_a_portrait_outside_every_card_surface_is_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_bundle(
        tmp_path,
        [_record("ghost", "4429795")],
        ["p1"],
        surfaces={"ros_tiers": ["p2"], "weekly_projections": ["p3"]},
    )
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == ["cross_artifact.headshot_player_outside_card_surfaces"]


def test_a_portrait_for_an_in_season_player_off_the_tier_board_passes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The old check (`headshot_player_not_in_tiers`) failed exactly this, the Cousins case."""
    _write_bundle(
        tmp_path,
        [_record("p1", "4429795"), _record(COUSINS, "14880")],
        ["p1"],
        surfaces={"ros_tiers": [COUSINS], "weekly_projections": [COUSINS]},
    )
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == []
    coverage = _check(gate, "cross_artifact.headshot_coverage")
    assert coverage.observed.startswith("2/2 player(s)")


def _cross(surfaces: dict[str, list[str]], portraits: list[str]) -> list[str]:
    """The union check alone, over in-memory envelopes (no other artifact check runs)."""
    envelopes = {
        name: {"records": [{"player_id": pid} for pid in players]}
        for name, players in surfaces.items()
    }
    envelopes["player_headshots"] = {
        "records": [_record(pid, str(i + 1)) for i, pid in enumerate(portraits)]
    }
    return [check.check_id for check in _headshot_cross_checks(envelopes) if check.blocking]


@pytest.mark.parametrize("surface", PORTRAIT_SURFACE_ARTIFACTS)
def test_every_card_surface_admits_a_portrait(surface: str) -> None:
    assert _cross({"tiers": ["p1"], surface: ["only-here"]}, ["only-here"]) == []


@pytest.mark.parametrize(
    "not_a_surface",
    ["player_usage", "player_status", "projections", "recent_form", "espn_ownership"],
)
def test_a_card_section_or_annotation_does_not_admit_a_portrait(not_a_surface: str) -> None:
    assert _cross({"tiers": ["p1"], not_a_surface: ["only-here"]}, ["only-here"]) == [
        "cross_artifact.headshot_player_outside_card_surfaces"
    ]


def test_a_portrait_file_with_no_surface_beside_it_is_refused() -> None:
    assert _cross({}, ["p1"]) == ["cross_artifact.headshot_player_outside_card_surfaces"]


def test_a_surface_player_with_no_portrait_is_coverage_and_not_a_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The asymmetry is the contract, not an oversight."""
    _write_bundle(
        tmp_path, [_record("p1", "4429795")], ["p1", "p2", "p3"], surfaces={"ros_tiers": ["p4"]}
    )
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == []
    coverage = _check(gate, "cross_artifact.headshot_coverage")
    assert coverage.observed == "1/4 player(s) (tiers 1/3, ros_tiers 0/1)"


# ------------------------------------------------------------- which metadata describes it


def _block(*, players: int, resolved: int, surfaces: dict[str, tuple[int, int]]) -> dict[str, Any]:
    return {
        "provider": "espn",
        "host": HEADSHOT_HOST,
        "source_ids": ["nflreadpy"],
        "population": {
            "rule_version": PORTRAIT_POPULATION_RULE,
            "surfaces_read": list(surfaces),
            "players": players,
        },
        "published_players": players,
        "resolved": resolved,
        "coverage": round(resolved / players, 4) if players else 0.0,
        "by_surface": {name: {"players": p, "resolved": r} for name, (p, r) in surfaces.items()},
        "by_position": {},
        "unresolved_reasons": {
            "not_in_identity_registry": 0,
            "no_espn_id": players - resolved,
            "invalid_espn_id": 0,
            "ambiguous_espn_id": 0,
        },
        "bridges": {"nflverse_roster": resolved, "nflverse_player_master": 0},
    }


def _in_season_directory(tmp_path: Path, *, ros_block: dict[str, Any] | None) -> Path:
    """Production's in-season shape: the draft build's block, then the ROS build's file."""
    _write_bundle(
        tmp_path,
        [_record("p1", "4429795"), _record(COUSINS, "14880")],
        ["p1", "p2"],
        headshot_build=ROS_BUILD,
        surfaces={"ros_tiers": [COUSINS, "p1"]},
    )
    _write(
        tmp_path,
        "build_metadata.json",
        {
            "build_id": BUILD,
            "player_headshots": _block(players=2, resolved=1, surfaces={"tiers": (2, 1)}),
        },
    )
    _write(
        tmp_path, "ros_build_metadata.json", {"build_id": ROS_BUILD, "player_headshots": ros_block}
    )
    return tmp_path


def test_the_in_season_build_owns_the_file_it_wrote(tmp_path) -> None:  # type: ignore[no-untyped-def]
    directory = _in_season_directory(
        tmp_path,
        ros_block=_block(players=3, resolved=2, surfaces={"tiers": (2, 1), "ros_tiers": (2, 2)}),
    )
    envelopes = {
        "player_headshots": json.loads((directory / "player_headshots.json").read_text()),
    }
    assert portrait_bundle(directory, envelopes) == "ros"
    gate = validate_artifact_directory(directory)
    assert _headshot_failures(gate) == []
    ids = {check.check_id for check in gate.checks}
    assert "cross_artifact.headshot_metadata_agrees" in ids
    assert "cross_artifact.headshot_metadata_superseded" in ids
    # The build-id half (draft metadata no longer compared, ROS metadata compared) runs on
    # complete metadata files in `tests/contract/test_two_bundle_validation.py`.


def test_a_ros_stamped_file_no_ros_metadata_describes_stays_the_draft_bundles(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """So its build id is compared with the draft build's, and a stray stamp fails there."""
    directory = _in_season_directory(tmp_path, ros_block=None)
    envelopes = {
        "player_headshots": json.loads((directory / "player_headshots.json").read_text()),
    }
    assert portrait_bundle(directory, envelopes) == "draft"


def test_metadata_that_describes_another_set_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The masking the 2026-11-06 audit found: 575/614 printed beside a 729-player site."""
    directory = _in_season_directory(
        tmp_path,
        ros_block=_block(players=2, resolved=1, surfaces={"tiers": (2, 1), "ros_tiers": (2, 2)}),
    )
    gate = validate_artifact_directory(directory)
    assert "cross_artifact.headshot_metadata_disagrees" in _headshot_failures(gate)


def test_surfaces_published_after_the_portrait_set_are_reported_not_failed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Preseason: the arbitrage board is built after the draft build's portraits."""
    _write_bundle(
        tmp_path, [_record("p1", "4429795")], ["p1"], surfaces={"arbitrage": ["p1", "a9"]}
    )
    _write(
        tmp_path,
        "build_metadata.json",
        {
            "build_id": BUILD,
            "player_headshots": _block(players=1, resolved=1, surfaces={"tiers": (1, 1)}),
        },
    )
    # The stand-in arbitrage file is stamped with the ROS id by `_write_bundle`; restamp it.
    payload = json.loads((tmp_path / "arbitrage.json").read_text())
    payload["build_id"] = BUILD
    (tmp_path / "arbitrage.json").write_text(json.dumps(payload))
    gate = validate_artifact_directory(tmp_path)
    assert _headshot_failures(gate) == []
    scope = _check(gate, "cross_artifact.headshot_population_scope")
    assert scope.observed == "1 player(s) only on arbitrage"


# ----------------------------------------------------- the rest-of-season build's step


def _cousins_registry():  # type: ignore[no-untyped-def]
    return build_identity_registry(
        _roster(
            [
                {
                    "gsis_id": "00-0029604",
                    "display_name": "Kirk Cousins",
                    "position": "QB",
                    "team": "LV",
                    "espn_id": "14880",
                    "sleeper_id": "1166",
                },
                {
                    "gsis_id": "00-0039139",
                    "display_name": "Jahmyr Gibbs",
                    "position": "RB",
                    "team": "DET",
                    "espn_id": "4429795",
                    "sleeper_id": "9221",
                },
                {
                    "gsis_id": "00-0000777",
                    "display_name": "Arbitrage Only",
                    "position": "WR",
                    "team": "BUF",
                    "espn_id": "7777777",
                    "sleeper_id": "777",
                },
            ],
        ),
    )


def test_the_ros_build_writes_portraits_over_every_surface_the_site_holds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`run_ros_build`'s portrait step: draft boards read from the publish directory."""
    from ffdraft.pipeline.ros import _portraits

    _write(tmp_path, "tiers.json", _envelope("tiers", "tier_record", _tier_rows([GIBBS])))
    _write(
        tmp_path,
        "arbitrage.json",
        _envelope("arbitrage", "arbitrage_record", [{"player_id": "gsis:00-0000777"}]),
    )
    gate = QualityGate()
    result = _portraits(
        records={
            "ros_tiers": [{"player_id": COUSINS, "position": "QB"}],
            "weekly_projections": [{"player_id": COUSINS, "position": "QB"}],
            "player_usage": [{"player_id": "gsis:00-0000999"}],  # a card section, not a surface
        },
        out_dir=tmp_path,
        registry=_cousins_registry(),
        player_master=None,
        build_id=ROS_BUILD,
        gate=gate,
    )
    assert result is not None
    assert {record["player_id"] for record in result.records} == {
        COUSINS,
        GIBBS,
        "gsis:00-0000777",
    }
    assert all(record["build_id"] == ROS_BUILD for record in result.records)
    summary = result.summary()
    assert summary["population"]["surfaces_read"] == [
        "tiers",
        "arbitrage",
        "ros_tiers",
        "weekly_projections",
    ]
    assert gate.passed


def test_the_ros_build_leaves_the_draft_set_when_it_has_no_registry(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """An empty registry must not replace a good portrait file with an empty one."""
    from ffdraft.identity.registry import build_registry as empty_registry
    from ffdraft.pipeline.ros import _portraits

    gate = QualityGate()
    result = _portraits(
        records={"ros_tiers": [{"player_id": COUSINS}]},
        out_dir=tmp_path,
        registry=empty_registry(pl.DataFrame()),
        player_master=None,
        build_id=ROS_BUILD,
        gate=gate,
    )
    assert result is None
    assert "ros.portraits_left_to_draft_build" in {check.check_id for check in gate.checks}


def test_an_unreadable_draft_board_costs_its_players_and_nothing_else(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ffdraft.pipeline.ros import _portraits

    (tmp_path / "tiers.json").write_text("{not json", encoding="utf-8")
    gate = QualityGate()
    result = _portraits(
        records={"ros_tiers": [{"player_id": COUSINS}]},
        out_dir=tmp_path,
        registry=_cousins_registry(),
        player_master=None,
        build_id=ROS_BUILD,
        gate=gate,
    )
    assert result is not None
    assert [record["player_id"] for record in result.records] == [COUSINS]
    assert gate.passed  # a warning, never a failed refresh
    assert "ros.portrait_draft_surface_unreadable" in {check.check_id for check in gate.warnings}


# --------------------------------------------------------------- the published goldens


def test_the_golden_build_publishes_the_in_season_shape() -> None:
    """The committed fixture build: the file is the ROS block's, over every surface."""
    golden = Path(__file__).resolve().parents[1] / "fixtures" / "artifacts"
    ros = json.loads((golden / "ros_build_metadata.json").read_text(encoding="utf-8"))
    draft = json.loads((golden / "build_metadata.json").read_text(encoding="utf-8"))
    block = ros["player_headshots"]
    assert block["population"]["surfaces_read"] == list(PORTRAIT_SURFACE_ARTIFACTS)
    assert draft["player_headshots"]["population"]["surfaces_read"] == ["tiers"]
    records = json.loads((golden / "player_headshots.json").read_text(encoding="utf-8"))["records"]
    tiers = {
        row["player_id"]
        for row in json.loads((golden / "tiers.json").read_text(encoding="utf-8"))["records"]
    }
    off_board = {row["player_id"] for row in records} - tiers
    # The fixture's two off-roster players (identified by last season's roster) are on the
    # Opportunity Board and in the season actuals and now have their portraits.
    assert {"gsis:00-0000020", "gsis:00-0000021"} <= off_board
    elsewhere: set[str] = set()
    for name in PORTRAIT_SURFACE_ARTIFACTS[1:]:
        rows = json.loads((golden / f"{name}.json").read_text(encoding="utf-8"))["records"]
        elsewhere |= {row["player_id"] for row in rows}
    assert off_board <= elsewhere
    assert block["resolved"] == len(records)
