"""The current market price layer: retained snapshot -> one price per preset and player.

**Boundary module.** Market data only.

This is what stands between the append-only store and the arbitrage build. It answers, for
each launch (scoring preset, league size) and each canonical player: what did the market
cost, which cohort said so, how many drafts backed it, how dispersed were they, how fresh is
the reading, and how far has it moved.

Everything here is offline. The snapshot was retrieved by :mod:`ffdraft.market.capture`;
this module reads bytes from disk, so an arbitrage board is reproducible from retained
evidence rather than from a feed that has since moved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ffdraft.contracts import EntityKind, QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.identity.resolver import FLAG_SECONDARY_ONLY, REASON_RESOLVED_SECONDARY
from ffdraft.market.cohorts import CohortAssignment
from ffdraft.market.snapshot import MarketSnapshot, SnapshotStore
from ffdraft.market.trend import (
    INSUFFICIENT_TREND_HISTORY,
    TREND_RULE,
    TrendResult,
    compute_trends,
    observations_from_snapshots,
)
from ffdraft.quality.thresholds import MARKET_SOURCE_MAX_AGE
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "LOW_MARKET_SAMPLE",
    "MARKET_SNAPSHOT_STALE",
    "SECONDARY_IDENTITY_BRIDGE_ONLY",
    "WIDE_MARKET_RANGE",
    "CurrentMarket",
    "MarketPrice",
    "build_current_market",
]

#: Quality flags this layer can attach to a price (ADR-041).
LOW_MARKET_SAMPLE = "low_market_sample"
WIDE_MARKET_RANGE = "wide_market_range"
MARKET_SNAPSHOT_STALE = "market_snapshot_stale"
SECONDARY_IDENTITY_BRIDGE_ONLY = "secondary_identity_bridge_only"

#: Fewer drafts than this priced the player: the market barely has an opinion (ADR-041).
LOW_SAMPLE_THRESHOLD = 30
#: At least this many drafts are needed before a price can be called high confidence.
HIGH_SAMPLE_THRESHOLD = 200
#: `adp_high - adp_low` spanning this many rounds or more is described as wide. Descriptive
#: only: min/max are extreme order statistics that widen with sample size, so they cannot
#: move a confidence tier (ADR-041).
WIDE_RANGE_ROUNDS = 5.0


@dataclass(frozen=True, slots=True)
class MarketPrice:
    """One player's market price for one preset, with its provenance and quality."""

    player_id: str
    scoring_preset: str
    league_size: int
    market_adp: float
    market_rank: int | None
    sample_size: int | None
    adp_low: float | None
    adp_high: float | None
    #: MFL publishes none. Never populated (`docs/DATA_SOURCES.md` 13.5).
    adp_sd: None
    source_id: str
    cohort_id: str
    cohort_detail: str
    cohort_exact: bool
    cohort_sufficient: bool
    snapshot_at_utc: datetime
    snapshot_stale: bool
    secondary_bridge_only: bool
    market_trend: float | None
    trend_flags: tuple[str, ...]
    quality_flags: tuple[str, ...]

    @property
    def range_rounds(self) -> float | None:
        if self.adp_low is None or self.adp_high is None or self.league_size <= 0:
            return None
        return (self.adp_high - self.adp_low) / self.league_size


@dataclass
class CurrentMarket:
    """Every current price, keyed by ``(scoring_preset, league_size, player_id)``."""

    season: int
    source_id: str
    snapshot_key: str
    snapshot_at_utc: datetime
    prices: dict[tuple[str, int, str], MarketPrice] = field(default_factory=dict)
    assignments: dict[tuple[str, int], CohortAssignment] = field(default_factory=dict)
    trend_by_cohort: dict[str, dict[str, TrendResult]] = field(default_factory=dict)
    checks: list[QualityCheck] = field(default_factory=list)
    #: Snapshot keys the trend window consumed, oldest first. Evidence for the method card.
    trend_history_keys: tuple[str, ...] = ()

    def price(self, scoring_preset: str, league_size: int, player_id: str) -> MarketPrice | None:
        return self.prices.get((scoring_preset, league_size, player_id))

    def prices_for(self, scoring_preset: str, league_size: int) -> list[MarketPrice]:
        return [
            price
            for (scoring, size, _), price in sorted(self.prices.items())
            if scoring == scoring_preset and size == league_size
        ]

    @property
    def trend_available(self) -> bool:
        return any(
            result.trend is not None
            for results in self.trend_by_cohort.values()
            for result in results.values()
        )


def _price_flags(
    *,
    assignment: CohortAssignment,
    sample_size: int | None,
    range_rounds: float | None,
    stale: bool,
    secondary_only: bool,
    trend_flags: Sequence[str],
) -> tuple[str, ...]:
    flags: list[str] = list(assignment.quality_flags)
    if sample_size is not None and sample_size < LOW_SAMPLE_THRESHOLD:
        flags.append(LOW_MARKET_SAMPLE)
    if range_rounds is not None and range_rounds >= WIDE_RANGE_ROUNDS:
        flags.append(WIDE_MARKET_RANGE)
    if stale:
        flags.append(MARKET_SNAPSHOT_STALE)
    if secondary_only:
        flags.append(SECONDARY_IDENTITY_BRIDGE_ONLY)
    flags.extend(trend_flags)
    return tuple(sorted(dict.fromkeys(flags)))


def build_current_market(
    snapshot: MarketSnapshot,
    *,
    assignments: Mapping[tuple[str, int], CohortAssignment],
    now: datetime,
    history: Sequence[MarketSnapshot] = (),
    max_age: timedelta = MARKET_SOURCE_MAX_AGE,
) -> CurrentMarket:
    """Assemble the current price layer from one retained snapshot and its history.

    ``history`` is the retained window the trend is computed over, latest snapshot
    included. When it holds too little to satisfy ADR-042's requirement, every price
    carries ``market_trend = None`` and an ``insufficient_trend_history`` flag, which is the
    correct output for a store that has just been started rather than a gap to fill in.
    """
    manifest = snapshot.manifest
    snapshot_at = snapshot.retrieved_at
    stale = (now - snapshot_at) > max_age

    window = list(history) or [snapshot]
    cohorts_used = sorted({assignment.cohort.cohort_id for assignment in assignments.values()})
    trend_by_cohort: dict[str, dict[str, TrendResult]] = {}
    for cohort_id in cohorts_used:
        observations = observations_from_snapshots(window, cohort_id=cohort_id)
        trend_by_cohort[cohort_id] = compute_trends(
            observations,
            now=snapshot_at,
            cohort_id=cohort_id,
            rule=TREND_RULE,
        )

    rows_by_cohort: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in snapshot.rows:
        player_id = row.get("player_id")
        if not player_id or str(row.get("entity_kind")) != str(EntityKind.PLAYER):
            continue
        rows_by_cohort.setdefault(str(row["cohort_id"]), {})[str(player_id)] = row

    market = CurrentMarket(
        season=manifest.season,
        source_id=manifest.source_id,
        snapshot_key=manifest.snapshot_key,
        snapshot_at_utc=snapshot_at,
        assignments=dict(assignments),
        trend_by_cohort=trend_by_cohort,
        trend_history_keys=tuple(item.manifest.snapshot_key for item in window),
    )

    for (scoring_preset, league_size), assignment in sorted(assignments.items()):
        cohort_id = assignment.cohort.cohort_id
        rows = rows_by_cohort.get(cohort_id, {})
        if not rows:
            market.checks.append(
                QualityCheck.fail(
                    "market.assigned_cohort_absent",
                    stage="market.current",
                    message=(
                        f"{scoring_preset}/{league_size}-team was assigned cohort "
                        f"{cohort_id!r}, which the retained snapshot does not contain"
                    ),
                    observed=f"cohort_id={cohort_id}",
                    expected="a cohort present in the snapshot",
                ),
            )
            continue
        trends = trend_by_cohort.get(cohort_id, {})
        for player_id, row in sorted(rows.items()):
            trend_result = trends.get(player_id)
            trend_value = trend_result.trend if trend_result else None
            trend_flags = (
                trend_result.quality_flags if trend_result else (INSUFFICIENT_TREND_HISTORY,)
            )
            sample_size = _as_int(row.get("sample_size"))
            low = _as_float(row.get("min_pick"))
            high = _as_float(row.get("max_pick"))
            row_flags = _as_flags(row.get("quality_flags"))
            secondary_only = (
                str(row.get("resolution_reason")) == REASON_RESOLVED_SECONDARY
                or FLAG_SECONDARY_ONLY in row_flags
            )
            range_rounds = (
                (high - low) / league_size if low is not None and high is not None else None
            )
            market.prices[(scoring_preset, league_size, player_id)] = MarketPrice(
                player_id=player_id,
                scoring_preset=scoring_preset,
                league_size=league_size,
                market_adp=float(_as_float(row["average_pick"]) or 0.0),
                market_rank=_as_int(row.get("market_rank")),
                sample_size=sample_size,
                adp_low=low,
                adp_high=high,
                adp_sd=None,
                source_id=market.source_id,
                cohort_id=cohort_id,
                cohort_detail=assignment.source_format_detail,
                cohort_exact=assignment.exact,
                cohort_sufficient=assignment.sufficient,
                snapshot_at_utc=snapshot_at,
                snapshot_stale=stale,
                secondary_bridge_only=secondary_only,
                market_trend=trend_value,
                trend_flags=tuple(trend_flags),
                quality_flags=_price_flags(
                    assignment=assignment,
                    sample_size=sample_size,
                    range_rounds=range_rounds,
                    stale=stale,
                    secondary_only=secondary_only,
                    trend_flags=trend_flags,
                ),
            )

    market.checks.append(
        QualityCheck.fail(
            "market.snapshot_freshness",
            stage="market.current",
            message="the retained market snapshot is older than the freshness budget",
            observed=f"snapshot {isoformat_utc(snapshot_at)}, now {isoformat_utc(now)}",
            expected=f"<= {max_age}",
            severity=Severity.WARNING,
        )
        if stale
        else QualityCheck.ok(
            "market.snapshot_freshness",
            stage="market.current",
            message="the retained market snapshot is inside the freshness budget",
            observed=f"snapshot {isoformat_utc(snapshot_at)}",
        ),
    )
    return market


def load_trend_window(
    store: SnapshotStore,
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
    from ffdraft.market.snapshot import parse_snapshot_key

    horizon = now - timedelta(days=rule_window_days)
    keys = [
        key for key in store.keys(source_id, season) if horizon <= parse_snapshot_key(key) <= now
    ]
    return store.read_window(source_id, season, keys=keys)


def _as_flags(value: object) -> tuple[str, ...]:
    """Row quality flags, whatever shape the retained JSON used."""
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(flag for flag in value.split(",") if flag)
    if isinstance(value, list | tuple):
        return tuple(str(flag) for flag in value)
    return ()


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
