"""Fail-closed identity resolution.

Every refusal path in ADR-019 gets a test, because the whole value of a fail-closed
resolver is that it refuses in exactly the cases where a permissive one would corrupt data
silently. Exit-gate item 5 - "at least one deliberately ambiguous fixture demonstrably
fails closed for the intended reason" - is covered several times over here.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from ffdraft.contracts import (
    MARKET_QUOTE_CONTRACT,
    PLAYER_STATUS_CONTRACT,
    EntityKind,
    ResolutionStatus,
)
from ffdraft.identity import build_registry, resolve_market_quotes, resolve_sleeper_status
from ffdraft.identity.aliases import AliasEntry, AliasMap, load_alias_map
from ffdraft.identity.ids import IdNamespace
from ffdraft.identity.registry import LookupStatus
from ffdraft.identity.resolver import (
    PRIMARY_MARKET_BRIDGE,
    REASON_ALIAS_CONFLICT,
    REASON_ALIAS_TARGET_UNKNOWN,
    REASON_BRIDGE_DISAGREEMENT,
    REASON_COLLIDING_INDEX,
    REASON_MALFORMED_EXTERNAL_ID,
    REASON_NO_BRIDGE,
    REASON_NON_PLAYER_ENTITY,
    REASON_RESOLVED_BOTH,
    REASON_RESOLVED_SECONDARY,
    REASON_SLEEPER_GSIS_MISMATCH,
    SECONDARY_MARKET_BRIDGE,
)
from ffdraft.sources import NflverseRosterAdapter


def _registry(roster_rows):
    batch = NflverseRosterAdapter().normalize(roster_rows, season=2026)
    return build_registry(batch.frame)


def _quote(external_id: str, *, kind: EntityKind = EntityKind.PLAYER) -> pl.DataFrame:
    return MARKET_QUOTE_CONTRACT.build(
        [
            {
                "source_id": "myfantasyleague_adp",
                "season": 2026,
                "external_player_id": external_id,
                "average_pick": 12.0,
                "entity_kind": str(kind),
                "scoring_preset": "PPR",
                "league_size": 12,
                "cohort_approximate": True,
                "source_format_detail": "no filters (approximate cohort)",
                "retrieved_at_utc": None,
            },
        ],
    )


@pytest.fixture
def roster(pipeline_fixture_dir):
    return json.loads((pipeline_fixture_dir / "nflverse_rosters.json").read_text())


def test_agreeing_bridges_resolve_and_record_both(roster):
    registry = _registry(roster)
    [outcome] = resolve_market_quotes(
        _quote("6000001"),
        registry=registry,
        espn_by_mfl_id={"6000001": "4000001"},
        gsis_by_mfl_id={"6000001": "00-0000001"},
    )
    assert outcome.status is ResolutionStatus.RESOLVED_CROSSWALK
    assert outcome.player_id == "gsis:00-0000001"
    assert outcome.reason == REASON_RESOLVED_BOTH
    assert set(outcome.bridges_agreed) == {PRIMARY_MARKET_BRIDGE, SECONDARY_MARKET_BRIDGE}


def test_disagreeing_bridges_fail_closed(roster):
    """The headline case. Two independent bridges, two different players, no guess."""
    registry = _registry(roster)
    [outcome] = resolve_market_quotes(
        _quote("6000015"),
        registry=registry,
        espn_by_mfl_id={"6000015": "4000015"},  # -> Hollis Amadi
        gsis_by_mfl_id={"6000015": "00-0000016"},  # -> Xavier Nkemdiche
    )
    assert outcome.status is ResolutionStatus.AMBIGUOUS
    assert outcome.reason == REASON_BRIDGE_DISAGREEMENT
    assert outcome.player_id is None, "an ambiguous outcome must not carry a usable id"
    assert set(outcome.bridges_disagreed) == {PRIMARY_MARKET_BRIDGE, SECONDARY_MARKET_BRIDGE}


def test_secondary_bridge_alone_resolves_but_is_flagged(roster):
    """The mirror is usable evidence, but the caller is told it was the only evidence."""
    registry = _registry(roster)
    [outcome] = resolve_market_quotes(
        _quote("6000009"),
        registry=registry,
        espn_by_mfl_id={},
        gsis_by_mfl_id={"6000009": "00-0000009"},
    )
    assert outcome.status is ResolutionStatus.RESOLVED_CROSSWALK
    assert outcome.reason == REASON_RESOLVED_SECONDARY
    assert "secondary_bridge_only" in outcome.quality_flags


def test_team_units_are_non_player_entities_not_identity_failures(roster):
    registry = _registry(roster)
    [outcome] = resolve_market_quotes(
        _quote("151", kind=EntityKind.TEAM_UNIT),
        registry=registry,
        espn_by_mfl_id={},
        gsis_by_mfl_id={},
    )
    assert outcome.status is ResolutionStatus.UNRESOLVED
    assert outcome.reason == REASON_NON_PLAYER_ENTITY
    assert outcome.entity_kind is EntityKind.TEAM_UNIT


def test_malformed_external_id_fails_closed(roster):
    registry = _registry(roster)
    [outcome] = resolve_market_quotes(
        _quote("not-an-id"),
        registry=registry,
        espn_by_mfl_id={"not-an-id": "4000001"},
        gsis_by_mfl_id={},
    )
    assert outcome.status is ResolutionStatus.UNRESOLVED
    assert outcome.reason == REASON_MALFORMED_EXTERNAL_ID


def test_a_poisoned_crosswalk_index_fails_every_lookup_through_it(pipeline_fixture_dir):
    """Two canonical players share one espn_id. Neither may win (ADR-005)."""
    rows = json.loads(
        (pipeline_fixture_dir / "collisions" / "roster_espn_collision.json").read_text(),
    )
    registry = _registry(rows)
    assert any(check.check_id == "identity.crosswalk_collision" for check in registry.checks)

    lookup = registry.lookup(IdNamespace.ESPN, "4000004")
    assert lookup.status is LookupStatus.AMBIGUOUS
    assert len(lookup.colliding) == 2

    [outcome] = resolve_market_quotes(
        _quote("6000004"),
        registry=registry,
        espn_by_mfl_id={"6000004": "4000004"},
        gsis_by_mfl_id={},
    )
    assert outcome.status is ResolutionStatus.AMBIGUOUS
    assert outcome.reason == REASON_COLLIDING_INDEX


def test_name_matching_never_resolves_a_production_record(roster):
    """Two players share a normalized name; neither may be chosen by name (ADR-005)."""
    registry = _registry(roster)

    [outcome] = resolve_market_quotes(
        _quote("6000004"),
        registry=registry,
        espn_by_mfl_id={},
        gsis_by_mfl_id={},
        names_by_mfl_id={"6000004": "Chris Johnson"},
    )
    assert outcome.status is ResolutionStatus.UNRESOLVED
    assert outcome.reason == REASON_NO_BRIDGE
    assert outcome.player_id is None
    # Candidates are reported as diagnostics, never acted on.
    assert outcome.name_candidates == ("gsis:00-0000004", "gsis:00-0000005")
    assert "name_candidates_not_used" in outcome.quality_flags


def test_a_unique_name_candidate_still_does_not_resolve(roster):
    """Even one unambiguous-looking candidate is not evidence. Ids resolve; names do not."""
    registry = _registry(roster)
    assert registry.name_candidates("Marcus Vandelay") == ("gsis:00-0000001",)

    [outcome] = resolve_market_quotes(
        _quote("6000001"),
        registry=registry,
        espn_by_mfl_id={},
        gsis_by_mfl_id={},
        names_by_mfl_id={"6000001": "Marcus Vandelay"},
    )
    assert outcome.status is ResolutionStatus.UNRESOLVED
    assert outcome.player_id is None


def test_generational_suffixes_collapse_which_is_why_names_are_not_keys(roster):
    """ "Chris Johnson" and "Chris Johnson Jr." share a normalized key.

    Suffix stripping is deliberate for candidate generation, and it is precisely why a
    normalized name can never be authoritative: two distinct players collide on it.
    """
    registry = _registry(roster)
    both = ("gsis:00-0000004", "gsis:00-0000005")
    assert registry.name_candidates("Chris Johnson") == both
    assert registry.name_candidates("Chris Johnson Jr.") == both


def test_reviewed_alias_resolves_only_when_no_bridge_does(roster):
    registry = _registry(roster)
    aliases = AliasMap(
        entries={
            ("myfantasyleague_adp", "6000004"): AliasEntry(
                source_id="myfantasyleague_adp",
                external_id="6000004",
                player_id="gsis:00-0000004",
                reviewed_by="tester",
            ),
        },
    )
    [outcome] = resolve_market_quotes(
        _quote("6000004"),
        registry=registry,
        espn_by_mfl_id={},
        gsis_by_mfl_id={},
        aliases=aliases,
    )
    assert outcome.status is ResolutionStatus.RESOLVED_REVIEWED_ALIAS
    assert outcome.player_id == "gsis:00-0000004"


def test_alias_contradicting_a_bridge_fails_closed(roster):
    """A stale alias must never quietly outvote live id evidence."""
    registry = _registry(roster)
    aliases = AliasMap(
        entries={
            ("myfantasyleague_adp", "6000004"): AliasEntry(
                source_id="myfantasyleague_adp",
                external_id="6000004",
                player_id="gsis:00-0000005",
                reviewed_by="tester",
            ),
        },
    )
    [outcome] = resolve_market_quotes(
        _quote("6000004"),
        registry=registry,
        espn_by_mfl_id={"6000004": "4000004"},
        gsis_by_mfl_id={},
        aliases=aliases,
    )
    assert outcome.status is ResolutionStatus.AMBIGUOUS
    assert outcome.reason == REASON_ALIAS_CONFLICT


def test_alias_pointing_at_an_unknown_player_fails_closed(roster):
    registry = _registry(roster)
    aliases = AliasMap(
        entries={
            ("myfantasyleague_adp", "6000004"): AliasEntry(
                source_id="myfantasyleague_adp",
                external_id="6000004",
                player_id="gsis:00-9999999",
                reviewed_by="tester",
            ),
        },
    )
    [outcome] = resolve_market_quotes(
        _quote("6000004"),
        registry=registry,
        espn_by_mfl_id={},
        gsis_by_mfl_id={},
        aliases=aliases,
    )
    assert outcome.status is ResolutionStatus.UNRESOLVED
    assert outcome.reason == REASON_ALIAS_TARGET_UNKNOWN


def test_missing_alias_file_is_an_empty_map(tmp_path):
    assert len(load_alias_map(tmp_path / "nope.yaml")) == 0
    assert len(load_alias_map(None)) == 0


# --------------------------------------------------------------------------------------
# nflverse -> Sleeper
# --------------------------------------------------------------------------------------


def _status_frame(rows):
    return PLAYER_STATUS_CONTRACT.build(rows)


def test_sleeper_join_runs_from_nflverse_and_ignores_sleeper_only_records(roster):
    from ffdraft.sources import SleeperPlayerAdapter

    registry = _registry(roster)
    batch = SleeperPlayerAdapter().normalize(
        {
            "5000001": {"player_id": "5000001", "gsis_id": " 00-0000001", "status": "Active"},
            "5009999": {"player_id": "5009999", "gsis_id": None, "status": "Inactive"},
        },
    )
    outcomes = resolve_sleeper_status(batch.frame, registry=registry)
    resolved = {o.external_player_id: o for o in outcomes if o.resolved}
    assert resolved["5000001"].player_id == "gsis:00-0000001"
    # The Sleeper-only record is never visited: iteration runs over canonical players.
    assert "5009999" not in {o.external_player_id for o in outcomes}


def test_sleeper_gsis_cross_check_failure_fails_the_record_closed(roster):
    """Sleeper's gsis_id is a cross-check; a mismatch is fatal, not something to average."""
    from ffdraft.sources import SleeperPlayerAdapter

    registry = _registry(roster)
    batch = SleeperPlayerAdapter().normalize(
        {"5000014": {"player_id": "5000014", "gsis_id": "00-0000010", "status": "Active"}},
    )
    resolved = resolve_sleeper_status(batch.frame, registry=registry)
    outcomes = {o.external_player_id: o for o in resolved}
    outcome = outcomes["5000014"]
    assert outcome.status is ResolutionStatus.AMBIGUOUS
    assert outcome.reason == REASON_SLEEPER_GSIS_MISMATCH
    assert outcome.player_id is None


def test_a_canonical_player_absent_from_sleeper_is_recorded_not_dropped(roster):
    registry = _registry(roster)
    outcomes = resolve_sleeper_status(_status_frame([]), registry=registry)
    assert outcomes, "every canonical player with a sleeper_id must produce an outcome"
    assert all(o.status is ResolutionStatus.UNRESOLVED for o in outcomes)
    assert all(o.reason == "sleeper_record_missing" for o in outcomes)
