"""The Opportunity Board: behaviour decides visibility, and never a value.

That sentence is Phase 12's central claim, so it is tested from both directions: the rows the
board produces must copy their intrinsic columns rather than compute them, and the behaviour
feed's absence must cost a column rather than a board.

The Sleeper retention half is tested here too, because what makes an add count interpretable
a month later is entirely in the manifest: the window is the one *requested*, and the source
publishes no observation time of its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ffdraft.behavior.capture import (
    BEHAVIOR_PREFIX,
    BehaviorCapture,
    capture_behavior,
    read_behavior_capture,
    verify_behavior_store,
    write_behavior_capture,
)
from ffdraft.contracts.enums import BehaviorType
from ffdraft.identity.registry import build_registry
from ffdraft.opportunity.board import (
    BEHAVIOR_MAX_AGE_HOURS,
    SURFACE_ADD_COUNT_MINIMUM,
    build_opportunity_records,
    resolve_behavior_signals,
)
from ffdraft.quality import QualityGate
from ffdraft.retention import SnapshotStore

_NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)


def _roster() -> pl.DataFrame:
    """Two canonical players with Sleeper ids, and one without."""
    return pl.DataFrame(
        [
            {
                "season": 2026,
                "gsis_id": "00-0000001",
                "display_name": "Alpha Back",
                "position": "RB",
                "team": "SEA",
                "status": "ACT",
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
                "display_name": "Charlie Tight",
                "position": "TE",
                "team": "KC",
                "status": "ACT",
                "sleeper_id": None,
            },
        ],
        schema_overrides={"season": pl.Int32, "sleeper_id": pl.String},
    )


def _capture(
    *,
    adds: dict[str, int],
    drops: dict[str, int],
    at: datetime = _NOW,
) -> BehaviorCapture:
    return capture_behavior(
        season=2026,
        as_of=at,
        payloads={
            "add": [{"player_id": key, "count": value} for key, value in adds.items()],
            "drop": [{"player_id": key, "count": value} for key, value in drops.items()],
        },
    )


def _ros_records() -> list[dict[str, Any]]:
    return [
        {
            "league_preset_id": "redraft-12",
            "scoring_preset": "PPR",
            "player_id": "gsis:00-0000001",
            "display_name": "Alpha Back",
            "team": "SEA",
            "position": "RB",
            "ros_fair_rank": 1,
            "ros_position_rank": 1,
            "ros_expected_vorp": 41.25,
            "ros_expected_points": 120.5,
            "ros_expected_games": 8.1,
            "ros_uncertainty": 12.5,
            "ros_tier": 0,
            "long_absence": False,
            "weeks_since_last_game": 0.0,
            "current_status": "ACT",
            "quality_flags": [],
        },
        {
            "league_preset_id": "redraft-12",
            "scoring_preset": "PPR",
            "player_id": "gsis:00-0000002",
            "display_name": "Bravo Wideout",
            "team": "DAL",
            "position": "WR",
            "ros_fair_rank": 2,
            "ros_position_rank": 1,
            "ros_expected_vorp": 30.0,
            "ros_expected_points": 100.0,
            "ros_expected_games": 7.5,
            "ros_uncertainty": 11.0,
            "ros_tier": 0,
            "long_absence": True,
            "weeks_since_last_game": 3.0,
            "current_status": "RES",
            "quality_flags": ["long_absence"],
        },
    ]


def _full_board(depth_extra: int = 0) -> list[dict[str, Any]]:
    board = [
        {
            "player_id": row["player_id"],
            "fair_rank": row["ros_fair_rank"],
            "display_name": row["display_name"],
            "position": row["position"],
            "team": row["team"],
            "scoring_preset": "PPR",
            "league_preset_id": "redraft-12",
        }
        for row in _ros_records()
    ]
    for index in range(depth_extra):
        board.append(
            {
                "player_id": f"gsis:00-000000{3 + index}",
                "fair_rank": 10 + index,
                "display_name": f"Deep Player {index}",
                "position": "TE",
                "team": "KC",
                "scoring_preset": "PPR",
                "league_preset_id": "redraft-12",
            },
        )
    return board


# -- retention ---------------------------------------------------------------------------


def test_a_capture_records_the_request_rather_than_claiming_a_window() -> None:
    capture = _capture(adds={"1001": 900}, drops={"1002": 40})
    manifest = capture.manifest(content_digest="deadbeef")
    assert manifest["lookback_hours"] == 24
    assert manifest["request_limit"] == 100
    assert any("window REQUESTED" in note for note in manifest["notes"])
    assert any("never a price" in note.lower() for note in manifest["notes"])
    assert capture.counts(BehaviorType.ADD) == {"1001": 900}
    assert capture.counts(BehaviorType.DROP) == {"1002": 40}


def test_a_half_missing_snapshot_is_refused_rather_than_retained(tmp_path: Path) -> None:
    """A drop count is only interpretable against the add count from the same moment."""
    capture = _capture(adds={"1001": 900}, drops={})
    assert not capture.is_complete
    with pytest.raises(ValueError, match="missing one of its two feeds"):
        write_behavior_capture(capture, store=SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX))


def test_a_retained_capture_round_trips_and_is_re_hashed(tmp_path: Path) -> None:
    store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    written = write_behavior_capture(_capture(adds={"1001": 900}, drops={"1002": 40}), store=store)
    assert len(written) == 2

    loaded = read_behavior_capture(store, season=2026)
    assert loaded is not None
    assert loaded.counts(BehaviorType.ADD) == {"1001": 900}
    assert loaded.lookback_hours == 24

    snapshots, files, problems = verify_behavior_store(store, season=2026)
    assert (snapshots, files, problems) == (1, 1, ())


def test_feed_ranks_order_the_feed_and_nothing_else() -> None:
    capture = _capture(adds={"1001": 10, "1002": 900, "1003": 500}, drops={"1001": 1})
    ranks = capture.ranks(BehaviorType.ADD)
    assert ranks == {"1002": 1, "1003": 2, "1001": 3}


# -- resolution ---------------------------------------------------------------------------


def test_signals_join_nflverse_first_and_count_what_they_cannot_resolve() -> None:
    registry = build_registry(_roster())
    signals = resolve_behavior_signals(
        _capture(adds={"1001": 900, "9999": 50}, drops={"1002": 40}),
        registry=registry,
        as_of=_NOW,
    )
    assert signals.available
    assert signals.add_counts == {"gsis:00-0000001": 900}
    assert signals.drop_counts == {"gsis:00-0000002": 40}
    # The unresolvable feed row is counted, never guessed at.
    assert signals.unresolved_rows == 1


def test_a_stale_capture_degrades_rather_than_being_presented_as_current() -> None:
    registry = build_registry(_roster())
    stale = _capture(
        adds={"1001": 900},
        drops={"1002": 40},
        at=_NOW - timedelta(hours=BEHAVIOR_MAX_AGE_HOURS + 1),
    )
    signals = resolve_behavior_signals(stale, registry=registry, as_of=_NOW)
    assert not signals.available
    assert signals.degraded_reason is not None
    assert "freshness window" in signals.degraded_reason
    assert [check.check_id for check in signals.checks()] == ["opportunity.behavior_unavailable"]
    assert not signals.checks()[0].blocking


def test_no_capture_at_all_is_a_warning_and_not_a_failure() -> None:
    signals = resolve_behavior_signals(None, registry=None, as_of=_NOW)
    assert not signals.available
    assert signals.to_dict()["degraded_reason"] == "no retained behaviour capture"


# -- the board -----------------------------------------------------------------------------


def test_every_intrinsic_column_is_copied_rather_than_recomputed() -> None:
    registry = build_registry(_roster())
    signals = resolve_behavior_signals(
        _capture(adds={"1001": 900}, drops={"1002": 40}),
        registry=registry,
        as_of=_NOW,
    )
    gate = QualityGate()
    records, universes, diagnostics = build_opportunity_records(
        ros_records=_ros_records(),
        full_board=_full_board(),
        context={},
        signals=signals,
        build_id="test",
        season=2026,
        through_week=8,
        gate=gate,
    )
    published = {row["player_id"]: row for row in _ros_records()}
    assert records
    for row in records:
        source = published[row["player_id"]]
        for field in ("ros_fair_rank", "ros_expected_vorp", "ros_uncertainty", "ros_tier"):
            assert row[field] == source[field]
    assert diagnostics["rows"] == len(records)
    assert len(universes) == 1


def test_behaviour_absence_empties_a_column_and_leaves_every_value_alone() -> None:
    gate = QualityGate()
    signals = resolve_behavior_signals(None, registry=None, as_of=_NOW)
    records, _, _ = build_opportunity_records(
        ros_records=_ros_records(),
        full_board=_full_board(),
        context={},
        signals=signals,
        build_id="test",
        season=2026,
        through_week=8,
        gate=gate,
    )
    for row in records:
        assert row["behavior_available"] is False
        # Null, not zero: a zero would claim nobody added him, which is a different fact.
        assert row["add_count"] is None
        assert row["net_add_count"] is None
    assert records[0]["ros_expected_vorp"] == _ros_records()[0]["ros_expected_vorp"]


def test_a_trending_player_beyond_the_depth_is_surfaced_without_a_tier() -> None:
    """Roadmap 12.3's motivating case: a formerly obscure player becomes relevant."""
    roster = _roster().with_columns(
        pl.when(pl.col("gsis_id") == "00-0000003")
        .then(pl.lit("1003"))
        .otherwise(pl.col("sleeper_id"))
        .alias("sleeper_id"),
    )
    registry = build_registry(roster)
    signals = resolve_behavior_signals(
        _capture(
            adds={"1001": 10, "1003": SURFACE_ADD_COUNT_MINIMUM + 500},
            drops={"1002": 5},
        ),
        registry=registry,
        as_of=_NOW,
    )
    gate = QualityGate()
    records, universes, diagnostics = build_opportunity_records(
        ros_records=_ros_records(),
        full_board=_full_board(depth_extra=1),
        context={},
        signals=signals,
        build_id="test",
        season=2026,
        through_week=8,
        gate=gate,
        tier_depth=2,
    )
    surfaced = [row for row in records if row["outside_tier_board"]]
    assert len(surfaced) == 1
    assert surfaced[0]["player_id"] == "gsis:00-0000003"
    # He carries the fair rank the model gave him and no tier at all.
    assert surfaced[0]["ros_fair_rank"] == 10
    assert surfaced[0]["ros_tier"] is None
    assert "sleeper_trending_add" in surfaced[0]["surface_reasons"]
    assert diagnostics["surfaced_beyond_depth"] == 1
    # The behaviour population is never a coverage requirement: a feed that trends a player
    # the model cannot value must not fail a production build (ADR-054's denominator lesson).
    assert all(not universe.missing for universe in universes)


def test_a_role_promotion_surfaces_a_player_the_feed_has_not_noticed() -> None:
    signals = resolve_behavior_signals(None, registry=None, as_of=_NOW)
    gate = QualityGate()
    records, _, _ = build_opportunity_records(
        ros_records=_ros_records(),
        full_board=_full_board(depth_extra=1),
        context={"gsis:00-0000003": {"snap_pct_last3": 0.78}},
        signals=signals,
        build_id="test",
        season=2026,
        through_week=8,
        gate=gate,
        tier_depth=2,
    )
    surfaced = [row for row in records if row["outside_tier_board"]]
    assert len(surfaced) == 1
    assert surfaced[0]["surface_reasons"] == ["current_depth_promotion"]
    assert surfaced[0]["snap_share_last3"] == 0.78


def test_net_adds_are_the_only_difference_the_board_takes() -> None:
    """Both sides are the same unit over the same window from the same feed. Nothing else is."""
    registry = build_registry(_roster())
    signals = resolve_behavior_signals(
        _capture(adds={"1001": 900, "1002": 10}, drops={"1001": 100, "1002": 40}),
        registry=registry,
        as_of=_NOW,
    )
    gate = QualityGate()
    records, _, _ = build_opportunity_records(
        ros_records=_ros_records(),
        full_board=_full_board(),
        context={},
        signals=signals,
        build_id="test",
        season=2026,
        through_week=8,
        gate=gate,
    )
    by_player = {row["player_id"]: row for row in records}
    assert by_player["gsis:00-0000001"]["net_add_count"] == 800
    assert by_player["gsis:00-0000002"]["net_add_count"] == -30
    # No field mixes a rank with a count. The schema has no place to put one, and neither
    # does the record.
    assert not any(
        key for key in records[0] if "gap" in key or "score" in key or key.endswith("_index")
    )
