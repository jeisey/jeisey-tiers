"""Roster allocation and realized-VORP tests.

`docs/TEST_STRATEGY.md` 2.7 asks for hand-worked league examples, and this is where the
project's scarcity model is actually decided: the replacement baseline is what turns raw
points into league-relative value, and getting it wrong shifts every tier boundary without
producing a single visible error.

The Phase-1 note that "the 16-player fixture produces identical replacement values across
every preset" is answered here rather than by enlarging that fixture: these tests build
purpose-made pools big enough that a 10-, 12- and 14-team league genuinely disagree, which
is the property the artifact fixture is too small to exercise.
"""

from __future__ import annotations

import pytest

from ffdraft.config import LeaguePreset, load_league_config
from ffdraft.labels.vorp import REPLACEMENT_UNAVAILABLE_FLAG
from ffdraft.simulation import PlayerPoints, allocate_starters, vorp_for_players

#: `LeaguePreset` bounds league size at 4-32 because the market-snapshot contract does; the
#: hand-worked examples therefore use the smallest legal league rather than the two-team
#: illustration in `docs/TEST_STRATEGY.md`, which is the same arithmetic one rank deeper.
MIN_LEGAL_TEAMS = 4


def preset(
    *,
    teams: int,
    starters: dict[str, int],
    preset_id: str = "test",
    flex: tuple[str, ...] = ("RB", "WR", "TE"),
) -> LeaguePreset:
    return LeaguePreset(
        preset_id=preset_id,
        teams=teams,
        starters=starters,
        flex_eligible=tuple(position for position in flex if position in starters),
        bench=0,
    )


def pool(position: str, points: list[float], *, prefix: str | None = None) -> list[PlayerPoints]:
    tag = prefix or position.lower()
    return [
        PlayerPoints(player_id=f"{tag}{index:03d}", position=position, points=value)
        for index, value in enumerate(points, start=1)
    ]


# --------------------------------------------------------------------------------------
# The worked example from docs/TEST_STRATEGY.md 2.7
# --------------------------------------------------------------------------------------


def test_the_documented_worked_example():
    """4 teams, 1 RB starter, no FLEX, points [100,90,80,70,60].

    Four starters consume the top four, so replacement is 60 and VORP is [40,30,20,10,0] -
    the same shape as the two-team illustration in `docs/TEST_STRATEGY.md` 2.7, at the
    smallest league size the configuration contract permits.
    """
    players = pool("RB", [100, 90, 80, 70, 60])
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"RB": 1}, flex=())
    allocation, vorp = vorp_for_players(players, league)
    assert allocation.replacement_points["RB"] == pytest.approx(60.0)
    assert [vorp[player.player_id] for player in players] == pytest.approx(
        [40.0, 30.0, 20.0, 10.0, 0.0],
    )


def test_flex_slots_are_a_global_competition_among_eligible_positions():
    """Four teams, one RB/WR/TE/FLEX slot each: sixteen starters from three pools.

    Worked by hand. Dedicated slots take the top four of each position, leaving
    RB [150, 90, 85, 80], WR [120, 100, 95, 90] and TE [60, 55, 50, 45]. The four FLEX slots
    then take the best four of *those* regardless of position - 150, 120, 100, 95 - which is
    one back and three receivers. Replacement is whoever is left at the front of each pool.
    """
    players = [
        *pool("RB", [200, 190, 180, 170, 150, 90, 85, 80]),
        *pool("WR", [195, 185, 175, 165, 120, 100, 95, 90]),
        *pool("TE", [160, 150, 140, 130, 60, 55, 50, 45]),
    ]
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"RB": 1, "WR": 1, "TE": 1, "FLEX": 1})
    allocation = allocate_starters(players, league)

    assert allocation.positional_starters["RB"] == ("rb001", "rb002", "rb003", "rb004")
    assert allocation.positional_starters["WR"] == ("wr001", "wr002", "wr003", "wr004")
    assert allocation.positional_starters["TE"] == ("te001", "te002", "te003", "te004")
    assert allocation.flex_starters == ("rb005", "wr005", "wr006", "wr007")
    assert allocation.fully_staffed

    assert allocation.replacement_points["RB"] == pytest.approx(90.0)
    assert allocation.replacement_points["WR"] == pytest.approx(90.0)
    assert allocation.replacement_points["TE"] == pytest.approx(60.0)
    assert allocation.replacement_player_id["TE"] == "te005"


def test_flex_competition_makes_a_position_scarcer_than_its_own_slots_imply():
    """Same pools, but with the FLEX slots removed.

    Without FLEX, tight end replacement is the fifth-best tight end (60). With FLEX, the
    receivers absorb three of the four flex slots, so receiver replacement drops from 120 to
    90 while tight end is untouched. That difference *is* positional scarcity, and it comes
    from roster shape alone - no market input anywhere.
    """
    players = [
        *pool("RB", [200, 190, 180, 170, 150, 90, 85, 80]),
        *pool("WR", [195, 185, 175, 165, 120, 100, 95, 90]),
        *pool("TE", [160, 150, 140, 130, 60, 55, 50, 45]),
    ]
    without_flex = allocate_starters(
        players,
        preset(teams=MIN_LEGAL_TEAMS, starters={"RB": 1, "WR": 1, "TE": 1}),
    )
    with_flex = allocate_starters(
        players,
        preset(teams=MIN_LEGAL_TEAMS, starters={"RB": 1, "WR": 1, "TE": 1, "FLEX": 1}),
    )
    assert without_flex.replacement_points["WR"] == pytest.approx(120.0)
    assert with_flex.replacement_points["WR"] == pytest.approx(90.0)
    assert without_flex.replacement_points["TE"] == with_flex.replacement_points["TE"]


def test_a_player_below_replacement_gets_negative_vorp():
    players = pool("WR", [200, 180, 160, 150, 100, 40])
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"WR": 1}, flex=())
    _, vorp = vorp_for_players(players, league)
    assert vorp["wr005"] == pytest.approx(0.0)
    assert vorp["wr006"] == pytest.approx(-60.0)


def test_ties_break_deterministically_on_player_id():
    players = [
        PlayerPoints("zzz", "RB", 100.0),
        PlayerPoints("aaa", "RB", 100.0),
        PlayerPoints("mmm", "RB", 100.0),
        PlayerPoints("bbb", "RB", 100.0),
        PlayerPoints("ccc", "RB", 100.0),
    ]
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"RB": 1}, flex=())
    first = allocate_starters(players, league)
    second = allocate_starters(list(reversed(players)), league)
    assert first.positional_starters["RB"] == ("aaa", "bbb", "ccc", "mmm")
    assert first.positional_starters == second.positional_starters
    assert first.replacement_player_id["RB"] == second.replacement_player_id["RB"] == "zzz"


def test_an_exhausted_position_has_no_replacement_and_null_vorp():
    players = pool("TE", [90, 80, 70, 60])
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"TE": 1}, flex=())
    allocation, vorp = vorp_for_players(players, league)
    assert allocation.replacement_points["TE"] is None
    assert allocation.replacement_player_id["TE"] is None
    assert vorp["te001"] is None
    assert allocation.fully_staffed is True


def test_an_undersized_pool_reports_the_slots_it_could_not_fill():
    players = pool("QB", [300])
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"QB": 1}, flex=())
    allocation = allocate_starters(players, league)
    assert allocation.unfilled_slots == {"QB": 3}
    assert allocation.fully_staffed is False


def test_a_position_absent_from_the_pool_is_reported_not_crashed():
    players = pool("RB", [100, 90, 80, 70, 60])
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"RB": 1, "TE": 1}, flex=())
    allocation = allocate_starters(players, league)
    assert allocation.unfilled_slots["TE"] == MIN_LEGAL_TEAMS
    assert "TE" not in allocation.replacement_points


def test_flex_shortage_is_reported_separately_from_positional_shortage():
    players = [*pool("RB", [100, 90, 80, 70]), *pool("WR", [95, 85, 75, 65])]
    league = preset(teams=MIN_LEGAL_TEAMS, starters={"RB": 1, "WR": 1, "FLEX": 1})
    allocation = allocate_starters(players, league)
    assert "RB" not in allocation.unfilled_slots
    assert allocation.unfilled_slots["FLEX"] == MIN_LEGAL_TEAMS


# --------------------------------------------------------------------------------------
# League size genuinely changes replacement value
# --------------------------------------------------------------------------------------


def _deep_pool() -> list[PlayerPoints]:
    """A pool deep enough that 10-, 12- and 14-team leagues reach different players.

    Points decline by a fixed step per rank, so the expected replacement value at each
    league size is arithmetic rather than a lookup: this is the numerical property the
    16-player Phase-1 artifact fixture cannot exercise.
    """
    return [
        *pool("QB", [400 - 5 * index for index in range(60)]),
        *pool("RB", [350 - 4 * index for index in range(90)]),
        *pool("WR", [340 - 3 * index for index in range(120)]),
        *pool("TE", [280 - 6 * index for index in range(60)]),
    ]


@pytest.mark.parametrize("preset_id", ["redraft-10", "redraft-12", "redraft-14"])
def test_launch_presets_allocate_the_expected_number_of_starters(repo_root, preset_id):
    league = load_league_config(repo_root / "config" / "league-defaults.yaml").preset(preset_id)
    allocation = allocate_starters(_deep_pool(), league)
    assert allocation.fully_staffed
    assert len(allocation.started_player_ids) == league.teams * league.starting_slots


def test_replacement_value_falls_as_the_league_grows(repo_root):
    league_config = load_league_config(repo_root / "config" / "league-defaults.yaml")
    players = _deep_pool()
    baselines = {
        preset_id: allocate_starters(players, league_config.preset(preset_id)).replacement_points
        for preset_id in ("redraft-10", "redraft-12", "redraft-14")
    }
    for position in ("QB", "RB", "WR", "TE"):
        ten = baselines["redraft-10"][position]
        twelve = baselines["redraft-12"][position]
        fourteen = baselines["redraft-14"][position]
        assert ten is not None and twelve is not None and fourteen is not None
        assert ten > twelve > fourteen, (
            f"{position}: a larger league must dig deeper into the pool, so its replacement "
            "baseline must be strictly lower"
        )


def test_quarterback_replacement_is_exactly_the_next_unstarted_passer(repo_root):
    """Hand-worked: one QB slot per team means the (teams+1)-th best QB is replacement."""
    league_config = load_league_config(repo_root / "config" / "league-defaults.yaml")
    players = _deep_pool()
    for preset_id, teams in (("redraft-10", 10), ("redraft-12", 12), ("redraft-14", 14)):
        allocation = allocate_starters(players, league_config.preset(preset_id))
        assert allocation.replacement_points["QB"] == pytest.approx(400 - 5 * teams)
        assert allocation.replacement_player_id["QB"] == f"qb{teams + 1:03d}"


def test_the_same_points_produce_different_vorp_in_different_leagues(repo_root):
    league_config = load_league_config(repo_root / "config" / "league-defaults.yaml")
    players = _deep_pool()
    subject = "qb001"
    values = {
        preset_id: vorp_for_players(players, league_config.preset(preset_id))[1][subject]
        for preset_id in ("redraft-10", "redraft-12", "redraft-14")
    }
    assert len(set(values.values())) == 3, values


# --------------------------------------------------------------------------------------
# Label table
# --------------------------------------------------------------------------------------


def test_build_vorp_labels_covers_every_preset_and_scoring_combination(repo_root):
    import polars as pl

    from ffdraft.labels import build_vorp_labels

    league_config = load_league_config(repo_root / "config" / "league-defaults.yaml")
    rows = []
    for scoring_preset in ("STD", "HALF", "PPR"):
        for index, player in enumerate(_deep_pool(), start=1):
            rows.append(
                {
                    "season": 2024,
                    "player_id": player.player_id,
                    "scoring_preset": scoring_preset,
                    "position": player.position,
                    "actual_fantasy_points": player.points + index * 0.0,
                },
            )
    labels = pl.DataFrame(rows)
    built = build_vorp_labels(labels, league_config)
    presets = sorted(league_config.presets)
    assert built.height == labels.height * len(presets)
    assert sorted(built.get_column("league_preset_id").unique().to_list()) == presets
    assert built.get_column("actual_vorp").null_count() == 0
    assert (
        built.height
        == built.select(
            "season",
            "player_id",
            "scoring_preset",
            "league_preset_id",
        ).n_unique()
    )


def test_a_pool_too_small_for_its_league_flags_the_missing_replacement(repo_root):
    import polars as pl

    from ffdraft.labels import build_vorp_labels

    league_config = load_league_config(repo_root / "config" / "league-defaults.yaml")
    labels = pl.DataFrame(
        [
            {
                "season": 2024,
                "player_id": f"te{index:03d}",
                "scoring_preset": "PPR",
                "position": "TE",
                "actual_fantasy_points": 100.0 - index,
            }
            for index in range(5)
        ],
    )
    built = build_vorp_labels(labels, league_config, preset_ids=["redraft-12"])
    assert built.get_column("actual_vorp").null_count() == built.height
    assert built.get_column("quality_flags").unique().to_list() == [REPLACEMENT_UNAVAILABLE_FLAG]
