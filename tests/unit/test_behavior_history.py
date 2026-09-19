"""`behavior_trend_v1`: momentum over the retained behaviour window (ADR-089).

The store has held a daily add/drop snapshot since the season opened and the only reader
resolved ``latest_key``, so a real history reached the board as one 24-hour number. These
tests cover the read that fixes it and, just as importantly, the two claims that keep a
short-window slope honest:

* **a direction needs two points, and two is enough.** The market rule refuses below three
  observation days spanning three days; this rule deliberately does not, because an add count
  moves in hours and a waiver edge is gone by the time a three-day bar admits it. What a
  two-point reading must never do is arrive without its span;
* **an absence is not a zero.** The feed is a top-100 list, so a snapshot that did not carry
  a player says nothing about his count that day. Filling it with zero would draw a collapse
  in interest out of a player leaving a leaderboard.

And one invariance, which is the whole safety argument for the change: publishing a history
must not move a number the Opportunity Board already published.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from ffdraft.behavior.capture import (
    BEHAVIOR_PREFIX,
    BehaviorCapture,
    capture_behavior,
    write_behavior_capture,
)
from ffdraft.behavior.history import (
    build_behavior_history,
    load_behavior_window,
    observations_from_captures,
    sleeper_to_canonical,
)
from ffdraft.behavior.trend import (
    BEHAVIOR_TREND_RULE,
    SINGLE_OBSERVATION,
    SPARSE_FEED_COVERAGE,
    BehaviorObservation,
    behavior_series_records,
    compute_behavior_trends,
)
from ffdraft.identity.registry import build_registry
from ffdraft.opportunity.board import resolve_behavior_signals
from ffdraft.retention import SnapshotStore

_NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
_PLAYER = "gsis:00-0000001"


def _roster() -> pl.DataFrame:
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
        ],
        schema_overrides={"season": pl.Int32, "sleeper_id": pl.String},
    )


def _capture(*, adds: dict[str, int], drops: dict[str, int], at: datetime) -> BehaviorCapture:
    return capture_behavior(
        season=2026,
        as_of=at,
        payloads={
            "add": [{"player_id": key, "count": value} for key, value in adds.items()],
            "drop": [{"player_id": key, "count": value} for key, value in drops.items()],
        },
    )


def _observations(*counts: tuple[int, int], player: str = _PLAYER) -> list[BehaviorObservation]:
    """One observation per entry, one day apart, oldest first, ending at ``_NOW``."""
    total = len(counts)
    return [
        BehaviorObservation(
            player_id=player,
            observed_at=_NOW - timedelta(days=total - 1 - index),
            add_count=adds,
            drop_count=drops,
        )
        for index, (adds, drops) in enumerate(counts)
    ]


# --------------------------------------------------------------------------------------
# The rule itself
# --------------------------------------------------------------------------------------


def test_one_observation_carries_no_direction() -> None:
    """A line needs two points. This is arithmetic, not a policy that could be relaxed."""
    trends = compute_behavior_trends(_observations((500, 10)), now=_NOW)
    result = trends[_PLAYER]
    assert result.add_trend is None
    assert result.net_trend is None
    assert result.observations == 1
    assert result.span_days == 0.0
    assert SINGLE_OBSERVATION in result.quality_flags


def test_two_observations_state_a_direction_over_their_own_span() -> None:
    """The case the rule exists for: a day-old series says what it saw in a day.

    `phase5_trend_v1` would publish nothing here. `behavior_trend_v1` publishes the slope
    *and* the one-day span it was measured over, which is what stops a consumer reading it
    as a week.
    """
    trends = compute_behavior_trends(_observations((400, 10), (900, 30)), now=_NOW)
    result = trends[_PLAYER]
    assert result.observations == 2
    assert result.span_days == pytest.approx(1.0)
    assert result.add_trend == pytest.approx(500.0)
    # Net moves by 480 over the same day: adds up 500, drops up 20.
    assert result.net_trend == pytest.approx(480.0)
    assert SINGLE_OBSERVATION not in result.quality_flags


def test_the_two_point_slope_is_the_ols_slope_and_not_a_special_case() -> None:
    """At two points the OLS fit reduces to the difference over the elapsed days.

    Stated as a test because it is the reason ``min_observations = 2`` is a continuous
    extension of one statistic rather than a second one bolted beside it.
    """
    pair = compute_behavior_trends(_observations((100, 0), (300, 0)), now=_NOW)[_PLAYER]
    assert pair.add_trend == pytest.approx((300 - 100) / 1.0)


def test_a_rising_count_is_positive_and_a_falling_one_is_negative() -> None:
    """The sign convention, which is deliberately *not* the market module's negation."""
    rising = compute_behavior_trends(_observations((100, 0), (200, 0), (300, 0)), now=_NOW)
    falling = compute_behavior_trends(_observations((300, 0), (200, 0), (100, 0)), now=_NOW)
    assert rising[_PLAYER].add_trend == pytest.approx(100.0)
    assert falling[_PLAYER].add_trend == pytest.approx(-100.0)


def test_two_observations_at_one_instant_have_no_slope() -> None:
    """No variance in x, so no line. Not an error, and not a zero either."""
    same = [
        BehaviorObservation(player_id=_PLAYER, observed_at=_NOW, add_count=100, drop_count=0),
        BehaviorObservation(player_id=_PLAYER, observed_at=_NOW, add_count=900, drop_count=0),
    ]
    result = compute_behavior_trends(same, now=_NOW)[_PLAYER]
    assert result.observations == 2
    assert result.add_trend is None


def test_several_captures_on_one_day_are_two_observations_and_one_day() -> None:
    """The same distinction `phase5_trend_v1` draws, for the same reason."""
    twice = [
        BehaviorObservation(
            player_id=_PLAYER,
            observed_at=_NOW - timedelta(hours=6),
            add_count=100,
            drop_count=0,
        ),
        BehaviorObservation(player_id=_PLAYER, observed_at=_NOW, add_count=160, drop_count=0),
    ]
    result = compute_behavior_trends(twice, now=_NOW)[_PLAYER]
    assert result.observations == 2
    assert result.observation_days == 1
    assert result.span_days == pytest.approx(0.25)


def test_observations_outside_the_window_are_not_used() -> None:
    old = BehaviorObservation(
        player_id=_PLAYER,
        observed_at=_NOW - timedelta(days=BEHAVIOR_TREND_RULE.window_days + 1),
        add_count=99999,
        drop_count=0,
    )
    inside = _observations((100, 0), (200, 0))
    result = compute_behavior_trends([old, *inside], now=_NOW)[_PLAYER]
    assert result.observations == 2
    assert result.add_trend == pytest.approx(100.0)


def test_a_snapshot_that_did_not_carry_the_player_is_a_gap_and_not_a_zero() -> None:
    """The top-N cutoff, which is the one place this data is easy to get wrong.

    Three snapshots were taken; the player appeared in two. The slope is fitted over the two
    he was in, the record says the window held three, and nothing anywhere invents a zero for
    the day he was outside the feed.
    """
    stamps = [_NOW - timedelta(days=days) for days in (2, 1, 0)]
    seen = [
        BehaviorObservation(player_id=_PLAYER, observed_at=stamps[0], add_count=100, drop_count=0),
        BehaviorObservation(player_id=_PLAYER, observed_at=stamps[2], add_count=300, drop_count=0),
    ]
    result = compute_behavior_trends(seen, now=_NOW, snapshot_times=stamps)[_PLAYER]
    assert result.observations == 2
    assert result.snapshots_in_window == 3
    assert result.missing_snapshots == 1
    assert SPARSE_FEED_COVERAGE in result.quality_flags
    assert result.add_trend == pytest.approx(100.0)  # 200 over 2 days, not over 3


def test_a_full_window_carries_no_sparse_flag() -> None:
    stamps = [_NOW - timedelta(days=days) for days in (1, 0)]
    result = compute_behavior_trends(
        _observations((100, 0), (200, 0)),
        now=_NOW,
        snapshot_times=stamps,
    )[_PLAYER]
    assert result.missing_snapshots == 0
    assert result.quality_flags == ()


# --------------------------------------------------------------------------------------
# The published record
# --------------------------------------------------------------------------------------


def _records(observations: list[BehaviorObservation], **kwargs: object) -> list[dict[str, object]]:
    trends = compute_behavior_trends(observations, now=_NOW, **kwargs)  # type: ignore[arg-type]
    return behavior_series_records(
        observations,
        trends=trends,
        build_id="build-1",
        season=2026,
        through_week=7,
        behavior_source_id="sleeper",
        lookback_hours=24,
        request_limit=100,
        window_days=BEHAVIOR_TREND_RULE.window_days,
        schema_version="1.0",
    )


def test_a_record_never_carries_a_trend_without_its_span() -> None:
    """The contract the validator also asserts, stated here at the source."""
    for record in _records(_observations((100, 0), (400, 5), (900, 9))):
        assert record["observations"] == len(record["points"])  # type: ignore[arg-type]
        assert record["span_days"] is not None
        assert record["observation_days"] is not None


def test_points_ascend_and_net_is_the_difference() -> None:
    record = _records(_observations((100, 10), (400, 15), (900, 40)))[0]
    points = record["points"]
    assert isinstance(points, list)
    stamps = [point["observed_at"] for point in points]
    assert stamps == sorted(stamps)
    for point in points:
        assert point["net_add_count"] == point["add_count"] - point["drop_count"]


def test_a_single_point_record_publishes_a_null_trend_and_says_so() -> None:
    record = _records(_observations((500, 10)))[0]
    assert record["add_trend"] is None
    assert record["net_trend"] is None
    assert record["observations"] == 1
    assert SINGLE_OBSERVATION in record["quality_flags"]  # type: ignore[operator]


def test_players_restricts_the_published_surface() -> None:
    observations = [
        *_observations((100, 0), (200, 0), player="gsis:00-0000001"),
        *_observations((300, 0), (400, 0), player="gsis:00-0000002"),
    ]
    trends = compute_behavior_trends(observations, now=_NOW)
    published = behavior_series_records(
        observations,
        trends=trends,
        build_id="build-1",
        season=2026,
        through_week=7,
        behavior_source_id="sleeper",
        lookback_hours=24,
        request_limit=100,
        window_days=BEHAVIOR_TREND_RULE.window_days,
        schema_version="1.0",
        players={"gsis:00-0000001"},
    )
    assert [record["player_id"] for record in published] == ["gsis:00-0000001"]


# --------------------------------------------------------------------------------------
# Reading the store
# --------------------------------------------------------------------------------------


def _store(tmp_path: Path, *, days: list[int]) -> SnapshotStore:
    store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    for offset in days:
        at = _NOW - timedelta(days=offset)
        write_behavior_capture(
            _capture(adds={"1001": 100 + offset * 10}, drops={"1001": 5}, at=at),
            store=store,
        )
    return store


def test_the_window_reads_every_retained_snapshot_inside_it(tmp_path: Path) -> None:
    store = _store(tmp_path, days=[3, 2, 1, 0])
    captures = load_behavior_window(store, season=2026, now=_NOW)
    assert len(captures) == 4
    assert [capture.observed_at_utc for capture in captures] == sorted(
        capture.observed_at_utc for capture in captures
    )


def test_the_window_excludes_snapshots_older_than_the_rule(tmp_path: Path) -> None:
    store = _store(tmp_path, days=[20, 1, 0])
    captures = load_behavior_window(store, season=2026, now=_NOW)
    assert len(captures) == 2


def test_an_unreadable_snapshot_shortens_the_history_rather_than_failing(
    tmp_path: Path,
) -> None:
    """The feed is optional by construction and a history over it is optional again."""
    store = _store(tmp_path, days=[2, 1, 0])
    behavior_store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    corrupt = behavior_store.keys("sleeper", 2026)[0]
    (behavior_store.snapshot_dir("sleeper", 2026, corrupt) / "manifest.json").write_text(
        "{not json",
        encoding="utf-8",
    )
    captures = load_behavior_window(store, season=2026, now=_NOW)
    assert len(captures) == 2


def test_the_history_projects_onto_canonical_ids_and_counts_what_it_cannot(
    tmp_path: Path,
) -> None:
    """nflverse-first, exactly as ADR-011 requires, on every snapshot rather than the last."""
    store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    for offset in (1, 0):
        write_behavior_capture(
            _capture(
                adds={"1001": 400 + offset, "9999": 12},  # 9999 reaches no canonical player
                drops={"1001": 10},
                at=_NOW - timedelta(days=offset),
            ),
            store=store,
        )
    history = build_behavior_history(
        load_behavior_window(store, season=2026, now=_NOW),
        registry=build_registry(_roster()),
        now=_NOW,
    )
    assert history.players() == (_PLAYER,)
    assert history.unresolved_rows == 2
    assert history.snapshots_in_window == 2
    assert history.trend_for(_PLAYER) is not None


def test_a_capture_that_carried_only_one_feed_still_yields_a_zero_for_the_other() -> None:
    """The one place a zero *is* correct: the feed reported, and he was in one half of it.

    A player can be in the top 100 adds and outside the top 100 drops. That is a drop count
    of zero-or-unknown for that day, and the board has always published it as zero; the
    series matches, because the union is taken per capture rather than per feed.
    """
    capture = _capture(adds={"1001": 900}, drops={"1002": 4}, at=_NOW)
    observations, _ = observations_from_captures(
        [capture],
        crosswalk=sleeper_to_canonical(build_registry(_roster())),
    )
    alpha = next(item for item in observations if item.player_id == _PLAYER)
    assert alpha.add_count == 900
    assert alpha.drop_count == 0


# --------------------------------------------------------------------------------------
# The invariance that makes the change safe
# --------------------------------------------------------------------------------------


def test_publishing_a_history_cannot_move_a_published_behaviour_count(tmp_path: Path) -> None:
    """The board's numbers come from the newest capture and this change does not touch them.

    Two stores holding the same newest snapshot — one with a week behind it, one with
    nothing — must resolve byte-identical behaviour signals. If a future refactor ever routes
    the board's counts through the history, this is the test that goes red.
    """
    registry = build_registry(_roster())
    long_store = _store(tmp_path / "long", days=[6, 5, 4, 3, 2, 1, 0])
    short_store = _store(tmp_path / "short", days=[0])

    def signals_for(store: SnapshotStore) -> dict[str, object]:
        captures = load_behavior_window(store, season=2026, now=_NOW)
        resolved = resolve_behavior_signals(captures[-1], registry=registry, as_of=_NOW)
        return resolved.to_dict()

    assert signals_for(long_store) == signals_for(short_store)

    # And the histories genuinely differ, so the assertion above is not vacuous.
    long_history = build_behavior_history(
        load_behavior_window(long_store, season=2026, now=_NOW),
        registry=registry,
        now=_NOW,
    )
    short_history = build_behavior_history(
        load_behavior_window(short_store, season=2026, now=_NOW),
        registry=registry,
        now=_NOW,
    )
    assert long_history.snapshots_in_window == 7
    assert short_history.snapshots_in_window == 1
    assert long_history.trend_for(_PLAYER) is not None
    assert short_history.trend_for(_PLAYER) is not None
    assert short_history.trend_for(_PLAYER).add_trend is None  # type: ignore[union-attr]


def test_an_empty_store_yields_an_empty_history(tmp_path: Path) -> None:
    history = build_behavior_history([], registry=build_registry(_roster()), now=_NOW)
    assert history.is_empty
    assert history.snapshots_in_window == 0
    assert history.summary()["players"] == 0


def test_a_window_whose_captures_disagree_about_the_lookback_publishes_null(
    tmp_path: Path,
) -> None:
    """A 6-hour count and a 24-hour count are different quantities wearing one label."""
    store = SnapshotStore(root=tmp_path, prefix=BEHAVIOR_PREFIX)
    for offset, lookback in ((1, 24), (0, 6)):
        write_behavior_capture(
            capture_behavior(
                season=2026,
                as_of=_NOW - timedelta(days=offset),
                lookback_hours=lookback,
                payloads={
                    "add": [{"player_id": "1001", "count": 100}],
                    "drop": [{"player_id": "1001", "count": 1}],
                },
            ),
            store=store,
        )
    history = build_behavior_history(
        load_behavior_window(store, season=2026, now=_NOW),
        registry=build_registry(_roster()),
        now=_NOW,
    )
    assert history.lookback_hours is None
    assert history.request_limit == 100
