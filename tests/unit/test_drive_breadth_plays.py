"""Which plays are slots, whose opportunities they are, and what is never counted (ADR-103)."""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.validate import _breadth_problems
from ffdraft.signals.drive_play import (
    DRIVE_PLAY_COLUMNS,
    Appearance,
    drive_plays,
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
            _run(1, QB),  # a scramble: a run by the quarterback
            _play(2),  # thrown away: no identified receiver
            _target(2, WR, lateral_reception=1.0),  # lateral: the original target keeps it
        ],
    )
    assert plays.get_column("kind").to_list() == ["other", "rush", "other", "target"]
    games, _ = game_breadths(plays, [Appearance(2024, 1, QB, "AAA", "QB")], POSITIONS)
    (qb,) = games[f"gsis:{QB}"]
    assert (qb.eligible_slots, qb.eligible_drives, qb.opportunities) == (4, 2, 1)
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
    assert _breadth_problems([{"player_id": record["player_id"], "drive_breadth": block}]) == []


def test_the_validator_refuses_a_gap_that_is_not_its_own_arithmetic() -> None:
    block = {
        "method_version": "drive_breadth_v1",
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
    }
    assert _breadth_problems([{"player_id": "p", "drive_breadth": block}]) == []
    for patch in (
        {"breadth_gap_pp": 0.0},
        {"displayable": False, "withheld_reason": "too_few_opportunities"},
        {"reached_drives": 41},
    ):
        assert _breadth_problems([{"player_id": "p", "drive_breadth": {**block, **patch}}])
