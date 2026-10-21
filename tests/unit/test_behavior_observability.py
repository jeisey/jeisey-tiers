"""ADR-114: each Sleeper trending feed is a separate top-100 list, observed side by side.

The defect these tests pin: before ADR-114 the Opportunity Board and the momentum history
both wrote ``0`` for a side the feed did not carry. On the retained 2026-10-17T11:24:45Z
capture Tyler Allgeier was #1 in the add feed (549,030) and absent from the drop feed, whose
smallest count was 17,444; the board published his net as +549,030 — "no drops at all".
Across the 76 captures retained through 2026-10-21, 73.7% of player-snapshot rows were
one-sided and every one of them was zero-filled.

The cases below are **synthetic** unless they say otherwise. The Allgeier case reuses the two
real numbers above (from the private retained store) on a synthetic player, and does not
claim to reproduce anything from today's API.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ffdraft.artifacts.validate import _behavior_series_checks, _behavior_side_violations
from ffdraft.behavior.capture import (
    BEHAVIOR_PREFIX,
    capture_behavior,
    read_behavior_capture,
    write_behavior_capture,
)
from ffdraft.behavior.history import build_behavior_history, observations_from_captures
from ffdraft.behavior.trend import (
    ONE_SIDED_POINTS,
    BehaviorObservation,
    behavior_series_records,
    compute_behavior_trends,
)
from ffdraft.contracts.enums import BehaviorType
from ffdraft.identity.registry import build_registry
from ffdraft.opportunity.board import (
    AMBIGUOUS_SLEEPER_ID,
    NO_SLEEPER_ID,
    NOT_IN_FEED,
    OBSERVED,
    STALE,
    UNAVAILABLE,
    resolve_behavior_signals,
)
from ffdraft.retention import MANIFEST_FILENAME, SnapshotStore
from ffdraft.sources.base import SourceFetchError

NOW = datetime(2026, 10, 17, 11, 24, 45, tzinfo=UTC)
ALLGEIER_LIKE = "gsis:00-0000001"  # synthetic player carrying the retained 2026-10-17 counts
ADD_ONLY_RIVAL = "gsis:00-0000002"
DROP_ONLY = "gsis:00-0000003"
NEITHER = "gsis:00-0000004"
NO_ID = "gsis:00-0000005"
POISONED_A = "gsis:00-0000006"
POISONED_B = "gsis:00-0000007"


def _roster() -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, sleeper in (
        (1, "8132"),
        (2, "2002"),
        (3, "3003"),
        (4, "4004"),
        (5, None),
        (6, "6666"),
        (7, "6666"),
    ):
        rows.append(
            {
                "season": 2026,
                "gsis_id": f"00-000000{index}",
                "display_name": f"Player {index}",
                "position": "RB",
                "team": "ARI",
                "status": "ACT",
                "sleeper_id": sleeper,
            },
        )
    return pl.DataFrame(rows, schema_overrides={"season": pl.Int32, "sleeper_id": pl.String})


def _feed(counts: dict[str, int], *, filler: int, floor: int) -> list[dict[str, Any]]:
    """A 100-row feed: the named players plus anonymous off-board rows down to ``floor``."""
    rows = [{"player_id": key, "count": value} for key, value in counts.items()]
    extra = 100 - len(rows)
    for index in range(extra):
        rows.append({"player_id": str(900000 + filler + index), "count": floor + extra - 1 - index})
    rows.sort(key=lambda row: -int(row["count"]))
    return rows


def _capture(*, at: datetime = NOW, add: bool = True, drop: bool = True, limit: int = 100) -> Any:
    payloads: dict[str, list[dict[str, Any]]] = {}
    if add:
        payloads["add"] = _feed({"8132": 549_030, "2002": 300_000}, filler=0, floor=9_546)
    if drop:
        payloads["drop"] = _feed({"3003": 80_000, "2002": 20_000}, filler=1000, floor=17_444)
    return capture_behavior(season=2026, as_of=at, payloads=payloads, limit=limit)


def _signals(capture: Any, *, as_of: datetime = NOW) -> Any:
    return resolve_behavior_signals(capture, registry=build_registry(_roster()), as_of=as_of)


# --------------------------------------------------------------------------------------
# The board row, per side
# --------------------------------------------------------------------------------------


def test_the_2026_10_17_case_publishes_no_net_and_a_labelled_drop_bound() -> None:
    columns = _signals(_capture()).behavior_columns(ALLGEIER_LIKE)
    assert columns["add_state"] == OBSERVED and columns["add_count"] == 549_030
    assert columns["drop_state"] == NOT_IN_FEED
    assert columns["drop_count"] is None, "an absence from a top-100 feed is not a zero"
    assert columns["drop_count_max"] == 17_444, "the drop feed's own floor"
    assert columns["net_add_count"] is None, "the board published +549,030 here before"
    assert columns["add_rank"] == 1 and columns["drop_rank"] is None


def test_both_sides_observed_is_the_only_exact_net() -> None:
    columns = _signals(_capture()).behavior_columns(ADD_ONLY_RIVAL)
    assert (columns["add_state"], columns["drop_state"]) == (OBSERVED, OBSERVED)
    assert columns["net_add_count"] == 300_000 - 20_000
    assert columns["add_count_max"] is None and columns["drop_count_max"] is None


def test_a_drop_only_player_keeps_his_drops_and_an_unknown_add_count() -> None:
    columns = _signals(_capture()).behavior_columns(DROP_ONLY)
    assert (columns["add_state"], columns["add_count"]) == (NOT_IN_FEED, None)
    assert columns["add_count_max"] == 9_546
    assert (columns["drop_state"], columns["drop_count"]) == (OBSERVED, 80_000)
    assert columns["net_add_count"] is None


def test_a_player_in_neither_feed_is_bounded_on_both_sides_and_never_zero() -> None:
    columns = _signals(_capture()).behavior_columns(NEITHER)
    assert (columns["add_state"], columns["drop_state"]) == (NOT_IN_FEED, NOT_IN_FEED)
    assert columns["add_count"] is None and columns["drop_count"] is None
    assert (columns["add_count_max"], columns["drop_count_max"]) == (9_546, 17_444)


def test_a_real_zero_from_the_feed_is_an_observed_zero() -> None:
    capture = capture_behavior(
        season=2026,
        as_of=NOW,
        payloads={
            "add": [{"player_id": "8132", "count": 12}, {"player_id": "4004", "count": 0}],
            "drop": [{"player_id": "4004", "count": 3}],
        },
    )
    columns = _signals(capture).behavior_columns(NEITHER)
    assert (columns["add_state"], columns["add_count"]) == (OBSERVED, 0)
    assert columns["add_count_max"] is None
    assert columns["net_add_count"] == -3


def test_identity_failures_are_their_own_states() -> None:
    signals = _signals(_capture())
    no_id = signals.behavior_columns(NO_ID)
    assert (no_id["add_state"], no_id["drop_state"]) == (NO_SLEEPER_ID, NO_SLEEPER_ID)
    assert no_id["add_count_max"] is None, "the feed cannot reach him, so no bound applies"
    for poisoned in (POISONED_A, POISONED_B):
        columns = signals.behavior_columns(poisoned)
        assert columns["add_state"] == AMBIGUOUS_SLEEPER_ID
        assert columns["drop_state"] == AMBIGUOUS_SLEEPER_ID


def test_one_endpoint_failing_keeps_the_other_side(tmp_path: Path) -> None:
    capture = _capture(drop=False)
    assert capture.is_usable and not capture.is_complete
    assert capture.feed(BehaviorType.DROP).status == "failed"
    signals = _signals(capture)
    assert signals.available and signals.add_available and not signals.drop_available
    columns = signals.behavior_columns(ALLGEIER_LIKE)
    assert (columns["add_state"], columns["add_count"]) == (OBSERVED, 549_030)
    assert (columns["drop_state"], columns["drop_count_max"]) == (UNAVAILABLE, None)
    assert columns["net_add_count"] is None

    store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    write_behavior_capture(capture, store=store)
    loaded = read_behavior_capture(store, season=2026)
    assert loaded is not None and not loaded.side_available(BehaviorType.DROP)
    assert loaded.counts(BehaviorType.ADD)["8132"] == 549_030


def test_a_network_failure_on_one_feed_is_recorded_not_raised(monkeypatch: Any) -> None:
    from ffdraft.sources.sleeper import SleeperTrendingAdapter

    real = SleeperTrendingAdapter.normalize

    def fetch(self: Any, *, as_of: datetime, config: Any) -> Any:
        if config.options["behavior_type"] is BehaviorType.DROP:
            raise SourceFetchError("sleeper: drop 503")
        return real(self, [{"player_id": "8132", "count": 5}], behavior_type=BehaviorType.ADD)

    monkeypatch.setattr(SleeperTrendingAdapter, "fetch", fetch)
    capture = capture_behavior(season=2026, as_of=NOW)
    assert capture.feed(BehaviorType.DROP).error == "sleeper: drop 503"
    assert capture.side_available(BehaviorType.ADD)
    manifest = capture.manifest(content_digest="x")
    assert manifest["feeds"]["drop"]["status"] == "failed"
    assert manifest["feeds"]["add"]["retrieved_at_utc"] is not None


def test_a_stale_capture_publishes_states_and_no_counts() -> None:
    signals = _signals(_capture(), as_of=NOW + timedelta(hours=49))
    assert not signals.available
    columns = signals.behavior_columns(ALLGEIER_LIKE)
    assert (columns["add_state"], columns["drop_state"]) == (STALE, STALE)
    assert columns["add_count"] is None and columns["add_count_max"] is None


def test_no_capture_at_all_is_unavailable() -> None:
    signals = resolve_behavior_signals(None, registry=build_registry(_roster()), as_of=NOW)
    assert signals.behavior_columns(ALLGEIER_LIKE)["add_state"] == UNAVAILABLE


def test_a_larger_limit_that_is_ignored_still_reads_as_a_capped_top_100() -> None:
    """The ceiling measured on 2026-10-21: limit=500 still returns 100 rows."""
    capture = _capture(limit=500)
    manifest = capture.manifest(content_digest="x")
    assert manifest["request_limit"] == 500
    assert manifest["feed_ceiling"] == 100
    assert manifest["feeds"]["add"]["rows"] == 100
    assert manifest["feeds"]["add"]["truncated"] is True
    assert manifest["feeds"]["add"]["floor"] == 9_546
    assert manifest["coverage_rule"] == "sleeper_top_n_v1"


# --------------------------------------------------------------------------------------
# Historical compatibility: 1.0 manifests, immutable rows
# --------------------------------------------------------------------------------------


def test_a_1_0_capture_reads_as_two_retrieved_feeds_with_derived_floors(tmp_path: Path) -> None:
    store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    paths = write_behavior_capture(_capture(), store=store)
    manifest_path = next(Path(path) for path in paths if path.endswith(MANIFEST_FILENAME))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("feeds", "coverage_rule", "feed_ceiling"):
        manifest.pop(key)
    manifest["manifest_version"] = "1.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = read_behavior_capture(store, season=2026)
    assert loaded is not None and loaded.is_complete
    assert loaded.floor(BehaviorType.DROP) == 17_444
    columns = _signals(loaded).behavior_columns(ALLGEIER_LIKE)
    assert columns["drop_state"] == NOT_IN_FEED and columns["net_add_count"] is None


def test_the_retained_rows_are_not_rewritten(tmp_path: Path) -> None:
    store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    paths = write_behavior_capture(_capture(), store=store)
    payload = next(Path(path) for path in paths if path.endswith(".json.gz"))
    rows = json.loads(gzip.decompress(payload.read_bytes()))
    assert {row["behavior_type"] for row in rows} == {"add", "drop"}
    assert all(isinstance(row["count"], int) for row in rows), "only observed rows are kept"
    assert len(rows) == 200


# --------------------------------------------------------------------------------------
# The momentum series: each side on its own observations
# --------------------------------------------------------------------------------------


def _obs(hours: float, add: int | None, drop: int | None) -> BehaviorObservation:
    return BehaviorObservation(
        player_id=ALLGEIER_LIKE,
        observed_at=NOW - timedelta(hours=hours),
        add_count=add,
        drop_count=drop,
    )


def test_a_drop_only_day_never_enters_the_add_slope_as_zero() -> None:
    points = [_obs(48, 100, None), _obs(24, None, 900), _obs(0, 300, None)]
    trend = compute_behavior_trends(points, now=NOW)[ALLGEIER_LIKE]
    # v1 fitted 100, 0, 300 and read a dip; v2 fits 100 then 300 over two days.
    assert trend.add_observations == 2
    assert trend.add_trend == pytest.approx(100.0)
    assert trend.add_span_days == pytest.approx(2.0)
    assert trend.net_trend is None and trend.net_observations == 0
    assert ONE_SIDED_POINTS in trend.quality_flags


def test_the_net_slope_uses_only_points_with_both_sides() -> None:
    points = [_obs(72, 50, 10), _obs(48, 80, None), _obs(24, 120, 20), _obs(0, 200, 30)]
    trend = compute_behavior_trends(points, now=NOW)[ALLGEIER_LIKE]
    assert trend.observations == 4 and trend.add_observations == 4
    assert trend.net_observations == 3
    assert trend.net_span_days == pytest.approx(3.0)
    # Nets 40 @0d, 100 @2d, 170 @3d: the OLS slope over those three, not over four.
    assert trend.net_trend == pytest.approx(41.4286, abs=1e-3)


def test_series_records_publish_nullable_sides_and_validate(tmp_path: Path) -> None:
    points = [_obs(48, 100, None), _obs(24, 200, 15), _obs(0, 260, 20)]
    trends = compute_behavior_trends(points, now=NOW)
    records = behavior_series_records(
        points,
        trends=trends,
        build_id="b",
        season=2026,
        through_week=6,
        behavior_source_id="sleeper",
        lookback_hours=24,
        request_limit=100,
        window_days=7.0,
        schema_version="2.0",
    )
    record = records[0]
    assert record["points"][0] == {
        "observed_at": "2026-10-15T11:24:45Z",
        "add_count": 100,
        "drop_count": None,
        "net_add_count": None,
    }
    assert (record["add_observations"], record["net_observations"]) == (3, 2)
    checks = _behavior_series_checks(records, "test")
    assert [check.check_id for check in checks] == ["behavior_trend_series.series_well_formed"]

    record["points"][0]["net_add_count"] = 100  # a net invented from a missing side
    failed = {check.check_id for check in _behavior_series_checks(records, "test")}
    assert "behavior_trend_series.net_is_not_the_difference" in failed


def test_the_history_reads_old_captures_under_the_same_rule(tmp_path: Path) -> None:
    captures = [_capture(at=NOW - timedelta(days=1)), _capture()]
    history = build_behavior_history(captures, registry=build_registry(_roster()))
    trend = history.trend_for(ALLGEIER_LIKE)
    assert trend is not None and trend.net_trend is None and trend.add_observations == 2
    observations, _ = observations_from_captures(
        captures,
        crosswalk={"8132": ALLGEIER_LIKE},
    )
    assert all(item.drop_count is None for item in observations)


# --------------------------------------------------------------------------------------
# The validator refuses the old zero-fill
# --------------------------------------------------------------------------------------


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "player_id": ALLGEIER_LIKE,
        "ros_fair_rank": 10,
        "behavior_available": True,
        "add_state": OBSERVED,
        "drop_state": NOT_IN_FEED,
        "add_count": 549_030,
        "drop_count": None,
        "add_count_max": None,
        "drop_count_max": 17_444,
        "net_add_count": None,
        "add_rank": 1,
        "drop_rank": None,
        "outside_tier_board": False,
        "surface_reasons": ["x"],
        "ros_tier": 1,
    }
    row.update(overrides)
    return row


def test_the_validator_accepts_a_one_sided_row() -> None:
    assert _behavior_side_violations([_row()]) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"drop_count": 0},  # the pre-ADR-114 zero-fill
        {"net_add_count": 549_030},  # a net from one side
        {"drop_count_max": None, "drop_state": OBSERVED},  # observed with no count
        {"add_count_max": 5},  # a bound on an observed side
        {"drop_count_max": 600_000},  # a floor above an observed count
    ],
)
def test_the_validator_refuses_an_invented_side(overrides: dict[str, Any]) -> None:
    rows = [_row(**overrides), _row(player_id="other", add_count=20_000, drop_count_max=17_444)]
    assert _behavior_side_violations(rows)
