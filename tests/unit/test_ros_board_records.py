"""The rest-of-season board's records, and ADR-076's disclosure contract on them.

Driven from a synthetic prediction frame with no source, no model file and no network, which
is the same split `build_board_records` uses for the draft board: the whole value chain —
sampling, in-season allocation, ranking, segmentation and record shape — is exercised without
anything that could be slow or absent.

The disclosure clauses are asserted as *data* properties rather than as rendering, because
that is what makes them enforceable: the flag has to mean exactly what ADR-076 defines, the
observable number has to travel beside it, and the sentences have to be on the artifact so a
renderer cannot publish the flag without them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import polars as pl
import pytest

from ffdraft.config import load_app_config
from ffdraft.pipeline.ros import (
    LONG_ABSENCE_MIN_CONSECUTIVE_WEEKS,
    ROS_LIMITATIONS,
    build_ros_board_records,
)
from ffdraft.quality import QualityGate
from ffdraft.ros.cutoff import RosCutoff
from ffdraft.ros.frozen import ROS_BUILD_CONFIG
from ffdraft.simulation.sampler import DomainBounds

_PRESETS = ("PPR",)
_LEAGUES = ("redraft-12",)


class _StubModel:
    """The narrow surface `build_ros_board_records` actually uses from a fitted model."""

    class _Spec:
        model_version = "intrinsic-ros-v1"

    spec = _Spec()

    def point_bounds(self) -> dict[str, dict[str, DomainBounds]]:
        bounds = DomainBounds(-20.0, 400.0)
        return {"PPR": dict.fromkeys(("QB", "RB", "WR", "TE"), bounds)}


def _predictions(players: int = 260) -> pl.DataFrame:
    rng = np.random.default_rng(7)
    positions = ["QB", "RB", "WR", "TE"]
    rows: list[dict[str, Any]] = []
    for index in range(players):
        centre = 140.0 - index * 2.5
        rows.append(
            {
                "player_id": f"gsis:00-{index:07d}",
                "through_week": 8,
                "position": positions[index % 4],
                "scoring_preset": "PPR",
                "q10": centre - 40 + float(rng.normal(0, 1)),
                "q25": centre - 20,
                "q50": centre,
                "q75": centre + 20,
                "q90": centre + 40,
                "expected_remaining_games": 8.0 - (index % 4),
            },
        )
    return pl.DataFrame(rows)


def _context(players: int = 260) -> pl.DataFrame:
    """One row per player and preset. Every third player is three weeks absent."""
    rows: list[dict[str, Any]] = []
    for index in range(players):
        absent = index % 3 == 2
        rows.append(
            {
                "player_id": f"gsis:00-{index:07d}",
                "scoring_preset": "PPR",
                "display_name": f"Player {index:02d}",
                "position": ["QB", "RB", "WR", "TE"][index % 4],
                "team": "SEA",
                "games_to_date": 8.0 - (3.0 if absent else 0.0),
                "points_to_date": 90.0 - index,
                "ppg_to_date": 11.0,
                "weeks_since_last_game": 3.0 if absent else 0.0,
                "consecutive_weeks_missed": 3.0 if absent else 0.0,
                "has_played_this_season": index != 5,
                "in_preseason_universe": index != 7,
                "remaining_horizon_weeks": 9,
                "team_remaining_scheduled_games": 8.0,
                "snap_pct_last3": 0.6,
                "target_share_last3": 0.2,
                "rookie_flag": index == 9,
            },
        )
    return pl.DataFrame(rows)


Built = tuple[dict[str, list[dict[str, Any]]], dict[str, Any], QualityGate]


def _build(players: int = 260, **overrides: Any) -> Built:
    gate = QualityGate()
    records, diagnostics, full_board = build_ros_board_records(
        _predictions(players),
        _context(players),
        settings=load_app_config(),
        # A small draw count: the arithmetic being tested is the record shape and the
        # disclosure contract, not the Monte Carlo, and the production count is asserted
        # against the frozen config elsewhere.
        config=replace(ROS_BUILD_CONFIG, draws=200),
        model=_StubModel(),  # type: ignore[arg-type]
        cutoff=RosCutoff(season=2026, through_week=8),
        build_id="test-build",
        league_preset_ids=_LEAGUES,
        scoring_presets=_PRESETS,
        preseason_ranks=overrides.get("preseason_ranks", {}),
        status_by_player=overrides.get("status_by_player", {}),
        gate=gate,
    )
    return records, {"diagnostics": diagnostics, "full_board": full_board}, gate


def test_the_board_publishes_rest_of_season_names_and_never_a_preseason_one() -> None:
    records, _, _ = _build()
    row = records["ros_tiers"][0]
    assert "fair_rank" not in row
    assert "expected_vorp" not in row
    assert row["ros_fair_rank"] == 1
    assert row["through_week"] == 8
    assert row["season"] == 2026


def test_the_long_absence_flag_means_exactly_what_adr_076_defines() -> None:
    records, _, _ = _build()
    for row in records["ros_tiers"]:
        expected = (
            bool(row["has_played_this_season"])
            and row["consecutive_weeks_missed"] >= LONG_ABSENCE_MIN_CONSECUTIVE_WEEKS
        )
        assert row["long_absence"] is expected
        # Clause 2: the observable number travels beside the flag, so it is checkable.
        assert "weeks_since_last_game" in row
        if row["long_absence"]:
            assert "long_absence" in row["quality_flags"]


def test_a_player_with_no_appearances_is_never_flagged_as_a_long_absence() -> None:
    """The flag is about a player who HAS played and then stopped. Not one who never has."""
    records, _, _ = _build()
    never = [row for row in records["ros_tiers"] if not row["has_played_this_season"]]
    assert never, "the fixture must contain one"
    for row in never:
        assert row["long_absence"] is False
        assert "no_appearances_this_season" in row["quality_flags"]


def test_current_status_is_annotation_joined_after_every_value_exists() -> None:
    records, _, _ = _build(status_by_player={"gsis:00-0000000": "RES"})
    by_player = {row["player_id"]: row for row in records["ros_tiers"]}
    assert by_player["gsis:00-0000000"]["current_status"] == "RES"
    assert by_player["gsis:00-0000001"]["current_status"] is None
    # Its presence changes no value: the same row's numbers are what the simulation produced.
    plain, _, _ = _build()
    plain_row = next(r for r in plain["ros_tiers"] if r["player_id"] == "gsis:00-0000000")
    assert plain_row["ros_expected_vorp"] == by_player["gsis:00-0000000"]["ros_expected_vorp"]
    assert plain_row["ros_fair_rank"] == by_player["gsis:00-0000000"]["ros_fair_rank"]


def test_the_preseason_delta_is_published_when_a_draft_board_was_supplied() -> None:
    records, _, _ = _build(
        preseason_ranks={("redraft-12", "PPR", "gsis:00-0000000"): 12},
    )
    row = next(r for r in records["ros_tiers"] if r["player_id"] == "gsis:00-0000000")
    assert row["preseason_fair_rank"] == 12
    # Positive means the model likes him more now than it did in August.
    assert row["fair_rank_change"] == 12 - row["ros_fair_rank"]

    without, _, _ = _build()
    absent = next(r for r in without["ros_tiers"] if r["player_id"] == "gsis:00-0000000")
    assert absent["preseason_fair_rank"] is None
    assert absent["fair_rank_change"] is None


def test_tiers_are_published_with_their_failed_stability_gate_stated() -> None:
    _, _, gate = _build()
    ids = [check.check_id for check in gate.warnings]
    assert "ros.tier_stability" in ids
    assert "ros.simulation_convergence" in ids
    stability = next(c for c in gate.warnings if c.check_id == "ros.tier_stability")
    assert "band" in stability.message
    # Warnings, not failures: the board ships with the limitation stated (ADR-074).
    assert gate.passed


def test_the_published_limitations_name_the_measured_inherited_weaknesses() -> None:
    joined = " ".join(ROS_LIMITATIONS).lower()
    assert "high-draft-capital rookies" in joined
    assert "long absence" in joined
    assert "sealed" in joined
    assert "band, not a line" in joined
    assert "no injury feature" in joined


def test_the_full_board_is_deeper_than_the_published_prefix() -> None:
    """The surface rule cannot rescue a player from a board he was already cut from."""
    records, extra, _ = _build()
    published = {row["player_id"] for row in records["ros_tiers"]}
    board = {row["player_id"] for row in extra["full_board"]}
    assert published <= board


def test_two_identical_builds_produce_identical_records() -> None:
    first, _, _ = _build()
    second, _, _ = _build()
    assert first["ros_tiers"] == second["ros_tiers"]


def test_a_pool_too_small_to_have_a_replacement_withholds_rather_than_publishing_nan() -> None:
    """The draw loop records "no baseline in this draw" as NaN, which is not valid JSON.

    A pool smaller than a league's roster slots consumes every player, so there is nobody
    left to be the replacement. Those rows have no league-relative value to publish, and
    withholding them is the correct answer — publishing `NaN` would break the browser, and
    publishing a zero would invent a number nobody measured.
    """
    records, _, gate = _build(players=8)
    assert records["ros_tiers"] == []
    withheld = [c for c in gate.warnings if c.check_id == "ros.unvalued_players_withheld"]
    assert withheld
    assert "no replacement baseline" in withheld[0].message


@pytest.mark.parametrize("week", [0, 17])
def test_the_cutoff_rule_refuses_a_snapshot_it_cannot_model(week: int) -> None:
    with pytest.raises(ValueError):
        RosCutoff(season=2026, through_week=week)


def test_the_frozen_build_config_is_the_measured_one() -> None:
    """These are outcomes of Phase 11 studies, not tuning knobs (ADR-071, ADR-074)."""
    assert ROS_BUILD_CONFIG.draws == 10_000
    assert ROS_BUILD_CONFIG.replacement_rule == "rostered_depth"
    assert ROS_BUILD_CONFIG.tier_penalty == 3.0
    assert ROS_BUILD_CONFIG.convergence_verdict == "fail"
    assert ROS_BUILD_CONFIG.tier_stability_verdict == "fail"
    payload = ROS_BUILD_CONFIG.to_dict()
    assert "declared fallback" in payload["draws_status"]
    assert "nobody rosters" in payload["replacement_rule_description"]


def test_the_build_never_reads_a_market_or_behaviour_field() -> None:
    """The firewall, from the intrinsic side: no published ROS field names a market signal."""
    records, _, _ = _build()
    forbidden = ("adp", "ecr", "market", "add_count", "drop_count", "consensus", "rank_gap")
    for row in records["ros_tiers"]:
        for key in row:
            assert not any(token in key for token in forbidden), key
