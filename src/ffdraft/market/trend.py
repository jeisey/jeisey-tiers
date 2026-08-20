"""Market trend from our own retained point-in-time snapshots (ADR-042).

**Boundary module.** Market data only.

MFL's historical export cannot supply a trend: it is a season-long aggregate recomputed at
request time, so yesterday's price is unrecoverable from it (ADR-010). The only honest
source of movement is the append-only store this project keeps for itself.

The definition is fixed, `phase5_trend_v1`::

    market_trend = -slope of an OLS fit of market_adp on days elapsed,
                   over the trailing 7 days, within one source/season/cohort

so **positive means the player is moving earlier — getting more expensive**, the same
direction ``rank_gap`` calls a bargain.

Two rules keep the number meaningful rather than merely present:

*the window never changes silently.* A "7-day trend" computed over whatever history happens
to exist would mean something different on every row. Below three observation days spanning
three days, the answer is ``None`` and the row is flagged, not softened to a 1-day delta.

*cohorts are never mixed.* Changing cohort changes the population being priced, and the
resulting jump would look exactly like movement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from ffdraft.market.snapshot import MarketSnapshot

__all__ = [
    "INSUFFICIENT_TREND_HISTORY",
    "TREND_RULE",
    "TREND_RULE_VERSION",
    "TrendObservation",
    "TrendResult",
    "TrendRule",
    "compute_trends",
    "observations_from_snapshots",
]

TREND_RULE_VERSION = "phase5_trend_v1"

#: Quality flag for a row whose history cannot support the declared window.
INSUFFICIENT_TREND_HISTORY = "insufficient_trend_history"


@dataclass(frozen=True, slots=True)
class TrendRule:
    """The frozen trend definition. A change here is a new version with its own ADR."""

    version: str = TREND_RULE_VERSION
    window_days: float = 7.0
    #: Distinct calendar days carrying an observation. Two points can fit any line.
    min_observation_days: int = 3
    #: Elapsed days between the first and last observation used.
    min_span_days: float = 3.0

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_version": self.version,
            "window_days": self.window_days,
            "min_observation_days": self.min_observation_days,
            "min_span_days": self.min_span_days,
            "sign_convention": "positive = moving earlier (more expensive)",
            "statistic": "negated OLS slope of market_adp on days elapsed, picks/day",
        }


TREND_RULE = TrendRule()


@dataclass(frozen=True, slots=True)
class TrendObservation:
    """One player's price at one retained instant, inside one cohort."""

    player_id: str
    cohort_id: str
    observed_at: datetime
    market_adp: float


@dataclass(frozen=True, slots=True)
class TrendResult:
    """A player's trend, or the reason there is not one."""

    player_id: str
    cohort_id: str
    trend: float | None
    observation_days: int
    span_days: float
    observations: int

    @property
    def quality_flags(self) -> tuple[str, ...]:
        return () if self.trend is not None else (INSUFFICIENT_TREND_HISTORY,)

    def to_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "cohort_id": self.cohort_id,
            "market_trend": self.trend,
            "observation_days": self.observation_days,
            "span_days": round(self.span_days, 4),
            "observations": self.observations,
        }


def observations_from_snapshots(
    snapshots: Sequence[MarketSnapshot],
    *,
    cohort_id: str,
) -> list[TrendObservation]:
    """Flatten retained snapshots into per-player observations for one cohort.

    Rows without a canonical ``player_id`` are skipped: a trend keyed by an external id
    would break the moment a crosswalk changed, and an unresolved row has no board position
    to move against anyway.
    """
    observations: list[TrendObservation] = []
    for snapshot in snapshots:
        moment = snapshot.retrieved_at
        for row in snapshot.rows_for(cohort_id):
            player_id = row.get("player_id")
            price = row.get("average_pick")
            if not player_id or price is None:
                continue
            observations.append(
                TrendObservation(
                    player_id=str(player_id),
                    cohort_id=cohort_id,
                    observed_at=moment,
                    market_adp=float(price),
                ),
            )
    return observations


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Ordinary least squares slope, or ``None`` when x has no variance.

    Written out rather than pulled from a library: it is four lines, it has to behave
    predictably on three points, and `AGENTS.md` section 13 says not to add a dependency
    for something a small module does.
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


def compute_trends(
    observations: Sequence[TrendObservation],
    *,
    now: datetime,
    cohort_id: str,
    rule: TrendRule = TREND_RULE,
) -> dict[str, TrendResult]:
    """Trend per player over the trailing window ending at ``now``.

    Deterministic in every respect a caller could notice: observations are sorted by
    instant then price, several snapshots on one calendar day all count as observations but
    only one *observation day*, and no point is ever discarded as an outlier — with three
    to seven points there is nothing to reject robustly, and dropping one silently is how a
    trend becomes an artefact.
    """
    window_start = now - timedelta(days=rule.window_days)
    grouped: dict[str, list[TrendObservation]] = {}
    for observation in observations:
        if observation.cohort_id != cohort_id:
            continue
        if not (window_start <= observation.observed_at <= now):
            continue
        grouped.setdefault(observation.player_id, []).append(observation)

    results: dict[str, TrendResult] = {}
    for player_id, points in grouped.items():
        ordered = sorted(points, key=lambda item: (item.observed_at, item.market_adp))
        days = {observation.observed_at.date() for observation in ordered}
        span = (ordered[-1].observed_at - ordered[0].observed_at).total_seconds() / 86400.0
        trend: float | None = None
        if len(days) >= rule.min_observation_days and span >= rule.min_span_days:
            origin = ordered[0].observed_at
            xs = [
                (observation.observed_at - origin).total_seconds() / 86400.0
                for observation in ordered
            ]
            ys = [observation.market_adp for observation in ordered]
            slope = _ols_slope(xs, ys)
            if slope is not None:
                # Negated: a falling ADP means the player is being taken earlier.
                trend = round(-slope, 4)
        results[player_id] = TrendResult(
            player_id=player_id,
            cohort_id=cohort_id,
            trend=trend,
            observation_days=len(days),
            span_days=span,
            observations=len(ordered),
        )
    return results


def trend_summary(results: Mapping[str, TrendResult]) -> dict[str, object]:
    """Counts for the build metadata and the method card."""
    available = [result for result in results.values() if result.trend is not None]
    return {
        "rule_version": TREND_RULE.version,
        "players": len(results),
        "players_with_trend": len(available),
        "trend_available": bool(available),
    }
