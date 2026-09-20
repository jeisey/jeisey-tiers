"""The retained behaviour window, read back and keyed to canonical players.

**Boundary module. Behaviour only.**

Phase 10 built the capture and consumed nothing, so that a real series would exist by the
time something needed one. Phase 12 needed one and read :func:`read_behavior_capture`, which
resolves ``latest_key`` — so the whole retained history reached the published board as a
single 24-hour number per player. This is the other half: one read of the trailing window,
one projection onto canonical ids, one frozen statistic over it.

It is `ffdraft.market.history` for a different quantity, deliberately shaped the same way::

    store -> trailing window (the frozen rule's window_days)
          -> observations, keyed by canonical player id
          -> compute_behavior_trends (`behavior_trend_v1`)
          -> BehaviorHistory

**What it does not touch.** The Opportunity Board's ``add_count``, ``drop_count``,
``net_add_count``, ``add_rank`` and ``drop_rank`` still come from
:func:`~ffdraft.opportunity.board.resolve_behavior_signals` reading the newest capture, and
this module cannot change any of them. `tests/unit/test_behavior_history.py` asserts that a
build with a seven-day window publishes byte-identical behaviour columns to one with a
one-snapshot window, because a history is a new artifact and not a revision of an old one.

**The join direction is ADR-011's, on every snapshot.** Iteration runs over canonical players
carrying a ``sleeper_id``, never over the feed, and a feed row reaching no canonical player is
counted and dropped rather than guessed at — the same rule the status artifact and the
Opportunity Board already follow, applied once per retained instant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ffdraft.behavior.capture import (
    BEHAVIOR_PREFIX,
    BehaviorCapture,
    read_behavior_capture,
)
from ffdraft.behavior.trend import (
    BEHAVIOR_TREND_RULE,
    BehaviorObservation,
    BehaviorTrendResult,
    BehaviorTrendRule,
    behavior_trend_summary,
    compute_behavior_trends,
)
from ffdraft.contracts.enums import BehaviorType
from ffdraft.identity.registry import CanonicalRegistry
from ffdraft.retention import SnapshotStore, parse_snapshot_key
from ffdraft.sources.sleeper import SLEEPER_SOURCE_ID

__all__ = [
    "BehaviorHistory",
    "build_behavior_history",
    "load_behavior_window",
    "sleeper_to_canonical",
]


def load_behavior_window(
    store: SnapshotStore | Path,
    *,
    season: int,
    now: datetime,
    source_id: str = SLEEPER_SOURCE_ID,
    window_days: float = BEHAVIOR_TREND_RULE.window_days,
) -> list[BehaviorCapture]:
    """Retained behaviour captures inside the window, oldest first.

    Reading only the window keeps a build's cost flat as the store grows: a season's captures
    are hundreds of directories and a momentum reading needs the handful inside the window.
    How many that is depends on the refresh cadence and not on the calendar — a snapshot is
    one `daily-refresh` run, the schedule adds a second on Tuesdays, and a day spent re-running
    the workflow adds however many were clicked, so fifteen in a seven-day window is ordinary
    (ADR-090). Each one goes through :func:`read_behavior_capture`, so every file is re-hashed
    against its own manifest on the way in — a truncated snapshot fails here rather than
    becoming a point on a chart.

    A capture that cannot be read is **skipped, not fatal**. The behaviour feed is optional by
    construction (ADR-079) and a history missing its oldest day is a shorter history, which
    this rule already handles; a history that takes the whole build down would make an
    enrichment critical.
    """
    root = store.root if isinstance(store, SnapshotStore) else store
    behavior_store = SnapshotStore(root=root, prefix=BEHAVIOR_PREFIX)
    horizon = now - timedelta(days=window_days)
    captures: list[BehaviorCapture] = []
    for key in behavior_store.keys(source_id, season):
        try:
            moment = parse_snapshot_key(key)
        except ValueError:
            continue
        if not (horizon <= moment <= now):
            continue
        try:
            capture = read_behavior_capture(
                behavior_store,
                season=season,
                source_id=source_id,
                key=key,
            )
        except (OSError, ValueError) as exc:  # noqa: PERF203 - one bad day is not an outage
            del exc
            continue
        if capture is not None:
            captures.append(capture)
    captures.sort(key=lambda capture: capture.observed_at_utc)
    return captures


def sleeper_to_canonical(registry: CanonicalRegistry) -> dict[str, str]:
    """``sleeper_id -> canonical player_id``, built nflverse-first (ADR-011).

    Sleeper's own ``gsis_id`` is present on about 32% of its records, so the crosswalk is
    read off the canonical player and never off the feed.
    """
    mapping: dict[str, str] = {}
    for player_id in sorted(registry.players):
        sleeper_id = registry.players[player_id].crosswalk.sleeper_id
        if sleeper_id:
            mapping[str(sleeper_id)] = player_id
    return mapping


@dataclass(frozen=True)
class BehaviorHistory:
    """One source's retained behaviour window, its observations and its momentum.

    The window is the evidence; ``trends`` is the frozen statistic over it. They are carried
    together because publishing one without the other is the bug ADR-081 recorded on the
    market side: a series with no slope reads as "no data", and a slope with no series leaves
    a chart to guess where the number came from.
    """

    source_id: str
    captures: tuple[BehaviorCapture, ...] = ()
    observations: tuple[BehaviorObservation, ...] = ()
    trends: Mapping[str, BehaviorTrendResult] = field(default_factory=dict)
    #: The instant the window was anchored on — the newest retained observation, not the
    #: build clock, so a build re-run hours later reproduces the same slopes.
    anchored_at: datetime | None = None
    unresolved_rows: int = 0
    rule: BehaviorTrendRule = BEHAVIOR_TREND_RULE

    @property
    def is_empty(self) -> bool:
        return not self.observations

    @property
    def snapshot_keys(self) -> tuple[str, ...]:
        return tuple(capture.snapshot_key for capture in self.captures)

    @property
    def snapshots_in_window(self) -> int:
        return len(self.captures)

    @property
    def lookback_hours(self) -> int | None:
        """The window every retained capture requested, or ``None`` if they disagree.

        A series whose points were taken over different lookback windows is not one series:
        a 6-hour count and a 24-hour count are different quantities wearing one label. The
        caller publishes this only when every capture agrees, and the artifact's field is
        nullable so a mixed window says so rather than picking one.
        """
        windows = {capture.lookback_hours for capture in self.captures}
        return next(iter(windows)) if len(windows) == 1 else None

    @property
    def request_limit(self) -> int | None:
        """The feed depth every capture asked for, or ``None`` if they disagree.

        Published so "no point on this day" has a stated ceiling: the player's count was at
        most the smallest count inside a feed this deep.
        """
        limits = {capture.request_limit for capture in self.captures}
        return next(iter(limits)) if len(limits) == 1 else None

    def trend_for(self, player_id: str) -> BehaviorTrendResult | None:
        return self.trends.get(player_id)

    def players(self) -> tuple[str, ...]:
        return tuple(sorted({observation.player_id for observation in self.observations}))

    def summary(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "snapshot_keys": list(self.snapshot_keys),
            "anchored_at_utc": (
                self.anchored_at.isoformat().replace("+00:00", "Z") if self.anchored_at else None
            ),
            "lookback_hours": self.lookback_hours,
            "request_limit": self.request_limit,
            "unresolved_rows": self.unresolved_rows,
            "observations": len(self.observations),
            **behavior_trend_summary(
                self.trends,
                snapshots_in_window=self.snapshots_in_window,
                rule=self.rule,
            ),
        }


def observations_from_captures(
    captures: Sequence[BehaviorCapture],
    *,
    crosswalk: Mapping[str, str],
) -> tuple[list[BehaviorObservation], int]:
    """Flatten retained captures into canonical-keyed observations.

    A player appears in one capture's output when **either** feed carried him: he can be in
    the top 100 adds and outside the top 100 drops, and the missing half is a zero rather than
    an unknown, because the feed did report on him that day. That is the one place a zero is
    correct, and it is why the union is taken per capture rather than per feed.
    """
    observations: list[BehaviorObservation] = []
    unresolved = 0
    for capture in captures:
        adds = capture.counts(BehaviorType.ADD)
        drops = capture.counts(BehaviorType.DROP)
        resolved: dict[str, tuple[int, int]] = {}
        for external in sorted(set(adds) | set(drops)):
            canonical = crosswalk.get(external)
            if canonical is None:
                unresolved += 1
                continue
            resolved[canonical] = (adds.get(external, 0), drops.get(external, 0))
        for player_id in sorted(resolved):
            add_count, drop_count = resolved[player_id]
            observations.append(
                BehaviorObservation(
                    player_id=player_id,
                    observed_at=capture.observed_at_utc,
                    add_count=add_count,
                    drop_count=drop_count,
                ),
            )
    return observations, unresolved


def build_behavior_history(
    captures: Sequence[BehaviorCapture],
    *,
    registry: CanonicalRegistry | None,
    now: datetime | None = None,
    source_id: str = SLEEPER_SOURCE_ID,
    rule: BehaviorTrendRule = BEHAVIOR_TREND_RULE,
) -> BehaviorHistory:
    """Project the window onto canonical ids and compute the frozen statistic over it.

    ``now`` anchors the trailing window and defaults to the newest retained observation
    rather than to the build clock, so a board rebuilt from the same bytes months later
    produces the same slopes.
    """
    window = tuple(sorted(captures, key=lambda capture: capture.observed_at_utc))
    if not window or registry is None:
        return BehaviorHistory(source_id=source_id, captures=window, rule=rule)
    anchor = now if now is not None else window[-1].observed_at_utc
    observations, unresolved = observations_from_captures(
        window,
        crosswalk=sleeper_to_canonical(registry),
    )
    trends = compute_behavior_trends(
        observations,
        now=anchor,
        snapshot_times=[capture.observed_at_utc for capture in window],
        rule=rule,
    )
    return BehaviorHistory(
        source_id=source_id,
        captures=window,
        observations=tuple(observations),
        trends=trends,
        anchored_at=anchor,
        unresolved_rows=unresolved,
        rule=rule,
    )


def behavior_history_payload(history: BehaviorHistory) -> dict[str, Any]:
    """The build-metadata block, in the shape the market history's already takes."""
    return history.summary()
