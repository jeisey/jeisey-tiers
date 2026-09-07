"""Retained market history, for **every** ADP source rather than only the first one.

**Boundary module.** Market data only.

Phase 5 gave MyFantasyLeague a retained trailing window, computed `phase5_trend_v1` over it
and published the points as `market_trend_series.json`. Phase 10 added a second ADP source
and read back only its *latest* snapshot, so FFC arrived with a price and no past: its
`market_trend` was structurally `None` — never computed, not merely unqualified — and no
series record was ever written for it. A player card showing a current FFC ADP beside
"0 snapshots so far" was that gap, rendered (ADR-081).

This module is the extraction. There is one retained-history path and every source uses it:

    store -> trailing window (the frozen 7-day rule)
          -> observations, per cohort
          -> compute_trends (the frozen `phase5_trend_v1` statistic, unchanged)
          -> RetainedHistory

Nothing here re-implements the trend. :func:`~ffdraft.market.trend.compute_trends` and
:func:`~ffdraft.market.trend.observations_from_snapshots` are the same functions Phase 5
froze; what is new is that a second source can reach them.

**Cohorts stay source-specific, and a source is never asked to claim more than it observes.**
MyFantasyLeague's cohort is chosen per ``(scoring preset, league size)`` by the ADR-039
selection rule, because MFL genuinely filters on both. FFC's is chosen by scoring preset
alone, because `teams` is accepted and ignored (ADR-056) — so
:func:`expand_cohorts_over_league_sizes` maps every supported league size onto the *same* FFC
cohort. That repetition is the honest encoding of "this source does not observe league size":
the key exists because the caller asks per preset, and the value does not vary because the
source cannot see the difference.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ffdraft.market.snapshot import MarketSnapshot, MarketSnapshotStore
from ffdraft.market.trend import (
    TREND_RULE,
    TrendObservation,
    TrendResult,
    TrendRule,
    compute_trends,
    observations_from_snapshots,
)

__all__ = [
    "RetainedHistory",
    "build_retained_history",
    "cohorts_by_scoring_preset",
    "expand_cohorts_over_league_sizes",
    "load_trend_window",
]


def load_trend_window(
    store: MarketSnapshotStore,
    *,
    source_id: str,
    season: int,
    now: datetime,
    rule_window_days: float = TREND_RULE.window_days,
) -> list[MarketSnapshot]:
    """Retained snapshots inside the trend window, oldest first.

    Reading only the window keeps a build's cost flat as the store grows: a season of daily
    captures is 365 directories, and a trend needs at most eight of them.
    """
    from ffdraft.retention import parse_snapshot_key

    horizon = now - timedelta(days=rule_window_days)
    keys = [
        key for key in store.keys(source_id, season) if horizon <= parse_snapshot_key(key) <= now
    ]
    return store.read_window(source_id, season, keys=keys)


@dataclass(frozen=True, slots=True)
class RetainedHistory:
    """One source's trailing retained window, its cohort map and its trends.

    The window is the evidence; ``trend_by_cohort`` is the frozen statistic over it. They are
    carried together because publishing one without the other is exactly the bug this module
    exists to end: a series with no slope reads as "no data", and a slope with no series
    leaves a chart to guess where the number came from.
    """

    source_id: str
    #: Oldest first. Always includes the snapshot the current price was read from.
    snapshots: tuple[MarketSnapshot, ...] = ()
    #: ``(scoring_preset, league_size) -> cohort_id``, this source's own cohort vocabulary.
    cohorts: Mapping[tuple[str, int], str] = field(default_factory=dict)
    trend_by_cohort: Mapping[str, Mapping[str, TrendResult]] = field(default_factory=dict)
    #: The instant the window was anchored on — the newest retained observation, not the
    #: build clock, so a build re-run hours later reproduces the same trend.
    anchored_at: datetime | None = None
    rule: TrendRule = TREND_RULE

    @property
    def snapshot_keys(self) -> tuple[str, ...]:
        return tuple(snapshot.manifest.snapshot_key for snapshot in self.snapshots)

    @property
    def is_empty(self) -> bool:
        return not self.snapshots

    @property
    def trend_available(self) -> bool:
        """Whether any player in any cohort cleared the frozen rule."""
        return any(
            result.trend is not None
            for results in self.trend_by_cohort.values()
            for result in results.values()
        )

    def cohort_for(self, scoring_preset: str, league_size: int) -> str | None:
        return self.cohorts.get((scoring_preset, league_size))

    def trends_for(self, cohort_id: str) -> Mapping[str, TrendResult]:
        return self.trend_by_cohort.get(cohort_id, {})

    def trend_for(self, cohort_id: str, player_id: str) -> TrendResult | None:
        return self.trend_by_cohort.get(cohort_id, {}).get(player_id)

    def observations_for(self, cohort_id: str) -> list[TrendObservation]:
        """Every retained point in the window for one cohort, for the chart.

        Deliberately *not* filtered by the trend rule's qualification: a point is a thing we
        observed, and whether three of them span three days is a separate question about
        whether a slope may be estimated. Conflating the two is what left a real FFC history
        undrawn (ADR-081).
        """
        return observations_from_snapshots(self.snapshots, cohort_id=cohort_id)


def build_retained_history(
    snapshots: Sequence[MarketSnapshot],
    *,
    source_id: str,
    cohorts: Mapping[tuple[str, int], str],
    now: datetime | None = None,
    rule: TrendRule = TREND_RULE,
) -> RetainedHistory:
    """Compute the frozen trend for each cohort over one source's retained window.

    ``now`` anchors the trailing window and defaults to the newest retained observation
    rather than to the build clock, so an arbitrage board rebuilt from the same bytes months
    later produces the same slopes.
    """
    window = tuple(sorted(snapshots, key=lambda snapshot: snapshot.retrieved_at))
    if not window:
        return RetainedHistory(source_id=source_id, cohorts=dict(cohorts), rule=rule)
    anchor = now if now is not None else window[-1].retrieved_at
    trend_by_cohort: dict[str, dict[str, TrendResult]] = {}
    for cohort_id in sorted(set(cohorts.values())):
        trend_by_cohort[cohort_id] = compute_trends(
            observations_from_snapshots(window, cohort_id=cohort_id),
            now=anchor,
            cohort_id=cohort_id,
            rule=rule,
        )
    return RetainedHistory(
        source_id=source_id,
        snapshots=window,
        cohorts=dict(cohorts),
        trend_by_cohort=trend_by_cohort,
        anchored_at=anchor,
        rule=rule,
    )


def cohorts_by_scoring_preset(
    snapshot: MarketSnapshot,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Which cohort serves each scoring preset, read from the source's own retained rows.

    Derived rather than declared, so enabling a third ADP source needs no edit here: a
    normalized row carries both the scoring preset it describes and the cohort it came from,
    which is exactly the mapping. Returns the unambiguous map plus, separately, every scoring
    preset whose rows came from more than one cohort.

    An ambiguous preset is **not** resolved by guessing. More than one cohort per scoring
    preset means the source has a selection to make — which is what ADR-039's rule is for on
    MyFantasyLeague — and picking one arbitrarily would mix populations, which is the single
    thing `phase5_trend_v1` says must never happen.
    """
    seen: dict[str, set[str]] = {}
    for row in snapshot.rows:
        scoring = str(row.get("scoring_preset") or "")
        cohort = str(row.get("cohort_id") or "")
        if not scoring or not cohort:
            continue
        seen.setdefault(scoring, set()).add(cohort)
    resolved = {
        scoring: next(iter(cohorts)) for scoring, cohorts in seen.items() if len(cohorts) == 1
    }
    ambiguous = {scoring: sorted(cohorts) for scoring, cohorts in seen.items() if len(cohorts) > 1}
    return resolved, ambiguous


def expand_cohorts_over_league_sizes(
    by_scoring: Mapping[str, str],
    league_sizes: Iterable[int],
) -> dict[tuple[str, int], str]:
    """Key a scoring-only cohort map the way every caller asks: by preset *and* size.

    The value is identical for every league size, and that is the claim, not a shortcut: a
    source whose cohort does not vary with league size did not observe league size. FFC is
    the case in hand — `teams` is accepted and ignored (ADR-056) — and the row-level
    ``league_size`` stays null so nothing downstream can read this expansion as an
    observation.
    """
    sizes = sorted(set(league_sizes))
    return {
        (scoring, size): cohort_id for scoring, cohort_id in by_scoring.items() for size in sizes
    }
