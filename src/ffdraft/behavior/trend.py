"""Add/drop momentum from our own retained behaviour snapshots (`behavior_trend_v1`).

**Boundary module. Behaviour only — never a price, never a rank, never a model feature.**

The store has held a daily Sleeper add/drop snapshot since the season opened and nothing
read more than the newest one, so a history that exists reached the board as a single
24-hour number. This computes the slope over the retained window instead; the capture side
is unchanged and no published behaviour count moves.

**The rule is deliberately *not* `phase5_trend_v1`.** The market rule refuses to estimate a
slope below three observation days spanning three days, and that is right for a draft price:
an ADP moves slowly, a two-point line through it is mostly noise, and a reader comparing
Tuesday's board with Friday's needs the same window on both. An add count is the opposite
kind of quantity. It is a count of transactions inside a declared 24-hour window, it moves in
hours rather than weeks, and a waiver edge is gone by the time a three-day rule admits it.
So:

    add_trend = OLS slope of add_count on days elapsed, over the retained window,
                using every observation that exists

with **two observations enough to state one**, and the span it was measured over published
beside it on every record. One observation is a point and no slope, which is arithmetic
rather than policy: a line needs two.

**Honesty here is the label, not suppression.** A two-point slope is a real measurement of a
short window and a bad estimate of a long one, so nothing in this module or downstream of it
may print a slope without its span. `span_days` and `observations` are required fields for
exactly that reason, and `tests/unit/test_behavior_trend.py` asserts a record can never carry
a trend without them.

**Sign convention, and why it is not the market's.** Positive means the count is rising —
more rosters adding him each day. `phase5_trend_v1` negates its slope because a *falling* ADP
means a player is getting more expensive; there is no such inversion here, because a bigger
add count is straightforwardly more interest. Do not "fix" this to match the market module.

**The feed is a top-N list, so an absence is not a zero.** Sleeper returns the 100 most-added
players and nothing else, so a player outside it on a given day has a count somewhere in
``[0, the smallest count that did appear]`` — unknown, not zero. A snapshot that did not carry
the player therefore produces **no point**, and the record publishes ``snapshots_in_window``
beside ``observations`` so a reader can see the difference. Filling those days with zero would
manufacture a collapse in interest out of a player leaving a leaderboard.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ffdraft.timeutil import isoformat_utc

__all__ = [
    "BEHAVIOR_TREND_RULE",
    "BEHAVIOR_TREND_RULE_VERSION",
    "SINGLE_OBSERVATION",
    "SPARSE_FEED_COVERAGE",
    "BehaviorObservation",
    "BehaviorTrendResult",
    "BehaviorTrendRule",
    "behavior_series_records",
    "behavior_trend_summary",
    "compute_behavior_trends",
]

BEHAVIOR_TREND_RULE_VERSION = "behavior_trend_v1"

#: A record carrying one observation. Not a defect and not a degradation — the series is
#: young, or the player entered the feed today — but a consumer must not print a direction.
SINGLE_OBSERVATION = "single_observation"

#: The window held snapshots this player did not appear in, so the slope is fitted over the
#: days he was inside the feed's top N rather than over the whole window.
SPARSE_FEED_COVERAGE = "sparse_feed_coverage"


@dataclass(frozen=True, slots=True)
class BehaviorTrendRule:
    """The frozen definition. A change here is a new version with its own ADR."""

    version: str = BEHAVIOR_TREND_RULE_VERSION
    #: The trailing window observations are taken from. Matches the market rule's window so
    #: the two charts on one site describe the same number of days.
    window_days: float = 7.0
    #: Two points define a line. This is the whole difference from `phase5_trend_v1`, and it
    #: is a deliberate one: see the module docstring.
    min_observations: int = 2

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_version": self.version,
            "window_days": self.window_days,
            "min_observations": self.min_observations,
            "sign_convention": "positive = the count is rising (more rosters adding him)",
            "statistic": "OLS slope of add_count on days elapsed, transactions/day",
            "span_is_published": (
                "every record carries observations and span_days; a slope may never be "
                "presented without the span it was measured over"
            ),
            "absence_is_not_zero": (
                "the feed is a top-N list, so a snapshot that did not carry the player "
                "produces no point rather than a zero"
            ),
        }


BEHAVIOR_TREND_RULE = BehaviorTrendRule()


@dataclass(frozen=True, slots=True)
class BehaviorObservation:
    """One player's add and drop counts at one retained instant."""

    player_id: str
    observed_at: datetime
    add_count: int
    drop_count: int

    @property
    def net_add_count(self) -> int:
        """Adds minus drops.

        Legitimate for the narrow reason the Opportunity Board already relies on: both sides
        are the same unit, over the same window, from the same feed, at the same moment.
        """
        return self.add_count - self.drop_count


@dataclass(frozen=True, slots=True)
class BehaviorTrendResult:
    """A player's momentum, and everything needed to say what it was measured over."""

    player_id: str
    add_trend: float | None
    net_trend: float | None
    observations: int
    observation_days: int
    span_days: float
    snapshots_in_window: int

    @property
    def missing_snapshots(self) -> int:
        """Retained snapshots inside the window that did not carry this player."""
        return max(0, self.snapshots_in_window - self.observations)

    @property
    def quality_flags(self) -> tuple[str, ...]:
        flags: list[str] = []
        if self.observations < BEHAVIOR_TREND_RULE.min_observations:
            flags.append(SINGLE_OBSERVATION)
        if self.missing_snapshots > 0:
            flags.append(SPARSE_FEED_COVERAGE)
        return tuple(flags)


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Ordinary least squares slope, or ``None`` when x has no variance.

    Written out here rather than imported from :mod:`ffdraft.market.trend`, which has the
    same four lines. Behaviour is not market data and must not acquire an import edge into
    the market package to borrow arithmetic — the same reasoning that keeps
    :mod:`ffdraft.retention` source-neutral. `AGENTS.md` section 13 is about not adding a
    *dependency* for something small; this is the opposite case.

    At two points this reduces exactly to ``(y1 - y0) / (x1 - x0)``, which is what makes the
    rule's ``min_observations = 2`` a continuous extension of the same statistic rather than
    a second special-cased one.
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0.0:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return numerator / denominator


def compute_behavior_trends(
    observations: Sequence[BehaviorObservation],
    *,
    now: datetime,
    snapshot_times: Iterable[datetime] = (),
    rule: BehaviorTrendRule = BEHAVIOR_TREND_RULE,
) -> dict[str, BehaviorTrendResult]:
    """Momentum per player over the trailing window ending at ``now``.

    ``snapshot_times`` is every retained instant inside the window, whether or not it carried
    a given player. It is what lets a record distinguish "the series is three days old" from
    "he was outside the top 100 on four of those days", which are different facts about the
    same three points.

    Deterministic in every respect a caller could notice: observations are ordered by instant
    then player, several snapshots on one calendar day all count as observations but only one
    *observation day*, and no point is ever discarded as an outlier.
    """
    window_start = now - timedelta(days=rule.window_days)
    in_window = [moment for moment in snapshot_times if window_start <= _aware(moment, now) <= now]
    snapshots_in_window = len(in_window)

    grouped: dict[str, list[BehaviorObservation]] = {}
    for observation in observations:
        if not (window_start <= observation.observed_at <= now):
            continue
        grouped.setdefault(observation.player_id, []).append(observation)

    results: dict[str, BehaviorTrendResult] = {}
    for player_id, points in grouped.items():
        ordered = sorted(points, key=lambda item: (item.observed_at, item.add_count))
        days = {observation.observed_at.date() for observation in ordered}
        span = (ordered[-1].observed_at - ordered[0].observed_at).total_seconds() / 86400.0
        add_trend: float | None = None
        net_trend: float | None = None
        if len(ordered) >= rule.min_observations:
            origin = ordered[0].observed_at
            xs = [
                (observation.observed_at - origin).total_seconds() / 86400.0
                for observation in ordered
            ]
            adds = _ols_slope(xs, [float(item.add_count) for item in ordered])
            nets = _ols_slope(xs, [float(item.net_add_count) for item in ordered])
            add_trend = None if adds is None else round(adds, 4)
            net_trend = None if nets is None else round(nets, 4)
        results[player_id] = BehaviorTrendResult(
            player_id=player_id,
            add_trend=add_trend,
            net_trend=net_trend,
            observations=len(ordered),
            observation_days=len(days),
            span_days=span,
            # A player can only be missing from snapshots that were actually taken, so the
            # floor is his own observation count: a caller that passes no snapshot times
            # gets "every snapshot carried him" rather than a negative absence.
            snapshots_in_window=max(snapshots_in_window, len(ordered)),
        )
    return results


def _aware(moment: datetime, reference: datetime) -> datetime:
    """Compare snapshot instants against the window on one timezone footing."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=reference.tzinfo)
    return moment


def behavior_series_records(
    observations: Sequence[BehaviorObservation],
    *,
    trends: Mapping[str, BehaviorTrendResult],
    build_id: str,
    season: int,
    through_week: int,
    behavior_source_id: str,
    # Nullable, and the schema says so: a window whose captures disagree about the
    # lookback has no single answer, and picking one would label a 6-hour count as a
    # 24-hour one. See `BehaviorHistory.lookback_hours`.
    lookback_hours: int | None,
    request_limit: int | None,
    window_days: float,
    schema_version: str,
    players: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """The retained history, shaped for the card's momentum sparkline.

    **One record per player, not one per preset.** An add count is preset-independent — the
    same transactions however points are scored — so keying this by league and scoring would
    publish nine identical copies of every series. `inseason_opportunity` already dedups its
    role columns across presets for the same reason.

    ``players`` restricts the output to the published surface. A series for a player no card
    can open is bytes shipped to every visitor for nothing.
    """
    wanted = set(players) if players is not None else None
    by_player: dict[str, list[BehaviorObservation]] = {}
    for observation in observations:
        if wanted is not None and observation.player_id not in wanted:
            continue
        by_player.setdefault(observation.player_id, []).append(observation)

    records: list[dict[str, Any]] = []
    for player_id in sorted(by_player):
        points = sorted(by_player[player_id], key=lambda item: item.observed_at)
        result = trends.get(player_id)
        records.append(
            {
                "schema_version": schema_version,
                "build_id": build_id,
                "season": season,
                "through_week": through_week,
                "behavior_source_id": behavior_source_id,
                "player_id": player_id,
                "lookback_hours": lookback_hours,
                "request_limit": request_limit,
                "window_days": window_days,
                "snapshots_in_window": result.snapshots_in_window if result else len(points),
                "observations": result.observations if result else len(points),
                "observation_days": result.observation_days if result else 0,
                "span_days": round(result.span_days, 4) if result else 0.0,
                "add_trend": result.add_trend if result else None,
                "net_trend": result.net_trend if result else None,
                "quality_flags": list(result.quality_flags) if result else [],
                "points": [
                    {
                        "observed_at": isoformat_utc(point.observed_at),
                        "add_count": point.add_count,
                        "drop_count": point.drop_count,
                        "net_add_count": point.net_add_count,
                    }
                    for point in points
                ],
            },
        )
    return records


def behavior_trend_summary(
    results: Mapping[str, BehaviorTrendResult],
    *,
    snapshots_in_window: int,
    rule: BehaviorTrendRule = BEHAVIOR_TREND_RULE,
) -> dict[str, object]:
    """Counts for the build metadata, in the shape the market summary already uses."""
    with_trend = [result for result in results.values() if result.add_trend is not None]
    sparse = [result for result in results.values() if result.missing_snapshots > 0]
    return {
        "rule_version": rule.version,
        "window_days": rule.window_days,
        "min_observations": rule.min_observations,
        "snapshots_in_window": snapshots_in_window,
        "players": len(results),
        "players_with_trend": len(with_trend),
        "players_with_sparse_coverage": len(sparse),
        "trend_available": bool(with_trend),
    }
