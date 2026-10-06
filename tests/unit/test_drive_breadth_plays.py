"""Which plays are slots, whose opportunities they are, and what is never counted (ADR-103/104)."""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.validate import _breadth_problems
from ffdraft.signals.breadth import GameBreadth
from ffdraft.signals.drive_play import (
    DRIVE_PLAY_COLUMNS,
    Appearance,
    drive_plays,
    drive_share_change,
    game_breadths,
    usage_breadth_blocks,
)

QB, RB, RB2, WR, TE = "00-QB", "00-RB", "00-RB2", "00-WR", "00-TE"
POSITIONS = {
    (2024, QB): "QB",
    (2024, RB): "RB",
    (2024, RB2): "RB",
    (2024, WR): "WR",
    (2024, TE): "TE",
}


def _play(drive: int, **values: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "season": 2024,
        "week": 1,
        "season_type": "REG",
        "game_id": "2024_01_AAA_BBB",
        "posteam": "AAA",
        "fixed_drive": drive,
        "play_type": "pass",
        "rush_attempt": 0.0,
        "pass_attempt": 1.0,
        "sack": 0.0,
        "qb_kneel": 0.0,
        "qb_spike": 0.0,
        "two_point_attempt": 0.0,
        "aborted_play": 0.0,
        "special_teams_play": 0.0,
        "play_deleted": 0.0,
        "rusher_player_id": None,
        "receiver_player_id": None,
        "yardline_100": 50.0,
        "qb_scramble": 0.0,
    }
    base.update(values)
    return base


def _run(drive: int, rusher: str, **values: Any) -> dict[str, Any]:
    return _play(
        drive,
        play_type="run",
        rush_attempt=1.0,
        pass_attempt=0.0,
        rusher_player_id=rusher,
        **values,
    )


def _target(drive: int, receiver: str, **values: Any) -> dict[str, Any]:
    return _play(drive, receiver_player_id=receiver, **values)


EXCLUDED = [
    _play(1, play_type="qb_kneel", qb_kneel=1.0),
    _play(1, play_type="qb_spike", qb_spike=1.0),
    _target(1, WR, two_point_attempt=1.0),
    _run(1, QB, aborted_play=1.0),
    _run(1, RB, special_teams_play=1.0),
    _target(1, WR, play_deleted=1.0),
    _play(1, play_type="no_play"),
    _target(1, WR, season_type="POST"),
]


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return drive_plays(pl.DataFrame(rows))


def test_clock_plays_two_points_aborts_special_teams_and_no_plays_are_not_slots() -> None:
    assert _frame(EXCLUDED).height == 0


def test_a_sack_is_a_qb_slot_and_never_a_target_and_a_scramble_is_a_run() -> None:
    plays = _frame(
        [
            _play(1, sack=1.0),
            _run(1, QB),  # a designed run by the quarterback
            _play(2),  # thrown away: no identified receiver
            _target(2, WR, lateral_reception=1.0),  # lateral: the original target keeps it
            _run(3, QB, qb_scramble=1.0),  # a scramble: a run, and a slot, but not designed
        ],
    )
    assert plays.get_column("kind").to_list() == ["other", "rush", "other", "target", "rush"]
    assert plays.get_column("scramble").to_list() == [False, False, False, False, True]
    games, _ = game_breadths(plays, [Appearance(2024, 1, QB, "AAA", "QB")], POSITIONS)
    (qb,) = games[f"gsis:{QB}"]
    # ADR-104: five slots on three drives; his one designed run is his only opportunity.
    assert (qb.eligible_slots, qb.eligible_drives, qb.opportunities) == (5, 3, 1)
    assert qb.reached_drives == 1
    games, _ = game_breadths(plays, [Appearance(2024, 1, WR, "AAA", "WR")], POSITIONS)
    (wr,) = games[f"gsis:{WR}"]
    assert (wr.eligible_slots, wr.eligible_drives, wr.opportunities) == (1, 1, 1)


def test_each_position_has_its_own_slots() -> None:
    plays = _frame(
        [
            _run(1, RB),
            _target(1, RB2),
            _target(1, WR),
            _run(2, RB2),
            _target(2, TE, yardline_100=15.0),  # red zone: not an open-field slot
            _target(3, TE, yardline_100=40.0),
            _target(3, WR, yardline_100=8.0),
        ],
    )
    appearances = [
        Appearance(2024, 1, pid, "AAA", POSITIONS[(2024, pid)]) for pid in (QB, RB, WR, TE)
    ]
    games, _ = game_breadths(plays, appearances, POSITIONS)
    rb = games[f"gsis:{RB}"][0]
    assert (rb.eligible_slots, rb.eligible_drives, rb.opportunities) == (3, 2, 1)
    wr = games[f"gsis:{WR}"][0]
    assert (wr.eligible_slots, wr.eligible_drives, wr.opportunities) == (5, 3, 2)
    te = games[f"gsis:{TE}"][0]
    # Open-field targets: two on drive 1 (RB2, WR) and his own on drive 3; drive 2 and the
    # red-zone target on drive 3 are not slots.
    assert (te.eligible_slots, te.eligible_drives, te.opportunities) == (3, 2, 1)
    assert te.reached_drives == 1


def test_an_unplaced_player_is_never_a_running_backs_slot() -> None:
    plays = _frame([_run(1, "00-UNKNOWN"), _run(1, RB)])
    games, diagnostics = game_breadths(plays, [Appearance(2024, 1, RB, "AAA", "RB")], POSITIONS)
    assert games[f"gsis:{RB}"][0].eligible_slots == 1
    assert diagnostics["rush_or_target_without_verified_position"] == 1


def test_a_zero_opportunity_appearance_counts_every_team_drive() -> None:
    plays = _frame([_target(1, WR), _target(2, WR), _target(3, WR)])
    games, _ = game_breadths(plays, [Appearance(2024, 1, TE, "AAA", "TE")], POSITIONS)
    (te,) = games[f"gsis:{TE}"]
    assert (te.eligible_drives, te.opportunities, te.reached_drives, te.expected_drives) == (
        3,
        0,
        0,
        0.0,
    )


def test_an_appearance_without_play_by_play_is_skipped_not_filled() -> None:
    plays = _frame([_target(1, WR)])
    games, diagnostics = game_breadths(plays, [Appearance(2024, 2, WR, "AAA", "WR")], POSITIONS)
    assert games == {} and diagnostics["appearances_without_play_by_play"] == 1


def test_a_renamed_column_is_refused() -> None:
    frame = pl.DataFrame([_target(1, WR)]).drop("fixed_drive")
    with pytest.raises(ValueError, match="fixed_drive"):
        drive_plays(frame)
    assert "fixed_drive" in DRIVE_PLAY_COLUMNS


def _usage(weeks: list[tuple[int, str]]) -> dict[str, Any]:
    return {
        "player_id": f"gsis:{WR}",
        "position": "WR",
        "weeks": [
            {"week": week, "status": status, "team": "AAA" if status == "played" else None}
            for week, status in weeks
        ],
    }


def test_published_blocks_ignore_byes_and_every_week_after_the_cutoff() -> None:
    rows = []
    for week in (1, 2, 4, 5):
        for drive in range(1, 9):
            rows.append(_target(drive, WR, week=week))
            rows.append(_target(drive, "00-OTHER", week=week))
    plays = _frame(rows)
    record = _usage([(1, "played"), (2, "played"), (3, "bye"), (4, "played"), (5, "played")])
    blocks, _ = usage_breadth_blocks(
        [record], plays, POSITIONS | {(2024, "00-OTHER"): "WR"}, season=2024, through_week=4
    )
    block = blocks[f"gsis:{WR}"]
    assert (block["appearances"], block["first_week"], block["last_week"]) == (3, 1, 4)
    assert block["eligible_drives"] == 24 and block["opportunities"] == 24
    assert block["displayable"] and block["metric"] == "targets"
    assert block["compares_with_random"] is True
    # ADR-104's rail: one entry per played game with play-by-play, none for the bye or week 5.
    assert [week["week"] for week in block["weeks"]] == [1, 2, 4]
    assert all(week["drive_share"] == 1.0 for week in block["weeks"])
    assert block["change"] == {
        "latest_week": 4,
        "latest": 1.0,
        "earlier": 1.0,
        "earlier_games": 2,
        "change": 0.0,
    }
    assert _breadth_problems([{**record, "drive_breadth": block}]) == []


def _game(week: int, drives: int, reached: int, expected: float = 0.0) -> GameBreadth:
    return GameBreadth(2024, week, drives, drives * 3, reached, reached, expected)


def test_the_drive_share_change_is_role_change_v1_pooled() -> None:
    games = [_game(1, 10, 5), _game(2, 6, 6), _game(4, 8, 2)]
    change = drive_share_change(games, [1, 2, 4])
    # Earlier pooled: 11 of 16 drives = 0.6875 -> 0.688; latest 2 of 8 = 0.25.
    assert change == {
        "latest_week": 4,
        "latest": 0.25,
        "earlier": 0.688,
        "earlier_games": 2,
        "change": -0.438,
    }
    # One game: a reading, not a trend.
    assert drive_share_change([_game(1, 10, 5)], [1]) == {
        "latest_week": 1,
        "latest": 0.5,
        "earlier": None,
        "earlier_games": 0,
        "change": None,
    }


def test_a_latest_game_without_play_by_play_is_no_change_never_an_older_game() -> None:
    # He played week 5; its play-by-play is not posted. The latest never moves back to week 4.
    assert drive_share_change([_game(1, 10, 5), _game(4, 8, 2)], [1, 4, 5]) is None
    assert drive_share_change([], []) is None


def test_the_validator_refuses_a_gap_that_is_not_its_own_arithmetic() -> None:
    record = {
        "player_id": "p",
        "weeks": [{"week": week, "status": "played"} for week in (1, 2, 3, 4)],
    }
    block = {
        "method_version": "drive_breadth_v2",
        "metric": "targets",
        "window_rule": 4,
        "appearances": 4,
        "first_week": 1,
        "last_week": 4,
        "eligible_drives": 40,
        "reached_drives": 30,
        "expected_drives": 25.0,
        "opportunities": 36,
        "breadth_gap_pp": 12.5,
        "displayable": True,
        "withheld_reason": None,
        "compares_with_random": True,
        "weeks": [
            {
                "week": week,
                "eligible_drives": 10,
                "reached_drives": 9 if week == 4 else 6,
                "drive_share": 0.9 if week == 4 else 0.6,
                "expected_share": 0.625,
            }
            for week in (1, 2, 3, 4)
        ],
        "change": {
            "latest_week": 4,
            "latest": 0.9,
            "earlier": 0.6,
            "earlier_games": 3,
            "change": 0.3,
        },
    }
    assert _breadth_problems([{**record, "drive_breadth": block}]) == []
    bad_week = {**block["weeks"][0], "drive_share": 0.7}
    for patch in (
        {"breadth_gap_pp": 0.0},
        {"displayable": False, "withheld_reason": "too_few_opportunities"},
        {"reached_drives": 41},
        {"weeks": [bad_week, *block["weeks"][1:]]},
        {"weeks": [*block["weeks"], {**block["weeks"][0], "week": 5}]},
        {"change": {**block["change"], "change": 0.2}},
        {"change": {**block["change"], "latest": 0.8, "change": 0.2}},
        {"compares_with_random": False},
        {"metric": "designed_runs"},
    ):
        assert _breadth_problems([{**record, "drive_breadth": {**block, **patch}}]), patch


def test_every_schema_pins_the_method_the_build_writes() -> None:
    # The real build is the first to write the metadata block; a schema left on an older
    # method would refuse it there and nowhere earlier (found on 2026-10-06, ADR-104).
    import json
    from pathlib import Path

    from ffdraft.signals.breadth import BREADTH_METHOD_VERSION

    root = Path(__file__).resolve().parents[2] / "schemas"
    usage = json.loads((root / "player_usage.schema.json").read_text())
    metadata = json.loads((root / "ros_build_metadata.schema.json").read_text())
    usage_pin = usage["properties"]["drive_breadth"]["properties"]["method_version"]["const"]
    metadata_pin = metadata["properties"]["signals"]["properties"]["drive_breadth"]["properties"][
        "method_version"
    ]["const"]
    assert usage_pin == metadata_pin == BREADTH_METHOD_VERSION
