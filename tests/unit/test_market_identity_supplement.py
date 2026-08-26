"""The canonical spine is the roster *plus* the players the roster file leaves out.

ADR-055. `load_rosters(season)` was the whole canonical player set, on the reasoning that a
current capture is asking "who is on a roster now". It does not answer that: on 2026-08-26
`load_rosters(2026)` omitted 101 skill-position players who were on NFL rosters — Stefon
Diggs (WAS), Keenan Allen (IND), Deebo Samuel Sr. (SF) among them — each priced by a real
market with 96 to 201 drafts behind the number.

A player the registry does not contain cannot be reached by *either* market bridge, because
both terminate at `registry.lookup`. So the effect was not a degraded join, it was an
invisible one: the price existed, the player existed, and the board could not use either.

These tests pin the two properties that make the supplement safe — it only ever *adds*, and
it does not add people who have left the league — plus the end-to-end case that motivated it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from ffdraft.contracts import MARKET_QUOTE_CONTRACT, EntityKind, ResolutionStatus
from ffdraft.identity import build_registry, resolve_market_quotes
from ffdraft.identity.resolver import PRIMARY_MARKET_BRIDGE
from ffdraft.market.identity import supplement_roster
from ffdraft.sources.nflverse import NflversePlayersAdapter, NflverseRosterAdapter

SEASON = 2026
STAMP = datetime(2026, 8, 26, tzinfo=UTC)


def _roster_frame(records):
    return NflverseRosterAdapter().normalize(records, season=SEASON, retrieved_at=STAMP).frame


def _players_frame(records):
    return NflversePlayersAdapter().normalize(records, season=SEASON, retrieved_at=STAMP).frame


#: On the roster file, and therefore visible today.
ON_ROSTER = {
    "season": SEASON,
    "gsis_id": "00-0000001",
    "full_name": "Terry Rostered",
    "position": "WR",
    "team": "WAS",
    "status": "ACT",
    "depth_chart_position": "WR",
    "espn_id": "4000001",
    "sleeper_id": "5000001",
    "pfr_id": "Rost0000",
    "sportradar_id": None,
    "yahoo_id": None,
    "birth_date": None,
    "years_exp": 5,
    "rookie_year": 2021,
}

#: The Stefon Diggs case: active this season, on a team, absent from the roster file.
MISSING_FROM_ROSTER = {
    "gsis_id": "00-0031588",
    "display_name": "Stefon Diggs",
    "position": "WR",
    "latest_team": "WAS",
    "status": "ACT",
    "last_season": SEASON,
    "espn_id": "2976212",
    "pfr_id": "DiggSt00",
    "rookie_season": 2015,
    "years_of_experience": 11,
}

#: Left the league. Adding him would expand the set with someone nobody can draft.
RETIRED = {
    "gsis_id": "00-0009999",
    "display_name": "Gone Retired",
    "position": "TE",
    "latest_team": "CHI",
    "status": "ACT",
    "last_season": SEASON - 3,
    "espn_id": "4009999",
    "pfr_id": None,
    "rookie_season": 2012,
    "years_of_experience": 12,
}


def test_the_adapter_keeps_only_players_whose_last_season_reaches_the_target():
    frame = _players_frame([MISSING_FROM_ROSTER, RETIRED])
    assert frame.get_column("gsis_id").to_list() == ["00-0031588"]


def test_the_supplement_adds_a_player_the_roster_omits():
    roster = _roster_frame([ON_ROSTER])
    players = _players_frame([MISSING_FROM_ROSTER])
    spine, check = supplement_roster(roster, players, season=SEASON)

    assert spine.height == 2
    assert set(spine.get_column("gsis_id").to_list()) == {"00-0000001", "00-0031588"}
    assert check is not None
    assert check.check_id == "identity.roster_supplemented"
    assert "1 player(s) added" in check.observed


def test_the_roster_wins_a_collision_because_its_record_is_richer():
    """The supplement adds players; it must never restate one, or a Sleeper id and a depth
    chart position would be silently replaced with the nulls this source cannot provide."""
    also_on_roster = {**MISSING_FROM_ROSTER, "gsis_id": ON_ROSTER["gsis_id"], "latest_team": "SF"}
    roster = _roster_frame([ON_ROSTER])
    spine, check = supplement_roster(roster, _players_frame([also_on_roster]), season=SEASON)

    assert spine.height == 1
    assert check is None
    row = spine.row(0, named=True)
    assert row["team"] == "WAS", "the roster's team must survive"
    assert row["sleeper_id"] == "5000001", "the roster's Sleeper id must survive"
    assert row["depth_chart_position"] == "WR"


def test_an_empty_supplement_is_a_no_op():
    roster = _roster_frame([ON_ROSTER])
    for empty in (None, pl.DataFrame()):
        spine, check = supplement_roster(roster, empty, season=SEASON)
        assert spine.height == roster.height
        assert check is None


def _quote(external_id: str) -> pl.DataFrame:
    return MARKET_QUOTE_CONTRACT.build(
        [
            {
                "source_id": "myfantasyleague_adp",
                "season": SEASON,
                "external_player_id": external_id,
                "average_pick": 115.33,
                "entity_kind": str(EntityKind.PLAYER),
                "scoring_preset": "HALF",
                "league_size": 10,
                "cohort_approximate": True,
                "source_format_detail": "IS_KEEPER=N",
                "retrieved_at_utc": None,
            },
        ],
    )


@pytest.mark.parametrize(
    ("supplemented", "expected"),
    [(False, ResolutionStatus.UNRESOLVED), (True, ResolutionStatus.RESOLVED_CROSSWALK)],
)
def test_a_priced_player_missing_from_the_roster_resolves_only_once_supplemented(
    supplemented,
    expected,
):
    """The whole failure in one test. MFL prices him and publishes his espn_id; nflverse's
    player master has him on a team. Only the roster file disagrees, and that used to decide."""
    roster = _roster_frame([ON_ROSTER])
    players = _players_frame([MISSING_FROM_ROSTER]) if supplemented else None
    spine, _ = supplement_roster(roster, players, season=SEASON)

    [outcome] = resolve_market_quotes(
        _quote("12186"),
        registry=build_registry(spine),
        # Exactly what MFL's own player directory publishes for him.
        espn_by_mfl_id={"12186": "2976212"},
        # The secondary bridge deliberately withheld: the point is that the *primary*,
        # nflverse-native bridge is sufficient once the registry knows the player.
        gsis_by_mfl_id={},
    )
    assert outcome.status is expected
    if supplemented:
        assert outcome.player_id == "gsis:00-0031588"
        assert PRIMARY_MARKET_BRIDGE in outcome.bridges_agreed
