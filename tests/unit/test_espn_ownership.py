"""ESPN ownership retention and `espn_ownership_v1`, offline (ADR-112).

Retention: validated before persistence, content-hashed, append-only, replayable and reused
once a day. The metric: every absence a named state, identity only through the registry,
changes in percentage points over a stated baseline inside a stated window, series with real
gaps and no duplicated captures, and nothing ever forward-filled or read as zero.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ffdraft.identity.registry import build_registry
from ffdraft.ownership import (
    OWNERSHIP_PREFIX,
    OwnershipCapture,
    build_ownership,
    capture_espn_ownership,
    capture_problems,
    load_ownership_window,
    read_ownership_capture,
    same_day_capture,
    verify_ownership_store,
    write_ownership_capture,
)
from ffdraft.ownership.capture import MIN_CORE_ROWS
from ffdraft.ownership.publish import ownership_layer
from ffdraft.retention import SnapshotConflictError, SnapshotStore, snapshot_key
from ffdraft.sources.espn import ESPN_SOURCE_ID, EspnFetch

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
VERSIONS = {"espn_ownership": "1.0", "espn_ownership_series": "1.0"}

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _roster(extra: list[dict[str, Any]] | None = None) -> pl.DataFrame:
    rows = [
        {"gsis_id": "00-0000001", "display_name": "Alpha Back", "position": "RB", "espn_id": "101"},
        {"gsis_id": "00-0000002", "display_name": "Bravo Wide", "position": "WR", "espn_id": "102"},
        {"gsis_id": "00-0000003", "display_name": "Charlie End", "position": "TE", "espn_id": None},
        *(extra or []),
    ]
    return pl.DataFrame(
        [{"season": 2026, "team": "SEA", "status": "ACT", **row} for row in rows],
        schema_overrides={"season": pl.Int32, "espn_id": pl.String},
    )


A, B, C = "gsis:00-0000001", "gsis:00-0000002", "gsis:00-0000003"
PLAYERS = [(A, "RB"), (B, "WR"), (C, "TE")]


def _row(espn_id: str, rostered: float | None, started: float | None = None, **extra: Any):
    return {
        "source_id": ESPN_SOURCE_ID,
        "external_player_id": espn_id,
        "position_id": 2,
        "full_name": None,
        "percent_rostered": rostered,
        "percent_started": started,
        "espn_percent_change": None,
        "league_type": 0,
        "source_updated_at_utc": None,
        "snapshot_at_utc": None,
        "quality_flags": "",
        **extra,
    }


def _capture(
    hours_ago: float,
    rows: list[dict[str, Any]],
    *,
    period: int | None = 6,
    season: int = 2026,
    anchor: datetime = NOW,
) -> OwnershipCapture:
    observed = anchor - timedelta(hours=hours_ago)
    return OwnershipCapture(
        source_id=ESPN_SOURCE_ID,
        season=season,
        snapshot_key=snapshot_key(observed),
        observed_at_utc=observed,
        adapter_version="1.0",
        source_policy_version="test",
        espn_current_period=period,
        request={"rows_returned": len(rows), "universe_count_header": len(rows)},
        rows=rows,
    )


def _build(captures: list[OwnershipCapture], *, generated_at: datetime = NOW, roster=None):
    registry = build_registry(roster if roster is not None else _roster())
    return build_ownership(
        captures,
        registry=registry,
        players=PLAYERS,
        build_id="b",
        season=2026,
        through_week=6,
        generated_at=generated_at,
        schema_versions=VERSIONS,
    )


def _latest(built, player_id: str) -> dict[str, Any]:
    return next(row for row in built.latest if row["player_id"] == player_id)


def _universe(count: int = MIN_CORE_ROWS) -> EspnFetch:
    players = tuple(
        {
            "id": 1000 + index,
            "player": {
                "id": 1000 + index,
                "defaultPositionId": 1 + index % 4,
                "ownership": {
                    "percentOwned": round(index / count * 100, 2),
                    "date": 1_790_000_000_000,
                },
            },
        }
        for index in range(count)
    )
    return EspnFetch(
        players=players,
        universe_count=count,
        wire_bytes=1,
        decoded_bytes=1,
        duration_ms=1,
        attempts=1,
        url="u",
    )


# --------------------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------------------


def test_a_capture_round_trips_through_the_store_with_its_hash(tmp_path: Path):
    store = SnapshotStore(root=tmp_path, prefix="market")
    capture = capture_espn_ownership(season=2026, as_of=NOW, fetched=_universe(), current_period=6)
    result = write_ownership_capture(capture, store=store)
    assert not result.idempotent
    read = read_ownership_capture(store, season=2026)
    assert read is not None
    assert read.rows == sorted(capture.rows, key=lambda r: r["external_player_id"])
    assert read.espn_current_period == 6
    assert read.observed_at_utc == NOW
    manifest = json.loads(
        (
            tmp_path
            / OWNERSHIP_PREFIX
            / ESPN_SOURCE_ID
            / "2026"
            / capture.snapshot_key
            / "manifest.json"
        ).read_text(),
    )
    assert manifest["request"]["universe_count_header"] == MIN_CORE_ROWS
    assert manifest["request"]["scoring_period_requested"] is None
    assert manifest["espn_current_period"] == 6
    # Vendor fields never reach the retained rows.
    assert not any("averageDraftPosition" in json.dumps(row) for row in read.rows)


def test_rewriting_the_same_capture_is_idempotent_and_a_different_one_conflicts(tmp_path: Path):
    store = SnapshotStore(root=tmp_path, prefix="market")
    capture = capture_espn_ownership(season=2026, as_of=NOW, fetched=_universe(), current_period=6)
    write_ownership_capture(capture, store=store)
    assert write_ownership_capture(capture, store=store).idempotent
    changed = capture_espn_ownership(season=2026, as_of=NOW, fetched=_universe(), current_period=7)
    with pytest.raises(SnapshotConflictError):
        write_ownership_capture(changed, store=store)


def test_an_incomplete_or_thin_capture_is_refused_and_leaves_the_good_one_newest(tmp_path: Path):
    store = SnapshotStore(root=tmp_path, prefix="market")
    good = capture_espn_ownership(season=2026, as_of=NOW, fetched=_universe(), current_period=6)
    write_ownership_capture(good, store=store)
    thin = capture_espn_ownership(
        season=2026,
        as_of=NOW + timedelta(days=1),
        fetched=_universe(MIN_CORE_ROWS - 1),
        current_period=6,
    )
    assert any("fewer than" in problem for problem in capture_problems(thin))
    with pytest.raises(ValueError, match="refusing to retain"):
        write_ownership_capture(thin, store=store)
    truncated = capture_espn_ownership(
        season=2026, as_of=NOW + timedelta(days=2), fetched=_universe()
    )
    truncated.request = {**truncated.request, "universe_count_header": MIN_CORE_ROWS + 9}
    assert any("incomplete" in problem for problem in capture_problems(truncated))
    with pytest.raises(ValueError):
        write_ownership_capture(truncated, store=store)
    newest = read_ownership_capture(store, season=2026)
    assert newest is not None and newest.snapshot_key == good.snapshot_key


def test_an_out_of_range_value_cannot_be_retained():
    capture = capture_espn_ownership(season=2026, as_of=NOW, fetched=_universe())
    capture.rows[0]["percent_rostered"] = 140.0
    assert any("out of range" in problem for problem in capture_problems(capture))


def test_one_capture_per_new_york_day_is_reused_and_tomorrow_is_not(tmp_path: Path):
    store = SnapshotStore(root=tmp_path, prefix="market")
    morning = datetime(2026, 10, 17, 11, 17, tzinfo=UTC)  # 07:17 New York
    capture = capture_espn_ownership(season=2026, as_of=morning, fetched=_universe())
    write_ownership_capture(capture, store=store)
    # The Tuesday-style second slot the same New York day: reused, original time kept.
    reused = same_day_capture(store, season=2026, now=morning + timedelta(hours=5))
    assert reused is not None and reused.observed_at_utc == morning
    # 23:30 New York is still the same day; 00:30 New York the next morning is not.
    late = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
    assert same_day_capture(store, season=2026, now=late) is not None
    assert same_day_capture(store, season=2026, now=late + timedelta(hours=1)) is None


def test_a_damaged_snapshot_is_never_reused_and_the_verifier_names_it(tmp_path: Path):
    store = SnapshotStore(root=tmp_path, prefix="market")
    capture = capture_espn_ownership(season=2026, as_of=NOW, fetched=_universe())
    write_ownership_capture(capture, store=store)
    payload = next((tmp_path / OWNERSHIP_PREFIX).rglob("ownership.normalized.json.gz"))
    payload.write_bytes(gzip.compress(b"[]", mtime=0))
    assert same_day_capture(store, season=2026, now=NOW + timedelta(hours=1)) is None
    snapshots, checked, problems = verify_ownership_store(store, season=2026)
    assert (snapshots, checked) == (1, 1)
    assert any("content hash" in problem for problem in problems)
    window, skipped = load_ownership_window(store, season=2026, now=NOW + timedelta(hours=1))
    assert window == [] and len(skipped) == 1


def test_the_window_reads_one_season_and_only_inside_28_days(tmp_path: Path):
    store = SnapshotStore(root=tmp_path, prefix="market")
    for days in (0, 3, 27.9, 28.5):
        capture = capture_espn_ownership(
            season=2026,
            as_of=NOW - timedelta(days=days),
            fetched=_universe(),
        )
        write_ownership_capture(capture, store=store)
    previous = capture_espn_ownership(
        season=2025, as_of=NOW - timedelta(days=1), fetched=_universe()
    )
    write_ownership_capture(previous, store=store)
    window, skipped = load_ownership_window(store, season=2026, now=NOW)
    assert skipped == []
    assert [round((NOW - c.observed_at_utc).total_seconds() / 86400, 1) for c in window] == [
        27.9,
        3.0,
        0.0,
    ]
    assert all(c.season == 2026 for c in window)


# --------------------------------------------------------------------------------------
# Reading states and identity
# --------------------------------------------------------------------------------------


def test_every_published_player_carries_exactly_one_named_state():
    built = _build([_capture(1, [_row("101", 18.0, 9.0)])])
    assert [(r["player_id"], r["reading_state"]) for r in built.latest] == [
        (A, "observed"),
        (B, "not_published"),  # verified ESPN id, ESPN published nothing: not 0%
        (C, "no_espn_id"),
    ]
    bravo = _latest(built, B)
    assert bravo["percent_rostered"] is None and bravo["start_state"] == "no_reading"


def test_zero_is_observed_and_a_missing_start_share_stays_unpublished():
    built = _build([_capture(1, [_row("101", 0.0, 0.0), _row("102", 40.0, None)])])
    alpha, bravo = _latest(built, A), _latest(built, B)
    assert (alpha["reading_state"], alpha["percent_rostered"], alpha["percent_started"]) == (
        "observed",
        0.0,
        0.0,
    )
    assert (bravo["start_state"], bravo["percent_started"]) == ("not_published", None)


def test_an_invalid_value_is_a_state_not_a_number():
    row = _row("101", None, None, quality_flags="invalid_percent_rostered")
    alpha = _latest(_build([_capture(1, [row])]), A)
    assert alpha["reading_state"] == "invalid"
    assert alpha["percent_rostered"] is None
    assert alpha["rostered_change_1d"]["state"] == "no_current_reading"


def test_a_shared_espn_id_fails_closed_for_both_players():
    roster = _roster(
        [{"gsis_id": "00-0000009", "display_name": "Dupe", "position": "RB", "espn_id": "101"}],
    )
    built = _build([_capture(1, [_row("101", 50.0, 20.0)])], roster=roster)
    assert _latest(built, A)["reading_state"] == "ambiguous_espn_id"
    assert _latest(built, A)["percent_rostered"] is None
    assert not [record for record in built.series if record["player_id"] == A]


def test_espn_never_adds_a_player_and_never_joins_by_name():
    rows = [_row("101", 10.0, full_name="Bravo Wide"), _row("999", 70.0, full_name="Bravo Wide")]
    built = _build([_capture(1, rows)])
    assert {r["player_id"] for r in built.latest} == {A, B, C}
    assert _latest(built, B)["reading_state"] == "not_published"
    assert built.summary["espn_rows_not_on_board"] == 1


def test_an_old_latest_capture_is_stale_values_kept_never_fresh():
    built = _build([_capture(40, [_row("101", 22.0, 8.0)])])
    alpha = _latest(built, A)
    assert alpha["reading_state"] == "stale"
    assert alpha["percent_rostered"] == 22.0
    assert alpha["observed_at_utc"] == "2026-10-15T23:00:00Z"  # the original retrieval time
    assert built.summary["stale"] is True and built.summary["latest_age_hours"] == 40.0
    fresh = _latest(_build([_capture(36, [_row("101", 22.0, 8.0)])]), A)
    assert fresh["reading_state"] == "observed"


# --------------------------------------------------------------------------------------
# Changes
# --------------------------------------------------------------------------------------


def test_the_seven_day_change_is_percentage_points_with_its_baseline_and_span():
    captures = [_capture(169, [_row("101", 18.0)]), _capture(1, [_row("101", 31.0)])]
    change = _latest(_build(captures), A)["rostered_change_7d"]
    assert change == {
        "state": "measured",
        "change_pp": 13.0,
        "baseline_percent_rostered": 18.0,
        "baseline_observed_at_utc": "2026-10-10T14:00:00Z",
        "span_hours": 168.0,
    }


def test_points_not_relative_growth_and_two_decimal_exactness():
    captures = [_capture(25, [_row("101", 0.07)]), _capture(1, [_row("101", 0.1)])]
    assert _latest(_build(captures), A)["rostered_change_1d"]["change_pp"] == 0.03


@pytest.mark.parametrize(
    ("age", "state"),
    [
        (17.9, "insufficient_history"),
        (18.0, "measured"),
        (30.0, "measured"),
        (30.1, "insufficient_history"),
    ],
)
def test_the_one_day_window_bounds(age, state):
    captures = [_capture(age + 1, [_row("101", 5.0)]), _capture(1, [_row("101", 6.0)])]
    assert _latest(_build(captures), A)["rostered_change_1d"]["state"] == state


@pytest.mark.parametrize(
    ("age", "state"),
    [
        (155.9, "insufficient_history"),
        (156.0, "measured"),
        (180.0, "measured"),
        (180.5, "insufficient_history"),
    ],
)
def test_the_seven_day_window_bounds(age, state):
    captures = [_capture(age + 1, [_row("101", 5.0)]), _capture(1, [_row("101", 6.0)])]
    assert _latest(_build(captures), A)["rostered_change_7d"]["state"] == state


def test_the_baseline_nearest_the_target_wins_and_a_tie_takes_the_earlier():
    captures = [
        _capture(1 + 28, [_row("101", 1.0)]),
        _capture(1 + 23, [_row("101", 2.0)]),
        _capture(1, [_row("101", 9.0)]),
    ]
    assert _latest(_build(captures), A)["rostered_change_1d"]["baseline_percent_rostered"] == 2.0
    tie = [
        _capture(1 + 26, [_row("101", 1.0)]),
        _capture(1 + 22, [_row("101", 2.0)]),
        _capture(1, [_row("101", 9.0)]),
    ]
    assert _latest(_build(tie), A)["rostered_change_1d"]["baseline_percent_rostered"] == 1.0


def test_a_first_observation_has_no_change_and_one_point():
    built = _build([_capture(1, [_row("101", 4.0)])])
    alpha = _latest(built, A)
    assert alpha["rostered_change_1d"]["state"] == "insufficient_history"
    assert alpha["rostered_change_7d"]["state"] == "insufficient_history"
    (series,) = [record for record in built.series if record["player_id"] == A]
    assert series["observations"] == 1 and series["span_hours"] == 0.0


def test_a_player_absent_from_the_baseline_is_not_backfilled():
    captures = [_capture(25, [_row("102", 3.0)]), _capture(1, [_row("101", 4.0), _row("102", 3.5)])]
    change = _latest(_build(captures), A)["rostered_change_1d"]
    assert change["state"] == "no_baseline_reading"
    assert change["change_pp"] is None and change["baseline_percent_rostered"] is None
    assert change["span_hours"] == 24.0


def test_a_league_type_change_is_incomparable():
    captures = [
        _capture(25, [_row("101", 3.0, league_type=1)]),
        _capture(1, [_row("101", 4.0, league_type=0)]),
    ]
    assert _latest(_build(captures), A)["rostered_change_1d"]["state"] == "incomparable"


# --------------------------------------------------------------------------------------
# Series
# --------------------------------------------------------------------------------------


def test_series_carry_real_gaps_week_rollover_and_no_invented_points():
    captures = [
        _capture(96, [_row("101", 10.0, 4.0)], period=5),
        _capture(72, [_row("102", 1.0)], period=5),  # Alpha absent: no point, not zero
        _capture(25, [_row("101", 12.0, None)], period=6),  # no start reading: null
        _capture(1, [_row("101", 14.0, 7.0)], period=6),
    ]
    built = _build(captures)
    (series,) = [record for record in built.series if record["player_id"] == A]
    assert series["captures_in_window"] == 4
    assert series["observations"] == 3
    assert [p["percent_rostered"] for p in series["points"]] == [10.0, 12.0, 14.0]
    assert [p["percent_started"] for p in series["points"]] == [4.0, None, 7.0]
    assert [p["espn_current_period"] for p in series["points"]] == [5, 6, 6]
    assert series["span_hours"] == 95.0
    assert built.summary["capture_times_utc"][1] == "2026-10-14T15:00:00Z"


def test_the_series_window_is_28_days_back_from_the_newest_capture():
    captures = [_capture(24 * 29, [_row("101", 1.0)]), _capture(1, [_row("101", 2.0)])]
    (series,) = [record for record in _build(captures).series if record["player_id"] == A]
    assert series["observations"] == 1


def test_the_publish_step_degrades_without_raising():
    registry = build_registry(_roster())
    opportunity = [{"player_id": A, "position": "RB"}]
    none = ownership_layer(
        opportunity_records=opportunity,
        registry=registry,
        store=None,
        season=2026,
        through_week=6,
        build_id="b",
        generated_at=NOW,
    )
    assert none.latest == [] and none.metadata is not None
    assert none.metadata["status"] == "unavailable"
    empty = ownership_layer(
        opportunity_records=opportunity,
        registry=registry,
        store=None,
        season=2026,
        through_week=6,
        build_id="b",
        generated_at=NOW,
        captures=[],
    )
    assert empty.metadata is not None and "28-day" in str(empty.metadata["reason"])
    published = ownership_layer(
        opportunity_records=opportunity,
        registry=registry,
        store=None,
        season=2026,
        through_week=6,
        build_id="b",
        generated_at=NOW,
        captures=[_capture(1, [_row("101", 5.0, 2.0)], period=6)],
    )
    assert published.metadata is not None and published.metadata["status"] == "published"
    assert "period 6" in published.metadata["start_context_statement"]
    assert [row["reading_state"] for row in published.latest] == ["observed"]


def test_the_publish_step_never_mutates_the_board_it_reads():
    registry = build_registry(_roster())
    opportunity = [{"player_id": A, "position": "RB", "ros_fair_rank": 4}]
    before = json.dumps(opportunity, sort_keys=True)
    ownership_layer(
        opportunity_records=opportunity,
        registry=registry,
        store=None,
        season=2026,
        through_week=6,
        build_id="b",
        generated_at=NOW,
        captures=[_capture(1, [_row("101", 5.0)])],
    )
    assert json.dumps(opportunity, sort_keys=True) == before
