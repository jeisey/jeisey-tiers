"""The reviewed-alias escape hatch, wired through the production capture path.

`config/identity-aliases.yaml` is the only way a genuinely unreachable id ever resolves: the
bridges refuse to guess, so a record no bridge can reach stays unresolved until a person
inspects the case and writes it down. That mechanism was implemented, documented and unit
tested at the resolver, and the fixture pipeline passed it — but `ffdraft.market.capture`,
which is what every production snapshot actually runs, never loaded the file. A review
nobody loads is not a review, so the hatch was closed in exactly the place it was for.

These tests pin the wiring rather than the resolver behaviour, which
`test_identity_resolution.py` already covers in full.

The fixture case mirrors the real one that surfaced this (ADR-054): a player who *is* on the
roster, and therefore is a known canonical player, but whom neither bridge can reach — MFL's
directory has no `espn_id` for him and the crosswalk mirror has no row at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from ffdraft.identity.aliases import AliasEntry, AliasMap, default_alias_path, load_alias_map
from ffdraft.market.capture import build_snapshot
from ffdraft.market.identity import load_market_identity
from ffdraft.sources.market import MFL_SOURCE_ID

#: In the pipeline fixtures this player is on the roster as `gsis:00-0000013` but appears in
#: neither the MFL player directory nor the crosswalk mirror, so both bridges come up empty.
UNREACHABLE_MFL_ID = "6000013"
UNREACHABLE_PLAYER_ID = "gsis:00-0000013"

STAMP = datetime(2026, 8, 26, 11, 29, 17, tzinfo=UTC)


@pytest.fixture
def payloads(pipeline_fixture_dir):
    """The MFL fixtures, with one priced row for a player no bridge can reach."""
    players = json.loads((pipeline_fixture_dir / "mfl_players.json").read_text())
    adp = json.loads((pipeline_fixture_dir / "mfl_adp.json").read_text())
    adp["adp"]["player"] = [
        *adp["adp"]["player"],
        {
            "id": UNREACHABLE_MFL_ID,
            "rank": "99",
            "averagePick": "136.53",
            "minPick": "120",
            "maxPick": "160",
            "draftsSelectedIn": "156",
            "draftSelPct": "38",
        },
    ]
    return players, adp


@pytest.fixture
def identity(pipeline_fixture_dir):
    import polars as pl

    from ffdraft.sources import NflversePlayerIdsAdapter, NflverseRosterAdapter

    roster = NflverseRosterAdapter().normalize(
        json.loads((pipeline_fixture_dir / "nflverse_rosters.json").read_text()),
        season=2026,
        retrieved_at=STAMP,
    )
    ids = NflversePlayerIdsAdapter().normalize(
        json.loads((pipeline_fixture_dir / "nflverse_ff_playerids.json").read_text()),
        retrieved_at=STAMP,
    )
    assert isinstance(roster.frame, pl.DataFrame)
    return load_market_identity(2026, as_of=STAMP, roster=roster.frame, player_ids=ids.frame)


def _snapshot(payloads, identity, **kwargs):
    players, adp = payloads
    return build_snapshot(
        season=2026,
        retrieved_at=STAMP,
        raw_by_cohort={"unfiltered": adp},
        raw_players=players,
        identity=identity,
        **kwargs,
    )


def _row(result, mfl_id):
    for row in result.rows:
        if row["external_player_id"] == mfl_id:
            return row
    return None


def test_a_row_no_bridge_can_reach_is_unresolved_without_a_review(payloads, identity):
    """The premise. If this ever resolves on its own the alias below is masking a bridge."""
    result = _snapshot(payloads, identity, aliases=AliasMap.empty())
    row = _row(result, UNREACHABLE_MFL_ID)
    assert row is not None, "the priced row must survive normalization even unresolved"
    assert row["player_id"] is None
    assert row["display_name"] is None


def test_a_reviewed_alias_resolves_that_row_through_the_capture_path(payloads, identity):
    result = _snapshot(
        payloads,
        identity,
        aliases=AliasMap(
            entries={
                (MFL_SOURCE_ID, UNREACHABLE_MFL_ID): AliasEntry(
                    source_id=MFL_SOURCE_ID,
                    external_id=UNREACHABLE_MFL_ID,
                    player_id=UNREACHABLE_PLAYER_ID,
                    reviewed_by="tester",
                ),
            },
        ),
    )
    row = _row(result, UNREACHABLE_MFL_ID)
    assert row is not None
    assert row["player_id"] == UNREACHABLE_PLAYER_ID
    # The price is the point: a resolved row is one the arbitrage board can actually use.
    assert row["average_pick"] == pytest.approx(136.53)


def test_the_capture_loads_the_repository_alias_file_by_default(payloads, identity, repo_root):
    """The regression this module exists for: no `aliases=` argument must still mean *the*
    reviewed aliases, not an empty map. Asserted through the resolved count rather than by
    inspecting an argument, so it survives a refactor of how the file is reached."""
    shipped = load_alias_map(default_alias_path(root=repo_root))
    everything = AliasMap(
        entries={
            **dict(shipped.entries),
            (MFL_SOURCE_ID, UNREACHABLE_MFL_ID): AliasEntry(
                source_id=MFL_SOURCE_ID,
                external_id=UNREACHABLE_MFL_ID,
                player_id=UNREACHABLE_PLAYER_ID,
                reviewed_by="tester",
            ),
        },
    )
    default = _snapshot(payloads, identity)
    empty = _snapshot(payloads, identity, aliases=AliasMap.empty())
    injected = _snapshot(payloads, identity, aliases=everything)

    def resolved(result):
        return sum(1 for row in result.rows if row["player_id"])

    assert resolved(default) == resolved(empty), (
        "the shipped file must not resolve a fixture id; this test would then prove nothing"
    )
    assert resolved(injected) == resolved(default) + 1


def test_the_shipped_alias_file_parses_and_every_entry_is_well_formed(repo_root):
    """A malformed review is worse than no review: it fails a capture, not a test."""
    aliases = load_alias_map(default_alias_path(root=repo_root))
    for (source_id, external_id), entry in aliases.entries.items():
        assert source_id == MFL_SOURCE_ID, f"unknown source {source_id!r}"
        assert external_id.isdigit(), f"{external_id!r} is not an MFL id"
        assert entry.player_id.startswith("gsis:"), (
            f"{external_id}: alias target {entry.player_id!r} is not a namespaced canonical id"
        )
        # Provenance is the whole justification for overriding nothing-resolved. An entry
        # without it cannot be audited later, which is when it will matter.
        assert entry.reviewed_by, f"{external_id}: no reviewer recorded"
        assert entry.reviewed_at, f"{external_id}: no review date recorded"
        assert entry.note, f"{external_id}: no reason recorded"
